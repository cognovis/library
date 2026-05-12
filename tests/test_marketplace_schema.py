#!/usr/bin/env python3
"""
test_marketplace_schema.py — Tests for marketplace_entry schema in library.yaml

Bead: CL-r92
Tests:
  1. library.yaml passes validation after migration (all entries have type: git)
  2. Valid marketplace_entry with type: git
  3. Valid marketplace_entry with type: git and auth: bearer
  4. marketplace_entry without type is rejected
  5. marketplace_entry with invalid type value is rejected
  6. marketplace_entry with invalid auth value is rejected
  7. marketplace_entry with type: skills-sh is accepted
  8. marketplace_entry with type: http-tarball and auth: basic is accepted

Run with:
    python3 -m pytest tests/test_marketplace_schema.py -v
  or:
    python3 tests/test_marketplace_schema.py
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
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_TYPE_GIT = {
    "name": "example-marketplace",
    "source": "https://github.com/example",
    "description": "An example marketplace",
    "type": "git",
}

FIXTURE_TYPE_GIT_AUTH_BEARER = {
    "name": "private-marketplace",
    "source": "https://github.com/private-org",
    "description": "A private marketplace requiring bearer auth",
    "type": "git",
    "auth": "bearer",
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_library_yaml_passes_validator():
    """The current library.yaml (including migrated marketplaces) must pass the validator."""
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    assert_valid(data, schema, "library.yaml on disk")
    print("PASS test_library_yaml_passes_validator")


def test_marketplace_entry_with_type_git():
    """Valid marketplace_entry with type: git is accepted."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [FIXTURE_TYPE_GIT]
    })
    assert_valid(data, schema, "marketplace_entry with type=git")
    print("PASS test_marketplace_entry_with_type_git")


def test_marketplace_entry_with_type_git_and_auth_bearer():
    """Valid marketplace_entry with type: git and auth: bearer is accepted."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [FIXTURE_TYPE_GIT_AUTH_BEARER]
    })
    assert_valid(data, schema, "marketplace_entry with type=git + auth=bearer")
    print("PASS test_marketplace_entry_with_type_git_and_auth_bearer")


def test_marketplace_entry_without_type_is_rejected():
    """marketplace_entry without type field is rejected."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [
            {
                "name": "no-type-marketplace",
                "source": "https://github.com/example",
                "description": "Missing required type field",
            }
        ]
    })
    assert_invalid(data, schema, "marketplace_entry missing type")
    print("PASS test_marketplace_entry_without_type_is_rejected")


def test_marketplace_entry_with_invalid_type_is_rejected():
    """marketplace_entry with an invalid type value is rejected."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [
            {
                "name": "bad-type-marketplace",
                "source": "https://github.com/example",
                "description": "Invalid type value",
                "type": "npm-registry",
            }
        ]
    })
    assert_invalid(data, schema, "marketplace_entry with type=npm-registry")
    print("PASS test_marketplace_entry_with_invalid_type_is_rejected")


def test_marketplace_entry_with_invalid_auth_is_rejected():
    """marketplace_entry with an invalid auth value is rejected."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [
            {
                "name": "bad-auth-marketplace",
                "source": "https://github.com/example",
                "description": "Invalid auth value",
                "type": "git",
                "auth": "api-key",
            }
        ]
    })
    assert_invalid(data, schema, "marketplace_entry with auth=api-key")
    print("PASS test_marketplace_entry_with_invalid_auth_is_rejected")


def test_marketplace_entry_with_type_skills_sh():
    """marketplace_entry with type: skills-sh is accepted."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [
            {
                "name": "skills-sh-marketplace",
                "source": "https://github.com/example",
                "description": "A skills.sh based marketplace",
                "type": "skills-sh",
            }
        ]
    })
    assert_valid(data, schema, "marketplace_entry with type=skills-sh")
    print("PASS test_marketplace_entry_with_type_skills_sh")


def test_marketplace_entry_with_type_http_tarball_and_auth_basic():
    """marketplace_entry with type: http-tarball and auth: basic is accepted."""
    schema = load_schema()
    data = minimal_library({
        "marketplaces": [
            {
                "name": "tarball-marketplace",
                "source": "https://github.com/example",
                "description": "A tarball-distributed marketplace with basic auth",
                "type": "http-tarball",
                "auth": "basic",
            }
        ]
    })
    assert_valid(data, schema, "marketplace_entry with type=http-tarball + auth=basic")
    print("PASS test_marketplace_entry_with_type_http_tarball_and_auth_basic")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_library_yaml_passes_validator,
    test_marketplace_entry_with_type_git,
    test_marketplace_entry_with_type_git_and_auth_bearer,
    test_marketplace_entry_without_type_is_rejected,
    test_marketplace_entry_with_invalid_type_is_rejected,
    test_marketplace_entry_with_invalid_auth_is_rejected,
    test_marketplace_entry_with_type_skills_sh,
    test_marketplace_entry_with_type_http_tarball_and_auth_basic,
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
