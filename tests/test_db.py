from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from thoughts.db import capture_thought, connect, initialize, open_store, status_summary
from thoughts.models import NewThought
from thoughts.paths import database_path


def test_fresh_database_initializes(tmp_path: Path) -> None:
    db_path = initialize(tmp_path)

    assert db_path == database_path(tmp_path)
    assert db_path.exists()
    assert (tmp_path / "Inbox").is_dir()

    with connect(db_path) as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        assert version == 3


def test_repeated_init_is_idempotent(tmp_path: Path) -> None:
    initialize(tmp_path)
    initialize(tmp_path)

    with connect(database_path(tmp_path)) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert [row["version"] for row in rows] == [1, 2, 3]


def test_foreign_keys_are_enabled(tmp_path: Path) -> None:
    initialize(tmp_path)

    with open_store(tmp_path) as conn:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO thought_tags (thought_id, tag) VALUES (?, ?)",
                ("missing", "orphan"),
            )


def test_invalid_enum_values_are_rejected(tmp_path: Path) -> None:
    initialize(tmp_path)

    with open_store(tmp_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO thoughts ("
                "id, title, body, type, status, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("th_bad", "Bad", "Bad", "invalid", "active", "2026-08-23T00:00:00Z", "x"),
            )


def test_capture_creates_valid_record_and_tags(tmp_path: Path) -> None:
    initialize(tmp_path)

    with open_store(tmp_path) as conn:
        thought = capture_thought(
            conn,
            NewThought(
                body="Buy milk",
                title="Buy milk",
                thought_type="task",
                due_on="2026-08-25",
                priority="medium",
                tags=("Shopping", "#Errands"),
            ),
        )

        assert thought.id.startswith("th_")
        assert thought.thought_type == "task"
        assert thought.status == "active"
        assert thought.tags == ("errands", "shopping")

        summary = status_summary(conn)
        assert summary.total_thoughts == 1
        assert summary.by_type == {"task": 1}
        assert summary.by_status == {"active": 1}


def test_capture_rollback_leaves_no_partial_tag_rows(tmp_path: Path) -> None:
    initialize(tmp_path)

    with open_store(tmp_path) as conn:
        with pytest.raises(ValueError, match="tag must not be blank"):
            capture_thought(
                conn,
                NewThought(
                    body="Rollback this",
                    title="Rollback this",
                    tags=("valid", ""),
                ),
            )

        assert conn.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM thought_tags").fetchone()[0] == 0
