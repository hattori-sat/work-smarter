"""Application service for independent, Markdown-authoritative managed projects."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from work_smarter.errors import EntityNotFoundError, InvalidDocumentError
from work_smarter.project_management.errors import (
    ProjectCompletionGateError,
    ProjectConflictError,
    ProjectItemNotFoundError,
    ProjectLinkError,
    ProjectScheduleError,
    ProjectTransitionError,
)
from work_smarter.project_management.events import (
    BASELINE_CREATED,
    CHANGE_REQUEST_ADDED,
    CHANGE_REQUEST_UPDATED,
    COMPLETION_CRITERION_UPDATED,
    EVIDENCE_RECORDED,
    GATE_REVIEW_RECORDED,
    MILESTONE_ADDED,
    MILESTONE_TRANSITIONED,
    MILESTONE_UPDATED,
    PHASE_ADDED,
    PHASE_TRANSITIONED,
    PHASE_UPDATED,
    PROJECT_CREATED,
    PROJECT_TRANSITIONED,
    PROJECT_UPDATED,
    REGISTER_ITEM_ADDED,
    REGISTER_ITEM_UPDATED,
    REQUIREMENT_ADDED,
    REQUIREMENT_UPDATED,
    VERIFICATION_RECORDED,
    WORK_PACKAGE_ADDED,
    WORK_PACKAGE_TRANSITIONED,
    WORK_PACKAGE_UPDATED,
)
from work_smarter.project_management.models import (
    Assumption,
    BaselineRecord,
    BaselineScheduleItem,
    ChangeKind,
    ChangeRequest,
    ChangeStatus,
    CompletionCriterion,
    CompletionCriterionStatus,
    Constraint,
    DependencyType,
    EvidenceRecord,
    GateDecision,
    GateReview,
    Health,
    ManagedProject,
    ManagedProjectDocument,
    Milestone,
    MilestoneStatus,
    Phase,
    ProjectDoctorIssue,
    ProjectDoctorReport,
    ProjectLifecycle,
    QcdPlan,
    QcdProjection,
    RegisterItem,
    RegisterItemKind,
    RegisterItemStatus,
    Requirement,
    RequirementKind,
    RequirementStatus,
    ScheduleDependency,
    ScheduleExplanation,
    ScheduleItem,
    ScheduleProjection,
    VerificationActivity,
    VerificationMethod,
    VerificationRecord,
    VerificationResult,
    WorkingCalendar,
    WorkPackage,
    WorkStatus,
    utc_now,
)
from work_smarter.project_management.templates import render_managed_project_template
from work_smarter.storage.events import Event, EventStore
from work_smarter.storage.workspace import EntityRecord, Workspace


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _body(value: str) -> str:
    cleaned = value.strip("\n").rstrip()
    return cleaned + "\n" if cleaned.strip() else ""


class _CalendarAxis:
    """Map project-local working dates to integer scheduling boundaries."""

    def __init__(self, calendar: WorkingCalendar, anchor: date):
        self.calendar = calendar
        self.anchor = self.on_or_after(anchor)
        self._dates: list[date] = [self.anchor]

    def on_or_after(self, value: date) -> date:
        current = value
        for _ in range(3700):
            if self.calendar.is_working_day(current):
                return current
            current += timedelta(days=1)
        raise ProjectScheduleError("working calendar has no reachable working day")

    def date_for_tick(self, tick: int) -> date:
        if tick < 0:
            raise ProjectScheduleError("schedule lead resolves before the project anchor")
        while len(self._dates) <= tick:
            candidate = self._dates[-1] + timedelta(days=1)
            self._dates.append(self.on_or_after(candidate))
        return self._dates[tick]

    def tick_for_date(self, value: date) -> int:
        target = self.on_or_after(value)
        if target < self.anchor:
            raise ProjectScheduleError("date constraint precedes the project anchor")
        tick = 0
        while self.date_for_tick(tick) < target:
            tick += 1
        return tick

    def non_working_between(self, start: date, finish: date) -> list[date]:
        values: list[date] = []
        current = start
        while current <= finish:
            if not self.calendar.is_working_day(current):
                values.append(current)
            current += timedelta(days=1)
        return values


PROJECT_TRANSITIONS: dict[ProjectLifecycle, set[ProjectLifecycle]] = {
    ProjectLifecycle.PROPOSED: {ProjectLifecycle.PLANNED, ProjectLifecycle.CANCELLED},
    ProjectLifecycle.PLANNED: {
        ProjectLifecycle.ACTIVE,
        ProjectLifecycle.ON_HOLD,
        ProjectLifecycle.CANCELLED,
    },
    ProjectLifecycle.ACTIVE: {
        ProjectLifecycle.ON_HOLD,
        ProjectLifecycle.COMPLETED,
        ProjectLifecycle.CANCELLED,
    },
    ProjectLifecycle.ON_HOLD: {
        ProjectLifecycle.PLANNED,
        ProjectLifecycle.ACTIVE,
        ProjectLifecycle.CANCELLED,
    },
    ProjectLifecycle.COMPLETED: set(),
    ProjectLifecycle.CANCELLED: set(),
}

WORK_TRANSITIONS: dict[WorkStatus, set[WorkStatus]] = {
    WorkStatus.PLANNED: {WorkStatus.READY, WorkStatus.CANCELLED},
    WorkStatus.READY: {
        WorkStatus.IN_PROGRESS,
        WorkStatus.BLOCKED,
        WorkStatus.CANCELLED,
    },
    WorkStatus.IN_PROGRESS: {
        WorkStatus.BLOCKED,
        WorkStatus.COMPLETED,
        WorkStatus.CANCELLED,
    },
    WorkStatus.BLOCKED: {
        WorkStatus.READY,
        WorkStatus.IN_PROGRESS,
        WorkStatus.CANCELLED,
    },
    WorkStatus.COMPLETED: set(),
    WorkStatus.CANCELLED: set(),
}

MILESTONE_TRANSITIONS: dict[MilestoneStatus, set[MilestoneStatus]] = {
    MilestoneStatus.PLANNED: {MilestoneStatus.ACHIEVED, MilestoneStatus.CANCELLED},
    MilestoneStatus.ACHIEVED: set(),
    MilestoneStatus.CANCELLED: set(),
}


class ProjectManagementService:
    """The only supported writer for one embedded managed-project aggregate."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.events: EventStore = workspace.event_store
        try:
            workspace.registry.require("managed_project")
        except ValueError as exc:
            raise InvalidDocumentError(
                "Workspace does not have the managed_project entity codec registered"
            ) from exc

    def _event(
        self,
        event_type: str,
        project_id: str,
        payload: dict[str, object] | None = None,
        *,
        event_id: str | None = None,
    ) -> Event:
        return self.events.append(
            Event(
                id=event_id or _new_id("PEVT"),
                type=event_type,
                entity_id=project_id,
                payload=payload or {},
            )
        )

    def _records(self) -> list[EntityRecord[BaseModel]]:
        return self.workspace.list_records("managed_project")

    def _record(self, query: str) -> EntityRecord[BaseModel]:
        return self.workspace.find_record(query, kinds={"managed_project"})

    def _document(self, record: EntityRecord[BaseModel]) -> ManagedProjectDocument:
        return ManagedProjectDocument(
            project=cast(ManagedProject, record.entity),
            body=_body(record.body),
            path=self.workspace.relative(record.path),
        )

    @staticmethod
    def _validated(project: ManagedProject, **changes: object) -> ManagedProject:
        data = project.model_dump(mode="json", exclude_computed_fields=True)
        data.update(changes)
        return ManagedProject.model_validate(data)

    def _commit(
        self,
        record: EntityRecord[BaseModel],
        candidate: ManagedProject,
        *,
        event_type: str,
        body: str | None = None,
        payload: dict[str, object] | None = None,
        audit_event_id: str | None = None,
    ) -> ManagedProjectDocument:
        existing = cast(ManagedProject, record.entity)
        updated = self._validated(
            candidate,
            revision=existing.revision + 1,
            created_at=existing.created_at,
            updated_at=utc_now(),
        )
        self._validate_aggregate(updated)
        written = self.workspace.write(updated, record.body if body is None else _body(body))
        self._event(
            event_type,
            updated.id,
            {"revision": updated.revision, **(payload or {})},
            event_id=audit_event_id,
        )
        return self._document(written)

    def _canonical_gtd_action_ids(self, queries: Iterable[str]) -> list[str]:
        canonical: list[str] = []
        seen: set[str] = set()
        for query in queries:
            try:
                record = self.workspace.find_record(query)
            except EntityNotFoundError as exc:
                raise ProjectLinkError(f"GTD action {query!r} does not exist") from exc
            kind = str(getattr(record.entity, "kind", ""))
            if kind != "task":
                raise ProjectLinkError(f"GTD action {query!r} points to {kind!r}, not a task")
            entity_id = str(record.entity.id)
            key = entity_id.casefold()
            if key not in seen:
                canonical.append(entity_id)
                seen.add(key)
        return canonical

    def _validate_gtd_action_ids(self, project: ManagedProject) -> None:
        records_by_id: dict[str, list[BaseModel]] = defaultdict(list)
        for record in self.workspace.all_records(include_archive=True):
            entity_id = str(getattr(record.entity, "id", ""))
            if entity_id:
                records_by_id[entity_id.casefold()].append(record.entity)
        links = [*project.gtd_action_ids]
        for work_package in project.work_packages:
            links.extend(work_package.gtd_action_ids)
        for entity_id in links:
            matches = records_by_id.get(entity_id.casefold(), [])
            if not matches:
                raise ProjectLinkError(f"GTD action {entity_id!r} does not exist")
            if len(matches) != 1:
                raise ProjectLinkError(f"GTD action {entity_id!r} is ambiguous")
            if str(getattr(matches[0], "kind", "")) != "task":
                raise ProjectLinkError(f"GTD action {entity_id!r} is not a task")

    @staticmethod
    def _all_criteria(project: ManagedProject) -> list[CompletionCriterion]:
        criteria = list(project.completion_criteria)
        for phase in project.phases:
            criteria.extend(phase.completion_criteria)
        for work_package in project.work_packages:
            criteria.extend(work_package.completion_criteria)
        for milestone in project.milestones:
            criteria.extend(milestone.completion_criteria)
        return criteria

    def _validate_aggregate(self, project: ManagedProject) -> None:
        phase_ids = [phase.id.casefold() for phase in project.phases]
        for item in [*project.work_packages, *project.milestones]:
            if item.phase_id is not None and not any(
                phase_id.startswith(item.phase_id.casefold()) for phase_id in phase_ids
            ):
                raise ProjectConflictError(f"{item.id} references missing phase {item.phase_id!r}")

        evidence_ids = {item.id.casefold() for item in project.evidence}
        for criterion in self._all_criteria(project):
            for evidence_id in criterion.evidence_ids:
                if evidence_id.casefold() not in evidence_ids:
                    raise ProjectConflictError(
                        f"criterion {criterion.id} references missing evidence {evidence_id!r}"
                    )
        requirement_ids = {item.id.casefold(): item.id for item in project.requirements}
        for requirement in project.requirements:
            if (
                requirement.parent_id is not None
                and requirement.parent_id.casefold() not in requirement_ids
            ):
                raise ProjectLinkError(
                    f"requirement {requirement.id} references missing parent requirement "
                    f"{requirement.parent_id!r}"
                )
        for verification in project.verification_records:
            for requirement_id in verification.requirement_ids:
                if requirement_id.casefold() not in requirement_ids:
                    raise ProjectLinkError(
                        f"V&V record {verification.id} references missing requirement "
                        f"{requirement_id!r}"
                    )
            for evidence_id in verification.evidence_ids:
                if evidence_id.casefold() not in evidence_ids:
                    raise ProjectLinkError(
                        f"V&V record {verification.id} references missing evidence {evidence_id!r}"
                    )
        criterion_ids = {item.id.casefold() for item in self._all_criteria(project)}
        for gate in project.gate_reviews:
            for criterion_id in gate.criterion_ids:
                if criterion_id.casefold() not in criterion_ids:
                    raise ProjectLinkError(
                        f"gate review {gate.id} references missing completion criterion "
                        f"{criterion_id!r}"
                    )
            for evidence_id in gate.evidence_ids:
                if evidence_id.casefold() not in evidence_ids:
                    raise ProjectLinkError(
                        f"gate review {gate.id} references missing evidence {evidence_id!r}"
                    )
        internal_ids = self._internal_ids(project)
        for change in project.change_requests:
            for target_id in change.target_ids:
                if target_id.casefold() not in internal_ids:
                    raise ProjectLinkError(
                        f"change request {change.id} references missing target {target_id!r}"
                    )
        self._compute_schedule(project)
        self._validate_gtd_action_ids(project)

    @staticmethod
    def _internal_ids(project: ManagedProject) -> set[str]:
        ids = {project.id.casefold()}
        for collection in (
            project.constraints,
            project.assumptions,
            project.completion_criteria,
            project.stakeholders,
            project.phases,
            project.work_packages,
            project.milestones,
            project.register_items,
            project.evidence,
            project.requirements,
            project.verification_records,
            project.gate_reviews,
            project.change_requests,
            project.baselines,
        ):
            ids.update(item.id.casefold() for item in collection)
        for item in [*project.phases, *project.work_packages, *project.milestones]:
            ids.update(criterion.id.casefold() for criterion in item.completion_criteria)
        return ids

    @staticmethod
    def _criterion(
        value: CompletionCriterion | str,
        *,
        prefix: str = "CR",
    ) -> CompletionCriterion:
        if isinstance(value, CompletionCriterion):
            return value
        return CompletionCriterion(id=_new_id(prefix), description=value)

    @staticmethod
    def _constraint(value: Constraint | str) -> Constraint:
        if isinstance(value, Constraint):
            return value
        return Constraint(id=_new_id("CON"), statement=value)

    @staticmethod
    def _assumption(value: Assumption | str) -> Assumption:
        if isinstance(value, Assumption):
            return value
        return Assumption(id=_new_id("ASM"), statement=value)

    def create(
        self,
        *,
        title: str,
        goal: str,
        body: str | None = None,
        project_id: str | None = None,
        sponsor: str | None = None,
        manager: str | None = None,
        planned_start_on: date | None = None,
        target_due_on: date | None = None,
        working_calendar: WorkingCalendar | None = None,
        constraints: Iterable[Constraint | str] = (),
        assumptions: Iterable[Assumption | str] = (),
        completion_criteria: Iterable[CompletionCriterion | str] = (),
        qcd: QcdPlan | None = None,
        gtd_action_ids: Iterable[str] = (),
    ) -> ManagedProjectDocument:
        """Create one project and a conservative default completion gate if omitted."""

        with self.workspace.lock():
            identifier = project_id or _new_id("MP")
            try:
                self.workspace.find_record(identifier)
            except EntityNotFoundError:
                pass
            else:
                raise ProjectConflictError(f"Stable ID {identifier!r} is already in use")
            canonical_links = self._canonical_gtd_action_ids(gtd_action_ids)
            criteria = [self._criterion(value) for value in completion_criteria]
            if not criteria:
                criteria = [
                    CompletionCriterion(
                        id=_new_id("CR"),
                        description=f"Project goal achieved: {goal.strip()}",
                    )
                ]
            now = utc_now()
            project = ManagedProject(
                id=identifier,
                title=title,
                goal=goal,
                sponsor=sponsor,
                manager=manager,
                planned_start_on=planned_start_on,
                target_due_on=target_due_on,
                working_calendar=working_calendar or WorkingCalendar(),
                constraints=[self._constraint(value) for value in constraints],
                assumptions=[self._assumption(value) for value in assumptions],
                completion_criteria=criteria,
                qcd=qcd or QcdPlan(),
                gtd_action_ids=canonical_links,
                created_at=now,
                updated_at=now,
            )
            self._validate_aggregate(project)
            rendered = (
                render_managed_project_template(self.workspace, title=project.title)
                if body is None
                else body
            )
            record = self.workspace.write(project, _body(rendered))
            self._event(PROJECT_CREATED, project.id, {"revision": 1})
            return self._document(record)

    def get(self, query: str) -> ManagedProjectDocument:
        return self._document(self._record(query))

    def list(
        self, *, lifecycles: Iterable[ProjectLifecycle | str] | None = None
    ) -> list[ManagedProjectDocument]:
        requested = (
            {ProjectLifecycle(item) for item in lifecycles} if lifecycles is not None else None
        )
        return [
            self._document(record)
            for record in self._records()
            if requested is None or cast(ManagedProject, record.entity).lifecycle in requested
        ]

    def update(
        self,
        query: str,
        *,
        title: str | None = None,
        goal: str | None = None,
        body: str | None = None,
        sponsor: str | None = None,
        manager: str | None = None,
        planned_start_on: date | None = None,
        target_due_on: date | None = None,
        working_calendar: WorkingCalendar | None = None,
        qcd: QcdPlan | None = None,
        gtd_action_ids: Iterable[str] | None = None,
    ) -> ManagedProjectDocument:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            changes: dict[str, object] = {}
            for name, value in (
                ("title", title),
                ("goal", goal),
                ("sponsor", sponsor),
                ("manager", manager),
                ("planned_start_on", planned_start_on),
                ("target_due_on", target_due_on),
                ("working_calendar", working_calendar),
                ("qcd", qcd),
            ):
                if value is not None:
                    changes[name] = value
            if gtd_action_ids is not None:
                changes["gtd_action_ids"] = self._canonical_gtd_action_ids(gtd_action_ids)
            if not changes and body is None:
                return self._document(record)
            candidate = self._validated(project, **changes)
            return self._commit(
                record,
                candidate,
                event_type=PROJECT_UPDATED,
                body=body,
                payload={
                    "changed_fields": sorted([*changes, *(("body",) if body is not None else ())])
                },
            )

    def transition_project(
        self,
        query: str,
        lifecycle: ProjectLifecycle | str,
    ) -> ManagedProjectDocument:
        target = ProjectLifecycle(lifecycle)
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            if target not in PROJECT_TRANSITIONS[project.lifecycle]:
                raise ProjectTransitionError(
                    f"Cannot transition project from {project.lifecycle.value} to {target.value}"
                )
            if target is ProjectLifecycle.COMPLETED:
                self._assert_project_complete(project)
            candidate = self._validated(project, lifecycle=target)
            return self._commit(
                record,
                candidate,
                event_type=PROJECT_TRANSITIONED,
                payload={"from": project.lifecycle.value, "to": target.value},
            )

    @staticmethod
    def _find(items: Iterable[BaseModel], item_id: str, label: str) -> tuple[int, BaseModel]:
        normalized = item_id.casefold()
        matches = [
            (index, item)
            for index, item in enumerate(items)
            if str(getattr(item, "id", "")).casefold().startswith(normalized)
        ]
        exact = [item for item in matches if str(item[1].id).casefold() == normalized]
        selected = exact or matches
        if not selected:
            raise ProjectItemNotFoundError(f"No {label} matches {item_id!r}")
        if len(selected) > 1:
            ids = ", ".join(str(item.id) for _, item in selected[:5])
            raise ProjectConflictError(f"{item_id!r} matches multiple {label}s: {ids}")
        return selected[0]

    @staticmethod
    def _replace(
        project: ManagedProject, field: str, index: int, item: BaseModel
    ) -> ManagedProject:
        values = list(getattr(project, field))
        values[index] = item
        return ProjectManagementService._validated(project, **{field: values})

    def add_phase(
        self,
        query: str,
        *,
        title: str,
        phase_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        start_on: date | None = None,
        due_on: date | None = None,
        completion_criteria: Iterable[CompletionCriterion | str] = (),
    ) -> Phase:
        phase = Phase(
            id=phase_id or _new_id("PH"),
            title=title,
            description=description,
            owner=owner,
            start_on=start_on,
            due_on=due_on,
            completion_criteria=[self._criterion(value) for value in completion_criteria],
        )
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            candidate = self._validated(project, phases=[*project.phases, phase])
            self._commit(
                record,
                candidate,
                event_type=PHASE_ADDED,
                payload={"phase_id": phase.id},
            )
        return phase

    def update_phase(
        self,
        query: str,
        phase_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        start_on: date | None = None,
        due_on: date | None = None,
        completion_criteria: Iterable[CompletionCriterion] | None = None,
    ) -> Phase:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.phases, phase_id, "phase")
            phase = cast(Phase, raw)
            changes = {
                name: value
                for name, value in (
                    ("title", title),
                    ("description", description),
                    ("owner", owner),
                    ("start_on", start_on),
                    ("due_on", due_on),
                    (
                        "completion_criteria",
                        list(completion_criteria) if completion_criteria is not None else None,
                    ),
                )
                if value is not None
            }
            updated = Phase.model_validate(
                {**phase.model_dump(mode="json", exclude_computed_fields=True), **changes}
            )
            candidate = self._replace(project, "phases", index, updated)
            self._commit(
                record,
                candidate,
                event_type=PHASE_UPDATED,
                payload={"phase_id": phase.id, "changed_fields": sorted(changes)},
            )
            return updated

    def add_work_package(
        self,
        query: str,
        *,
        title: str,
        duration_days: int,
        work_package_id: str | None = None,
        phase_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        dependency_ids: Iterable[str] = (),
        dependencies: Iterable[ScheduleDependency] = (),
        start_on: date | None = None,
        due_on: date | None = None,
        progress_percent: int = 0,
        jira_status: str | None = None,
        completion_criteria: Iterable[CompletionCriterion | str] = (),
        gtd_action_ids: Iterable[str] = (),
    ) -> WorkPackage:
        criteria = [self._criterion(value) for value in completion_criteria]
        if not criteria:
            criteria = [
                CompletionCriterion(
                    id=_new_id("CR"),
                    description=f"Work package accepted: {title.strip()}",
                )
            ]
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            work_package = WorkPackage(
                id=work_package_id or _new_id("WP"),
                title=title,
                duration_days=duration_days,
                phase_id=phase_id,
                description=description,
                owner=owner,
                dependency_ids=list(dependency_ids),
                dependencies=list(dependencies),
                start_on=start_on,
                due_on=due_on,
                progress_percent=progress_percent,
                jira_status=jira_status,
                completion_criteria=criteria,
                gtd_action_ids=self._canonical_gtd_action_ids(gtd_action_ids),
            )
            candidate = self._validated(
                project, work_packages=[*project.work_packages, work_package]
            )
            self._commit(
                record,
                candidate,
                event_type=WORK_PACKAGE_ADDED,
                payload={"work_package_id": work_package.id},
            )
            return work_package

    def update_work_package(
        self,
        query: str,
        work_package_id: str,
        *,
        title: str | None = None,
        duration_days: int | None = None,
        phase_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        dependency_ids: Iterable[str] | None = None,
        dependencies: Iterable[ScheduleDependency] | None = None,
        start_on: date | None = None,
        due_on: date | None = None,
        progress_percent: int | None = None,
        jira_status: str | None = None,
        completion_criteria: Iterable[CompletionCriterion] | None = None,
        gtd_action_ids: Iterable[str] | None = None,
    ) -> WorkPackage:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.work_packages, work_package_id, "work package")
            item = cast(WorkPackage, raw)
            changes: dict[str, object] = {}
            for name, value in (
                ("title", title),
                ("duration_days", duration_days),
                ("phase_id", phase_id),
                ("description", description),
                ("owner", owner),
                ("start_on", start_on),
                ("due_on", due_on),
                ("progress_percent", progress_percent),
                ("jira_status", jira_status),
            ):
                if value is not None:
                    changes[name] = value
            if dependency_ids is not None:
                changes["dependency_ids"] = list(dependency_ids)
            if dependencies is not None:
                changes["dependencies"] = list(dependencies)
            if completion_criteria is not None:
                changes["completion_criteria"] = list(completion_criteria)
            if gtd_action_ids is not None:
                changes["gtd_action_ids"] = self._canonical_gtd_action_ids(gtd_action_ids)
            updated = WorkPackage.model_validate(
                {**item.model_dump(mode="json", exclude_computed_fields=True), **changes}
            )
            candidate = self._replace(project, "work_packages", index, updated)
            self._commit(
                record,
                candidate,
                event_type=WORK_PACKAGE_UPDATED,
                payload={"work_package_id": item.id, "changed_fields": sorted(changes)},
            )
            return updated

    def add_milestone(
        self,
        query: str,
        *,
        title: str,
        milestone_id: str | None = None,
        phase_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        dependency_ids: Iterable[str] = (),
        dependencies: Iterable[ScheduleDependency] = (),
        planned_on: date | None = None,
        due_on: date | None = None,
        completion_criteria: Iterable[CompletionCriterion | str] = (),
        jira_status: str | None = None,
    ) -> Milestone:
        milestone = Milestone(
            id=milestone_id or _new_id("MS"),
            title=title,
            phase_id=phase_id,
            description=description,
            owner=owner,
            dependency_ids=list(dependency_ids),
            dependencies=list(dependencies),
            planned_on=planned_on,
            due_on=due_on,
            completion_criteria=[self._criterion(value) for value in completion_criteria],
            jira_status=jira_status,
        )
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            candidate = self._validated(project, milestones=[*project.milestones, milestone])
            self._commit(
                record,
                candidate,
                event_type=MILESTONE_ADDED,
                payload={"milestone_id": milestone.id},
            )
        return milestone

    def update_milestone(
        self,
        query: str,
        milestone_id: str,
        *,
        title: str | None = None,
        phase_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        dependency_ids: Iterable[str] | None = None,
        dependencies: Iterable[ScheduleDependency] | None = None,
        planned_on: date | None = None,
        due_on: date | None = None,
        completion_criteria: Iterable[CompletionCriterion] | None = None,
        jira_status: str | None = None,
    ) -> Milestone:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.milestones, milestone_id, "milestone")
            item = cast(Milestone, raw)
            changes: dict[str, object] = {}
            for name, value in (
                ("title", title),
                ("phase_id", phase_id),
                ("description", description),
                ("owner", owner),
                ("planned_on", planned_on),
                ("due_on", due_on),
                ("jira_status", jira_status),
            ):
                if value is not None:
                    changes[name] = value
            if dependency_ids is not None:
                changes["dependency_ids"] = list(dependency_ids)
            if dependencies is not None:
                changes["dependencies"] = list(dependencies)
            if completion_criteria is not None:
                changes["completion_criteria"] = list(completion_criteria)
            updated = Milestone.model_validate(
                {**item.model_dump(mode="json", exclude_computed_fields=True), **changes}
            )
            candidate = self._replace(project, "milestones", index, updated)
            self._commit(
                record,
                candidate,
                event_type=MILESTONE_UPDATED,
                payload={"milestone_id": item.id, "changed_fields": sorted(changes)},
            )
            return updated

    def add_dependency(
        self,
        query: str,
        successor_id: str,
        predecessor_id: str,
        *,
        dependency_type: DependencyType | str = DependencyType.FINISH_TO_START,
        lag_days: int = 0,
    ) -> WorkPackage | Milestone:
        """Add or replace one typed precedence relation under the workspace lock."""

        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            collections: tuple[tuple[str, list[WorkPackage | Milestone], str], ...] = (
                (
                    "work_packages",
                    cast(list[WorkPackage | Milestone], project.work_packages),
                    "work package",
                ),
                (
                    "milestones",
                    cast(list[WorkPackage | Milestone], project.milestones),
                    "milestone",
                ),
            )
            for field, values, label in collections:
                matches = [
                    (index, item)
                    for index, item in enumerate(values)
                    if item.id.casefold().startswith(successor_id.casefold())
                ]
                if not matches:
                    continue
                if len(matches) != 1:
                    raise ProjectConflictError(f"{successor_id!r} matches multiple schedule items")
                index, item = matches[0]
                canonical_predecessor = self._canonical_internal_ids(
                    project,
                    [predecessor_id],
                    candidates=(node.id for node in [*project.work_packages, *project.milestones]),
                    label="schedule predecessor",
                )[0]
                dependency = ScheduleDependency(
                    predecessor_id=canonical_predecessor,
                    type=DependencyType(dependency_type),
                    lag_days=lag_days,
                )
                dependencies = [
                    existing
                    for existing in item.dependencies
                    if existing.predecessor_id.casefold() != canonical_predecessor.casefold()
                ]
                dependencies.append(dependency)
                legacy = [
                    value
                    for value in item.dependency_ids
                    if value.casefold() != canonical_predecessor.casefold()
                ]
                updated = type(item).model_validate(
                    {
                        **item.model_dump(mode="json", exclude_computed_fields=True),
                        "dependency_ids": legacy,
                        "dependencies": dependencies,
                    }
                )
                candidate = self._replace(project, field, index, updated)
                event_type = WORK_PACKAGE_UPDATED if field == "work_packages" else MILESTONE_UPDATED
                self._commit(
                    record,
                    candidate,
                    event_type=event_type,
                    payload={
                        f"{label.replace(' ', '_')}_id": item.id,
                        "changed_fields": ["dependencies"],
                    },
                )
                return cast(WorkPackage | Milestone, updated)
            raise ProjectItemNotFoundError(f"No schedule item matches {successor_id!r}")

    def remove_dependency(
        self,
        query: str,
        successor_id: str,
        predecessor_id: str,
    ) -> WorkPackage | Milestone:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            for field, values in (
                ("work_packages", project.work_packages),
                ("milestones", project.milestones),
            ):
                matches = [
                    (index, item)
                    for index, item in enumerate(values)
                    if item.id.casefold().startswith(successor_id.casefold())
                ]
                if len(matches) != 1:
                    continue
                index, item = matches[0]
                typed = [
                    value
                    for value in item.dependencies
                    if not value.predecessor_id.casefold().startswith(predecessor_id.casefold())
                ]
                legacy = [
                    value
                    for value in item.dependency_ids
                    if not value.casefold().startswith(predecessor_id.casefold())
                ]
                if len(typed) == len(item.dependencies) and len(legacy) == len(item.dependency_ids):
                    raise ProjectItemNotFoundError(
                        f"No dependency from {predecessor_id!r} to {item.id}"
                    )
                updated = type(item).model_validate(
                    {
                        **item.model_dump(mode="json", exclude_computed_fields=True),
                        "dependency_ids": legacy,
                        "dependencies": typed,
                    }
                )
                candidate = self._replace(project, field, index, updated)
                self._commit(
                    record,
                    candidate,
                    event_type=(
                        WORK_PACKAGE_UPDATED if field == "work_packages" else MILESTONE_UPDATED
                    ),
                    payload={"schedule_item_id": item.id, "changed_fields": ["dependencies"]},
                )
                return cast(WorkPackage | Milestone, updated)
            raise ProjectItemNotFoundError(f"No schedule item matches {successor_id!r}")

    def _transition_work_item(
        self,
        query: str,
        item_id: str,
        target: WorkStatus,
        *,
        field: str,
        label: str,
        event_type: str,
    ) -> ManagedProjectDocument:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(cast(list[BaseModel], getattr(project, field)), item_id, label)
            existing = cast(Phase | WorkPackage, raw)
            if target not in WORK_TRANSITIONS[existing.status]:
                raise ProjectTransitionError(
                    f"Cannot transition {label} from {existing.status.value} to {target.value}"
                )
            if target is WorkStatus.COMPLETED:
                self._assert_criteria(existing.completion_criteria, label)
                if isinstance(existing, Phase):
                    children = [
                        item
                        for item in project.work_packages
                        if item.phase_id is not None
                        and item.phase_id.casefold() == existing.id.casefold()
                    ]
                    if any(
                        item.status not in {WorkStatus.COMPLETED, WorkStatus.CANCELLED}
                        for item in children
                    ):
                        raise ProjectCompletionGateError(f"{label} has unfinished work packages")
                    milestones = [
                        item
                        for item in project.milestones
                        if item.phase_id is not None
                        and item.phase_id.casefold() == existing.id.casefold()
                    ]
                    if any(
                        item.status
                        not in {
                            MilestoneStatus.ACHIEVED,
                            MilestoneStatus.CANCELLED,
                        }
                        for item in milestones
                    ):
                        raise ProjectCompletionGateError(f"{label} has open milestones")
            item_type = Phase if isinstance(existing, Phase) else WorkPackage
            updated = item_type.model_validate(
                {
                    **existing.model_dump(mode="json", exclude_computed_fields=True),
                    "status": target,
                }
            )
            candidate = self._replace(project, field, index, updated)
            return self._commit(
                record,
                candidate,
                event_type=event_type,
                payload={"item_id": existing.id, "from": existing.status.value, "to": target.value},
            )

    def transition_phase(
        self, query: str, phase_id: str, status: WorkStatus | str
    ) -> ManagedProjectDocument:
        return self._transition_work_item(
            query,
            phase_id,
            WorkStatus(status),
            field="phases",
            label="phase",
            event_type=PHASE_TRANSITIONED,
        )

    def transition_work_package(
        self, query: str, work_package_id: str, status: WorkStatus | str
    ) -> ManagedProjectDocument:
        return self._transition_work_item(
            query,
            work_package_id,
            WorkStatus(status),
            field="work_packages",
            label="work package",
            event_type=WORK_PACKAGE_TRANSITIONED,
        )

    def transition_milestone(
        self,
        query: str,
        milestone_id: str,
        status: MilestoneStatus | str,
        *,
        achieved_on: date | None = None,
    ) -> ManagedProjectDocument:
        target = MilestoneStatus(status)
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.milestones, milestone_id, "milestone")
            milestone = cast(Milestone, raw)
            if target not in MILESTONE_TRANSITIONS[milestone.status]:
                raise ProjectTransitionError(
                    f"Cannot transition milestone from {milestone.status.value} to {target.value}"
                )
            if target is MilestoneStatus.ACHIEVED:
                self._assert_criteria(milestone.completion_criteria, "milestone")
            updated = Milestone.model_validate(
                {
                    **milestone.model_dump(mode="json", exclude_computed_fields=True),
                    "status": target,
                    "achieved_on": (achieved_on or date.today())
                    if target is MilestoneStatus.ACHIEVED
                    else None,
                }
            )
            candidate = self._replace(project, "milestones", index, updated)
            return self._commit(
                record,
                candidate,
                event_type=MILESTONE_TRANSITIONED,
                payload={
                    "milestone_id": milestone.id,
                    "from": milestone.status.value,
                    "to": target.value,
                },
            )

    @staticmethod
    def _assert_criteria(criteria: Iterable[CompletionCriterion], label: str) -> None:
        if any(not item.satisfied for item in criteria):
            raise ProjectCompletionGateError(f"{label} completion criteria are not satisfied")

    def _assert_project_complete(self, project: ManagedProject) -> None:
        self._assert_criteria(project.completion_criteria, "project")
        passing = {
            (requirement_id.casefold(), record.activity)
            for record in project.verification_records
            if record.result is VerificationResult.PASS and record.evidence_ids
            for requirement_id in record.requirement_ids
        }
        for requirement in project.requirements:
            if requirement.status is not RequirementStatus.APPROVED:
                continue
            missing = [
                activity.value
                for activity in requirement.required_activities
                if (requirement.id.casefold(), activity) not in passing
            ]
            if missing:
                raise ProjectCompletionGateError(
                    f"project requirement {requirement.id} lacks passing "
                    f"{', '.join(missing)} evidence"
                )
        if any(
            phase.status not in {WorkStatus.COMPLETED, WorkStatus.CANCELLED}
            for phase in project.phases
        ):
            raise ProjectCompletionGateError("project has unfinished phases")
        if any(
            item.status not in {WorkStatus.COMPLETED, WorkStatus.CANCELLED}
            for item in project.work_packages
        ):
            raise ProjectCompletionGateError("project has unfinished work packages")
        if any(
            item.status not in {MilestoneStatus.ACHIEVED, MilestoneStatus.CANCELLED}
            for item in project.milestones
        ):
            raise ProjectCompletionGateError("project has open milestones")

    def record_evidence(
        self,
        query: str,
        *,
        statement: str,
        source: str,
        evidence_id: str | None = None,
    ) -> EvidenceRecord:
        evidence = EvidenceRecord(
            id=evidence_id or _new_id("EV"), statement=statement, source=source
        )
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            candidate = self._validated(project, evidence=[*project.evidence, evidence])
            self._commit(
                record,
                candidate,
                event_type=EVIDENCE_RECORDED,
                payload={"evidence_id": evidence.id},
            )
        return evidence

    def update_completion_criterion(
        self,
        query: str,
        criterion_id: str,
        *,
        status: CompletionCriterionStatus | str,
        evidence_ids: Iterable[str] = (),
        waiver_reason: str | None = None,
    ) -> CompletionCriterion:
        target = CompletionCriterionStatus(status)
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            known_evidence = {item.id.casefold(): item.id for item in project.evidence}
            canonical_evidence: list[str] = []
            for query_id in evidence_ids:
                matches = [
                    stable_id
                    for key, stable_id in known_evidence.items()
                    if key.startswith(query_id.casefold())
                ]
                if len(matches) != 1:
                    raise ProjectConflictError(
                        f"Evidence {query_id!r} must resolve to exactly one record"
                    )
                canonical_evidence.append(matches[0])
            criterion = CompletionCriterion(
                id=criterion_id,
                description="placeholder",
                status=target,
                evidence_ids=canonical_evidence,
                waiver_reason=waiver_reason,
            )

            def replace_criteria(
                values: list[CompletionCriterion],
            ) -> tuple[list[CompletionCriterion], bool]:
                updated_values: list[CompletionCriterion] = []
                changed = False
                for existing in values:
                    if existing.id.casefold().startswith(criterion_id.casefold()):
                        if changed:
                            raise ProjectConflictError(
                                f"{criterion_id!r} matches multiple completion criteria"
                            )
                        criterion.description = existing.description
                        updated_values.append(criterion)
                        changed = True
                    else:
                        updated_values.append(existing)
                return updated_values, changed

            data = project.model_dump(mode="json", exclude_computed_fields=True)
            found = False
            data["completion_criteria"], found = replace_criteria(project.completion_criteria)
            for collection_name in ("phases", "work_packages", "milestones"):
                collection: list[BaseModel] = []
                for item in cast(list[BaseModel], getattr(project, collection_name)):
                    values, item_found = replace_criteria(
                        cast(list[CompletionCriterion], item.completion_criteria)
                    )
                    found = found or item_found
                    item_data = item.model_dump(mode="json", exclude_computed_fields=True)
                    item_data["completion_criteria"] = values
                    collection.append(type(item).model_validate(item_data))
                data[collection_name] = collection
            if not found:
                raise ProjectItemNotFoundError(f"No completion criterion matches {criterion_id!r}")
            candidate = ManagedProject.model_validate(data)
            self._commit(
                record,
                candidate,
                event_type=COMPLETION_CRITERION_UPDATED,
                payload={"criterion_id": criterion.id, "status": target.value},
            )
            return criterion

    def add_register_item(
        self,
        query: str,
        *,
        kind: RegisterItemKind | str,
        title: str,
        register_item_id: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        probability: Decimal | None = None,
        impact_cost: Decimal = Decimal("0"),
        impact_days: int = 0,
        response: str | None = None,
        decision: str | None = None,
        due_on: date | None = None,
    ) -> RegisterItem:
        item = RegisterItem(
            id=register_item_id or _new_id("RI"),
            kind=RegisterItemKind(kind),
            title=title,
            description=description,
            owner=owner,
            probability=probability,
            impact_cost=impact_cost,
            impact_days=impact_days,
            response=response,
            decision=decision,
            due_on=due_on,
        )
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            candidate = self._validated(project, register_items=[*project.register_items, item])
            self._commit(
                record,
                candidate,
                event_type=REGISTER_ITEM_ADDED,
                payload={"register_item_id": item.id, "kind": item.kind.value},
            )
        return item

    def update_register_item(
        self,
        query: str,
        register_item_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        owner: str | None = None,
        status: RegisterItemStatus | str | None = None,
        probability: Decimal | None = None,
        impact_cost: Decimal | None = None,
        impact_days: int | None = None,
        response: str | None = None,
        decision: str | None = None,
        due_on: date | None = None,
    ) -> RegisterItem:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.register_items, register_item_id, "register item")
            item = cast(RegisterItem, raw)
            changes: dict[str, object] = {}
            for name, value in (
                ("title", title),
                ("description", description),
                ("owner", owner),
                ("status", RegisterItemStatus(status) if status is not None else None),
                ("probability", probability),
                ("impact_cost", impact_cost),
                ("impact_days", impact_days),
                ("response", response),
                ("decision", decision),
                ("due_on", due_on),
            ):
                if value is not None:
                    changes[name] = value
            updated = RegisterItem.model_validate(
                {**item.model_dump(mode="json", exclude_computed_fields=True), **changes}
            )
            candidate = self._replace(project, "register_items", index, updated)
            self._commit(
                record,
                candidate,
                event_type=REGISTER_ITEM_UPDATED,
                payload={"register_item_id": item.id, "changed_fields": sorted(changes)},
            )
            return updated

    @staticmethod
    def _canonical_internal_ids(
        project: ManagedProject,
        queries: Iterable[str],
        *,
        candidates: Iterable[str],
        label: str,
    ) -> list[str]:
        stable_ids = list(candidates)
        canonical: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = query.casefold()
            exact = [item for item in stable_ids if item.casefold() == normalized]
            matches = exact or [
                item for item in stable_ids if item.casefold().startswith(normalized)
            ]
            if not matches:
                raise ProjectLinkError(f"{label} {query!r} does not exist in {project.id}")
            if len(matches) > 1:
                raise ProjectLinkError(f"{label} {query!r} is ambiguous in {project.id}")
            key = matches[0].casefold()
            if key not in seen:
                canonical.append(matches[0])
                seen.add(key)
        return canonical

    def add_requirement(
        self,
        query: str,
        *,
        title: str,
        statement: str,
        requirement_id: str | None = None,
        kind: RequirementKind | str = RequirementKind.FUNCTIONAL,
        status: RequirementStatus | str = RequirementStatus.DRAFT,
        source: str | None = None,
        parent_id: str | None = None,
        required_activities: Iterable[VerificationActivity | str] = (
            VerificationActivity.VERIFICATION,
        ),
    ) -> Requirement:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            canonical_parent = None
            if parent_id is not None:
                canonical_parent = self._canonical_internal_ids(
                    project,
                    [parent_id],
                    candidates=(item.id for item in project.requirements),
                    label="parent requirement",
                )[0]
            requirement = Requirement(
                id=requirement_id or _new_id("REQ"),
                title=title,
                statement=statement,
                kind=RequirementKind(kind),
                status=RequirementStatus(status),
                source=source,
                parent_id=canonical_parent,
                required_activities=[VerificationActivity(item) for item in required_activities],
            )
            candidate = self._validated(project, requirements=[*project.requirements, requirement])
            self._commit(
                record,
                candidate,
                event_type=REQUIREMENT_ADDED,
                payload={"requirement_id": requirement.id},
            )
            return requirement

    def update_requirement(
        self,
        query: str,
        requirement_id: str,
        *,
        title: str | None = None,
        statement: str | None = None,
        kind: RequirementKind | str | None = None,
        status: RequirementStatus | str | None = None,
        source: str | None = None,
        parent_id: str | None = None,
        required_activities: Iterable[VerificationActivity | str] | None = None,
    ) -> Requirement:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.requirements, requirement_id, "requirement")
            requirement = cast(Requirement, raw)
            changes: dict[str, object] = {}
            for name, value in (
                ("title", title),
                ("statement", statement),
                ("kind", RequirementKind(kind) if kind is not None else None),
                ("source", source),
            ):
                if value is not None:
                    changes[name] = value
            if status is not None:
                target = RequirementStatus(status)
                allowed = {
                    RequirementStatus.DRAFT: {
                        RequirementStatus.APPROVED,
                        RequirementStatus.RETIRED,
                    },
                    RequirementStatus.APPROVED: {RequirementStatus.RETIRED},
                    RequirementStatus.RETIRED: set(),
                }
                if target not in allowed[requirement.status]:
                    raise ProjectTransitionError(
                        f"Cannot transition requirement from {requirement.status.value} "
                        f"to {target.value}"
                    )
                changes["status"] = target
            if parent_id is not None:
                changes["parent_id"] = self._canonical_internal_ids(
                    project,
                    [parent_id],
                    candidates=(
                        item.id for item in project.requirements if item.id != requirement.id
                    ),
                    label="parent requirement",
                )[0]
            if required_activities is not None:
                changes["required_activities"] = [
                    VerificationActivity(item) for item in required_activities
                ]
            updated = Requirement.model_validate(
                {
                    **requirement.model_dump(mode="json", exclude_computed_fields=True),
                    **changes,
                }
            )
            candidate = self._replace(project, "requirements", index, updated)
            self._commit(
                record,
                candidate,
                event_type=REQUIREMENT_UPDATED,
                payload={"requirement_id": requirement.id, "changed_fields": sorted(changes)},
            )
            return updated

    def record_verification(
        self,
        query: str,
        *,
        activity: VerificationActivity | str,
        method: VerificationMethod | str,
        result: VerificationResult | str,
        requirement_ids: Iterable[str],
        evidence_ids: Iterable[str] = (),
        verification_id: str | None = None,
        notes: str | None = None,
    ) -> VerificationRecord:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            canonical_requirements = self._canonical_internal_ids(
                project,
                requirement_ids,
                candidates=(item.id for item in project.requirements),
                label="requirement",
            )
            canonical_evidence = self._canonical_internal_ids(
                project,
                evidence_ids,
                candidates=(item.id for item in project.evidence),
                label="evidence",
            )
            target_result = VerificationResult(result)
            verification = VerificationRecord(
                id=verification_id or _new_id("VV"),
                activity=VerificationActivity(activity),
                method=VerificationMethod(method),
                result=target_result,
                requirement_ids=canonical_requirements,
                evidence_ids=canonical_evidence,
                performed_at=None if target_result is VerificationResult.PLANNED else utc_now(),
                notes=notes,
            )
            candidate = self._validated(
                project,
                verification_records=[*project.verification_records, verification],
            )
            self._commit(
                record,
                candidate,
                event_type=VERIFICATION_RECORDED,
                payload={
                    "verification_id": verification.id,
                    "activity": verification.activity.value,
                    "result": verification.result.value,
                },
            )
            return verification

    def record_gate_review(
        self,
        query: str,
        *,
        title: str,
        decision: GateDecision | str,
        rationale: str,
        criterion_ids: Iterable[str] = (),
        evidence_ids: Iterable[str] = (),
        exceptions: Iterable[str] = (),
        gate_review_id: str | None = None,
    ) -> GateReview:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            canonical_criteria = self._canonical_internal_ids(
                project,
                criterion_ids,
                candidates=(item.id for item in self._all_criteria(project)),
                label="completion criterion",
            )
            canonical_evidence = self._canonical_internal_ids(
                project,
                evidence_ids,
                candidates=(item.id for item in project.evidence),
                label="evidence",
            )
            target = GateDecision(decision)
            if target is GateDecision.GO:
                criteria_by_id = {item.id.casefold(): item for item in self._all_criteria(project)}
                if any(
                    not criteria_by_id[item.casefold()].satisfied for item in canonical_criteria
                ):
                    raise ProjectCompletionGateError(
                        "a go gate requires every referenced completion criterion to be satisfied"
                    )
            gate = GateReview(
                id=gate_review_id or _new_id("GATE"),
                title=title,
                reviewed_at=utc_now(),
                criterion_ids=canonical_criteria,
                evidence_ids=canonical_evidence,
                exceptions=list(exceptions),
                decision=target,
                rationale=rationale,
            )
            candidate = self._validated(project, gate_reviews=[*project.gate_reviews, gate])
            self._commit(
                record,
                candidate,
                event_type=GATE_REVIEW_RECORDED,
                payload={"gate_review_id": gate.id, "decision": gate.decision.value},
            )
            return gate

    def add_change_request(
        self,
        query: str,
        *,
        title: str,
        kind: ChangeKind | str,
        before: str,
        after: str,
        qcd_impact: str,
        vv_impact: str,
        target_ids: Iterable[str] = (),
        change_request_id: str | None = None,
    ) -> ChangeRequest:
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            stable_ids = self._internal_ids(project)
            originals = [
                stable_id
                for collection in (
                    [project],
                    project.constraints,
                    project.assumptions,
                    self._all_criteria(project),
                    project.stakeholders,
                    project.phases,
                    project.work_packages,
                    project.milestones,
                    project.register_items,
                    project.evidence,
                    project.requirements,
                    project.verification_records,
                    project.gate_reviews,
                    project.baselines,
                )
                for stable_id in (item.id for item in collection)
                if stable_id.casefold() in stable_ids
            ]
            canonical_targets = self._canonical_internal_ids(
                project,
                target_ids,
                candidates=originals,
                label="change target",
            )
            change = ChangeRequest(
                id=change_request_id or _new_id("CHG"),
                title=title,
                kind=ChangeKind(kind),
                target_ids=canonical_targets,
                before=before,
                after=after,
                qcd_impact=qcd_impact,
                vv_impact=vv_impact,
            )
            candidate = self._validated(project, change_requests=[*project.change_requests, change])
            self._commit(
                record,
                candidate,
                event_type=CHANGE_REQUEST_ADDED,
                payload={"change_request_id": change.id},
            )
            return change

    def update_change_request(
        self,
        query: str,
        change_request_id: str,
        *,
        status: ChangeStatus | str,
        decision: str | None = None,
        rationale: str | None = None,
    ) -> ChangeRequest:
        target = ChangeStatus(status)
        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            index, raw = self._find(project.change_requests, change_request_id, "change request")
            change = cast(ChangeRequest, raw)
            allowed = {
                ChangeStatus.PROPOSED: {ChangeStatus.APPROVED, ChangeStatus.REJECTED},
                ChangeStatus.APPROVED: {ChangeStatus.IMPLEMENTED},
                ChangeStatus.REJECTED: set(),
                ChangeStatus.IMPLEMENTED: set(),
            }
            if target not in allowed[change.status]:
                raise ProjectTransitionError(
                    f"Cannot transition change request from {change.status.value} to {target.value}"
                )
            updated = ChangeRequest.model_validate(
                {
                    **change.model_dump(mode="json", exclude_computed_fields=True),
                    "status": target,
                    "decision": decision,
                    "rationale": rationale,
                    "decided_at": utc_now(),
                }
            )
            candidate = self._replace(project, "change_requests", index, updated)
            self._commit(
                record,
                candidate,
                event_type=CHANGE_REQUEST_UPDATED,
                payload={"change_request_id": change.id, "status": target.value},
            )
            return updated

    def create_baseline(self, query: str, *, label: str) -> BaselineRecord:
        """Append an immutable hash/reference, not a duplicate project snapshot."""

        with self.workspace.lock():
            record = self._record(query)
            project = cast(ManagedProject, record.entity)
            serialized = json.dumps(
                project.model_dump(
                    mode="json",
                    exclude={"baselines"},
                    exclude_computed_fields=True,
                ),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            event_id = _new_id("PEVT")
            schedule = self._compute_schedule(project)
            baseline = BaselineRecord(
                id=_new_id("BASE"),
                label=label,
                project_revision=project.revision,
                content_hash=hashlib.sha256(serialized).hexdigest(),
                event_id=event_id,
                schedule_items=[
                    BaselineScheduleItem(
                        id=item.id,
                        start_on=item.scheduled_start_on,
                        finish_on=item.scheduled_finish_on,
                    )
                    for item in schedule.items
                ],
            )
            candidate = self._validated(project, baselines=[*project.baselines, baseline])
            self._commit(
                record,
                candidate,
                event_type=BASELINE_CREATED,
                payload={
                    "baseline_id": baseline.id,
                    "project_revision": baseline.project_revision,
                    "content_hash": baseline.content_hash,
                },
                audit_event_id=event_id,
            )
            return baseline

    @staticmethod
    def _duration(node: WorkPackage | Milestone) -> int:
        return node.duration_days if isinstance(node, WorkPackage) else 0

    @staticmethod
    def _dependency_weight(
        dependency: ScheduleDependency,
        predecessor_duration: int,
        successor_duration: int,
    ) -> int:
        """Convert every precedence relation to ``start_s >= start_p + weight``."""

        if dependency.type is DependencyType.FINISH_TO_START:
            return predecessor_duration + dependency.lag_days
        if dependency.type is DependencyType.START_TO_START:
            return dependency.lag_days
        if dependency.type is DependencyType.FINISH_TO_FINISH:
            return predecessor_duration - successor_duration + dependency.lag_days
        return -successor_duration + dependency.lag_days

    @staticmethod
    def _schedule_dependencies(
        node: WorkPackage | Milestone,
        canonical: dict[str, str],
    ) -> list[ScheduleDependency]:
        typed = {item.predecessor_id.casefold(): item for item in node.dependencies}
        for predecessor_id in node.dependency_ids:
            typed.setdefault(
                predecessor_id.casefold(),
                ScheduleDependency(predecessor_id=predecessor_id),
            )
        resolved: list[ScheduleDependency] = []
        for dependency in typed.values():
            predecessor_id = canonical.get(dependency.predecessor_id.casefold())
            if predecessor_id is None:
                raise ProjectScheduleError(
                    f"{node.id} has missing dependency {dependency.predecessor_id!r}"
                )
            if predecessor_id == node.id:
                raise ProjectScheduleError(f"dependency cycle detected at {node.id}")
            resolved.append(dependency.model_copy(update={"predecessor_id": predecessor_id}))
        return sorted(resolved, key=lambda item: item.predecessor_id)

    @classmethod
    def _compute_schedule(cls, project: ManagedProject) -> ScheduleProjection:
        nodes: dict[str, WorkPackage | Milestone] = {}
        for item in [*project.work_packages, *project.milestones]:
            if item.id in nodes:
                raise ProjectScheduleError(f"duplicate schedule node {item.id!r}")
            nodes[item.id] = item
        canonical = {node_id.casefold(): node_id for node_id in nodes}
        dependencies: dict[str, list[ScheduleDependency]] = {}
        successors: dict[str, list[tuple[str, ScheduleDependency]]] = defaultdict(list)
        indegree: dict[str, int] = {}
        for node_id, node in nodes.items():
            resolved = cls._schedule_dependencies(node, canonical)
            dependencies[node_id] = resolved
            indegree[node_id] = len(resolved)
            for dependency in resolved:
                successors[dependency.predecessor_id].append((node_id, dependency))

        queue = [node_id for node_id, degree in indegree.items() if degree == 0]
        heapq.heapify(queue)
        order: list[str] = []
        while queue:
            node_id = heapq.heappop(queue)
            order.append(node_id)
            for successor, _dependency in sorted(successors[node_id], key=lambda item: item[0]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    heapq.heappush(queue, successor)
        if len(order) != len(nodes):
            cyclic = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
            raise ProjectScheduleError(f"dependency cycle detected involving {', '.join(cyclic)}")

        explicit_dates = [
            value
            for node in nodes.values()
            for value in (node.start_on if isinstance(node, WorkPackage) else node.planned_on,)
            if value is not None
        ]
        anchor_candidates = [*explicit_dates]
        if project.planned_start_on is not None:
            anchor_candidates.append(project.planned_start_on)
        raw_anchor = min(anchor_candidates) if anchor_candidates else project.created_at.date()
        axis = _CalendarAxis(project.working_calendar, raw_anchor)
        start_offsets: dict[str, int] = {}
        end_offsets: dict[str, int] = {}
        driving_predecessor: dict[str, str | None] = {}
        for node_id in order:
            node = nodes[node_id]
            duration = cls._duration(node)
            candidates: list[tuple[int, str]] = []
            for dependency in dependencies[node_id]:
                predecessor_id = dependency.predecessor_id
                weight = cls._dependency_weight(
                    dependency,
                    cls._duration(nodes[predecessor_id]),
                    duration,
                )
                candidates.append((start_offsets[predecessor_id] + weight, predecessor_id))
            explicit = node.start_on if isinstance(node, WorkPackage) else node.planned_on
            explicit_offset = axis.tick_for_date(explicit) if explicit is not None else 0
            dependency_offset, predecessor = (
                sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
                if candidates
                else (0, None)
            )
            start = max(0, explicit_offset, dependency_offset)
            start_offsets[node_id] = start
            end_offsets[node_id] = start + duration
            driving_predecessor[node_id] = (
                predecessor if predecessor is not None and dependency_offset == start else None
            )

        project_end = max(end_offsets.values(), default=0)
        latest_start: dict[str, int] = {}
        for node_id in reversed(order):
            node = nodes[node_id]
            bounds: list[int] = []
            for successor_id, dependency in successors[node_id]:
                weight = cls._dependency_weight(
                    dependency,
                    cls._duration(node),
                    cls._duration(nodes[successor_id]),
                )
                bounds.append(latest_start[successor_id] - weight)
            latest_start[node_id] = min(bounds) if bounds else project_end - cls._duration(node)
        total_float = {
            node_id: max(0, latest_start[node_id] - start_offsets[node_id]) for node_id in order
        }
        free_float: dict[str, int] = {}
        for node_id in order:
            slacks: list[int] = []
            for successor_id, dependency in successors[node_id]:
                weight = cls._dependency_weight(
                    dependency,
                    cls._duration(nodes[node_id]),
                    cls._duration(nodes[successor_id]),
                )
                slacks.append(start_offsets[successor_id] - start_offsets[node_id] - weight)
            free_float[node_id] = max(
                0,
                min(slacks) if slacks else project_end - end_offsets[node_id],
            )

        critical_path: list[str] = []
        if order:
            end_node = sorted(order, key=lambda item: (-end_offsets[item], item))[0]
            cursor: str | None = end_node
            while cursor is not None and total_float[cursor] == 0:
                critical_path.append(cursor)
                predecessor = driving_predecessor[cursor]
                cursor = (
                    predecessor
                    if predecessor is not None and total_float[predecessor] == 0
                    else None
                )
            critical_path.reverse()

        baseline_by_id = {
            item.id: item for baseline in project.baselines[-1:] for item in baseline.schedule_items
        }
        items: list[ScheduleItem] = []
        for node_id in order:
            node = nodes[node_id]
            duration = cls._duration(node)
            start_on = axis.date_for_tick(start_offsets[node_id])
            finish_tick = end_offsets[node_id] - 1 if duration else end_offsets[node_id]
            finish_on = axis.date_for_tick(finish_tick)
            latest_on = axis.date_for_tick(latest_start[node_id])
            latest_finish_tick = latest_start[node_id] + duration - (1 if duration else 0)
            latest_finish_on = axis.date_for_tick(latest_finish_tick)
            due_on = node.due_on
            violation = (
                f"finishes after due date {due_on.isoformat()}"
                if due_on is not None and finish_on > due_on
                else None
            )
            baseline = baseline_by_id.get(node_id)
            delay_days = (
                max(0, (finish_on - baseline.finish_on).days) if baseline is not None else 0
            )
            items.append(
                ScheduleItem(
                    id=node_id,
                    kind="work_package" if isinstance(node, WorkPackage) else "milestone",
                    title=node.title,
                    duration_days=duration,
                    dependency_ids=[item.predecessor_id for item in dependencies[node_id]],
                    dependencies=dependencies[node_id],
                    scheduled_start_on=start_on,
                    scheduled_finish_on=finish_on,
                    earliest_start_on=start_on,
                    earliest_finish_on=finish_on,
                    latest_start_on=latest_on,
                    latest_finish_on=latest_finish_on,
                    due_on=due_on,
                    critical=total_float[node_id] == 0,
                    total_float_days=total_float[node_id],
                    free_float_days=free_float[node_id],
                    progress_percent=(
                        node.progress_percent if isinstance(node, WorkPackage) else 0
                    ),
                    owner=node.owner,
                    jira_status=node.jira_status,
                    delay_days=delay_days,
                    constraint_violation=violation,
                )
            )
        project_finish_on = max(
            (item.scheduled_finish_on for item in items),
            default=axis.anchor,
        )
        return ScheduleProjection(
            project_id=project.id,
            anchor_on=axis.anchor,
            project_finish_on=project_finish_on,
            topological_order=order,
            critical_path=critical_path,
            total_duration_days=project_end,
            items=items,
        )

    def compute_schedule(self, query: str) -> ScheduleProjection:
        return self._compute_schedule(self.get(query).project)

    def explain_schedule(self, query: str, item_id: str) -> ScheduleExplanation:
        project = self.get(query).project
        schedule = self._compute_schedule(project)
        by_id = {item.id: item for item in schedule.items}
        matches = [
            item for key, item in by_id.items() if key.casefold().startswith(item_id.casefold())
        ]
        if len(matches) != 1:
            raise ProjectItemNotFoundError(
                f"Schedule item {item_id!r} must resolve to exactly one work item or milestone"
            )
        item = matches[0]
        node_by_id: dict[str, WorkPackage | Milestone] = {
            node.id: node for node in [*project.work_packages, *project.milestones]
        }
        node = node_by_id[item.id]
        canonical = {node_id.casefold(): node_id for node_id in node_by_id}
        dependencies = self._schedule_dependencies(node, canonical)
        axis = _CalendarAxis(project.working_calendar, schedule.anchor_on)
        item_start_tick = axis.tick_for_date(item.scheduled_start_on)
        candidates: list[tuple[int, str, ScheduleDependency]] = []
        for dependency in dependencies:
            predecessor = by_id[dependency.predecessor_id]
            predecessor_node = node_by_id[dependency.predecessor_id]
            weight = self._dependency_weight(
                dependency,
                self._duration(predecessor_node),
                self._duration(node),
            )
            constraint = axis.tick_for_date(predecessor.scheduled_start_on) + weight
            candidates.append((constraint, dependency.predecessor_id, dependency))
        driving = (
            sorted(candidates, key=lambda value: (-value[0], value[1]))[0] if candidates else None
        )
        reasons: list[str] = []
        driving_id: str | None = None
        if driving is not None and driving[0] == item_start_tick:
            _constraint, driving_id, dependency = driving
            predecessor = by_id[driving_id]
            reasons.append(
                f"{dependency.type.label} dependency on {driving_id} "
                f"({predecessor.scheduled_start_on.isoformat()} to "
                f"{predecessor.scheduled_finish_on.isoformat()})"
            )
            if dependency.lag_days > 0:
                unit = "day" if dependency.lag_days == 1 else "days"
                reasons.append(f"{dependency.lag_days} working {unit} lag")
            elif dependency.lag_days < 0:
                lead = abs(dependency.lag_days)
                unit = "day" if lead == 1 else "days"
                reasons.append(f"{lead} working {unit} lead")
            gap_start = predecessor.scheduled_finish_on + timedelta(days=1)
            gap_finish = item.scheduled_start_on - timedelta(days=1)
            skipped = axis.non_working_between(gap_start, gap_finish)
            if skipped:
                reasons.append(
                    "Working calendar skipped non-working dates: "
                    + ", ".join(value.isoformat() for value in skipped)
                )
        explicit = node.start_on if isinstance(node, WorkPackage) else node.planned_on
        if explicit is not None and axis.tick_for_date(explicit) == item_start_tick:
            reasons.append(f"Explicit no-earlier-than date {explicit.isoformat()}")
        if not reasons:
            reasons.append(f"Project working-calendar anchor {schedule.anchor_on.isoformat()}")
        return ScheduleExplanation(
            project_id=project.id,
            item_id=item.id,
            scheduled_start_on=item.scheduled_start_on,
            scheduled_finish_on=item.scheduled_finish_on,
            driving_predecessor_id=driving_id,
            reasons=reasons,
        )

    @staticmethod
    def _health_from_upper(value: Decimal | int | None, amber: Decimal | int) -> Health:
        if value is None:
            return Health.UNKNOWN
        if value <= 0:
            return Health.GREEN
        if value <= amber:
            return Health.AMBER
        return Health.RED

    def qcd_projection(self, query: str) -> QcdProjection:
        project = self.get(query).project
        baseline = project.qcd.baseline
        current = project.qcd.current
        forecast = project.qcd.forecast
        cost_variance = forecast.cost - baseline.cost
        cost_percent = (
            (cost_variance / baseline.cost * Decimal("100")).quantize(Decimal("0.01"))
            if baseline.cost != 0
            else (Decimal("0") if cost_variance == 0 else None)
        )
        quality_variance = (
            forecast.quality_percent - baseline.quality_percent
            if forecast.quality_percent is not None and baseline.quality_percent is not None
            else None
        )
        delivery_variance = (
            (forecast.delivery_on - baseline.delivery_on).days
            if forecast.delivery_on is not None and baseline.delivery_on is not None
            else None
        )
        scope_variance = forecast.scope_units - baseline.scope_units
        cost_health = self._health_from_upper(cost_percent, Decimal("10"))
        delivery_health = self._health_from_upper(delivery_variance, 7)
        quality_health = self._health_from_upper(
            -quality_variance if quality_variance is not None else None,
            Decimal("5"),
        )
        scope_health = (
            Health.GREEN
            if scope_variance == 0
            else Health.AMBER
            if abs(scope_variance) <= max(Decimal("1"), baseline.scope_units * Decimal("0.1"))
            else Health.RED
        )
        rank = {Health.UNKNOWN: 0, Health.GREEN: 1, Health.AMBER: 2, Health.RED: 3}
        overall = max(
            (cost_health, delivery_health, quality_health, scope_health),
            key=lambda item: rank[item],
        )
        return QcdProjection(
            project_id=project.id,
            current_cost_variance=current.cost - baseline.cost,
            forecast_cost_variance=cost_variance,
            forecast_cost_variance_percent=cost_percent,
            current_effort_variance=current.effort_hours - baseline.effort_hours,
            forecast_effort_variance=forecast.effort_hours - baseline.effort_hours,
            forecast_quality_variance=quality_variance,
            forecast_delivery_variance_days=delivery_variance,
            forecast_scope_variance=scope_variance,
            cost_health=cost_health,
            delivery_health=delivery_health,
            quality_health=quality_health,
            scope_health=scope_health,
            overall_health=overall,
        )

    def doctor(self) -> ProjectDoctorReport:
        issues: list[ProjectDoctorIssue] = []
        projects: list[ManagedProject] = []
        seen_ids: dict[str, str] = {}
        spec = self.workspace.registry.require("managed_project")
        directory = self.workspace.root / spec.directory
        for path in sorted(directory.glob("*.md")):
            try:
                record = self.workspace.read(path, expected_kind="managed_project")
                project = cast(ManagedProject, record.entity)
            except (InvalidDocumentError, ValidationError, ValueError) as exc:
                issues.append(
                    ProjectDoctorIssue(
                        severity="error",
                        code="malformed_document",
                        message=str(exc),
                        path=self.workspace.relative(path),
                    )
                )
                continue
            key = project.id.casefold()
            if key in seen_ids:
                issues.append(
                    ProjectDoctorIssue(
                        severity="error",
                        code="duplicate_project_id",
                        message=f"duplicate project ID {project.id}",
                        project_id=project.id,
                        path=self.workspace.relative(path),
                    )
                )
            seen_ids[key] = self.workspace.relative(path)
            projects.append(project)

        for project in projects:
            phase_ids = {item.id.casefold() for item in project.phases}
            for item in [*project.work_packages, *project.milestones]:
                if item.phase_id is not None and item.phase_id.casefold() not in phase_ids:
                    issues.append(
                        ProjectDoctorIssue(
                            severity="error",
                            code="missing_phase",
                            message=f"{item.id} references missing phase {item.phase_id}",
                            project_id=project.id,
                            nested_id=item.id,
                        )
                    )
            evidence_ids = {item.id.casefold() for item in project.evidence}
            for criterion in self._all_criteria(project):
                for evidence_id in criterion.evidence_ids:
                    if evidence_id.casefold() not in evidence_ids:
                        issues.append(
                            ProjectDoctorIssue(
                                severity="error",
                                code="broken_evidence_link",
                                message=(
                                    f"criterion {criterion.id} references missing evidence "
                                    f"{evidence_id}"
                                ),
                                project_id=project.id,
                                nested_id=criterion.id,
                            )
                        )
            try:
                schedule = self._compute_schedule(project)
            except ProjectScheduleError as exc:
                code = "dependency_cycle" if "cycle" in str(exc) else "missing_dependency"
                issues.append(
                    ProjectDoctorIssue(
                        severity="error",
                        code=code,
                        message=str(exc),
                        project_id=project.id,
                    )
                )
            else:
                issues.extend(
                    ProjectDoctorIssue(
                        severity="warning",
                        code="schedule_constraint",
                        message=item.constraint_violation or "",
                        project_id=project.id,
                        nested_id=item.id,
                    )
                    for item in schedule.items
                    if item.constraint_violation is not None
                )
            records_by_id: dict[str, list[BaseModel]] = defaultdict(list)
            try:
                all_records = self.workspace.all_records(include_archive=True)
            except InvalidDocumentError:
                all_records = []
            for record in all_records:
                entity_id = str(getattr(record.entity, "id", ""))
                if entity_id:
                    records_by_id[entity_id.casefold()].append(record.entity)
            gtd_ids = [*project.gtd_action_ids]
            for work_package in project.work_packages:
                gtd_ids.extend(work_package.gtd_action_ids)
            for entity_id in gtd_ids:
                matches = records_by_id.get(entity_id.casefold(), [])
                if not matches:
                    issues.append(
                        ProjectDoctorIssue(
                            severity="error",
                            code="broken_gtd_link",
                            message=f"GTD action {entity_id} does not exist",
                            project_id=project.id,
                            nested_id=entity_id,
                        )
                    )
                elif len(matches) != 1 or str(getattr(matches[0], "kind", "")) != "task":
                    issues.append(
                        ProjectDoctorIssue(
                            severity="error",
                            code="wrong_gtd_link_kind",
                            message=f"GTD action {entity_id} does not uniquely identify a task",
                            project_id=project.id,
                            nested_id=entity_id,
                        )
                    )
        issues.sort(key=lambda issue: (issue.project_id or "", issue.code, issue.nested_id or ""))
        return ProjectDoctorReport(
            issues=issues,
            counts={
                "projects": len(projects),
                "errors": sum(issue.severity == "error" for issue in issues),
                "warnings": sum(issue.severity == "warning" for issue in issues),
            },
        )

    validate = doctor


__all__ = ["ProjectManagementService"]
