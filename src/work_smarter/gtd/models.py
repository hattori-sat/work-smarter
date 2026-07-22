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


class Task(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["task"] = "task"
    title: str = Field(min_length=1)
    status: TaskStatus = TaskStatus.NEXT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_inbox_id: str | None = None
    project_id: str | None = None
    contexts: list[str] = Field(default_factory=list)
    energy: Energy | None = None
    estimate_minutes: int | None = Field(default=None, gt=0)
    actual_minutes: float = Field(default=0, ge=0)
    not_before: datetime | None = None
    due_on: date | None = None
    scheduled_for: datetime | None = None
    waiting_for: str | None = None
    follow_up_on: date | None = None
    blocked_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completion_criteria: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_fields(self) -> Task:
        if self.status is TaskStatus.WAITING and not self.waiting_for:
            raise ValueError("waiting tasks require waiting_for")
        if self.status is TaskStatus.SCHEDULED and self.scheduled_for is None:
            raise ValueError("scheduled tasks require scheduled_for")
        if self.status is TaskStatus.BLOCKED and not self.blocked_reason:
            raise ValueError("blocked tasks require blocked_reason")
        if self.status is TaskStatus.DOING and self.started_at is None:
            raise ValueError("doing tasks require started_at")
        if self.status is TaskStatus.DONE and self.completed_at is None:
            raise ValueError("done tasks require completed_at")
        return self


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
