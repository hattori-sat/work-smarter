from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from work_smarter.api import create_app


def test_api_supports_capture_clarify_focus_and_completion(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["initialized"] is False

        initialized = client.post("/api/workspace/init")
        assert initialized.status_code == 201

        captured = client.post(
            "/api/gtd/inbox",
            json={"text": "Prepare review", "tags": ["work"]},
        )
        assert captured.status_code == 201
        inbox_id = captured.json()["id"]

        clarified = client.post(
            f"/api/gtd/inbox/{inbox_id}/clarify",
            json={
                "decision": "next",
                "contexts": ["@computer"],
                "energy": "low",
                "estimate_minutes": 15,
                "completion_criteria": ["Review prepared"],
            },
        )
        assert clarified.status_code == 200
        task_id = clarified.json()["created"][0]["id"]

        focused = client.get(
            "/api/gtd/focus",
            params={"context": "@computer", "minutes": 20, "energy": "low"},
        )
        assert [task["id"] for task in focused.json()] == [task_id]

        status = client.get("/api/gtd/status")
        assert status.status_code == 200
        assert status.json()["tasks_by_status"]["next"] == 1

        started = client.post(f"/api/gtd/tasks/{task_id}/start")
        assert started.status_code == 200
        assert started.json()["status"] == "doing"

        stopped = client.post("/api/gtd/tasks/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "next"

        client.post(f"/api/gtd/tasks/{task_id}/start")
        completed = client.post(f"/api/gtd/tasks/{task_id}/complete")
        assert completed.status_code == 200
        assert completed.json()["task"]["status"] == "done"

        metrics = client.get("/api/gtd/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["completed_total"] == 1


def test_api_maps_domain_errors_to_conflict(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_ids: list[str] = []
        for title in ("First", "Second"):
            item = client.post("/api/gtd/inbox", json={"text": title}).json()
            result = client.post(
                f"/api/gtd/inbox/{item['id']}/clarify",
                json={"decision": "next"},
            ).json()
            task_ids.append(result["created"][0]["id"])

        client.post(f"/api/gtd/tasks/{task_ids[0]}/start")
        conflict = client.post(f"/api/gtd/tasks/{task_ids[1]}/start")

        assert conflict.status_code == 409
        assert conflict.json()["error"] == "WipLimitError"


def test_api_quick_add_and_ready_transition(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        added = client.post(
            "/api/gtd/tasks",
            json={
                "text": "Call the supplier",
                "contexts": ["@phone"],
                "estimate_minutes": 5,
            },
        )
        assert added.status_code == 201
        task_id = added.json()["created"][0]["id"]

        blocked = client.post(
            f"/api/gtd/tasks/{task_id}/block",
            json={"reason": "Need the phone number"},
        )
        assert blocked.json()["status"] == "blocked"

        ready = client.post(f"/api/gtd/tasks/{task_id}/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "next"


def test_openapi_exposes_typed_contracts_for_vscode_clients(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    task_response = schema["paths"]["/api/gtd/tasks"]["get"]["responses"]["200"]
    task_schema = task_response["content"]["application/json"]["schema"]
    status_schema = schema["paths"]["/api/gtd/status"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert task_schema["items"]["$ref"] == "#/components/schemas/Task"
    assert status_schema["$ref"] == "#/components/schemas/StatusReport"


def test_api_defines_reads_and_checks_a_rigorous_ticket(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        added = client.post(
            "/api/gtd/tasks",
            json={"text": "Make the release decision"},
        )
        task_id = added.json()["created"][0]["id"]

        defined = client.patch(
            f"/api/gtd/tasks/{task_id}",
            json={
                "work_type": "decision",
                "rigor": "standard",
                "goal": "Record a defensible release decision",
                "why": "The rollout has irreversible effects",
                "desired_outcome": "A go/no-go decision with rationale",
                "constraints": ["Security review must be complete"],
                "assumptions": ["Load test data is representative"],
                "completion_criteria": ["Decision and rationale are recorded"],
            },
        )
        assert defined.status_code == 200
        assert defined.json()["rigor"] == "standard"
        assert defined.json()["completion"]["conditions"][0]["id"] == "CC-1"

        shown = client.get(f"/api/gtd/tasks/{task_id}")
        assert shown.status_code == 200
        assert shown.json()["goal"] == "Record a defensible release decision"

        checked = client.post(
            f"/api/gtd/tasks/{task_id}/completion/CC-1",
            json={"evidence": "knowledge/decisions/release.md"},
        )
        assert checked.status_code == 200
        assert checked.json()["completion"]["conditions"][0]["met_at"] is not None


def test_api_creates_a_directional_task_link(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_ids = [
            client.post("/api/gtd/tasks", json={"text": title}).json()["created"][0]["id"]
            for title in ("Produce input", "Use input")
        ]

        linked = client.post(
            f"/api/gtd/tasks/{task_ids[0]}/links",
            json={"target_id": task_ids[1], "relation_type": "blocks"},
        )

        assert linked.status_code == 200
        assert linked.json()["relations"] == [{"type": "blocks", "target_id": task_ids[1]}]


def test_api_manages_parent_effort_priority_and_recurrence(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        parent_id, task_id = [
            client.post("/api/gtd/tasks", json={"text": title}).json()["created"][0]["id"]
            for title in ("Prepare review", "Inspect evidence")
        ]

        defined = client.patch(
            f"/api/gtd/tasks/{task_id}",
            json={
                "urgency": "high",
                "impact": "high",
                "commitment": "committed",
                "original_estimate_minutes": 60,
            },
        )
        assert defined.json()["remaining_estimate_minutes"] == 60

        parented = client.put(
            f"/api/gtd/tasks/{task_id}/parent",
            json={"parent_id": parent_id},
        )
        assert parented.json()["parent_id"] == parent_id

        logged = client.post(
            f"/api/gtd/tasks/{task_id}/work-logs",
            json={"minutes": 15, "note": "Inspected first trace"},
        )
        assert logged.json()["actual_minutes"] == 15

        estimated = client.patch(
            f"/api/gtd/tasks/{task_id}/remaining-estimate",
            json={"minutes": 30, "reason": "One more environment remains"},
        )
        assert estimated.json()["original_estimate_minutes"] == 60
        assert estimated.json()["remaining_estimate_minutes"] == 30

        recurring = client.put(
            f"/api/gtd/tasks/{task_id}/recurrence",
            json={
                "frequency": "weekly",
                "interval": 1,
                "anchor_on": "2026-07-23",
            },
        )
        assert recurring.json()["next_occurrence_on"] == "2026-07-30"
