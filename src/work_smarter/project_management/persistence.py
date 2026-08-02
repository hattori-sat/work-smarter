"""Managed-project entity codec and explicit frontmatter migrations."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

from work_smarter.project_management.models import ManagedProject
from work_smarter.shared.persistence.database import (
    StructuredStateBackend,
    create_database_backend,
)
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace

CURRENT_PROJECT_SCHEMA_VERSION = 1
PROJECT_MANAGEMENT_ENTITY_SPECS = (
    EntitySpec("managed_project", ManagedProject, "projects/managed"),
)
PROJECT_MANAGEMENT_ENTITY_REGISTRY = EntityRegistry(PROJECT_MANAGEMENT_ENTITY_SPECS)


def migrate_project_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """Return current metadata without mutating a hand-edited source mapping.

    Version 0 was the pre-release shape with ``status`` instead of
    ``lifecycle``.  Migration is explicit rather than silently performed by a
    normal read so users can inspect a diff before durable files are changed.
    """

    migrated = deepcopy(dict(metadata))
    version = migrated.get("schema_version", 0)
    if version == CURRENT_PROJECT_SCHEMA_VERSION:
        return migrated
    if version == 0:
        migrated["schema_version"] = CURRENT_PROJECT_SCHEMA_VERSION
        if "status" in migrated and "lifecycle" not in migrated:
            migrated["lifecycle"] = migrated.pop("status")
        return migrated
    raise ValueError(f"unsupported managed project schema version: {version!r}")


def initialize_workspace(root: Path | str) -> Workspace:
    return Workspace.initialize(root, PROJECT_MANAGEMENT_ENTITY_REGISTRY)


def open_workspace(root: Path | str) -> Workspace:
    probe = Workspace.open(root, PROJECT_MANAGEMENT_ENTITY_REGISTRY)
    database = create_database_backend(probe.root, probe.settings().database)
    database.migrate()
    store = database.structured_store if isinstance(database, StructuredStateBackend) else None
    return Workspace.open(root, PROJECT_MANAGEMENT_ENTITY_REGISTRY, structured_store=store)


__all__ = [
    "CURRENT_PROJECT_SCHEMA_VERSION",
    "PROJECT_MANAGEMENT_ENTITY_REGISTRY",
    "PROJECT_MANAGEMENT_ENTITY_SPECS",
    "initialize_workspace",
    "migrate_project_metadata",
    "open_workspace",
]
