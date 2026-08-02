"""Provider-neutral relational persistence contracts."""

from work_smarter.shared.persistence.database import (
    DatabaseBackend,
    DatabaseBackendRegistry,
    DatabaseConfiguration,
    DatabaseMigrationReport,
    DatabaseSnapshot,
    DatabaseStatus,
    create_database_backend,
    default_database_registry,
)

__all__ = [
    "DatabaseBackend",
    "DatabaseBackendRegistry",
    "DatabaseConfiguration",
    "DatabaseMigrationReport",
    "DatabaseSnapshot",
    "DatabaseStatus",
    "create_database_backend",
    "default_database_registry",
]
