from __future__ import annotations

import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from work_smarter.cli import app
from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.gtd.service import GtdService
from work_smarter.knowledge.models import KnowledgeNoteType
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.project_management.models import ProjectLifecycle
from work_smarter.project_management.service import ProjectManagementService
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
