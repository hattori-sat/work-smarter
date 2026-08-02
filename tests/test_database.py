from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from work_smarter.errors import InvalidDocumentError
from work_smarter.shared.persistence.database import DatabaseConfiguration
from work_smarter.shared.persistence.sqlite import LATEST_SCHEMA_VERSION, SQLiteDatabaseBackend


def test_database_migrations_are_idempotent_and_report_the_current_schema(tmp_path: Path) -> None:
    database = SQLiteDatabaseBackend.for_path(tmp_path / "work-smarter.db")

    first = database.migrate()
    second = database.migrate()

    assert first.schema_version == LATEST_SCHEMA_VERSION
    assert first.applied_versions == [1, 2]
    assert second.schema_version == LATEST_SCHEMA_VERSION
    assert second.applied_versions == []
    assert database.status().initialized is True


def test_database_refuses_a_schema_created_by_a_newer_application(tmp_path: Path) -> None:
    path = tmp_path / "work-smarter.db"
    database = SQLiteDatabaseBackend.for_path(path)
    database.migrate()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
            (LATEST_SCHEMA_VERSION + 1, "future"),
        )

    with pytest.raises(InvalidDocumentError, match="newer than this application"):
        database.migrate()


def test_activity_events_are_append_only(tmp_path: Path) -> None:
    database = SQLiteDatabaseBackend.for_path(tmp_path / "work-smarter.db")
    database.migrate()
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO activity_events(
                id, aggregate_type, aggregate_id, event_type, event_version, payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("EVT-1", "gtd_action", "ACT-1", "gtd.action.started", 1, "{}"),
        )

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE activity_events SET event_type = ? WHERE id = ?",
            ("changed", "EVT-1"),
        )

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        database.transaction() as connection,
    ):
        connection.execute("DELETE FROM activity_events WHERE id = ?", ("EVT-1",))


def test_online_snapshot_excludes_an_uncommitted_transaction(tmp_path: Path) -> None:
    database = SQLiteDatabaseBackend.for_path(tmp_path / "work-smarter.db")
    database.migrate()
    snapshot = tmp_path / "snapshot.db"

    with sqlite3.connect(database.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            """
            INSERT INTO activity_events(
                id, aggregate_type, aggregate_id, event_type, event_version, payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("EVT-PENDING", "gtd_action", "ACT-1", "gtd.action.started", 1, "{}"),
        )
        database.snapshot(snapshot)
        writer.rollback()

    with sqlite3.connect(snapshot) as restored:
        event = restored.execute(
            "SELECT id FROM activity_events WHERE id = ?",
            ("EVT-PENDING",),
        ).fetchone()
        integrity = restored.execute("PRAGMA quick_check").fetchone()

    assert event is None
    assert integrity == ("ok",)


def test_sqlite_location_cannot_escape_the_workspace(tmp_path: Path) -> None:
    with pytest.raises(InvalidDocumentError, match="escapes the workspace"):
        SQLiteDatabaseBackend(
            tmp_path / "workspace",
            DatabaseConfiguration(backend="sqlite", location="../outside.db"),
        )
