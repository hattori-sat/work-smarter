"""Deterministic, side-effect-free projections for managed projects.

The project Markdown document remains authoritative.  These renderers turn the
validated aggregate and computed projections into disposable views for a
terminal, Mermaid, a browser, or a future publishing adapter.  They do not read
or write files and deliberately contain no provider-specific state.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

from work_smarter.project_management.models import (
    ManagedProject,
    QcdProjection,
    ScheduleItem,
    ScheduleProjection,
)


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate)


def _date_text(value: date | None) -> str:
    return "-" if value is None else value.isoformat()


def _datetime_text(value: datetime | None) -> str:
    return "-" if value is None else value.isoformat()


def _number_text(value: Decimal | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _plain(value: object | None) -> str:
    """Collapse control characters and whitespace for single-line views."""

    if value is None:
        return "-"
    raw = str(value)
    printable = "".join(
        " " if unicodedata.category(character).startswith("C") else character for character in raw
    )
    return " ".join(printable.split()) or "-"


def _terminal_cell(value: object | None) -> str:
    return _plain(value).replace("|", "¦")


def _display_width(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1 for character in value
    )


def _display_pad(value: str, width: int) -> str:
    return value + " " * max(0, width - _display_width(value))


def _markdown_cell(value: object | None) -> str:
    value_text = _plain(value)
    escaped = html.escape(value_text, quote=True).replace("\\", "\\\\")
    for character in ("|", "`", "*", "_", "[", "]", "#", "!"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _markdown_inline(value: object | None) -> str:
    return _markdown_cell(value)


def _mermaid_text(value: object | None) -> str:
    """Return a Unicode label that cannot open another Mermaid statement."""

    value_text = _plain(value)
    # Mermaid Gantt uses colons and commas as grammar and %% as comments.
    # Keeping letters, numbers and a conservative punctuation set preserves
    # useful Japanese labels while making multi-line/directive injection inert.
    without_markup = re.sub(r"<[^>]*(?:>|$)", " ", value_text)
    sanitized = re.sub(r"[^\w .()/+\-]", " ", without_markup, flags=re.UNICODE)
    return " ".join(sanitized.split()) or "Untitled"


def _mermaid_id(entity_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]", "_", entity_id).strip("_").lower()
    if not slug:
        slug = "item"
    digest = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:8]
    return f"ws_{slug}_{digest}"


def _source_items(project: ManagedProject) -> dict[str, object]:
    return {item.id: item for item in (*project.work_packages, *project.milestones)}


def _ordered_schedule_items(schedule: ScheduleProjection) -> list[ScheduleItem]:
    by_id = {item.id: item for item in schedule.items}
    order = {entity_id: index for index, entity_id in enumerate(schedule.topological_order)}
    return sorted(
        by_id.values(),
        key=lambda item: (order.get(item.id, len(order)), item.id.casefold(), item.id),
    )


def _phase_name(project: ManagedProject, phase_id: str | None) -> str:
    if phase_id is None:
        return "Unassigned"
    for phase in project.phases:
        if phase.id == phase_id:
            return phase.title
    return f"Unknown phase ({phase_id})"


def _schedule_rows(
    project: ManagedProject,
    schedule: ScheduleProjection,
) -> list[list[str]]:
    source_by_id = _source_items(project)
    rows: list[list[str]] = []
    for item in _ordered_schedule_items(schedule):
        source = source_by_id.get(item.id)
        phase_id = getattr(source, "phase_id", None)
        planned_start = (
            getattr(source, "planned_on", None)
            if item.kind == "milestone"
            else getattr(source, "start_on", None)
        )
        planned_due = getattr(source, "due_on", None)
        status = _enum_value(getattr(source, "status", "unknown"))
        rows.append(
            [
                item.id,
                item.kind.replace("_", " "),
                _phase_name(project, phase_id),
                item.title,
                status,
                _date_text(planned_start),
                _date_text(planned_due),
                item.scheduled_start_on.isoformat(),
                item.scheduled_finish_on.isoformat(),
                str(item.duration_days),
                str(item.total_float_days),
                "*" if item.critical else "",
            ]
        )
    return rows


def _text_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    safe_rows = [[_terminal_cell(cell) for cell in row] for row in rows]
    widths = [_display_width(header) for header in headers]
    for row in safe_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _display_width(cell))

    def line(cells: Sequence[str]) -> str:
        return " | ".join(
            _display_pad(cell, widths[index]) for index, cell in enumerate(cells)
        ).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    lines = [line(headers), separator]
    lines.extend(line(row) for row in safe_rows)
    if not rows:
        lines.append("(no scheduled items)")
    return "\n".join(lines)


SCHEDULE_HEADERS = (
    "ID",
    "Type",
    "Phase",
    "Title",
    "Status",
    "Planned start",
    "Planned due",
    "Forecast start",
    "Forecast finish",
    "Days",
    "Float",
    "Critical",
)


def render_schedule_table(project: ManagedProject, schedule: ScheduleProjection) -> str:
    """Render a readable WBS/schedule table without terminal control codes."""

    return _text_table(SCHEDULE_HEADERS, _schedule_rows(project, schedule))


def _mermaid_markers(item: ScheduleItem, status: str) -> list[str]:
    markers: list[str] = []
    if item.critical:
        markers.append("crit")
    if status in {"completed", "achieved"}:
        markers.append("done")
    elif status == "in_progress":
        markers.append("active")
    if item.kind == "milestone":
        markers.append("milestone")
    return markers


def render_mermaid_gantt(project: ManagedProject, schedule: ScheduleProjection) -> str:
    """Render a Mermaid Gantt diagram with stable, sanitized task IDs."""

    source_by_id = _source_items(project)
    ordered = _ordered_schedule_items(schedule)
    phase_order: list[str | None] = [phase.id for phase in project.phases]
    phase_ids = {getattr(source_by_id.get(item.id), "phase_id", None) for item in ordered}
    phase_order.extend(
        sorted(
            (phase_id for phase_id in phase_ids if phase_id not in phase_order),
            key=lambda value: "" if value is None else value.casefold(),
        )
    )

    lines = [
        "gantt",
        f"    title {_mermaid_text(project.title)}",
        "    dateFormat YYYY-MM-DD",
        "    axisFormat %Y-%m-%d",
    ]
    for phase_id in phase_order:
        phase_items = [
            item
            for item in ordered
            if getattr(source_by_id.get(item.id), "phase_id", None) == phase_id
        ]
        if not phase_items:
            continue
        lines.append(f"    section {_mermaid_text(_phase_name(project, phase_id))}")
        for item in phase_items:
            source = source_by_id.get(item.id)
            status = _enum_value(getattr(source, "status", "unknown"))
            markers = _mermaid_markers(item, status)
            grammar = [*markers, _mermaid_id(item.id), item.scheduled_start_on.isoformat()]
            grammar.append(f"{item.duration_days}d")
            lines.append(f"    {_mermaid_text(item.title)} :{', '.join(grammar)}")
    if not ordered:
        lines.append("    %% No scheduled items")
    return "\n".join(lines) + "\n"


def _html_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    empty_message: str,
) -> str:
    rendered_rows = list(rows)
    head = "".join(f'<th scope="col">{html.escape(header)}</th>' for header in headers)
    if rendered_rows:
        body = "".join(
            "<tr>"
            + "".join(f"<td>{html.escape(_plain(cell), quote=True)}</td>" for cell in row)
            + "</tr>"
            for row in rendered_rows
        )
    else:
        body = (
            f'<tr><td colspan="{len(headers)}" class="empty">'
            f"{html.escape(empty_message, quote=True)}</td></tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _snapshot_row(
    metric: str,
    baseline: object,
    current: object,
    forecast: object,
    current_variance: object,
    forecast_variance: object,
    health: object,
) -> list[object]:
    return [
        metric,
        baseline,
        current,
        forecast,
        current_variance,
        forecast_variance,
        _enum_value(health),
    ]


def _days_between(current: date | None, baseline: date | None) -> int | None:
    if current is None or baseline is None:
        return None
    return (current - baseline).days


def _decimal_difference(current: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    if current is None or baseline is None:
        return None
    return current - baseline


def _qcd_rows(project: ManagedProject, qcd: QcdProjection | None) -> list[list[object]]:
    baseline = project.qcd.baseline
    current = project.qcd.current
    forecast = project.qcd.forecast
    unknown = "unknown"
    return [
        _snapshot_row(
            "Cost",
            _number_text(baseline.cost),
            _number_text(current.cost),
            _number_text(forecast.cost),
            _number_text(qcd.current_cost_variance if qcd else current.cost - baseline.cost),
            _number_text(qcd.forecast_cost_variance if qcd else forecast.cost - baseline.cost),
            qcd.cost_health if qcd else unknown,
        ),
        _snapshot_row(
            "Effort hours",
            _number_text(baseline.effort_hours),
            _number_text(current.effort_hours),
            _number_text(forecast.effort_hours),
            _number_text(
                qcd.current_effort_variance if qcd else current.effort_hours - baseline.effort_hours
            ),
            _number_text(
                qcd.forecast_effort_variance
                if qcd
                else forecast.effort_hours - baseline.effort_hours
            ),
            qcd.cost_health if qcd else unknown,
        ),
        _snapshot_row(
            "Quality %",
            _number_text(baseline.quality_percent),
            _number_text(current.quality_percent),
            _number_text(forecast.quality_percent),
            _number_text(_decimal_difference(current.quality_percent, baseline.quality_percent)),
            _number_text(
                qcd.forecast_quality_variance
                if qcd
                else _decimal_difference(forecast.quality_percent, baseline.quality_percent)
            ),
            qcd.quality_health if qcd else unknown,
        ),
        _snapshot_row(
            "Scope units",
            _number_text(baseline.scope_units),
            _number_text(current.scope_units),
            _number_text(forecast.scope_units),
            _number_text(current.scope_units - baseline.scope_units),
            _number_text(
                qcd.forecast_scope_variance if qcd else forecast.scope_units - baseline.scope_units
            ),
            qcd.scope_health if qcd else unknown,
        ),
        _snapshot_row(
            "Delivery",
            _date_text(baseline.delivery_on),
            _date_text(current.delivery_on),
            _date_text(forecast.delivery_on),
            _number_text(_days_between(current.delivery_on, baseline.delivery_on)),
            _number_text(
                qcd.forecast_delivery_variance_days
                if qcd
                else _days_between(forecast.delivery_on, baseline.delivery_on)
            ),
            qcd.delivery_health if qcd else unknown,
        ),
    ]


QCD_HEADERS = (
    "Metric",
    "Baseline",
    "Current",
    "Forecast",
    "Current variance",
    "Forecast variance",
    "Health",
)


def _milestone_rows(project: ManagedProject, schedule: ScheduleProjection) -> list[list[object]]:
    projection_by_id = {item.id: item for item in schedule.items}
    result: list[list[object]] = []
    for milestone in sorted(project.milestones, key=lambda item: (item.id.casefold(), item.id)):
        item = projection_by_id.get(milestone.id)
        result.append(
            [
                milestone.id,
                milestone.title,
                _phase_name(project, milestone.phase_id),
                _enum_value(milestone.status),
                _date_text(milestone.planned_on),
                _date_text(item.scheduled_finish_on if item else None),
                _date_text(milestone.due_on),
                _date_text(milestone.achieved_on),
            ]
        )
    return result


MILESTONE_HEADERS = (
    "ID",
    "Milestone",
    "Phase",
    "Status",
    "Planned",
    "Forecast",
    "Due",
    "Achieved",
)


def _register_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            _enum_value(item.kind),
            item.title,
            item.description or "-",
            _enum_value(item.status),
            item.owner or "-",
            _number_text(item.probability),
            _number_text(item.expected_cost_exposure),
            str(item.impact_days),
            item.response or "-",
            item.decision or "-",
            _date_text(item.due_on),
        ]
        for item in sorted(
            project.register_items, key=lambda item: (item.kind.value, item.id.casefold())
        )
    ]


REGISTER_HEADERS = (
    "ID",
    "Kind",
    "Title",
    "Description",
    "Status",
    "Owner",
    "Probability",
    "Expected cost exposure",
    "Impact days",
    "Response",
    "Decision",
    "Due",
)


def _critical_rows(schedule: ScheduleProjection) -> list[list[object]]:
    by_id = {item.id: item for item in schedule.items}
    return [
        [index, entity_id, by_id[entity_id].title]
        for index, entity_id in enumerate(schedule.critical_path, start=1)
        if entity_id in by_id
    ]


def _project_control_rows(project: ManagedProject) -> list[list[object]]:
    return [
        ["Project ID", project.id],
        ["Lifecycle", _enum_value(project.lifecycle)],
        ["Sponsor", project.sponsor or "-"],
        ["Manager", project.manager or "-"],
        ["Planned start", _date_text(project.planned_start_on)],
        ["Target due", _date_text(project.target_due_on)],
        ["Revision", project.revision],
    ]


def _criterion_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [item.id, item.description, _enum_value(item.status), ", ".join(item.evidence_ids) or "-"]
        for item in project.completion_criteria
    ]


def _constraint_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [item.id, item.statement, item.owner or "-", "yes" if item.active else "no"]
        for item in project.constraints
    ]


def _assumption_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [item.id, item.statement, _enum_value(item.status), item.validation_note or "-"]
        for item in project.assumptions
    ]


REQUIREMENT_HEADERS = (
    "ID",
    "Kind",
    "Title",
    "Statement",
    "Status",
    "Source",
    "Parent",
    "Required V&V",
)


def _requirement_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            _enum_value(item.kind),
            item.title,
            item.statement,
            _enum_value(item.status),
            item.source or "-",
            item.parent_id or "-",
            ", ".join(_enum_value(activity) for activity in item.required_activities),
        ]
        for item in sorted(project.requirements, key=lambda item: (item.id.casefold(), item.id))
    ]


VERIFICATION_HEADERS = (
    "ID",
    "Activity",
    "Method",
    "Result",
    "Requirements",
    "Evidence",
    "Performed",
    "Notes",
)


def _verification_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            _enum_value(item.activity),
            _enum_value(item.method),
            _enum_value(item.result),
            ", ".join(item.requirement_ids),
            ", ".join(item.evidence_ids) or "-",
            _datetime_text(item.performed_at),
            item.notes or "-",
        ]
        for item in sorted(
            project.verification_records, key=lambda item: (item.id.casefold(), item.id)
        )
    ]


GATE_HEADERS = (
    "ID",
    "Gate",
    "Reviewed",
    "Decision",
    "Criteria",
    "Evidence",
    "Exceptions",
    "Rationale",
)


def _gate_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            item.title,
            _datetime_text(item.reviewed_at),
            _enum_value(item.decision),
            ", ".join(item.criterion_ids) or "-",
            ", ".join(item.evidence_ids) or "-",
            "; ".join(item.exceptions) or "-",
            item.rationale,
        ]
        for item in sorted(project.gate_reviews, key=lambda item: (item.reviewed_at, item.id))
    ]


CHANGE_HEADERS = (
    "ID",
    "Kind",
    "Title",
    "Status",
    "Targets",
    "Before",
    "After",
    "QCD impact",
    "V&V impact",
    "Decision",
    "Rationale",
    "Requested",
    "Decided",
)


def _change_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            _enum_value(item.kind),
            item.title,
            _enum_value(item.status),
            ", ".join(item.target_ids) or "-",
            item.before,
            item.after,
            item.qcd_impact,
            item.vv_impact,
            item.decision or "-",
            item.rationale or "-",
            _datetime_text(item.requested_at),
            _datetime_text(item.decided_at),
        ]
        for item in sorted(project.change_requests, key=lambda item: (item.requested_at, item.id))
    ]


BASELINE_HEADERS = (
    "ID",
    "Label",
    "Project revision",
    "Content hash",
    "Event ID",
    "Created",
)


def _baseline_rows(project: ManagedProject) -> list[list[object]]:
    return [
        [
            item.id,
            item.label,
            item.project_revision,
            item.content_hash,
            item.event_id,
            _datetime_text(item.created_at),
        ]
        for item in sorted(project.baselines, key=lambda item: (item.created_at, item.id))
    ]


def render_html_project_report(
    project: ManagedProject,
    schedule: ScheduleProjection,
    qcd: QcdProjection | None = None,
) -> str:
    """Render a standalone HTML status report, escaping every dynamic value."""

    schedule_rows = _schedule_rows(project, schedule)
    report_title = f"{project.title} — Project report"
    overall_health = _enum_value(qcd.overall_health) if qcd else "unknown"
    sections = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(report_title, quote=True)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;line-height:1.45;margin:2rem;color:#172b4d}",
        "main{max-width:120rem;margin:auto}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0 2rem}",
        "th,td{border:1px solid #c1c7d0;padding:.45rem;text-align:left;vertical-align:top}",
        "th{background:#f4f5f7}.empty{color:#626f86;font-style:italic}",
        "code{background:#f4f5f7;padding:.1rem .25rem}.health{font-weight:700}",
        "</style>",
        "</head>",
        "<body><main>",
        f"<h1>{html.escape(project.title, quote=True)}</h1>",
        f'<p class="health">Overall QCD health: {html.escape(overall_health, quote=True)}</p>',
        _html_table(
            ("Field", "Value"), _project_control_rows(project), empty_message="No controls"
        ),
        "<h2>Goal</h2>",
        f"<p>{html.escape(_plain(project.goal), quote=True)}</p>",
        "<h2>Requirements</h2>",
        _html_table(
            REQUIREMENT_HEADERS,
            _requirement_rows(project),
            empty_message="No requirements",
        ),
        "<h2>Verification and validation</h2>",
        _html_table(
            VERIFICATION_HEADERS,
            _verification_rows(project),
            empty_message="No V&V records",
        ),
        "<h2>Gate reviews</h2>",
        _html_table(GATE_HEADERS, _gate_rows(project), empty_message="No gate reviews"),
        "<h2>QCD</h2>",
        _html_table(QCD_HEADERS, _qcd_rows(project, qcd), empty_message="No QCD plan"),
        "<h2>Schedule and WBS</h2>",
        _html_table(SCHEDULE_HEADERS, schedule_rows, empty_message="No scheduled work"),
        "<h2>Milestones</h2>",
        _html_table(
            MILESTONE_HEADERS,
            _milestone_rows(project, schedule),
            empty_message="No milestones",
        ),
        "<h2>Critical path</h2>",
        _html_table(
            ("Order", "ID", "Title"),
            _critical_rows(schedule),
            empty_message="No critical path",
        ),
        "<h2>Risk, opportunity, issue, and decision register</h2>",
        _html_table(REGISTER_HEADERS, _register_rows(project), empty_message="Register is empty"),
        "<h2>Change requests</h2>",
        _html_table(CHANGE_HEADERS, _change_rows(project), empty_message="No change requests"),
        "<h2>Baselines</h2>",
        _html_table(BASELINE_HEADERS, _baseline_rows(project), empty_message="No baselines"),
        "<h2>Constraints</h2>",
        _html_table(
            ("ID", "Constraint", "Owner", "Active"),
            _constraint_rows(project),
            empty_message="No constraints",
        ),
        "<h2>Assumptions</h2>",
        _html_table(
            ("ID", "Assumption", "Status", "Validation note"),
            _assumption_rows(project),
            empty_message="No assumptions",
        ),
        "<h2>Project completion criteria</h2>",
        _html_table(
            ("ID", "Criterion", "Status", "Evidence"),
            _criterion_rows(project),
            empty_message="No completion criteria",
        ),
        "</main></body></html>",
    ]
    return "\n".join(sections) + "\n"


def render_html_gantt(
    project: ManagedProject,
    schedule: ScheduleProjection,
    *,
    today: date | None = None,
) -> str:
    """Render an offline, interactive Gantt using only HTML, CSS, and SVG."""

    ordered = _ordered_schedule_items(schedule)
    latest_baseline = project.baselines[-1] if project.baselines else None
    baseline_by_id = (
        {item.id: item for item in latest_baseline.schedule_items} if latest_baseline else {}
    )
    starts = [item.scheduled_start_on for item in ordered]
    finishes = [item.scheduled_finish_on for item in ordered]
    starts.extend(item.start_on for item in baseline_by_id.values())
    finishes.extend(item.finish_on for item in baseline_by_id.values())
    timeline_start = min(starts, default=schedule.anchor_on)
    timeline_finish = max(finishes, default=schedule.project_finish_on or schedule.anchor_on)
    total_days = max(1, (timeline_finish - timeline_start).days + 1)
    source_by_id = _source_items(project)

    def position(start: date, finish: date) -> tuple[int, int]:
        return (start - timeline_start).days, max(1, (finish - start).days + 1)

    day_headers = []
    for offset in range(total_days):
        value = timeline_start.fromordinal(timeline_start.toordinal() + offset)
        day_headers.append(
            f'<span class="day" style="grid-column:{offset + 1}">{value:%m-%d}</span>'
        )

    rows: list[str] = []
    dependency_rows: list[str] = []
    for item in ordered:
        source = source_by_id.get(item.id)
        phase_id = getattr(source, "phase_id", None)
        phase = _phase_name(project, phase_id)
        owner = item.owner or "-"
        jira = item.jira_status or "-"
        search = " ".join((item.id, item.title, phase, owner, jira)).casefold()
        current_left, current_width = position(item.scheduled_start_on, item.scheduled_finish_on)
        bar_id = _mermaid_id(item.id)
        baseline_html = ""
        baseline = baseline_by_id.get(item.id)
        if baseline is not None:
            baseline_left, baseline_width = position(baseline.start_on, baseline.finish_on)
            baseline_html = (
                f'<span class="baseline-bar" style="--left:{baseline_left};'
                f'--span:{baseline_width}" title="Baseline: '
                f'{baseline.start_on.isoformat()} to {baseline.finish_on.isoformat()}"></span>'
            )
        classes = ["gantt-bar"]
        if item.critical:
            classes.append("critical")
        if item.delay_days:
            classes.append("delayed")
        if item.kind == "milestone":
            milestone_classes = ["milestone"]
            if item.critical:
                milestone_classes.append("critical")
            current_html = (
                f'<span id="{bar_id}" class="{" ".join(milestone_classes)}" '
                f'style="--left:{current_left}" title="Milestone: '
                f'{html.escape(item.title, quote=True)}"></span>'
            )
        else:
            current_html = (
                f'<span id="{bar_id}" class="{" ".join(classes)}" '
                f'style="--left:{current_left};--span:{current_width}" '
                f'title="{item.scheduled_start_on.isoformat()} to '
                f"{item.scheduled_finish_on.isoformat()}; total float "
                f'{item.total_float_days}; free float {item.free_float_days}">'
                f'<span class="progress" style="width:{item.progress_percent}%"></span></span>'
            )
        rows.append(
            f'<div class="gantt-row" data-search="{html.escape(search, quote=True)}">'
            '<div class="item-meta">'
            f"<strong>{html.escape(item.id, quote=True)}</strong>"
            f'<span class="item-title">{html.escape(item.title, quote=True)}</span>'
            f"<span>{html.escape(phase, quote=True)}</span>"
            f"<span>{html.escape(owner, quote=True)}</span>"
            f"<span>{item.progress_percent}%</span>"
            f"<span>{html.escape(jira, quote=True)}</span>"
            f"<span>TF {item.total_float_days} / FF {item.free_float_days}</span>"
            "</div>"
            f'<div class="track" style="--days:{total_days}">{baseline_html}{current_html}</div>'
            "</div>"
        )
        for dependency in item.dependencies:
            dependency_rows.append(
                f'<li data-from="{_mermaid_id(dependency.predecessor_id)}" '
                f'data-to="{bar_id}">{dependency.type.label}'
                f" ({dependency.lag_days:+d} working days)</li>"
            )

    today_html = ""
    marker_day = today or date.today()
    if timeline_start <= marker_day <= timeline_finish:
        marker_left = (marker_day - timeline_start).days
        today_html = f'<span class="today-marker" style="--left:{marker_left}"></span>'

    title = html.escape(f"{project.title} — Gantt", quote=True)
    css = f"""
:root{{--day:34px;--meta:690px;--ink:#172033;--muted:#657087;--grid:#dce2ea;
--critical:#c73737;--accent:#3069d3}}
*{{box-sizing:border-box}}
body{{margin:0;font:14px system-ui,sans-serif;color:var(--ink);background:#f6f8fb}}
main{{padding:24px;min-width:900px}} h1{{margin:0 0 16px}}
.controls{{display:flex;gap:12px;margin-bottom:12px}}
input,select{{padding:7px 9px;border:1px solid #aeb8c8;border-radius:6px;background:white}}
.gantt{{background:white;border:1px solid var(--grid);border-radius:10px;
overflow:auto;position:relative}}
.timeline-head,.gantt-row{{display:grid;grid-template-columns:var(--meta) max-content;
min-width:max-content}}
.meta-head,.item-meta{{position:sticky;left:0;z-index:5;background:white;display:grid;
grid-template-columns:100px 150px 100px 80px 60px 90px 110px;gap:0;
border-right:1px solid var(--grid)}}
.meta-head span,.item-meta>*{{padding:8px;border-right:1px solid #edf0f5;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.days,.track{{width:calc(var(--days) * var(--day));display:grid;
grid-template-columns:repeat(var(--days),var(--day));position:relative;
background:repeating-linear-gradient(90deg,transparent 0 calc(var(--day) - 1px),
var(--grid) calc(var(--day) - 1px) var(--day))}}
.days{{--days:{total_days};height:34px}}
.day{{font-size:11px;color:var(--muted);padding:8px 2px;
border-right:1px solid var(--grid)}}
.gantt-row{{border-top:1px solid var(--grid);min-height:54px}}
.track{{min-height:54px;--days:{total_days}}}
.baseline-bar,.gantt-bar{{position:absolute;
left:calc(var(--left) * var(--day) + 3px);
width:calc(var(--span) * var(--day) - 6px);border-radius:5px}}
.baseline-bar{{top:7px;height:7px;background:#9aa6b8}}
.gantt-bar{{top:20px;height:24px;background:var(--accent);overflow:hidden}}
.gantt-bar.critical{{outline:2px solid var(--critical)}}
.gantt-bar.delayed{{background:#d77a2e}}
.progress{{display:block;height:100%;background:#173f91;opacity:.7}}
.milestone{{position:absolute;left:calc(var(--left) * var(--day) + 11px);top:19px;
width:18px;height:18px;background:var(--accent);transform:rotate(45deg)}}
.milestone.critical{{outline:2px solid var(--critical)}}
.today-marker{{position:absolute;z-index:4;
left:calc(var(--meta) + var(--left) * var(--day) + 17px);top:34px;bottom:0;
border-left:2px solid #d53b80;pointer-events:none}}
#dependency-lines{{position:absolute;inset:34px 0 0 var(--meta);pointer-events:none;
z-index:3;overflow:visible}}
.dependencies{{position:absolute;left:-9999px}}
""".strip()
    script = """
const root=document.documentElement;
const filter=document.getElementById('gantt-filter');
const zoom=document.getElementById('gantt-zoom');
filter.addEventListener('input',()=>document.querySelectorAll('.gantt-row').forEach(
  row=>row.hidden=!row.dataset.search.includes(filter.value.toLowerCase())));
zoom.addEventListener('change',()=>{
  root.style.setProperty('--day',zoom.value+'px');drawDependencies()});
function drawDependencies(){
  const svg=document.getElementById('dependency-lines');svg.replaceChildren();
  const base=svg.getBoundingClientRect();
  document.querySelectorAll('.dependencies li').forEach(link=>{
    const from=document.getElementById(link.dataset.from);
    const to=document.getElementById(link.dataset.to);
    if(!from||!to||from.closest('.gantt-row').hidden||
       to.closest('.gantt-row').hidden)return;
    const a=from.getBoundingClientRect(),b=to.getBoundingClientRect();
    const ns='http://www.w3.org/2000/svg';
    const path=document.createElementNS(ns,'path');
    const x1=a.right-base.left,y1=a.top+a.height/2-base.top;
    const x2=b.left-base.left,y2=b.top+b.height/2-base.top;
    path.setAttribute('d',`M${x1},${y1} H${x1+12} V${y2} H${x2}`);
    path.setAttribute('fill','none');path.setAttribute('stroke','#657087');
    path.setAttribute('stroke-width','1.5');svg.append(path)})}
filter.addEventListener('input',drawDependencies);
addEventListener('resize',drawDependencies);addEventListener('load',drawDependencies);
""".strip()
    controls = (
        '<div class="controls"><label>Filter <input id="gantt-filter" type="search" '
        'placeholder="ID, title, owner, phase"></label><label>Zoom '
        '<select id="gantt-zoom"><option value="24">Compact</option>'
        '<option value="34" selected>Day</option><option value="52">Wide</option>'
        "</select></label></div>"
    )
    meta_header = (
        '<div class="timeline-head"><div class="meta-head"><span>ID</span>'
        "<span>Work item</span><span>WBS / phase</span><span>Owner</span>"
        "<span>Progress</span><span>Jira</span><span>Float</span></div>"
    )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            f"<title>{title}</title>",
            "<style>",
            css,
            "</style></head><body><main>",
            f"<h1>{title}</h1>",
            controls,
            '<section class="gantt" data-testid="gantt-chart">',
            meta_header,
            f'<div class="days">{"".join(day_headers)}</div></div>',
            today_html,
            '<svg id="dependency-lines" aria-label="Dependency lines"></svg>',
            *rows,
            f'<ul class="dependencies">{"".join(dependency_rows)}</ul>',
            "</section>",
            "<script>",
            script,
            "</script></main></body></html>",
            "",
        ]
    )


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = [
        "| " + " | ".join(_markdown_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    if rows:
        lines.extend("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |" for row in rows)
    else:
        lines.append("| " + " | ".join(["No data", *("-" for _ in headers[1:])]) + " |")
    return "\n".join(lines)


def render_markdown_project_report(
    project: ManagedProject,
    schedule: ScheduleProjection,
    qcd: QcdProjection | None = None,
) -> str:
    """Render provider-neutral Markdown suitable for a publishing adapter."""

    overall_health = _enum_value(qcd.overall_health) if qcd else "unknown"
    sections = [
        f"# {_markdown_inline(project.title)}",
        "",
        f"**Overall QCD health:** {_markdown_inline(overall_health)}",
        "",
        _markdown_table(("Field", "Value"), _project_control_rows(project)),
        "",
        "## Goal",
        "",
        _markdown_inline(project.goal),
        "",
        "## Requirements",
        "",
        _markdown_table(REQUIREMENT_HEADERS, _requirement_rows(project)),
        "",
        "## Verification and validation",
        "",
        _markdown_table(VERIFICATION_HEADERS, _verification_rows(project)),
        "",
        "## Gate reviews",
        "",
        _markdown_table(GATE_HEADERS, _gate_rows(project)),
        "",
        "## QCD",
        "",
        _markdown_table(QCD_HEADERS, _qcd_rows(project, qcd)),
        "",
        "## Schedule and WBS",
        "",
        _markdown_table(SCHEDULE_HEADERS, _schedule_rows(project, schedule)),
        "",
        "## Mermaid Gantt",
        "",
        "```mermaid",
        render_mermaid_gantt(project, schedule).rstrip(),
        "```",
        "",
        "## Milestones",
        "",
        _markdown_table(MILESTONE_HEADERS, _milestone_rows(project, schedule)),
        "",
        "## Critical path",
        "",
        _markdown_table(("Order", "ID", "Title"), _critical_rows(schedule)),
        "",
        "## Risk, opportunity, issue, and decision register",
        "",
        _markdown_table(REGISTER_HEADERS, _register_rows(project)),
        "",
        "## Change requests",
        "",
        _markdown_table(CHANGE_HEADERS, _change_rows(project)),
        "",
        "## Baselines",
        "",
        _markdown_table(BASELINE_HEADERS, _baseline_rows(project)),
        "",
        "## Constraints",
        "",
        _markdown_table(("ID", "Constraint", "Owner", "Active"), _constraint_rows(project)),
        "",
        "## Assumptions",
        "",
        _markdown_table(
            ("ID", "Assumption", "Status", "Validation note"), _assumption_rows(project)
        ),
        "",
        "## Project completion criteria",
        "",
        _markdown_table(("ID", "Criterion", "Status", "Evidence"), _criterion_rows(project)),
    ]
    return "\n".join(sections).rstrip() + "\n"


__all__ = [
    "render_html_project_report",
    "render_markdown_project_report",
    "render_mermaid_gantt",
    "render_schedule_table",
]
