"""
test_migrate_originals.py — RED/GREEN migration tests for CL-sxt.

Tests that the 78 ORIGINAL artefacts with migration_action=move_to_cognovis_library_core
are correctly copied into cognovis/library-core at the expected skeleton paths.

Run:
    python3 -m pytest tests/test_migrate_originals.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).parent.parent
AUDIT_JSON = WORKTREE_ROOT / "docs" / "audit" / "skills-origin.json"
LIBRARY_CORE = Path(os.environ.get("LIBRARY_CORE", "/tmp/cognovis-library-core"))
SOURCE_PLUGINS = Path(os.environ.get("SOURCE_PLUGINS", "/Users/malte/code/claude-code-plugins"))

# The 5 specific skills chosen for spot-check (AK3).
# All of these must exist on disk in SOURCE_PLUGINS.
SPOT_CHECK_SKILLS = ["dolt", "cmux", "council", "prompt-refiner", "inject-standards"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def load_audit() -> list[dict]:
    """Return only the 78 artefacts that should be migrated."""
    with AUDIT_JSON.open() as fh:
        data = json.load(fh)
    return [
        a
        for a in data["artifacts"]
        if a["origin"] == "ORIGINAL"
        and a["migration_action"] == "move_to_cognovis_library_core"
    ]


@pytest.fixture(scope="module")
def audit_artifacts() -> list[dict]:
    return load_audit()


# ---------------------------------------------------------------------------
# Test 1 (AK1): Expected files present in library-core
# ---------------------------------------------------------------------------


def test_expected_files_present(audit_artifacts: list[dict]) -> None:
    """
    Verify that after migration, library-core has exactly:
    - 41 .claude/skills/*/SKILL.md files (including beads from worktree)
    - 27 .claude/agents/*.md files
    - 5+ .claude/hooks/* files
    - 3+ .claude/commands/*.md files
    """
    # Count skills (audit lists 41 skills including beads copied from worktree).
    # Some skills use lowercase 'skill.md' — count both variants.
    skills_dir = LIBRARY_CORE / ".claude" / "skills"
    skill_files = list(skills_dir.glob("*/SKILL.md")) + list(skills_dir.glob("*/skill.md"))
    assert len(skill_files) == 41, (
        f"Expected == 41 SKILL.md files under {skills_dir}, found {len(skill_files)}"
    )

    # Count agents
    agents_dir = LIBRARY_CORE / ".claude" / "agents"
    agent_files = list(agents_dir.glob("*.md"))
    assert len(agent_files) == 27, (
        f"Expected == 27 agent .md files under {agents_dir}, found {len(agent_files)}"
    )

    # Count hooks
    hooks_dir = LIBRARY_CORE / ".claude" / "hooks"
    hook_files = [f for f in hooks_dir.iterdir() if f.is_file() and not f.name.endswith(".gitkeep")]
    assert len(hook_files) >= 5, (
        f"Expected >= 5 hook files under {hooks_dir}, found {len(hook_files)}"
    )

    # Count commands
    commands_dir = LIBRARY_CORE / ".claude" / "commands"
    command_files = list(commands_dir.glob("*.md"))
    assert len(command_files) >= 3, (
        f"Expected >= 3 command .md files under {commands_dir}, found {len(command_files)}"
    )


# ---------------------------------------------------------------------------
# Test 2 (AK2): Frontmatter preserved in all SKILL.md files
# ---------------------------------------------------------------------------


def test_frontmatter_preserved(audit_artifacts: list[dict]) -> None:
    """
    For each SKILL.md in library-core's .claude/skills/:
    - Must contain 'description:' in its content.
    - If source had 'requires_standards:', the dest must also have it.
    """
    skills_dir = LIBRARY_CORE / ".claude" / "skills"
    skill_files = list(skills_dir.glob("*/SKILL.md"))

    assert skill_files, f"No SKILL.md files found in {skills_dir} — run migration first"

    failures: list[str] = []

    for dest_skill in skill_files:
        content = dest_skill.read_text()

        # Must have description:
        if "description:" not in content:
            failures.append(f"{dest_skill}: missing 'description:' in content")
            continue

        # Check if source had requires_standards:
        skill_name = dest_skill.parent.name
        # Find the matching artifact to get the source path
        source_path: Path | None = None
        for artifact in audit_artifacts:
            path_parts = artifact["path"].split("/")
            if artifact["current_type"] == "skill" and path_parts[-2] == skill_name:
                source_path = SOURCE_PLUGINS / artifact["path"]
                break

        if source_path is not None and source_path.exists():
            source_content = source_path.read_text()
            if "requires_standards:" in source_content:
                if "requires_standards:" not in content:
                    failures.append(
                        f"{dest_skill}: source had 'requires_standards:' but dest does not"
                    )

    assert not failures, "Frontmatter preservation failures:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Test 3 (AK3): 5 specific skills installable — content match + bridge symlinks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name", SPOT_CHECK_SKILLS)
def test_five_skills_content_match(skill_name: str, audit_artifacts: list[dict]) -> None:
    """
    For each of the 5 spot-check skills:
    a. .claude/skills/<name>/SKILL.md exists in library-core
    b. Content matches source file exactly
    c. .agents/skills/<name> symlink exists in library-core
    """
    # a. Dest SKILL.md exists
    dest_skill = LIBRARY_CORE / ".claude" / "skills" / skill_name / "SKILL.md"
    assert dest_skill.exists(), (
        f"SKILL.md not found at {dest_skill}"
    )

    # b. Content matches source
    source_path: Path | None = None
    for artifact in audit_artifacts:
        path_parts = artifact["path"].split("/")
        if artifact["current_type"] == "skill" and path_parts[-2] == skill_name:
            source_path = SOURCE_PLUGINS / artifact["path"]
            break

    assert source_path is not None, (
        f"Skill '{skill_name}' not found in audit artifacts"
    )
    assert source_path.exists(), (
        f"Source file not found: {source_path}"
    )

    source_content = source_path.read_text()
    dest_content = dest_skill.read_text()
    assert source_content == dest_content, (
        f"Content mismatch for skill '{skill_name}':\n"
        f"  source: {source_path}\n"
        f"  dest:   {dest_skill}"
    )

    # c. Bridge symlink exists
    bridge_link = LIBRARY_CORE / ".agents" / "skills" / skill_name
    assert bridge_link.is_symlink(), (
        f"Bridge symlink not found at {bridge_link}"
    )

    # Symlink must resolve to the skill directory
    resolved = bridge_link.resolve()
    expected_dir = (LIBRARY_CORE / ".claude" / "skills" / skill_name).resolve()
    assert resolved == expected_dir, (
        f"Bridge symlink {bridge_link} resolves to {resolved}, "
        f"expected {expected_dir}"
    )


# ---------------------------------------------------------------------------
# Test 4 (AK1): Plugin artefacts migrated to library-core plugins/
# ---------------------------------------------------------------------------


def test_plugin_migration() -> None:
    """AK1: Verify architecture-trinity plugin was migrated to library-core plugins/."""
    plugins_dir = LIBRARY_CORE / "plugins"
    trinity_dir = plugins_dir / "architecture-trinity"

    # The architecture-trinity plugin should have been migrated
    assert trinity_dir.exists(), f"plugins/architecture-trinity not found in library-core at {trinity_dir}"
    assert trinity_dir.is_dir(), "architecture-trinity should be a directory"

    # Should have a README
    readme = trinity_dir / "README.md"
    assert readme.exists(), f"architecture-trinity/README.md missing at {readme}"
