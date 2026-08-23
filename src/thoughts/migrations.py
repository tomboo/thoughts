"""SQLite migration runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

INITIAL_SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    INITIAL_SCHEMA_VERSION: """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE thoughts (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('inbox', 'task', 'note', 'idea')),
        status TEXT NOT NULL CHECK (
            status IN ('active', 'done', 'archived', 'superseded', 'flagged')
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        due_on TEXT,
        priority TEXT CHECK (priority IN ('low', 'medium', 'high') OR priority IS NULL),
        source TEXT NOT NULL DEFAULT 'cli',
        schema_version INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE thought_tags (
        thought_id TEXT NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
        tag TEXT NOT NULL,
        PRIMARY KEY (thought_id, tag)
    );

    CREATE TABLE markdown_projections (
        thought_id TEXT PRIMARY KEY REFERENCES thoughts(id) ON DELETE CASCADE,
        path TEXT NOT NULL UNIQUE,
        last_exported_at TEXT NOT NULL,
        last_exported_hash TEXT NOT NULL,
        last_seen_hash TEXT
    );

    CREATE TABLE sync_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thought_id TEXT REFERENCES thoughts(id),
        path TEXT,
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
        message TEXT NOT NULL,
        detected_at TEXT NOT NULL,
        resolved_at TEXT
    );
    """,
}


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations."""
    applied = set(applied_versions(conn))
    for version in sorted(MIGRATIONS):
        if version in applied:
            continue
        with conn:
            conn.executescript(MIGRATIONS[version])
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (version,),
            )


def applied_versions(conn: sqlite3.Connection) -> Iterable[int]:
    """Yield already-applied migration versions."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return []
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row["version"]) for row in rows]
