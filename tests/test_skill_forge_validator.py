from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "skills" / "skill-forge" / "scripts" / "validate-skill.py"
FLEET_SCAN_SCRIPT = REPO_ROOT / "skills" / "skill-forge" / "scripts" / "scan-skills.sh"


def run_validator(skill_md: Path, *args: str) -> subprocess.CompletedProcess[str]:
    validator_args = args or ("--strict",)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(skill_md), *validator_args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_validator_rejects_unquoted_bracketed_argument_hint(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: ob-cli\n"
        "description: valid test skill\n"
        "argument-hint: [subcommand] [args]\n"
        "---\n"
        "# Test\n"
    )

    result = run_validator(skill)

    assert result.returncode == 2
    assert "Invalid YAML frontmatter" in result.stderr


def test_validator_accepts_quoted_bracketed_argument_hint(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: ob-cli\n"
        "description: valid test skill\n"
        'argument-hint: "[subcommand] [args]"\n'
        "---\n"
        "# Test\n"
    )

    result = run_validator(skill)

    assert result.returncode == 0
    assert result.stderr == ""


def test_fleet_scan_reports_skill_metrics(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    skills_root = project / "skills"
    home.mkdir()
    skills_root.mkdir(parents=True)

    measured_skill = skills_root / "measured-skill"
    measured_skill.mkdir()
    (measured_skill / "SKILL.md").write_text(
        "---\n"
        "name: measured-skill\n"
        "description: valid test skill\n"
        "---\n"
        "# Measured Skill\n"
    )

    clean_skill = skills_root / "clean-skill"
    clean_skill.mkdir()
    (clean_skill / "SKILL.md").write_text(
        "---\n"
        "name: clean-skill\n"
        "description: valid test skill\n"
        "---\n"
        "# Clean Skill\n"
    )

    result = subprocess.run(
        ["bash", str(FLEET_SCAN_SCRIPT)],
        cwd=project,
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "TOKENS" in result.stdout
    assert "measured-skill" in result.stdout
    assert "clean-skill" in result.stdout
    assert "Total skills:            2" in result.stdout
