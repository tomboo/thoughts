"""Command line interface for Thoughts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from thoughts import __version__


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
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Console-script entrypoint."""
    raise SystemExit(run(argv))
