"""Typed HTTP adapter for the independent managed-project feature."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from work_smarter.project_management.gantt import HtmlGanttRenderer
from work_smarter.project_management.models import (
    BaselineRecord,
    CompletionCriterion,
    CompletionCriterionStatus,
    EvidenceRecord,
    ManagedProjectDocument,
    Milestone,
    MilestoneStatus,
    Phase,
    ProjectDoctorReport,
    ProjectLifecycle,
    QcdPlan,
    QcdProjection,
    RegisterItem,
    RegisterItemKind,
    RegisterItemStatus,
    ScheduleDependency,
    ScheduleExplanation,
    ScheduleProjection,
    WorkingCalendar,
    WorkPackage,
    WorkStatus,
)
from work_smarter.project_management.projections import (
    render_html_project_report,
    render_markdown_project_report,
    render_mermaid_gantt,
    render_schedule_table,
)
from work_smarter.project_management.service import ProjectManagementService

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EntityId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,127}$",
    ),
]


class ProjectApiModel(BaseModel):
    """Reject unknown fields so automation mistakes cannot silently mutate a project."""

    model_config = ConfigDict(extra="forbid")


class ProjectCreateRequest(ProjectApiModel):
    title: NonBlankString
    goal: NonBlankString
    body: str | None = None
    sponsor: NonBlankString | None = None
    manager: NonBlankString | None = None
    planned_start_on: date | None = None
    target_due_on: date | None = None
    working_calendar: WorkingCalendar | None = None
    constraints: list[NonBlankString] = Field(default_factory=list)
    assumptions: list[NonBlankString] = Field(default_factory=list)
    completion_criteria: list[NonBlankString] = Field(min_length=1)
    qcd: QcdPlan | None = None
    gtd_action_ids: list[EntityId] = Field(default_factory=list)
    project_id: EntityId | None = None


class ProjectUpdateRequest(ProjectApiModel):
    title: NonBlankString | None = None
    goal: NonBlankString | None = None
    body: str | None = None
    sponsor: NonBlankString | None = None
    manager: NonBlankString | None = None
    planned_start_on: date | None = None
    target_due_on: date | None = None
    working_calendar: WorkingCalendar | None = None
    qcd: QcdPlan | None = None
    gtd_action_ids: list[EntityId] | None = None


class ProjectLifecycleRequest(ProjectApiModel):
    lifecycle: ProjectLifecycle


class PhaseCreateRequest(ProjectApiModel):
    title: NonBlankString
    description: NonBlankString | None = None
    owner: NonBlankString | None = None
    start_on: date | None = None
    due_on: date | None = None
    completion_criteria: list[NonBlankString] = Field(default_factory=list)
    phase_id: EntityId | None = None


class PhaseUpdateRequest(ProjectApiModel):
    title: NonBlankString | None = None
    description: NonBlankString | None = None
    owner: NonBlankString | None = None
    start_on: date | None = None
    due_on: date | None = None


class WorkPackageCreateRequest(ProjectApiModel):
    title: NonBlankString
    duration_days: int = Field(ge=1)
    completion_criteria: list[NonBlankString] = Field(min_length=1)
    description: NonBlankString | None = None
    phase_id: EntityId | None = None
    owner: NonBlankString | None = None
    dependency_ids: list[EntityId] = Field(default_factory=list)
    dependencies: list[ScheduleDependency] = Field(default_factory=list)
    start_on: date | None = None
    due_on: date | None = None
    progress_percent: int = Field(default=0, ge=0, le=100)
    jira_status: NonBlankString | None = None
    gtd_action_ids: list[EntityId] = Field(default_factory=list)
    work_package_id: EntityId | None = None


class WorkPackageUpdateRequest(ProjectApiModel):
    title: NonBlankString | None = None
    description: NonBlankString | None = None
    phase_id: EntityId | None = None
    owner: NonBlankString | None = None
    duration_days: int | None = Field(default=None, ge=1)
    dependency_ids: list[EntityId] | None = None
    dependencies: list[ScheduleDependency] | None = None
    start_on: date | None = None
    due_on: date | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    jira_status: NonBlankString | None = None
    gtd_action_ids: list[EntityId] | None = None


class WorkTransitionRequest(ProjectApiModel):
    status: WorkStatus


class MilestoneCreateRequest(ProjectApiModel):
    title: NonBlankString
    description: NonBlankString | None = None
    phase_id: EntityId | None = None
    owner: NonBlankString | None = None
    dependency_ids: list[EntityId] = Field(default_factory=list)
    dependencies: list[ScheduleDependency] = Field(default_factory=list)
    planned_on: date | None = None
    due_on: date | None = None
    completion_criteria: list[NonBlankString] = Field(default_factory=list)
    milestone_id: EntityId | None = None
    jira_status: NonBlankString | None = None


class MilestoneUpdateRequest(ProjectApiModel):
    title: NonBlankString | None = None
    description: NonBlankString | None = None
    phase_id: EntityId | None = None
    owner: NonBlankString | None = None
    dependency_ids: list[EntityId] | None = None
    dependencies: list[ScheduleDependency] | None = None
    planned_on: date | None = None
    due_on: date | None = None
    jira_status: NonBlankString | None = None


class MilestoneTransitionRequest(ProjectApiModel):
    status: MilestoneStatus
    achieved_on: date | None = None


class BaselineCreateRequest(ProjectApiModel):
    label: NonBlankString


class EvidenceCreateRequest(ProjectApiModel):
    statement: NonBlankString
    source: NonBlankString
    evidence_id: EntityId | None = None


class CompletionCriterionResolutionRequest(ProjectApiModel):
    status: CompletionCriterionStatus
    evidence_ids: list[EntityId] | None = None
    waiver_reason: NonBlankString | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.status is CompletionCriterionStatus.MET and not self.evidence_ids:
            raise ValueError("a met completion criterion requires evidence_ids")
        if self.status is CompletionCriterionStatus.WAIVED and self.waiver_reason is None:
            raise ValueError("a waived completion criterion requires waiver_reason")
        if self.status is CompletionCriterionStatus.OPEN and (
            self.evidence_ids or self.waiver_reason is not None
        ):
            raise ValueError("an open completion criterion cannot include resolution data")
        return self


class RegisterItemCreateRequest(ProjectApiModel):
    kind: RegisterItemKind
    title: NonBlankString
    description: NonBlankString | None = None
    owner: NonBlankString | None = None
    probability: Decimal | None = Field(default=None, ge=0, le=1)
    impact_cost: Decimal = Field(default=Decimal("0"), ge=0)
    impact_days: int = Field(default=0, ge=0)
    response: NonBlankString | None = None
    decision: NonBlankString | None = None
    due_on: date | None = None
    register_item_id: EntityId | None = None

    @model_validator(mode="after")
    def validate_probability(self) -> Self:
        risk_kinds = {RegisterItemKind.RISK, RegisterItemKind.OPPORTUNITY}
        if self.kind in risk_kinds and self.probability is None:
            raise ValueError("risk and opportunity items require probability")
        if self.kind not in risk_kinds and self.probability is not None:
            raise ValueError("only risk and opportunity items may have probability")
        return self


class RegisterItemUpdateRequest(ProjectApiModel):
    title: NonBlankString | None = None
    description: NonBlankString | None = None
    owner: NonBlankString | None = None
    status: RegisterItemStatus | None = None
    probability: Decimal | None = Field(default=None, ge=0, le=1)
    impact_cost: Decimal | None = Field(default=None, ge=0)
    impact_days: int | None = Field(default=None, ge=0)
    response: NonBlankString | None = None
    decision: NonBlankString | None = None
    due_on: date | None = None


class RenderedProjectProjection(ProjectApiModel):
    project_id: str
    format: Literal["table", "mermaid", "html", "markdown", "gantt_html"]
    media_type: str
    content: str


ProjectManagementServiceDependency = Callable[..., ProjectManagementService]


def _provided(payload: ProjectApiModel) -> dict[str, object]:
    """Preserve omitted versus explicit empty collections at the HTTP boundary."""

    return payload.model_dump(exclude_unset=True)


def create_project_management_router(
    service_dependency: ProjectManagementServiceDependency,
) -> APIRouter:
    """Create the managed-project HTTP contract under ``/api/projects``."""

    router = APIRouter(prefix="/api/projects", tags=["project-management"])
    service_dep = Depends(service_dependency)

    @router.post("", status_code=201)
    def create_project(
        payload: ProjectCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.create(**_provided(payload))

    @router.get("")
    def list_projects(
        service: ProjectManagementService = service_dep,
    ) -> list[ManagedProjectDocument]:
        return service.list()

    # Static routes are registered before /{project_id} to avoid treating
    # "doctor" as an ID prefix.
    @router.get("/doctor")
    def doctor(
        service: ProjectManagementService = service_dep,
    ) -> ProjectDoctorReport:
        return service.doctor()

    @router.get("/{project_id}")
    def get_project(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.get(project_id)

    @router.patch("/{project_id}")
    def update_project(
        project_id: str,
        payload: ProjectUpdateRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.update(project_id, **_provided(payload))

    @router.post("/{project_id}/lifecycle")
    def transition_project(
        project_id: str,
        payload: ProjectLifecycleRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.transition_project(project_id, payload.lifecycle)

    @router.post("/{project_id}/phases", status_code=201)
    def add_phase(
        project_id: str,
        payload: PhaseCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> Phase:
        return service.add_phase(project_id, **_provided(payload))

    @router.patch("/{project_id}/phases/{phase_id}")
    def update_phase(
        project_id: str,
        phase_id: str,
        payload: PhaseUpdateRequest,
        service: ProjectManagementService = service_dep,
    ) -> Phase:
        return service.update_phase(project_id, phase_id, **_provided(payload))

    @router.post("/{project_id}/phases/{phase_id}/transition")
    def transition_phase(
        project_id: str,
        phase_id: str,
        payload: WorkTransitionRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.transition_phase(project_id, phase_id, payload.status)

    @router.post("/{project_id}/work-packages", status_code=201)
    def add_work_package(
        project_id: str,
        payload: WorkPackageCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> WorkPackage:
        return service.add_work_package(project_id, **_provided(payload))

    @router.patch("/{project_id}/work-packages/{work_package_id}")
    def update_work_package(
        project_id: str,
        work_package_id: str,
        payload: WorkPackageUpdateRequest,
        service: ProjectManagementService = service_dep,
    ) -> WorkPackage:
        return service.update_work_package(
            project_id,
            work_package_id,
            **_provided(payload),
        )

    @router.post("/{project_id}/work-packages/{work_package_id}/transition")
    def transition_work_package(
        project_id: str,
        work_package_id: str,
        payload: WorkTransitionRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.transition_work_package(project_id, work_package_id, payload.status)

    @router.post("/{project_id}/milestones", status_code=201)
    def add_milestone(
        project_id: str,
        payload: MilestoneCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> Milestone:
        return service.add_milestone(project_id, **_provided(payload))

    @router.patch("/{project_id}/milestones/{milestone_id}")
    def update_milestone(
        project_id: str,
        milestone_id: str,
        payload: MilestoneUpdateRequest,
        service: ProjectManagementService = service_dep,
    ) -> Milestone:
        return service.update_milestone(project_id, milestone_id, **_provided(payload))

    @router.post("/{project_id}/milestones/{milestone_id}/transition")
    def transition_milestone(
        project_id: str,
        milestone_id: str,
        payload: MilestoneTransitionRequest,
        service: ProjectManagementService = service_dep,
    ) -> ManagedProjectDocument:
        return service.transition_milestone(
            project_id,
            milestone_id,
            payload.status,
            achieved_on=payload.achieved_on,
        )

    @router.post("/{project_id}/evidence", status_code=201)
    def record_evidence(
        project_id: str,
        payload: EvidenceCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> EvidenceRecord:
        return service.record_evidence(project_id, **_provided(payload))

    @router.patch("/{project_id}/completion-criteria/{criterion_id}")
    def resolve_completion_criterion(
        project_id: str,
        criterion_id: str,
        payload: CompletionCriterionResolutionRequest,
        service: ProjectManagementService = service_dep,
    ) -> CompletionCriterion:
        return service.update_completion_criterion(
            project_id,
            criterion_id,
            **_provided(payload),
        )

    @router.post("/{project_id}/register", status_code=201)
    def add_register_item(
        project_id: str,
        payload: RegisterItemCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> RegisterItem:
        return service.add_register_item(project_id, **_provided(payload))

    @router.patch("/{project_id}/register/{register_item_id}")
    def update_register_item(
        project_id: str,
        register_item_id: str,
        payload: RegisterItemUpdateRequest,
        service: ProjectManagementService = service_dep,
    ) -> RegisterItem:
        return service.update_register_item(
            project_id,
            register_item_id,
            **_provided(payload),
        )

    @router.get("/{project_id}/schedule")
    def schedule_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> ScheduleProjection:
        return service.compute_schedule(project_id)

    @router.get("/{project_id}/schedule/{item_id}/explanation")
    def schedule_explanation(
        project_id: str,
        item_id: str,
        service: ProjectManagementService = service_dep,
    ) -> ScheduleExplanation:
        return service.explain_schedule(project_id, item_id)

    @router.get("/{project_id}/gantt")
    def gantt_projection(
        project_id: str,
        today: Annotated[date | None, Query()] = None,
        service: ProjectManagementService = service_dep,
    ) -> RenderedProjectProjection:
        document = service.get(project_id)
        schedule = service.compute_schedule(project_id)
        renderer = HtmlGanttRenderer()
        return RenderedProjectProjection(
            project_id=document.project.id,
            format=renderer.format,
            media_type=renderer.media_type,
            content=renderer.render(document.project, schedule, today=today),
        )

    @router.get("/{project_id}/qcd")
    def qcd_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> QcdProjection:
        return service.qcd_projection(project_id)

    @router.post("/{project_id}/baselines", status_code=201)
    def create_baseline(
        project_id: str,
        payload: BaselineCreateRequest,
        service: ProjectManagementService = service_dep,
    ) -> BaselineRecord:
        return service.create_baseline(project_id, label=payload.label)

    @router.get("/{project_id}/baselines")
    def list_baselines(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> list[BaselineRecord]:
        return service.get(project_id).project.baselines

    def projection_inputs(
        project_id: str,
        service: ProjectManagementService,
    ) -> tuple[ManagedProjectDocument, ScheduleProjection, QcdProjection]:
        return (
            service.get(project_id),
            service.compute_schedule(project_id),
            service.qcd_projection(project_id),
        )

    @router.get("/{project_id}/projections/table")
    def table_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> RenderedProjectProjection:
        document, schedule, _qcd = projection_inputs(project_id, service)
        return RenderedProjectProjection(
            project_id=document.project.id,
            format="table",
            media_type="text/plain",
            content=render_schedule_table(document.project, schedule),
        )

    @router.get("/{project_id}/projections/mermaid")
    def mermaid_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> RenderedProjectProjection:
        document, schedule, _qcd = projection_inputs(project_id, service)
        return RenderedProjectProjection(
            project_id=document.project.id,
            format="mermaid",
            media_type="text/plain",
            content=render_mermaid_gantt(document.project, schedule),
        )

    @router.get("/{project_id}/projections/html")
    def html_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> RenderedProjectProjection:
        document, schedule, qcd = projection_inputs(project_id, service)
        return RenderedProjectProjection(
            project_id=document.project.id,
            format="html",
            media_type="text/html",
            content=render_html_project_report(document.project, schedule, qcd),
        )

    @router.get("/{project_id}/projections/markdown")
    def markdown_projection(
        project_id: str,
        service: ProjectManagementService = service_dep,
    ) -> RenderedProjectProjection:
        document, schedule, qcd = projection_inputs(project_id, service)
        return RenderedProjectProjection(
            project_id=document.project.id,
            format="markdown",
            media_type="text/markdown",
            content=render_markdown_project_report(document.project, schedule, qcd),
        )

    return router


__all__ = [
    "BaselineCreateRequest",
    "CompletionCriterionResolutionRequest",
    "EvidenceCreateRequest",
    "MilestoneCreateRequest",
    "MilestoneTransitionRequest",
    "MilestoneUpdateRequest",
    "PhaseCreateRequest",
    "PhaseUpdateRequest",
    "ProjectCreateRequest",
    "ProjectLifecycleRequest",
    "ProjectUpdateRequest",
    "RegisterItemCreateRequest",
    "RegisterItemUpdateRequest",
    "RenderedProjectProjection",
    "WorkPackageCreateRequest",
    "WorkPackageUpdateRequest",
    "WorkTransitionRequest",
    "create_project_management_router",
]
