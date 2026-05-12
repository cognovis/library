#!/usr/bin/env python3
"""
test_agent_sources_schema.py -- Tests for CL-l0c: agent_entry.sources map + install-hook Codex branch

Bead: CL-l0c
Tests:
  AK1:
    1. agent_entry schema accepts sources: map with claude + codex keys
    2. agent_entry schema still accepts legacy source: (singular) -- backward compat
    3. sources map with only claude key is valid
    4. sources map with only codex key is valid
  AK3:
    5. library.yaml bead-orchestrator entry has sources: map
    6. library.yaml session-close entry has sources: map
    7. library.yaml wave-orchestrator entry has sources: map
    8. library.yaml still passes schema validation after sources migration
  AK4:
    9. install-hook.py accepts --harness flag
    10. install-hook.py --harness codex dry-run shows SessionStart event
  AK5:
    11. mismatch_warning emitted for SubagentStop event with --harness codex

Run with:
    python3 -m pytest tests/test_agent_sources_schema.py -v
  or:
    python3 tests/test_agent_sources_schema.py
"""

import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("SKIP: PyYAML not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(0)

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    print("SKIP: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(0)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"
INSTALL_HOOK_PATH = REPO_ROOT / "scripts" / "install-hook.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def minimal_library_with_agents(agents: list) -> dict:
    """Build a minimal valid library.yaml structure with given agent entries."""
    return {
        "default_dirs": {
            "skills": [{"default": ".claude/skills/"}],
            "agents": [{"default": ".claude/agents/"}],
            "prompts": [{"default": ".claude/commands/"}],
        },
        "library": {
            "skills": [],
            "agents": agents,
            "prompts": [],
        },
    }


def assert_valid(data: dict, schema: dict, label: str) -> None:
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        raise AssertionError(f"Expected valid {label!r}, got: {e.message}") from e


def assert_invalid(data: dict, schema: dict, label: str) -> None:
    try:
        validate(instance=data, schema=schema)
        raise AssertionError(f"Expected invalid {label!r} to fail validation, but it passed")
    except ValidationError:
        pass


def load_library() -> dict:
    with LIBRARY_PATH.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# AK1: agent_entry sources: map schema
# ---------------------------------------------------------------------------


def test_agent_entry_sources_map_accepted():
    """agent_entry with sources: map (both claude + codex) passes validation."""
    schema = load_schema()
    data = minimal_library_with_agents([
        {
            "name": "bead-orchestrator",
            "description": "Test orchestrator agent",
            "sources": {
                "claude": "agents/bead-orchestrator.md",
                "codex": "agents/bead-orchestrator.toml",
            },
        }
    ])
    assert_valid(data, schema, "agent_entry with sources map")
    print("PASS test_agent_entry_sources_map_accepted")


def test_agent_entry_legacy_source_still_accepted():
    """agent_entry with legacy source: (singular) still passes -- backward compat."""
    schema = load_schema()
    data = minimal_library_with_agents([
        {
            "name": "my-agent",
            "description": "Legacy agent",
            "source": "https://github.com/cognovis/library-core/blob/main/agents/my-agent.md",
        }
    ])
    assert_valid(data, schema, "agent_entry with legacy source:")
    print("PASS test_agent_entry_legacy_source_still_accepted")


def test_agent_entry_sources_claude_only():
    """sources map with only claude key is valid."""
    schema = load_schema()
    data = minimal_library_with_agents([
        {
            "name": "my-agent",
            "description": "Claude-only agent",
            "sources": {
                "claude": "agents/my-agent.md",
            },
        }
    ])
    assert_valid(data, schema, "agent_entry with sources.claude only")
    print("PASS test_agent_entry_sources_claude_only")


def test_agent_entry_sources_codex_only():
    """sources map with only codex key is valid."""
    schema = load_schema()
    data = minimal_library_with_agents([
        {
            "name": "my-agent",
            "description": "Codex-only agent",
            "sources": {
                "codex": "agents/my-agent.toml",
            },
        }
    ])
    assert_valid(data, schema, "agent_entry with sources.codex only")
    print("PASS test_agent_entry_sources_codex_only")


# ---------------------------------------------------------------------------
# AK3: library.yaml has sources: map for 3 Codex agents
# ---------------------------------------------------------------------------


def _find_agent_entry(library: dict, name: str) -> dict | None:
    for entry in library.get("library", {}).get("agents", []):
        if entry.get("name") == name:
            return entry
    return None


def test_bead_orchestrator_uses_sources_map():
    """library.yaml bead-orchestrator entry uses sources: map (not legacy source:)."""
    library = load_library()
    entry = _find_agent_entry(library, "bead-orchestrator")
    assert entry is not None, "bead-orchestrator not found in library.yaml agents"
    assert "sources" in entry, (
        f"bead-orchestrator should use sources: map, found: {list(entry.keys())}"
    )
    sources = entry["sources"]
    assert "claude" in sources, f"sources.claude missing: {sources}"
    assert "codex" in sources, f"sources.codex missing: {sources}"
    print("PASS test_bead_orchestrator_uses_sources_map")


def test_session_close_uses_sources_map():
    """library.yaml session-close entry uses sources: map."""
    library = load_library()
    entry = _find_agent_entry(library, "session-close")
    assert entry is not None, "session-close not found in library.yaml agents"
    assert "sources" in entry, (
        f"session-close should use sources: map, found: {list(entry.keys())}"
    )
    sources = entry["sources"]
    assert "claude" in sources, f"sources.claude missing: {sources}"
    assert "codex" in sources, f"sources.codex missing: {sources}"
    print("PASS test_session_close_uses_sources_map")


def test_wave_orchestrator_uses_sources_map():
    """library.yaml wave-orchestrator entry uses sources: map."""
    library = load_library()
    entry = _find_agent_entry(library, "wave-orchestrator")
    assert entry is not None, "wave-orchestrator not found in library.yaml agents"
    assert "sources" in entry, (
        f"wave-orchestrator should use sources: map, found: {list(entry.keys())}"
    )
    sources = entry["sources"]
    assert "claude" in sources, f"sources.claude missing: {sources}"
    assert "codex" in sources, f"sources.codex missing: {sources}"
    print("PASS test_wave_orchestrator_uses_sources_map")


def test_library_yaml_still_valid_after_sources_migration():
    """library.yaml with sources: maps still passes schema validation."""
    result = subprocess.run(
        ["python3", str(REPO_ROOT / "scripts" / "validate-library.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"validate-library.py failed:\n{result.stdout}\n{result.stderr}"
    )
    print("PASS test_library_yaml_still_valid_after_sources_migration")


# ---------------------------------------------------------------------------
# AK4: install-hook.py --harness flag
# ---------------------------------------------------------------------------


def test_install_hook_accepts_harness_flag():
    """install-hook.py has a --harness argument."""
    result = subprocess.run(
        ["python3", str(INSTALL_HOOK_PATH), "--help"],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    assert "--harness" in combined, (
        f"--harness flag not found in install-hook.py --help:\n{combined}"
    )
    print("PASS test_install_hook_accepts_harness_flag")


def test_install_hook_codex_dry_run_shows_sessionstart():
    """install-hook.py --harness codex --dry-run exits 0 and shows SessionStart in output."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_codex_hooks = Path(tmp) / "codex-hooks.json"
        env = {**os.environ, "CODEX_HOOKS_FILE": str(fake_codex_hooks)}

        result = subprocess.run(
            [
                "python3", str(INSTALL_HOOK_PATH),
                "open-brain-hooks",
                "--harness", "codex",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"install-hook.py --harness codex failed:\n{combined}"
        )
        assert "SessionStart" in combined, (
            f"Expected SessionStart in codex dry-run output. Got:\n{combined}"
        )
    print("PASS test_install_hook_codex_dry_run_shows_sessionstart")


def test_install_hook_codex_single_hook_uses_current_schema():
    """Codex single-hook install uses current hook events, command runner, matcher, and timeout."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_codex_hooks = Path(tmp) / "codex-hooks.json"
        env = {**os.environ, "CODEX_HOOKS_FILE": str(fake_codex_hooks)}

        result = subprocess.run(
            [
                "python3", str(INSTALL_HOOK_PATH),
                "block-destructive-bash",
                "--harness", "codex",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"install-hook.py --harness codex failed:\n{combined}"
        )
        data = json.loads(fake_codex_hooks.read_text())
        serialized = json.dumps(data)
        assert "claude_code" not in combined, combined
        assert "PreToolUse" in data["hooks"], data
        group = data["hooks"]["PreToolUse"][0]
        hook = group["hooks"][0]
        assert group["matcher"] == "Bash", data
        assert hook["command"].startswith("node "), data
        assert hook["timeout"] == 15, data
        assert "timeoutSec" not in serialized, data
        assert not hook["command"].startswith("python3 "), data
    print("PASS test_install_hook_codex_single_hook_uses_current_schema")


# ---------------------------------------------------------------------------
# AK5: mismatch_warning for unsupported Codex events
# ---------------------------------------------------------------------------


def test_mismatch_warning_for_subagent_stop():
    """open-brain-hooks has SubagentStop -- must emit mismatch_warning with --harness codex."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_codex_hooks = Path(tmp) / "codex-hooks.json"
        env = {**os.environ, "CODEX_HOOKS_FILE": str(fake_codex_hooks)}

        result = subprocess.run(
            [
                "python3", str(INSTALL_HOOK_PATH),
                "open-brain-hooks",
                "--harness", "codex",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stdout + result.stderr
        # SubagentStop is unsupported in Codex and should not be written to hooks.json.
        # The script must emit a mismatch_warning for it
        assert "SubagentStop" in combined or "mismatch" in combined.lower(), (
            f"Expected SubagentStop mismatch warning in output. Got:\n{combined}"
        )
    print("PASS test_mismatch_warning_for_subagent_stop")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [
        test_agent_entry_sources_map_accepted,
        test_agent_entry_legacy_source_still_accepted,
        test_agent_entry_sources_claude_only,
        test_agent_entry_sources_codex_only,
        test_bead_orchestrator_uses_sources_map,
        test_session_close_uses_sources_map,
        test_wave_orchestrator_uses_sources_map,
        test_library_yaml_still_valid_after_sources_migration,
        test_install_hook_accepts_harness_flag,
        test_install_hook_codex_dry_run_shows_sessionstart,
        test_install_hook_codex_single_hook_uses_current_schema,
        test_mismatch_warning_for_subagent_stop,
    ]

    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
