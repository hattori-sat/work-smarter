"""Independent, text-first managed-project feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from work_smarter.project_management.models import (
    Assumption,
    AssumptionStatus,
    CompletionCriterion,
    CompletionCriterionStatus,
    Constraint,
    EvidenceRecord,
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
    QcdSnapshot,
    RegisterItem,
    RegisterItemKind,
    RegisterItemStatus,
    ScheduleItem,
    ScheduleProjection,
    Stakeholder,
    WorkPackage,
    WorkStatus,
)

if TYPE_CHECKING:
    from work_smarter.features import FeatureRegistry


class ProjectManagementFeature:
    """Feature descriptor composed without importing another product feature."""

    name = "project-management"
    version = "0.1"

    def register(self, registry: FeatureRegistry) -> None:
        from work_smarter.project_management.persistence import PROJECT_MANAGEMENT_ENTITY_SPECS
        from work_smarter.project_management.templates import (
            initialize_project_management_templates,
        )

        for spec in PROJECT_MANAGEMENT_ENTITY_SPECS:
            registry.add_entity(spec)
        registry.add_workspace_initializer(initialize_project_management_templates)


def __getattr__(name: str) -> Any:
    if name == "ProjectManagementService":
        from work_smarter.project_management.service import ProjectManagementService

        return ProjectManagementService
    raise AttributeError(name)


__all__ = [
    "Assumption",
    "AssumptionStatus",
    "CompletionCriterion",
    "CompletionCriterionStatus",
    "Constraint",
    "EvidenceRecord",
    "Health",
    "ManagedProject",
    "ManagedProjectDocument",
    "Milestone",
    "MilestoneStatus",
    "Phase",
    "ProjectDoctorIssue",
    "ProjectDoctorReport",
    "ProjectLifecycle",
    "ProjectManagementFeature",
    "ProjectManagementService",
    "QcdPlan",
    "QcdProjection",
    "QcdSnapshot",
    "RegisterItem",
    "RegisterItemKind",
    "RegisterItemStatus",
    "ScheduleItem",
    "ScheduleProjection",
    "Stakeholder",
    "WorkPackage",
    "WorkStatus",
]
