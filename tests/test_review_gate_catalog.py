"""Delivery contract for Repository Delivery over the shared execution loop."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_repository_delivery_bundle_is_installable_from_catalog():
    catalog = yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))["library"]
    skills = {entry["name"]: entry for entry in catalog["skills"]}

    requires = set(skills["executive-pack"]["requires"])
    assert "skill:bead-execution-loop" in requires
    assert "skill:session-close" in requires
    assert not {
        "agent:diff-risk-classifier",
        "agent:review-gates",
        "agent:seam-contract-reviewer",
    } & requires
