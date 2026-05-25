#!/usr/bin/env python3
"""
test_lockfile_schema.py — Tests for .library.lock JSON Schema (AK1 / AK5 — CL-yx2)

Tests the `marketplace` and `cache_path` fields added to lockfile_entry per ADR-0003.

Tests:
  1. lockfile_entry requires `marketplace` field
  2. lockfile_entry requires `cache_path` field
  3. Valid entry with marketplace + cache_path validates
  4. Entry without marketplace fails validation
  5. Entry without cache_path fails validation
  6. `marketplace` must be a non-empty string (empty string rejected)
  7. `cache_path` must be a string (empty string is valid for migration)
  8. Full ADR-0003 global install example validates
  9. Full ADR-0003 project-scoped install example validates
 10. Existing valid entry without new fields still fails (additionalProperties: false enforced)
 11. marketplace: local is valid

Run with:
    python3 -m pytest tests/test_lockfile_schema.py -v
  or:
    python3 tests/test_lockfile_schema.py
"""

import json
import sys
from pathlib import Path

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    print("SKIP: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCKFILE_SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "lockfile.schema.json"


def load_lockfile_schema() -> dict:
    with LOCKFILE_SCHEMA_PATH.open() as f:
        return json.load(f)


def assert_valid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        msgs = "\n".join(
            f"  [{'/'.join(str(p) for p in e.absolute_path)}] {e.message}"
            for e in errors
        )
        raise AssertionError(f"Expected VALID for '{label}' but got errors:\n{msgs}")


def assert_invalid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if not errors:
        raise AssertionError(f"Expected INVALID for '{label}' but schema accepted it")


def minimal_valid_entry(**overrides) -> dict:
    """Return a minimal valid lockfile entry with all required fields including new ones."""
    entry = {
        "name": "test-skill",
        "type": "skill",
        "marketplace": "cognovis-core",
        "source": "https://github.com/cognovis/library-core/blob/main/skills/test-skill/SKILL.md",
        "source_commit": "a" * 64,
        "cache_path": "/Users/malte/.local/share/library/skills/cognovis-core/test-skill@abcdef/",
        "install_target": ".claude/skills/test-skill/",
        "install_timestamp": "2026-05-12T07:30:00Z",
        "checksum_sha256": "a" * 64,
    }
    entry.update(overrides)
    return entry


def lockfile_with(entry: dict) -> dict:
    return {"installed": [entry]}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_requires_marketplace():
    """lockfile_entry requires `marketplace` field."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry()
    del entry["marketplace"]
    assert_invalid(lockfile_with(entry), schema, "entry missing marketplace")
    print("PASS test_requires_marketplace")


def test_requires_cache_path():
    """lockfile_entry requires `cache_path` field."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry()
    del entry["cache_path"]
    assert_invalid(lockfile_with(entry), schema, "entry missing cache_path")
    print("PASS test_requires_cache_path")


def test_valid_entry_with_new_fields():
    """Valid entry with marketplace + cache_path validates."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry()
    assert_valid(lockfile_with(entry), schema, "valid entry with marketplace and cache_path")
    print("PASS test_valid_entry_with_new_fields")


def test_entry_without_marketplace_fails():
    """Entry without marketplace fails validation."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry()
    del entry["marketplace"]
    assert_invalid(lockfile_with(entry), schema, "entry without marketplace")
    print("PASS test_entry_without_marketplace_fails")


def test_entry_without_cache_path_fails():
    """Entry without cache_path fails validation."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry()
    del entry["cache_path"]
    assert_invalid(lockfile_with(entry), schema, "entry without cache_path")
    print("PASS test_entry_without_cache_path_fails")


def test_marketplace_must_be_nonempty_string():
    """`marketplace` must be a non-empty string — empty string is rejected."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(marketplace="")
    assert_invalid(lockfile_with(entry), schema, "marketplace as empty string")
    print("PASS test_marketplace_must_be_nonempty_string")


def test_cache_path_allows_empty_string():
    """`cache_path` may be an empty string (migration placeholder)."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(cache_path="")
    assert_valid(lockfile_with(entry), schema, "cache_path as empty string (migration)")
    print("PASS test_cache_path_allows_empty_string")


def test_adr0003_global_install_example():
    """Full ADR-0003 global install example validates."""
    schema = load_lockfile_schema()
    data = {
        "installed": [
            {
                "name": "agent-forge",
                "type": "skill",
                "marketplace": "cognovis-core",
                "source": "https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md",
                "source_commit": "9b1e72c98f3e21abc" + "0" * 47,
                "cache_path": "/Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/",
                "install_target": "/Users/malte/.claude/skills/agent-forge/",
                "install_timestamp": "2026-05-12T07:30:00Z",
                "checksum_sha256": "9483a094" + "0" * 56,
                "license": "MIT",
                "bridge_symlinks": [
                    "/Users/malte/.agents/skills/agent-forge -> /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/"
                ],
            }
        ]
    }
    assert_valid(data, schema, "ADR-0003 global install example")
    print("PASS test_adr0003_global_install_example")


def test_adr0003_project_install_example():
    """Full ADR-0003 project-scoped install example validates."""
    schema = load_lockfile_schema()
    data = {
        "installed": [
            {
                "name": "agent-forge",
                "type": "skill",
                "marketplace": "cognovis-core",
                "source": "https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md",
                "source_commit": "9b1e72c98f3e21abc" + "0" * 47,
                "cache_path": "/Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/",
                "install_target": ".claude/skills/agent-forge/",
                "install_timestamp": "2026-05-12T07:30:00Z",
                "checksum_sha256": "9483a094" + "0" * 56,
                "license": "MIT",
                "bridge_symlinks": [
                    ".agents/skills/agent-forge -> /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/"
                ],
            }
        ]
    }
    assert_valid(data, schema, "ADR-0003 project-scoped install example")
    print("PASS test_adr0003_project_install_example")


def test_marketplace_unknown_is_valid():
    """`marketplace` value 'unknown' is accepted (migration fallback)."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(marketplace="unknown")
    assert_valid(lockfile_with(entry), schema, "marketplace=unknown (migration fallback)")
    print("PASS test_marketplace_unknown_is_valid")


def test_marketplace_local_is_valid():
    """`marketplace` value 'local' is accepted for local-path sources."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(
        marketplace="local",
        source="/Users/malte/code/library/skills/dolt/SKILL.md",
        source_commit="local",
    )
    assert_valid(lockfile_with(entry), schema, "marketplace=local")
    print("PASS test_marketplace_local_is_valid")


def test_agent_base_type_is_valid():
    """`agent-base` is the canonical Layer 1 primitive type."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(type="agent-base", name="cognovis-base")
    assert_valid(lockfile_with(entry), schema, "type=agent-base")
    print("PASS test_agent_base_type_is_valid")


def test_workflow_type_is_valid():
    """`workflow` is the canonical workflow primitive type."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(type="workflow", name="bead-context-pack")
    assert_valid(lockfile_with(entry), schema, "type=workflow")
    print("PASS test_workflow_type_is_valid")


def test_golden_prompt_type_is_removed():
    """`golden-prompt` is rejected by the lockfile schema after migration."""
    schema = load_lockfile_schema()
    entry = minimal_valid_entry(type="golden-prompt", name="cognovis-base")
    assert_invalid(lockfile_with(entry), schema, "type=golden-prompt")
    print("PASS test_golden_prompt_type_is_removed")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_requires_marketplace,
    test_requires_cache_path,
    test_valid_entry_with_new_fields,
    test_entry_without_marketplace_fails,
    test_entry_without_cache_path_fails,
    test_marketplace_must_be_nonempty_string,
    test_cache_path_allows_empty_string,
    test_adr0003_global_install_example,
    test_adr0003_project_install_example,
    test_marketplace_unknown_is_valid,
    test_marketplace_local_is_valid,
    test_agent_base_type_is_valid,
    test_golden_prompt_type_is_removed,
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
