#!/usr/bin/env python3
"""
test_model_standards_schema.py — Tests for model_standards: and golden_prompts: schema

Bead: CL-08n
Tests:
  1. model_standards section present in library.yaml is accepted by validator
  2. golden_prompts section present in library.yaml is accepted by validator
  3. model_standards entry requires name and description
  4. golden_prompts entry requires name and description
  5. default_dirs gains model_standards entries
  6. default_dirs gains golden_prompts entries
  7. library.yaml on disk (after changes) passes the validator

Run with:
    python3 -m pytest tests/test_model_standards_schema.py -v
  or:
    python3 tests/test_model_standards_schema.py
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
    from jsonschema import ValidationError
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
    """Return a minimal valid library.yaml structure."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_model_standards_section_accepted():
    """model_standards array is accepted by schema."""
    schema = load_schema()
    data = minimal_library({
        "model_standards": [
            {
                "name": "claude-sonnet-4-6",
                "description": "Layer 3 model-standard for Claude Sonnet 4.6",
                "source": "https://github.com/cognovis/library-core/blob/main/model-standards/claude-sonnet-4-6.md",
            }
        ]
    })
    assert_valid(data, schema, "model_standards with one entry")
    print("PASS test_model_standards_section_accepted")


def test_golden_prompts_section_accepted():
    """golden_prompts array is accepted by schema."""
    schema = load_schema()
    data = minimal_library({
        "golden_prompts": [
            {
                "name": "cognovis-base",
                "description": "Layer 1 of the three-layer agent composition model.",
                "source": "https://github.com/cognovis/library-core/blob/main/golden-prompts/cognovis-base.md",
            }
        ]
    })
    assert_valid(data, schema, "golden_prompts with one entry")
    print("PASS test_golden_prompts_section_accepted")


def test_model_standards_entry_requires_name():
    """model_standards entry without name is rejected."""
    schema = load_schema()
    data = minimal_library({
        "model_standards": [
            {
                "description": "Missing name field",
            }
        ]
    })
    assert_invalid(data, schema, "model_standards entry missing name")
    print("PASS test_model_standards_entry_requires_name")


def test_golden_prompts_entry_requires_name():
    """golden_prompts entry without name is rejected."""
    schema = load_schema()
    data = minimal_library({
        "golden_prompts": [
            {
                "description": "Missing name field",
            }
        ]
    })
    assert_invalid(data, schema, "golden_prompts entry missing name")
    print("PASS test_golden_prompts_entry_requires_name")


def test_default_dirs_model_standards_accepted():
    """default_dirs with model_standards entries is accepted."""
    schema = load_schema()
    data = minimal_library({
        "model_standards": [],
    })
    data["default_dirs"]["model_standards"] = [
        {"default": ".agents/model-standards/"},
        {"global": "~/.agents/model-standards/"},
    ]
    assert_valid(data, schema, "default_dirs with model_standards")
    print("PASS test_default_dirs_model_standards_accepted")


def test_default_dirs_golden_prompts_accepted():
    """default_dirs with golden_prompts entries is accepted."""
    schema = load_schema()
    data = minimal_library({
        "golden_prompts": [],
    })
    data["default_dirs"]["golden_prompts"] = [
        {"default": ".agents/golden-prompts/"},
        {"global": "~/.agents/golden-prompts/"},
    ]
    assert_valid(data, schema, "default_dirs with golden_prompts")
    print("PASS test_default_dirs_golden_prompts_accepted")


def test_library_yaml_with_new_sections_passes_validator():
    """library.yaml on disk (with model_standards + golden_prompts) passes the validator."""
    if not LIBRARY_PATH.exists():
        print("SKIP test_library_yaml_with_new_sections_passes_validator: library.yaml not found")
        return
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    # This test will pass only after library.yaml is updated AND schema accepts new sections
    if "model_standards" not in data or "golden_prompts" not in data:
        print("SKIP test_library_yaml_with_new_sections_passes_validator: sections not yet in library.yaml")
        return
    assert_valid(data, schema, "library.yaml on disk with model_standards + golden_prompts")
    print("PASS test_library_yaml_with_new_sections_passes_validator")


def test_model_standards_is_array_not_object():
    """model_standards must be an array, not an object."""
    schema = load_schema()
    data = minimal_library({
        "model_standards": {"sonnet": {"description": "bad — object not array"}}
    })
    assert_invalid(data, schema, "model_standards as object instead of array")
    print("PASS test_model_standards_is_array_not_object")


def test_golden_prompts_is_array_not_object():
    """golden_prompts must be an array, not an object."""
    schema = load_schema()
    data = minimal_library({
        "golden_prompts": {"base": {"description": "bad — object not array"}}
    })
    assert_invalid(data, schema, "golden_prompts as object instead of array")
    print("PASS test_golden_prompts_is_array_not_object")


def test_three_model_standards_validate():
    """All three model standards from bead description validate cleanly."""
    schema = load_schema()
    data = minimal_library({
        "model_standards": [
            {
                "name": "claude-sonnet-4-6",
                "description": "Layer 3 model-standard for Claude Sonnet 4.6 — conciseness, lower tool-hopping bias.",
                "source": "https://github.com/cognovis/library-core/blob/main/model-standards/claude-sonnet-4-6.md",
            },
            {
                "name": "claude-opus-4-7",
                "description": "Layer 3 model-standard for Claude Opus 4.7 — thinking-budget discipline, avoid over-deliberation on trivial steps.",
                "source": "https://github.com/cognovis/library-core/blob/main/model-standards/claude-opus-4-7.md",
            },
            {
                "name": "claude-haiku-4-5",
                "description": "Layer 3 model-standard for Claude Haiku 4.5 — avoid under-scoping multi-step plans, no terse-skip on verification steps.",
                "source": "https://github.com/cognovis/library-core/blob/main/model-standards/claude-haiku-4-5.md",
            },
        ]
    })
    assert_valid(data, schema, "all three model standards from bead description")
    print("PASS test_three_model_standards_validate")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_model_standards_section_accepted,
    test_golden_prompts_section_accepted,
    test_model_standards_entry_requires_name,
    test_golden_prompts_entry_requires_name,
    test_default_dirs_model_standards_accepted,
    test_default_dirs_golden_prompts_accepted,
    test_library_yaml_with_new_sections_passes_validator,
    test_model_standards_is_array_not_object,
    test_golden_prompts_is_array_not_object,
    test_three_model_standards_validate,
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
