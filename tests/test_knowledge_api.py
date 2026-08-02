from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from work_smarter.api import create_app


def _initialized_client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/workspace/init")
    assert response.status_code == 201
    return client


def test_knowledge_api_creates_reads_lists_updates_and_searches_notes(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        created = client.post(
            "/api/knowledge/notes",
            json={
                "title": "Deploy the Python service",
                "note_type": "how_to",
                "body": "Use the release pipeline.\n",
                "tags": ["Python", "Operations"],
                "aliases": ["service deploy"],
                "sources": [
                    {
                        "kind": "url",
                        "locator": "https://example.com/runbook",
                        "title": "Runbook",
                    }
                ],
            },
        )

        assert created.status_code == 201
        document = created.json()
        note_id = document["note"]["id"]
        assert document["note"]["tags"] == ["operations", "python"]
        assert document["body"] == "Use the release pipeline.\n"

        shown = client.get(f"/api/knowledge/notes/{note_id[:12]}")
        assert shown.status_code == 200
        assert shown.json()["note"]["id"] == note_id

        listed = client.get(
            "/api/knowledge/notes",
            params={"note_type": "how_to", "tag": "PYTHON"},
        )
        assert [item["note"]["id"] for item in listed.json()] == [note_id]

        updated = client.patch(
            f"/api/knowledge/notes/{note_id}",
            json={
                "title": "Deploy a Python release",
                "body": "The deployment NEEDLE is here.\n",
                "tags": [],
                "aliases": [],
                "sources": [],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["note"]["revision"] == 2
        assert updated.json()["note"]["tags"] == []

        searched = client.get(
            "/api/knowledge/search",
            params={"q": "needle", "field": "body"},
        )
        assert searched.status_code == 200
        assert searched.json()[0]["note"]["id"] == note_id
        assert searched.json()[0]["matched_fields"] == ["body"]


def test_knowledge_api_accepts_explicit_links_and_returns_backlinks(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        target = client.post(
            "/api/knowledge/notes",
            json={"title": "Architecture decision", "note_type": "decision"},
        ).json()
        target_id = target["note"]["id"]

        source = client.post(
            "/api/knowledge/notes",
            json={
                "title": "Implementation guide",
                "links": [
                    {
                        "target_id": target_id,
                        "relation": "derived_from",
                        "label": "Design basis",
                    }
                ],
            },
        )
        assert source.status_code == 201

        backlinks = client.get(f"/api/knowledge/backlinks/{target_id[:12]}")
        assert backlinks.status_code == 200
        assert backlinks.json() == [
            {
                "source": source.json(),
                "link": {
                    "target_id": target_id,
                    "relation": "derived_from",
                    "label": "Design basis",
                },
            }
        ]


def test_knowledge_api_promotes_any_generic_workspace_record_by_id(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        created_task = client.post(
            "/api/gtd/tasks",
            json={"text": "Investigate deployment latency"},
        )
        task_id = created_task.json()["created"][0]["id"]

        promoted = client.post(
            f"/api/knowledge/records/{task_id[:12]}/promote",
            json={
                "note_type": "reference",
                "title": "Deployment latency investigation",
                "tags": ["performance"],
            },
        )

        assert promoted.status_code == 201
        document = promoted.json()
        assert document["note"]["title"] == "Deployment latency investigation"
        assert document["note"]["sources"][0]["kind"] == "entity"
        assert document["note"]["sources"][0]["locator"] == task_id

        repeated = client.post(
            f"/api/knowledge/records/{task_id}/promote",
            json={"title": "Must not replace the first promotion"},
        )
        assert repeated.status_code == 201
        assert repeated.json() == document


def test_knowledge_api_returns_typed_marp_projection_without_writing_source(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        created = client.post(
            "/api/knowledge/notes",
            json={
                "title": "Migration report",
                "note_type": "technical_report",
                "body": "## Outcome\n\nMigration is ready.\n",
            },
        ).json()
        note_id = created["note"]["id"]

        rendered = client.get(
            f"/api/knowledge/notes/{note_id[:12]}/presentations/marp",
            params={"theme": "gaia", "paginate": "false"},
        )

        assert rendered.status_code == 200
        payload = rendered.json()
        assert payload["source_id"] == note_id
        assert payload["source_revision"] == 1
        assert payload["mode"] == "technical_report"
        assert payload["theme"] == "gaia"
        assert payload["paginate"] is False
        assert "## Outcome" in payload["markdown"]

        unsafe = client.get(
            f"/api/knowledge/notes/{note_id}/presentations/marp",
            params={"theme": "default\npaginate: false"},
        )
        assert unsafe.status_code == 422


def test_knowledge_api_maps_domain_errors_and_exposes_doctor(tmp_path: Path) -> None:
    with _initialized_client(tmp_path) as client:
        first = client.post(
            "/api/knowledge/notes",
            json={"title": "First", "aliases": ["shared"]},
        )
        assert first.status_code == 201

        conflict = client.post(
            "/api/knowledge/notes",
            json={"title": "Second", "aliases": ["SHARED"]},
        )
        assert conflict.status_code == 400
        assert conflict.json()["error"] == "KnowledgeConflictError"

        missing = client.get("/api/knowledge/notes/KN-MISSING")
        assert missing.status_code == 404
        assert missing.json()["error"] == "EntityNotFoundError"

        report = client.get("/api/knowledge/doctor")
        assert report.status_code == 200
        assert report.json()["valid"] is True
        assert report.json()["counts"] == {"notes": 1, "orphan": 1}


def test_knowledge_api_rejects_unknown_and_malformed_request_fields(tmp_path: Path) -> None:
    with _initialized_client(tmp_path) as client:
        unknown = client.post(
            "/api/knowledge/notes",
            json={"title": "Strict request", "unexpected": True},
        )
        blank_source = client.post(
            "/api/knowledge/notes",
            json={
                "title": "Bad source",
                "sources": [{"kind": "url", "locator": "   "}],
            },
        )
        unsafe_link = client.post(
            "/api/knowledge/notes",
            json={
                "title": "Bad link",
                "links": [{"target_id": "../outside"}],
            },
        )

        assert unknown.status_code == 422
        assert blank_source.status_code == 422
        assert unsafe_link.status_code == 422
        assert client.get("/api/knowledge/notes").json() == []


def test_knowledge_openapi_is_typed_for_clients(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    create_operation = paths["/api/knowledge/notes"]["post"]
    create_request = create_operation["requestBody"]["content"]["application/json"]["schema"]
    create_response = create_operation["responses"]["201"]["content"]["application/json"]["schema"]
    backlinks_response = paths["/api/knowledge/backlinks/{target_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    doctor_response = paths["/api/knowledge/doctor"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    marp_response = paths["/api/knowledge/notes/{note_id}/presentations/marp"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]

    assert create_request["$ref"] == "#/components/schemas/KnowledgeCreateRequest"
    assert create_response["$ref"] == "#/components/schemas/KnowledgeDocument"
    assert backlinks_response["items"]["$ref"] == "#/components/schemas/KnowledgeBacklink"
    assert doctor_response["$ref"] == "#/components/schemas/KnowledgeDoctorReport"
    assert marp_response["$ref"] == "#/components/schemas/MarpPresentation"
    assert "KnowledgeLinkRequest" in schema["components"]["schemas"]
    assert "SourceReferenceRequest" in schema["components"]["schemas"]
