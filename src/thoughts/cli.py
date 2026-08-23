"""Command line interface for Thoughts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from sqlite3 import IntegrityError

from thoughts import __version__
from thoughts.db import StatusSummary, capture_thought, initialize, open_store, status_summary
from thoughts.models import VALID_PRIORITIES, VALID_TYPES, NewThought


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
        parser.print_help()
        return 0
    except (FileNotFoundError, IntegrityError, ValueError) as error:
        parser.exit(1, f"thoughts: error: {error}\n")


def main(argv: Sequence[str] | None = None) -> None:
    """Console-script entrypoint."""
    raise SystemExit(run(argv))


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
    print(f"latest_migration: {summary.latest_migration}")
    print("by_type:")
    for thought_type, count in summary.by_type.items():
        print(f"  {thought_type}: {count}")
    print("by_status:")
    for status, count in summary.by_status.items():
        print(f"  {status}: {count}")
