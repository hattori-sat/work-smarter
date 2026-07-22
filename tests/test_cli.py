from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from work_smarter.cli import app

runner = CliRunner()


def test_cli_happy_path_uses_short_ids_and_json(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]

    initialized = runner.invoke(app, [*common, "init"])
    assert initialized.exit_code == 0, initialized.output

    captured = runner.invoke(
        app,
        [*common, "--json", "capture", "Draft release notes", "--tag", "Work"],
    )
    assert captured.exit_code == 0, captured.output
    inbox = json.loads(captured.stdout)

    clarified = runner.invoke(
        app,
        [
            *common,
            "--json",
            "clarify",
            inbox["id"][:12],
            "--decision",
            "next",
            "--context",
            "@computer",
            "--estimate",
            "20",
        ],
    )
    assert clarified.exit_code == 0, clarified.output
    task_id = json.loads(clarified.stdout)["created"][0]["id"]

    focused = runner.invoke(
        app,
        [*common, "--json", "focus", "--context", "@computer", "--minutes", "30"],
    )
    assert focused.exit_code == 0, focused.output
    assert [task["id"] for task in json.loads(focused.stdout)] == [task_id]

    overview = runner.invoke(app, [*common, "--json", "status"])
    assert overview.exit_code == 0, overview.output
    assert json.loads(overview.stdout)["tasks_by_status"]["next"] == 1

    started = runner.invoke(app, [*common, "start", task_id[:14]])
    assert started.exit_code == 0, started.output
    completed = runner.invoke(app, [*common, "done", task_id[:14]])
    assert completed.exit_code == 0, completed.output
    assert "Completed" in completed.stdout


def test_cli_capture_reads_stdin_for_editor_and_pipe_adapters(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    runner.invoke(app, [*common, "init"])

    captured = runner.invoke(
        app,
        [*common, "--json", "capture", "--source", "vscode-selection"],
        input="Selected TODO from source code\n",
    )

    assert captured.exit_code == 0, captured.output
    item = json.loads(captured.stdout)
    assert item["title"] == "Selected TODO from source code"
    assert item["source"] == "vscode-selection"


def test_cli_add_is_a_single_command_next_action_shortcut(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    runner.invoke(app, [*common, "init"])

    added = runner.invoke(
        app,
        [
            *common,
            "--json",
            "add",
            "Run unit tests",
            "--context",
            "@computer",
            "--estimate",
            "10",
        ],
    )

    assert added.exit_code == 0, added.output
    result = json.loads(added.stdout)
    assert result["created"][0]["kind"] == "task"
    inbox = runner.invoke(app, [*common, "--json", "inbox"])
    assert json.loads(inbox.stdout) == []


def test_cli_noninteractive_clarify_never_prompts_for_missing_fields(
    tmp_path: Path,
) -> None:
    common = ["--workspace", str(tmp_path)]
    runner.invoke(app, [*common, "init"])
    captured = runner.invoke(app, [*common, "--json", "capture", "Plan a release"])
    inbox_id = json.loads(captured.stdout)["id"]

    result = runner.invoke(
        app,
        [*common, "clarify", inbox_id, "--decision", "project"],
    )

    assert result.exit_code == 2
    assert "--outcome is required" in result.output
    assert "Successful outcome" not in result.output


def test_cli_task_define_and_show_expose_personal_work_rigor(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    runner.invoke(app, [*common, "init"])
    added = runner.invoke(app, [*common, "--json", "add", "Review the design"])
    task_id = json.loads(added.stdout)["created"][0]["id"]

    defined = runner.invoke(
        app,
        [
            *common,
            "--json",
            "task",
            "define",
            task_id,
            "--type",
            "communication",
            "--rigor",
            "standard",
            "--goal",
            "Obtain an explicit review decision",
            "--why",
            "Unresolved interfaces make implementation unsafe",
            "--constraint",
            "Use sanitized material",
            "--assumption",
            "Reviewers can access the proposal",
            "--criterion",
            "Decision and actions are recorded",
        ],
    )
    assert defined.exit_code == 0, defined.output
    assert json.loads(defined.stdout)["rigor"] == "standard"

    shown = runner.invoke(app, [*common, "--json", "task", "show", task_id[:14]])
    assert shown.exit_code == 0, shown.output
    ticket = json.loads(shown.stdout)
    assert ticket["goal"] == "Obtain an explicit review decision"
    assert ticket["constraints"] == ["Use sanitized material"]


def test_cli_task_logs_estimates_and_recurrence_without_file_editing(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path)]
    runner.invoke(app, [*common, "init"])
    added = runner.invoke(
        app,
        [*common, "--json", "add", "Review access permissions", "--estimate", "45"],
    )
    task_id = json.loads(added.stdout)["created"][0]["id"]

    logged = runner.invoke(
        app,
        [*common, "--json", "task", "log", task_id, "10", "--note", "First pass"],
    )
    assert logged.exit_code == 0, logged.output
    assert json.loads(logged.stdout)["actual_minutes"] == 10

    estimated = runner.invoke(
        app,
        [
            *common,
            "--json",
            "task",
            "estimate",
            task_id,
            "20",
            "--reason",
            "Second system added",
        ],
    )
    assert estimated.exit_code == 0, estimated.output
    assert json.loads(estimated.stdout)["remaining_estimate_minutes"] == 20

    repeated = runner.invoke(
        app,
        [
            *common,
            "--json",
            "task",
            "repeat",
            task_id,
            "--frequency",
            "weekly",
            "--anchor",
            "2026-07-23",
        ],
    )
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.stdout)["next_occurrence_on"] == "2026-07-30"


def test_cli_correct_work_preserves_original_log_and_updates_actual(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path), "--json"]
    runner.invoke(app, ["--workspace", str(tmp_path), "init"])
    added = runner.invoke(app, [*common, "add", "Investigate production alert"])
    task_id = json.loads(added.stdout)["created"][0]["id"]
    logged = runner.invoke(app, [*common, "task", "log", task_id, "25"])
    work_log_id = json.loads(logged.stdout)["work_logs"][0]["id"]

    corrected = runner.invoke(
        app,
        [
            *common,
            "task",
            "correct-work",
            task_id[:14],
            work_log_id,
            "15",
            "--reason",
            "Ten minutes belonged to another task",
        ],
    )

    assert corrected.exit_code == 0, corrected.output
    task = json.loads(corrected.stdout)
    assert task["work_logs"][0]["minutes"] == 25
    assert task["actual_minutes"] == 15
    assert task["work_log_corrections"][-1]["work_log_id"] == work_log_id
    assert task["work_log_corrections"][-1]["corrected_minutes"] == 15


def test_cli_task_workflow_manages_waiting_blockers_dates_and_reopening(
    tmp_path: Path,
) -> None:
    common = ["--workspace", str(tmp_path), "--json"]
    runner.invoke(app, ["--workspace", str(tmp_path), "init"])
    added = runner.invoke(app, [*common, "add", "Obtain security approval"])
    task_id = json.loads(added.stdout)["created"][0]["id"]

    delegated = runner.invoke(
        app,
        [
            *common,
            "task",
            "delegate",
            task_id[:14],
            "Security lead",
            "--request",
            "Approve the threat model",
            "--follow-up",
            "2099-05-01",
            "--escalation",
            "2099-05-01",
            "--escalate-to",
            "CTO",
        ],
    )
    assert delegated.exit_code == 0, delegated.output
    assert json.loads(delegated.stdout)["waiting"]["target"] == "Security lead"

    followed_up = runner.invoke(
        app,
        [
            *common,
            "task",
            "follow-up",
            task_id,
            "--note",
            "Asked in the review channel",
            "--next",
            "2099-05-02",
        ],
    )
    assert followed_up.exit_code == 0, followed_up.output
    assert json.loads(followed_up.stdout)["waiting"]["follow_up_on"] == "2099-05-02"

    escalated = runner.invoke(
        app,
        [
            *common,
            "task",
            "escalate",
            task_id,
            "--note",
            "Approval is now on the critical path",
            "--to",
            "CTO",
            "--next",
            "2099-05-03",
        ],
    )
    assert escalated.exit_code == 0, escalated.output

    still_waiting = runner.invoke(
        app,
        [
            *common,
            "task",
            "respond",
            task_id,
            "--note",
            "More evidence requested",
            "--still-waiting",
            "--next",
            "2099-05-04",
        ],
    )
    assert still_waiting.exit_code == 0, still_waiting.output
    assert json.loads(still_waiting.stdout)["status"] == "waiting"

    resolved = runner.invoke(
        app,
        [
            *common,
            "task",
            "respond",
            task_id,
            "--note",
            "Approved",
            "--resolved",
        ],
    )
    assert resolved.exit_code == 0, resolved.output
    assert json.loads(resolved.stdout)["status"] == "next"

    blocked = runner.invoke(
        app,
        ["--workspace", str(tmp_path), "--json", "block", task_id, "--reason", "VPN down"],
    )
    blocker_id = json.loads(blocked.stdout)["blockers"][-1]["id"]
    unblocked = runner.invoke(
        app,
        [
            *common,
            "task",
            "unblock",
            task_id,
            blocker_id,
            "--note",
            "VPN restored",
        ],
    )
    assert unblocked.exit_code == 0, unblocked.output
    assert json.loads(unblocked.stdout)["status"] == "next"

    scheduled = runner.invoke(
        app,
        [*common, "task", "schedule", task_id, "2099-05-05T09:00:00+09:00"],
    )
    assert scheduled.exit_code == 0, scheduled.output
    assert json.loads(scheduled.stdout)["status"] == "scheduled"
    runner.invoke(app, [*common, "ready", task_id])

    deferred = runner.invoke(
        app,
        [*common, "task", "defer", task_id, "2099-05-04T09:00:00+09:00"],
    )
    assert deferred.exit_code == 0, deferred.output
    assert json.loads(deferred.stdout)["schedule"]["not_before"].startswith("2099-05-04")
    due = runner.invoke(app, [*common, "task", "due", task_id, "2099-05-06"])
    assert due.exit_code == 0, due.output
    assert json.loads(due.stdout)["schedule"]["due_on"] == "2099-05-06"

    completed = runner.invoke(app, [*common, "done", task_id])
    assert completed.exit_code == 0, completed.output
    reopened = runner.invoke(
        app,
        [*common, "task", "reopen", task_id, "--reason", "Approval was withdrawn"],
    )
    assert reopened.exit_code == 0, reopened.output
    assert json.loads(reopened.stdout)["status"] == "next"
    assert json.loads(reopened.stdout)["completion_history"][-1]["reopen_reason"]


def test_cli_today_dashboard_surfaces_due_waiting_and_scheduled_work(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path), "--json"]
    runner.invoke(app, ["--workspace", str(tmp_path), "init"])
    waiting_id = json.loads(runner.invoke(app, [*common, "add", "Wait for vendor quote"]).stdout)[
        "created"
    ][0]["id"]
    due_id = json.loads(runner.invoke(app, [*common, "add", "Submit purchase order"]).stdout)[
        "created"
    ][0]["id"]
    scheduled_id = json.loads(
        runner.invoke(app, [*common, "add", "Attend architecture review"]).stdout
    )["created"][0]["id"]
    runner.invoke(
        app,
        [
            *common,
            "task",
            "delegate",
            waiting_id,
            "Vendor",
            "--follow-up",
            "2099-05-01",
            "--escalation",
            "2099-05-01",
            "--escalate-to",
            "Procurement lead",
        ],
    )
    runner.invoke(app, [*common, "task", "due", due_id, "2099-05-01"])
    runner.invoke(
        app,
        [*common, "task", "schedule", scheduled_id, "2099-05-01T10:00:00+09:00"],
    )

    today = runner.invoke(app, [*common, "today", "--day", "2099-05-01"])

    assert today.exit_code == 0, today.output
    dashboard = json.loads(today.stdout)
    assert [item["id"] for item in dashboard["due_today"]] == [due_id]
    assert [item["id"] for item in dashboard["follow_ups_due"]] == [waiting_id]
    assert [item["id"] for item in dashboard["escalations_due"]] == [waiting_id]
    assert [item["id"] for item in dashboard["scheduled_today"]] == [scheduled_id]


def test_cli_weekly_review_session_can_start_resume_check_and_complete(
    tmp_path: Path,
) -> None:
    common = ["--workspace", str(tmp_path), "--json"]
    runner.invoke(app, ["--workspace", str(tmp_path), "init"])

    started = runner.invoke(app, [*common, "review", "start"])
    assert started.exit_code == 0, started.output
    review_id = json.loads(started.stdout)["id"]

    resumed = runner.invoke(app, [*common, "review", "resume"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.stdout)["session_id"] == review_id

    for step in (
        "inbox_zero",
        "calendar_reviewed",
        "waiting_reviewed",
        "projects_reviewed",
        "someday_reviewed",
    ):
        checked = runner.invoke(app, [*common, "review", "check", review_id[:14], step])
        assert checked.exit_code == 0, checked.output

    completed = runner.invoke(app, [*common, "review", "complete", review_id[:14]])
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.stdout)["completed_at"] is not None

    legacy = runner.invoke(app, [*common, "review"])
    assert legacy.exit_code == 0, legacy.output
    assert json.loads(legacy.stdout)["session_id"] is None
