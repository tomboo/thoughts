"""Owner-routed remote capture protocol and receiver.

Non-owner devices never write canonical SQLite. They send one JSON capture
request to the owner machine, which validates it and performs exactly one
create. Requests carry a client-generated ``request_id`` that makes redelivery
idempotent, so a retry after a lost response can never duplicate a thought.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from thoughts.db import (
    find_capture_request,
    insert_thought,
    record_capture_request,
)
from thoughts.models import NewThought

PROTOCOL_VERSION = 1
ORIGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
REQUEST_KEYS = frozenset({"protocol_version", "request_id", "submitted_at", "origin", "thought"})
REQUIRED_REQUEST_KEYS = frozenset({"protocol_version", "request_id", "origin", "thought"})
THOUGHT_KEYS = frozenset({"body", "title", "type", "tags", "due", "priority"})


class ProtocolError(ValueError):
    """A capture request was malformed or violated the protocol contract."""


@dataclass(frozen=True)
class CaptureRequest:
    """One validated create-only capture request."""

    request_id: str
    origin: str
    body: str
    title: str | None = None
    thought_type: str = "inbox"
    tags: tuple[str, ...] = field(default_factory=tuple)
    due_on: str | None = None
    priority: str | None = None
    submitted_at: str | None = None

    @property
    def source(self) -> str:
        """Return the canonical provenance value for this request's origin."""
        return f"remote:{self.origin}"


@dataclass(frozen=True)
class CaptureResponse:
    """The owner's answer to one capture request."""

    status: str
    request_id: str
    thought_id: str | None = None
    error: str | None = None

    @property
    def accepted(self) -> bool:
        """Return whether the owner holds a canonical thought for this request."""
        return self.status in {"created", "duplicate"}

    def to_json(self) -> str:
        """Encode the response as one JSON line."""
        payload: dict[str, Any] = {
            "protocol_version": PROTOCOL_VERSION,
            "status": self.status,
            "request_id": self.request_id,
        }
        if self.thought_id is not None:
            payload["thought_id"] = self.thought_id
        if self.error is not None:
            payload["error"] = self.error
        return json.dumps(payload, sort_keys=True)


def new_request_id() -> str:
    """Generate a durable capture request ID."""
    return f"req_{uuid4().hex}"


def encode_request(request: CaptureRequest) -> str:
    """Encode a capture request as one JSON line."""
    payload: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "origin": request.origin,
        "thought": {
            "body": request.body,
            "title": request.title,
            "type": request.thought_type,
            "tags": list(request.tags),
            "due": request.due_on,
            "priority": request.priority,
        },
    }
    if request.submitted_at is not None:
        payload["submitted_at"] = request.submitted_at
    return json.dumps(payload, sort_keys=True)


def parse_request(text: str) -> CaptureRequest:
    """Decode and validate one JSON capture request.

    Unknown keys are rejected rather than ignored so a newer client fails
    loudly against an older owner instead of silently losing fields.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"request is not valid JSON: {error}"
        raise ProtocolError(msg) from error
    if not isinstance(payload, dict):
        msg = "request must be a JSON object"
        raise ProtocolError(msg)

    reject_unknown_keys(payload, REQUEST_KEYS, "request")
    missing = sorted(REQUIRED_REQUEST_KEYS - set(payload))
    if missing:
        msg = f"request is missing required field(s): {', '.join(missing)}"
        raise ProtocolError(msg)

    version = payload["protocol_version"]
    if version != PROTOCOL_VERSION:
        msg = f"unsupported protocol_version: {version!r} (owner speaks {PROTOCOL_VERSION})"
        raise ProtocolError(msg)

    request_id = required_text(payload, "request_id")
    origin = required_text(payload, "origin")
    if not ORIGIN_PATTERN.match(origin):
        msg = f"invalid origin: {origin!r}"
        raise ProtocolError(msg)

    thought = payload["thought"]
    if not isinstance(thought, dict):
        msg = "thought must be a JSON object"
        raise ProtocolError(msg)
    reject_unknown_keys(thought, THOUGHT_KEYS, "thought")

    body = required_text(thought, "body")
    return CaptureRequest(
        request_id=request_id,
        origin=origin,
        body=body,
        title=optional_text(thought, "title"),
        thought_type=optional_text(thought, "type") or "inbox",
        tags=parse_tags(thought.get("tags")),
        due_on=optional_text(thought, "due"),
        priority=optional_text(thought, "priority"),
        submitted_at=optional_text(payload, "submitted_at"),
    )


def receive_capture(conn: sqlite3.Connection, request: CaptureRequest) -> CaptureResponse:
    """Create one canonical thought for a capture request, idempotently.

    A ``request_id`` the owner has already recorded returns the original
    thought id without writing, so a client that retries a request whose
    response was lost still ends up with exactly one thought.
    """
    existing = find_capture_request(conn, request.request_id)
    if existing is not None:
        return CaptureResponse(
            status="duplicate",
            request_id=request.request_id,
            thought_id=existing,
        )

    new_thought = NewThought(
        body=request.body,
        title=request.title if request.title else default_title(request.body),
        thought_type=request.thought_type,
        due_on=request.due_on,
        priority=request.priority,
        tags=request.tags,
        source=request.source,
    )
    with conn:
        thought_id = insert_thought(conn, new_thought)
        record_capture_request(
            conn,
            request_id=request.request_id,
            thought_id=thought_id,
            origin=request.origin,
            submitted_at=request.submitted_at,
        )
    return CaptureResponse(status="created", request_id=request.request_id, thought_id=thought_id)


def parse_response(text: str) -> CaptureResponse:
    """Decode one JSON capture response from the owner."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"response is not valid JSON: {error}"
        raise ProtocolError(msg) from error
    if not isinstance(payload, dict):
        msg = "response must be a JSON object"
        raise ProtocolError(msg)
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        msg = f"unsupported response protocol_version: {payload.get('protocol_version')!r}"
        raise ProtocolError(msg)
    status = payload.get("status")
    if status not in {"created", "duplicate", "rejected"}:
        msg = f"unsupported response status: {status!r}"
        raise ProtocolError(msg)
    return CaptureResponse(
        status=str(status),
        request_id=str(payload.get("request_id", "")),
        thought_id=None if payload.get("thought_id") is None else str(payload["thought_id"]),
        error=None if payload.get("error") is None else str(payload["error"]),
    )


def default_title(text: str) -> str:
    """Derive a compact title from captured text."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) <= 80:
        return first_line
    return f"{first_line[:77]}..."


def reject_unknown_keys(payload: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    """Raise when a payload carries fields this protocol version does not define."""
    unknown = sorted(set(payload) - allowed)
    if unknown:
        msg = f"unknown {label} field(s): {', '.join(unknown)}"
        raise ProtocolError(msg)


def required_text(payload: dict[str, Any], key: str) -> str:
    """Read a required non-blank string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{key} must be a non-empty string"
        raise ProtocolError(msg)
    return value


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    """Read an optional string field, treating null and blank as absent."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string or null"
        raise ProtocolError(msg)
    return value or None


def parse_tags(value: Any) -> tuple[str, ...]:
    """Read the optional tag list."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        msg = "tags must be a list of strings"
        raise ProtocolError(msg)
    return tuple(value)
