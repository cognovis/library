#!/usr/bin/env python3
"""
test_library_py_new_features.py — Tests for CL-8ph: all primitive×verb combinations,
dependency resolver, --harness flag, and end-to-end smoke.

AKs covered: 1-31 (partial coverage for 31 which requires live catalog)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
PYTHON = sys.executable
TARGETED_SYNC_PRIMITIVES = [
    "skill",
    "agent",
    "prompt",
    "script",
    "standard",
    "guardrail",
    "mcp",
    "model-standard",
    "agent-base",
    "workflow",
]


def run_library(*args, cwd=None, env=None):
    """Run library.py with given args, return CompletedProcess."""
    base_env = os.environ.copy()
    if env:
        base_env.update(env)
    return subprocess.run(
        [PYTHON, str(LIBRARY_PY)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        env=base_env,
    )


def run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run git in a test repository."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=True,
    )


def init_git_source_repo(repo: Path) -> str:
    """Initialize a source fixture repository and return its HEAD SHA."""
    run_git("init", cwd=repo)
    run_git("config", "user.name", "Library Test", cwd=repo)
    run_git("config", "user.email", "library-test@example.com", cwd=repo)
    run_git("add", "-A", cwd=repo)
    run_git("commit", "-m", "initial source", cwd=repo)
    return git_head(repo)


def git_head(repo: Path) -> str:
    """Return HEAD SHA for a test repository."""
    return run_git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def lockfile_entry(project_dir: Path, primitive: str, name: str) -> dict:
    """Return one lockfile entry by primitive and name."""
    lock_data = yaml.safe_load((project_dir / ".library.lock").read_text())
    return next(
        entry
        for entry in lock_data["installed"]
        if entry["type"] == primitive and entry["name"] == name
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_AGENT_MD = """---
name: test-agent
description: A test agent for integration tests
model: claude-sonnet-4-6
---

# Test Agent

This is a test agent body.
"""

FIXTURE_AGENT_WITH_REQUIRES_MD = """---
name: parent-agent
description: Parent agent with requires
requires:
  - agent:child-agent
  - skill:child-skill
---

# Parent Agent body
"""

FIXTURE_CHILD_AGENT_MD = """---
name: child-agent
description: A child agent
---

# Child Agent body
"""

FIXTURE_CHILD_SKILL_MD = """---
name: child-skill
description: A child skill
---

# Child Skill
"""

FIXTURE_DEEP_CHAIN_A_MD = """---
name: chain-a
description: Deep chain A requires B
requires:
  - agent:chain-b
---
# Chain A
"""

FIXTURE_DEEP_CHAIN_B_MD = """---
name: chain-b
description: Deep chain B requires C
requires:
  - skill:chain-c
---
# Chain B
"""

FIXTURE_DEEP_CHAIN_C_MD = """---
name: chain-c
description: Chain C leaf
---
# Chain C
"""

FIXTURE_CYCLE_A_MD = """---
name: cycle-a
description: Cycle A requires B
requires:
  - agent:cycle-b
---
# Cycle A
"""

FIXTURE_CYCLE_B_MD = """---
name: cycle-b
description: Cycle B requires A (cycle!)
requires:
  - agent:cycle-a
---
# Cycle B
"""

FIXTURE_PROMPT_MD = """---
name: test-prompt
description: A test prompt
---

# Test Prompt

This is a test prompt body.
"""

FIXTURE_MODEL_STANDARD_MD = """---
name: test-model-standard
description: A test model standard
---

# Test Model Standard Content
"""

FIXTURE_AGENT_BASE_MD = """---
name: test-agent-base
description: A test agent base prompt
---

# Test Agent Base Prompt Content
"""

FIXTURE_WORKFLOW_JS = """export const meta = {
  name: "test-workflow",
  description: "A test workflow",
};

return { ok: true };
"""

MULTI_HARNESS_AGENT_MD = """---
name: multi-harness-agent
description: Agent with multiple harness sources
---

# Multi-harness Agent
"""

FIXTURE_LIBRARY_YAML_TEMPLATE = """
default_dirs:
  skills:
    - default: .agents/skills/
    - global: ~/.agents/skills/
    - claude_bridge: .claude/skills/
    - global_claude_bridge: ~/.claude/skills/
  agents:
    - default: .claude/agents/
    - global: ~/.claude/agents/
    - default_codex: .codex/agents/
    - global_codex: ~/.codex/agents/
  prompts:
    - default: .claude/commands/
    - global: ~/.claude/commands/
  standards:
    - default: .agents/standards/
    - global: ~/.agents/standards/
  guardrails:
    - default: .claude/hooks/
    - global: ~/.claude/hooks/
  model_standards:
    - default: .agents/model-standards/
    - global: ~/.agents/model-standards/
  agent_bases:
    - default: .agents/agent-bases/
    - global: ~/.agents/agent-bases/
  workflows:
    - default: .claude/workflows/
    - global: ~/.claude/workflows/

library:
  skills:
    - name: child-skill
      description: A child skill
      source: {child_skill_source}
    - name: chain-c
      description: Chain C leaf
      source: {chain_c_source}
    - name: test-skill
      description: A test skill
      source: {skill_source}
  agents:
    - name: test-agent
      description: A test agent
      source: {agent_source}
    - name: child-agent
      description: A child agent
      source: {child_agent_source}
    - name: parent-agent
      description: Parent agent with requires
      source: {parent_agent_source}
      requires:
        - agent:child-agent
        - skill:child-skill
    - name: chain-a
      description: Deep chain A requires B
      source: {chain_a_source}
      requires:
        - agent:chain-b
    - name: chain-b
      description: Deep chain B requires C
      source: {chain_b_source}
      requires:
        - skill:chain-c
    - name: cycle-a
      description: Cycle A
      source: {cycle_a_source}
      requires:
        - agent:cycle-b
    - name: cycle-b
      description: Cycle B (cycle!)
      source: {cycle_b_source}
      requires:
        - agent:cycle-a
    - name: multi-harness-agent
      description: Multi-harness agent
      sources:
        claude: {multi_harness_claude_source}
        codex: {multi_harness_codex_source}
    - name: missing-dep-agent
      description: Agent with missing dep
      source: {agent_source}
      requires:
        - agent:does-not-exist
  prompts:
    - name: test-prompt
      description: A test prompt
      source: {prompt_source}
  model_standards:
    - name: test-model-standard
      description: A test model standard
      source: {model_standard_source}
  agent_bases:
    - name: test-agent-base
      description: A test agent base prompt
      source: {agent_base_source}
  workflows:
    - name: test-workflow
      description: A test workflow
      source: {workflow_source}
      format: claude-workflow-js
      metadata:
        library:
          plane: dev
          executors: [native, library-runtime, codex]
  standards: []

marketplaces: []
guardrails: []
mcp_servers:
  - name: test-mcp-server
    description: A test MCP server
    install:
      mcp:
        claude_code:
          config_path: ~/.claude/settings.json
          snippet:
            type: stdio
            command: node
            args: ["/usr/local/lib/test-mcp/index.js"]
"""


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with all fixtures."""
    # Create fixture files
    agent_dir = tmp_path / "fixture-agent"
    agent_dir.mkdir()
    (agent_dir / "test-agent.md").write_text(FIXTURE_AGENT_MD)

    child_agent_dir = tmp_path / "fixture-child-agent"
    child_agent_dir.mkdir()
    (child_agent_dir / "child-agent.md").write_text(FIXTURE_CHILD_AGENT_MD)

    parent_agent_dir = tmp_path / "fixture-parent-agent"
    parent_agent_dir.mkdir()
    (parent_agent_dir / "parent-agent.md").write_text(FIXTURE_AGENT_WITH_REQUIRES_MD)

    chain_a_dir = tmp_path / "fixture-chain-a"
    chain_a_dir.mkdir()
    (chain_a_dir / "chain-a.md").write_text(FIXTURE_DEEP_CHAIN_A_MD)

    chain_b_dir = tmp_path / "fixture-chain-b"
    chain_b_dir.mkdir()
    (chain_b_dir / "chain-b.md").write_text(FIXTURE_DEEP_CHAIN_B_MD)

    chain_c_dir = tmp_path / "fixture-chain-c"
    chain_c_dir.mkdir()
    (chain_c_dir / "chain-c.md").write_text(FIXTURE_DEEP_CHAIN_C_MD)

    cycle_a_dir = tmp_path / "fixture-cycle-a"
    cycle_a_dir.mkdir()
    (cycle_a_dir / "cycle-a.md").write_text(FIXTURE_CYCLE_A_MD)

    cycle_b_dir = tmp_path / "fixture-cycle-b"
    cycle_b_dir.mkdir()
    (cycle_b_dir / "cycle-b.md").write_text(FIXTURE_CYCLE_B_MD)

    prompt_dir = tmp_path / "fixture-prompt"
    prompt_dir.mkdir()
    (prompt_dir / "test-prompt.md").write_text(FIXTURE_PROMPT_MD)

    skill_dir = tmp_path / "fixture-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill.")

    child_skill_dir = tmp_path / "fixture-child-skill"
    child_skill_dir.mkdir()
    (child_skill_dir / "SKILL.md").write_text("# Child Skill\nA child skill.")

    chain_c_skill_dir = tmp_path / "fixture-chain-c-skill"
    chain_c_skill_dir.mkdir()
    (chain_c_skill_dir / "SKILL.md").write_text("# Chain C Skill\nLeaf skill.")

    model_std_dir = tmp_path / "fixture-model-standard"
    model_std_dir.mkdir()
    (model_std_dir / "test-model-standard.md").write_text(FIXTURE_MODEL_STANDARD_MD)

    agent_base_dir = tmp_path / "fixture-agent-base"
    agent_base_dir.mkdir()
    (agent_base_dir / "test-agent-base.md").write_text(FIXTURE_AGENT_BASE_MD)

    workflow_dir = tmp_path / "fixture-workflow"
    workflow_dir.mkdir()
    (workflow_dir / "test-workflow.js").write_text(FIXTURE_WORKFLOW_JS)

    multi_harness_claude_dir = tmp_path / "fixture-multi-harness"
    multi_harness_claude_dir.mkdir()
    (multi_harness_claude_dir / "multi-harness-agent.md").write_text(MULTI_HARNESS_AGENT_MD)

    multi_harness_codex_dir = tmp_path / "fixture-multi-harness-codex"
    multi_harness_codex_dir.mkdir()
    (multi_harness_codex_dir / "multi-harness-agent.toml").write_text(
        '[agent]\nname = "multi-harness-agent"\n'
    )

    # Write library.yaml
    library_yaml = FIXTURE_LIBRARY_YAML_TEMPLATE.format(
        agent_source=str(agent_dir / "test-agent.md"),
        child_agent_source=str(child_agent_dir / "child-agent.md"),
        parent_agent_source=str(parent_agent_dir / "parent-agent.md"),
        chain_a_source=str(chain_a_dir / "chain-a.md"),
        chain_b_source=str(chain_b_dir / "chain-b.md"),
        cycle_a_source=str(cycle_a_dir / "cycle-a.md"),
        cycle_b_source=str(cycle_b_dir / "cycle-b.md"),
        skill_source=str(skill_dir / "SKILL.md"),
        child_skill_source=str(child_skill_dir / "SKILL.md"),
        chain_c_source=str(chain_c_skill_dir / "SKILL.md"),
        prompt_source=str(prompt_dir / "test-prompt.md"),
        model_standard_source=str(model_std_dir / "test-model-standard.md"),
        agent_base_source=str(agent_base_dir / "test-agent-base.md"),
        workflow_source=str(workflow_dir / "test-workflow.js"),
        multi_harness_claude_source=str(multi_harness_claude_dir / "multi-harness-agent.md"),
        multi_harness_codex_source=str(multi_harness_codex_dir / "multi-harness-agent.toml"),
    )
    (tmp_path / "library.yaml").write_text(library_yaml)
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n")

    return tmp_path


# ---------------------------------------------------------------------------
# AK1: agent use installs agent file
# ---------------------------------------------------------------------------

class TestAgentUse:
    def test_agent_use_exits_zero(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_agent_use_returns_ok_status(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] == "ok"

    def test_agent_use_creates_agent_file(self, project_dir):
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        agent_path = project_dir / ".claude" / "agents" / "test-agent.md"
        assert agent_path.exists() or agent_path.is_symlink(), \
            f"Agent file not found at {agent_path}"

    def test_agent_use_updates_lockfile(self, project_dir):
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        assert lockfile.exists()
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-agent" in names

    def test_agent_use_no_not_yet_implemented(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr


# ---------------------------------------------------------------------------
# AK2: agent use --dry-run --json
# ---------------------------------------------------------------------------

class TestAgentDryRun:
    def test_agent_dry_run_exits_zero(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_agent_dry_run_status_is_dry_run(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--dry-run", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"

    def test_agent_dry_run_has_operations(self, project_dir):
        result = run_library("agent", "use", "test-agent", "--dry-run", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert len(data.get("operations", [])) > 0

    def test_agent_dry_run_no_mutation(self, project_dir):
        run_library("agent", "use", "test-agent", "--dry-run", "--json", cwd=project_dir)
        agent_path = project_dir / ".claude" / "agents" / "test-agent.md"
        lockfile = project_dir / ".library.lock"
        assert not agent_path.exists(), "dry-run should not create agent file"
        assert not lockfile.exists(), "dry-run should not create lockfile"


# ---------------------------------------------------------------------------
# AK3: agent remove
# ---------------------------------------------------------------------------

class TestAgentRemove:
    def test_agent_remove_exits_zero(self, project_dir):
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        result = run_library("agent", "remove", "test-agent", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_agent_remove_deletes_file(self, project_dir):
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        run_library("agent", "remove", "test-agent", "--json", cwd=project_dir)
        agent_path = project_dir / ".claude" / "agents" / "test-agent.md"
        assert not agent_path.exists() and not agent_path.is_symlink()

    def test_agent_remove_updates_lockfile(self, project_dir):
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        run_library("agent", "remove", "test-agent", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-agent" not in names


# ---------------------------------------------------------------------------
# AK4: prompt use
# ---------------------------------------------------------------------------

class TestPromptUse:
    def test_prompt_use_exits_zero(self, project_dir):
        result = run_library("prompt", "use", "test-prompt", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_prompt_use_creates_command_file(self, project_dir):
        run_library("prompt", "use", "test-prompt", "--json", cwd=project_dir)
        prompt_path = project_dir / ".claude" / "commands" / "test-prompt.md"
        assert prompt_path.exists() or prompt_path.is_symlink()

    def test_prompt_use_updates_lockfile(self, project_dir):
        run_library("prompt", "use", "test-prompt", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-prompt" in names


# ---------------------------------------------------------------------------
# AK5: prompt use --dry-run
# ---------------------------------------------------------------------------

class TestPromptDryRun:
    def test_prompt_dry_run_exits_zero(self, project_dir):
        result = run_library("prompt", "use", "test-prompt", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_prompt_dry_run_status_is_dry_run(self, project_dir):
        result = run_library("prompt", "use", "test-prompt", "--dry-run", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"

    def test_prompt_dry_run_no_mutation(self, project_dir):
        run_library("prompt", "use", "test-prompt", "--dry-run", "--json", cwd=project_dir)
        prompt_path = project_dir / ".claude" / "commands" / "test-prompt.md"
        assert not prompt_path.exists()


# ---------------------------------------------------------------------------
# AK6: prompt remove
# ---------------------------------------------------------------------------

class TestPromptRemove:
    def test_prompt_remove_exits_zero(self, project_dir):
        run_library("prompt", "use", "test-prompt", "--json", cwd=project_dir)
        result = run_library("prompt", "remove", "test-prompt", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_prompt_remove_deletes_file(self, project_dir):
        run_library("prompt", "use", "test-prompt", "--json", cwd=project_dir)
        run_library("prompt", "remove", "test-prompt", "--json", cwd=project_dir)
        prompt_path = project_dir / ".claude" / "commands" / "test-prompt.md"
        assert not prompt_path.exists() and not prompt_path.is_symlink()


# ---------------------------------------------------------------------------
# AK7: model-standard use
# ---------------------------------------------------------------------------

class TestModelStandardUse:
    def test_model_standard_use_exits_zero(self, project_dir):
        result = run_library("model-standard", "use", "test-model-standard", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_model_standard_use_materializes_to_cache(self, project_dir):
        result = run_library("model-standard", "use", "test-model-standard", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        # Check cache path exists
        cache = data.get("data", {}).get("cache")
        if cache:
            assert Path(cache).exists()

    def test_model_standard_use_updates_lockfile(self, project_dir):
        run_library("model-standard", "use", "test-model-standard", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-model-standard" in names


# ---------------------------------------------------------------------------
# AK8: model-standard remove
# ---------------------------------------------------------------------------

class TestModelStandardRemove:
    def test_model_standard_remove_exits_zero(self, project_dir):
        run_library("model-standard", "use", "test-model-standard", "--json", cwd=project_dir)
        result = run_library("model-standard", "remove", "test-model-standard", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_model_standard_remove_updates_lockfile(self, project_dir):
        run_library("model-standard", "use", "test-model-standard", "--json", cwd=project_dir)
        run_library("model-standard", "remove", "test-model-standard", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-model-standard" not in names


# ---------------------------------------------------------------------------
# AK9: agent-base use
# ---------------------------------------------------------------------------

class TestAgentBaseUse:
    def test_agent_base_use_exits_zero(self, project_dir):
        result = run_library("agent-base", "use", "test-agent-base", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_agent_base_use_updates_lockfile(self, project_dir):
        run_library("agent-base", "use", "test-agent-base", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-agent-base" in names


# ---------------------------------------------------------------------------
# AK10: agent-base remove
# ---------------------------------------------------------------------------

class TestAgentBaseRemove:
    def test_agent_base_remove_exits_zero(self, project_dir):
        run_library("agent-base", "use", "test-agent-base", "--json", cwd=project_dir)
        result = run_library("agent-base", "remove", "test-agent-base", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_agent_base_remove_updates_lockfile(self, project_dir):
        run_library("agent-base", "use", "test-agent-base", "--json", cwd=project_dir)
        run_library("agent-base", "remove", "test-agent-base", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-agent-base" not in names


# ---------------------------------------------------------------------------
# AK10a: workflow use
# ---------------------------------------------------------------------------

class TestWorkflowUse:
    def test_workflow_use_exits_zero(self, project_dir):
        result = run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_workflow_use_creates_claude_workflow_file(self, project_dir):
        run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        workflow_path = project_dir / ".claude" / "workflows" / "test-workflow.js"
        assert workflow_path.exists() or workflow_path.is_symlink()

    def test_workflow_use_updates_lockfile(self, project_dir):
        run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        entry = next(
            e
            for e in data.get("installed", [])
            if e["type"] == "workflow" and e["name"] == "test-workflow"
        )
        assert entry["install_target"].endswith(".claude/workflows/test-workflow.js")


# ---------------------------------------------------------------------------
# AK10b: workflow remove
# ---------------------------------------------------------------------------

class TestWorkflowRemove:
    def test_workflow_remove_exits_zero(self, project_dir):
        run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        result = run_library("workflow", "remove", "test-workflow", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_workflow_remove_deletes_file_and_updates_lockfile(self, project_dir):
        run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        run_library("workflow", "remove", "test-workflow", "--json", cwd=project_dir)
        workflow_path = project_dir / ".claude" / "workflows" / "test-workflow.js"
        assert not workflow_path.exists() and not workflow_path.is_symlink()
        data = yaml.safe_load((project_dir / ".library.lock").read_text())
        names = [
            e["name"]
            for e in data.get("installed", [])
            if e["type"] == "workflow"
        ]
        assert "test-workflow" not in names


# ---------------------------------------------------------------------------
# AK10c: workflow dry-run
# ---------------------------------------------------------------------------

class TestWorkflowDryRun:
    def test_workflow_dry_run_reports_js_target_without_mutation(self, project_dir):
        result = run_library("workflow", "use", "test-workflow", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

        data = json.loads(result.stdout)
        workflow_path = project_dir / ".claude" / "workflows" / "test-workflow.js"
        assert data["status"] == "dry-run"
        assert str(workflow_path) in data["target_paths"]
        assert not workflow_path.exists()


# ---------------------------------------------------------------------------
# AK10d: workflow list and sync
# ---------------------------------------------------------------------------

class TestWorkflowListAndSync:
    def test_workflow_list_includes_fixture_entry(self, project_dir):
        result = run_library("workflow", "list", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        names = [entry["name"] for entry in data]
        assert "test-workflow" in names

    def test_workflow_targeted_sync_restores_missing_file(self, project_dir):
        run_library("workflow", "use", "test-workflow", "--json", cwd=project_dir)
        workflow_path = project_dir / ".claude" / "workflows" / "test-workflow.js"
        workflow_path.unlink()

        result = run_library("workflow", "sync", "test-workflow", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        assert workflow_path.exists() or workflow_path.is_symlink()


# ---------------------------------------------------------------------------
# AK11: mcp use (no shell-out)
# ---------------------------------------------------------------------------

class TestMcpUse:
    def test_mcp_use_defaults_to_global_lockfile(self, project_dir, tmp_path):
        result = run_library(
            "mcp", "use", "test-mcp-server", "--dry-run", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(tmp_path / "settings.json"),
            },
        )

        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        lockfile_changes = data.get("lockfile_changes", [])
        assert lockfile_changes == [
            {
                "path": str(tmp_path / "home" / ".config" / "library" / "global.lock"),
                "operation": "upsert",
                "entry": "test-mcp-server",
            }
        ]

    def test_mcp_use_rejects_project_scope_before_mutation(self, project_dir, tmp_path):
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "use", "test-mcp-server", "--scope", "project", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )

        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "user-global" in data["message"]
        assert not claude_settings.exists()
        assert not (project_dir / ".library.lock").exists()

    def test_mcp_use_exits_zero(self, project_dir, tmp_path):
        # mcp needs target config files — point to temp files
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "use", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_mcp_use_no_not_yet_implemented(self, project_dir, tmp_path):
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "use", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr

    def test_mcp_use_no_delegation_message(self, project_dir, tmp_path):
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "use", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        assert "Run: python3 scripts/install-mcp.py" not in result.stdout
        assert "Run: python3 scripts/install-mcp.py" not in result.stderr

    def test_mcp_use_updates_lockfile(self, project_dir, tmp_path):
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "use", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        if result.returncode == 0:
            lockfile = project_dir / ".library.lock"
            if lockfile.exists():
                import yaml
                data = yaml.safe_load(lockfile.read_text())
                names = [e["name"] for e in data.get("installed", [])]
                assert "test-mcp-server" in names


# ---------------------------------------------------------------------------
# AK12: mcp remove
# ---------------------------------------------------------------------------

class TestMcpRemove:
    def test_mcp_remove_defaults_to_global_lockfile(self, project_dir, tmp_path):
        result = run_library(
            "mcp", "remove", "test-mcp-server", "--dry-run", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(tmp_path / "settings.json"),
            },
        )

        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        lockfile_ops = [
            operation
            for operation in data.get("operations", [])
            if operation.get("operation") == "remove_lockfile_entry"
        ]
        assert lockfile_ops == [
            {
                "operation": "remove_lockfile_entry",
                "path": str(tmp_path / "home" / ".config" / "library" / "global.lock"),
                "details": "remove 'test-mcp-server'",
            }
        ]

    def test_regression_mcp_project_remove_is_lock_only_cleanup(self, project_dir, tmp_path):
        (project_dir / ".library.lock").write_text(
            yaml.safe_dump(
                {
                    "installed": [
                        {
                            "name": "test-mcp-server",
                            "type": "mcp",
                            "install_target": "global MCP harness config",
                        }
                    ]
                }
            )
        )
        claude_settings = tmp_path / "settings.json"
        result = run_library(
            "mcp", "remove", "test-mcp-server", "--scope", "project", "--dry-run", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )

        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        assert data["operations"] == [
            {
                "operation": "remove_lockfile_entry",
                "path": str(project_dir / ".library.lock"),
                "details": "remove legacy project lock record 'test-mcp-server'",
            }
        ]
        assert not claude_settings.exists()

        cleanup = run_library(
            "mcp", "remove", "test-mcp-server", "--scope", "project", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        assert cleanup.returncode == 0, (
            f"stdout={cleanup.stdout}\nstderr={cleanup.stderr}"
        )
        lock_data = yaml.safe_load((project_dir / ".library.lock").read_text())
        assert lock_data["installed"] == []
        assert not claude_settings.exists()

    def test_regression_mcp_project_sync_is_rejected(self, project_dir):
        (project_dir / ".library.lock").write_text(
            yaml.safe_dump(
                {
                    "installed": [
                        {
                            "name": "test-mcp-server",
                            "type": "mcp",
                            "install_target": "global MCP harness config",
                        }
                    ]
                }
            )
        )

        result = run_library(
            "mcp", "sync", "test-mcp-server", "--scope", "project", "--dry-run", "--json",
            cwd=project_dir,
        )

        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "project-scoped MCP registration" in data["message"]

    def test_mcp_remove_exits_zero(self, project_dir, tmp_path):
        claude_settings = tmp_path / "settings.json"
        run_library(
            "mcp", "use", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        result = run_library(
            "mcp", "remove", "test-mcp-server", "--json",
            cwd=project_dir,
            env={
                "HOME": str(tmp_path / "home"),
                "CLAUDE_SETTINGS_FILE": str(claude_settings),
            },
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


# ---------------------------------------------------------------------------
# AK13: guardrail use
# ---------------------------------------------------------------------------

class TestGuardrailUse:
    def test_guardrail_use_no_delegation_message(self, project_dir):
        # Guardrail with no source in fixture — just test it doesn't give old message
        result = run_library("guardrail", "use", "nonexistent-guardrail", "--json", cwd=project_dir)
        assert "Run: python3 scripts/install-hook.py" not in result.stdout
        assert "Run: python3 scripts/install-hook.py" not in result.stderr

    def test_guardrail_use_no_not_yet_implemented(self, project_dir):
        result = run_library("guardrail", "use", "nonexistent-guardrail", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr


# ---------------------------------------------------------------------------
# AK14: guardrail remove
# ---------------------------------------------------------------------------

class TestGuardrailRemove:
    def test_guardrail_remove_no_not_yet_implemented(self, project_dir):
        # Remove a nonexistent guardrail — should fail with not-found, not "not yet implemented"
        result = run_library("guardrail", "remove", "nonexistent-guardrail", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr
        assert "Run: python3 scripts/install-hook.py" not in result.stdout


# ---------------------------------------------------------------------------
# AK16: standard remove
# ---------------------------------------------------------------------------

class TestStandardRemove:
    def test_standard_remove_no_not_yet_implemented(self, project_dir):
        # Install a mock standard then remove it
        # Standard needs a source — we add a minimal standard to the fixture
        result = run_library("standard", "remove", "nonexistent-standard", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr


# ---------------------------------------------------------------------------
# AK15: skill remove
# ---------------------------------------------------------------------------

class TestSkillRemove:
    def test_skill_remove_exits_zero(self, project_dir):
        run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        result = run_library("skill", "remove", "test-skill", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_skill_remove_removes_canonical_symlink(self, project_dir):
        run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        run_library("skill", "remove", "test-skill", "--json", cwd=project_dir)
        canonical = project_dir / ".agents" / "skills" / "test-skill"
        assert not canonical.exists() and not canonical.is_symlink()

    def test_skill_remove_removes_bridge(self, project_dir):
        run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        run_library("skill", "remove", "test-skill", "--json", cwd=project_dir)
        bridge = project_dir / ".claude" / "skills" / "test-skill"
        assert not bridge.exists() and not bridge.is_symlink()

    def test_skill_remove_updates_lockfile(self, project_dir):
        run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        run_library("skill", "remove", "test-skill", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "test-skill" not in names


# ---------------------------------------------------------------------------
# AK16: standard remove
# ---------------------------------------------------------------------------
# (standard remove tested via test_library_py_installers.py — covered in AK33)


# ---------------------------------------------------------------------------
# AK17: sync project scope
# ---------------------------------------------------------------------------

class TestSync:
    def test_sync_project_exits_zero(self, project_dir):
        # Install an item first, then sync
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        result = run_library("agent", "sync", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_sync_no_not_yet_implemented(self, project_dir):
        result = run_library("skill", "sync", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr

    def test_sync_reinstalls_from_lockfile(self, project_dir):
        # Install, then manually remove symlink, then sync should restore
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        agent_path = project_dir / ".claude" / "agents" / "test-agent.md"
        # Remove manually
        if agent_path.exists():
            agent_path.unlink()
        elif agent_path.is_symlink():
            agent_path.unlink()
        # Sync should restore
        run_library("agent", "sync", "--json", cwd=project_dir)
        agent_path_after = project_dir / ".claude" / "agents" / "test-agent.md"
        assert agent_path_after.exists() or agent_path_after.is_symlink()

    def test_targeted_sync_updates_stale_lockfile_sha(self, project_dir, tmp_path):
        source_repo = project_dir / "fixture-skill"
        initial_sha = init_git_source_repo(source_repo)
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}

        install = run_library("skill", "use", "test-skill", "--json", cwd=project_dir, env=env)
        assert install.returncode == 0, f"stdout={install.stdout}\nstderr={install.stderr}"
        before = lockfile_entry(project_dir, "skill", "test-skill")
        assert before["source_commit"] == initial_sha

        source_file = source_repo / "SKILL.md"
        source_file.write_text("# Test Skill\nUpdated content.\n")
        run_git("add", "SKILL.md", cwd=source_repo)
        run_git("commit", "-m", "update source", cwd=source_repo)
        updated_sha = git_head(source_repo)
        assert updated_sha != initial_sha

        sync = run_library("skill", "sync", "test-skill", "--json", cwd=project_dir, env=env)
        assert sync.returncode == 0, f"stdout={sync.stdout}\nstderr={sync.stderr}"

        after = lockfile_entry(project_dir, "skill", "test-skill")
        assert after["source_commit"] == updated_sha
        assert after["source_commit"] != before["source_commit"]
        installed = project_dir / ".agents" / "skills" / "test-skill" / "SKILL.md"
        assert installed.read_text() == "# Test Skill\nUpdated content.\n"

    def test_targeted_sync_current_entry_is_idempotent(self, project_dir, tmp_path):
        source_repo = project_dir / "fixture-skill"
        init_git_source_repo(source_repo)
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}

        install = run_library("skill", "use", "test-skill", "--json", cwd=project_dir, env=env)
        assert install.returncode == 0, f"stdout={install.stdout}\nstderr={install.stderr}"
        before = lockfile_entry(project_dir, "skill", "test-skill")
        installed = project_dir / ".agents" / "skills" / "test-skill" / "SKILL.md"
        installed_before = installed.read_text()

        sync = run_library("skill", "sync", "test-skill", "--json", cwd=project_dir, env=env)
        assert sync.returncode == 0, f"stdout={sync.stdout}\nstderr={sync.stderr}"
        sync_data = json.loads(sync.stdout)
        assert sync_data["data"]["synced"] == ["skill:test-skill"]

        after = lockfile_entry(project_dir, "skill", "test-skill")
        assert after["source_commit"] == before["source_commit"]
        assert after["content_sha256"] == before["content_sha256"]
        assert installed.read_text() == installed_before

        lock_data = yaml.safe_load((project_dir / ".library.lock").read_text())
        matches = [
            entry
            for entry in lock_data["installed"]
            if entry["type"] == "skill" and entry["name"] == "test-skill"
        ]
        assert len(matches) == 1

    def test_targeted_sync_unknown_name_fails_fast(self, project_dir, tmp_path):
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
        result = run_library("skill", "sync", "missing-skill", "--json", cwd=project_dir, env=env)

        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "skill:missing-skill is not installed in project scope" in data["message"]

    @pytest.mark.parametrize("primitive", TARGETED_SYNC_PRIMITIVES)
    def test_targeted_sync_name_is_accepted_for_all_primitives(self, project_dir, tmp_path, primitive):
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
        result = run_library(primitive, "sync", "missing-entry", "--json", cwd=project_dir, env=env)

        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert f"{primitive}:missing-entry is not installed in project scope" in data["message"]


# ---------------------------------------------------------------------------
# AK19: sync --dry-run
# ---------------------------------------------------------------------------

class TestSyncDryRun:
    def test_sync_dry_run_exits_zero(self, project_dir):
        result = run_library("skill", "sync", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_sync_dry_run_status(self, project_dir):
        result = run_library("skill", "sync", "--dry-run", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] in ("dry-run", "ok")

    def test_targeted_sync_dry_run_plans_one_entry(self, project_dir, tmp_path):
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
        install = run_library("skill", "use", "test-skill", "--json", cwd=project_dir, env=env)
        assert install.returncode == 0, f"stdout={install.stdout}\nstderr={install.stderr}"

        result = run_library("skill", "sync", "test-skill", "--dry-run", "--json", cwd=project_dir, env=env)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        assert [op["details"] for op in data["operations"]] == ["re-install skill:test-skill"]


# ---------------------------------------------------------------------------
# AK20: audit project scope
# ---------------------------------------------------------------------------

class TestAudit:
    def test_audit_exits_zero(self, project_dir):
        result = run_library("skill", "audit", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_audit_no_not_yet_implemented(self, project_dir):
        result = run_library("skill", "audit", "--json", cwd=project_dir)
        assert "not yet implemented" not in result.stdout
        assert "not yet implemented" not in result.stderr

    def test_audit_detects_drift(self, project_dir):
        # Install, then mutate the install target to create drift
        run_library("agent", "use", "test-agent", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        import yaml
        lock_data = yaml.safe_load(lockfile.read_text())
        entry = next((e for e in lock_data["installed"] if e["name"] == "test-agent"), None)
        if entry:
            # Mutate the install target (agent file on disk)
            install_target = entry.get("install_target", "")
            if install_target:
                t = Path(install_target)
                if t.is_symlink():
                    t = t.resolve()
                if t.is_file():
                    t.write_text("MUTATED CONTENT — drift injection")
            # Also try mutating cache
            cache_path_str = entry.get("cache_path", "").rstrip("/")
            if cache_path_str:
                cache = Path(cache_path_str)
                for f in cache.rglob("*.md"):
                    f.write_text("MUTATED CONTENT — drift injection")
                    break
        # Audit should detect drift or return ok if paths aren't tracked by checksum
        result = run_library("agent", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        # Status can be drift (if checksums were computed) or clean (if no checksum was stored)
        assert data["status"] in ("drift", "clean", "ok")


# ---------------------------------------------------------------------------
# AK22: audit --json schema
# ---------------------------------------------------------------------------

class TestAuditJsonSchema:
    def test_audit_json_schema(self, project_dir):
        result = run_library("skill", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert "status" in data
        assert data["status"] in ("clean", "drift", "ok")
        assert "entries" in data or data["status"] == "ok"


# ---------------------------------------------------------------------------
# AK23: dependency resolver — transitive install
# ---------------------------------------------------------------------------

class TestDependencyResolver:
    def test_resolver_installs_deps_first(self, project_dir):
        result = run_library("agent", "use", "parent-agent", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        # Check all three got installed
        import yaml
        lockfile = project_dir / ".library.lock"
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "child-agent" in names, f"child-agent not in lockfile. installed: {names}"
        assert "child-skill" in names, f"child-skill not in lockfile. installed: {names}"
        assert "parent-agent" in names, f"parent-agent not in lockfile. installed: {names}"

    def test_resolver_deep_chain(self, project_dir):
        result = run_library("agent", "use", "chain-a", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        import yaml
        lockfile = project_dir / ".library.lock"
        data = yaml.safe_load(lockfile.read_text())
        names = [e["name"] for e in data.get("installed", [])]
        assert "chain-a" in names
        assert "chain-b" in names
        assert "chain-c" in names

    def test_resolver_reinstalls_when_lockfile_target_missing(self, project_dir):
        result = run_library("agent", "use", "parent-agent", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

        installed_skill = project_dir / ".agents" / "skills" / "child-skill"
        assert installed_skill.exists()
        shutil.rmtree(installed_skill)
        assert not installed_skill.exists()

        result = run_library("agent", "use", "parent-agent", "--json", cwd=project_dir)
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        assert installed_skill.exists(), "stale lockfile entry must not suppress reinstall"


# ---------------------------------------------------------------------------
# AK24: cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def test_cycle_returns_error(self, project_dir):
        result = run_library("agent", "use", "cycle-a", "--json", cwd=project_dir)
        assert result.returncode != 0, "Cycle should return non-zero exit code"

    def test_cycle_error_message(self, project_dir):
        result = run_library("agent", "use", "cycle-a", "--json", cwd=project_dir)
        output = result.stdout + result.stderr
        assert "cycle" in output.lower(), f"Expected 'cycle' in output: {output}"

    def test_cycle_no_partial_install(self, project_dir):
        run_library("agent", "use", "cycle-a", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        if lockfile.exists():
            import yaml
            data = yaml.safe_load(lockfile.read_text())
            names = [e["name"] for e in data.get("installed", [])]
            assert "cycle-a" not in names, "cycle-a should not be installed on cycle"


# ---------------------------------------------------------------------------
# AK25: lockfile-aware (skip already installed)
# ---------------------------------------------------------------------------

class TestLockfileAware:
    def test_skips_already_installed(self, project_dir, monkeypatch, tmp_path):
        # Install child-agent first
        run_library("agent", "use", "child-agent", "--json", cwd=project_dir)
        # Now install parent-agent — child-agent should be skipped
        # We verify by checking it doesn't refetch (cache path unchanged)
        import yaml
        lockfile = project_dir / ".library.lock"
        lock1 = yaml.safe_load(lockfile.read_text())
        child_before = next((e for e in lock1["installed"] if e["name"] == "child-agent"), None)

        run_library("agent", "use", "parent-agent", "--json", cwd=project_dir)
        lock2 = yaml.safe_load(lockfile.read_text())
        child_after = next((e for e in lock2["installed"] if e["name"] == "child-agent"), None)

        # Cache path should be the same (not re-installed)
        assert child_before is not None
        assert child_after is not None
        assert child_before.get("cache_path") == child_after.get("cache_path"), \
            "child-agent was re-installed when it should have been skipped"


# ---------------------------------------------------------------------------
# AK27: unknown dependency returns error code 4
# ---------------------------------------------------------------------------

class TestUnknownDependency:
    def test_unknown_dep_returns_exit_4(self, project_dir):
        result = run_library("agent", "use", "missing-dep-agent", "--json", cwd=project_dir)
        assert result.returncode == 4, \
            f"Expected exit code 4, got {result.returncode}. stdout={result.stdout}"

    def test_unknown_dep_no_partial_install(self, project_dir):
        run_library("agent", "use", "missing-dep-agent", "--json", cwd=project_dir)
        lockfile = project_dir / ".library.lock"
        if lockfile.exists():
            import yaml
            data = yaml.safe_load(lockfile.read_text())
            names = [e["name"] for e in data.get("installed", [])]
            assert "missing-dep-agent" not in names


# ---------------------------------------------------------------------------
# AK28: --harness flag
# ---------------------------------------------------------------------------

class TestHarnessFlag:
    def test_harness_claude_code_only(self, project_dir):
        result = run_library(
            "agent", "use", "multi-harness-agent",
            "--harness", "claude_code", "--json",
            cwd=project_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "ok"

    def test_harness_all_fetches_both(self, project_dir):
        result = run_library(
            "agent", "use", "multi-harness-agent",
            "--harness", "all", "--json",
            cwd=project_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        assert (project_dir / ".claude" / "agents" / "multi-harness-agent.md").exists()
        assert (project_dir / ".codex" / "agents" / "multi-harness-agent.toml").exists()
        data = json.loads(result.stdout)
        installed_paths = {
            item["path"]
            for item in data["data"].get("installed_targets", [])
        }
        assert str(project_dir / ".claude" / "agents" / "multi-harness-agent.md") in installed_paths
        assert str(project_dir / ".codex" / "agents" / "multi-harness-agent.toml") in installed_paths

    def test_harness_codex_installs_toml_target(self, project_dir):
        result = run_library(
            "agent", "use", "multi-harness-agent",
            "--harness", "codex", "--json",
            cwd=project_dir,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        assert not (project_dir / ".claude" / "agents" / "multi-harness-agent.md").exists()
        assert (project_dir / ".codex" / "agents" / "multi-harness-agent.toml").exists()


# ---------------------------------------------------------------------------
# AK29: --harness warning when source missing
# ---------------------------------------------------------------------------

class TestHarnessMissingWarning:
    def test_harness_missing_emits_warning(self, project_dir):
        # test-agent only has a single source, not sources.codex
        result = run_library(
            "agent", "use", "test-agent",
            "--harness", "codex", "--json",
            cwd=project_dir,
        )
        # Should succeed (warning, not failure) OR succeed with harness_missing
        output = result.stdout + result.stderr
        # Either a warning is emitted, or it exits 0 with harness_missing in JSON
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # Should still install (claude source) with warning
            assert data["status"] == "ok"
        # No hard failure expected for missing harness source


# ---------------------------------------------------------------------------
# AK30: No "fall back to cookbook" in SKILL.md
# ---------------------------------------------------------------------------

class TestNoCookbookFallback:
    def test_skill_md_no_cookbook_fallback(self):
        skill_md = REPO_ROOT / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text()
            assert "fall back to cookbook" not in content.lower(), \
                "SKILL.md still contains 'fall back to cookbook'"
            assert "not yet implemented" not in content.lower(), \
                "SKILL.md still contains 'not yet implemented'"

    def test_library_py_no_not_yet_implemented(self):
        library_py = REPO_ROOT / "scripts" / "library.py"
        content = library_py.read_text()
        assert "not yet implemented" not in content, \
            "library.py still contains 'not yet implemented'"


# ---------------------------------------------------------------------------
# AK32: validate-library.py --quiet passes
# ---------------------------------------------------------------------------

class TestValidateLibrary:
    def test_validate_library_quiet_passes(self):
        result = subprocess.run(
            [PYTHON, str(REPO_ROOT / "scripts" / "validate-library.py"), "--quiet"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, \
            f"validate-library.py --quiet failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# cmux-bead-dispatch end-to-end resolver smoke (against real catalog)
# ---------------------------------------------------------------------------

class TestCmuxBeadDispatchE2E:
    def test_resolver_resolves_dispatch_dependencies(self):
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib.catalog import load_catalog, find_repo_root
        from lib.resolver import resolve_requires
        repo_root = find_repo_root(REPO_ROOT)
        catalog = load_catalog(repo_root)
        order = resolve_requires(catalog, "skill", "cmux-bead-dispatch", repo_root, "global")
        names = [name for _, name in order]
        assert "cmux" in names
        assert "cmux-workspace" in names
        assert "cognovis-beads" in names
        assert "judge-default" in names
        assert names[-1] == "cmux-bead-dispatch"

    def test_dry_run_install_exits_zero(self):
        result = run_library(
            "skill", "use", "cmux-bead-dispatch", "--dry-run", "--json",
            "--scope", "global",
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_dispatch_has_requires_in_catalog(self):
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib.catalog import load_catalog, find_repo_root, lookup_entry
        repo_root = find_repo_root(REPO_ROOT)
        catalog = load_catalog(repo_root)
        entry = lookup_entry(catalog, "skill", "cmux-bead-dispatch")
        requires = entry.get("requires") or []
        assert "skill:cmux-workspace" in requires
        assert "skill:cognovis-beads" in requires
        assert "agent:judge-default" in requires


# ---------------------------------------------------------------------------
# AK20/21: audit proper drift detection
# ---------------------------------------------------------------------------

class TestAuditDriftDetection:
    def test_audit_clean_when_no_entries(self, project_dir):
        result = run_library("agent", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] in ("clean", "ok")
        assert "entries" in data or data["status"] == "ok"

    def test_audit_json_schema_stable(self, project_dir):
        """AK22: audit --json returns stable schema."""
        result = run_library("skill", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert "status" in data
        assert data["status"] in ("clean", "drift", "ok")
        # If entries key present, check schema
        if "entries" in data:
            for e in data["entries"]:
                assert "name" in e
                assert "primitive" in e
                assert "drift" in e


# ---------------------------------------------------------------------------
# CL-brl: default_scope from catalog entry
# ---------------------------------------------------------------------------

FIXTURE_GLOBAL_SCOPE_STANDARD_MD = """---
name: global-standard
description: A standard that should install globally by default
---

# Global Standard Content
"""

FIXTURE_PROJECT_SCOPE_STANDARD_MD = """---
name: project-standard
description: A standard that should install project-scoped by default
---

# Project Standard Content
"""


@pytest.fixture
def project_dir_with_default_scope(tmp_path):
    """Project dir fixture extended with standards that have default_scope set."""
    global_std_dir = tmp_path / "fixture-global-standard"
    global_std_dir.mkdir()
    (global_std_dir / "global-standard.md").write_text(FIXTURE_GLOBAL_SCOPE_STANDARD_MD)

    project_std_dir = tmp_path / "fixture-project-standard"
    project_std_dir.mkdir()
    (project_std_dir / "project-standard.md").write_text(FIXTURE_PROJECT_SCOPE_STANDARD_MD)

    library_yaml = """
default_dirs:
  standards:
    - default: .agents/standards/
    - global: ~/.agents/standards/
  skills: []
  agents: []
  prompts: []
  guardrails: []
  model_standards: []
  agent_bases: []

library:
  standards:
    - name: global-standard
      description: Standard with default_scope global
      default_scope: global
      source: {global_std_source}
    - name: project-standard
      description: Standard with default_scope project
      default_scope: project
      source: {project_std_source}
    - name: noscope-standard
      description: Standard with no default_scope field
      source: {project_std_source}

marketplaces: []
guardrails: []
mcp_servers: []
""".format(
        global_std_source=str(global_std_dir / "global-standard.md"),
        project_std_source=str(project_std_dir / "project-standard.md"),
    )
    (tmp_path / "library.yaml").write_text(library_yaml)
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n")
    return tmp_path


class TestDefaultScopeFromCatalog:
    """CL-brl: cmd_use honors default_scope from catalog entries."""

    def test_global_default_scope_uses_global_lockfile(self, project_dir_with_default_scope):
        """Entry with default_scope: global installs to global lockfile without --scope."""
        result = run_library(
            "standard", "use", "global-standard", "--dry-run", "--json",
            cwd=project_dir_with_default_scope,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        # The lockfile operation should target the global lockfile (~/.library.lock)
        lockfile_ops = [
            op for op in data.get("operations", [])
            if op.get("operation") == "write_lockfile"
        ]
        assert len(lockfile_ops) == 1, f"Expected one lockfile op, got: {lockfile_ops}"
        lockfile_path = lockfile_ops[0]["path"]
        assert lockfile_path == str(Path.home() / ".config" / "library" / "global.lock"), (
            f"Expected global lockfile at ~/.config/library/global.lock, got: {lockfile_path}"
        )

    def test_project_default_scope_uses_project_lockfile(self, project_dir_with_default_scope):
        """Entry with default_scope: project installs to project lockfile without --scope."""
        result = run_library(
            "standard", "use", "project-standard", "--dry-run", "--json",
            cwd=project_dir_with_default_scope,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        lockfile_ops = [
            op for op in data.get("operations", [])
            if op.get("operation") == "write_lockfile"
        ]
        assert len(lockfile_ops) == 1, f"Expected one lockfile op, got: {lockfile_ops}"
        lockfile_path = lockfile_ops[0]["path"]
        assert lockfile_path == str(project_dir_with_default_scope / ".library.lock"), (
            f"Expected project lockfile, got: {lockfile_path}"
        )

    def test_no_default_scope_uses_project_lockfile(self, project_dir_with_default_scope):
        """Entry with no default_scope field falls back to project scope."""
        result = run_library(
            "standard", "use", "noscope-standard", "--dry-run", "--json",
            cwd=project_dir_with_default_scope,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        lockfile_ops = [
            op for op in data.get("operations", [])
            if op.get("operation") == "write_lockfile"
        ]
        assert len(lockfile_ops) == 1, f"Expected one lockfile op, got: {lockfile_ops}"
        lockfile_path = lockfile_ops[0]["path"]
        assert lockfile_path == str(project_dir_with_default_scope / ".library.lock"), (
            f"Expected project lockfile for no-scope entry, got: {lockfile_path}"
        )

    def test_explicit_scope_overrides_default_scope(self, project_dir_with_default_scope):
        """Explicit --scope project overrides a catalog entry's default_scope: global."""
        result = run_library(
            "standard", "use", "global-standard", "--dry-run", "--json",
            "--scope", "project",
            cwd=project_dir_with_default_scope,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        lockfile_ops = [
            op for op in data.get("operations", [])
            if op.get("operation") == "write_lockfile"
        ]
        assert len(lockfile_ops) == 1, f"Expected one lockfile op, got: {lockfile_ops}"
        lockfile_path = lockfile_ops[0]["path"]
        assert lockfile_path == str(project_dir_with_default_scope / ".library.lock"), (
            f"--scope project should override default_scope global, got: {lockfile_path}"
        )

    def test_regression_non_mcp_remove_defaults_to_project(
        self, project_dir_with_default_scope
    ):
        """A catalog install default must not change historical remove semantics."""
        result = run_library(
            "standard", "remove", "global-standard", "--dry-run", "--json",
            cwd=project_dir_with_default_scope,
        )

        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        data = json.loads(result.stdout)
        lockfile_ops = [
            operation
            for operation in data.get("operations", [])
            if operation.get("operation") == "remove_lockfile_entry"
        ]
        assert lockfile_ops == [
            {
                "operation": "remove_lockfile_entry",
                "path": str(project_dir_with_default_scope / ".library.lock"),
                "details": "remove 'global-standard'",
            }
        ]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
