"""Catalog contracts for the Executive Pack workflow."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> dict:
    return yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))["library"]


def _entry(catalog: dict, section: str, name: str) -> dict:
    return next(item for item in catalog[section] if item["name"] == name)


def test_executive_pack_primitives_are_registered() -> None:
    catalog = _catalog()

    for agent in (
        "bead-implementer",
        "bead-change-reviewer",
        "bead-loop-implementer",
        "bead-lead",
        "executive-pack-agent",
        "topic-agent",
    ):
        assert _entry(catalog, "agents", agent)

    assert _entry(catalog, "skills", "bead-execution-loop")
    assert _entry(catalog, "standards", "executive-pack")
    assert _entry(catalog, "prompts", "topic")["requires"] == ["agent:topic-agent"]


def test_delivery_dependencies_preserve_ownership_boundaries() -> None:
    catalog = _catalog()
    single = set(_entry(catalog, "agents", "bead-loop-implementer")["requires"])
    pack = set(_entry(catalog, "agents", "executive-pack-agent")["requires"])
    lead = set(_entry(catalog, "agents", "bead-lead")["requires"])

    assert {"skill:bead-execution-loop", "skill:session-close"} <= single
    assert {"agent:plan-reviewer", "agent:doc-changelog-updater"} <= single
    assert {"skill:bead-execution-loop", "skill:session-close"} <= pack
    assert lead == {
        "agent:bead-loop-implementer",
        "skill:cognovis-beads",
        "skill:cmux-bead-dispatch",
    }
    assert "agent:executive-pack-agent" not in lead
    assert {"skill:cmux", "skill:cmux-workspace"} <= set(
        _entry(catalog, "agents", "topic-agent")["requires"]
    )


def test_all_new_dependencies_resolve() -> None:
    catalog = _catalog()
    names = {
        prefix: {entry["name"] for entry in catalog[section]}
        for prefix, section in (
            ("skill", "skills"),
            ("agent", "agents"),
            ("standard", "standards"),
        )
    }

    for section in ("skills", "agents", "prompts"):
        for entry in catalog[section]:
            if entry["name"] not in {
                "bead-execution-loop",
                "bead-implementation-loop",
                "cohesive-bead-chain",
                "bead-implementer",
                "bead-change-reviewer",
                "bead-loop-implementer",
                "bead-lead",
                "bead-fleet-lead",
                "cohesive-bead-chain-orchestrator",
                "executive-pack-agent",
                "topic-agent",
                "topic",
            }:
                continue
            for dependency in entry.get("requires", []):
                prefix, name = dependency.split(":", 1)
                assert name in names[prefix], dependency
