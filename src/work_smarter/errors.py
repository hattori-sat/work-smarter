"""Application errors shared by the CLI, API, and future clients."""


class WorkSmarterError(Exception):
    """Base class for errors safe to present to a user."""


class WorkspaceNotInitializedError(WorkSmarterError):
    """Raised when a command targets a directory without a workspace."""


class EntityNotFoundError(WorkSmarterError):
    """Raised when an entity ID or unique prefix cannot be resolved."""


class AmbiguousEntityError(WorkSmarterError):
    """Raised when a short ID matches more than one entity."""


class InvalidTransitionError(WorkSmarterError):
    """Raised when a GTD state transition would violate the workflow."""


class WipLimitError(InvalidTransitionError):
    """Raised when another task is already in progress."""


class InvalidDocumentError(WorkSmarterError):
    """Raised when Markdown frontmatter is missing or invalid."""
