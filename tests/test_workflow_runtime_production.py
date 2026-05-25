"""Production tests for the ADR-0006 workflow runtime."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

from lib.workflow_runtime import SpineConstraintChecker, WorkflowRuntime  # noqa: E402


def test_agent_extraction_ignores_commented_calls() -> None:
    """AC2: agent() calls in line comments must not be extracted."""
    source = textwrap.dedent(
        """
        export const meta = {"name": "t"};
        // await agent("this is a comment", {})
        /* await agent("block comment", {"slot": "impl"}) */
        await agent("real call", {"slot": "implementation"});
        """
    )

    calls = WorkflowRuntime._extract_agent_calls(source)

    assert len(calls) == 1
    assert calls[0]["prompt"] == "real call"


def test_agent_extraction_ignores_string_literals() -> None:
    """AC2: agent() text inside string literals must not be extracted."""
    source = textwrap.dedent(
        """
        export const meta = {"name": "t"};
        const example = 'await agent("inside string", {})';
        await agent("real", {"slot": "impl"});
        """
    )

    calls = WorkflowRuntime._extract_agent_calls(source)

    assert len(calls) == 1
    assert calls[0]["prompt"] == "real"
