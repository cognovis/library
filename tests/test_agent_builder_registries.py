#!/usr/bin/env python3
"""Tests for agent-builder model and capability registries."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jsonschema
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_YAML = REPO_ROOT / "models.yaml"
CAPABILITIES_YAML = REPO_ROOT / "capabilities.yaml"
MODELS_SCHEMA = REPO_ROOT / "docs" / "schema" / "models.schema.json"
CAPABILITIES_SCHEMA = REPO_ROOT / "docs" / "schema" / "capabilities.schema.json"
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"


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


def test_runtime_model_registry_has_distinct_capability_namespace_and_variants() -> None:
    data = _load_yaml(MODELS_YAML)
    by_id = {model["id"]: model for model in data["models"]}

    assert data["runtime_registry_version"]
    assert {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"} <= set(by_id)
    assert by_id["gpt-5.6-sol"]["suitability_capabilities"] != by_id["gpt-5.6-terra"]["suitability_capabilities"]
    assert all("capabilities" not in model for model in data["models"])

    model_ids = [model["id"] for model in data["models"]]
    assert len(model_ids) == len(set(model_ids))
    assert {"claude-code", "codex"} <= {model["harness"] for model in data["models"]}
    assert {"haiku", "sonnet", "opus"} <= set(model_ids)
    retired_models = {"gpt-5." + "4", "gpt-5." + "4-mini"}
    assert retired_models.isdisjoint(model_ids)


def test_regression_codex_cost_tiers_resolve_to_current_generation() -> None:
    """Economy and standard requests must resolve to Luna and Terra, never retired models."""
    economy = _resolve_against_real_registry(
        {
            "tier": "economy",
            "reasoning": "low",
            "context": "small",
            "cost_priority": "cheapest",
        },
        harness="codex",
    )
    standard = _resolve_against_real_registry(
        {
            "tier": "standard",
            "reasoning": "high",
            "context": "large",
            "cost_priority": "balanced",
        },
        harness="codex",
    )

    assert economy == ("gpt-5.6-luna", "low")
    assert standard == ("gpt-5.6-terra", "high")


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


def _resolve_against_real_registry(
    requirements: dict, *, harness: str = "claude"
) -> tuple[str, str | None] | None:
    """Resolve a requirement block through build-agent.py against the live registry."""
    spec = importlib.util.spec_from_file_location("build_agent_registry_probe", BUILD_AGENT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = _load_yaml(MODELS_YAML)["models"]
    return module.resolve_model(requirements, harness, registry)


def test_claude_code_resolves_a_frontier_reviewer() -> None:
    """A frontier quality-first requirement resolves to the Claude frontier model."""
    resolved = _resolve_against_real_registry(
        {
            "tier": "frontier",
            "reasoning": "high",
            "context": "large",
            "cost_priority": "quality-first",
        }
    )
    assert resolved is not None
    assert resolved[0] == "fable"


def test_claude_code_premium_still_resolves_to_opus() -> None:
    """Adding a frontier entry keeps every premium claude-code requirement on opus."""
    resolved = _resolve_against_real_registry(
        {
            "tier": "premium",
            "reasoning": "high",
            "context": "large",
            "cost_priority": "balanced",
        }
    )
    assert resolved is not None
    assert resolved[0] == "opus"


def test_claude_code_cheapest_premium_resolves_to_opus() -> None:
    """A cost-led premium requirement picks opus, never the frontier model."""
    resolved = _resolve_against_real_registry(
        {
            "tier": "premium",
            "reasoning": "high",
            "context": "large",
            "cost_priority": "cheapest",
        }
    )
    assert resolved is not None
    assert resolved[0] == "opus"


def test_codex_premium_tier_holds_only_the_current_generation() -> None:
    """No superseded codex model sits at the premium tier it can never win."""
    models = _load_yaml(MODELS_YAML)["models"]
    premium = {
        model["id"]
        for model in models
        if model["harness"] == "codex" and model["tier"] == "premium"
    }
    assert premium == {"gpt-5.6-terra"}
