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
        "topic-agent",
    ):
        assert _entry(catalog, "agents", agent)

    assert _entry(catalog, "skills", "bead-execution-loop")
    assert _entry(catalog, "skills", "executive-pack")
    assert _entry(catalog, "standards", "executive-pack")
    assert _entry(catalog, "prompts", "executive-pack")["requires"] == [
        "skill:executive-pack"
    ]
    assert _entry(catalog, "prompts", "topic")["requires"] == ["agent:topic-agent"]
    assert not any(
        item["name"] in {"executive-pack-agent", "cohesive-bead-chain-orchestrator"}
        for item in catalog["agents"]
    )


def test_delivery_dependencies_preserve_ownership_boundaries() -> None:
    catalog = _catalog()
    pack = set(_entry(catalog, "skills", "executive-pack")["requires"])
    loop = set(_entry(catalog, "skills", "bead-execution-loop")["requires"])

    assert {"skill:bead-execution-loop", "skill:session-close"} <= pack
    assert {"agent:bead-implementer", "agent:bead-change-reviewer"} <= loop
    assert "agent:executive-pack-agent" not in pack
    assert {"skill:cmux", "skill:cmux-workspace"} <= set(
        _entry(catalog, "agents", "topic-agent")["requires"]
    )
    assert "skill:executive-pack" in _entry(catalog, "agents", "topic-agent")["requires"]


def test_all_new_dependencies_resolve() -> None:
    catalog = _catalog()
    names = {
        prefix: {entry["name"] for entry in catalog[section]}
        for prefix, section in (
            ("skill", "skills"),
            ("agent", "agents"),
            ("standard", "standards"),
            ("mcp", "mcp_servers"),
        )
    }

    for section in ("skills", "agents", "prompts"):
        for entry in catalog[section]:
            if entry["name"] not in {
                "bead-execution-loop",
                "parallelize",
                "cohesive-bead-chain",
                "bead-implementer",
                "bead-change-reviewer",
                "executive-pack",
                "topic-agent",
                "topic",
            }:
                continue
            for dependency in entry.get("requires", []):
                prefix, name = dependency.split(":", 1)
                assert name in names[prefix], dependency
