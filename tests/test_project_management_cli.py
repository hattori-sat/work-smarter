from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from work_smarter.cli import app
from work_smarter.project_management.errors import ProjectScheduleError

runner = CliRunner()


def _common(workspace: Path) -> list[str]:
    return ["--workspace", str(workspace), "--json", "pm"]


def _initialize(workspace: Path) -> None:
    initialized = runner.invoke(app, ["--workspace", str(workspace), "init"])
    assert initialized.exit_code == 0, initialized.output


def _create(workspace: Path, *, project_id: str = "MP-CLI") -> dict[str, object]:
    created = runner.invoke(
        app,
        [
            *_common(workspace),
            "create",
            "Release R1",
            "--goal",
            "Deliver a safe release",
            "--criterion",
            "Sponsor accepts the release",
            "--constraint",
            "Budget is fixed",
            "--assumption",
            "Test rig remains available",
            "--start",
            "2026-08-03",
            "--due",
            "2026-08-31",
            "--id",
            project_id,
        ],
    )
    assert created.exit_code == 0, created.output
    return json.loads(created.stdout)


def test_pm_cli_project_wbs_and_schedule_journey_is_pure_json(tmp_path: Path) -> None:
    _initialize(tmp_path)
    created = _create(tmp_path)
    assert created["project"]["id"] == "MP-CLI"

    phase = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "phase",
            "add",
            "MP-CL",
            "Build",
            "--id",
            "PH-BUILD",
        ],
    )
    assert phase.exit_code == 0, phase.output
    assert json.loads(phase.stdout)["id"] == "PH-BUILD"

    design = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "work",
            "add",
            "MP-CL",
            "Design",
            "--days",
            "2",
            "--phase",
            "PH-BU",
            "--criterion",
            "Design reviewed",
            "--id",
            "WP-DESIGN",
        ],
    )
    assert design.exit_code == 0, design.output
    assert json.loads(design.stdout)["phase_id"] == "PH-BU"

    implementation = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "work",
            "add",
            "MP-CL",
            "Implement",
            "--days",
            "3",
            "--phase",
            "PH-BUILD",
            "--depends",
            "WP-DESIGN",
            "--criterion",
            "CI passes",
            "--id",
            "WP-IMPLEMENT",
        ],
    )
    assert implementation.exit_code == 0, implementation.output

    milestone = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "milestone",
            "add",
            "MP-CL",
            "Release",
            "--depends",
            "WP-IMPLEMENT",
            "--id",
            "MS-RELEASE",
        ],
    )
    assert milestone.exit_code == 0, milestone.output

    schedule = runner.invoke(
        app,
        [*_common(tmp_path), "schedule", "MP-CL", "--format", "mermaid"],
    )
    assert schedule.exit_code == 0, schedule.output
    rendered = json.loads(schedule.stdout)
    assert rendered["project_id"] == "MP-CLI"
    assert rendered["format"] == "mermaid"
    assert rendered["content"].startswith("gantt\n")
    assert "WP-DESIGN" not in schedule.stderr

    listed = runner.invoke(app, [*_common(tmp_path), "list", "--state", "proposed"])
    shown = runner.invoke(app, [*_common(tmp_path), "show", "MP-CL"])
    assert [item["project"]["id"] for item in json.loads(listed.stdout)] == ["MP-CLI"]
    assert json.loads(shown.stdout)["project"]["work_packages"][1]["id"] == "WP-IMPLEMENT"


def test_pm_cli_update_states_evidence_criteria_and_register(tmp_path: Path) -> None:
    _initialize(tmp_path)
    project = _create(tmp_path)
    project_id = project["project"]["id"]

    updated = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "update",
            "MP-CL",
            "--manager",
            "Ada",
            "--title",
            "Release R1.1",
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)["project"]["manager"] == "Ada"

    planned = runner.invoke(app, [*_common(tmp_path), "state", "MP-CL", "planned"])
    active = runner.invoke(app, [*_common(tmp_path), "state", "MP-CL", "active"])
    assert json.loads(planned.stdout)["project"]["lifecycle"] == "planned"
    assert json.loads(active.stdout)["project"]["lifecycle"] == "active"

    work = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "work",
            "add",
            "MP-CL",
            "Verify",
            "--days",
            "1",
            "--criterion",
            "System tests pass",
            "--id",
            "WP-VERIFY",
        ],
    )
    criterion_id = json.loads(work.stdout)["completion_criteria"][0]["id"]
    evidence = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "evidence",
            "add",
            "MP-CL",
            "CI run 42 passed",
            "--source",
            "ci://run/42",
            "--id",
            "EV-CI-42",
        ],
    )
    assert evidence.exit_code == 0, evidence.output
    resolved = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "criterion",
            "resolve",
            "MP-CL",
            criterion_id[:10],
            "--evidence",
            "EV-CI",
        ],
    )
    assert resolved.exit_code == 0, resolved.output
    assert json.loads(resolved.stdout)["status"] == "met"

    for state in ("ready", "in_progress", "completed"):
        result = runner.invoke(
            app,
            [*_common(tmp_path), "work", "state", "MP-CL", "WP-VER", state],
        )
        assert result.exit_code == 0, result.output
    shown = json.loads(runner.invoke(app, [*_common(tmp_path), "show", project_id]).stdout)
    assert shown["project"]["work_packages"][0]["status"] == "completed"

    risk = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "register",
            "add",
            "MP-CL",
            "risk",
            "Supplier delay",
            "--probability",
            "0.25",
            "--impact-cost",
            "400",
            "--impact-days",
            "5",
            "--id",
            "RI-SUPPLIER",
        ],
    )
    assert risk.exit_code == 0, risk.output
    changed = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "register",
            "update",
            "MP-CL",
            "RI-SUP",
            "--state",
            "closed",
            "--response",
            "Alternate supplier qualified",
        ],
    )
    assert changed.exit_code == 0, changed.output
    assert json.loads(changed.stdout)["expected_cost_exposure"] == "100.00"


def test_pm_cli_qcd_update_and_show_accept_decimal_and_dates(tmp_path: Path) -> None:
    _initialize(tmp_path)
    _create(tmp_path)

    updated = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "qcd",
            "update",
            "MP-CL",
            "forecast",
            "--cost",
            "1250.50",
            "--effort",
            "88.5",
            "--quality",
            "97.5",
            "--scope",
            "13",
            "--delivery",
            "2026-08-28",
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)["project"]["qcd"]["forecast"]["cost"] == "1250.50"

    shown = runner.invoke(app, [*_common(tmp_path), "qcd", "show", "MP-CL"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["forecast_delivery_variance_days"] is None

    malformed_decimal = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "qcd",
            "update",
            "MP-CL",
            "current",
            "--cost",
            "not-money",
        ],
    )
    assert malformed_decimal.exit_code == 2
    assert "decimal" in malformed_decimal.output.lower()


def test_pm_cli_rejects_malformed_dates_and_dependency_cycles_without_partial_write(
    tmp_path: Path,
) -> None:
    _initialize(tmp_path)
    malformed = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "create",
            "Bad date",
            "--goal",
            "Never persist",
            "--criterion",
            "Done",
            "--start",
            "03/08/2026",
        ],
    )
    assert malformed.exit_code == 2
    assert "ISO date" in malformed.output
    assert json.loads(runner.invoke(app, [*_common(tmp_path), "list"]).stdout) == []

    _create(tmp_path)
    for identifier, dependency in (("WP-A", None), ("WP-B", "WP-A")):
        args = [
            *_common(tmp_path),
            "work",
            "add",
            "MP-CL",
            identifier,
            "--days",
            "1",
            "--criterion",
            f"{identifier} done",
            "--id",
            identifier,
        ]
        if dependency:
            args.extend(["--depends", dependency])
        assert runner.invoke(app, args).exit_code == 0

    rejected = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "work",
            "update",
            "MP-CL",
            "WP-A",
            "--depends",
            "WP-B",
        ],
    )
    assert rejected.exit_code != 0
    assert isinstance(rejected.exception, ProjectScheduleError)
    shown = json.loads(runner.invoke(app, [*_common(tmp_path), "show", "MP-CL"]).stdout)
    first = next(item for item in shown["project"]["work_packages"] if item["id"] == "WP-A")
    assert first["dependency_ids"] == []


def test_pm_cli_projection_output_requires_force_before_overwrite(tmp_path: Path) -> None:
    _initialize(tmp_path)
    _create(tmp_path)
    runner.invoke(
        app,
        [
            *_common(tmp_path),
            "work",
            "add",
            "MP-CL",
            "Plan",
            "--days",
            "1",
            "--criterion",
            "Reviewed",
        ],
    )
    output = tmp_path / "views" / "schedule.md"
    first = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "schedule",
            "MP-CL",
            "--format",
            "markdown",
            "--output",
            str(output),
        ],
    )
    assert first.exit_code == 0, first.output
    assert output.read_text(encoding="utf-8").startswith("# Release R1")

    output.write_text("keep me\n", encoding="utf-8")
    refused = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "schedule",
            "MP-CL",
            "--format",
            "markdown",
            "--output",
            str(output),
        ],
    )
    assert refused.exit_code == 2
    assert "--force" in refused.output
    assert output.read_text(encoding="utf-8") == "keep me\n"

    forced = runner.invoke(
        app,
        [
            *_common(tmp_path),
            "schedule",
            "MP-CL",
            "--format",
            "markdown",
            "--output",
            str(output),
            "--force",
        ],
    )
    assert forced.exit_code == 0, forced.output
    assert output.read_text(encoding="utf-8").startswith("# Release R1")


def test_pm_cli_doctor_reports_clean_workspace_and_existing_cli_still_works(
    tmp_path: Path,
) -> None:
    _initialize(tmp_path)
    _create(tmp_path)
    report = runner.invoke(app, [*_common(tmp_path), "doctor"])
    assert report.exit_code == 0, report.output
    assert json.loads(report.stdout)["valid"] is True

    captured = runner.invoke(
        app,
        ["--workspace", str(tmp_path), "--json", "capture", "Check PM CLI"],
    )
    assert captured.exit_code == 0, captured.output
    assert json.loads(captured.stdout)["title"] == "Check PM CLI"
