"""Keyboard-first command-line interface for the GTD feature."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.errors import WorkSmarterError
from work_smarter.gtd.models import ClarifyDecision, Energy, ReviewReport
from work_smarter.gtd.service import GtdService

app = typer.Typer(
    name="ws",
    help="Text-first GTD without clerical file management.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@dataclass(slots=True)
class CliState:
    workspace: Path
    json_output: bool = False


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            envvar="WORK_SMARTER_WORKSPACE",
            help="Work Smarter workspace directory.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Select a workspace shared by every command."""

    ctx.obj = CliState(workspace=workspace or Path.cwd(), json_output=json_output)


def _state(ctx: typer.Context) -> CliState:
    return ctx.ensure_object(CliState)


def _service(ctx: typer.Context) -> GtdService:
    return GtdService(open_workspace(_state(ctx).workspace))


def _emit(ctx: typer.Context, value: Any) -> None:
    if _state(ctx).json_output:
        if hasattr(value, "model_dump_json"):
            typer.echo(value.model_dump_json(indent=2))
        else:
            typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if hasattr(value, "id") and hasattr(value, "title"):
        typer.echo(f"{value.id}  {value.title}")
    else:
        typer.echo(str(value))


@app.command("init")
def init_workspace(
    ctx: typer.Context,
    path: Annotated[Path | None, typer.Argument(help="Directory to initialize.")] = None,
) -> None:
    """Initialize a text-first workspace without overwriting documents."""

    target = path or _state(ctx).workspace
    workspace = initialize_workspace(target)
    if _state(ctx).json_output:
        _emit(ctx, {"workspace": str(workspace.root), "initialized": True})
    else:
        typer.echo(f"Initialized {workspace.root}")


@app.command()
def capture(
    ctx: typer.Context,
    text: Annotated[str | None, typer.Argument(help="Thought to capture. Quote spaces.")] = None,
    source: Annotated[str, typer.Option(help="Capture adapter/source name.")] = "cli",
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
) -> None:
    """Capture immediately; classification deliberately happens later."""

    if text is None:
        text = (
            typer.prompt("Capture")
            if sys.stdin.isatty() and not _state(ctx).json_output
            else sys.stdin.read()
        )
    item = _service(ctx).capture(text, source=source, tags=tag)
    _emit(ctx, item)


@app.command()
def add(
    ctx: typer.Context,
    text: Annotated[str | None, typer.Argument(help="Known physical next action.")] = None,
    context: Annotated[list[str] | None, typer.Option("--context", "-c")] = None,
    energy: Annotated[Energy | None, typer.Option(case_sensitive=False)] = None,
    estimate_minutes: Annotated[int | None, typer.Option("--estimate", min=1)] = None,
    project_id: Annotated[str | None, typer.Option("--project")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
    due_on: Annotated[str | None, typer.Option("--due")] = None,
    not_before: Annotated[str | None, typer.Option("--not-before")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
) -> None:
    """Create a known next action in one command, preserving inbox provenance."""

    if text is None:
        text = (
            typer.prompt("Next action")
            if sys.stdin.isatty() and not _state(ctx).json_output
            else sys.stdin.read()
        )
    result = _service(ctx).add_next_action(
        text,
        tags=tag,
        contexts=context,
        energy=energy,
        estimate_minutes=estimate_minutes,
        project_id=project_id,
        completion_criteria=criterion,
        due_on=due_on,
        not_before=not_before,
    )
    if _state(ctx).json_output:
        _emit(ctx, result)
        return
    action = result.created[0]
    typer.echo(f"Added {action.id}  {action.title}  ({action.path})")


@app.command("inbox")
def show_inbox(ctx: typer.Context) -> None:
    """Show unclarified items oldest first."""

    items = _service(ctx).list_inbox()
    if _state(ctx).json_output:
        _emit(ctx, [item.model_dump(mode="json") for item in items])
        return
    if not items:
        typer.echo("Inbox is empty.")
        return
    for item in items:
        typer.echo(f"{item.id}  {item.captured_at:%Y-%m-%d %H:%M}  {item.title}")


DECISION_SHORTCUTS = {
    "n": ClarifyDecision.NEXT,
    "p": ClarifyDecision.PROJECT,
    "w": ClarifyDecision.WAITING,
    "c": ClarifyDecision.SCHEDULED,
    "s": ClarifyDecision.SOMEDAY,
    "r": ClarifyDecision.REFERENCE,
    "t": ClarifyDecision.TRASH,
    "d": ClarifyDecision.DONE,
}


def _interactive_decision() -> ClarifyDecision:
    typer.echo(
        "n next | p project | w waiting | c calendar | s someday | "
        "r reference | t trash | d done now"
    )
    while True:
        raw = typer.prompt("Decision").strip().lower()
        if raw in DECISION_SHORTCUTS:
            return DECISION_SHORTCUTS[raw]
        try:
            return ClarifyDecision(raw)
        except ValueError:
            typer.echo("Choose one of: " + ", ".join(DECISION_SHORTCUTS))


def _required_clarify_value(
    value: str | None,
    *,
    option: str,
    prompt: str,
    interactive: bool,
) -> str:
    if value:
        return value
    if interactive:
        return typer.prompt(prompt)
    raise typer.BadParameter(f"{option} is required for this disposition", param_hint=option)


@app.command()
def clarify(
    ctx: typer.Context,
    item_id: Annotated[
        str | None,
        typer.Argument(help="Inbox ID or unique prefix; oldest when omitted."),
    ] = None,
    decision: Annotated[
        ClarifyDecision | None,
        typer.Option("--decision", "-d", case_sensitive=False),
    ] = None,
    title: Annotated[str | None, typer.Option()] = None,
    outcome: Annotated[str | None, typer.Option()] = None,
    first_action: Annotated[str | None, typer.Option("--first-action")] = None,
    waiting_for: Annotated[str | None, typer.Option("--waiting-for")] = None,
    scheduled_for: Annotated[str | None, typer.Option("--scheduled-for")] = None,
    context: Annotated[list[str] | None, typer.Option("--context", "-c")] = None,
    energy: Annotated[Energy | None, typer.Option(case_sensitive=False)] = None,
    estimate_minutes: Annotated[int | None, typer.Option("--estimate")] = None,
    project_id: Annotated[str | None, typer.Option("--project")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
    follow_up_on: Annotated[str | None, typer.Option("--follow-up")] = None,
    due_on: Annotated[str | None, typer.Option("--due")] = None,
    not_before: Annotated[str | None, typer.Option("--not-before")] = None,
) -> None:
    """Process one inbox item and let the system move/transform its file."""

    service = _service(ctx)
    source = service.preview_inbox(item_id)
    if not _state(ctx).json_output:
        typer.echo(f"\n{source.item.id}  {source.item.title}\n")
        typer.echo(source.body.rstrip())
        typer.echo()
    interactive = decision is None and sys.stdin.isatty() and not _state(ctx).json_output
    if decision is None and not interactive:
        raise typer.BadParameter(
            "--decision is required in JSON or non-interactive mode",
            param_hint="--decision",
        )
    choice = decision or _interactive_decision()
    fields: dict[str, Any] = {
        "title": title,
        "outcome": outcome,
        "first_action": first_action,
        "waiting_for": waiting_for,
        "scheduled_for": scheduled_for,
        "contexts": context,
        "energy": energy,
        "estimate_minutes": estimate_minutes,
        "project_id": project_id,
        "completion_criteria": criterion,
        "follow_up_on": follow_up_on,
        "due_on": due_on,
        "not_before": not_before,
    }
    if choice is ClarifyDecision.PROJECT:
        fields["outcome"] = _required_clarify_value(
            outcome,
            option="--outcome",
            prompt="Successful outcome",
            interactive=interactive,
        )
        fields["first_action"] = _required_clarify_value(
            first_action,
            option="--first-action",
            prompt="First physical next action",
            interactive=interactive,
        )
    elif choice is ClarifyDecision.WAITING:
        fields["waiting_for"] = _required_clarify_value(
            waiting_for,
            option="--waiting-for",
            prompt="Waiting for whom/what",
            interactive=interactive,
        )
    elif choice is ClarifyDecision.SCHEDULED:
        fields["scheduled_for"] = _required_clarify_value(
            scheduled_for,
            option="--scheduled-for",
            prompt="Scheduled date/time (ISO 8601)",
            interactive=interactive,
        )
    result = service.clarify(
        source.item.id,
        choice,
        **{key: value for key, value in fields.items() if value is not None},
    )
    if _state(ctx).json_output:
        _emit(ctx, result)
        return
    typer.echo(f"Clarified as {result.decision.value}.")
    for entity in result.created:
        typer.echo(f"  {entity.id}  {entity.title}  ({entity.path})")


@app.command()
def focus(
    ctx: typer.Context,
    context: Annotated[list[str] | None, typer.Option("--context", "-c")] = None,
    minutes: Annotated[int | None, typer.Option("--minutes", "-m", min=1)] = None,
    energy: Annotated[Energy | None, typer.Option(case_sensitive=False)] = None,
) -> None:
    """Show what can actually be done in the current context."""

    tasks = _service(ctx).focus(
        contexts=context,
        available_minutes=minutes,
        energy=energy,
    )
    if _state(ctx).json_output:
        _emit(ctx, [task.model_dump(mode="json") for task in tasks])
        return
    if not tasks:
        typer.echo("No eligible next action.")
        return
    for index, task in enumerate(tasks, start=1):
        estimate = f" {task.estimate_minutes}m" if task.estimate_minutes else ""
        contexts = f" [{' '.join(task.contexts)}]" if task.contexts else ""
        typer.echo(f"{index:>2}. {task.id}  {task.title}{estimate}{contexts}")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show the whole GTD system at a glance."""

    report = _service(ctx).status()
    if _state(ctx).json_output:
        _emit(ctx, report)
        return
    if report.current_task:
        typer.echo(f"Doing: {report.current_task.id}  {report.current_task.title}")
    else:
        typer.echo("Doing: none")
    typer.echo(f"Inbox: {report.inbox_count}")
    typer.echo(
        "Tasks: " + ", ".join(f"{name}={count}" for name, count in report.tasks_by_status.items())
    )
    typer.echo(
        "GTD projects: "
        + ", ".join(f"{name}={count}" for name, count in report.projects_by_status.items())
    )
    typer.echo(f"\nReady actions ({len(report.ready_actions)})")
    for action in report.ready_actions:
        typer.echo(f"  {action.id}  {action.title}")
    typer.echo(f"\nProjects needing a next action ({len(report.projects_needing_action)})")
    for project in report.projects_needing_action:
        typer.echo(f"  {project.id}  {project.title}")


@app.command()
def start(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    switch: Annotated[bool, typer.Option(help="Stop the current task first.")] = False,
) -> None:
    """Start one task, enforcing the default WIP limit of one."""

    _emit(ctx, _service(ctx).start_task(task_id, switch=switch))


@app.command()
def stop(
    ctx: typer.Context,
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID; current task when omitted."),
    ] = None,
) -> None:
    """Stop timing and return the task to Next Actions."""

    _emit(ctx, _service(ctx).stop_task(task_id))


@app.command("done")
def complete(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
) -> None:
    """Complete a task and surface a project that now lacks a next action."""

    result = _service(ctx).complete_task(task_id)
    if _state(ctx).json_output:
        _emit(ctx, result)
        return
    typer.echo(f"Completed {result.task.id}: {result.task.title}")
    if result.project_attention_required:
        typer.echo(
            f"Project {result.project_id} now needs a next action or completion decision.",
            err=True,
        )


@app.command()
def block(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option(prompt=True)],
) -> None:
    """Block a task with an explicit reason."""

    _emit(ctx, _service(ctx).block_task(task_id, reason))


@app.command()
def ready(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Waiting, blocked, or scheduled task ID.")],
) -> None:
    """Return an unavailable task to Next Actions."""

    _emit(ctx, _service(ctx).ready_task(task_id))


@app.command("project-done")
def project_done(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(help="GTD project ID or unique prefix.")],
) -> None:
    """Complete a GTD outcome after its open actions are finished."""

    _emit(ctx, _service(ctx).complete_project(project_id))


def _show_review(report: ReviewReport) -> None:
    if report.current_task:
        typer.echo(f"Doing: {report.current_task.id}  {report.current_task.title}")
    groups = (
        ("Inbox", report.inbox),
        ("Waiting", report.waiting_followups),
        ("Blocked", report.blocked),
        ("Stale next actions", report.stale_actions),
        ("Projects needing a next action", report.projects_without_next_action),
        ("Scheduled", report.scheduled),
    )
    for heading, items in groups:
        typer.echo(f"\n{heading} ({len(items)})")
        for item in items:
            age = f", {item.age_days}d" if item.age_days is not None else ""
            typer.echo(f"  {item.id}  {item.title} — {item.reason}{age}")
    typer.echo(f"\nSomeday/Maybe ({report.someday_count})")
    typer.echo(f"Attention items: {report.attention_count}")


@app.command()
def review(
    ctx: typer.Context,
    complete: Annotated[
        bool,
        typer.Option("--complete", help="Record this weekly review as completed."),
    ] = False,
) -> None:
    """Run the GTD weekly review checklist."""

    service = _service(ctx)
    report = service.record_review() if complete else service.weekly_review()
    if _state(ctx).json_output:
        _emit(ctx, report)
    else:
        _show_review(report)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Validate metadata, relations, event history, and GTD invariants."""

    report = _service(ctx).validate()
    if _state(ctx).json_output:
        _emit(ctx, report)
    else:
        typer.echo("Workspace is valid." if report.valid else "Workspace has errors.")
        for issue in report.issues:
            location = f" ({issue.path})" if issue.path else ""
            typer.echo(f"{issue.severity.upper()} {issue.code}: {issue.message}{location}")
        typer.echo("Counts: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    if not report.valid:
        raise typer.Exit(1)


@app.command()
def metrics(ctx: typer.Context) -> None:
    """Show reflection metrics derived from task and timer history."""

    report = _service(ctx).metrics()
    if _state(ctx).json_output:
        _emit(ctx, report)
        return
    typer.echo(f"Completed: {report.completed_total}")
    typer.echo(f"Completed in 7 days: {report.completed_last_7_days}")
    typer.echo(f"Focused minutes: {report.focus_minutes_total:.2f}")
    if report.average_lead_time_hours is not None:
        typer.echo(f"Average lead time: {report.average_lead_time_hours:.2f}h")
    if report.average_estimate_ratio is not None:
        typer.echo(f"Actual / estimate: {report.average_estimate_ratio:.2f}")


@app.command()
def serve(
    ctx: typer.Context,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    """Serve the local API used by the future VS Code extension."""

    import uvicorn

    from work_smarter.api import create_app

    uvicorn.run(create_app(_state(ctx).workspace), host=host, port=port)


def run() -> None:
    """Console-script entry point with concise, user-facing failures."""

    try:
        app()
    except WorkSmarterError as exc:
        if "--json" in sys.argv[1:]:
            typer.echo(
                json.dumps(
                    {"error": type(exc).__name__, "detail": str(exc)},
                    ensure_ascii=False,
                ),
                err=True,
            )
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(2) from exc
