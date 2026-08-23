"""Stable identifier generation."""

from __future__ import annotations

from uuid import uuid4


def new_thought_id() -> str:
    """Generate a durable thought ID."""
    return f"th_{uuid4().hex}"
