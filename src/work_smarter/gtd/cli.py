"""Canonical domain/resource/operation CLI for GTD.

The historical root commands remain ergonomic aliases.  This module owns the
stable command tree used by scripts, Vim integrations, and documentation.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import date
from typing import Annotated, Any

import typer

from work_smarter.composition import open_workspace
from work_smarter.gtd.models import Energy, ProjectStatus, TaskStatus
from work_smarter.gtd.service import GtdService

app = typer.Typer(help="Capture, organize, engage, and review GTD work.", no_args_is_help=True)
inbox_app = typer.Typer(help="Process unclarified inputs.", no_args_is_help=True)
action_app = typer.Typer(help="Manage concrete next actions.", no_args_is_help=True)
project_app = typer.Typer(help="Manage multi-action GTD outcomes.", no_args_is_help=True)
review_app = typer.Typer(help="Run daily and weekly reviews.", no_args_is_help=True)
app.add_typer(inbox_app, name="inbox")
app.add_typer(action_app, name="action")
app.add_typer(project_app, name="project")
app.add_typer(review_app, name="review")


def _state(ctx: typer.Context) -> Any:
    state = ctx.find_root().obj
    if state is None:
        raise RuntimeError("GTD commands require the Work Smarter root CLI")
    return state


def _service(ctx: typer.Context) -> GtdService:
    return GtdService(open_workspace(_state(ctx).workspace))


def _emit(ctx: typer.Context, value: Any) -> None:
    if _state(ctx).json_output:
        if hasattr(value, "model_dump_json"):
            typer.echo(value.model_dump_json(indent=2))
            return
        if isinstance(value, list):
            value = [item.model_dump(mode="json") for item in value]
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, list):
        for item in value:
            typer.echo(f"{item.id}  {item.title}")
    elif hasattr(value, "id") and hasattr(value, "title"):
        typer.echo(f"{value.id}  {value.title}")
    else:
        typer.echo(str(value))


def _open_document(ctx: typer.Context, query: str) -> None:
    service = _service(ctx)
    reference = service.document_ref(query)
    path = service.workspace.root / reference.path
    editor = shlex.split(os.environ.get("EDITOR", "vi"))
    if not editor:
        raise typer.BadParameter("EDITOR cannot be empty")
    completed = subprocess.run([*editor, str(path)], check=False)
    if completed.returncode:
        raise typer.Exit(completed.returncode)


def _date(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must be YYYY-MM-DD", param_hint=option) from exc


@app.command("capture")
def capture(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="Thought to capture without classification.")],
    source: Annotated[str, typer.Option("--source")] = "cli",
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
) -> None:
    _emit(ctx, _service(ctx).capture(text, source=source, tags=tag))


@inbox_app.command("list")
def list_inbox(ctx: typer.Context) -> None:
    _emit(ctx, _service(ctx).list_inbox())


@inbox_app.command("show")
def show_inbox(ctx: typer.Context, query: str | None = None) -> None:
    _emit(ctx, _service(ctx).preview_inbox(query))


@action_app.command("create")
def create_action(
    ctx: typer.Context,
    title: str,
    project: Annotated[str | None, typer.Option("--project")] = None,
    context: Annotated[list[str] | None, typer.Option("--context", "-c")] = None,
    energy: Annotated[Energy | None, typer.Option("--energy")] = None,
    estimate: Annotated[int | None, typer.Option("--estimate", min=1)] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
) -> None:
    result = _service(ctx).add_next_action(
        title,
        project_id=project,
        contexts=context,
        energy=energy,
        estimate_minutes=estimate,
        due_on=_date(due, "--due"),
    )
    _emit(ctx, result.created[0])


@action_app.command("list")
def list_actions(
    ctx: typer.Context,
    status: Annotated[list[TaskStatus] | None, typer.Option("--status")] = None,
    output: Annotated[str, typer.Option("--output")] = "table",
) -> None:
    tasks = _service(ctx).list_tasks(set(status) if status else None)
    if output == "picker":
        if _state(ctx).json_output:
            raise typer.BadParameter("--output picker cannot be combined with --json")
        for task in tasks:
            contexts = " ".join(task.contexts)
            effort = task.remaining_estimate_minutes or task.estimate_minutes
            estimate = f"{effort:g}m" if effort is not None else ""
            row = f"{task.status.value:<8} {task.id}  {task.title:<40} {contexts:<20} {estimate}"
            typer.echo(row.rstrip())
        return
    if output != "table":
        raise typer.BadParameter("choose table or picker", param_hint="--output")
    _emit(ctx, tasks)


@action_app.command("show")
def show_action(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).get_task(query))


@action_app.command("open")
def open_action(ctx: typer.Context, query: str) -> None:
    _open_document(ctx, query)


@action_app.command("focus")
def focus_actions(
    ctx: typer.Context,
    context: Annotated[list[str] | None, typer.Option("--context", "-c")] = None,
    minutes: Annotated[int | None, typer.Option("--minutes", "-m", min=1)] = None,
    energy: Annotated[Energy | None, typer.Option("--energy")] = None,
) -> None:
    _emit(
        ctx,
        _service(ctx).focus(contexts=context, available_minutes=minutes, energy=energy),
    )


@action_app.command("start")
def start_action(ctx: typer.Context, query: str, switch: bool = False) -> None:
    _emit(ctx, _service(ctx).start_task(query, switch=switch))


@action_app.command("pause")
def pause_action(ctx: typer.Context, query: str | None = None) -> None:
    _emit(ctx, _service(ctx).stop_task(query))


@action_app.command("resume")
def resume_action(ctx: typer.Context, query: str, switch: bool = False) -> None:
    _emit(ctx, _service(ctx).start_task(query, switch=switch))


@action_app.command("complete")
def complete_action(ctx: typer.Context, query: str, waiver: str | None = None) -> None:
    _emit(ctx, _service(ctx).complete_task(query, waiver_reason=waiver))


@action_app.command("wait")
def wait_action(
    ctx: typer.Context,
    query: str,
    target: Annotated[str, typer.Option("--target")],
    request: Annotated[str, typer.Option("--request")],
    follow_up: Annotated[str | None, typer.Option("--follow-up")] = None,
) -> None:
    _emit(
        ctx,
        _service(ctx).delegate_task(
            query,
            target=target,
            request=request,
            follow_up_on=_date(follow_up, "--follow-up"),
        ),
    )


@action_app.command("schedule")
def schedule_action(ctx: typer.Context, query: str, scheduled_for: str) -> None:
    _emit(ctx, _service(ctx).schedule_task(query, scheduled_for=scheduled_for))


@action_app.command("defer")
def defer_action(ctx: typer.Context, query: str, not_before: str) -> None:
    _emit(ctx, _service(ctx).defer_task(query, not_before=not_before))


@project_app.command("create")
def create_project(
    ctx: typer.Context,
    title: str,
    outcome: Annotated[str, typer.Option("--outcome")],
    project_id: Annotated[str | None, typer.Option("--id")] = None,
    area: Annotated[str | None, typer.Option("--area")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
) -> None:
    _emit(
        ctx,
        _service(ctx).create_project(
            title=title,
            outcome=outcome,
            project_id=project_id,
            area=area,
            tags=tag,
        ),
    )


@project_app.command("list")
def list_projects(
    ctx: typer.Context,
    status: Annotated[list[ProjectStatus] | None, typer.Option("--status")] = None,
) -> None:
    _emit(ctx, _service(ctx).list_projects(set(status) if status else None))


@project_app.command("show")
def show_project(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).get_project(query))


@project_app.command("open")
def open_project(ctx: typer.Context, query: str) -> None:
    _open_document(ctx, query)


@project_app.command("complete")
def complete_project(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).complete_project(query))


@review_app.command("daily")
def daily_review(
    ctx: typer.Context,
    day: Annotated[str | None, typer.Option("--day")] = None,
) -> None:
    _emit(ctx, _service(ctx).daily_dashboard(today=_date(day, "--day")))


@review_app.command("weekly")
def weekly_review(ctx: typer.Context) -> None:
    _emit(ctx, _service(ctx).weekly_review())


__all__ = ["app"]
