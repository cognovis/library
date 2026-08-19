"""clc-1wis: platform catalog entries must not remain library-platform-owned."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

MOVED_SKILL_NAMES = {
    "library",
    "agent-forge",
    "hook-forge",
    "mcp-forge",
    "skill-forge",
    "script-forge",
    "standard-forge",
}


def _catalog() -> dict:
    return yaml.safe_load((REPO_ROOT / "library.yaml").read_text())


def test_no_catalog_entry_uses_library_platform_source_catalog() -> None:
    leftover: list[str] = []
    for section, entries in _catalog()["library"].items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            metadata = ((entry.get("metadata") or {}).get("library") or {})
            if metadata.get("source_catalog") == "library-platform":
                leftover.append(f"{section}:{entry.get('name')}")
    assert leftover == [], leftover


def test_moved_skill_names_stay_registered() -> None:
    names = {entry["name"] for entry in _catalog()["library"]["skills"]}
    assert MOVED_SKILL_NAMES <= names


def test_moved_skill_sources_belong_to_library_core() -> None:
    entries = {
        entry["name"]: entry for entry in _catalog()["library"]["skills"]
    }
    for name in MOVED_SKILL_NAMES:
        entry = entries[name]
        metadata = entry["metadata"]["library"]
        assert metadata["source_catalog"] == "cognovis-library-core"
        assert "cognovis/library-core" in str(entry["source"])
        assert "github.com/cognovis/library/" not in str(entry["source"])
