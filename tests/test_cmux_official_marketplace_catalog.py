"""Catalog contract for the official CMUX Marketplace rollout."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CMUX_PIN = "a4c2ce93a461cf784dd3bd1bcc03e2a7cd2420ee"
OFFICIAL_SKILLS = frozenset(
    {
        "cmux",
        "cmux-workspace",
        "cmux-settings",
        "cmux-customization",
        "cmux-diagnostics",
        "cmux-browser",
        "cmux-markdown",
    }
)


def _catalog() -> dict:
    return yaml.safe_load((ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def test_cmux_official_is_one_remote_git_marketplace_with_gpl_evidence() -> None:
    catalog = _catalog()
    matches = [
        entry
        for entry in catalog["sources"]["marketplaces"]
        if entry["name"] == "cmux-official"
    ]

    assert len(matches) == 1
    marketplace = matches[0]
    assert marketplace["source"] == "https://github.com/manaflow-ai/cmux"
    assert marketplace["type"] == "git"
    assert marketplace["provider_kind"] == "git-repo"
    assert marketplace["local_path"] is None
    assert marketplace["writable"] is False
    assert marketplace["content_types"] == ["skills"]
    assert marketplace["rights"] == {
        "fetch_authorization": "granted",
        "install_rights": "granted",
        "redistribution_rights": "granted",
        "derivative_rights": "granted",
        "evidence_source": (
            "upstream LICENSE (GPL-3.0-or-later), reviewed at "
            "a4c2ce93a461cf784dd3bd1bcc03e2a7cd2420ee on 2026-08-21"
        ),
    }


def test_official_cmux_skills_have_foreign_pinned_provenance_without_local_copies() -> None:
    catalog = _catalog()
    skills = {
        entry["name"]: entry
        for entry in catalog["library"]["skills"]
        if entry["name"] in OFFICIAL_SKILLS
    }

    assert set(skills) == OFFICIAL_SKILLS
    for name, entry in skills.items():
        assert entry["source"] == (
            "https://github.com/manaflow-ai/cmux/blob/"
            f"{CMUX_PIN}/skills/{name}/SKILL.md"
        )
        assert entry["from_marketplace"] == "cmux-official"
        assert entry["repo"] == "cmux"
        assert entry["path"] == f"skills/{name}"
        assert entry["branch"] == CMUX_PIN
        assert entry["metadata"]["library"] == {
            "source_catalog": "cmux-official",
            "inventory": "marketplace",
            "plane": "dev",
            "steward": "manaflow-ai",
        }
        assert "origin:third-party" in entry["tags"]
        assert not any(
            "cognovis/library-core/blob/main/skills/cmux" in value
            for value in entry.values()
            if isinstance(value, str)
        )


def test_dispatch_remains_cognovis_owned_but_depends_on_official_cmux_skills() -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "cmux-bead-dispatch")

    assert dispatch["metadata"]["library"]["source_catalog"] == "cognovis-library-core"
    assert {"skill:cmux", "skill:cmux-workspace"} <= set(dispatch["requires"])


def test_cognovis_core_uses_its_canonical_forgejo_identity() -> None:
    catalog = _catalog()
    core = next(
        entry
        for entry in catalog["sources"]["catalogs"]
        if entry["name"] == "cognovis-library-core"
    )

    assert core["source"] == "https://git.cognovis.de/cognovis/library-core"
    workspace = _entry(catalog, "workspaces", "cognovis-cmux-dispatch")
    assert workspace["catalogs"][0]["identity"] == core["source"]


def test_cmux_workspaces_are_published_from_core_with_their_exact_manifests() -> None:
    catalog = _catalog()
    core_root = Path("/Users/malte/code/library/cognovis-core")

    for name in ("cognovis-cmux", "cognovis-cmux-dispatch"):
        manifest = yaml.safe_load(
            (core_root / "workspaces" / f"{name}.yaml").read_text(encoding="utf-8")
        )
        entry = _entry(catalog, "workspaces", name)
        for key in (
            "schema_version",
            "name",
            "version",
            "description",
            "status",
            "catalogs",
            "roots",
        ):
            assert entry[key] == manifest[key]
        assert entry["metadata"]["library"]["source_catalog"] == "cognovis-library-core"
