from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from work_smarter.api import create_app
from work_smarter.cli import app
from work_smarter.http_client import (
    RemoteApiError,
    WorkSmarterHttpClient,
    validate_loopback_server,
)
from work_smarter.shared.persistence.database import OutboxMessage


class _ApiDestination:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def deliver(self, message: OutboxMessage) -> None:
        self.operations.append(message.operation_id)


def test_typed_system_api_exposes_journal_recovery_and_outbox(tmp_path: Path) -> None:
    destination = _ApiDestination()
    with TestClient(create_app(tmp_path, outbox_destinations={"fake": destination})) as client:
        assert client.post("/api/workspace/init").status_code == 201
        captured = client.post(
            "/api/gtd/inbox",
            json={"text": "Journal-backed capture"},
        )
        assert captured.status_code == 201

        operations = client.get("/api/system/operations").json()
        assert operations[0]["operation_type"] == "entity.write"
        assert operations[0]["status"] == "completed"
        assert client.get(f"/api/system/operations/{operations[0]['id']}").status_code == 200
        assert client.post("/api/system/operations/recover").json() == {
            "pending_before": 0,
            "pending_after": 0,
        }

        enqueued = client.post(
            "/api/system/outbox",
            json={
                "message_id": "MSG-API",
                "operation_id": "SYNC-API",
                "destination": "fake",
                "message_type": "entity.changed",
                "payload": {"id": "IN-1"},
            },
        )
        assert enqueued.status_code == 201
        assert client.post("/api/system/outbox/run", json={"limit": 5}).json() == {
            "claimed": 1,
            "completed": 1,
            "failed": 0,
            "unavailable": 0,
        }
        assert client.get("/api/system/outbox").json()[0]["status"] == "completed"
        assert destination.operations == ["SYNC-API"]

        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/system/operations"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert schema["paths"]["/api/system/outbox"]["post"]["requestBody"]["required"]


def test_loopback_http_client_validates_and_decodes_typed_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "version": "1.0.0",
                    "workspace": "/tmp/ws",
                    "initialized": True,
                    "database": {
                        "backend": "sqlite",
                        "initialized": True,
                        "schema_version": 2,
                        "latest_schema_version": 2,
                    },
                },
            )
        if request.url.path == "/api/system/operations":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "OP-1",
                        "operation_type": "entity.write",
                        "status": "completed",
                        "aggregate_kind": "task",
                        "aggregate_id": "T-1",
                        "projection_path": "tasks/T-1.md",
                        "idempotency_key": "OP-1",
                        "last_error": None,
                    }
                ],
            )
        return httpx.Response(404, json={"detail": "not found"})

    with WorkSmarterHttpClient(
        "http://127.0.0.1:8765",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.health().database.schema_version == 2
        assert client.list_operations()[0].aggregate_id == "T-1"
        with pytest.raises(RemoteApiError, match="404"):
            client.get_operation("missing")

    assert validate_loopback_server("http://localhost:8765") == "http://localhost:8765"
    with pytest.raises(RemoteApiError, match="loopback"):
        validate_loopback_server("https://example.com")


def test_canonical_system_cli_lists_operations_and_outbox_as_json(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--workspace", str(tmp_path), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            ["--workspace", str(tmp_path), "gtd", "capture", "CLI journal capture"],
        ).exit_code
        == 0
    )

    operations = runner.invoke(
        app,
        ["--workspace", str(tmp_path), "--json", "system", "operation", "list"],
    )
    assert operations.exit_code == 0, operations.output
    assert json.loads(operations.output)[0]["status"] == "completed"

    enqueue = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "--json",
            "system",
            "outbox",
            "enqueue",
            "SYNC-CLI",
            "--destination",
            "missing",
            "--type",
            "entity.changed",
            "--payload",
            '{"id":"T-1"}',
        ],
    )
    assert enqueue.exit_code == 0, enqueue.output
    assert json.loads(enqueue.output)["operation_id"] == "SYNC-CLI"

    listing = runner.invoke(
        app,
        ["--workspace", str(tmp_path), "--json", "system", "outbox", "list"],
    )
    assert listing.exit_code == 0, listing.output
    assert json.loads(listing.output)[0]["destination"] == "missing"


def test_knowledge_note_uses_canonical_resource_operation_tree(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--workspace", str(tmp_path), "init"]).exit_code == 0
    created = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "--json",
            "knowledge",
            "note",
            "create",
            "Canonical knowledge",
            "--id",
            "KN-CANONICAL",
        ],
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["note"]["id"] == "KN-CANONICAL"

    shown = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path),
            "--json",
            "knowledge",
            "note",
            "show",
            "KN-CAN",
        ],
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["note"]["title"] == "Canonical knowledge"
