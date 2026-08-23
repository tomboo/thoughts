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
