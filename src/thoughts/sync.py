"""Markdown projection sync validation and import."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from thoughts.db import (
    get_thought,
    normalize_tag,
    record_projection,
    record_sync_issue,
    update_thought_from_projection,
)
from thoughts.markdown import (
    MarkdownParseError,
    parse_projection,
    projection_hash,
    render_projection,
)
from thoughts.models import VALID_PRIORITIES, VALID_STATUSES, VALID_TYPES
from thoughts.paths import projection_dirs


@dataclass(frozen=True)
class SyncIssue:
    """A validation or consistency issue found during sync."""

    thought_id: str | None
    relative_path: Path | None
    issue_type: str
    severity: str
    message: str


@dataclass(frozen=True)
class ProjectionUpdate:
    """Validated Markdown edits ready to import."""

    thought_id: str
    relative_path: Path
    title: str
    body: str
    thought_type: str
    status: str
    due_on: str | None
    priority: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SyncResult:
    """Result of sync validation or apply."""

    updates: tuple[ProjectionUpdate, ...]
    issues: tuple[SyncIssue, ...]
    applied_count: int = 0

    @property
    def has_errors(self) -> bool:
        """Return whether any issue blocks apply."""
        return any(issue.severity == "error" for issue in self.issues)


def check_sync(conn: sqlite3.Connection, root: Path) -> SyncResult:
    """Validate projected Markdown files without mutating canonical state."""
    projection_files = list_projection_files(root)
    issues: list[SyncIssue] = []
    updates: list[ProjectionUpdate] = []
    seen_ids: dict[str, Path] = {}

    for relative_path in projection_files:
        absolute_path = root / relative_path
        content = absolute_path.read_text(encoding="utf-8")
        try:
            parsed = parse_projection(content)
        except MarkdownParseError as error:
            issues.append(
                SyncIssue(
                    thought_id=None,
                    relative_path=relative_path,
                    issue_type="invalid_frontmatter",
                    severity="error",
                    message=str(error),
                )
            )
            continue

        raw_id = parsed.frontmatter.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            issues.append(
                SyncIssue(
                    thought_id=None,
                    relative_path=relative_path,
                    issue_type="missing_id",
                    severity="error",
                    message="projection is missing a non-empty id",
                )
            )
            continue
        thought_id = raw_id.strip()

        previous_path = seen_ids.get(thought_id)
        if previous_path is not None:
            message = f"duplicate id {thought_id} also appears in {previous_path.as_posix()}"
            issues.append(
                SyncIssue(thought_id, relative_path, "duplicate_id", "error", message)
            )
            issues.append(
                SyncIssue(thought_id, previous_path, "duplicate_id", "error", message)
            )
            continue
        seen_ids[thought_id] = relative_path

        try:
            update = validate_projection_update(
                conn,
                relative_path,
                parsed.frontmatter,
                parsed.body,
            )
        except ValueError as error:
            issues.append(
                SyncIssue(
                    thought_id=thought_id,
                    relative_path=relative_path,
                    issue_type="validation_error",
                    severity="error",
                    message=str(error),
                )
            )
            continue

        projection_row = conn.execute(
            "SELECT last_exported_hash FROM markdown_projections WHERE thought_id = ?",
            (thought_id,),
        ).fetchone()
        current_hash = projection_hash(content)
        if projection_row is not None and current_hash != projection_row["last_exported_hash"]:
            updates.append(update)

    issues.extend(deleted_projection_issues(conn, root))
    return SyncResult(updates=tuple(updates), issues=tuple(issues))


def apply_sync(conn: sqlite3.Connection, root: Path) -> SyncResult:
    """Import valid Markdown edits into SQLite and re-export normalized projections.

    Apply is all-or-nothing per run for canonical thought updates. If any validation error is
    present, no thoughts are updated; blocking issues are recorded in ``sync_issues`` instead.
    """
    result = check_sync(conn, root)
    if result.has_errors:
        with conn:
            for issue in result.issues:
                if issue.severity == "error":
                    record_sync_issue_from_result(conn, issue)
        return result

    with conn:
        for update in result.updates:
            update_thought_from_projection(
                conn,
                thought_id=update.thought_id,
                title=update.title,
                body=update.body,
                thought_type=update.thought_type,
                status=update.status,
                due_on=update.due_on,
                priority=update.priority,
                tags=update.tags,
            )
            re_export_update(conn, root, update)
        for issue in result.issues:
            record_sync_issue_from_result(conn, issue)

    return SyncResult(
        updates=result.updates,
        issues=result.issues,
        applied_count=len(result.updates),
    )


def validate_projection_update(
    conn: sqlite3.Connection,
    relative_path: Path,
    frontmatter: dict[str, Any],
    body: str,
) -> ProjectionUpdate:
    """Validate user-editable fields from one parsed Markdown projection."""
    thought_id = require_string(frontmatter, "id")
    try:
        get_thought(conn, thought_id)
    except KeyError as error:
        msg = f"unknown thought id: {thought_id}"
        raise ValueError(msg) from error

    title = require_string(frontmatter, "title").strip()
    if not title:
        msg = "title must not be blank"
        raise ValueError(msg)

    thought_type = require_string(frontmatter, "type")
    if thought_type not in VALID_TYPES:
        msg = f"invalid type: {thought_type}"
        raise ValueError(msg)

    status = require_string(frontmatter, "status")
    if status not in VALID_STATUSES:
        msg = f"invalid status: {status}"
        raise ValueError(msg)

    due_on = nullable_string(frontmatter.get("due"), "due")
    if due_on is not None:
        try:
            date.fromisoformat(due_on)
        except ValueError as error:
            msg = f"malformed due date: {due_on}"
            raise ValueError(msg) from error

    priority = nullable_string(frontmatter.get("priority"), "priority")
    if priority is not None and priority not in VALID_PRIORITIES:
        msg = f"invalid priority: {priority}"
        raise ValueError(msg)

    tags = normalize_tags(frontmatter.get("tags", []))
    normalized_body = body.rstrip() + "\n" if body.strip() else ""
    return ProjectionUpdate(
        thought_id=thought_id,
        relative_path=relative_path,
        title=title,
        body=normalized_body,
        thought_type=thought_type,
        status=status,
        due_on=due_on,
        priority=priority,
        tags=tags,
    )


def list_projection_files(root: Path) -> list[Path]:
    """List Markdown projection files under known projection directories."""
    files: list[Path] = []
    for directory in projection_dirs(root):
        if not directory.exists():
            continue
        files.extend(
            path.relative_to(root)
            for path in directory.rglob("*.md")
            if path.is_file() and not path.name.startswith(".")
        )
    return sorted(files, key=lambda path: path.as_posix())


def deleted_projection_issues(conn: sqlite3.Connection, root: Path) -> list[SyncIssue]:
    """Report deleted Markdown projections without deleting canonical rows."""
    issues: list[SyncIssue] = []
    rows = conn.execute(
        "SELECT thought_id, path FROM markdown_projections ORDER BY path"
    ).fetchall()
    for row in rows:
        relative_path = Path(str(row["path"]))
        if (root / relative_path).exists():
            continue
        issues.append(
            SyncIssue(
                thought_id=str(row["thought_id"]),
                relative_path=relative_path,
                issue_type="projection_deleted",
                severity="warning",
                message="projection file is missing; canonical thought was not deleted",
            )
        )
    return issues


def require_string(frontmatter: dict[str, Any], field_name: str) -> str:
    """Read a required string frontmatter field."""
    value = frontmatter.get(field_name)
    if not isinstance(value, str):
        msg = f"{field_name} must be a string"
        raise ValueError(msg)
    return value


def nullable_string(value: object, field_name: str) -> str | None:
    """Read a nullable string frontmatter field."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null"
        raise ValueError(msg)
    return value


def normalize_tags(value: object) -> tuple[str, ...]:
    """Validate and normalize frontmatter tags."""
    if value is None:
        return ()
    if not isinstance(value, list):
        msg = "tags must be a list"
        raise ValueError(msg)
    normalized = []
    for tag in value:
        if not isinstance(tag, str):
            msg = "tags must contain only strings"
            raise ValueError(msg)
        normalized.append(normalize_tag(tag))
    return tuple(sorted(set(normalized)))


def record_sync_issue_from_result(conn: sqlite3.Connection, issue: SyncIssue) -> None:
    """Persist a sync issue."""
    record_sync_issue(
        conn,
        thought_id=issue.thought_id,
        path=issue.relative_path,
        issue_type=issue.issue_type,
        severity=issue.severity,
        message=issue.message,
    )


def re_export_update(conn: sqlite3.Connection, root: Path, update: ProjectionUpdate) -> None:
    """Re-render an accepted projection edit and update projection metadata."""
    thought = get_thought(conn, update.thought_id)
    rendered = render_projection(thought, update.relative_path)
    absolute_path = root / rendered.relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_text(rendered.content, encoding="utf-8")
    record_projection(
        conn,
        thought_id=thought.id,
        path=rendered.relative_path,
        content_hash=rendered.content_hash,
    )
