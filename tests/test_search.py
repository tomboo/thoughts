from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from thoughts.cli import run
from thoughts.db import (
    capture_thought,
    get_thought,
    initialize,
    open_store,
    update_thought_from_projection,
)
from thoughts.models import NewThought
from thoughts.search import refresh_embeddings, search_text


class CountingEmbedder:
    provider = "local"
    model = "counting"

    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.calls = 0

    def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        base = float(len(text))
        return tuple(base + offset for offset in range(self.dimension))


def test_fts_search_returns_expected_records(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        milk = capture_thought(
            conn,
            NewThought(body="Buy oat milk and apples", title="Grocery list", tags=("shopping",)),
        )
        capture_thought(
            conn,
            NewThought(body="Sketch database migration plan", title="Schema work"),
        )

        results = search_text(conn, "oat milk")

    assert [result.thought_id for result in results] == [milk.id]
    assert results[0].title == "Grocery list"


def test_search_cli_prints_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        capture_thought(conn, NewThought(body="Remember FTS search", title="Search milestone"))

    assert run(["--root", str(tmp_path), "search", "FTS"]) == 0
    output = capsys.readouterr().out

    assert "results: 1" in output
    assert "Search milestone" in output


def test_embedding_rows_include_provider_model_dimension_content_hash_and_timestamp(
    tmp_path: Path,
) -> None:
    thought_id = captured_thought(tmp_path)
    embedder = CountingEmbedder(dimension=4)

    with open_store(tmp_path) as conn:
        result = refresh_embeddings(conn, embedder)
        row = conn.execute(
            "SELECT em.provider, em.model, em.dimension, te.content_hash, te.generated_at "
            "FROM thought_embeddings AS te "
            "JOIN embedding_models AS em ON em.id = te.model_id "
            "WHERE te.thought_id = ?",
            (thought_id,),
        ).fetchone()

    assert result.updated_count == 1
    assert row["provider"] == "local"
    assert row["model"] == "counting"
    assert row["dimension"] == 4
    assert len(row["content_hash"]) == 64
    assert row["generated_at"].startswith("20")


def test_model_dimension_mismatch_is_detected_before_querying(tmp_path: Path) -> None:
    captured_thought(tmp_path)

    with open_store(tmp_path) as conn:
        refresh_embeddings(conn, CountingEmbedder(dimension=3))
        with pytest.raises(ValueError, match="embedding dimension mismatch"):
            refresh_embeddings(conn, CountingEmbedder(dimension=4))


def test_reembedding_only_updates_stale_records_unless_forced(tmp_path: Path) -> None:
    thought_id = captured_thought(tmp_path)
    embedder = CountingEmbedder()

    with open_store(tmp_path) as conn:
        first = refresh_embeddings(conn, embedder)
        second = refresh_embeddings(conn, embedder)
        update_thought_from_projection(
            conn,
            thought_id=thought_id,
            title="Updated title",
            body="Updated body",
            thought_type="note",
            status="active",
            due_on=None,
            priority=None,
            tags=("updated",),
        )
        stale = refresh_embeddings(conn, embedder)
        forced = refresh_embeddings(conn, embedder, force=True)

    assert first.updated_count == 1
    assert first.skipped_count == 0
    assert second.updated_count == 0
    assert second.skipped_count == 1
    assert stale.updated_count == 1
    assert stale.skipped_count == 0
    assert forced.updated_count == 1
    assert forced.skipped_count == 0
    assert embedder.calls == 3


def test_search_does_not_mutate_canonical_state(tmp_path: Path) -> None:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(
            conn,
            NewThought(body="Searchable body", title="Canonical title", tags=("stable",)),
        )
        before = get_thought(conn, thought.id)
        search_text(conn, "searchable")
        after = get_thought(conn, thought.id)

    assert after == before


def captured_thought(tmp_path: Path) -> str:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(
            conn,
            NewThought(body="Original body", title="Original title"),
        )
    return thought.id


def test_fts_table_exists_after_migration(tmp_path: Path) -> None:
    initialize(tmp_path)

    with open_store(tmp_path) as conn:
        assert table_exists(conn, "embedding_models")
        assert table_exists(conn, "thought_embeddings")
        assert table_exists(conn, "thought_fts")


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
