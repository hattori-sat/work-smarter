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


def test_api_corrects_work_without_rewriting_the_original_log(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_id = client.post(
            "/api/gtd/tasks",
            json={"text": "Inspect the execution trace"},
        ).json()["created"][0]["id"]
        logged = client.post(
            f"/api/gtd/tasks/{task_id}/work-logs",
            json={"minutes": 15, "note": "Mistyped duration"},
        ).json()
        work_log_id = logged["work_logs"][0]["id"]

        corrected = client.post(
            f"/api/gtd/tasks/{task_id}/work-logs/{work_log_id}/correct",
            json={"corrected_minutes": 5, "reason": "Timer included an interruption"},
        )

        assert corrected.status_code == 200
        assert corrected.json()["work_logs"][0]["minutes"] == 15
        assert corrected.json()["actual_minutes"] == 5
        correction = corrected.json()["work_log_corrections"][0]
        assert correction["work_log_id"] == work_log_id
        assert correction["previous_minutes"] == 15
        assert correction["corrected_minutes"] == 5
        assert correction["reason"] == "Timer included an interruption"


def test_api_manages_delegation_follow_up_escalation_and_blockers(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_id = client.post(
            "/api/gtd/tasks",
            json={"text": "Obtain the security decision"},
        ).json()["created"][0]["id"]

        delegated = client.post(
            f"/api/gtd/tasks/{task_id}/delegate",
            json={
                "target": "Security team",
                "target_kind": "external",
                "request": "Approve the release",
                "expected_on": "2026-07-23",
                "follow_up_on": "2026-07-24",
                "escalation_on": "2026-07-25",
                "escalation_to": "CTO",
            },
        )
        assert delegated.status_code == 200
        assert delegated.json()["disposition"] == "waiting"
        assert delegated.json()["waiting"]["target"] == "Security team"

        followed_up = client.post(
            f"/api/gtd/tasks/{task_id}/follow-up",
            json={"note": "Asked in the review channel", "next_follow_up_on": "2026-07-25"},
        )
        assert followed_up.status_code == 200
        assert followed_up.json()["waiting"]["follow_up_on"] == "2026-07-25"

        pending = client.post(
            f"/api/gtd/tasks/{task_id}/response",
            json={
                "note": "Needs one more trace",
                "resolved": False,
                "next_follow_up_on": "2026-07-26",
            },
        )
        assert pending.status_code == 200
        assert pending.json()["disposition"] == "waiting"

        escalated = client.post(
            f"/api/gtd/tasks/{task_id}/escalate",
            json={"note": "Decision is now release-critical", "escalation_to": "CTO"},
        )
        assert escalated.status_code == 200
        assert escalated.json()["waiting"]["last_escalated_at"] is not None

        resolved = client.post(
            f"/api/gtd/tasks/{task_id}/response",
            json={"note": "Approved with recorded evidence", "resolved": True},
        )
        assert resolved.status_code == 200
        assert resolved.json()["disposition"] == "next"
        assert resolved.json()["waiting"] is None
        assert resolved.json()["waiting_history"][0]["resolution_note"] == (
            "Approved with recorded evidence"
        )

        blocked = client.post(
            f"/api/gtd/tasks/{task_id}/block",
            json={"reason": "Release branch is locked"},
        ).json()
        blocker_id = blocked["blockers"][0]["id"]
        unblocked = client.post(
            f"/api/gtd/tasks/{task_id}/blockers/{blocker_id}/resolve",
            json={"note": "Branch unlocked by release manager"},
        )
        assert unblocked.status_code == 200
        assert unblocked.json()["blockers"][0]["resolved_at"] is not None


def test_api_manages_schedule_due_defer_dashboard_and_reopen(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_id = client.post(
            "/api/gtd/tasks",
            json={"text": "Run the release window"},
        ).json()["created"][0]["id"]

        scheduled = client.put(
            f"/api/gtd/tasks/{task_id}/schedule",
            json={"scheduled_for": "2026-07-23T09:00:00+09:00"},
        )
        assert scheduled.status_code == 200
        assert scheduled.json()["disposition"] == "calendar"

        deferred = client.put(
            f"/api/gtd/tasks/{task_id}/defer",
            json={"not_before": "2026-07-23T08:00:00+09:00"},
        )
        assert deferred.status_code == 200
        assert deferred.json()["schedule"]["not_before"] == "2026-07-23T08:00:00+09:00"

        due = client.put(
            f"/api/gtd/tasks/{task_id}/due",
            json={"due_on": "2026-07-23"},
        )
        assert due.status_code == 200
        assert due.json()["schedule"]["due_on"] == "2026-07-23"

        dashboard = client.get(
            "/api/gtd/dashboard/today",
            params={"day": "2026-07-23"},
        )
        assert dashboard.status_code == 200
        assert dashboard.json()["day"] == "2026-07-23"
        assert [item["id"] for item in dashboard.json()["due_today"]] == [task_id]
        assert [item["id"] for item in dashboard.json()["scheduled_today"]] == [task_id]

        completed_task_id = client.post(
            "/api/gtd/tasks",
            json={"text": "Record the decision"},
        ).json()["created"][0]["id"]
        client.post(f"/api/gtd/tasks/{completed_task_id}/start")
        client.post(f"/api/gtd/tasks/{completed_task_id}/complete")
        reopened = client.post(
            f"/api/gtd/tasks/{completed_task_id}/reopen",
            json={"reason": "The evidence link was incorrect"},
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "next"
        assert reopened.json()["completion_history"][0]["reopen_reason"] == (
            "The evidence link was incorrect"
        )


def test_api_runs_a_durable_weekly_review_and_exposes_typed_workflow_contracts(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")

        started = client.post("/api/gtd/review/weekly/start")
        assert started.status_code == 201
        review_id = started.json()["id"]

        for step in (
            "inbox_zero",
            "calendar_reviewed",
            "waiting_reviewed",
            "projects_reviewed",
            "someday_reviewed",
        ):
            checked = client.put(
                f"/api/gtd/review/weekly/{review_id}/steps/{step}",
                json={"checked": True},
            )
            assert checked.status_code == 200

        completed = client.post(f"/api/gtd/review/weekly/{review_id}/complete")
        assert completed.status_code == 200
        assert completed.json()["completed_at"] is not None

        schema = client.get("/openapi.json").json()
        assert (
            schema["paths"]["/api/gtd/dashboard/today"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/DailyDashboard"
        )
        assert (
            schema["paths"]["/api/gtd/review/weekly/start"]["post"]["responses"]["201"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/WeeklyReviewSession"
        )


def test_api_maps_workflow_refusals_and_rejects_malformed_requests(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/workspace/init")
        task_id = client.post(
            "/api/gtd/tasks",
            json={"text": "Review the dependency"},
        ).json()["created"][0]["id"]

        not_waiting = client.post(
            f"/api/gtd/tasks/{task_id}/follow-up",
            json={"note": "This task was never delegated"},
        )
        assert not_waiting.status_code == 409
        assert not_waiting.json()["error"] == "InvalidTransitionError"

        malformed = client.put(
            f"/api/gtd/tasks/{task_id}/schedule",
            json={"scheduled_for": "tomorrow morning"},
        )
        assert malformed.status_code == 422

        review_id = client.post("/api/gtd/review/weekly/start").json()["id"]
        unchecked = client.post(f"/api/gtd/review/weekly/{review_id}/complete")
        assert unchecked.status_code == 409
        assert unchecked.json()["error"] == "InvalidTransitionError"
