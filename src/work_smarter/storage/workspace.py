"""Generic workspace layout and typed Markdown persistence."""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from work_smarter.errors import (
    AmbiguousEntityError,
    EntityNotFoundError,
    InvalidDocumentError,
    WorkspaceNotInitializedError,
)
from work_smarter.storage.events import EventStore
from work_smarter.storage.frontmatter import read_markdown, write_markdown


class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workspace_version: int = 1
    name: str
    features: list[str] = Field(default_factory=lambda: ["gtd"])
    wip_limit: Literal[1] = 1
    stale_after_days: int = Field(default=14, ge=1)
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"unknown IANA timezone: {value!r}") from exc
        return cleaned


EntityT = TypeVar("EntityT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class EntityRecord[EntityT]:
    entity: EntityT
    body: str
    path: Path


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """A feature-owned codec and directory registered with a workspace."""

    kind: str
    model: type[BaseModel]
    directory: str
    archived: bool = False


class EntityRegistry:
    """Closed set of entity codecs for one composed application instance."""

    def __init__(self, specs: list[EntitySpec] | tuple[EntitySpec, ...] = ()):
        self._specs: dict[str, EntitySpec] = {}
        for spec in specs:
            if spec.kind in self._specs:
                raise ValueError(f"Entity kind already registered: {spec.kind}")
            self._specs[spec.kind] = spec

    @property
    def specs(self) -> tuple[EntitySpec, ...]:
        return tuple(self._specs.values())

    def get(self, kind: str) -> EntitySpec | None:
        return self._specs.get(kind)

    def require(self, kind: str) -> EntitySpec:
        spec = self.get(kind)
        if spec is None:
            raise ValueError(f"Unknown entity kind: {kind}")
        return spec


ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def validate_entity_id(entity_id: str) -> str:
    """Reject IDs that are ambiguous as filenames or can traverse directories."""

    if not ENTITY_ID_PATTERN.fullmatch(entity_id):
        raise InvalidDocumentError(
            f"Invalid entity ID {entity_id!r}; use letters, numbers, '.', '_' or '-'"
        )
    return entity_id


def _process_lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


class Workspace:
    """A directory whose durable state is ordinary Markdown and JSON Lines."""

    def __init__(self, root: Path | str, registry: EntityRegistry | None = None):
        self.root = Path(root).expanduser().resolve()
        self.registry = registry or EntityRegistry()

    @property
    def state_dir(self) -> Path:
        return self.root / ".work-smarter"

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.yml"

    @property
    def event_store(self) -> EventStore:
        return EventStore(self.state_dir / "events.ndjson")

    @classmethod
    def initialize(
        cls,
        root: Path | str,
        registry: EntityRegistry | None = None,
    ) -> Workspace:
        workspace = cls(root, registry)
        workspace.root.mkdir(parents=True, exist_ok=True)
        workspace.state_dir.mkdir(parents=True, exist_ok=True)
        for spec in workspace.registry.specs:
            (workspace.root / spec.directory).mkdir(parents=True, exist_ok=True)
        if not workspace.config_path.exists():
            settings = WorkspaceSettings(name=workspace.root.name or "work-smarter")
            workspace._write_config(settings)
        events_path = workspace.state_dir / "events.ndjson"
        events_path.touch(exist_ok=True)
        return workspace

    @classmethod
    def open(
        cls,
        root: Path | str,
        registry: EntityRegistry | None = None,
    ) -> Workspace:
        workspace = cls(root, registry)
        if not workspace.config_path.is_file():
            raise WorkspaceNotInitializedError(
                f"{workspace.root} is not initialized; run `ws init {workspace.root}`"
            )
        workspace.settings()
        return workspace

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Serialize state transitions across threads and local processes."""

        self.state_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_dir / "workspace.lock"
        process_lock = _process_lock_for(lock_path)
        with process_lock, lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def settings(self) -> WorkspaceSettings:
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
            return WorkspaceSettings.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise InvalidDocumentError(
                f"Invalid workspace config {self.config_path}: {exc}"
            ) from exc

    def _write_config(self, settings: WorkspaceSettings) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(
            settings.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_dir,
                prefix=".config.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.config_path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    def path_for(self, entity: BaseModel) -> Path:
        kind = str(getattr(entity, "kind", ""))
        entity_id = validate_entity_id(str(getattr(entity, "id", "")))
        try:
            spec = self.registry.require(kind)
        except ValueError as exc:
            raise InvalidDocumentError(str(exc)) from exc
        directory = (self.root / spec.directory).resolve()
        path = (directory / f"{entity_id}.md").resolve()
        if not path.is_relative_to(directory):
            raise InvalidDocumentError(f"Entity path escapes {directory}: {entity_id!r}")
        return path

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as exc:
            raise InvalidDocumentError(f"Path is outside workspace: {path}") from exc

    def write(self, entity: EntityT, body: str = "") -> EntityRecord[EntityT]:
        path = self.path_for(entity)
        write_markdown(
            path,
            entity.model_dump(
                mode="json",
                exclude_none=True,
                exclude_computed_fields=True,
            ),
            body,
        )
        return EntityRecord(entity=entity, body=body, path=path)

    def read(
        self,
        path: Path,
        *,
        expected_kind: str | None = None,
    ) -> EntityRecord[BaseModel]:
        document = read_markdown(path)
        kind = str(document.metadata.get("kind", ""))
        spec = self.registry.get(kind)
        if spec is None:
            raise InvalidDocumentError(f"{path}: unknown entity kind {kind!r}")
        if expected_kind is not None and kind != expected_kind:
            raise InvalidDocumentError(
                f"{path}: kind {kind!r} is stored in the {expected_kind!r} directory"
            )
        try:
            entity = spec.model.model_validate(document.metadata)
        except ValidationError as exc:
            raise InvalidDocumentError(f"{path}: invalid {kind} metadata: {exc}") from exc
        entity_id = validate_entity_id(str(getattr(entity, "id", "")))
        if path.stem != entity_id:
            raise InvalidDocumentError(f"{path}: filename must match entity ID {entity_id!r}")
        return EntityRecord(entity=entity, body=document.body, path=path)

    def list_records(
        self,
        kind: str,
        *,
        include_archive: bool = False,
    ) -> list[EntityRecord[BaseModel]]:
        spec = self.registry.require(kind)
        if spec.archived and not include_archive:
            return []
        directory = self.root / spec.directory
        records = [self.read(path, expected_kind=kind) for path in sorted(directory.glob("*.md"))]
        return sorted(records, key=self._sort_key)

    @staticmethod
    def _sort_key(record: EntityRecord[BaseModel]) -> tuple[str, str]:
        entity = record.entity
        timestamp = getattr(entity, "captured_at", None) or getattr(entity, "created_at", None)
        return (timestamp.isoformat() if timestamp else "", str(getattr(entity, "id", "")))

    def all_records(
        self,
        *,
        include_archive: bool = False,
    ) -> list[EntityRecord[BaseModel]]:
        records: list[EntityRecord[BaseModel]] = []
        for spec in self.registry.specs:
            records.extend(self.list_records(spec.kind, include_archive=include_archive))
        return records

    def find_record(
        self,
        query: str,
        *,
        kinds: set[str] | None = None,
    ) -> EntityRecord[BaseModel]:
        normalized = query.strip().upper()
        candidates = [
            record
            for record in self.all_records()
            if kinds is None or getattr(record.entity, "kind", None) in kinds
        ]
        exact = [
            record
            for record in candidates
            if str(getattr(record.entity, "id", "")).upper() == normalized
        ]
        if len(exact) > 1:
            paths = ", ".join(self.relative(record.path) for record in exact[:5])
            raise AmbiguousEntityError(f"Duplicate ID {query!r} exists at: {paths}")
        if exact:
            return exact[0]
        prefix = [
            record
            for record in candidates
            if str(getattr(record.entity, "id", "")).upper().startswith(normalized)
        ]
        if not prefix:
            raise EntityNotFoundError(f"No entity matches {query!r}")
        if len(prefix) > 1:
            ids = ", ".join(str(getattr(record.entity, "id", "")) for record in prefix[:5])
            raise AmbiguousEntityError(f"{query!r} matches multiple entities: {ids}")
        return prefix[0]

    def archive_record(
        self,
        record: EntityRecord[BaseModel],
        archived: EntityT,
    ) -> EntityRecord[EntityT]:
        destination = self.write(archived, record.body)
        record.path.unlink()
        return destination
