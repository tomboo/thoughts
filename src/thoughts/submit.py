"""Client-side remote capture: submit to the owner, spool when it is unreachable.

Nothing in this module opens the canonical store. A non-owner device that
cannot reach the owner accumulates queued requests on local disk; it never
becomes a second writer.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from thoughts.remote import (
    CaptureRequest,
    CaptureResponse,
    ProtocolError,
    encode_request,
    new_request_id,
    parse_request,
    parse_response,
)

CONFIG_ENV_VAR = "THOUGHTS_REMOTE_CONFIG"
OWNER_COMMAND_ENV_VAR = "THOUGHTS_OWNER_COMMAND"
ORIGIN_ENV_VAR = "THOUGHTS_ORIGIN"
SPOOL_ENV_VAR = "THOUGHTS_SPOOL_DIR"
DEFAULT_TIMEOUT_SECONDS = 20.0
REJECTED_DIR_NAME = "rejected"


class ConfigError(RuntimeError):
    """The remote capture client is not configured."""


class TransportError(RuntimeError):
    """The owner command could not be reached or did not answer usably."""


@dataclass(frozen=True)
class RemoteConfig:
    """Where the owner lives and how this device identifies itself."""

    owner_command: tuple[str, ...]
    origin: str
    spool_dir: Path
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class SubmitOutcome:
    """The result of one submit attempt, including the offline path."""

    status: str
    request_id: str
    thought_id: str | None = None
    detail: str | None = None


def default_config_path() -> Path:
    """Return the remote client configuration path."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "thoughts" / "remote.json"


def default_spool_dir() -> Path:
    """Return the offline spool directory."""
    override = os.environ.get(SPOOL_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "thoughts" / "spool"


def load_config() -> RemoteConfig:
    """Resolve remote client configuration from the environment, then a config file."""
    file_settings = read_config_file(default_config_path())

    command_source = os.environ.get(OWNER_COMMAND_ENV_VAR)
    if command_source:
        owner_command = tuple(shlex.split(command_source))
    else:
        owner_command = config_command(file_settings.get("owner_command"))
    if not owner_command:
        msg = (
            "remote capture is not configured: set "
            f"{OWNER_COMMAND_ENV_VAR} or add \"owner_command\" to {default_config_path()}"
        )
        raise ConfigError(msg)

    origin = os.environ.get(ORIGIN_ENV_VAR) or config_text(file_settings.get("origin"), "origin")
    if not origin:
        msg = (
            "remote capture is not configured: set "
            f"{ORIGIN_ENV_VAR} or add \"origin\" to {default_config_path()}"
        )
        raise ConfigError(msg)

    timeout = config_timeout(file_settings.get("timeout_seconds"))
    return RemoteConfig(
        owner_command=owner_command,
        origin=origin,
        spool_dir=default_spool_dir(),
        timeout_seconds=timeout,
    )


def read_config_file(path: Path) -> dict[str, object]:
    """Read the optional JSON config file."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        msg = f"invalid remote config {path}: {error}"
        raise ConfigError(msg) from error
    if not isinstance(payload, dict):
        msg = f"invalid remote config {path}: expected a JSON object"
        raise ConfigError(msg)
    return payload


def config_command(value: object) -> tuple[str, ...]:
    """Read the owner command from config as an argv list."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
        msg = "owner_command must be a list of strings"
        raise ConfigError(msg)
    return tuple(str(part) for part in value)


def config_text(value: object, key: str) -> str | None:
    """Read an optional string setting from config."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise ConfigError(msg)
    return value


def config_timeout(value: object) -> float:
    """Read the owner command timeout from config."""
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        msg = "timeout_seconds must be a positive number"
        raise ConfigError(msg)
    return float(value)


def send(request: CaptureRequest, config: RemoteConfig) -> CaptureResponse:
    """Pipe one capture request to the owner command and read its response."""
    try:
        completed = subprocess.run(
            list(config.owner_command),
            input=encode_request(request),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except OSError as error:
        msg = f"could not run owner command: {error}"
        raise TransportError(msg) from error
    except subprocess.TimeoutExpired as error:
        msg = f"owner command timed out after {config.timeout_seconds:g}s"
        raise TransportError(msg) from error

    output = completed.stdout.strip()
    if not output:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        msg = f"owner command returned no response: {detail}"
        raise TransportError(msg)
    try:
        return parse_response(output)
    except ProtocolError as error:
        msg = f"owner command returned an unusable response: {error}"
        raise TransportError(msg) from error


def submit(request: CaptureRequest, config: RemoteConfig) -> SubmitOutcome:
    """Send a request, spooling it locally if the owner cannot be reached."""
    try:
        response = send(request, config)
    except TransportError as error:
        spool_path = spool_request(request, config.spool_dir)
        return SubmitOutcome(
            status="spooled",
            request_id=request.request_id,
            detail=f"{error}; queued at {spool_path}",
        )
    return SubmitOutcome(
        status=response.status,
        request_id=response.request_id or request.request_id,
        thought_id=response.thought_id,
        detail=response.error,
    )


def build_request(
    config: RemoteConfig,
    *,
    body: str,
    title: str | None = None,
    thought_type: str = "inbox",
    tags: tuple[str, ...] = (),
    due_on: str | None = None,
    priority: str | None = None,
) -> CaptureRequest:
    """Build a capture request stamped with this device's origin and clock."""
    return CaptureRequest(
        request_id=new_request_id(),
        origin=config.origin,
        body=body,
        title=title,
        thought_type=thought_type,
        tags=tags,
        due_on=due_on,
        priority=priority,
        submitted_at=utc_timestamp(),
    )


def utc_timestamp() -> str:
    """Return the current time in the timestamp format the store uses."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def spool_request(request: CaptureRequest, spool_dir: Path) -> Path:
    """Persist a request for a later flush, keyed by its idempotent request id."""
    spool_dir.mkdir(parents=True, exist_ok=True)
    path = spool_dir / f"{request.request_id}.json"
    path.write_text(encode_request(request) + "\n", encoding="utf-8")
    return path


def iter_spooled(spool_dir: Path) -> Iterator[tuple[Path, CaptureRequest]]:
    """Yield spooled requests oldest-first, skipping the rejected sidelines."""
    if not spool_dir.exists():
        return
    for path in sorted(spool_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
        yield path, parse_request(path.read_text(encoding="utf-8"))


def spool_depth(spool_dir: Path) -> int:
    """Count requests waiting to be flushed."""
    if not spool_dir.exists():
        return 0
    return len(list(spool_dir.glob("*.json")))


def flush_spool(config: RemoteConfig) -> list[SubmitOutcome]:
    """Drain the spool oldest-first, stopping at the first transport failure.

    A spooled file is deleted only once the owner confirms it holds the
    thought. A request the owner rejects is moved aside instead of being
    retried forever.
    """
    outcomes: list[SubmitOutcome] = []
    for path, request in iter_spooled(config.spool_dir):
        try:
            response = send(request, config)
        except TransportError as error:
            outcomes.append(
                SubmitOutcome(
                    status="deferred",
                    request_id=request.request_id,
                    detail=str(error),
                )
            )
            break
        if response.accepted:
            path.unlink(missing_ok=True)
        else:
            path.rename(reject_path(config.spool_dir, path))
        outcomes.append(
            SubmitOutcome(
                status=response.status,
                request_id=request.request_id,
                thought_id=response.thought_id,
                detail=response.error,
            )
        )
    return outcomes


def reject_path(spool_dir: Path, path: Path) -> Path:
    """Return the sidelined location for a request the owner rejected."""
    rejected_dir = spool_dir / REJECTED_DIR_NAME
    rejected_dir.mkdir(parents=True, exist_ok=True)
    return rejected_dir / path.name
