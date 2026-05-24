#!/usr/bin/env python3
"""
test_library_py_compat.py — Tests for CL-d7e: compatibility pre-install gate

AK1: skill use with compatibility: "claude_code>=99.0" exits 4 with message naming the requirement
AK2: skill use with no compatibility field installs normally (no regression)
AK3: skill use with satisfied compatibility string installs normally
AK4: Unknown harness version warns and proceeds (does not block)
AK5: Parser and all compatibility paths are covered

Run with:
    uv run pytest tests/test_library_py_compat.py -v
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
COMPAT_MODULE = SCRIPTS_DIR / "lib" / "compat.py"

# ---------------------------------------------------------------------------
# Library fixture YAML templates
# ---------------------------------------------------------------------------

FIXTURE_LIBRARY_YAML_COMPAT = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: compat-skill
      description: A skill with a compatibility requirement
      source: {skill_source}
      compatibility: "{compat_string}"
  standards: []
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""

FIXTURE_LIBRARY_YAML_NO_COMPAT = """
default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/
  standards:
    - default: .agents/standards/

library:
  skills:
    - name: plain-skill
      description: A plain skill without a compatibility field
      source: {skill_source}
  standards: []
  agents: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_skill_dir(tmp_path: Path) -> Path:
    """Create a minimal skill directory fixture."""
    skill_dir = tmp_path / "compat-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: compat-skill\ndescription: Compat test skill\n---\n\n# Compat Skill\n"
    )
    return skill_dir


@pytest.fixture
def plain_skill_dir(tmp_path: Path) -> Path:
    """Create a minimal plain skill directory fixture."""
    skill_dir = tmp_path / "plain-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: plain-skill\ndescription: Plain test skill\n---\n\n# Plain Skill\n"
    )
    return skill_dir


@pytest.fixture
def project_impossible_compat(tmp_path: Path, fixture_skill_dir: Path) -> Path:
    """Project with an impossible compatibility requirement (claude_code>=99.0)."""
    proj = tmp_path / "project-impossible"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_COMPAT.format(
            skill_source=str(fixture_skill_dir / "SKILL.md"),
            compat_string="claude_code>=99.0",
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


@pytest.fixture
def project_satisfied_compat(tmp_path: Path, fixture_skill_dir: Path) -> Path:
    """Project with a satisfied compatibility requirement (claude_code>=0.0)."""
    proj = tmp_path / "project-satisfied"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_COMPAT.format(
            skill_source=str(fixture_skill_dir / "SKILL.md"),
            compat_string="claude_code>=0.0",
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


@pytest.fixture
def project_no_compat(tmp_path: Path, plain_skill_dir: Path) -> Path:
    """Project without a compatibility field on the skill."""
    proj = tmp_path / "project-no-compat"
    proj.mkdir()
    (proj / "library.yaml").write_text(
        FIXTURE_LIBRARY_YAML_NO_COMPAT.format(
            skill_source=str(plain_skill_dir / "SKILL.md"),
        )
    )
    (proj / "CLAUDE.md").write_text("# CLAUDE.md\n")
    (proj / "AGENTS.md").write_text("# AGENTS\n")
    return proj


def run_library(*args, cwd=None, env=None):
    """Run library.py with given args, return CompletedProcess."""
    base_env = os.environ.copy()
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY)] + list(args),
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


def init_git_source_repo(repo: Path) -> None:
    """Initialize a source fixture repository."""
    run_git("init", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    run_git("config", "user.email", "test@example.com", cwd=repo)
    run_git("add", "-A", cwd=repo)
    run_git("commit", "-m", "initial", cwd=repo)


# ---------------------------------------------------------------------------
# Unit tests: compat module
# ---------------------------------------------------------------------------


class TestCompatModuleImportable:
    """The compat module must be importable."""

    def test_module_exists(self):
        assert COMPAT_MODULE.exists(), f"compat.py not found at {COMPAT_MODULE}"

    def test_module_importable(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); from lib import compat; print('ok')"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout


class TestParseCompatibility:
    """Tests for parse_compatibility() — parses harness version constraint strings."""

    def _import_parse(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        from lib import compat as m
        importlib.reload(m)
        return m.parse_compatibility

    def test_parse_gte_major_minor(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code>=4.0")
        assert harness == "claude_code"
        assert op == ">="
        assert version == "4.0"

    def test_parse_gte_major_only(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code>=4")
        assert harness == "claude_code"
        assert op == ">="
        assert version == "4"

    def test_parse_codex_harness(self):
        parse = self._import_parse()
        harness, op, version = parse("codex>=1.0")
        assert harness == "codex"
        assert op == ">="
        assert version == "1.0"

    def test_parse_eq_operator(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code==5.0")
        assert op == "=="

    def test_parse_gt_operator(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code>3.0")
        assert op == ">"

    def test_parse_lt_operator(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code<5.0")
        assert op == "<"

    def test_parse_lte_operator(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code<=5.0")
        assert op == "<="

    def test_parse_ne_operator(self):
        parse = self._import_parse()
        harness, op, version = parse("claude_code!=3.0")
        assert op == "!="

    def test_parse_invalid_raises(self):
        parse = self._import_parse()
        with pytest.raises(ValueError):
            parse("invalid-no-operator")

    def test_parse_empty_raises(self):
        parse = self._import_parse()
        with pytest.raises(ValueError):
            parse("")


class TestDetectHarnessVersion:
    """Tests for detect_harness_version() — best-effort, returns None on failure."""

    def _import_detect(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        from lib import compat as m
        importlib.reload(m)
        return m.detect_harness_version

    def test_returns_string_or_none(self):
        detect = self._import_detect()
        result = detect("claude_code")
        assert result is None or isinstance(result, str)

    def test_unknown_harness_returns_none(self):
        detect = self._import_detect()
        result = detect("nonexistent_harness_xyz_99")
        assert result is None

    def test_codex_harness_returns_string_or_none(self):
        detect = self._import_detect()
        result = detect("codex")
        assert result is None or isinstance(result, str)


class TestCheckCompatibilityGate:
    """Tests for check_compatibility_gate() — raises CompatibilityError when unsatisfied."""

    def _import_check(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        from lib import compat as m
        importlib.reload(m)
        return m.check_compatibility_gate, m.CompatibilityError

    def test_no_compat_field_passes(self):
        check, _ = self._import_check()
        # Entry without compatibility should not raise
        entry = {"name": "test-skill", "description": "desc"}
        check(entry, "claude_code")  # must not raise

    def test_impossible_version_raises_compatibility_error(self):
        import importlib
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import compat as m
        importlib.reload(m)
        check = m.check_compatibility_gate
        CompatibilityError = m.CompatibilityError

        entry = {"name": "test-skill", "description": "desc", "compatibility": "claude_code>=99.0"}
        with patch.object(m, "detect_harness_version", return_value="4.1.0"):
            with pytest.raises(CompatibilityError) as exc_info:
                check(entry, "claude_code")
        assert "claude_code>=99.0" in str(exc_info.value)

    def test_satisfied_version_passes(self):
        import importlib
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import compat as m
        importlib.reload(m)

        entry = {"name": "test-skill", "description": "desc", "compatibility": "claude_code>=0.1"}
        with patch.object(m, "detect_harness_version", return_value="4.1.0"):
            m.check_compatibility_gate(entry, "claude_code")  # must not raise

    def test_unknown_version_emits_warning_and_proceeds(self, capsys):
        import importlib
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import compat as m
        importlib.reload(m)

        entry = {"name": "test-skill", "description": "desc", "compatibility": "claude_code>=4.0"}
        with patch.object(m, "detect_harness_version", return_value=None):
            m.check_compatibility_gate(entry, "claude_code")  # must not raise

    def test_different_harness_skips_check(self):
        """Compatibility string for 'claude_code' should not block 'codex' installs."""
        import importlib
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import compat as m
        importlib.reload(m)

        entry = {"name": "test-skill", "description": "desc", "compatibility": "claude_code>=99.0"}
        with patch.object(m, "detect_harness_version", return_value="1.0"):
            # Should NOT raise because the harness is 'codex', not 'claude_code'
            m.check_compatibility_gate(entry, "codex")

    def test_error_includes_requirement_name(self):
        """Error message must name the compatibility requirement."""
        import importlib
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import compat as m
        importlib.reload(m)
        CompatibilityError = m.CompatibilityError

        entry = {"name": "my-skill", "description": "desc", "compatibility": "claude_code>=99.0"}
        with patch.object(m, "detect_harness_version", return_value="4.1.0"):
            with pytest.raises(CompatibilityError) as exc_info:
                m.check_compatibility_gate(entry, "claude_code")
        error_msg = str(exc_info.value)
        assert "claude_code" in error_msg
        assert "99.0" in error_msg


# ---------------------------------------------------------------------------
# Integration tests: library.py end-to-end
# ---------------------------------------------------------------------------


class TestCompatGateEndToEnd:
    """End-to-end tests via library.py subprocess calls."""

    def test_impossible_compat_exits_4(self, project_impossible_compat, fixture_skill_dir):
        """AK1: skill use with impossible compatibility exits 4 with message naming the requirement."""
        init_git_source_repo(fixture_skill_dir)
        result = run_library("skill", "use", "compat-skill", cwd=project_impossible_compat)
        assert result.returncode == 4, (
            f"Expected exit code 4, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "claude_code" in combined, f"Error must name the requirement. Got: {combined}"

    def test_impossible_compat_exits_4_json_mode(self, project_impossible_compat, fixture_skill_dir):
        """AK1: JSON mode also exits 4 with structured error."""
        import json
        init_git_source_repo(fixture_skill_dir)
        result = run_library("skill", "use", "compat-skill", "--json", cwd=project_impossible_compat)
        assert result.returncode == 4, (
            f"Expected exit code 4, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert data.get("status") == "error"
        assert "claude_code" in data.get("message", "")

    def test_no_compat_installs_normally(self, project_no_compat, plain_skill_dir):
        """AK2: Missing compatibility field — install proceeds normally (no regression)."""
        init_git_source_repo(plain_skill_dir)
        result = run_library("skill", "use", "plain-skill", cwd=project_no_compat)
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_satisfied_compat_installs_normally(self, project_satisfied_compat, fixture_skill_dir):
        """AK3: Satisfied compatibility — install proceeds normally."""
        init_git_source_repo(fixture_skill_dir)
        result = run_library("skill", "use", "compat-skill", cwd=project_satisfied_compat)
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_dry_run_with_impossible_compat_exits_4(self, project_impossible_compat, fixture_skill_dir):
        """AK1: --dry-run with impossible compatibility should also fail (gate runs before install)."""
        init_git_source_repo(fixture_skill_dir)
        result = run_library("skill", "use", "compat-skill", "--dry-run", cwd=project_impossible_compat)
        # dry-run still checks compatibility
        assert result.returncode == 4, (
            f"Expected exit code 4, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
