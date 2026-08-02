"""Keyboard-first CLI adapter for provider-neutral knowledge notes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Protocol, cast

import typer
from pydantic import BaseModel, ValidationError

from work_smarter.errors import EntityNotFoundError
from work_smarter.knowledge.models import (
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeLinkType,
    KnowledgeNoteType,
    KnowledgePresentationMode,
    KnowledgeSearchField,
    SourceReference,
    SourceReferenceKind,
)
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.storage.workspace import Workspace

app = typer.Typer(
    help="Capture, connect, search, and maintain Markdown knowledge notes.",
    no_args_is_help=True,
)
presentation_app = typer.Typer(
    help="Render knowledge as presentation projections.",
    no_args_is_help=True,
)
app.add_typer(presentation_app, name="presentation")


class _RootCliState(Protocol):
    workspace: Path
    json_output: bool


def _state(ctx: typer.Context) -> _RootCliState:
    state = ctx.find_root().obj
    if state is None:
        raise RuntimeError("Knowledge commands require the Work Smarter root CLI")
    return cast(_RootCliState, state)


def _workspace(ctx: typer.Context) -> Workspace:
    # Import here so the feature CLI stays independent from the root CLI module.
    from work_smarter.composition import open_workspace

    return open_workspace(_state(ctx).workspace)


def _service(ctx: typer.Context) -> KnowledgeService:
    return KnowledgeService(_workspace(ctx))


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _emit_json(value: object) -> None:
    typer.echo(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, default=str))


def _show_document(document: KnowledgeDocument, *, include_body: bool = True) -> None:
    note = document.note
    typer.echo(f"{note.id}  {note.title}")
    typer.echo(f"Type: {note.note_type.value} | Revision: {note.revision}")
    typer.echo(f"Path: {document.path}")
    if note.tags:
        typer.echo("Tags: " + ", ".join(note.tags))
    if note.aliases:
        typer.echo("Aliases: " + ", ".join(note.aliases))
    if note.links:
        typer.echo("Links:")
        for link in note.links:
            label = f" ({link.label})" if link.label else ""
            typer.echo(f"  {link.relation.value}: {link.target_id}{label}")
    if note.sources:
        typer.echo("Sources:")
        for source in note.sources:
            title = f" ({source.title})" if source.title else ""
            typer.echo(f"  {source.kind.value}: {source.locator}{title}")
    if include_body and document.body:
        typer.echo()
        typer.echo(document.body.rstrip())


def _emit_document(ctx: typer.Context, document: KnowledgeDocument) -> None:
    if _state(ctx).json_output:
        _emit_json(document)
    else:
        _show_document(document)


def _body_value(
    body: str | None,
    body_file: Path | None,
) -> str | None:
    if body is not None and body_file is not None:
        raise typer.BadParameter(
            "--body and --body-file are mutually exclusive",
            param_hint="--body",
        )
    return body_file.read_text(encoding="utf-8") if body_file is not None else body


def _resolve_entity_id(service: KnowledgeService, query: str) -> str:
    """Resolve public workspace prefixes, falling back to knowledge aliases."""

    try:
        return str(service.workspace.find_record(query).entity.id)
    except EntityNotFoundError:
        return service.get(query).note.id


def _link_from_spec(service: KnowledgeService, spec: str) -> KnowledgeLink:
    """Parse TARGET or RELATION=TARGET, then persist the full stable target ID."""

    relation = KnowledgeLinkType.RELATED_TO
    target = spec
    if "=" in spec:
        raw_relation, target = spec.split("=", maxsplit=1)
        try:
            relation = KnowledgeLinkType(raw_relation.strip().lower())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in KnowledgeLinkType)
            raise typer.BadParameter(
                f"unknown link relation {raw_relation!r}; choose {allowed}",
                param_hint="--link",
            ) from exc
    if not target.strip():
        raise typer.BadParameter("link target cannot be blank", param_hint="--link")
    return KnowledgeLink(
        target_id=_resolve_entity_id(service, target.strip()),
        relation=relation,
    )


def _links_from_specs(
    service: KnowledgeService,
    specs: list[str] | None,
) -> list[KnowledgeLink] | None:
    return None if specs is None else [_link_from_spec(service, spec) for spec in specs]


def _source_from_spec(spec: str) -> SourceReference:
    """Parse KIND=LOCATOR; infer URL/FILE/OTHER when KIND is omitted."""

    raw = spec.strip()
    if not raw:
        raise typer.BadParameter("source cannot be blank", param_hint="--source")
    if "=" in raw:
        raw_kind, locator = raw.split("=", maxsplit=1)
        try:
            kind = SourceReferenceKind(raw_kind.strip().lower())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in SourceReferenceKind)
            raise typer.BadParameter(
                f"unknown source kind {raw_kind!r}; choose {allowed}",
                param_hint="--source",
            ) from exc
    else:
        locator = raw
        if raw.startswith(("https://", "http://")):
            kind = SourceReferenceKind.URL
        elif raw.startswith(("/", "./", "../")):
            kind = SourceReferenceKind.FILE
        else:
            kind = SourceReferenceKind.OTHER
    return SourceReference(kind=kind, locator=locator)


def _sources_from_specs(specs: list[str] | None) -> list[SourceReference] | None:
    return None if specs is None else [_source_from_spec(spec) for spec in specs]


def _replacement[T](
    values: list[T] | None,
    *,
    clear: bool,
    option: str,
) -> list[T] | None:
    if clear and values:
        raise typer.BadParameter(
            f"{option} and its clear option are mutually exclusive",
            param_hint=option,
        )
    return [] if clear else values


def _write_projection(output: Path, content: str, *, force: bool) -> None:
    if output.exists() and not force:
        raise typer.BadParameter(
            "output exists; pass --force to overwrite",
            param_hint="--output",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


@presentation_app.command("render")
def render_presentation(
    ctx: typer.Context,
    note_id: Annotated[str, typer.Argument(help="Note ID, unique prefix, or exact alias.")],
    mode: Annotated[
        KnowledgePresentationMode,
        typer.Option("--mode", case_sensitive=False, help="Presentation narrative mode."),
    ] = KnowledgePresentationMode.TECHNICAL_REPORT,
    theme: Annotated[str, typer.Option(help="Marp theme name.")] = "default",
    paginate: Annotated[
        bool,
        typer.Option("--paginate/--no-paginate", help="Show page numbers."),
    ] = True,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write a .marp.md projection."),
    ] = None,
    force: Annotated[bool, typer.Option(help="Replace an existing output file.")] = False,
) -> None:
    """Render a technical-report deck from an immutable Knowledge revision."""

    try:
        presentation = _service(ctx).render_presentation(
            note_id,
            mode=mode,
            theme=theme,
            paginate=paginate,
        )
    except ValidationError as exc:
        raise typer.BadParameter(
            "must start with an alphanumeric character and contain only letters, "
            "numbers, '.', '_', or '-' (maximum 64 characters)",
            param_hint="--theme",
        ) from exc
    if output is not None:
        _write_projection(output, presentation.markdown, force=force)
    if _state(ctx).json_output:
        _emit_json(presentation)
    elif output is not None:
        typer.echo(str(output))
    else:
        typer.echo(presentation.markdown, nl=False)


@app.command("add")
def add_note(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Knowledge note title.")],
    note_type: Annotated[
        KnowledgeNoteType,
        typer.Option("--type", case_sensitive=False, help="Knowledge note template/type."),
    ] = KnowledgeNoteType.NOTE,
    body: Annotated[str | None, typer.Option(help="Markdown body text.")] = None,
    body_file: Annotated[
        Path | None,
        typer.Option(
            "--body-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Read the Markdown body from a file.",
        ),
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
    alias: Annotated[list[str] | None, typer.Option("--alias", "-a")] = None,
    link: Annotated[
        list[str] | None,
        typer.Option("--link", help="TARGET or RELATION=TARGET; repeatable."),
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="KIND=LOCATOR, URL, or file; repeatable."),
    ] = None,
    note_id: Annotated[
        str | None,
        typer.Option("--id", help="Explicit stable ID for imports/automation."),
    ] = None,
) -> None:
    """Create one Markdown note without manually choosing its file path."""

    service = _service(ctx)
    document = service.create(
        title=title,
        note_type=note_type,
        body=_body_value(body, body_file),
        tags=tag or (),
        aliases=alias or (),
        links=_links_from_specs(service, link) or (),
        sources=_sources_from_specs(source) or (),
        note_id=note_id,
    )
    _emit_document(ctx, document)


@app.command("show")
def show_note(
    ctx: typer.Context,
    note_id: Annotated[str, typer.Argument(help="Note ID, unique prefix, or exact alias.")],
) -> None:
    """Show one note with its metadata, links, sources, and Markdown body."""

    _emit_document(ctx, _service(ctx).get(note_id))


@app.command("list")
def list_notes(
    ctx: typer.Context,
    note_type: Annotated[
        list[KnowledgeNoteType] | None,
        typer.Option("--type", case_sensitive=False, help="Include these note types."),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", "-t", help="Require every supplied tag."),
    ] = None,
) -> None:
    """List knowledge notes, optionally filtering by type and tags."""

    documents = _service(ctx).list(note_types=note_type, tags=tag)
    if _state(ctx).json_output:
        _emit_json(documents)
        return
    if not documents:
        typer.echo("No knowledge notes.")
        return
    for document in documents:
        tags = " " + " ".join(f"#{tag}" for tag in document.note.tags)
        typer.echo(
            f"{document.note.id}  [{document.note.note_type.value}] "
            f"{document.note.title}{tags if document.note.tags else ''}"
        )


@app.command("search")
def search_notes(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Case-insensitive search text.")],
    field: Annotated[
        list[KnowledgeSearchField] | None,
        typer.Option("--field", case_sensitive=False, help="Restrict matched fields."),
    ] = None,
) -> None:
    """Search titles, aliases, tags, and Markdown bodies."""

    hits = _service(ctx).search(query, fields=field)
    if _state(ctx).json_output:
        _emit_json(hits)
        return
    if not hits:
        typer.echo("No matching knowledge notes.")
        return
    for hit in hits:
        matched = ",".join(item.value for item in hit.matched_fields)
        typer.echo(f"{hit.note.id}  {hit.note.title}  [{matched}]")


@app.command("update")
def update_note(
    ctx: typer.Context,
    note_id: Annotated[str, typer.Argument(help="Note ID, unique prefix, or exact alias.")],
    title: Annotated[str | None, typer.Option(help="Replacement title.")] = None,
    note_type: Annotated[
        KnowledgeNoteType | None,
        typer.Option("--type", case_sensitive=False, help="Replacement note type."),
    ] = None,
    body: Annotated[str | None, typer.Option(help="Replacement Markdown body.")] = None,
    body_file: Annotated[
        Path | None,
        typer.Option(
            "--body-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Read the replacement Markdown body from a file.",
        ),
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
    alias: Annotated[list[str] | None, typer.Option("--alias", "-a")] = None,
    link: Annotated[
        list[str] | None,
        typer.Option("--link", help="Replace links with TARGET or RELATION=TARGET."),
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Replace sources with KIND=LOCATOR values."),
    ] = None,
    clear_tags: Annotated[bool, typer.Option("--clear-tags")] = False,
    clear_aliases: Annotated[bool, typer.Option("--clear-aliases")] = False,
    clear_links: Annotated[bool, typer.Option("--clear-links")] = False,
    clear_sources: Annotated[bool, typer.Option("--clear-sources")] = False,
) -> None:
    """Replace supplied note fields while retaining a revision history event."""

    service = _service(ctx)
    links = _links_from_specs(service, link)
    sources = _sources_from_specs(source)
    document = service.update(
        note_id,
        title=title,
        note_type=note_type,
        body=_body_value(body, body_file),
        tags=_replacement(tag, clear=clear_tags, option="--tag"),
        aliases=_replacement(alias, clear=clear_aliases, option="--alias"),
        links=_replacement(links, clear=clear_links, option="--link"),
        sources=_replacement(sources, clear=clear_sources, option="--source"),
    )
    _emit_document(ctx, document)


@app.command("link")
def link_note(
    ctx: typer.Context,
    source_id: Annotated[
        str,
        typer.Argument(help="Source note ID, unique prefix, or exact alias."),
    ],
    target_id: Annotated[
        str,
        typer.Argument(help="Target workspace entity ID or unique prefix."),
    ],
    relation: Annotated[
        KnowledgeLinkType,
        typer.Option("--type", case_sensitive=False, help="Meaning of this edge."),
    ] = KnowledgeLinkType.RELATED_TO,
    label: Annotated[str | None, typer.Option(help="Human explanation of the edge.")] = None,
) -> None:
    """Append one explicit relation to any stable workspace entity."""

    service = _service(ctx)
    document = service.get(source_id)
    link = KnowledgeLink(
        target_id=_resolve_entity_id(service, target_id),
        relation=relation,
        label=label,
    )
    _emit_document(
        ctx,
        service.update(source_id, links=[*document.note.links, link]),
    )


@app.command("backlinks")
def show_backlinks(
    ctx: typer.Context,
    target_id: Annotated[
        str,
        typer.Argument(help="Target entity ID, unique prefix, or knowledge alias."),
    ],
) -> None:
    """Show every knowledge note that explicitly points to an entity."""

    backlinks = _service(ctx).backlinks(target_id)
    if _state(ctx).json_output:
        _emit_json(backlinks)
        return
    if not backlinks:
        typer.echo("No backlinks.")
        return
    for backlink in backlinks:
        typer.echo(
            f"{backlink.source.note.id}  {backlink.source.note.title}  "
            f"[{backlink.link.relation.value}]"
        )


@app.command("promote")
def promote_record(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source entity ID or unique prefix.")],
    note_type: Annotated[
        KnowledgeNoteType,
        typer.Option("--type", case_sensitive=False, help="Created knowledge note type."),
    ] = KnowledgeNoteType.NOTE,
    title: Annotated[str | None, typer.Option(help="Override the source title.")] = None,
    body: Annotated[str | None, typer.Option(help="Override the source Markdown body.")] = None,
    body_file: Annotated[
        Path | None,
        typer.Option(
            "--body-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Read replacement Markdown from a file.",
        ),
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
    alias: Annotated[list[str] | None, typer.Option("--alias", "-a")] = None,
    link: Annotated[
        list[str] | None,
        typer.Option("--link", help="TARGET or RELATION=TARGET; repeatable."),
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Additional KIND=LOCATOR; repeatable."),
    ] = None,
    note_id: Annotated[str | None, typer.Option("--id")] = None,
) -> None:
    """Promote any public workspace record into independent knowledge."""

    service = _service(ctx)
    source_record = service.workspace.find_record(source_id)
    document = service.promote_record(
        source_record,
        note_type=note_type,
        title=title,
        body=_body_value(body, body_file),
        tags=tag or (),
        aliases=alias or (),
        links=_links_from_specs(service, link) or (),
        sources=_sources_from_specs(source) or (),
        note_id=note_id,
    )
    _emit_document(ctx, document)


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    """Validate the hand-editable knowledge graph and report orphan notes."""

    report = _service(ctx).doctor()
    if _state(ctx).json_output:
        _emit_json(report)
    else:
        typer.echo("Knowledge graph is valid." if report.valid else "Knowledge graph has errors.")
        for issue in report.issues:
            location = f" ({issue.path})" if issue.path else ""
            typer.echo(f"{issue.severity.upper()} {issue.code}: {issue.message}{location}")
        typer.echo("Counts: " + ", ".join(f"{key}={value}" for key, value in report.counts.items()))
    if not report.valid:
        raise typer.Exit(1)


__all__ = ["app"]
