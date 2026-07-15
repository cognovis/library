"""Catalog contract for cmux multi-bead dispatch."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> dict:
    return yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def test_dispatch_and_workspace_are_installable_skills() -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "cmux-bead-dispatch")
    workspace = _entry(catalog, "skills", "cmux-workspace")

    assert dispatch["requires"][:3] == [
        "skill:cmux",
        "skill:cmux-workspace",
        "skill:cognovis-beads",
    ]
    assert dispatch["metadata"]["library"]["gascity"]["exportable"] is False
    assert dispatch["scripts"][0]["entrypoint"] is True
    assert workspace["metadata"]["library"]["gascity"]["exportable"] is False


def test_retired_runtime_entries_are_absent() -> None:
    catalog = _catalog()
    names = {
        kind: {entry["name"] for entry in catalog["library"][kind]}
        for kind in ("skills", "agents")
    }
    retired_skill = "wave-" + "dispatch"
    retired_agents = {"wave-" + "monitor", "wave-" + "orchestrator"}

    assert retired_skill not in names["skills"]
    assert not retired_agents & names["agents"]


def test_canonical_launchers_accept_coordinator_identity_flags() -> None:
    for launcher in ("cld", "cdx"):
        source = (ROOT / "bin" / launcher).read_text(encoding="utf-8")
        assert "--coordinator-workspace)" in source
        assert "--coordinator-surface)" in source
        assert "--coordinator-workspace workspace:<n>" in source
        assert "--coordinator-surface surface:<n>" in source
