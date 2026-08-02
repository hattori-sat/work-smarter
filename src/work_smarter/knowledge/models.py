"""Public, provider-neutral models for text-first knowledge records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from work_smarter.errors import InvalidDocumentError
from work_smarter.publishing.models import PublicationTarget
from work_smarter.storage.workspace import validate_entity_id


def utc_now() -> datetime:
    """Return an aware timestamp suitable for durable metadata."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Reject unknown frontmatter so hand-edited typos remain visible."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class KnowledgeNoteType(StrEnum):
    NOTE = "note"
    DECISION = "decision"
    HOW_TO = "how_to"
    REFERENCE = "reference"
    MEETING_NOTE = "meeting_note"
    TECHNICAL_REPORT = "technical_report"


class KnowledgePresentationMode(StrEnum):
    """Supported narrative-to-presentation projections."""

    TECHNICAL_REPORT = "technical_report"


class MarpPresentationFormat(StrEnum):
    """Output formats supported by the presentation adapter."""

    MARKDOWN = "markdown"
    HTML = "html"


class KnowledgeLinkType(StrEnum):
    RELATED_TO = "related_to"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"


class SourceReferenceKind(StrEnum):
    ENTITY = "entity"
    URL = "url"
    FILE = "file"
    CITATION = "citation"
    OTHER = "other"


class KnowledgeSearchField(StrEnum):
    TITLE = "title"
    TAG = "tag"
    BODY = "body"
    ALIAS = "alias"


def _nonblank(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank")
    return cleaned


def _stable_id(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    try:
        return validate_entity_id(cleaned)
    except InvalidDocumentError as exc:
        raise ValueError(f"invalid {field_name}: {cleaned!r}") from exc


class KnowledgeLink(StrictModel):
    """An explicit edge to a stable workspace entity ID."""

    target_id: str
    relation: KnowledgeLinkType = KnowledgeLinkType.RELATED_TO
    label: str | None = None

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str) -> str:
        return _stable_id(value, field_name="link target ID")

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value, field_name="link label")


class SourceReference(StrictModel):
    """A provider-neutral pointer to material from which a note was derived."""

    kind: SourceReferenceKind
    locator: str
    title: str | None = None

    @field_validator("locator")
    @classmethod
    def validate_locator(cls, value: str) -> str:
        return _nonblank(value, field_name="source locator")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value, field_name="source title")


class KnowledgeNote(StrictModel):
    """Frontmatter for one Markdown knowledge document."""

    schema_version: Literal[1] = 1
    id: str
    kind: Literal["knowledge_note"] = "knowledge_note"
    note_type: KnowledgeNoteType = KnowledgeNoteType.NOTE
    title: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    links: list[KnowledgeLink] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    publications: list[PublicationTarget] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(default=1, ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _stable_id(value, field_name="knowledge note ID")

    @field_validator("title")
    @classmethod
    def validate_note_title(cls, value: str) -> str:
        return _nonblank(value, field_name="title")

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return sorted({_nonblank(value, field_name="tag").lower() for value in values})

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = _nonblank(value, field_name="alias")
            key = cleaned.casefold()
            if key not in seen:
                aliases.append(cleaned)
                seen.add(key)
        return aliases

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("knowledge timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> KnowledgeNote:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class KnowledgeDocument(StrictModel):
    """A note together with its Markdown body and workspace-relative path."""

    note: KnowledgeNote
    body: str
    path: str


class MarpPresentation(StrictModel):
    """A reproducible Marp Markdown projection of one knowledge revision."""

    source_id: str
    source_revision: int = Field(ge=1)
    mode: KnowledgePresentationMode = KnowledgePresentationMode.TECHNICAL_REPORT
    theme: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    paginate: bool = True
    media_type: Literal["text/markdown"] = "text/markdown"
    file_extension: Literal[".marp.md"] = ".marp.md"
    markdown: str

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _stable_id(value, field_name="presentation source ID")


class MarpHtmlPresentation(StrictModel):
    """Browser-ready HTML compiled from one Marp projection."""

    source_id: str
    source_revision: int = Field(ge=1)
    mode: KnowledgePresentationMode
    theme: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    paginate: bool
    media_type: Literal["text/html"] = "text/html"
    file_extension: Literal[".html"] = ".html"
    html: str = Field(min_length=1)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _stable_id(value, field_name="presentation source ID")


class KnowledgeSearchHit(StrictModel):
    note: KnowledgeNote
    body: str
    path: str
    matched_fields: list[KnowledgeSearchField]


class KnowledgeBacklink(StrictModel):
    source: KnowledgeDocument
    link: KnowledgeLink


class KnowledgeDoctorIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: Literal["orphan", "broken_link", "duplicate_link", "ambiguous_link"]
    message: str
    note_id: str
    target_id: str | None = None
    path: str | None = None


class KnowledgeDoctorReport(StrictModel):
    checked_at: datetime = Field(default_factory=utc_now)
    issues: list[KnowledgeDoctorIssue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


__all__ = [
    "KnowledgeBacklink",
    "KnowledgeDoctorIssue",
    "KnowledgeDoctorReport",
    "KnowledgeDocument",
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
    "SourceReference",
    "SourceReferenceKind",
    "utc_now",
]
