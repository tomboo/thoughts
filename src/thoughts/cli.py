"""Command line interface for Thoughts."""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from sqlite3 import IntegrityError

from thoughts import __version__
from thoughts.classify import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    Classifier,
    FileClassifier,
    MissingClassifier,
    ProcessResult,
    apply_process,
    dry_run_process,
)
from thoughts.db import StatusSummary, capture_thought, initialize, open_store, status_summary
from thoughts.doctor import DoctorResult, run_doctor
from thoughts.export import ProjectionDriftError, export_markdown
from thoughts.models import VALID_PRIORITIES, VALID_TYPES, NewThought
from thoughts.remote import CaptureResponse, ProtocolError, parse_request, receive_capture
from thoughts.search import SearchResult, search_text
from thoughts.submit import (
    ConfigError,
    SubmitOutcome,
    build_request,
    flush_spool,
    load_config,
    spool_depth,
    submit,
)
from thoughts.sync import SyncResult, apply_sync, check_sync


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="thoughts",
        description=(
            "Capture thoughts into a SQLite canonical store and export Obsidian Markdown "
            "projections."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing the .thoughts runtime directory.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize the canonical SQLite store.")

    capture_parser = subparsers.add_parser("capture", help="Capture one canonical thought.")
    capture_parser.add_argument("text", help="Thought body text.")
    capture_parser.add_argument("--title", help="Thought title. Defaults to the first body line.")
    capture_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Tag to add. May be passed more than once.",
    )
    capture_parser.add_argument(
        "--type",
        choices=sorted(VALID_TYPES),
        default="inbox",
        help="Thought type.",
    )
    capture_parser.add_argument("--due", help="Due date as YYYY-MM-DD.")
    capture_parser.add_argument(
        "--priority",
        choices=sorted(VALID_PRIORITIES),
        help="Task priority.",
    )

    subparsers.add_parser("status", help="Show canonical store status.")
    subparsers.add_parser("export-md", help="Export canonical thoughts to Markdown projections.")
    subparsers.add_parser("doctor", help="Run repository consistency diagnostics.")
    sync_parser = subparsers.add_parser(
        "sync",
        help="Validate or import Markdown projection edits.",
    )
    sync_mode = sync_parser.add_mutually_exclusive_group(required=True)
    sync_mode.add_argument("--check", action="store_true", help="Report Markdown edits and issues.")
    sync_mode.add_argument("--apply", action="store_true", help="Import valid Markdown edits.")
    process_parser = subparsers.add_parser(
        "process",
        help="Classify thoughts with reviewed model output.",
    )
    process_mode = process_parser.add_mutually_exclusive_group(required=True)
    process_mode.add_argument("--dry-run", action="store_true", help="Validate proposals only.")
    process_mode.add_argument("--apply", action="store_true", help="Apply approved proposals.")
    process_parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        help="Minimum confidence required before canonical metadata is updated.",
    )
    process_parser.add_argument(
        "--mock-output",
        type=Path,
        help="JSON or JSONL classifier output keyed by thought id.",
    )
    receive_parser = subparsers.add_parser(
        "receive",
        help="Owner-only: create one thought from a JSON capture request on stdin.",
    )
    receive_parser.add_argument(
        "--export",
        action="store_true",
        help="Refresh Markdown projections after a successful create.",
    )
    remote_parser = subparsers.add_parser(
        "remote",
        help="Submit thoughts to the owner machine from a non-owner device.",
    )
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command")
    remote_capture_parser = remote_subparsers.add_parser(
        "capture",
        help="Submit one thought to the owner, spooling locally if it is unreachable.",
    )
    remote_capture_parser.add_argument("text", help="Thought body text.")
    remote_capture_parser.add_argument(
        "--title",
        help="Thought title. Defaults to the first body line.",
    )
    remote_capture_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Tag to add. May be passed more than once.",
    )
    remote_capture_parser.add_argument(
        "--type",
        choices=sorted(VALID_TYPES),
        default="inbox",
        help="Thought type.",
    )
    remote_capture_parser.add_argument("--due", help="Due date as YYYY-MM-DD.")
    remote_capture_parser.add_argument(
        "--priority",
        choices=sorted(VALID_PRIORITIES),
        help="Task priority.",
    )
    remote_subparsers.add_parser("flush", help="Send spooled capture requests to the owner.")
    remote_subparsers.add_parser(
        "status",
        help="Show remote capture configuration and spool depth.",
    )

    search_parser = subparsers.add_parser("search", help="Search canonical thoughts.")
    search_parser.add_argument("query", help="Plain-text search query.")
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results to print.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            db_path = initialize(args.root)
            print(f"Initialized {db_path}")
            return 0
        if args.command == "capture":
            title = args.title if args.title is not None else default_title(args.text)
            with open_store(args.root) as conn:
                thought = capture_thought(
                    conn,
                    NewThought(
                        body=args.text,
                        title=title,
                        thought_type=args.type,
                        due_on=args.due,
                        priority=args.priority,
                        tags=tuple(args.tag),
                    ),
                )
            print(thought.id)
            return 0
        if args.command == "status":
            with open_store(args.root) as conn:
                print_status(status_summary(conn))
            return 0
        if args.command == "export-md":
            with open_store(args.root) as conn:
                result = export_markdown(conn, args.root)
            print(f"Exported {result.exported_count} projection(s)")
            return 0
        if args.command == "doctor":
            with open_store(args.root) as conn:
                doctor_result = run_doctor(conn, args.root)
            print_doctor_result(doctor_result)
            return doctor_result.exit_code
        if args.command == "sync":
            with open_store(args.root) as conn:
                sync_result = (
                    apply_sync(conn, args.root) if args.apply else check_sync(conn, args.root)
                )
            print_sync_result(sync_result, applied=args.apply)
            return 1 if sync_result.has_errors else 0
        if args.command == "process":
            classifier: Classifier = (
                FileClassifier(args.mock_output)
                if args.mock_output is not None
                else MissingClassifier()
            )
            with open_store(args.root) as conn:
                process_result = (
                    apply_process(
                        conn,
                        classifier,
                        confidence_threshold=args.confidence_threshold,
                    )
                    if args.apply
                    else dry_run_process(
                        conn,
                        classifier,
                        confidence_threshold=args.confidence_threshold,
                    )
                )
            print_process_result(process_result, applied=args.apply)
            return 1 if process_result.has_errors else 0
        if args.command == "receive":
            return run_receive(args.root, export=args.export)
        if args.command == "remote":
            return run_remote(parser, args)
        if args.command == "search":
            with open_store(args.root) as conn:
                search_results = search_text(conn, args.query, limit=args.limit)
            print_search_results(search_results)
            return 0
        parser.print_help()
        return 0
    except (
        ConfigError,
        FileNotFoundError,
        IntegrityError,
        ProjectionDriftError,
        RuntimeError,
        ValueError,
    ) as error:
        parser.exit(1, f"thoughts: error: {error}\n")


def main(argv: Sequence[str] | None = None) -> None:
    """Console-script entrypoint."""
    raise SystemExit(run(argv))


def run_receive(root: Path, *, export: bool) -> int:
    """Handle one owner-side capture request read from stdin."""
    payload = sys.stdin.read()
    try:
        request = parse_request(payload)
    except ProtocolError as error:
        print(CaptureResponse(status="rejected", request_id="", error=str(error)).to_json())
        return 1

    with open_store(root) as conn:
        try:
            response = receive_capture(conn, request)
        except (IntegrityError, ValueError) as error:
            rejection = CaptureResponse(
                status="rejected",
                request_id=request.request_id,
                error=str(error),
            )
            print(rejection.to_json())
            return 1
        if export and response.status == "created":
            export_markdown(conn, root)
    print(response.to_json())
    return 0


def run_remote(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Handle non-owner capture submission. Never opens the canonical store."""
    config = load_config()
    if args.remote_command == "capture":
        request = build_request(
            config,
            body=args.text,
            title=args.title,
            thought_type=args.type,
            tags=tuple(args.tag),
            due_on=args.due,
            priority=args.priority,
        )
        outcome = submit(request, config)
        print_submit_outcome(outcome)
        return 0 if outcome.status in {"created", "duplicate", "spooled"} else 1
    if args.remote_command == "flush":
        outcomes = flush_spool(config)
        print(f"flushed: {sum(1 for outcome in outcomes if outcome.status != 'deferred')}")
        print(f"remaining: {spool_depth(config.spool_dir)}")
        for outcome in outcomes:
            print_submit_outcome(outcome, indent="  ")
        return 1 if any(outcome.status == "rejected" for outcome in outcomes) else 0
    if args.remote_command == "status":
        print(f"origin: {config.origin}")
        print(f"owner_command: {shlex.join(config.owner_command)}")
        print(f"spool_dir: {config.spool_dir}")
        print(f"spooled: {spool_depth(config.spool_dir)}")
        return 0
    parser.parse_args(["remote", "--help"])
    return 0


def print_submit_outcome(outcome: SubmitOutcome, *, indent: str = "") -> None:
    """Print a stable human-readable submit outcome."""
    thought_id = outcome.thought_id or "<none>"
    print(f"{indent}{outcome.status}: {outcome.request_id}: {thought_id}")
    if outcome.detail:
        print(f"{indent}  {outcome.detail}")


def default_title(text: str) -> str:
    """Derive a compact title from captured text."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) <= 80:
        return first_line
    return f"{first_line[:77]}..."


def print_status(summary: StatusSummary) -> None:
    """Print a stable human-readable status summary."""
    print(f"thoughts: {summary.total_thoughts}")
    print(f"projections: {summary.projection_count}")
    print(f"unresolved_sync_issues: {summary.unresolved_sync_issues}")
    print(f"remote_capture_requests: {summary.remote_capture_requests}")
    print(f"latest_migration: {summary.latest_migration}")
    print("by_type:")
    for thought_type, count in summary.by_type.items():
        print(f"  {thought_type}: {count}")
    print("by_status:")
    for status, count in summary.by_status.items():
        print(f"  {status}: {count}")


def print_sync_result(result: SyncResult, *, applied: bool) -> None:
    """Print a stable human-readable sync result."""
    action = "Applied" if applied else "Found"
    print(f"{action} {result.applied_count if applied else len(result.updates)} update(s)")
    if result.issues:
        print("issues:")
        for issue in result.issues:
            path = "<database>" if issue.relative_path is None else issue.relative_path.as_posix()
            print(f"  {issue.severity}: {issue.issue_type}: {path}: {issue.message}")


def print_doctor_result(result: DoctorResult) -> None:
    """Print a stable human-readable doctor result."""
    print(f"errors: {result.error_count}")
    print(f"warnings: {result.warning_count}")
    if not result.issues:
        print("ok")
        return
    print("issues:")
    for issue in result.issues:
        path = "<database>" if issue.relative_path is None else issue.relative_path.as_posix()
        thought_id = "<none>" if issue.thought_id is None else issue.thought_id
        print(f"  {issue.severity}: {issue.issue_type}: {path}: {thought_id}: {issue.message}")
        print(f"    repair: {issue.repair}")


def print_process_result(result: ProcessResult, *, applied: bool) -> None:
    """Print a stable human-readable process result."""
    action = "Applied" if applied else "Validated"
    print(f"{action} {result.applied_count if applied else len(result.proposals)} proposal(s)")
    if result.proposals:
        print("proposals:")
        for proposal in result.proposals:
            print(
                "  "
                f"{proposal.thought_id}: "
                f"type={proposal.thought_type} "
                f"status={proposal.status} "
                f"due={proposal.due_on or '<none>'} "
                f"priority={proposal.priority or '<none>'} "
                f"tags={','.join(proposal.tags) or '<none>'} "
                f"confidence={proposal.confidence:.2f}"
            )
    if result.issues:
        print("issues:")
        for issue in result.issues:
            print(f"  {issue.severity}: {issue.issue_type}: {issue.thought_id}: {issue.message}")


def print_search_results(results: list[SearchResult]) -> None:
    """Print stable human-readable search results."""
    print(f"results: {len(results)}")
    for result in results:
        snippet = result.body.strip().splitlines()[0] if result.body.strip() else ""
        print(f"  {result.thought_id}: {result.title}")
        if snippet:
            print(f"    {snippet}")
