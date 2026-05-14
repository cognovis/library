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
