"""Append-only event history for timers, transitions, and reviews."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    id: str
    type: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=utc_now)
    entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventStore:
    """Durable JSON Lines log using an advisory process lock for appends."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, event: Event) -> Event:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = event.model_dump_json(exclude_none=True) + "\n"
        with self.path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return event

    def read_all(self) -> list[Event]:
        if not self.path.exists():
            return []
        events: list[Event] = []
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    events.append(Event.model_validate_json(line))
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Invalid event at {self.path}:{line_number}: {exc}") from exc
        return events
