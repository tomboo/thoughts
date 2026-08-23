from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from thoughts.cli import run
from thoughts.db import get_thought, open_store
from thoughts.markdown import parse_projection
from thoughts.search import refresh_embeddings


class CountingEmbedder:
    provider = "local"
    model = "adversarial-e2e"
    dimension = 3

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        base = float(len(text))
        return (base, base + 1, base + 2)


def test_renamed_projection_still_syncs_by_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thought_id = capture_and_export(
        tmp_path,
        "Original body",
        title="Original title",
        capsys=capsys,
    )
    original_path = projection_path(tmp_path)
    renamed_path = tmp_path / "Inbox" / "renamed-by-user.md"
    original_path.rename(renamed_path)
    write_projection(
        renamed_path,
        {"title": "Renamed title"},
        "Renamed body\n",
    )

    assert run(["--root", str(tmp_path), "sync", "--check"]) == 0
    check_output = capsys.readouterr().out
    assert "Found 1 update(s)" in check_output
    assert "error:" not in check_output

    assert run(["--root", str(tmp_path), "sync", "--apply"]) == 0
    apply_output = capsys.readouterr().out
    assert "Applied 1 update(s)" in apply_output

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)
        total = conn.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0]
        projection = conn.execute(
            "SELECT path FROM markdown_projections WHERE thought_id = ?",
            (thought_id,),
        ).fetchone()

    assert thought.title == "Renamed title"
    assert thought.body == "Renamed body\n"
    assert total == 1
    assert projection["path"] == "Inbox/renamed-by-user.md"


def test_duplicate_frontmatter_ids_block_all_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(tmp_path), "init"]) == 0
    capsys.readouterr()
    first_id = capture(tmp_path, "First body", title="First", capsys=capsys)
    second_id = capture(tmp_path, "Second body", title="Second", capsys=capsys)
    assert run(["--root", str(tmp_path), "export-md"]) == 0
    capsys.readouterr()
    first_path = projection_path_for_id(tmp_path, first_id)
    second_path = projection_path_for_id(tmp_path, second_id)
    write_projection(first_path, {"title": "Tempting update"}, "Tempting body\n")
    first_frontmatter = read_frontmatter(first_path)
    write_projection(second_path, {"id": first_frontmatter["id"]}, "Second duplicate body\n")

    assert run(["--root", str(tmp_path), "sync", "--apply"]) == 1
    output = capsys.readouterr().out

    with open_store(tmp_path) as conn:
        first = get_thought(conn, first_id)
        second = get_thought(conn, second_id)
        issues = conn.execute(
            "SELECT issue_type, severity FROM sync_issues WHERE resolved_at IS NULL "
            "ORDER BY id"
        ).fetchall()

    assert "duplicate_id" in output
    assert first.title == "First"
    assert first.body == "First body"
    assert second.title == "Second"
    assert second.body == "Second body"
    assert [(row["issue_type"], row["severity"]) for row in issues] == [
        ("duplicate_id", "error"),
        ("duplicate_id", "error"),
    ]


def test_relative_llm_due_date_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thought_id = capture_initialized(tmp_path, "Call Alex tomorrow", capsys=capsys)
    output_path = classifier_output(
        tmp_path,
        thought_id,
        {
            "type": "task",
            "status": "active",
            "due": "tomorrow",
            "priority": "medium",
            "tags": ["followup"],
            "confidence": 0.95,
        },
    )

    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "process",
                "--apply",
                "--mock-output",
                str(output_path),
            ]
        )
        == 1
    )
    capsys.readouterr()

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)
        issue = conn.execute(
            "SELECT issue_type, severity, message FROM sync_issues WHERE resolved_at IS NULL"
        ).fetchone()

    assert thought.due_on is None
    assert issue["issue_type"] == "classification_invalid_output"
    assert issue["severity"] == "error"
    assert "malformed due date: tomorrow" in issue["message"]


def test_low_confidence_negation_classification_goes_to_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thought_id = capture_initialized(tmp_path, "do not buy milk", capsys=capsys)
    output_path = classifier_output(
        tmp_path,
        thought_id,
        {
            "type": "task",
            "status": "active",
            "due": None,
            "priority": "medium",
            "tags": ["shopping"],
            "confidence": 0.2,
        },
    )

    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "process",
                "--apply",
                "--mock-output",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)
        issue = conn.execute(
            "SELECT issue_type, severity FROM sync_issues WHERE resolved_at IS NULL"
        ).fetchone()

    assert thought.thought_type == "inbox"
    assert thought.priority is None
    assert thought.tags == ()
    assert issue["issue_type"] == "classification_low_confidence"
    assert issue["severity"] == "warning"


def test_yaml_looking_capture_body_round_trips(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = "---\nnot: frontmatter\n---\nactual body"
    thought_id = capture_and_export(tmp_path, body, title="YAML body", capsys=capsys)
    path = projection_path(tmp_path)
    parsed = parse_projection(path.read_text(encoding="utf-8"))

    assert run(["--root", str(tmp_path), "sync", "--check"]) == 0
    output = capsys.readouterr().out

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)

    assert parsed.body == f"{body}\n"
    assert output.startswith("Found 0 update(s)")
    assert "error:" not in output
    assert thought.body == body


def test_mobile_markdown_edit_survives_processing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thought_id = capture_and_export(
        tmp_path,
        "Canonical body",
        title="Mobile edit target",
        capsys=capsys,
    )
    path = projection_path(tmp_path)
    write_projection(path, {}, "Mobile edited body\n")
    output_path = classifier_output(
        tmp_path,
        thought_id,
        {
            "type": "task",
            "status": "flagged",
            "due": "2026-08-25",
            "priority": "high",
            "tags": ["mobile"],
            "confidence": 0.95,
        },
    )

    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "process",
                "--apply",
                "--mock-output",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    processed_content = path.read_text(encoding="utf-8")
    assert "Mobile edited body" in processed_content

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)

    assert thought.body == "Canonical body"
    assert thought.thought_type == "task"
    assert thought.status == "flagged"
    assert thought.priority == "high"
    assert thought.tags == ("mobile",)

    assert run(["--root", str(tmp_path), "doctor"]) == 1
    doctor_output = capsys.readouterr().out
    assert "hash_drift" in doctor_output


def test_search_and_embedding_work_do_not_mutate_canonical_fields(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(tmp_path), "init"]) == 0
    capsys.readouterr()
    first_id = capture(
        tmp_path,
        "Searchable oat milk note",
        title="Grocery search",
        capsys=capsys,
        tags=("shopping",),
    )
    capture(tmp_path, "Unrelated schema note", title="Schema", capsys=capsys)

    with open_store(tmp_path) as conn:
        before = {thought_id: get_thought(conn, thought_id) for thought_id in [first_id]}

    assert run(["--root", str(tmp_path), "search", "oat"]) == 0
    search_output = capsys.readouterr().out
    assert first_id in search_output

    embedder = CountingEmbedder()
    with open_store(tmp_path) as conn:
        result = refresh_embeddings(conn, embedder)
        after = {thought_id: get_thought(conn, thought_id) for thought_id in [first_id]}
        embedding_count = conn.execute("SELECT COUNT(*) FROM thought_embeddings").fetchone()[0]

    assert result.updated_count == 2
    assert embedding_count == 2
    assert after == before


def capture_initialized(
    tmp_path: Path,
    body: str,
    *,
    capsys: pytest.CaptureFixture[str],
) -> str:
    assert run(["--root", str(tmp_path), "init"]) == 0
    capsys.readouterr()
    return capture(tmp_path, body, title=body, capsys=capsys)


def capture_and_export(
    tmp_path: Path,
    body: str,
    *,
    title: str,
    capsys: pytest.CaptureFixture[str],
) -> str:
    assert run(["--root", str(tmp_path), "init"]) == 0
    capsys.readouterr()
    thought_id = capture(tmp_path, body, title=title, capsys=capsys)
    assert run(["--root", str(tmp_path), "export-md"]) == 0
    capsys.readouterr()
    return thought_id


def capture(
    tmp_path: Path,
    body: str,
    *,
    title: str,
    capsys: pytest.CaptureFixture[str],
    tags: tuple[str, ...] = (),
) -> str:
    args = ["--root", str(tmp_path), "capture", body, "--title", title]
    for tag in tags:
        args.extend(["--tag", tag])
    assert run(args) == 0
    return capsys.readouterr().out.strip()


def projection_path(tmp_path: Path) -> Path:
    return next((tmp_path / "Inbox").glob("*.md"))


def projection_path_for_id(tmp_path: Path, thought_id: str) -> Path:
    return next((tmp_path / "Inbox").glob(f"{thought_id}-*.md"))


def read_frontmatter(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(content.split("---", 2)[1])
    assert isinstance(loaded, dict)
    return loaded


def write_projection(path: Path, frontmatter_updates: dict[str, object], body: str) -> None:
    frontmatter = read_frontmatter(path)
    frontmatter.update(frontmatter_updates)
    path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n{body}",
        encoding="utf-8",
    )


def classifier_output(tmp_path: Path, thought_id: str, output: dict[str, object]) -> Path:
    output_path = tmp_path / f"{thought_id}-classifier-output.json"
    output_path.write_text(json.dumps({thought_id: output}), encoding="utf-8")
    return output_path
