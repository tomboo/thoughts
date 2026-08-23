from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from thoughts.cli import run
from thoughts.db import capture_thought, initialize, open_store
from thoughts.doctor import run_doctor
from thoughts.export import export_markdown
from thoughts.models import NewThought


def test_missing_projection_row_detected(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(conn, NewThought(body="Unexported", title="Unexported"))
        result = run_doctor(conn, tmp_path)

    assert [(issue.issue_type, issue.severity, issue.thought_id) for issue in result.issues] == [
        ("missing_projection_row", "warning", thought.id)
    ]
    assert result.exit_code == 1


def test_missing_projection_file_detected(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    path.unlink()

    with open_store(tmp_path) as conn:
        result = run_doctor(conn, tmp_path)

    assert [(issue.issue_type, issue.severity, issue.thought_id) for issue in result.issues] == [
        ("missing_projection_file", "warning", thought_id)
    ]
    assert "export-md" in result.issues[0].repair


def test_duplicate_markdown_id_detected(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    duplicate = path.with_name("duplicate.md")
    duplicate.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    with open_store(tmp_path) as conn:
        result = run_doctor(conn, tmp_path)

    duplicate_issues = [
        issue for issue in result.issues if issue.issue_type == "duplicate_markdown_id"
    ]
    assert len(duplicate_issues) == 2
    assert {issue.severity for issue in duplicate_issues} == {"error"}
    assert {issue.thought_id for issue in duplicate_issues} == {thought_id}
    assert result.exit_code == 2


def test_orphaned_projection_row_detected(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO markdown_projections ("
            "thought_id, path, last_exported_at, last_exported_hash"
            ") VALUES (?, ?, ?, ?)",
            ("th_missing", "Inbox/th_missing-orphan.md", "2026-08-23T00:00:00Z", "hash"),
        )
        result = run_doctor(conn, tmp_path)

    assert [(issue.issue_type, issue.severity, issue.thought_id) for issue in result.issues] == [
        ("orphaned_projection_row", "error", "th_missing"),
        ("missing_projection_file", "warning", "th_missing"),
    ]


def test_invalid_frontmatter_detected(tmp_path: Path) -> None:
    path, _ = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    path.write_text("---\ntitle: [unterminated\n---\nBody\n", encoding="utf-8")

    with open_store(tmp_path) as conn:
        result = run_doctor(conn, tmp_path)

    assert [(issue.issue_type, issue.severity) for issue in result.issues] == [
        ("invalid_frontmatter", "error")
    ]
    assert "frontmatter" in result.issues[0].repair


def test_hash_drift_detected(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    update_projection(path, {"title": "Edited title"}, "Edited body\n")

    with open_store(tmp_path) as conn:
        result = run_doctor(conn, tmp_path)

    assert [(issue.issue_type, issue.severity, issue.thought_id) for issue in result.issues] == [
        ("hash_drift", "warning", thought_id)
    ]
    assert "sync --check" in result.issues[0].repair


def test_doctor_exit_codes_distinguish_clean_warning_and_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initialize(tmp_path)
    assert run(["--root", str(tmp_path), "doctor"]) == 0
    assert "ok" in capsys.readouterr().out

    with open_store(tmp_path) as conn:
        capture_thought(conn, NewThought(body="Needs export", title="Needs export"))
    assert run(["--root", str(tmp_path), "doctor"]) == 1
    assert "warnings: 1" in capsys.readouterr().out

    invalid = tmp_path / "Inbox" / "invalid.md"
    invalid.write_text("---\ntitle: [unterminated\n---\n", encoding="utf-8")
    assert run(["--root", str(tmp_path), "doctor"]) == 2
    output = capsys.readouterr().out
    assert "errors: 1" in output
    assert "warnings: 1" in output


def exported_thought(tmp_path: Path, thought: NewThought) -> tuple[Path, str]:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        captured = capture_thought(conn, thought)
        export_markdown(conn, tmp_path)
    return next((tmp_path / "Inbox").glob("*.md")), captured.id


def update_projection(path: Path, frontmatter_updates: dict[str, object], body: str) -> None:
    content = path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(content.split("---", 2)[1])
    frontmatter.update(frontmatter_updates)
    path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n{body}",
        encoding="utf-8",
    )
