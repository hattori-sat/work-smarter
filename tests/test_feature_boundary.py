from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from work_smarter.composition import compose_features
from work_smarter.features import FeatureRegistry
from work_smarter.gtd.persistence import GTD_ENTITY_REGISTRY
from work_smarter.storage.workspace import EntitySpec


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
