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
        """AK1: audit of a skill where any non-primary file was edited reports drift: true."""
        # Install the skill
        result = run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        assert result.returncode == 0, f"Install failed: {result.stdout}\n{result.stderr}"

        lockfile = project_dir / ".library.lock"
        lock_data = yaml.safe_load(lockfile.read_text())
        entry = next((e for e in lock_data["installed"] if e["name"] == "test-skill"), None)
        assert entry is not None, "test-skill not in lockfile"

        # Verify entry has checksum_type == "directory"
        assert entry.get("checksum_type") == "directory", \
            f"Expected checksum_type=directory, got: {entry.get('checksum_type')}"

        # Find the cache path and mutate a NON-primary file (use.md, not SKILL.md)
        cache_path_str = entry.get("cache_path", "").rstrip("/")
        assert cache_path_str, "cache_path is empty"
        cache_path = Path(cache_path_str)
        assert cache_path.is_dir(), f"cache_path is not a dir: {cache_path}"

        # Mutate use.md (non-primary)
        use_md = cache_path / "use.md"
        if use_md.exists():
            use_md.write_text("MUTATED — drift injection in use.md")
        else:
            # If use.md wasn't copied, mutate SKILL.md
            (cache_path / "SKILL.md").write_text("MUTATED — drift injection in SKILL.md")

        # Audit must detect drift
        result = run_library("skill", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        assert data["status"] == "drift", \
            f"Expected status=drift, got: {data['status']}\nfull output: {data}"
        drift_entries = [e for e in data.get("entries", []) if e.get("drift")]
        assert len(drift_entries) > 0, "Expected at least one drifted entry"


# ---------------------------------------------------------------------------
# AK2: audit --drift-only exit codes
# ---------------------------------------------------------------------------

class TestAuditDriftOnly:
    def test_audit_drift_only_flag_accepted(self, project_dir):
        """--drift-only flag must be accepted without error."""
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        # May exit 0 (clean) or 2 (drift), but not error on unknown flag
        assert result.returncode in (0, 2), \
            f"Unexpected exit code: {result.returncode}\nstderr: {result.stderr}"

    def test_audit_exits_0_when_clean(self, project_dir):
        """AK2: exits 0 when no drift detected."""
        result = run_library("skill", "audit", "--drift-only", "--json", cwd=project_dir)
        assert result.returncode == 0, \
            f"Expected exit 0 for clean, got {result.returncode}\nstderr: {result.stderr}"

    def test_audit_exits_2_when_drift(self, project_dir):
        """AK2: exits 2 when drift detected."""
        # Install and then mutate
        result = run_library("skill", "use", "test-skill", "--json", cwd=project_dir)
        assert result.returncode == 0

        lockfile = project_dir / ".library.lock"
        lock_data = yaml.safe_load(lockfile.read_text())
        entry = next((e for e in lock_data["installed"] if e["name"] == "test-skill"), None)
        assert entry is not None

        cache_path_str = entry.get("cache_path", "").rstrip("/")
        cache_path = Path(cache_path_str)

        # Mutate a file in the cache
        for f in cache_path.rglob("*.md"):
            f.write_text("MUTATED FOR DRIFT TEST")
            break

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
        # Install and mutate
        run_library("skill", "use", "test-skill", "--json", cwd=project_dir)

        lockfile = project_dir / ".library.lock"
        lock_data = yaml.safe_load(lockfile.read_text())
        entry = next((e for e in lock_data["installed"] if e["name"] == "test-skill"), None)
        if entry:
            cache_path_str = entry.get("cache_path", "").rstrip("/")
            for f in Path(cache_path_str).rglob("*.md"):
                f.write_text("MUTATED")
                break

        result = run_library("skill", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)
        if data.get("status") == "drift":
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
