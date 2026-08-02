from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from work_smarter.project_management import ProjectManagementFeature
from work_smarter.project_management.errors import (
    ProjectCompletionGateError,
    ProjectLinkError,
    ProjectScheduleError,
    ProjectTransitionError,
)
from work_smarter.project_management.models import (
    ChangeKind,
    ChangeStatus,
    CompletionCriterionStatus,
    GateDecision,
    ManagedProject,
    MilestoneStatus,
    ProjectLifecycle,
    QcdPlan,
    QcdSnapshot,
    RegisterItemKind,
    RegisterItemStatus,
    RequirementKind,
    RequirementStatus,
    VerificationActivity,
    VerificationMethod,
    VerificationResult,
    WorkStatus,
)
from work_smarter.project_management.persistence import (
    PROJECT_MANAGEMENT_ENTITY_SPECS,
    migrate_project_metadata,
)
from work_smarter.project_management.service import ProjectManagementService
from work_smarter.project_management.templates import (
    initialize_project_management_templates,
    managed_project_template_path,
)
from work_smarter.storage.frontmatter import read_markdown, write_markdown
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace


class GenericTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["task"] = "task"
    title: str


@pytest.fixture
def project_workspace(tmp_path: Path) -> Workspace:
    registry = EntityRegistry(PROJECT_MANAGEMENT_ENTITY_SPECS)
    workspace = Workspace.initialize(tmp_path, registry)
    initialize_project_management_templates(workspace)
    return workspace


@pytest.fixture
def projects(project_workspace: Workspace) -> ProjectManagementService:
    return ProjectManagementService(project_workspace)


def test_feature_is_independent_and_initializes_non_destructive_template(tmp_path: Path) -> None:
    from work_smarter.features import FeatureRegistry

    registry = FeatureRegistry()
    ProjectManagementFeature().register(registry)
    spec = registry.entity_registry().require("managed_project")
    assert spec.model is ManagedProject
    assert spec.directory == "projects/managed"

    workspace = Workspace.initialize(tmp_path, registry.entity_registry())
    for initializer in registry.workspace_initializers:
        initializer(workspace)
    template = managed_project_template_path(workspace)
    assert "## Delivery strategy" in template.read_text(encoding="utf-8")
    assert len(list(template.parent.glob("*.md"))) == 12
    assert (template.parent / "gate-review.md").is_file()

    template.write_text("# My project template\n", encoding="utf-8")
    for initializer in registry.workspace_initializers:
        initializer(workspace)
    assert template.read_text(encoding="utf-8") == "# My project template\n"

    source_root = Path(__file__).parents[1] / "src"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import work_smarter.project_management; import sys; "
                "assert 'work_smarter.gtd' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source_root)},
    )
    assert completed.returncode == 0, completed.stderr


def test_schema_is_strict_and_nested_ids_are_unique() -> None:
    with pytest.raises(ValidationError):
        ManagedProject.model_validate(
            {
                "id": "MP-1",
                "title": "Strict",
                "goal": "Deliver it",
                "completion_criteria": [{"id": "CR-1", "description": "Accepted"}],
                "typo_field": True,
            }
        )

    with pytest.raises(ValidationError, match="nested IDs must be unique"):
        ManagedProject.model_validate(
            {
                "id": "MP-1",
                "title": "Duplicate",
                "goal": "Deliver it",
                "completion_criteria": [{"id": "NESTED-1", "description": "Accepted"}],
                "constraints": [{"id": "NESTED-1", "statement": "Fixed budget"}],
            }
        )

    migrated = migrate_project_metadata(
        {
            "schema_version": 0,
            "id": "MP-OLD",
            "title": "Old",
            "goal": "Migrate safely",
            "status": "planned",
            "completion_criteria": [{"id": "CR-OLD", "description": "Done"}],
        }
    )
    assert migrated["schema_version"] == 1
    assert migrated["lifecycle"] == "planned"
    assert "status" not in migrated
    with pytest.raises(ValueError, match="unsupported managed project schema"):
        migrate_project_metadata({"schema_version": 99})


def test_create_update_list_reload_body_and_audit(
    projects: ProjectManagementService,
    project_workspace: Workspace,
) -> None:
    created = projects.create(
        title="  Flight software release ",
        goal=" Ship a safe release ",
        constraints=["Budget is fixed"],
        assumptions=["Test rig remains available"],
        completion_criteria=["Release is accepted"],
        planned_start_on=date(2026, 8, 3),
        target_due_on=date(2026, 8, 31),
    )
    assert created.project.title == "Flight software release"
    assert created.project.goal == "Ship a safe release"
    assert created.project.lifecycle is ProjectLifecycle.PROPOSED
    assert created.path == f"projects/managed/{created.project.id}.md"
    assert "## Delivery strategy" in created.body
    assert created.project.constraints[0].statement == "Budget is fixed"
    assert created.project.completion_criteria[0].description == "Release is accepted"

    updated = projects.update(
        created.project.id[:10],
        title="Flight software R1",
        body="# Working agreement\n\nText is authoritative.\n",
        manager="Ada",
    )
    assert updated.project.revision == 2
    assert updated.project.manager == "Ada"
    assert updated.body == "# Working agreement\n\nText is authoritative.\n"
    assert [item.project.id for item in projects.list()] == [created.project.id]
    assert ProjectManagementService(project_workspace).get(created.project.id) == updated

    events = project_workspace.event_store.read_all()
    assert [event.type for event in events] == [
        "project_management.project.created",
        "project_management.project.updated",
    ]
    assert events[-1].payload["revision"] == 2


def test_allowed_and_refused_lifecycle_transitions_are_durable_and_audited(
    projects: ProjectManagementService,
    project_workspace: Workspace,
) -> None:
    project = projects.create(title="Lifecycle", goal="Deliver", completion_criteria=["Done"])
    planned = projects.transition_project(project.project.id, ProjectLifecycle.PLANNED)
    active = projects.transition_project(project.project.id, ProjectLifecycle.ACTIVE)
    assert planned.project.lifecycle is ProjectLifecycle.PLANNED
    assert active.project.lifecycle is ProjectLifecycle.ACTIVE
    assert ProjectManagementService(project_workspace).get(project.project.id).project.revision == 3

    event_count = len(project_workspace.event_store.read_all())
    with pytest.raises(ProjectTransitionError, match="active.*proposed"):
        projects.transition_project(project.project.id, ProjectLifecycle.PROPOSED)
    reloaded = projects.get(project.project.id)
    assert reloaded.project.lifecycle is ProjectLifecycle.ACTIVE
    assert reloaded.project.revision == 3
    assert len(project_workspace.event_store.read_all()) == event_count


def test_wbs_mutations_reject_missing_dependencies_and_cycles_without_partial_write(
    projects: ProjectManagementService,
    project_workspace: Workspace,
) -> None:
    project = projects.create(title="WBS", goal="Deliver", completion_criteria=["Accepted"])
    phase = projects.add_phase(project.project.id, title="Build", phase_id="PH-BUILD")
    first = projects.add_work_package(
        project.project.id,
        title="Design",
        phase_id=phase.id,
        duration_days=3,
        work_package_id="WP-DESIGN",
        completion_criteria=["Design reviewed"],
    )
    second = projects.add_work_package(
        project.project.id,
        title="Implement",
        phase_id=phase.id,
        duration_days=5,
        dependency_ids=[first.id],
        work_package_id="WP-IMPLEMENT",
        completion_criteria=["Tests pass"],
    )
    assert second.dependency_ids == [first.id]

    revision = projects.get(project.project.id).project.revision
    event_count = len(project_workspace.event_store.read_all())
    with pytest.raises(ProjectScheduleError, match="missing dependency"):
        projects.add_work_package(
            project.project.id,
            title="Bad",
            duration_days=1,
            dependency_ids=["WP-MISSING"],
            completion_criteria=["Never"],
        )
    with pytest.raises(ProjectScheduleError, match="cycle"):
        projects.update_work_package(
            project.project.id,
            first.id,
            dependency_ids=[second.id],
        )
    assert projects.get(project.project.id).project.revision == revision
    assert len(project_workspace.event_store.read_all()) == event_count


def test_schedule_is_deterministic_preserves_constraints_and_selects_ties_by_id(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="Schedule",
        goal="Predict delivery",
        completion_criteria=["Delivered"],
        planned_start_on=date(2026, 9, 1),
    )
    # Equal branches deliberately use reverse insertion order. Lexical IDs break the tie.
    projects.add_work_package(
        project.project.id,
        title="Branch B",
        duration_days=2,
        work_package_id="WP-B",
        start_on=date(2026, 9, 3),
        completion_criteria=["B done"],
    )
    projects.add_work_package(
        project.project.id,
        title="Branch A",
        duration_days=2,
        work_package_id="WP-A",
        start_on=date(2026, 9, 3),
        due_on=date(2026, 9, 3),
        completion_criteria=["A done"],
    )
    projects.add_work_package(
        project.project.id,
        title="Join",
        duration_days=1,
        work_package_id="WP-JOIN",
        dependency_ids=["WP-B", "WP-A"],
        completion_criteria=["Joined"],
    )
    projects.add_milestone(
        project.project.id,
        title="Release",
        milestone_id="MS-RELEASE",
        dependency_ids=["WP-JOIN"],
        planned_on=date(2026, 9, 6),
    )

    projection = projects.compute_schedule(project.project.id)
    assert projection.topological_order == ["WP-A", "WP-B", "WP-JOIN", "MS-RELEASE"]
    assert projection.critical_path == ["WP-A", "WP-JOIN", "MS-RELEASE"]
    assert projection.total_duration_days == 5
    by_id = {item.id: item for item in projection.items}
    assert by_id["WP-A"].scheduled_start_on == date(2026, 9, 3)
    assert by_id["WP-A"].scheduled_finish_on == date(2026, 9, 4)
    assert by_id["WP-A"].constraint_violation == "finishes after due date 2026-09-03"
    assert by_id["MS-RELEASE"].scheduled_finish_on == date(2026, 9, 6)
    assert by_id["WP-A"].total_float_days == 0


def test_completion_gates_require_evidence_and_nested_delivery(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(title="Gate", goal="Deliver", completion_criteria=["Accepted"])
    phase = projects.add_phase(project.project.id, title="Build", phase_id="PH-1")
    work = projects.add_work_package(
        project.project.id,
        title="Implementation",
        phase_id=phase.id,
        duration_days=1,
        work_package_id="WP-1",
        completion_criteria=["Tests pass"],
    )
    milestone = projects.add_milestone(
        project.project.id,
        title="Release gate",
        phase_id=phase.id,
        milestone_id="MS-1",
    )

    projects.transition_project(project.project.id, ProjectLifecycle.PLANNED)
    projects.transition_project(project.project.id, ProjectLifecycle.ACTIVE)
    projects.transition_phase(project.project.id, phase.id, WorkStatus.READY)
    projects.transition_phase(project.project.id, phase.id, WorkStatus.IN_PROGRESS)
    projects.transition_work_package(project.project.id, work.id, WorkStatus.READY)
    projects.transition_work_package(project.project.id, work.id, WorkStatus.IN_PROGRESS)

    with pytest.raises(ProjectCompletionGateError, match="completion criteria"):
        projects.transition_work_package(project.project.id, work.id, WorkStatus.COMPLETED)

    work_evidence = projects.record_evidence(
        project.project.id, statement="CI run 42 passed", source="ci://run/42"
    )
    projects.update_completion_criterion(
        project.project.id,
        work.completion_criteria[0].id,
        status=CompletionCriterionStatus.MET,
        evidence_ids=[work_evidence.id],
    )
    projects.transition_work_package(project.project.id, work.id, WorkStatus.COMPLETED)
    projects.transition_milestone(project.project.id, milestone.id, MilestoneStatus.ACHIEVED)
    projects.transition_phase(project.project.id, phase.id, WorkStatus.COMPLETED)

    with pytest.raises(ProjectCompletionGateError, match="completion criteria"):
        projects.transition_project(project.project.id, ProjectLifecycle.COMPLETED)
    project_evidence = projects.record_evidence(
        project.project.id, statement="Sponsor accepted release", source="mail://acceptance"
    )
    projects.update_completion_criterion(
        project.project.id,
        project.project.completion_criteria[0].id,
        status=CompletionCriterionStatus.MET,
        evidence_ids=[project_evidence.id],
    )
    completed = projects.transition_project(project.project.id, ProjectLifecycle.COMPLETED)
    assert completed.project.lifecycle is ProjectLifecycle.COMPLETED


def test_register_and_qcd_projection_use_decimal_math_and_health_thresholds(
    projects: ProjectManagementService,
) -> None:
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
    project = projects.create(
        title="QCD",
        goal="Control delivery",
        completion_criteria=["Accepted"],
        qcd=qcd,
    )
    risk = projects.add_register_item(
        project.project.id,
        kind=RegisterItemKind.RISK,
        title="Supplier delay",
        probability=Decimal("0.25"),
        impact_cost=Decimal("400"),
        impact_days=5,
        register_item_id="RI-1",
    )
    closed = projects.update_register_item(
        project.project.id,
        risk.id,
        status=RegisterItemStatus.CLOSED,
        response="Alternate supplier qualified",
    )
    assert closed.expected_cost_exposure == Decimal("100.00")

    projection = projects.qcd_projection(project.project.id)
    assert projection.current_cost_variance == Decimal("-400")
    assert projection.forecast_cost_variance == Decimal("80")
    assert projection.forecast_cost_variance_percent == Decimal("8.00")
    assert projection.forecast_delivery_variance_days == 4
    assert projection.forecast_quality_variance == Decimal("-4")
    assert projection.cost_health == "amber"
    assert projection.delivery_health == "amber"
    assert projection.quality_health == "amber"
    assert projection.overall_health == "amber"


def test_gtd_links_use_generic_workspace_contract_and_do_not_import_gtd(tmp_path: Path) -> None:
    registry = EntityRegistry(
        (
            *PROJECT_MANAGEMENT_ENTITY_SPECS,
            EntitySpec("task", GenericTask, "tasks"),
        )
    )
    workspace = Workspace.initialize(tmp_path, registry)
    workspace.write(GenericTask(id="TASK-ABC123", title="Independent action"), "")
    service = ProjectManagementService(workspace)

    project = service.create(
        title="Linked",
        goal="Coordinate",
        completion_criteria=["Done"],
        gtd_action_ids=["TASK-ABC"],
    )
    assert project.project.gtd_action_ids == ["TASK-ABC123"]
    work = service.add_work_package(
        project.project.id,
        title="Execute",
        duration_days=1,
        completion_criteria=["Executed"],
        gtd_action_ids=["TASK-ABC"],
    )
    assert work.gtd_action_ids == ["TASK-ABC123"]

    with pytest.raises(ProjectLinkError, match="does not exist"):
        service.update(project.project.id, gtd_action_ids=["TASK-MISSING"])


def test_doctor_reports_direct_edit_corruption_graph_and_links(
    projects: ProjectManagementService,
    project_workspace: Workspace,
) -> None:
    valid = projects.create(title="Doctor", goal="Inspect", completion_criteria=["Clean"])
    projects.add_work_package(
        valid.project.id,
        title="One",
        duration_days=1,
        work_package_id="WP-1",
        completion_criteria=["One done"],
    )
    projects.add_work_package(
        valid.project.id,
        title="Two",
        duration_days=1,
        work_package_id="WP-2",
        dependency_ids=["WP-1"],
        completion_criteria=["Two done"],
    )

    path = project_workspace.root / f"projects/managed/{valid.project.id}.md"
    document = read_markdown(path)
    metadata = dict(document.metadata)
    metadata["work_packages"][0]["dependency_ids"] = ["WP-2"]
    metadata["gtd_action_ids"] = ["TASK-NOT-THERE"]
    write_markdown(path, metadata, document.body)

    malformed_path = project_workspace.root / "projects/managed/MP-MALFORMED.md"
    malformed_path.write_text("---\nid: MP-MALFORMED\nkind: managed_project\nunknown: true\n---\n")

    report = projects.doctor()
    assert not report.valid
    assert {issue.code for issue in report.issues} >= {
        "dependency_cycle",
        "broken_gtd_link",
        "malformed_document",
    }
    assert report.counts["projects"] == 1
    assert report.counts["errors"] >= 3


def test_requirements_vv_gates_changes_and_baselines_are_traceable(
    projects: ProjectManagementService,
    project_workspace: Workspace,
) -> None:
    project = projects.create(
        title="Assured delivery",
        goal="Release verified and useful behavior",
        completion_criteria=["Sponsor accepts evidence"],
    )
    requirement = projects.add_requirement(
        project.project.id,
        requirement_id="REQ-1",
        title="Fail-safe output",
        statement="The output enters a safe state after detected corruption.",
        kind=RequirementKind.FUNCTIONAL,
        status=RequirementStatus.APPROVED,
        required_activities=[
            VerificationActivity.VERIFICATION,
            VerificationActivity.VALIDATION,
        ],
    )
    evidence = projects.record_evidence(
        project.project.id,
        statement="Fault-injection run passed",
        source="test://fault-injection/17",
    )
    verification = projects.record_verification(
        project.project.id,
        activity=VerificationActivity.VERIFICATION,
        method=VerificationMethod.TEST,
        result=VerificationResult.PASS,
        requirement_ids=[requirement.id],
        evidence_ids=[evidence.id],
        notes="Observed the specified safe state.",
    )
    assert verification.requirement_ids == ["REQ-1"]
    with pytest.raises(ProjectLinkError, match="requirement"):
        projects.record_verification(
            project.project.id,
            activity=VerificationActivity.VALIDATION,
            method=VerificationMethod.DEMONSTRATION,
            result=VerificationResult.PASS,
            requirement_ids=["REQ-MISSING"],
            evidence_ids=[evidence.id],
        )

    gate = projects.record_gate_review(
        project.project.id,
        title="Release readiness",
        criterion_ids=[project.project.completion_criteria[0].id],
        evidence_ids=[evidence.id],
        exceptions=["Validation remains open"],
        decision=GateDecision.CONDITIONAL_GO,
        rationale="Verification evidence is sufficient for the next phase.",
    )
    assert gate.decision is GateDecision.CONDITIONAL_GO

    change = projects.add_change_request(
        project.project.id,
        change_request_id="CHG-1",
        title="Adjust safe-state latency",
        kind=ChangeKind.REQUIREMENT,
        target_ids=[requirement.id],
        before="100 ms",
        after="120 ms",
        qcd_impact="Reduces implementation cost without changing delivery date.",
        vv_impact="Repeat timing analysis and fault-injection test.",
    )
    decided = projects.update_change_request(
        project.project.id,
        change.id,
        status=ChangeStatus.APPROVED,
        decision="Approve the controlled relaxation.",
        rationale="System hazard analysis accepts the new bound.",
    )
    assert decided.status is ChangeStatus.APPROVED

    baseline = projects.create_baseline(project.project.id, label="SRR approved baseline")
    assert baseline.project_revision >= 1
    assert len(baseline.content_hash) == 64
    reloaded = ProjectManagementService(project_workspace).get(project.project.id).project
    assert reloaded.baselines == [baseline]
    assert project_workspace.event_store.read_all()[-1].id == baseline.event_id


def test_project_completion_checks_required_vv_results(
    projects: ProjectManagementService,
) -> None:
    project = projects.create(
        title="V&V gate", goal="Assured outcome", completion_criteria=["Done"]
    )
    requirement = projects.add_requirement(
        project.project.id,
        title="Useful workflow",
        statement="The user can complete the primary workflow.",
        status=RequirementStatus.APPROVED,
        required_activities=[VerificationActivity.VALIDATION],
    )
    evidence = projects.record_evidence(
        project.project.id,
        statement="Acceptance session completed",
        source="session://acceptance/1",
    )
    projects.update_completion_criterion(
        project.project.id,
        project.project.completion_criteria[0].id,
        status=CompletionCriterionStatus.MET,
        evidence_ids=[evidence.id],
    )
    projects.transition_project(project.project.id, ProjectLifecycle.PLANNED)
    projects.transition_project(project.project.id, ProjectLifecycle.ACTIVE)
    with pytest.raises(ProjectCompletionGateError, match="validation"):
        projects.transition_project(project.project.id, ProjectLifecycle.COMPLETED)

    projects.record_verification(
        project.project.id,
        activity=VerificationActivity.VALIDATION,
        method=VerificationMethod.DEMONSTRATION,
        result=VerificationResult.PASS,
        requirement_ids=[requirement.id],
        evidence_ids=[evidence.id],
    )
    completed = projects.transition_project(project.project.id, ProjectLifecycle.COMPLETED)
    assert completed.project.lifecycle is ProjectLifecycle.COMPLETED
