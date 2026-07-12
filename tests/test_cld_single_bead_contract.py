"""Regression tests for cld's single-bead-only contract."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


CLD_BIN = Path(__file__).resolve().parents[1] / "bin" / "cld"


@pytest.mark.parametrize(
    "flag",
    ["-bw", "--bead-wave", "-bl", "--bead-label", "-bi", "--bead-ids"],
)
def test_cld_rejects_multi_bead_dispatch_flags(tmp_path: Path, flag: str) -> None:
    called = tmp_path / "claude-called"
    claude_mock = tmp_path / "claude-mock"
    claude_mock.write_text(
        "#!/bin/sh\n"
        "touch \"$CALLED_FILE\"\n",
        encoding="utf-8",
    )
    claude_mock.chmod(0o755)

    env = dict(os.environ)
    env["CLAUDE_BIN"] = str(claude_mock)
    env["CALLED_FILE"] = str(called)

    result = subprocess.run(
        [str(CLD_BIN), flag, "CL-parent"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert not called.exists()
    assert "cld does not dispatch multi-bead waves" in result.stderr
    assert "wave skills with cmux panes" in result.stderr
    assert "cld -b <bead-id>" in result.stderr


def test_cld_contains_no_wave_dispatch_prompt_or_help_entry() -> None:
    source = CLD_BIN.read_text(encoding="utf-8")

    assert "Wave orchestration request" not in source
    assert "Dispatch wave-orchestrator" not in source
    assert "cld -bw ${bead_id}" not in source
    assert "Waves must be started manually using the wave skills with cmux panes" in source
