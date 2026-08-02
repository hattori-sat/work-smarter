"""Knowledge-specific errors safe to expose through adapters."""

from __future__ import annotations

from work_smarter.errors import WorkSmarterError


class KnowledgeError(WorkSmarterError):
    """Base class for knowledge feature errors."""


class KnowledgeConflictError(KnowledgeError):
    """Raised when a stable ID or alias would no longer be unique."""


class KnowledgeLinkError(KnowledgeError):
    """Raised when a link would violate knowledge graph invariants."""


class KnowledgeImportError(KnowledgeError):
    """Raised when a generic workspace record cannot be promoted."""


class MarpCompilerUnavailableError(KnowledgeError):
    """Raised when HTML preview is requested without an available compiler."""


class MarpCompilationError(KnowledgeError):
    """Raised when the configured Marp compiler refuses a presentation."""


__all__ = [
    "KnowledgeConflictError",
    "KnowledgeError",
    "KnowledgeImportError",
    "KnowledgeLinkError",
    "MarpCompilationError",
    "MarpCompilerUnavailableError",
]
