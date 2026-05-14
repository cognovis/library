#!/usr/bin/env python3
"""Tests for CL-55k judge-layer taxonomy and catalog discovery."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import search_all


def test_judge_layer_tags_are_documented_in_catalog():
    """library.yaml must define the judge-layer tag vocabulary."""
    data = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    definitions = {
        entry["tag"]: entry["description"]
        for entry in data.get("tag_vocabulary", [])
    }

    for tag in ("judge-layer", "requires-proposal", "produces-mandate"):
        assert tag in definitions
        assert definitions[tag].strip()


def test_search_matches_catalog_entry_tags():
    """Tag-only matches must be discoverable via library search."""
    catalog = {
        "library": {
            "skills": [
                {
                    "name": "judge-eval",
                    "description": "Evaluate judge behavior.",
                    "source": "https://github.com/cognovis/library-core/blob/main/skills/judge-eval/SKILL.md",
                    "tags": ["origin:original", "judge-layer"],
                }
            ]
        }
    }

    results = search_all(catalog, "judge-layer")

    assert [result["name"] for result in results] == ["judge-eval"]
    assert results[0]["tags"] == ["origin:original", "judge-layer"]


def test_search_judge_layer_returns_valid_json():
    """The CLI must handle judge-layer searches cleanly before artifacts ship."""
    result = subprocess.run(
        [sys.executable, "scripts/library.py", "search", "judge-layer", "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, result.stderr
    assert isinstance(json.loads(result.stdout), list)


def test_primitives_documents_judge_layer_contracts():
    """PRIMITIVES.md must document the judge-layer vocabulary."""
    text = (REPO_ROOT / "docs" / "PRIMITIVES.md").read_text()

    for expected in (
        "#### Judge Specialization",
        "C7: pre-action gate",
        "`action_boundary` frontmatter",
        "Action Proposal Schema",
        "Mandate",
    ):
        assert expected in text


def test_agent_justification_gate_keeps_existing_c_numbering():
    """Judge C7 must extend, not renumber, the existing C1-C6 gate."""
    text = (REPO_ROOT / "docs" / "PRIMITIVES.md").read_text()

    for expected in (
        "| C1: different tool permission set |",
        "| C2: own context budget |",
        "| C3: parallel siblings |",
        "| C4: information barrier |",
        "| C5: different model |",
        "| C6: multi-phase orchestration |",
        "| C7: pre-action gate |",
    ):
        assert expected in text

    assert "| C1: isolated context |" not in text
    assert "| C2: specialized prompt |" not in text
    assert "| C5: independent review |" not in text
    assert "| C6: model fit |" not in text


def test_persona_alone_is_not_agent_justification():
    """Durable persona/rubric language must remain a counterexample, not C2."""
    text = (REPO_ROOT / "docs" / "PRIMITIVES.md").read_text()

    assert "Do NOT create an agent just because the work needs a durable persona" in text
    assert "unless one of C1-C7 also" in text


def test_action_boundary_uses_risk_class_effect_type_and_uri_refs():
    """action_boundary examples must use the stable downstream contract shape."""
    text = (REPO_ROOT / "docs" / "PRIMITIVES.md").read_text()

    for expected in (
        "risk_class: external-side-effect",
        "effect_type: financial",
        "proposal_schema: standard://judge-layer/proposals/action-proposal.v1",
        "judge: agent://judge-default",
        'risk_class = "external-side-effect"',
        'effect_type = "financial"',
        'proposal_schema = "standard://judge-layer/proposals/action-proposal.v1"',
        'judge = "agent://judge-default"',
    ):
        assert expected in text

    for forbidden in (
        "class: external-system",
        "class: financial",
        "proposal_schema: action-proposal.v1",
        "judge: default-judge",
        'class = "financial"',
        'proposal_schema = "action-proposal.v1"',
        'judge = "default-judge"',
    ):
        assert forbidden not in text


def test_portability_matrix_includes_action_boundary_row():
    """Action Boundary metadata must be discoverable from the matrix."""
    text = (REPO_ROOT / "docs" / "PRIMITIVES.md").read_text()

    assert "| 3a | [Action Boundary](#action-boundary-metadata) |" in text
    assert "### Action Boundary Metadata" in text
    assert "YAML for skills, TOML for agents" in text
