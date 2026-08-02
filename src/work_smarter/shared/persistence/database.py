"""Database port, backend selection, and provider-neutral backup contracts."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_smarter.errors import InvalidDocumentError

DATABASE_BACKEND_ENTRY_POINT = "work_smarter.database_backends"
BACKEND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class DatabaseConfiguration(BaseModel):
    """Provider-neutral workspace selection; credentials must remain external."""

    model_config = ConfigDict(extra="forbid")

    backend: str = Field(default="sqlite", min_length=1, max_length=64)
    location: str | None = Field(default=None, min_length=1)

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not BACKEND_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use lowercase letters, numbers, '_' or '-'")
        return normalized

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError("database location must be a non-empty safe string")
        return cleaned


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    initialized: bool
    schema_version: int
    latest_schema_version: int


@dataclass(frozen=True, slots=True)
class DatabaseMigrationReport:
    schema_version: int
    applied_versions: list[int]


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    backend: str
    archive_member: str
    path: Path


@dataclass(frozen=True, slots=True)
class StructuredEntityState:
    """Provider-neutral structured state owned by the application database."""

    kind: str
    entity_id: str
    payload: dict[str, object]
    projection_path: str
    revision: int


@dataclass(frozen=True, slots=True)
class OperationJournalRecord:
    """Durable intent spanning the database and a Markdown projection."""

    id: str
    operation_type: str
    status: str
    aggregate_kind: str
    aggregate_id: str
    payload: dict[str, object]
    projection_path: str
    idempotency_key: str
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """A leased provider-neutral delivery request."""

    id: str
    operation_id: str
    destination: str
    message_type: str
    payload: dict[str, object]
    status: str
    attempt_count: int
    available_at: str
    lease_token: str | None = None
    last_error: str | None = None


@runtime_checkable
class StructuredStateStore(Protocol):
    """Domain-record, journal, activity-event, and outbox persistence port."""

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
        """Persist an idempotent write intent before touching its Markdown projection."""

    def legacy_import_completed(self) -> bool:
        """Return whether legacy Markdown/JSONL ownership was imported once."""

    def complete_legacy_import(self) -> None:
        """Mark the domain ownership migration complete after all imports succeed."""

    def commit_entity_write(self, operation_id: str) -> StructuredEntityState:
        """Atomically commit staged state, activity event, and journal completion."""

    def stage_entity_delete(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        kind: str,
        entity_id: str,
        projection_path: str,
    ) -> OperationJournalRecord:
        """Persist an idempotent delete intent before removing a projection."""

    def commit_entity_delete(self, operation_id: str) -> None:
        """Atomically delete structured state and complete its journal entry."""

    def fail_operation(self, operation_id: str, error: str) -> OperationJournalRecord:
        """Mark a normally-refused operation failed without changing entity state."""

    def pending_operations(self) -> list[OperationJournalRecord]:
        """List incomplete intents in deterministic creation order."""

    def get_operation(self, operation_id: str) -> OperationJournalRecord:
        """Return one operation journal record."""

    def list_operations(self, *, limit: int = 100) -> list[OperationJournalRecord]:
        """Return recent operations newest first."""

    def import_entity(
        self,
        *,
        kind: str,
        entity_id: str,
        payload: dict[str, object],
        projection_path: str,
    ) -> StructuredEntityState:
        """Import one legacy record only when no database record exists."""

    def get_entity(self, kind: str, entity_id: str) -> StructuredEntityState | None:
        """Read one authoritative structured record."""

    def list_entities(self, kind: str) -> list[StructuredEntityState]:
        """List authoritative records for one registered kind."""

    def append_activity_event(self, event: dict[str, object]) -> dict[str, object]:
        """Append one idempotent domain activity event."""

    def list_activity_events(self) -> list[dict[str, object]]:
        """Read append-only activity history in occurrence order."""

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
        """Enqueue one idempotent external delivery."""

    def claim_outbox(
        self,
        *,
        lease_token: str,
        now: str,
        limit: int,
    ) -> list[OutboxMessage]:
        """Lease pending or failed messages for one worker."""

    def complete_outbox(self, message_id: str, *, lease_token: str) -> OutboxMessage:
        """Idempotently complete a leased delivery."""

    def fail_outbox(
        self,
        message_id: str,
        *,
        lease_token: str,
        error: str,
        available_at: str,
    ) -> OutboxMessage:
        """Release a failed delivery for a later retry."""

    def list_outbox(self, *, limit: int = 100) -> list[OutboxMessage]:
        """Return recent outbox messages newest first."""


@runtime_checkable
class DatabaseBackend(Protocol):
    """Port implemented by SQLite, Access, or another persistence adapter."""

    name: str
    archive_member: str
    workspace_members: frozenset[str]

    def status(self) -> DatabaseStatus:
        """Report initialization and adapter-specific schema versions."""

    def migrate(self) -> DatabaseMigrationReport:
        """Bring this backend to the schema version supported by its adapter."""

    def create_snapshot(self, destination: Path) -> DatabaseSnapshot:
        """Create a consistent artifact inside the supplied temporary directory."""

    def verify_snapshot(self, path: Path) -> DatabaseStatus:
        """Validate a snapshot without mutating the source workspace."""


@runtime_checkable
class StructuredStateBackend(Protocol):
    """Optional backend capability used after a domain ownership migration."""

    @property
    def structured_store(self) -> StructuredStateStore:
        """Return the backend's domain-specific structured-state ports."""


DatabaseBackendFactory = Callable[[Path, DatabaseConfiguration], DatabaseBackend]


class DatabaseBackendRegistry:
    """Resolve a configured backend without leaking its driver into application code."""

    def __init__(self) -> None:
        self._factories: dict[str, DatabaseBackendFactory] = {}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def register(self, name: str, factory: DatabaseBackendFactory) -> None:
        normalized = name.strip().lower()
        if not BACKEND_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid database backend name: {name!r}")
        if normalized in self._factories:
            raise ValueError(f"Database backend already registered: {normalized}")
        self._factories[normalized] = factory

    def create(
        self,
        workspace_root: Path | str,
        configuration: DatabaseConfiguration,
    ) -> DatabaseBackend:
        factory = self._factories.get(configuration.backend)
        if factory is None:
            available = ", ".join(self.names) or "none"
            raise InvalidDocumentError(
                f"Database backend {configuration.backend!r} is not available; "
                f"installed backends: {available}"
            )
        backend = factory(Path(workspace_root).expanduser().resolve(), configuration)
        if not isinstance(backend, DatabaseBackend):
            raise TypeError(
                f"Database factory {configuration.backend!r} returned an invalid adapter"
            )
        if backend.name != configuration.backend:
            raise TypeError(
                f"Database adapter name {backend.name!r} does not match "
                f"configuration {configuration.backend!r}"
            )
        return backend


def _sqlite_factory(
    workspace_root: Path,
    configuration: DatabaseConfiguration,
) -> DatabaseBackend:
    from work_smarter.shared.persistence.sqlite import SQLiteDatabaseBackend

    return SQLiteDatabaseBackend(workspace_root, configuration)


def default_database_registry(
    extra: Iterable[tuple[str, DatabaseBackendFactory]] = (),
) -> DatabaseBackendRegistry:
    """Build the runtime registry from the built-in SQLite and installed adapters."""

    registry = DatabaseBackendRegistry()
    registry.register("sqlite", _sqlite_factory)
    for entry_point in entry_points(group=DATABASE_BACKEND_ENTRY_POINT):
        registry.register(entry_point.name, entry_point.load())
    for name, factory in extra:
        registry.register(name, factory)
    return registry


def create_database_backend(
    workspace_root: Path | str,
    configuration: DatabaseConfiguration,
    *,
    registry: DatabaseBackendRegistry | None = None,
) -> DatabaseBackend:
    selected = registry or default_database_registry()
    return selected.create(workspace_root, configuration)
