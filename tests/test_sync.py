from __future__ import annotations

from pathlib import Path

import yaml

from thoughts.db import capture_thought, get_thought, initialize, open_store
from thoughts.export import export_markdown
from thoughts.models import NewThought
from thoughts.sync import apply_sync, check_sync


def test_valid_title_body_status_and_tag_edits_import(tmp_path: Path) -> None:
    path, thought_id = exported_thought(
        tmp_path,
        NewThought(body="Original body", title="Original title", tags=("old",)),
    )
    write_projection(
        path,
        {
            "title": "Edited title",
            "status": "flagged",
            "tags": ["New", "#old"],
        },
        "Edited body\n",
    )

    with open_store(tmp_path) as conn:
        result = apply_sync(conn, tmp_path)
        thought = get_thought(conn, thought_id)

    assert result.applied_count == 1
    assert not result.issues
    assert thought.title == "Edited title"
    assert thought.body == "Edited body\n"
    assert thought.status == "flagged"
    assert thought.tags == ("new", "old")
    assert 'title: "Edited title"' in path.read_text(encoding="utf-8")


def test_invalid_status_is_rejected_and_written_to_sync_issues(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    write_projection(path, {"status": "later"}, "Body\n")

    with open_store(tmp_path) as conn:
        result = apply_sync(conn, tmp_path)
        thought = get_thought(conn, thought_id)
        issue = conn.execute(
            "SELECT issue_type, severity, message FROM sync_issues WHERE resolved_at IS NULL"
        ).fetchone()

    assert result.has_errors
    assert thought.status == "active"
    assert issue["issue_type"] == "validation_error"
    assert issue["severity"] == "error"
    assert "invalid status: later" in issue["message"]


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    duplicate = path.with_name("duplicate.md")
    duplicate.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    with open_store(tmp_path) as conn:
        result = check_sync(conn, tmp_path)

    duplicate_issues = [issue for issue in result.issues if issue.issue_type == "duplicate_id"]
    assert len(duplicate_issues) == 2
    assert {issue.thought_id for issue in duplicate_issues} == {thought_id}


def test_missing_id_is_rejected(tmp_path: Path) -> None:
    path, _ = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    data = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    del data["id"]
    body = path.read_text(encoding="utf-8").split("---", 2)[2].lstrip("\n")
    path.write_text(render_markdown(data, body), encoding="utf-8")

    with open_store(tmp_path) as conn:
        result = check_sync(conn, tmp_path)

    assert [(issue.issue_type, issue.severity) for issue in result.issues] == [
        ("missing_id", "error")
    ]


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    path, _ = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    path.write_text("---\ntitle: [unterminated\n---\nBody\n", encoding="utf-8")

    with open_store(tmp_path) as conn:
        result = check_sync(conn, tmp_path)

    assert [(issue.issue_type, issue.severity) for issue in result.issues] == [
        ("invalid_frontmatter", "error")
    ]


def test_malformed_due_date_is_rejected(tmp_path: Path) -> None:
    path, _ = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    write_projection(path, {"due": "not-a-date"}, "Body\n")

    with open_store(tmp_path) as conn:
        result = check_sync(conn, tmp_path)

    assert result.has_errors
    assert result.issues[0].message == "malformed due date: not-a-date"


def test_markdown_deletion_is_reported_without_deleting_database_row(tmp_path: Path) -> None:
    path, thought_id = exported_thought(tmp_path, NewThought(body="Body", title="Title"))
    path.unlink()

    with open_store(tmp_path) as conn:
        result = apply_sync(conn, tmp_path)
        thought = get_thought(conn, thought_id)

    assert result.applied_count == 0
    assert [(issue.issue_type, issue.severity) for issue in result.issues] == [
        ("projection_deleted", "warning")
    ]
    assert thought.id == thought_id


def test_apply_mode_is_transactional_for_canonical_updates(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        first = capture_thought(conn, NewThought(body="First body", title="First"))
        second = capture_thought(conn, NewThought(body="Second body", title="Second"))
        export_markdown(conn, tmp_path)

    paths = sorted((tmp_path / "Inbox").glob("*.md"))
    first_path = next(path for path in paths if first.id in path.name)
    second_path = next(path for path in paths if second.id in path.name)
    write_projection(first_path, {"title": "Updated first"}, "Updated first body\n")
    write_projection(second_path, {"status": "invalid"}, "Second body\n")

    with open_store(tmp_path) as conn:
        result = apply_sync(conn, tmp_path)
        unchanged_first = get_thought(conn, first.id)
        unchanged_second = get_thought(conn, second.id)

    assert result.has_errors
    assert unchanged_first.title == "First"
    assert unchanged_first.body == "First body"
    assert unchanged_second.status == "active"


def exported_thought(tmp_path: Path, thought: NewThought) -> tuple[Path, str]:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        captured = capture_thought(conn, thought)
        export_markdown(conn, tmp_path)
    return next((tmp_path / "Inbox").glob("*.md")), captured.id


def write_projection(path: Path, frontmatter_updates: dict[str, object], body: str) -> None:
    content = path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(content.split("---", 2)[1])
    frontmatter.update(frontmatter_updates)
    path.write_text(render_markdown(frontmatter, body), encoding="utf-8")


def render_markdown(frontmatter: dict[str, object], body: str) -> str:
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n{body}"
