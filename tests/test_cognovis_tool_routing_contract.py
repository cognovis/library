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
    "mcp__cognovis-tools__bead_effort_classify",
    "mcp__cognovis-tools__bead_claim_prepare",
    "mcp__cognovis-tools__bead_claim_commit",
    "mcp__cognovis-tools__bead_claim",
    "mcp__cognovis-tools__bead_update",
    "mcp__cognovis-tools__bead_update_notes",
    "mcp__cognovis-tools__bead_review_write",
    "mcp__cognovis-tools__bead_close",
    "mcp__cognovis-tools__bead_dep_add",
    "mcp__cognovis-tools__bead_dep_remove",
    "mcp__cognovis-tools__bead_dolt_sync",
    "mcp__cognovis-tools__session_close_record_handoff",
    "mcp__cognovis-tools__bead_session_close_finalize",
    "mcp__cognovis-tools__bead_session_close_finalize_status",
}
READ_ONLY_BEAD_TOOLS = {
    "mcp__cognovis-tools__bead_show",
    "mcp__cognovis-tools__bead_ready",
    "mcp__cognovis-tools__bead_list",
    "mcp__cognovis-tools__bead_search",
    "mcp__cognovis-tools__bead_repos",
    "mcp__cognovis-tools__bead_session_close_finalize_status",
}
MUTATING_BEAD_TOOLS = TYPED_BEAD_TOOLS - READ_ONLY_BEAD_TOOLS


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


def _claude_frontmatter(artifact: Path) -> dict:
    return yaml.safe_load(artifact.read_text().split("---", 2)[1]) or {}


def _claude_tools(frontmatter: dict) -> set[str]:
    tools = frontmatter.get("tools", "")
    if isinstance(tools, str):
        return {tool.strip() for tool in tools.split(",") if tool.strip()}
    return set(tools)


@pytest.mark.parametrize("agent_name", sorted(MUTATING_AGENTS))
def test_mutating_agents_receive_cognovis_tools_in_both_harnesses(
    agent_name: str, tmp_path: Path
) -> None:
    claude_artifact = _build(agent_name, "claude", tmp_path / agent_name / "claude")
    frontmatter = _claude_frontmatter(claude_artifact)
    tools = _claude_tools(frontmatter)
    assert not TYPED_BEAD_TOOLS - tools
    assert "cognovis-tools" in frontmatter["mcpServers"]

    codex_artifact = _build(agent_name, "codex", tmp_path / agent_name / "codex")
    codex_text = codex_artifact.read_text()
    mcp_line = next(
        line for line in codex_text.splitlines() if line.startswith("# mcp_servers:")
    )
    assert "cognovis-tools" in mcp_line


def test_wave_monitor_receives_read_only_bead_tools_in_both_harnesses(
    tmp_path: Path,
) -> None:
    claude_artifact = _build("wave-monitor", "claude", tmp_path / "claude")
    claude_frontmatter = _claude_frontmatter(claude_artifact)
    claude_tools = _claude_tools(claude_frontmatter)
    assert READ_ONLY_BEAD_TOOLS <= claude_tools
    assert not MUTATING_BEAD_TOOLS & claude_tools
    assert "cognovis-tools" in claude_frontmatter["mcpServers"]

    codex_artifact = _build("wave-monitor", "codex", tmp_path / "codex")
    codex_text = codex_artifact.read_text()
    assert '# mcp_servers: ["cognovis-tools"]' in codex_text
    assert 'sandbox_mode = "read-only"' in codex_text


def test_effort_classifier_receives_no_bead_access_in_either_harness(
    tmp_path: Path,
) -> None:
    claude_artifact = _build("effort-classifier", "claude", tmp_path / "claude")
    claude_frontmatter = _claude_frontmatter(claude_artifact)
    assert not TYPED_BEAD_TOOLS & _claude_tools(claude_frontmatter)
    assert "cognovis-tools" not in claude_frontmatter.get("mcpServers", [])

    codex_artifact = _build("effort-classifier", "codex", tmp_path / "codex")
    codex_mcp_lines = [
        line
        for line in codex_artifact.read_text().splitlines()
        if line.startswith("# mcp_servers:")
    ]
    assert all("cognovis-tools" not in line for line in codex_mcp_lines)


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


def test_catalog_installs_cognovis_tools_only_for_the_read_only_consumer() -> None:
    catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())["library"]
    agents = {entry["name"]: entry for entry in catalog["agents"]}

    assert "mcp:cognovis-tools" in agents["wave-monitor"].get("requires", [])
    assert "mcp:cognovis-tools" not in agents["effort-classifier"].get("requires", [])
