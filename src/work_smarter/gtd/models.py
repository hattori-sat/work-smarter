"""Typed GTD entities and application result models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base model for durable metadata with typo detection."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Energy(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    NEXT = "next"
    DOING = "doing"
    WAITING = "waiting"
    SCHEDULED = "scheduled"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkType(StrEnum):
    ACTION = "action"
    DECISION = "decision"
    INVESTIGATION = "investigation"
    COMMUNICATION = "communication"
    ROUTINE = "routine"


class TaskRigor(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    ASSURED = "assured"


class TaskLifecycle(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskDisposition(StrEnum):
    NEXT = "next"
    WAITING = "waiting"
    CALENDAR = "calendar"


class ExecutionState(StrEnum):
    IDLE = "idle"
    DOING = "doing"


class RelationType(StrEnum):
    BLOCKS = "blocks"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"
    IMPLEMENTS = "implements"


class AssumptionStatus(StrEnum):
    OPEN = "open"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"


class TaskResolution(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DUPLICATE = "duplicate"
    WONT_DO = "wont_do"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    DONE = "done"
    CANCELLED = "cancelled"


class ClarifyDecision(StrEnum):
    NEXT = "next"
    PROJECT = "project"
    WAITING = "waiting"
    SCHEDULED = "scheduled"
    SOMEDAY = "someday"
    REFERENCE = "reference"
    TRASH = "trash"
    DONE = "done"


class EntityKind(StrEnum):
    INBOX = "inbox"
    TASK = "task"
    GTD_PROJECT = "gtd_project"
    REFERENCE = "reference"
    SOMEDAY = "someday"
    INBOX_ARCHIVE = "inbox_archive"


class InboxItem(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["inbox"] = "inbox"
    title: str = Field(min_length=1)
    source: str = "manual"
    captured_at: datetime = Field(default_factory=utc_now)
    tags: list[str] = Field(default_factory=list)


class InboxPreview(StrictModel):
    item: InboxItem
    body: str


class ArchivedInboxItem(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["inbox_archive"] = "inbox_archive"
    title: str = Field(min_length=1)
    source: str = "manual"
    captured_at: datetime
    clarified_at: datetime = Field(default_factory=utc_now)
    disposition: ClarifyDecision
    result_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class TaskExecution(StrictModel):
    state: ExecutionState = ExecutionState.IDLE
    started_at: datetime | None = None

    @model_validator(mode="after")
    def validate_started_at(self) -> TaskExecution:
        if self.state is ExecutionState.DOING and self.started_at is None:
            raise ValueError("doing execution requires started_at")
        if self.state is ExecutionState.IDLE and self.started_at is not None:
            raise ValueError("idle execution cannot retain started_at")
        return self


class TaskSchedule(StrictModel):
    not_before: datetime | None = None
    scheduled_for: datetime | None = None
    due_on: date | None = None


class WaitingDetail(StrictModel):
    target_kind: Literal["person", "external"] = "person"
    target: str = Field(min_length=1)
    request: str | None = None
    delegated_at: datetime = Field(default_factory=utc_now)
    expected_on: date | None = None
    follow_up_on: date | None = None
    escalation_on: date | None = None
    escalation_to: str | None = None
    last_followed_up_at: datetime | None = None


class TaskBlocker(StrictModel):
    id: str
    description: str = Field(min_length=1)
    task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class TaskRelation(StrictModel):
    type: RelationType
    target_id: str


class Assumption(StrictModel):
    id: str
    statement: str = Field(min_length=1)
    status: AssumptionStatus = AssumptionStatus.OPEN


class CompletionCondition(StrictModel):
    id: str
    text: str = Field(min_length=1)
    met_at: datetime | None = None
    evidence: str | None = None


class CompletionDefinition(StrictModel):
    obvious: bool = True
    conditions: list[CompletionCondition] = Field(default_factory=list)
    waiver_reason: str | None = None


class Task(StrictModel):
    schema_version: Literal[2] = 2
    id: str
    kind: Literal["task"] = "task"
    revision: int = Field(default=1, ge=1)
    work_type: WorkType = WorkType.ACTION
    rigor: TaskRigor = TaskRigor.QUICK
    title: str = Field(min_length=1)
    goal: str | None = None
    why: str | None = None
    desired_outcome: str | None = None
    lifecycle: TaskLifecycle = TaskLifecycle.OPEN
    disposition: TaskDisposition = TaskDisposition.NEXT
    execution: TaskExecution = Field(default_factory=TaskExecution)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_inbox_id: str | None = None
    project_id: str | None = None
    parent_id: str | None = None
    relations: list[TaskRelation] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    energy: Energy | None = None
    original_estimate_minutes: int | None = Field(default=None, gt=0)
    remaining_estimate_minutes: int | None = Field(default=None, ge=0)
    actual_minutes: float = Field(default=0, ge=0)
    schedule: TaskSchedule = Field(default_factory=TaskSchedule)
    waiting: WaitingDetail | None = None
    blockers: list[TaskBlocker] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    completion: CompletionDefinition = Field(default_factory=CompletionDefinition)
    resolution: TaskResolution | None = None
    result_summary: str | None = None
    evidence_links: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_v1(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("schema_version", 2) != 1:
            return value
        data = dict(value)
        status = TaskStatus(data.pop("status", TaskStatus.NEXT))
        created_at = data.get("created_at") or utc_now()
        lifecycle = TaskLifecycle.OPEN
        disposition = TaskDisposition.NEXT
        execution: dict[str, Any] = {"state": ExecutionState.IDLE}
        blockers: list[dict[str, Any]] = []
        resolution: TaskResolution | None = None
        if status is TaskStatus.DOING:
            execution = {
                "state": ExecutionState.DOING,
                "started_at": data.pop("started_at", None) or created_at,
            }
        else:
            data.pop("started_at", None)
        if status is TaskStatus.WAITING:
            disposition = TaskDisposition.WAITING
        elif status is TaskStatus.SCHEDULED:
            disposition = TaskDisposition.CALENDAR
        elif status is TaskStatus.BLOCKED:
            blockers.append(
                {
                    "id": "BLK-LEGACY-1",
                    "description": data.pop("blocked_reason", None) or "Legacy blocker",
                    "created_at": created_at,
                }
            )
        else:
            data.pop("blocked_reason", None)
        if status is TaskStatus.DONE:
            lifecycle = TaskLifecycle.COMPLETED
            resolution = TaskResolution.COMPLETED
        elif status is TaskStatus.CANCELLED:
            lifecycle = TaskLifecycle.CANCELLED
            resolution = TaskResolution.CANCELLED

        waiting_for = data.pop("waiting_for", None)
        follow_up_on = data.pop("follow_up_on", None)
        waiting = None
        if waiting_for:
            waiting = {
                "target": waiting_for,
                "delegated_at": created_at,
                "follow_up_on": follow_up_on,
            }
        criteria = data.pop("completion_criteria", []) or []
        estimate = data.pop("estimate_minutes", None)
        schedule = {
            "not_before": data.pop("not_before", None),
            "scheduled_for": data.pop("scheduled_for", None),
            "due_on": data.pop("due_on", None),
        }
        return {
            **data,
            "schema_version": 2,
            "revision": 1,
            "work_type": WorkType.ACTION,
            "rigor": TaskRigor.QUICK,
            "lifecycle": lifecycle,
            "disposition": disposition,
            "execution": execution,
            "original_estimate_minutes": estimate,
            "remaining_estimate_minutes": estimate,
            "schedule": schedule,
            "waiting": waiting,
            "blockers": blockers,
            "completion": {
                "obvious": True,
                "conditions": [
                    {"id": f"CC-{index}", "text": text}
                    for index, text in enumerate(criteria, start=1)
                ],
            },
            "resolution": resolution,
        }

    @model_validator(mode="after")
    def validate_state_fields(self) -> Task:
        if self.disposition is TaskDisposition.WAITING and self.waiting is None:
            raise ValueError("waiting tasks require waiting detail")
        if self.disposition is TaskDisposition.CALENDAR and self.schedule.scheduled_for is None:
            raise ValueError("calendar tasks require scheduled_for")
        if self.lifecycle is TaskLifecycle.COMPLETED:
            if self.completed_at is None:
                raise ValueError("completed tasks require completed_at")
            if self.resolution is None:
                raise ValueError("completed tasks require resolution")
        if self.lifecycle is TaskLifecycle.OPEN and self.resolution is not None:
            raise ValueError("open tasks cannot have a resolution")
        if self.rigor in {TaskRigor.STANDARD, TaskRigor.ASSURED}:
            if not self.goal:
                raise ValueError(f"{self.rigor.value} tasks require goal")
            if not self.completion.conditions:
                raise ValueError(
                    f"{self.rigor.value} tasks require at least one completion condition"
                )
        return self

    @computed_field
    @property
    def status(self) -> TaskStatus:
        if self.lifecycle is TaskLifecycle.COMPLETED:
            return TaskStatus.DONE
        if self.lifecycle is TaskLifecycle.CANCELLED:
            return TaskStatus.CANCELLED
        if self.execution.state is ExecutionState.DOING:
            return TaskStatus.DOING
        if any(blocker.resolved_at is None for blocker in self.blockers):
            return TaskStatus.BLOCKED
        if self.disposition is TaskDisposition.WAITING:
            return TaskStatus.WAITING
        if self.disposition is TaskDisposition.CALENDAR:
            return TaskStatus.SCHEDULED
        return TaskStatus.NEXT

    @computed_field
    @property
    def estimate_minutes(self) -> int | None:
        return self.original_estimate_minutes

    @computed_field
    @property
    def not_before(self) -> datetime | None:
        return self.schedule.not_before

    @computed_field
    @property
    def due_on(self) -> date | None:
        return self.schedule.due_on

    @computed_field
    @property
    def scheduled_for(self) -> datetime | None:
        return self.schedule.scheduled_for

    @computed_field
    @property
    def waiting_for(self) -> str | None:
        return self.waiting.target if self.waiting else None

    @computed_field
    @property
    def follow_up_on(self) -> date | None:
        return self.waiting.follow_up_on if self.waiting else None

    @computed_field
    @property
    def blocked_reason(self) -> str | None:
        return next(
            (blocker.description for blocker in self.blockers if blocker.resolved_at is None),
            None,
        )

    @computed_field
    @property
    def started_at(self) -> datetime | None:
        return self.execution.started_at

    @computed_field
    @property
    def completion_criteria(self) -> list[str]:
        return [condition.text for condition in self.completion.conditions]

    def persistent_dict(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude_none=True,
            exclude_computed_fields=True,
        )


class GtdProject(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["gtd_project"] = "gtd_project"
    title: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_inbox_id: str | None = None
    area: str | None = None
    review_every_days: int = Field(default=7, gt=0)
    last_reviewed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class Reference(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["reference"] = "reference"
    title: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_inbox_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class SomedayItem(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["someday"] = "someday"
    title: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_inbox_id: str | None = None
    review_on: date | None = None
    tags: list[str] = Field(default_factory=list)


DurableEntity = InboxItem | Task | GtdProject | Reference | SomedayItem | ArchivedInboxItem


class EntityRef(StrictModel):
    id: str
    kind: str
    title: str
    path: str


class ClarifyResult(StrictModel):
    source_id: str
    decision: ClarifyDecision
    created: list[EntityRef] = Field(default_factory=list)
    archived_path: str


class CompletionResult(StrictModel):
    task: Task
    project_attention_required: bool = False
    project_id: str | None = None


class StatusReport(StrictModel):
    generated_at: datetime = Field(default_factory=utc_now)
    current_task: EntityRef | None = None
    inbox_count: int = 0
    tasks_by_status: dict[str, int] = Field(default_factory=dict)
    projects_by_status: dict[str, int] = Field(default_factory=dict)
    ready_actions: list[EntityRef] = Field(default_factory=list)
    projects_needing_action: list[EntityRef] = Field(default_factory=list)


class ReviewItem(StrictModel):
    id: str
    title: str
    reason: str
    age_days: int | None = None


class ReviewReport(StrictModel):
    generated_at: datetime = Field(default_factory=utc_now)
    current_task: EntityRef | None = None
    inbox: list[ReviewItem] = Field(default_factory=list)
    waiting_followups: list[ReviewItem] = Field(default_factory=list)
    blocked: list[ReviewItem] = Field(default_factory=list)
    stale_actions: list[ReviewItem] = Field(default_factory=list)
    projects_without_next_action: list[ReviewItem] = Field(default_factory=list)
    scheduled: list[ReviewItem] = Field(default_factory=list)
    someday_count: int = 0

    @computed_field
    @property
    def attention_count(self) -> int:
        return sum(
            len(items)
            for items in (
                self.inbox,
                self.waiting_followups,
                self.blocked,
                self.stale_actions,
                self.projects_without_next_action,
            )
        )


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None
    entity_id: str | None = None


class ValidationReport(StrictModel):
    checked_at: datetime = Field(default_factory=utc_now)
    issues: list[ValidationIssue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class MetricsReport(StrictModel):
    generated_at: datetime = Field(default_factory=utc_now)
    completed_total: int = 0
    completed_last_7_days: int = 0
    focus_minutes_total: float = 0
    average_lead_time_hours: float | None = None
    average_estimate_ratio: float | None = None


class EventPayload(StrictModel):
    """Typed-enough event payload while preserving extension data."""

    model_config = ConfigDict(extra="allow")
    data: dict[str, Any] = Field(default_factory=dict)
