"""CLI adapter for Confluence Cloud publication."""
# Typer requires Option declarations in function signatures for CLI metadata.
# ruff: noqa: B008

from __future__ import annotations

import json
from typing import Any

import typer

from work_smarter.composition import open_workspace
from work_smarter.confluence.client import ConfluenceClient
from work_smarter.confluence.models import SyncDirection
from work_smarter.confluence.service import ConfluencePublishingService

app = typer.Typer(help="Publish Markdown to Confluence Cloud.", no_args_is_help=True)


def _service(ctx: typer.Context) -> ConfluencePublishingService:
    state = ctx.find_root().obj
    return ConfluencePublishingService(
        open_workspace(state.workspace), ConfluenceClient.from_environment()
    )


def _emit(ctx: typer.Context, value: Any) -> None:
    state = ctx.find_root().obj
    if state.json_output:
        if hasattr(value, "model_dump_json"):
            typer.echo(value.model_dump_json(indent=2))
        else:
            typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(str(value))


@app.command("configure")
def configure(
    ctx: typer.Context,
    query: str,
    space: str = typer.Option(..., "--space"),
    page: str | None = typer.Option(None, "--page"),
    parent: str | None = typer.Option(None, "--parent"),
    title: str | None = typer.Option(None, "--title"),
) -> None:
    _emit(
        ctx,
        _service(ctx).configure(
            query, space_key=space, page_id=page, parent_id=parent, title=title
        ),
    )


@app.command("plan")
def plan(
    ctx: typer.Context,
    query: str,
    direction: SyncDirection = typer.Option(SyncDirection.PUSH, "--direction"),
) -> None:
    _emit(ctx, _service(ctx).plan(query, direction=direction))


@app.command("push")
def push(
    ctx: typer.Context,
    query: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    _emit(ctx, _service(ctx).push(query, dry_run=dry_run, force=force))


@app.command("pull")
def pull(
    ctx: typer.Context,
    query: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    accept_loss: bool = typer.Option(False, "--accept-loss"),
) -> None:
    _emit(ctx, _service(ctx).pull(query, dry_run=dry_run, force=force, accept_loss=accept_loss))


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    _emit(ctx, _service(ctx).doctor())


__all__ = ["app"]
