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
