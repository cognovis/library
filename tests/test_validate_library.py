#!/usr/bin/env python3
"""
test_validate_library.py — Acceptance tests for validate-library.py (CL-49a)

Tests:
  M2: Schema accepts new optional fields: globs, always_apply, compatibility, metadata
  M3: Validator enforces agentskills.io name/description rules

Run with:
    python3 -m pytest tests/test_validate_library.py -v
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_PY = REPO_ROOT / "scripts" / "validate-library.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"


def _run_validator(yaml_content: str) -> subprocess.CompletedProcess:
    """Write yaml_content to a temp file and run validate-library.py against it."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), "--yaml", tmp_path, "--schema", str(SCHEMA_PATH)],
            capture_output=True,
            text=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return result


def _make_library_yaml(skill_entry: dict) -> str:
    """Wrap a skill entry dict into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "skills": [skill_entry],
        },
    }
    return yaml.dump(data, default_flow_style=False)


def _make_library_yaml_with_standard(standard_entry: dict) -> str:
    """Wrap a standard entry dict into a minimal valid library.yaml string."""
    data = {
        "default_dirs": {
            "skills": [{"claude": "~/.claude/skills"}],
        },
        "library": {
            "standards": [standard_entry],
        },
    }
    return yaml.dump(data, default_flow_style=False)


def _base_skill_entry() -> dict:
    """Return a minimal valid skill entry."""
    return {
        "name": "my-skill",
        "description": "A valid skill.",
        "source": "https://github.com/example/repo/blob/main/skills/my-skill/SKILL.md",
    }


# ---------------------------------------------------------------------------
# M2: Schema accepts new optional fields
# ---------------------------------------------------------------------------


def test_m2_schema_accepts_new_fields():
    """Skill entry using all four new fields (globs, always_apply, compatibility, metadata)
    must validate successfully (exit 0)."""
    entry = _base_skill_entry()
    entry["globs"] = ["**/*.py", "**/*.ts"]
    entry["always_apply"] = True
    entry["compatibility"] = "claude_code>=4.0"
    entry["metadata"] = {"author": "test", "tier": "beta"}

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for skill entry with new fields, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# M3: Validator enforces agentskills.io name/description rules
# ---------------------------------------------------------------------------


def test_m3_name_invalid_consecutive_hyphens():
    """Skill with name 'bad--name' (consecutive hyphens) must fail (exit 1) and mention 'name'."""
    entry = _base_skill_entry()
    entry["name"] = "bad--name"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with consecutive hyphens, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "name" in output.lower(), (
        f"Expected error output to mention 'name', got:\n{output}"
    )


def test_m3_name_too_long():
    """Skill with name exceeding 64 chars must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["name"] = "a" * 65

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name >64 chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_name_with_invalid_chars():
    """Skill with name containing invalid chars ('bad name!') must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["name"] = "bad name!"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with invalid chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_description_too_long():
    """Skill with description exceeding 1024 chars must fail (exit 1)."""
    entry = _base_skill_entry()
    entry["description"] = "x" * 1025

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for description >1024 chars, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_valid_entry_passes():
    """Skill with valid name and description must pass (exit 0)."""
    entry = {
        "name": "my-skill",
        "description": "A valid skill.",
        "source": "https://github.com/example/repo/blob/main/skills/my-skill/SKILL.md",
    }

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for valid entry, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_m3_name_with_trailing_hyphen():
    """Skill with name 'bad-name-' (trailing hyphen) must fail (exit 1) and mention 'trailing hyphen'."""
    entry = _base_skill_entry()
    entry["name"] = "bad-name-"

    yaml_str = _make_library_yaml(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 1, (
        f"Expected exit 1 for name with trailing hyphen, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "trailing hyphen" in output.lower(), (
        f"Expected error output to mention 'trailing hyphen', got:\n{output}"
    )


def test_m2_standard_entry_with_globs_and_always_apply():
    """Standard entry with globs and always_apply fields must validate successfully (exit 0)."""
    entry = {
        "name": "my-standard",
        "description": "A valid standard.",
        "source": "https://github.com/example/repo/blob/main/standards/my-standard.md",
        "globs": ["*.md"],
        "always_apply": False,
    }

    yaml_str = _make_library_yaml_with_standard(entry)
    result = _run_validator(yaml_str)
    assert result.returncode == 0, (
        f"Expected exit 0 for standard entry with globs and always_apply, got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
