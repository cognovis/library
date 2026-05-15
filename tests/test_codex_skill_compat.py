"""Tests for the skill-forge Codex compatibility scanner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
SCAN_SCRIPT = REPO_ROOT / "skills" / "skill-forge" / "scripts" / "scan-codex-compat.py"
FLEET_SCAN_SCRIPT = REPO_ROOT / "skills" / "skill-forge" / "scripts" / "scan-skills.sh"


def scan_subset(*skills: str) -> list[dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), "--json", "--skills", ",".join(skills)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_portable_script_forge_scans_as_works_as_is() -> None:
    results = scan_subset("script-forge")
    assert results[0]["status"] == "works-as-is"


def test_portable_standard_forge_scans_as_works_as_is() -> None:
    results = scan_subset("standard-forge")
    assert results[0]["name"] == "standard-forge"
    assert results[0]["status"] == "works-as-is"
    assert not results[0]["findings"]


def test_fleet_scan_checks_non_claude_harness_roots(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    for root, name in (
        (home / ".agents" / "skills", "agents-only"),
        (home / ".codex" / "skills", "codex-only"),
        (home / ".opencode" / "skills", "opencode-only"),
        (project / ".agents" / "skills", "project-agents"),
        (project / ".codex" / "skills", "project-codex"),
        (project / ".opencode" / "skills", "project-opencode"),
    ):
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test skill\n---\n# {name}\n"
        )

    result = subprocess.run(
        ["bash", str(FLEET_SCAN_SCRIPT)],
        cwd=project,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    for name in (
        "agents-only",
        "codex-only",
        "opencode-only",
        "project-agents",
        "project-codex",
        "project-opencode",
    ):
        assert name in result.stdout


def test_fleet_scan_follows_installed_skill_symlinks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source" / "symlink-skill"
    installed = home / ".codex" / "skills" / "symlink-skill"
    source.mkdir(parents=True)
    installed.parent.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: symlink-skill\ndescription: test skill\n---\n# Symlink Skill\n"
    )
    installed.symlink_to(source)

    result = subprocess.run(
        ["bash", str(FLEET_SCAN_SCRIPT)],
        cwd=tmp_path,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "symlink-skill" in result.stdout
