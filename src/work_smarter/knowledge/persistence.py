"""Knowledge-owned entity codecs for generic Markdown workspace storage."""

from __future__ import annotations

from pathlib import Path

from work_smarter.knowledge.models import KnowledgeNote
from work_smarter.shared.persistence.database import (
    StructuredStateBackend,
    create_database_backend,
)
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace

KNOWLEDGE_ENTITY_SPECS = (EntitySpec("knowledge_note", KnowledgeNote, "knowledge/notes"),)
KNOWLEDGE_ENTITY_REGISTRY = EntityRegistry(KNOWLEDGE_ENTITY_SPECS)


def initialize_workspace(root: Path | str) -> Workspace:
    """Initialize a workspace containing only the knowledge feature."""

    return Workspace.initialize(root, KNOWLEDGE_ENTITY_REGISTRY)


def open_workspace(root: Path | str) -> Workspace:
    """Open a workspace containing only the knowledge feature."""

    probe = Workspace.open(root, KNOWLEDGE_ENTITY_REGISTRY)
    database = create_database_backend(probe.root, probe.settings().database)
    database.migrate()
    store = database.structured_store if isinstance(database, StructuredStateBackend) else None
    return Workspace.open(root, KNOWLEDGE_ENTITY_REGISTRY, structured_store=store)


__all__ = [
    "KNOWLEDGE_ENTITY_REGISTRY",
    "KNOWLEDGE_ENTITY_SPECS",
    "initialize_workspace",
    "open_workspace",
]
