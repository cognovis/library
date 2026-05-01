#!/usr/bin/env python3
"""
test_list_cookbook.py — Tests for cookbook/list.md 3-section layout (CL-2x4)

Bead: CL-2x4
Tests:
  1. cookbook/list.md contains a Section 1 (Catalog) header
  2. cookbook/list.md contains a Section 2 (Plugin-Marketplace Installs) header
  3. cookbook/list.md contains a Section 3 (/library use Installs) header
  4. cookbook/list.md describes how to read installed_plugins.json
  5. cookbook/list.md describes annotation logic for catalog entries
  6. cookbook/list.md describes how to handle missing installed_plugins.json
  7. cookbook/list.md describes how to handle missing .library.lock
  8. installed_plugins.json parser logic: fixture data parses to correct tuples
  9. Annotation logic: a catalog entry whose name matches a plugin gets annotated

Run with:
    python3 -m pytest tests/test_list_cookbook.py -v
  or:
    python3 tests/test_list_cookbook.py
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIST_COOKBOOK = REPO_ROOT / "cookbook" / "list.md"

# ---------------------------------------------------------------------------
# Fixture data (small subset of real installed_plugins.json)
# ---------------------------------------------------------------------------

FIXTURE_PLUGINS_JSON = {
    "version": 2,
    "plugins": {
        "beads@beads-marketplace": [
            {
                "scope": "user",
                "installPath": "/Users/malte/.claude/plugins/cache/beads-marketplace/beads/1.0.3",
                "version": "1.0.3",
                "installedAt": "2026-01-28T13:24:11.767Z",
                "lastUpdated": "2026-04-25T05:24:23.360Z",
                "gitCommitSha": "2e6789d450784ef5e1290db22c627bb16dae0383",
            }
        ],
        "code-simplifier@claude-plugins-official": [
            {
                "scope": "project",
                "projectPath": "/Users/malte/code/swamp",
                "installPath": "/Users/malte/.claude/plugins/cache/claude-plugins-official/code-simplifier/1.0.0",
                "version": "1.0.0",
                "installedAt": "2026-02-15T07:12:21.651Z",
                "lastUpdated": "2026-02-15T07:12:21.651Z",
                "gitCommitSha": "2cd88e7947b7382e045666abee790c7f55f669f3",
            }
        ],
        "open-brain@open-brain-marketplace": [
            {
                "scope": "user",
                "installPath": "/Users/malte/.claude/plugins/cache/open-brain-marketplace/open-brain/0.22.1",
                "version": "0.22.1",
                "installedAt": "2026-04-11T11:25:14.571Z",
                "lastUpdated": "2026-04-25T12:32:02.008Z",
                "gitCommitSha": "e69c64e3c0d404a3db0574c1dff7d9b84e7b1120",
            }
        ],
    },
}

# ---------------------------------------------------------------------------
# Helper: parse installed_plugins.json into list of (name, marketplace, version, scope) tuples
# This mirrors the logic the cookbook instructs the AI to perform.
# ---------------------------------------------------------------------------


def parse_installed_plugins(data: dict) -> list:
    """
    Given a parsed installed_plugins.json dict (version 2 format), return a list of
    dicts with keys: name, marketplace, version, scope, project_path (optional).
    """
    results = []
    plugins = data.get("plugins", {})
    for key, entries in plugins.items():
        # key format: "name@marketplace"
        if "@" in key:
            name, marketplace = key.rsplit("@", 1)
        else:
            name, marketplace = key, "unknown"
        for entry in entries:
            record = {
                "name": name,
                "marketplace": marketplace,
                "version": entry.get("version", "unknown"),
                "scope": entry.get("scope", "user"),
            }
            if entry.get("scope") == "project":
                record["project_path"] = entry.get("projectPath", "")
            results.append(record)
    return results


# ---------------------------------------------------------------------------
# Helper: annotation logic
# ---------------------------------------------------------------------------


def annotate_catalog_entry(catalog_name: str, installed_plugin_names: set) -> bool:
    """
    Returns True if the catalog entry name appears in the installed plugin names,
    indicating it should be annotated with [also: plugin-marketplace].
    """
    return catalog_name in installed_plugin_names


# ---------------------------------------------------------------------------
# Tests: cookbook structure
# ---------------------------------------------------------------------------


def test_cookbook_has_catalog_section():
    """cookbook/list.md must contain a Section 1 Catalog header."""
    text = LIST_COOKBOOK.read_text()
    assert "Section 1" in text and "Catalog" in text, (
        "Expected 'Section 1' and 'Catalog' in cookbook/list.md — not found. "
        "Update the cookbook to add 3-section layout."
    )
    print("PASS test_cookbook_has_catalog_section")


def test_cookbook_has_plugin_marketplace_section():
    """cookbook/list.md must describe a Plugin-Marketplace Installs section."""
    text = LIST_COOKBOOK.read_text()
    assert "Plugin-Marketplace" in text or "Plugin-marketplace" in text or "plugin-marketplace" in text, (
        "Expected a Plugin-Marketplace Installs section in cookbook/list.md — not found."
    )
    print("PASS test_cookbook_has_plugin_marketplace_section")


def test_cookbook_has_lockfile_section():
    """cookbook/list.md must describe a /library use Installs (lockfile) section."""
    text = LIST_COOKBOOK.read_text()
    assert ".library.lock" in text, (
        "Expected '.library.lock' reference in cookbook/list.md — not found. "
        "Add a Section 3 for lockfile-based installs."
    )
    print("PASS test_cookbook_has_lockfile_section")


def test_cookbook_references_installed_plugins_json():
    """cookbook/list.md must reference installed_plugins.json."""
    text = LIST_COOKBOOK.read_text()
    assert "installed_plugins.json" in text, (
        "Expected 'installed_plugins.json' reference in cookbook/list.md — not found."
    )
    print("PASS test_cookbook_references_installed_plugins_json")


def test_cookbook_has_annotation_logic():
    """cookbook/list.md must describe annotation logic for catalog entries."""
    text = LIST_COOKBOOK.read_text()
    assert "also: plugin-marketplace" in text or "[also:" in text, (
        "Expected annotation marker '[also: plugin-marketplace]' logic in cookbook/list.md — not found."
    )
    print("PASS test_cookbook_has_annotation_logic")


def test_cookbook_handles_missing_plugins_json():
    """cookbook/list.md must describe graceful handling of missing installed_plugins.json."""
    text = LIST_COOKBOOK.read_text()
    # Either explicit mention of missing file handling or a graceful fallback note
    assert "missing" in text.lower() or "not found" in text.lower() or "gracefully" in text.lower(), (
        "Expected cookbook/list.md to describe handling of missing installed_plugins.json."
    )
    print("PASS test_cookbook_handles_missing_plugins_json")


def test_cookbook_handles_missing_lockfile():
    """cookbook/list.md must describe graceful handling of missing .library.lock."""
    text = LIST_COOKBOOK.read_text()
    assert "No /library use installs found" in text or "no .library.lock" in text.lower() or (
        ".library.lock" in text and ("missing" in text.lower() or "not found" in text.lower())
    ), (
        "Expected cookbook/list.md to describe handling of missing .library.lock file."
    )
    print("PASS test_cookbook_handles_missing_lockfile")


# ---------------------------------------------------------------------------
# Tests: parsing logic (verifying the cookbook's described algorithm)
# ---------------------------------------------------------------------------


def test_parse_installed_plugins_count():
    """Fixture data with 3 plugins parses to 3 records."""
    results = parse_installed_plugins(FIXTURE_PLUGINS_JSON)
    assert len(results) == 3, f"Expected 3 records, got {len(results)}: {results}"
    print("PASS test_parse_installed_plugins_count")


def test_parse_installed_plugins_user_scope():
    """User-scoped plugin parses correctly."""
    results = parse_installed_plugins(FIXTURE_PLUGINS_JSON)
    beads = next((r for r in results if r["name"] == "beads"), None)
    assert beads is not None, "Expected 'beads' plugin in results"
    assert beads["marketplace"] == "beads-marketplace"
    assert beads["version"] == "1.0.3"
    assert beads["scope"] == "user"
    assert "project_path" not in beads
    print("PASS test_parse_installed_plugins_user_scope")


def test_parse_installed_plugins_project_scope():
    """Project-scoped plugin parses correctly and includes project_path."""
    results = parse_installed_plugins(FIXTURE_PLUGINS_JSON)
    simplifier = next((r for r in results if r["name"] == "code-simplifier"), None)
    assert simplifier is not None, "Expected 'code-simplifier' plugin in results"
    assert simplifier["marketplace"] == "claude-plugins-official"
    assert simplifier["version"] == "1.0.0"
    assert simplifier["scope"] == "project"
    assert simplifier.get("project_path") == "/Users/malte/code/swamp"
    print("PASS test_parse_installed_plugins_project_scope")


def test_parse_installed_plugins_names():
    """All three fixture plugins are present with correct names."""
    results = parse_installed_plugins(FIXTURE_PLUGINS_JSON)
    names = {r["name"] for r in results}
    assert names == {"beads", "code-simplifier", "open-brain"}, (
        f"Expected plugin names {{beads, code-simplifier, open-brain}}, got {names}"
    )
    print("PASS test_parse_installed_plugins_names")


def test_annotation_match():
    """A catalog entry whose name is in the installed plugin set gets annotated."""
    installed_names = {"beads", "code-simplifier", "open-brain"}
    assert annotate_catalog_entry("beads", installed_names) is True
    assert annotate_catalog_entry("open-brain", installed_names) is True
    print("PASS test_annotation_match")


def test_annotation_no_match():
    """A catalog entry not in the installed plugin set is NOT annotated."""
    installed_names = {"beads", "code-simplifier", "open-brain"}
    assert annotate_catalog_entry("impeccable", installed_names) is False
    assert annotate_catalog_entry("dolt", installed_names) is False
    print("PASS test_annotation_no_match")


def test_parse_full_installed_plugins_json():
    """Parse the real installed_plugins.json (if present) and verify 16 plugins."""
    real_path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not real_path.exists():
        pytest.skip("installed_plugins.json not found")
    with real_path.open() as f:
        data = json.load(f)
    results = parse_installed_plugins(data)
    assert len(results) == 16, (
        f"Expected 16 plugins in installed_plugins.json, got {len(results)}: "
        f"{[r['name'] for r in results]}"
    )
    print(f"PASS test_parse_full_installed_plugins_json ({len(results)} plugins)")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_cookbook_has_catalog_section,
    test_cookbook_has_plugin_marketplace_section,
    test_cookbook_has_lockfile_section,
    test_cookbook_references_installed_plugins_json,
    test_cookbook_has_annotation_logic,
    test_cookbook_handles_missing_plugins_json,
    test_cookbook_handles_missing_lockfile,
    test_parse_installed_plugins_count,
    test_parse_installed_plugins_user_scope,
    test_parse_installed_plugins_project_scope,
    test_parse_installed_plugins_names,
    test_annotation_match,
    test_annotation_no_match,
    test_parse_full_installed_plugins_json,
]


def main() -> int:
    pass_count = 0
    fail_count = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            pass_count += 1
        except AssertionError as e:
            print(f"FAIL {test_fn.__name__}: {e}")
            fail_count += 1
        except Exception as e:
            print(f"ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            fail_count += 1

    print(f"\n{pass_count} passed, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
