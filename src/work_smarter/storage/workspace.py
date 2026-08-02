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
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from work_smarter.errors import (
    AmbiguousEntityError,
    EntityNotFoundError,
    InvalidDocumentError,
    WorkspaceNotInitializedError,
)
from work_smarter.shared.persistence.database import (
    DatabaseConfiguration,
    StructuredEntityState,
    StructuredStateStore,
)
from work_smarter.storage.events import DatabaseEventStore, EventStore
from work_smarter.storage.frontmatter import read_markdown, write_markdown

DEFAULT_WORKSPACE_FEATURES: tuple[str, ...] = (
    "gtd",
    "knowledge",
    "project-management",
)


class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workspace_version: int = 1
    name: str
    features: list[str] = Field(default_factory=lambda: list(DEFAULT_WORKSPACE_FEATURES))
    wip_limit: Literal[1] = 1
    stale_after_days: int = Field(default=14, ge=1)
    timezone: str = "UTC"
    database: DatabaseConfiguration = Field(default_factory=DatabaseConfiguration)

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
    """A workspace with optional database-owned structure and Markdown narrative."""

    def __init__(
        self,
        root: Path | str,
        registry: EntityRegistry | None = None,
        structured_store: StructuredStateStore | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.registry = registry or EntityRegistry()
        self.structured_store = structured_store

    @property
    def state_dir(self) -> Path:
        return self.root / ".work-smarter"

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.yml"

    @property
    def event_store(self) -> EventStore:
        path = self.state_dir / "events.ndjson"
        if self.structured_store is not None:
            return DatabaseEventStore(path, self.structured_store)
        return EventStore(path)

    @classmethod
    def initialize(
        cls,
        root: Path | str,
        registry: EntityRegistry | None = None,
        structured_store: StructuredStateStore | None = None,
    ) -> Workspace:
        workspace = cls(root, registry, structured_store)
        workspace.root.mkdir(parents=True, exist_ok=True)
        workspace.state_dir.mkdir(parents=True, exist_ok=True)
        for spec in workspace.registry.specs:
            (workspace.root / spec.directory).mkdir(parents=True, exist_ok=True)
        if not workspace.config_path.exists():
            settings = WorkspaceSettings(name=workspace.root.name or "work-smarter")
            workspace._write_config(settings)
        events_path = workspace.state_dir / "events.ndjson"
        events_path.touch(exist_ok=True)
        if structured_store is not None:
            workspace._activate_structured_state()
        return workspace

    @classmethod
    def open(
        cls,
        root: Path | str,
        registry: EntityRegistry | None = None,
        structured_store: StructuredStateStore | None = None,
    ) -> Workspace:
        workspace = cls(root, registry, structured_store)
        if not workspace.config_path.is_file():
            raise WorkspaceNotInitializedError(
                f"{workspace.root} is not initialized; run `ws init {workspace.root}`"
            )
        workspace.settings()
        if structured_store is not None:
            workspace._activate_structured_state()
        return workspace

    def attach_structured_store(self, store: StructuredStateStore) -> None:
        """Switch registered structured kinds to a migrated database authority."""

        self.structured_store = store
        self._activate_structured_state()

    def _activate_structured_state(self) -> None:
        self._recover_operations()
        if (
            self.structured_store is not None
            and not self.structured_store.legacy_import_completed()
        ):
            self._import_legacy_records()
            self._import_legacy_events()
            self.structured_store.complete_legacy_import()

    def _import_legacy_events(self) -> None:
        store = self.structured_store
        if store is None:
            return
        legacy = EventStore(self.state_dir / "events.ndjson")
        for event in legacy.read_all():
            store.append_activity_event(event.model_dump(mode="json", exclude_none=True))

    def _operation_path(self, projection_path: str) -> Path:
        relative = Path(projection_path)
        if relative.is_absolute():
            raise InvalidDocumentError("Operation projection path must be workspace-relative")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise InvalidDocumentError("Operation projection path escapes workspace")
        return path

    def _recover_operations(self) -> None:
        store = self.structured_store
        if store is None:
            return
        for operation in store.pending_operations():
            path = self._operation_path(operation.projection_path)
            if operation.operation_type == "entity.delete":
                if path.exists():
                    store.fail_operation(operation.id, "projection still exists")
                else:
                    store.commit_entity_delete(operation.id)
                continue
            if not path.is_file():
                store.fail_operation(operation.id, "projection was not written")
                continue
            try:
                document = read_markdown(path)
                spec = self.registry.require(operation.aggregate_kind)
                projected = spec.model.model_validate(document.metadata).model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude_computed_fields=True,
                )
            except (InvalidDocumentError, ValidationError, ValueError) as exc:
                store.fail_operation(operation.id, f"invalid projection: {exc}")
                continue
            if projected != operation.payload:
                store.fail_operation(operation.id, "projection does not match staged payload")
                continue
            store.commit_entity_write(operation.id)

    def _import_legacy_records(self) -> None:
        store = self.structured_store
        if store is None:
            return
        refused_paths = {
            operation.projection_path
            for operation in store.list_operations(limit=1000)
            if operation.status == "failed"
        }
        for spec in self.registry.specs:
            directory = self.root / spec.directory
            for path in sorted(directory.glob("*.md")):
                if self.relative(path) in refused_paths:
                    continue
                document = self._read_projection(path, expected_kind=spec.kind)
                entity_id = str(getattr(document.entity, "id", ""))
                if store.get_entity(spec.kind, entity_id) is not None:
                    continue
                store.import_entity(
                    kind=spec.kind,
                    entity_id=entity_id,
                    payload=document.entity.model_dump(
                        mode="json",
                        exclude_none=True,
                        exclude_computed_fields=True,
                    ),
                    projection_path=self.relative(path),
                )

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
        payload = entity.model_dump(
            mode="json",
            exclude_none=True,
            exclude_computed_fields=True,
        )
        store = self.structured_store
        if store is None:
            write_markdown(path, payload, body)
            return EntityRecord(entity=entity, body=body, path=path)
        operation_id = f"OP-{uuid4().hex}"
        store.stage_entity_write(
            operation_id=operation_id,
            idempotency_key=operation_id,
            kind=str(getattr(entity, "kind", "")),
            entity_id=str(getattr(entity, "id", "")),
            payload=payload,
            projection_path=self.relative(path),
        )
        try:
            write_markdown(path, payload, body)
            store.commit_entity_write(operation_id)
        except Exception as exc:
            store.fail_operation(operation_id, str(exc))
            raise
        return EntityRecord(entity=entity, body=body, path=path)

    def read(
        self,
        path: Path,
        *,
        expected_kind: str | None = None,
    ) -> EntityRecord[BaseModel]:
        store = self.structured_store
        if store is None:
            return self._read_projection(path, expected_kind=expected_kind)
        if expected_kind is None:
            projected = self._read_projection(path)
            expected_kind = str(getattr(projected.entity, "kind", ""))
        entity_id = validate_entity_id(path.stem)
        state = store.get_entity(expected_kind, entity_id)
        if state is None:
            return self._read_projection(path, expected_kind=expected_kind)
        return self._record_from_state(state, expected_kind=expected_kind)

    def _read_projection(
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

    def _record_from_state(
        self,
        state: StructuredEntityState,
        *,
        expected_kind: str,
    ) -> EntityRecord[BaseModel]:
        if state.kind != expected_kind:
            raise InvalidDocumentError(
                f"Database kind {state.kind!r} does not match {expected_kind!r}"
            )
        spec = self.registry.require(expected_kind)
        path = self._operation_path(state.projection_path)
        expected_directory = (self.root / spec.directory).resolve()
        if not path.is_relative_to(expected_directory):
            raise InvalidDocumentError(
                f"Database projection path is outside {spec.directory}: {state.projection_path}"
            )
        if not path.is_file():
            raise InvalidDocumentError(f"Narrative projection is missing: {path}")
        try:
            entity = spec.model.model_validate(state.payload)
        except ValidationError as exc:
            raise InvalidDocumentError(
                f"Database contains invalid {expected_kind} state: {exc}"
            ) from exc
        entity_id = validate_entity_id(str(getattr(entity, "id", "")))
        if entity_id != state.entity_id or path.stem != entity_id:
            raise InvalidDocumentError(
                f"Database entity ID/path mismatch for {state.kind}:{state.entity_id}"
            )
        body = read_markdown(path).body
        return EntityRecord(entity=entity, body=body, path=path)

    def list_records(
        self,
        kind: str,
        *,
        include_archive: bool = False,
    ) -> list[EntityRecord[BaseModel]]:
        spec = self.registry.require(kind)
        if spec.archived and not include_archive:
            return []
        if self.structured_store is not None:
            records = [
                self._record_from_state(state, expected_kind=kind)
                for state in self.structured_store.list_entities(kind)
            ]
            return sorted(records, key=self._sort_key)
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
        store = self.structured_store
        if store is None:
            record.path.unlink()
            return destination
        operation_id = f"OP-{uuid4().hex}"
        kind = str(getattr(record.entity, "kind", ""))
        entity_id = str(getattr(record.entity, "id", ""))
        store.stage_entity_delete(
            operation_id=operation_id,
            idempotency_key=operation_id,
            kind=kind,
            entity_id=entity_id,
            projection_path=self.relative(record.path),
        )
        try:
            record.path.unlink()
            store.commit_entity_delete(operation_id)
        except Exception as exc:
            store.fail_operation(operation_id, str(exc))
            raise
        return destination
