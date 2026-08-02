"""GTD-owned entity codecs composed with generic workspace storage."""

from __future__ import annotations

from pathlib import Path

from work_smarter.gtd.models import (
    ArchivedInboxItem,
    GtdProject,
    InboxItem,
    Reference,
    SomedayItem,
    Task,
    WeeklyReviewSession,
)
from work_smarter.shared.persistence.database import (
    StructuredStateBackend,
    create_database_backend,
)
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace

GTD_ENTITY_SPECS = (
    EntitySpec("inbox", InboxItem, "inbox"),
    EntitySpec("task", Task, "tasks"),
    EntitySpec("gtd_project", GtdProject, "gtd/projects"),
    EntitySpec("reference", Reference, "knowledge/gtd"),
    EntitySpec("someday", SomedayItem, "someday"),
    EntitySpec("inbox_archive", ArchivedInboxItem, "archive/inbox", archived=True),
    EntitySpec("weekly_review", WeeklyReviewSession, "gtd/reviews"),
)
GTD_ENTITY_REGISTRY = EntityRegistry(GTD_ENTITY_SPECS)


def initialize_workspace(root: Path | str) -> Workspace:
    return Workspace.initialize(root, GTD_ENTITY_REGISTRY)


def open_workspace(root: Path | str) -> Workspace:
    probe = Workspace.open(root, GTD_ENTITY_REGISTRY)
    database = create_database_backend(probe.root, probe.settings().database)
    database.migrate()
    store = database.structured_store if isinstance(database, StructuredStateBackend) else None
    return Workspace.open(root, GTD_ENTITY_REGISTRY, structured_store=store)
