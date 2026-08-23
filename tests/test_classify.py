from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoughts.classify import (
    CLASSIFIER_OUTPUT_SCHEMA,
    Classifier,
    apply_process,
    dry_run_process,
    validate_classifier_output,
)
from thoughts.cli import run
from thoughts.db import capture_thought, get_thought, initialize, open_store
from thoughts.models import NewThought, Thought


class FakeClassifier:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs

    def classify(self, thought: Thought) -> str:
        return self.outputs[thought.id]


def test_mock_model_output_is_validated() -> None:
    proposal = validate_classifier_output(
        "th_test",
        json.dumps(
            {
                "type": "task",
                "status": "active",
                "due": "2026-08-25",
                "priority": "high",
                "tags": ["Home", "#Errands"],
                "confidence": 0.91,
            }
        ),
    )

    assert CLASSIFIER_OUTPUT_SCHEMA["required"] == [
        "type",
        "status",
        "due",
        "priority",
        "tags",
        "confidence",
    ]
    assert proposal.thought_type == "task"
    assert proposal.due_on == "2026-08-25"
    assert proposal.priority == "high"
    assert proposal.tags == ("errands", "home")
    assert proposal.confidence == 0.91


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid classifier JSON"):
        validate_classifier_output("th_test", "{not json")


def test_unknown_enum_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="invalid type: reminder"):
        validate_classifier_output(
            "th_test",
            json.dumps(
                {
                    "type": "reminder",
                    "status": "active",
                    "due": None,
                    "priority": None,
                    "tags": [],
                    "confidence": 0.9,
                }
            ),
        )


def test_low_confidence_creates_review_issue_instead_of_updating_canonical_state(
    tmp_path: Path,
) -> None:
    thought_id = captured_thought(tmp_path)
    classifier = FakeClassifier(
        {
            thought_id: json.dumps(
                {
                    "type": "task",
                    "status": "active",
                    "due": "2026-08-25",
                    "priority": "high",
                    "tags": ["Review"],
                    "confidence": 0.4,
                }
            )
        }
    )

    with open_store(tmp_path) as conn:
        result = apply_process(conn, classifier)
        thought = get_thought(conn, thought_id)
        issue = conn.execute(
            "SELECT issue_type, severity, message FROM sync_issues WHERE resolved_at IS NULL"
        ).fetchone()

    assert result.applied_count == 0
    assert thought.thought_type == "inbox"
    assert thought.due_on is None
    assert thought.priority is None
    assert thought.tags == ()
    assert issue["issue_type"] == "classification_low_confidence"
    assert issue["severity"] == "warning"


def test_dry_run_does_not_mutate_sqlite(tmp_path: Path) -> None:
    thought_id = captured_thought(tmp_path)
    classifier = high_confidence_classifier(thought_id)

    with open_store(tmp_path) as conn:
        result = dry_run_process(conn, classifier)
        thought = get_thought(conn, thought_id)
        issue_count = conn.execute("SELECT COUNT(*) FROM sync_issues").fetchone()[0]

    assert len(result.proposals) == 1
    assert result.applied_count == 0
    assert thought.thought_type == "inbox"
    assert thought.title == "Original title"
    assert thought.body == "Original body"
    assert thought.tags == ()
    assert issue_count == 0


def test_apply_mutates_only_approved_canonical_fields(tmp_path: Path) -> None:
    thought_id = captured_thought(tmp_path)
    classifier = high_confidence_classifier(thought_id)

    with open_store(tmp_path) as conn:
        result = apply_process(conn, classifier)
        thought = get_thought(conn, thought_id)

    assert result.applied_count == 1
    assert not result.issues
    assert thought.title == "Original title"
    assert thought.body == "Original body"
    assert thought.thought_type == "task"
    assert thought.status == "flagged"
    assert thought.due_on == "2026-08-25"
    assert thought.priority == "medium"
    assert thought.tags == ("followup", "work")


def test_process_cli_accepts_mock_output_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thought_id = captured_thought(tmp_path)
    output_path = tmp_path / "classifier-output.json"
    output_path.write_text(
        json.dumps(
            {
                thought_id: {
                    "type": "note",
                    "status": "active",
                    "due": None,
                    "priority": None,
                    "tags": ["Reference"],
                    "confidence": 0.95,
                }
            }
        ),
        encoding="utf-8",
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
    output = capsys.readouterr().out

    with open_store(tmp_path) as conn:
        thought = get_thought(conn, thought_id)

    assert "Applied 1 proposal(s)" in output
    assert thought.thought_type == "note"
    assert thought.tags == ("reference",)


def captured_thought(tmp_path: Path) -> str:
    initialize(tmp_path)
    with open_store(tmp_path) as conn:
        thought = capture_thought(
            conn,
            NewThought(body="Original body", title="Original title"),
        )
    return thought.id


def high_confidence_classifier(thought_id: str) -> Classifier:
    return FakeClassifier(
        {
            thought_id: json.dumps(
                {
                    "type": "task",
                    "status": "flagged",
                    "due": "2026-08-25",
                    "priority": "medium",
                    "tags": ["Work", "followup"],
                    "confidence": 0.92,
                }
            )
        }
    )
