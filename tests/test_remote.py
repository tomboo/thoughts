from __future__ import annotations

import json
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from thoughts.cli import run
from thoughts.db import get_thought, initialize, open_store
from thoughts.remote import (
    CaptureRequest,
    ProtocolError,
    encode_request,
    parse_request,
    receive_capture,
)
from thoughts.submit import (
    ConfigError,
    RemoteConfig,
    TransportError,
    build_request,
    flush_spool,
    load_config,
    send,
    spool_depth,
    spool_request,
    submit,
)


def test_receive_creates_one_thought_with_remote_provenance(tmp_path: Path) -> None:
    initialize_root(tmp_path)
    request = sample_request()

    with open_store(tmp_path) as conn:
        response = receive_capture(conn, request)
        thought = get_thought(conn, str(response.thought_id))
        total = thought_count(conn)

    assert response.status == "created"
    assert response.request_id == request.request_id
    assert total == 1
    assert thought.body == "Remote body"
    assert thought.title == "Remote title"
    assert thought.thought_type == "note"
    assert thought.tags == ("capture", "remote")
    assert thought.source == "remote:macbook"


def test_replayed_request_id_is_idempotent(tmp_path: Path) -> None:
    initialize_root(tmp_path)
    request = sample_request()

    with open_store(tmp_path) as conn:
        first = receive_capture(conn, request)
        second = receive_capture(conn, request)
        total = thought_count(conn)
        recorded = conn.execute("SELECT COUNT(*) FROM capture_requests").fetchone()[0]

    assert first.status == "created"
    assert second.status == "duplicate"
    assert second.thought_id == first.thought_id
    assert total == 1
    assert recorded == 1


def test_receive_defaults_title_from_body(tmp_path: Path) -> None:
    initialize_root(tmp_path)
    request = sample_request(title=None, body="First line\nSecond line")

    with open_store(tmp_path) as conn:
        response = receive_capture(conn, request)
        thought = get_thought(conn, str(response.thought_id))

    assert thought.title == "First line"


def test_invalid_request_writes_nothing(tmp_path: Path) -> None:
    initialize_root(tmp_path)
    request = sample_request(thought_type="not-a-type")

    with open_store(tmp_path) as conn:
        with pytest.raises(ValueError):
            receive_capture(conn, request)
        total = thought_count(conn)
        recorded = conn.execute("SELECT COUNT(*) FROM capture_requests").fetchone()[0]

    assert total == 0
    assert recorded == 0


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps([1, 2, 3]),
        json.dumps({"protocol_version": 2, "request_id": "req_1", "origin": "a", "thought": {}}),
        json.dumps({"protocol_version": 1, "origin": "a", "thought": {"body": "x"}}),
        json.dumps(
            {
                "protocol_version": 1,
                "request_id": "req_1",
                "origin": "Not Valid",
                "thought": {"body": "x"},
            }
        ),
        json.dumps(
            {
                "protocol_version": 1,
                "request_id": "req_1",
                "origin": "a",
                "thought": {"body": "x"},
                "run_this": "rm -rf /",
            }
        ),
        json.dumps(
            {
                "protocol_version": 1,
                "request_id": "req_1",
                "origin": "a",
                "thought": {"body": "x", "status": "done"},
            }
        ),
        json.dumps({"protocol_version": 1, "request_id": "req_1", "origin": "a", "thought": {}}),
    ],
)
def test_malformed_requests_are_rejected(payload: str) -> None:
    with pytest.raises(ProtocolError):
        parse_request(payload)


def test_request_round_trips_through_the_wire_format() -> None:
    request = sample_request()

    decoded = parse_request(encode_request(request))

    assert decoded == request


def test_client_cannot_forge_a_local_source(tmp_path: Path) -> None:
    initialize_root(tmp_path)
    request = parse_request(
        json.dumps(
            {
                "protocol_version": 1,
                "request_id": "req_forge",
                "origin": "macbook",
                "thought": {"body": "Pretending to be local"},
            }
        )
    )

    with open_store(tmp_path) as conn:
        response = receive_capture(conn, request)
        thought = get_thought(conn, str(response.thought_id))

    assert thought.source == "remote:macbook"


def test_receive_cli_creates_and_exports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_root(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", StubStdin(encode_request(sample_request())))

    assert run(["--root", str(tmp_path), "receive", "--export"]) == 0

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "created"
    assert payload["thought_id"].startswith("th_")
    assert list((tmp_path / "Inbox").glob("*.md"))


def test_receive_cli_rejects_malformed_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_root(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", StubStdin("{"))

    assert run(["--root", str(tmp_path), "receive"]) == 1

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "rejected"
    assert "error" in payload

    with open_store(tmp_path) as conn:
        assert thought_count(conn) == 0


def test_remote_capture_reaches_owner_sqlite(
    owner_root: Path,
    config: RemoteConfig,
) -> None:
    request = build_request(config, body="Captured from a non-owner device", thought_type="note")

    outcome = submit(request, config)

    with open_store(owner_root) as conn:
        assert thought_count(conn) == 1
        thought = get_thought(conn, str(outcome.thought_id))

    assert outcome.status == "created"
    assert thought.source == "remote:macbook"


def test_remote_capture_spools_when_owner_is_unreachable(
    owner_root: Path,
    config: RemoteConfig,
) -> None:
    broken = RemoteConfig(
        owner_command=("/nonexistent/owner-command",),
        origin=config.origin,
        spool_dir=config.spool_dir,
    )
    request = build_request(broken, body="Captured while offline")

    outcome = submit(request, broken)

    with open_store(owner_root) as conn:
        assert thought_count(conn) == 0
    assert outcome.status == "spooled"
    assert spool_depth(config.spool_dir) == 1


def test_flush_drains_the_spool_into_owner_sqlite(
    owner_root: Path,
    config: RemoteConfig,
) -> None:
    broken = RemoteConfig(
        owner_command=("/nonexistent/owner-command",),
        origin=config.origin,
        spool_dir=config.spool_dir,
    )
    submit(build_request(broken, body="First offline thought"), broken)
    submit(build_request(broken, body="Second offline thought"), broken)
    assert spool_depth(config.spool_dir) == 2

    outcomes = flush_spool(config)

    with open_store(owner_root) as conn:
        assert thought_count(conn) == 2
    assert [outcome.status for outcome in outcomes] == ["created", "created"]
    assert spool_depth(config.spool_dir) == 0


def test_flush_of_an_already_received_request_does_not_duplicate(
    owner_root: Path,
    config: RemoteConfig,
) -> None:
    request = build_request(config, body="Response was lost on the way back")
    submit(request, config)
    # Simulate a client that never saw the response and retried from its spool.
    spool_request(request, config.spool_dir)

    outcomes = flush_spool(config)

    with open_store(owner_root) as conn:
        assert thought_count(conn) == 1
    assert [outcome.status for outcome in outcomes] == ["duplicate"]
    assert spool_depth(config.spool_dir) == 0


def test_flush_sidelines_a_rejected_request(
    owner_root: Path,
    config: RemoteConfig,
) -> None:
    bad = CaptureRequest(
        request_id="req_bad",
        origin=config.origin,
        body="Body is fine but the type is not",
        thought_type="not-a-type",
    )
    spool_request(bad, config.spool_dir)

    outcomes = flush_spool(config)

    with open_store(owner_root) as conn:
        assert thought_count(conn) == 0
    assert [outcome.status for outcome in outcomes] == ["rejected"]
    assert spool_depth(config.spool_dir) == 0
    assert (config.spool_dir / "rejected" / "req_bad.json").exists()


def test_flush_stops_at_the_first_transport_failure(config: RemoteConfig) -> None:
    spool_request(build_request(config, body="One"), config.spool_dir)
    spool_request(build_request(config, body="Two"), config.spool_dir)
    broken = RemoteConfig(
        owner_command=("/nonexistent/owner-command",),
        origin=config.origin,
        spool_dir=config.spool_dir,
    )

    outcomes = flush_spool(broken)

    assert [outcome.status for outcome in outcomes] == ["deferred"]
    assert spool_depth(config.spool_dir) == 2


def test_send_rejects_an_owner_that_answers_with_garbage(
    tmp_path: Path,
    config: RemoteConfig,
) -> None:
    garbage = write_script(tmp_path / "garbage.sh", "echo 'this is not json'\n")
    broken = RemoteConfig(
        owner_command=(str(garbage),),
        origin=config.origin,
        spool_dir=config.spool_dir,
    )

    with pytest.raises(TransportError):
        send(build_request(broken, body="x"), broken)


def test_remote_client_never_opens_a_local_store(
    tmp_path: Path,
    config: RemoteConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client runs from a directory with no runtime, proving it cannot write locally."""
    client_root = tmp_path / "client"
    client_root.mkdir()
    monkeypatch.setenv("THOUGHTS_OWNER_COMMAND", " ".join(config.owner_command))
    monkeypatch.setenv("THOUGHTS_ORIGIN", config.origin)
    monkeypatch.setenv("THOUGHTS_SPOOL_DIR", str(config.spool_dir))

    assert run(["--root", str(client_root), "remote", "capture", "From a bare client"]) == 0

    assert not (client_root / ".thoughts").exists()


def test_remote_status_reports_configuration(
    config: RemoteConfig,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOUGHTS_OWNER_COMMAND", " ".join(config.owner_command))
    monkeypatch.setenv("THOUGHTS_ORIGIN", config.origin)
    monkeypatch.setenv("THOUGHTS_SPOOL_DIR", str(config.spool_dir))
    capsys.readouterr()

    assert run(["remote", "status"]) == 0

    output = capsys.readouterr().out
    assert "origin: macbook" in output
    assert "spooled: 0" in output


def test_unconfigured_client_fails_loudly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THOUGHTS_OWNER_COMMAND", raising=False)
    monkeypatch.delenv("THOUGHTS_ORIGIN", raising=False)
    monkeypatch.setenv("THOUGHTS_REMOTE_CONFIG", str(tmp_path / "missing.json"))

    with pytest.raises(ConfigError):
        load_config()


def test_config_file_supplies_owner_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "remote.json"
    config_path.write_text(
        json.dumps({"owner_command": ["ssh", "owner", "thoughts receive"], "origin": "iphone"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("THOUGHTS_OWNER_COMMAND", raising=False)
    monkeypatch.delenv("THOUGHTS_ORIGIN", raising=False)
    monkeypatch.setenv("THOUGHTS_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("THOUGHTS_SPOOL_DIR", str(tmp_path / "spool"))

    loaded = load_config()

    assert loaded.owner_command == ("ssh", "owner", "thoughts receive")
    assert loaded.origin == "iphone"


@pytest.fixture
def owner_root(tmp_path: Path) -> Path:
    """An initialized canonical store standing in for the owner machine."""
    root = tmp_path / "owner"
    root.mkdir()
    initialize_root(root)
    return root


@pytest.fixture
def config(tmp_path: Path, owner_root: Path) -> Iterator[RemoteConfig]:
    """A client configured to reach the owner store through a local receiver."""
    script = write_script(
        tmp_path / "owner-command.sh",
        f'exec {sys.executable} -m thoughts --root {owner_root} receive\n',
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    yield RemoteConfig(
        owner_command=(str(script),),
        origin="macbook",
        spool_dir=tmp_path / "spool",
    )


class StubStdin:
    """Minimal stdin stand-in for CLI tests."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> str:
        return self._payload


def initialize_root(root: Path) -> None:
    """Initialize a canonical store without going through the CLI printer."""
    initialize(root)


def thought_count(conn) -> int:  # type: ignore[no-untyped-def]
    return int(conn.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0])


def sample_request(
    *,
    body: str = "Remote body",
    title: str | None = "Remote title",
    thought_type: str = "note",
) -> CaptureRequest:
    return CaptureRequest(
        request_id="req_sample",
        origin="macbook",
        body=body,
        title=title,
        thought_type=thought_type,
        tags=("capture", "remote"),
        submitted_at="2026-08-23T21:00:00.000Z",
    )


def write_script(path: Path, command: str, env: dict[str, str] | None = None) -> Path:
    """Write an executable shell script used as a stub owner command."""
    exports = "".join(f'export {key}="{value}"\n' for key, value in (env or {}).items())
    path.write_text(f"#!/bin/sh\n{exports}{command}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path
