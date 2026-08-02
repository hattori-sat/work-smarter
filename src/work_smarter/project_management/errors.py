"""Stable errors owned by the managed-project feature."""

from __future__ import annotations

from work_smarter.errors import WorkSmarterError


class ProjectManagementError(WorkSmarterError):
    """Base class for errors safe to expose through CLI and HTTP adapters."""


class ProjectItemNotFoundError(ProjectManagementError):
    """Raised when a nested stable ID cannot be resolved."""


class ProjectConflictError(ProjectManagementError):
    """Raised when an edit would violate aggregate identity invariants."""


class ProjectTransitionError(ProjectManagementError):
    """Raised for a disallowed lifecycle or work-state transition."""


class ProjectCompletionGateError(ProjectTransitionError):
    """Raised when declared completion evidence or child delivery is incomplete."""


class ProjectScheduleError(ProjectManagementError):
    """Raised when a dependency graph is incomplete or cyclic."""


class ProjectLinkError(ProjectManagementError):
    """Raised for an invalid stable link to another feature."""


__all__ = [
    "ProjectCompletionGateError",
    "ProjectConflictError",
    "ProjectItemNotFoundError",
    "ProjectLinkError",
    "ProjectManagementError",
    "ProjectScheduleError",
    "ProjectTransitionError",
]
