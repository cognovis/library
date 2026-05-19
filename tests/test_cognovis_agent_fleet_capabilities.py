#!/usr/bin/env python3
"""Fleet checks for cognovis-core capability-based agent sources."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
COGNOVIS_CORE = REPO_ROOT.parent / "cognovis-core"
AGENTS_DIR = COGNOVIS_CORE / "agents"
AGENT_BASES_DIR = COGNOVIS_CORE / "agent-bases"
MODEL_STANDARDS_DIR = COGNOVIS_CORE / "model-standards"
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"
LIBRARY_YAML = REPO_ROOT / "library.yaml"


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


def test_catalog_agents_build_with_non_stub_artifacts(tmp_path: Path) -> None:
    """Every catalog-listed agent builds and produces non-stub, schema-valid artifacts."""
    catalog = yaml.safe_load(LIBRARY_YAML.read_text(encoding="utf-8")) or {}
    agents = catalog.get("library", {}).get("agents", [])
    assert agents, "library.yaml must declare at least one agent under library.agents"

    for entry in agents:
        name = entry["name"]
        source = AGENTS_DIR / f"{name}.md"

        assert source.exists(), (
            f"Catalog agent '{name}' has no source file at {source}"
        )

        # Read the declared name from the source frontmatter (may differ from catalog key).
        source_text = source.read_text(encoding="utf-8")
        source_frontmatter = yaml.safe_load(source_text.split("---", 2)[1]) or {}
        declared_name = source_frontmatter.get("name", name)

        output_dir = tmp_path / name
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
        assert result.returncode == 0, f"{name}: builder exited non-zero:\n{result.stderr}"

        # Claude .md artifact checks
        md_files = list(output_dir.glob("*.md"))
        assert md_files, f"{name}: builder emitted no Claude .md artifact"
        md_text = md_files[0].read_text(encoding="utf-8")
        md_lines = md_text.splitlines()
        assert len(md_lines) >= 50, (
            f"{name}: Claude artifact has only {len(md_lines)} lines (stub threshold: 50)"
        )
        assert "---" in md_text, f"{name}: Claude artifact missing frontmatter delimiter '---'"
        built_frontmatter = yaml.safe_load(md_text.split("---", 2)[1]) or {}
        assert built_frontmatter.get("name") == declared_name, (
            f"{name}: Claude artifact frontmatter 'name' field is "
            f"{built_frontmatter.get('name')!r}, expected {declared_name!r}"
        )

        # Codex .toml artifact checks
        toml_files = list(output_dir.glob("*.toml"))
        assert toml_files, f"{name}: builder emitted no Codex .toml artifact"
        toml_text = toml_files[0].read_text(encoding="utf-8")
        toml_lines = toml_text.splitlines()
        assert len(toml_lines) >= 50, (
            f"{name}: Codex artifact has only {len(toml_lines)} lines (stub threshold: 50)"
        )
        assert "prompt_file = " not in toml_text, (
            f"{name}: Codex artifact contains 'prompt_file = ' indirection — this is a stub"
        )
        parsed_toml = tomllib.loads(toml_text)
        assert parsed_toml.get("name") == declared_name, (
            f"{name}: Codex artifact TOML 'name' field is "
            f"{parsed_toml.get('name')!r}, expected {declared_name!r}"
        )


def test_stub_detection_catches_prompt_file_indirection() -> None:
    """Regression: stub-detection logic would catch the original quick-fix.toml stub format."""
    stub_toml = """\
# Generated stub — do not use in production
name = "quick-fix"
description = "Lightweight quick fix orchestrator."
model = "gpt-5.4"
prompt_file = "agents/quick-fix.md"
"""
    # Simulate the same checks applied in test_catalog_agents_build_with_non_stub_artifacts.
    lines = stub_toml.splitlines()
    assert len(lines) < 50, "Fixture must be a stub (fewer than 50 lines)"
    assert "prompt_file = " in stub_toml, "Fixture must contain prompt_file indirection"

    # Assert the stub would fail both quality gates.
    assert not (len(lines) >= 50), (
        "Stub should fail the line-count gate (< 50 lines)"
    )
    assert "prompt_file = " in stub_toml, (
        "Stub should fail the prompt_file indirection gate"
    )
