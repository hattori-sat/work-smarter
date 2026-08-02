from __future__ import annotations

from datetime import date

from work_smarter.project_management.models import (
    BaselineRecord,
    BaselineScheduleItem,
    CompletionCriterion,
    DependencyType,
    ManagedProject,
    Milestone,
    ScheduleDependency,
    ScheduleItem,
    ScheduleProjection,
    WorkPackage,
)
from work_smarter.project_management.projections import render_html_gantt


def test_self_contained_html_gantt_has_required_layers_controls_and_escaping() -> None:
    work = WorkPackage(
        id="WP-BUILD",
        title='Build <script>alert("x")</script>',
        owner="Ada & Bob",
        duration_days=3,
        progress_percent=50,
        jira_status="In Progress",
        completion_criteria=[CompletionCriterion(id="CR-BUILD", description="Accepted")],
    )
    milestone = Milestone(
        id="MS-RELEASE",
        title="Release <candidate>",
        dependencies=[
            ScheduleDependency(
                predecessor_id=work.id,
                type=DependencyType.FINISH_TO_START,
            )
        ],
    )
    baseline = BaselineRecord(
        id="BASE-1",
        label="Approved",
        project_revision=1,
        content_hash="a" * 64,
        event_id="EV-1",
        schedule_items=[
            BaselineScheduleItem(
                id=work.id,
                start_on=date(2026, 8, 3),
                finish_on=date(2026, 8, 5),
            )
        ],
    )
    project = ManagedProject(
        id="MP-GANTT",
        title="Release & readiness",
        goal="Ship safely",
        completion_criteria=[CompletionCriterion(id="CR-P", description="Accepted")],
        work_packages=[work],
        milestones=[milestone],
        baselines=[baseline],
    )
    schedule = ScheduleProjection(
        project_id=project.id,
        anchor_on=date(2026, 8, 3),
        project_finish_on=date(2026, 8, 7),
        topological_order=[work.id, milestone.id],
        critical_path=[work.id, milestone.id],
        total_duration_days=5,
        items=[
            ScheduleItem(
                id=work.id,
                kind="work_package",
                title=work.title,
                duration_days=3,
                dependency_ids=[],
                scheduled_start_on=date(2026, 8, 4),
                scheduled_finish_on=date(2026, 8, 6),
                earliest_start_on=date(2026, 8, 4),
                earliest_finish_on=date(2026, 8, 6),
                latest_start_on=date(2026, 8, 4),
                latest_finish_on=date(2026, 8, 6),
                owner=work.owner,
                progress_percent=50,
                jira_status=work.jira_status,
                critical=True,
                total_float_days=0,
                delay_days=1,
            ),
            ScheduleItem(
                id=milestone.id,
                kind="milestone",
                title=milestone.title,
                duration_days=0,
                dependency_ids=[work.id],
                dependencies=milestone.dependencies,
                scheduled_start_on=date(2026, 8, 7),
                scheduled_finish_on=date(2026, 8, 7),
                earliest_start_on=date(2026, 8, 7),
                earliest_finish_on=date(2026, 8, 7),
                latest_start_on=date(2026, 8, 7),
                latest_finish_on=date(2026, 8, 7),
                critical=True,
                total_float_days=0,
            ),
        ],
    )

    html = render_html_gantt(project, schedule, today=date(2026, 8, 5))

    assert html.startswith("<!doctype html>")
    assert 'data-testid="gantt-chart"' in html
    assert 'id="gantt-filter"' in html
    assert 'id="gantt-zoom"' in html
    assert 'id="dependency-lines"' in html
    assert 'class="today-marker"' in html
    assert 'class="baseline-bar"' in html
    assert 'class="gantt-bar critical delayed"' in html
    assert 'class="progress" style="width:50%"' in html
    assert 'class="milestone critical"' in html
    assert "Finish-to-Start" in html
    assert "Ada &amp; Bob" in html
    assert "In Progress" in html
    assert "<script>alert" not in html
    assert "Build &lt;script&gt;alert" in html
    assert "Release &lt;candidate&gt;" in html
    assert "addEventListener" in html
    assert "https://" not in html
