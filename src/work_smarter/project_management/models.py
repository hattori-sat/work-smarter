"""Strict public models for text-first managed projects.

The aggregate embeds phases, work packages, milestones, registers, evidence,
and QCD snapshots.  Separate Markdown entities would reduce merge contention,
but would require a transaction spanning several editable files for each DAG
change.  The embedded representation keeps graph validation, revisioning, and
audit writes atomic.  Public nested models intentionally retain stable IDs so
they can be split into entities later without changing adapter contracts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from work_smarter.errors import InvalidDocumentError
from work_smarter.publishing.models import PublicationTarget
from work_smarter.storage.workspace import validate_entity_id


def utc_now() -> datetime:
    return datetime.now(UTC)


def _text(value: str, name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} cannot be blank")
    return cleaned


def _optional_text(value: str | None, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _id(value: str, name: str) -> str:
    cleaned = value.strip()
    try:
        return validate_entity_id(cleaned)
    except InvalidDocumentError as exc:
        raise ValueError(f"invalid {name}: {cleaned!r}") from exc


def _unique_ids(values: list[str], name: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _id(value, name)
        key = cleaned.casefold()
        if key in seen:
            raise ValueError(f"duplicate {name}: {cleaned}")
        seen.add(key)
        result.append(cleaned)
    return result


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ProjectLifecycle(StrEnum):
    PROPOSED = "proposed"
    PLANNED = "planned"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MilestoneStatus(StrEnum):
    PLANNED = "planned"
    ACHIEVED = "achieved"
    CANCELLED = "cancelled"


class CompletionCriterionStatus(StrEnum):
    OPEN = "open"
    MET = "met"
    WAIVED = "waived"


class AssumptionStatus(StrEnum):
    OPEN = "open"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"


class RegisterItemKind(StrEnum):
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    ISSUE = "issue"
    DECISION = "decision"


class RegisterItemStatus(StrEnum):
    OPEN = "open"
    MONITORING = "monitoring"
    CLOSED = "closed"


class Health(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    UNKNOWN = "unknown"


class RequirementKind(StrEnum):
    FUNCTIONAL = "functional"
    QUALITY = "quality"
    INTERFACE = "interface"
    OPERATIONAL = "operational"
    CONSTRAINT = "constraint"


class RequirementStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class VerificationActivity(StrEnum):
    VERIFICATION = "verification"
    VALIDATION = "validation"


class VerificationMethod(StrEnum):
    ANALYSIS = "analysis"
    INSPECTION = "inspection"
    TEST = "test"
    DEMONSTRATION = "demonstration"


class VerificationResult(StrEnum):
    PLANNED = "planned"
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class GateDecision(StrEnum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    HOLD = "hold"
    TERMINATE = "terminate"


class ChangeKind(StrEnum):
    SCOPE = "scope"
    SCHEDULE = "schedule"
    COST = "cost"
    QUALITY = "quality"
    REQUIREMENT = "requirement"
    BASELINE = "baseline"
    OTHER = "other"


class ChangeStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


class CompletionCriterion(StrictModel):
    id: str
    description: str
    status: CompletionCriterionStatus = CompletionCriterionStatus.OPEN
    evidence_ids: list[str] = Field(default_factory=list)
    waiver_reason: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "completion criterion ID")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _text(value, "completion criterion")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "evidence ID")

    @field_validator("waiver_reason")
    @classmethod
    def validate_waiver_reason(cls, value: str | None) -> str | None:
        return _optional_text(value, "waiver reason")

    @model_validator(mode="after")
    def validate_resolution(self) -> CompletionCriterion:
        if self.status is CompletionCriterionStatus.MET and not self.evidence_ids:
            raise ValueError("a met completion criterion requires evidence")
        if self.status is CompletionCriterionStatus.WAIVED and self.waiver_reason is None:
            raise ValueError("a waived completion criterion requires a waiver reason")
        if self.status is CompletionCriterionStatus.OPEN and (
            self.evidence_ids or self.waiver_reason is not None
        ):
            raise ValueError("an open completion criterion cannot retain resolution data")
        return self

    @computed_field
    @property
    def satisfied(self) -> bool:
        return self.status in {
            CompletionCriterionStatus.MET,
            CompletionCriterionStatus.WAIVED,
        }


class EvidenceRecord(StrictModel):
    id: str
    statement: str
    source: str
    recorded_at: datetime = Field(default_factory=utc_now)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "evidence ID")

    @field_validator("statement", "source")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "evidence")
        return _text(value, str(field_name))

    @field_validator("recorded_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence timestamp must include a timezone")
        return value


class Constraint(StrictModel):
    id: str
    statement: str
    owner: str | None = None
    active: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "constraint ID")

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _text(value, "constraint")

    @field_validator("owner")
    @classmethod
    def validate_owner(cls, value: str | None) -> str | None:
        return _optional_text(value, "constraint owner")


class Assumption(StrictModel):
    id: str
    statement: str
    status: AssumptionStatus = AssumptionStatus.OPEN
    validation_note: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "assumption ID")

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _text(value, "assumption")

    @field_validator("validation_note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        return _optional_text(value, "assumption validation note")


class Stakeholder(StrictModel):
    id: str
    name: str
    role: str
    influence: Literal["low", "medium", "high"] = "medium"
    interest: Literal["low", "medium", "high"] = "medium"
    communication: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "stakeholder ID")

    @field_validator("name", "role")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "stakeholder")
        return _text(value, str(field_name))

    @field_validator("communication")
    @classmethod
    def validate_communication(cls, value: str | None) -> str | None:
        return _optional_text(value, "communication plan")


class Phase(StrictModel):
    id: str
    title: str
    description: str | None = None
    owner: str | None = None
    status: WorkStatus = WorkStatus.PLANNED
    start_on: date | None = None
    due_on: date | None = None
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "phase ID")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _text(value, "phase title")

    @field_validator("description", "owner")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "phase field")))


class WorkPackage(StrictModel):
    id: str
    title: str
    description: str | None = None
    phase_id: str | None = None
    owner: str | None = None
    status: WorkStatus = WorkStatus.PLANNED
    duration_days: int = Field(ge=1)
    dependency_ids: list[str] = Field(default_factory=list)
    start_on: date | None = None
    due_on: date | None = None
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list, min_length=1)
    gtd_action_ids: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "work package ID")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _text(value, "work package title")

    @field_validator("description", "owner")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "work package field")))

    @field_validator("phase_id")
    @classmethod
    def validate_phase_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value, "phase ID")

    @field_validator("dependency_ids")
    @classmethod
    def validate_dependency_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "dependency ID")

    @field_validator("gtd_action_ids")
    @classmethod
    def validate_gtd_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "GTD action ID")


class Milestone(StrictModel):
    id: str
    title: str
    description: str | None = None
    phase_id: str | None = None
    owner: str | None = None
    status: MilestoneStatus = MilestoneStatus.PLANNED
    dependency_ids: list[str] = Field(default_factory=list)
    planned_on: date | None = None
    due_on: date | None = None
    achieved_on: date | None = None
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "milestone ID")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _text(value, "milestone title")

    @field_validator("description", "owner")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "milestone field")))

    @field_validator("phase_id")
    @classmethod
    def validate_phase_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value, "phase ID")

    @field_validator("dependency_ids")
    @classmethod
    def validate_dependency_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "dependency ID")

    @model_validator(mode="after")
    def validate_achievement(self) -> Milestone:
        if self.status is MilestoneStatus.ACHIEVED and self.achieved_on is None:
            raise ValueError("an achieved milestone requires achieved_on")
        if self.status is not MilestoneStatus.ACHIEVED and self.achieved_on is not None:
            raise ValueError("only an achieved milestone can have achieved_on")
        return self


class QcdSnapshot(StrictModel):
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    effort_hours: Decimal = Field(default=Decimal("0"), ge=0)
    quality_percent: Decimal | None = Field(default=None, ge=0, le=100)
    scope_units: Decimal = Field(default=Decimal("0"), ge=0)
    delivery_on: date | None = None


class QcdPlan(StrictModel):
    baseline: QcdSnapshot = Field(default_factory=QcdSnapshot)
    current: QcdSnapshot = Field(default_factory=QcdSnapshot)
    forecast: QcdSnapshot = Field(default_factory=QcdSnapshot)


class RegisterItem(StrictModel):
    id: str
    kind: RegisterItemKind
    title: str
    description: str | None = None
    owner: str | None = None
    status: RegisterItemStatus = RegisterItemStatus.OPEN
    probability: Decimal | None = Field(default=None, ge=0, le=1)
    impact_cost: Decimal = Field(default=Decimal("0"), ge=0)
    impact_days: int = Field(default=0, ge=0)
    response: str | None = None
    decision: str | None = None
    due_on: date | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "register item ID")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _text(value, "register title")

    @field_validator("description", "owner", "response", "decision")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "register field")))

    @model_validator(mode="after")
    def validate_probability(self) -> RegisterItem:
        if self.kind in {RegisterItemKind.RISK, RegisterItemKind.OPPORTUNITY}:
            if self.probability is None:
                raise ValueError("risk and opportunity items require probability")
        elif self.probability is not None:
            raise ValueError("only risk and opportunity items may have probability")
        return self

    @computed_field
    @property
    def expected_cost_exposure(self) -> Decimal | None:
        if self.probability is None:
            return None
        return (self.probability * self.impact_cost).quantize(Decimal("0.01"))


class Requirement(StrictModel):
    id: str
    title: str
    statement: str
    kind: RequirementKind = RequirementKind.FUNCTIONAL
    status: RequirementStatus = RequirementStatus.DRAFT
    source: str | None = None
    parent_id: str | None = None
    required_activities: list[VerificationActivity] = Field(
        default_factory=lambda: [VerificationActivity.VERIFICATION]
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "requirement ID")

    @field_validator("title", "statement")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        return _text(value, str(getattr(info, "field_name", "requirement field")))

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str | None) -> str | None:
        return _optional_text(value, "requirement source")

    @field_validator("parent_id")
    @classmethod
    def validate_parent_id(cls, value: str | None) -> str | None:
        return None if value is None else _id(value, "parent requirement ID")

    @field_validator("required_activities")
    @classmethod
    def validate_activities(cls, values: list[VerificationActivity]) -> list[VerificationActivity]:
        if not values:
            raise ValueError("a requirement needs at least one V&V activity")
        return list(dict.fromkeys(values))


class VerificationRecord(StrictModel):
    id: str
    activity: VerificationActivity
    method: VerificationMethod
    result: VerificationResult
    requirement_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    performed_at: datetime | None = None
    notes: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "verification record ID")

    @field_validator("requirement_ids")
    @classmethod
    def validate_requirement_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "requirement ID")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "evidence ID")

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str | None) -> str | None:
        return _optional_text(value, "verification notes")

    @model_validator(mode="after")
    def validate_result_evidence(self) -> VerificationRecord:
        if self.result is VerificationResult.PASS and not self.evidence_ids:
            raise ValueError("a passing V&V record requires evidence")
        if self.result is not VerificationResult.PLANNED and self.performed_at is None:
            raise ValueError("a completed V&V record requires performed_at")
        if self.performed_at is not None and (
            self.performed_at.tzinfo is None or self.performed_at.utcoffset() is None
        ):
            raise ValueError("V&V timestamp must include a timezone")
        return self


class GateReview(StrictModel):
    id: str
    title: str
    reviewed_at: datetime
    criterion_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    decision: GateDecision
    rationale: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "gate review ID")

    @field_validator("title", "rationale")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        return _text(value, str(getattr(info, "field_name", "gate field")))

    @field_validator("criterion_ids")
    @classmethod
    def validate_criterion_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "completion criterion ID")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "evidence ID")

    @field_validator("exceptions")
    @classmethod
    def validate_exceptions(cls, values: list[str]) -> list[str]:
        return [_text(value, "gate exception") for value in values]

    @field_validator("reviewed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("gate review timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> GateReview:
        if self.decision is GateDecision.CONDITIONAL_GO and not self.exceptions:
            raise ValueError("a conditional gate decision requires exceptions")
        if (
            self.decision in {GateDecision.GO, GateDecision.CONDITIONAL_GO}
            and not self.evidence_ids
        ):
            raise ValueError("a go gate decision requires evidence")
        return self


class ChangeRequest(StrictModel):
    id: str
    title: str
    kind: ChangeKind
    status: ChangeStatus = ChangeStatus.PROPOSED
    target_ids: list[str] = Field(default_factory=list)
    before: str
    after: str
    qcd_impact: str
    vv_impact: str
    decision: str | None = None
    rationale: str | None = None
    requested_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "change request ID")

    @field_validator("title", "before", "after", "qcd_impact", "vv_impact")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        return _text(value, str(getattr(info, "field_name", "change field")))

    @field_validator("target_ids")
    @classmethod
    def validate_target_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "change target ID")

    @field_validator("decision", "rationale")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "change field")))

    @field_validator("requested_at", "decided_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("change timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_resolution(self) -> ChangeRequest:
        decided = self.status in {
            ChangeStatus.APPROVED,
            ChangeStatus.REJECTED,
            ChangeStatus.IMPLEMENTED,
        }
        if decided and (self.decision is None or self.rationale is None or self.decided_at is None):
            raise ValueError("a decided change requires decision, rationale, and decided_at")
        if not decided and any(
            value is not None for value in (self.decision, self.rationale, self.decided_at)
        ):
            raise ValueError("a proposed change cannot retain decision data")
        return self


class BaselineRecord(StrictModel):
    id: str
    label: str
    project_revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", "event_id")
    @classmethod
    def validate_id(cls, value: str, info: object) -> str:
        return _id(value, str(getattr(info, "field_name", "baseline ID")))

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _text(value, "baseline label")

    @field_validator("created_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("baseline timestamp must include a timezone")
        return value


class ManagedProject(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    kind: Literal["managed_project"] = "managed_project"
    title: str
    goal: str
    lifecycle: ProjectLifecycle = ProjectLifecycle.PROPOSED
    sponsor: str | None = None
    manager: str | None = None
    planned_start_on: date | None = None
    target_due_on: date | None = None
    constraints: list[Constraint] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    completion_criteria: list[CompletionCriterion] = Field(min_length=1)
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    phases: list[Phase] = Field(default_factory=list)
    work_packages: list[WorkPackage] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    qcd: QcdPlan = Field(default_factory=QcdPlan)
    register_items: list[RegisterItem] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    verification_records: list[VerificationRecord] = Field(default_factory=list)
    gate_reviews: list[GateReview] = Field(default_factory=list)
    change_requests: list[ChangeRequest] = Field(default_factory=list)
    baselines: list[BaselineRecord] = Field(default_factory=list)
    publications: list[PublicationTarget] = Field(default_factory=list)
    gtd_action_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(default=1, ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _id(value, "managed project ID")

    @field_validator("title", "goal")
    @classmethod
    def validate_required_text(cls, value: str, info: object) -> str:
        return _text(value, str(getattr(info, "field_name", "project field")))

    @field_validator("sponsor", "manager")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        return _optional_text(value, str(getattr(info, "field_name", "project field")))

    @field_validator("gtd_action_ids")
    @classmethod
    def validate_gtd_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, "GTD action ID")

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("project timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_aggregate_identity(self) -> ManagedProject:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")

        ids: list[str] = []
        ids.extend(item.id for item in self.constraints)
        ids.extend(item.id for item in self.assumptions)
        ids.extend(item.id for item in self.completion_criteria)
        ids.extend(item.id for item in self.stakeholders)
        ids.extend(item.id for item in self.phases)
        ids.extend(item.id for item in self.work_packages)
        ids.extend(item.id for item in self.milestones)
        ids.extend(item.id for item in self.register_items)
        ids.extend(item.id for item in self.evidence)
        ids.extend(item.id for item in self.requirements)
        ids.extend(item.id for item in self.verification_records)
        ids.extend(item.id for item in self.gate_reviews)
        ids.extend(item.id for item in self.change_requests)
        ids.extend(item.id for item in self.baselines)
        for phase in self.phases:
            ids.extend(item.id for item in phase.completion_criteria)
        for work_package in self.work_packages:
            ids.extend(item.id for item in work_package.completion_criteria)
        for milestone in self.milestones:
            ids.extend(item.id for item in milestone.completion_criteria)
        folded = [item.casefold() for item in ids]
        if len(folded) != len(set(folded)):
            raise ValueError("nested IDs must be unique across a managed project")
        return self


class ManagedProjectDocument(StrictModel):
    project: ManagedProject
    body: str
    path: str


class ScheduleItem(StrictModel):
    id: str
    kind: Literal["work_package", "milestone"]
    title: str
    duration_days: int = Field(ge=0)
    dependency_ids: list[str]
    scheduled_start_on: date
    scheduled_finish_on: date
    due_on: date | None = None
    critical: bool = False
    total_float_days: int = Field(ge=0)
    constraint_violation: str | None = None


class ScheduleProjection(StrictModel):
    project_id: str
    anchor_on: date
    topological_order: list[str]
    critical_path: list[str]
    total_duration_days: int = Field(ge=0)
    items: list[ScheduleItem]


class QcdProjection(StrictModel):
    project_id: str
    current_cost_variance: Decimal
    forecast_cost_variance: Decimal
    forecast_cost_variance_percent: Decimal | None
    current_effort_variance: Decimal
    forecast_effort_variance: Decimal
    forecast_quality_variance: Decimal | None
    forecast_delivery_variance_days: int | None
    forecast_scope_variance: Decimal
    cost_health: Health
    delivery_health: Health
    quality_health: Health
    scope_health: Health
    overall_health: Health


class ProjectDoctorIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: Literal[
        "malformed_document",
        "duplicate_project_id",
        "missing_dependency",
        "dependency_cycle",
        "missing_phase",
        "broken_evidence_link",
        "broken_gtd_link",
        "wrong_gtd_link_kind",
        "schedule_constraint",
    ]
    message: str
    project_id: str | None = None
    nested_id: str | None = None
    path: str | None = None


class ProjectDoctorReport(StrictModel):
    checked_at: datetime = Field(default_factory=utc_now)
    issues: list[ProjectDoctorIssue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


__all__ = [
    "Assumption",
    "AssumptionStatus",
    "BaselineRecord",
    "ChangeKind",
    "ChangeRequest",
    "ChangeStatus",
    "CompletionCriterion",
    "CompletionCriterionStatus",
    "Constraint",
    "EvidenceRecord",
    "GateDecision",
    "GateReview",
    "Health",
    "ManagedProject",
    "ManagedProjectDocument",
    "Milestone",
    "MilestoneStatus",
    "Phase",
    "ProjectDoctorIssue",
    "ProjectDoctorReport",
    "ProjectLifecycle",
    "QcdPlan",
    "QcdProjection",
    "QcdSnapshot",
    "RegisterItem",
    "RegisterItemKind",
    "RegisterItemStatus",
    "Requirement",
    "RequirementKind",
    "RequirementStatus",
    "ScheduleItem",
    "ScheduleProjection",
    "Stakeholder",
    "WorkPackage",
    "WorkStatus",
    "VerificationActivity",
    "VerificationMethod",
    "VerificationRecord",
    "VerificationResult",
    "utc_now",
]
