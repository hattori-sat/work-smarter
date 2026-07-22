"""Local HTTP API shared by VS Code and future user interfaces."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from work_smarter import __version__
from work_smarter.composition import (
    initialize_workspace as initialize_composed_workspace,
)
from work_smarter.composition import open_workspace as open_composed_workspace
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
    WorkType,
)
from work_smarter.gtd.service import GtdService


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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

    @router.get("/status")
    def status(service: GtdService = service_dep) -> StatusReport:
        return service.status()

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

    @router.get("/doctor")
    def doctor(service: GtdService = service_dep) -> ValidationReport:
        return service.validate()

    @router.get("/metrics")
    def metrics(service: GtdService = service_dep) -> MetricsReport:
        return service.metrics()

    return router


def create_app(workspace_path: Path | str | None = None) -> FastAPI:
    """Create an isolated application for a configured local workspace."""

    configured = (
        Path(workspace_path or os.environ.get("WORK_SMARTER_WORKSPACE") or Path.cwd())
        .expanduser()
        .resolve()
    )
    app = FastAPI(
        title="Work Smarter",
        version=__version__,
        description="Local-first GTD API. Project management is a separate feature.",
    )
    app.state.workspace_path = configured

    def get_service(request: Request) -> GtdService:
        return GtdService(open_composed_workspace(request.app.state.workspace_path))

    @app.exception_handler(WorkSmarterError)
    async def work_smarter_error(_request: Request, exc: WorkSmarterError) -> JSONResponse:
        status_code = 400
        if isinstance(exc, EntityNotFoundError):
            status_code = 404
        elif isinstance(exc, (WipLimitError, InvalidTransitionError)):
            status_code = 409
        elif isinstance(exc, (InvalidDocumentError, WorkspaceNotInitializedError)):
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "workspace": str(configured),
            "initialized": (configured / ".work-smarter" / "config.yml").is_file(),
        }

    @app.post("/api/workspace/init", tags=["system"], status_code=201)
    def initialize_workspace() -> dict[str, Any]:
        workspace = initialize_composed_workspace(configured)
        return {"workspace": str(workspace.root), "initialized": True}

    app.include_router(create_gtd_router(get_service))
    return app


app = create_app()
