"""Regression test: requires_standards frontmatter must map into the catalog
entry's ``requires:`` list for every primitive type, not agents only.

Bug found during clc-b9wq's catalog registration (cognovis-core): a full
`catalog sync --write` silently dropped `requires: [standard:english-only]`
from every skill entry whose SKILL.md declares `requires_standards` (the
dominant convention for skills -- ~60 of them), because artifact_entry() only
read requires_standards inside an `if primitive_name == "agent":` guard.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib.catalog_inventory import artifact_entry  # noqa: E402

SOURCE_ENTRY = {"name": "cognovis-library-core", "source": "https://github.com/cognovis/library-core"}


def _write_skill(root: Path, name: str, frontmatter_body: str) -> Path:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\n{frontmatter_body}\n---\n\n# {name}\n")
    return skill_dir


def test_skill_with_only_requires_standards_gets_typed_requires(tmp_path: Path) -> None:
    """The reported failing case: a skill using only requires_standards (no
    requires:), matching adr-gap and angebotserstellung's actual frontmatter."""
    skill_dir = _write_skill(
        tmp_path,
        "adr-gap-like",
        "name: adr-gap-like\ndescription: audit adrs\nrequires_standards: [english-only]",
    )

    entry = artifact_entry(tmp_path, SOURCE_ENTRY, "skill", skill_dir / "SKILL.md")

    assert entry.get("requires") == ["standard:english-only"]


def test_skill_with_multiple_requires_standards_entries(tmp_path: Path) -> None:
    skill_dir = _write_skill(
        tmp_path,
        "multi-standards",
        "name: multi-standards\ndescription: does things\n"
        "requires_standards: [tool-standards, english-only, no-emoji]",
    )

    entry = artifact_entry(tmp_path, SOURCE_ENTRY, "skill", skill_dir / "SKILL.md")

    assert entry.get("requires") == [
        "standard:english-only",
        "standard:no-emoji",
        "standard:tool-standards",
    ]


def test_skill_requires_and_requires_standards_are_merged(tmp_path: Path) -> None:
    """Control: a skill declaring both requires: and requires_standards: (like
    bead-implementation-loop) must merge both into the typed requires list."""
    skill_dir = _write_skill(
        tmp_path,
        "merged-skill",
        "name: merged-skill\ndescription: merges both fields\n"
        "requires:\n  - skill:cognovis-beads\n  - standard:english-only\n"
        "requires_standards:\n  - dispatch/model-routing",
    )

    entry = artifact_entry(tmp_path, SOURCE_ENTRY, "skill", skill_dir / "SKILL.md")

    assert entry.get("requires") == [
        "skill:cognovis-beads",
        "standard:dispatch/model-routing",
        "standard:english-only",
    ]


def test_skill_with_no_requires_fields_omits_requires_key(tmp_path: Path) -> None:
    """Control: a skill with neither field must not get a spurious requires key."""
    skill_dir = _write_skill(
        tmp_path,
        "no-requires",
        "name: no-requires\ndescription: needs nothing special",
    )

    entry = artifact_entry(tmp_path, SOURCE_ENTRY, "skill", skill_dir / "SKILL.md")

    assert "requires" not in entry


def test_agent_requires_standards_still_works(tmp_path: Path) -> None:
    """Control: the previously-only-supported agent case keeps working."""
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    agent_file = agent_dir / "example-agent.md"
    agent_file.write_text(
        "---\nname: example-agent\ndescription: an agent\n"
        "requires_standards: [english-only]\n---\n\n# example-agent\n"
    )

    entry = artifact_entry(tmp_path, SOURCE_ENTRY, "agent", agent_file)

    assert entry.get("requires") == ["standard:english-only"]
