"""Relational persistence shared by application modules."""

from work_smarter.shared.persistence.database import (
    LATEST_SCHEMA_VERSION,
    ApplicationDatabase,
    DatabaseMigrationReport,
    DatabaseStatus,
)

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "ApplicationDatabase",
    "DatabaseMigrationReport",
    "DatabaseStatus",
]
