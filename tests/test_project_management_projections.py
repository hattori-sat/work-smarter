from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from work_smarter.project_management.models import (
    BaselineRecord,
    ChangeKind,
    ChangeRequest,
    ChangeStatus,
    CompletionCriterion,
    Constraint,
    EvidenceRecord,
    GateDecision,
    GateReview,
    Health,
    ManagedProject,
    Milestone,
    MilestoneStatus,
    Phase,
    QcdPlan,
    QcdProjection,
    QcdSnapshot,
    RegisterItem,
    RegisterItemKind,
    Requirement,
    ScheduleItem,
    ScheduleProjection,
    VerificationActivity,
    VerificationMethod,
    VerificationRecord,
    VerificationResult,
    WorkPackage,
    WorkStatus,
)
from work_smarter.project_management.projections import (
    render_html_project_report,
    render_markdown_project_report,
    render_mermaid_gantt,
    render_schedule_table,
)


def criterion(entity_id: str, description: str = "Accepted") -> CompletionCriterion:
    return CompletionCriterion(id=entity_id, description=description)


def empty_project(**changes: object) -> ManagedProject:
    values: dict[str, object] = {
        "id": "MP-REPORT",
        "title": "Release project",
        "goal": "Deliver a safe release",
        "completion_criteria": [criterion("CR-PROJECT")],
    }
    values.update(changes)
    return ManagedProject.model_validate(values)


def empty_schedule(project_id: str = "MP-REPORT") -> ScheduleProjection:
    return ScheduleProjection(
        project_id=project_id,
        anchor_on=date(2026, 9, 1),
        topological_order=[],
        critical_path=[],
        total_duration_days=0,
        items=[],
    )


def qcd_projection(project_id: str = "MP-REPORT") -> QcdProjection:
    return QcdProjection(
        project_id=project_id,
        current_cost_variance=Decimal("-400"),
        forecast_cost_variance=Decimal("80"),
        forecast_cost_variance_percent=Decimal("8.00"),
        current_effort_variance=Decimal("-45"),
        forecast_effort_variance=Decimal("10"),
        forecast_quality_variance=Decimal("-4"),
        forecast_delivery_variance_days=4,
        forecast_scope_variance=Decimal("0"),
        cost_health=Health.AMBER,
        delivery_health=Health.AMBER,
        quality_health=Health.AMBER,
        scope_health=Health.GREEN,
        overall_health=Health.AMBER,
    )


def test_empty_project_has_explicit_deterministic_views() -> None:
    project = empty_project()
    schedule = empty_schedule()

    terminal = render_schedule_table(project, schedule)
    assert terminal.splitlines()[0].startswith("ID ")
    assert "Forecast finish" in terminal
    assert "Float" in terminal
    assert terminal.endswith("(no scheduled items)")

    mermaid = render_mermaid_gantt(project, schedule)
    assert mermaid == (
        "gantt\n"
        "    title Release project\n"
        "    dateFormat YYYY-MM-DD\n"
        "    axisFormat %Y-%m-%d\n"
        "    %% No scheduled items\n"
    )

    html_report = render_html_project_report(project, schedule)
    assert html_report.startswith('<!doctype html>\n<html lang="en">')
    assert "Deliver a safe release" in html_report
    assert "No scheduled work" in html_report
    assert html_report.endswith("</html>\n")

    markdown = render_markdown_project_report(project, schedule)
    assert markdown.startswith("# Release project\n")
    assert "## QCD" in markdown
    assert "## Mermaid Gantt" in markdown
    assert "No data" in markdown


def test_chain_renders_planned_forecast_status_float_critical_and_milestone() -> None:
    phase = Phase(id="PH-BUILD", title="検証フェーズ", status=WorkStatus.IN_PROGRESS)
    design = WorkPackage(
        id="WP-DESIGN",
        title="設計",
        phase_id=phase.id,
        status=WorkStatus.COMPLETED,
        duration_days=2,
        start_on=date(2026, 9, 1),
        due_on=date(2026, 9, 2),
        completion_criteria=[criterion("CR-DESIGN")],
    )
    build = WorkPackage(
        id="WP-BUILD",
        title="実装",
        phase_id=phase.id,
        status=WorkStatus.IN_PROGRESS,
        duration_days=3,
        dependency_ids=[design.id],
        start_on=date(2026, 9, 3),
        due_on=date(2026, 9, 5),
        completion_criteria=[criterion("CR-BUILD")],
    )
    release = Milestone(
        id="MS-RELEASE",
        title="リリース",
        phase_id=phase.id,
        status=MilestoneStatus.ACHIEVED,
        dependency_ids=[build.id],
        planned_on=date(2026, 9, 7),
        achieved_on=date(2026, 9, 7),
    )
    project = empty_project(
        phases=[phase],
        work_packages=[design, build],
        milestones=[release],
    )
    schedule = ScheduleProjection(
        project_id=project.id,
        anchor_on=date(2026, 9, 1),
        # The renderer follows the computed stable order, not aggregate insertion.
        topological_order=[design.id, build.id, release.id],
        critical_path=[design.id, build.id, release.id],
        total_duration_days=7,
        items=[
            ScheduleItem(
                id=release.id,
                kind="milestone",
                title=release.title,
                duration_days=0,
                dependency_ids=[build.id],
                scheduled_start_on=date(2026, 9, 7),
                scheduled_finish_on=date(2026, 9, 7),
                total_float_days=0,
                critical=True,
            ),
            ScheduleItem(
                id=build.id,
                kind="work_package",
                title=build.title,
                duration_days=3,
                dependency_ids=[design.id],
                scheduled_start_on=date(2026, 9, 3),
                scheduled_finish_on=date(2026, 9, 5),
                due_on=build.due_on,
                total_float_days=0,
                critical=True,
            ),
            ScheduleItem(
                id=design.id,
                kind="work_package",
                title=design.title,
                duration_days=2,
                dependency_ids=[],
                scheduled_start_on=date(2026, 9, 1),
                scheduled_finish_on=date(2026, 9, 2),
                due_on=design.due_on,
                total_float_days=0,
                critical=True,
            ),
        ],
    )

    terminal = render_schedule_table(project, schedule)
    assert terminal.index("WP-DESIGN") < terminal.index("WP-BUILD") < terminal.index("MS-RELEASE")
    assert "2026-09-03" in terminal
    assert "in_progress" in terminal
    assert re.search(r"WP-BUILD\s+\|.*\| 3\s+\| 0\s+\| \*", terminal)

    mermaid = render_mermaid_gantt(project, schedule)
    assert "section 検証フェーズ" in mermaid
    assert re.search(r"設計 :crit, done, ws_wp_design_[0-9a-f]{8}, 2026-09-01, 2d", mermaid)
    assert re.search(r"実装 :crit, active, ws_wp_build_[0-9a-f]{8}", mermaid)
    assert re.search(r"リリース :crit, done, milestone, ws_ms_release_[0-9a-f]{8}", mermaid)


def test_parallel_critical_work_is_stable_and_each_critical_item_is_marked() -> None:
    left = WorkPackage(
        id="WP-LEFT",
        title="Left branch",
        duration_days=2,
        completion_criteria=[criterion("CR-LEFT")],
    )
    right = WorkPackage(
        id="WP-RIGHT",
        title="Right branch",
        duration_days=2,
        completion_criteria=[criterion("CR-RIGHT")],
    )
    project = empty_project(work_packages=[right, left])
    schedule = ScheduleProjection(
        project_id=project.id,
        anchor_on=date(2026, 9, 1),
        topological_order=[left.id, right.id],
        critical_path=[left.id],
        total_duration_days=2,
        items=[
            ScheduleItem(
                id=right.id,
                kind="work_package",
                title=right.title,
                duration_days=2,
                dependency_ids=[],
                scheduled_start_on=date(2026, 9, 1),
                scheduled_finish_on=date(2026, 9, 2),
                critical=True,
                total_float_days=0,
            ),
            ScheduleItem(
                id=left.id,
                kind="work_package",
                title=left.title,
                duration_days=2,
                dependency_ids=[],
                scheduled_start_on=date(2026, 9, 1),
                scheduled_finish_on=date(2026, 9, 2),
                critical=True,
                total_float_days=0,
            ),
        ],
    )

    first = render_mermaid_gantt(project, schedule)
    assert first == render_mermaid_gantt(project, schedule)
    assert first.index("Left branch") < first.index("Right branch")
    assert first.count(":crit,") == 2


def test_html_report_escapes_all_user_text_and_shows_qcd_and_registers() -> None:
    hostile_title = 'Release <script>alert("x")</script> & QCD'
    hostile_goal = '<img src=x onerror="alert(1)"> | deliver'
    phase = Phase(id="PH-SAFE", title="Phase <unsafe>")
    work = WorkPackage(
        id="WP-SAFE",
        title="Build : %% <b>bold</b>",
        phase_id=phase.id,
        duration_days=1,
        completion_criteria=[criterion("CR-SAFE")],
    )
    milestone = Milestone(id="MS-SAFE", title="Gate <iframe>", phase_id=phase.id)
    risk = RegisterItem(
        id="RI-RISK",
        kind=RegisterItemKind.RISK,
        title="Supplier <b>delay</b>",
        description="Unsafe </td><script>boom()</script> [run](javascript:boom)",
        probability=Decimal("0.25"),
        impact_cost=Decimal("400"),
        impact_days=5,
        response="Use A | B & C",
    )
    evidence = EvidenceRecord(
        id="EV-SAFE",
        statement="Observed <expected> result",
        source="ci://run/<42>",
    )
    requirement = Requirement(
        id="REQ-SAFE",
        title="Safe <requirement>",
        statement="The output shall resist [links](javascript:boom)",
        source="Stakeholder <Ada>",
        required_activities=[VerificationActivity.VERIFICATION, VerificationActivity.VALIDATION],
    )
    verification = VerificationRecord(
        id="VV-SAFE",
        activity=VerificationActivity.VERIFICATION,
        method=VerificationMethod.TEST,
        result=VerificationResult.PASS,
        requirement_ids=[requirement.id],
        evidence_ids=[evidence.id],
        performed_at=datetime(2026, 9, 2, 3, 4, tzinfo=UTC),
        notes="Executed with <script>bad()</script>",
    )
    gate = GateReview(
        id="GR-SAFE",
        title="Commit <gate>",
        reviewed_at=datetime(2026, 9, 3, tzinfo=UTC),
        criterion_ids=["CR-PROJECT"],
        evidence_ids=[evidence.id],
        decision=GateDecision.GO,
        rationale="Evidence > opinion & haste",
    )
    change = ChangeRequest(
        id="CHG-SAFE",
        title="Change <scope>",
        kind=ChangeKind.SCOPE,
        status=ChangeStatus.APPROVED,
        target_ids=[requirement.id],
        before="Unsafe <before>",
        after="Safe </td><after>",
        qcd_impact="Cost + 1 & day",
        vv_impact="Repeat [test](javascript:bad)",
        decision="Approve <now>",
        rationale="Risk reduced > cost",
        requested_at=datetime(2026, 9, 3, tzinfo=UTC),
        decided_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    baseline = BaselineRecord(
        id="BL-SAFE",
        label="Commit <baseline>",
        project_revision=7,
        content_hash="a" * 64,
        event_id="EVT-SAFE",
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    qcd = QcdPlan(
        baseline=QcdSnapshot(
            cost=Decimal("1000"),
            effort_hours=Decimal("100"),
            quality_percent=Decimal("98"),
            scope_units=Decimal("20"),
            delivery_on=date(2026, 10, 1),
        ),
        current=QcdSnapshot(
            cost=Decimal("600"),
            effort_hours=Decimal("55"),
            quality_percent=Decimal("97"),
            scope_units=Decimal("12"),
            delivery_on=date(2026, 9, 10),
        ),
        forecast=QcdSnapshot(
            cost=Decimal("1080"),
            effort_hours=Decimal("110"),
            quality_percent=Decimal("94"),
            scope_units=Decimal("20"),
            delivery_on=date(2026, 10, 5),
        ),
    )
    project = empty_project(
        title=hostile_title,
        goal=hostile_goal,
        phases=[phase],
        work_packages=[work],
        milestones=[milestone],
        register_items=[risk],
        evidence=[evidence],
        requirements=[requirement],
        verification_records=[verification],
        gate_reviews=[gate],
        change_requests=[change],
        baselines=[baseline],
        constraints=[Constraint(id="CO-SAFE", statement="Never use <raw>")],
        qcd=qcd,
    )
    schedule = ScheduleProjection(
        project_id=project.id,
        anchor_on=date(2026, 9, 1),
        topological_order=[work.id, milestone.id],
        critical_path=[work.id, milestone.id],
        total_duration_days=1,
        items=[
            ScheduleItem(
                id=work.id,
                kind="work_package",
                title=work.title,
                duration_days=1,
                dependency_ids=[],
                scheduled_start_on=date(2026, 9, 1),
                scheduled_finish_on=date(2026, 9, 1),
                critical=True,
                total_float_days=0,
            ),
            ScheduleItem(
                id=milestone.id,
                kind="milestone",
                title=milestone.title,
                duration_days=0,
                dependency_ids=[work.id],
                scheduled_start_on=date(2026, 9, 1),
                scheduled_finish_on=date(2026, 9, 1),
                critical=True,
                total_float_days=0,
            ),
        ],
    )

    report = render_html_project_report(project, schedule, qcd_projection())
    assert "<script>" not in report
    assert "<img " not in report
    assert "<iframe>" not in report
    assert "</td><script>" not in report
    assert "&lt;script&gt;" in report
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in report
    assert "Supplier &lt;b&gt;delay&lt;/b&gt;" in report
    assert "Overall QCD health: amber" in report
    assert "1080" in report
    assert "Forecast variance" in report
    assert "80" in report
    assert "Risk, opportunity, issue, and decision register" in report
    assert "Critical path" in report
    assert "Requirements" in report
    assert "Verification and validation" in report
    assert "Gate reviews" in report
    assert "Change requests" in report
    assert "Baselines" in report
    assert "Safe &lt;requirement&gt;" in report
    assert "Executed with &lt;script&gt;bad()&lt;/script&gt;" in report
    assert "Commit &lt;gate&gt;" in report
    assert "Safe &lt;/td&gt;&lt;after&gt;" in report
    assert "Commit &lt;baseline&gt;" in report

    markdown = render_markdown_project_report(project, schedule, qcd_projection())
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "Use A \\| B &amp; C" in markdown
    assert "\\[run\\](javascript:boom)" in markdown
    assert "\\[links\\](javascript:boom)" in markdown
    assert "\\[test\\](javascript:bad)" in markdown
    assert "```mermaid" in markdown
    # Mermaid labels are grammar-safe while preserving useful Unicode text.
    assert "%% <b>" not in markdown
    assert "Build bold" in markdown
