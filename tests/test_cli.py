from __future__ import annotations

import pytest

from thoughts.cli import main, run


def test_cli_help_renders(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "usage: thoughts" in output
    assert "SQLite canonical store" in output


def test_cli_run_without_command_exits_cleanly() -> None:
    assert run([]) == 0


def test_cli_init_capture_status(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--root", str(tmp_path), "init"]) == 0
    init_output = capsys.readouterr().out
    assert "Initialized" in init_output

    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "capture",
                "Remember durable IDs",
                "--type",
                "note",
                "--tag",
                "Design",
            ]
        )
        == 0
    )
    capture_output = capsys.readouterr().out.strip()
    assert capture_output.startswith("th_")

    assert run(["--root", str(tmp_path), "status"]) == 0
    status_output = capsys.readouterr().out
    assert "thoughts: 1" in status_output
    assert "latest_migration: 1" in status_output
    assert "  note: 1" in status_output

    assert run(["--root", str(tmp_path), "export-md"]) == 0
    export_output = capsys.readouterr().out
    assert "Exported 1 projection(s)" in export_output
    assert list((tmp_path / "Inbox").glob("*.md"))
