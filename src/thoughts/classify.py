"""Reviewed LLM classification pipeline."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from thoughts.db import get_thought, list_thoughts, normalize_tag, record_sync_issue
from thoughts.models import VALID_PRIORITIES, VALID_STATUSES, VALID_TYPES, Thought

DEFAULT_CONFIDENCE_THRESHOLD = 0.75

CLASSIFIER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "status", "due", "priority", "tags", "confidence"],
    "properties": {
        "type": {"enum": sorted(VALID_TYPES)},
        "status": {"enum": sorted(VALID_STATUSES)},
        "due": {"type": ["string", "null"], "format": "date"},
        "priority": {"enum": [*sorted(VALID_PRIORITIES), None]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}


class Classifier(Protocol):
    """A model adapter that returns raw JSON classification output."""

    def classify(self, thought: Thought) -> str:
        """Classify one thought and return a JSON object string."""


class MissingClassifier:
    """Default classifier used until a real model adapter is configured."""

    def classify(self, thought: Thought) -> str:
        """Raise a clear configuration error."""
        msg = "no classifier configured; pass a classifier object or --mock-output"
        raise RuntimeError(msg)


class FileClassifier:
    """Deterministic classifier backed by a JSON/JSONL file for review and tests."""

    def __init__(self, path: Path) -> None:
        self._responses = load_file_responses(path)

    def classify(self, thought: Thought) -> str:
        """Return the response for a thought ID."""
        try:
            return self._responses[thought.id]
        except KeyError as error:
            msg = f"mock output is missing thought id: {thought.id}"
            raise RuntimeError(msg) from error


@dataclass(frozen=True)
class ClassificationProposal:
    """Validated classifier output."""

    thought_id: str
    thought_type: str
    status: str
    due_on: str | None
    priority: str | None
    tags: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class ProcessIssue:
    """A processing issue found while validating or applying model output."""

    thought_id: str
    issue_type: str
    severity: str
    message: str


@dataclass(frozen=True)
class ProcessResult:
    """Result of a dry-run or apply processing run."""

    proposals: tuple[ClassificationProposal, ...]
    issues: tuple[ProcessIssue, ...]
    applied_count: int = 0

    @property
    def has_errors(self) -> bool:
        """Return whether any issue blocks canonical updates."""
        return any(issue.severity == "error" for issue in self.issues)


def dry_run_process(
    conn: sqlite3.Connection,
    classifier: Classifier,
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ProcessResult:
    """Classify thoughts and validate outputs without mutating SQLite."""
    return build_process_result(
        list_thoughts(conn),
        classifier,
        confidence_threshold=confidence_threshold,
    )


def apply_process(
    conn: sqlite3.Connection,
    classifier: Classifier,
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ProcessResult:
    """Apply high-confidence validated classifier proposals to canonical metadata."""
    result = dry_run_process(conn, classifier, confidence_threshold=confidence_threshold)
    if result.has_errors:
        with conn:
            for issue in result.issues:
                if issue.severity == "error":
                    record_process_issue(conn, issue)
        return result

    approved = [
        proposal
        for proposal in result.proposals
        if proposal.confidence >= confidence_threshold
    ]
    review_issues = [
        issue for issue in result.issues if issue.issue_type == "classification_low_confidence"
    ]

    with conn:
        for proposal in approved:
            update_thought_classification(conn, proposal)
        for issue in review_issues:
            record_process_issue(conn, issue)

    return ProcessResult(
        proposals=result.proposals,
        issues=result.issues,
        applied_count=len(approved),
    )


def build_process_result(
    thoughts: Iterable[Thought],
    classifier: Classifier,
    *,
    confidence_threshold: float,
) -> ProcessResult:
    """Build a process result from classifier outputs."""
    proposals: list[ClassificationProposal] = []
    issues: list[ProcessIssue] = []

    for thought in thoughts:
        try:
            raw_output = classifier.classify(thought)
            proposal = validate_classifier_output(thought.id, raw_output)
        except (RuntimeError, ValueError) as error:
            issues.append(
                ProcessIssue(
                    thought_id=thought.id,
                    issue_type="classification_invalid_output",
                    severity="error",
                    message=str(error),
                )
            )
            continue

        proposals.append(proposal)
        if proposal.confidence < confidence_threshold:
            issues.append(
                ProcessIssue(
                    thought_id=thought.id,
                    issue_type="classification_low_confidence",
                    severity="warning",
                    message=(
                        f"confidence {proposal.confidence:.2f} is below "
                        f"threshold {confidence_threshold:.2f}; queued for review"
                    ),
                )
            )

    return ProcessResult(proposals=tuple(proposals), issues=tuple(issues))


def validate_classifier_output(thought_id: str, raw_output: str) -> ClassificationProposal:
    """Parse and validate strict JSON classifier output."""
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as error:
        msg = f"invalid classifier JSON: {error.msg}"
        raise ValueError(msg) from error

    if not isinstance(data, dict):
        msg = "classifier output must be a JSON object"
        raise ValueError(msg)

    allowed_fields = {"type", "status", "due", "priority", "tags", "confidence"}
    extra_fields = set(data) - allowed_fields
    if extra_fields:
        msg = f"unknown classifier field: {sorted(extra_fields)[0]}"
        raise ValueError(msg)

    missing_fields = allowed_fields - set(data)
    if missing_fields:
        msg = f"missing classifier field: {sorted(missing_fields)[0]}"
        raise ValueError(msg)

    thought_type = require_enum(data["type"], "type", VALID_TYPES)
    status = require_enum(data["status"], "status", VALID_STATUSES)
    due_on = require_nullable_string(data["due"], "due")
    if due_on is not None:
        try:
            date.fromisoformat(due_on)
        except ValueError as error:
            msg = f"malformed due date: {due_on}"
            raise ValueError(msg) from error

    priority = require_nullable_string(data["priority"], "priority")
    if priority is not None and priority not in VALID_PRIORITIES:
        msg = f"invalid priority: {priority}"
        raise ValueError(msg)

    tags = require_tags(data["tags"])
    confidence = data["confidence"]
    if not isinstance(confidence, int | float):
        msg = "confidence must be a number"
        raise ValueError(msg)
    confidence_float = float(confidence)
    if not 0 <= confidence_float <= 1:
        msg = "confidence must be between 0 and 1"
        raise ValueError(msg)

    return ClassificationProposal(
        thought_id=thought_id,
        thought_type=thought_type,
        status=status,
        due_on=due_on,
        priority=priority,
        tags=tags,
        confidence=confidence_float,
    )


def update_thought_classification(
    conn: sqlite3.Connection,
    proposal: ClassificationProposal,
) -> None:
    """Update only classifier-approved canonical metadata fields."""
    get_thought(conn, proposal.thought_id)
    conn.execute(
        "UPDATE thoughts SET "
        "type = ?, status = ?, due_on = ?, priority = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        (
            proposal.thought_type,
            proposal.status,
            proposal.due_on,
            proposal.priority,
            proposal.thought_id,
        ),
    )
    conn.execute("DELETE FROM thought_tags WHERE thought_id = ?", (proposal.thought_id,))
    for tag in proposal.tags:
        conn.execute(
            "INSERT INTO thought_tags (thought_id, tag) VALUES (?, ?)",
            (proposal.thought_id, tag),
        )


def record_process_issue(conn: sqlite3.Connection, issue: ProcessIssue) -> None:
    """Persist one processing issue into the existing review issue table."""
    record_sync_issue(
        conn,
        thought_id=issue.thought_id,
        path=None,
        issue_type=issue.issue_type,
        severity=issue.severity,
        message=issue.message,
    )


def require_enum(value: object, field_name: str, allowed: frozenset[str]) -> str:
    """Validate a required enum string."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string"
        raise ValueError(msg)
    if value not in allowed:
        msg = f"invalid {field_name}: {value}"
        raise ValueError(msg)
    return value


def require_nullable_string(value: object, field_name: str) -> str | None:
    """Validate a nullable string."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null"
        raise ValueError(msg)
    return value


def require_tags(value: object) -> tuple[str, ...]:
    """Validate and normalize classifier tags."""
    if not isinstance(value, list):
        msg = "tags must be a list"
        raise ValueError(msg)
    tags = []
    for tag in value:
        if not isinstance(tag, str):
            msg = "tags must contain only strings"
            raise ValueError(msg)
        tags.append(normalize_tag(tag))
    return tuple(sorted(set(tags)))


def load_file_responses(path: Path) -> dict[str, str]:
    """Load deterministic classifier responses from JSON or JSONL."""
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return load_jsonl_responses(content)

    data = json.loads(content)
    if not isinstance(data, dict):
        msg = "mock output JSON must be an object keyed by thought id"
        raise ValueError(msg)
    responses: dict[str, str] = {}
    for thought_id, output in data.items():
        if not isinstance(thought_id, str):
            msg = "mock output keys must be thought ids"
            raise ValueError(msg)
        responses[thought_id] = json.dumps(output) if isinstance(output, dict) else str(output)
    return responses


def load_jsonl_responses(content: str) -> dict[str, str]:
    """Load responses from JSONL rows containing id and output fields."""
    responses: dict[str, str] = {}
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            msg = f"mock output line {line_number} must be an object"
            raise ValueError(msg)
        thought_id = row.get("id")
        output = row.get("output")
        if not isinstance(thought_id, str):
            msg = f"mock output line {line_number} is missing string id"
            raise ValueError(msg)
        responses[thought_id] = json.dumps(output) if isinstance(output, dict) else str(output)
    return responses
