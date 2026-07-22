from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from work_smarter.errors import InvalidTransitionError
from work_smarter.gtd.events import EventType
from work_smarter.gtd.models import (
    Commitment,
    CompletionCondition,
    CompletionDefinition,
    Impact,
    RecurrenceFrequency,
    Task,
    TaskRigor,
    TaskStatus,
    Urgency,
    WorkLog,
    WorkType,
)
from work_smarter.gtd.service import GtdService
from work_smarter.storage.events import Event
from work_smarter.storage.frontmatter import read_markdown, write_markdown
from work_smarter.storage.workspace import Workspace


def test_quick_ticket_exposes_rich_personal_work_fields() -> None:
    task = Task(
        id="TASK-RICH-1",
        title="Review the failure mode",
        work_type=WorkType.INVESTIGATION,
        goal="Make retry behavior decidable",
        why="Avoid another production incident",
        desired_outcome="Reviewed failure-mode table",
        constraints=["Do not expose production credentials"],
        assumptions=[{"id": "ASM-1", "statement": "Staging reproduces the failure"}],
        risks=["The failure may be timing dependent"],
    )

    assert task.schema_version == 3
    assert task.rigor is TaskRigor.QUICK
    assert task.status is TaskStatus.NEXT
    assert task.original_estimate_minutes is None
    assert task.completion.obvious is True
    assert task.assumptions[0].statement == "Staging reproduces the failure"


def test_standard_ticket_requires_goal_and_completion_condition() -> None:
    with pytest.raises(ValueError, match="standard tasks require goal"):
        Task(id="TASK-STANDARD-1", title="Ambiguous", rigor=TaskRigor.STANDARD)

    with pytest.raises(ValueError, match="completion condition"):
        Task(
            id="TASK-STANDARD-2",
            title="Still ambiguous",
            rigor=TaskRigor.STANDARD,
            goal="Produce a reviewable decision",
        )


def test_rigorous_fields_reject_blank_text_and_duplicate_condition_ids() -> None:
    with pytest.raises(ValueError, match="intent fields cannot be blank"):
        Task(
            id="TASK-BLANK-GOAL",
            title="Invalid",
            rigor="standard",
            goal="   ",
            completion={"conditions": [{"id": "CC-1", "text": "Done"}]},
        )

    with pytest.raises(ValueError, match="condition IDs must be unique"):
        CompletionDefinition(
            conditions=[
                {"id": "CC-1", "text": "First"},
                {"id": "CC-1", "text": "Second"},
            ]
        )


def test_v1_task_is_lazily_migrated_and_next_write_is_v3(
    workspace: Workspace,
) -> None:
    path = workspace.root / "tasks" / "TASK-LEGACY-1.md"
    write_markdown(
        path,
        {
            "schema_version": 1,
            "id": "TASK-LEGACY-1",
            "kind": "task",
            "title": "Legacy waiting task",
            "status": "waiting",
            "created_at": "2026-07-20T00:00:00Z",
            "updated_at": "2026-07-20T00:00:00Z",
            "contexts": ["@computer"],
            "estimate_minutes": 25,
            "actual_minutes": 0,
            "waiting_for": "Alice",
            "follow_up_on": "2026-07-24",
            "blocked_reason": "stale field from a direct edit",
            "completion_criteria": ["Alice has replied", ""],
            "tags": [],
        },
        "Legacy body",
    )

    record = workspace.read(path, expected_kind="task")
    task = record.entity
    assert isinstance(task, Task)
    assert task.schema_version == 3
    assert task.status is TaskStatus.BLOCKED
    assert task.disposition.value == "waiting"
    assert task.waiting is not None
    assert task.waiting.target == "Alice"
    assert task.original_estimate_minutes == 25
    assert [condition.text for condition in task.completion.conditions] == ["Alice has replied"]

    workspace.write(task, record.body)
    metadata = read_markdown(path).metadata
    assert metadata["schema_version"] == 3
    assert "status" not in metadata
    assert metadata["execution"]["state"] == "idle"


def test_v2_completed_assured_task_is_grandfathered_during_v3_migration() -> None:
    completed_at = datetime.now(UTC)

    task = Task.model_validate(
        {
            "schema_version": 2,
            "id": "TASK-V2-ASSURED",
            "kind": "task",
            "rigor": "assured",
            "title": "Previously completed assured task",
            "goal": "Preserve readable history",
            "lifecycle": "completed",
            "disposition": "next",
            "execution": {"state": "idle"},
            "completion": {
                "obvious": False,
                "conditions": [
                    {
                        "id": "CC-1",
                        "text": "Historic condition",
                        "met_at": completed_at,
                        "evidence": "historic-evidence",
                    }
                ],
            },
            "completed_at": completed_at,
            "resolution": "completed",
        }
    )

    assert task.schema_version == 3
    assert task.completion.assurance_grandfathered is True


def test_assured_ticket_needs_evidence_before_completion(
    service: GtdService,
) -> None:
    item = service.capture("Validate the safety mechanism")
    result = service.clarify(
        item.id,
        "next",
        rigor="assured",
        goal="Demonstrate the mechanism is safe",
        completion_criteria=["Hazard analysis reviewed"],
        constraints=["Independent review is required"],
    )
    task_id = result.created[0].id

    with pytest.raises(InvalidTransitionError, match="completion conditions"):
        service.complete_task(task_id)

    checked = service.check_completion_condition(
        task_id,
        "CC-1",
        evidence="knowledge/gtd/hazard-review.md",
    )
    assert checked.completion.conditions[0].met_at is not None
    reviewed = service.review_task_assurance(task_id)
    assert reviewed.completion.assurance_reviewed_at is not None

    completed = service.complete_task(task_id)
    assert completed.task.status is TaskStatus.DONE


def test_rigorous_completion_rejects_blank_evidence_and_waiver(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Verify the release control",
            rigor="assured",
            goal="Demonstrate release control effectiveness",
            completion_criteria=["Control result is reviewed"],
        )
        .created[0]
        .id
    )

    with pytest.raises(InvalidTransitionError, match="evidence cannot be blank"):
        service.check_completion_condition(task_id, "CC-1", evidence="   ")

    with pytest.raises(InvalidTransitionError, match="waiver reason cannot be blank"):
        service.complete_task(task_id, waiver_reason="   ")


def test_refused_doing_completion_does_not_append_timer_events(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = (
        service.add_next_action(
            "Complete with an invalid waiver",
            rigor="standard",
            goal="Preserve truthful audit history",
            completion_criteria=["Valid completion exists"],
        )
        .created[0]
        .id
    )
    service.start_task(task_id)
    before = list(workspace.event_store.read_all())

    with pytest.raises(InvalidTransitionError, match="waiver reason cannot be blank"):
        service.complete_task(task_id, waiver_reason="   ")

    after = workspace.event_store.read_all()
    assert after == before
    assert service.get_task(task_id).status is TaskStatus.DOING


def test_assured_completion_requires_constraints_and_assumptions_review(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Approve the hazardous operation",
            rigor="assured",
            goal="Make an evidence-backed approval decision",
            constraints=["Independent approval is mandatory"],
            assumptions=["The test environment matches production"],
            completion_criteria=["Approval decision is recorded"],
        )
        .created[0]
        .id
    )
    service.check_completion_condition(task_id, "CC-1", evidence="DEC-1")

    with pytest.raises(InvalidTransitionError, match="assurance review"):
        service.complete_task(task_id)

    service.review_task_assurance(task_id)
    assert service.complete_task(task_id).task.status is TaskStatus.DONE


def test_changing_assurance_inputs_invalidates_the_previous_review(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Approve the control",
            rigor="assured",
            goal="Approve an effective control",
            constraints=["Independent approval"],
            completion_criteria=["Decision recorded"],
        )
        .created[0]
        .id
    )
    service.check_completion_condition(task_id, "CC-1", evidence="DEC-1")
    service.review_task_assurance(task_id)

    changed = service.define_task(task_id, constraints=["Two independent approvals"])

    assert changed.completion.assurance_reviewed_at is None
    with pytest.raises(InvalidTransitionError, match="assurance review"):
        service.complete_task(task_id)


def test_direct_assurance_input_edit_makes_the_review_stale(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = (
        service.add_next_action(
            "Approve another control",
            rigor="assured",
            goal="Approve a verified control",
            constraints=["Independent approval"],
            completion_criteria=["Decision recorded"],
        )
        .created[0]
        .id
    )
    service.check_completion_condition(task_id, "CC-1", evidence="DEC-2")
    service.review_task_assurance(task_id)
    record = workspace.find_record(task_id, kinds={"task"})
    task = record.entity
    assert isinstance(task, Task)
    task.constraints = ["Two independent approvals"]
    workspace.write(task, record.body)

    with pytest.raises(InvalidTransitionError, match="review is stale"):
        service.complete_task(task_id)
    assert "stale_assurance_review" in {issue.code for issue in service.validate().issues}


def test_define_ticket_updates_rigor_fields_atomically(service: GtdService) -> None:
    result = service.add_next_action("Prepare the design review")
    task_id = result.created[0].id

    task = service.define_task(
        task_id,
        work_type="communication",
        rigor="standard",
        goal="Obtain approval for the design",
        why="Implementation must not start with an unresolved interface",
        desired_outcome="Review decision is recorded",
        constraints=["Use sanitized diagrams"],
        assumptions=["Reviewers have access to the proposal"],
        completion_criteria=["Decision and action items are recorded"],
    )

    assert task.work_type is WorkType.COMMUNICATION
    assert task.rigor is TaskRigor.STANDARD
    assert task.goal == "Obtain approval for the design"
    assert task.completion.conditions[0].id == "CC-1"


def test_blocks_relation_prevents_start_until_predecessor_is_done(
    service: GtdService,
) -> None:
    predecessor = service.add_next_action("Prepare input").created[0].id
    successor = service.add_next_action("Consume input").created[0].id
    service.link_tasks(predecessor, successor, relation_type="blocks")

    with pytest.raises(InvalidTransitionError, match="blocked by"):
        service.start_task(successor)

    service.complete_task(predecessor)
    started = service.start_task(successor)
    assert started.status is TaskStatus.DOING


def test_blocks_relation_rejects_a_cycle(service: GtdService) -> None:
    first = service.add_next_action("First").created[0].id
    second = service.add_next_action("Second").created[0].id
    service.link_tasks(first, second, relation_type="blocks")

    with pytest.raises(InvalidTransitionError, match="cycle"):
        service.link_tasks(second, first, relation_type="blocks")


def test_ticket_template_displays_rigor_sections(
    service: GtdService,
    workspace: Workspace,
) -> None:
    result = service.add_next_action("Write an operational decision")
    record = workspace.find_record(result.created[0].id, kinds={"task"})

    assert "## Why" in record.body
    assert "## Goal" in record.body
    assert "## Constraints" in record.body
    assert "## Assumptions" in record.body
    assert "## Definition of Done" in record.body
    assert "## Result / Evidence" in record.body


def test_completion_condition_model_records_evidence() -> None:
    now = datetime.now(UTC)
    definition = CompletionDefinition(
        obvious=False,
        conditions=[
            CompletionCondition(
                id="CC-1",
                text="Review passed",
                met_at=now,
                evidence="REF-1",
            )
        ],
    )

    assert definition.conditions[0].evidence == "REF-1"


def test_personal_priority_is_expressed_as_decision_facets() -> None:
    task = Task(
        id="TASK-PRIORITY-1",
        title="Restore the production service",
        urgency=Urgency.CRITICAL,
        impact=Impact.HIGH,
        commitment=Commitment.COMMITTED,
    )

    assert task.urgency is Urgency.CRITICAL
    assert task.impact is Impact.HIGH
    assert task.commitment is Commitment.COMMITTED
    assert "priority" not in task.persistent_dict()


def test_parent_hierarchy_rejects_a_cycle(service: GtdService) -> None:
    parent_id = service.add_next_action("Prepare the review").created[0].id
    child_id = service.add_next_action("Sanitize the diagram").created[0].id

    child = service.set_task_parent(child_id, parent_id)
    assert child.parent_id == parent_id

    with pytest.raises(InvalidTransitionError, match="parent cycle"):
        service.set_task_parent(parent_id, child_id)


def test_depends_on_relation_is_the_inverse_dependency_spelling(
    service: GtdService,
) -> None:
    predecessor_id = service.add_next_action("Obtain the data").created[0].id
    successor_id = service.add_next_action("Make the decision").created[0].id
    service.link_tasks(successor_id, predecessor_id, relation_type="depends_on")

    with pytest.raises(InvalidTransitionError, match="blocked by"):
        service.start_task(successor_id)

    service.complete_task(predecessor_id)
    assert service.start_task(successor_id).status is TaskStatus.DOING


def test_work_log_preserves_original_and_updates_remaining_estimate(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Analyze the trace",
            estimate_minutes=60,
        )
        .created[0]
        .id
    )

    logged = service.log_work(task_id, minutes=15, note="First trace pass")
    adjusted = service.set_remaining_estimate(
        task_id,
        minutes=30,
        reason="A second environment must be checked",
    )

    assert logged.original_estimate_minutes == 60
    assert logged.remaining_estimate_minutes == 45
    assert logged.actual_minutes == 15
    assert logged.work_logs[0].minutes == 15
    assert logged.work_logs[0].note == "First trace pass"
    assert adjusted.original_estimate_minutes == 60
    assert adjusted.remaining_estimate_minutes == 30

    with pytest.raises(InvalidTransitionError, match="original.*immutable"):
        service.define_task(task_id, original_estimate_minutes=90)

    with pytest.raises(InvalidTransitionError, match="with a reason"):
        service.define_task(task_id, remaining_estimate_minutes=20)


def test_fractional_work_logs_are_not_lost_to_rounding(service: GtdService) -> None:
    task_id = (
        service.add_next_action(
            "Inspect ten small findings",
            estimate_minutes=10,
        )
        .created[0]
        .id
    )

    for _ in range(10):
        task = service.log_work(task_id, minutes=0.4)

    assert task.actual_minutes == 4
    assert task.remaining_estimate_minutes == 6


def test_work_log_rejects_an_inverted_timer_range() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="cannot precede"):
        WorkLog(
            id="WL-1",
            minutes=5,
            started_at=now.replace(tzinfo=None),
            stopped_at=now - timedelta(minutes=5),
        )


def test_focus_uses_remaining_work_instead_of_the_original_estimate(
    service: GtdService,
) -> None:
    task_id = (
        service.add_next_action(
            "Finish the investigation",
            estimate_minutes=60,
        )
        .created[0]
        .id
    )
    service.set_remaining_estimate(task_id, minutes=10, reason="Most analysis is complete")

    assert [task.id for task in service.focus(available_minutes=15)] == [task_id]


def test_completion_creates_a_new_recurring_occurrence(service: GtdService) -> None:
    task_id = service.add_next_action("Run the fortnightly access review").created[0].id
    recurring = service.set_recurrence(
        task_id,
        frequency="weekly",
        interval=2,
        anchor_on=date(2026, 7, 23),
    )

    result = service.complete_task(task_id)

    assert recurring.recurrence is not None
    assert recurring.recurrence.frequency is RecurrenceFrequency.WEEKLY
    assert recurring.next_occurrence_on == date(2026, 8, 6)
    assert result.next_occurrence is not None
    assert result.next_occurrence.id != task_id
    assert result.next_occurrence.occurrence_on == date(2026, 8, 6)
    assert result.next_occurrence.status is TaskStatus.NEXT


def test_recurring_occurrence_does_not_copy_notes_or_result_evidence(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = service.add_next_action("Run the access review").created[0].id
    service.set_recurrence(
        task_id,
        frequency="monthly",
        anchor_on=date(2026, 7, 23),
    )
    record = workspace.find_record(task_id, kinds={"task"})
    workspace.write(
        record.entity,
        record.body.replace("## Notes", "## Notes\n\nOld private note").replace(
            "## Result / Evidence",
            "## Result / Evidence\n\nOld evidence",
        ),
    )

    result = service.complete_task(task_id)
    assert result.next_occurrence is not None
    next_record = workspace.find_record(result.next_occurrence.id, kinds={"task"})

    assert "Old private note" not in next_record.body
    assert "Old evidence" not in next_record.body
    assert "Run the access review" in next_record.body


def test_retry_repairs_a_missing_recurring_successor_after_partial_failure(
    service: GtdService,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = service.add_next_action("Run the recoverable review").created[0].id
    service.set_recurrence(
        task_id,
        frequency="weekly",
        anchor_on=date(2026, 7, 23),
    )
    original_write = workspace.write

    def fail_successor(entity: object, body: str):
        if (
            isinstance(entity, Task)
            and entity.id != task_id
            and entity.recurrence_series_id == task_id
        ):
            raise OSError("simulated successor write failure")
        return original_write(entity, body)

    monkeypatch.setattr(workspace, "write", fail_successor)
    with pytest.raises(OSError, match="successor write failure"):
        service.complete_task(task_id)
    monkeypatch.setattr(workspace, "write", original_write)

    repaired = service.complete_task(task_id)

    assert repaired.task.status is TaskStatus.DONE
    assert repaired.next_occurrence is not None
    assert repaired.next_occurrence.occurrence_on == date(2026, 7, 30)
    successors = [
        task
        for task in service.list_tasks()
        if task.recurrence_series_id == task_id and task.id != task_id
    ]
    assert [task.id for task in successors] == [repaired.next_occurrence.id]


def test_resolving_a_blocker_does_not_destroy_waiting_context(
    service: GtdService,
) -> None:
    item = service.capture("Receive the signed review record")
    task_id = (
        service.clarify(
            item.id,
            "waiting",
            waiting_for="Reviewer",
            follow_up_on="2026-07-30",
        )
        .created[0]
        .id
    )
    blocked = service.block_task(task_id, "Reviewer account is disabled")
    assert blocked.status is TaskStatus.BLOCKED

    unblocked = service.ready_task(task_id)

    assert unblocked.status is TaskStatus.WAITING
    assert unblocked.waiting is not None
    assert unblocked.waiting.target == "Reviewer"


def test_weekly_review_preserves_each_attention_facet(service: GtdService) -> None:
    item = service.capture("Receive an external approval")
    task_id = (
        service.clarify(
            item.id,
            "waiting",
            waiting_for="Approver",
        )
        .created[0]
        .id
    )
    service.block_task(task_id, "Approver cannot access the document")

    report = service.weekly_review()

    assert [item.id for item in report.waiting_followups] == [task_id]
    assert [item.id for item in report.blocked] == [task_id]


def test_doctor_reports_missing_parent_and_relation(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = service.add_next_action("Repair direct metadata edits").created[0].id
    record = workspace.find_record(task_id, kinds={"task"})
    task = record.entity
    assert isinstance(task, Task)
    task.parent_id = "TASK-MISSING-PARENT"
    task.relations = [{"type": "depends_on", "target_id": "TASK-MISSING-DEPENDENCY"}]
    workspace.write(task, record.body)

    report = service.validate()

    assert report.valid is False
    assert {issue.code for issue in report.issues} >= {
        "missing_task_parent",
        "missing_task_relation",
    }


def test_manual_work_is_included_in_metrics(service: GtdService) -> None:
    task_id = (
        service.add_next_action(
            "Review a small change",
            estimate_minutes=15,
        )
        .created[0]
        .id
    )
    service.log_work(task_id, minutes=15, note="Review complete")
    service.complete_task(task_id)

    metrics = service.metrics()

    assert metrics.focus_minutes_total == 15
    assert metrics.average_estimate_ratio == 1

    with pytest.raises(InvalidTransitionError, match="completed task"):
        service.set_remaining_estimate(
            task_id,
            minutes=20,
            reason="Invalid post-completion forecast",
        )


def test_metrics_adds_legacy_timer_history_to_new_work_logs(
    service: GtdService,
    workspace: Workspace,
) -> None:
    task_id = service.add_next_action("Continue a migrated task").created[0].id
    workspace.event_store.append(
        Event(
            id="EVT-LEGACY-STOP",
            type=EventType.TASK_STOPPED,
            entity_id=task_id,
            payload={"duration_seconds": 30 * 60},
        )
    )
    service.log_work(task_id, minutes=10)

    assert service.metrics().focus_minutes_total == 40


def test_focus_priority_facets_outrank_a_distant_due_date(service: GtdService) -> None:
    low = (
        service.add_next_action(
            "Low impact future commitment",
            urgency="low",
            impact="low",
            commitment="none",
            due_on="2030-01-01",
        )
        .created[0]
        .id
    )
    critical = (
        service.add_next_action(
            "Restore a critical capability",
            urgency="critical",
            impact="high",
            commitment="committed",
        )
        .created[0]
        .id
    )

    assert [task.id for task in service.focus()] == [critical, low]
