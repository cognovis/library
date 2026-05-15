from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "skills" / "skill-forge" / "scripts" / "validate-skill.py"


def run_validator(skill_md: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(skill_md), "--strict"],
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
