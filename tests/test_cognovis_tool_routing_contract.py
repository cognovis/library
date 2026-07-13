"""Cross-harness contract tests for typed cognovis-tools bead mutations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
COGNOVIS_CORE = (
    Path(os.environ["COGNOVIS_CORE"]).expanduser()
    if os.environ.get("COGNOVIS_CORE")
    else REPO_ROOT.parent / "cognovis-core"
)
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"
MUTATING_AGENTS = {
    "bead-author",
    "bead-orchestrator",
    "quick-fix",
    "session-close",
    "wave-orchestrator",
}
MUTATING_SKILLS = {
    "beads",
    "billing-reviewer",
    "bug-triage",
    "compound",
    "impl",
    "intake",
    "plan",
    "refactor-note",
    "retro",
    "review-conventions",
    "session-close",
    "vision",
    "vision-author",
    "wave-dispatch",
    "workplan",
}
TYPED_BEAD_TOOLS = {
    "mcp__cognovis-tools__bead_show",
    "mcp__cognovis-tools__bead_ready",
    "mcp__cognovis-tools__bead_list",
    "mcp__cognovis-tools__bead_search",
    "mcp__cognovis-tools__bead_repos",
    "mcp__cognovis-tools__bead_create",
    "mcp__cognovis-tools__bead_claim",
    "mcp__cognovis-tools__bead_update",
    "mcp__cognovis-tools__bead_update_notes",
    "mcp__cognovis-tools__bead_review_write",
    "mcp__cognovis-tools__bead_close",
    "mcp__cognovis-tools__bead_dep_add",
    "mcp__cognovis-tools__bead_dep_remove",
    "mcp__cognovis-tools__bead_dolt_sync",
}


pytestmark = pytest.mark.skipif(
    not (COGNOVIS_CORE / "agents").exists(),
    reason="cognovis-core sibling checkout is not available",
)


def _build(agent_name: str, harness: str, output_dir: Path) -> Path:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(COGNOVIS_CORE / "agents" / f"{agent_name}.md"),
            "--harness",
            harness,
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(COGNOVIS_CORE / "agent-bases"),
            "--model-standards-dir",
            str(COGNOVIS_CORE / "model-standards"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    suffix = ".md" if harness == "claude" else ".toml"
    return next(output_dir.glob(f"*{suffix}"))


@pytest.mark.parametrize("agent_name", sorted(MUTATING_AGENTS))
def test_mutating_agents_receive_cognovis_tools_in_both_harnesses(
    agent_name: str, tmp_path: Path
) -> None:
    claude_artifact = _build(agent_name, "claude", tmp_path / agent_name / "claude")
    frontmatter = yaml.safe_load(claude_artifact.read_text().split("---", 2)[1]) or {}
    tools = {tool.strip() for tool in frontmatter["tools"].split(",")}
    assert not TYPED_BEAD_TOOLS - tools
    assert "cognovis-tools" in frontmatter["mcpServers"]

    codex_artifact = _build(agent_name, "codex", tmp_path / agent_name / "codex")
    codex_text = codex_artifact.read_text()
    mcp_line = next(
        line for line in codex_text.splitlines() if line.startswith("# mcp_servers:")
    )
    assert "cognovis-tools" in mcp_line


def test_catalog_declares_cognovis_tools_for_all_mutating_primitives() -> None:
    catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())["library"]
    entries = {
        kind: {entry["name"]: entry for entry in catalog[kind]}
        for kind in ("agents", "skills")
    }

    for name in MUTATING_AGENTS:
        assert "mcp:cognovis-tools" in entries["agents"][name].get("requires", [])
    for name in MUTATING_SKILLS:
        assert "mcp:cognovis-tools" in entries["skills"][name].get("requires", [])

    intake = entries["skills"]["intake"]
    assert "agent:bead-author" not in intake.get("requires", [])
    assert "inline cognovis-tools bead creation" in intake["description"]
