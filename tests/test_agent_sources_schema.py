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
    5. library.yaml bead-orchestrator entry has one Markdown source
    6. library.yaml session-close entry has one Markdown source
    7. retired agents do not require source-shape coverage
    8. library.yaml still passes schema validation after sources migration
  AK4:
    9. install-hook.py accepts --harness flag
    10. install-hook.py --harness codex dry-run shows SessionStart event
  AK5:
    11. Codex uses its per-harness OpenBrain manifest without Claude-only events

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
import importlib.util
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


def seed_open_brain_hooks_checkout(xdg_data_home: Path) -> None:
    """Create a minimal cached OpenBrain checkout for install-hook dry-runs."""
    hooks_dir = xdg_data_home / "library" / "guardrails" / "open-brain-hooks" / "checkout" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "hooks.json").write_text(json.dumps({
        "description": "claude manifest",
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/context_inject.py",
                        }
                    ]
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/worktree_turn_log.py",
                        }
                    ]
                }
            ],
        },
    }))
    (hooks_dir / "hooks.codex.json").write_text(json.dumps({
        "description": "codex manifest",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${OPEN_BRAIN_PLUGIN_ROOT}/hooks/scripts/context_inject.py --harness codex",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${OPEN_BRAIN_PLUGIN_ROOT}/hooks/scripts/codex_session_summary.py",
                            "timeout": 15,
                        }
                    ]
                }
            ],
        },
    }))


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


def load_install_hook_module():
    """Load scripts/install-hook.py despite the hyphenated filename."""
    scripts_path = str(REPO_ROOT / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    spec = importlib.util.spec_from_file_location("install_hook", INSTALL_HOOK_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
# AK3: library.yaml has one source for formerly dual-source agents
# ---------------------------------------------------------------------------


def _find_agent_entry(library: dict, name: str) -> dict | None:
    for entry in library.get("library", {}).get("agents", []):
        if entry.get("name") == name:
            return entry
    return None


def test_bead_orchestrator_uses_single_source():
    """library.yaml bead-orchestrator entry uses one Markdown source."""
    library = load_library()
    entry = _find_agent_entry(library, "bead-orchestrator")
    assert entry is not None, "bead-orchestrator not found in library.yaml agents"
    assert "source" in entry, f"bead-orchestrator should use source:, found: {list(entry.keys())}"
    assert "sources" not in entry, "bead-orchestrator should not use dual sources"
    assert entry["source"].endswith("/agents/bead-orchestrator.md")
    print("PASS test_bead_orchestrator_uses_single_source")


def test_session_close_uses_single_source():
    """library.yaml session-close entry uses one Markdown source."""
    library = load_library()
    entry = _find_agent_entry(library, "session-close")
    assert entry is not None, "session-close not found in library.yaml agents"
    assert "source" in entry, f"session-close should use source:, found: {list(entry.keys())}"
    assert "sources" not in entry, "session-close should not use dual sources"
    assert entry["source"].endswith("/agents/session-close.md")
    print("PASS test_session_close_uses_single_source")


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
        xdg_data_home = Path(tmp) / "xdg"
        seed_open_brain_hooks_checkout(xdg_data_home)
        fake_codex_hooks = Path(tmp) / "codex-hooks.json"
        env = {
            **os.environ,
            "CODEX_HOOKS_FILE": str(fake_codex_hooks),
            "XDG_DATA_HOME": str(xdg_data_home),
        }

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
        assert "codex_session_summary.py" in combined, combined
        assert "${OPEN_BRAIN_PLUGIN_ROOT}" not in combined, combined
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
# AK5: Codex-specific OpenBrain manifest
# ---------------------------------------------------------------------------


def test_open_brain_codex_manifest_avoids_claude_only_events():
    """open-brain-hooks uses hooks.codex.json for Codex without Claude-only events."""
    with tempfile.TemporaryDirectory() as tmp:
        xdg_data_home = Path(tmp) / "xdg"
        seed_open_brain_hooks_checkout(xdg_data_home)
        fake_codex_hooks = Path(tmp) / "codex-hooks.json"
        env = {
            **os.environ,
            "CODEX_HOOKS_FILE": str(fake_codex_hooks),
            "XDG_DATA_HOME": str(xdg_data_home),
        }

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
        assert result.returncode == 0, combined
        assert "SessionStart" in combined, combined
        assert "Stop" in combined, combined
        assert "SubagentStop" not in combined, combined
        assert "mismatch_warning" not in combined, combined
    print("PASS test_open_brain_codex_manifest_avoids_claude_only_events")


# ---------------------------------------------------------------------------
# CL-gi5x: Codex hook installs are origin-idempotent
# ---------------------------------------------------------------------------


def test_merge_codex_hooks_replaces_same_origin_with_new_command():
    """Reinstalling a Codex hook manifest replaces stale same-origin commands."""
    install_hook = load_install_hook_module()
    existing = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /old-cache/hooks/scripts/context_inject.py --harness codex",
                            "timeout": 10,
                            "_origin": "library:hook:open-brain-hooks",
                        }
                    ],
                }
            ]
        }
    }
    manifest = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /new-cache/hooks/scripts/context_inject.py --harness codex",
                            "timeout": 10,
                        }
                    ],
                }
            ]
        }
    }

    merged = install_hook.merge_codex_hooks(existing, manifest, "open-brain-hooks")
    hooks = [
        hook
        for group in merged["hooks"]["SessionStart"]
        for hook in group.get("hooks", [])
        if hook.get("_origin") == "library:hook:open-brain-hooks"
    ]

    assert len(hooks) == 1, merged
    assert hooks[0]["command"] == "python3 /new-cache/hooks/scripts/context_inject.py --harness codex"
    assert "/old-cache/" not in json.dumps(merged), merged
    print("PASS test_merge_codex_hooks_replaces_same_origin_with_new_command")


def test_merge_codex_hooks_collapses_duplicate_same_origin_entries():
    """Existing duplicate same-origin Codex hooks collapse to the manifest hook."""
    install_hook = load_install_hook_module()
    existing = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /cache-a/hooks/scripts/context_inject.py --harness codex",
                            "_origin": "library:hook:open-brain-hooks",
                        }
                    ],
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /cache-b/hooks/scripts/context_inject.py --harness codex",
                            "_origin": "library:hook:open-brain-hooks",
                        }
                    ],
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "bash /Users/malte/.codex/herdr-agent-state.sh session",
                        }
                    ],
                },
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /cache-a/hooks/scripts/codex_session_summary.py",
                            "_origin": "library:hook:open-brain-hooks",
                        }
                    ],
                }
            ],
        }
    }
    manifest = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /current/hooks/scripts/context_inject.py --harness codex",
                            "timeout": 10,
                        }
                    ],
                }
            ]
        }
    }

    merged = install_hook.merge_codex_hooks(existing, manifest, "open-brain-hooks")
    serialized = json.dumps(merged)
    open_brain_hooks = [
        hook
        for groups in merged["hooks"].values()
        for group in groups
        for hook in group.get("hooks", [])
        if hook.get("_origin") == "library:hook:open-brain-hooks"
    ]

    assert len(open_brain_hooks) == 1, merged
    assert open_brain_hooks[0]["command"] == "python3 /current/hooks/scripts/context_inject.py --harness codex"
    assert "herdr-agent-state.sh" in serialized, merged
    assert "/cache-a/" not in serialized, merged
    assert "/cache-b/" not in serialized, merged
    print("PASS test_merge_codex_hooks_collapses_duplicate_same_origin_entries")


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
        test_bead_orchestrator_uses_single_source,
        test_session_close_uses_single_source,
        test_wave_orchestrator_uses_single_source,
        test_library_yaml_still_valid_after_sources_migration,
        test_install_hook_accepts_harness_flag,
        test_install_hook_codex_dry_run_shows_sessionstart,
        test_install_hook_codex_single_hook_uses_current_schema,
        test_open_brain_codex_manifest_avoids_claude_only_events,
        test_merge_codex_hooks_replaces_same_origin_with_new_command,
        test_merge_codex_hooks_collapses_duplicate_same_origin_entries,
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
