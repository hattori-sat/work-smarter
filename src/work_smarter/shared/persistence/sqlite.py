"""SQLite adapter for the provider-neutral application database port."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from work_smarter.errors import EntityNotFoundError, InvalidDocumentError
from work_smarter.shared.persistence.database import (
    DatabaseConfiguration,
    DatabaseMigrationReport,
    DatabaseSnapshot,
    DatabaseStatus,
    OperationJournalRecord,
    OutboxMessage,
    StructuredEntityState,
)

DEFAULT_DATABASE_MEMBER = ".work-smarter/work-smarter.db"
LATEST_SCHEMA_VERSION = 2


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


def _apply_structured_state_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE application_markers (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE TABLE structured_entities (
            kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload TEXT NOT NULL CHECK (json_valid(payload)),
            projection_path TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (kind, entity_id)
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE TABLE operation_journal (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL
                CHECK (operation_type IN ('entity.write', 'entity.delete')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'completed', 'failed')),
            aggregate_kind TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload TEXT NOT NULL CHECK (json_valid(payload)),
            projection_path TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT,
            last_error TEXT
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE INDEX operation_journal_recovery
        ON operation_journal(status, created_at)
        """
    )
    connection.execute("ALTER TABLE outbox_items ADD COLUMN lease_token TEXT")
    connection.execute("ALTER TABLE outbox_items ADD COLUMN locked_at TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS outbox_items_delivery
        ON outbox_items(status, available_at)
        """
    )


MIGRATIONS = (
    (1, "architecture_foundation", _apply_foundation_schema),
    (2, "structured_state_and_operation_journal", _apply_structured_state_schema),
)


class SQLiteDatabaseBackend:
    """SQLite implementation isolated from application and domain modules."""

    name = "sqlite"

    def __init__(
        self,
        workspace_root: Path | str,
        configuration: DatabaseConfiguration,
    ) -> None:
        if configuration.backend != self.name:
            raise ValueError(f"SQLite adapter cannot serve {configuration.backend!r}")
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        relative = Path(configuration.location or DEFAULT_DATABASE_MEMBER)
        if relative.is_absolute():
            raise InvalidDocumentError("SQLite database location must be workspace-relative")
        candidate = self.workspace_root / relative
        if candidate.is_symlink():
            raise InvalidDocumentError(
                "application database must be a regular file inside the workspace"
            )
        self.path = candidate.resolve()
        if not self.path.is_relative_to(self.workspace_root):
            raise InvalidDocumentError("SQLite database location escapes the workspace")
        self.archive_member = self.path.relative_to(self.workspace_root).as_posix()
        self.workspace_members = frozenset(
            {
                self.archive_member,
                f"{self.archive_member}-journal",
                f"{self.archive_member}-shm",
                f"{self.archive_member}-wal",
            }
        )

    @classmethod
    def for_path(cls, path: Path | str) -> SQLiteDatabaseBackend:
        resolved = Path(path).expanduser().resolve()
        return cls(
            resolved.parent,
            DatabaseConfiguration(backend="sqlite", location=resolved.name),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @property
    def structured_store(self) -> SQLiteStructuredStateStore:
        """Expose provider-neutral domain state without leaking sqlite3 upstream."""

        return SQLiteStructuredStateStore(self)

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
            return DatabaseStatus(
                initialized=False,
                schema_version=0,
                latest_schema_version=LATEST_SCHEMA_VERSION,
            )
        try:
            with closing(self._connect()) as connection:
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if table is None:
                    return DatabaseStatus(
                        initialized=False,
                        schema_version=0,
                        latest_schema_version=LATEST_SCHEMA_VERSION,
                    )
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise InvalidDocumentError(f"Invalid application database {self.path}: {exc}") from exc
        return DatabaseStatus(
            initialized=True,
            schema_version=int(row[0]),
            latest_schema_version=LATEST_SCHEMA_VERSION,
        )

    @staticmethod
    def _verify_path(path: Path) -> DatabaseStatus:
        if not path.is_file():
            raise InvalidDocumentError(f"Application database is missing: {path}")
        try:
            with closing(sqlite3.connect(path, timeout=5)) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                if integrity != ("ok",):
                    detail = integrity[0] if integrity else "no integrity result"
                    raise InvalidDocumentError(f"Invalid application database {path}: {detail}")
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if table is None:
                    raise InvalidDocumentError(
                        f"Invalid application database {path}: migration metadata is missing"
                    )
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise InvalidDocumentError(f"Invalid application database {path}: {exc}") from exc
        version = int(row[0])
        if version > LATEST_SCHEMA_VERSION:
            raise InvalidDocumentError(
                f"Database schema {version} is newer than this application "
                f"(latest {LATEST_SCHEMA_VERSION})"
            )
        return DatabaseStatus(
            initialized=True,
            schema_version=version,
            latest_schema_version=LATEST_SCHEMA_VERSION,
        )

    def verify(self) -> DatabaseStatus:
        return self._verify_path(self.path)

    def verify_snapshot(self, path: Path) -> DatabaseStatus:
        return self._verify_path(path)

    def snapshot(self, destination: Path | str) -> Path:
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
            self._verify_path(temporary)
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

    def create_snapshot(self, destination: Path) -> DatabaseSnapshot:
        path = self.snapshot(destination / Path(self.archive_member).name)
        return DatabaseSnapshot(
            backend=self.name,
            archive_member=self.archive_member,
            path=path,
        )

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


class SQLiteStructuredStateStore:
    """SQLite implementation of structured entity, journal, and outbox ports."""

    def __init__(self, backend: SQLiteDatabaseBackend) -> None:
        self.backend = backend

    def legacy_import_completed(self) -> bool:
        with closing(self.backend._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM application_markers WHERE key = 'legacy_import_v1'"
            ).fetchone()
        return row is not None and str(row["value"]) == "completed"

    def complete_legacy_import(self) -> None:
        with self.backend.transaction() as connection:
            connection.execute(
                """
                INSERT INTO application_markers(key, value)
                VALUES ('legacy_import_v1', 'completed')
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """
            )

    @staticmethod
    def _dump(payload: dict[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load(payload: str) -> dict[str, object]:
        loaded = json.loads(payload)
        if not isinstance(loaded, dict):
            raise InvalidDocumentError("Database JSON payload must be an object")
        return loaded

    @classmethod
    def _entity(cls, row: sqlite3.Row) -> StructuredEntityState:
        return StructuredEntityState(
            kind=str(row["kind"]),
            entity_id=str(row["entity_id"]),
            payload=cls._load(str(row["payload"])),
            projection_path=str(row["projection_path"]),
            revision=int(row["revision"]),
        )

    @classmethod
    def _operation(cls, row: sqlite3.Row) -> OperationJournalRecord:
        return OperationJournalRecord(
            id=str(row["id"]),
            operation_type=str(row["operation_type"]),
            status=str(row["status"]),
            aggregate_kind=str(row["aggregate_kind"]),
            aggregate_id=str(row["aggregate_id"]),
            payload=cls._load(str(row["payload"])),
            projection_path=str(row["projection_path"]),
            idempotency_key=str(row["idempotency_key"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        )

    @classmethod
    def _outbox(cls, row: sqlite3.Row) -> OutboxMessage:
        return OutboxMessage(
            id=str(row["id"]),
            operation_id=str(row["operation_id"]),
            destination=str(row["destination"]),
            message_type=str(row["message_type"]),
            payload=cls._load(str(row["payload"])),
            status=str(row["status"]),
            attempt_count=int(row["attempt_count"]),
            available_at=str(row["available_at"]),
            lease_token=str(row["lease_token"]) if row["lease_token"] is not None else None,
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        )

    def stage_entity_write(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        kind: str,
        entity_id: str,
        payload: dict[str, object],
        projection_path: str,
    ) -> OperationJournalRecord:
        encoded = self._dump(payload)
        with self.backend.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO operation_journal(
                        id, operation_type, aggregate_kind, aggregate_id,
                        payload, projection_path, idempotency_key
                    ) VALUES (?, 'entity.write', ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        kind,
                        entity_id,
                        encoded,
                        projection_path,
                        idempotency_key,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM operation_journal
                    WHERE idempotency_key = ? OR id = ?
                    ORDER BY created_at LIMIT 1
                    """,
                    (idempotency_key, operation_id),
                ).fetchone()
                if row is None:
                    raise
                existing = self._operation(row)
                expected = (
                    existing.operation_type == "entity.write"
                    and existing.aggregate_kind == kind
                    and existing.aggregate_id == entity_id
                    and existing.payload == payload
                    and existing.projection_path == projection_path
                    and existing.idempotency_key == idempotency_key
                )
                if not expected:
                    raise InvalidDocumentError(
                        f"Idempotency key {idempotency_key!r} was reused for another operation"
                    ) from None
                return existing
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded by the transaction above
                raise InvalidDocumentError(f"Operation journal write failed: {operation_id}")
            return self._operation(row)

    def commit_entity_write(self, operation_id: str) -> StructuredEntityState:
        with self.backend.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"Operation not found: {operation_id}")
            operation = self._operation(row)
            if operation.status == "failed":
                raise InvalidDocumentError(f"Operation {operation_id} has failed")
            if operation.status == "pending":
                connection.execute(
                    """
                    INSERT INTO structured_entities(
                        kind, entity_id, payload, projection_path, revision
                    ) VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(kind, entity_id) DO UPDATE SET
                        payload = excluded.payload,
                        projection_path = excluded.projection_path,
                        revision = structured_entities.revision + 1,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        operation.aggregate_kind,
                        operation.aggregate_id,
                        self._dump(operation.payload),
                        operation.projection_path,
                    ),
                )
                entity_row = connection.execute(
                    """
                    SELECT * FROM structured_entities
                    WHERE kind = ? AND entity_id = ?
                    """,
                    (operation.aggregate_kind, operation.aggregate_id),
                ).fetchone()
                if entity_row is None:  # pragma: no cover - guarded by upsert
                    raise InvalidDocumentError("Structured entity commit failed")
                entity = self._entity(entity_row)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_events(
                        id, aggregate_type, aggregate_id, event_type,
                        event_version, correlation_id, payload
                    ) VALUES (?, ?, ?, 'workspace.entity.saved', 1, ?, ?)
                    """,
                    (
                        f"EVT-{operation.id}",
                        operation.aggregate_kind,
                        operation.aggregate_id,
                        operation.id,
                        self._dump({"revision": entity.revision}),
                    ),
                )
                connection.execute(
                    """
                    UPDATE operation_journal
                    SET status = 'completed',
                        completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                        last_error = NULL
                    WHERE id = ? AND status = 'pending'
                    """,
                    (operation_id,),
                )
                return entity
            entity_row = connection.execute(
                """
                SELECT * FROM structured_entities
                WHERE kind = ? AND entity_id = ?
                """,
                (operation.aggregate_kind, operation.aggregate_id),
            ).fetchone()
            if entity_row is None:
                raise InvalidDocumentError(
                    f"Completed operation {operation_id} has no structured entity"
                )
            return self._entity(entity_row)

    def stage_entity_delete(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        kind: str,
        entity_id: str,
        projection_path: str,
    ) -> OperationJournalRecord:
        with self.backend.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO operation_journal(
                        id, operation_type, aggregate_kind, aggregate_id,
                        payload, projection_path, idempotency_key
                    ) VALUES (?, 'entity.delete', ?, ?, '{}', ?, ?)
                    """,
                    (operation_id, kind, entity_id, projection_path, idempotency_key),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM operation_journal
                    WHERE idempotency_key = ? OR id = ?
                    ORDER BY created_at LIMIT 1
                    """,
                    (idempotency_key, operation_id),
                ).fetchone()
                if row is None:
                    raise
                existing = self._operation(row)
                if not (
                    existing.operation_type == "entity.delete"
                    and existing.aggregate_kind == kind
                    and existing.aggregate_id == entity_id
                    and existing.projection_path == projection_path
                    and existing.idempotency_key == idempotency_key
                ):
                    raise InvalidDocumentError(
                        f"Idempotency key {idempotency_key!r} was reused for another operation"
                    ) from None
                return existing
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:  # pragma: no cover
                raise InvalidDocumentError(f"Operation journal write failed: {operation_id}")
            return self._operation(row)

    def commit_entity_delete(self, operation_id: str) -> None:
        with self.backend.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"Operation not found: {operation_id}")
            operation = self._operation(row)
            if operation.operation_type != "entity.delete":
                raise InvalidDocumentError(f"Operation {operation_id} is not an entity delete")
            if operation.status == "failed":
                raise InvalidDocumentError(f"Operation {operation_id} has failed")
            if operation.status == "completed":
                return
            connection.execute(
                "DELETE FROM structured_entities WHERE kind = ? AND entity_id = ?",
                (operation.aggregate_kind, operation.aggregate_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    id, aggregate_type, aggregate_id, event_type,
                    event_version, correlation_id, payload
                ) VALUES (?, ?, ?, 'workspace.entity.deleted', 1, ?, '{}')
                """,
                (
                    f"EVT-{operation.id}",
                    operation.aggregate_kind,
                    operation.aggregate_id,
                    operation.id,
                ),
            )
            connection.execute(
                """
                UPDATE operation_journal
                SET status = 'completed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    last_error = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (operation_id,),
            )

    def fail_operation(self, operation_id: str, error: str) -> OperationJournalRecord:
        with self.backend.transaction() as connection:
            connection.execute(
                """
                UPDATE operation_journal
                SET status = 'failed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    last_error = ?
                WHERE id = ? AND status = 'pending'
                """,
                (error[:2000], operation_id),
            )
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"Operation not found: {operation_id}")
            return self._operation(row)

    def pending_operations(self) -> list[OperationJournalRecord]:
        with closing(self.backend._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM operation_journal
                WHERE status = 'pending' ORDER BY created_at, id
                """
            ).fetchall()
        return [self._operation(row) for row in rows]

    def get_operation(self, operation_id: str) -> OperationJournalRecord:
        with closing(self.backend._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM operation_journal WHERE id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError(f"Operation not found: {operation_id}")
        return self._operation(row)

    def list_operations(self, *, limit: int = 100) -> list[OperationJournalRecord]:
        bounded = max(1, min(limit, 1000))
        with closing(self.backend._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM operation_journal
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [self._operation(row) for row in rows]

    def import_entity(
        self,
        *,
        kind: str,
        entity_id: str,
        payload: dict[str, object],
        projection_path: str,
    ) -> StructuredEntityState:
        encoded = self._dump(payload)
        with self.backend.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO structured_entities(
                    kind, entity_id, payload, projection_path, revision
                ) VALUES (?, ?, ?, ?, 1)
                """,
                (kind, entity_id, encoded, projection_path),
            )
            if cursor.rowcount:
                event_id = f"EVT-IMPORT-{kind}-{entity_id}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_events(
                        id, aggregate_type, aggregate_id, event_type,
                        event_version, payload
                    ) VALUES (?, ?, ?, 'workspace.entity.imported', 1, '{}')
                    """,
                    (event_id, kind, entity_id),
                )
            row = connection.execute(
                """
                SELECT * FROM structured_entities
                WHERE kind = ? AND entity_id = ?
                """,
                (kind, entity_id),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded by insert/select
                raise InvalidDocumentError("Legacy entity import failed")
            return self._entity(row)

    def get_entity(self, kind: str, entity_id: str) -> StructuredEntityState | None:
        with closing(self.backend._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM structured_entities
                WHERE kind = ? AND entity_id = ?
                """,
                (kind, entity_id),
            ).fetchone()
        return self._entity(row) if row is not None else None

    def list_entities(self, kind: str) -> list[StructuredEntityState]:
        with closing(self.backend._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM structured_entities
                WHERE kind = ? ORDER BY entity_id
                """,
                (kind,),
            ).fetchall()
        return [self._entity(row) for row in rows]

    def append_activity_event(self, event: dict[str, object]) -> dict[str, object]:
        event_id = str(event.get("id", "")).strip()
        event_type = str(event.get("type", "")).strip()
        entity_id = str(event.get("entity_id") or "workspace")
        occurred_at = str(event.get("occurred_at", "")).strip()
        schema_version = int(event.get("schema_version", 1))
        raw_payload = event.get("payload", {})
        if not event_id or not event_type or not occurred_at or not isinstance(raw_payload, dict):
            raise InvalidDocumentError("Activity event requires id, type, time, and object payload")
        aggregate_type = event_type.split(".", maxsplit=1)[0]
        with self.backend.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    id, aggregate_type, aggregate_id, event_type,
                    event_version, occurred_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    aggregate_type,
                    entity_id,
                    event_type,
                    schema_version,
                    occurred_at,
                    self._dump(raw_payload),
                ),
            )
            row = connection.execute(
                "SELECT * FROM activity_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:  # pragma: no cover
                raise InvalidDocumentError("Activity event append failed")
            stored = self._activity_event(row)
            expected = {
                "schema_version": schema_version,
                "id": event_id,
                "type": event_type,
                "occurred_at": occurred_at,
                "entity_id": entity_id,
                "payload": raw_payload,
            }
            if stored != expected:
                raise InvalidDocumentError(f"Activity event ID {event_id!r} was reused")
            return stored

    @classmethod
    def _activity_event(cls, row: sqlite3.Row) -> dict[str, object]:
        return {
            "schema_version": int(row["event_version"]),
            "id": str(row["id"]),
            "type": str(row["event_type"]),
            "occurred_at": str(row["occurred_at"]),
            "entity_id": str(row["aggregate_id"]),
            "payload": cls._load(str(row["payload"])),
        }

    def list_activity_events(self) -> list[dict[str, object]]:
        with closing(self.backend._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM activity_events
                ORDER BY occurred_at, id
                """
            ).fetchall()
        return [self._activity_event(row) for row in rows]

    def enqueue_outbox(
        self,
        *,
        message_id: str,
        operation_id: str,
        destination: str,
        message_type: str,
        payload: dict[str, object],
        available_at: str,
    ) -> OutboxMessage:
        encoded = self._dump(payload)
        with self.backend.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO outbox_items(
                        id, operation_id, destination, message_type, payload, available_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        operation_id,
                        destination,
                        message_type,
                        encoded,
                        available_at,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM outbox_items
                    WHERE operation_id = ? OR id = ?
                    ORDER BY created_at LIMIT 1
                    """,
                    (operation_id, message_id),
                ).fetchone()
                if row is None:
                    raise
                existing = self._outbox(row)
                if not (
                    existing.operation_id == operation_id
                    and existing.destination == destination
                    and existing.message_type == message_type
                    and existing.payload == payload
                ):
                    raise InvalidDocumentError(
                        f"Outbox operation {operation_id!r} was reused with other content"
                    ) from None
                return existing
            row = connection.execute(
                "SELECT * FROM outbox_items WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded by insert
                raise InvalidDocumentError("Outbox enqueue failed")
            return self._outbox(row)

    def claim_outbox(
        self,
        *,
        lease_token: str,
        now: str,
        limit: int,
    ) -> list[OutboxMessage]:
        try:
            moment = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidDocumentError("Outbox claim time must be ISO 8601") from exc
        stale_before = (moment - timedelta(minutes=5)).isoformat()
        bounded = max(1, min(limit, 100))
        with self.backend.transaction() as connection:
            rows = connection.execute(
                """
                SELECT id FROM outbox_items
                WHERE (
                    status IN ('pending', 'failed') AND available_at <= ?
                ) OR (
                    status = 'processing' AND locked_at IS NOT NULL AND locked_at <= ?
                )
                ORDER BY available_at, created_at, id LIMIT ?
                """,
                (now, stale_before, bounded),
            ).fetchall()
            connection.executemany(
                """
                UPDATE outbox_items
                SET status = 'processing', lease_token = ?, locked_at = ?,
                    attempt_count = attempt_count + 1, last_error = NULL
                WHERE id = ?
                """,
                [(lease_token, now, str(row["id"])) for row in rows],
            )
            claimed = connection.execute(
                """
                SELECT * FROM outbox_items
                WHERE lease_token = ? AND status = 'processing'
                ORDER BY available_at, created_at, id
                """,
                (lease_token,),
            ).fetchall()
        return [self._outbox(row) for row in claimed]

    def complete_outbox(self, message_id: str, *, lease_token: str) -> OutboxMessage:
        with self.backend.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox_items WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"Outbox message not found: {message_id}")
            existing = self._outbox(row)
            if existing.status == "completed":
                return existing
            if existing.status != "processing" or existing.lease_token != lease_token:
                raise InvalidDocumentError(f"Outbox lease does not own {message_id}")
            connection.execute(
                """
                UPDATE outbox_items
                SET status = 'completed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    lease_token = NULL, locked_at = NULL, last_error = NULL
                WHERE id = ? AND lease_token = ?
                """,
                (message_id, lease_token),
            )
            completed = connection.execute(
                "SELECT * FROM outbox_items WHERE id = ?",
                (message_id,),
            ).fetchone()
            if completed is None:  # pragma: no cover
                raise InvalidDocumentError("Outbox completion failed")
            return self._outbox(completed)

    def fail_outbox(
        self,
        message_id: str,
        *,
        lease_token: str,
        error: str,
        available_at: str,
    ) -> OutboxMessage:
        with self.backend.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox_items WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise EntityNotFoundError(f"Outbox message not found: {message_id}")
            existing = self._outbox(row)
            if existing.status != "processing" or existing.lease_token != lease_token:
                raise InvalidDocumentError(f"Outbox lease does not own {message_id}")
            connection.execute(
                """
                UPDATE outbox_items
                SET status = 'failed', available_at = ?, last_error = ?,
                    lease_token = NULL, locked_at = NULL
                WHERE id = ? AND lease_token = ?
                """,
                (available_at, error[:2000], message_id, lease_token),
            )
            failed = connection.execute(
                "SELECT * FROM outbox_items WHERE id = ?",
                (message_id,),
            ).fetchone()
            if failed is None:  # pragma: no cover
                raise InvalidDocumentError("Outbox failure update failed")
            return self._outbox(failed)

    def list_outbox(self, *, limit: int = 100) -> list[OutboxMessage]:
        bounded = max(1, min(limit, 1000))
        with closing(self.backend._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox_items
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [self._outbox(row) for row in rows]
