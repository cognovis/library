#!/usr/bin/env python3
"""Tests for agent-builder model and capability registries."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_YAML = REPO_ROOT / "models.yaml"
CAPABILITIES_YAML = REPO_ROOT / "capabilities.yaml"
MODELS_SCHEMA = REPO_ROOT / "docs" / "schema" / "models.schema.json"
CAPABILITIES_SCHEMA = REPO_ROOT / "docs" / "schema" / "capabilities.schema.json"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _assert_valid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    assert not errors, f"{label} schema errors: {[error.message for error in errors]}"


def test_models_yaml_validates_against_schema() -> None:
    """models.yaml conforms to the committed registry schema."""
    data = _load_yaml(MODELS_YAML)
    _assert_valid(data, _load_json(MODELS_SCHEMA), "models.yaml")

    model_ids = [model["id"] for model in data["models"]]
    assert len(model_ids) == len(set(model_ids))
    assert {"claude-code", "codex"} <= {model["harness"] for model in data["models"]}
    assert {"haiku", "sonnet", "opus"} <= set(model_ids)
    assert {"gpt-5.4-mini", "gpt-5.4"} <= set(model_ids)


def test_capabilities_yaml_validates_against_schema() -> None:
    """capabilities.yaml conforms to the committed registry schema."""
    data = _load_yaml(CAPABILITIES_YAML)
    _assert_valid(data, _load_json(CAPABILITIES_SCHEMA), "capabilities.yaml")

    capability_names = [capability["name"] for capability in data["capabilities"]]
    assert len(capability_names) == len(set(capability_names))
    assert len(capability_names) >= 10
    assert {
        "read_files",
        "write_files",
        "edit_files",
        "run_shell",
        "spawn_subagents",
        "query_memory",
        "search_web",
        "search_searxng",
        "use_skills",
        "query_executive_library",
        "refine_prompts",
        "browser",
    } <= set(capability_names)
