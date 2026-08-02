"""Confluence synchronization state and observable results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_smarter.publishing.models import PublishableDocument


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfluenceTarget(StrictModel):
    space_key: str = Field(min_length=1)
    page_id: str | None = None
    parent_id: str | None = None
    title: str | None = None

    @field_validator("space_key", "page_id", "parent_id", "title")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return None if value is None else (value.strip() or None)


class SyncDirection(StrEnum):
    PUSH = "push"
    PULL = "pull"


class SyncAction(StrEnum):
    NOOP = "noop"
    CREATE_REMOTE = "create_remote"
    UPDATE_REMOTE = "update_remote"
    UPDATE_LOCAL = "update_local"
    LOCAL_AHEAD = "local_ahead"
    REMOTE_AHEAD = "remote_ahead"
    CONFLICT = "conflict"
    UNTRACKED_REMOTE = "untracked_remote"


class ConfluenceSyncState(StrictModel):
    schema_version: int = 1
    source_id: str
    page_id: str
    remote_version: int = Field(ge=1)
    local_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    synced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SyncPlan(StrictModel):
    source_id: str
    direction: SyncDirection
    action: SyncAction
    local_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_hash: str | None = None
    remote_version: int | None = None
    warnings: list[str] = Field(default_factory=list)


class SyncResult(StrictModel):
    plan: SyncPlan
    mutated: bool = False
    page_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    document: PublishableDocument | None = None


class ConfluenceDoctorIssue(StrictModel):
    code: str
    message: str
    source_id: str | None = None
    severity: str = "error"


class ConfluenceDoctorReport(StrictModel):
    issues: list[ConfluenceDoctorIssue] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


__all__ = [
    "ConfluenceDoctorIssue",
    "ConfluenceDoctorReport",
    "ConfluenceSyncState",
    "ConfluenceTarget",
    "SyncAction",
    "SyncDirection",
    "SyncPlan",
    "SyncResult",
]
