"""Application service implementing the GTD workflow and its invariants."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from work_smarter.errors import (
    EntityNotFoundError,
    InvalidDocumentError,
    InvalidTransitionError,
    WipLimitError,
)
from work_smarter.gtd.events import EventType
from work_smarter.gtd.metrics import project_metrics
from work_smarter.gtd.models import (
    ArchivedInboxItem,
    Assumption,
    ClarifyDecision,
    ClarifyResult,
    Commitment,
    CompletionCondition,
    CompletionDefinition,
    CompletionResult,
    CompletionSnapshot,
    DailyDashboard,
    Energy,
    EntityRef,
    ExecutionState,
    GtdProject,
    Impact,
    InboxItem,
    InboxPreview,
    MetricsReport,
    ProjectStatus,
    RecurrenceFrequency,
    RecurrenceRule,
    Reference,
    RelationType,
    ReviewChecklistItem,
    ReviewItem,
    ReviewReport,
    ReviewStepState,
    SomedayItem,
    StatusReport,
    Task,
    TaskBlocker,
    TaskDisposition,
    TaskExecution,
    TaskLifecycle,
    TaskRelation,
    TaskResolution,
    TaskRigor,
    TaskSchedule,
    TaskStatus,
    Urgency,
    ValidationIssue,
    ValidationReport,
    WaitingDetail,
    WaitingInteraction,
    WaitingInteractionKind,
    WeeklyReviewSession,
    WeeklyReviewStep,
    WorkLog,
    WorkLogCorrection,
    WorkLogSource,
    WorkType,
    utc_now,
)
from work_smarter.gtd.templates import render_gtd_template
from work_smarter.storage.events import Event, EventStore
from work_smarter.storage.workspace import EntityRecord, Workspace

OPEN_TASK_STATUSES = {
    TaskStatus.NEXT,
    TaskStatus.DOING,
    TaskStatus.WAITING,
    TaskStatus.SCHEDULED,
    TaskStatus.BLOCKED,
}

ENERGY_RANK = {Energy.LOW: 1, Energy.MEDIUM: 2, Energy.HIGH: 3}
URGENCY_RANK = {Urgency.LOW: 1, Urgency.NORMAL: 2, Urgency.HIGH: 3, Urgency.CRITICAL: 4}
IMPACT_RANK = {Impact.LOW: 1, Impact.MEDIUM: 2, Impact.HIGH: 3}
COMMITMENT_RANK = {
    Commitment.NONE: 1,
    Commitment.INTENDED: 2,
    Commitment.COMMITTED: 3,
}

WEEKLY_REVIEW_LABELS = {
    WeeklyReviewStep.INBOX_ZERO: "Clarify inbox to zero",
    WeeklyReviewStep.CALENDAR_REVIEWED: "Review calendar and date commitments",
    WeeklyReviewStep.WAITING_REVIEWED: "Review waiting-for and follow-ups",
    WeeklyReviewStep.PROJECTS_REVIEWED: "Ensure every active project has a next action",
    WeeklyReviewStep.SOMEDAY_REVIEWED: "Review Someday/Maybe",
}


def _new_id(prefix: str) -> str:
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{timestamp}-{uuid4().hex[:6].upper()}"


def _next_sequence_id(prefix: str, existing_ids: Iterable[str]) -> str:
    existing = set(existing_ids)
    sequence = 1
    while f"{prefix}-{sequence}" in existing:
        sequence += 1
    return f"{prefix}-{sequence}"


def _title_from_text(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) <= 100:
        return first_line
    return first_line[:97].rstrip() + "..."


def _normalize_tags(values: Iterable[str] | None) -> list[str]:
    return sorted({value.strip().lower() for value in values or [] if value.strip()})


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_days(value: datetime, now: datetime) -> int:
    return max(0, (now - _ensure_aware(value)).days)


class GtdService:
    """The only supported writer for GTD state transitions."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.events: EventStore = workspace.event_store

    @classmethod
    def from_path(cls, root: Path | str) -> GtdService:
        from work_smarter.composition import open_workspace

        return cls(open_workspace(root))

    def _event(
        self,
        event_type: EventType,
        *,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        return self.events.append(
            Event(
                id=_new_id("EVT"),
                type=event_type,
                entity_id=entity_id,
                payload=payload or {},
            )
        )

    def capture(
        self,
        text: str,
        *,
        source: str = "manual",
        tags: Iterable[str] | None = None,
    ) -> InboxItem:
        with self.workspace.lock():
            return self._capture_unlocked(text, source=source, tags=tags)

    def _capture_unlocked(
        self,
        text: str,
        *,
        source: str,
        tags: Iterable[str] | None,
    ) -> InboxItem:
        clean = text.strip()
        if not clean:
            raise InvalidTransitionError("Capture text cannot be empty")
        item = InboxItem(
            id=_new_id("IN"),
            title=_title_from_text(clean),
            source=source.strip() or "manual",
            tags=_normalize_tags(tags),
        )
        self.workspace.write(item, clean)
        self._event(EventType.CAPTURED, entity_id=item.id, payload={"source": item.source})
        return item

    def list_inbox(self) -> list[InboxItem]:
        return [cast(InboxItem, record.entity) for record in self.workspace.list_records("inbox")]

    def add_next_action(
        self,
        text: str,
        *,
        source: str = "quick-add",
        tags: Iterable[str] | None = None,
        **fields: Any,
    ) -> ClarifyResult:
        """Capture and clarify a known next action as one atomic user operation."""

        with self.workspace.lock():
            item = self._capture_unlocked(text, source=source, tags=tags)
            return self._clarify_unlocked(
                item.id,
                ClarifyDecision.NEXT,
                **fields,
            )

    def _inbox_record(self, item_id: str | None) -> EntityRecord[InboxItem]:
        if item_id is None:
            records = self.workspace.list_records("inbox")
            if not records:
                raise EntityNotFoundError("Inbox is empty")
            return cast(EntityRecord[InboxItem], records[0])
        record = self.workspace.find_record(item_id, kinds={"inbox"})
        return cast(EntityRecord[InboxItem], record)

    def preview_inbox(self, item_id: str | None = None) -> InboxPreview:
        """Return the selected inbox item and body without exposing storage internals."""

        record = self._inbox_record(item_id)
        return InboxPreview(item=record.entity, body=record.body)

    def clarify(
        self,
        item_id: str | None,
        decision: ClarifyDecision | str,
        **fields: Any,
    ) -> ClarifyResult:
        with self.workspace.lock():
            return self._clarify_unlocked(item_id, decision, **fields)

    def _clarify_unlocked(
        self,
        item_id: str | None,
        decision: ClarifyDecision | str,
        **fields: Any,
    ) -> ClarifyResult:
        source = self._inbox_record(item_id)
        item = source.entity
        choice = ClarifyDecision(decision)
        task_choices = {
            ClarifyDecision.NEXT,
            ClarifyDecision.WAITING,
            ClarifyDecision.SCHEDULED,
            ClarifyDecision.DONE,
        }
        requested_project = fields.get("project_id")
        if requested_project is not None:
            if choice not in task_choices:
                raise InvalidTransitionError(
                    f"project_id does not apply to the {choice.value} disposition"
                )
            project = self._project_record(str(requested_project)).entity
            if project.status is not ProjectStatus.ACTIVE:
                raise InvalidTransitionError(
                    f"Cannot add an action to {project.id} while it is {project.status.value}"
                )
            fields = {**fields, "project_id": project.id}
        requested_parent = fields.get("parent_id")
        if requested_parent is not None:
            if choice not in task_choices:
                raise InvalidTransitionError(
                    f"parent_id does not apply to the {choice.value} disposition"
                )
            parent = self._task_record(str(requested_parent)).entity
            fields = {**fields, "parent_id": parent.id}
        title = str(fields.get("title") or item.title).strip()
        tags = _normalize_tags(fields.get("tags") or item.tags)
        now = utc_now()
        created: list[tuple[Any, str]] = []

        try:
            if choice is ClarifyDecision.NEXT:
                task = self._task_from_fields(
                    title=title,
                    source=item,
                    tags=tags,
                    status=TaskStatus.NEXT,
                    fields=fields,
                )
                created.append((task, self._task_body(source.body)))

            elif choice is ClarifyDecision.PROJECT:
                outcome = str(fields.get("outcome") or "").strip()
                first_action = str(fields.get("first_action") or "").strip()
                if not outcome or not first_action:
                    raise InvalidTransitionError("A project requires both outcome and first_action")
                project = GtdProject(
                    id=_new_id("PRJ"),
                    title=title,
                    outcome=outcome,
                    source_inbox_id=item.id,
                    area=fields.get("area"),
                    tags=tags,
                )
                task_fields = dict(fields)
                task_fields["project_id"] = project.id
                task = self._task_from_fields(
                    title=first_action,
                    source=item,
                    tags=tags,
                    status=TaskStatus.NEXT,
                    fields=task_fields,
                )
                project_body = render_gtd_template(
                    self.workspace,
                    "project.md",
                    outcome=outcome,
                    source_id=item.id,
                )
                created.extend([(project, project_body), (task, self._task_body(source.body))])

            elif choice is ClarifyDecision.WAITING:
                waiting_for = str(fields.get("waiting_for") or "").strip()
                if not waiting_for:
                    raise InvalidTransitionError("Waiting items require waiting_for")
                waiting_fields = dict(fields)
                waiting_fields["waiting_for"] = waiting_for
                task = self._task_from_fields(
                    title=title,
                    source=item,
                    tags=tags,
                    status=TaskStatus.WAITING,
                    fields=waiting_fields,
                )
                created.append((task, self._task_body(source.body)))

            elif choice is ClarifyDecision.SCHEDULED:
                if fields.get("scheduled_for") is None:
                    raise InvalidTransitionError(
                        "Scheduled items require scheduled_for (an ISO date or datetime)"
                    )
                task = self._task_from_fields(
                    title=title,
                    source=item,
                    tags=tags,
                    status=TaskStatus.SCHEDULED,
                    fields=fields,
                )
                created.append((task, self._task_body(source.body)))

            elif choice is ClarifyDecision.SOMEDAY:
                someday = SomedayItem(
                    id=_new_id("SOM"),
                    title=title,
                    source_inbox_id=item.id,
                    review_on=fields.get("review_on"),
                    tags=tags,
                )
                created.append((someday, source.body))

            elif choice is ClarifyDecision.REFERENCE:
                reference = Reference(
                    id=_new_id("REF"),
                    title=title,
                    source_inbox_id=item.id,
                    tags=tags,
                )
                created.append((reference, source.body))

            elif choice is ClarifyDecision.DONE:
                task = self._task_from_fields(
                    title=title,
                    source=item,
                    tags=tags,
                    status=TaskStatus.DONE,
                    fields={**fields, "completed_at": now},
                )
                created.append((task, self._task_body(source.body)))

            elif choice is ClarifyDecision.TRASH:
                pass
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc

        refs: list[EntityRef] = []
        for entity, body in created:
            record = self.workspace.write(entity, body)
            refs.append(
                EntityRef(
                    id=entity.id,
                    kind=entity.kind,
                    title=entity.title,
                    path=self.workspace.relative(record.path),
                )
            )

        archived = ArchivedInboxItem(
            id=item.id,
            title=item.title,
            source=item.source,
            captured_at=item.captured_at,
            disposition=choice,
            result_ids=[ref.id for ref in refs],
            tags=item.tags,
        )
        archive_record = self.workspace.archive_record(source, archived)
        self._event(
            EventType.CLARIFIED,
            entity_id=item.id,
            payload={
                "decision": choice.value,
                "result_ids": archived.result_ids,
                "handling": ("two_minute" if choice is ClarifyDecision.DONE else "normal"),
            },
        )
        if choice is ClarifyDecision.DONE and refs:
            self._event(
                EventType.TASK_COMPLETED,
                entity_id=refs[0].id,
                payload={"completed_during_clarify": True, "two_minute_rule": True},
            )
        return ClarifyResult(
            source_id=item.id,
            decision=choice,
            created=refs,
            archived_path=self.workspace.relative(archive_record.path),
        )

    def _task_body(self, source_body: str) -> str:
        return render_gtd_template(
            self.workspace,
            "task.md",
            intent=source_body,
        )

    @staticmethod
    def _task_from_fields(
        *,
        title: str,
        source: InboxItem,
        tags: list[str],
        status: TaskStatus,
        fields: dict[str, Any],
    ) -> Task:
        criteria = fields.get("completion_criteria") or []
        if isinstance(criteria, str):
            criteria = [criteria]
        contexts = fields.get("contexts") or fields.get("context") or []
        if isinstance(contexts, str):
            contexts = [contexts]
        completed_at = fields.get("completed_at")
        lifecycle = TaskLifecycle.OPEN
        disposition = TaskDisposition.NEXT
        execution = TaskExecution()
        waiting = None
        blockers: list[TaskBlocker] = []
        resolution = None
        if status is TaskStatus.DOING:
            execution = TaskExecution(
                state=ExecutionState.DOING,
                started_at=fields.get("started_at") or utc_now(),
            )
        elif status is TaskStatus.WAITING:
            disposition = TaskDisposition.WAITING
            waiting = WaitingDetail(
                target=str(fields.get("waiting_for") or "").strip(),
                request=fields.get("waiting_request"),
                expected_on=fields.get("expected_on"),
                follow_up_on=fields.get("follow_up_on"),
                escalation_on=fields.get("escalation_on"),
                escalation_to=fields.get("escalation_to"),
            )
        elif status is TaskStatus.SCHEDULED:
            disposition = TaskDisposition.CALENDAR
        elif status is TaskStatus.BLOCKED:
            blockers = [
                TaskBlocker(
                    id="BLK-1",
                    description=str(fields.get("blocked_reason") or "Blocked"),
                )
            ]
        elif status is TaskStatus.DONE:
            lifecycle = TaskLifecycle.COMPLETED
            resolution = TaskResolution.COMPLETED
        elif status is TaskStatus.CANCELLED:
            lifecycle = TaskLifecycle.CANCELLED
            resolution = TaskResolution.CANCELLED
        assumption_values = fields.get("assumptions") or []
        assumptions = [
            value
            if isinstance(value, Assumption)
            else Assumption(
                id=f"ASM-{index}",
                statement=(value if isinstance(value, str) else value["statement"]),
            )
            for index, value in enumerate(assumption_values, start=1)
        ]
        conditions = [
            CompletionCondition(id=f"CC-{index}", text=str(value).strip())
            for index, value in enumerate(criteria, start=1)
            if str(value).strip()
        ]
        estimate = fields.get("estimate_minutes")
        rigor = TaskRigor(fields.get("rigor") or TaskRigor.QUICK)
        return Task(
            id=_new_id("TASK"),
            title=title,
            work_type=fields.get("work_type") or WorkType.ACTION,
            rigor=rigor,
            goal=fields.get("goal"),
            why=fields.get("why"),
            desired_outcome=fields.get("desired_outcome"),
            urgency=fields.get("urgency") or Urgency.NORMAL,
            impact=fields.get("impact") or Impact.MEDIUM,
            commitment=fields.get("commitment") or Commitment.NONE,
            lifecycle=lifecycle,
            disposition=disposition,
            execution=execution,
            source_inbox_id=source.id,
            project_id=fields.get("project_id"),
            parent_id=fields.get("parent_id"),
            contexts=_normalize_tags(contexts),
            energy=fields.get("energy"),
            original_estimate_minutes=estimate,
            remaining_estimate_minutes=estimate,
            schedule=TaskSchedule(
                not_before=fields.get("not_before"),
                due_on=fields.get("due_on"),
                scheduled_for=fields.get("scheduled_for"),
            ),
            waiting=waiting,
            blockers=blockers,
            constraints=[str(value).strip() for value in fields.get("constraints") or []],
            assumptions=assumptions,
            risks=[str(value).strip() for value in fields.get("risks") or []],
            completion=CompletionDefinition(
                obvious=rigor is TaskRigor.QUICK,
                conditions=conditions,
            ),
            recurrence=fields.get("recurrence"),
            recurrence_series_id=fields.get("recurrence_series_id"),
            occurrence_on=fields.get("occurrence_on"),
            resolution=resolution,
            completed_at=completed_at,
            tags=tags,
        )

    def list_tasks(self, statuses: set[TaskStatus] | None = None) -> list[Task]:
        tasks = [cast(Task, record.entity) for record in self.workspace.list_records("task")]
        return [task for task in tasks if statuses is None or task.status in statuses]

    def list_projects(self, statuses: set[ProjectStatus] | None = None) -> list[GtdProject]:
        projects = [
            cast(GtdProject, record.entity) for record in self.workspace.list_records("gtd_project")
        ]
        return [project for project in projects if statuses is None or project.status in statuses]

    def create_project(
        self,
        *,
        title: str,
        outcome: str,
        project_id: str | None = None,
        area: str | None = None,
        review_every_days: int = 7,
        tags: Iterable[str] | None = None,
        body: str | None = None,
    ) -> GtdProject:
        """Create an outcome directly, without inventing an Inbox provenance record."""

        clean_title = title.strip()
        clean_outcome = outcome.strip()
        if not clean_title or not clean_outcome:
            raise InvalidTransitionError("A GTD project requires both title and outcome")
        try:
            project = GtdProject(
                id=project_id or _new_id("GPR"),
                title=clean_title,
                outcome=clean_outcome,
                area=area,
                review_every_days=review_every_days,
                tags=_normalize_tags(tags),
            )
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc
        content = body or render_gtd_template(
            self.workspace,
            "project.md",
            outcome=project.outcome,
            source_id="direct creation",
        )
        with self.workspace.lock():
            path = self.workspace.path_for(project)
            if path.exists():
                raise InvalidTransitionError(f"GTD project ID already exists: {project.id}")
            self.workspace.write(project, content)
            self._event(
                EventType.PROJECT_CREATED,
                entity_id=project.id,
                payload={"outcome": project.outcome},
            )
        return project

    def _task_record(self, task_id: str) -> EntityRecord[Task]:
        return cast(
            EntityRecord[Task],
            self.workspace.find_record(task_id, kinds={"task"}),
        )

    def _project_record(self, project_id: str) -> EntityRecord[GtdProject]:
        return cast(
            EntityRecord[GtdProject],
            self.workspace.find_record(project_id, kinds={"gtd_project"}),
        )

    def _write_task(self, record: EntityRecord[Task], task: Task) -> Task:
        self.workspace.write(task, record.body)
        return task

    @staticmethod
    def _evolve_task(task: Task, **updates: Any) -> Task:
        data = task.persistent_dict()
        data.update(updates)
        data["revision"] = task.revision + 1
        data["updated_at"] = utc_now()
        try:
            return Task.model_validate(data)
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc

    @staticmethod
    def _evolve_waiting(waiting: WaitingDetail, **updates: Any) -> WaitingDetail:
        data = waiting.model_dump(mode="json", exclude_none=True)
        data.update(updates)
        try:
            return WaitingDetail.model_validate(data)
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc

    @staticmethod
    def _waiting_interaction(
        waiting: WaitingDetail,
        *,
        kind: WaitingInteractionKind,
        note: str | None,
        occurred_at: datetime,
        party: str | None = None,
        next_follow_up_on: date | str | None = None,
    ) -> WaitingInteraction:
        try:
            return WaitingInteraction(
                id=_next_sequence_id(
                    "INT",
                    (interaction.id for interaction in waiting.interactions),
                ),
                kind=kind,
                occurred_at=occurred_at,
                note=note,
                party=party,
                next_follow_up_on=next_follow_up_on,
            )
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc

    @staticmethod
    def _evolve_schedule(schedule: TaskSchedule, **updates: Any) -> TaskSchedule:
        data = schedule.model_dump(mode="json", exclude_none=True)
        data.update(updates)
        try:
            return TaskSchedule.model_validate(data)
        except ValidationError as exc:
            raise InvalidTransitionError(str(exc)) from exc

    def get_task(self, task_id: str) -> Task:
        return self._task_record(task_id).entity

    def get_project(self, project_id: str) -> GtdProject:
        return self._project_record(project_id).entity

    def document_ref(self, query: str) -> EntityRef:
        """Resolve a human ID prefix to an editor-safe public document reference."""

        record = self.workspace.find_record(query, kinds={"task", "gtd_project"})
        entity = cast(Task | GtdProject, record.entity)
        return EntityRef(
            id=entity.id,
            kind=entity.kind,
            title=entity.title,
            path=self.workspace.relative(record.path),
        )

    def define_task(
        self,
        task_id: str,
        *,
        work_type: WorkType | str | None = None,
        rigor: TaskRigor | str | None = None,
        urgency: Urgency | str | None = None,
        impact: Impact | str | None = None,
        commitment: Commitment | str | None = None,
        goal: str | None = None,
        why: str | None = None,
        desired_outcome: str | None = None,
        constraints: Iterable[str] | None = None,
        assumptions: Iterable[str] | None = None,
        risks: Iterable[str] | None = None,
        completion_criteria: Iterable[str] | None = None,
        original_estimate_minutes: int | None = None,
        remaining_estimate_minutes: int | None = None,
    ) -> Task:
        """Define rigor fields together so validation never sees a partial ticket."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            updates: dict[str, Any] = {}
            for key, value in {
                "work_type": work_type,
                "rigor": rigor,
                "urgency": urgency,
                "impact": impact,
                "commitment": commitment,
                "goal": goal.strip() if goal else None,
                "why": why.strip() if why else None,
                "desired_outcome": desired_outcome.strip() if desired_outcome else None,
            }.items():
                if value is not None:
                    updates[key] = value
            if constraints is not None:
                updates["constraints"] = [value.strip() for value in constraints if value.strip()]
            if risks is not None:
                updates["risks"] = [value.strip() for value in risks if value.strip()]
            if assumptions is not None:
                updates["assumptions"] = [
                    Assumption(id=f"ASM-{index}", statement=value.strip()).model_dump(mode="json")
                    for index, value in enumerate(assumptions, start=1)
                    if value.strip()
                ]
            if (constraints is not None or assumptions is not None) and completion_criteria is None:
                updates["completion"] = task.completion.model_copy(
                    update={
                        "assurance_reviewed_at": None,
                        "assurance_review_hash": None,
                    }
                ).model_dump(mode="json", exclude_none=True)
            if completion_criteria is not None:
                conditions = [
                    CompletionCondition(id=f"CC-{index}", text=value.strip())
                    for index, value in enumerate(completion_criteria, start=1)
                    if value.strip()
                ]
                updates["completion"] = CompletionDefinition(
                    obvious=not conditions,
                    conditions=conditions,
                ).model_dump(mode="json", exclude_none=True)
            if original_estimate_minutes is not None:
                if (
                    task.original_estimate_minutes is not None
                    and task.original_estimate_minutes != original_estimate_minutes
                ):
                    raise InvalidTransitionError(
                        "original_estimate_minutes is immutable once recorded"
                    )
                updates["original_estimate_minutes"] = original_estimate_minutes
                if task.remaining_estimate_minutes is None and remaining_estimate_minutes is None:
                    updates["remaining_estimate_minutes"] = original_estimate_minutes
            if remaining_estimate_minutes is not None:
                if (
                    task.remaining_estimate_minutes is not None
                    and task.remaining_estimate_minutes != remaining_estimate_minutes
                ):
                    raise InvalidTransitionError(
                        "Use set_remaining_estimate with a reason to revise remaining work"
                    )
                updates["remaining_estimate_minutes"] = remaining_estimate_minutes
            updated = self._evolve_task(task, **updates)
            self._write_task(record, updated)
            self._event(
                EventType.TASK_DEFINED,
                entity_id=updated.id,
                payload={"fields": sorted(updates)},
            )
            return updated

    def set_task_parent(self, task_id: str, parent_id: str | None) -> Task:
        """Set decomposition hierarchy independently from dependency links."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            canonical_parent_id: str | None = None
            if parent_id is not None:
                parent = self._task_record(parent_id).entity
                canonical_parent_id = parent.id
                if parent.id == task.id:
                    raise InvalidTransitionError("A task cannot be its own parent")
                cursor = parent
                visited: set[str] = set()
                while True:
                    if cursor.id == task.id:
                        raise InvalidTransitionError(
                            f"Setting {parent.id} as parent of {task.id} creates a parent cycle"
                        )
                    if cursor.id in visited or cursor.parent_id is None:
                        break
                    visited.add(cursor.id)
                    cursor = self._task_record(cursor.parent_id).entity
            if task.parent_id == canonical_parent_id:
                return task
            updated = self._evolve_task(task, parent_id=canonical_parent_id)
            self._write_task(record, updated)
            self._event(
                EventType.TASK_PARENT_SET,
                entity_id=task.id,
                payload={"parent_id": canonical_parent_id},
            )
            return updated

    def log_work(
        self,
        task_id: str,
        *,
        minutes: float,
        note: str | None = None,
        source: WorkLogSource | str = WorkLogSource.MANUAL,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> Task:
        """Append actual effort without mutating the original estimate."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            return self._append_work_log(
                record,
                task,
                minutes=minutes,
                note=note,
                source=source,
                started_at=started_at,
                stopped_at=stopped_at,
            )

    @staticmethod
    def _effective_work_log_minutes(task: Task) -> dict[str, float]:
        effective = {log.id: log.minutes for log in GtdService._logs_with_legacy_actual(task)}
        for correction in task.work_log_corrections:
            effective[correction.work_log_id] = correction.corrected_minutes
        return effective

    def correct_work_log(
        self,
        task_id: str,
        work_log_id: str,
        *,
        corrected_minutes: float,
        reason: str,
    ) -> Task:
        """Append an auditable correction without rewriting the original work log."""

        clean_reason = reason.strip()
        if corrected_minutes < 0:
            raise InvalidTransitionError("Corrected work-log minutes cannot be negative")
        if not clean_reason:
            raise InvalidTransitionError("Correcting a work log requires a reason")
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            effective = self._effective_work_log_minutes(task)
            previous = effective.get(work_log_id)
            if previous is None:
                raise EntityNotFoundError(f"No work log {work_log_id!r} on {task.id}")
            if abs(previous - corrected_minutes) <= 0.000001:
                raise InvalidTransitionError(
                    f"Work log {work_log_id} is already {corrected_minutes} minutes"
                )
            correction = WorkLogCorrection(
                id=_new_id("WLC"),
                work_log_id=work_log_id,
                previous_minutes=previous,
                corrected_minutes=corrected_minutes,
                reason=clean_reason,
            )
            effective[work_log_id] = corrected_minutes
            updated = self._evolve_task(
                task,
                actual_minutes=round(sum(effective.values()), 2),
                work_log_corrections=[
                    *(
                        item.model_dump(mode="json", exclude_none=True)
                        for item in task.work_log_corrections
                    ),
                    correction.model_dump(mode="json", exclude_none=True),
                ],
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_WORK_LOG_CORRECTED,
                entity_id=task.id,
                payload={
                    "correction_id": correction.id,
                    "work_log_id": correction.work_log_id,
                    "from_minutes": correction.previous_minutes,
                    "to_minutes": correction.corrected_minutes,
                    "reason": correction.reason,
                },
            )
            return updated

    def _append_work_log(
        self,
        record: EntityRecord[Task],
        task: Task,
        *,
        minutes: float,
        note: str | None,
        source: WorkLogSource | str,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
        extra_updates: dict[str, Any] | None = None,
    ) -> Task:
        if minutes <= 0:
            raise InvalidTransitionError("Work log minutes must be greater than zero")
        existing_logs = self._logs_with_legacy_actual(task)
        effective_existing = self._effective_work_log_minutes(task)
        log = WorkLog(
            id=_next_sequence_id("WL", (item.id for item in existing_logs)),
            minutes=max(round(minutes, 6), 0.000001),
            source=source,
            note=note.strip() if note else None,
            started_at=started_at,
            stopped_at=stopped_at,
        )
        remaining = task.remaining_estimate_minutes
        if remaining is not None:
            remaining = max(0, round(remaining - log.minutes, 2))
        updates: dict[str, Any] = {
            "actual_minutes": round(
                sum(effective_existing.values()) + log.minutes,
                2,
            ),
            "remaining_estimate_minutes": remaining,
            "work_logs": [
                *(item.model_dump(mode="json", exclude_none=True) for item in existing_logs),
                log.model_dump(mode="json", exclude_none=True),
            ],
        }
        updates.update(extra_updates or {})
        updated = self._evolve_task(task, **updates)
        self._write_task(record, updated)
        self._event(
            EventType.TASK_WORK_LOGGED,
            entity_id=task.id,
            payload={
                "work_log_id": log.id,
                "minutes": log.minutes,
                "source": log.source.value,
                "note": log.note,
            },
        )
        return updated

    @staticmethod
    def _logs_with_legacy_actual(task: Task) -> list[WorkLog]:
        logs = list(task.work_logs)
        if not logs and task.actual_minutes > 0:
            logs.append(
                WorkLog(
                    id="WL-LEGACY",
                    minutes=task.actual_minutes,
                    source=WorkLogSource.MIGRATED,
                    note="Migrated from legacy actual_minutes projection",
                    recorded_at=task.updated_at,
                )
            )
        return logs

    def set_remaining_estimate(
        self,
        task_id: str,
        *,
        minutes: int,
        reason: str,
    ) -> Task:
        if minutes < 0:
            raise InvalidTransitionError("Remaining estimate cannot be negative")
        if not reason.strip():
            raise InvalidTransitionError("Changing remaining estimate requires a reason")
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            if task.lifecycle is not TaskLifecycle.OPEN:
                raise InvalidTransitionError(
                    f"Cannot revise remaining estimate on a {task.lifecycle.value} task"
                )
            previous = task.remaining_estimate_minutes
            updated = self._evolve_task(task, remaining_estimate_minutes=minutes)
            self._write_task(record, updated)
            self._event(
                EventType.TASK_ESTIMATE_UPDATED,
                entity_id=task.id,
                payload={
                    "field": "remaining_estimate_minutes",
                    "from": previous,
                    "to": minutes,
                    "reason": reason.strip(),
                },
            )
            return updated

    def set_recurrence(
        self,
        task_id: str,
        *,
        frequency: RecurrenceFrequency | str,
        interval: int = 1,
        anchor_on: date | str | None = None,
        until_on: date | str | None = None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            anchor = anchor_on or task.occurrence_on or utc_now().date()
            rule = RecurrenceRule(
                frequency=frequency,
                interval=interval,
                anchor_on=anchor,
                until_on=until_on,
            )
            updated = self._evolve_task(
                task,
                recurrence=rule.model_dump(mode="json", exclude_none=True),
                recurrence_series_id=task.recurrence_series_id or task.id,
                occurrence_on=rule.anchor_on,
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_RECURRENCE_SET,
                entity_id=task.id,
                payload=rule.model_dump(mode="json", exclude_none=True),
            )
            return updated

    @staticmethod
    def _require_open(task: Task, operation: str) -> None:
        if task.lifecycle is not TaskLifecycle.OPEN:
            raise InvalidTransitionError(
                f"Cannot {operation} {task.id} while it is {task.lifecycle.value}"
            )

    def delegate_task(
        self,
        task_id: str,
        *,
        target: str,
        request: str | None = None,
        target_kind: str = "person",
        expected_on: date | str | None = None,
        follow_up_on: date | str | None = None,
        escalation_on: date | str | None = None,
        escalation_to: str | None = None,
    ) -> Task:
        """Delegate an open action without losing its blocker or due-date facets."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            self._require_open(task, "delegate")
            if task.waiting is not None:
                raise InvalidTransitionError(
                    f"Task {task.id} is already delegated; follow up or resolve it"
                )
            if task.status is TaskStatus.DOING:
                task = self._stop_task_unlocked(task.id)
                record = self._task_record(task.id)
            now = utc_now()
            clean_request = request.strip() if request and request.strip() else None
            waiting_id = _new_id("WAIT")
            try:
                delegated_interaction = WaitingInteraction(
                    id="INT-1",
                    kind=WaitingInteractionKind.DELEGATED,
                    occurred_at=now,
                    note=clean_request,
                )
                waiting = WaitingDetail(
                    id=waiting_id,
                    target_kind=target_kind,
                    target=target,
                    request=clean_request,
                    delegated_at=now,
                    expected_on=expected_on,
                    follow_up_on=follow_up_on,
                    escalation_on=escalation_on,
                    escalation_to=escalation_to,
                    interactions=[delegated_interaction],
                )
            except ValidationError as exc:
                raise InvalidTransitionError(str(exc)) from exc
            schedule = task.schedule.model_copy(update={"scheduled_for": None})
            updated = self._evolve_task(
                task,
                disposition=TaskDisposition.WAITING,
                waiting=waiting.model_dump(mode="json", exclude_none=True),
                schedule=schedule.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_DELEGATED,
                entity_id=task.id,
                payload={
                    "waiting_id": waiting.id,
                    "target": waiting.target,
                    "request": waiting.request,
                    "delegated_at": waiting.delegated_at.isoformat(),
                    "expected_on": (
                        waiting.expected_on.isoformat() if waiting.expected_on else None
                    ),
                    "follow_up_on": (
                        waiting.follow_up_on.isoformat() if waiting.follow_up_on else None
                    ),
                    "escalation_on": (
                        waiting.escalation_on.isoformat() if waiting.escalation_on else None
                    ),
                    "escalation_to": waiting.escalation_to,
                },
            )
            return updated

    def follow_up_waiting(
        self,
        task_id: str,
        *,
        note: str,
        next_follow_up_on: date | str | None = None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            waiting = task.waiting
            if (
                task.lifecycle is not TaskLifecycle.OPEN
                or task.disposition is not TaskDisposition.WAITING
                or waiting is None
            ):
                raise InvalidTransitionError(f"Task {task.id} is not waiting for a response")
            now = utc_now()
            interaction = self._waiting_interaction(
                waiting,
                kind=WaitingInteractionKind.FOLLOW_UP,
                occurred_at=now,
                note=note,
                next_follow_up_on=next_follow_up_on,
            )
            updated_waiting = self._evolve_waiting(
                waiting,
                last_followed_up_at=now,
                follow_up_on=next_follow_up_on,
                interactions=[*waiting.interactions, interaction],
            )
            updated = self._evolve_task(
                task,
                waiting=updated_waiting.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_WAITING_FOLLOWED_UP,
                entity_id=task.id,
                payload={
                    "waiting_id": waiting.id,
                    "scheduled_on": (
                        waiting.follow_up_on.isoformat() if waiting.follow_up_on else None
                    ),
                    "note": interaction.note,
                    "next_follow_up_on": (
                        interaction.next_follow_up_on.isoformat()
                        if interaction.next_follow_up_on
                        else None
                    ),
                },
            )
            return updated

    def escalate_waiting(
        self,
        task_id: str,
        *,
        note: str,
        escalation_to: str | None = None,
        next_escalation_on: date | str | None = None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            waiting = task.waiting
            if (
                task.lifecycle is not TaskLifecycle.OPEN
                or task.disposition is not TaskDisposition.WAITING
                or waiting is None
            ):
                raise InvalidTransitionError(f"Task {task.id} is not waiting for a response")
            target = (escalation_to or waiting.escalation_to or "").strip()
            if not target:
                raise InvalidTransitionError("Escalation requires escalation_to")
            now = utc_now()
            interaction = self._waiting_interaction(
                waiting,
                kind=WaitingInteractionKind.ESCALATED,
                occurred_at=now,
                note=note,
                party=target,
            )
            updated_waiting = self._evolve_waiting(
                waiting,
                escalation_to=target,
                escalation_on=next_escalation_on,
                last_escalated_at=now,
                interactions=[*waiting.interactions, interaction],
            )
            updated = self._evolve_task(
                task,
                waiting=updated_waiting.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_ESCALATED,
                entity_id=task.id,
                payload={
                    "waiting_id": waiting.id,
                    "scheduled_on": (
                        waiting.escalation_on.isoformat() if waiting.escalation_on else None
                    ),
                    "escalation_to": target,
                    "next_escalation_on": (
                        updated_waiting.escalation_on.isoformat()
                        if updated_waiting.escalation_on
                        else None
                    ),
                    "note": interaction.note,
                },
            )
            return updated

    def record_waiting_response(
        self,
        task_id: str,
        *,
        note: str,
        resolved: bool,
        next_follow_up_on: date | str | None = None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            waiting = task.waiting
            if (
                task.lifecycle is not TaskLifecycle.OPEN
                or task.disposition is not TaskDisposition.WAITING
                or waiting is None
            ):
                raise InvalidTransitionError(f"Task {task.id} is not waiting for a response")
            if resolved and next_follow_up_on is not None:
                raise InvalidTransitionError(
                    "A resolved waiting response cannot schedule another follow-up"
                )
            now = utc_now()
            interaction = self._waiting_interaction(
                waiting,
                kind=WaitingInteractionKind.RESPONSE,
                occurred_at=now,
                note=note,
                next_follow_up_on=next_follow_up_on,
            )
            interactions = [*waiting.interactions, interaction]
            updates: dict[str, Any]
            if resolved:
                resolved_waiting = self._evolve_waiting(
                    waiting,
                    interactions=interactions,
                    resolved_at=now,
                    resolution_note=interaction.note,
                )
                updates = {
                    "disposition": TaskDisposition.NEXT,
                    "waiting": None,
                    "waiting_history": [
                        *(
                            item.model_dump(mode="json", exclude_none=True)
                            for item in task.waiting_history
                        ),
                        resolved_waiting.model_dump(mode="json", exclude_none=True),
                    ],
                }
            else:
                updated_waiting = self._evolve_waiting(
                    waiting,
                    interactions=interactions,
                    follow_up_on=next_follow_up_on,
                )
                updates = {"waiting": updated_waiting.model_dump(mode="json", exclude_none=True)}
            updated = self._evolve_task(task, **updates)
            self._write_task(record, updated)
            self._event(
                EventType.TASK_RESPONSE_RECORDED,
                entity_id=task.id,
                payload={
                    "waiting_id": waiting.id,
                    "resolved": resolved,
                    "note": interaction.note,
                    "next_follow_up_on": (
                        interaction.next_follow_up_on.isoformat()
                        if interaction.next_follow_up_on
                        else None
                    ),
                },
            )
            if resolved:
                self._event(
                    EventType.TASK_WAITING_RESOLVED,
                    entity_id=task.id,
                    payload={
                        "waiting_id": waiting.id,
                        "outcome": interaction.note,
                    },
                )
            return updated

    def schedule_task(
        self,
        task_id: str,
        *,
        scheduled_for: datetime | str,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            self._require_open(task, "schedule")
            if task.waiting is not None:
                raise InvalidTransitionError("Resolve waiting before scheduling the task")
            if task.status is TaskStatus.DOING:
                task = self._stop_task_unlocked(task.id)
                record = self._task_record(task.id)
            schedule = self._evolve_schedule(
                task.schedule,
                scheduled_for=scheduled_for,
            )
            updated = self._evolve_task(
                task,
                disposition=TaskDisposition.CALENDAR,
                schedule=schedule.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_SCHEDULED,
                entity_id=task.id,
                payload={"scheduled_for": schedule.scheduled_for.isoformat()},
            )
            return updated

    def defer_task(
        self,
        task_id: str,
        *,
        not_before: datetime | str,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            self._require_open(task, "defer")
            if task.waiting is not None:
                raise InvalidTransitionError("Resolve waiting before deferring the task")
            if task.status is TaskStatus.DOING:
                task = self._stop_task_unlocked(task.id)
                record = self._task_record(task.id)
            schedule = self._evolve_schedule(
                task.schedule,
                not_before=not_before,
            )
            updated = self._evolve_task(
                task,
                schedule=schedule.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_DEFERRED,
                entity_id=task.id,
                payload={"not_before": schedule.not_before.isoformat()},
            )
            return updated

    def set_task_due(
        self,
        task_id: str,
        *,
        due_on: date | str | None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            self._require_open(task, "set a due date on")
            schedule = self._evolve_schedule(task.schedule, due_on=due_on)
            updated = self._evolve_task(
                task,
                schedule=schedule.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_DUE_SET,
                entity_id=task.id,
                payload={"due_on": schedule.due_on.isoformat() if schedule.due_on else None},
            )
            return updated

    def check_completion_condition(
        self,
        task_id: str,
        condition_id: str,
        *,
        evidence: str | None = None,
    ) -> Task:
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            matches = [
                condition
                for condition in task.completion.conditions
                if condition.id == condition_id
            ]
            if not matches:
                raise EntityNotFoundError(f"No completion condition {condition_id!r} on {task.id}")
            now = utc_now()
            conditions = [
                condition.model_copy(update={"met_at": now, "evidence": evidence})
                if condition.id == condition_id
                else condition
                for condition in task.completion.conditions
            ]
            completion = task.completion.model_copy(update={"conditions": conditions})
            updated = self._evolve_task(
                task,
                completion=completion.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_CONDITION_CHECKED,
                entity_id=task.id,
                payload={"condition_id": condition_id, "evidence": evidence},
            )
            return updated

    def review_task_assurance(self, task_id: str) -> Task:
        """Record that constraints and assumptions were explicitly reviewed."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            if task.rigor is not TaskRigor.ASSURED:
                raise InvalidTransitionError(
                    f"Task {task.id} is {task.rigor.value}; assurance review is not required"
                )
            reviewed_at = utc_now()
            completion = task.completion.model_copy(
                update={
                    "assurance_reviewed_at": reviewed_at,
                    "assurance_review_hash": task.assurance_input_hash(),
                }
            )
            updated = self._evolve_task(
                task,
                completion=completion.model_dump(mode="json", exclude_none=True),
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_ASSURANCE_REVIEWED,
                entity_id=task.id,
                payload={
                    "reviewed_at": reviewed_at.isoformat(),
                    "constraint_count": len(task.constraints),
                    "assumption_count": len(task.assumptions),
                },
            )
            return updated

    def link_tasks(
        self,
        source_id: str,
        target_id: str,
        *,
        relation_type: RelationType | str,
    ) -> Task:
        with self.workspace.lock():
            source_record = self._task_record(source_id)
            source = source_record.entity
            target = self._task_record(target_id).entity
            relation = TaskRelation(type=relation_type, target_id=target.id)
            if source.id == target.id:
                raise InvalidTransitionError("A task relation cannot target itself")
            if relation in source.relations:
                return source
            if relation.type is RelationType.BLOCKS:
                creates_cycle = self._has_dependency_path(target.id, source.id)
            elif relation.type is RelationType.DEPENDS_ON:
                creates_cycle = self._has_dependency_path(source.id, target.id)
            else:
                creates_cycle = False
            if creates_cycle:
                raise InvalidTransitionError(
                    f"{relation.type.value} relation {source.id} -> {target.id} creates a cycle"
                )
            relations = [*source.relations, relation]
            updated = self._evolve_task(
                source,
                relations=[item.model_dump(mode="json") for item in relations],
            )
            self._write_task(source_record, updated)
            self._event(
                EventType.TASK_LINKED,
                entity_id=source.id,
                payload={"type": relation.type.value, "target_id": target.id},
            )
            return updated

    def _dependency_graph(self) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {task.id: [] for task in self.list_tasks()}
        for task in self.list_tasks():
            for relation in task.relations:
                if relation.type is RelationType.BLOCKS:
                    graph[task.id].append(relation.target_id)
                elif relation.type is RelationType.DEPENDS_ON:
                    graph.setdefault(relation.target_id, []).append(task.id)
        return graph

    def _has_dependency_path(self, start_id: str, goal_id: str) -> bool:
        graph = self._dependency_graph()
        pending = [start_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == goal_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(graph.get(current, []))
        return False

    def _unfinished_predecessors(self, task_id: str, *, strict: bool = True) -> list[Task]:
        current = self._task_record(task_id).entity
        depends_on = {
            relation.target_id
            for relation in current.relations
            if relation.type is RelationType.DEPENDS_ON
        }
        tasks = self.list_tasks()
        known_ids = {task.id for task in tasks}
        missing = sorted(depends_on - known_ids)
        if missing:
            if strict:
                raise InvalidTransitionError(
                    f"{current.id} depends on missing tasks: {', '.join(missing)}"
                )
            return [current]
        return [
            task
            for task in tasks
            if task.status is not TaskStatus.DONE
            and (
                task.id in depends_on
                or any(
                    relation.type is RelationType.BLOCKS and relation.target_id == task_id
                    for relation in task.relations
                )
            )
        ]

    def _write_project(
        self,
        record: EntityRecord[GtdProject],
        project: GtdProject,
    ) -> GtdProject:
        self.workspace.write(project, record.body)
        return project

    def _entity_ref(self, entity: Task | GtdProject) -> EntityRef:
        return EntityRef(
            id=entity.id,
            kind=entity.kind,
            title=entity.title,
            path=self.workspace.relative(self.workspace.path_for(entity)),
        )

    def current_task(self) -> Task | None:
        doing = self.list_tasks({TaskStatus.DOING})
        if len(doing) > 1:
            raise WipLimitError(f"Workspace has {len(doing)} doing tasks; run `ws doctor`")
        return doing[0] if doing else None

    def focus(
        self,
        *,
        contexts: Iterable[str] | None = None,
        available_minutes: int | None = None,
        energy: Energy | str | None = None,
        as_of: datetime | None = None,
    ) -> list[Task]:
        current = self.current_task()
        if current is not None:
            return [current]

        requested_contexts = set(_normalize_tags(contexts))
        available_energy = Energy(energy) if energy is not None else None
        now = _ensure_aware(as_of) if as_of is not None else utc_now()
        candidates: list[Task] = []
        for task in self.list_tasks():
            is_ready_scheduled = (
                task.status is TaskStatus.SCHEDULED
                and task.scheduled_for is not None
                and _ensure_aware(task.scheduled_for) <= now
            )
            if task.status is not TaskStatus.NEXT and not is_ready_scheduled:
                continue
            if self._unfinished_predecessors(task.id, strict=False):
                continue
            if task.occurrence_on is not None and task.occurrence_on > now.date():
                continue
            if task.not_before is not None and _ensure_aware(task.not_before) > now:
                continue
            if requested_contexts and not requested_contexts.intersection(task.contexts):
                continue
            effort = (
                task.remaining_estimate_minutes
                if task.remaining_estimate_minutes is not None
                else task.estimate_minutes
            )
            if available_minutes is not None and effort is not None and effort > available_minutes:
                continue
            if (
                available_energy is not None
                and task.energy is not None
                and ENERGY_RANK[task.energy] > ENERGY_RANK[available_energy]
            ):
                continue
            candidates.append(task)

        return sorted(
            candidates,
            key=lambda task: (
                -URGENCY_RANK[task.urgency],
                -COMMITMENT_RANK[task.commitment],
                -IMPACT_RANK[task.impact],
                task.due_on is None,
                task.due_on or date.max,
                task.created_at,
            ),
        )

    def status(self) -> StatusReport:
        """Return the compact daily overview used by CLI and UI clients."""

        tasks = self.list_tasks()
        projects = self.list_projects()
        current = self.current_task()
        needs_action = [
            project
            for project in projects
            if project.status is ProjectStatus.ACTIVE and self._project_needs_action(project.id)
        ]
        return StatusReport(
            current_task=self._entity_ref(current) if current else None,
            inbox_count=len(self.list_inbox()),
            tasks_by_status={
                status.value: sum(task.status is status for task in tasks) for status in TaskStatus
            },
            projects_by_status={
                status.value: sum(project.status is status for project in projects)
                for status in ProjectStatus
            },
            ready_actions=[self._entity_ref(task) for task in self.focus()[:5]],
            projects_needing_action=[self._entity_ref(project) for project in needs_action],
        )

    def daily_dashboard(self, *, today: date | None = None) -> DailyDashboard:
        timezone = ZoneInfo(self.workspace.settings().timezone)
        day = today or utc_now().astimezone(timezone).date()
        tasks = [task for task in self.list_tasks() if task.lifecycle is TaskLifecycle.OPEN]

        def refs(items: Iterable[Task]) -> list[EntityRef]:
            ordered = sorted(items, key=lambda item: item.created_at)
            return [self._entity_ref(task) for task in ordered]

        overdue = [task for task in tasks if task.due_on is not None and task.due_on < day]
        due_today = [task for task in tasks if task.due_on == day]
        follow_ups = [
            task
            for task in tasks
            if task.waiting is not None
            and (task.waiting.follow_up_on is None or task.waiting.follow_up_on <= day)
        ]
        escalations = [
            task
            for task in tasks
            if task.waiting is not None
            and task.waiting.escalation_on is not None
            and task.waiting.escalation_on <= day
        ]
        scheduled = [
            task
            for task in tasks
            if task.disposition is TaskDisposition.CALENDAR
            and task.scheduled_for is not None
            and _ensure_aware(task.scheduled_for).astimezone(timezone).date() == day
        ]
        blocked = [task for task in tasks if task.status is TaskStatus.BLOCKED]
        as_of = datetime.combine(day, time.max, tzinfo=timezone)
        current = self.current_task()
        return DailyDashboard(
            day=day,
            current_task=self._entity_ref(current) if current else None,
            inbox_count=len(self.list_inbox()),
            overdue=refs(overdue),
            due_today=refs(due_today),
            follow_ups_due=refs(follow_ups),
            escalations_due=refs(escalations),
            scheduled_today=refs(scheduled),
            blocked=refs(blocked),
            available_actions=refs(self.focus(as_of=as_of)),
        )

    def start_task(self, task_id: str, *, switch: bool = False) -> Task:
        with self.workspace.lock():
            return self._start_task_unlocked(task_id, switch=switch)

    def _start_task_unlocked(self, task_id: str, *, switch: bool) -> Task:
        record = self._task_record(task_id)
        task = record.entity
        predecessors = self._unfinished_predecessors(task.id)
        if predecessors:
            ids = ", ".join(predecessor.id for predecessor in predecessors)
            raise InvalidTransitionError(f"{task.id} is blocked by {ids}")
        current = self.current_task()
        if current is not None and current.id != task.id:
            if not switch:
                raise WipLimitError(f"{current.id} is already doing; stop it or pass --switch")
            self._stop_task_unlocked(current.id)
            self._event(
                EventType.TASK_SWITCHED,
                entity_id=task.id,
                payload={"from_task_id": current.id},
            )
        if task.status is TaskStatus.DOING:
            return task
        if task.status in {
            TaskStatus.WAITING,
            TaskStatus.BLOCKED,
            TaskStatus.DONE,
            TaskStatus.CANCELLED,
        }:
            raise InvalidTransitionError(f"Cannot start {task.id} while it is {task.status.value}")
        if (
            task.status is TaskStatus.SCHEDULED
            and task.scheduled_for is not None
            and _ensure_aware(task.scheduled_for) > utc_now()
        ):
            raise InvalidTransitionError(f"{task.id} is scheduled for {task.scheduled_for}")

        now = utc_now()
        updated = self._evolve_task(
            task,
            execution=TaskExecution(
                state=ExecutionState.DOING,
                started_at=now,
            ).model_dump(mode="json", exclude_none=True),
        )
        self._write_task(record, updated)
        self._event(EventType.TASK_STARTED, entity_id=updated.id)
        return updated

    def stop_task(self, task_id: str | None = None) -> Task:
        with self.workspace.lock():
            return self._stop_task_unlocked(task_id)

    def _stop_task_unlocked(self, task_id: str | None = None) -> Task:
        if task_id is None:
            current = self.current_task()
            if current is None:
                raise EntityNotFoundError("No task is currently doing")
            task_id = current.id
        record = self._task_record(task_id)
        task = record.entity
        if task.status is not TaskStatus.DOING or task.started_at is None:
            raise InvalidTransitionError(f"{task.id} is not doing")
        now = utc_now()
        duration_seconds = max(0.0, (now - _ensure_aware(task.started_at)).total_seconds())
        if duration_seconds > 0:
            updated = self._append_work_log(
                record,
                task,
                minutes=duration_seconds / 60,
                note=None,
                source=WorkLogSource.TIMER,
                started_at=task.started_at,
                stopped_at=now,
                extra_updates={"execution": TaskExecution().model_dump(mode="json")},
            )
        else:
            updated = self._evolve_task(
                task,
                execution=TaskExecution().model_dump(mode="json"),
            )
            self._write_task(record, updated)
        self._event(
            EventType.TASK_STOPPED,
            entity_id=task.id,
            payload={
                "duration_seconds": duration_seconds,
                "next_status": updated.status.value,
                "work_log_id": updated.work_logs[-1].id if duration_seconds > 0 else None,
            },
        )
        return updated

    def complete_task(
        self,
        task_id: str,
        *,
        waiver_reason: str | None = None,
    ) -> CompletionResult:
        with self.workspace.lock():
            return self._complete_task_unlocked(task_id, waiver_reason=waiver_reason)

    def _complete_task_unlocked(
        self,
        task_id: str,
        *,
        waiver_reason: str | None = None,
    ) -> CompletionResult:
        record = self._task_record(task_id)
        task = record.entity
        if task.status is TaskStatus.DONE:
            next_occurrence = self._create_next_occurrence(record, task)
            return CompletionResult(
                task=task,
                project_attention_required=self._project_needs_action(task.project_id),
                project_id=task.project_id,
                next_occurrence=next_occurrence,
            )
        if task.status is TaskStatus.CANCELLED:
            raise InvalidTransitionError(f"Cancelled task {task.id} cannot be completed")
        if task.waiting is not None:
            raise InvalidTransitionError(
                f"Task {task.id} is waiting; record or resolve the response before completion"
            )
        unresolved_blockers = [blocker for blocker in task.blockers if blocker.resolved_at is None]
        if unresolved_blockers:
            ids = ", ".join(blocker.id for blocker in unresolved_blockers)
            raise InvalidTransitionError(f"Task {task.id} has unresolved blockers: {ids}")
        if waiver_reason is not None:
            waiver_reason = waiver_reason.strip()
            if not waiver_reason:
                raise InvalidTransitionError("Completion waiver reason cannot be blank")

        unmet = [condition for condition in task.completion.conditions if condition.met_at is None]
        missing_evidence = [
            condition
            for condition in task.completion.conditions
            if condition.met_at is not None and not condition.evidence
        ]
        if task.rigor in {TaskRigor.STANDARD, TaskRigor.ASSURED} and unmet and not waiver_reason:
            ids = ", ".join(condition.id for condition in unmet)
            raise InvalidTransitionError(f"Task {task.id} has unmet completion conditions: {ids}")
        if task.rigor is TaskRigor.ASSURED and missing_evidence and not waiver_reason:
            ids = ", ".join(condition.id for condition in missing_evidence)
            raise InvalidTransitionError(
                f"Task {task.id} completion conditions need evidence: {ids}"
            )
        if (
            task.rigor is TaskRigor.ASSURED
            and task.completion.assurance_reviewed_at is None
            and not waiver_reason
        ):
            raise InvalidTransitionError(
                f"Task {task.id} constraints and assumptions need assurance review"
            )
        if (
            task.rigor is TaskRigor.ASSURED
            and task.completion.assurance_reviewed_at is not None
            and task.completion.assurance_review_hash != task.assurance_input_hash()
            and not waiver_reason
        ):
            raise InvalidTransitionError(
                f"Task {task.id} assurance review is stale after constraints or assumptions changed"
            )

        now = utc_now()
        actual_minutes = round(sum(self._effective_work_log_minutes(task).values()), 2)
        remaining_estimate = task.remaining_estimate_minutes
        work_logs = self._logs_with_legacy_actual(task)
        timer_log: WorkLog | None = None
        duration_seconds = 0.0
        if task.status is TaskStatus.DOING and task.started_at is not None:
            duration_seconds = max(
                0.0,
                (now - _ensure_aware(task.started_at)).total_seconds(),
            )
            timer_minutes = max(round(duration_seconds / 60, 6), 0.000001)
            timer_log = WorkLog(
                id=_next_sequence_id("WL", (item.id for item in work_logs)),
                minutes=timer_minutes,
                source=WorkLogSource.TIMER,
                started_at=task.started_at,
                stopped_at=now,
            )
            work_logs.append(timer_log)
            actual_minutes = round(actual_minutes + timer_minutes, 2)
            if remaining_estimate is not None:
                remaining_estimate = max(0, round(remaining_estimate - timer_minutes, 2))
        completion = task.completion.model_copy(
            update={"waiver_reason": waiver_reason or task.completion.waiver_reason}
        )
        updated = self._evolve_task(
            task,
            lifecycle=TaskLifecycle.COMPLETED,
            execution=TaskExecution().model_dump(mode="json"),
            actual_minutes=actual_minutes,
            remaining_estimate_minutes=(0 if remaining_estimate is not None else None),
            work_logs=[item.model_dump(mode="json", exclude_none=True) for item in work_logs],
            completed_at=now,
            resolution=TaskResolution.COMPLETED,
            completion=completion.model_dump(mode="json", exclude_none=True),
        )
        self._write_task(record, updated)
        if timer_log is not None:
            self._event(
                EventType.TASK_WORK_LOGGED,
                entity_id=task.id,
                payload={
                    "work_log_id": timer_log.id,
                    "minutes": timer_log.minutes,
                    "source": timer_log.source.value,
                },
            )
            self._event(
                EventType.TASK_STOPPED,
                entity_id=task.id,
                payload={
                    "duration_seconds": duration_seconds,
                    "next_status": "done",
                    "work_log_id": timer_log.id,
                },
            )
        self._event(
            EventType.TASK_COMPLETED,
            entity_id=updated.id,
            payload={"waiver_reason": waiver_reason},
        )
        next_occurrence = self._create_next_occurrence(record, updated)
        needs_action = self._project_needs_action(updated.project_id)
        return CompletionResult(
            task=updated,
            project_attention_required=needs_action,
            project_id=updated.project_id,
            next_occurrence=next_occurrence,
        )

    def _create_next_occurrence(
        self,
        completed_record: EntityRecord[Task],
        completed: Task,
    ) -> Task | None:
        next_on = completed.next_occurrence_on
        if completed.recurrence is None or next_on is None:
            return None
        series_id = completed.recurrence_series_id or completed.id
        existing = next(
            (
                task
                for task in self.list_tasks()
                if task.id != completed.id
                and task.recurrence_series_id == series_id
                and task.occurrence_on == next_on
            ),
            None,
        )
        if existing is not None:
            self._ensure_recurrence_created_event(existing, completed, next_on)
            return existing
        now = utc_now()
        completion = CompletionDefinition(
            obvious=completed.completion.obvious,
            conditions=[
                CompletionCondition(id=item.id, text=item.text)
                for item in completed.completion.conditions
            ],
        )
        data = completed.persistent_dict()
        data.update(
            {
                "id": _new_id("TASK"),
                "revision": 1,
                "lifecycle": TaskLifecycle.OPEN,
                "disposition": TaskDisposition.NEXT,
                "execution": TaskExecution().model_dump(mode="json"),
                "created_at": now,
                "updated_at": now,
                "relations": [],
                "remaining_estimate_minutes": completed.original_estimate_minutes,
                "actual_minutes": 0,
                "work_logs": [],
                "work_log_corrections": [],
                "schedule": TaskSchedule().model_dump(mode="json"),
                "waiting": None,
                "waiting_history": [],
                "blockers": [],
                "completion": completion.model_dump(mode="json", exclude_none=True),
                "resolution": None,
                "result_summary": None,
                "evidence_links": [],
                "completed_at": None,
                "completion_history": [],
                "recurrence_series_id": series_id,
                "occurrence_on": next_on,
            }
        )
        next_task = Task.model_validate(data)
        self.workspace.write(
            next_task,
            self._task_body(self._recurring_intent(completed_record.body, completed.title)),
        )
        self._ensure_recurrence_created_event(next_task, completed, next_on)
        return next_task

    def _ensure_recurrence_created_event(
        self,
        next_task: Task,
        completed: Task,
        next_on: date,
    ) -> None:
        already_recorded = any(
            event.type == EventType.TASK_RECURRENCE_CREATED
            and event.entity_id == next_task.id
            and event.payload.get("previous_task_id") == completed.id
            for event in self.events.read_all()
        )
        if already_recorded:
            return
        self._event(
            EventType.TASK_RECURRENCE_CREATED,
            entity_id=next_task.id,
            payload={
                "series_id": next_task.recurrence_series_id,
                "previous_task_id": completed.id,
                "occurrence_on": next_on.isoformat(),
            },
        )

    @staticmethod
    def _recurring_intent(body: str, fallback: str) -> str:
        """Carry instructions forward without leaking notes or completion evidence."""

        lines = body.splitlines()
        try:
            start = lines.index("## Intent") + 1
        except ValueError:
            return fallback
        intent: list[str] = []
        for line in lines[start:]:
            if line.startswith("## "):
                break
            intent.append(line)
        rendered = "\n".join(intent).strip()
        return rendered or fallback

    def reopen_task(self, task_id: str, *, reason: str) -> Task:
        clean_reason = reason.strip()
        if not clean_reason:
            raise InvalidTransitionError("Reopening a task requires a reason")
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            if task.status is not TaskStatus.DONE or task.completed_at is None:
                raise InvalidTransitionError(f"Task {task.id} is not completed")
            if task.recurrence is not None:
                raise InvalidTransitionError(
                    "A recurring occurrence cannot be reopened after its successor is generated"
                )
            if task.resolution is None:
                raise InvalidTransitionError(f"Task {task.id} has no completion resolution")
            now = utc_now()
            snapshot = CompletionSnapshot(
                completed_at=task.completed_at,
                resolution=task.resolution,
                completion=task.completion,
                result_summary=task.result_summary,
                evidence_links=task.evidence_links,
                actual_minutes=task.actual_minutes,
                reopened_at=now,
                reopen_reason=clean_reason,
            )
            completion = CompletionDefinition(
                obvious=task.completion.obvious,
                conditions=[
                    CompletionCondition(id=condition.id, text=condition.text)
                    for condition in task.completion.conditions
                ],
            )
            updated = self._evolve_task(
                task,
                lifecycle=TaskLifecycle.OPEN,
                disposition=TaskDisposition.NEXT,
                execution=TaskExecution().model_dump(mode="json"),
                completion=completion.model_dump(mode="json", exclude_none=True),
                resolution=None,
                completed_at=None,
                result_summary=None,
                evidence_links=[],
                remaining_estimate_minutes=task.original_estimate_minutes,
                completion_history=[
                    *(
                        item.model_dump(mode="json", exclude_none=True)
                        for item in task.completion_history
                    ),
                    snapshot.model_dump(mode="json", exclude_none=True),
                ],
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_REOPENED,
                entity_id=task.id,
                payload={"reason": clean_reason},
            )
            return updated

    def block_task(self, task_id: str, reason: str) -> Task:
        with self.workspace.lock():
            return self._block_task_unlocked(task_id, reason)

    def _block_task_unlocked(self, task_id: str, reason: str) -> Task:
        if not reason.strip():
            raise InvalidTransitionError("A blocked task requires a reason")
        record = self._task_record(task_id)
        task = record.entity
        if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            raise InvalidTransitionError(f"Cannot block a {task.status.value} task")
        if task.status is TaskStatus.DOING:
            task = self._stop_task_unlocked(task.id)
            record = self._task_record(task.id)
        blockers = [
            *task.blockers,
            TaskBlocker(
                id=_next_sequence_id("BLK", (item.id for item in task.blockers)),
                description=reason.strip(),
            ),
        ]
        updated = self._evolve_task(
            task,
            blockers=[blocker.model_dump(mode="json") for blocker in blockers],
        )
        self._write_task(record, updated)
        blocker = blockers[-1]
        self._event(
            EventType.TASK_BLOCKED,
            entity_id=task.id,
            payload={
                "blocker_id": blocker.id,
                "reason": blocker.description,
                "created_at": blocker.created_at.isoformat(),
                "blocking_task_id": blocker.task_id,
            },
        )
        return updated

    def resolve_blocker(
        self,
        task_id: str,
        blocker_id: str,
        *,
        note: str,
    ) -> Task:
        if not note.strip():
            raise InvalidTransitionError("Resolving a blocker requires a note")
        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            matches = [blocker for blocker in task.blockers if blocker.id == blocker_id]
            if not matches:
                raise EntityNotFoundError(f"No blocker {blocker_id!r} on {task.id}")
            blocker = matches[0]
            if blocker.resolved_at is not None:
                return task
            resolved_at = utc_now()
            blockers = [
                item.model_copy(
                    update={
                        "resolved_at": resolved_at,
                        "resolution_note": note.strip(),
                    }
                )
                if item.id == blocker.id
                else item
                for item in task.blockers
            ]
            updated = self._evolve_task(
                task,
                blockers=[item.model_dump(mode="json", exclude_none=True) for item in blockers],
            )
            self._write_task(record, updated)
            self._event(
                EventType.TASK_UNBLOCKED,
                entity_id=task.id,
                payload={
                    "blocker_id": blocker.id,
                    "note": note.strip(),
                    "resolved_at": resolved_at.isoformat(),
                },
            )
            return updated

    def ready_task(self, task_id: str) -> Task:
        """Return a waiting, blocked, or scheduled task to actionable state."""

        with self.workspace.lock():
            record = self._task_record(task_id)
            task = record.entity
            if task.status not in {
                TaskStatus.WAITING,
                TaskStatus.BLOCKED,
                TaskStatus.SCHEDULED,
            }:
                raise InvalidTransitionError(
                    f"Cannot make {task.id} ready while it is {task.status.value}"
                )
            previous_status = task.status
            resolved_at = utc_now()
            resolved_blocker_ids: list[str] = []
            resolved_waiting_id: str | None = None
            if previous_status is TaskStatus.BLOCKED:
                resolved_blocker_ids = [
                    blocker.id for blocker in task.blockers if blocker.resolved_at is None
                ]
                blockers = [
                    blocker.model_copy(
                        update={
                            "resolved_at": blocker.resolved_at or resolved_at,
                            "resolution_note": (blocker.resolution_note or "Made ready manually"),
                        }
                    )
                    for blocker in task.blockers
                ]
                updated = self._evolve_task(
                    task,
                    blockers=[blocker.model_dump(mode="json") for blocker in blockers],
                )
            elif previous_status is TaskStatus.WAITING:
                if task.waiting is None:
                    raise InvalidTransitionError(f"Task {task.id} has no waiting detail")
                resolved_waiting_id = task.waiting.id
                resolved_waiting = self._evolve_waiting(
                    task.waiting,
                    resolved_at=resolved_at,
                    resolution_note="Made ready manually",
                )
                updated = self._evolve_task(
                    task,
                    disposition=TaskDisposition.NEXT,
                    waiting=None,
                    waiting_history=[
                        *(
                            item.model_dump(mode="json", exclude_none=True)
                            for item in task.waiting_history
                        ),
                        resolved_waiting.model_dump(mode="json", exclude_none=True),
                    ],
                )
            else:
                schedule = task.schedule.model_copy(update={"scheduled_for": None})
                updated = self._evolve_task(
                    task,
                    disposition=TaskDisposition.NEXT,
                    schedule=schedule.model_dump(mode="json", exclude_none=True),
                )
            self._write_task(record, updated)
            for resolved_blocker_id in resolved_blocker_ids:
                self._event(
                    EventType.TASK_UNBLOCKED,
                    entity_id=task.id,
                    payload={
                        "blocker_id": resolved_blocker_id,
                        "note": "Made ready manually",
                    },
                )
            if resolved_waiting_id is not None:
                self._event(
                    EventType.TASK_WAITING_RESOLVED,
                    entity_id=task.id,
                    payload={
                        "waiting_id": resolved_waiting_id,
                        "manual_ready": True,
                        "outcome": "Made ready manually",
                    },
                )
            self._event(
                EventType.TASK_READY,
                entity_id=updated.id,
                payload={"from_status": previous_status.value},
            )
            return updated

    def complete_project(self, project_id: str) -> GtdProject:
        """Close an outcome only after it has no unfinished actions."""

        with self.workspace.lock():
            record = self._project_record(project_id)
            project = record.entity
            if project.status is ProjectStatus.DONE:
                return project
            open_actions = [
                task
                for task in self.list_tasks()
                if task.project_id == project.id and task.status in OPEN_TASK_STATUSES
            ]
            if open_actions:
                ids = ", ".join(task.id for task in open_actions[:5])
                raise InvalidTransitionError(f"Project {project.id} still has open actions: {ids}")
            project.status = ProjectStatus.DONE
            project.updated_at = utc_now()
            self._write_project(record, project)
            self._event(EventType.PROJECT_COMPLETED, entity_id=project.id)
            return project

    def _project_needs_action(self, project_id: str | None) -> bool:
        if project_id is None:
            return False
        try:
            project = self._project_record(project_id).entity
        except EntityNotFoundError:
            return True
        if project.status is not ProjectStatus.ACTIVE:
            return False
        return not any(
            task.project_id == project_id and task.status in OPEN_TASK_STATUSES
            for task in self.list_tasks()
        )

    def _weekly_review_record(
        self,
        review_id: str,
    ) -> EntityRecord[WeeklyReviewSession]:
        return cast(
            EntityRecord[WeeklyReviewSession],
            self.workspace.find_record(review_id, kinds={"weekly_review"}),
        )

    def _active_weekly_review(self) -> WeeklyReviewSession | None:
        active = [
            cast(WeeklyReviewSession, record.entity)
            for record in self.workspace.list_records("weekly_review")
            if cast(WeeklyReviewSession, record.entity).completed_at is None
        ]
        if len(active) > 1:
            raise InvalidDocumentError("Multiple unfinished weekly reviews exist; run `ws doctor`")
        return active[0] if active else None

    @staticmethod
    def _weekly_review_body() -> str:
        return (
            "# Weekly review\n\n"
            "Check each step only after consciously reviewing its queue. "
            "Attention items do not need to be empty before the review can finish.\n"
        )

    def start_weekly_review(self) -> WeeklyReviewSession:
        """Start or resume the single durable weekly-review session."""

        with self.workspace.lock():
            active = self._active_weekly_review()
            if active is not None:
                return active
            session = WeeklyReviewSession(id=_new_id("REVIEW"))
            self.workspace.write(session, self._weekly_review_body())
            self._event(
                EventType.REVIEW_STARTED,
                entity_id=session.id,
                payload={"kind": "weekly"},
            )
            return session

    def check_weekly_review_step(
        self,
        review_id: str,
        step: WeeklyReviewStep | str,
        *,
        checked: bool = True,
    ) -> WeeklyReviewSession:
        """Mark one review queue checked, preserving the resumable session."""

        try:
            requested = WeeklyReviewStep(step)
        except ValueError as exc:
            raise InvalidTransitionError(f"Unknown weekly review step: {step}") from exc
        with self.workspace.lock():
            record = self._weekly_review_record(review_id)
            session = record.entity
            if session.completed_at is not None:
                raise InvalidTransitionError(f"Weekly review {session.id} is already complete")
            current = next(state for state in session.steps if state.step is requested)
            target_checked_at = utc_now() if checked else None
            if (current.checked_at is not None) is checked:
                return session
            steps = [
                ReviewStepState(
                    step=state.step,
                    checked_at=target_checked_at if state.step is requested else state.checked_at,
                )
                for state in session.steps
            ]
            updated = WeeklyReviewSession.model_validate(
                {
                    **session.model_dump(mode="json", exclude_none=True),
                    "revision": session.revision + 1,
                    "steps": [state.model_dump(mode="json", exclude_none=True) for state in steps],
                }
            )
            self.workspace.write(updated, record.body)
            self._event(
                EventType.REVIEW_STEP_CHECKED,
                entity_id=session.id,
                payload={"step": requested.value, "checked": checked},
            )
            return updated

    def complete_weekly_review(self, review_id: str) -> WeeklyReviewSession:
        """Complete a review only after every queue was consciously checked."""

        with self.workspace.lock():
            record = self._weekly_review_record(review_id)
            session = record.entity
            if session.completed_at is not None:
                return session
            unchecked = [state.step.value for state in session.steps if state.checked_at is None]
            if unchecked:
                raise InvalidTransitionError(
                    "Weekly review has unchecked steps: " + ", ".join(unchecked)
                )
            now = utc_now()
            updated = WeeklyReviewSession.model_validate(
                {
                    **session.model_dump(mode="json", exclude_none=True),
                    "revision": session.revision + 1,
                    "completed_at": now,
                }
            )
            self.workspace.write(updated, record.body)
            for project_record in self.workspace.list_records("gtd_project"):
                project = cast(GtdProject, project_record.entity)
                if project.status is ProjectStatus.ACTIVE:
                    project.last_reviewed_at = now
                    project.updated_at = now
                    self.workspace.write(project, project_record.body)
            report = self.weekly_review(review_id=session.id)
            self._event(
                EventType.REVIEW_COMPLETED,
                entity_id=session.id,
                payload={"kind": "weekly", "attention_count": report.attention_count},
            )
            return updated

    def weekly_review(self, review_id: str | None = None) -> ReviewReport:
        now = utc_now()
        settings = self.workspace.settings()
        today = now.astimezone(ZoneInfo(settings.timezone)).date()
        session = (
            self._weekly_review_record(review_id).entity
            if review_id is not None
            else self._active_weekly_review()
        )
        inbox = [
            ReviewItem(
                id=item.id,
                title=item.title,
                reason="unclarified inbox item",
                age_days=_age_days(item.captured_at, now),
            )
            for item in self.list_inbox()
        ]
        tasks = self.list_tasks()
        waiting = [
            ReviewItem(
                id=task.id,
                title=task.title,
                reason=(
                    f"follow up with {task.waiting_for}"
                    if task.follow_up_on is None or task.follow_up_on <= today
                    else f"waiting for {task.waiting_for} until {task.follow_up_on}"
                ),
                age_days=_age_days(task.updated_at, now),
            )
            for task in tasks
            if task.lifecycle is TaskLifecycle.OPEN and task.disposition is TaskDisposition.WAITING
        ]
        blocked = [
            ReviewItem(
                id=task.id,
                title=task.title,
                reason=task.blocked_reason or "blocked",
                age_days=_age_days(task.updated_at, now),
            )
            for task in tasks
            if task.status is TaskStatus.BLOCKED
        ]
        stale = [
            ReviewItem(
                id=task.id,
                title=task.title,
                reason="next action has not changed recently",
                age_days=_age_days(task.updated_at, now),
            )
            for task in tasks
            if task.status is TaskStatus.NEXT
            and _age_days(task.updated_at, now) >= settings.stale_after_days
        ]
        projects_without_action = [
            ReviewItem(
                id=project.id,
                title=project.title,
                reason="active project has no open next action",
                age_days=_age_days(project.updated_at, now),
            )
            for project in self.list_projects({ProjectStatus.ACTIVE})
            if self._project_needs_action(project.id)
        ]
        scheduled = [
            ReviewItem(
                id=task.id,
                title=task.title,
                reason=f"scheduled for {task.scheduled_for}",
                age_days=None,
            )
            for task in tasks
            if task.lifecycle is TaskLifecycle.OPEN and task.disposition is TaskDisposition.CALENDAR
        ]
        current = self.current_task()
        current_ref = None
        if current is not None:
            current_ref = self._entity_ref(current)
        someday_count = len(self.workspace.list_records("someday"))
        checklist_counts = {
            WeeklyReviewStep.INBOX_ZERO: len(inbox),
            WeeklyReviewStep.CALENDAR_REVIEWED: len(scheduled),
            WeeklyReviewStep.WAITING_REVIEWED: len(waiting),
            WeeklyReviewStep.PROJECTS_REVIEWED: len(projects_without_action),
            WeeklyReviewStep.SOMEDAY_REVIEWED: someday_count,
        }
        checked_at_by_step = (
            {state.step: state.checked_at for state in session.steps} if session else {}
        )
        checklist = [
            ReviewChecklistItem(
                key=step.value,
                label=WEEKLY_REVIEW_LABELS[step],
                complete=(
                    checked_at_by_step.get(step) is not None if session is not None else count == 0
                ),
                count=count,
                checked_at=checked_at_by_step.get(step),
            )
            for step, count in checklist_counts.items()
        ]
        return ReviewReport(
            current_task=current_ref,
            inbox=inbox,
            waiting_followups=waiting,
            blocked=blocked,
            stale_actions=stale,
            projects_without_next_action=projects_without_action,
            scheduled=scheduled,
            someday_count=someday_count,
            checklist=checklist,
            session_id=session.id if session else None,
            session_started_at=session.started_at if session else None,
        )

    def record_review(self, kind: str = "weekly") -> ReviewReport:
        if kind != "weekly":
            raise InvalidTransitionError(f"Unsupported review kind: {kind}")
        session = self.start_weekly_review()
        for state in session.steps:
            if state.checked_at is None:
                session = self.check_weekly_review_step(session.id, state.step)
        self.complete_weekly_review(session.id)
        return self.weekly_review(review_id=session.id)

    def validate(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        counts: dict[str, int] = {}
        records: list[Any] = []
        seen_ids: dict[str, str] = {}

        for spec in self.workspace.registry.specs:
            directory = self.workspace.root / spec.directory
            for path in sorted(directory.glob("*.md")):
                try:
                    record = self.workspace.read(path, expected_kind=spec.kind)
                except InvalidDocumentError as exc:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="invalid_document",
                            message=str(exc),
                            path=self.workspace.relative(path),
                        )
                    )
                    continue
                records.append(record)
                entity = record.entity
                counts[entity.kind] = counts.get(entity.kind, 0) + 1
                previous = seen_ids.get(entity.id)
                if previous is not None:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="duplicate_id",
                            message=f"{entity.id} also exists at {previous}",
                            path=self.workspace.relative(path),
                            entity_id=entity.id,
                        )
                    )
                else:
                    seen_ids[entity.id] = self.workspace.relative(path)

        tasks = [record.entity for record in records if isinstance(record.entity, Task)]
        task_by_id = {task.id: task for task in tasks}
        projects = {
            record.entity.id: record.entity
            for record in records
            if isinstance(record.entity, GtdProject)
        }
        doing = [task for task in tasks if task.status is TaskStatus.DOING]
        if len(doing) > self.workspace.settings().wip_limit:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="wip_limit",
                    message=f"{len(doing)} tasks are doing; limit is 1",
                )
            )
        for task in tasks:
            task_path = self.workspace.relative(self.workspace.path_for(task))
            if task.project_id and task.project_id not in projects:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_project",
                        message=f"Task references missing project {task.project_id}",
                        entity_id=task.id,
                        path=task_path,
                    )
                )
            if task.parent_id and task.parent_id not in task_by_id:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_task_parent",
                        message=f"Task references missing parent {task.parent_id}",
                        entity_id=task.id,
                        path=task_path,
                    )
                )
            elif task.parent_id:
                cursor = task
                ancestors: set[str] = set()
                while cursor.parent_id and cursor.parent_id in task_by_id:
                    if cursor.parent_id == task.id or cursor.parent_id in ancestors:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="task_parent_cycle",
                                message=f"Task parent hierarchy containing {task.id} is cyclic",
                                entity_id=task.id,
                                path=task_path,
                            )
                        )
                        break
                    ancestors.add(cursor.parent_id)
                    cursor = task_by_id[cursor.parent_id]
            for relation in task.relations:
                if relation.target_id == task.id:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="self_task_relation",
                            message=f"Task has a self relation of type {relation.type.value}",
                            entity_id=task.id,
                            path=task_path,
                        )
                    )
                elif relation.target_id not in task_by_id:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="missing_task_relation",
                            message=(
                                f"Task relation {relation.type.value} references missing "
                                f"task {relation.target_id}"
                            ),
                            entity_id=task.id,
                            path=task_path,
                        )
                    )
            if task.work_logs:
                logged_minutes = round(sum(log.minutes for log in task.work_logs), 2)
                if abs(logged_minutes - task.actual_minutes) > 0.01:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="work_log_projection_mismatch",
                            message=(
                                f"actual_minutes={task.actual_minutes} but work logs "
                                f"sum to {logged_minutes}"
                            ),
                            entity_id=task.id,
                            path=task_path,
                        )
                    )
            if (
                task.rigor is TaskRigor.ASSURED
                and task.completion.assurance_reviewed_at is not None
                and task.completion.assurance_review_hash != task.assurance_input_hash()
                and not task.completion.assurance_grandfathered
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="stale_assurance_review",
                        message="Assurance review does not match current constraints/assumptions",
                        entity_id=task.id,
                        path=task_path,
                    )
                )
            if task.status is TaskStatus.DONE and task.remaining_estimate_minutes not in {
                None,
                0,
            }:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="completed_task_has_remaining_estimate",
                        message="Completed task retains a non-zero remaining estimate",
                        entity_id=task.id,
                        path=task_path,
                    )
                )

        dependency_graph: dict[str, set[str]] = {task.id: set() for task in tasks}
        for task in tasks:
            for relation in task.relations:
                if relation.target_id not in task_by_id:
                    continue
                if relation.type is RelationType.BLOCKS:
                    dependency_graph[task.id].add(relation.target_id)
                elif relation.type is RelationType.DEPENDS_ON:
                    dependency_graph[relation.target_id].add(task.id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def has_cycle(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            cyclic = any(has_cycle(target) for target in dependency_graph[node])
            visiting.remove(node)
            visited.add(node)
            return cyclic

        if any(has_cycle(task_id) for task_id in dependency_graph):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="task_dependency_cycle",
                    message="Task dependency graph contains a cycle",
                )
            )
        for project in projects.values():
            if project.status is ProjectStatus.ACTIVE and not any(
                task.project_id == project.id and task.status in OPEN_TASK_STATUSES
                for task in tasks
            ):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="project_without_next_action",
                        message="Active project has no open next action",
                        entity_id=project.id,
                        path=self.workspace.relative(self.workspace.path_for(project)),
                    )
                )
        try:
            self.events.read_all()
        except ValueError as exc:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_event_log",
                    message=str(exc),
                    path=self.workspace.relative(self.events.path),
                )
            )
        return ValidationReport(issues=issues, counts=counts)

    def metrics(self, *, as_of: datetime | None = None) -> MetricsReport:
        return project_metrics(
            self.list_tasks(),
            self.events.read_all(),
            as_of=as_of,
        )
