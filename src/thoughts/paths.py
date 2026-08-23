"""Repository path helpers."""

from __future__ import annotations

from pathlib import Path

RUNTIME_DIR_NAME = ".thoughts"
DATABASE_FILE_NAME = "thoughts.sqlite"
INBOX_DIR_NAME = "Inbox"


def runtime_dir(root: Path) -> Path:
    """Return the tool-owned runtime directory for a project root."""
    return root / RUNTIME_DIR_NAME


def database_path(root: Path) -> Path:
    """Return the canonical SQLite database path for a project root."""
    return runtime_dir(root) / DATABASE_FILE_NAME


def projection_dirs(root: Path) -> list[Path]:
    """Return projection directories created during initialization."""
    return [root / INBOX_DIR_NAME]
