"""Markdown projection serialization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from thoughts.models import Thought
from thoughts.paths import INBOX_DIR_NAME

HASH_FIELD = "last_exported_hash"
HASH_PLACEHOLDER = "__THOUGHTS_HASH__"


@dataclass(frozen=True)
class RenderedProjection:
    """Rendered Markdown and its drift-detection hash."""

    relative_path: Path
    content: str
    content_hash: str


def render_projection(
    thought: Thought,
    existing_relative_path: Path | None = None,
) -> RenderedProjection:
    """Render one canonical thought as an Obsidian-readable Markdown projection."""
    relative_path = existing_relative_path or projection_path(thought)
    content_without_hash = render_projection_content(thought, HASH_PLACEHOLDER)
    content_hash = projection_hash(content_without_hash)
    content = content_without_hash.replace(HASH_PLACEHOLDER, content_hash)
    return RenderedProjection(
        relative_path=relative_path,
        content=content,
        content_hash=content_hash,
    )


def render_projection_content(thought: Thought, last_exported_hash: str) -> str:
    """Render Markdown content with stable frontmatter ordering."""
    frontmatter = [
        "---",
        f"id: {yaml_scalar(thought.id)}",
        f"title: {yaml_scalar(thought.title)}",
        f"type: {yaml_scalar(thought.thought_type)}",
        f"status: {yaml_scalar(thought.status)}",
        f"due: {yaml_nullable(thought.due_on)}",
        f"priority: {yaml_nullable(thought.priority)}",
    ]
    if thought.tags:
        frontmatter.append("tags:")
        frontmatter.extend(f"  - {yaml_scalar(tag)}" for tag in thought.tags)
    else:
        frontmatter.append("tags: []")
    frontmatter.extend(
        [
            f"schema_version: {thought.schema_version}",
            f"{HASH_FIELD}: {yaml_scalar(last_exported_hash)}",
            "---",
            "",
        ]
    )
    body = thought.body.rstrip()
    if body:
        return "\n".join(frontmatter) + body + "\n"
    return "\n".join(frontmatter)


def projection_path(thought: Thought) -> Path:
    """Return the deterministic initial projection path for a thought."""
    return Path(INBOX_DIR_NAME) / f"{thought.id}-{slugify(thought.title)}.md"


def slugify(value: str) -> str:
    """Create a compact filesystem slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "untitled"


def projection_hash(content: str) -> str:
    """Hash Markdown content while ignoring the embedded export-hash value."""
    normalized = re.sub(
        rf"^{HASH_FIELD}: .*$",
        f"{HASH_FIELD}: {HASH_PLACEHOLDER}",
        content,
        flags=re.MULTILINE,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def yaml_scalar(value: str) -> str:
    """Render a string as a YAML-safe JSON-style scalar."""
    return json.dumps(value, ensure_ascii=False)


def yaml_nullable(value: str | None) -> str:
    """Render a nullable scalar for YAML frontmatter."""
    if value is None:
        return "null"
    return yaml_scalar(value)
