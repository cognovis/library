#!/usr/bin/env python3
"""
test_library_py_harness_materializer.py — Tests for CL-3kq: always_apply/globs harness materialization

AK1: skill use with always_apply: true writes harness artifact for each harness (Claude Code, Codex, Cursor)
AK2: skill use with globs writes Cursor .mdc frontmatter; emits warning for Claude Code and Codex
AK3: Existing installs without the fields are unaffected (no regression)
AK4: Tests cover all three harness paths and the no-field fallback

Run with:
    uv run pytest tests/test_library_py_harness_materializer.py -v
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_LIBRARY_YAML_ALWAYS_APPLY = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: always-skill
      description: A skill with always_apply true
      source: {skill_source}
      always_apply: true
  standards: []
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
"""

FIXTURE_LIBRARY_YAML_GLOBS_ONLY = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: globs-skill
      description: A skill with globs only (no always_apply)
      source: {skill_source}
      globs:
        - "*.py"
        - "*.js"
  standards: []
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
"""

FIXTURE_LIBRARY_YAML_NO_FIELDS = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: plain-skill
      description: A plain skill with no always_apply or globs
      source: {skill_source}
  standards: []
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
"""

FIXTURE_LIBRARY_YAML_STANDARD_ALWAYS_APPLY = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills: []
  standards:
    - name: always-standard
      description: A standard with always_apply true
      source: {standard_source}
      always_apply: true
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
"""


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
def fixture_standard_dir(tmp_path: Path) -> Path:
    """Create a minimal standard directory fixture."""
    standard_dir = tmp_path / "fixture-standard"
    standard_dir.mkdir()
    standard_file = standard_dir / "always-standard.md"
    standard_file.write_text("# Always Standard\n\nThis is a test standard.\n")
    return standard_dir


@pytest.fixture
def project_always_apply(tmp_path: Path, fixture_skill_dir: Path) -> Path:
    """Project directory with always_apply: true skill."""
    proj = tmp_path / "test-project-always"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_ALWAYS_APPLY.format(
            skill_source=str(fixture_skill_dir / "SKILL.md")
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


@pytest.fixture
def project_globs_only(tmp_path: Path, fixture_skill_dir: Path) -> Path:
    """Project directory with globs-only skill (no always_apply)."""
    proj = tmp_path / "test-project-globs"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_GLOBS_ONLY.format(
            skill_source=str(fixture_skill_dir / "SKILL.md")
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


@pytest.fixture
def project_no_fields(tmp_path: Path, fixture_skill_dir: Path) -> Path:
    """Project directory with a plain skill (no always_apply, no globs)."""
    proj = tmp_path / "test-project-plain"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_NO_FIELDS.format(
            skill_source=str(fixture_skill_dir / "SKILL.md")
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


@pytest.fixture
def project_standard_always_apply(tmp_path: Path, fixture_standard_dir: Path) -> Path:
    """Project directory with always_apply standard."""
    proj = tmp_path / "test-project-std-always"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_STANDARD_ALWAYS_APPLY.format(
            standard_source=str(fixture_standard_dir / "always-standard.md")
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


# ---------------------------------------------------------------------------
# Unit tests for harness_materializer module
# ---------------------------------------------------------------------------

class TestHarnessMaterializerImport:
    """The harness_materializer module must be importable."""

    def test_module_importable(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'scripts'); "
                    "from lib.installers.harness_materializer import materialize_harness_fields; "
                    "print('ok')"
                ),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "ok" in result.stdout

    def test_function_signature(self):
        """materialize_harness_fields must accept the documented parameters."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'scripts'); "
                    "from lib.installers.harness_materializer import materialize_harness_fields; "
                    "import inspect; "
                    "sig = inspect.signature(materialize_harness_fields); "
                    "params = list(sig.parameters.keys()); "
                    "assert 'entry' in params, params; "
                    "assert 'name' in params, params; "
                    "assert 'primitive_type' in params, params; "
                    "assert 'repo_root' in params, params; "
                    "assert 'dry_run' in params, params; "
                    "print('ok')"
                ),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Signature check failed: {result.stderr}\n{result.stdout}"
        assert "ok" in result.stdout

    def test_function_returns_dict_with_operations_and_warnings(self, tmp_path: Path):
        """materialize_harness_fields must return dict with 'operations' and 'warnings'."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'scripts'); "
                    "from lib.installers.harness_materializer import materialize_harness_fields; "
                    "from pathlib import Path; "
                    f"r = materialize_harness_fields({{}}, 'test-skill', 'skill', Path('{tmp_path}')); "
                    "assert 'operations' in r, r; "
                    "assert 'warnings' in r, r; "
                    "print('ok')"
                ),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Function call failed: {result.stderr}\n{result.stdout}"
        assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# AK1: always_apply: true — Claude Code (CLAUDE.md)
# ---------------------------------------------------------------------------

class TestAlwaysApplyClaudeCode:
    """AK1a: always_apply: true appends @-import to CLAUDE.md."""

    def test_skill_use_always_apply_appends_to_claude_md(self, project_always_apply: Path):
        """After installing always-skill, CLAUDE.md must contain the @-import."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        assert result.returncode == 0, (
            f"skill use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        claude_md = project_always_apply / "CLAUDE.md"
        content = claude_md.read_text()
        assert "@.agents/skills/always-skill/SKILL.md" in content, (
            f"Expected @-import in CLAUDE.md, got:\n{content}"
        )

    def test_skill_use_always_apply_idempotent_claude_md(self, project_always_apply: Path):
        """Installing the same always-skill twice must NOT duplicate the @-import in CLAUDE.md."""
        for _ in range(2):
            subprocess.run(
                [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
                capture_output=True,
                text=True,
                cwd=str(project_always_apply),
            )
        claude_md = project_always_apply / "CLAUDE.md"
        content = claude_md.read_text()
        count = content.count("@.agents/skills/always-skill/SKILL.md")
        assert count == 1, (
            f"Expected exactly 1 @-import in CLAUDE.md, found {count}:\n{content}"
        )


# ---------------------------------------------------------------------------
# AK1: always_apply: true — Codex (AGENTS.md)
# ---------------------------------------------------------------------------

class TestAlwaysApplyCodex:
    """AK1b: always_apply: true appends @-import to AGENTS.md."""

    def test_skill_use_always_apply_appends_to_agents_md(self, project_always_apply: Path):
        """After installing always-skill, AGENTS.md must contain the @-import."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        assert result.returncode == 0, (
            f"skill use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        agents_md = project_always_apply / "AGENTS.md"
        content = agents_md.read_text()
        assert "@.agents/skills/always-skill/SKILL.md" in content, (
            f"Expected @-import in AGENTS.md, got:\n{content}"
        )

    def test_skill_use_always_apply_idempotent_agents_md(self, project_always_apply: Path):
        """Installing twice must NOT duplicate the @-import in AGENTS.md."""
        for _ in range(2):
            subprocess.run(
                [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
                capture_output=True,
                text=True,
                cwd=str(project_always_apply),
            )
        agents_md = project_always_apply / "AGENTS.md"
        content = agents_md.read_text()
        count = content.count("@.agents/skills/always-skill/SKILL.md")
        assert count == 1, (
            f"Expected exactly 1 @-import in AGENTS.md, found {count}:\n{content}"
        )


# ---------------------------------------------------------------------------
# AK1: always_apply: true — Cursor (.cursor/rules/<name>.mdc)
# ---------------------------------------------------------------------------

class TestAlwaysApplyCursor:
    """AK1c: always_apply: true writes .cursor/rules/<name>.mdc with alwaysApply: true."""

    def test_skill_use_always_apply_creates_cursor_mdc(self, project_always_apply: Path):
        """After installing always-skill, .cursor/rules/always-skill.mdc must exist."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        assert result.returncode == 0, (
            f"skill use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        mdc_path = project_always_apply / ".cursor" / "rules" / "always-skill.mdc"
        assert mdc_path.exists(), f"Expected {mdc_path} to exist"

    def test_cursor_mdc_has_always_apply_frontmatter(self, project_always_apply: Path):
        """The .mdc file must have alwaysApply: true in frontmatter."""
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        mdc_path = project_always_apply / ".cursor" / "rules" / "always-skill.mdc"
        content = mdc_path.read_text()
        assert "alwaysApply: true" in content, (
            f"Expected 'alwaysApply: true' in .mdc frontmatter:\n{content}"
        )

    def test_cursor_mdc_has_skill_reference(self, project_always_apply: Path):
        """The .mdc file must reference the SKILL.md path."""
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "always-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        mdc_path = project_always_apply / ".cursor" / "rules" / "always-skill.mdc"
        content = mdc_path.read_text()
        assert "@.agents/skills/always-skill/SKILL.md" in content, (
            f"Expected skill reference in .mdc:\n{content}"
        )


# ---------------------------------------------------------------------------
# AK2: globs only (no always_apply) — Cursor gets .mdc, Claude Code/Codex get warning
# ---------------------------------------------------------------------------

class TestGlobsOnly:
    """AK2: globs set but always_apply not set."""

    def test_globs_skill_creates_cursor_mdc(self, project_globs_only: Path):
        """Installing globs-only skill must create .cursor/rules/<name>.mdc."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "globs-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_globs_only),
        )
        assert result.returncode == 0, (
            f"skill use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        mdc_path = project_globs_only / ".cursor" / "rules" / "globs-skill.mdc"
        assert mdc_path.exists(), f"Expected {mdc_path} to exist"

    def test_globs_skill_mdc_has_glob_patterns(self, project_globs_only: Path):
        """The .mdc file must include the globs in its frontmatter."""
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "globs-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_globs_only),
        )
        mdc_path = project_globs_only / ".cursor" / "rules" / "globs-skill.mdc"
        content = mdc_path.read_text()
        assert "*.py" in content, f"Expected '*.py' glob in .mdc:\n{content}"

    def test_globs_skill_no_always_apply_in_mdc(self, project_globs_only: Path):
        """The .mdc for globs-only skill must NOT have alwaysApply: true."""
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "globs-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_globs_only),
        )
        mdc_path = project_globs_only / ".cursor" / "rules" / "globs-skill.mdc"
        content = mdc_path.read_text()
        assert "alwaysApply: true" not in content, (
            f"globs-only skill should NOT have alwaysApply: true:\n{content}"
        )

    def test_globs_skill_emits_warning_not_claude_md(self, project_globs_only: Path):
        """Globs-only skill must emit a warning for Claude Code and NOT modify CLAUDE.md."""
        claude_md_before = (project_globs_only / "CLAUDE.md").read_text()
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "globs-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_globs_only),
        )
        assert result.returncode == 0
        # CLAUDE.md must be unchanged
        claude_md_after = (project_globs_only / "CLAUDE.md").read_text()
        assert claude_md_before == claude_md_after, (
            f"CLAUDE.md was modified for globs-only skill (must not be modified)"
        )
        # A warning must appear on stderr
        assert "warn" in result.stderr.lower() or "globs" in result.stderr.lower(), (
            f"Expected warning on stderr for globs-only skill, got: {result.stderr!r}"
        )

    def test_globs_skill_emits_warning_not_agents_md(self, project_globs_only: Path):
        """Globs-only skill must NOT modify AGENTS.md."""
        agents_md_before = (project_globs_only / "AGENTS.md").read_text()
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "globs-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_globs_only),
        )
        assert result.returncode == 0
        agents_md_after = (project_globs_only / "AGENTS.md").read_text()
        assert agents_md_before == agents_md_after, (
            f"AGENTS.md was modified for globs-only skill (must not be modified)"
        )


# ---------------------------------------------------------------------------
# AK3: No regression — plain skill (no always_apply, no globs)
# ---------------------------------------------------------------------------

class TestNoFieldsNoRegression:
    """AK3: Installs without always_apply/globs are unaffected."""

    def test_plain_skill_does_not_modify_claude_md(self, project_no_fields: Path):
        """Plain skill install must NOT modify CLAUDE.md."""
        claude_md_before = (project_no_fields / "CLAUDE.md").read_text()
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "plain-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_no_fields),
        )
        assert result.returncode == 0, (
            f"skill use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        claude_md_after = (project_no_fields / "CLAUDE.md").read_text()
        assert claude_md_before == claude_md_after, (
            f"CLAUDE.md was modified by a plain skill install (regression!)"
        )

    def test_plain_skill_does_not_modify_agents_md(self, project_no_fields: Path):
        """Plain skill install must NOT modify AGENTS.md."""
        agents_md_before = (project_no_fields / "AGENTS.md").read_text()
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "plain-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_no_fields),
        )
        agents_md_after = (project_no_fields / "AGENTS.md").read_text()
        assert agents_md_before == agents_md_after, (
            f"AGENTS.md was modified by plain skill install (regression!)"
        )

    def test_plain_skill_does_not_create_cursor_mdc(self, project_no_fields: Path):
        """Plain skill install must NOT create any .cursor/rules/*.mdc."""
        subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "plain-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_no_fields),
        )
        cursor_rules = project_no_fields / ".cursor" / "rules"
        if cursor_rules.exists():
            mdc_files = list(cursor_rules.glob("*.mdc"))
            assert len(mdc_files) == 0, (
                f"Unexpected .mdc files created by plain skill: {mdc_files}"
            )

    def test_plain_skill_still_installs_correctly(self, project_no_fields: Path):
        """Plain skill install must still create the canonical symlink."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "plain-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_no_fields),
        )
        assert result.returncode == 0
        canonical = project_no_fields / ".agents" / "skills" / "plain-skill"
        assert canonical.exists(), f"Canonical symlink not created at {canonical}"

    def test_plain_skill_exits_zero_json_ok(self, project_no_fields: Path):
        """Plain skill install must return status=ok."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", "plain-skill", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_no_fields),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("status") == "ok", f"Expected status=ok, got: {data}"


# ---------------------------------------------------------------------------
# AK4: Standard with always_apply: true
# ---------------------------------------------------------------------------

class TestStandardAlwaysApply:
    """AK4: Standard with always_apply: true appends to CLAUDE.md and AGENTS.md."""

    def test_standard_always_apply_appends_to_claude_md(
        self, project_standard_always_apply: Path
    ):
        """Standard install with always_apply must append @-import to CLAUDE.md."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "always-standard", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_standard_always_apply),
        )
        assert result.returncode == 0, (
            f"standard use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        claude_md = project_standard_always_apply / "CLAUDE.md"
        content = claude_md.read_text()
        assert "@.agents/standards/always-standard/" in content, (
            f"Expected standard @-import in CLAUDE.md, got:\n{content}"
        )

    def test_standard_always_apply_appends_to_agents_md(
        self, project_standard_always_apply: Path
    ):
        """Standard install with always_apply must append @-import to AGENTS.md."""
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", "always-standard", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project_standard_always_apply),
        )
        assert result.returncode == 0, (
            f"standard use failed: {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        agents_md = project_standard_always_apply / "AGENTS.md"
        content = agents_md.read_text()
        assert "@.agents/standards/always-standard/" in content, (
            f"Expected standard @-import in AGENTS.md, got:\n{content}"
        )


# ---------------------------------------------------------------------------
# AK4: Dry-run mode includes harness ops
# ---------------------------------------------------------------------------

class TestDryRunHarnessOps:
    """Dry-run must include harness materialization ops in the operations list."""

    def test_dry_run_always_apply_includes_harness_ops(self, project_always_apply: Path):
        """Dry-run with always_apply must list harness ops."""
        result = subprocess.run(
            [
                sys.executable, str(LIBRARY_PY),
                "skill", "use", "always-skill", "--dry-run", "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        assert result.returncode == 0, f"dry-run failed: {result.stderr}"
        data = json.loads(result.stdout)
        ops = data.get("operations", [])
        op_names = [op.get("operation") for op in ops]
        # Must include a harness op for claude_md, agents_md, and cursor
        harness_related = [n for n in op_names if n and "harness" in n.lower()]
        harness_paths = [
            op.get("path", "") for op in ops
            if any(x in op.get("path", "") for x in ["CLAUDE.md", "AGENTS.md", ".mdc"])
        ]
        assert len(harness_related) > 0 or len(harness_paths) > 0, (
            f"Expected harness ops in dry-run operations, got: {ops}"
        )

    def test_dry_run_always_apply_no_mutation(self, project_always_apply: Path):
        """Dry-run with always_apply must NOT mutate CLAUDE.md, AGENTS.md, or .cursor/."""
        claude_before = (project_always_apply / "CLAUDE.md").read_text()
        agents_before = (project_always_apply / "AGENTS.md").read_text()
        result = subprocess.run(
            [
                sys.executable, str(LIBRARY_PY),
                "skill", "use", "always-skill", "--dry-run", "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(project_always_apply),
        )
        assert result.returncode == 0
        assert (project_always_apply / "CLAUDE.md").read_text() == claude_before, (
            "CLAUDE.md was modified during dry-run"
        )
        assert (project_always_apply / "AGENTS.md").read_text() == agents_before, (
            "AGENTS.md was modified during dry-run"
        )
        assert not (project_always_apply / ".cursor").exists(), (
            ".cursor dir was created during dry-run"
        )
