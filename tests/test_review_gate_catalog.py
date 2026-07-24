"""Delivery contract for the shift-left review-gate bundle."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _by_name(entries):
    return {entry["name"]: entry for entry in entries}


def test_review_gate_bundle_is_installable_from_catalog():
    catalog = yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))["library"]
    skills = _by_name(catalog["skills"])
    agents = _by_name(catalog["agents"])
    standards = _by_name(catalog["standards"])

    requires = set(skills["bead-implementation-loop"]["requires"])
    assert {
        "skill:inject-standards",
        "skill:session-close",
        "agent:diff-risk-classifier",
        "agent:review-gates",
        "agent:seam-contract-reviewer",
    } <= requires
    assert agents["diff-risk-classifier"]["handlers"] == [
        "agents/diff-risk-classifier-handlers"
    ]
    assert agents["review-gates"]["handlers"] == [
        "agents/review-gates-handlers"
    ]
    assert "standard:seam-contract" in agents["seam-contract-reviewer"]["requires"]
    assert standards["seam-contract"]["source"].endswith(
        "/standards/seam-contract/seam-contract.md"
    )
