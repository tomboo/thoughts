"""Repository consistency diagnostics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from thoughts.markdown import MarkdownParseError, parse_projection, projection_hash
from thoughts.sync import list_projection_files


@dataclass(frozen=True)
class DoctorIssue:
    """One repository consistency diagnostic."""

    issue_type: str
    severity: str
    message: str
    repair: str
    thought_id: str | None = None
    relative_path: Path | None = None


@dataclass(frozen=True)
class DoctorResult:
    """Complete doctor result."""

    issues: tuple[DoctorIssue, ...]

    @property
    def error_count(self) -> int:
        """Return the number of error diagnostics."""
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        """Return the number of warning diagnostics."""
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def exit_code(self) -> int:
        """Return CLI exit code: 0 clean, 1 warnings, 2 errors."""
        if self.error_count:
            return 2
        if self.warning_count:
            return 1
        return 0


def run_doctor(conn: sqlite3.Connection, root: Path) -> DoctorResult:
    """Run consistency checks across SQLite and Markdown projections."""
    issues: list[DoctorIssue] = []
    issues.extend(missing_projection_row_issues(conn))
    issues.extend(orphaned_projection_row_issues(conn))
    issues.extend(missing_projection_file_issues(conn, root))
    markdown_issues, valid_projection_paths = inspect_markdown_files(root)
    issues.extend(markdown_issues)
    issues.extend(hash_drift_issues(conn, root, valid_projection_paths))
    return DoctorResult(issues=tuple(issues))


def missing_projection_row_issues(conn: sqlite3.Connection) -> list[DoctorIssue]:
    """Find thoughts that have no projection metadata row."""
    rows = conn.execute(
        "SELECT thoughts.id "
        "FROM thoughts "
        "LEFT JOIN markdown_projections ON markdown_projections.thought_id = thoughts.id "
        "WHERE markdown_projections.thought_id IS NULL "
        "ORDER BY thoughts.id"
    ).fetchall()
    return [
        DoctorIssue(
            issue_type="missing_projection_row",
            severity="warning",
            thought_id=str(row["id"]),
            relative_path=None,
            message=f"thought {row['id']} has no Markdown projection row",
            repair="Run `thoughts export-md` to create missing projection metadata and files.",
        )
        for row in rows
    ]


def orphaned_projection_row_issues(conn: sqlite3.Connection) -> list[DoctorIssue]:
    """Find projection rows that do not point at a canonical thought."""
    rows = conn.execute(
        "SELECT markdown_projections.thought_id, markdown_projections.path "
        "FROM markdown_projections "
        "LEFT JOIN thoughts ON thoughts.id = markdown_projections.thought_id "
        "WHERE thoughts.id IS NULL "
        "ORDER BY markdown_projections.path"
    ).fetchall()
    return [
        DoctorIssue(
            issue_type="orphaned_projection_row",
            severity="error",
            thought_id=str(row["thought_id"]),
            relative_path=Path(str(row["path"])),
            message=f"projection row points at missing thought {row['thought_id']}",
            repair="Remove the orphaned projection row after confirming the thought was deleted.",
        )
        for row in rows
    ]


def missing_projection_file_issues(conn: sqlite3.Connection, root: Path) -> list[DoctorIssue]:
    """Find projection rows whose files are missing on disk."""
    rows = conn.execute(
        "SELECT thought_id, path FROM markdown_projections ORDER BY path"
    ).fetchall()
    issues: list[DoctorIssue] = []
    for row in rows:
        relative_path = Path(str(row["path"]))
        if (root / relative_path).exists():
            continue
        issues.append(
            DoctorIssue(
                issue_type="missing_projection_file",
                severity="warning",
                thought_id=str(row["thought_id"]),
                relative_path=relative_path,
                message=f"projection file is missing for thought {row['thought_id']}",
                repair="Run `thoughts export-md` to regenerate the missing projection file.",
            )
        )
    return issues


def inspect_markdown_files(root: Path) -> tuple[list[DoctorIssue], set[Path]]:
    """Parse projection Markdown and find invalid frontmatter and duplicate IDs."""
    issues: list[DoctorIssue] = []
    valid_paths: set[Path] = set()
    seen_ids: dict[str, Path] = {}
    duplicate_pairs: set[tuple[str, Path]] = set()

    for relative_path in list_projection_files(root):
        content = (root / relative_path).read_text(encoding="utf-8")
        try:
            parsed = parse_projection(content)
        except MarkdownParseError as error:
            issues.append(
                DoctorIssue(
                    issue_type="invalid_frontmatter",
                    severity="error",
                    thought_id=None,
                    relative_path=relative_path,
                    message=str(error),
                    repair="Fix the YAML frontmatter, then rerun `thoughts doctor`.",
                )
            )
            continue

        valid_paths.add(relative_path)
        raw_id = parsed.frontmatter.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            issues.append(
                DoctorIssue(
                    issue_type="invalid_frontmatter",
                    severity="error",
                    thought_id=None,
                    relative_path=relative_path,
                    message="projection is missing a non-empty id",
                    repair=(
                        "Restore the stable `id` field from SQLite or regenerate the projection."
                    ),
                )
            )
            continue

        thought_id = raw_id.strip()
        previous_path = seen_ids.get(thought_id)
        if previous_path is not None:
            duplicate_pairs.add((thought_id, previous_path))
            duplicate_pairs.add((thought_id, relative_path))
            continue
        seen_ids[thought_id] = relative_path

    for thought_id, relative_path in sorted(
        duplicate_pairs,
        key=lambda item: (item[0], item[1].as_posix()),
    ):
        issues.append(
            DoctorIssue(
                issue_type="duplicate_markdown_id",
                severity="error",
                thought_id=thought_id,
                relative_path=relative_path,
                message=f"duplicate Markdown id {thought_id}",
                repair="Keep one projection for the ID and remove or repair the duplicate.",
            )
        )
    return issues, valid_paths


def hash_drift_issues(
    conn: sqlite3.Connection,
    root: Path,
    valid_projection_paths: set[Path],
) -> list[DoctorIssue]:
    """Find tracked projection files whose content changed since export."""
    rows = conn.execute(
        "SELECT thought_id, path, last_exported_hash FROM markdown_projections ORDER BY path"
    ).fetchall()
    issues: list[DoctorIssue] = []
    for row in rows:
        relative_path = Path(str(row["path"]))
        absolute_path = root / relative_path
        if relative_path not in valid_projection_paths or not absolute_path.exists():
            continue
        current_hash = projection_hash(absolute_path.read_text(encoding="utf-8"))
        if current_hash == row["last_exported_hash"]:
            continue
        issues.append(
            DoctorIssue(
                issue_type="hash_drift",
                severity="warning",
                thought_id=str(row["thought_id"]),
                relative_path=relative_path,
                message=f"projection content changed for thought {row['thought_id']}",
                repair="Run `thoughts sync --check` to review edits, then `thoughts sync --apply`.",
            )
        )
    return issues
