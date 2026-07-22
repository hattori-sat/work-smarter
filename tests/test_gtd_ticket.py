from __future__ import annotations

from datetime import UTC, datetime

import pytest

from work_smarter.errors import InvalidTransitionError
from work_smarter.gtd.models import (
    CompletionCondition,
    CompletionDefinition,
    Task,
    TaskRigor,
    TaskStatus,
    WorkType,
)
from work_smarter.gtd.service import GtdService
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

    assert task.schema_version == 2
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


def test_v1_task_is_lazily_migrated_and_next_write_is_v2(
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
            "completion_criteria": ["Alice has replied"],
            "tags": [],
        },
        "Legacy body",
    )

    record = workspace.read(path, expected_kind="task")
    task = record.entity
    assert isinstance(task, Task)
    assert task.schema_version == 2
    assert task.status is TaskStatus.WAITING
    assert task.waiting is not None
    assert task.waiting.target == "Alice"
    assert task.original_estimate_minutes == 25
    assert [condition.text for condition in task.completion.conditions] == ["Alice has replied"]

    workspace.write(task, record.body)
    metadata = read_markdown(path).metadata
    assert metadata["schema_version"] == 2
    assert "status" not in metadata
    assert metadata["execution"]["state"] == "idle"


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

    completed = service.complete_task(task_id)
    assert completed.task.status is TaskStatus.DONE


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
