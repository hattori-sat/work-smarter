"""GTD feature: capture, clarify, organize, engage, and reflect."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from work_smarter.gtd.models import (
    ClarifyDecision,
    GtdProject,
    InboxItem,
    Task,
    TaskStatus,
)

if TYPE_CHECKING:
    from work_smarter.features import FeatureRegistry
    from work_smarter.gtd.service import GtdService


class GtdFeature:
    """Feature descriptor loaded through the public extension registry."""

    name = "gtd"
    version = "0.1"

    def register(self, registry: FeatureRegistry) -> None:
        """Register GTD-owned persistence contracts with the composition root."""

        from work_smarter.gtd.persistence import GTD_ENTITY_SPECS
        from work_smarter.gtd.templates import initialize_gtd_templates

        for spec in GTD_ENTITY_SPECS:
            registry.add_entity(spec)
        registry.add_workspace_initializer(initialize_gtd_templates)


def __getattr__(name: str) -> Any:
    if name == "GtdService":
        from work_smarter.gtd.service import GtdService

        return GtdService
    raise AttributeError(name)


__all__ = [
    "ClarifyDecision",
    "GtdFeature",
    "GtdProject",
    "GtdService",
    "InboxItem",
    "Task",
    "TaskStatus",
]
