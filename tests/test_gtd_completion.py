from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from work_smarter.api import create_app
from work_smarter.cli import app
from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.errors import InvalidTransitionError
from work_smarter.gtd.models import ProjectStatus
from work_smarter.gtd.service import GtdService

runner = CliRunner()


def test_standalone_gtd_project_create_complete_audit_and_reload(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path)
    service = GtdService(workspace)

    project = service.create_project(
        title="Reproducible debugging",
        outcome="Every API failure can be reproduced locally",
        project_id="GPR-DEBUG",
        tags=["Engineering", "debugging"],
    )

    assert project.status is ProjectStatus.ACTIVE
    assert project.tags == ["debugging", "engineering"]
    assert service.get_project("GPR-DEB") == project
    assert service.document_ref("GPR-DEB").path == "gtd/projects/GPR-DEBUG.md"
    assert "Every API failure" in (tmp_path / "gtd/projects/GPR-DEBUG.md").read_text()
    assert workspace.event_store.read_all()[-1].type == "gtd.project.created"

    action = service.add_next_action("Reproduce timeout", project_id=project.id).created[0]
    with pytest.raises(InvalidTransitionError, match="still has open actions"):
        service.complete_project(project.id)

    service.complete_task(action.id)
    completed = service.complete_project(project.id)
    assert completed.status is ProjectStatus.DONE

    reopened = GtdService(open_workspace(tmp_path))
    assert reopened.get_project(project.id).status is ProjectStatus.DONE
    assert [event.type for event in workspace.event_store.read_all()][-2:] == [
        "gtd.task.completed",
        "gtd.project.completed",
    ]


def test_canonical_gtd_cli_project_and_picker_contract(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    assert runner.invoke(app, [*common, "init"]).exit_code == 0

    created = runner.invoke(
        app,
        [
            *common,
            "--json",
            "gtd",
            "project",
            "create",
            "Release readiness",
            "--outcome",
            "Release evidence is complete",
            "--id",
            "GPR-RELEASE",
        ],
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)["id"] == "GPR-RELEASE"

    action = runner.invoke(
        app,
        [
            *common,
            "--json",
            "gtd",
            "action",
            "create",
            "Collect CI evidence",
            "--project",
            "GPR-REL",
            "--context",
            "@computer",
            "--estimate",
            "20",
        ],
    )
    assert action.exit_code == 0, action.output
    action_id = json.loads(action.stdout)["id"]

    picker = runner.invoke(app, [*common, "gtd", "action", "list", "--output", "picker"])
    assert picker.exit_code == 0, picker.output
    assert f"next     {action_id}" in picker.stdout
    assert "Collect CI evidence" in picker.stdout
    assert "@computer" in picker.stdout
    assert "20m" in picker.stdout

    projects = runner.invoke(app, [*common, "--json", "gtd", "project", "list"])
    assert projects.exit_code == 0, projects.output
    assert [item["id"] for item in json.loads(projects.stdout)] == ["GPR-RELEASE"]

    with patch("work_smarter.gtd.cli.subprocess.run") as editor:
        editor.return_value.returncode = 0
        opened = runner.invoke(
            app,
            [*common, "gtd", "action", "open", action_id[:10]],
            env={"EDITOR": "code --wait"},
        )
    assert opened.exit_code == 0, opened.output
    assert editor.call_args.args[0][0:2] == ["code", "--wait"]
    assert Path(editor.call_args.args[0][-1]).name == f"{action_id}.md"


def test_gtd_project_http_contract_is_typed_and_uses_unique_prefixes(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        created = client.post(
            "/api/gtd/projects",
            json={
                "title": "Operational handbook",
                "outcome": "Support can resolve known failures",
                "project_id": "GPR-HANDBOOK",
                "tags": ["ops"],
            },
        )
        assert created.status_code == 201
        assert created.json()["id"] == "GPR-HANDBOOK"

        listed = client.get("/api/gtd/projects", params={"status": "active"})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == ["GPR-HANDBOOK"]

        shown = client.get("/api/gtd/projects/GPR-HAND")
        assert shown.status_code == 200
        assert shown.json()["outcome"] == "Support can resolve known failures"

        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/gtd/projects"]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert request_schema["$ref"].endswith("/GtdProjectCreateRequest")
        assert operation["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/GtdProject")
