from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from work_smarter.project_management.errors import ProjectScheduleError
from work_smarter.project_management.models import (
    DependencyType,
    ScheduleDependency,
    WorkingCalendar,
)
from work_smarter.project_management.service import ProjectManagementService


@pytest.fixture
def projects(tmp_path: Path) -> ProjectManagementService:
    from work_smarter.composition import initialize_workspace

    return ProjectManagementService(initialize_workspace(tmp_path))


def test_working_calendar_and_four_dependency_types_drive_schedule(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="Calendar schedule",
        goal="Explain every planned date",
        completion_criteria=["Accepted"],
        planned_start_on=date(2026, 8, 3),
        working_calendar=WorkingCalendar(
            working_weekdays=[0, 1, 2, 3, 4],
            non_working_days=[date(2026, 8, 7)],
        ),
        project_id="MP-CALENDAR",
    )
    projects.add_work_package(
        project.project.id,
        title="A",
        duration_days=4,
        work_package_id="WP-A",
    )
    projects.add_work_package(
        project.project.id,
        title="B",
        duration_days=3,
        dependencies=[
            ScheduleDependency(
                predecessor_id="WP-A",
                type=DependencyType.FINISH_TO_START,
                lag_days=1,
            )
        ],
        work_package_id="WP-B",
    )
    projects.add_work_package(
        project.project.id,
        title="C",
        duration_days=2,
        dependencies=[
            ScheduleDependency(
                predecessor_id="WP-B",
                type=DependencyType.START_TO_START,
                lag_days=1,
            )
        ],
        work_package_id="WP-C",
    )
    projects.add_work_package(
        project.project.id,
        title="D",
        duration_days=1,
        dependencies=[
            ScheduleDependency(
                predecessor_id="WP-B",
                type=DependencyType.FINISH_TO_FINISH,
                lag_days=1,
            )
        ],
        work_package_id="WP-D",
    )
    projects.add_work_package(
        project.project.id,
        title="E",
        duration_days=2,
        dependencies=[
            ScheduleDependency(
                predecessor_id="WP-B",
                type=DependencyType.START_TO_FINISH,
                lag_days=1,
            )
        ],
        work_package_id="WP-E",
    )
    projects.add_milestone(
        project.project.id,
        title="Release",
        milestone_id="MS-RELEASE",
        dependencies=[ScheduleDependency(predecessor_id="WP-D")],
    )

    schedule = projects.compute_schedule(project.project.id)
    items = {item.id: item for item in schedule.items}

    assert (items["WP-A"].earliest_start_on, items["WP-A"].earliest_finish_on) == (
        date(2026, 8, 3),
        date(2026, 8, 6),
    )
    # Friday is a configured holiday, then the weekend is skipped, and the
    # one-working-day lag leaves Monday as the gap.
    assert items["WP-B"].earliest_start_on == date(2026, 8, 11)
    assert items["WP-B"].earliest_finish_on == date(2026, 8, 13)
    assert items["WP-C"].earliest_start_on == date(2026, 8, 12)
    assert items["WP-D"].earliest_finish_on == date(2026, 8, 14)
    # Start-to-Finish constrains the successor's end boundary; a two-day E can
    # therefore occupy Monday/Tuesday and finish at Wednesday's boundary.
    assert items["WP-E"].earliest_finish_on == date(2026, 8, 11)
    assert items["MS-RELEASE"].earliest_start_on == date(2026, 8, 17)
    assert schedule.project_finish_on == date(2026, 8, 17)

    assert all(item.latest_start_on >= item.earliest_start_on for item in schedule.items)
    assert all(item.total_float_days >= 0 for item in schedule.items)
    assert all(item.free_float_days >= 0 for item in schedule.items)
    assert "WP-A" in schedule.critical_path
    assert "MS-RELEASE" in schedule.critical_path

    explanation = projects.explain_schedule(project.project.id, "WP-B")
    assert explanation.item_id == "WP-B"
    assert explanation.driving_predecessor_id == "WP-A"
    assert any("Finish-to-Start" in reason for reason in explanation.reasons)
    assert any("1 working day lag" in reason for reason in explanation.reasons)
    assert any("non-working" in reason for reason in explanation.reasons)


def test_negative_lag_is_a_lead_and_cycles_are_refused_without_partial_write(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="Lead schedule",
        goal="Overlap safely",
        completion_criteria=["Accepted"],
        planned_start_on=date(2026, 8, 3),
        project_id="MP-LEAD",
    )
    projects.add_work_package(
        project.project.id,
        title="Build",
        duration_days=4,
        work_package_id="WP-BUILD",
    )
    projects.add_work_package(
        project.project.id,
        title="Test",
        duration_days=2,
        dependencies=[
            ScheduleDependency(predecessor_id="WP-BUILD", lag_days=-1),
        ],
        work_package_id="WP-TEST",
    )
    schedule = projects.compute_schedule(project.project.id)
    test = next(item for item in schedule.items if item.id == "WP-TEST")
    assert test.earliest_start_on == date(2026, 8, 6)

    before = projects.get(project.project.id)
    with pytest.raises(ProjectScheduleError, match="dependency cycle"):
        projects.update_work_package(
            project.project.id,
            "WP-BUILD",
            dependencies=[ScheduleDependency(predecessor_id="WP-TEST")],
        )
    assert projects.get(project.project.id) == before


def test_baseline_captures_schedule_and_survives_current_plan_change(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="Baseline",
        goal="Compare plans",
        completion_criteria=["Accepted"],
        planned_start_on=date(2026, 8, 3),
        project_id="MP-BASELINE",
    )
    projects.add_work_package(
        project.project.id,
        title="Implement",
        duration_days=2,
        progress_percent=25,
        work_package_id="WP-IMPLEMENT",
    )
    baseline = projects.create_baseline(project.project.id, label="Approved plan")
    assert baseline.schedule_items[0].finish_on == date(2026, 8, 4)

    projects.update_work_package(
        project.project.id,
        "WP-IMPLEMENT",
        duration_days=5,
        progress_percent=60,
    )
    current = projects.compute_schedule(project.project.id).items[0]
    assert current.scheduled_finish_on == date(2026, 8, 7)
    assert current.progress_percent == 60
    assert projects.get(project.project.id).project.baselines[-1] == baseline


def test_typed_dependency_add_remove_is_audited_and_reloadable(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="Dependency mutation",
        goal="Keep precedence auditable",
        completion_criteria=["Accepted"],
        project_id="MP-DEPENDENCY",
    )
    for item_id in ("WP-FIRST", "WP-SECOND"):
        projects.add_work_package(
            project.project.id,
            title=item_id,
            duration_days=1,
            work_package_id=item_id,
        )

    updated = projects.add_dependency(
        project.project.id,
        "WP-SECOND",
        "WP-FIRST",
        dependency_type=DependencyType.FINISH_TO_FINISH,
        lag_days=2,
    )
    assert updated.dependencies[0].type is DependencyType.FINISH_TO_FINISH
    assert projects.compute_schedule(project.project.id).items[1].dependencies[0].lag_days == 2

    reloaded = ProjectManagementService(projects.workspace)
    persisted = reloaded.get(project.project.id).project.work_packages[1]
    assert persisted.dependencies == updated.dependencies
    assert projects.workspace.event_store.read_all()[-1].payload["changed_fields"] == [
        "dependencies"
    ]

    removed = projects.remove_dependency(project.project.id, "WP-SECOND", "WP-FIRST")
    assert removed.dependencies == []
    assert (
        ProjectManagementService(projects.workspace)
        .get(project.project.id)
        .project.work_packages[1]
        .dependencies
        == []
    )
