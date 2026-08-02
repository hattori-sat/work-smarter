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
