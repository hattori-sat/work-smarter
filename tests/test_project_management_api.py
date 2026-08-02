from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from work_smarter.api import create_app


def _initialized_client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/workspace/init")
    assert response.status_code == 201
    return client


def _create_project(client: TestClient, *, title: str = "Release R1") -> dict[str, object]:
    response = client.post(
        "/api/projects",
        json={
            "title": title,
            "goal": "Deliver a safe release",
            "constraints": ["Budget is fixed"],
            "assumptions": ["The test rig remains available"],
            "completion_criteria": ["The sponsor accepts the release"],
            "planned_start_on": "2026-08-03",
            "target_due_on": "2026-08-31",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_api_manages_wbs_register_schedule_qcd_and_rendered_views(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        created = _create_project(client)
        project_id = created["project"]["id"]

        shown = client.get(f"/api/projects/{project_id[:12]}")
        assert shown.status_code == 200
        assert shown.json() == created
        assert [item["project"]["id"] for item in client.get("/api/projects").json()] == [
            project_id
        ]

        updated = client.patch(
            f"/api/projects/{project_id}",
            json={"manager": "Ada", "gtd_action_ids": []},
        )
        assert updated.status_code == 200
        assert updated.json()["project"]["manager"] == "Ada"

        phase = client.post(
            f"/api/projects/{project_id}/phases",
            json={"title": "Build", "phase_id": "PH-BUILD"},
        )
        assert phase.status_code == 201, phase.text
        assert phase.json()["id"] == "PH-BUILD"
        renamed_phase = client.patch(
            f"/api/projects/{project_id}/phases/PH-BU",
            json={"owner": "Grace"},
        )
        assert renamed_phase.status_code == 200
        assert renamed_phase.json()["owner"] == "Grace"

        design = client.post(
            f"/api/projects/{project_id}/work-packages",
            json={
                "title": "Design",
                "phase_id": "PH-BUILD",
                "duration_days": 2,
                "completion_criteria": ["Design is reviewed"],
                "work_package_id": "WP-DESIGN",
            },
        )
        assert design.status_code == 201, design.text
        implement = client.post(
            f"/api/projects/{project_id}/work-packages",
            json={
                "title": "Implement",
                "phase_id": "PH-BUILD",
                "duration_days": 3,
                "dependency_ids": ["WP-DESIGN"],
                "completion_criteria": ["CI passes"],
                "work_package_id": "WP-IMPLEMENT",
            },
        )
        assert implement.status_code == 201, implement.text

        milestone = client.post(
            f"/api/projects/{project_id}/milestones",
            json={
                "title": "Release",
                "dependency_ids": ["WP-IMPLEMENT"],
                "milestone_id": "MS-RELEASE",
            },
        )
        assert milestone.status_code == 201, milestone.text
        changed_milestone = client.patch(
            f"/api/projects/{project_id}/milestones/MS-REL",
            json={"owner": "Linus"},
        )
        assert changed_milestone.status_code == 200
        assert changed_milestone.json()["owner"] == "Linus"

        risk = client.post(
            f"/api/projects/{project_id}/register",
            json={
                "kind": "risk",
                "title": "Supplier delay",
                "probability": "0.25",
                "impact_cost": "400",
                "impact_days": 5,
                "register_item_id": "RI-SUPPLIER",
            },
        )
        assert risk.status_code == 201, risk.text
        closed_risk = client.patch(
            f"/api/projects/{project_id}/register/RI-SUP",
            json={"status": "closed", "response": "Alternate supplier qualified"},
        )
        assert closed_risk.status_code == 200
        assert closed_risk.json()["expected_cost_exposure"] == "100.00"

        schedule = client.get(f"/api/projects/{project_id}/schedule")
        assert schedule.status_code == 200, schedule.text
        assert schedule.json()["topological_order"] == [
            "WP-DESIGN",
            "WP-IMPLEMENT",
            "MS-RELEASE",
        ]
        qcd = client.get(f"/api/projects/{project_id}/qcd")
        assert qcd.status_code == 200
        assert qcd.json()["project_id"] == project_id

        for projection_format in ("table", "mermaid", "html", "markdown"):
            rendered = client.get(f"/api/projects/{project_id}/projections/{projection_format}")
            assert rendered.status_code == 200, rendered.text
            assert rendered.json()["project_id"] == project_id
            assert rendered.json()["format"] == projection_format
            assert rendered.json()["content"]

        doctor = client.get("/api/projects/doctor")
        assert doctor.status_code == 200
        assert doctor.json()["valid"] is True


def test_project_api_rejects_dependency_cycles_with_no_partial_write(tmp_path: Path) -> None:
    with _initialized_client(tmp_path) as client:
        created = _create_project(client, title="DAG safety")
        project_id = created["project"]["id"]
        for identifier, dependencies in (("WP-A", []), ("WP-B", ["WP-A"])):
            response = client.post(
                f"/api/projects/{project_id}/work-packages",
                json={
                    "title": identifier,
                    "duration_days": 1,
                    "dependency_ids": dependencies,
                    "completion_criteria": [f"{identifier} complete"],
                    "work_package_id": identifier,
                },
            )
            assert response.status_code == 201, response.text

        before = client.get(f"/api/projects/{project_id}").json()["project"]
        rejected = client.patch(
            f"/api/projects/{project_id}/work-packages/WP-A",
            json={"dependency_ids": ["WP-B"]},
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"] == "ProjectScheduleError"

        after = client.get(f"/api/projects/{project_id}").json()["project"]
        assert after["revision"] == before["revision"]
        assert (
            next(item for item in after["work_packages"] if item["id"] == "WP-A")["dependency_ids"]
            == []
        )


def test_project_api_enforces_completion_evidence_gate(tmp_path: Path) -> None:
    with _initialized_client(tmp_path) as client:
        created = _create_project(client, title="Evidence gate")
        project_id = created["project"]["id"]
        work = client.post(
            f"/api/projects/{project_id}/work-packages",
            json={
                "title": "Verify",
                "duration_days": 1,
                "completion_criteria": ["System tests pass"],
                "work_package_id": "WP-VERIFY",
            },
        ).json()
        criterion_id = work["completion_criteria"][0]["id"]

        for lifecycle in ("planned", "active"):
            transition = client.post(
                f"/api/projects/{project_id}/lifecycle",
                json={"lifecycle": lifecycle},
            )
            assert transition.status_code == 200, transition.text

        for status in ("ready", "in_progress"):
            transition = client.post(
                f"/api/projects/{project_id}/work-packages/WP-VER/transition",
                json={"status": status},
            )
            assert transition.status_code == 200, transition.text

        blocked = client.post(
            f"/api/projects/{project_id}/work-packages/WP-VER/transition",
            json={"status": "completed"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"] == "ProjectCompletionGateError"

        evidence = client.post(
            f"/api/projects/{project_id}/evidence",
            json={
                "statement": "CI run 42 passed",
                "source": "ci://run/42",
                "evidence_id": "EV-CI-42",
            },
        )
        assert evidence.status_code == 201, evidence.text
        resolved = client.patch(
            f"/api/projects/{project_id}/completion-criteria/{criterion_id}",
            json={"status": "met", "evidence_ids": ["EV-CI-42"]},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["satisfied"] is True

        completed = client.post(
            f"/api/projects/{project_id}/work-packages/WP-VER/transition",
            json={"status": "completed"},
        )
        assert completed.status_code == 200
        saved_work = next(
            item
            for item in completed.json()["project"]["work_packages"]
            if item["id"] == "WP-VERIFY"
        )
        assert saved_work["status"] == "completed"


def test_project_api_rejects_unknown_and_malformed_input_without_writes(
    tmp_path: Path,
) -> None:
    with _initialized_client(tmp_path) as client:
        unknown = client.post(
            "/api/projects",
            json={
                "title": "Strict",
                "goal": "Catch typos",
                "completion_criteria": ["Done"],
                "unexpected": True,
            },
        )
        missing_criterion = client.post(
            "/api/projects",
            json={"title": "Incomplete", "goal": "Must be testable"},
        )
        blank_title = client.post(
            "/api/projects",
            json={"title": "   ", "goal": "Invalid", "completion_criteria": ["Done"]},
        )
        missing = client.get("/api/projects/MP-MISSING")

        assert unknown.status_code == 422
        assert missing_criterion.status_code == 422
        assert blank_title.status_code == 422
        assert missing.status_code == 404
        assert client.get("/api/projects").json() == []


def test_project_openapi_exposes_concrete_request_and_response_models(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    create_operation = schema["paths"]["/api/projects"]["post"]
    request = create_operation["requestBody"]["content"]["application/json"]["schema"]
    response = create_operation["responses"]["201"]["content"]["application/json"]["schema"]
    schedule_response = schema["paths"]["/api/projects/{project_id}/schedule"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    render_response = schema["paths"]["/api/projects/{project_id}/projections/markdown"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    doctor_response = schema["paths"]["/api/projects/doctor"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert request["$ref"] == "#/components/schemas/ProjectCreateRequest"
    assert response["$ref"] == "#/components/schemas/ManagedProjectDocument"
    assert schedule_response["$ref"] == "#/components/schemas/ScheduleProjection"
    assert render_response["$ref"] == "#/components/schemas/RenderedProjectProjection"
    assert doctor_response["$ref"] == "#/components/schemas/ProjectDoctorReport"
    assert "CompletionCriterionResolutionRequest" in schema["components"]["schemas"]
