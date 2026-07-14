"""Cross-repository contracts for the retired cognovis-tools Bead family."""

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
BEAD_CONSUMERS = {
    "bead-author",
    "bead-orchestrator",
    "session-close",
    "wave-monitor",
    "wave-orchestrator",
}


pytestmark = pytest.mark.skipif(
    not (COGNOVIS_CORE / "agents").exists(),
    reason="cognovis-core sibling checkout is not available",
)


def _build_claude(agent_name: str, output_dir: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(COGNOVIS_CORE / "agents" / f"{agent_name}.md"),
            "--harness",
            "claude",
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
    artifact = next(output_dir.glob("*.md"))
    return yaml.safe_load(artifact.read_text().split("---", 2)[1]) or {}


def test_capability_registry_has_no_bead_mcp_surface() -> None:
    registry = yaml.safe_load((REPO_ROOT / "capabilities.yaml").read_text())
    capabilities = registry["capabilities"]
    assert not {"manage_beads", "read_beads"} & {
        capability["name"] for capability in capabilities
    }
    for capability in capabilities:
        tools = (capability.get("claude") or {}).get("tools") or []
        assert not any(
            str(tool).startswith("mcp__cognovis-tools__bead_") for tool in tools
        )


def test_core_runtime_sources_do_not_reference_retired_bead_tools() -> None:
    offenders: list[str] = []
    for root in ("agents", "skills", "workflows"):
        for source in (COGNOVIS_CORE / root).rglob("*"):
            if source.suffix not in {".md", ".toml", ".yaml", ".yml", ".py", ".js"}:
                continue
            text = source.read_text(encoding="utf-8")
            if "mcp__cognovis-tools__bead_" in text:
                offenders.append(str(source.relative_to(COGNOVIS_CORE)))
    assert not offenders


@pytest.mark.parametrize("agent_name", sorted(BEAD_CONSUMERS))
def test_built_bead_consumers_receive_no_bead_mcp_tools(
    agent_name: str, tmp_path: Path
) -> None:
    frontmatter = _build_claude(agent_name, tmp_path / agent_name)
    tools = frontmatter.get("tools", "")
    rendered = tools if isinstance(tools, str) else ",".join(tools)
    assert "mcp__cognovis-tools__bead_" not in rendered
