#!/usr/bin/env python3
"""Tests for scripts/build-agent.py unified agent source builder."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
FIXTURES_DIR = REPO_ROOT / "tests" / "compose" / "fixtures"


def make_agent_bases(tmp_path: Path) -> Path:
    base_dir = tmp_path / "agent-bases"
    base_dir.mkdir()
    (base_dir / "claude-agent-base.md").write_text(
        (FIXTURES_DIR / "base-claude-agent-base.md").read_text()
    )
    (base_dir / "codex-agent-base.md").write_text(
        (FIXTURES_DIR / "base-codex-agent-base.md").read_text()
    )
    return base_dir


def write_unified_source(tmp_path: Path, body: str | None = None) -> Path:
    source = tmp_path / "unified-agent.md"
    source.write_text(
        "---\n"
        "name: unified-agent\n"
        "description: Shared agent description.\n"
        "model: sonnet\n"
        "tools: Read, Grep\n"
        "agent_base: auto\n"
        "model_standards: []\n"
        "codex:\n"
        "  model: gpt-5.4\n"
        "  model_reasoning_effort: high\n"
        "  sandbox_mode: workspace-write\n"
        "  nickname_candidates:\n"
        "    - unified agent\n"
        "---\n\n"
        + (
            body
            if body is not None
            else "# Unified Agent\n\n"
            "Shared body.\n\n"
            "::: harness claude :::\n"
            "Claude-only body.\n"
            "::: end :::\n\n"
            "::: harness codex :::\n"
            "Codex-only body.\n"
            "::: end :::\n"
        )
    )
    return source


def write_source_without_codex_override(tmp_path: Path) -> Path:
    source = tmp_path / "plain-agent.md"
    source.write_text(
        "---\n"
        "name: plain-agent\n"
        "description: Plain agent description.\n"
        "model: sonnet\n"
        "tools: Read, Grep\n"
        "agent_base: auto\n"
        "model_standards: []\n"
        "---\n\n"
        "# Plain Agent\n\nShared body.\n"
    )
    return source


def write_capability_source(tmp_path: Path) -> Path:
    source = tmp_path / "capability-agent.md"
    source.write_text(
        "---\n"
        "name: capability-agent\n"
        "description: Capability agent description.\n"
        "model:\n"
        "  tier: standard\n"
        "  reasoning: high\n"
        "  context: large\n"
        "  cost_priority: cheapest\n"
        "capabilities:\n"
        "  - read_files\n"
        "  - edit_files\n"
        "  - run_shell\n"
        "  - query_memory\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Capability Agent\n\nShared body.\n"
    )
    return source


def write_pair_loop_reviewer_source(
    tmp_path: Path,
    *,
    include_constraints: bool = True,
) -> Path:
    source = tmp_path / "pair-loop-reviewer.md"
    constraints = (
        "pair_loop_constraints:\n"
        "  review_contexts:\n"
        "    - in_loop\n"
        "    - cold\n"
        "  run_shell: read_only\n"
        if include_constraints
        else ""
    )
    source.write_text(
        "---\n"
        "name: pair-loop-reviewer\n"
        "description: Pair-loop reviewer fixture.\n"
        "model: sonnet\n"
        "tools: Read, Write, Edit, MultiEdit, Bash\n"
        "capabilities:\n"
        "  - run_shell\n"
        f"{constraints}"
        "agent_base: auto\n"
        "---\n\n"
        "# Pair-loop Reviewer\n\nShared body.\n"
    )
    return source


def write_escape_hatch_source(tmp_path: Path) -> Path:
    source = tmp_path / "escape-agent.md"
    source.write_text(
        "---\n"
        "name: escape-agent\n"
        "description: Escape hatch agent description.\n"
        "model:\n"
        "  tier: standard\n"
        "  reasoning: high\n"
        "  context: large\n"
        "  claude-code: claude-opus-4-8\n"
        "  codex:\n"
        "    tier: premium\n"
        "    reasoning: high\n"
        "    context: large\n"
        "capabilities:\n"
        "  - read_files\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Escape Agent\n\nShared body.\n"
    )
    return source


def write_unknown_capability_source(tmp_path: Path) -> Path:
    source = tmp_path / "unknown-capability-agent.md"
    source.write_text(
        "---\n"
        "name: unknown-capability-agent\n"
        "description: Unknown capability agent description.\n"
        "model:\n"
        "  tier: standard\n"
        "capabilities:\n"
        "  - not_registered\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Unknown Capability Agent\n\nShared body.\n"
    )
    return source


def write_no_match_model_source(tmp_path: Path) -> Path:
    source = tmp_path / "no-match-agent.md"
    source.write_text(
        "---\n"
        "name: no-match-agent\n"
        "description: No match agent description.\n"
        "model:\n"
        "  tier: frontier\n"
        "  reasoning: max\n"
        "  context: large\n"
        "capabilities:\n"
        "  - read_files\n"
        "agent_base: auto\n"
        "---\n\n"
        "# No Match Agent\n\nShared body.\n"
    )
    return source


def make_model_standards(tmp_path: Path, names: list[str]) -> Path:
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()
    for name in names:
        (model_standards_dir / f"{name}.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"model_id: {name}\n"
            "---\n\n"
            f"{name.upper()}_LAYER3_MARKER\n"
        )
    return model_standards_dir


def load_build_agent_module():
    spec = importlib.util.spec_from_file_location("build_agent_under_test", BUILD_AGENT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_build(
    source: Path,
    output_dir: Path,
    agent_bases_dir: Path,
    model_standards_dir: Path,
    harness: str = "all",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(source),
            f"--harness={harness}",
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(agent_bases_dir),
            "--model-standards-dir",
            str(model_standards_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_build_agent_emits_claude_md_and_codex_toml(tmp_path: Path) -> None:
    """Unified source builds distinct Claude and Codex artifacts."""
    source = write_unified_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 0, result.stderr
    claude = (output_dir / "unified-agent.md").read_text()
    codex_text = (output_dir / "unified-agent.toml").read_text()
    codex = tomllib.loads(codex_text)

    assert "CLAUDE_AGENT_BASE_LAYER1_MARKER" in claude
    assert "CODEX_AGENT_BASE_LAYER1_MARKER" not in claude
    assert "Claude-only body." in claude
    assert "Codex-only body." not in claude
    assert "::: harness" not in claude
    assert claude.startswith("---\nname: unified-agent\n")

    assert codex["name"] == "unified-agent"
    assert codex["model"] == "gpt-5.4"
    assert codex["model_reasoning_effort"] == "high"
    assert codex["sandbox_mode"] == "workspace-write"
    assert codex["nickname_candidates"] == ["unified agent"]
    assert "CODEX_AGENT_BASE_LAYER1_MARKER" in codex["developer_instructions"]
    assert "CLAUDE_AGENT_BASE_LAYER1_MARKER" not in codex["developer_instructions"]
    assert "Codex-only body." in codex["developer_instructions"]
    assert "Claude-only body." not in codex["developer_instructions"]
    assert "::: harness" not in codex["developer_instructions"]


def test_build_agent_rejects_nested_directives(tmp_path: Path) -> None:
    """Nested harness directive blocks fail loudly."""
    source = write_unified_source(
        tmp_path,
        "::: harness claude :::\n"
        "outer\n"
        "::: harness codex :::\n"
        "inner\n"
        "::: end :::\n"
        "::: end :::\n",
    )
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 1
    assert "Nested harness directive" in result.stderr


def test_build_agent_derives_codex_defaults_without_override(tmp_path: Path) -> None:
    """Codex output maps Claude model names when no codex override is present."""
    source = write_source_without_codex_override(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="codex")

    assert result.returncode == 0, result.stderr
    codex = tomllib.loads((output_dir / "plain-agent.toml").read_text())
    assert codex["model"] == "gpt-5.4"
    assert codex["model_reasoning_effort"] == "high"
    assert codex["sandbox_mode"] == "read-only"
    assert codex["nickname_candidates"] == ["plain-agent"]


def test_build_agent_resolves_models_and_capabilities_per_harness(tmp_path: Path) -> None:
    """Capability-era model and tool declarations project to concrete artifacts."""
    source = write_capability_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.4"])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 0, result.stderr
    claude = (output_dir / "capability-agent.md").read_text()
    codex_text = (output_dir / "capability-agent.toml").read_text()
    codex = tomllib.loads(codex_text)

    assert "model: sonnet" in claude
    assert "tools: Read, Grep, Glob, Edit, Bash" in claude
    assert "mcp__open-brain__search" in claude
    assert "mcpServers:\n- open-brain" in claude
    assert "SONNET_LAYER3_MARKER" in claude

    assert codex["model"] == "gpt-5.4"
    assert codex["model_reasoning_effort"] == "high"
    assert codex["sandbox_mode"] == "workspace-write"
    assert '# mcp_servers: ["open-brain"]' in codex_text
    assert "GPT-5.4_LAYER3_MARKER" in codex["developer_instructions"]


def test_pair_loop_read_only_constraints_override_run_shell_codex_sandbox(
    tmp_path: Path,
) -> None:
    """Pair-loop reviewers keep read-only Codex sandbox despite run_shell."""
    source = write_pair_loop_reviewer_source(tmp_path, include_constraints=True)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 0, result.stderr
    codex = tomllib.loads((output_dir / "pair-loop-reviewer.toml").read_text())
    claude_text = (output_dir / "pair-loop-reviewer.md").read_text()
    claude_frontmatter = yaml.safe_load(claude_text.split("---", 2)[1]) or {}
    claude_tools = {
        tool.strip()
        for tool in str(claude_frontmatter.get("tools", "")).split(",")
        if tool.strip()
    }

    assert codex["sandbox_mode"] == "read-only"
    assert not ({"Write", "Edit", "MultiEdit"} & claude_tools)
    assert "Bash" in claude_tools


def test_run_shell_without_pair_loop_constraints_keeps_workspace_write(
    tmp_path: Path,
) -> None:
    """Non-reviewer run_shell capability keeps the existing workspace-write behavior."""
    source = write_pair_loop_reviewer_source(tmp_path, include_constraints=False)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="codex")

    assert result.returncode == 0, result.stderr
    codex = tomllib.loads((output_dir / "pair-loop-reviewer.toml").read_text())
    assert codex["sandbox_mode"] == "workspace-write"


def test_pair_loop_read_only_guard_rejects_drift() -> None:
    """The defensive guard fails loudly if read-only reviewer constraints drift."""
    module = load_build_agent_module()
    frontmatter = {"pair_loop_constraints": {"run_shell": "read_only"}}

    with pytest.raises(module.BuildAgentError, match="pair_loop_constraints"):
        module._validate_pair_loop_read_only_constraints(  # noqa: SLF001
            {"sandbox_mode": "workspace-write"},
            frontmatter,
            "codex",
        )

    with pytest.raises(module.BuildAgentError, match="pair_loop_constraints"):
        module._validate_pair_loop_read_only_constraints(  # noqa: SLF001
            {"tools": "Read, Write, Bash"},
            frontmatter,
            "claude",
        )


def test_build_agent_model_escape_hatch_overrides_per_harness(tmp_path: Path) -> None:
    """Explicit per-harness model declarations beat registry resolution."""
    source = write_escape_hatch_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["claude-opus-4-8", "gpt-5.5"])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 0, result.stderr
    claude = (output_dir / "escape-agent.md").read_text()
    codex = tomllib.loads((output_dir / "escape-agent.toml").read_text())
    assert "model: claude-opus-4-8" in claude
    assert "CLAUDE-OPUS-4-8_LAYER3_MARKER" in claude
    assert codex["model"] == "gpt-5.5"
    assert "GPT-5.5_LAYER3_MARKER" in codex["developer_instructions"]


def test_build_agent_rejects_unknown_capability(tmp_path: Path) -> None:
    """Capabilities are a closed vocabulary."""
    source = write_unknown_capability_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 1
    assert "Unknown capability 'not_registered'" in result.stderr


def test_build_agent_rejects_model_requirements_with_no_match(tmp_path: Path) -> None:
    """Model requirements fail clearly when no registry row satisfies them."""
    source = write_no_match_model_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 1
    assert "No model in models.yaml matches harness" in result.stderr


def test_build_agent_rejects_unclosed_directives(tmp_path: Path) -> None:
    """Unclosed harness directive blocks fail loudly."""
    source = write_unified_source(
        tmp_path,
        "Shared\n\n::: harness codex :::\nCodex-only without end.\n",
    )
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir)

    assert result.returncode == 1
    assert "Unclosed harness directive" in result.stderr


def test_build_agent_is_idempotent(tmp_path: Path) -> None:
    """Running the builder twice produces byte-identical artifacts."""
    source = write_unified_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    first = run_build(source, output_dir, agent_bases_dir, model_standards_dir)
    assert first.returncode == 0, first.stderr
    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output_dir.iterdir()
    }

    second = run_build(source, output_dir, agent_bases_dir, model_standards_dir)
    assert second.returncode == 0, second.stderr
    second_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output_dir.iterdir()
    }

    assert first_hashes == second_hashes


def test_library_agent_use_builds_single_source_for_both_harnesses(tmp_path: Path) -> None:
    """agent use --harness all builds Claude and Codex artifacts from one source."""
    source = write_unified_source(tmp_path)
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "library.yaml").write_text(
        "default_dirs:\n"
        "  agents:\n"
        "    - default: .claude/agents/\n"
        "    - default_codex: .codex/agents/\n"
        "library:\n"
        "  agents:\n"
        "    - name: unified-agent\n"
        "      description: Unified agent fixture\n"
        f"      source: {source}\n"
        "  skills: []\n"
        "  prompts: []\n"
        "marketplaces: []\n"
        "guardrails: []\n"
        "mcp_servers: []\n"
        "model_standards: []\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "agent",
            "use",
            "unified-agent",
            "--harness",
            "all",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(project),
        env={
            **os.environ,
            "AGENT_BASES_DIR": str(agent_bases_dir),
            "MODEL_STANDARDS_DIR": str(model_standards_dir),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
            "HOME": str(tmp_path / "home"),
        },
    )

    assert result.returncode == 0, result.stderr
    claude = project / ".claude" / "agents" / "unified-agent.md"
    codex = project / ".codex" / "agents" / "unified-agent.toml"
    assert claude.exists()
    assert codex.exists()
    assert "CLAUDE_AGENT_BASE_LAYER1_MARKER" in claude.read_text()
    codex_data = tomllib.loads(codex.read_text())
    assert "CODEX_AGENT_BASE_LAYER1_MARKER" in codex_data["developer_instructions"]


# ---------------------------------------------------------------------------
# manage_beads typed-tool regression (CL-j92j)
#
# Root cause: capabilities.yaml's manage_beads capability declared
# `claude.tools: []` (an explicit empty list) alongside `mcpServers:
# [cognovis-tools]`. Registering an MCP server does not, by itself, grant any
# callable tool from that server in Claude Code — only exact `mcp__<server>__
# <tool>` names listed in an agent's `tools:` allowlist are callable. Every
# agent declaring manage_beads therefore had zero callable bead_* tools
# despite the server being nominally registered.
#
# These fixtures are hermetic: they read the REAL capabilities.yaml in this
# repo (no cognovis-core sibling checkout required), so they always run.
# ---------------------------------------------------------------------------

# Source of truth for this list: cognovis-core/mcp-servers/cognovis-tools/
# tools/bead_tools.py `def bead_*` function names (verified via grep during
# CL-j92j implementation). Do not add or rename entries without re-verifying
# against that file.
_MANAGE_BEADS_TYPED_TOOLS = [
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
]


def _assert_manage_beads_tools_present(tools: set[str]) -> None:
    """Regression guard: manage_beads must expose every typed bead_* tool.

    Raises AssertionError (with "CL-j92j regression" in the message for the
    empty case) if *tools* is empty or missing any expected typed tool name.
    """
    assert tools, "manage_beads granted zero Claude tools (CL-j92j regression)"
    missing = set(_MANAGE_BEADS_TYPED_TOOLS) - tools
    assert not missing, f"manage_beads is missing typed tools: {sorted(missing)}"


def write_manage_beads_source(tmp_path: Path) -> Path:
    source = tmp_path / "bead-capability-agent.md"
    source.write_text(
        "---\n"
        "name: bead-capability-agent\n"
        "description: Fixture agent that only declares manage_beads.\n"
        "model: sonnet\n"
        "capabilities:\n"
        "  - manage_beads\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Bead Capability Agent\n\nFixture body for CL-j92j regression coverage.\n"
    )
    return source


def test_manage_beads_capability_registry_has_explicit_typed_tools() -> None:
    """capabilities.yaml's manage_beads.claude.tools is the explicit typed list."""
    module = load_build_agent_module()
    registry = module.load_capabilities_registry()
    manage_beads = registry.get("manage_beads")
    assert manage_beads is not None, "manage_beads capability missing from capabilities.yaml"

    claude_binding = manage_beads.get("claude") or {}
    tools = set(module._as_string_list(claude_binding.get("tools")))  # noqa: SLF001
    _assert_manage_beads_tools_present(tools)

    mcp_servers = set(module._as_string_list(claude_binding.get("mcpServers")))  # noqa: SLF001
    assert "cognovis-tools" in mcp_servers, (
        "manage_beads.claude.mcpServers must keep registering cognovis-tools"
    )


def test_manage_beads_empty_tools_regression_fixture_would_have_caught_the_bug() -> None:
    """Regression fixture: the pre-CL-j92j `tools: []` shape fails the guard helper.

    Confirms _assert_manage_beads_tools_present is not vacuous — it would have
    caught the historical bug where manage_beads.claude.tools was an explicit [].
    """
    with pytest.raises(AssertionError, match="CL-j92j regression"):
        _assert_manage_beads_tools_present(set())


def test_build_agent_grants_manage_beads_typed_tools_end_to_end(tmp_path: Path) -> None:
    """An agent declaring only manage_beads gets the full typed bead_* tool set.

    Exercises the real merge path (apply_capabilities -> _set_tools) against
    the real repo capabilities.yaml, end to end through the CLI entry point.
    """
    source = write_manage_beads_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "bead-capability-agent.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {t.strip() for t in str(frontmatter.get("tools", "")).split(",") if t.strip()}
    _assert_manage_beads_tools_present(tools)

    mcp_servers = frontmatter.get("mcpServers") or []
    assert "cognovis-tools" in mcp_servers, (
        "built agent frontmatter must register the cognovis-tools MCP server "
        "alongside the typed tools (CL-j92j AC4: server-absent regression)"
    )


# Guards CL-h76a: bead-orchestrator instructions required Bead Claim tools that
# the generated Claude tools allowlist did not expose.
def test_regression_bead_claim_prepare_is_projected_to_manage_beads(tmp_path: Path) -> None:
    source = write_manage_beads_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "bead-capability-agent.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {t.strip() for t in str(frontmatter.get("tools", "")).split(",") if t.strip()}
    assert {
        "mcp__cognovis-tools__bead_claim_prepare",
        "mcp__cognovis-tools__bead_claim_commit",
    } <= tools


def write_synthetic_reviewer_manage_beads_source(tmp_path: Path) -> Path:
    """A reviewer-shaped agent that WRONGLY declares manage_beads.

    Mirrors the fleet-level fixture in
    tests/test_cognovis_agent_fleet_capabilities.py::
    test_manage_beads_role_leakage_regression_fixture_would_be_caught, but is
    fully self-contained so the AC4 role-leakage guard has coverage even when
    the cognovis-core sibling checkout is absent (isolated CI, fresh clone).
    """
    source = tmp_path / "synthetic-reviewer.md"
    source.write_text(
        "---\n"
        "name: synthetic-reviewer\n"
        "description: Synthetic reviewer fixture that wrongly declares manage_beads.\n"
        "model: sonnet\n"
        "capabilities:\n"
        "  - read_files\n"
        "  - run_shell\n"
        "  - manage_beads\n"
        "agent_base: auto\n"
        "---\n\n# Synthetic Reviewer\n\nFixture body for CL-j92j hermetic role-leakage coverage.\n"
    )
    return source


def test_manage_beads_role_leakage_regression_fixture_hermetic(tmp_path: Path) -> None:
    """AC4 (hermetic): a reviewer-shaped agent that declares manage_beads leaks bead_* tools.

    Proves the mcp__cognovis-tools__bead_* leak-detection mechanism (asserted
    against the real review-agent/verification-agent sources by the fleet test
    test_manage_beads_read_only_agents_stay_read_only) is exercised without any
    cognovis-core dependency. Uses the hermetic agent-base fixtures so the guard
    is covered in environments where the sibling checkout is unavailable.
    """
    source = write_synthetic_reviewer_manage_beads_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "synthetic-reviewer.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {t.strip() for t in str(frontmatter.get("tools", "")).split(",") if t.strip()}
    leaked = {t for t in tools if t.startswith("mcp__cognovis-tools__bead_")}
    assert leaked, (
        "hermetic fixture expected mcp__cognovis-tools__bead_* tools to leak when a "
        "reviewer-shaped agent wrongly declares manage_beads — the leak-detection "
        "assertion is therefore not vacuous"
    )


# ---------------------------------------------------------------------------
# read_beads read-only typed-tool capability (CL-j92j Part 2)
#
# read_beads is the least-privilege sibling of manage_beads: it grants the 5
# read-only bead_* tools and NONE of the 12 mutating ones. It exists so
# non-orchestrator consumers (classifiers, pollers) can see bead state without
# gaining mutation access. The companion cognovis-core bead clc-zbj4 (separate
# repo, separate tracker) migrates effort-classifier / wave-monitor onto it;
# these hermetic tests must exist and pass independent of that cross-repo work.
# ---------------------------------------------------------------------------

# The 5 read-only tools read_beads is allowed to grant.
_READ_BEADS_READ_TOOLS = {
    "mcp__cognovis-tools__bead_show",
    "mcp__cognovis-tools__bead_ready",
    "mcp__cognovis-tools__bead_list",
    "mcp__cognovis-tools__bead_search",
    "mcp__cognovis-tools__bead_repos",
}

# The 12 mutating tools read_beads must NEVER grant.
_READ_BEADS_FORBIDDEN_MUTATING_TOOLS = {
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
}


def write_read_beads_source(tmp_path: Path) -> Path:
    source = tmp_path / "read-beads-agent.md"
    source.write_text(
        "---\n"
        "name: read-beads-agent\n"
        "description: Fixture agent that only declares read_beads.\n"
        "model: sonnet\n"
        "capabilities:\n"
        "  - read_beads\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Read Beads Agent\n\nFixture body for CL-j92j read_beads coverage.\n"
    )
    return source


def test_read_beads_capability_registry_is_read_only_typed_tools() -> None:
    """capabilities.yaml's read_beads grants exactly the 5 read-only bead_* tools.

    Mirrors test_manage_beads_capability_registry_has_explicit_typed_tools: reads
    the real capabilities.yaml directly and asserts the read-only tool set is
    exact, non-empty, free of any mutating tool, and keeps cognovis-tools
    registered.
    """
    module = load_build_agent_module()
    registry = module.load_capabilities_registry()
    read_beads = registry.get("read_beads")
    assert read_beads is not None, "read_beads capability missing from capabilities.yaml"

    claude_binding = read_beads.get("claude") or {}
    tools = set(module._as_string_list(claude_binding.get("tools")))  # noqa: SLF001
    assert tools == _READ_BEADS_READ_TOOLS, (
        f"read_beads.claude.tools must be exactly the 5 read-only tools; got {sorted(tools)}"
    )
    assert not (tools & _READ_BEADS_FORBIDDEN_MUTATING_TOOLS), (
        "read_beads.claude.tools must not grant any mutating bead_* tool"
    )

    mcp_servers = set(module._as_string_list(claude_binding.get("mcpServers")))  # noqa: SLF001
    assert "cognovis-tools" in mcp_servers, (
        "read_beads.claude.mcpServers must keep registering cognovis-tools"
    )


def test_build_agent_grants_read_beads_read_only_tools_end_to_end(tmp_path: Path) -> None:
    """An agent declaring only read_beads gets the 5 read tools and none of the 12 mutating.

    Exercises the real merge path (apply_capabilities -> _set_tools) against the
    real repo capabilities.yaml, end to end through the CLI entry point.
    """
    source = write_read_beads_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "read-beads-agent.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {t.strip() for t in str(frontmatter.get("tools", "")).split(",") if t.strip()}

    bead_tools = {t for t in tools if t.startswith("mcp__cognovis-tools__bead_")}
    assert bead_tools == _READ_BEADS_READ_TOOLS, (
        f"read_beads agent must grant exactly the 5 read-only bead_* tools; got {sorted(bead_tools)}"
    )
    leaked = tools & _READ_BEADS_FORBIDDEN_MUTATING_TOOLS
    assert not leaked, (
        f"read_beads agent leaked mutating bead_* tools: {sorted(leaked)}"
    )

    mcp_servers = frontmatter.get("mcpServers") or []
    assert "cognovis-tools" in mcp_servers, (
        "built read_beads agent frontmatter must register the cognovis-tools MCP server"
    )


# ---------------------------------------------------------------------------
# manage_agent_sessions typed-tool capability (CL-2n27)
# ---------------------------------------------------------------------------

_AGENT_SESSION_TOOLS = {
    "mcp__cognovis-tools__agent_session_start",
    "mcp__cognovis-tools__agent_session_continue",
    "mcp__cognovis-tools__agent_session_status",
    "mcp__cognovis-tools__agent_session_cancel",
}


def write_manage_agent_sessions_source(tmp_path: Path, *, enabled: bool) -> Path:
    source = tmp_path / "agent-session-capability-agent.md"
    capability = "  - manage_agent_sessions\n" if enabled else ""
    source.write_text(
        "---\n"
        "name: agent-session-capability-agent\n"
        "description: Fixture agent for typed provider session dispatch.\n"
        "model: sonnet\n"
        "capabilities:\n"
        "  - read_files\n"
        f"{capability}"
        "agent_base: auto\n"
        "---\n\n"
        "# Agent Session Capability Agent\n\nFixture body for CL-2n27 coverage.\n"
    )
    return source


def test_manage_agent_sessions_registry_grants_exact_typed_tools() -> None:
    """The dedicated capability grants exactly the four provider-session tools."""
    module = load_build_agent_module()
    registry = module.load_capabilities_registry()
    capability = registry.get("manage_agent_sessions")
    assert capability is not None, "manage_agent_sessions capability missing"

    claude_binding = capability.get("claude") or {}
    tools = set(module._as_string_list(claude_binding.get("tools")))  # noqa: SLF001
    assert tools == _AGENT_SESSION_TOOLS
    assert set(module._as_string_list(claude_binding.get("mcpServers"))) == {  # noqa: SLF001
        "cognovis-tools"
    }

    codex_binding = capability.get("codex") or {}
    assert set(module._as_string_list(codex_binding.get("mcp_servers"))) == {  # noqa: SLF001
        "cognovis-tools"
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_build_agent_scopes_agent_session_tools_to_declared_capability(
    tmp_path: Path, enabled: bool
) -> None:
    """The builder grants all four tools only when the capability is declared."""
    source = write_manage_agent_sessions_source(tmp_path, enabled=enabled)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "agent-session-capability-agent.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {
        tool.strip()
        for tool in str(frontmatter.get("tools", "")).split(",")
        if tool.strip()
    }
    granted = tools & _AGENT_SESSION_TOOLS
    assert granted == (_AGENT_SESSION_TOOLS if enabled else set())
