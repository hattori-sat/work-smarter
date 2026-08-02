"""Cross-feature read models and portable workspace maintenance operations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from work_smarter.errors import InvalidDocumentError
from work_smarter.gtd.service import GtdService
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.project_management.service import ProjectManagementService
from work_smarter.storage.workspace import Workspace

MANIFEST_NAME = "WORK-SMARTER-BACKUP.json"
EXCLUDED_PARTS = {"cache", "secrets", "__pycache__"}
EXCLUDED_NAMES = {"workspace.lock", ".DS_Store"}


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


class WorkspaceOperations:
    """Coordinate features without importing one feature's private model into another."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

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
        hashes: dict[str, str] = {}
        with self.workspace.lock():
            files = self._included_files(self.workspace.root, excluding=archive)
            for path in files:
                relative = path.relative_to(self.workspace.root).as_posix()
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = {
                "format": "work-smarter-backup",
                "version": 1,
                "files": hashes,
            }
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
                    for path in files:
                        bundle.write(path, path.relative_to(self.workspace.root).as_posix())
                    bundle.writestr(MANIFEST_NAME, json.dumps(manifest, sort_keys=True))
                os.replace(temporary, archive)
            except OSError:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                raise
        return ArchiveReport(
            archive=str(archive),
            file_count=len(files),
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

    @staticmethod
    def _safe_member(name: str) -> PurePosixPath:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or "\\" in name:
            raise InvalidDocumentError(f"unsafe archive path: {name!r}")
        return member

    @classmethod
    def restore(cls, source: Path | str, destination: Path | str) -> ArchiveReport:
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
                manifest = json.loads(bundle.read(MANIFEST_NAME))
                if manifest.get("format") != "work-smarter-backup" or manifest.get("version") != 1:
                    raise InvalidDocumentError("unsupported backup format")
                expected: dict[str, str] = manifest.get("files", {})
                if set(names) - {MANIFEST_NAME} != set(expected):
                    raise InvalidDocumentError("backup manifest does not match archive members")
                payloads: dict[str, bytes] = {}
                for name, digest in expected.items():
                    data = bundle.read(name)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise InvalidDocumentError(f"backup checksum mismatch: {name}")
                    payloads[name] = data
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise InvalidDocumentError(f"invalid workspace backup {archive}: {exc}") from exc

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
