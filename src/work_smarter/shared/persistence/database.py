"""SQLite application database and forward-only schema migrations."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from work_smarter.errors import InvalidDocumentError

DATABASE_NAME = "work-smarter.db"
LATEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    initialized: bool
    schema_version: int
    latest_schema_version: int = LATEST_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class DatabaseMigrationReport:
    schema_version: int
    applied_versions: list[int]


def _apply_foundation_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE activity_events (
            id TEXT PRIMARY KEY,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_version INTEGER NOT NULL CHECK (event_version >= 1),
            occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            actor TEXT,
            correlation_id TEXT,
            causation_id TEXT,
            payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload))
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE INDEX activity_events_aggregate
        ON activity_events(aggregate_type, aggregate_id, occurred_at)
        """
    )
    connection.execute(
        """
        CREATE TRIGGER activity_events_no_update
        BEFORE UPDATE ON activity_events
        BEGIN
            SELECT RAISE(ABORT, 'activity_events are append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER activity_events_no_delete
        BEFORE DELETE ON activity_events
        BEGIN
            SELECT RAISE(ABORT, 'activity_events are append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TABLE outbox_items (
            id TEXT PRIMARY KEY,
            operation_id TEXT NOT NULL UNIQUE,
            destination TEXT NOT NULL,
            message_type TEXT NOT NULL,
            payload TEXT NOT NULL CHECK (json_valid(payload)),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            available_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT,
            last_error TEXT
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE INDEX outbox_items_delivery
        ON outbox_items(status, available_at)
        """
    )


MIGRATIONS = ((1, "architecture_foundation", _apply_foundation_schema),)


class ApplicationDatabase:
    """Own the application database without exposing SQLite to domain modules."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()

    @classmethod
    def for_workspace(cls, workspace_root: Path | str) -> ApplicationDatabase:
        return cls(Path(workspace_root) / ".work-smarter" / DATABASE_NAME)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def status(self) -> DatabaseStatus:
        if not self.path.is_file():
            return DatabaseStatus(initialized=False, schema_version=0)
        try:
            with closing(self._connect()) as connection:
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if table is None:
                    return DatabaseStatus(initialized=False, schema_version=0)
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise InvalidDocumentError(f"Invalid application database {self.path}: {exc}") from exc
        return DatabaseStatus(initialized=True, schema_version=int(row[0]))

    def verify(self) -> DatabaseStatus:
        """Verify SQLite integrity and the Work Smarter schema without modifying it."""

        if not self.path.is_file():
            raise InvalidDocumentError(f"Application database is missing: {self.path}")
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                if integrity != ("ok",):
                    detail = integrity[0] if integrity else "no integrity result"
                    raise InvalidDocumentError(
                        f"Invalid application database {self.path}: {detail}"
                    )
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if table is None:
                    raise InvalidDocumentError(
                        f"Invalid application database {self.path}: migration metadata is missing"
                    )
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise InvalidDocumentError(f"Invalid application database {self.path}: {exc}") from exc
        version = int(row[0])
        if version > LATEST_SCHEMA_VERSION:
            raise InvalidDocumentError(
                f"Database schema {version} is newer than this application "
                f"(latest {LATEST_SCHEMA_VERSION})"
            )
        return DatabaseStatus(initialized=True, schema_version=version)

    def snapshot(self, destination: Path | str) -> Path:
        """Create an atomic, transactionally consistent online SQLite snapshot."""

        target = Path(destination).expanduser().resolve()
        if target == self.path:
            raise InvalidDocumentError("Database snapshot destination must differ from source")
        if not self.path.is_file():
            raise InvalidDocumentError(f"Application database is missing: {self.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
            with (
                closing(self._connect()) as source,
                closing(sqlite3.connect(temporary, timeout=5)) as snapshot,
            ):
                source.backup(snapshot)
            ApplicationDatabase(temporary).verify()
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except InvalidDocumentError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise InvalidDocumentError(
                f"Cannot snapshot application database {self.path}: {exc}"
            ) from exc
        return target

    def migrate(self) -> DatabaseMigrationReport:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        applied: list[int] = []
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    ) STRICT
                    """
                )
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
                current = int(row[0])
                if current > LATEST_SCHEMA_VERSION:
                    raise InvalidDocumentError(
                        f"Database schema {current} is newer than this application "
                        f"(latest {LATEST_SCHEMA_VERSION})"
                    )
                for version, name, apply in MIGRATIONS:
                    if version <= current:
                        continue
                    apply(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                        (version, name),
                    )
                    applied.append(version)
                    current = version
        except sqlite3.DatabaseError as exc:
            raise InvalidDocumentError(
                f"Cannot migrate application database {self.path}: {exc}"
            ) from exc
        return DatabaseMigrationReport(schema_version=current, applied_versions=applied)
