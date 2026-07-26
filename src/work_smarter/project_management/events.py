"""Namespaced audit-event contracts for managed projects."""

from __future__ import annotations

PROJECT_CREATED = "project_management.project.created"
PROJECT_UPDATED = "project_management.project.updated"
PROJECT_TRANSITIONED = "project_management.project.transitioned"
PHASE_ADDED = "project_management.phase.added"
PHASE_UPDATED = "project_management.phase.updated"
PHASE_TRANSITIONED = "project_management.phase.transitioned"
WORK_PACKAGE_ADDED = "project_management.work_package.added"
WORK_PACKAGE_UPDATED = "project_management.work_package.updated"
WORK_PACKAGE_TRANSITIONED = "project_management.work_package.transitioned"
MILESTONE_ADDED = "project_management.milestone.added"
MILESTONE_UPDATED = "project_management.milestone.updated"
MILESTONE_TRANSITIONED = "project_management.milestone.transitioned"
REGISTER_ITEM_ADDED = "project_management.register_item.added"
REGISTER_ITEM_UPDATED = "project_management.register_item.updated"
EVIDENCE_RECORDED = "project_management.evidence.recorded"
COMPLETION_CRITERION_UPDATED = "project_management.completion_criterion.updated"
REQUIREMENT_ADDED = "project_management.requirement.added"
REQUIREMENT_UPDATED = "project_management.requirement.updated"
VERIFICATION_RECORDED = "project_management.verification.recorded"
GATE_REVIEW_RECORDED = "project_management.gate_review.recorded"
CHANGE_REQUEST_ADDED = "project_management.change_request.added"
CHANGE_REQUEST_UPDATED = "project_management.change_request.updated"
BASELINE_CREATED = "project_management.baseline.created"

__all__ = [name for name in globals() if name.isupper()]
