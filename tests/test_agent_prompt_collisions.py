#!/usr/bin/env python3
"""Tests for flat target name-collision enforcement on agents and prompts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"


def run_library(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args],
        capture_output=True,
        text=True,
        cwd=str(project_dir),
    )


def write_collision_catalog(
    project_dir: Path,
    *,
    agent_source: Path,
    prompt_source: Path,
) -> None:
    project_dir.joinpath("library.yaml").write_text(
        f"""
default_dirs:
  agents:
    - default: .claude/agents/
  prompts:
    - default: .claude/commands/
  skills:
    - default: .agents/skills/

library:
  skills: []
  agents:
    - name: same-name-agent
      description: Synthetic agent collision fixture.
      source: {agent_source}
  prompts:
    - name: same-name-prompt
      description: Synthetic prompt collision fixture.
      source: {prompt_source}

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
""".lstrip()
    )


def test_agent_collision_from_different_source_is_blocked(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    project_dir.mkdir()
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "same-name-agent.md").write_text("# Agent A\n")
    (source_b / "same-name-agent.md").write_text("# Agent B\n")
    prompt_source = tmp_path / "same-name-prompt.md"
    prompt_source.write_text("# Prompt\n")

    write_collision_catalog(
        project_dir,
        agent_source=source_a / "same-name-agent.md",
        prompt_source=prompt_source,
    )
    first = run_library(project_dir, "agent", "use", "same-name-agent", "--json")
    assert first.returncode == 0, first.stderr

    write_collision_catalog(
        project_dir,
        agent_source=source_b / "same-name-agent.md",
        prompt_source=prompt_source,
    )
    second = run_library(project_dir, "agent", "use", "same-name-agent", "--json")
    data = json.loads(second.stdout)

    assert second.returncode == 1
    assert data["status"] == "blocked"
    assert "--replace" in data["options"]
    assert "--merge-into=<canonical-repo>" in data["options"]
    assert "--skip" in data["options"]
    assert (project_dir / ".claude" / "agents" / "same-name-agent.md").read_text() == "# Agent A\n"


def test_agent_collision_replace_overwrites(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    project_dir.mkdir()
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "same-name-agent.md").write_text("# Agent A\n")
    (source_b / "same-name-agent.md").write_text("# Agent B\n")
    prompt_source = tmp_path / "same-name-prompt.md"
    prompt_source.write_text("# Prompt\n")

    write_collision_catalog(
        project_dir,
        agent_source=source_a / "same-name-agent.md",
        prompt_source=prompt_source,
    )
    assert run_library(project_dir, "agent", "use", "same-name-agent", "--json").returncode == 0

    write_collision_catalog(
        project_dir,
        agent_source=source_b / "same-name-agent.md",
        prompt_source=prompt_source,
    )
    replaced = run_library(
        project_dir,
        "agent",
        "use",
        "same-name-agent",
        "--replace",
        "--json",
    )

    assert replaced.returncode == 0, replaced.stderr
    assert (project_dir / ".claude" / "agents" / "same-name-agent.md").read_text() == "# Agent B\n"


def test_prompt_collision_from_different_source_is_blocked(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    source_a = tmp_path / "prompt-a.md"
    source_b = tmp_path / "prompt-b.md"
    agent_source = tmp_path / "same-name-agent.md"
    project_dir.mkdir()
    source_a.write_text("# Prompt A\n")
    source_b.write_text("# Prompt B\n")
    agent_source.write_text("# Agent\n")

    write_collision_catalog(project_dir, agent_source=agent_source, prompt_source=source_a)
    first = run_library(project_dir, "prompt", "use", "same-name-prompt", "--json")
    assert first.returncode == 0, first.stderr

    write_collision_catalog(project_dir, agent_source=agent_source, prompt_source=source_b)
    second = run_library(project_dir, "prompt", "use", "same-name-prompt", "--json")
    data = json.loads(second.stdout)

    assert second.returncode == 1
    assert data["status"] == "blocked"
    assert data["data"]["primitive"] == "prompt"
    assert (project_dir / ".claude" / "commands" / "same-name-prompt.md").read_text() == "# Prompt A\n"
