"""Small public contract for mapping Markdown entities to publishers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    target: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("publication provider cannot be blank")
        return cleaned


class PublishableDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_kind: str
    title: str
    markdown: str
    path: str
    revision: int = Field(ge=1)
    publication: PublicationTarget


__all__ = ["PublicationTarget", "PublishableDocument"]
