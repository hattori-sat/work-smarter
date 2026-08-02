"""Independent text-first knowledge management feature."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from work_smarter.knowledge.models import (
    KnowledgeBacklink,
    KnowledgeDoctorIssue,
    KnowledgeDoctorReport,
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeLinkType,
    KnowledgeNote,
    KnowledgeNoteType,
    KnowledgePresentationMode,
    KnowledgeSearchField,
    KnowledgeSearchHit,
    MarpHtmlPresentation,
    MarpPresentation,
    MarpPresentationFormat,
    MarpPresentationTemplate,
    SourceReference,
    SourceReferenceKind,
)

if TYPE_CHECKING:
    from work_smarter.features import FeatureRegistry
    from work_smarter.knowledge.service import KnowledgeService


class KnowledgeFeature:
    """Feature descriptor registered by the application composition root."""

    name = "knowledge"
    version = "0.1"

    def register(self, registry: FeatureRegistry) -> None:
        from work_smarter.knowledge.persistence import KNOWLEDGE_ENTITY_SPECS
        from work_smarter.knowledge.templates import initialize_knowledge_templates

        for spec in KNOWLEDGE_ENTITY_SPECS:
            registry.add_entity(spec)
        registry.add_workspace_initializer(initialize_knowledge_templates)


def __getattr__(name: str) -> Any:
    if name == "KnowledgeService":
        from work_smarter.knowledge.service import KnowledgeService

        return KnowledgeService
    raise AttributeError(name)


__all__ = [
    "KnowledgeBacklink",
    "KnowledgeDoctorIssue",
    "KnowledgeDoctorReport",
    "KnowledgeDocument",
    "KnowledgeFeature",
    "KnowledgeLink",
    "KnowledgeLinkType",
    "KnowledgeNote",
    "KnowledgeNoteType",
    "KnowledgePresentationMode",
    "KnowledgeSearchField",
    "KnowledgeSearchHit",
    "MarpHtmlPresentation",
    "MarpPresentation",
    "MarpPresentationFormat",
    "MarpPresentationTemplate",
    "KnowledgeService",
    "SourceReference",
    "SourceReferenceKind",
]
