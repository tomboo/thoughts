"""Canonical SQLite store operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from thoughts.ids import new_thought_id
from thoughts.migrations import apply_migrations
from thoughts.models import NewThought, Thought, validate_new_thought
from thoughts.paths import database_path, projection_dirs, runtime_dir


@dataclass(frozen=True)
class StatusSummary:
    """Summary of canonical store and projection state."""

    total_thoughts: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    projection_count: int
    unresolved_sync_issues: int
    remote_capture_requests: int
    latest_migration: int | None


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for canonical-store operations."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def open_store(root: Path) -> Iterator[sqlite3.Connection]:
    """Open the canonical store for an initialized project."""
    db_path = database_path(root)
    if not db_path.exists():
        msg = f"database is not initialized: {db_path}"
        raise FileNotFoundError(msg)
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def initialize(root: Path) -> Path:
    """Initialize the runtime directory, database, and projection folders."""
    runtime_dir(root).mkdir(parents=True, exist_ok=True)
    for directory in projection_dirs(root):
        directory.mkdir(parents=True, exist_ok=True)
    db_path = database_path(root)
    with connect(db_path) as conn:
        apply_migrations(conn)
    return db_path


def capture_thought(conn: sqlite3.Connection, thought: NewThought) -> Thought:
    """Create one canonical thought in a single transaction."""
    with conn:
        thought_id = insert_thought(conn, thought)
    return get_thought(conn, thought_id)


def insert_thought(conn: sqlite3.Connection, thought: NewThought) -> str:
    """Write one thought and its tags without managing a transaction.

    Callers own the surrounding transaction so a thought can be committed
    together with related rows, such as a remote capture request record.
    """
    validate_new_thought(thought)
    thought_id = new_thought_id()
    timestamp_expr = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

    conn.execute(
        "INSERT INTO thoughts ("
        "id, title, body, type, status, created_at, updated_at, due_on, priority, source"
        f") VALUES (?, ?, ?, ?, ?, {timestamp_expr}, {timestamp_expr}, ?, ?, ?)",
        (
            thought_id,
            thought.title.strip(),
            thought.body,
            thought.thought_type,
            thought.status,
            thought.due_on,
            thought.priority,
            thought.source,
        ),
    )
    for tag in thought.tags:
        normalized = normalize_tag(tag)
        conn.execute(
            "INSERT INTO thought_tags (thought_id, tag) VALUES (?, ?)",
            (thought_id, normalized),
        )

    return thought_id


def find_capture_request(conn: sqlite3.Connection, request_id: str) -> str | None:
    """Return the thought id already recorded for a capture request, if any."""
    row = conn.execute(
        "SELECT thought_id FROM capture_requests WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["thought_id"])


def record_capture_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    thought_id: str,
    origin: str,
    submitted_at: str | None,
) -> None:
    """Record that a remote capture request produced a canonical thought."""
    conn.execute(
        "INSERT INTO capture_requests ("
        "request_id, thought_id, origin, submitted_at, received_at"
        ") VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (request_id, thought_id, origin, submitted_at),
    )


def normalize_tag(tag: str) -> str:
    """Normalize a tag for canonical storage."""
    normalized = tag.strip().removeprefix("#").lower()
    if not normalized:
        msg = "tag must not be blank"
        raise ValueError(msg)
    if any(character.isspace() for character in normalized):
        msg = f"tag must not contain whitespace: {tag}"
        raise ValueError(msg)
    return normalized


def get_thought(conn: sqlite3.Connection, thought_id: str) -> Thought:
    """Load a canonical thought with tags."""
    row = conn.execute(
        "SELECT id, title, body, type, status, created_at, updated_at, completed_at, due_on, "
        "priority, source, schema_version FROM thoughts WHERE id = ?",
        (thought_id,),
    ).fetchone()
    if row is None:
        msg = f"unknown thought: {thought_id}"
        raise KeyError(msg)
    tags = tuple(
        str(tag_row["tag"])
        for tag_row in conn.execute(
            "SELECT tag FROM thought_tags WHERE thought_id = ? ORDER BY tag",
            (thought_id,),
        )
    )
    return Thought(
        id=str(row["id"]),
        title=str(row["title"]),
        body=str(row["body"]),
        thought_type=str(row["type"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        completed_at=row["completed_at"],
        due_on=row["due_on"],
        priority=row["priority"],
        source=str(row["source"]),
        schema_version=int(row["schema_version"]),
        tags=tags,
    )


def list_thoughts(conn: sqlite3.Connection) -> list[Thought]:
    """Load all canonical thoughts in deterministic export order."""
    rows = conn.execute("SELECT id FROM thoughts ORDER BY created_at, id").fetchall()
    return [get_thought(conn, str(row["id"])) for row in rows]


def projection_path_for(conn: sqlite3.Connection, thought_id: str) -> Path | None:
    """Return an existing projection path for a thought, if one is recorded."""
    row = conn.execute(
        "SELECT path FROM markdown_projections WHERE thought_id = ?",
        (thought_id,),
    ).fetchone()
    if row is None:
        return None
    return Path(str(row["path"]))


def record_projection(
    conn: sqlite3.Connection,
    *,
    thought_id: str,
    path: Path,
    content_hash: str,
) -> None:
    """Record projection export metadata."""
    conn.execute(
        "INSERT INTO markdown_projections ("
        "thought_id, path, last_exported_at, last_exported_hash, last_seen_hash"
        ") VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?, ?) "
        "ON CONFLICT(thought_id) DO UPDATE SET "
        "path = excluded.path, "
        "last_exported_at = excluded.last_exported_at, "
        "last_exported_hash = excluded.last_exported_hash, "
        "last_seen_hash = excluded.last_seen_hash",
        (thought_id, path.as_posix(), content_hash, content_hash),
    )


def update_thought_from_projection(
    conn: sqlite3.Connection,
    *,
    thought_id: str,
    title: str,
    body: str,
    thought_type: str,
    status: str,
    due_on: str | None,
    priority: str | None,
    tags: tuple[str, ...],
) -> None:
    """Update user-editable canonical fields from a validated Markdown projection."""
    conn.execute(
        "UPDATE thoughts SET "
        "title = ?, body = ?, type = ?, status = ?, due_on = ?, priority = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        (title, body, thought_type, status, due_on, priority, thought_id),
    )
    conn.execute("DELETE FROM thought_tags WHERE thought_id = ?", (thought_id,))
    for tag in tags:
        conn.execute(
            "INSERT INTO thought_tags (thought_id, tag) VALUES (?, ?)",
            (thought_id, tag),
        )


def record_sync_issue(
    conn: sqlite3.Connection,
    *,
    thought_id: str | None,
    path: Path | None,
    issue_type: str,
    severity: str,
    message: str,
) -> None:
    """Record one unresolved sync issue."""
    conn.execute(
        "INSERT INTO sync_issues ("
        "thought_id, path, issue_type, severity, message, detected_at"
        ") VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (
            thought_id,
            None if path is None else path.as_posix(),
            issue_type,
            severity,
            message,
        ),
    )


def status_summary(conn: sqlite3.Connection) -> StatusSummary:
    """Compute database and projection health counts."""
    total_thoughts = int(conn.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0])
    by_type = count_by(conn, "type")
    by_status = count_by(conn, "status")
    projection_count = int(conn.execute("SELECT COUNT(*) FROM markdown_projections").fetchone()[0])
    unresolved_sync_issues = int(
        conn.execute("SELECT COUNT(*) FROM sync_issues WHERE resolved_at IS NULL").fetchone()[0]
    )
    remote_capture_requests = int(
        conn.execute("SELECT COUNT(*) FROM capture_requests").fetchone()[0]
    )
    latest_migration_row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    latest_migration = latest_migration_row[0] if latest_migration_row is not None else None
    return StatusSummary(
        total_thoughts=total_thoughts,
        by_type=by_type,
        by_status=by_status,
        projection_count=projection_count,
        unresolved_sync_issues=unresolved_sync_issues,
        remote_capture_requests=remote_capture_requests,
        latest_migration=latest_migration,
    )


def count_by(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    """Return counts grouped by a controlled thoughts column."""
    if column not in {"type", "status"}:
        msg = f"unsupported count column: {column}"
        raise ValueError(msg)
    return {
        str(row[column]): int(row["count"])
        for row in conn.execute(
            f"SELECT {column}, COUNT(*) AS count FROM thoughts GROUP BY {column} ORDER BY {column}"
        )
    }
