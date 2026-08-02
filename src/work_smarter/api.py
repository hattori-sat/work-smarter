"""Local HTTP API shared by VS Code and future user interfaces."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from work_smarter import __version__
from work_smarter.composition import (
    configured_database,
)
from work_smarter.composition import (
    initialize_workspace as initialize_composed_workspace,
)
from work_smarter.composition import (
    open_workspace as open_composed_workspace,
)
from work_smarter.errors import (
    EntityNotFoundError,
    InvalidDocumentError,
    InvalidTransitionError,
    WipLimitError,
    WorkSmarterError,
    WorkspaceNotInitializedError,
)
from work_smarter.gtd.models import (
    ClarifyDecision,
    ClarifyResult,
    Commitment,
    CompletionResult,
    DailyDashboard,
    Energy,
    GtdProject,
    Impact,
    InboxItem,
    MetricsReport,
    RecurrenceFrequency,
    RelationType,
    ReviewReport,
    StatusReport,
    Task,
    TaskRigor,
    Urgency,
    ValidationReport,
    WeeklyReviewSession,
    WeeklyReviewStep,
    WorkType,
)
from work_smarter.gtd.service import GtdService
from work_smarter.knowledge.api import create_knowledge_router
from work_smarter.knowledge.errors import MarpCompilerUnavailableError
from work_smarter.knowledge.marp import MarpCliCompiler
from work_smarter.knowledge.presentations import MarpCompiler
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.project_management.api import create_project_management_router
from work_smarter.project_management.errors import (
    ProjectCompletionGateError,
    ProjectConflictError,
    ProjectItemNotFoundError,
    ProjectScheduleError,
    ProjectTransitionError,
)
from work_smarter.project_management.service import ProjectManagementService
from work_smarter.shared.persistence.database import DatabaseBackendRegistry


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatabaseHealth(ApiModel):
    backend: str
    initialized: bool
    schema_version: int
    latest_schema_version: int


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    version: str
    workspace: str
    initialized: bool
    database: DatabaseHealth


class WorkspaceInitializationResponse(ApiModel):
    workspace: str
    initialized: bool
    database_backend: str
    database_schema_version: int


class CaptureRequest(ApiModel):
    text: str = Field(min_length=1)
    source: str = "api"
    tags: list[str] = Field(default_factory=list)


class ClarifyRequest(ApiModel):
    decision: ClarifyDecision
    title: str | None = None
    outcome: str | None = None
    first_action: str | None = None
    waiting_for: str | None = None
    scheduled_for: datetime | None = None
    contexts: list[str] = Field(default_factory=list)
    energy: Energy | None = None
    estimate_minutes: int | None = Field(default=None, gt=0)
    project_id: str | None = None
    completion_criteria: list[str] = Field(default_factory=list)
    not_before: datetime | None = None
    follow_up_on: date | None = None
    due_on: date | None = None
    work_type: WorkType | None = None
    rigor: TaskRigor | None = None
    goal: str | None = None
    why: str | None = None
    desired_outcome: str | None = None
    constraints: list[str] | None = None
    assumptions: list[str] | None = None
    risks: list[str] | None = None
    urgency: Urgency | None = None
    impact: Impact | None = None
    commitment: Commitment | None = None


class StartRequest(ApiModel):
    switch: bool = False


class BlockRequest(ApiModel):
    reason: str = Field(min_length=1)


class CompleteRequest(ApiModel):
    waiver_reason: str | None = None


class TaskDefinitionRequest(ApiModel):
    work_type: WorkType | None = None
    rigor: TaskRigor | None = None
    goal: str | None = None
    why: str | None = None
    desired_outcome: str | None = None
    constraints: list[str] | None = None
    assumptions: list[str] | None = None
    risks: list[str] | None = None
    completion_criteria: list[str] | None = None
    urgency: Urgency | None = None
    impact: Impact | None = None
    commitment: Commitment | None = None
    original_estimate_minutes: int | None = Field(default=None, gt=0)
    remaining_estimate_minutes: int | None = Field(default=None, ge=0)


class ConditionCheckRequest(ApiModel):
    evidence: str | None = None


class TaskLinkRequest(ApiModel):
    target_id: str = Field(min_length=1)
    relation_type: RelationType


class TaskParentRequest(ApiModel):
    parent_id: str | None = None


class WorkLogRequest(ApiModel):
    minutes: float = Field(gt=0)
    note: str | None = None


class WorkLogCorrectionRequest(ApiModel):
    corrected_minutes: float = Field(ge=0)
    reason: str = Field(min_length=1)


class RemainingEstimateRequest(ApiModel):
    minutes: int = Field(ge=0)
    reason: str = Field(min_length=1)


class RecurrenceRequest(ApiModel):
    frequency: RecurrenceFrequency
    interval: int = Field(default=1, ge=1)
    anchor_on: date | None = None
    until_on: date | None = None


class QuickAddRequest(ApiModel):
    text: str = Field(min_length=1)
    source: str = "api-quick-add"
    tags: list[str] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    energy: Energy | None = None
    estimate_minutes: int | None = Field(default=None, gt=0)
    project_id: str | None = None
    completion_criteria: list[str] = Field(default_factory=list)
    not_before: datetime | None = None
    due_on: date | None = None
    work_type: WorkType | None = None
    rigor: TaskRigor | None = None
    goal: str | None = None
    why: str | None = None
    desired_outcome: str | None = None
    constraints: list[str] | None = None
    assumptions: list[str] | None = None
    risks: list[str] | None = None
    urgency: Urgency | None = None
    impact: Impact | None = None
    commitment: Commitment | None = None


class DelegateRequest(ApiModel):
    target: str = Field(min_length=1)
    request: str | None = None
    target_kind: Literal["person", "external"] = "person"
    expected_on: date | None = None
    follow_up_on: date | None = None
    escalation_on: date | None = None
    escalation_to: str | None = None


class FollowUpRequest(ApiModel):
    note: str = Field(min_length=1)
    next_follow_up_on: date | None = None


class WaitingResponseRequest(ApiModel):
    note: str = Field(min_length=1)
    resolved: bool
    next_follow_up_on: date | None = None


class EscalateRequest(ApiModel):
    note: str = Field(min_length=1)
    escalation_to: str | None = None
    next_escalation_on: date | None = None


class ResolveBlockerRequest(ApiModel):
    note: str = Field(min_length=1)


class ScheduleRequest(ApiModel):
    scheduled_for: datetime


class DeferRequest(ApiModel):
    not_before: datetime


class DueRequest(ApiModel):
    due_on: date | None


class ReopenRequest(ApiModel):
    reason: str = Field(min_length=1)


class WeeklyReviewStepRequest(ApiModel):
    checked: bool = True


def create_gtd_router(service_dependency: Any) -> APIRouter:
    router = APIRouter(prefix="/api/gtd", tags=["gtd"])
    service_dep = Depends(service_dependency)

    @router.get("/inbox")
    def list_inbox(service: GtdService = service_dep) -> list[InboxItem]:
        return service.list_inbox()

    @router.post("/inbox", status_code=201)
    def capture(
        payload: CaptureRequest,
        service: GtdService = service_dep,
    ) -> InboxItem:
        return service.capture(payload.text, source=payload.source, tags=payload.tags)

    @router.post("/inbox/{item_id}/clarify")
    def clarify(
        item_id: str,
        payload: ClarifyRequest,
        service: GtdService = service_dep,
    ) -> ClarifyResult:
        fields = payload.model_dump(exclude_none=True)
        decision = fields.pop("decision")
        return service.clarify(item_id, decision, **fields)

    @router.get("/tasks")
    def list_tasks(service: GtdService = service_dep) -> list[Task]:
        return service.list_tasks()

    @router.post("/tasks", status_code=201)
    def add_next_action(
        payload: QuickAddRequest,
        service: GtdService = service_dep,
    ) -> ClarifyResult:
        fields = payload.model_dump(exclude={"text", "source", "tags"}, exclude_none=True)
        return service.add_next_action(
            payload.text,
            source=payload.source,
            tags=payload.tags,
            **fields,
        )

    @router.get("/tasks/{task_id}")
    def get_task(
        task_id: str,
        service: GtdService = service_dep,
    ) -> Task:
        return service.get_task(task_id)

    @router.patch("/tasks/{task_id}")
    def define_task(
        task_id: str,
        payload: TaskDefinitionRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.define_task(
            task_id,
            **payload.model_dump(exclude_none=True),
        )

    @router.post("/tasks/{task_id}/completion/{condition_id}")
    def check_completion_condition(
        task_id: str,
        condition_id: str,
        payload: ConditionCheckRequest | None = None,
        service: GtdService = service_dep,
    ) -> Task:
        return service.check_completion_condition(
            task_id,
            condition_id,
            evidence=payload.evidence if payload else None,
        )

    @router.post("/tasks/{task_id}/assurance-review")
    def review_task_assurance(
        task_id: str,
        service: GtdService = service_dep,
    ) -> Task:
        return service.review_task_assurance(task_id)

    @router.post("/tasks/{task_id}/links")
    def link_tasks(
        task_id: str,
        payload: TaskLinkRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.link_tasks(
            task_id,
            payload.target_id,
            relation_type=payload.relation_type,
        )

    @router.put("/tasks/{task_id}/parent")
    def set_task_parent(
        task_id: str,
        payload: TaskParentRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.set_task_parent(task_id, payload.parent_id)

    @router.post("/tasks/{task_id}/work-logs")
    def log_work(
        task_id: str,
        payload: WorkLogRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.log_work(task_id, minutes=payload.minutes, note=payload.note)

    @router.post("/tasks/{task_id}/work-logs/{work_log_id}/correct")
    def correct_work_log(
        task_id: str,
        work_log_id: str,
        payload: WorkLogCorrectionRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.correct_work_log(
            task_id,
            work_log_id,
            corrected_minutes=payload.corrected_minutes,
            reason=payload.reason,
        )

    @router.patch("/tasks/{task_id}/remaining-estimate")
    def set_remaining_estimate(
        task_id: str,
        payload: RemainingEstimateRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.set_remaining_estimate(
            task_id,
            minutes=payload.minutes,
            reason=payload.reason,
        )

    @router.put("/tasks/{task_id}/recurrence")
    def set_recurrence(
        task_id: str,
        payload: RecurrenceRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.set_recurrence(
            task_id,
            **payload.model_dump(exclude_none=True),
        )

    @router.post("/tasks/{task_id}/delegate")
    def delegate_task(
        task_id: str,
        payload: DelegateRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.delegate_task(
            task_id,
            **payload.model_dump(exclude_none=True),
        )

    @router.post("/tasks/{task_id}/follow-up")
    def follow_up_waiting(
        task_id: str,
        payload: FollowUpRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.follow_up_waiting(
            task_id,
            note=payload.note,
            next_follow_up_on=payload.next_follow_up_on,
        )

    @router.post("/tasks/{task_id}/response")
    def record_waiting_response(
        task_id: str,
        payload: WaitingResponseRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.record_waiting_response(
            task_id,
            note=payload.note,
            resolved=payload.resolved,
            next_follow_up_on=payload.next_follow_up_on,
        )

    @router.post("/tasks/{task_id}/escalate")
    def escalate_waiting(
        task_id: str,
        payload: EscalateRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.escalate_waiting(
            task_id,
            **payload.model_dump(exclude_none=True),
        )

    @router.post("/tasks/{task_id}/blockers/{blocker_id}/resolve")
    def resolve_blocker(
        task_id: str,
        blocker_id: str,
        payload: ResolveBlockerRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.resolve_blocker(task_id, blocker_id, note=payload.note)

    @router.put("/tasks/{task_id}/schedule")
    def schedule_task(
        task_id: str,
        payload: ScheduleRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.schedule_task(task_id, scheduled_for=payload.scheduled_for)

    @router.put("/tasks/{task_id}/defer")
    def defer_task(
        task_id: str,
        payload: DeferRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.defer_task(task_id, not_before=payload.not_before)

    @router.put("/tasks/{task_id}/due")
    def set_task_due(
        task_id: str,
        payload: DueRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.set_task_due(task_id, due_on=payload.due_on)

    @router.post("/tasks/{task_id}/reopen")
    def reopen_task(
        task_id: str,
        payload: ReopenRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.reopen_task(task_id, reason=payload.reason)

    @router.get("/status")
    def status(service: GtdService = service_dep) -> StatusReport:
        return service.status()

    @router.get("/dashboard/today")
    def daily_dashboard(
        day: Annotated[date | None, Query()] = None,
        service: GtdService = service_dep,
    ) -> DailyDashboard:
        return service.daily_dashboard(today=day)

    @router.get("/focus")
    def focus(
        context: Annotated[list[str] | None, Query()] = None,
        minutes: Annotated[int | None, Query(gt=0)] = None,
        energy: Annotated[Energy | None, Query()] = None,
        service: GtdService = service_dep,
    ) -> list[Task]:
        return service.focus(
            contexts=context,
            available_minutes=minutes,
            energy=energy,
        )

    @router.post("/tasks/{task_id}/start")
    def start_task(
        task_id: str,
        payload: StartRequest | None = None,
        service: GtdService = service_dep,
    ) -> Task:
        return service.start_task(task_id, switch=payload.switch if payload else False)

    @router.post("/tasks/{task_id}/stop")
    def stop_task(
        task_id: str,
        service: GtdService = service_dep,
    ) -> Task:
        return service.stop_task(task_id)

    @router.post("/tasks/stop")
    def stop_current_task(service: GtdService = service_dep) -> Task:
        return service.stop_task()

    @router.post("/tasks/{task_id}/complete")
    def complete_task(
        task_id: str,
        payload: CompleteRequest | None = None,
        service: GtdService = service_dep,
    ) -> CompletionResult:
        return service.complete_task(
            task_id,
            waiver_reason=payload.waiver_reason if payload else None,
        )

    @router.post("/tasks/{task_id}/block")
    def block_task(
        task_id: str,
        payload: BlockRequest,
        service: GtdService = service_dep,
    ) -> Task:
        return service.block_task(task_id, payload.reason)

    @router.post("/tasks/{task_id}/ready")
    def ready_task(
        task_id: str,
        service: GtdService = service_dep,
    ) -> Task:
        return service.ready_task(task_id)

    @router.post("/projects/{project_id}/complete")
    def complete_project(
        project_id: str,
        service: GtdService = service_dep,
    ) -> GtdProject:
        return service.complete_project(project_id)

    @router.get("/review/weekly")
    def weekly_review(service: GtdService = service_dep) -> ReviewReport:
        return service.weekly_review()

    @router.post("/review/weekly/complete")
    def complete_review(service: GtdService = service_dep) -> ReviewReport:
        return service.record_review()

    @router.post("/review/weekly/start", status_code=201)
    def start_weekly_review(
        service: GtdService = service_dep,
    ) -> WeeklyReviewSession:
        return service.start_weekly_review()

    @router.put("/review/weekly/{review_id}/steps/{step}")
    def check_weekly_review_step(
        review_id: str,
        step: WeeklyReviewStep,
        payload: WeeklyReviewStepRequest,
        service: GtdService = service_dep,
    ) -> WeeklyReviewSession:
        return service.check_weekly_review_step(
            review_id,
            step,
            checked=payload.checked,
        )

    @router.post("/review/weekly/{review_id}/complete")
    def complete_weekly_review(
        review_id: str,
        service: GtdService = service_dep,
    ) -> WeeklyReviewSession:
        return service.complete_weekly_review(review_id)

    @router.get("/doctor")
    def doctor(service: GtdService = service_dep) -> ValidationReport:
        return service.validate()

    @router.get("/metrics")
    def metrics(service: GtdService = service_dep) -> MetricsReport:
        return service.metrics()

    return router


def create_app(
    workspace_path: Path | str | None = None,
    *,
    database_registry: DatabaseBackendRegistry | None = None,
    marp_compiler: MarpCompiler | None = None,
) -> FastAPI:
    """Create an isolated application for a configured local workspace."""

    configured = (
        Path(workspace_path or os.environ.get("WORK_SMARTER_WORKSPACE") or Path.cwd())
        .expanduser()
        .resolve()
    )
    database = configured_database(configured, database_registry=database_registry)
    presentation_compiler = marp_compiler or MarpCliCompiler.from_environment()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if (configured / ".work-smarter" / "config.yml").is_file():
            database.migrate()
        yield

    app = FastAPI(
        title="Work Smarter",
        version=__version__,
        description="Local-first GTD API. Project management is a separate feature.",
        lifespan=lifespan,
    )
    app.state.workspace_path = configured

    def get_service(request: Request) -> GtdService:
        return GtdService(open_composed_workspace(request.app.state.workspace_path))

    def get_knowledge_service(request: Request) -> KnowledgeService:
        return KnowledgeService(open_composed_workspace(request.app.state.workspace_path))

    def get_marp_compiler() -> MarpCompiler:
        return presentation_compiler

    def get_project_management_service(request: Request) -> ProjectManagementService:
        return ProjectManagementService(open_composed_workspace(request.app.state.workspace_path))

    @app.exception_handler(WorkSmarterError)
    async def work_smarter_error(_request: Request, exc: WorkSmarterError) -> JSONResponse:
        status_code = 400
        if isinstance(exc, (EntityNotFoundError, ProjectItemNotFoundError)):
            status_code = 404
        elif isinstance(exc, MarpCompilerUnavailableError):
            status_code = 503
        elif isinstance(
            exc,
            (
                WipLimitError,
                InvalidTransitionError,
                ProjectCompletionGateError,
                ProjectConflictError,
                ProjectScheduleError,
                ProjectTransitionError,
            ),
        ):
            status_code = 409
        elif isinstance(exc, (InvalidDocumentError, WorkspaceNotInitializedError)):
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.get("/health", tags=["system"])
    def health() -> HealthResponse:
        database_status = database.status()
        return HealthResponse(
            version=__version__,
            workspace=str(configured),
            initialized=(configured / ".work-smarter" / "config.yml").is_file(),
            database=DatabaseHealth(
                backend=database.name,
                initialized=database_status.initialized,
                schema_version=database_status.schema_version,
                latest_schema_version=database_status.latest_schema_version,
            ),
        )

    @app.post("/api/workspace/init", tags=["system"], status_code=201)
    def initialize_workspace() -> WorkspaceInitializationResponse:
        workspace = initialize_composed_workspace(
            configured,
            database_registry=database_registry,
        )
        status = database.status()
        return WorkspaceInitializationResponse(
            workspace=str(workspace.root),
            initialized=True,
            database_backend=database.name,
            database_schema_version=status.schema_version,
        )

    app.include_router(create_gtd_router(get_service))
    app.include_router(create_knowledge_router(get_knowledge_service, get_marp_compiler))
    app.include_router(create_project_management_router(get_project_management_service))
    return app


app = create_app()
