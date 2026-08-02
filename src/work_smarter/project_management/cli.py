"""Keyboard and script adapter for managed project planning."""
# Typer requires Option declarations in function signatures for CLI metadata.
# ruff: noqa: B008

from __future__ import annotations

import json
import webbrowser
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import typer

from work_smarter.composition import open_workspace
from work_smarter.project_management.gantt import HtmlGanttRenderer
from work_smarter.project_management.models import (
    CompletionCriterionStatus,
    DependencyType,
    MilestoneStatus,
    ProjectLifecycle,
    QcdSnapshot,
    RegisterItemKind,
    RegisterItemStatus,
    WorkingCalendar,
    WorkStatus,
)
from work_smarter.project_management.projections import (
    render_html_project_report,
    render_markdown_project_report,
    render_mermaid_gantt,
    render_schedule_table,
)
from work_smarter.project_management.service import ProjectManagementService

app = typer.Typer(help="Plan managed projects without Excel.", no_args_is_help=True)
phase_app = typer.Typer(help="Manage project phases.", no_args_is_help=True)
work_app = typer.Typer(help="Manage WBS work packages.", no_args_is_help=True)
milestone_app = typer.Typer(help="Manage milestones.", no_args_is_help=True)
evidence_app = typer.Typer(help="Record durable evidence.", no_args_is_help=True)
criterion_app = typer.Typer(help="Resolve completion criteria.", no_args_is_help=True)
register_app = typer.Typer(
    help="Manage risks, opportunities, issues, and decisions.", no_args_is_help=True
)
qcd_app = typer.Typer(help="Manage QCD snapshots.", no_args_is_help=True)
gantt_app = typer.Typer(help="Export an interactive offline Gantt.", no_args_is_help=True)
dependency_app = typer.Typer(help="Manage typed schedule dependencies.", no_args_is_help=True)
baseline_app = typer.Typer(
    help="Capture and compare immutable schedule baselines.", no_args_is_help=True
)
app.add_typer(phase_app, name="phase")
app.add_typer(work_app, name="work")
app.add_typer(milestone_app, name="milestone")
app.add_typer(evidence_app, name="evidence")
app.add_typer(criterion_app, name="criterion")
app.add_typer(register_app, name="register")
app.add_typer(qcd_app, name="qcd")
app.add_typer(gantt_app, name="gantt")
app.add_typer(dependency_app, name="dependency")
app.add_typer(baseline_app, name="baseline")


def _root_state(ctx: typer.Context) -> Any:
    state = ctx.find_root().obj
    if state is None:
        raise RuntimeError("PM commands require the Work Smarter root CLI")
    return state


def _service(ctx: typer.Context) -> ProjectManagementService:
    return ProjectManagementService(open_workspace(_root_state(ctx).workspace))


def _emit(ctx: typer.Context, value: Any) -> None:
    if _root_state(ctx).json_output:
        if hasattr(value, "model_dump_json"):
            typer.echo(value.model_dump_json(indent=2))
        else:
            if isinstance(value, list):
                value = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in value
                ]
            typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    elif hasattr(value, "project"):
        typer.echo(f"{value.project.id}  {value.project.title}")
    else:
        typer.echo(str(value))


def _date(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must be an ISO date (YYYY-MM-DD)", param_hint=option) from exc


def _decimal(value: str | None, option: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise typer.BadParameter("must be a decimal", param_hint=option) from exc


def _write_output(ctx: typer.Context, output: Path | None, content: str, force: bool) -> None:
    if output is None:
        typer.echo(content, nl=not content.endswith("\n"))
        return
    if output.exists() and not force:
        raise typer.BadParameter("output exists; pass --force to overwrite", param_hint="--output")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    if not _root_state(ctx).json_output:
        typer.echo(str(output))


@app.command("create")
def create(
    ctx: typer.Context,
    title: str,
    goal: str = typer.Option(..., "--goal"),
    criterion: list[str] = typer.Option([], "--criterion"),
    constraint: list[str] = typer.Option([], "--constraint"),
    assumption: list[str] = typer.Option([], "--assumption"),
    start: str | None = typer.Option(None, "--start"),
    due: str | None = typer.Option(None, "--due"),
    project_id: str | None = typer.Option(None, "--id"),
    working_weekday: list[int] | None = typer.Option(None, "--working-weekday", min=0, max=6),
    holiday: list[str] = typer.Option([], "--holiday"),
    working_day: list[str] = typer.Option([], "--working-day"),
) -> None:
    calendar = (
        WorkingCalendar(
            working_weekdays=working_weekday or list(range(7)),
            non_working_days=[_date(value, "--holiday") for value in holiday],
            additional_working_days=[_date(value, "--working-day") for value in working_day],
        )
        if working_weekday is not None or holiday or working_day
        else None
    )
    _emit(
        ctx,
        _service(ctx).create(
            title=title,
            goal=goal,
            completion_criteria=criterion,
            constraints=constraint,
            assumptions=assumption,
            planned_start_on=_date(start, "--start"),
            target_due_on=_date(due, "--due"),
            working_calendar=calendar,
            project_id=project_id,
        ),
    )


@app.command("list")
def list_projects(
    ctx: typer.Context, state: list[ProjectLifecycle] | None = typer.Option(None, "--state")
) -> None:
    _emit(ctx, _service(ctx).list(lifecycles=state))


@app.command("show")
def show(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).get(query))


@app.command("update")
def update(
    ctx: typer.Context,
    query: str,
    title: str | None = typer.Option(None, "--title"),
    goal: str | None = typer.Option(None, "--goal"),
    manager: str | None = typer.Option(None, "--manager"),
) -> None:
    _emit(ctx, _service(ctx).update(query, title=title, goal=goal, manager=manager))


@app.command("state")
def state(ctx: typer.Context, query: str, lifecycle: ProjectLifecycle) -> None:
    _emit(ctx, _service(ctx).transition_project(query, lifecycle))


@phase_app.command("add")
def add_phase(
    ctx: typer.Context,
    query: str,
    title: str,
    phase_id: str | None = typer.Option(None, "--id"),
    description: str | None = typer.Option(None, "--description"),
    owner: str | None = typer.Option(None, "--owner"),
    start: str | None = typer.Option(None, "--start"),
    due: str | None = typer.Option(None, "--due"),
    criterion: list[str] = typer.Option([], "--criterion"),
) -> None:
    _emit(
        ctx,
        _service(ctx).add_phase(
            query,
            title=title,
            phase_id=phase_id,
            description=description,
            owner=owner,
            start_on=_date(start, "--start"),
            due_on=_date(due, "--due"),
            completion_criteria=criterion,
        ),
    )


@phase_app.command("state")
def phase_state(ctx: typer.Context, query: str, phase_id: str, state: WorkStatus) -> None:
    _emit(ctx, _service(ctx).transition_phase(query, phase_id, state))


@work_app.command("add")
def add_work(
    ctx: typer.Context,
    query: str,
    title: str,
    days: int = typer.Option(..., "--days", min=1),
    phase: str | None = typer.Option(None, "--phase"),
    depends: list[str] = typer.Option([], "--depends"),
    criterion: list[str] = typer.Option([], "--criterion"),
    gtd_action: list[str] = typer.Option([], "--gtd-action"),
    work_package_id: str | None = typer.Option(None, "--id"),
    start: str | None = typer.Option(None, "--start"),
    due: str | None = typer.Option(None, "--due"),
) -> None:
    _emit(
        ctx,
        _service(ctx).add_work_package(
            query,
            title=title,
            duration_days=days,
            phase_id=phase,
            dependency_ids=depends,
            completion_criteria=criterion,
            gtd_action_ids=gtd_action,
            work_package_id=work_package_id,
            start_on=_date(start, "--start"),
            due_on=_date(due, "--due"),
        ),
    )


@work_app.command("update")
def update_work(
    ctx: typer.Context,
    query: str,
    work_package_id: str,
    depends: list[str] | None = typer.Option(None, "--depends"),
    days: int | None = typer.Option(None, "--days", min=1),
    progress: int | None = typer.Option(None, "--progress", min=0, max=100),
    owner: str | None = typer.Option(None, "--owner"),
) -> None:
    _emit(
        ctx,
        _service(ctx).update_work_package(
            query,
            work_package_id,
            dependency_ids=depends,
            duration_days=days,
            progress_percent=progress,
            owner=owner,
        ),
    )


@dependency_app.command("add")
def add_dependency(
    ctx: typer.Context,
    query: str,
    successor_id: str,
    predecessor_id: str,
    dependency_type: DependencyType = typer.Option(DependencyType.FINISH_TO_START, "--type"),
    lag: int = typer.Option(0, "--lag"),
) -> None:
    _emit(
        ctx,
        _service(ctx).add_dependency(
            query,
            successor_id,
            predecessor_id,
            dependency_type=dependency_type,
            lag_days=lag,
        ),
    )


@dependency_app.command("remove")
def remove_dependency(
    ctx: typer.Context,
    query: str,
    successor_id: str,
    predecessor_id: str,
) -> None:
    _emit(ctx, _service(ctx).remove_dependency(query, successor_id, predecessor_id))


@dependency_app.command("explain")
def explain_dependency(ctx: typer.Context, query: str, item_id: str) -> None:
    _emit(ctx, _service(ctx).explain_schedule(query, item_id))


@work_app.command("state")
def work_state(ctx: typer.Context, query: str, work_package_id: str, state: WorkStatus) -> None:
    _emit(ctx, _service(ctx).transition_work_package(query, work_package_id, state))


@milestone_app.command("add")
def add_milestone(
    ctx: typer.Context,
    query: str,
    title: str,
    milestone_id: str | None = typer.Option(None, "--id"),
    phase: str | None = typer.Option(None, "--phase"),
    depends: list[str] = typer.Option([], "--depends"),
    planned: str | None = typer.Option(None, "--planned"),
    due: str | None = typer.Option(None, "--due"),
    criterion: list[str] = typer.Option([], "--criterion"),
) -> None:
    _emit(
        ctx,
        _service(ctx).add_milestone(
            query,
            title=title,
            milestone_id=milestone_id,
            phase_id=phase,
            dependency_ids=depends,
            planned_on=_date(planned, "--planned"),
            due_on=_date(due, "--due"),
            completion_criteria=criterion,
        ),
    )


@milestone_app.command("state")
def milestone_state(
    ctx: typer.Context, query: str, milestone_id: str, state: MilestoneStatus
) -> None:
    _emit(ctx, _service(ctx).transition_milestone(query, milestone_id, state))


@evidence_app.command("add")
def add_evidence(
    ctx: typer.Context,
    query: str,
    statement: str,
    source: str = typer.Option(..., "--source"),
    evidence_id: str | None = typer.Option(None, "--id"),
) -> None:
    _emit(
        ctx,
        _service(ctx).record_evidence(
            query, statement=statement, source=source, evidence_id=evidence_id
        ),
    )


@criterion_app.command("resolve")
def resolve_criterion(
    ctx: typer.Context,
    query: str,
    criterion_id: str,
    evidence: list[str] = typer.Option([], "--evidence"),
) -> None:
    _emit(
        ctx,
        _service(ctx).update_completion_criterion(
            query, criterion_id, status=CompletionCriterionStatus.MET, evidence_ids=evidence
        ),
    )


@criterion_app.command("waive")
def waive_criterion(
    ctx: typer.Context, query: str, criterion_id: str, reason: str = typer.Option(..., "--reason")
) -> None:
    _emit(
        ctx,
        _service(ctx).update_completion_criterion(
            query, criterion_id, status=CompletionCriterionStatus.WAIVED, waiver_reason=reason
        ),
    )


@register_app.command("add")
def add_register(
    ctx: typer.Context,
    query: str,
    kind: RegisterItemKind,
    title: str,
    probability: str | None = typer.Option(None, "--probability"),
    impact_cost: str | None = typer.Option(None, "--impact-cost"),
    impact_days: int = typer.Option(0, "--impact-days"),
    register_item_id: str | None = typer.Option(None, "--id"),
) -> None:
    _emit(
        ctx,
        _service(ctx).add_register_item(
            query,
            kind=kind,
            title=title,
            probability=_decimal(probability, "--probability"),
            impact_cost=_decimal(impact_cost, "--impact-cost") or Decimal("0"),
            impact_days=impact_days,
            register_item_id=register_item_id,
        ),
    )


@register_app.command("update")
def update_register(
    ctx: typer.Context,
    query: str,
    register_item_id: str,
    state: RegisterItemStatus | None = typer.Option(None, "--state"),
    response: str | None = typer.Option(None, "--response"),
) -> None:
    _emit(
        ctx,
        _service(ctx).update_register_item(
            query, register_item_id, status=state, response=response
        ),
    )


@qcd_app.command("update")
def update_qcd(
    ctx: typer.Context,
    query: str,
    snapshot: str,
    cost: str | None = typer.Option(None, "--cost"),
    effort: str | None = typer.Option(None, "--effort"),
    quality: str | None = typer.Option(None, "--quality"),
    scope: str | None = typer.Option(None, "--scope"),
    delivery: str | None = typer.Option(None, "--delivery"),
) -> None:
    service = _service(ctx)
    current = service.get(query).project.qcd
    base = getattr(current, snapshot)
    updated = QcdSnapshot(
        cost=_decimal(cost, "--cost") if cost is not None else base.cost,
        effort_hours=_decimal(effort, "--effort") if effort is not None else base.effort_hours,
        quality_percent=_decimal(quality, "--quality")
        if quality is not None
        else base.quality_percent,
        scope_units=_decimal(scope, "--scope") if scope is not None else base.scope_units,
        delivery_on=_date(delivery, "--delivery") if delivery is not None else base.delivery_on,
    )
    _emit(ctx, service.update(query, qcd=current.model_copy(update={snapshot: updated})))


@qcd_app.command("show")
def show_qcd(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).qcd_projection(query))


@baseline_app.command("create")
def create_baseline(
    ctx: typer.Context,
    query: str,
    label: str = typer.Option(..., "--label"),
) -> None:
    _emit(ctx, _service(ctx).create_baseline(query, label=label))


@baseline_app.command("list")
def list_baselines(ctx: typer.Context, query: str) -> None:
    _emit(ctx, _service(ctx).get(query).project.baselines)


@app.command("schedule")
def schedule(
    ctx: typer.Context,
    query: str,
    format: str = typer.Option("table", "--format"),
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    service = _service(ctx)
    document = service.get(query)
    projection = service.compute_schedule(query)
    qcd = service.qcd_projection(query)
    renderers = {
        "table": lambda: render_schedule_table(document.project, projection),
        "mermaid": lambda: render_mermaid_gantt(document.project, projection),
        "html": lambda: render_html_project_report(document.project, projection, qcd),
        "markdown": lambda: render_markdown_project_report(document.project, projection, qcd),
    }
    if format not in renderers:
        raise typer.BadParameter("choose table, mermaid, html, or markdown", param_hint="--format")
    content = renderers[format]()
    if output is not None:
        _write_output(ctx, output, content, force)
    elif _root_state(ctx).json_output:
        _emit(ctx, {"project_id": document.project.id, "format": format, "content": content})
    else:
        typer.echo(content, nl=not content.endswith("\n"))


@app.command("schedule-explain")
def schedule_explain(ctx: typer.Context, query: str, item_id: str) -> None:
    _emit(ctx, _service(ctx).explain_schedule(query, item_id))


@gantt_app.command("export")
def export_gantt(
    ctx: typer.Context,
    query: str,
    output: Path = typer.Option(..., "--output"),
    today: str | None = typer.Option(None, "--today"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    service = _service(ctx)
    document = service.get(query)
    renderer = HtmlGanttRenderer()
    content = renderer.render(
        document.project,
        service.compute_schedule(query),
        today=_date(today, "--today"),
    )
    _write_output(ctx, output, content, force)
    if _root_state(ctx).json_output:
        _emit(
            ctx,
            {
                "project_id": document.project.id,
                "format": renderer.format,
                "output": str(output),
            },
        )


@gantt_app.command("open")
def open_gantt(
    ctx: typer.Context,
    query: str,
    output: Path | None = typer.Option(None, "--output"),
    today: str | None = typer.Option(None, "--today"),
) -> None:
    service = _service(ctx)
    document = service.get(query)
    destination = output or (
        service.workspace.state_dir / "projections" / f"{document.project.id}-gantt.html"
    )
    renderer = HtmlGanttRenderer()
    content = renderer.render(
        document.project,
        service.compute_schedule(query),
        today=_date(today, "--today"),
    )
    _write_output(ctx, destination, content, force=True)
    if _root_state(ctx).json_output:
        _emit(ctx, {"project_id": document.project.id, "output": str(destination)})
        return
    webbrowser.open(destination.resolve().as_uri())


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    report = _service(ctx).doctor()
    _emit(ctx, report)
    if not report.valid:
        raise typer.Exit(1)


__all__ = ["app"]
