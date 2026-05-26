"""Tests for compact filtering of Codex JSONL bead output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "filter-codex-jsonl.py"


def _run_filter(lines: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )


def test_filter_suppresses_command_noise_but_preserves_markers() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "bd show noisy",
            "aggregated_output": (
                "huge bead json should not print\n"
                "## LEAF_DISPATCH workflow=full slot=implementation adapter=cursor-composer\n"
                "regular command output should not print\n"
                "## CURSOR_AGENT_START adapter=cursor-impl model=composer-2.5\n"
            ),
            "exit_code": 0,
        },
    }

    result = _run_filter([
        "Reading additional input from stdin...",
        json.dumps(event),
    ])

    assert result.returncode == 0
    assert "## LEAF_DISPATCH workflow=full" in result.stdout
    assert "## CURSOR_AGENT_START adapter=cursor-impl" in result.stdout
    assert "huge bead json" not in result.stdout
    assert "regular command output" not in result.stdout
    assert "Reading additional input" not in result.stdout


def test_filter_bounds_agent_messages() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": "x" * 20,
        },
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(event) + "\n",
        capture_output=True,
        text=True,
        check=False,
        env={"CDX_COMPACT_AGENT_MESSAGE_LIMIT": "8"},
    )

    assert result.returncode == 0
    assert "xxxxxxxx" in result.stdout
    assert "truncated 12 chars" in result.stdout
