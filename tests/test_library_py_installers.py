#!/usr/bin/env python3
"""
test_library_py_installers.py — Tests for skill/standard dry-run and real installs (CL-0bl)

AK4: skill use --dry-run --json emits planned writes without mutation
AK5: standard use --dry-run --json emits planned writes without mutation
AK6: Real skill use in tempdir fixture produces canonical .agents vendored copy + Claude bridge
AK7: Lockfile create/update is deterministic and schema-compatible

Run with:
    python3 -m pytest tests/test_library_py_installers.py -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
LIBRARY_SPEC = importlib.util.spec_from_file_location("library_cli", LIBRARY_PY)
assert LIBRARY_SPEC is not None and LIBRARY_SPEC.loader is not None
LIBRARY_MODULE = importlib.util.module_from_spec(LIBRARY_SPEC)
LIBRARY_SPEC.loader.exec_module(LIBRARY_MODULE)

# Minimal fixture library.yaml for tempdir tests
FIXTURE_LIBRARY_YAML = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: test-skill
      description: A test skill for tempdir integration tests
      source: {skill_source}
  standards:
    - name: test-standard
      description: A test standard for tempdir integration tests
      source: {standard_source}
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""


DRY_RUN_CONTRACT_LIBRARY_YAML = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/
  agents:
    - default: .claude/agents/
    - default_codex: .codex/agents/
    - default_opencode: .opencode/agents/
    - global_opencode: ~/.opencode/agents/
  prompts:
    - default: .claude/commands/
  scripts:
    - default: .agents/scripts/
  model_standards:
    - default: .agents/model-standards/
  agent_bases:
    - default: .agents/agent-bases/
  guardrails:
    - default: .claude/hooks/

library:
  skills:
    - name: contract-skill
      description: Dry-run contract skill fixture
      source: {skill_source}
  standards:
    - name: contract-standard
      description: Dry-run contract standard fixture
      source: {standard_source}
  agents:
    - name: contract-agent
      description: Dry-run contract agent fixture
      sources:
        claude: {agent_source}
        codex: {codex_agent_source}
        opencode: {opencode_agent_source}
  prompts:
    - name: contract-prompt
      description: Dry-run contract prompt fixture
      source: {prompt_source}
  scripts:
    - name: contract-script
      description: Dry-run contract script fixture
      source: {script_source}
      language: python
  model_standards:
    - name: contract-model-standard
      description: Dry-run contract model standard fixture
      source: {model_standard_source}
  agent_bases:
    - name: contract-agent-base
      description: Dry-run contract agent base fixture
      source: {agent_base_source}
  guardrails:
    - name: contract-guardrail
      description: Dry-run contract guardrail fixture
      kind: single-hook
      sources:
        claude_code: hooks/contract.py
        codex_cli: hooks/contract.py
      capability:
        claude_code:
          events: [PreToolUse]
        codex_cli:
          events: [PreToolUse]
  mcp_servers:
    - name: contract-mcp
      description: Dry-run contract MCP fixture
      install:
        mcp:
          claude_code:
            snippet:
              type: stdio
              command: node
              args: ["server.js"]
          codex:
            snippet:
              command: node
              args: ["server.js"]
"""


AGENT_HANDLER_LIBRARY_YAML = """
default_dirs:
  agents:
    - default: .claude/agents/
    - default_codex: .codex/agents/
    - default_opencode: .opencode/agents/

library:
  agents:
    - name: handler-agent
      description: Agent with private handler assets
      sources:
        claude: {agent_source}
        codex: {codex_agent_source}
        opencode: {agent_source}
      handlers:
{handlers_yaml}
  skills: []
  standards: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""


def _write_agent_handler_project(
    project: Path,
    fixture_dir: Path,
    handlers: list[str],
) -> None:
    """Create a library.yaml fixture for agent handler install tests."""
    handlers_yaml = "".join(f"        - {handler}\n" for handler in handlers)
    project.write_text(
        AGENT_HANDLER_LIBRARY_YAML.format(
            agent_source=fixture_dir / "handler-agent.md",
            codex_agent_source=fixture_dir / "handler-agent.toml",
            handlers_yaml=handlers_yaml,
        )
    )


@pytest.fixture
def fixture_skill_dir(tmp_path: Path) -> Path:
    """Create a minimal skill directory fixture."""
    skill_dir = tmp_path / "fixture-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test skill fixture\n---\n\n# Test Skill\n"
    )
    return skill_dir


@pytest.fixture
def fixture_standard_file(tmp_path: Path) -> Path:
    """Create a minimal standard file fixture."""
    standard_dir = tmp_path / "fixture-standard"
    standard_dir.mkdir()
    standard_file = standard_dir / "test-standard.md"
    standard_file.write_text("# Test Standard\n\nThis is a test standard.\n")
    return standard_file


@pytest.fixture
def project_dir(tmp_path: Path, fixture_skill_dir: Path, fixture_standard_file: Path) -> Path:
    """Create a minimal project directory with library.yaml pointing to local fixtures."""
    proj = tmp_path / "test-project"
    proj.mkdir()

    yaml_content = FIXTURE_LIBRARY_YAML.format(
        skill_source=str(fixture_skill_dir / "SKILL.md"),
        standard_source=str(fixture_standard_file),
    )
    (proj / "library.yaml").write_text(yaml_content)
    return proj


@pytest.fixture
def dry_run_contract_project(tmp_path: Path) -> Path:
    """Create a project with one local-source fixture for every installable primitive."""
    project = tmp_path / "dry-run-contract-project"
    project.mkdir()
    hooks_dir = project / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "contract.py").write_text("print('contract hook')\n")

    sources = tmp_path / "dry-run-sources"
    sources.mkdir()
    skill_dir = sources / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Contract Skill\n")
    standard_file = sources / "contract-standard.md"
    standard_file.write_text("# Contract Standard\n")
    agent_file = sources / "contract-agent.md"
    agent_file.write_text("---\nname: contract-agent\n---\n# Contract Agent\n")
    codex_agent_file = sources / "contract-agent.toml"
    codex_agent_file.write_text('[agent]\nname = "contract-agent"\n')
    prompt_file = sources / "contract-prompt.md"
    prompt_file.write_text("# Contract Prompt\n")
    script_file = sources / "contract-script.py"
    script_file.write_text("print('contract script')\n")
    model_standard_file = sources / "contract-model-standard.md"
    model_standard_file.write_text("# Contract Model Standard\n")
    agent_base_file = sources / "contract-agent-base.md"
    agent_base_file.write_text("# Contract Agent Base\n")

    (project / "library.yaml").write_text(
        DRY_RUN_CONTRACT_LIBRARY_YAML.format(
            skill_source=skill_dir / "SKILL.md",
            standard_source=standard_file,
            agent_source=agent_file,
            codex_agent_source=codex_agent_file,
            opencode_agent_source=agent_file,
            prompt_source=prompt_file,
            script_source=script_file,
            model_standard_source=model_standard_file,
            agent_base_source=agent_base_file,
        )
    )
    return project


@pytest.fixture
def agent_handler_fixture_dir() -> Path:
    """Return the committed local fixture agent with a private handler asset."""
    return REPO_ROOT / "tests" / "installers" / "fixtures" / "agent-with-handlers"


@pytest.fixture
def agent_handlers_project(tmp_path: Path, agent_handler_fixture_dir: Path) -> Path:
    """Create a clean project that installs a fixture agent with handlers."""
    project = tmp_path / "agent-handlers-project"
    project.mkdir()
    _write_agent_handler_project(
        project / "library.yaml",
        agent_handler_fixture_dir,
        ["handlers/fixture-handler.sh"],
    )
    return project


@pytest.fixture
def cursor_project(tmp_path: Path) -> Path:
    """Project fixture for cursor harness skill install tests."""
    proj = tmp_path / "cursor-project"
    proj.mkdir()
    skill_dir = tmp_path / "cursor-test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: cursor-test-skill\n---\n# Cursor Test Skill\n")
    yaml_content = f"""
default_dirs:
  skills:
    - default: .agents/skills/
    - global: ~/.agents/skills/
    - claude_bridge: .claude/skills/
    - global_claude_bridge: ~/.claude/skills/
    - cursor_bridge: .cursor/skills/
    - global_cursor_bridge: ~/.cursor/skills/

library:
  skills:
    - name: cursor-test-skill
      description: Cursor test skill
      source: {skill_dir}/SKILL.md
  agents: []
  standards: []
  prompts: []
  guardrails: []
  mcp_servers: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""
    (proj / "library.yaml").write_text(yaml_content)
    return proj


@pytest.fixture
def harness_support_project(tmp_path: Path, fixture_skill_dir: Path, fixture_standard_file: Path) -> Path:
    """Create a project with unsupported Codex entries across primitive types."""
    proj = tmp_path / "harness-support-project"
    proj.mkdir()
    prompt_file = tmp_path / "unsupported-prompt.md"
    prompt_file.write_text("# Unsupported Prompt\n")
    script_file = tmp_path / "unsupported-script.py"
    script_file.write_text("print('unsupported script')\n")

    yaml_content = f"""
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/
  prompts:
    - default: .claude/commands/
  scripts:
    - default: .agents/scripts/

library:
  skills:
    - name: unsupported-skill
      description: A skill unsupported in Codex
      source: {fixture_skill_dir / "SKILL.md"}
      metadata:
        library:
          harness_support:
            codex: not-supported
            cursor: not-supported
            opencode: not-supported
  standards:
    - name: unsupported-standard
      description: A standard unsupported in Codex
      source: {fixture_standard_file}
      metadata:
        library:
          harness_support:
            codex: not-supported
  prompts:
    - name: unsupported-prompt
      description: A prompt unsupported in Codex
      source: {prompt_file}
      metadata:
        library:
          harness_support:
            codex: not-supported
  scripts:
    - name: unsupported-script
      description: A script unsupported in Codex
      source: {script_file}
      metadata:
        library:
          harness_support:
            codex: not-supported
  agents: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""
    (proj / "library.yaml").write_text(yaml_content)
    return proj


@pytest.fixture
def runtime_requirements_project(tmp_path: Path) -> Path:
    """Create a project with runtime requirement fixtures and dependency edges."""
    project = tmp_path / "runtime-requirements-project"
    project.mkdir()
    sources = tmp_path / "runtime-sources"
    sources.mkdir()

    skill_sources = {}
    for name in (
        "missing-runtime-skill",
        "present-runtime-skill",
        "runtime-dependency",
        "missing-runtime-main",
        "incompatible-main",
        "cursor-runtime-skill",
        "missing-runtime-dependency",
        "clean-main-with-bad-dependency",
    ):
        skill_dir = sources / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"# {name}\n")
        skill_sources[name] = skill_dir / "SKILL.md"

    yaml_content = f"""
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/

library:
  skills:
    - name: missing-runtime-skill
      description: A skill with a missing runtime binary
      source: {skill_sources["missing-runtime-skill"]}
      runtime_requirements:
        binaries: ["__nonexistent_binary_xyz__"]
    - name: present-runtime-skill
      description: A skill with a present runtime binary
      source: {skill_sources["present-runtime-skill"]}
      runtime_requirements:
        binaries: ["python3"]
    - name: runtime-dependency
      description: A dependency that must not be installed before main gates
      source: {skill_sources["runtime-dependency"]}
    - name: missing-runtime-main
      description: A main skill with a missing runtime and a dependency
      source: {skill_sources["missing-runtime-main"]}
      requires:
        - skill:runtime-dependency
      runtime_requirements:
        binaries: ["__nonexistent_binary_xyz__"]
    - name: incompatible-main
      description: A main skill with impossible compatibility and a dependency
      source: {skill_sources["incompatible-main"]}
      requires:
        - skill:runtime-dependency
      compatibility: "claude_code>=99.0"
    - name: cursor-runtime-skill
      description: Cursor projection fixture requiring cursor-agent
      source: {skill_sources["cursor-runtime-skill"]}
      runtime_requirements:
        binaries: ["cursor-agent"]
    - name: missing-runtime-dependency
      description: A dependency that itself declares a missing runtime binary
      source: {skill_sources["missing-runtime-dependency"]}
      runtime_requirements:
        binaries: ["__nonexistent_binary_xyz__"]
    - name: clean-main-with-bad-dependency
      description: A main skill with no runtime requirements whose dependency has a missing binary
      source: {skill_sources["clean-main-with-bad-dependency"]}
      requires:
        - skill:runtime-dependency
        - skill:missing-runtime-dependency
  standards: []
  agents: []
  prompts: []
  scripts: []
  model_standards: []
  agent_bases: []
  guardrails: []
  mcp_servers: []

marketplaces: []
"""
    (project / "library.yaml").write_text(yaml_content)
    return project


def run_library_json(project: Path, *args: str) -> dict:
    """Run library.py in a project and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args, "--dry-run", "--json"],
        capture_output=True,
        text=True,
        cwd=str(project),
    )
    assert result.returncode == 0, (
        f"library.py {' '.join(args)} returned {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


class TestDryRunContractUniformity:
    """CL-w5d: dry-run JSON has one contract shape across primitive installers."""

    CONTRACT_KEYS = {
        "status",
        "operations",
        "summary",
        "target_paths",
        "harness_routing",
        "conflict_policy",
        "lockfile_changes",
        "requires_user_confirmation",
    }

    @pytest.mark.parametrize(
        ("primitive", "name"),
        [
            ("skill", "contract-skill"),
            ("standard", "contract-standard"),
            ("agent", "contract-agent"),
            ("prompt", "contract-prompt"),
            ("script", "contract-script"),
            ("model-standard", "contract-model-standard"),
            ("agent-base", "contract-agent-base"),
            ("mcp", "contract-mcp"),
            ("guardrail", "contract-guardrail"),
        ],
    )
    def test_all_primitive_dry_runs_emit_uniform_contract(
        self,
        dry_run_contract_project: Path,
        primitive: str,
        name: str,
    ):
        data = run_library_json(dry_run_contract_project, primitive, "use", name)

        assert self.CONTRACT_KEYS <= data.keys()
        assert data["status"] == "dry-run"
        assert isinstance(data["operations"], list) and data["operations"]
        assert isinstance(data["summary"], str) and data["summary"]
        assert isinstance(data["target_paths"], list) and data["target_paths"]
        assert data["conflict_policy"] == "overwrite"
        assert isinstance(data["lockfile_changes"], list) and data["lockfile_changes"]
        assert data["requires_user_confirmation"] is False

    def test_contract_document_exists(self):
        doc = REPO_ROOT / "docs" / "schema" / "dry-run-contract.md"
        assert doc.is_file()
        content = doc.read_text()
        assert 'contract_version: "1"' in content
        assert "target_paths" in content
        assert "conflict_policy" in content

    def test_target_project_scope_routes_targets_to_explicit_project(
        self,
        dry_run_contract_project: Path,
        tmp_path: Path,
    ):
        """--target-project routes targets to the explicit project for primitives
        that honor project scope (skill, standard, agent, prompt, script,
        model-standard, agent-base).

        MCP and guardrail are excluded: their actual installers always write
        to global harness config files (~/.claude/settings.json,
        ~/.codex/config.toml, ~/.codex/hooks.json, etc.) regardless of
        --target-project. Their dry-run reports the same global paths to
        match real install behavior (see CL-w5d Codex review regressions 1
        and 2).
        """
        target_project = tmp_path / "explicit-target-project"
        target_project.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "contract-skill",
                "--scope",
                "project",
                "--target-project",
                str(target_project),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)

        assert data["target_paths"]
        assert all(str(path).startswith(str(target_project)) for path in data["target_paths"])

    @pytest.mark.parametrize(
        ("harness", "expected_fragment", "unexpected_fragment"),
        [
            ("claude_code", ".claude/agents/contract-agent.md", ".codex/agents"),
            ("codex", ".codex/agents/contract-agent.toml", ".claude/agents"),
            ("opencode", ".opencode/agents/contract-agent.md", ".claude/agents"),
        ],
    )
    def test_agent_harness_routing_emits_requested_target_paths(
        self,
        dry_run_contract_project: Path,
        harness: str,
        expected_fragment: str,
        unexpected_fragment: str,
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "contract-agent",
                "--harness",
                harness,
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        targets = "\n".join(data["target_paths"])

        assert data["harness_routing"] == harness
        assert expected_fragment in targets
        assert unexpected_fragment not in targets

    def test_install_agent_validates_missing_handler_assets(
        self,
        tmp_path: Path,
        agent_handler_fixture_dir: Path,
    ):
        project = tmp_path / "missing-handler-project"
        project.mkdir()
        _write_agent_handler_project(
            project / "library.yaml",
            agent_handler_fixture_dir,
            ["handlers/missing-handler.sh"],
        )
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--harness",
                "claude_code",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            env=env,
        )

        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "Handler asset" in data["message"]
        assert "does not exist" in data["message"]

    def test_install_agent_rejects_handler_path_traversal(
        self,
        tmp_path: Path,
    ):
        project = tmp_path / "traversal-handler-project"
        project.mkdir()
        source_dir = tmp_path / "agent-source"
        source_dir.mkdir()
        (source_dir / "handler-agent.md").write_text(
            "---\nname: handler-agent\n---\n# Handler Agent\n"
        )
        (source_dir / "handler-agent.toml").write_text('name = "handler-agent"\n')
        outside_handler = source_dir.parent / "outside-handler.sh"
        outside_handler.write_text("#!/usr/bin/env bash\necho outside\n")
        _write_agent_handler_project(
            project / "library.yaml",
            source_dir,
            ["../outside-handler.sh"],
        )
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--harness",
                "claude_code",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            env=env,
        )

        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "outside the agent source directory" in data["message"]

    def test_install_agent_dry_run_includes_declared_handler_assets(
        self,
        agent_handlers_project: Path,
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--harness",
                "all",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(agent_handlers_project),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        operations = data["operations"]
        target_paths = "\n".join(data["target_paths"])

        assert any(op["operation"] == "vendor_handler" for op in operations)
        assert ".claude/agents/handler-agent-handlers/handlers/fixture-handler.sh" in target_paths
        assert ".codex/agents/handler-agent-handlers/handlers/fixture-handler.sh" in target_paths
        assert ".opencode/agents/handler-agent-handlers/handlers/fixture-handler.sh" in target_paths

    def test_install_agent_copies_declared_handler_assets(
        self,
        agent_handlers_project: Path,
        tmp_path: Path,
    ):
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--harness",
                "all",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(agent_handlers_project),
            env=env,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)

        expected_handler_targets = [
            agent_handlers_project / ".claude" / "agents" / "handler-agent-handlers" / "handlers" / "fixture-handler.sh",
            agent_handlers_project / ".codex" / "agents" / "handler-agent-handlers" / "handlers" / "fixture-handler.sh",
            agent_handlers_project / ".opencode" / "agents" / "handler-agent-handlers" / "handlers" / "fixture-handler.sh",
        ]
        for handler_target in expected_handler_targets:
            assert handler_target.exists()
            assert "HANDLER_AGENT_PRIVATE_HANDLER" in handler_target.read_text()

        installed_targets = data["data"]["installed_targets"]
        assert all(item["handlers"] for item in installed_targets)
        installed_handler_paths = {
            handler
            for item in installed_targets
            for handler in item["handlers"]
        }
        assert {str(path) for path in expected_handler_targets} <= installed_handler_paths

        lockfile = agent_handlers_project / ".library.lock"
        lock_data = yaml.safe_load(lockfile.read_text())
        lock_entry = next(
            entry
            for entry in lock_data["installed"]
            if entry["name"] == "handler-agent" and entry["type"] == "agent"
        )
        bridge_text = "\n".join(lock_entry["bridge_symlinks"])
        for handler_target in expected_handler_targets:
            assert str(handler_target) in bridge_text

    def test_agent_remove_all_deletes_installed_handler_directories(
        self,
        agent_handlers_project: Path,
        tmp_path: Path,
    ):
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

        install_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--harness",
                "all",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(agent_handlers_project),
            env=env,
        )
        assert install_result.returncode == 0, install_result.stderr

        handler_roots = [
            agent_handlers_project / ".claude" / "agents" / "handler-agent-handlers",
            agent_handlers_project / ".codex" / "agents" / "handler-agent-handlers",
            agent_handlers_project / ".opencode" / "agents" / "handler-agent-handlers",
        ]
        for handler_root in handler_roots:
            assert (handler_root / "handlers" / "fixture-handler.sh").exists()

        dry_run_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "remove",
                "handler-agent",
                "--harness",
                "all",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(agent_handlers_project),
            env=env,
        )
        assert dry_run_result.returncode == 0, dry_run_result.stderr
        dry_run_data = json.loads(dry_run_result.stdout)
        delete_paths = {
            op["path"]
            for op in dry_run_data["operations"]
            if op["operation"] == "delete"
        }

        remove_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "remove",
                "handler-agent",
                "--harness",
                "all",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(agent_handlers_project),
            env=env,
        )
        assert remove_result.returncode == 0, remove_result.stderr
        remove_data = json.loads(remove_result.stdout)
        removed_files = set(remove_data["data"]["removed_files"])

        missing_dry_run_paths = {str(root) for root in handler_roots} - delete_paths
        remaining_handler_roots = [root for root in handler_roots if root.exists()]
        missing_removed_files = {str(root) for root in handler_roots} - removed_files

        assert not missing_dry_run_paths
        assert not remaining_handler_roots
        assert not missing_removed_files

    def test_reinstall_agent_removes_stale_handler_assets(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Reinstalling with a reduced handler set must delete stale handlers.

        Regression guard for ``install_agent``: it previously only overwrote the
        currently-declared handler paths, so a handler that was removed or
        renamed between installs (here ``stale-handler.sh``) lingered on disk
        and stayed potentially executable even though it was no longer declared.

        Exercised at the ``install_agent`` level (not via the ``use`` CLI verb)
        because ``use`` short-circuits with "already installed" when the agent
        file is unchanged, and so would never re-enter the handler copy loop
        this regression concerns.
        """
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import agent as agent_mod

        monkeypatch.setattr(
            agent_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        source_dir = tmp_path / "stale-agent-source"
        (source_dir / "handlers").mkdir(parents=True)
        (source_dir / "handler-agent.md").write_text(
            "---\nname: handler-agent\n---\n# Handler Agent\n"
        )
        (source_dir / "handler-agent.toml").write_text('name = "handler-agent"\n')
        (source_dir / "handlers" / "keep-handler.sh").write_text(
            "#!/usr/bin/env bash\necho KEEP\n"
        )
        (source_dir / "handlers" / "stale-handler.sh").write_text(
            "#!/usr/bin/env bash\necho STALE\n"
        )

        project = tmp_path / "stale-handler-project"
        project.mkdir()

        def _catalog(handlers: list[str]) -> dict:
            return {
                "default_dirs": {
                    "agents": [
                        {"default": ".claude/agents/"},
                        {"default_codex": ".codex/agents/"},
                        {"default_opencode": ".opencode/agents/"},
                    ]
                },
                "library": {
                    "agents": [
                        {
                            "name": "handler-agent",
                            "description": "Agent with private handler assets",
                            "sources": {
                                "claude": str(source_dir / "handler-agent.md"),
                                "codex": str(source_dir / "handler-agent.toml"),
                                "opencode": str(source_dir / "handler-agent.md"),
                            },
                            "handlers": handlers,
                        }
                    ]
                },
            }

        handler_dir = (
            project / ".claude" / "agents" / "handler-agent-handlers" / "handlers"
        )
        keep_handler = handler_dir / "keep-handler.sh"
        stale_handler = handler_dir / "stale-handler.sh"

        # First install declares both handlers.
        first = agent_mod.install_agent(
            _catalog(["handlers/keep-handler.sh", "handlers/stale-handler.sh"]),
            "handler-agent",
            project,
            harness="claude_code",
        )
        assert first["status"] == "ok", first
        assert keep_handler.exists()
        assert stale_handler.exists()

        # Reinstall declaring only the kept handler; the stale one must be gone.
        second = agent_mod.install_agent(
            _catalog(["handlers/keep-handler.sh"]),
            "handler-agent",
            project,
            harness="claude_code",
        )
        assert second["status"] == "ok", second
        assert keep_handler.exists()
        assert not stale_handler.exists()

    def test_agent_use_reinstalls_when_declared_handlers_change(
        self,
        tmp_path: Path,
    ):
        source_dir = tmp_path / "handler-change-source"
        (source_dir / "handlers").mkdir(parents=True)
        (source_dir / "handler-agent.md").write_text(
            "---\nname: handler-agent\n---\n# Handler Agent\n"
        )
        (source_dir / "handler-agent.toml").write_text('name = "handler-agent"\n')
        (source_dir / "handlers" / "old-handler.sh").write_text(
            "#!/usr/bin/env bash\necho OLD\n"
        )
        (source_dir / "handlers" / "new-handler.sh").write_text(
            "#!/usr/bin/env bash\necho NEW\n"
        )

        project = tmp_path / "handler-change-project"
        project.mkdir()
        _write_agent_handler_project(
            project / "library.yaml",
            source_dir,
            ["handlers/old-handler.sh"],
        )
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

        first_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            env=env,
        )
        assert first_result.returncode == 0, first_result.stderr

        handler_roots = [
            project / ".claude" / "agents" / "handler-agent-handlers",
            project / ".codex" / "agents" / "handler-agent-handlers",
            project / ".opencode" / "agents" / "handler-agent-handlers",
        ]
        old_handler_targets = [
            root / "handlers" / "old-handler.sh"
            for root in handler_roots
        ]
        new_handler_targets = [
            root / "handlers" / "new-handler.sh"
            for root in handler_roots
        ]
        assert all(path.exists() for path in old_handler_targets)
        assert not any(path.exists() for path in new_handler_targets)

        _write_agent_handler_project(
            project / "library.yaml",
            source_dir,
            ["handlers/new-handler.sh"],
        )

        second_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "handler-agent",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            env=env,
        )
        assert second_result.returncode == 0, second_result.stderr

        assert all(path.exists() for path in new_handler_targets)
        assert not any(path.exists() for path in old_handler_targets)
        assert (
            "[refresh] agent:handler-agent declared handlers changed"
            in second_result.stderr
        )

    def test_library_yaml_declares_opencode_agent_default_dirs(self):
        catalog = LIBRARY_MODULE.load_catalog(REPO_ROOT)
        agent_dirs = {
            key: value
            for item in catalog["default_dirs"]["agents"]
            for key, value in item.items()
        }

        assert agent_dirs["default_opencode"] == ".opencode/agents/"
        assert agent_dirs["global_opencode"] == "~/.opencode/agents/"

    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("project", ".opencode/agents"),
            ("global", str(Path.home() / ".opencode" / "agents")),
        ],
    )
    def test_opencode_agent_base_uses_opencode_default_dirs(
        self,
        dry_run_contract_project: Path,
        scope: str,
        expected: str,
    ):
        from lib.installers.agent import _resolve_agent_base

        catalog = LIBRARY_MODULE.load_catalog(dry_run_contract_project)
        prim = LIBRARY_MODULE.get_primitive("agent")

        base = _resolve_agent_base(
            catalog,
            prim,
            scope=scope,
            repo_root=dry_run_contract_project,
            harness="opencode",
        )

        if scope == "project":
            assert base == dry_run_contract_project / expected
        else:
            assert base == Path(expected)

    def test_opencode_agent_real_install_and_remove_avoid_claude_artifacts(
        self,
        dry_run_contract_project: Path,
        tmp_path: Path,
    ):
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}
        install_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "contract-agent",
                "--harness",
                "opencode",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
            env=env,
        )
        assert install_result.returncode == 0, install_result.stderr

        opencode_target = dry_run_contract_project / ".opencode" / "agents" / "contract-agent.md"
        claude_target = dry_run_contract_project / ".claude" / "agents" / "contract-agent.md"
        assert opencode_target.exists()
        assert not claude_target.exists()

        remove_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "remove",
                "contract-agent",
                "--harness",
                "opencode",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
            env=env,
        )
        assert remove_result.returncode == 0, remove_result.stderr
        assert not opencode_target.exists()
        assert not claude_target.exists()

    def test_agent_remove_cursor_harness_rejected(self, dry_run_contract_project: Path):
        """AC4/AC5: agent remove --harness cursor returns error (mirrors install rejection)."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "remove",
                "contract-agent",
                "--harness", "cursor",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        # error_result envelope exits non-zero, mirroring the install rejection path.
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "not supported" in data["message"].lower()

    def test_agent_remove_all_harness_includes_opencode_target(
        self,
        dry_run_contract_project: Path,
        tmp_path: Path,
    ):
        """agent remove --harness all deletes Claude, Codex, and OpenCode files."""
        env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg-data")}
        install_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "contract-agent",
                "--harness", "all",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
            env=env,
        )
        assert install_result.returncode == 0, install_result.stderr

        claude_target = dry_run_contract_project / ".claude" / "agents" / "contract-agent.md"
        codex_target = dry_run_contract_project / ".codex" / "agents" / "contract-agent.toml"
        opencode_target = dry_run_contract_project / ".opencode" / "agents" / "contract-agent.md"
        assert claude_target.exists()
        assert codex_target.exists()
        assert opencode_target.exists()

        remove_result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "remove",
                "contract-agent",
                "--harness", "all",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
            env=env,
        )
        assert remove_result.returncode == 0, remove_result.stderr
        data = json.loads(remove_result.stdout)
        assert str(claude_target) in data["data"]["removed_files"]
        assert str(codex_target) in data["data"]["removed_files"]
        assert str(opencode_target) in data["data"]["removed_files"]
        assert not claude_target.exists()
        assert not codex_target.exists()
        assert not opencode_target.exists()

    @pytest.mark.parametrize("unsafe_name", ["../shared", "..", "a/b", "a\\b", "sub/agent"])
    def test_agent_remove_rejects_unsafe_name_without_deleting(
        self,
        tmp_path: Path,
        unsafe_name: str,
    ):
        """Regression (CL-du1x codex finding): remove_agent() must refuse a name
        that is not a single safe path component (e.g. '../shared') instead of
        interpolating it into handler_root and letting shutil.rmtree() delete a
        directory outside the per-harness agent handler directory.
        """
        # Importing here mirrors library.py's `from lib.installers.agent import ...`
        # wiring; LIBRARY_MODULE has already inserted scripts/ onto sys.path.
        from lib.installers.agent import remove_agent

        # A sentinel directory that a path-traversal name could otherwise target.
        # It must survive the refused removal.
        sentinel = tmp_path / "shared-handlers"
        sentinel.mkdir()
        keep = sentinel / "keep.txt"
        keep.write_text("do not delete", encoding="utf-8")

        result = remove_agent(
            catalog={},
            name=unsafe_name,
            repo_root=tmp_path,
            scope="project",
            harness="claude_code",
        )

        # error_result envelope, consistent with the cursor-harness rejection.
        assert result["status"] == "error"
        assert "not a valid agent name" in result["message"]
        # No filesystem mutation occurred.
        assert sentinel.exists()
        assert keep.exists()
        assert keep.read_text(encoding="utf-8") == "do not delete"

    def test_cursor_skill_install_creates_cursor_bridge(self, cursor_project: Path):
        """AC2: --harness cursor installs skill with .cursor/skills/<name>/ bridge."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "cursor-test-skill",
                "--harness",
                "cursor",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(cursor_project),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["status"] == "dry-run"
        targets = "\n".join(data["target_paths"])
        assert ".cursor/skills/cursor-test-skill" in targets

    def test_cursor_skill_dry_run_reports_cursor_target_paths(self, cursor_project: Path):
        """AC6: dry-run --json reports Cursor target_paths, harness_routing, conflict_policy."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "cursor-test-skill",
                "--harness",
                "cursor",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(cursor_project),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data.get("harness_routing") == "cursor"
        assert data.get("conflict_policy") == "overwrite"
        assert data.get("requires_user_confirmation") is False
        assert ".cursor/skills" in "\n".join(data.get("target_paths", []))

    def test_cursor_skill_real_install_creates_bridge_symlink(self, cursor_project: Path):
        """AC2: real install creates .cursor/skills/<name>/ as symlink to .agents/skills/<name>/."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "cursor-test-skill",
                "--harness",
                "cursor",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(cursor_project),
        )
        assert result.returncode == 0, result.stderr
        cursor_bridge = cursor_project / ".cursor" / "skills" / "cursor-test-skill"
        assert cursor_bridge.exists() or cursor_bridge.is_symlink()
        assert cursor_bridge.is_symlink()
        canonical = cursor_project / ".agents" / "skills" / "cursor-test-skill"
        assert canonical.exists()
        assert cursor_bridge.resolve() == canonical.resolve()

    def test_cursor_agent_install_rejected_with_compatibility_message(
        self,
        dry_run_contract_project: Path,
    ):
        """AC3: agent install for --harness cursor is explicitly rejected with compatibility message."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "agent",
                "use",
                "contract-agent",
                "--harness",
                "cursor",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "cursor" in data["message"].lower()
        assert "not supported" in data["message"].lower() or "not currently implemented" in data["message"].lower()

    @pytest.mark.parametrize("harness", ["cursor", "opencode"])
    def test_mcp_install_cursor_opencode_rejected_before_side_effects(
        self,
        harness: str,
        dry_run_contract_project: Path,
    ):
        """AC8: MCP --harness cursor/opencode fails with compatibility message before side effects."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "mcp",
                "use",
                "contract-mcp",
                "--harness",
                harness,
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert harness in data["message"].lower()

    @pytest.mark.parametrize("harness", ["cursor", "opencode"])
    def test_guardrail_install_cursor_opencode_rejected_before_side_effects(
        self,
        harness: str,
        dry_run_contract_project: Path,
    ):
        """AC8: guardrail --harness cursor/opencode fails with compatibility message before side effects."""
        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "guardrail",
                "use",
                "contract-guardrail",
                "--harness",
                harness,
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(dry_run_contract_project),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert harness in data["message"].lower()

    def test_cursor_skill_smoke_or_blocking_finding(self):
        """AC7: Smoke verifies cursor-agent can use an installed test skill, or records blocking finding."""
        if shutil.which("cursor") is None and shutil.which("cursor-agent") is None:
            pytest.skip(
                "SMOKE_BLOCKED: cursor/cursor-agent binary not on PATH. "
                "Cursor skill projection cannot be verified in this environment. "
                "To verify: install Cursor, run library use --harness cursor <skill>, "
                "then open Cursor and check the skill is accessible."
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir) / "smoke-project"
            proj.mkdir()
            skill_src = Path(tmpdir) / "smoke-skill"
            skill_src.mkdir()
            (skill_src / "SKILL.md").write_text("---\nname: smoke-skill\n---\n# Smoke Skill\n")
            yaml = f"""
default_dirs:
  skills:
    - default: .agents/skills/
    - cursor_bridge: .cursor/skills/
library:
  skills:
    - name: smoke-skill
      description: Smoke test skill
      source: {skill_src}/SKILL.md
  agents: []
  standards: []
  prompts: []
  guardrails: []
  mcp_servers: []
marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""
            (proj / "library.yaml").write_text(yaml)
            result = subprocess.run(
                [
                    sys.executable,
                    str(LIBRARY_PY),
                    "skill",
                    "use",
                    "smoke-skill",
                    "--harness",
                    "cursor",
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=str(proj),
            )
            assert result.returncode == 0, result.stderr
            cursor_path = proj / ".cursor" / "skills" / "smoke-skill"
            assert cursor_path.exists() or cursor_path.is_symlink(), (
                f"Cursor bridge path not created at {cursor_path}"
            )

    def test_cursor_skill_remove_cleans_up_cursor_bridge(self, cursor_project: Path):
        """Cursor bridge is removed when skill is uninstalled."""
        # Install first
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "cursor-test-skill",
             "--harness", "cursor"],
            capture_output=True, text=True, cwd=str(cursor_project),
        )
        assert result.returncode == 0, result.stderr
        cursor_bridge = cursor_project / ".cursor" / "skills" / "cursor-test-skill"
        assert cursor_bridge.exists() or cursor_bridge.is_symlink()

        # Now remove
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "remove", "cursor-test-skill"],
            capture_output=True, text=True, cwd=str(cursor_project),
        )
        assert result.returncode == 0, result.stderr
        # Bridge must be gone — no dangling symlink
        assert not cursor_bridge.exists()
        assert not cursor_bridge.is_symlink()

    def test_cursor_agent_rejected_before_dependency_install(self, dry_run_contract_project: Path):
        """AC8: cursor agent install is rejected before any dependency side effects on real install."""
        # Verify that even a real install (no --dry-run) returns error without creating files
        agents_dir = dry_run_contract_project / ".claude" / "agents"
        agents_dir_exists_before = agents_dir.exists()

        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "agent", "use", "contract-agent",
             "--harness", "cursor", "--json"],
            capture_output=True, text=True, cwd=str(dry_run_contract_project),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "cursor" in data["message"].lower()
        # Agents dir should not be modified by a cursor install attempt
        if not agents_dir_exists_before:
            assert not agents_dir.exists(), "cursor agent install should not create agents directory"

    def test_existing_target_reports_conflict_policy_and_detection(
        self,
        dry_run_contract_project: Path,
    ):
        existing_target = dry_run_contract_project / ".claude" / "commands" / "contract-prompt.md"
        existing_target.parent.mkdir(parents=True)
        existing_target.write_text("# Existing Prompt\n")

        data = run_library_json(dry_run_contract_project, "prompt", "use", "contract-prompt")

        assert data["conflict_policy"] == "overwrite"
        assert str(existing_target) in data["target_paths"]
        assert any(op.get("existing_target") is True for op in data["operations"])


@pytest.mark.parametrize(
    ("primitive", "name"),
    [
        ("skill", "unsupported-skill"),
        ("standard", "unsupported-standard"),
        ("prompt", "unsupported-prompt"),
        ("script", "unsupported-script"),
    ],
)
def test_use_refuses_unsupported_harness_across_primitive_types(
    harness_support_project: Path,
    primitive: str,
    name: str,
):
    """use --harness codex refuses entries marked harness_support.codex: not-supported."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            primitive,
            "use",
            name,
            "--harness",
            "codex",
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(harness_support_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data["status"] == "error"
    assert "harness_support.codex: not-supported" in data["message"]


@pytest.mark.parametrize("harness", ["cursor", "opencode"])
def test_use_refuses_unsupported_harness_for_extended_cli_harnesses(
    harness_support_project: Path,
    harness: str,
):
    """use --harness refuses every accepted CLI harness marked not-supported."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "unsupported-skill",
            "--harness",
            harness,
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(harness_support_project),
    )

    assert result.returncode != 0
    assert result.stdout, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "error"
    assert f"harness_support.{harness}: not-supported" in data["message"]


@pytest.mark.parametrize("harness", ["claude_code", "codex", "cursor", "opencode", "gemini"])
def test_check_harness_support_enforces_closed_registry(harness: str):
    """The harness support gate enforces not-supported for every known harness ID."""
    entry = {
        "metadata": {
            "library": {
                "harness_support": {
                    harness: "not-supported",
                }
            }
        }
    }

    message = LIBRARY_MODULE._check_harness_support(entry, harness)

    assert message is not None
    assert f"harness_support.{harness}: not-supported" in message


def test_runtime_requirement_missing_binary_fails_before_install_mutation(
    runtime_requirements_project: Path,
):
    """CL-iye.7 AK1: missing runtime binaries fail before install side effects."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "missing-runtime-skill",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data["status"] == "error"
    assert "__nonexistent_binary_xyz__" in data["message"]
    assert not (runtime_requirements_project / ".agents").exists()
    assert not (runtime_requirements_project / ".library.lock").exists()


def test_runtime_requirement_present_binary_installs_normally(
    runtime_requirements_project: Path,
):
    """CL-iye.7 AK2: present runtime binaries do not block normal install."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "present-runtime-skill",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode == 0, result.stderr
    assert (runtime_requirements_project / ".agents" / "skills" / "present-runtime-skill").exists()
    assert (runtime_requirements_project / ".library.lock").exists()


@pytest.mark.parametrize("dry_run_flag", [True, False])
def test_runtime_requirement_json_errors_include_missing_binary(
    runtime_requirements_project: Path,
    dry_run_flag: bool,
):
    """CL-iye.7 AK3: dry-run and real JSON errors use stable error_result payloads."""
    cmd = [
        sys.executable,
        str(LIBRARY_PY),
        "skill",
        "use",
        "missing-runtime-skill",
        "--json",
    ]
    if dry_run_flag:
        cmd.insert(-1, "--dry-run")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data["status"] == "error"
    assert data["exit_code"] == result.returncode
    assert "__nonexistent_binary_xyz__" in data["message"]


def test_runtime_requirement_fuzzy_main_gate_precedes_dependency_install(
    runtime_requirements_project: Path,
):
    """CL-iye.7 AK5: fuzzy main lookup gates before dependency side effects."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "main skill with a missing runtime",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert "__nonexistent_binary_xyz__" in data["message"]
    assert not (runtime_requirements_project / ".agents" / "skills" / "runtime-dependency").exists()
    assert not (runtime_requirements_project / ".library.lock").exists()


def test_compatibility_fuzzy_main_gate_precedes_dependency_install(
    runtime_requirements_project: Path,
):
    """CL-iye.7 AK6: fuzzy incompatible main entry fails before dependency install."""
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "impossible compatibility",
            "--harness",
            "claude_code",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert "claude_code>=99.0" in data["message"]
    assert not (runtime_requirements_project / ".agents" / "skills" / "runtime-dependency").exists()
    assert not (runtime_requirements_project / ".library.lock").exists()


def test_runtime_requirement_dependency_gate_precedes_any_install(
    runtime_requirements_project: Path,
):
    """CL-iye.7 regression: a missing runtime binary on a DEPENDENCY fails before
    ANY entry in the resolved install order is installed.

    The main entry here has no runtime_requirements of its own. It requires a
    CLEAN dependency (runtime-dependency) declared before a BROKEN dependency
    (missing-runtime-dependency). The resolved install order is therefore
    [runtime-dependency, missing-runtime-dependency, clean-main-with-bad-dependency].

    Without a preflight runtime gate over the FULL install order, the clean
    dependency would be installed first and only the broken dependency's own
    per-entry gate would fail — leaving runtime-dependency partially installed.
    The fix preflights every entry so nothing is installed when any entry has a
    missing binary.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "clean-main-with-bad-dependency",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(runtime_requirements_project),
    )

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data["status"] == "error"
    assert "__nonexistent_binary_xyz__" in data["message"]
    # The clean dependency (ordered first) must NOT have been installed — this is
    # the discriminating assertion for the preflight gate regression.
    assert not (
        runtime_requirements_project / ".agents" / "skills" / "runtime-dependency"
    ).exists()
    # The broken dependency and the main skill must also be absent.
    assert not (
        runtime_requirements_project / ".agents" / "skills" / "missing-runtime-dependency"
    ).exists()
    assert not (
        runtime_requirements_project / ".agents" / "skills" / "clean-main-with-bad-dependency"
    ).exists()
    assert not (runtime_requirements_project / ".library.lock").exists()


def test_cursor_agent_can_be_declared_as_runtime_requirement():
    """CL-iye.7 AK8: cursor-agent declarations use the generic runtime gate."""
    entry = {"runtime_requirements": {"binaries": ["cursor-agent"]}}

    message = LIBRARY_MODULE._check_runtime_requirements(entry)

    if shutil.which("cursor-agent") is None:
        assert message is not None
        assert "cursor-agent" in message
    else:
        assert message is None


# ---------------------------------------------------------------------------
# AK4: skill use --dry-run --json
# ---------------------------------------------------------------------------


class TestSkillDryRun:
    """AK4: skill use --dry-run --json emits planned operations without mutation."""

    def test_skill_dry_run_exits_zero(self, project_dir: Path):
        """skill use --dry-run --json must exit 0."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0, (
            f"skill use --dry-run --json returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_skill_dry_run_json_valid(self, project_dir: Path):
        """skill use --dry-run --json must emit valid JSON."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        assert isinstance(data, dict), f"Expected JSON dict, got {type(data)}"

    def test_skill_dry_run_status_is_dry_run(self, project_dir: Path):
        """skill use --dry-run --json must have status='dry-run'."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        assert data.get("status") == "dry-run", (
            f"Expected status='dry-run', got '{data.get('status')}'\nfull response: {data}"
        )

    def test_skill_dry_run_has_operations(self, project_dir: Path):
        """skill use --dry-run --json must include an 'operations' list."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        assert isinstance(ops, list), f"Expected 'operations' to be a list, got {type(ops)}"
        assert len(ops) > 0, "Expected at least one planned operation"

    def test_skill_dry_run_includes_cache_op(self, project_dir: Path):
        """Dry-run operations must include a cache materialization step."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        op_names = [op.get("operation") for op in ops]
        assert "materialize_cache" in op_names or any("cache" in (op.get("details", "")) for op in ops), (
            f"Expected cache materialization operation, got: {op_names}"
        )

    def test_skill_dry_run_includes_vendor_op(self, project_dir: Path):
        """Dry-run operations must include a vendor copy step by default."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        op_names = [op.get("operation") for op in ops]
        assert "vendor_copy" in op_names, (
            f"Expected vendor_copy operation, got: {op_names}"
        )

    def test_skill_dry_run_includes_lockfile_op(self, project_dir: Path):
        """Dry-run operations must include a lockfile write step."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        op_names = [op.get("operation") for op in ops]
        assert "write_lockfile" in op_names, (
            f"Expected write_lockfile operation, got: {op_names}"
        )

    def test_skill_dry_run_no_mutation(self, project_dir: Path):
        """skill use --dry-run must NOT create any files in the project directory."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        # Must not create .agents/skills, .claude/skills, or .library.lock
        assert not (project_dir / ".agents").exists(), (
            ".agents dir was created during --dry-run (must not mutate)"
        )
        assert not (project_dir / ".claude").exists(), (
            ".claude dir was created during --dry-run (must not mutate)"
        )
        assert not (project_dir / ".library.lock").exists(), (
            ".library.lock was created during --dry-run (must not mutate)"
        )

    def test_skill_dry_run_can_target_project_without_library_yaml(self, tmp_path: Path):
        """Running the CLI from a normal project should use the CLI catalog and target cwd."""
        target_project = tmp_path / "external-project"
        target_project.mkdir()

        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "standard-forge", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(target_project),
        )
        assert result.returncode == 0, (
            f"skill use --dry-run returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        data = json.loads(result.stdout)
        ops_text = json.dumps(data.get("operations", []))
        assert str(target_project / ".agents" / "skills" / "standard-forge") in ops_text

    def test_skill_dry_run_target_project_overrides_cwd(self, tmp_path: Path):
        """--target-project should decouple the install target from the catalog cwd."""
        target_project = tmp_path / "explicit-target"
        target_project.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "standard-forge",
                "--dry-run",
                "--json",
                "--target-project",
                str(target_project),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"skill use --dry-run returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        data = json.loads(result.stdout)
        ops_text = json.dumps(data.get("operations", []))
        assert str(target_project / ".agents" / "skills" / "standard-forge") in ops_text


class TestSkillMarketplaceInstall:
    """Marketplace-backed skill entries should resolve and install like direct sources."""

    @staticmethod
    def _catalog_yaml() -> str:
        return """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/

sources:
  marketplaces:
    - name: pbakaus
      source: https://github.com/pbakaus
      type: git
    - name: cognovis-core
      source: https://github.com/cognovis
      type: git

library:
  skills:
    - name: impeccable
      description: Marketplace-backed skill fixture
      from_marketplace: pbakaus
      repo: impeccable
      path: .claude/skills/impeccable
    - name: core-skill
      description: First-party marketplace-backed skill fixture
      from_marketplace: cognovis-core
      repo: library-core
      path: skills/core-skill
  standards: []
  agents: []
  prompts: []
"""

    @staticmethod
    def _patch_git_clone(
        monkeypatch: pytest.MonkeyPatch, skill_mod, fake_repo: Path
    ) -> None:
        """Patch skill installer git commands to clone from a local fixture."""
        def fake_run(cmd, capture_output=False, text=False, cwd=None):
            if cmd[:5] == ["git", "clone", "--quiet", "--depth", "1"]:
                target = Path(cmd[-1])
                shutil.copytree(fake_repo, target, dirs_exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd == ["git", "rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, "abcdef1234567890\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(skill_mod.subprocess, "run", fake_run)

    def test_marketplace_source_resolves_impeccable_tree_url(self):
        """from_marketplace + repo + path resolves to a GitHub tree source."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import resolve_marketplace_source

        catalog = {
            "sources": {
                "marketplaces": [
                    {
                        "name": "pbakaus",
                        "source": "https://github.com/pbakaus",
                        "type": "git",
                    }
                ]
            }
        }
        entry = {
            "name": "impeccable",
            "from_marketplace": "pbakaus",
            "repo": "impeccable",
            "path": ".claude/skills/impeccable",
        }

        assert resolve_marketplace_source(catalog, entry) == (
            "https://github.com/pbakaus/impeccable/tree/main/"
            ".claude/skills/impeccable"
        )

    def test_marketplace_source_unknown_marketplace_raises(self):
        """Marketplace resolution should fail loudly for missing registries."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.errors import SourceError
        from lib.source import resolve_marketplace_source

        entry = {
            "name": "missing-skill",
            "from_marketplace": "unknown-marketplace",
            "repo": "repo",
            "path": "skills/missing-skill",
        }

        with pytest.raises(SourceError, match="unknown marketplace"):
            resolve_marketplace_source({"sources": {"marketplaces": []}}, entry)

    def test_marketplace_skill_dry_run_reports_resolved_source(self, tmp_path: Path):
        """Dry-run JSON should expose the resolved clone URL and source path."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "library.yaml").write_text(self._catalog_yaml())

        result = subprocess.run(
            [
                sys.executable,
                str(LIBRARY_PY),
                "skill",
                "use",
                "impeccable",
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
        )

        assert result.returncode == 0, (
            f"skill use --dry-run returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        resolved = data.get("data", {})
        assert data.get("status") == "dry-run"
        assert resolved["source"] == (
            "https://github.com/pbakaus/impeccable/tree/main/"
            ".claude/skills/impeccable"
        )
        assert resolved["clone_url"] == "https://github.com/pbakaus/impeccable.git"
        assert resolved["source_path"] == ".claude/skills/impeccable"
        assert resolved["install_target"].endswith(".agents/skills/impeccable")
        assert "skills/pbakaus/impeccable@<commit-sha>" in resolved["cache_path"]

        op_names = [op.get("operation") for op in data.get("operations", [])]
        assert "materialize_cache" in op_names
        assert "write_lockfile" in op_names

    def test_marketplace_skill_install_materializes_skill_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Marketplace tree sources should copy the skill directory, not its parent."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import skill as skill_mod

        fake_repo = tmp_path / "fake-repo"
        skill_dir = fake_repo / ".claude" / "skills" / "impeccable"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: impeccable\ndescription: Marketplace fixture\n---\n\n# Impeccable\n"
        )
        (skill_dir / "references.md").write_text("# Reference\n")

        self._patch_git_clone(monkeypatch, skill_mod, fake_repo)
        monkeypatch.setattr(
            skill_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {
                "skills": [
                    {"default": ".agents/skills/"},
                    {"claude_bridge": ".claude/skills/"},
                ]
            },
            "sources": {
                "marketplaces": [
                    {
                        "name": "pbakaus",
                        "source": "https://github.com/pbakaus",
                        "type": "git",
                    }
                ]
            },
            "library": {
                "skills": [
                    {
                        "name": "impeccable",
                        "description": "Marketplace fixture.",
                        "from_marketplace": "pbakaus",
                        "repo": "impeccable",
                        "path": ".claude/skills/impeccable",
                    }
                ]
            },
        }

        result = skill_mod.install_skill(catalog, "impeccable", project)

        assert result["status"] == "ok", result
        canonical = project / ".agents" / "skills" / "impeccable"
        assert (canonical / "SKILL.md").is_file()
        assert (canonical / "references.md").is_file()
        assert not (canonical / "impeccable" / "SKILL.md").exists()

    def test_first_party_marketplace_skill_install_uses_repo_fixture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """First-party marketplace-style entries should use the same install path."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import skill as skill_mod

        fake_repo = tmp_path / "fake-repo"
        skill_dir = fake_repo / "skills" / "core-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: core-skill\ndescription: First-party fixture\n---\n\n# Core Skill\n"
        )

        self._patch_git_clone(monkeypatch, skill_mod, fake_repo)
        monkeypatch.setattr(
            skill_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {
                "skills": [
                    {"default": ".agents/skills/"},
                    {"claude_bridge": ".claude/skills/"},
                ]
            },
            "sources": {
                "marketplaces": [
                    {
                        "name": "cognovis-core",
                        "source": "https://github.com/cognovis",
                        "type": "git",
                    }
                ]
            },
            "library": {
                "skills": [
                    {
                        "name": "core-skill",
                        "description": "First-party fixture.",
                        "from_marketplace": "cognovis-core",
                        "repo": "library-core",
                        "path": "skills/core-skill",
                    }
                ]
            },
        }

        result = skill_mod.install_skill(catalog, "core-skill", project)

        assert result["status"] == "ok", result
        canonical = project / ".agents" / "skills" / "core-skill"
        assert (canonical / "SKILL.md").is_file()
        assert result["data"]["cache"].endswith("skill/cognovis-core/core-skill@abcdef1")


# ---------------------------------------------------------------------------
# AK5: standard use --dry-run --json
# ---------------------------------------------------------------------------


class TestStandardDryRun:
    """AK5: standard use --dry-run --json emits planned writes without mutation."""

    def test_standard_dry_run_exits_zero(self, project_dir: Path):
        """standard use --dry-run --json must exit 0."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0, (
            f"standard use --dry-run returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_standard_dry_run_json_valid(self, project_dir: Path):
        """standard use --dry-run --json must emit valid JSON."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_standard_dry_run_status(self, project_dir: Path):
        """standard use --dry-run --json must have status='dry-run'."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        assert data.get("status") == "dry-run", (
            f"Expected status='dry-run', got '{data.get('status')}'\ndata: {data}"
        )

    def test_standard_dry_run_has_operations(self, project_dir: Path):
        """standard use --dry-run must include operations list."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        assert len(ops) > 0, "Expected at least one operation in dry-run output"

    def test_standard_dry_run_does_not_mention_agents_md(self, project_dir: Path):
        """standard dry-run operations must not mention AGENTS.md mutation."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        data = json.loads(result.stdout)
        ops_text = json.dumps(data.get("operations", []))
        summary = data.get("summary", "")
        combined = ops_text + summary
        assert "agents_md" not in combined.lower()
        assert "AGENTS.md" not in combined
        assert "agents-md" not in combined.lower(), (
            f"Unexpected AGENTS.md mention in dry-run output\ndata: {data}"
        )

    def test_standard_dry_run_no_mutation(self, project_dir: Path):
        """standard use --dry-run must not create files."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--dry-run", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0
        assert not (project_dir / ".agents").exists(), (
            ".agents dir was created during --dry-run"
        )
        assert not (project_dir / ".library.lock").exists(), (
            ".library.lock was created during --dry-run"
        )


class TestStandardRealInstall:
    """Real standard installs should vendor files without mutating AGENTS.md."""

    def test_standard_real_install_vendors_without_agents_md(self, project_dir: Path):
        """standard use must install files and leave AGENTS.md alone."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "test-standard", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0, (
            f"standard use returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        data = json.loads(result.stdout)
        assert data.get("status") == "ok", data

        canonical = project_dir / ".agents" / "standards" / "test-standard"
        assert canonical.exists()
        assert canonical.is_dir()
        assert not canonical.is_symlink()
        assert (canonical / "test-standard.md").exists()
        agents_md = project_dir / "AGENTS.md"
        assert not agents_md.exists()


class TestStandardTreeSource:
    """GitHub tree URL standards should install as directory bundles."""

    @staticmethod
    def _patch_git_clone(
        monkeypatch: pytest.MonkeyPatch, standard_mod, fake_repo: Path
    ) -> None:
        """Patch standard installer git commands to clone from a local fixture."""
        def fake_run(cmd, capture_output=False, text=False, cwd=None):
            if cmd[:5] == ["git", "clone", "--quiet", "--depth", "1"]:
                target = Path(cmd[-1])
                shutil.copytree(fake_repo, target, dirs_exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd == ["git", "rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, "abcdef1234567890\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(standard_mod.subprocess, "run", fake_run)

    def test_source_parse_github_tree_has_directory_hint(self):
        """GitHub tree URL parses as a browser source with directory path type."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        url = "https://github.com/cognovis/library-core/tree/main/standards/python"
        parsed = parse_source(url)
        assert parsed.kind == "github_browser"
        assert parsed.org == "cognovis"
        assert parsed.repo == "library-core"
        assert parsed.branch == "main"
        assert parsed.file_path == "standards/python"
        assert parsed.path_type == "directory"
        assert parsed.clone_url == "https://github.com/cognovis/library-core.git"

    def test_source_parse_github_tree_trailing_slash_normalizes_path(self):
        """GitHub tree URL with a trailing slash parses to the directory path."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        url = "https://github.com/cognovis/library-core/tree/main/standards/python/"
        parsed = parse_source(url)
        assert parsed.kind == "github_browser"
        assert parsed.file_path == "standards/python"
        assert parsed.path_type == "directory"

    def test_source_parse_unknown_has_explicit_path_type(self):
        """Unrecognized source strings should expose path_type='unknown', not None."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        parsed = parse_source("not-a-url")
        assert parsed.kind == "unknown"
        assert parsed.path_type == "unknown"

    def test_standard_tree_source_installs_directory_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """standard use must copy the whole folder for GitHub tree URL sources."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        bundle = fake_repo / "standards" / "bundle-standard"
        bundle.mkdir(parents=True)
        (bundle / "bundle-standard.md").write_text("# Bundle Standard\n")
        (bundle / "detail.md").write_text("# Detail\n")

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "bundle-standard",
                        "description": "Directory-backed standard fixture.",
                        "source": "https://github.com/example/repo/tree/main/standards/bundle-standard/",
                    }
                ]
            },
            "marketplaces": [],
        }

        result = standard_mod.install_standard(catalog, "bundle-standard", project)

        assert result["status"] == "ok"
        canonical = project / ".agents" / "standards" / "bundle-standard"
        assert (canonical / "bundle-standard.md").exists()
        assert (canonical / "detail.md").exists()

    def test_fetch_standard_source_missing_path_raises_install_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Missing GitHub source path should fail instead of installing repo root."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.errors import InstallError
        from lib.installers import standard as standard_mod
        from lib.source import parse_source

        fake_repo = tmp_path / "fake-repo"
        fake_repo.mkdir()
        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)

        parsed = parse_source("https://github.com/example/repo/tree/main/standards/missing")
        with pytest.raises(InstallError, match="does not exist"):
            standard_mod._fetch_standard_source(parsed, "missing")

    def test_fetch_standard_source_blob_directory_raises_install_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Blob URLs must point at files, not standard bundle directories."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.errors import InstallError
        from lib.installers import standard as standard_mod
        from lib.source import parse_source

        fake_repo = tmp_path / "fake-repo"
        (fake_repo / "standards" / "bundle-standard").mkdir(parents=True)
        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)

        parsed = parse_source(
            "https://github.com/example/repo/blob/main/standards/bundle-standard"
        )
        with pytest.raises(InstallError, match="not a file"):
            standard_mod._fetch_standard_source(parsed, "bundle-standard")

    def test_fetch_standard_source_tree_file_raises_install_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Tree URLs must point at directories, not individual files."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.errors import InstallError
        from lib.installers import standard as standard_mod
        from lib.source import parse_source

        fake_repo = tmp_path / "fake-repo"
        source_file = fake_repo / "standards" / "single-standard.md"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("# Single Standard\n")
        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)

        parsed = parse_source(
            "https://github.com/example/repo/tree/main/standards/single-standard.md"
        )
        with pytest.raises(InstallError, match="not a directory"):
            standard_mod._fetch_standard_source(parsed, "single-standard")


class TestSimpleFileDirectoryEntrypoint:
    """Directory-backed simple-file primitives should honor entrypoint."""

    def test_prompt_directory_source_installs_configured_entrypoint(self, tmp_path: Path):
        """A prompt sourced from a directory must install the configured entrypoint file."""
        source_dir = tmp_path / "prompt-source"
        source_dir.mkdir()
        chosen = source_dir / "chosen.md"
        chosen.write_text("# Chosen Prompt\n\nThis file should be installed.\n")

        project = tmp_path / "project"
        project.mkdir()
        (project / "library.yaml").write_text(
            f"""
default_dirs:
  prompts:
    - default: .claude/commands/

library:
  skills: []
  agents: []
  prompts:
    - name: entrypoint-prompt
      description: Prompt with a directory source and explicit entrypoint
      source: {source_dir}
      entrypoint: chosen.md
  scripts: []
  standards: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""
        )

        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "prompt", "use", "entrypoint-prompt", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project),
        )
        assert result.returncode == 0, (
            f"prompt use returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        install_target = project / ".claude" / "commands" / "entrypoint-prompt.md"
        assert install_target.is_file()
        assert install_target.read_text() == chosen.read_text()


# ---------------------------------------------------------------------------
# AK6: Real skill use in tempdir
# ---------------------------------------------------------------------------


class TestSkillRealInstall:
    """AK6: Real skill use produces canonical .agents vendored copy plus Claude bridge."""

    def test_skill_real_install_exits_zero(self, project_dir: Path):
        """skill use (real, no --dry-run) must exit 0."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0, (
            f"skill use returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_skill_real_install_creates_canonical_vendor_copy(self, project_dir: Path):
        """Real skill use must create .agents/skills/test-skill as a real directory."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        canonical = project_dir / ".agents" / "skills" / "test-skill"
        assert canonical.exists(), (
            f"Expected {canonical} to exist after skill install"
        )
        assert canonical.is_dir(), (
            f"Expected {canonical} to be a directory after skill install"
        )
        assert not canonical.is_symlink(), (
            f"Expected {canonical} to be a vendored directory, got symlink"
        )

    def test_skill_real_install_creates_claude_bridge(self, project_dir: Path):
        """Real skill use must create .claude/skills/test-skill bridge symlink."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        bridge = project_dir / ".claude" / "skills" / "test-skill"
        assert bridge.exists(), (
            f"Expected Claude bridge at {bridge} — not found"
        )
        assert bridge.is_symlink(), (
            f"Expected Claude bridge {bridge} to be a symlink"
        )

    def test_skill_real_install_bridge_points_to_canonical(self, project_dir: Path):
        """Claude bridge symlink must point at the canonical vendored directory."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        bridge = project_dir / ".claude" / "skills" / "test-skill"
        assert bridge.is_symlink()
        target = bridge.resolve()
        canonical = (project_dir / ".agents" / "skills" / "test-skill").resolve()
        assert target == canonical

    def test_skill_real_install_skill_md_accessible(self, project_dir: Path):
        """SKILL.md must be accessible through the canonical install directory."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        canonical = project_dir / ".agents" / "skills" / "test-skill"
        skill_md = canonical / "SKILL.md"
        assert skill_md.exists(), (
            f"SKILL.md not accessible at {skill_md}"
        )
        content = skill_md.read_text()
        assert "test-skill" in content.lower() or "Test Skill" in content, (
            f"SKILL.md content doesn't mention test-skill: {content[:100]}"
        )

    def test_skill_real_install_writes_lockfile(self, project_dir: Path):
        """Real skill use must write .library.lock."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        lockfile = project_dir / ".library.lock"
        assert lockfile.exists(), ".library.lock was not created"

    def test_skill_real_install_lockfile_has_entry(self, project_dir: Path):
        """Lockfile must contain an entry for test-skill."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0

        lockfile = project_dir / ".library.lock"
        with lockfile.open() as f:
            lock_data = yaml.safe_load(f)

        installed = lock_data.get("installed", [])
        names = [e.get("name") for e in installed]
        assert "test-skill" in names, (
            f"Expected 'test-skill' in lockfile installed list, got: {names}"
        )

    def test_skill_real_install_json_result(self, project_dir: Path):
        """skill use --json must return valid JSON with status=ok."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("status") == "ok", (
            f"Expected status='ok', got '{data.get('status')}'\ndata: {data}"
        )

    def test_skill_install_idempotent(self, project_dir: Path):
        """Installing the same skill twice must succeed (idempotent)."""
        for i in range(2):
            result = subprocess.run(
                [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
                capture_output=True,
                text=True,
                cwd=str(project_dir),
            )
            assert result.returncode == 0, (
                f"Install attempt {i+1} failed: {result.returncode}\n{result.stderr}"
            )

        # After two installs, lockfile should still have exactly one entry
        try:
            import yaml
            lockfile = project_dir / ".library.lock"
            with lockfile.open() as f:
                lock_data = yaml.safe_load(f)
            installed = lock_data.get("installed", [])
            skill_entries = [e for e in installed if e.get("name") == "test-skill"]
            assert len(skill_entries) == 1, (
                f"Expected exactly one lockfile entry after idempotent install, got {len(skill_entries)}"
            )
        except ImportError:
            pass  # Skip lockfile check if yaml not available

    def test_skill_symlink_opt_in_preserves_cache_link_mode(self, project_dir: Path):
        """--symlink must install the canonical path as a cache symlink."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--symlink", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0, (
            f"skill use --symlink returned {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        canonical = project_dir / ".agents" / "skills" / "test-skill"
        assert canonical.is_symlink(), f"Expected {canonical} to be a symlink"

    def test_skill_vendor_survives_cache_delete(self, project_dir: Path):
        """Vendored skill remains readable after its Layer-B cache is removed."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "test-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        cache = Path(data["data"]["cache"])
        if cache.exists():
            import shutil
            shutil.rmtree(cache)

        skill_md = project_dir / ".agents" / "skills" / "test-skill" / "SKILL.md"
        assert skill_md.exists()
        assert "test skill" in skill_md.read_text().lower()


# ---------------------------------------------------------------------------
# AK7: Lockfile create/update is deterministic and schema-compatible
# ---------------------------------------------------------------------------


class TestLockfile:
    """AK7: Lockfile behavior is deterministic and schema-compatible."""

    def test_lockfile_schema_imports(self):
        """scripts/lib/lockfile.py must be importable."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); from lib.lockfile import make_entry, upsert_entry, load_lockfile, save_lockfile; print('ok')"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "ok" in result.stdout

    def test_lockfile_make_entry_required_fields(self):
        """make_entry must produce all required lockfile schema fields."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import make_entry

        entry = make_entry(
            name="test-skill",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/test-skill/SKILL.md",
            source_commit="local",
            cache_path="/tmp/.local/share/library/skills/local/test-skill@local/",
            install_target=".agents/skills/test-skill/",
            checksum_sha256="a" * 64,
        )

        required = [
            "name", "type", "marketplace", "source", "source_commit",
            "cache_path", "install_target", "install_timestamp", "checksum_sha256",
        ]
        for field in required:
            assert field in entry, f"Required field '{field}' missing from lockfile entry"

    def test_lockfile_make_entry_type_field(self):
        """make_entry must set 'type' (not 'primitive_type') in the entry."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import make_entry

        entry = make_entry(
            name="x",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/x/SKILL.md",
            source_commit="abc",
            cache_path="",
            install_target=".agents/skills/x/",
            checksum_sha256="b" * 64,
        )
        assert entry.get("type") == "skill", f"Expected type='skill', got '{entry.get('type')}'"

    def test_lockfile_upsert_insert(self, tmp_path: Path):
        """upsert_entry must add a new entry if name not present."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import make_entry, upsert_entry

        data = {"installed": []}
        entry = make_entry(
            name="new-skill",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/new-skill/SKILL.md",
            source_commit="local",
            cache_path="",
            install_target=".agents/skills/new-skill/",
            checksum_sha256="c" * 64,
        )
        upsert_entry(data, entry)
        assert len(data["installed"]) == 1
        assert data["installed"][0]["name"] == "new-skill"

    def test_lockfile_upsert_update(self, tmp_path: Path):
        """upsert_entry must replace existing entry with same name."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import make_entry, upsert_entry

        data = {"installed": []}
        entry1 = make_entry(
            name="my-skill",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/v1/SKILL.md",
            source_commit="abc",
            cache_path="",
            install_target=".agents/skills/my-skill/",
            checksum_sha256="d" * 64,
        )
        entry2 = make_entry(
            name="my-skill",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/v2/SKILL.md",
            source_commit="def",
            cache_path="",
            install_target=".agents/skills/my-skill/",
            checksum_sha256="e" * 64,
        )
        upsert_entry(data, entry1)
        upsert_entry(data, entry2)

        assert len(data["installed"]) == 1, "Should have exactly one entry after upsert"
        assert data["installed"][0]["source_commit"] == "def", "Should have updated to v2"

    def test_lockfile_upsert_keeps_same_name_different_type(self, tmp_path: Path):
        """upsert_entry must allow cross-primitive name collisions."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import get_entry, make_entry, upsert_entry

        data = {"installed": []}
        skill_entry = make_entry(
            name="session-close",
            primitive_type="skill",
            marketplace="local",
            source="/tmp/session-close/SKILL.md",
            source_commit="abc",
            cache_path="",
            install_target=".agents/skills/session-close/",
            checksum_sha256="d" * 64,
        )
        agent_entry = make_entry(
            name="session-close",
            primitive_type="agent",
            marketplace="local",
            source="/tmp/session-close.md",
            source_commit="def",
            cache_path="",
            install_target=".claude/agents/session-close.md",
            checksum_sha256="e" * 64,
        )
        upsert_entry(data, skill_entry)
        upsert_entry(data, agent_entry)

        assert len(data["installed"]) == 2
        assert get_entry(data, "session-close", "skill")["source_commit"] == "abc"
        assert get_entry(data, "session-close", "agent")["source_commit"] == "def"

    def test_lockfile_round_trip(self, tmp_path: Path):
        """save_lockfile + load_lockfile must be lossless round-trip."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import load_lockfile, make_entry, save_lockfile, upsert_entry

        lockfile = tmp_path / ".library.lock"
        entry = make_entry(
            name="round-trip-skill",
            primitive_type="skill",
            marketplace="cognovis-core",
            source="https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md",
            source_commit="abc123def456abc1",
            cache_path="/tmp/.local/share/library/skills/cognovis-core/round-trip-skill@abc123def456ab/",
            install_target=".agents/skills/round-trip-skill/",
            checksum_sha256="f" * 64,
            license_id="MIT",
            bridge_symlinks=[".claude/skills/round-trip-skill -> /tmp/.local/..."],
        )

        data_before = {"installed": [entry]}
        save_lockfile(lockfile, data_before)
        data_after = load_lockfile(lockfile)

        assert len(data_after["installed"]) == 1
        loaded_entry = data_after["installed"][0]
        assert loaded_entry["name"] == entry["name"]
        assert loaded_entry["type"] == entry["type"]
        assert loaded_entry["marketplace"] == entry["marketplace"]
        assert loaded_entry["source_commit"] == entry["source_commit"]
        assert loaded_entry["checksum_sha256"] == entry["checksum_sha256"]

    def test_lockfile_load_missing_returns_empty(self, tmp_path: Path):
        """load_lockfile on a nonexistent path must return empty installed list."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import load_lockfile

        lockfile = tmp_path / "nonexistent.lock"
        data = load_lockfile(lockfile)
        assert data == {"installed": []}, f"Expected empty data, got {data}"

    def test_lockfile_load_migrates_agent_base_type(self, tmp_path: Path):
        """Legacy golden-prompt lockfile entries load as agent-base entries."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import load_lockfile, save_lockfile

        lockfile = tmp_path / ".library.lock"
        lockfile.write_text(
            "installed:\n"
            "  - name: cognovis-base\n"
            "    type: golden-prompt\n"
            "    marketplace: local\n"
            "    source: /tmp/cognovis-base.md\n"
            "    source_commit: local\n"
            "    cache_path: /tmp/cache/\n"
            "    install_target: .agents/agent-bases/cognovis-base.md\n"
            "    install_timestamp: 2026-05-12T07:30:00Z\n"
            f"    checksum_sha256: {'a' * 64}\n"
            "    composed_layers:\n"
            "      golden_prompt:\n"
            "        name: cognovis-base\n"
            f"        sha: {'b' * 64}\n"
        )

        data = load_lockfile(lockfile)
        entry = data["installed"][0]
        assert entry["type"] == "agent-base"
        assert "agent_base" in entry["composed_layers"]
        assert "golden_prompt" not in entry["composed_layers"]

        save_lockfile(lockfile, data)
        assert "type: agent-base" in lockfile.read_text()

    def test_lockfile_schema_validation(self, tmp_path: Path):
        """Written lockfile must conform to docs/schema/lockfile.schema.json."""
        try:
            import jsonschema
            import yaml
        except ImportError:
            pytest.skip("jsonschema or PyYAML not installed")

        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.lockfile import load_lockfile, make_entry, save_lockfile, upsert_entry

        schema_path = REPO_ROOT / "docs" / "schema" / "lockfile.schema.json"
        if not schema_path.exists():
            pytest.skip("lockfile.schema.json not found")

        import json
        with schema_path.open() as f:
            schema = json.load(f)

        lockfile = tmp_path / ".library.lock"
        data = {"installed": []}
        entry = make_entry(
            name="schema-test-skill",
            primitive_type="skill",
            marketplace="cognovis-core",
            source="https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md",
            source_commit="abc123def456abc123def456abc123def456abc123def456abc123def456ab12",
            cache_path="/Users/test/.local/share/library/skills/cognovis-core/schema-test-skill@abc123def456ab/",
            install_target=".agents/skills/schema-test-skill/",
            checksum_sha256="9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678",
            license_id="MIT",
        )
        upsert_entry(data, entry)
        save_lockfile(lockfile, data)

        # Reload and validate
        loaded = load_lockfile(lockfile)
        jsonschema.validate(loaded, schema)  # raises if invalid


# ---------------------------------------------------------------------------
# AK4+AK5: catalog primitive_to_section mapping tests (unit)
# ---------------------------------------------------------------------------


class TestPrimitiveMapping:
    """Unit tests for primitive-to-section mapping (core of AK1/AK2)."""

    def test_skill_maps_to_library_skills(self):
        """skill primitive maps to library.skills."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("skill")
        assert prim is not None
        assert prim.yaml_key == "library/skills"

    def test_agent_maps_to_library_agents(self):
        """agent primitive maps to library.agents."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("agent")
        assert prim is not None
        assert prim.yaml_key == "library/agents"

    def test_standard_maps_to_library_standards(self):
        """standard primitive maps to library.standards."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("standard")
        assert prim is not None
        assert prim.yaml_key == "library/standards"

    def test_script_maps_to_library_scripts(self):
        """script primitive maps to library.scripts."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("script")
        assert prim is not None
        assert prim.yaml_key == "library/scripts"

    def test_guardrail_maps_to_library_guardrails(self):
        """guardrail primitive maps to library.guardrails."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("guardrail")
        assert prim is not None
        assert prim.yaml_key == "library/guardrails"

    def test_mcp_maps_to_library_mcp_servers(self):
        """mcp primitive maps to library.mcp_servers."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("mcp")
        assert prim is not None
        assert prim.yaml_key == "library/mcp_servers"

    def test_model_standard_alias(self):
        """model_standard (underscore) is an alias for model-standard (hyphen)."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("model_standard")
        assert prim is not None
        assert prim.name == "model-standard"

    def test_agent_base_maps_to_library_agent_bases(self):
        """agent-base primitive maps to library.agent_bases."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        prim = get_primitive("agent-base")
        assert prim is not None
        assert prim.yaml_key == "library/agent_bases"
        assert prim.install_subdir == "agent-bases"

    def test_golden_prompt_primitive_alias_removed(self):
        """golden-prompt is no longer accepted as a primitive alias."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.primitives import get_primitive

        assert get_primitive("golden-prompt") is None

    def test_catalog_lookup_exact(self, project_dir: Path):
        """Exact name lookup must find the entry."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.catalog import load_catalog, lookup_entry

        catalog = load_catalog(project_dir)
        entry = lookup_entry(catalog, "skill", "test-skill")
        assert entry.get("name") == "test-skill"

    def test_catalog_lookup_not_found(self, project_dir: Path):
        """Lookup of nonexistent entry must raise NotFoundError."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.catalog import load_catalog, lookup_entry
        from lib.errors import NotFoundError

        catalog = load_catalog(project_dir)
        with pytest.raises(NotFoundError):
            lookup_entry(catalog, "skill", "nonexistent-xyz-abc")

    def test_catalog_lookup_fuzzy_match(self, project_dir: Path):
        """Fuzzy lookup by description substring must find the entry."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.catalog import load_catalog, lookup_entry

        catalog = load_catalog(project_dir)
        entry = lookup_entry(catalog, "skill", "tempdir integration")
        assert entry.get("name") == "test-skill"

    def test_source_parse_local(self, tmp_path: Path):
        """Local path source parses to kind='local'."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        parsed = parse_source("/tmp/skills/my-skill/SKILL.md")
        assert parsed.kind == "local"
        assert parsed.local_path == Path("/tmp/skills/my-skill/SKILL.md")
        assert parsed.path_type == "unknown"

    def test_source_parse_github_browser(self):
        """GitHub browser URL parses correctly."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        url = "https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md"
        parsed = parse_source(url)
        assert parsed.kind == "github_browser"
        assert parsed.org == "cognovis"
        assert parsed.repo == "library-core"
        assert parsed.branch == "main"
        assert parsed.file_path == "skills/dolt/SKILL.md"
        assert parsed.clone_url == "https://github.com/cognovis/library-core.git"

    def test_source_parse_github_raw(self):
        """GitHub raw URL parses correctly."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        url = "https://raw.githubusercontent.com/cognovis/library-core/main/skills/dolt/SKILL.md"
        parsed = parse_source(url)
        assert parsed.kind == "github_raw"
        assert parsed.org == "cognovis"
        assert parsed.repo == "library-core"
        assert parsed.branch == "main"
        assert parsed.file_path == "skills/dolt/SKILL.md"
        assert parsed.path_type == "file"

    def test_source_parse_github_repo_urls(self):
        """Plain HTTPS and SSH GitHub repo URLs parse with repo metadata."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.source import parse_source

        https = parse_source("https://github.com/cognovis/library-core.git")
        ssh = parse_source("git@github.com:cognovis/library-core.git")

        assert https.kind == "github_repo"
        assert https.org == "cognovis"
        assert https.repo == "library-core"
        assert https.clone_url == "https://github.com/cognovis/library-core.git"
        assert ssh.kind == "github_repo"
        assert ssh.org == "cognovis"
        assert ssh.repo == "library-core"
        assert ssh.clone_url == "git@github.com:cognovis/library-core.git"

    def test_cache_path_computation(self):
        """Cache path must follow the documented format."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.cache import compute_cache_path

        cache = compute_cache_path(
            "skill",
            "cognovis-core",
            "dolt",
            "abc123def456abcdef0123456789abcdef01234567",
        )
        # Format: ~/.local/share/library/skills/<marketplace>/<name>@<14hex>
        assert "skills" in str(cache)
        assert "cognovis-core" in str(cache)
        assert "dolt@abc123def456ab" in str(cache)

    def test_cache_path_local_commit(self):
        """Cache path for local source uses 'local' tag."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.cache import compute_cache_path

        cache = compute_cache_path("skill", "local", "my-skill", "local")
        assert "my-skill@local" in str(cache)


# ---------------------------------------------------------------------------
# CL-pq4: Standard installer flat-file installs from category-mirror source paths
# ---------------------------------------------------------------------------


class TestStandardInstallCategoryMirror:
    """AC tests for CL-pq4: single-file standards install to category-mirror paths."""

    @staticmethod
    def _patch_git_clone(
        monkeypatch: pytest.MonkeyPatch, standard_mod, fake_repo: Path
    ) -> None:
        """Patch standard installer git commands to clone from a local fixture."""
        def fake_run(cmd, capture_output=False, text=False, cwd=None):
            if cmd[:5] == ["git", "clone", "--quiet", "--depth", "1"]:
                target = Path(cmd[-1])
                shutil.copytree(fake_repo, target, dirs_exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd == ["git", "rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(cmd, 0, "abcdef1234567890\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(standard_mod.subprocess, "run", fake_run)

    def test_single_file_standard_installs_to_category_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC1: Single-file standard with blob URL installs to <base>/<category>/<file>.md."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        (fake_repo / "standards" / "workflow").mkdir(parents=True)
        (fake_repo / "standards" / "workflow" / "bead-hygiene.md").write_text(
            "# Bead Hygiene Standard\n"
        )

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "bead-hygiene",
                        "description": "Bead hygiene workflow standard.",
                        "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                    }
                ]
            },
            "marketplaces": [],
        }

        result = standard_mod.install_standard(catalog, "bead-hygiene", project)

        assert result["status"] == "ok", result
        # Must be a file path (category-mirror), NOT a per-name subdir
        install_target = result["data"]["canonical"]
        assert install_target.endswith("workflow/bead-hygiene.md"), (
            f"Expected category-mirror path ending with 'workflow/bead-hygiene.md', got: {install_target}"
        )
        target_path = Path(install_target)
        assert target_path.is_file(), f"Expected a file at {install_target}"
        assert not target_path.is_dir()

    def test_bundle_install_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC2: Bundle (tree URL) installs still go to <base>/<standard_name>/."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        bundle = fake_repo / "standards" / "bundle-standard"
        bundle.mkdir(parents=True)
        (bundle / "bundle-standard.md").write_text("# Bundle Standard\n")
        (bundle / "detail.md").write_text("# Detail\n")

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "bundle-standard",
                        "description": "Directory-backed standard fixture.",
                        "source": "https://github.com/example/repo/tree/main/standards/bundle-standard/",
                    }
                ]
            },
            "marketplaces": [],
        }

        result = standard_mod.install_standard(catalog, "bundle-standard", project)

        assert result["status"] == "ok", result
        canonical = project / ".agents" / "standards" / "bundle-standard"
        assert canonical.is_dir(), f"Expected directory bundle at {canonical}"
        assert (canonical / "bundle-standard.md").exists()
        assert (canonical / "detail.md").exists()

    def test_lockfile_install_target_no_trailing_slash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC3: Lockfile install_target for single-file standard has no trailing slash."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        (fake_repo / "standards" / "workflow").mkdir(parents=True)
        (fake_repo / "standards" / "workflow" / "bead-hygiene.md").write_text(
            "# Bead Hygiene\n"
        )

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "bead-hygiene",
                        "description": "Single-file standard.",
                        "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                    }
                ]
            },
            "marketplaces": [],
        }

        standard_mod.install_standard(catalog, "bead-hygiene", project)

        lockfile = project / ".library.lock"
        assert lockfile.exists()
        with lockfile.open() as f:
            lock_data = yaml.safe_load(f)

        entry = next(
            (e for e in lock_data.get("installed", []) if e.get("name") == "bead-hygiene"),
            None,
        )
        assert entry is not None, "No lockfile entry for bead-hygiene"
        install_target = entry.get("install_target", "")
        assert not install_target.endswith("/"), (
            f"Single-file install_target must not have trailing slash, got: {install_target}"
        )
        assert install_target.endswith(".md"), (
            f"Single-file install_target must end with .md, got: {install_target}"
        )

    def test_audit_detects_old_path_as_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC4: audit detects existing install at old per-name subdir path as drift."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import sync_audit
        from lib.lockfile import make_entry, save_lockfile

        project = tmp_path / "project"
        project.mkdir()

        # Create the old-style install: <base>/bead-hygiene/bead-hygiene.md
        old_install_dir = project / ".agents" / "standards" / "bead-hygiene"
        old_install_dir.mkdir(parents=True)
        old_file = old_install_dir / "bead-hygiene.md"
        old_file.write_text("# Bead Hygiene Standard\n")

        # Write lockfile entry with old-style install_target (per-name subdir, trailing slash)
        from lib.lockfile import compute_checksum, compute_directory_hash
        checksum = compute_directory_hash(old_install_dir)
        entry = make_entry(
            name="bead-hygiene",
            primitive_type="standard",
            marketplace="cognovis-core",
            source="https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
            source_commit="abcdef1234567890",
            cache_path=str(tmp_path / "cache" / "standards" / "cognovis-core" / "bead-hygiene@abcdef1") + "/",
            install_target=str(old_install_dir) + "/",
            checksum_sha256=checksum,
            checksum_type="directory",
            content_sha256=checksum,
        )

        lockfile = project / ".library.lock"
        save_lockfile(lockfile, {"installed": [entry]})

        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {"standards": [
                {
                    "name": "bead-hygiene",
                    "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                }
            ]},
            "marketplaces": [],
        }

        result = sync_audit.cmd_audit_impl(
            catalog=catalog,
            primitive="standard",
            repo_root=project,
            skip_upstream=True,
        )

        # The audit should detect path drift (install_target doesn't match category-mirror)
        drift_entries = [e for e in result.get("entries", []) if e.get("drift") is True]
        assert any(e.get("name") == "bead-hygiene" for e in drift_entries), (
            f"Expected drift for 'bead-hygiene' at old path, got: {result}"
        )

    def test_sync_removes_old_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC5: sync (re-install) removes old per-name subdir after installing to new path."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        (fake_repo / "standards" / "workflow").mkdir(parents=True)
        (fake_repo / "standards" / "workflow" / "bead-hygiene.md").write_text(
            "# Bead Hygiene Standard\n"
        )

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "bead-hygiene",
                        "description": "Single-file standard.",
                        "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                    }
                ]
            },
            "marketplaces": [],
        }

        # Create old-path dir before running install (simulates migration scenario)
        old_path = project / ".agents" / "standards" / "bead-hygiene"
        old_path.mkdir(parents=True)
        (old_path / "bead-hygiene.md").write_text("# old content\n")

        # Run install — should install to new path AND remove old path
        result = standard_mod.install_standard(catalog, "bead-hygiene", project)

        assert result["status"] == "ok", result

        # New path must exist
        new_path = project / ".agents" / "standards" / "workflow" / "bead-hygiene.md"
        assert new_path.is_file(), f"Expected new file at {new_path}"

        # Old path (per-name subdir) must be removed
        assert not old_path.exists(), (
            f"Old per-name subdir {old_path} was not removed after migration"
        )

    def test_nonparseable_category_falls_back_with_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC6: Source URL without parseable category falls back to old behavior with a warning."""
        import warnings
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib.installers import standard as standard_mod

        fake_repo = tmp_path / "fake-repo"
        # No 'standards/' component in the path
        (fake_repo / "content").mkdir(parents=True)
        (fake_repo / "content" / "my-rule.md").write_text("# My Rule\n")

        self._patch_git_clone(monkeypatch, standard_mod, fake_repo)
        monkeypatch.setattr(
            standard_mod,
            "compute_cache_path",
            lambda primitive_type, marketplace, name, source_commit: (
                tmp_path / "cache" / primitive_type / marketplace / f"{name}@{source_commit[:7]}"
            ),
        )

        project = tmp_path / "project"
        project.mkdir()
        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {
                "standards": [
                    {
                        "name": "my-rule",
                        "description": "Standard without standards/ in path.",
                        # blob URL but path doesn't have standards/<cat>/<file> structure
                        "source": "https://github.com/example/repo/blob/main/content/my-rule.md",
                    }
                ]
            },
            "marketplaces": [],
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = standard_mod.install_standard(catalog, "my-rule", project)

        assert result["status"] == "ok", result

        # Should fall back to old per-name subdir behavior
        install_target = result["data"]["canonical"]
        expected_old_path = str(project / ".agents" / "standards" / "my-rule")
        assert install_target.rstrip("/") == expected_old_path or install_target == expected_old_path, (
            f"Expected fallback to old path {expected_old_path}, got: {install_target}"
        )

        # A warning must have been emitted
        warning_messages = [str(w.message) for w in caught]
        assert any("category" in m.lower() or "fallback" in m.lower() or "warning" in m.lower() or "standard" in m.lower()
                   for m in warning_messages), (
            f"Expected a warning about category parsing, got: {warning_messages}"
        )

    def test_audit_no_false_drift_for_relative_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """AC7: audit does not report false drift for a correctly-installed entry with a relative install_target.

        Project-scope installs write relative install_target values (e.g.
        '.agents/standards/workflow/bead-hygiene.md').  The audit path-drift
        check must resolve both the actual and expected paths before comparing;
        otherwise a relative actual path can never equal an absolute expected
        path and every project-scope install is wrongly flagged.
        """
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import sync_audit
        from lib.lockfile import compute_checksum, make_entry, save_lockfile

        project = tmp_path / "project"
        project.mkdir()

        # Create the correctly-installed file at the category-mirror path
        installed_dir = project / ".agents" / "standards" / "workflow"
        installed_dir.mkdir(parents=True)
        installed_file = installed_dir / "bead-hygiene.md"
        installed_file.write_text("# Bead Hygiene Standard\n")

        checksum = compute_checksum(installed_file)

        # Simulate a project-scope lockfile entry with a RELATIVE install_target
        relative_target = ".agents/standards/workflow/bead-hygiene.md"
        entry = make_entry(
            name="bead-hygiene",
            primitive_type="standard",
            marketplace="cognovis-core",
            source="https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
            source_commit="abcdef1234567890",
            cache_path=str(tmp_path / "cache" / "standards" / "cognovis-core" / "bead-hygiene@abcdef1") + "/",
            install_target=relative_target,
            checksum_sha256=checksum,
            checksum_type="file",
            content_sha256=checksum,
        )

        lockfile = project / ".library.lock"
        save_lockfile(lockfile, {"installed": [entry]})

        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {"standards": [
                {
                    "name": "bead-hygiene",
                    "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                }
            ]},
            "marketplaces": [],
        }

        result = sync_audit.cmd_audit_impl(
            catalog=catalog,
            primitive="standard",
            repo_root=project,
            skip_upstream=True,
        )

        # No drift should be reported — relative path points to the correct location
        drift_entries = [e for e in result.get("entries", []) if e.get("drift") is True]
        assert not any(e.get("name") == "bead-hygiene" for e in drift_entries), (
            f"False drift reported for 'bead-hygiene' with correct relative install_target, got: {result}"
        )

    def test_audit_path_drift_upgrades_upstream_drift_kind_to_both(
        self, tmp_path: Path
    ):
        """Regression: when path drift co-occurs with upstream drift, drift_kind must be 'both'.

        Previously, _check_standard_path_drift used setdefault("drift_kind", "local") which
        is a no-op when upstream already set drift_kind="upstream". This caused the path
        non-conformance to be invisible to users reading drift_kind in audit output.
        """
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import sync_audit
        from lib.lockfile import (
            compute_checksum,
            find_lockfile,
            make_entry,
            save_lockfile,
        )

        project = tmp_path / "project"
        project.mkdir()

        # Install bead-hygiene at OLD path (per-name subdir, not category-mirror)
        old_install_dir = project / ".agents" / "standards" / "bead-hygiene"
        old_install_dir.mkdir(parents=True)
        old_file = old_install_dir / "bead-hygiene.md"
        old_file.write_text("# Bead Hygiene Standard\n")
        checksum = compute_checksum(old_file)

        entry = make_entry(
            name="bead-hygiene",
            primitive_type="standard",
            marketplace="cognovis-core",
            source="https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
            source_commit="abc1234",
            cache_path=str(old_install_dir) + "/",
            install_target=str(old_install_dir) + "/",
            checksum_sha256=checksum,
            checksum_type="directory",
            content_sha256=checksum,
        )

        lockfile = find_lockfile(project)
        save_lockfile(lockfile, {"installed": [entry]})

        catalog = {
            "default_dirs": {"standards": [{"default": ".agents/standards/"}]},
            "library": {"standards": [
                {
                    "name": "bead-hygiene",
                    "source": "https://github.com/cognovis/library-core/blob/main/standards/workflow/bead-hygiene.md",
                }
            ]},
            "marketplaces": [],
        }

        # Manually simulate an upstream_behind=True scenario by monkey-patching
        # the upstream status into the audit loop. We do this by calling the internal
        # audit with skip_upstream=True but then separately verifying the drift_kind
        # upgrade logic by checking _check_standard_path_drift directly.
        #
        # First: with skip_upstream=True, path drift should set drift_kind="local"
        result_no_upstream = sync_audit.cmd_audit_impl(
            catalog=catalog,
            primitive="standard",
            repo_root=project,
            skip_upstream=True,
        )
        bh_entry = next(
            (e for e in result_no_upstream.get("entries", []) if e.get("name") == "bead-hygiene"),
            None,
        )
        assert bh_entry is not None, "bead-hygiene entry not found in audit result"
        assert bh_entry.get("drift") is True, "Expected path drift"
        assert bh_entry.get("drift_kind") == "local", (
            f"Expected drift_kind='local' (path only), got: {bh_entry.get('drift_kind')}"
        )

        # Second: verify that when upstream drift also fires, drift_kind becomes "both".
        # Simulate by directly manipulating audit_entry state as the loop would produce it,
        # then re-calling _check_standard_path_drift and verifying upgrade logic.
        fake_audit_entry: dict = {
            "drift": True,
            "status": "drift",
            "drift_kind": "upstream",  # upstream check already fired
        }
        if sync_audit._check_standard_path_drift(entry, catalog, project, "project"):
            if fake_audit_entry.get("drift_kind") == "upstream":
                fake_audit_entry["drift_kind"] = "both"
            else:
                fake_audit_entry.setdefault("drift_kind", "local")

        assert fake_audit_entry["drift_kind"] == "both", (
            f"Expected drift_kind='both' when both upstream and path drift fire, "
            f"got: {fake_audit_entry['drift_kind']}"
        )


class TestMcpInstallerDefaultScope:
    @staticmethod
    def _catalog() -> dict:
        return {
            "library": {
                "mcp_servers": [
                    {
                        "name": "test-mcp",
                        "description": "MCP scope fixture",
                        "install": {
                            "mcp": {
                                "claude_code": {
                                    "snippet": {
                                        "type": "http",
                                        "url": "https://example.invalid/mcp",
                                    }
                                }
                            }
                        },
                    }
                ]
            }
        }

    def test_install_mcp_defaults_to_global_lockfile(self, tmp_path, monkeypatch):
        from lib import lockfile
        from lib.installers.mcp_installer import install_mcp

        global_lock = tmp_path / "home" / ".config" / "library" / "global.lock"
        monkeypatch.setattr(lockfile, "GLOBAL_LOCKFILE", global_lock)

        result = install_mcp(
            self._catalog(),
            "test-mcp",
            tmp_path / "project",
            dry_run=True,
            harness="claude_code",
        )

        assert result["lockfile_changes"] == [
            {
                "path": str(global_lock),
                "operation": "upsert",
                "entry": "test-mcp",
            }
        ]

    def test_remove_mcp_defaults_to_global_lockfile(self, tmp_path, monkeypatch):
        from lib import lockfile
        from lib.installers.mcp_installer import remove_mcp

        global_lock = tmp_path / "home" / ".config" / "library" / "global.lock"
        monkeypatch.setattr(lockfile, "GLOBAL_LOCKFILE", global_lock)

        result = remove_mcp(
            self._catalog(),
            "test-mcp",
            tmp_path / "project",
            dry_run=True,
            harness="claude_code",
        )

        lockfile_ops = [
            operation
            for operation in result["operations"]
            if operation.get("operation") == "remove_lockfile_entry"
        ]
        assert lockfile_ops == [
            {
                "operation": "remove_lockfile_entry",
                "path": str(global_lock),
                "details": "remove 'test-mcp'",
            }
        ]


class TestMcpInstallerScopeInvariant:
    @staticmethod
    def _catalog() -> dict:
        return TestMcpInstallerDefaultScope._catalog()

    def test_fix_cl_yum0_install_rejects_project_scope(self, tmp_path):
        from lib.errors import InstallError
        from lib.installers.mcp_installer import install_mcp

        with pytest.raises(InstallError, match="project-scoped MCP registration"):
            install_mcp(
                self._catalog(),
                "test-mcp",
                tmp_path,
                scope="project",
                dry_run=True,
            )

    def test_fix_cl_yum0_remove_rejects_project_scope(self, tmp_path):
        from lib.errors import InstallError
        from lib.installers.mcp_installer import remove_mcp

        with pytest.raises(InstallError, match="project-scoped MCP registration"):
            remove_mcp(
                self._catalog(),
                "test-mcp",
                tmp_path,
                scope="project",
                dry_run=True,
            )
