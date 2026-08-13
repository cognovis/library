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
        "  model: gpt-5.6-terra\n"
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
        "  codex: gpt-5.5\n"
        "capabilities:\n"
        "  - read_files\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Escape Agent\n\nShared body.\n"
    )
    return source


def write_model_free_source(tmp_path: Path) -> Path:
    source = tmp_path / "model-free-agent.md"
    source.write_text(
        "---\n"
        "name: model-free-agent\n"
        "description: Model-free agent description.\n"
        "tools: Read\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Model Free Agent\n\nShared body.\n"
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
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.6-terra"])

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
    assert codex["model"] == "gpt-5.6-terra"
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
    model_standards_dir = make_model_standards(tmp_path, ["gpt-5.6-terra"])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="codex")

    assert result.returncode == 0, result.stderr
    codex = tomllib.loads((output_dir / "plain-agent.toml").read_text())
    assert codex["model"] == "gpt-5.6-terra"
    assert codex["model_reasoning_effort"] == "high"
    assert codex["sandbox_mode"] == "read-only"
    assert codex["nickname_candidates"] == ["plain-agent"]


def test_build_agent_resolves_models_and_capabilities_per_harness(tmp_path: Path) -> None:
    """Capability-era model and tool declarations project to concrete artifacts."""
    source = write_capability_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.6-terra"])

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

    assert codex["model"] == "gpt-5.6-terra"
    assert codex["model_reasoning_effort"] == "high"
    assert codex["sandbox_mode"] == "workspace-write"
    assert '# mcp_servers: ["open-brain"]' in codex_text
    assert "GPT-5.6-TERRA_LAYER3_MARKER" in codex["developer_instructions"]


def test_pair_loop_read_only_constraints_override_run_shell_codex_sandbox(
    tmp_path: Path,
) -> None:
    """Pair-loop reviewers keep read-only Codex sandbox despite run_shell."""
    source = write_pair_loop_reviewer_source(tmp_path, include_constraints=True)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.6-terra"])

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
    model_standards_dir = make_model_standards(tmp_path, ["gpt-5.6-terra"])

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


def test_build_agent_rejects_resolved_model_without_standard(tmp_path: Path) -> None:
    """A resolved model with no Layer 3 standard fails instead of thinning the artifact."""
    source = write_source_without_codex_override(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["gpt-5.6-terra"])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 1
    assert "sonnet" in result.stderr
    assert not (output_dir / "plain-agent.md").exists()


def test_build_agent_rejects_a_model_standard_with_an_empty_body(tmp_path: Path) -> None:
    """A standard that resolves but carries no body is dropped just as silently."""
    source = write_source_without_codex_override(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, [])
    (model_standards_dir / "sonnet.md").write_text(
        "---\nname: sonnet\nmodel_id: sonnet\n---\n\n"
    )

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 1
    assert "sonnet" in result.stderr
    assert "empty body" in result.stderr
    assert not (output_dir / "plain-agent.md").exists()


def test_build_agent_allows_an_agent_that_resolves_no_model(tmp_path: Path) -> None:
    """The standard guard stays silent when no model is resolved at all."""
    source = write_model_free_source(tmp_path)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, [])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    assert (output_dir / "model-free-agent.md").exists()


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
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.6-terra"])

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
    model_standards_dir = make_model_standards(tmp_path, ["sonnet", "gpt-5.6-terra"])
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
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


def test_retired_private_gateway_capabilities_are_absent() -> None:
    registry = load_build_agent_module().load_capabilities_registry()
    assert "manage_beads" not in registry
    assert "read_beads" not in registry
    assert "manage_agent_sessions" not in registry


def test_blank_output_dir_is_rejected_instead_of_writing_to_cwd(tmp_path: Path) -> None:
    """An empty --output-dir must fail, not scatter artifacts into the CWD.

    `Path("")` normalizes to `Path(".")`, so an unset shell variable expanded
    into `--output-dir "$DIR"` silently wrote the built agent next to whatever
    the caller was working in — inside a checkout, that looks like new tracked
    files nobody asked for.
    """
    source = write_unified_source(tmp_path)
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            "--harness=claude",
            "--output-dir",
            "",
            str(source),
        ],
        capture_output=True,
        text=True,
        cwd=str(workdir),
    )

    assert result.returncode != 0, result.stdout
    assert "--output-dir" in result.stderr
    assert list(workdir.iterdir()) == []


def write_ask_user_source(tmp_path: Path, *, enabled: bool) -> Path:
    source = tmp_path / "gate-agent.md"
    capability = "  - ask_user\n" if enabled else ""
    source.write_text(
        "---\n"
        "name: gate-agent\n"
        "description: Fixture agent that must ask a human before it writes.\n"
        "model: sonnet\n"
        "capabilities:\n"
        "  - read_files\n"
        f"{capability}"
        "agent_base: auto\n"
        "---\n\n"
        "# Gate Agent\n\nFixture body for the human approval gate.\n"
    )
    return source


@pytest.mark.parametrize("enabled", [True, False])
def test_ask_user_capability_grants_the_claude_question_tool(
    tmp_path: Path, enabled: bool
) -> None:
    """AskUserQuestion is granted exactly when ask_user is declared.

    Agents that own a human approval gate previously could not be granted the
    tool at all: no capability in the registry mapped to it, and the built tool
    grant is the agent's behavioral permission boundary.
    """
    source = write_ask_user_source(tmp_path, enabled=enabled)
    output_dir = tmp_path / "out"
    agent_bases_dir = make_agent_bases(tmp_path)
    model_standards_dir = make_model_standards(tmp_path, ["sonnet"])

    result = run_build(source, output_dir, agent_bases_dir, model_standards_dir, harness="claude")

    assert result.returncode == 0, result.stderr
    built = (output_dir / "gate-agent.md").read_text()
    frontmatter = yaml.safe_load(built.split("---", 2)[1]) or {}
    tools = {
        tool.strip()
        for tool in str(frontmatter.get("tools", "")).split(",")
        if tool.strip()
    }
    assert ("AskUserQuestion" in tools) is enabled


def test_ask_user_capability_does_not_widen_the_codex_sandbox(tmp_path: Path) -> None:
    """ask_user has no Codex tool, so it must not change a Codex build."""
    module = load_build_agent_module()
    capability = module.load_capabilities_registry().get("ask_user")

    assert capability is not None, "ask_user capability missing"
    assert capability["claude"]["tools"] == ["AskUserQuestion"]
    assert capability["codex"]["sandbox_mode"] == "read-only"
    assert "tools" not in capability["codex"]
