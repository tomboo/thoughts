"""Markdown projection export."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from thoughts.db import list_thoughts, projection_path_for, record_projection
from thoughts.markdown import projection_hash, render_projection


class ProjectionDriftError(RuntimeError):
    """Raised when export would overwrite externally modified Markdown."""


@dataclass(frozen=True)
class ExportResult:
    """Result of exporting Markdown projections."""

    exported_count: int
    skipped_count: int


@dataclass(frozen=True)
class ExportPlanItem:
    """A projection write that has passed drift checks."""

    thought_id: str
    relative_path: Path
    absolute_path: Path
    content: str
    content_hash: str


def export_markdown(conn: sqlite3.Connection, root: Path) -> ExportResult:
    """Export all canonical thoughts to Markdown projection files."""
    plan = build_export_plan(conn, root)
    with conn:
        for item in plan:
            item.absolute_path.parent.mkdir(parents=True, exist_ok=True)
            item.absolute_path.write_text(item.content, encoding="utf-8")
            record_projection(
                conn,
                thought_id=item.thought_id,
                path=item.relative_path,
                content_hash=item.content_hash,
            )
    return ExportResult(exported_count=len(plan), skipped_count=0)


def build_export_plan(conn: sqlite3.Connection, root: Path) -> list[ExportPlanItem]:
    """Build a complete export plan, refusing all drift before writes begin."""
    plan: list[ExportPlanItem] = []
    for thought in list_thoughts(conn):
        existing_path = projection_path_for(conn, thought.id)
        rendered = render_projection(thought, existing_path)
        absolute_path = root / rendered.relative_path
        if absolute_path.exists():
            current_hash = projection_hash(absolute_path.read_text(encoding="utf-8"))
            row = conn.execute(
                "SELECT last_exported_hash FROM markdown_projections WHERE thought_id = ?",
                (thought.id,),
            ).fetchone()
            if row is None or current_hash != row["last_exported_hash"]:
                msg = f"projection has external changes: {rendered.relative_path}"
                raise ProjectionDriftError(msg)
        plan.append(
            ExportPlanItem(
                thought_id=thought.id,
                relative_path=rendered.relative_path,
                absolute_path=absolute_path,
                content=rendered.content,
                content_hash=rendered.content_hash,
            )
        )
    return plan
