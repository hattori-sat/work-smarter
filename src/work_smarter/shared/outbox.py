"""Provider-neutral transactional outbox delivery worker."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from work_smarter.shared.persistence.database import OutboxMessage, StructuredStateStore


class OutboxDestination(Protocol):
    """Idempotent external destination selected by a stable name."""

    def deliver(self, message: OutboxMessage) -> None:
        """Deliver one message using ``operation_id`` as the idempotency key."""


class OutboxRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claimed: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    unavailable: int = Field(ge=0)


class OutboxWorker:
    """Claim, deliver, and retry outbox messages without holding a DB transaction."""

    def __init__(
        self,
        store: StructuredStateStore,
        destinations: Mapping[str, OutboxDestination],
        *,
        retry_delay: timedelta = timedelta(minutes=1),
    ) -> None:
        self.store = store
        self.destinations = dict(destinations)
        self.retry_delay = retry_delay

    def run_once(
        self,
        *,
        now: datetime | None = None,
        limit: int = 25,
    ) -> OutboxRunReport:
        moment = now or datetime.now(UTC)
        lease_token = f"LEASE-{uuid4().hex}"
        messages = self.store.claim_outbox(
            lease_token=lease_token,
            now=moment.isoformat(),
            limit=limit,
        )
        completed = 0
        failed = 0
        unavailable = 0
        for message in messages:
            destination = self.destinations.get(message.destination)
            if destination is None:
                unavailable += 1
                self.store.fail_outbox(
                    message.id,
                    lease_token=lease_token,
                    error=f"Destination is not installed: {message.destination}",
                    available_at=(moment + self.retry_delay).isoformat(),
                )
                continue
            try:
                destination.deliver(message)
            except Exception as exc:
                failed += 1
                self.store.fail_outbox(
                    message.id,
                    lease_token=lease_token,
                    error=str(exc),
                    available_at=(moment + self.retry_delay).isoformat(),
                )
                continue
            self.store.complete_outbox(message.id, lease_token=lease_token)
            completed += 1
        return OutboxRunReport(
            claimed=len(messages),
            completed=completed,
            failed=failed,
            unavailable=unavailable,
        )


__all__ = ["OutboxDestination", "OutboxRunReport", "OutboxWorker"]
