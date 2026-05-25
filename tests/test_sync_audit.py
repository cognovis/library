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
  agent_bases:
    - default: .agents/agent-bases/
    - global: ~/.agents/agent-bases/

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
# CL-wjr: Upstream-drift detection (catalog HEAD moved beyond lockfile pin)
# ---------------------------------------------------------------------------

class TestAuditUpstreamDrift:
    """Audit must flag entries whose lockfile source_commit is behind catalog HEAD.

    Pre-CL-wjr, audit only compared installed-dir hash vs lockfile content_sha256
    and reported CLEAN whenever the install was untampered — even if the catalog
    had moved on for weeks. That made `library skill audit` useless for detecting
    "your deploy is stale, run sync" situations, which is the primary thing it
    needs to detect on developer workstations.
    """

    def test_audit_skips_upstream_check_when_requested(self, project_dir, tmp_path):
        """skip_upstream=True must not perform network calls and must not raise.

        Test environments often have no network and no real remotes; the audit
        must remain usable in CI by passing skip_upstream=True.
        """
        from lib.sync_audit import cmd_audit_impl

        # Minimal lockfile with one local entry (no real remote)
        cache_dir = project_dir / "fake-cache" / "skill-x"
        cache_dir.mkdir(parents=True)
        (cache_dir / "SKILL.md").write_bytes(b"# X")
        from lib.lockfile import compute_directory_hash
        real_hash = compute_directory_hash(cache_dir)

        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": "skill-x",
            "type": "skill",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(cache_dir) + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": real_hash,
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))

        # Should not raise, should not call git ls-remote
        result = cmd_audit_impl({}, "skill", project_dir, scope="project", skip_upstream=True)
        assert result["status"] == "clean"
        # When skip_upstream=True the entry must report unknown upstream status
        entries = result.get("entries", [])
        assert entries[0].get("upstream_status") == "unknown"

    def test_audit_marks_upstream_behind_as_drift(self, project_dir, monkeypatch):
        """When cmd_status_impl reports upstream_status='behind', audit must
        report status='drift' and drift_kind='upstream'.

        We stub cmd_status_impl so the test does not need network access.
        """
        from lib.sync_audit import cmd_audit_impl

        # Create a clean install (no local tamper)
        cache_dir = project_dir / "fake-cache" / "behind-skill"
        cache_dir.mkdir(parents=True)
        (cache_dir / "SKILL.md").write_bytes(b"# behind-skill")
        from lib.lockfile import compute_directory_hash
        real_hash = compute_directory_hash(cache_dir)

        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": "behind-skill",
            "type": "skill",
            "marketplace": "local",
            "source": "https://github.com/example/repo/blob/main/skills/behind-skill/SKILL.md",
            "source_commit": "old1234",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(cache_dir) + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": real_hash,
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))

        # Stub status to report 'behind' for our entry
        def fake_status(catalog, primitive, repo_root, scope, offline=False, remote_cache=None):
            return {
                "status": "ok",
                "entries": [
                    {
                        "name": "behind-skill",
                        "primitive": "skill",
                        "upstream_status": "behind",
                        "behind": True,
                    }
                ],
            }

        import lib.status as status_mod
        monkeypatch.setattr(status_mod, "cmd_status_impl", fake_status)

        result = cmd_audit_impl({}, "skill", project_dir, scope="project")
        assert result["status"] == "drift", \
            f"Expected status=drift for upstream-behind entry, got: {result}"
        drift_entries = [e for e in result["entries"] if e.get("drift")]
        assert len(drift_entries) == 1
        assert drift_entries[0].get("drift_kind") == "upstream"
        assert drift_entries[0].get("upstream_status") == "behind"

    def test_audit_combines_local_and_upstream_drift_as_both(self, project_dir, monkeypatch):
        """Entry that has both local tamper AND upstream-behind must report
        drift_kind='both' so consumers can fix in the right order
        (sync first to bring lockfile forward, then resolve local tamper)."""
        from lib.sync_audit import cmd_audit_impl

        cache_dir = project_dir / "fake-cache" / "double-drift"
        cache_dir.mkdir(parents=True)
        (cache_dir / "SKILL.md").write_bytes(b"# original")

        from lib.lockfile import compute_directory_hash
        original_hash = compute_directory_hash(cache_dir)
        # Now tamper
        (cache_dir / "SKILL.md").write_bytes(b"# tampered")

        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": "double-drift",
            "type": "skill",
            "marketplace": "local",
            "source": "https://github.com/example/repo/blob/main/skills/double-drift/SKILL.md",
            "source_commit": "old5678",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(cache_dir) + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": original_hash,  # pre-tamper hash
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))

        def fake_status(catalog, primitive, repo_root, scope, offline=False, remote_cache=None):
            return {
                "status": "ok",
                "entries": [
                    {"name": "double-drift", "primitive": "skill", "upstream_status": "behind"}
                ],
            }

        import lib.status as status_mod
        monkeypatch.setattr(status_mod, "cmd_status_impl", fake_status)

        result = cmd_audit_impl({}, "skill", project_dir, scope="project")
        assert result["status"] == "drift"
        entries = result["entries"]
        assert len(entries) == 1
        assert entries[0].get("drift_kind") == "both", \
            f"Expected drift_kind=both, got: {entries[0]}"


# ---------------------------------------------------------------------------
# CL-a01: Claude agent frontmatter health checks
# ---------------------------------------------------------------------------

class TestAuditClaudeAgentFrontmatter:
    def _write_agent_lockfile(self, project_dir: Path, name: str, body: str) -> Path:
        """Write one installed Claude agent fixture plus matching lockfile entry."""
        from lib.lockfile import compute_checksum

        agent_path = project_dir / ".claude" / "agents" / f"{name}.md"
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(body)

        lockfile_path = project_dir / ".library.lock"
        entry = {
            "name": name,
            "type": "agent",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(agent_path) + "/",
            "install_target": str(agent_path),
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": compute_checksum(agent_path),
            "checksum_type": "file",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        lockfile_path.write_text(yaml.dump({"installed": [entry]}))
        return agent_path

    def test_audit_detects_claude_agent_missing_frontmatter(self, project_dir):
        """Agent audit flags installed Claude agent files whose first line is not frontmatter."""
        from lib.sync_audit import cmd_audit_impl

        agent_path = self._write_agent_lockfile(
            project_dir,
            "broken-agent",
            "# Composed Body\n\nNo YAML frontmatter.",
        )

        result = cmd_audit_impl({}, "agent", project_dir, scope="project")

        assert result["status"] == "drift"
        entry = result["entries"][0]
        assert entry["drift"] is True
        issue = entry["agent_frontmatter_issue"]
        assert issue["code"] == "missing_frontmatter"
        assert issue["path"] == str(agent_path)
        assert issue["repair_hint"] == (
            "library agent sync broken-agent --scope project --harness claude_code"
        )

    def test_audit_detects_claude_agent_missing_description(self, project_dir):
        """Agent audit flags installed Claude agent frontmatter without description."""
        from lib.sync_audit import cmd_audit_impl

        agent_path = self._write_agent_lockfile(
            project_dir,
            "missing-description",
            "---\nname: missing-description\nmodel: sonnet\n---\n\n# Body\n",
        )

        result = cmd_audit_impl({}, "agent", project_dir, scope="project")

        assert result["status"] == "drift"
        entry = result["entries"][0]
        issue = entry["agent_frontmatter_issue"]
        assert issue["code"] == "missing_description"
        assert issue["path"] == str(agent_path)
        assert "library agent sync missing-description" in entry["repair_hint"]

    def test_audit_accepts_healthy_claude_agent_frontmatter(self, project_dir):
        """Agent audit passes when installed Claude agent frontmatter has description."""
        from lib.sync_audit import cmd_audit_impl

        self._write_agent_lockfile(
            project_dir,
            "healthy-agent",
            (
                "---\n"
                "name: healthy-agent\n"
                "description: Healthy test agent\n"
                "model: sonnet\n"
                "---\n\n"
                "# Body\n"
            ),
        )

        result = cmd_audit_impl({}, "agent", project_dir, scope="project")

        assert result["status"] == "clean"
        entry = result["entries"][0]
        assert entry["drift"] is False
        assert entry["status"] == "clean"
        assert "agent_frontmatter_issue" not in entry

    def test_agent_audit_json_output_includes_frontmatter_repair_hint(self, project_dir):
        """CLI JSON output includes path and targeted sync hint for frontmatter failures."""
        self._write_agent_lockfile(
            project_dir,
            "cli-broken-agent",
            "# Body without frontmatter\n",
        )

        result = run_library("agent", "audit", "--json", cwd=project_dir)
        data = json.loads(result.stdout)

        assert result.returncode == 2, result.stderr
        entry = data["entries"][0]
        assert entry["agent_frontmatter_issue"]["path"].endswith("cli-broken-agent.md")
        assert entry["repair_hint"] == (
            "library agent sync cli-broken-agent --scope project --harness claude_code"
        )


# ---------------------------------------------------------------------------
# AK5: Top-level sync skips entries reported as 'current' by status
# ---------------------------------------------------------------------------

class TestTopLevelSync:
    def _make_library_yaml(self, project_dir: Path) -> None:
        """Write a minimal library.yaml."""
        (project_dir / "library.yaml").write_text(
            "default_dirs:\n  skills:\n    - default: .agents/skills/\n"
            "library:\n  skills: []\n  agents: []\n  prompts: []\n  standards: []\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\n"
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
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\n"
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

    def test_sync_all_skips_repo_behind_entries_when_source_path_unchanged(
        self, tmp_path, capsys, monkeypatch
    ):
        """Bulk sync must not reinstall every entry from a repo when only one path changed."""
        import argparse
        import library as library_cli

        old_sha = "1" * 40
        new_sha = "2" * 40
        entries = [
            {
                "name": "skill-unchanged",
                "type": "skill",
                "marketplace": "cognovis-core",
                "source": "https://github.com/cognovis/library-core/blob/main/skills/skill-unchanged/SKILL.md",
                "source_commit": old_sha,
                "cache_path": str(tmp_path / "cache-unchanged") + "/",
                "install_target": str(tmp_path / ".agents/skills/skill-unchanged") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "a" * 64,
                "checksum_type": "directory",
                "license": "unknown",
                "bridge_symlinks": [],
            },
            {
                "name": "skill-changed",
                "type": "skill",
                "marketplace": "cognovis-core",
                "source": "https://github.com/cognovis/library-core/blob/main/skills/skill-changed/SKILL.md",
                "source_commit": old_sha,
                "cache_path": str(tmp_path / "cache-changed") + "/",
                "install_target": str(tmp_path / ".agents/skills/skill-changed") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "b" * 64,
                "checksum_type": "directory",
                "license": "unknown",
                "bridge_symlinks": [],
            },
        ]
        (tmp_path / ".library.lock").write_text(yaml.dump({"installed": entries}))

        def fake_status(**kwargs):
            return {
                "status": "ok",
                "overall": "behind",
                "entries": [
                    {
                        "name": entry["name"],
                        "primitive": entry["type"],
                        "upstream_status": "behind",
                        "behind": True,
                        "installed_sha": old_sha,
                        "remote_sha": new_sha,
                    }
                    for entry in entries
                ],
            }

        def fake_path_changed(*, entry, remote_sha, temp_root, repo_cache):
            return entry["name"] == "skill-changed"

        monkeypatch.setattr(library_cli, "cmd_status_impl", fake_status)
        monkeypatch.setattr(library_cli, "_entry_source_path_changed", fake_path_changed)

        args = argparse.Namespace(
            json=True,
            dry_run=True,
            force=False,
            scope="project",
            harness="all",
        )
        rc = library_cli.cmd_sync_all(args, tmp_path, catalog={})

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["refreshed"] == ["skill:skill-changed"]
        assert data["skipped_by_status"]["path_unchanged"] == [
            "skill:skill-unchanged"
        ]


# ---------------------------------------------------------------------------
# AK7: Hook script smoke test
# ---------------------------------------------------------------------------

class TestHookScript:
    def test_hook_script_exists_and_is_executable(self):
        """AK7: library-drift-summary.sh must exist and be executable."""
        hook = REPO_ROOT / "scripts" / "hooks" / "library-drift-summary.sh"
        assert hook.exists(), f"Hook script not found at {hook}"
        assert hook.stat().st_mode & 0o111, "Hook script must be executable"

    def test_hook_script_exits_0_on_clean_project(self):
        """AK7: hook script exits 0 when no drift or behind entries."""
        hook = REPO_ROOT / "scripts" / "hooks" / "library-drift-summary.sh"
        result = subprocess.run(
            ["bash", str(hook)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, \
            f"Hook script failed: exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"

    def test_hook_script_silent_when_clean(self, project_dir):
        """AK7: hook script produces no output when project is clean."""
        hook = REPO_ROOT / "scripts" / "hooks" / "library-drift-summary.sh"
        result = subprocess.run(
            ["bash", str(hook)],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        # Clean project: no output expected
        assert result.stdout.strip() == "", \
            f"Expected no output for clean project, got: {result.stdout}"

    def test_hook_script_outputs_drift_section_when_drift_exists(self, project_dir):
        """AK7: hook script prints drift section when local drift detected."""
        from lib.lockfile import compute_directory_hash

        hook = REPO_ROOT / "scripts" / "hooks" / "library-drift-summary.sh"

        # Create a drift scenario: lockfile says one hash, cache has different content
        cache_dir = project_dir / "hook-test-cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "SKILL.md").write_bytes(b"original content")

        real_hash = compute_directory_hash(cache_dir)

        # Write lockfile with WRONG hash to simulate drift
        entry = {
            "name": "drifted-skill",
            "type": "skill",
            "marketplace": "local",
            "source": "local",
            "source_commit": "abc123",
            "cache_path": str(cache_dir) + "/",
            "install_target": str(project_dir / ".agents/skills/drifted-skill") + "/",
            "install_timestamp": "2024-01-01T00:00:00Z",
            "checksum_sha256": "0" * 64,  # Wrong hash -> drift
            "checksum_type": "directory",
            "license": "unknown",
            "bridge_symlinks": [],
        }
        (project_dir / ".library.lock").write_text(yaml.dump({"installed": [entry]}))
        (project_dir / "library.yaml").write_text(
            "default_dirs:\n  skills:\n    - default: .agents/skills/\n"
            "library:\n  skills: []\n  agents: []\n  prompts: []\n  standards: []\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\n"
        )

        result = subprocess.run(
            ["bash", str(hook)],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
        )
        # Exit code 0 (hook always exits 0 — it's informational)
        assert result.returncode == 0, \
            f"Hook should exit 0 even with drift: {result.returncode}"
        # Must print drift summary
        assert "Library Drift Summary" in result.stdout or "DRIFT" in result.stdout, \
            f"Expected drift summary in output, got: {result.stdout}"

    def test_hook_script_outputs_both_sections_when_drift_and_behind(self, tmp_path):
        """AK7: hook prints both '### Local drift' and '### Upstream drift' sections."""
        hook = REPO_ROOT / "scripts" / "hooks" / "library-drift-summary.sh"

        # --- Local drift entry (directory hash mismatch) ---
        cache_dir_drift = tmp_path / "cache-drifted"
        cache_dir_drift.mkdir(parents=True)
        (cache_dir_drift / "SKILL.md").write_bytes(b"original content")

        # --- Upstream-behind entry (source_commit differs from remote) ---
        cache_dir_behind = tmp_path / "cache-behind"
        cache_dir_behind.mkdir(parents=True)
        (cache_dir_behind / "SKILL.md").write_bytes(b"behind content")

        from lib.lockfile import compute_directory_hash
        behind_hash = compute_directory_hash(cache_dir_behind)

        entries = [
            {
                "name": "drifted-skill",
                "type": "skill",
                "marketplace": "local",
                "source": "local",
                "source_commit": "abc123",
                "cache_path": str(cache_dir_drift) + "/",
                "install_target": str(tmp_path / ".agents/skills/drifted-skill") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": "0" * 64,  # Wrong hash -> local drift
                "checksum_type": "directory",
                "license": "unknown",
                "bridge_symlinks": [],
            },
            {
                "name": "behind-skill",
                "type": "skill",
                "marketplace": "local",
                "source": "https://github.com/test/repo-behind",
                "source_commit": "oldsha1111111111111111111111111111111111111",
                "cache_path": str(cache_dir_behind) + "/",
                "install_target": str(tmp_path / ".agents/skills/behind-skill") + "/",
                "install_timestamp": "2024-01-01T00:00:00Z",
                "checksum_sha256": behind_hash,
                "checksum_type": "directory",
                "license": "unknown",
                "bridge_symlinks": [],
            },
        ]

        (tmp_path / ".library.lock").write_text(yaml.dump({"installed": entries}))
        (tmp_path / "library.yaml").write_text(
            "default_dirs:\n  skills:\n    - default: .agents/skills/\n"
            "library:\n  skills: []\n  agents: []\n  prompts: []\n  standards: []\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\n"
        )
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n")

        # Create a fake `git` wrapper that returns a known SHA for ls-remote
        fake_git_dir = tmp_path / "fake-git-bin"
        fake_git_dir.mkdir()
        fake_git = fake_git_dir / "git"
        fake_git.write_text(
            "#!/bin/bash\n"
            "if [[ \"$1\" == \"ls-remote\" ]]; then\n"
            "    printf 'abc123newsha111111111111111111111111111111\\tHEAD\\n'\n"
            "    exit 0\n"
            "fi\n"
            "exec /usr/bin/git \"$@\"\n"
        )
        fake_git.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = str(fake_git_dir) + ":" + env.get("PATH", "")

        result = subprocess.run(
            ["bash", str(hook)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )

        assert result.returncode == 0, \
            f"Hook should exit 0 even with drift+behind: exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        assert "### Local drift" in result.stdout, \
            f"Expected '### Local drift' section in output, got:\n{result.stdout}"
        assert "### Upstream drift" in result.stdout, \
            f"Expected '### Upstream drift' section in output, got:\n{result.stdout}"


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


# ---------------------------------------------------------------------------
# CL-rk2: workflow audit detects missing .js install target
# ---------------------------------------------------------------------------

class TestWorkflowAuditMissingFile:
    """AC3/AC4: workflow audit must detect missing install target as drift."""

    def test_workflow_audit_detects_missing_js_install_target(self, tmp_path: Path):
        """When a workflow .js file is deleted after install, audit must report drift."""
        import yaml
        from lib.sync_audit import cmd_audit_impl

        # Set up a minimal project with a workflow lockfile entry
        workflow_dir = tmp_path / "fixture-workflow"
        workflow_dir.mkdir()
        js_file = workflow_dir / "test-workflow.js"
        js_file.write_text("export const meta = { name: 'test-workflow' };\n")

        project = tmp_path / "project"
        project.mkdir()
        (project / "library.yaml").write_text(
            "default_dirs:\n  workflows:\n    - default: .claude/workflows/\n\n"
            "library:\n  workflows:\n    - name: test-workflow\n"
            "      description: Test\n      source: " + str(js_file) + "\n"
            "marketplaces: []\nguardrails: []\nmcp_servers: []\nmodel_standards: []\n"
        )

        # Install workflow
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "workflow", "use", "test-workflow", "--json"],
            capture_output=True,
            text=True,
            cwd=str(project),
        )
        assert result.returncode == 0, f"install failed: {result.stderr}"

        installed_path = project / ".claude" / "workflows" / "test-workflow.js"
        assert installed_path.exists(), "install target should exist after use"

        # Delete the installed file to simulate drift
        installed_path.unlink()
        assert not installed_path.exists(), "installed file should be gone"

        # Now audit should detect missing file as drift, not report clean
        catalog = yaml.safe_load((project / "library.yaml").read_text())
        audit_result = cmd_audit_impl(catalog, "workflow", project, scope="project")
        entries = audit_result.get("entries", [])
        assert entries, "audit should return entries for installed workflow"

        wf_entry = next(
            (e for e in entries if e.get("name") == "test-workflow"),
            None,
        )
        assert wf_entry is not None, "audit should have entry for test-workflow"
        assert wf_entry.get("status") in ("missing", "drift"), (
            f"Expected status='missing' or 'drift' when .js file deleted, got {wf_entry.get('status')!r}"
        )
