from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from work_smarter.errors import InvalidTransitionError
from work_smarter.gtd.events import EventType
from work_smarter.gtd.models import (
    Task,
    TaskDisposition,
    TaskStatus,
    WaitingDetail,
    WeeklyReviewStep,
)
from work_smarter.gtd.service import GtdService
from work_smarter.storage.events import Event
from work_smarter.storage.workspace import Workspace


def test_delegate_follow_up_escalate_and_resolve_preserves_history(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Obtain the security approval").created[0].id

    delegated = service.delegate_task(
        task_id,
        target="Security reviewer",
        request="Approve the threat model",
        expected_on=date(2026, 7, 25),
        follow_up_on=date(2026, 7, 24),
        escalation_on=date(2026, 7, 26),
        escalation_to="Security lead",
    )
    followed = service.follow_up_waiting(
        task_id,
        note="Asked in the review channel",
        next_follow_up_on=date(2026, 7, 25),
    )
    escalated = service.escalate_waiting(
        task_id,
        note="Approval is now on the release critical path",
        escalation_to="Security lead",
    )
    resolved = service.record_waiting_response(
        task_id,
        note="Approved with no additional action",
        resolved=True,
    )

    assert delegated.status is TaskStatus.WAITING
    assert delegated.waiting is not None
    assert delegated.waiting.request == "Approve the threat model"
    assert followed.waiting is not None
    assert followed.waiting.follow_up_on == date(2026, 7, 25)
    assert escalated.waiting is not None
    assert [item.kind.value for item in escalated.waiting.interactions] == [
        "delegated",
        "follow_up",
        "escalated",
    ]
    assert resolved.status is TaskStatus.NEXT
    assert resolved.waiting is None
    assert len(resolved.waiting_history) == 1
    assert resolved.waiting_history[0].resolution_note == "Approved with no additional action"
    assert resolved.waiting_history[0].interactions[-1].kind.value == "response"


def test_unresolved_response_keeps_waiting_with_a_new_follow_up(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Receive the vendor answer").created[0].id
    service.delegate_task(task_id, target="Vendor", request="Explain the failure")

    task = service.record_waiting_response(
        task_id,
        note="Vendor needs logs from another region",
        resolved=False,
        next_follow_up_on=date(2026, 7, 28),
    )

    assert task.status is TaskStatus.WAITING
    assert task.waiting is not None
    assert task.waiting.follow_up_on == date(2026, 7, 28)
    assert task.waiting.interactions[-1].kind.value == "response"


def test_resolve_blocker_is_individual_and_reveals_waiting_facet(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Receive the signed decision").created[0].id
    service.delegate_task(task_id, target="Decision owner")
    first = service.block_task(task_id, "Document access is broken")
    second = service.block_task(task_id, "Owner is on leave")
    assert first.blockers[-1].id == "BLK-1"
    assert second.status is TaskStatus.BLOCKED

    still_blocked = service.resolve_blocker(task_id, "BLK-1", note="Access restored")
    waiting = service.resolve_blocker(task_id, "BLK-2", note="Delegate returned")

    assert still_blocked.status is TaskStatus.BLOCKED
    assert waiting.status is TaskStatus.WAITING
    assert waiting.waiting is not None


def test_schedule_defer_and_due_have_distinct_execution_semantics(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Attend the architecture review").created[0].id
    scheduled_for = datetime.now(UTC) + timedelta(days=2)

    scheduled = service.schedule_task(task_id, scheduled_for=scheduled_for)
    with pytest.raises(InvalidTransitionError, match="scheduled for"):
        service.start_task(task_id)

    ready = service.ready_task(task_id)
    deferred = service.defer_task(
        task_id,
        not_before=datetime.now(UTC) + timedelta(days=1),
    )
    due = service.set_task_due(task_id, due_on=date.today())

    assert scheduled.status is TaskStatus.SCHEDULED
    assert ready.status is TaskStatus.NEXT
    assert deferred.status is TaskStatus.NEXT
    assert due.due_on == date.today()
    assert task_id not in [task.id for task in service.focus()]


def test_daily_dashboard_surfaces_due_follow_up_escalation_and_tickler(
    service: GtdService,
) -> None:
    today = date(2026, 7, 23)
    overdue = service.add_next_action("Submit yesterday's report", due_on="2026-07-22")
    due_today = service.add_next_action("Make today's release decision", due_on=today)
    waiting_id = service.add_next_action("Receive approval").created[0].id
    service.delegate_task(
        waiting_id,
        target="Approver",
        follow_up_on=today,
        escalation_on=today,
        escalation_to="Director",
    )
    tickler_id = (
        service.add_next_action(
            "Prepare available material",
            not_before="2026-07-23T00:00:00Z",
        )
        .created[0]
        .id
    )

    dashboard = service.daily_dashboard(today=today)

    assert [item.id for item in dashboard.overdue] == [overdue.created[0].id]
    assert [item.id for item in dashboard.due_today] == [due_today.created[0].id]
    assert [item.id for item in dashboard.follow_ups_due] == [waiting_id]
    assert [item.id for item in dashboard.escalations_due] == [waiting_id]
    assert tickler_id in [item.id for item in dashboard.available_actions]


def test_weekly_review_has_a_systematic_checklist(service: GtdService) -> None:
    service.capture("Unclarified input")

    report = service.weekly_review()

    assert [item.key for item in report.checklist] == [
        "inbox_zero",
        "calendar_reviewed",
        "waiting_reviewed",
        "projects_reviewed",
        "someday_reviewed",
    ]
    assert report.checklist[0].complete is False
    assert report.checklist[0].count == 1


def test_reopen_preserves_the_completion_snapshot_and_requires_a_reason(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Verify the rollout").created[0].id
    service.complete_task(task_id)

    with pytest.raises(InvalidTransitionError, match="reason"):
        service.reopen_task(task_id, reason=" ")

    reopened = service.reopen_task(task_id, reason="Production evidence contradicted the result")

    assert reopened.status is TaskStatus.NEXT
    assert reopened.completed_at is None
    assert len(reopened.completion_history) == 1
    assert reopened.completion_history[0].reopen_reason == (
        "Production evidence contradicted the result"
    )


def test_workflow_metrics_include_cycle_waiting_and_blocked_time(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = service.add_next_action("Measure this flow", estimate_minutes=60).created[0].id
    base = datetime(2026, 7, 20, tzinfo=UTC)
    for event_id, event_type, occurred_at in (
        ("EVT-START", EventType.TASK_STARTED, base),
        ("EVT-DELEGATE", EventType.TASK_DELEGATED, base + timedelta(hours=1)),
        ("EVT-WAIT-DONE", EventType.TASK_WAITING_RESOLVED, base + timedelta(hours=3)),
        ("EVT-BLOCK", EventType.TASK_BLOCKED, base + timedelta(hours=4)),
        ("EVT-UNBLOCK", EventType.TASK_UNBLOCKED, base + timedelta(hours=5)),
        ("EVT-COMPLETE", EventType.TASK_COMPLETED, base + timedelta(hours=8)),
    ):
        workspace.event_store.append(
            Event(
                id=event_id,
                type=event_type,
                entity_id=task_id,
                occurred_at=occurred_at,
            )
        )

    report = service.metrics()

    assert report.average_cycle_time_hours == 8
    assert report.waiting_minutes_total == 120
    assert report.blocked_minutes_total == 60
    assert report.wip_current == 0


def test_done_during_clarify_records_the_two_minute_rule(
    service: GtdService,
    workspace: Workspace,
) -> None:
    item = service.capture("Send the two-line acknowledgement")
    result = service.clarify(item.id, "done")

    completion_event = next(
        event
        for event in workspace.event_store.read_all()
        if event.type == EventType.TASK_COMPLETED and event.entity_id == result.created[0].id
    )
    assert completion_event.payload["two_minute_rule"] is True


def test_waiting_facet_model_rejects_inconsistent_active_and_history() -> None:
    with pytest.raises(ValueError, match="must agree"):
        Task(id="TASK-1", title="Invalid waiting", disposition=TaskDisposition.WAITING)

    with pytest.raises(ValueError, match="only resolved cycles"):
        Task(
            id="TASK-2",
            title="Invalid history",
            waiting_history=[WaitingDetail(id="WAIT-1", target="Owner")],
        )


def test_escalation_records_party_and_clears_the_consumed_deadline(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Receive launch approval").created[0].id
    service.delegate_task(
        task_id,
        target="Approver",
        escalation_on=date(2026, 7, 23),
        escalation_to="Director",
    )

    escalated = service.escalate_waiting(
        task_id,
        note="Launch is at risk",
    )

    assert escalated.waiting is not None
    assert escalated.waiting.escalation_on is None
    assert escalated.waiting.interactions[-1].party == "Director"
    assert service.daily_dashboard(today=date(2026, 7, 24)).escalations_due == []


def test_weekly_review_session_is_resumable_and_requires_checked_steps(
    service: GtdService,
) -> None:
    first = service.start_weekly_review()
    resumed = service.start_weekly_review()
    assert resumed.id == first.id

    with pytest.raises(InvalidTransitionError, match="unchecked"):
        service.complete_weekly_review(first.id)

    for step in WeeklyReviewStep:
        service.check_weekly_review_step(first.id, step)

    completed = service.complete_weekly_review(first.id)
    assert completed.completed_at is not None
    assert all(step.checked_at is not None for step in completed.steps)

    next_session = service.start_weekly_review()
    assert next_session.id != first.id


def test_work_log_correction_is_append_only_and_updates_effective_actual(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Correct a mistaken timer",
            estimate_minutes=60,
        )
        .created[0]
        .id
    )
    logged = service.log_work(task_id, minutes=30, note="Timer ran during lunch")
    remaining_after_log = logged.remaining_estimate_minutes

    corrected = service.correct_work_log(
        task_id,
        logged.work_logs[0].id,
        corrected_minutes=20,
        reason="Ten minutes were not active work",
    )

    assert corrected.work_logs[0].minutes == 30
    assert corrected.work_log_corrections[0].previous_minutes == 30
    assert corrected.work_log_corrections[0].corrected_minutes == 20
    assert corrected.actual_minutes == 20
    assert corrected.remaining_estimate_minutes == remaining_after_log
    assert service.metrics().focus_minutes_total == 20


def test_metrics_report_current_waiting_and_blocked_age(
    service: GtdService,
) -> None:
    task_id = service.add_next_action("Wait while separately blocked").created[0].id
    delegated = service.delegate_task(task_id, target="Owner")
    blocked = service.block_task(task_id, "Environment unavailable")
    assert delegated.waiting is not None
    assert blocked.blockers[-1].resolved_at is None

    as_of = max(
        delegated.waiting.delegated_at,
        blocked.blockers[-1].created_at,
    ) + timedelta(hours=2)
    report = service.metrics(as_of=as_of)

    assert report.waiting_current == 1
    assert report.blocked_current == 1
    assert report.oldest_waiting_age_hours == pytest.approx(2, abs=0.01)
    assert report.oldest_blocked_age_hours == pytest.approx(2, abs=0.01)
