#!/usr/bin/env python3
"""Fleet checks for cognovis-core capability-based agent sources."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
COGNOVIS_CORE = REPO_ROOT.parent / "cognovis-core"
AGENTS_DIR = COGNOVIS_CORE / "agents"
AGENT_BASES_DIR = COGNOVIS_CORE / "agent-bases"
MODEL_STANDARDS_DIR = COGNOVIS_CORE / "model-standards"
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"


pytestmark = pytest.mark.skipif(
    not AGENTS_DIR.exists(),
    reason="cognovis-core sibling checkout is not available",
)


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path.name} has no frontmatter"
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def test_cognovis_agents_are_capability_first() -> None:
    """Every first-party agent uses capability declarations after CL-2yp."""
    for path in sorted(AGENTS_DIR.glob("*.md")):
        frontmatter = _frontmatter(path)
        assert frontmatter.get("agent_base") == "auto", f"{path.name} missing agent_base: auto"
        assert "agent_base_extends" not in frontmatter, f"{path.name} still uses agent_base_extends"
        assert "capabilities" in frontmatter, f"{path.name} missing capabilities"
        assert isinstance(frontmatter.get("model"), dict), f"{path.name} model is not a mapping"
        assert "tools" not in frontmatter, f"{path.name} still has tools"
        assert "model_standards" not in frontmatter, f"{path.name} still has model_standards"


def test_cognovis_agents_have_no_stale_codex_subagent_claims() -> None:
    """Migrated Codex prose no longer says subagents are unavailable."""
    stale_patterns = [
        "no subagent spawning is available in Codex",
        "no subagent spawning",
    ]
    for path in sorted(AGENTS_DIR.glob("*.md")):
        text = path.read_text()
        for pattern in stale_patterns:
            assert pattern not in text, f"{path.name} contains stale Codex claim: {pattern}"


def test_researcher_preserves_searxng_only_tool_contract() -> None:
    """The researcher agent does not receive generic built-in web-search tools."""
    frontmatter = _frontmatter(AGENTS_DIR / "researcher.md")
    assert "search_searxng" in frontmatter["capabilities"]
    assert "search_web" not in frontmatter["capabilities"]


def test_cognovis_agents_build_for_claude_and_codex(tmp_path: Path) -> None:
    """All migrated agents build through the unified agent builder."""
    for source in sorted(AGENTS_DIR.glob("*.md")):
        output_dir = tmp_path / source.stem
        result = subprocess.run(
            [
                sys.executable,
                str(BUILD_AGENT),
                str(source),
                "--harness",
                "all",
                "--output-dir",
                str(output_dir),
                "--agent-bases-dir",
                str(AGENT_BASES_DIR),
                "--model-standards-dir",
                str(MODEL_STANDARDS_DIR),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{source.name} failed:\n{result.stderr}"
        assert list(output_dir.glob("*.md")), f"{source.name} emitted no Claude artifact"
        assert list(output_dir.glob("*.toml")), f"{source.name} emitted no Codex artifact"


def test_researcher_build_keeps_claude_builtin_web_tools_blocked(tmp_path: Path) -> None:
    """The generated Claude researcher grants SearXNG, not WebSearch/WebFetch."""
    output_dir = tmp_path / "researcher"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(AGENTS_DIR / "researcher.md"),
            "--harness",
            "claude",
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(AGENT_BASES_DIR),
            "--model-standards-dir",
            str(MODEL_STANDARDS_DIR),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    artifact = next(output_dir.glob("*.md"))
    built_frontmatter = yaml.safe_load(artifact.read_text().split("---", 2)[1]) or {}
    tools = built_frontmatter.get("tools", "")
    assert "mcp__searxng__searxng_web_search" in tools
    assert "WebSearch" not in tools
    assert "WebFetch" not in tools
