from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import pytest
import yaml
from pydantic import BaseModel

from work_smarter.composition import compose_features, initialize_workspace, open_workspace
from work_smarter.errors import InvalidDocumentError
from work_smarter.features import FeatureRegistry
from work_smarter.gtd.persistence import GTD_ENTITY_REGISTRY
from work_smarter.storage.frontmatter import write_markdown
from work_smarter.storage.workspace import EntitySpec, Workspace


class FakeNote(BaseModel):
    id: str
    kind: Literal["fake_note"] = "fake_note"
    title: str


class FakeFeature:
    name = "fake"
    version = "1"

    def register(self, registry: FeatureRegistry) -> None:
        registry.add_entity(EntitySpec("fake_note", FakeNote, "fake/notes"))


def test_generic_storage_imports_without_loading_gtd() -> None:
    source_root = Path(__file__).parents[1] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from work_smarter.storage.workspace import Workspace; "
                "import sys; "
                "assert 'work_smarter.gtd' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_knowledge_package_imports_without_loading_gtd() -> None:
    source_root = Path(__file__).parents[1] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import work_smarter.knowledge; "
                "import sys; "
                "assert 'work_smarter.gtd' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_gtd_owns_namespaced_directories() -> None:
    directories = {spec.kind: spec.directory for spec in GTD_ENTITY_REGISTRY.specs}

    assert directories["gtd_project"] == "gtd/projects"
    assert directories["reference"] == "knowledge/gtd"
    assert len(set(directories.values())) == len(directories)


def test_new_feature_can_register_a_codec_without_changing_storage() -> None:
    composition = compose_features(["fake"], extra=[FakeFeature()])

    spec = composition.entity_registry().require("fake_note")
    assert spec.model is FakeNote
    assert spec.directory == "fake/notes"


def test_knowledge_can_be_composed_without_gtd() -> None:
    composition = compose_features(["knowledge"])
    registry = composition.entity_registry()

    assert registry.require("knowledge_note").directory == "knowledge/notes"
    assert registry.get("task") is None
    assert registry.get("gtd_project") is None


def test_builtin_feature_directories_do_not_collide() -> None:
    registry = compose_features(["gtd", "knowledge"]).entity_registry()
    directories = [spec.directory for spec in registry.specs]

    assert len(directories) == len(set(directories))
    assert registry.require("reference").directory == "knowledge/gtd"
    assert registry.require("knowledge_note").directory == "knowledge/notes"


def test_fresh_workspace_config_matches_initialized_features(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "fresh")
    settings = workspace.settings()
    composed = compose_features(settings.features)

    assert settings.features == ["gtd", "knowledge", "project-management"]
    assert settings.database.backend == "sqlite"
    assert {spec.kind for spec in workspace.registry.specs} == {
        spec.kind for spec in composed.entity_registry().specs
    }
    assert all((workspace.root / spec.directory).is_dir() for spec in workspace.registry.specs)
    assert (workspace.root / "templates/gtd/task.md").is_file()
    assert (workspace.root / "templates/knowledge/note.md").is_file()
    assert (workspace.root / "templates/project-management/managed-project.md").is_file()
    assert (workspace.state_dir / "work-smarter.db").is_file()


def test_disabled_knowledge_kind_is_not_guessed_from_disk(tmp_path: Path) -> None:
    workspace = Workspace.initialize(
        tmp_path,
        compose_features(["gtd"]).entity_registry(),
    )
    settings = workspace.settings().model_copy(update={"features": ["gtd"]})
    workspace.config_path.write_text(
        yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    reinitialized = initialize_workspace(workspace.root)

    assert reinitialized.settings().features == ["gtd"]
    assert reinitialized.registry.get("knowledge_note") is None

    note_path = workspace.root / "knowledge/notes/KN-DISABLED.md"
    write_markdown(
        note_path,
        {
            "schema_version": 1,
            "id": "KN-DISABLED",
            "kind": "knowledge_note",
            "title": "Should remain disabled",
        },
        "Body\n",
    )

    reopened = open_workspace(workspace.root)

    assert reopened.settings().features == ["gtd"]
    assert reopened.registry.get("knowledge_note") is None
    with pytest.raises(InvalidDocumentError, match="unknown entity kind 'knowledge_note'"):
        reopened.read(note_path)
