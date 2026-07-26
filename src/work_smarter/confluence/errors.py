"""Stable domain errors for Confluence publishing."""

from __future__ import annotations

from work_smarter.errors import WorkSmarterError


class ConfluenceError(WorkSmarterError):
    """Base class for provider and synchronization failures."""


class ConfluenceCredentialError(ConfluenceError):
    """Required credentials are missing or unsafe."""


class ConfluenceTransportError(ConfluenceError):
    """The provider could not be reached or returned an invalid response."""


class ConfluenceAuthenticationError(ConfluenceError):
    """The credential lacks authentication or authorization."""


class ConfluenceNotFoundError(ConfluenceError):
    """A mapped page or space does not exist."""


class ConfluenceConflictError(ConfluenceError):
    """The remote rejected a stale or conflicting update."""


class ConfluenceRateLimitError(ConfluenceError):
    """The provider asked the client to retry later."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ConfluenceSyncConflictError(ConfluenceConflictError):
    """Local and remote content cannot be reconciled without an explicit choice."""


__all__ = [
    "ConfluenceAuthenticationError",
    "ConfluenceConflictError",
    "ConfluenceCredentialError",
    "ConfluenceError",
    "ConfluenceNotFoundError",
    "ConfluenceRateLimitError",
    "ConfluenceSyncConflictError",
    "ConfluenceTransportError",
]
