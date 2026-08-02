"""Application service for independent, text-first knowledge management."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import BaseModel

from work_smarter.errors import (
    AmbiguousEntityError,
    EntityNotFoundError,
    InvalidDocumentError,
)
from work_smarter.knowledge.errors import (
    KnowledgeConflictError,
    KnowledgeImportError,
    KnowledgeLinkError,
)
from work_smarter.knowledge.events import (
    KNOWLEDGE_NOTE_CREATED,
    KNOWLEDGE_NOTE_PROMOTED,
    KNOWLEDGE_NOTE_UPDATED,
)
from work_smarter.knowledge.models import (
    KnowledgeBacklink,
    KnowledgeDoctorIssue,
    KnowledgeDoctorReport,
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeNote,
    KnowledgeNoteType,
    KnowledgeSearchField,
    KnowledgeSearchHit,
    SourceReference,
    SourceReferenceKind,
    utc_now,
)
from work_smarter.knowledge.templates import render_knowledge_template
from work_smarter.storage.events import Event, EventStore
from work_smarter.storage.workspace import EntityRecord, Workspace


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _normalize_body(body: str) -> str:
    clean = body.strip("\n").rstrip()
    return clean + "\n" if clean.strip() else ""


def _link_key(link: KnowledgeLink) -> tuple[str, str]:
    return (link.relation.value, link.target_id.casefold())


class KnowledgeService:
    """The supported writer and query facade for knowledge notes."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.events: EventStore = workspace.event_store
        try:
            workspace.registry.require("knowledge_note")
        except ValueError as exc:
            raise InvalidDocumentError(
                "Workspace does not have the knowledge_note entity codec registered"
            ) from exc

    def _event(
        self,
        event_type: str,
        *,
        entity_id: str,
        payload: dict[str, object] | None = None,
    ) -> Event:
        return self.events.append(
            Event(
                id=_new_id("KEVT"),
                type=event_type,
                entity_id=entity_id,
                payload=payload or {},
            )
        )

    def _records(self) -> list[EntityRecord[BaseModel]]:
        return self.workspace.list_records("knowledge_note")

    def _document(self, record: EntityRecord[BaseModel]) -> KnowledgeDocument:
        note = cast(KnowledgeNote, record.entity)
        return KnowledgeDocument(
            note=note,
            body=_normalize_body(record.body),
            path=self.workspace.relative(record.path),
        )

    def _note_record(self, query: str) -> EntityRecord[BaseModel]:
        try:
            return self.workspace.find_record(query, kinds={"knowledge_note"})
        except EntityNotFoundError:
            alias = query.strip().casefold()
            matches = [
                record
                for record in self._records()
                if any(
                    item.casefold() == alias for item in cast(KnowledgeNote, record.entity).aliases
                )
            ]
            if not matches:
                raise
            if len(matches) > 1:
                ids = ", ".join(cast(KnowledgeNote, item.entity).id for item in matches[:5])
                raise AmbiguousEntityError(
                    f"Alias {query!r} identifies multiple knowledge notes: {ids}"
                ) from None
            return matches[0]

    def _entity_id_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for record in self.workspace.all_records(include_archive=True):
            entity_id = str(getattr(record.entity, "id", ""))
            if entity_id:
                index.setdefault(entity_id.casefold(), []).append(entity_id)
        return index

    def _assert_id_available(self, note_id: str) -> None:
        matches = self._entity_id_index().get(note_id.casefold(), [])
        if matches:
            raise KnowledgeConflictError(
                f"Stable ID {note_id!r} is already used by a workspace entity"
            )

    def _assert_aliases_available(
        self,
        aliases: Iterable[str],
        *,
        excluding_id: str | None = None,
    ) -> None:
        requested = {alias.casefold() for alias in aliases}
        if not requested:
            return
        for record in self._records():
            existing = cast(KnowledgeNote, record.entity)
            if excluding_id is not None and existing.id == excluding_id:
                continue
            collision = requested.intersection(alias.casefold() for alias in existing.aliases)
            if collision:
                alias = next(iter(sorted(collision)))
                raise KnowledgeConflictError(
                    f"Knowledge alias {alias!r} is already used by {existing.id}"
                )

    def _validate_links(self, note_id: str, links: Iterable[KnowledgeLink]) -> None:
        requested = list(links)
        seen: set[tuple[str, str]] = set()
        for link in requested:
            key = _link_key(link)
            if key in seen:
                raise KnowledgeLinkError(
                    f"Knowledge note {note_id} has a duplicate "
                    f"{link.relation.value} link to {link.target_id}"
                )
            seen.add(key)
            if link.target_id.casefold() == note_id.casefold():
                raise KnowledgeLinkError(f"Knowledge note {note_id} cannot link to itself")

        entity_ids = self._entity_id_index()
        for link in requested:
            matches = entity_ids.get(link.target_id.casefold(), [])
            if not matches:
                raise KnowledgeLinkError(f"Link target {link.target_id!r} does not exist")
            if len(matches) > 1:
                raise KnowledgeLinkError(
                    f"Link target {link.target_id!r} is ambiguous across workspace entities"
                )

    def create(
        self,
        *,
        title: str,
        note_type: KnowledgeNoteType | str = KnowledgeNoteType.NOTE,
        body: str | None = None,
        tags: Iterable[str] = (),
        aliases: Iterable[str] = (),
        links: Iterable[KnowledgeLink] = (),
        sources: Iterable[SourceReference] = (),
        note_id: str | None = None,
    ) -> KnowledgeDocument:
        """Create one note; omitted body content comes from the user's template."""

        with self.workspace.lock():
            return self._create_unlocked(
                title=title,
                note_type=note_type,
                body=body,
                tags=tags,
                aliases=aliases,
                links=links,
                sources=sources,
                note_id=note_id,
                event_type=KNOWLEDGE_NOTE_CREATED,
            )

    def _create_unlocked(
        self,
        *,
        title: str,
        note_type: KnowledgeNoteType | str,
        body: str | None,
        tags: Iterable[str],
        aliases: Iterable[str],
        links: Iterable[KnowledgeLink],
        sources: Iterable[SourceReference],
        note_id: str | None,
        event_type: str,
        event_payload: dict[str, object] | None = None,
    ) -> KnowledgeDocument:
        requested_type = KnowledgeNoteType(note_type)
        requested_aliases = list(aliases)
        requested_links = list(links)
        requested_sources = list(sources)
        now = utc_now()
        entity = KnowledgeNote(
            id=note_id or _new_id("KN"),
            note_type=requested_type,
            title=title,
            tags=list(tags),
            aliases=requested_aliases,
            links=requested_links,
            sources=requested_sources,
            created_at=now,
            updated_at=now,
        )
        self._assert_id_available(entity.id)
        self._assert_aliases_available(entity.aliases)
        self._validate_links(entity.id, entity.links)
        rendered_body = (
            render_knowledge_template(self.workspace, requested_type, title=entity.title)
            if body is None
            else body
        )
        normalized_body = _normalize_body(rendered_body)
        record = self.workspace.write(entity, normalized_body)
        self._event(
            event_type,
            entity_id=entity.id,
            payload={"note_type": entity.note_type.value, **(event_payload or {})},
        )
        return self._document(record)

    def get(self, query: str) -> KnowledgeDocument:
        """Resolve a full ID, unique ID prefix, or exact unique alias."""

        return self._document(self._note_record(query))

    def list(
        self,
        *,
        note_types: Iterable[KnowledgeNoteType | str] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[KnowledgeDocument]:
        """List notes, optionally requiring a type and every requested tag."""

        requested_types = (
            {KnowledgeNoteType(note_type) for note_type in note_types}
            if note_types is not None
            else None
        )
        requested_tags = (
            {tag.strip().lower() for tag in tags if tag.strip()} if tags is not None else None
        )
        documents: list[KnowledgeDocument] = []
        for record in self._records():
            note = cast(KnowledgeNote, record.entity)
            if requested_types is not None and note.note_type not in requested_types:
                continue
            if requested_tags is not None and not requested_tags.issubset(note.tags):
                continue
            documents.append(self._document(record))
        return documents

    def update(
        self,
        query: str,
        *,
        title: str | None = None,
        note_type: KnowledgeNoteType | str | None = None,
        body: str | None = None,
        tags: Iterable[str] | None = None,
        aliases: Iterable[str] | None = None,
        links: Iterable[KnowledgeLink] | None = None,
        sources: Iterable[SourceReference] | None = None,
    ) -> KnowledgeDocument:
        """Replace explicitly supplied note fields and increment its revision."""

        if all(value is None for value in (title, note_type, body, tags, aliases, links, sources)):
            return self.get(query)

        with self.workspace.lock():
            record = self._note_record(query)
            existing = cast(KnowledgeNote, record.entity)
            metadata = existing.model_dump(mode="json", exclude_computed_fields=True)
            changed_fields: list[str] = []
            replacements: tuple[tuple[str, object | None], ...] = (
                ("title", title),
                ("note_type", KnowledgeNoteType(note_type) if note_type is not None else None),
                ("tags", list(tags) if tags is not None else None),
                ("aliases", list(aliases) if aliases is not None else None),
                ("links", list(links) if links is not None else None),
                ("sources", list(sources) if sources is not None else None),
            )
            for field_name, value in replacements:
                if value is not None:
                    metadata[field_name] = value
                    changed_fields.append(field_name)
            if body is not None:
                changed_fields.append("body")
            metadata["updated_at"] = utc_now()
            metadata["revision"] = existing.revision + 1
            updated = KnowledgeNote.model_validate(metadata)
            self._assert_aliases_available(updated.aliases, excluding_id=existing.id)
            self._validate_links(existing.id, updated.links)
            normalized_body = _normalize_body(body if body is not None else record.body)
            updated_record = self.workspace.write(updated, normalized_body)
            self._event(
                KNOWLEDGE_NOTE_UPDATED,
                entity_id=existing.id,
                payload={"changed_fields": changed_fields, "revision": updated.revision},
            )
            return self._document(updated_record)

    def search(
        self,
        query: str,
        *,
        fields: Iterable[KnowledgeSearchField | str] | None = None,
    ) -> list[KnowledgeSearchHit]:
        """Case-insensitively search title, tags, Markdown body, and aliases."""

        needle = query.strip().casefold()
        if not needle:
            raise ValueError("Knowledge search query cannot be blank")
        requested = (
            {KnowledgeSearchField(field) for field in fields}
            if fields is not None
            else set(KnowledgeSearchField)
        )
        hits: list[KnowledgeSearchHit] = []
        for document in self.list():
            values = {
                KnowledgeSearchField.TITLE: [document.note.title],
                KnowledgeSearchField.TAG: document.note.tags,
                KnowledgeSearchField.BODY: [document.body],
                KnowledgeSearchField.ALIAS: document.note.aliases,
            }
            matches = [
                field
                for field in KnowledgeSearchField
                if field in requested and any(needle in value.casefold() for value in values[field])
            ]
            if matches:
                hits.append(
                    KnowledgeSearchHit(
                        note=document.note,
                        body=document.body,
                        path=document.path,
                        matched_fields=matches,
                    )
                )
        return hits

    def _resolve_target_id(self, query: str) -> str:
        try:
            record = self.workspace.find_record(query)
            return str(record.entity.id)
        except EntityNotFoundError:
            return self._document(self._note_record(query)).note.id

    def backlinks(self, target: str) -> list[KnowledgeBacklink]:
        """Return knowledge notes whose explicit links target an existing entity."""

        target_id = self._resolve_target_id(target)
        results: list[KnowledgeBacklink] = []
        for document in self.list():
            for link in document.note.links:
                if link.target_id.casefold() == target_id.casefold():
                    results.append(KnowledgeBacklink(source=document, link=link))
        return results

    def _promotions_for(self, source_id: str) -> list[KnowledgeDocument]:
        source_key = source_id.casefold()
        return [
            document
            for document in self.list()
            if any(
                reference.kind is SourceReferenceKind.ENTITY
                and reference.locator.casefold() == source_key
                for reference in document.note.sources
            )
        ]

    def promote_record(
        self,
        source: EntityRecord[BaseModel],
        *,
        note_type: KnowledgeNoteType | str = KnowledgeNoteType.NOTE,
        title: str | None = None,
        body: str | None = None,
        tags: Iterable[str] = (),
        aliases: Iterable[str] = (),
        links: Iterable[KnowledgeLink] = (),
        sources: Iterable[SourceReference] = (),
        note_id: str | None = None,
    ) -> KnowledgeDocument:
        """Promote any generic workspace record without importing its feature model."""

        source_id = str(getattr(source.entity, "id", "")).strip()
        source_kind = str(getattr(source.entity, "kind", "")).strip()
        source_title = str(getattr(source.entity, "title", "")).strip()
        if not source_id or not source_kind or not source_title:
            raise KnowledgeImportError(
                "Promoted records require public id, kind, and title attributes"
            )
        source_reference = SourceReference(
            kind=SourceReferenceKind.ENTITY,
            locator=source_id,
            title=f"{source_kind}: {source_title}",
        )
        requested_sources = [source_reference, *sources]
        with self.workspace.lock():
            existing = self._promotions_for(source_id)
            if len(existing) == 1:
                return existing[0]
            if len(existing) > 1:
                ids = ", ".join(document.note.id for document in existing[:5])
                raise KnowledgeConflictError(
                    f"Source {source_id!r} is claimed by multiple knowledge notes: {ids}"
                )
            return self._create_unlocked(
                title=title if title is not None else source_title,
                note_type=note_type,
                body=source.body if body is None else body,
                tags=tags,
                aliases=aliases,
                links=links,
                sources=requested_sources,
                note_id=note_id,
                event_type=KNOWLEDGE_NOTE_PROMOTED,
                event_payload={
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "source_path": self.workspace.relative(Path(source.path)),
                },
            )

    def doctor(self) -> KnowledgeDoctorReport:
        """Inspect the hand-editable graph for orphan, broken, and duplicate links."""

        documents = self.list()
        id_index = self._entity_id_index()
        connected_ids: set[str] = set()
        issues: list[KnowledgeDoctorIssue] = []

        for document in documents:
            if document.note.sources:
                connected_ids.add(document.note.id.casefold())
            seen: set[tuple[str, str]] = set()
            duplicate_keys: set[tuple[str, str]] = set()
            checked_targets: set[str] = set()
            for link in document.note.links:
                key = _link_key(link)
                if key in seen and key not in duplicate_keys:
                    issues.append(
                        KnowledgeDoctorIssue(
                            severity="warning",
                            code="duplicate_link",
                            message=(
                                f"{document.note.id} repeats a {link.relation.value} link "
                                f"to {link.target_id}"
                            ),
                            note_id=document.note.id,
                            target_id=link.target_id,
                            path=document.path,
                        )
                    )
                    duplicate_keys.add(key)
                seen.add(key)

                target_key = link.target_id.casefold()
                if target_key in checked_targets:
                    continue
                checked_targets.add(target_key)
                matches = id_index.get(target_key, [])
                if not matches:
                    issues.append(
                        KnowledgeDoctorIssue(
                            severity="error",
                            code="broken_link",
                            message=(
                                f"{document.note.id} links to missing entity {link.target_id}"
                            ),
                            note_id=document.note.id,
                            target_id=link.target_id,
                            path=document.path,
                        )
                    )
                elif len(matches) > 1:
                    issues.append(
                        KnowledgeDoctorIssue(
                            severity="error",
                            code="ambiguous_link",
                            message=(
                                f"{document.note.id} links to non-unique entity ID {link.target_id}"
                            ),
                            note_id=document.note.id,
                            target_id=link.target_id,
                            path=document.path,
                        )
                    )
                else:
                    connected_ids.add(document.note.id.casefold())
                    connected_ids.add(target_key)

        for document in documents:
            if document.note.id.casefold() not in connected_ids:
                issues.append(
                    KnowledgeDoctorIssue(
                        severity="warning",
                        code="orphan",
                        message=f"{document.note.id} has no valid links or backlinks",
                        note_id=document.note.id,
                        path=document.path,
                    )
                )

        counts: dict[str, int] = {"notes": len(documents)}
        for code in ("orphan", "broken_link", "duplicate_link", "ambiguous_link"):
            count = sum(issue.code == code for issue in issues)
            if count:
                counts[code] = count
        return KnowledgeDoctorReport(issues=issues, counts=counts)


__all__ = ["KnowledgeService"]
