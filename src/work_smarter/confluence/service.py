"""Conflict-aware publication service for provider-neutral Markdown entities."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from pydantic import BaseModel

from work_smarter.confluence.client import ConfluencePage, ConfluenceSpace
from work_smarter.confluence.conversion import markdown_to_storage, storage_to_markdown
from work_smarter.confluence.errors import ConfluenceSyncConflictError
from work_smarter.confluence.models import (
    ConfluenceDoctorIssue,
    ConfluenceDoctorReport,
    ConfluenceSyncState,
    ConfluenceTarget,
    SyncAction,
    SyncDirection,
    SyncPlan,
    SyncResult,
)
from work_smarter.publishing.models import PublicationTarget, PublishableDocument
from work_smarter.storage.events import Event, EventStore
from work_smarter.storage.workspace import EntityRecord, Workspace


class PublisherClient(Protocol):
    def resolve_space(self, space_key: str) -> ConfluenceSpace: ...

    def get_page(self, page_id: str) -> ConfluencePage: ...

    def create_page(
        self,
        *,
        space_id: str,
        title: str,
        storage: str,
        parent_id: str | None = None,
    ) -> ConfluencePage: ...

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        storage: str,
        current_version: int,
        parent_id: str | None = None,
        message: str = "Published by Work Smarter",
    ) -> ConfluencePage: ...


def _event_id() -> str:
    return f"CEVT-{uuid4().hex[:12].upper()}"


def _hash(title: str, storage: str) -> str:
    value = json.dumps({"title": title, "storage": storage}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


class _StateStore:
    def __init__(self, workspace: Workspace):
        self.directory = workspace.state_dir / "sync" / "confluence"

    def path(self, source_id: str) -> Path:
        return self.directory / f"{source_id}.json"

    def load(self, source_id: str) -> ConfluenceSyncState | None:
        path = self.path(source_id)
        if not path.is_file():
            return None
        try:
            return ConfluenceSyncState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfluenceSyncConflictError(f"Invalid Confluence sync state: {path}") from exc

    def save(self, state: ConfluenceSyncState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(state.source_id)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(state.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, path)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ConfluenceSyncConflictError(
                f"Cannot write Confluence sync state: {path}"
            ) from exc


class ConfluencePublishingService:
    """Use frontmatter mapping for intent and sidecar state for sync bookkeeping."""

    def __init__(self, workspace: Workspace, client: PublisherClient):
        self.workspace = workspace
        self.client = client
        self.events: EventStore = workspace.event_store
        self.states = _StateStore(workspace)

    def _event(self, event_type: str, source_id: str, payload: dict[str, object]) -> None:
        self.events.append(
            Event(id=_event_id(), type=event_type, entity_id=source_id, payload=payload)
        )

    def _record(self, query: str) -> EntityRecord[BaseModel]:
        return cast(EntityRecord[BaseModel], self.workspace.find_record(query))

    @staticmethod
    def _publication(entity: BaseModel) -> PublicationTarget:
        publications = getattr(entity, "publications", None)
        if publications is None:
            raise ValueError("entity does not expose publication metadata")
        matches = [item for item in publications if item.provider == "confluence"]
        if len(matches) > 1:
            raise ValueError("entity has multiple Confluence publication mappings")
        if not matches:
            raise ValueError("entity has no Confluence publication mapping")
        return cast(PublicationTarget, matches[0])

    def _document(self, record: EntityRecord[BaseModel]) -> PublishableDocument:
        entity = record.entity
        publication = self._publication(entity)
        return PublishableDocument(
            source_id=str(entity.id),
            source_kind=str(entity.kind),
            title=str(entity.title),
            markdown=record.body,
            path=self.workspace.relative(record.path),
            revision=int(getattr(entity, "revision", 1)),
            publication=publication,
        )

    def get_document(self, query: str) -> PublishableDocument:
        return self._document(self._record(query))

    def configure(
        self,
        query: str,
        *,
        space_key: str,
        page_id: str | None = None,
        parent_id: str | None = None,
        title: str | None = None,
    ) -> PublishableDocument:
        with self.workspace.lock():
            record = self._record(query)
            entity = record.entity
            publications = getattr(entity, "publications", None)
            if publications is None:
                raise ValueError("entity does not expose publication metadata")
            target = ConfluenceTarget(
                space_key=space_key,
                page_id=page_id,
                parent_id=parent_id,
                title=title,
            )
            replacement = PublicationTarget(
                provider="confluence",
                target=target.model_dump(exclude_none=True),
            )
            updated_publications = [item for item in publications if item.provider != "confluence"]
            updated_publications.append(replacement)
            metadata = entity.model_dump(mode="json", exclude_computed_fields=True)
            metadata["publications"] = [
                item.model_dump(mode="json") for item in updated_publications
            ]
            if "revision" in metadata:
                metadata["revision"] = int(metadata["revision"]) + 1
            if "updated_at" in metadata:
                metadata["updated_at"] = datetime.now(UTC).isoformat()
            updated = type(entity).model_validate(metadata)
            new_record = self.workspace.write(updated, record.body)
            self._event(
                "confluence.mapping.configured",
                str(entity.id),
                {"space_key": target.space_key, "page_id": target.page_id},
            )
            return self._document(new_record)

    def _local_storage(self, document: PublishableDocument) -> tuple[str, list[str]]:
        from work_smarter.confluence.conversion import markdown_to_storage

        converted = markdown_to_storage(document.markdown)
        return converted.value, [warning.message for warning in converted.warnings]

    def _target(self, document: PublishableDocument) -> ConfluenceTarget:
        return ConfluenceTarget.model_validate(document.publication.target)

    def plan(
        self,
        query: str,
        *,
        direction: SyncDirection,
    ) -> SyncPlan:
        document = self.get_document(query)
        target = self._target(document)
        local_storage, warnings = self._local_storage(document)
        local_hash = _hash(target.title or document.title, local_storage)
        state = self.states.load(document.source_id)
        if target.page_id is None:
            if direction is SyncDirection.PULL:
                raise ConfluenceSyncConflictError("Cannot pull without a mapped page_id")
            return SyncPlan(
                source_id=document.source_id,
                direction=direction,
                action=SyncAction.CREATE_REMOTE,
                local_hash=local_hash,
                warnings=warnings,
            )
        remote = self.client.get_page(target.page_id)
        remote_hash = _hash(remote.title, remote.storage)
        if state is None:
            return SyncPlan(
                source_id=document.source_id,
                direction=direction,
                action=SyncAction.UNTRACKED_REMOTE,
                local_hash=local_hash,
                remote_hash=remote_hash,
                remote_version=remote.version,
                warnings=warnings,
            )
        local_changed = local_hash != state.local_hash
        remote_changed = remote_hash != state.remote_hash or remote.version != state.remote_version
        if local_changed and remote_changed:
            action = SyncAction.CONFLICT
        elif direction is SyncDirection.PUSH:
            action = (
                SyncAction.UPDATE_REMOTE
                if local_changed
                else (SyncAction.REMOTE_AHEAD if remote_changed else SyncAction.NOOP)
            )
        else:
            action = (
                SyncAction.UPDATE_LOCAL
                if remote_changed
                else (SyncAction.LOCAL_AHEAD if local_changed else SyncAction.NOOP)
            )
        return SyncPlan(
            source_id=document.source_id,
            direction=direction,
            action=action,
            local_hash=local_hash,
            remote_hash=remote_hash,
            remote_version=remote.version,
            warnings=warnings,
        )

    def _save_state(
        self,
        document: PublishableDocument,
        *,
        page: ConfluencePage,
        local_storage: str,
    ) -> None:
        self.states.save(
            ConfluenceSyncState(
                source_id=document.source_id,
                page_id=page.id,
                remote_version=page.version,
                local_hash=_hash(self._target(document).title or document.title, local_storage),
                remote_hash=_hash(page.title, page.storage),
            )
        )

    def _set_page_id(self, document: PublishableDocument, page_id: str) -> PublishableDocument:
        target = self._target(document)
        return self.configure(
            document.source_id,
            space_key=target.space_key,
            page_id=page_id,
            parent_id=target.parent_id,
            title=target.title,
        )

    def push(self, query: str, *, dry_run: bool = False, force: bool = False) -> SyncResult:
        document = self.get_document(query)
        plan = self.plan(query, direction=SyncDirection.PUSH)
        blocked = {
            SyncAction.REMOTE_AHEAD,
            SyncAction.CONFLICT,
            SyncAction.UNTRACKED_REMOTE,
        }
        if plan.action in blocked and not force:
            raise ConfluenceSyncConflictError(f"Confluence push blocked: {plan.action.value}")
        if dry_run:
            return SyncResult(plan=plan, warnings=plan.warnings)
        storage, warnings = self._local_storage(document)
        target = self._target(document)
        if plan.action is SyncAction.CREATE_REMOTE:
            space = self.client.resolve_space(target.space_key)
            page = self.client.create_page(
                space_id=space.id,
                title=target.title or document.title,
                storage=storage,
                parent_id=target.parent_id,
            )
            mapped = self._set_page_id(document, page.id)
            self._save_state(mapped, page=page, local_storage=storage)
            self._event("confluence.page.pushed", document.source_id, {"page_id": page.id})
            return SyncResult(
                plan=plan,
                mutated=True,
                page_id=page.id,
                warnings=warnings,
                document=mapped,
            )
        if plan.action is SyncAction.NOOP:
            return SyncResult(plan=plan, page_id=target.page_id, warnings=warnings)
        page = self.client.get_page(cast(str, target.page_id))
        updated_page = self.client.update_page(
            page_id=page.id,
            title=target.title or document.title,
            storage=storage,
            current_version=page.version,
            parent_id=target.parent_id,
        )
        self._save_state(document, page=updated_page, local_storage=storage)
        self._event("confluence.page.pushed", document.source_id, {"page_id": page.id})
        return SyncResult(
            plan=plan,
            mutated=True,
            page_id=page.id,
            warnings=warnings,
            document=document,
        )

    def pull(
        self,
        query: str,
        *,
        force: bool = False,
        accept_loss: bool = False,
    ) -> SyncResult:
        document = self.get_document(query)
        plan = self.plan(query, direction=SyncDirection.PULL)
        if (
            plan.action
            in {
                SyncAction.UNTRACKED_REMOTE,
                SyncAction.CONFLICT,
                SyncAction.LOCAL_AHEAD,
            }
            and not force
        ):
            raise ConfluenceSyncConflictError(f"Confluence pull blocked: {plan.action.value}")
        page = self.client.get_page(cast(str, self._target(document).page_id))
        converted = storage_to_markdown(page.storage)
        warnings = [warning.message for warning in converted.warnings]
        if warnings and not accept_loss:
            raise ConfluenceSyncConflictError(
                "Confluence pull has conversion warnings; use accept_loss explicitly"
            )
        if plan.action is SyncAction.NOOP:
            return SyncResult(plan=plan, page_id=page.id, warnings=warnings)
        with self.workspace.lock():
            record = self._record(document.source_id)
            entity = record.entity
            metadata = entity.model_dump(mode="json", exclude_computed_fields=True)
            if "revision" in metadata:
                metadata["revision"] = int(metadata["revision"]) + 1
            if "updated_at" in metadata:
                metadata["updated_at"] = datetime.now(UTC).isoformat()
            updated = type(entity).model_validate(metadata)
            new_record = self.workspace.write(updated, converted.value)
            updated_document = self._document(new_record)
            round_trip_storage = markdown_to_storage(converted.value).value
            self._save_state(updated_document, page=page, local_storage=round_trip_storage)
            self._event("confluence.page.pulled", document.source_id, {"page_id": page.id})
        return SyncResult(
            plan=plan,
            mutated=True,
            page_id=page.id,
            warnings=warnings,
            document=updated_document,
        )

    def doctor(self) -> ConfluenceDoctorReport:
        issues: list[ConfluenceDoctorIssue] = []
        for record in self.workspace.all_records():
            publications = getattr(record.entity, "publications", None)
            if not publications:
                continue
            for publication in publications:
                if publication.provider != "confluence":
                    continue
                try:
                    target = ConfluenceTarget.model_validate(publication.target)
                    if target.page_id and self.states.load(str(record.entity.id)) is None:
                        issues.append(
                            ConfluenceDoctorIssue(
                                code="untracked_remote",
                                message="mapping has page_id but no local sync state",
                                source_id=str(record.entity.id),
                                severity="warning",
                            )
                        )
                except ValueError as exc:
                    issues.append(
                        ConfluenceDoctorIssue(
                            code="invalid_mapping",
                            message=str(exc),
                            source_id=str(record.entity.id),
                        )
                    )
        return ConfluenceDoctorReport(issues=issues)


__all__ = ["ConfluencePublishingService", "PublisherClient"]
