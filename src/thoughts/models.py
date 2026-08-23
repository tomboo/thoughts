"""Domain models and validators."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

VALID_TYPES = frozenset({"inbox", "task", "note", "idea"})
VALID_STATUSES = frozenset({"active", "done", "archived", "superseded", "flagged"})
VALID_PRIORITIES = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class NewThought:
    """Input fields for creating a canonical thought."""

    body: str
    title: str
    thought_type: str = "inbox"
    status: str = "active"
    due_on: str | None = None
    priority: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    source: str = "cli"


@dataclass(frozen=True)
class Thought:
    """A canonical thought row."""

    id: str
    title: str
    body: str
    thought_type: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None
    due_on: str | None
    priority: str | None
    source: str
    schema_version: int
    tags: tuple[str, ...]


def validate_new_thought(thought: NewThought) -> None:
    """Validate input before it reaches SQLite constraints."""
    if not thought.body.strip():
        msg = "body must not be blank"
        raise ValueError(msg)
    if not thought.title.strip():
        msg = "title must not be blank"
        raise ValueError(msg)
    if thought.thought_type not in VALID_TYPES:
        msg = f"invalid type: {thought.thought_type}"
        raise ValueError(msg)
    if thought.status not in VALID_STATUSES:
        msg = f"invalid status: {thought.status}"
        raise ValueError(msg)
    if thought.priority is not None and thought.priority not in VALID_PRIORITIES:
        msg = f"invalid priority: {thought.priority}"
        raise ValueError(msg)
    if thought.due_on is not None:
        date.fromisoformat(thought.due_on)
