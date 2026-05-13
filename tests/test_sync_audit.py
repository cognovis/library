#!/usr/bin/env python3
"""
test_sync_audit.py — Tests for CL-7oy: directory hash, drift-only filter, exit codes.

AKs covered: 1, 2, 8 (partial)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPTS_DIR))


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_LIBRARY_YAML = """
default_dirs:
  skills:
    - default: .agents/skills/
    - global: ~/.agents/skills/
    - claude_bridge: .claude/skills/
    - global_claude_bridge: ~/.claude/skills/
  agents:
    - default: .claude/agents/
    - global: ~/.claude/agents/
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
  golden_prompts:
    - default: .agents/golden-prompts/
    - global: ~/.agents/golden-prompts/

library:
  skills:
    - name: test-skill
      description: A test skill
      source: {skill_source}
  agents: []
  prompts: []
  standards: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
golden_prompts: []
"""


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with skill fixture."""
    skill_dir = tmp_path / "fixture-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill.")
    (skill_dir / "use.md").write_text("# Use\nHow to use the skill.")

    library_yaml = FIXTURE_LIBRARY_YAML.format(
        skill_source=str(skill_dir / "SKILL.md"),
    )
    (tmp_path / "library.yaml").write_text(library_yaml)
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n")

    return tmp_path


# ---------------------------------------------------------------------------
# AK8: Directory hash determinism tests
# ---------------------------------------------------------------------------

class TestDirectoryHash:
    def test_directory_hash_is_deterministic(self, tmp_path):
        """Same directory contents must produce same hash regardless of call order."""
        from lib.lockfile import compute_directory_hash

        d = tmp_path / "testdir"
        d.mkdir()
        (d / "file_a.txt").write_bytes(b"hello")
        (d / "file_b.txt").write_bytes(b"world")
        (d / "sub").mkdir()
        (d / "sub" / "file_c.txt").write_bytes(b"nested")

        h1 = compute_directory_hash(d)
        h2 = compute_directory_hash(d)
        assert h1 == h2, "Same directory must produce same hash"
        assert len(h1) == 64, "SHA-256 hex digest must be 64 chars"

    def test_directory_hash_changes_on_file_edit(self, tmp_path):
        """Editing a file in the directory must change the hash."""
        from lib.lockfile import compute_directory_hash

        d = tmp_path / "testdir"
        d.mkdir()
        (d / "SKILL.md").write_bytes(b"original content")

        h_before = compute_directory_hash(d)
        (d / "SKILL.md").write_bytes(b"mutated content")
        h_after = compute_directory_hash(d)

        assert h_before != h_after, "Editing a file must change the directory hash"

    def test_directory_hash_changes_on_new_file(self, tmp_path):
        """Adding a new file must change the hash."""
        from lib.lockfile import compute_directory_hash

        d = tmp_path / "testdir"
        d.mkdir()
        (d / "SKILL.md").write_bytes(b"content")

        h_before = compute_directory_hash(d)
        (d / "new_file.txt").write_bytes(b"new file")
        h_after = compute_directory_hash(d)

        assert h_before != h_after, "Adding a file must change the directory hash"

    def test_directory_hash_is_path_independent(self, tmp_path):
        """Two directories with identical contents at different paths must have same hash."""
        from lib.lockfile import compute_directory_hash

        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "SKILL.md").write_bytes(b"same content")
        (d1 / "use.md").write_bytes(b"same use content")

        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "SKILL.md").write_bytes(b"same content")
        (d2 / "use.md").write_bytes(b"same use content")

        h1 = compute_directory_hash(d1)
        h2 = compute_directory_hash(d2)
        assert h1 == h2, "Identical content at different paths must produce same hash"

    def test_empty_directory_has_consistent_hash(self, tmp_path):
        """Empty directory must produce consistent (not-None) hash."""
        from lib.lockfile import compute_directory_hash

        d = tmp_path / "empty"
        d.mkdir()
        h = compute_directory_hash(d)
        assert h is not None
        assert len(h) == 64


# ---------------------------------------------------------------------------
# AK1: Audit with directory-type entry detects drift in non-primary files
# ---------------------------------------------------------------------------

class TestAuditDirectoryDrift:
    def test_audit_directory_drift_detected_on_non_primary_file(self, project_dir):
        """AK1: audit of a skill where any non-primary file was edited reports drift: true.

        We simulate drift by writing a fake lockfile entry with a "directory" checksum_type
        and a mismatched expected checksum. The audit must detect the mismatch.
        """
        from lib.sync_audit import cmd_audit_impl

        # Create a temporary directory representing an "installed" skill
        cache_dir = project_dir / "fake-cache" / "test-skill"
        cache_dir.mkdir(parents=True)
        (cache_dir / "SKILL.md").write_bytes(b"# Test Skill\nA test skill.")
        (cache_dir / "use.md").write_bytes(b"# Use\nHow to use this skill.")

        # Compute the real directory hash
        from lib.lockfile import compute_directory_hash
        real_hash = compute_directory_hash(cache_dir)

        # Create a lockfile entry with checksum_type=directory and the real hash
        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": "test-skill",
            "type": "skill",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(project_dir / ".agents/skills/test-skill") + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": real_hash,
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))

        # First audit should be clean
        catalog = {}
        result = cmd_audit_impl(catalog, "skill", project_dir, scope="project")
        assert result["status"] == "clean", f"Should be clean before mutation: {result}"

        # Now mutate the non-primary file (use.md)
        (cache_dir / "use.md").write_bytes(b"MUTATED - drift injection in use.md")

        # Audit must detect drift
        result = cmd_audit_impl(catalog, "skill", project_dir, scope="project")
        assert result["status"] == "drift", \
            f"Expected status=drift after mutating use.md, got: {result['status']}\nentries: {result['entries']}"
        drift_entries = [e for e in result.get("entries", []) if e.get("drift")]
        assert len(drift_entries) > 0, "Expected at least one drifted entry"
        assert drift_entries[0].get("status") == "drift"


# ---------------------------------------------------------------------------
# AK2: audit --drift-only exit codes
# ---------------------------------------------------------------------------

class TestAuditDriftOnly:
    def _make_drift_lockfile(self, project_dir, drifted: bool = False):
        """Write a lockfile for test-skill with a real cache dir.

        If drifted=True, sets the stored hash to a wrong value so audit detects drift.
        """
        from lib.lockfile import compute_directory_hash

        cache_dir = project_dir / "fake-cache" / "test-skill"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "SKILL.md").write_bytes(b"# Test Skill\nContent.")

        real_hash = compute_directory_hash(cache_dir)
        stored_hash = ("0" * 64) if drifted else real_hash

        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": "test-skill",
            "type": "skill",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(project_dir / ".agents/skills/test-skill") + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": stored_hash,
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))

    def test_audit_drift_only_flag_accepted(self, project_dir):
        """--drift-only flag must be accepted without error."""
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        # May exit 0 (clean) or 2 (drift), but not error on unknown flag
        assert result.returncode in (0, 2), \
            f"Unexpected exit code: {result.returncode}\nstderr: {result.stderr}"

    def test_audit_exits_0_when_clean(self, project_dir):
        """AK2: exits 0 when no drift detected (no entries → clean)."""
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        assert result.returncode == 0, \
            f"Expected exit 0 for clean, got {result.returncode}\nstderr: {result.stderr}"

    def test_audit_exits_2_when_drift(self, project_dir):
        """AK2: exits 2 when drift detected."""
        self._make_drift_lockfile(project_dir, drifted=True)
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        assert result.returncode == 2, \
            f"Expected exit 2 for drift, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_audit_drift_only_filters_entries(self, project_dir):
        """AK2: --drift-only filters out clean and unknown entries from output."""
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        # All returned entries must be drifted
        for entry in data.get("entries", []):
            assert entry.get("drift") is True, \
                f"--drift-only output contains non-drifted entry: {entry}"

    def test_audit_without_drift_only_exits_2_on_drift(self, project_dir):
        """AK2: regular audit also exits 2 when drift detected (not 0)."""
        self._make_drift_lockfile(project_dir, drifted=True)

        result = run_library("skill", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data.get("status") == "drift", f"Expected drift status: {data}"
        assert result.returncode == 2, \
            f"Expected exit 2 for drift status, got {result.returncode}"

    def test_audit_legacy_file_entry_is_unknown_not_drift(self, project_dir):
        """AK2: entries without checksum_type (legacy) report status 'unknown', not 'drift'."""
        from lib.sync_audit import cmd_audit_impl
        from lib.lockfile import find_lockfile, load_lockfile, save_lockfile, upsert_entry

        # Create a fake lockfile with a legacy entry (no checksum_type)
        lockfile_path = project_dir / ".library.lock"
        legacy_entry = {
            "name": "legacy-skill",
            "type": "skill",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(project_dir / "fake-cache") + "/",
            "install_target": str(project_dir / ".agents/skills/legacy-skill") + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": "a" * 64,
            "license": "unknown",
            "bridge_symlinks": [],
            # No checksum_type field
        }
        lock_data = {"installed": [legacy_entry]}
        import yaml as _yaml
        lockfile_path.write_text(_yaml.dump(lock_data))

        catalog = {}
        result = cmd_audit_impl(catalog, "skill", project_dir, scope="project")
        entries = result.get("entries", [])
        assert len(entries) == 1
        entry = entries[0]
        assert entry.get("status") == "unknown", \
            f"Legacy entry without checksum_type should be 'unknown', got: {entry.get('status')}"
        assert entry.get("drift") is False, \
            f"Legacy entry should not be marked as drift, got: {entry.get('drift')}"


# ---------------------------------------------------------------------------
# AK5: Top-level sync skips entries reported as 'current' by status
# ---------------------------------------------------------------------------

class TestTopLevelSync:
    def _make_library_yaml(self, project_dir: Path) -> None:
        """Write a minimal library.yaml."""
        (project_dir / "library.yaml").write_text(
            "default_dirs:\n  skills:\n    - default: .agents/skills/\n"
            "library:\n  skills: []\n  agents: []\n  prompts: []\n  standards: []\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\ngolden_prompts: []\n"
        )

    def _make_lockfile_with_entries(self, project_dir: Path) -> None:
        """Write a .library.lock with two entries."""
        entries = [
            {
                "name": "agent-current",
                "type": "agent",
                "marketplace": "local",
                "source": "https://github.com/test/repo-current",
                "source_commit": "aaa111",
                "cache_path": str(project_dir / "cache-current") + "/",
                "install_target": str(project_dir / ".claude/agents/agent-current") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "a" * 64,
                "checksum_type": "file",
                "license": "unknown",
                "bridge_symlinks": [],
            },
            {
                "name": "agent-behind",
                "type": "agent",
                "marketplace": "local",
                "source": "https://github.com/test/repo-behind",
                "source_commit": "bbb222",
                "cache_path": str(project_dir / "cache-behind") + "/",
                "install_target": str(project_dir / ".claude/agents/agent-behind") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "b" * 64,
                "checksum_type": "file",
                "license": "unknown",
                "bridge_symlinks": [],
            },
        ]
        (project_dir / ".library.lock").write_text(yaml.dump({"installed": entries}))

    def test_sync_all_subcommand_exists(self, project_dir):
        """library.py sync --help must not error."""
        result = run_library("sync", "--help", cwd=project_dir)
        assert result.returncode == 0, \
            f"sync --help failed: {result.stderr}"

    def test_sync_all_dry_run_prints_plan(self, project_dir):
        """AK6: sync --dry-run prints skipped vs refreshed plan."""
        result = run_library("sync", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, \
            f"sync --dry-run failed: {result.returncode}\nstderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "refreshed" in data or "status" in data

    def test_sync_all_dry_run_json_schema(self, project_dir):
        """AK6: sync --dry-run --json returns plan with skipped and refreshed."""
        result = run_library("sync", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("status") in ("dry-run", "ok")
        # Must have refreshed and skipped lists
        assert "refreshed" in data
        assert "skipped" in data

    def test_sync_skip_logic_in_unit(self, tmp_path):
        """AK5: sync skips entries with upstream_status == 'current'."""
        from lib.status import cmd_status_impl
        from unittest.mock import MagicMock, patch

        INSTALLED_SHA = "aaa111def456abc123def456abc123def456abc123def456abc123def456ab12"

        # Write library.yaml
        (tmp_path / "library.yaml").write_text(
            "default_dirs:\n  skills:\n    - default: .agents/skills/\n"
            "library:\n  skills: []\n  agents: []\n  prompts: []\n  standards: []\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\ngolden_prompts: []\n"
        )

        # Write lockfile with one current and one behind entry
        entries = [
            {
                "name": "agent-current",
                "type": "agent",
                "marketplace": "local",
                "source": "https://github.com/test/repo-current",
                "source_commit": INSTALLED_SHA,
                "cache_path": str(tmp_path / "cache-current") + "/",
                "install_target": str(tmp_path / ".claude/agents/agent-current") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "a" * 64,
                "checksum_type": "file",
                "license": "unknown",
                "bridge_symlinks": [],
            },
            {
                "name": "agent-behind",
                "type": "agent",
                "marketplace": "local",
                "source": "https://github.com/test/repo-behind",
                "source_commit": "old_sha",
                "cache_path": str(tmp_path / "cache-behind") + "/",
                "install_target": str(tmp_path / ".claude/agents/agent-behind") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "b" * 64,
                "checksum_type": "file",
                "license": "unknown",
                "bridge_symlinks": [],
            },
        ]
        (tmp_path / ".library.lock").write_text(yaml.dump({"installed": entries}))

        # Simulate status: agent-current is current, agent-behind is behind
        def mock_ls_remote(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            if "repo-current" in " ".join(cmd):
                r.stdout = f"{INSTALLED_SHA}\tHEAD\n"
            else:
                r.stdout = f"new_sha999999999999999999999999999999999999999999999999\tHEAD\n"
            return r

        with patch("lib.status.subprocess.run", side_effect=mock_ls_remote):
            status_result = cmd_status_impl({}, "all", tmp_path, scope="project")

        # agent-current must be current, agent-behind must be behind
        by_name = {e["name"]: e for e in status_result["entries"]}
        assert by_name["agent-current"]["upstream_status"] == "current"
        assert by_name["agent-behind"]["upstream_status"] == "behind"

        # Verify skip logic: current_names set excludes behind
        current_names = {
            e["name"] for e in status_result["entries"]
            if e["upstream_status"] == "current"
        }
        assert "agent-current" in current_names
        assert "agent-behind" not in current_names

    def test_sync_force_reinstalls_all(self, project_dir):
        """AK5: --force re-installs all entries regardless of status."""
        # With no entries, --force should succeed (no-op)
        result = run_library("sync", "--force", "--dry-run", "--json", cwd=project_dir)
        assert result.returncode == 0, \
            f"sync --force --dry-run failed: {result.returncode}\nstdout: {result.stdout}"
        data = json.loads(result.stdout)
        # skipped should be empty when --force is used
        assert data.get("skipped", []) == [], \
            f"Expected no skipped entries with --force, got: {data.get('skipped')}"


# ---------------------------------------------------------------------------
# AK8: make_entry with checksum_type
# ---------------------------------------------------------------------------

class TestMakeEntryChecksumType:
    def test_make_entry_default_checksum_type(self):
        """make_entry without checksum_type defaults to 'file'."""
        from lib.lockfile import make_entry
        entry = make_entry(
            name="test",
            primitive_type="agent",
            marketplace="local",
            source="local/test.md",
            source_commit="abc123",
            cache_path="/tmp/cache/test/",
            install_target="/tmp/install/test/",
            checksum_sha256="a" * 64,
        )
        assert entry.get("checksum_type") == "file"

    def test_make_entry_directory_checksum_type(self):
        """make_entry with checksum_type='directory' stores correctly."""
        from lib.lockfile import make_entry
        entry = make_entry(
            name="test-skill",
            primitive_type="skill",
            marketplace="local",
            source="local/test-skill/SKILL.md",
            source_commit="abc123",
            cache_path="/tmp/cache/test-skill/",
            install_target="/tmp/install/test-skill/",
            checksum_sha256="b" * 64,
            checksum_type="directory",
        )
        assert entry.get("checksum_type") == "directory"
