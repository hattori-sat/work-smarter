from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from work_smarter.errors import (
    AmbiguousEntityError,
    EntityNotFoundError,
    InvalidDocumentError,
    InvalidTransitionError,
    WipLimitError,
)
from work_smarter.gtd.events import EventType
from work_smarter.gtd.models import (
    ClarifyDecision,
    Energy,
    InboxItem,
    Reference,
    Task,
    TaskStatus,
)
from work_smarter.gtd.persistence import open_workspace
from work_smarter.gtd.service import GtdService
from work_smarter.storage.workspace import Workspace


def make_next_action(
    service: GtdService,
    title: str,
    **fields: object,
) -> Task:
    item = service.capture(title)
    result = service.clarify(item.id, ClarifyDecision.NEXT, **fields)
    task_id = result.created[0].id
    return next(task for task in service.list_tasks() if task.id == task_id)


def test_capture_and_clarify_next_action_without_manual_file_moves(
    service: GtdService,
    workspace: Workspace,
) -> None:
    item = service.capture(
        "Reply to design review\nInclude the benchmark.",
        source="cli",
        tags=["Work", "work"],
    )

    result = service.clarify(
        item.id[:12],
        ClarifyDecision.NEXT,
        contexts=["@Laptop"],
        energy=Energy.MEDIUM,
        estimate_minutes=20,
        completion_criteria=["Reply sent"],
    )

    assert service.list_inbox() == []
    assert result.source_id == item.id
    assert result.decision is ClarifyDecision.NEXT
    assert len(result.created) == 1
    task = service.list_tasks()[0]
    assert task.source_inbox_id == item.id
    assert task.contexts == ["@laptop"]
    assert task.tags == ["work"]
    assert task.estimate_minutes == 20
    assert task.completion_criteria == ["Reply sent"]
    assert (workspace.root / result.created[0].path).is_file()
    assert (workspace.root / result.archived_path).is_file()
    assert not (workspace.root / "inbox" / f"{item.id}.md").exists()
    assert [event.type for event in workspace.event_store.read_all()] == [
        EventType.CAPTURED,
        EventType.CLARIFIED,
    ]


def test_omitting_inbox_id_processes_oldest_item(service: GtdService) -> None:
    first = service.capture("First thought")
    second = service.capture("Second thought")

    result = service.clarify(None, ClarifyDecision.REFERENCE)

    assert result.source_id == first.id
    assert [item.id for item in service.list_inbox()] == [second.id]


def test_quick_add_creates_a_task_without_leaving_inbox_clerical_work(
    service: GtdService,
) -> None:
    result = service.add_next_action(
        "Run the smoke test",
        contexts=["@computer"],
        estimate_minutes=10,
    )

    assert service.list_inbox() == []
    assert [ref.kind for ref in result.created] == ["task"]
    task = service.list_tasks()[0]
    assert task.contexts == ["@computer"]
    assert task.source_inbox_id == result.source_id


def test_workspace_task_template_is_created_and_user_overridable(
    service: GtdService,
    workspace: Workspace,
) -> None:
    template = workspace.root / "templates" / "gtd" / "task.md"
    assert template.is_file()
    template.write_text("# ACTION\n\n{{ intent }}\n", encoding="utf-8")

    result = service.add_next_action("Use my template")
    record = workspace.find_record(result.created[0].id, kinds={"task"})

    assert record.body == "# ACTION\n\nUse my template\n"


def test_project_creation_requires_outcome_and_first_action(service: GtdService) -> None:
    item = service.capture("Launch the internal tool")

    with pytest.raises(InvalidTransitionError, match="outcome and first_action"):
        service.clarify(item.id, ClarifyDecision.PROJECT, outcome="Team can use it")

    assert [inbox_item.id for inbox_item in service.list_inbox()] == [item.id]


def test_project_first_action_completion_surfaces_missing_next_action(
    service: GtdService,
) -> None:
    item = service.capture("Launch the internal tool")
    result = service.clarify(
        item.id,
        ClarifyDecision.PROJECT,
        outcome="The team can use the tool",
        first_action="Write the problem statement",
    )
    project_id = next(ref.id for ref in result.created if ref.kind == "gtd_project")
    task_id = next(ref.id for ref in result.created if ref.kind == "task")

    service.start_task(task_id)
    completion = service.complete_task(task_id)

    assert completion.task.status is TaskStatus.DONE
    assert completion.task.started_at is None
    assert completion.project_id == project_id
    assert completion.project_attention_required is True
    review = service.weekly_review()
    assert [project.id for project in review.projects_without_next_action] == [project_id]

    completed_project = service.complete_project(project_id[:14])
    assert completed_project.status.value == "done"
    assert service.weekly_review().projects_without_next_action == []


def test_project_cannot_complete_while_an_action_is_open(service: GtdService) -> None:
    item = service.capture("Ship a feature")
    result = service.clarify(
        item.id,
        ClarifyDecision.PROJECT,
        outcome="Feature is in production",
        first_action="Write the test",
    )
    project_id = next(ref.id for ref in result.created if ref.kind == "gtd_project")

    with pytest.raises(InvalidTransitionError, match="still has open actions"):
        service.complete_project(project_id)


def test_one_piece_flow_requires_explicit_switch(service: GtdService) -> None:
    first = make_next_action(service, "Investigate failure")
    second = make_next_action(service, "Write incident summary")

    service.start_task(first.id)
    with pytest.raises(WipLimitError, match="already doing"):
        service.start_task(second.id)

    switched = service.start_task(second.id, switch=True)

    tasks = {task.id: task for task in service.list_tasks()}
    assert tasks[first.id].status is TaskStatus.NEXT
    assert switched.status is TaskStatus.DOING
    assert service.current_task().id == second.id  # type: ignore[union-attr]


def test_status_shows_the_whole_system_and_ready_actions(service: GtdService) -> None:
    service.capture("Still in inbox")
    ready = make_next_action(service, "Ready to execute")

    report = service.status()

    assert report.inbox_count == 1
    assert report.tasks_by_status["next"] == 1
    assert report.tasks_by_status["doing"] == 0
    assert [action.id for action in report.ready_actions] == [ready.id]


def test_focus_filters_by_context_time_and_available_energy(service: GtdService) -> None:
    easy = make_next_action(
        service,
        "Send status message",
        contexts=["@computer"],
        estimate_minutes=10,
        energy=Energy.LOW,
    )
    make_next_action(
        service,
        "Deep architecture review",
        contexts=["@computer"],
        estimate_minutes=90,
        energy=Energy.HIGH,
    )
    make_next_action(
        service,
        "Buy a cable",
        contexts=["@errands"],
        estimate_minutes=10,
        energy=Energy.LOW,
    )

    focused = service.focus(
        contexts=["@computer"],
        available_minutes=20,
        energy=Energy.LOW,
    )

    assert [task.id for task in focused] == [easy.id]


def test_context_filter_excludes_actions_without_a_matching_context(
    service: GtdService,
) -> None:
    make_next_action(service, "No context yet")

    assert service.focus(contexts=["@office"]) == []


@pytest.mark.parametrize(
    ("decision", "fields"),
    [
        (ClarifyDecision.WAITING, {"waiting_for": "Alice"}),
        (ClarifyDecision.SCHEDULED, {"scheduled_for": "2030-01-01T09:00:00Z"}),
    ],
)
def test_unavailable_task_can_be_returned_to_ready(
    service: GtdService,
    decision: ClarifyDecision,
    fields: dict[str, object],
) -> None:
    item = service.capture(f"Temporarily {decision.value}")
    result = service.clarify(item.id, decision, **fields)

    task = service.ready_task(result.created[0].id)

    assert task.status is TaskStatus.NEXT
    assert task.waiting_for is None
    assert task.scheduled_for is None


def test_clarify_refuses_a_missing_project_relation(service: GtdService) -> None:
    item = service.capture("Action for a missing project")

    with pytest.raises(EntityNotFoundError, match="No entity matches"):
        service.clarify(
            item.id,
            ClarifyDecision.NEXT,
            project_id="PRJ-MISSING",
        )

    assert [remaining.id for remaining in service.list_inbox()] == [item.id]


@pytest.mark.parametrize(
    ("decision", "fields", "expected_kind"),
    [
        (ClarifyDecision.WAITING, {"waiting_for": "Alice"}, "task"),
        (
            ClarifyDecision.SCHEDULED,
            {"scheduled_for": "2030-01-02T09:00:00+09:00"},
            "task",
        ),
        (ClarifyDecision.SOMEDAY, {}, "someday"),
        (ClarifyDecision.REFERENCE, {}, "reference"),
        (ClarifyDecision.DONE, {}, "task"),
        (ClarifyDecision.TRASH, {}, None),
    ],
)
def test_all_clarify_dispositions_archive_the_inbox_item(
    service: GtdService,
    decision: ClarifyDecision,
    fields: dict[str, object],
    expected_kind: str | None,
) -> None:
    item = service.capture(f"Handle as {decision.value}")

    result = service.clarify(item.id, decision, **fields)

    assert service.list_inbox() == []
    assert [ref.kind for ref in result.created] == (
        [expected_kind] if expected_kind is not None else []
    )


def test_weekly_review_validation_and_metrics(
    service: GtdService,
    workspace: Workspace,
) -> None:
    service.capture("Unprocessed thought")
    waiting_item = service.capture("Wait for vendor")
    service.clarify(
        waiting_item.id,
        ClarifyDecision.WAITING,
        waiting_for="Vendor",
    )
    task = make_next_action(service, "Implement parser", estimate_minutes=30)
    service.start_task(task.id)
    doing_record = workspace.find_record(task.id, kinds={"task"})
    doing = doing_record.entity
    assert isinstance(doing, Task)
    doing.started_at = datetime.now(UTC) - timedelta(minutes=30)
    doing.created_at = datetime.now(UTC) - timedelta(hours=2)
    workspace.write(doing, doing_record.body)
    completion = service.complete_task(task.id)
    assert completion.task.actual_minutes == 30

    report = service.weekly_review()
    metrics = service.metrics()
    validation = service.validate()

    assert len(report.inbox) == 1
    assert len(report.waiting_followups) == 1
    assert metrics.completed_total == 1
    assert metrics.completed_last_7_days == 1
    assert metrics.focus_minutes_total == 30
    assert metrics.average_estimate_ratio == 1
    assert validation.valid is True


def test_done_during_clarify_is_present_in_the_audit_log(
    service: GtdService,
    workspace: Workspace,
) -> None:
    item = service.capture("Two-minute reply already sent")
    result = service.clarify(item.id, ClarifyDecision.DONE)

    completed_id = result.created[0].id
    completed_events = [
        event
        for event in workspace.event_store.read_all()
        if event.type == EventType.TASK_COMPLETED
    ]
    assert [event.entity_id for event in completed_events] == [completed_id]


def test_workspace_rejects_path_traversal_ids(workspace: Workspace) -> None:
    malicious = InboxItem(id="../../outside-workspace", title="Escape")

    with pytest.raises(InvalidDocumentError, match="Invalid entity ID"):
        workspace.write(malicious)

    assert not (workspace.root.parent / "outside-workspace.md").exists()


def test_doctor_rejects_a_document_in_the_wrong_kind_directory(
    service: GtdService,
    workspace: Workspace,
) -> None:
    item = service.capture("Create a misplaced project")
    result = service.clarify(
        item.id,
        ClarifyDecision.PROJECT,
        outcome="A valid project exists",
        first_action="Start it",
    )
    project_ref = next(ref for ref in result.created if ref.kind == "gtd_project")
    project_path = workspace.root / project_ref.path
    project_path.rename(workspace.root / "tasks" / project_path.name)

    report = service.validate()

    assert report.valid is False
    assert any(
        issue.code == "invalid_document" and "stored in the 'task' directory" in issue.message
        for issue in report.issues
    )


def test_duplicate_exact_ids_are_never_selected_arbitrarily(workspace: Workspace) -> None:
    duplicate_id = "DUPLICATE-1"
    workspace.write(Task(id=duplicate_id, title="Task"))
    workspace.write(Reference(id=duplicate_id, title="Reference"))

    with pytest.raises(AmbiguousEntityError, match="Duplicate ID"):
        workspace.find_record(duplicate_id)


def test_concurrent_starts_still_enforce_one_piece_flow(
    service: GtdService,
    workspace: Workspace,
) -> None:
    first = make_next_action(service, "Concurrent first")
    second = make_next_action(service, "Concurrent second")

    def start(task_id: str) -> str:
        separate_service = GtdService(open_workspace(workspace.root))
        try:
            separate_service.start_task(task_id)
        except WipLimitError:
            return "rejected"
        return "started"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(start, (first.id, second.id)))

    assert sorted(outcomes) == ["rejected", "started"]
    assert len(service.list_tasks({TaskStatus.DOING})) == 1


def test_doctor_reports_malformed_document(
    service: GtdService,
    workspace: Workspace,
) -> None:
    broken = workspace.root / "tasks" / "broken.md"
    broken.write_text("not frontmatter\n", encoding="utf-8")

    report = service.validate()

    assert report.valid is False
    assert [(issue.code, issue.path) for issue in report.issues] == [
        ("invalid_document", "tasks/broken.md")
    ]
