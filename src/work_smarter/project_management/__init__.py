"""Project-management feature boundary.

GTD projects remain part of :mod:`work_smarter.gtd`.  WBS, schedules, Gantt,
QCD, requirements, and review gates will be implemented here without changing
the GTD state machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from work_smarter.features import FeatureRegistry


class ProjectManagementFeature:
    """Reserved extension point for the separately delivered PM capability."""

    name = "project-management"
    version = "0.1"

    def register(self, registry: FeatureRegistry) -> None:
        """The first release intentionally exposes no PM commands or routes."""
