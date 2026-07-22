"""Typed GTD entities and application result models."""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


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


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Commitment(StrEnum):
    NONE = "none"
    INTENDED = "intended"
    COMMITTED = "committed"


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
    DEPENDS_ON = "depends_on"
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


class WorkLogSource(StrEnum):
    TIMER = "timer"
    MANUAL = "manual"
    MIGRATED = "migrated"


class WaitingInteractionKind(StrEnum):
    DELEGATED = "delegated"
    FOLLOW_UP = "follow_up"
    RESPONSE = "response"
    ESCALATED = "escalated"


class RecurrenceFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


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
    WEEKLY_REVIEW = "weekly_review"


class WeeklyReviewStep(StrEnum):
    INBOX_ZERO = "inbox_zero"
    CALENDAR_REVIEWED = "calendar_reviewed"
    WAITING_REVIEWED = "waiting_reviewed"
    PROJECTS_REVIEWED = "projects_reviewed"
    SOMEDAY_REVIEWED = "someday_reviewed"


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


class WaitingInteraction(StrictModel):
    id: str
    kind: WaitingInteractionKind
    occurred_at: datetime = Field(default_factory=utc_now)
    note: str | None = None
    party: str | None = None
    next_follow_up_on: date | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("waiting interaction ID cannot be blank")
        return cleaned

    @field_validator("note", "party")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("waiting interaction text cannot be blank")
        return cleaned


class WaitingDetail(StrictModel):
    id: str = "WAIT-1"
    target_kind: Literal["person", "external"] = "person"
    target: str = Field(min_length=1)
    request: str | None = None
    delegated_at: datetime = Field(default_factory=utc_now)
    expected_on: date | None = None
    follow_up_on: date | None = None
    escalation_on: date | None = None
    escalation_to: str | None = None
    last_followed_up_at: datetime | None = None
    last_escalated_at: datetime | None = None
    interactions: list[WaitingInteraction] = Field(default_factory=list)
    resolved_at: datetime | None = None
    resolution_note: str | None = None

    @field_validator("id", "target")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("waiting ID and target cannot be blank")
        return cleaned

    @field_validator("request", "escalation_to", "resolution_note")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("waiting text fields cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_waiting_detail(self) -> WaitingDetail:
        if self.escalation_on is not None and self.escalation_to is None:
            raise ValueError("waiting escalation_on requires escalation_to")
        interaction_ids = [interaction.id for interaction in self.interactions]
        if len(interaction_ids) != len(set(interaction_ids)):
            raise ValueError("waiting interaction IDs must be unique within a cycle")
        if self.resolved_at is None and self.resolution_note is not None:
            raise ValueError("active waiting cannot have a resolution note")
        if self.resolved_at is not None and self.resolution_note is None:
            raise ValueError("resolved waiting requires a resolution note")
        return self


class TaskBlocker(StrictModel):
    id: str
    description: str = Field(min_length=1)
    task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolution_note: str | None = None


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

    @field_validator("id", "text")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("completion condition ID and text cannot be blank")
        return cleaned

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("completion evidence cannot be blank")
        return cleaned


class CompletionDefinition(StrictModel):
    obvious: bool = True
    conditions: list[CompletionCondition] = Field(default_factory=list)
    waiver_reason: str | None = None
    assurance_reviewed_at: datetime | None = None
    assurance_review_hash: str | None = None
    assurance_grandfathered: bool = False

    @field_validator("waiver_reason")
    @classmethod
    def validate_waiver_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("completion waiver reason cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_unique_condition_ids(self) -> CompletionDefinition:
        ids = [condition.id for condition in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("completion condition IDs must be unique")
        return self


class CompletionSnapshot(StrictModel):
    completed_at: datetime
    resolution: TaskResolution
    completion: CompletionDefinition
    result_summary: str | None = None
    evidence_links: list[str] = Field(default_factory=list)
    actual_minutes: float = Field(default=0, ge=0)
    reopened_at: datetime = Field(default_factory=utc_now)
    reopen_reason: str


class WorkLog(StrictModel):
    id: str
    minutes: float = Field(gt=0)
    source: WorkLogSource = WorkLogSource.MANUAL
    note: str | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_timer_range(self) -> WorkLog:
        started = self.started_at
        stopped = self.stopped_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if stopped is not None and stopped.tzinfo is None:
            stopped = stopped.replace(tzinfo=UTC)
        if started is not None and stopped is not None and stopped < started:
            raise ValueError("work log stopped_at cannot precede started_at")
        return self


class RecurrenceRule(StrictModel):
    frequency: RecurrenceFrequency
    interval: int = Field(default=1, ge=1)
    anchor_on: date
    until_on: date | None = None

    def next_after(self, current: date) -> date | None:
        if self.frequency is RecurrenceFrequency.DAILY:
            candidate = current + timedelta(days=self.interval)
        elif self.frequency is RecurrenceFrequency.WEEKLY:
            candidate = current + timedelta(weeks=self.interval)
        else:
            month_index = current.year * 12 + current.month - 1 + self.interval
            year, zero_based_month = divmod(month_index, 12)
            month = zero_based_month + 1
            day = min(self.anchor_on.day, calendar.monthrange(year, month)[1])
            candidate = date(year, month, day)
        if self.until_on is not None and candidate > self.until_on:
            return None
        return candidate


class Task(StrictModel):
    schema_version: Literal[3] = 3
    id: str
    kind: Literal["task"] = "task"
    revision: int = Field(default=1, ge=1)
    work_type: WorkType = WorkType.ACTION
    rigor: TaskRigor = TaskRigor.QUICK
    title: str = Field(min_length=1)
    goal: str | None = None
    why: str | None = None
    desired_outcome: str | None = None
    urgency: Urgency = Urgency.NORMAL
    impact: Impact = Impact.MEDIUM
    commitment: Commitment = Commitment.NONE
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
    remaining_estimate_minutes: float | None = Field(default=None, ge=0)
    actual_minutes: float = Field(default=0, ge=0)
    work_logs: list[WorkLog] = Field(default_factory=list)
    schedule: TaskSchedule = Field(default_factory=TaskSchedule)
    waiting: WaitingDetail | None = None
    waiting_history: list[WaitingDetail] = Field(default_factory=list)
    blockers: list[TaskBlocker] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    completion: CompletionDefinition = Field(default_factory=CompletionDefinition)
    resolution: TaskResolution | None = None
    result_summary: str | None = None
    evidence_links: list[str] = Field(default_factory=list)
    recurrence: RecurrenceRule | None = None
    recurrence_series_id: str | None = None
    occurrence_on: date | None = None
    completed_at: datetime | None = None
    completion_history: list[CompletionSnapshot] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("goal", "why", "desired_outcome")
    @classmethod
    def validate_optional_intent_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("task intent fields cannot be blank")
        return cleaned

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        version = value.get("schema_version", 3)
        if version == 3:
            return value
        if version == 2:
            data = dict(value)
            data["schema_version"] = 3
            completion = dict(data.get("completion") or {})
            if (
                data.get("lifecycle") == TaskLifecycle.COMPLETED
                and data.get("rigor") == TaskRigor.ASSURED
                and not completion.get("assurance_reviewed_at")
            ):
                completion["assurance_grandfathered"] = True
            data["completion"] = completion
            return data
        if version != 1:
            return value
        data = dict(value)
        status = TaskStatus(data.pop("status", TaskStatus.NEXT))
        created_at = data.get("created_at") or utc_now()
        lifecycle = TaskLifecycle.OPEN
        disposition = TaskDisposition.NEXT
        execution: dict[str, Any] = {"state": ExecutionState.IDLE}
        blockers: list[dict[str, Any]] = []
        resolution: TaskResolution | None = None
        legacy_blocked_reason = data.pop("blocked_reason", None)
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
                    "description": legacy_blocked_reason or "Legacy blocker",
                    "created_at": created_at,
                }
            )
        if legacy_blocked_reason and status is not TaskStatus.BLOCKED:
            blockers.append(
                {
                    "id": "BLK-LEGACY-1",
                    "description": legacy_blocked_reason,
                    "created_at": created_at,
                }
            )
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
            "schema_version": 3,
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
                    {"id": f"CC-{index}", "text": str(text).strip()}
                    for index, text in enumerate(criteria, start=1)
                    if str(text).strip()
                ],
            },
            "resolution": resolution,
        }

    @model_validator(mode="after")
    def validate_state_fields(self) -> Task:
        has_active_waiting = self.waiting is not None
        if (self.disposition is TaskDisposition.WAITING) != has_active_waiting:
            raise ValueError("waiting disposition and active waiting detail must agree")
        if self.waiting is not None and self.waiting.resolved_at is not None:
            raise ValueError("active waiting detail cannot already be resolved")
        if any(item.resolved_at is None for item in self.waiting_history):
            raise ValueError("waiting history can contain only resolved cycles")
        waiting_ids = [item.id for item in self.waiting_history]
        if self.waiting is not None:
            waiting_ids.append(self.waiting.id)
        if len(waiting_ids) != len(set(waiting_ids)):
            raise ValueError("waiting cycle IDs must be unique")
        if self.disposition is TaskDisposition.CALENDAR and self.schedule.scheduled_for is None:
            raise ValueError("calendar tasks require scheduled_for")
        if self.lifecycle is not TaskLifecycle.OPEN:
            if self.execution.state is not ExecutionState.IDLE:
                raise ValueError("closed tasks cannot be doing")
            if self.waiting is not None:
                raise ValueError("closed tasks cannot retain active waiting")
            if any(blocker.resolved_at is None for blocker in self.blockers):
                raise ValueError("closed tasks cannot retain unresolved blockers")
        if self.lifecycle is TaskLifecycle.COMPLETED:
            if self.completed_at is None:
                raise ValueError("completed tasks require completed_at")
            if self.resolution is None:
                raise ValueError("completed tasks require resolution")
            unmet = [
                condition for condition in self.completion.conditions if condition.met_at is None
            ]
            if (
                self.rigor in {TaskRigor.STANDARD, TaskRigor.ASSURED}
                and unmet
                and not self.completion.waiver_reason
            ):
                raise ValueError("completed rigorous tasks require every condition or a waiver")
            missing_evidence = [
                condition
                for condition in self.completion.conditions
                if condition.met_at is not None and not condition.evidence
            ]
            if (
                self.rigor is TaskRigor.ASSURED
                and missing_evidence
                and not self.completion.waiver_reason
            ):
                raise ValueError("completed assured tasks require condition evidence or a waiver")
            if (
                self.rigor is TaskRigor.ASSURED
                and self.completion.assurance_reviewed_at is None
                and not self.completion.waiver_reason
                and not self.completion.assurance_grandfathered
            ):
                raise ValueError(
                    "completed assured tasks require constraints and assumptions review or a waiver"
                )
            if (
                self.rigor is TaskRigor.ASSURED
                and self.completion.assurance_reviewed_at is not None
                and self.completion.assurance_review_hash != self.assurance_input_hash()
                and not self.completion.waiver_reason
                and not self.completion.assurance_grandfathered
            ):
                raise ValueError(
                    "assured task review no longer matches constraints and assumptions"
                )
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

    @computed_field
    @property
    def next_occurrence_on(self) -> date | None:
        if self.recurrence is None:
            return None
        return self.recurrence.next_after(self.occurrence_on or self.recurrence.anchor_on)

    def persistent_dict(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude_none=True,
            exclude_computed_fields=True,
        )

    def assurance_input_hash(self) -> str:
        payload = {
            "constraints": self.constraints,
            "assumptions": [assumption.model_dump(mode="json") for assumption in self.assumptions],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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


class ReviewStepState(StrictModel):
    step: WeeklyReviewStep
    checked_at: datetime | None = None


class WeeklyReviewSession(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["weekly_review"] = "weekly_review"
    revision: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    steps: list[ReviewStepState] = Field(
        default_factory=lambda: [ReviewStepState(step=step) for step in WeeklyReviewStep]
    )

    @model_validator(mode="after")
    def validate_steps(self) -> WeeklyReviewSession:
        step_values = [state.step for state in self.steps]
        if len(step_values) != len(set(step_values)):
            raise ValueError("weekly review steps must be unique")
        if set(step_values) != set(WeeklyReviewStep):
            raise ValueError("weekly review must contain every required step")
        if self.completed_at is not None and any(state.checked_at is None for state in self.steps):
            raise ValueError("completed weekly review requires every step to be checked")
        return self


DurableEntity = (
    InboxItem
    | Task
    | GtdProject
    | Reference
    | SomedayItem
    | ArchivedInboxItem
    | WeeklyReviewSession
)


class EntityRef(StrictModel):
    id: str
    kind: str
    title: str
    path: str


class DailyDashboard(StrictModel):
    generated_at: datetime = Field(default_factory=utc_now)
    day: date
    current_task: EntityRef | None = None
    inbox_count: int = 0
    overdue: list[EntityRef] = Field(default_factory=list)
    due_today: list[EntityRef] = Field(default_factory=list)
    follow_ups_due: list[EntityRef] = Field(default_factory=list)
    escalations_due: list[EntityRef] = Field(default_factory=list)
    scheduled_today: list[EntityRef] = Field(default_factory=list)
    blocked: list[EntityRef] = Field(default_factory=list)
    available_actions: list[EntityRef] = Field(default_factory=list)


class ClarifyResult(StrictModel):
    source_id: str
    decision: ClarifyDecision
    created: list[EntityRef] = Field(default_factory=list)
    archived_path: str


class CompletionResult(StrictModel):
    task: Task
    project_attention_required: bool = False
    project_id: str | None = None
    next_occurrence: Task | None = None


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


class ReviewChecklistItem(StrictModel):
    key: str
    label: str
    complete: bool
    count: int = 0
    checked_at: datetime | None = None


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
    checklist: list[ReviewChecklistItem] = Field(default_factory=list)
    session_id: str | None = None
    session_started_at: datetime | None = None

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
    average_cycle_time_hours: float | None = None
    waiting_minutes_total: float = 0
    blocked_minutes_total: float = 0
    wip_current: int = 0
    waiting_current: int = 0
    blocked_current: int = 0


class EventPayload(StrictModel):
    """Typed-enough event payload while preserving extension data."""

    model_config = ConfigDict(extra="allow")
    data: dict[str, Any] = Field(default_factory=dict)
