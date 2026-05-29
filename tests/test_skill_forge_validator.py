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


def test_validator_reports_mcp_debt_in_target_fenced_blocks(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: mcp-debt\n"
        "description: valid test skill\n"
        "---\n"
        "# MCP Debt\n"
        "Plain body text mentions bd list, git status, and $HANDLERS_DIR.\n"
        "Inline code mentions `bd show CL-1`, `git diff`, and `$HANDLERS_DIR`.\n"
        "```bash\n"
        "bd list --status=open\n"
        "git status\n"
        "uv run python \"$HANDLERS_DIR/session-close-runner.py\"\n"
        "```\n"
        "```text\n"
        "bd show CL-1\n"
        "${HANDLERS_DIR}/session-close-runner.py\n"
        "```\n"
        "```python\n"
        "bd close CL-1\n"
        "git commit -m test\n"
        "```\n"
    )

    result = run_validator(skill, "--strict", "--suggest-mcp")

    assert result.returncode == 1
    assert result.stdout.count("MCP_DEBT_BD:") == 2
    assert result.stdout.count("MCP_DEBT_GIT:") == 1
    assert result.stdout.count("MCP_DEBT_HANDLER_BASH:") == 2
    assert "mcp__cognovis_tools__bd_* equivalents" in result.stdout
    assert "mcp__cognovis_tools__git_* equivalents" in result.stdout
    assert "cognovis-tools MCP server invocation" in result.stdout
    assert "bd close" not in result.stdout
    assert "git commit" not in result.stdout


def test_validator_debt_count_reports_only_mcp_debt_findings(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: debt-count\n"
        "description: valid test skill\n"
        "---\n"
        "# Debt Count\n"
        "Plain body text mentions bd list, git status, and $HANDLERS_DIR.\n"
        "```text\n"
        "bd list\n"
        "git diff\n"
        "$HANDLERS_DIR/session-close-runner.py\n"
        "```\n"
    )

    result = run_validator(skill, "--format=debt-count")

    assert result.returncode == 0
    assert result.stdout.strip() == "3"
    assert result.stderr == ""


def test_fleet_scan_reports_debt_column_and_total(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    skills_root = project / "skills"
    home.mkdir()
    skills_root.mkdir(parents=True)

    debt_skill = skills_root / "debt-skill"
    debt_skill.mkdir()
    (debt_skill / "SKILL.md").write_text(
        "---\n"
        "name: debt-skill\n"
        "description: valid test skill\n"
        "---\n"
        "# Debt Skill\n"
        "```bash\n"
        "bd ready\n"
        "git status\n"
        "```\n"
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
    assert " DEBT" in result.stdout
    assert "debt-skill" in result.stdout
    assert "clean-skill" in result.stdout
    assert "Total MCP debt findings: 2" in result.stdout
