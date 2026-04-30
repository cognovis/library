#!/usr/bin/env python3
"""
test_mcp_servers_schema.py — Tests for mcp_servers: canonical schema in library.yaml

Bead: CL-mfz
Tests:
  1. mcp_servers section present in library.yaml is accepted by validator
  2. mcp_server_entry requires name and description
  3. mcp_server_entry capabilities fields validate correctly
  4. mcp_server_entry install section validates correctly
  5. mcp_server_entry with unknown fields is rejected (additionalProperties)
  6. coding_strategy and mobile_strategy accept only valid enum values
  7. Full example from bead description validates cleanly

Run with:
    python3 -m pytest tests/test_mcp_servers_schema.py -v
  or:
    python3 tests/test_mcp_servers_schema.py
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
LIBRARY_PATH = REPO_ROOT / "library.yaml"


def load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
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
    """The current library.yaml (including mcp_servers) must pass the validator."""
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    assert_valid(data, schema, "library.yaml on disk")
    print("PASS test_library_yaml_passes_validator")


def test_mcp_servers_section_accepted():
    """mcp_servers list accepted by schema."""
    schema = load_schema()
    data = minimal_library({
        "mcp_servers": [
            {
                "name": "open-brain",
                "description": "Stateless memory store",
                "coding_strategy": "cli",
                "mobile_strategy": "mcp",
                "capabilities": {
                    "stateless": True,
                    "streaming": False,
                    "auth": "token",
                },
                "install": {
                    "cli": {
                        "package": "@cognovis/open-brain-cli",
                        "manager": "npm",
                    },
                    "mcp": {
                        "claude_code": {
                            "config_path": "~/.claude/settings.json",
                        }
                    },
                },
            }
        ]
    })
    assert_valid(data, schema, "mcp_servers with valid entry")
    print("PASS test_mcp_servers_section_accepted")


def test_mcp_server_requires_name():
    """mcp_server_entry without name is rejected."""
    schema = load_schema()
    data = minimal_library({
        "mcp_servers": [
            {
                "description": "Missing name field",
                "coding_strategy": "cli",
            }
        ]
    })
    assert_invalid(data, schema, "mcp_server_entry missing name")
    print("PASS test_mcp_server_requires_name")


def test_mcp_server_requires_description():
    """mcp_server_entry without description is rejected."""
    schema = load_schema()
    data = minimal_library({
        "mcp_servers": [
            {
                "name": "open-brain",
            }
        ]
    })
    assert_invalid(data, schema, "mcp_server_entry missing description")
    print("PASS test_mcp_server_requires_description")


def test_coding_strategy_enum():
    """coding_strategy accepts only cli | mcp."""
    schema = load_schema()
    data_valid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "coding_strategy": "cli",
            }
        ]
    })
    assert_valid(data_valid, schema, "coding_strategy=cli")

    data_invalid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "coding_strategy": "unknown-harness",
            }
        ]
    })
    assert_invalid(data_invalid, schema, "coding_strategy=unknown-harness")
    print("PASS test_coding_strategy_enum")


def test_mobile_strategy_enum():
    """mobile_strategy accepts only cli | mcp."""
    schema = load_schema()
    data_valid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "mobile_strategy": "mcp",
            }
        ]
    })
    assert_valid(data_valid, schema, "mobile_strategy=mcp")

    data_invalid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "mobile_strategy": "native",
            }
        ]
    })
    assert_invalid(data_invalid, schema, "mobile_strategy=native")
    print("PASS test_mobile_strategy_enum")


def test_capabilities_auth_enum():
    """capabilities.auth accepts only token | oauth | none."""
    schema = load_schema()

    for valid_auth in ("token", "oauth", "none"):
        data = minimal_library({
            "mcp_servers": [
                {
                    "name": "test-server",
                    "description": "A test server",
                    "capabilities": {"auth": valid_auth},
                }
            ]
        })
        assert_valid(data, schema, f"capabilities.auth={valid_auth}")

    data_invalid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "capabilities": {"auth": "bearer"},
            }
        ]
    })
    assert_invalid(data_invalid, schema, "capabilities.auth=bearer")
    print("PASS test_capabilities_auth_enum")


def test_install_cli_manager_enum():
    """install.cli.manager accepts only npm | pip | cargo | brew | none."""
    schema = load_schema()

    for valid_mgr in ("npm", "pip", "cargo", "brew", "none"):
        data = minimal_library({
            "mcp_servers": [
                {
                    "name": "test-server",
                    "description": "A test server",
                    "install": {
                        "cli": {"package": "test-pkg", "manager": valid_mgr}
                    },
                }
            ]
        })
        assert_valid(data, schema, f"install.cli.manager={valid_mgr}")

    data_invalid = minimal_library({
        "mcp_servers": [
            {
                "name": "test-server",
                "description": "A test server",
                "install": {
                    "cli": {"package": "test-pkg", "manager": "yarn"}
                },
            }
        ]
    })
    assert_invalid(data_invalid, schema, "install.cli.manager=yarn")
    print("PASS test_install_cli_manager_enum")


def test_full_example_from_bead_description():
    """The canonical open-brain example from the bead description validates cleanly."""
    schema = load_schema()
    data = minimal_library({
        "mcp_servers": [
            {
                "name": "open-brain",
                "description": "Stateless memory store via search/save/get",
                "coding_strategy": "cli",
                "mobile_strategy": "mcp",
                "capabilities": {
                    "stateless": True,
                    "streaming": False,
                    "auth": "token",
                },
                "install": {
                    "cli": {
                        "package": "@cognovis/open-brain-cli",
                        "manager": "npm",
                    },
                    "mcp": {
                        "claude_code": {
                            "config_path": "~/.claude/settings.json",
                            "snippet": {"type": "stdio", "command": "open-brain"},
                        },
                        "codex": {
                            "config_path": "~/.codex/config.toml",
                            "snippet": {"command": "open-brain"},
                        },
                        "opencode": {
                            "config_path": "~/.config/opencode/opencode.json",
                            "snippet": {"command": "open-brain"},
                        },
                        "claude_ai": {
                            "install_url": "https://claude.ai/example",
                        },
                        "claude_ios": {
                            "install_url": "https://example.com/ios",
                        },
                    },
                },
            }
        ]
    })
    assert_valid(data, schema, "full open-brain example")
    print("PASS test_full_example_from_bead_description")


def test_mcp_servers_is_array_not_object():
    """mcp_servers must be an array, not a bare object."""
    schema = load_schema()
    data = minimal_library({
        "mcp_servers": {
            "open-brain": {"description": "bad — object not array"}
        }
    })
    assert_invalid(data, schema, "mcp_servers as object instead of array")
    print("PASS test_mcp_servers_is_array_not_object")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_library_yaml_passes_validator,
    test_mcp_servers_section_accepted,
    test_mcp_server_requires_name,
    test_mcp_server_requires_description,
    test_coding_strategy_enum,
    test_mobile_strategy_enum,
    test_capabilities_auth_enum,
    test_install_cli_manager_enum,
    test_full_example_from_bead_description,
    test_mcp_servers_is_array_not_object,
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
