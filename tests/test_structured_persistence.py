from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from work_smarter.composition import initialize_workspace, open_workspace
from work_smarter.gtd.models import TaskStatus
from work_smarter.gtd.persistence import GTD_ENTITY_REGISTRY
from work_smarter.gtd.service import GtdService
from work_smarter.shared.outbox import OutboxWorker
from work_smarter.shared.persistence.database import StructuredStateBackend
from work_smarter.shared.persistence.sqlite import SQLiteDatabaseBackend
from work_smarter.storage.frontmatter import read_markdown, write_markdown
from work_smarter.storage.workspace import Workspace


def test_legacy_frontmatter_is_imported_once_and_then_becomes_a_projection(
    tmp_path: Path,
) -> None:
    legacy = Workspace.initialize(tmp_path, GTD_ENTITY_REGISTRY)
    legacy_service = GtdService(legacy)
    captured = legacy_service.capture("Original database-owned title")

    migrated = open_workspace(tmp_path)
    assert migrated.structured_store is not None
    assert GtdService(migrated).list_inbox()[0].title == "Original database-owned title"

    path = tmp_path / "inbox" / f"{captured.id}.md"
    document = read_markdown(path)
    edited = dict(document.metadata)
    edited["title"] = "Untrusted frontmatter edit"
    write_markdown(path, edited, "Narrative remains editable.\n")

    reopened = open_workspace(tmp_path)
    record = reopened.find_record(captured.id, kinds={"inbox"})
    assert record.entity.title == "Original database-owned title"
    assert record.body == "Narrative remains editable.\n"

    stray = dict(document.metadata)
    stray["id"] = "IN-STRAY"
    stray["title"] = "Must not be imported after cutover"
    write_markdown(tmp_path / "inbox" / "IN-STRAY.md", stray, "Unregistered narrative")
    (tmp_path / ".work-smarter" / "events.ndjson").write_text(
        "broken compatibility projection\n",
        encoding="utf-8",
    )

    authoritative = open_workspace(tmp_path)
    assert [item.id for item in GtdService(authoritative).list_inbox()] == [captured.id]


def test_pending_write_is_recovered_after_process_style_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path)
    store = workspace.structured_store
    assert store is not None

    def crash_after_projection(_operation_id: str) -> None:
        raise SystemExit("simulated process crash")

    monkeypatch.setattr(store, "commit_entity_write", crash_after_projection)
    with pytest.raises(SystemExit, match="simulated process crash"):
        GtdService(workspace).capture("Recover my durable intent")

    assert len(store.pending_operations()) == 1
    reopened = open_workspace(tmp_path)

    assert [item.title for item in GtdService(reopened).list_inbox()] == [
        "Recover my durable intent"
    ]
    assert reopened.structured_store is not None
    assert reopened.structured_store.list_operations()[0].status == "completed"


def test_normal_write_failure_is_refused_instead_of_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path)
    store = workspace.structured_store
    assert store is not None

    def refuse_commit(_operation_id: str) -> None:
        raise RuntimeError("commit refused")

    monkeypatch.setattr(store, "commit_entity_write", refuse_commit)
    with pytest.raises(RuntimeError, match="commit refused"):
        GtdService(workspace).capture("Must not become state")

    reopened = open_workspace(tmp_path)
    assert GtdService(reopened).list_inbox() == []
    assert reopened.structured_store is not None
    assert reopened.structured_store.list_operations()[0].status == "failed"


class _RecordingDestination:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.operations: list[str] = []

    def deliver(self, message) -> None:  # type: ignore[no-untyped-def]
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary provider failure")
        self.operations.append(message.operation_id)


def test_outbox_worker_retries_and_completes_idempotently(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path)
    backend = SQLiteDatabaseBackend.for_path(workspace.root / ".work-smarter" / "work-smarter.db")
    assert isinstance(backend, StructuredStateBackend)
    store = backend.structured_store
    start = datetime(2026, 8, 3, tzinfo=UTC)
    first = store.enqueue_outbox(
        message_id="MSG-1",
        operation_id="SYNC-1",
        destination="fake",
        message_type="note.push",
        payload={"id": "NOTE-1"},
        available_at=start.isoformat(),
    )
    duplicate = store.enqueue_outbox(
        message_id="MSG-DUPLICATE",
        operation_id="SYNC-1",
        destination="fake",
        message_type="note.push",
        payload={"id": "NOTE-1"},
        available_at=start.isoformat(),
    )
    assert duplicate.id == first.id

    destination = _RecordingDestination(fail_once=True)
    worker = OutboxWorker(store, {"fake": destination})
    failed = worker.run_once(now=start)
    completed = worker.run_once(now=start + timedelta(minutes=2))

    assert failed.model_dump() == {
        "claimed": 1,
        "completed": 0,
        "failed": 1,
        "unavailable": 0,
    }
    assert completed.completed == 1
    assert destination.operations == ["SYNC-1"]
    assert store.list_outbox()[0].status == "completed"


def test_concurrent_outbox_workers_never_share_a_lease(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path)
    store = workspace.structured_store
    assert store is not None
    now = datetime(2026, 8, 3, tzinfo=UTC).isoformat()
    for index in range(8):
        store.enqueue_outbox(
            message_id=f"MSG-{index}",
            operation_id=f"OP-SYNC-{index}",
            destination="fake",
            message_type="entity.changed",
            payload={"index": index},
            available_at=now,
        )

    def claim(worker: int) -> set[str]:
        backend = SQLiteDatabaseBackend.for_path(
            workspace.root / ".work-smarter" / "work-smarter.db"
        )
        return {
            message.id
            for message in backend.structured_store.claim_outbox(
                lease_token=f"WORKER-{worker}",
                now=now,
                limit=4,
            )
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(claim, (1, 2)))

    assert len(leases[0]) == 4
    assert len(leases[1]) == 4
    assert leases[0].isdisjoint(leases[1])


def test_structured_task_state_survives_persistence_reload(tmp_path: Path) -> None:
    service = GtdService(initialize_workspace(tmp_path))
    task = service.add_next_action("Database task").created[0]
    service.start_task(task.id)

    reopened = GtdService(open_workspace(tmp_path))
    assert [item.id for item in reopened.list_tasks({TaskStatus.DOING})] == [task.id]


def test_database_event_history_survives_a_corrupt_jsonl_projection(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path)
    GtdService(workspace).capture("Database event authority")
    expected_ids = [event.id for event in workspace.event_store.read_all()]
    (workspace.state_dir / "events.ndjson").write_text("not-json\n", encoding="utf-8")

    reopened = open_workspace(tmp_path)
    assert [event.id for event in reopened.event_store.read_all()] == expected_ids
