"""Keyboard-first command-line interface for the GTD feature."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer

from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.confluence.cli import app as confluence_app
from work_smarter.errors import WorkSmarterError
from work_smarter.gtd.models import (
    ClarifyDecision,
    Commitment,
    Energy,
    Impact,
    RecurrenceFrequency,
    RelationType,
    ReviewReport,
    Task,
    TaskRigor,
    Urgency,
    WeeklyReviewSession,
    WeeklyReviewStep,
    WorkType,
)
from work_smarter.gtd.service import GtdService
from work_smarter.gtd.tui import run_tui
from work_smarter.knowledge.cli import app as knowledge_app
from work_smarter.project_management.cli import app as project_management_app

app = typer.Typer(
    name="ws",
    help="Text-first GTD without clerical file management.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
task_app = typer.Typer(
    help="Define, inspect, verify, and relate durable GTD work tickets.",
    no_args_is_help=True,
)
review_app = typer.Typer(
    help="Run and resume a durable GTD weekly review.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(task_app, name="task")
app.add_typer(review_app, name="review")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(project_management_app, name="pm")
app.add_typer(confluence_app, name="confluence")


@app.command("tui")
def tui(ctx: typer.Context) -> None:
    """Open the vim-like GTD terminal interface."""
    run_tui(_state(ctx).workspace)


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


def _iso_date(value: str | None, *, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must be an ISO date (YYYY-MM-DD)",
            param_hint=option,
        ) from exc


def _show_task_ticket(task: Task) -> None:
    """Render the fields needed to decide and execute personal work."""

    typer.echo(f"{task.id}  {task.title}")
    typer.echo(
        f"Type: {task.work_type.value} | Rigor: {task.rigor.value} | Status: {task.status.value}"
    )
    typer.echo(
        f"Urgency: {task.urgency.value} | Impact: {task.impact.value} | "
        f"Commitment: {task.commitment.value}"
    )
    original = task.original_estimate_minutes or "-"
    remaining = (
        task.remaining_estimate_minutes if task.remaining_estimate_minutes is not None else "-"
    )
    typer.echo(
        f"Estimate: original={original}m, remaining={remaining}m, actual={task.actual_minutes:g}m"
    )
    if task.parent_id:
        typer.echo(f"Parent: {task.parent_id}")
    if task.recurrence:
        typer.echo(
            f"Recurrence: every {task.recurrence.interval} "
            f"{task.recurrence.frequency.value}; next={task.next_occurrence_on}"
        )
    if task.schedule.due_on:
        typer.echo(f"Due: {task.schedule.due_on}")
    if task.schedule.not_before:
        typer.echo(f"Deferred until: {task.schedule.not_before.isoformat()}")
    if task.schedule.scheduled_for:
        typer.echo(f"Scheduled for: {task.schedule.scheduled_for.isoformat()}")
    for label, value in (
        ("Goal", task.goal),
        ("Why", task.why),
        ("Desired outcome", task.desired_outcome),
    ):
        if value:
            typer.echo(f"{label}: {value}")
    for heading, values in (
        ("Constraints", task.constraints),
        ("Assumptions", [item.statement for item in task.assumptions]),
        ("Risks", task.risks),
    ):
        if values:
            typer.echo(f"\n{heading}")
            for value in values:
                typer.echo(f"  - {value}")
    if task.completion.conditions:
        typer.echo("\nDefinition of Done")
        for condition in task.completion.conditions:
            checked = "x" if condition.met_at else " "
            evidence = f" — {condition.evidence}" if condition.evidence else ""
            typer.echo(f"  [{checked}] {condition.id}: {condition.text}{evidence}")
    if task.relations:
        typer.echo("\nRelations")
        for relation in task.relations:
            typer.echo(f"  - {relation.type.value}: {relation.target_id}")
    if task.waiting:
        typer.echo("\nWaiting for")
        typer.echo(f"  {task.waiting.target_kind}: {task.waiting.target}")
        if task.waiting.request:
            typer.echo(f"  Request: {task.waiting.request}")
        if task.waiting.expected_on:
            typer.echo(f"  Expected: {task.waiting.expected_on}")
        if task.waiting.follow_up_on:
            typer.echo(f"  Follow up: {task.waiting.follow_up_on}")
        if task.waiting.escalation_on:
            typer.echo(
                f"  Escalate: {task.waiting.escalation_on}"
                + (f" to {task.waiting.escalation_to}" if task.waiting.escalation_to else "")
            )
    if task.blockers:
        typer.echo("\nBlockers")
        for blocker in task.blockers:
            marker = "resolved" if blocker.resolved_at else "open"
            typer.echo(f"  - {blocker.id} [{marker}] {blocker.description}")


@task_app.command("show")
def task_show(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
) -> None:
    """Show one complete GTD work ticket."""

    task = _service(ctx).get_task(task_id)
    if _state(ctx).json_output:
        _emit(ctx, task)
    else:
        _show_task_ticket(task)


@task_app.command("define")
def task_define(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    work_type: Annotated[
        WorkType | None,
        typer.Option("--type", case_sensitive=False, help="Nature of this work."),
    ] = None,
    rigor: Annotated[
        TaskRigor | None,
        typer.Option(case_sensitive=False, help="Required completion rigor."),
    ] = None,
    urgency: Annotated[Urgency | None, typer.Option(case_sensitive=False)] = None,
    impact: Annotated[Impact | None, typer.Option(case_sensitive=False)] = None,
    commitment: Annotated[
        Commitment | None,
        typer.Option(case_sensitive=False),
    ] = None,
    goal: Annotated[str | None, typer.Option(help="State to make true.")] = None,
    why: Annotated[str | None, typer.Option(help="Reason this work matters.")] = None,
    outcome: Annotated[
        str | None,
        typer.Option("--outcome", help="Observable desired outcome."),
    ] = None,
    constraint: Annotated[list[str] | None, typer.Option("--constraint")] = None,
    assumption: Annotated[list[str] | None, typer.Option("--assumption")] = None,
    risk: Annotated[list[str] | None, typer.Option("--risk")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
    original_estimate: Annotated[
        int | None,
        typer.Option("--estimate", min=1, help="Original estimate in minutes."),
    ] = None,
    remaining_estimate: Annotated[
        int | None,
        typer.Option("--remaining", min=0, help="Current remaining estimate."),
    ] = None,
) -> None:
    """Define intent and completion gates without editing or moving Markdown."""

    task = _service(ctx).define_task(
        task_id,
        work_type=work_type,
        rigor=rigor,
        urgency=urgency,
        impact=impact,
        commitment=commitment,
        goal=goal,
        why=why,
        desired_outcome=outcome,
        constraints=constraint,
        assumptions=assumption,
        risks=risk,
        completion_criteria=criterion,
        original_estimate_minutes=original_estimate,
        remaining_estimate_minutes=remaining_estimate,
    )
    if _state(ctx).json_output:
        _emit(ctx, task)
    else:
        _show_task_ticket(task)


@task_app.command("check")
def task_check(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    condition_id: Annotated[str, typer.Argument(help="Completion condition ID.")],
    evidence: Annotated[
        str | None,
        typer.Option(help="Evidence path, URL, or concise observation."),
    ] = None,
) -> None:
    """Mark one completion condition as satisfied."""

    _emit(
        ctx,
        _service(ctx).check_completion_condition(
            task_id,
            condition_id,
            evidence=evidence,
        ),
    )


@task_app.command("assure")
def task_assure(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
) -> None:
    """Confirm an assured task's constraints and assumptions were reviewed."""

    _emit(ctx, _service(ctx).review_task_assurance(task_id))


@task_app.command("link")
def task_link(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source task ID or prefix.")],
    target_id: Annotated[str, typer.Argument(help="Target task ID or prefix.")],
    relation_type: Annotated[
        RelationType,
        typer.Option("--type", case_sensitive=False),
    ],
) -> None:
    """Add a directional task relation, rejecting dependency cycles."""

    _emit(
        ctx,
        _service(ctx).link_tasks(
            source_id,
            target_id,
            relation_type=relation_type,
        ),
    )


@task_app.command("parent")
def task_parent(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Child task ID or prefix.")],
    parent_id: Annotated[
        str | None,
        typer.Argument(help="Parent task ID; omit to clear."),
    ] = None,
) -> None:
    """Set or clear task decomposition without adding an execution dependency."""

    _emit(ctx, _service(ctx).set_task_parent(task_id, parent_id))


@task_app.command("log")
def task_log(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or prefix.")],
    minutes: Annotated[float, typer.Argument(min=0.01, help="Actual minutes worked.")],
    note: Annotated[str | None, typer.Option(help="What was accomplished.")] = None,
) -> None:
    """Append manual effort to a task's durable work history."""

    _emit(ctx, _service(ctx).log_work(task_id, minutes=minutes, note=note))


@task_app.command("correct-work")
def task_correct_work(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    work_log_id: Annotated[str, typer.Argument(help="Work log ID, such as WL-1.")],
    minutes: Annotated[
        float,
        typer.Argument(min=0, help="Corrected effective minutes."),
    ],
    reason: Annotated[
        str,
        typer.Option(help="Why the original work-log value is being corrected."),
    ],
) -> None:
    """Correct effective effort without rewriting the append-only original log."""

    _emit(
        ctx,
        _service(ctx).correct_work_log(
            task_id,
            work_log_id,
            corrected_minutes=minutes,
            reason=reason,
        ),
    )


@task_app.command("estimate")
def task_estimate(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or prefix.")],
    minutes: Annotated[int, typer.Argument(min=0, help="Remaining minutes.")],
    reason: Annotated[str, typer.Option(help="Why the forecast changed.")],
) -> None:
    """Revise remaining work while preserving the original estimate."""

    _emit(
        ctx,
        _service(ctx).set_remaining_estimate(task_id, minutes=minutes, reason=reason),
    )


@task_app.command("repeat")
def task_repeat(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or prefix.")],
    frequency: Annotated[
        RecurrenceFrequency,
        typer.Option(case_sensitive=False),
    ],
    interval: Annotated[int, typer.Option(min=1)] = 1,
    anchor_on: Annotated[str | None, typer.Option("--anchor")] = None,
    until_on: Annotated[str | None, typer.Option("--until")] = None,
) -> None:
    """Generate a fresh task ID after each recurring occurrence completes."""

    _emit(
        ctx,
        _service(ctx).set_recurrence(
            task_id,
            frequency=frequency,
            interval=interval,
            anchor_on=anchor_on,
            until_on=until_on,
        ),
    )


@task_app.command("delegate")
def task_delegate(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    target: Annotated[str, typer.Argument(help="Person, team, or system now responsible.")],
    request: Annotated[
        str | None,
        typer.Option(help="Concrete response or result requested."),
    ] = None,
    target_kind: Annotated[
        str,
        typer.Option("--target-kind", help="Kind of delegation target."),
    ] = "person",
    expected_on: Annotated[
        str | None,
        typer.Option("--expected", help="Expected response date (YYYY-MM-DD)."),
    ] = None,
    follow_up_on: Annotated[
        str | None,
        typer.Option("--follow-up", help="First follow-up date (YYYY-MM-DD)."),
    ] = None,
    escalation_on: Annotated[
        str | None,
        typer.Option("--escalation", help="Escalation date (YYYY-MM-DD)."),
    ] = None,
    escalation_to: Annotated[
        str | None,
        typer.Option("--escalate-to", help="Escalation target."),
    ] = None,
) -> None:
    """Delegate an action and create a durable Waiting For episode."""

    _emit(
        ctx,
        _service(ctx).delegate_task(
            task_id,
            target=target,
            request=request,
            target_kind=target_kind,
            expected_on=expected_on,
            follow_up_on=follow_up_on,
            escalation_on=escalation_on,
            escalation_to=escalation_to,
        ),
    )


@task_app.command("follow-up")
def task_follow_up(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Waiting task ID or unique prefix.")],
    note: Annotated[str, typer.Option(help="What was sent or attempted.")],
    next_follow_up_on: Annotated[
        str | None,
        typer.Option("--next", help="Next follow-up date (YYYY-MM-DD)."),
    ] = None,
) -> None:
    """Record a follow-up without resolving the Waiting For episode."""

    _emit(
        ctx,
        _service(ctx).follow_up_waiting(
            task_id,
            note=note,
            next_follow_up_on=next_follow_up_on,
        ),
    )


@task_app.command("respond")
def task_respond(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Waiting task ID or unique prefix.")],
    note: Annotated[str, typer.Option(help="Response received and its outcome.")],
    resolved: Annotated[
        bool,
        typer.Option(
            "--resolved/--still-waiting",
            help="Resolve the episode or keep waiting (the safe default).",
        ),
    ] = False,
    next_follow_up_on: Annotated[
        str | None,
        typer.Option("--next", help="Next follow-up date when still waiting."),
    ] = None,
) -> None:
    """Record a response, explicitly deciding whether Waiting For is resolved."""

    _emit(
        ctx,
        _service(ctx).record_waiting_response(
            task_id,
            note=note,
            resolved=resolved,
            next_follow_up_on=next_follow_up_on,
        ),
    )


@task_app.command("escalate")
def task_escalate(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Waiting task ID or unique prefix.")],
    note: Annotated[str, typer.Option(help="Why and how this was escalated.")],
    escalation_to: Annotated[
        str | None,
        typer.Option("--to", help="Override the configured escalation target."),
    ] = None,
    next_escalation_on: Annotated[
        str | None,
        typer.Option("--next", help="Next escalation date (YYYY-MM-DD)."),
    ] = None,
) -> None:
    """Escalate a Waiting For episode and retain its interaction history."""

    _emit(
        ctx,
        _service(ctx).escalate_waiting(
            task_id,
            note=note,
            escalation_to=escalation_to,
            next_escalation_on=next_escalation_on,
        ),
    )


@task_app.command("unblock")
def task_unblock(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    blocker_id: Annotated[str, typer.Argument(help="Blocker ID, such as BLK-1.")],
    note: Annotated[str, typer.Option(help="Evidence that this blocker was resolved.")],
) -> None:
    """Resolve one blocker while preserving other blocker and waiting facets."""

    _emit(
        ctx,
        _service(ctx).resolve_blocker(task_id, blocker_id, note=note),
    )


@task_app.command("schedule")
def task_schedule(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    scheduled_for: Annotated[
        str,
        typer.Argument(help="Hard calendar date/time in ISO 8601 form."),
    ],
) -> None:
    """Put work on the calendar for a specific date and time."""

    _emit(ctx, _service(ctx).schedule_task(task_id, scheduled_for=scheduled_for))


@task_app.command("defer")
def task_defer(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    not_before: Annotated[
        str,
        typer.Argument(help="Earliest eligible date/time in ISO 8601 form."),
    ],
) -> None:
    """Hide an action from focus until a date without making it a calendar event."""

    _emit(ctx, _service(ctx).defer_task(task_id, not_before=not_before))


@task_app.command("due")
def task_due(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID or unique prefix.")],
    due_on: Annotated[
        str | None,
        typer.Argument(help="Commitment deadline (YYYY-MM-DD)."),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Remove the current deadline."),
    ] = False,
) -> None:
    """Set or explicitly clear a deadline without scheduling the task."""

    if clear and due_on is not None:
        raise typer.BadParameter("DATE and --clear are mutually exclusive", param_hint="DATE")
    if due_on is None and not clear:
        raise typer.BadParameter("DATE is required unless --clear is used", param_hint="DATE")
    _emit(ctx, _service(ctx).set_task_due(task_id, due_on=None if clear else due_on))


@task_app.command("reopen")
def task_reopen(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Completed task ID or unique prefix.")],
    reason: Annotated[str, typer.Option(help="Why the completion decision changed.")],
) -> None:
    """Reopen completed work while retaining its completion snapshot."""

    _emit(ctx, _service(ctx).reopen_task(task_id, reason=reason))


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
        effort = (
            task.remaining_estimate_minutes
            if task.remaining_estimate_minutes is not None
            else task.estimate_minutes
        )
        estimate = f" {effort}m" if effort is not None else ""
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


@app.command("today")
def today_dashboard(
    ctx: typer.Context,
    day: Annotated[
        str | None,
        typer.Option("--day", help="Dashboard date (YYYY-MM-DD); defaults to today."),
    ] = None,
) -> None:
    """Show due, delegated, calendar, blocked, and available work in one view."""

    report = _service(ctx).daily_dashboard(today=_iso_date(day, option="--day"))
    if _state(ctx).json_output:
        _emit(ctx, report)
        return
    typer.echo(f"Today: {report.day}")
    if report.current_task:
        typer.echo(f"Doing: {report.current_task.id}  {report.current_task.title}")
    else:
        typer.echo("Doing: none")
    typer.echo(f"Inbox: {report.inbox_count}")
    groups = (
        ("Overdue", report.overdue),
        ("Due today", report.due_today),
        ("Follow-ups due", report.follow_ups_due),
        ("Escalations due", report.escalations_due),
        ("Scheduled today", report.scheduled_today),
        ("Blocked", report.blocked),
        ("Available actions", report.available_actions),
    )
    for heading, items in groups:
        typer.echo(f"\n{heading} ({len(items)})")
        for item in items:
            typer.echo(f"  {item.id}  {item.title}")


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
    waiver_reason: Annotated[
        str | None,
        typer.Option("--waiver", help="Explain an exceptional completion."),
    ] = None,
) -> None:
    """Complete a task and surface a project that now lacks a next action."""

    result = _service(ctx).complete_task(task_id, waiver_reason=waiver_reason)
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
    if report.session_id:
        typer.echo(f"Weekly review: {report.session_id} (in progress)")
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
    typer.echo("\nChecklist")
    for item in report.checklist:
        marker = "x" if item.complete else " "
        typer.echo(f"  [{marker}] {item.key} — {item.label} ({item.count})")
    typer.echo(f"Attention items: {report.attention_count}")


def _show_review_session(session: WeeklyReviewSession) -> None:
    state = "complete" if session.completed_at else "in progress"
    typer.echo(f"Weekly review {session.id} ({state})")
    typer.echo(f"Started: {session.started_at.isoformat()}")
    for step in session.steps:
        marker = "x" if step.checked_at else " "
        typer.echo(f"  [{marker}] {step.step.value}")


@review_app.callback(invoke_without_command=True)
def review(
    ctx: typer.Context,
    complete: Annotated[
        bool,
        typer.Option("--complete", help="Record this weekly review as completed."),
    ] = False,
) -> None:
    """Show the review queues; use subcommands for a resumable review."""

    if ctx.invoked_subcommand is not None:
        return

    service = _service(ctx)
    report = service.record_review() if complete else service.weekly_review()
    if _state(ctx).json_output:
        _emit(ctx, report)
    else:
        _show_review(report)


@review_app.command("start")
def review_start(ctx: typer.Context) -> None:
    """Start a weekly review, or return the unfinished session."""

    session = _service(ctx).start_weekly_review()
    if _state(ctx).json_output:
        _emit(ctx, session)
    else:
        _show_review_session(session)


@review_app.command("resume")
def review_resume(ctx: typer.Context) -> None:
    """Resume the active review, starting one when none exists."""

    service = _service(ctx)
    report = service.weekly_review()
    if report.session_id is None:
        session = service.start_weekly_review()
        report = service.weekly_review(review_id=session.id)
    if _state(ctx).json_output:
        _emit(ctx, report)
    else:
        _show_review(report)


@review_app.command("check")
def review_check(
    ctx: typer.Context,
    review_id: Annotated[str, typer.Argument(help="Review ID or unique prefix.")],
    step: Annotated[
        WeeklyReviewStep,
        typer.Argument(case_sensitive=False, help="Checklist step to confirm."),
    ],
    undo: Annotated[
        bool,
        typer.Option("--undo", help="Mark this step unchecked again."),
    ] = False,
) -> None:
    """Confirm one queue was consciously reviewed, regardless of its item count."""

    session = _service(ctx).check_weekly_review_step(
        review_id,
        step,
        checked=not undo,
    )
    if _state(ctx).json_output:
        _emit(ctx, session)
    else:
        _show_review_session(session)


@review_app.command("complete")
def review_complete(
    ctx: typer.Context,
    review_id: Annotated[str, typer.Argument(help="Review ID or unique prefix.")],
) -> None:
    """Complete a review only after every required step is checked."""

    session = _service(ctx).complete_weekly_review(review_id)
    if _state(ctx).json_output:
        _emit(ctx, session)
    else:
        _show_review_session(session)


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
