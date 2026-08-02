"""Typed HTTP adapter for the independent knowledge feature."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from work_smarter.errors import InvalidDocumentError
from work_smarter.knowledge.models import (
    KnowledgeBacklink,
    KnowledgeDoctorReport,
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeLinkType,
    KnowledgeNoteType,
    KnowledgePresentationMode,
    KnowledgeSearchField,
    KnowledgeSearchHit,
    MarpPresentation,
    SourceReference,
    SourceReferenceKind,
)
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.storage.workspace import validate_entity_id

NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MarpTheme = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    ),
]


class KnowledgeApiModel(BaseModel):
    """Reject unknown HTTP fields to expose client typos immediately."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeLinkRequest(KnowledgeApiModel):
    """Provider-neutral outbound link supplied by an API client."""

    target_id: NonBlankString
    relation: KnowledgeLinkType = KnowledgeLinkType.RELATED_TO
    label: NonBlankString | None = None

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str) -> str:
        try:
            return validate_entity_id(value)
        except InvalidDocumentError as exc:
            raise ValueError(str(exc)) from exc

    def to_domain(self) -> KnowledgeLink:
        return KnowledgeLink.model_validate(self.model_dump())


class SourceReferenceRequest(KnowledgeApiModel):
    """Provider-neutral source reference supplied by an API client."""

    kind: SourceReferenceKind
    locator: NonBlankString
    title: NonBlankString | None = None

    def to_domain(self) -> SourceReference:
        return SourceReference.model_validate(self.model_dump())


class KnowledgeCreateRequest(KnowledgeApiModel):
    title: NonBlankString
    note_type: KnowledgeNoteType = KnowledgeNoteType.NOTE
    body: str | None = None
    tags: list[NonBlankString] = Field(default_factory=list)
    aliases: list[NonBlankString] = Field(default_factory=list)
    links: list[KnowledgeLinkRequest] = Field(default_factory=list)
    sources: list[SourceReferenceRequest] = Field(default_factory=list)
    note_id: NonBlankString | None = None

    @field_validator("note_id")
    @classmethod
    def validate_note_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_entity_id(value)
        except InvalidDocumentError as exc:
            raise ValueError(str(exc)) from exc


class KnowledgeUpdateRequest(KnowledgeApiModel):
    title: NonBlankString | None = None
    note_type: KnowledgeNoteType | None = None
    body: str | None = None
    tags: list[NonBlankString] | None = None
    aliases: list[NonBlankString] | None = None
    links: list[KnowledgeLinkRequest] | None = None
    sources: list[SourceReferenceRequest] | None = None


class KnowledgePromoteRequest(KnowledgeApiModel):
    note_type: KnowledgeNoteType = KnowledgeNoteType.NOTE
    title: NonBlankString | None = None
    body: str | None = None
    tags: list[NonBlankString] = Field(default_factory=list)
    aliases: list[NonBlankString] = Field(default_factory=list)
    links: list[KnowledgeLinkRequest] = Field(default_factory=list)
    sources: list[SourceReferenceRequest] = Field(default_factory=list)
    note_id: NonBlankString | None = None

    @field_validator("note_id")
    @classmethod
    def validate_note_id(cls, value: str | None) -> str | None:
        return KnowledgeCreateRequest.validate_note_id(value)


KnowledgeServiceDependency = Callable[..., KnowledgeService]


def _links(requests: list[KnowledgeLinkRequest]) -> list[KnowledgeLink]:
    return [request.to_domain() for request in requests]


def _sources(requests: list[SourceReferenceRequest]) -> list[SourceReference]:
    return [request.to_domain() for request in requests]


def create_knowledge_router(
    service_dependency: KnowledgeServiceDependency,
) -> APIRouter:
    """Create the statically mounted knowledge HTTP contract."""

    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
    service_dep = Depends(service_dependency)

    @router.post("/notes", status_code=201)
    def create_note(
        payload: KnowledgeCreateRequest,
        service: KnowledgeService = service_dep,
    ) -> KnowledgeDocument:
        return service.create(
            title=payload.title,
            note_type=payload.note_type,
            body=payload.body,
            tags=payload.tags,
            aliases=payload.aliases,
            links=_links(payload.links),
            sources=_sources(payload.sources),
            note_id=payload.note_id,
        )

    @router.get("/notes")
    def list_notes(
        note_types: Annotated[
            list[KnowledgeNoteType] | None,
            Query(alias="note_type"),
        ] = None,
        tags: Annotated[list[str] | None, Query(alias="tag")] = None,
        service: KnowledgeService = service_dep,
    ) -> list[KnowledgeDocument]:
        return service.list(note_types=note_types, tags=tags)

    @router.get("/notes/{note_id}")
    def get_note(
        note_id: str,
        service: KnowledgeService = service_dep,
    ) -> KnowledgeDocument:
        return service.get(note_id)

    @router.get("/notes/{note_id}/presentations/marp")
    def render_marp(
        note_id: str,
        mode: KnowledgePresentationMode = KnowledgePresentationMode.TECHNICAL_REPORT,
        theme: MarpTheme = "default",
        paginate: bool = True,
        service: KnowledgeService = service_dep,
    ) -> MarpPresentation:
        return service.render_presentation(
            note_id,
            mode=mode,
            theme=theme,
            paginate=paginate,
        )

    @router.patch("/notes/{note_id}")
    def update_note(
        note_id: str,
        payload: KnowledgeUpdateRequest,
        service: KnowledgeService = service_dep,
    ) -> KnowledgeDocument:
        return service.update(
            note_id,
            title=payload.title,
            note_type=payload.note_type,
            body=payload.body,
            tags=payload.tags,
            aliases=payload.aliases,
            links=None if payload.links is None else _links(payload.links),
            sources=None if payload.sources is None else _sources(payload.sources),
        )

    @router.get("/search")
    def search_notes(
        query: Annotated[str, Query(alias="q", min_length=1)],
        fields: Annotated[
            list[KnowledgeSearchField] | None,
            Query(alias="field"),
        ] = None,
        service: KnowledgeService = service_dep,
    ) -> list[KnowledgeSearchHit]:
        if not query.strip():
            raise InvalidDocumentError("Knowledge search query cannot be blank")
        return service.search(query, fields=fields)

    @router.get("/backlinks/{target_id}")
    def backlinks(
        target_id: str,
        service: KnowledgeService = service_dep,
    ) -> list[KnowledgeBacklink]:
        return service.backlinks(target_id)

    @router.post("/records/{record_id}/promote", status_code=201)
    def promote_record(
        record_id: str,
        payload: KnowledgePromoteRequest,
        service: KnowledgeService = service_dep,
    ) -> KnowledgeDocument:
        source = service.workspace.find_record(record_id)
        return service.promote_record(
            source,
            note_type=payload.note_type,
            title=payload.title,
            body=payload.body,
            tags=payload.tags,
            aliases=payload.aliases,
            links=_links(payload.links),
            sources=_sources(payload.sources),
            note_id=payload.note_id,
        )

    @router.get("/doctor")
    def doctor(service: KnowledgeService = service_dep) -> KnowledgeDoctorReport:
        return service.doctor()

    return router


__all__ = [
    "KnowledgeCreateRequest",
    "KnowledgeLinkRequest",
    "KnowledgePromoteRequest",
    "KnowledgeUpdateRequest",
    "SourceReferenceRequest",
    "create_knowledge_router",
]
