"""Cross-feature read models and portable workspace maintenance operations."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from work_smarter.errors import InvalidDocumentError
from work_smarter.gtd.service import GtdService
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.project_management.service import ProjectManagementService
from work_smarter.shared.persistence.database import (
    DatabaseBackendRegistry,
    DatabaseConfiguration,
    default_database_registry,
)
from work_smarter.storage.workspace import Workspace, WorkspaceSettings

MANIFEST_NAME = "WORK-SMARTER-BACKUP.json"
EXCLUDED_PARTS = {"cache", "secrets", "__pycache__"}
EXCLUDED_NAMES = {"workspace.lock", ".DS_Store"}
LEGACY_SQLITE_MEMBER = ".work-smarter/work-smarter.db"
LEGACY_SQLITE_SIDECARS = {
    f"{LEGACY_SQLITE_MEMBER}-journal",
    f"{LEGACY_SQLITE_MEMBER}-shm",
    f"{LEGACY_SQLITE_MEMBER}-wal",
}


class OperationsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GtdOverview(OperationsModel):
    inbox_count: int
    current_task_id: str | None = None
    tasks_by_status: dict[str, int] = Field(default_factory=dict)


class KnowledgeOverview(OperationsModel):
    note_count: int
    issue_count: int


class ManagedProjectOverview(OperationsModel):
    project_count: int
    by_lifecycle: dict[str, int] = Field(default_factory=dict)
    issue_count: int


class WorkspaceOverview(OperationsModel):
    generated_at: datetime = Field(default_factory=datetime.now)
    gtd: GtdOverview | None = None
    knowledge: KnowledgeOverview | None = None
    managed_projects: ManagedProjectOverview | None = None


class ArchiveReport(OperationsModel):
    archive: str
    file_count: int
    sha256: str


class MigrationReport(OperationsModel):
    record_count: int


class DatabaseArchiveMetadata(OperationsModel):
    backend: str
    member: str


class BackupManifest(OperationsModel):
    format: Literal["work-smarter-backup"]
    version: Literal[1]
    files: dict[str, str]
    database: DatabaseArchiveMetadata | None = None


class WorkspaceOperations:
    """Coordinate features without importing one feature's private model into another."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        database_registry: DatabaseBackendRegistry | None = None,
    ):
        self.workspace = workspace
        self.database_registry = database_registry or default_database_registry()

    def overview(self) -> WorkspaceOverview:
        enabled = set(self.workspace.settings().features)
        gtd: GtdOverview | None = None
        knowledge: KnowledgeOverview | None = None
        managed_projects: ManagedProjectOverview | None = None
        if "gtd" in enabled:
            status = GtdService(self.workspace).status()
            gtd = GtdOverview(
                inbox_count=status.inbox_count,
                current_task_id=status.current_task.id if status.current_task else None,
                tasks_by_status=status.tasks_by_status,
            )
        if "knowledge" in enabled:
            service = KnowledgeService(self.workspace)
            knowledge = KnowledgeOverview(
                note_count=len(service.list()),
                issue_count=len(service.doctor().issues),
            )
        if "project-management" in enabled:
            service = ProjectManagementService(self.workspace)
            projects = service.list()
            managed_projects = ManagedProjectOverview(
                project_count=len(projects),
                by_lifecycle=dict(
                    sorted(Counter(item.project.lifecycle.value for item in projects).items())
                ),
                issue_count=len(service.doctor().issues),
            )
        return WorkspaceOverview(
            gtd=gtd,
            knowledge=knowledge,
            managed_projects=managed_projects,
        )

    @staticmethod
    def _included_files(root: Path, *, excluding: Path | None = None) -> list[Path]:
        files: list[Path] = []
        excluded = excluding.resolve() if excluding else None
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if path.resolve() == excluded:
                continue
            if relative.name in EXCLUDED_NAMES or any(
                part in EXCLUDED_PARTS for part in relative.parts
            ):
                continue
            files.append(path)
        return files

    def backup(self, destination: Path | str) -> ArchiveReport:
        archive = Path(destination).expanduser().resolve()
        archive.parent.mkdir(parents=True, exist_ok=True)
        with self.workspace.lock():
            database = self.database_registry.create(
                self.workspace.root,
                self.workspace.settings().database,
            )
            files = self._included_files(self.workspace.root, excluding=archive)
            regular_files = [
                path
                for path in files
                if path.relative_to(self.workspace.root).as_posix()
                not in database.workspace_members
            ]
            with tempfile.TemporaryDirectory(prefix="work-smarter-backup-") as temporary_dir:
                snapshot = None
                if database.status().initialized:
                    snapshot = database.create_snapshot(Path(temporary_dir))
                    self._safe_member(snapshot.archive_member)
                    if (
                        snapshot.backend != database.name
                        or snapshot.archive_member != database.archive_member
                    ):
                        raise InvalidDocumentError(
                            "database adapter returned inconsistent snapshot metadata"
                        )
                hashes = {
                    path.relative_to(self.workspace.root).as_posix(): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in regular_files
                }
                if snapshot is not None:
                    hashes[snapshot.archive_member] = hashlib.sha256(
                        snapshot.path.read_bytes()
                    ).hexdigest()
                database_metadata = None
                if snapshot is not None:
                    database_metadata = DatabaseArchiveMetadata(
                        backend=snapshot.backend,
                        member=snapshot.archive_member,
                    )
                manifest = BackupManifest(
                    format="work-smarter-backup",
                    version=1,
                    files=hashes,
                    database=database_metadata,
                )
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=archive.parent,
                        prefix=f".{archive.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as stream:
                        temporary = Path(stream.name)
                    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
                        for path in regular_files:
                            bundle.write(path, path.relative_to(self.workspace.root).as_posix())
                        if snapshot is not None:
                            bundle.write(snapshot.path, snapshot.archive_member)
                        bundle.writestr(
                            MANIFEST_NAME,
                            manifest.model_dump_json(exclude_none=True),
                        )
                    os.replace(temporary, archive)
                except OSError:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                    raise
        return ArchiveReport(
            archive=str(archive),
            file_count=len(hashes),
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

    @staticmethod
    def _safe_member(name: str) -> PurePosixPath:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or "\\" in name:
            raise InvalidDocumentError(f"unsafe archive path: {name!r}")
        return member

    @classmethod
    def restore(
        cls,
        source: Path | str,
        destination: Path | str,
        *,
        database_registry: DatabaseBackendRegistry | None = None,
    ) -> ArchiveReport:
        archive = Path(source).expanduser().resolve()
        root = Path(destination).expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise InvalidDocumentError(f"restore destination must be empty: {root}")
        try:
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                for name in names:
                    cls._safe_member(name)
                if MANIFEST_NAME not in names:
                    raise InvalidDocumentError("backup manifest is missing")
                manifest = BackupManifest.model_validate_json(bundle.read(MANIFEST_NAME))
                expected = manifest.files
                if set(names) - {MANIFEST_NAME} != set(expected):
                    raise InvalidDocumentError("backup manifest does not match archive members")
                payloads: dict[str, bytes] = {}
                for name, digest in expected.items():
                    data = bundle.read(name)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise InvalidDocumentError(f"backup checksum mismatch: {name}")
                    payloads[name] = data
        except (OSError, zipfile.BadZipFile, ValidationError) as exc:
            raise InvalidDocumentError(f"invalid workspace backup {archive}: {exc}") from exc

        metadata = manifest.database
        if metadata is None and (
            LEGACY_SQLITE_MEMBER in payloads or set(payloads) & LEGACY_SQLITE_SIDECARS
        ):
            metadata = DatabaseArchiveMetadata(
                backend="sqlite",
                member=LEGACY_SQLITE_MEMBER,
            )
        if metadata is not None:
            cls._safe_member(metadata.member)
            registry = database_registry or default_database_registry()
            with tempfile.TemporaryDirectory(prefix="work-smarter-restore-") as temporary_dir:
                temporary_root = Path(temporary_dir)
                database = registry.create(
                    temporary_root,
                    DatabaseConfiguration(
                        backend=metadata.backend,
                        location=metadata.member,
                    ),
                )
                if database.archive_member != metadata.member:
                    raise InvalidDocumentError(
                        "database manifest member does not match backend configuration"
                    )
                sidecars = (database.workspace_members - {metadata.member}) & set(payloads)
                if sidecars:
                    raise InvalidDocumentError(
                        "backup contains database sidecar files instead of a consistent snapshot"
                    )
                if metadata.member not in payloads:
                    raise InvalidDocumentError("database snapshot is missing from backup")
                database_path = temporary_root.joinpath(*PurePosixPath(metadata.member).parts)
                database_path.parent.mkdir(parents=True, exist_ok=True)
                database_path.write_bytes(payloads[metadata.member])
                database.verify_snapshot(database_path)

            config_payload = payloads.get(".work-smarter/config.yml")
            if config_payload is not None:
                try:
                    settings = WorkspaceSettings.model_validate(
                        yaml.safe_load(config_payload.decode("utf-8")) or {}
                    )
                except (UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
                    raise InvalidDocumentError(
                        f"invalid workspace config in backup: {exc}"
                    ) from exc
                if settings.database.backend != metadata.backend:
                    raise InvalidDocumentError(
                        "workspace database backend does not match backup manifest"
                    )
                configured = registry.create(root, settings.database)
                if configured.archive_member != metadata.member:
                    raise InvalidDocumentError(
                        "workspace database location does not match backup manifest"
                    )

        root.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            target = root.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return ArchiveReport(
            archive=str(archive),
            file_count=len(payloads),
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

    def migrate(self) -> MigrationReport:
        with self.workspace.lock():
            records = self.workspace.all_records(include_archive=True)
            for record in records:
                self.workspace.write(record.entity, record.body)
        return MigrationReport(record_count=len(records))
