#!/usr/bin/env python3
"""Tests for agent-forge validate-agent.py capability migration checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_AGENT = REPO_ROOT / "skills" / "agent-forge" / "scripts" / "validate-agent.py"


def _write_agent(path: Path, frontmatter: str) -> None:
    path.write_text(
        "---\n"
        f"{frontmatter}"
        "---\n\n"
        "# Purpose\n\n"
        "Validate a fixture agent.\n\n"
        "## Instructions\n\n"
        "1. Read the input.\n"
        "2. Return the result.\n\n"
        "## Pre-flight Checklist\n\n"
        "1. Confirm input exists.\n\n"
        "## Responsibility\n\n"
        "Own validation only.\n\n"
        "## VERIFY\n\n"
        "1. Re-check the result.\n\n"
        "## LEARN\n\n"
        "Record reusable findings.\n",
        encoding="utf-8",
    )


def _run_validate(path: Path, strict: bool = False) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(VALIDATE_AGENT), str(path)]
    if strict:
        args.append("--strict")
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)


def test_validate_agent_warns_on_tools_without_capabilities(tmp_path: Path) -> None:
    """Default validation reports legacy tools-only frontmatter as a warning."""
    agent = tmp_path / "legacy-tools.md"
    _write_agent(
        agent,
        "name: legacy-tools\n"
        "description: Use when testing legacy tool-only frontmatter.\n"
        "tools: Read, Grep, Glob\n"
        "model: sonnet\n",
    )

    result = _run_validate(agent)

    assert result.returncode == 0
    assert "Legacy tools-only frontmatter" in result.stdout


def test_validate_agent_strict_rejects_tools_without_capabilities(tmp_path: Path) -> None:
    """Strict validation fails migrated marketplace agents that still use tools only."""
    agent = tmp_path / "legacy-tools.md"
    _write_agent(
        agent,
        "name: legacy-tools\n"
        "description: Use when testing legacy tool-only frontmatter.\n"
        "tools: Read, Grep, Glob\n"
        "model: sonnet\n",
    )

    result = _run_validate(agent, strict=True)

    assert result.returncode == 1
    assert "Legacy tools-only frontmatter" in result.stdout


def test_validate_agent_accepts_capability_frontmatter_in_strict_mode(tmp_path: Path) -> None:
    """Capability-first frontmatter does not trigger migration errors."""
    agent = tmp_path / "capability-agent.md"
    _write_agent(
        agent,
        "name: capability-agent\n"
        "description: Use when testing capability frontmatter.\n"
        "model:\n"
        "  tier: standard\n"
        "  reasoning: medium\n"
        "  context: large\n"
        "  cost_priority: balanced\n"
        "capabilities:\n"
        "  - read_files\n",
    )

    result = _run_validate(agent, strict=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Legacy tools-only frontmatter" not in result.stdout


def test_validate_agent_strict_rejects_scalar_model_with_manual_model_standard(
    tmp_path: Path,
) -> None:
    """Strict validation catches manual Layer 3 wiring on migrated agents."""
    agent = tmp_path / "manual-model-standard.md"
    _write_agent(
        agent,
        "name: manual-model-standard\n"
        "description: Use when testing manual model standards.\n"
        "model: sonnet\n"
        "model_standards: [claude-sonnet-4-6]\n"
        "capabilities:\n"
        "  - read_files\n",
    )

    result = _run_validate(agent, strict=True)

    assert result.returncode == 1
    assert "Manual model_standards with scalar model is legacy" in result.stdout
