"""Tests for the normalized library.yaml information model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import get_catalogs, get_entries, get_marketplaces

SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _assert_valid(data: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(_schema())
    errors = list(validator.iter_errors(data))
    if errors:
        messages = "\n".join(
            f"  [{'/'.join(str(part) for part in error.absolute_path)}] {error.message}"
            for error in errors
        )
        raise AssertionError(f"Expected valid schema for {label}, got:\n{messages}")


def _minimal_catalog(**library_sections: list[dict]) -> dict:
    return {
        "default_dirs": {"skills": [{"default": ".agents/skills/"}]},
        "library": {
            "skills": [],
            "agents": [],
            "prompts": [],
            "scripts": [],
            "standards": [],
            **library_sections,
        },
    }


def test_library_yaml_uses_normalized_root_sections() -> None:
    """The checked-in catalog keeps primitives and source registries in canonical sections."""
    data = yaml.safe_load(LIBRARY_PATH.read_text())

    assert {
        "default_dirs",
        "tag_vocabulary",
        "sources",
        "library",
        "project_tooling",
    } <= set(data)
    for legacy_key in (
        "catalog",
        "marketplaces",
        "guardrails",
        "mcp_servers",
        "model_standards",
        "agent_bases",
        "golden_prompts",
    ):
        assert legacy_key not in data

    for primitive_key in (
        "skills",
        "agents",
        "prompts",
        "scripts",
        "standards",
        "guardrails",
        "mcp_servers",
        "model_standards",
        "agent_bases",
    ):
        assert primitive_key in data["library"]

    assert "catalogs" in data["sources"]
    assert "marketplaces" in data["sources"]


def test_cognovis_base_catalog_source_matches_current_source_layout() -> None:
    """The agent-base catalog entry must match the current cognovis-core path."""
    data = yaml.safe_load(LIBRARY_PATH.read_text())
    agent_bases = data["library"]["agent_bases"]
    entry = next(item for item in agent_bases if item["name"] == "cognovis-base")

    assert entry["source"].endswith("/golden-prompts/cognovis-base.md")

    catalogs = {item["name"]: item for item in data["sources"]["catalogs"]}
    local_path = catalogs["cognovis-library-core"].get("local_path")
    if local_path:
        source_root = Path(local_path).expanduser()
        if source_root.exists():
            assert (source_root / "golden-prompts" / "cognovis-base.md").exists()


def test_schema_accepts_canonical_primitive_sections() -> None:
    """New primitive-like sections are valid under library.*."""
    data = _minimal_catalog(
        guardrails=[
            {
                "name": "sample-guardrail",
                "description": "A sample guardrail.",
                "purpose": "pre-tool-veto",
            }
        ],
        mcp_servers=[
            {
                "name": "sample-mcp",
                "description": "A sample MCP server.",
            }
        ],
        model_standards=[
            {
                "name": "sample-model-standard",
                "description": "A sample model standard.",
            }
        ],
        agent_bases=[
            {
                "name": "sample-agent-base",
                "description": "A sample agent base prompt.",
            }
        ],
    )

    _assert_valid(data, "canonical primitive sections")


def test_schema_accepts_canonical_sources_section() -> None:
    """Source registries are valid under sources.*."""
    data = _minimal_catalog()
    data["sources"] = {
        "catalogs": [
            {
                "name": "first-party-core",
                "source": "https://github.com/example/core",
                "description": "First-party catalog.",
            }
        ],
        "marketplaces": [
            {
                "name": "example-marketplace",
                "source": "https://github.com/example",
                "description": "Example marketplace.",
                "type": "git",
            }
        ],
    }

    _assert_valid(data, "canonical sources")


def test_loader_reads_canonical_primitive_sections() -> None:
    """Runtime lookup reads the canonical library.* primitive sections."""
    data = _minimal_catalog(
        guardrails=[{"name": "canonical-guardrail"}],
        mcp_servers=[{"name": "canonical-mcp"}],
        model_standards=[{"name": "canonical-model-standard"}],
        agent_bases=[{"name": "canonical-agent-base"}],
    )

    assert get_entries(data, "guardrail")[0]["name"] == "canonical-guardrail"
    assert get_entries(data, "mcp")[0]["name"] == "canonical-mcp"
    assert get_entries(data, "model-standard")[0]["name"] == "canonical-model-standard"
    assert get_entries(data, "agent-base")[0]["name"] == "canonical-agent-base"


def test_loader_keeps_legacy_primitive_fallbacks() -> None:
    """Older root primitive sections remain readable except removed agent-base aliases."""
    data = {
        "default_dirs": {"skills": [{"default": ".agents/skills/"}]},
        "library": {"skills": [], "agents": [], "prompts": []},
        "guardrails": [{"name": "legacy-guardrail"}],
        "mcp_servers": [{"name": "legacy-mcp"}],
        "model_standards": [{"name": "legacy-model-standard"}],
        "agent_bases": [{"name": "legacy-agent-base"}],
        "golden_prompts": [{"name": "legacy-golden-prompt"}],
    }

    assert get_entries(data, "guardrail")[0]["name"] == "legacy-guardrail"
    assert get_entries(data, "mcp")[0]["name"] == "legacy-mcp"
    assert get_entries(data, "model-standard")[0]["name"] == "legacy-model-standard"
    assert get_entries(data, "agent-base") == []


def test_schema_rejects_removed_agent_base_root_aliases() -> None:
    """agent_bases must live under library.*; golden_prompts is removed."""
    for removed_key in ("agent_bases", "golden_prompts"):
        data = _minimal_catalog()
        data[removed_key] = [{"name": "removed", "description": "Removed alias."}]
        validator = jsonschema.Draft202012Validator(_schema())
        errors = list(validator.iter_errors(data))
        assert errors, f"Expected schema to reject root {removed_key}"


def test_loader_reads_canonical_sources_with_legacy_fallbacks() -> None:
    """Source registry helpers prefer sources.* and fall back to root aliases."""
    canonical = {
        "sources": {
            "catalogs": [{"name": "canonical-catalog"}],
            "marketplaces": [{"name": "canonical-marketplace"}],
        },
        "catalog": [{"name": "legacy-catalog"}],
        "marketplaces": [{"name": "legacy-marketplace"}],
    }
    legacy = {
        "catalog": [{"name": "legacy-catalog"}],
        "marketplaces": [{"name": "legacy-marketplace"}],
    }
    canonical_empty = {
        "sources": {
            "catalogs": [],
            "marketplaces": [],
        },
        "catalog": [{"name": "legacy-catalog"}],
        "marketplaces": [{"name": "legacy-marketplace"}],
    }

    assert get_catalogs(canonical)[0]["name"] == "canonical-catalog"
    assert get_marketplaces(canonical)[0]["name"] == "canonical-marketplace"
    assert get_catalogs(legacy)[0]["name"] == "legacy-catalog"
    assert get_marketplaces(legacy)[0]["name"] == "legacy-marketplace"
    assert get_catalogs(canonical_empty) == []
    assert get_marketplaces(canonical_empty) == []
