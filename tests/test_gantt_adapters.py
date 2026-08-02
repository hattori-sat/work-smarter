from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from work_smarter.api import create_app
from work_smarter.cli import app

runner = CliRunner()


def _create_project_and_work(client: TestClient) -> str:
    created = client.post(
        "/api/projects",
        json={
            "title": "Gantt delivery",
            "goal": "Make the plan visible",
            "completion_criteria": ["Accepted"],
            "planned_start_on": "2026-08-03",
            "project_id": "MP-GANTT-API",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project"]["id"]
    first = client.post(
        f"/api/projects/{project_id}/work-packages",
        json={
            "title": "Design",
            "duration_days": 2,
            "work_package_id": "WP-DESIGN",
            "completion_criteria": ["Reviewed"],
        },
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/projects/{project_id}/work-packages",
        json={
            "title": "Build",
            "duration_days": 3,
            "work_package_id": "WP-BUILD",
            "dependencies": [
                {
                    "predecessor_id": "WP-DESIGN",
                    "type": "finish_to_start",
                    "lag_days": 1,
                }
            ],
            "progress_percent": 40,
            "completion_criteria": ["CI passes"],
        },
    )
    assert second.status_code == 201, second.text
    baseline = client.post(
        f"/api/projects/{project_id}/baselines",
        json={"label": "Approved plan"},
    )
    assert baseline.status_code == 201, baseline.text
    assert len(baseline.json()["schedule_items"]) == 2
    return project_id


def test_typed_api_exposes_gantt_and_schedule_explanation(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        project_id = _create_project_and_work(client)

        gantt = client.get(f"/api/projects/{project_id}/gantt", params={"today": "2026-08-05"})
        assert gantt.status_code == 200, gantt.text
        assert gantt.json()["format"] == "gantt_html"
        assert gantt.json()["media_type"] == "text/html"
        assert 'data-testid="gantt-chart"' in gantt.json()["content"]
        assert 'class="baseline-bar"' in gantt.json()["content"]

        explanation = client.get(f"/api/projects/{project_id}/schedule/WP-BUILD/explanation")
        assert explanation.status_code == 200, explanation.text
        assert explanation.json()["driving_predecessor_id"] == "WP-DESIGN"
        assert "Finish-to-Start" in explanation.json()["reasons"][0]

        schema = client.get("/openapi.json").json()
        response = schema["paths"]["/api/projects/{project_id}/gantt"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response["$ref"].endswith("/RenderedProjectProjection")


def test_canonical_project_gantt_export_is_offline_and_deterministic(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    assert runner.invoke(app, [*common, "init"]).exit_code == 0
    created = runner.invoke(
        app,
        [
            *common,
            "--json",
            "project",
            "create",
            "Gantt CLI",
            "--goal",
            "Export a local chart",
            "--criterion",
            "Accepted",
            "--start",
            "2026-08-03",
            "--id",
            "MP-GANTT-CLI",
        ],
    )
    assert created.exit_code == 0, created.output
    work = runner.invoke(
        app,
        [
            *common,
            "project",
            "work",
            "add",
            "MP-GANTT",
            "Implement",
            "--days",
            "2",
            "--criterion",
            "CI passes",
            "--id",
            "WP-IMPLEMENT",
        ],
    )
    assert work.exit_code == 0, work.output

    destination = tmp_path / "reports" / "gantt.html"
    exported = runner.invoke(
        app,
        [
            *common,
            "--json",
            "project",
            "gantt",
            "export",
            "MP-GANTT",
            "--output",
            str(destination),
        ],
    )
    assert exported.exit_code == 0, exported.output
    payload = json.loads(exported.stdout)
    assert payload == {
        "project_id": "MP-GANTT-CLI",
        "format": "gantt_html",
        "output": str(destination),
    }
    assert destination.is_file()
    assert 'id="gantt-filter"' in destination.read_text(encoding="utf-8")
