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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"

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
