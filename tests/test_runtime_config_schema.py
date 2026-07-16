#!/usr/bin/env python3
"""
test_runtime_config_schema.py — Schema tests for the runtime_configs section.

Bead: CL-7ipt
Covers:
  1. library.runtime_configs array is accepted by the validator
  2. runtime_config entry requires name, description, and base
  3. global_overlay and deploy_filename are optional
  4. runtime_configs must be an array (not an object)
  5. default_dirs.runtime_configs is accepted
  6. library.yaml on disk validates with the runtime_configs section present
  7. runtime-config is a registered primitive with the expected yaml_key
"""

import json
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def minimal_library(extra: dict | None = None) -> dict:
    base = {
        "default_dirs": {"skills": [{"default": ".claude/skills/"}]},
        "library": {"skills": [], "agents": [], "prompts": []},
    }
    if extra:
        if "library" in extra and isinstance(extra["library"], dict):
            base["library"].update(extra["library"])
            extra = {k: v for k, v in extra.items() if k != "library"}
        base.update(extra)
    return base


def assert_valid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        msgs = "\n".join(
            f"  [{'/'.join(str(p) for p in e.absolute_path)}] {e.message}" for e in errors
        )
        raise AssertionError(f"Expected VALID for '{label}' but got errors:\n{msgs}")


def assert_invalid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    if not list(validator.iter_errors(data)):
        raise AssertionError(f"Expected INVALID for '{label}' but schema accepted it")


def _entry(**over) -> dict:
    entry = {
        "name": "orchestrator-config",
        "description": "Composed global orchestrator-config.",
        "base": "https://github.com/cognovis/library-core/blob/main/runtime-configs/orchestrator-config.base.yml",
    }
    entry.update(over)
    return entry


def test_runtime_configs_section_accepted():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": [_entry(
        global_overlay="https://github.com/cognovis/library-core/blob/main/runtime-configs/orchestrator-config.global-overlay.yml",
        deploy_filename="orchestrator-config.yml",
    )]}})
    assert_valid(data, schema, "runtime_configs with one entry")


def test_runtime_config_optional_fields():
    schema = load_schema()
    # base only — global_overlay/deploy_filename omitted
    data = minimal_library({"library": {"runtime_configs": [_entry()]}})
    assert_valid(data, schema, "runtime_config base only")


def test_runtime_config_requires_name():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": [
        {"description": "no name", "base": "x"}
    ]}})
    assert_invalid(data, schema, "runtime_config missing name")


def test_runtime_config_requires_base():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": [
        {"name": "orchestrator-config", "description": "no base"}
    ]}})
    assert_invalid(data, schema, "runtime_config missing base")


def test_runtime_config_rejects_unknown_field():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": [_entry(bogus="x")]}})
    assert_invalid(data, schema, "runtime_config with unknown field")


def test_runtime_configs_is_array_not_object():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": {"orchestrator-config": {}}}})
    assert_invalid(data, schema, "runtime_configs as object")


def test_default_dirs_runtime_configs_accepted():
    schema = load_schema()
    data = minimal_library({"library": {"runtime_configs": []}})
    data["default_dirs"]["runtime_configs"] = [
        {"default": ".agents/"},
        {"global": "~/.agents/"},
    ]
    assert_valid(data, schema, "default_dirs with runtime_configs")


def test_library_yaml_on_disk_validates():
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    assert "runtime_configs" in (data.get("library") or {}), "library.yaml lacks runtime_configs"
    assert_valid(data, schema, "library.yaml on disk with runtime_configs")


def test_runtime_config_registered_primitive():
    from lib.primitives import get_primitive

    prim = get_primitive("runtime-config")
    assert prim is not None
    assert prim.yaml_key == "library/runtime_configs"
    # alias resolves to the same primitive
    assert get_primitive("runtime_config") is prim
