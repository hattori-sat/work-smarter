from __future__ import annotations

from pathlib import Path

import pytest

from work_smarter.composition import initialize_workspace
from work_smarter.gtd.service import GtdService
from work_smarter.storage.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return initialize_workspace(tmp_path)


@pytest.fixture
def service(workspace: Workspace) -> GtdService:
    return GtdService(workspace)
