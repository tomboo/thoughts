"""Search and embedding-index helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from thoughts.db import list_thoughts
from thoughts.models import Thought


class Embedder(Protocol):
    """Embedding provider used by the optional semantic index."""

    provider: str
    model: str
    dimension: int

    def embed(self, text: str) -> tuple[float, ...]:
        """Return one embedding vector for the supplied text."""


@dataclass(frozen=True)
class SearchResult:
    """A full-text search result."""

    thought_id: str
    title: str
    body: str
    rank: float


@dataclass(frozen=True)
class EmbeddingRefreshResult:
    """Summary of an embedding refresh run."""

    updated_count: int
    skipped_count: int


def search_text(conn: sqlite3.Connection, query: str, *, limit: int = 10) -> list[SearchResult]:
    """Refresh the FTS index and search canonical title, body, and tags."""
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    refresh_fts_index(conn)
    rows = conn.execute(
        "SELECT t.id, t.title, t.body, bm25(thought_fts) AS rank "
        "FROM thought_fts "
        "JOIN thoughts AS t ON t.id = thought_fts.thought_id "
        "WHERE thought_fts MATCH ? "
        "ORDER BY rank, t.created_at, t.id "
        "LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    return [
        SearchResult(
            thought_id=str(row["id"]),
            title=str(row["title"]),
            body=str(row["body"]),
            rank=float(row["rank"]),
        )
        for row in rows
    ]


def refresh_fts_index(conn: sqlite3.Connection) -> None:
    """Rebuild the derived full-text index from canonical records."""
    with conn:
        conn.execute("DELETE FROM thought_fts")
        for thought in list_thoughts(conn):
            conn.execute(
                "INSERT INTO thought_fts (thought_id, title, body, tags) VALUES (?, ?, ?, ?)",
                (
                    thought.id,
                    thought.title,
                    thought.body,
                    " ".join(thought.tags),
                ),
            )


def refresh_embeddings(
    conn: sqlite3.Connection,
    embedder: Embedder,
    *,
    force: bool = False,
) -> EmbeddingRefreshResult:
    """Create or refresh stale embedding rows for one provider/model/dimension."""
    model_id = get_or_create_embedding_model(conn, embedder)
    updated_count = 0
    skipped_count = 0

    with conn:
        for thought in list_thoughts(conn):
            content = embedding_content(thought)
            content_hash = stable_hash(content)
            row = conn.execute(
                "SELECT content_hash FROM thought_embeddings "
                "WHERE thought_id = ? AND model_id = ?",
                (thought.id, model_id),
            ).fetchone()
            if row is not None and row["content_hash"] == content_hash and not force:
                skipped_count += 1
                continue

            vector = embedder.embed(content)
            if len(vector) != embedder.dimension:
                msg = (
                    f"embedder returned dimension {len(vector)} "
                    f"for configured dimension {embedder.dimension}"
                )
                raise ValueError(msg)

            conn.execute(
                "INSERT INTO thought_embeddings ("
                "thought_id, model_id, content_hash, embedding, generated_at"
                ") VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ON CONFLICT(thought_id, model_id) DO UPDATE SET "
                "content_hash = excluded.content_hash, "
                "embedding = excluded.embedding, "
                "generated_at = excluded.generated_at",
                (
                    thought.id,
                    model_id,
                    content_hash,
                    serialize_vector(vector),
                ),
            )
            updated_count += 1

    return EmbeddingRefreshResult(updated_count=updated_count, skipped_count=skipped_count)


def get_or_create_embedding_model(conn: sqlite3.Connection, embedder: Embedder) -> int:
    """Return the model row, rejecting provider/model dimension drift."""
    existing_dimensions = [
        int(row["dimension"])
        for row in conn.execute(
            "SELECT dimension FROM embedding_models WHERE provider = ? AND model = ?",
            (embedder.provider, embedder.model),
        )
    ]
    incompatible = [
        dimension for dimension in existing_dimensions if dimension != embedder.dimension
    ]
    if incompatible:
        msg = (
            f"embedding dimension mismatch for {embedder.provider}/{embedder.model}: "
            f"stored {incompatible[0]}, requested {embedder.dimension}"
        )
        raise ValueError(msg)

    row = conn.execute(
        "SELECT id FROM embedding_models WHERE provider = ? AND model = ? AND dimension = ?",
        (embedder.provider, embedder.model, embedder.dimension),
    ).fetchone()
    if row is not None:
        return int(row["id"])

    with conn:
        cursor = conn.execute(
            "INSERT INTO embedding_models (provider, model, dimension, created_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (embedder.provider, embedder.model, embedder.dimension),
        )
    if cursor.lastrowid is None:
        msg = "failed to create embedding model row"
        raise RuntimeError(msg)
    return int(cursor.lastrowid)


def build_fts_query(query: str) -> str:
    """Build a conservative FTS query from plain user text."""
    terms = [
        "".join(character for character in raw if character.isalnum() or character in {"_", "-"})
        for raw in query.split()
    ]
    quoted_terms = [f'"{term}"' for term in terms if term]
    return " OR ".join(quoted_terms)


def embedding_content(thought: Thought) -> str:
    """Return the stable text used for embedding freshness."""
    return "\n".join(
        [
            f"title: {thought.title}",
            f"type: {thought.thought_type}",
            f"status: {thought.status}",
            f"tags: {', '.join(thought.tags)}",
            "",
            thought.body,
        ]
    )


def stable_hash(value: str) -> str:
    """Return a stable SHA-256 hash for derived-index freshness."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def serialize_vector(vector: tuple[float, ...]) -> bytes:
    """Serialize a vector into a portable BLOB."""
    return json.dumps(list(vector), separators=(",", ":")).encode("utf-8")
