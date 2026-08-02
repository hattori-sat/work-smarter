from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from work_smarter.api import create_app
from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.errors import InvalidDocumentError
from work_smarter.shared.persistence.database import (
    DatabaseBackendRegistry,
    DatabaseConfiguration,
    DatabaseMigrationReport,
    DatabaseSnapshot,
    DatabaseStatus,
)
from work_smarter.workspace_ops import WorkspaceOperations


class FakeDatabaseBackend:
    name = "fake"

    def __init__(self, workspace_root: Path, configuration: DatabaseConfiguration):
        self.workspace_root = workspace_root
        self.configuration = configuration
        self.archive_member = configuration.location or ".work-smarter/fake.database"
        self.workspace_members = frozenset({self.archive_member})
        self.path = workspace_root / self.archive_member

    def status(self) -> DatabaseStatus:
        return DatabaseStatus(
            initialized=self.path.is_file(),
            schema_version=1 if self.path.is_file() else 0,
            latest_schema_version=1,
        )

    def migrate(self) -> DatabaseMigrationReport:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"fake-database-v1")
        return DatabaseMigrationReport(schema_version=1, applied_versions=[1])

    def create_snapshot(self, destination: Path) -> DatabaseSnapshot:
        snapshot = destination / Path(self.archive_member).name
        snapshot.write_bytes(self.path.read_bytes())
        return DatabaseSnapshot(
            backend=self.name,
            archive_member=self.archive_member,
            path=snapshot,
        )

    def verify_snapshot(self, path: Path) -> DatabaseStatus:
        if path.read_bytes() != b"fake-database-v1":
            raise InvalidDocumentError("invalid fake database")
        return DatabaseStatus(initialized=True, schema_version=1, latest_schema_version=1)


def fake_database_factory(
    workspace_root: Path,
    configuration: DatabaseConfiguration,
) -> FakeDatabaseBackend:
    return FakeDatabaseBackend(workspace_root, configuration)


def fake_database_registry() -> DatabaseBackendRegistry:
    registry = DatabaseBackendRegistry()
    registry.register("fake", fake_database_factory)
    return registry


def test_database_port_import_does_not_load_sqlite() -> None:
    source_root = Path(__file__).parents[1] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import work_smarter.shared.persistence.database; "
                "import sys; assert 'sqlite3' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_sqlite_driver_is_isolated_to_the_sqlite_adapter() -> None:
    source_root = Path(__file__).parents[1] / "src/work_smarter"
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        if path == source_root / "shared/persistence/sqlite.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "sqlite3" for alias in node.names
            ):
                violations.append(f"{path.relative_to(source_root)}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                violations.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert violations == [], f"sqlite3 must remain inside its adapter: {violations}"


def test_registry_selects_a_backend_from_workspace_configuration(tmp_path: Path) -> None:
    configuration = DatabaseConfiguration(
        backend="fake",
        location=".work-smarter/custom.fake",
    )

    backend = fake_database_registry().create(tmp_path, configuration)

    assert isinstance(backend, FakeDatabaseBackend)
    assert backend.path == tmp_path / ".work-smarter/custom.fake"


def test_registry_refuses_an_unavailable_backend(tmp_path: Path) -> None:
    registry = DatabaseBackendRegistry()

    with pytest.raises(InvalidDocumentError, match="Database backend 'access'.*not available"):
        registry.create(tmp_path, DatabaseConfiguration(backend="access"))


def test_workspace_config_rejects_provider_secrets_and_unknown_fields(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    settings = yaml.safe_load(workspace.config_path.read_text(encoding="utf-8"))
    settings["database"]["password"] = "must-not-live-here"
    workspace.config_path.write_text(
        yaml.safe_dump(settings, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(InvalidDocumentError, match="Invalid workspace config"):
        open_workspace(workspace.root)


def test_configured_non_sqlite_backend_round_trips_through_backup(tmp_path: Path) -> None:
    root = tmp_path / "source"
    state_dir = root / ".work-smarter"
    state_dir.mkdir(parents=True)
    settings = {
        "workspace_version": 1,
        "name": "fake-workspace",
        "features": ["gtd", "knowledge", "project-management"],
        "wip_limit": 1,
        "stale_after_days": 14,
        "timezone": "UTC",
        "database": {
            "backend": "fake",
            "location": ".work-smarter/fake.database",
        },
    }
    (state_dir / "config.yml").write_text(
        yaml.safe_dump(settings, sort_keys=False),
        encoding="utf-8",
    )
    registry = fake_database_registry()
    workspace = initialize_workspace(root, database_registry=registry)
    archive = tmp_path / "fake-backup.ws.zip"

    with TestClient(create_app(root, database_registry=registry)) as client:
        assert client.get("/health").json()["database"] == {
            "backend": "fake",
            "initialized": True,
            "schema_version": 1,
            "latest_schema_version": 1,
        }

    WorkspaceOperations(workspace, database_registry=registry).backup(archive)

    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("WORK-SMARTER-BACKUP.json"))
        assert manifest["database"] == {
            "backend": "fake",
            "member": ".work-smarter/fake.database",
        }

    restored = tmp_path / "restored"
    WorkspaceOperations.restore(archive, restored, database_registry=registry)
    assert (restored / ".work-smarter/fake.database").read_bytes() == b"fake-database-v1"
