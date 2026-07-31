"""Delivery contract for the lean bead implementation loop bundle."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_lean_review_loop_bundle_is_installable_from_catalog():
    catalog = yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))["library"]
    skills = {entry["name"]: entry for entry in catalog["skills"]}

    requires = set(skills["bead-implementation-loop"]["requires"])
    assert requires == {
        "agent:bead-loop-implementer",
        "skill:bead-execution-loop",
        "skill:cognovis-beads",
        "skill:session-close",
        "standard:executive-pack",
        "standard:english-only",
    }
    assert not {
        "agent:diff-risk-classifier",
        "agent:review-gates",
        "agent:seam-contract-reviewer",
    } & requires
