#!/usr/bin/env python3
"""
test_guardrails_schema.py — Tests for guardrails: canonical schema in library.yaml

Bead: CL-xcm
Tests:
  1. library.yaml with guardrails: section passes schema validator
  2. Minimal guardrail entry accepted
  3. guardrail_entry requires name
  4. guardrail_entry requires description
  5. guardrail_entry requires purpose
  6. purpose enum validates correctly
  7. capability section accepts all valid harness keys
  8. Unknown harness key in capability is rejected
  9. sources section accepts valid harness keys
  10. lockfile schema now accepts type: guardrail
  11. Full block-destructive-bash example validates cleanly

Run with:
    python3 -m pytest tests/test_guardrails_schema.py -v
  or:
    python3 tests/test_guardrails_schema.py
"""

import json
import sys
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LOCKFILE_SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "lockfile.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"


def load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def load_lockfile_schema() -> dict:
    with LOCKFILE_SCHEMA_PATH.open() as f:
        return json.load(f)


def minimal_library(extra: dict | None = None) -> dict:
    """Return a minimal valid library.yaml structure, optionally merged with extra keys."""
    base = {
        "default_dirs": {
            "skills": [{"default": ".claude/skills/"}],
        },
        "library": {
            "skills": [],
            "agents": [],
            "prompts": [],
        },
        "marketplaces": [],
    }
    if extra:
        base.update(extra)
    return base


def assert_valid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        msgs = "\n".join(f"  [{'/'.join(str(p) for p in e.absolute_path)}] {e.message}" for e in errors)
        raise AssertionError(f"Expected VALID for '{label}' but got errors:\n{msgs}")


def assert_invalid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if not errors:
        raise AssertionError(f"Expected INVALID for '{label}' but schema accepted it")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_library_yaml_passes_validator():
    """The current library.yaml (including guardrails:) must pass the validator."""
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    assert_valid(data, schema, "library.yaml on disk")
    print("PASS test_library_yaml_passes_validator")


def test_guardrails_section_accepted():
    """A minimal guardrail entry is accepted by schema."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
                "purpose": "pre-tool-veto",
            }
        ]
    })
    assert_valid(data, schema, "guardrails with minimal valid entry")
    print("PASS test_guardrails_section_accepted")


def test_guardrail_requires_name():
    """guardrail_entry without name is rejected."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "description": "Missing name field",
                "purpose": "pre-tool-veto",
            }
        ]
    })
    assert_invalid(data, schema, "guardrail_entry missing name")
    print("PASS test_guardrail_requires_name")


def test_guardrail_requires_description():
    """guardrail_entry without description is rejected."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "purpose": "pre-tool-veto",
            }
        ]
    })
    assert_invalid(data, schema, "guardrail_entry missing description")
    print("PASS test_guardrail_requires_description")


def test_guardrail_requires_purpose():
    """guardrail_entry without purpose is rejected."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
            }
        ]
    })
    assert_invalid(data, schema, "guardrail_entry missing purpose")
    print("PASS test_guardrail_requires_purpose")


def test_guardrail_purpose_enum():
    """purpose accepts only valid enum values."""
    schema = load_schema()

    for valid_purpose in ("pre-tool-veto", "post-tool-reaction", "session-init", "cleanup", "audit-log"):
        data = minimal_library({
            "guardrails": [
                {
                    "name": "my-guardrail",
                    "description": "A test guardrail",
                    "purpose": valid_purpose,
                }
            ]
        })
        assert_valid(data, schema, f"purpose={valid_purpose}")

    data_invalid = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
                "purpose": "block-everything",
            }
        ]
    })
    assert_invalid(data_invalid, schema, "purpose=block-everything (invalid)")
    print("PASS test_guardrail_purpose_enum")


def test_guardrail_capability_harnesses():
    """capability section accepts all valid harness keys."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
                "purpose": "pre-tool-veto",
                "capability": {
                    "claude_code": {"events": ["PreToolUse"], "handler": "bash-script"},
                    "codex_cli": {"events": ["SessionStart"], "handler": "node-mjs"},
                    "codex_cloud": {"mechanism": "approval_policy"},
                    "pi": {"events": ["tool_call"], "handler": "typescript-extension"},
                    "opencode": {"mechanism": "permission-rule"},
                },
            }
        ]
    })
    assert_valid(data, schema, "guardrail with all valid harness keys in capability")
    print("PASS test_guardrail_capability_harnesses")


def test_guardrail_unknown_harness_rejected():
    """Unknown harness key in capability is rejected."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
                "purpose": "pre-tool-veto",
                "capability": {
                    "unknown_harness": {"events": ["PreToolUse"]},
                },
            }
        ]
    })
    assert_invalid(data, schema, "guardrail with unknown harness key in capability")
    print("PASS test_guardrail_unknown_harness_rejected")


def test_guardrail_sources_section():
    """sources section accepts valid harness keys."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "my-guardrail",
                "description": "A test guardrail",
                "purpose": "pre-tool-veto",
                "sources": {
                    "claude_code": "guardrails/my-guardrail/claude-code.sh",
                    "codex_cli": "guardrails/my-guardrail/codex-cli.mjs",
                    "codex_cloud": "guardrails/my-guardrail/codex-cloud-fragment.toml",
                    "opencode": "guardrails/my-guardrail/opencode-fragment.json",
                },
            }
        ]
    })
    assert_valid(data, schema, "guardrail with valid sources section")
    print("PASS test_guardrail_sources_section")


def test_lockfile_type_includes_guardrail():
    """Lockfile schema now accepts type: guardrail."""
    schema = load_lockfile_schema()
    data = {
        "installed": [
            {
                "name": "block-destructive-bash",
                "type": "guardrail",
                "source": "guardrails/block-destructive-bash/claude-code.sh",
                "source_commit": "local",
                "install_target": ".claude/hooks/block-destructive-bash/",
                "install_timestamp": "2026-04-30T12:00:00Z",
                "checksum_sha256": "a" * 64,
                "license": "MIT",
                "bridge_symlinks": [],
            }
        ]
    }
    assert_valid(data, schema, "lockfile with guardrail type entry")
    print("PASS test_lockfile_type_includes_guardrail")


def test_full_example_validates():
    """The full block-destructive-bash example validates cleanly."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": [
            {
                "name": "block-destructive-bash",
                "description": "Blocks destructive bash commands that cannot be undone",
                "purpose": "pre-tool-veto",
                "capability": {
                    "claude_code": {
                        "events": ["PreToolUse"],
                        "handler": "bash-script",
                        "matcher": "Bash",
                    },
                    "codex_cli": {
                        "events": ["SessionStart"],
                        "handler": "node-mjs",
                        "note": "Codex CLI has no PreToolUse; inject blocking logic via SessionStart context",
                    },
                    "codex_cloud": {
                        "mechanism": "approval_policy",
                        "config_key": "approval_policy",
                        "value": "all",
                        "note": "No event-level veto; use blunt approval_policy=all or sandbox restrictions",
                    },
                    "opencode": {
                        "mechanism": "permission-rule",
                        "config_key": "rules",
                    },
                },
                "sources": {
                    "claude_code": "guardrails/block-destructive-bash/claude-code.sh",
                    "codex_cli": "guardrails/block-destructive-bash/codex-cli.mjs",
                    "codex_cloud": "guardrails/block-destructive-bash/codex-cloud-config-fragment.toml",
                    "opencode": "guardrails/block-destructive-bash/opencode-fragment.json",
                },
                "tags": ["security", "destructive-prevention"],
            }
        ]
    })
    assert_valid(data, schema, "full block-destructive-bash example")
    print("PASS test_full_example_validates")


def test_guardrails_is_array_not_object():
    """guardrails must be an array, not a bare object."""
    schema = load_schema()
    data = minimal_library({
        "guardrails": {
            "block-destructive-bash": {"description": "bad — object not array"}
        }
    })
    assert_invalid(data, schema, "guardrails as object instead of array")
    print("PASS test_guardrails_is_array_not_object")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_library_yaml_passes_validator,
    test_guardrails_section_accepted,
    test_guardrail_requires_name,
    test_guardrail_requires_description,
    test_guardrail_requires_purpose,
    test_guardrail_purpose_enum,
    test_guardrail_capability_harnesses,
    test_guardrail_unknown_harness_rejected,
    test_guardrail_sources_section,
    test_lockfile_type_includes_guardrail,
    test_full_example_validates,
    test_guardrails_is_array_not_object,
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
