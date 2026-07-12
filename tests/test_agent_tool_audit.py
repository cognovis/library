#!/usr/bin/env python3
"""Regression tests for generated agent fleet audit behavior."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FLEET_AUDIT = REPO_ROOT / "scripts" / "agent-fleet-audit.py"
BUILD_AGENT = REPO_ROOT / "scripts" / "build-agent.py"
FIXTURES_DIR = REPO_ROOT / "tests" / "compose" / "fixtures"


def _legacy_nested_dir_only_scan(root: Path) -> list[Path]:
    """Reproduce the old bash scripts' nested-directory-only scan shape."""
    matches: list[Path] = []
    for child in root.iterdir():
        if child.is_dir():
            matches.extend(sorted(child.glob("*.md")))
    return matches


def _make_agent_bases(tmp_path: Path) -> Path:
    base_dir = tmp_path / "agent-bases"
    base_dir.mkdir()
    (base_dir / "claude-agent-base.md").write_text(
        (FIXTURES_DIR / "base-claude-agent-base.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (base_dir / "codex-agent-base.md").write_text(
        (FIXTURES_DIR / "base-codex-agent-base.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return base_dir


def _write_pair_loop_source(tmp_path: Path) -> Path:
    source = tmp_path / "review-agent.md"
    source.write_text(
        "---\n"
        "name: review-agent\n"
        "description: Reviewer regression fixture.\n"
        "model: sonnet\n"
        "tools: Read, Write, Edit, MultiEdit, Bash\n"
        "capabilities:\n"
        "  - run_shell\n"
        "pair_loop_constraints:\n"
        "  review_contexts:\n"
        "    - in_loop\n"
        "    - cold\n"
        "  run_shell: read_only\n"
        "agent_base: auto\n"
        "---\n\n"
        "# Review Agent\n\nRead-only reviewer fixture.\n",
        encoding="utf-8",
    )
    return source


def _run_fleet_audit(claude_root: Path, codex_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(FLEET_AUDIT),
            "--claude-root",
            str(claude_root),
            "--codex-root",
            str(codex_root),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_fleet_audit_counts_flat_claude_agents_missed_by_legacy_scan(tmp_path: Path) -> None:
    """Flat Claude agent files are inspected even though the old nested scan missed them."""
    claude_root = tmp_path / "claude-agents"
    codex_root = tmp_path / "codex-agents"
    claude_root.mkdir()
    codex_root.mkdir()
    for name in ("review-agent", "verification-agent", "constraint-checker"):
        (claude_root / f"{name}.md").write_text("---\nname: fixture\n---\n", encoding="utf-8")
    (codex_root / "review-agent.toml").write_text(
        'name = "review-agent"\ndescription = "fixture"\n',
        encoding="utf-8",
    )

    assert _legacy_nested_dir_only_scan(claude_root) == []

    result = _run_fleet_audit(claude_root, codex_root)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["harnesses"]["claude"]["inspected_count"] == 3
    assert payload["harnesses"]["codex"]["inspected_count"] == 1


def test_fleet_audit_fails_closed_for_empty_or_missing_roots(tmp_path: Path) -> None:
    """An expected root that is missing or has zero agents returns non-zero."""
    codex_root = tmp_path / "codex-agents"
    codex_root.mkdir()
    (codex_root / "review-agent.toml").write_text(
        'name = "review-agent"\ndescription = "fixture"\n',
        encoding="utf-8",
    )

    missing = _run_fleet_audit(tmp_path / "missing-claude", codex_root)
    assert missing.returncode != 0
    assert "does not exist" in missing.stderr

    empty_claude = tmp_path / "empty-claude"
    empty_claude.mkdir()
    empty = _run_fleet_audit(empty_claude, codex_root)
    assert empty.returncode != 0
    assert "inspected zero agents" in empty.stderr


def test_pair_loop_reviewer_regression_builds_read_only_codex_artifact(tmp_path: Path) -> None:
    """Regression: run_shell no longer turns pair-loop reviewers into workspace-write agents."""
    source = _write_pair_loop_source(tmp_path)
    output_dir = tmp_path / "out"
    model_standards_dir = tmp_path / "model-standards"
    model_standards_dir.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_AGENT),
            str(source),
            "--harness",
            "codex",
            "--output-dir",
            str(output_dir),
            "--agent-bases-dir",
            str(_make_agent_bases(tmp_path)),
            "--model-standards-dir",
            str(model_standards_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    parsed = tomllib.loads((output_dir / "review-agent.toml").read_text(encoding="utf-8"))
    assert parsed["sandbox_mode"] == "read-only"
