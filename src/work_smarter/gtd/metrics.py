"""Pure metrics projection from GTD snapshots and append-only audit events."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from work_smarter.gtd.events import EventType
from work_smarter.gtd.models import MetricsReport, Task, TaskStatus, utc_now
from work_smarter.storage.events import Event

__all__ = ["project_metrics"]

_Interval = tuple[datetime, datetime]
_EpisodeKey = tuple[str, str]


def _aware(value: datetime) -> datetime:
    """Normalize naive legacy timestamps to UTC without changing aware values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _payload_number(payload: dict[str, object], key: str) -> float:
    """Read a non-negative finite number from an extensible event payload."""

    try:
        value = float(payload.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def _episode_id(event: Event, field: str) -> str:
    """Return a stable key, including for pre-identifier legacy events."""

    value = event.payload.get(field)
    if value is not None and str(value).strip():
        return str(value).strip()
    return f"legacy:{event.id}"


def _oldest_open_key(
    opened: dict[_EpisodeKey, datetime],
    entity_id: str,
) -> _EpisodeKey | None:
    candidates = ((key, started_at) for key, started_at in opened.items() if key[0] == entity_id)
    return min(candidates, key=lambda item: (item[1], item[0][1]), default=(None, None))[0]


def _close_episode(
    opened: dict[_EpisodeKey, datetime],
    intervals: dict[str, list[_Interval]],
    *,
    entity_id: str,
    episode_id: str | None,
    ended_at: datetime,
) -> None:
    key = (entity_id, episode_id) if episode_id is not None else None
    if key not in opened:
        # Identifier-less legacy closing events are paired FIFO. An explicit but unknown
        # identifier is not allowed to close an unrelated concurrent episode.
        if episode_id is not None:
            return
        key = _oldest_open_key(opened, entity_id)
    if key is None:
        return
    started_at = opened.pop(key)
    intervals.setdefault(entity_id, []).append((started_at, max(started_at, ended_at)))


def _close_all_episodes(
    opened: dict[_EpisodeKey, datetime],
    intervals: dict[str, list[_Interval]],
    *,
    entity_id: str,
    ended_at: datetime,
) -> None:
    """Close every independent facet when its owning task becomes terminal."""

    keys = [key for key in opened if key[0] == entity_id]
    for key in keys:
        started_at = opened.pop(key)
        intervals.setdefault(entity_id, []).append((started_at, max(started_at, ended_at)))


def _seconds(intervals: Iterable[_Interval]) -> float:
    return sum(max(0.0, (end - start).total_seconds()) for start, end in intervals)


def _union_seconds(intervals: Iterable[_Interval]) -> float:
    """Measure wall-clock coverage once even when blockers overlap."""

    ordered = sorted(intervals, key=lambda interval: (interval[0], interval[1]))
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += max(0.0, (current_end - current_start).total_seconds())
        current_start, current_end = start, end
    return total + max(0.0, (current_end - current_start).total_seconds())


def project_metrics(
    tasks: Iterable[Task],
    events: Iterable[Event],
    *,
    as_of: datetime | None = None,
) -> MetricsReport:
    """Project GTD metrics without reading or mutating a workspace.

    ``tasks`` is the authoritative current snapshot. ``events`` supplies historical
    effort and interval facts. Callers can pass ``as_of`` for a deterministic clock;
    events after that instant are ignored and open intervals accrue only to it.
    """

    projected_at = _aware(as_of or utc_now())
    snapshots = list(tasks)
    task_ids = {task.id for task in snapshots}
    ordered_events = [
        event
        for _, event in sorted(
            enumerate(events),
            key=lambda item: (_aware(item[1].occurred_at), item[0]),
        )
        if _aware(event.occurred_at) <= projected_at
    ]

    logged_seconds_by_task: dict[str, float] = {}
    legacy_stopped_seconds_by_task: dict[str, float] = {}
    seen_work_logs: set[tuple[str, str]] = set()
    effective_work_log_seconds: dict[tuple[str, str], float] = {}
    seen_corrections: set[str] = set()

    active_cycles: dict[str, datetime] = {}
    cycle_seconds: list[float] = []

    open_waiting: dict[_EpisodeKey, datetime] = {}
    waiting_intervals: dict[str, list[_Interval]] = {}
    open_blockers: dict[_EpisodeKey, datetime] = {}
    blocker_intervals: dict[str, list[_Interval]] = {}

    for event in ordered_events:
        entity_id = event.entity_id
        if entity_id is None:
            continue
        occurred_at = _aware(event.occurred_at)

        if entity_id in task_ids:
            if event.type == EventType.TASK_WORK_LOGGED:
                raw_work_log_id = event.payload.get("work_log_id")
                work_log_id = (
                    str(raw_work_log_id).strip()
                    if raw_work_log_id is not None and str(raw_work_log_id).strip()
                    else f"event:{event.id}"
                )
                work_log_key = (entity_id, work_log_id)
                if work_log_key not in seen_work_logs:
                    seen_work_logs.add(work_log_key)
                    logged_seconds = _payload_number(event.payload, "minutes") * 60
                    effective_work_log_seconds[work_log_key] = logged_seconds
                    logged_seconds_by_task[entity_id] = (
                        logged_seconds_by_task.get(entity_id, 0.0) + logged_seconds
                    )
            elif event.type == EventType.TASK_WORK_LOG_CORRECTED:
                correction_id = str(event.payload.get("correction_id") or f"event:{event.id}")
                work_log_id = str(event.payload.get("work_log_id") or "").strip()
                work_log_key = (entity_id, work_log_id)
                if (
                    correction_id not in seen_corrections
                    and work_log_id
                    and work_log_key in effective_work_log_seconds
                ):
                    seen_corrections.add(correction_id)
                    previous_seconds = effective_work_log_seconds[work_log_key]
                    corrected_seconds = _payload_number(event.payload, "to_minutes") * 60
                    effective_work_log_seconds[work_log_key] = corrected_seconds
                    logged_seconds_by_task[entity_id] = (
                        logged_seconds_by_task.get(entity_id, 0.0)
                        - previous_seconds
                        + corrected_seconds
                    )
            elif event.type == EventType.TASK_STOPPED and not event.payload.get("work_log_id"):
                legacy_stopped_seconds_by_task[entity_id] = legacy_stopped_seconds_by_task.get(
                    entity_id, 0.0
                ) + _payload_number(event.payload, "duration_seconds")

        if event.type == EventType.TASK_STARTED:
            active_cycles.setdefault(entity_id, occurred_at)
        elif event.type == EventType.TASK_COMPLETED:
            started_at = active_cycles.pop(entity_id, None)
            if started_at is not None:
                cycle_seconds.append(max(0.0, (occurred_at - started_at).total_seconds()))
            # Completion is a terminal boundary even if an older adapter omitted
            # dedicated waiting/blocker resolution events.
            _close_all_episodes(
                open_waiting,
                waiting_intervals,
                entity_id=entity_id,
                ended_at=occurred_at,
            )
            _close_all_episodes(
                open_blockers,
                blocker_intervals,
                entity_id=entity_id,
                ended_at=occurred_at,
            )

        if event.type == EventType.TASK_DELEGATED:
            key = (entity_id, _episode_id(event, "waiting_id"))
            open_waiting.setdefault(key, occurred_at)
        elif event.type == EventType.TASK_WAITING_RESOLVED:
            raw_waiting_id = event.payload.get("waiting_id")
            waiting_id = (
                str(raw_waiting_id).strip()
                if raw_waiting_id is not None and str(raw_waiting_id).strip()
                else None
            )
            _close_episode(
                open_waiting,
                waiting_intervals,
                entity_id=entity_id,
                episode_id=waiting_id,
                ended_at=occurred_at,
            )

        if event.type == EventType.TASK_BLOCKED:
            key = (entity_id, _episode_id(event, "blocker_id"))
            open_blockers.setdefault(key, occurred_at)
        elif event.type == EventType.TASK_UNBLOCKED:
            raw_blocker_id = event.payload.get("blocker_id")
            blocker_id = (
                str(raw_blocker_id).strip()
                if raw_blocker_id is not None and str(raw_blocker_id).strip()
                else None
            )
            _close_episode(
                open_blockers,
                blocker_intervals,
                entity_id=entity_id,
                episode_id=blocker_id,
                ended_at=occurred_at,
            )

    for (entity_id, _), started_at in open_waiting.items():
        waiting_intervals.setdefault(entity_id, []).append((started_at, projected_at))
    for (entity_id, _), started_at in open_blockers.items():
        blocker_intervals.setdefault(entity_id, []).append((started_at, projected_at))

    focus_seconds_by_task = {
        task.id: logged_seconds_by_task.get(task.id, 0.0)
        + legacy_stopped_seconds_by_task.get(task.id, 0.0)
        for task in snapshots
    }
    completed = [
        task
        for task in snapshots
        if task.status is TaskStatus.DONE
        and task.completed_at is not None
        and _aware(task.completed_at) <= projected_at
    ]
    recent = [
        task for task in completed if projected_at - _aware(task.completed_at) <= timedelta(days=7)
    ]
    lead_hours = [
        (_aware(task.completed_at) - _aware(task.created_at)).total_seconds() / 3600
        for task in completed
        if task.completed_at is not None
    ]
    estimate_ratios = [
        (focus_seconds_by_task.get(task.id, 0.0) / 60) / task.estimate_minutes
        for task in completed
        if task.estimate_minutes and focus_seconds_by_task.get(task.id, 0.0) > 0
    ]
    waiting_ages = [
        max(
            0.0,
            (projected_at - _aware(task.waiting.delegated_at)).total_seconds() / 3600,
        )
        for task in snapshots
        if task.waiting is not None and _aware(task.waiting.delegated_at) <= projected_at
    ]
    blocked_ages = [
        max(
            0.0,
            (
                projected_at
                - min(
                    _aware(blocker.created_at)
                    for blocker in task.blockers
                    if blocker.resolved_at is None
                )
            ).total_seconds()
            / 3600,
        )
        for task in snapshots
        if any(
            blocker.resolved_at is None and _aware(blocker.created_at) <= projected_at
            for blocker in task.blockers
        )
    ]

    return MetricsReport(
        generated_at=projected_at,
        completed_total=len(completed),
        completed_last_7_days=len(recent),
        focus_minutes_total=round(sum(focus_seconds_by_task.values()) / 60, 2),
        average_lead_time_hours=(
            round(sum(lead_hours) / len(lead_hours), 2) if lead_hours else None
        ),
        average_estimate_ratio=(
            round(sum(estimate_ratios) / len(estimate_ratios), 2) if estimate_ratios else None
        ),
        average_cycle_time_hours=(
            round(sum(cycle_seconds) / len(cycle_seconds) / 3600, 2) if cycle_seconds else None
        ),
        cycle_time_sample_count=len(cycle_seconds),
        waiting_minutes_total=round(
            sum(_seconds(intervals) for intervals in waiting_intervals.values()) / 60,
            2,
        ),
        blocked_minutes_total=round(
            sum(_union_seconds(intervals) for intervals in blocker_intervals.values()) / 60,
            2,
        ),
        wip_current=sum(task.status is TaskStatus.DOING for task in snapshots),
        waiting_current=sum(task.waiting is not None for task in snapshots),
        blocked_current=sum(task.status is TaskStatus.BLOCKED for task in snapshots),
        average_current_waiting_age_hours=(
            round(sum(waiting_ages) / len(waiting_ages), 2) if waiting_ages else None
        ),
        oldest_waiting_age_hours=(round(max(waiting_ages), 2) if waiting_ages else None),
        average_current_blocked_age_hours=(
            round(sum(blocked_ages) / len(blocked_ages), 2) if blocked_ages else None
        ),
        oldest_blocked_age_hours=(round(max(blocked_ages), 2) if blocked_ages else None),
    )
