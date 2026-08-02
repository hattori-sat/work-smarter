from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from work_smarter.cli import app
from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.errors import InvalidDocumentError
from work_smarter.gtd.service import GtdService
from work_smarter.knowledge.models import KnowledgeNoteType
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.project_management.models import ProjectLifecycle
from work_smarter.project_management.service import ProjectManagementService
from work_smarter.shared.persistence.database import DatabaseConfiguration
from work_smarter.shared.persistence.sqlite import SQLiteDatabaseBackend
from work_smarter.workspace_ops import WorkspaceOperations

runner = CliRunner()


def test_cross_feature_dashboard_reports_public_feature_summaries(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    GtdService(workspace).capture("Clarify integration")
    KnowledgeService(workspace).create(
        title="Integration contract",
        note_type=KnowledgeNoteType.REFERENCE,
    )
    ProjectManagementService(workspace).create(
        title="Release",
        goal="Ship safely",
    )

    result = runner.invoke(
        app,
        ["--workspace", str(workspace.root), "--json", "overview"],
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["gtd"]["inbox_count"] == 1
    assert report["knowledge"]["note_count"] == 1
    assert report["managed_projects"]["by_lifecycle"] == {ProjectLifecycle.PROPOSED.value: 1}


def test_backup_restore_round_trip_preserves_documents_and_events(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source")
    captured = GtdService(workspace).capture("Portable record")
    archive = tmp_path / "backup.ws.zip"

    backup = WorkspaceOperations(workspace).backup(archive)
    restored_root = tmp_path / "restored"
    restored = WorkspaceOperations.restore(archive, restored_root)

    assert backup.file_count > 0
    assert restored.file_count == backup.file_count
    reopened = open_workspace(restored_root)
    assert reopened.find_record(captured.id).entity.title == "Portable record"
    assert reopened.event_store.read_all()


def test_backup_uses_a_consistent_sqlite_snapshot_without_wal_sidecars(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source")
    database = SQLiteDatabaseBackend(workspace.root, DatabaseConfiguration())
    archive = tmp_path / "backup.ws.zip"
    injection_payload = "EVT-1'); DROP TABLE activity_events; --"

    with sqlite3.connect(database.path) as writer:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute(
            """
            INSERT INTO activity_events(
                id, aggregate_type, aggregate_id, event_type, event_version, payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (injection_payload, "gtd_action", "ACT-1", "gtd.action.started", 1, "{}"),
        )
        writer.commit()
        assert database.path.with_name(f"{database.path.name}-wal").is_file()

        WorkspaceOperations(workspace).backup(archive)

    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert ".work-smarter/work-smarter.db" in names
        assert ".work-smarter/work-smarter.db-wal" not in names
        assert ".work-smarter/work-smarter.db-shm" not in names

    restored_root = tmp_path / "restored"
    WorkspaceOperations.restore(archive, restored_root)
    restored_database = SQLiteDatabaseBackend(restored_root, DatabaseConfiguration())
    with sqlite3.connect(restored_database.path) as connection:
        event = connection.execute(
            "SELECT id FROM activity_events WHERE id = ?",
            (injection_payload,),
        ).fetchone()
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "activity_events"),
        ).fetchone()

    assert event == (injection_payload,)
    assert table == ("activity_events",)


def test_restore_rejects_a_checksum_valid_but_invalid_sqlite_database(tmp_path: Path) -> None:
    archive = tmp_path / "invalid-database.ws.zip"
    database_name = ".work-smarter/work-smarter.db"
    database_payload = b"this is not sqlite"
    manifest = {
        "format": "work-smarter-backup",
        "version": 1,
        "files": {database_name: hashlib.sha256(database_payload).hexdigest()},
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(database_name, database_payload)
        bundle.writestr("WORK-SMARTER-BACKUP.json", json.dumps(manifest))

    target = tmp_path / "target"
    with pytest.raises(InvalidDocumentError, match="application database"):
        WorkspaceOperations.restore(archive, target)

    assert not target.exists()


def test_restore_rejects_sqlite_sidecars_instead_of_guessing_consistency(tmp_path: Path) -> None:
    archive = tmp_path / "sidecar.ws.zip"
    sidecar_name = ".work-smarter/work-smarter.db-wal"
    sidecar_payload = b"untracked transaction state"
    manifest = {
        "format": "work-smarter-backup",
        "version": 1,
        "files": {sidecar_name: hashlib.sha256(sidecar_payload).hexdigest()},
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(sidecar_name, sidecar_payload)
        bundle.writestr("WORK-SMARTER-BACKUP.json", json.dumps(manifest))

    with pytest.raises(InvalidDocumentError, match="sidecar"):
        WorkspaceOperations.restore(archive, tmp_path / "target")


def test_backup_rejects_a_database_symlink_outside_the_workspace(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source")
    database_path = workspace.state_dir / "work-smarter.db"
    external_database = tmp_path / "external.db"
    database_path.replace(external_database)
    database_path.symlink_to(external_database)

    with pytest.raises(InvalidDocumentError, match="database.*workspace"):
        WorkspaceOperations(workspace).backup(tmp_path / "backup.ws.zip")


def test_restore_rejects_archive_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside", "no")

    result = runner.invoke(
        app,
        [
            "--workspace",
            str(tmp_path / "target"),
            "workspace",
            "import",
            str(archive),
        ],
    )

    assert result.exit_code == 2
    assert "unsafe archive path" in result.output
    assert not (tmp_path / "outside").exists()


def test_workspace_export_import_and_migrate_cli(tmp_path: Path) -> None:
    source = initialize_workspace(tmp_path / "source")
    GtdService(source).capture("CLI archive")
    archive = tmp_path / "workspace.zip"

    exported = runner.invoke(
        app,
        [
            "--workspace",
            str(source.root),
            "--json",
            "workspace",
            "export",
            str(archive),
        ],
    )
    assert exported.exit_code == 0, exported.stdout
    assert json.loads(exported.stdout)["file_count"] > 0

    target = tmp_path / "target"
    imported = runner.invoke(
        app,
        [
            "--workspace",
            str(target),
            "--json",
            "workspace",
            "import",
            str(archive),
        ],
    )
    assert imported.exit_code == 0, imported.stdout

    migrated = runner.invoke(
        app,
        ["--workspace", str(target), "--json", "workspace", "migrate"],
    )
    assert migrated.exit_code == 0, migrated.stdout
    assert json.loads(migrated.stdout)["record_count"] == 1
