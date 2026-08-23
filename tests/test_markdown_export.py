from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from thoughts.db import capture_thought, initialize, open_store
from thoughts.export import ProjectionDriftError, export_markdown
from thoughts.markdown import projection_hash
from thoughts.models import NewThought


def test_exported_markdown_parses_as_yaml(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(
            conn,
            NewThought(
                body="Buy milk\nCheck pantry first.",
                title="Buy milk",
                thought_type="task",
                due_on="2026-08-25",
                priority="medium",
                tags=("Shopping", "Errands"),
            ),
        )
        result = export_markdown(conn, tmp_path)

    assert result.exported_count == 1
    path = next((tmp_path / "Inbox").glob("*.md"))
    frontmatter_text = path.read_text(encoding="utf-8").split("---", 2)[1]
    frontmatter = yaml.safe_load(frontmatter_text)

    assert frontmatter == {
        "id": thought.id,
        "title": "Buy milk",
        "type": "task",
        "status": "active",
        "due": "2026-08-25",
        "priority": "medium",
        "tags": ["errands", "shopping"],
        "schema_version": 1,
        "last_exported_hash": projection_hash(path.read_text(encoding="utf-8")),
    }


def test_export_is_deterministic(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        capture_thought(conn, NewThought(body="Stable export", title="Stable export"))
        export_markdown(conn, tmp_path)
        path = next((tmp_path / "Inbox").glob("*.md"))
        first_content = path.read_text(encoding="utf-8")

        export_markdown(conn, tmp_path)
        second_content = path.read_text(encoding="utf-8")

    assert first_content == second_content


def test_title_changes_keep_existing_projection_path(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(conn, NewThought(body="Original body", title="Original title"))
        export_markdown(conn, tmp_path)
        original_path = next((tmp_path / "Inbox").glob("*.md"))

        conn.execute(
            "UPDATE thoughts SET title = ?, updated_at = updated_at WHERE id = ?",
            ("New title", thought.id),
        )
        export_markdown(conn, tmp_path)

    assert original_path.exists()
    assert original_path.name.endswith("-original-title.md")
    assert not list((tmp_path / "Inbox").glob("*new-title.md"))
    assert 'title: "New title"' in original_path.read_text(encoding="utf-8")


def test_externally_modified_file_is_not_overwritten(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        capture_thought(conn, NewThought(body="Original body", title="Original title"))
        export_markdown(conn, tmp_path)
        path = next((tmp_path / "Inbox").glob("*.md"))
        path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit\n", encoding="utf-8")

        with pytest.raises(ProjectionDriftError, match="external changes"):
            export_markdown(conn, tmp_path)

    assert "External edit" in path.read_text(encoding="utf-8")


def test_export_refuses_to_overwrite_untracked_projection_path(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(conn, NewThought(body="Collision", title="Collision"))
        path = tmp_path / "Inbox" / f"{thought.id}-collision.md"
        path.write_text("user-owned file\n", encoding="utf-8")

        with pytest.raises(ProjectionDriftError, match="external changes"):
            export_markdown(conn, tmp_path)

    assert path.read_text(encoding="utf-8") == "user-owned file\n"


def test_tags_round_trip_in_normalized_form(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        capture_thought(
            conn,
            NewThought(
                body="Normalize tags",
                title="Normalize tags",
                tags=("#MixedCase", "plain"),
            ),
        )
        export_markdown(conn, tmp_path)

    path = next((tmp_path / "Inbox").glob("*.md"))
    frontmatter_text = path.read_text(encoding="utf-8").split("---", 2)[1]
    frontmatter = yaml.safe_load(frontmatter_text)

    assert frontmatter["tags"] == ["mixedcase", "plain"]
