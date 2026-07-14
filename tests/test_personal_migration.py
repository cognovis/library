#!/usr/bin/env python3
"""
test_personal_migration.py — Tests for CL-4mt: personal artefacts in sussdorff/library-core

Tests:
  1. All current cataloged personal skills exist at their source paths in sussdorff/library-core
  2. Each SKILL.md has frontmatter with description: field
  3. mm-cli smoke: SKILL.md accessible and has correct frontmatter (installable)
  4. home-infra smoke: SKILL.md accessible and has correct frontmatter (installable)
  5. Committed migration evidence remains in platform documentation

Run with:
    uv run pytest tests/test_personal_migration.py -v
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = "sussdorff/library-core"
REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_YAML = REPO_ROOT / "library.yaml"

SOURCE_PREFIX = f"https://github.com/{REPO}/blob/main/"


def expected_skill_files() -> list[tuple[str, str]]:
    """Return current sussdorff/library-core skill paths from library.yaml."""
    catalog = yaml.safe_load(LIBRARY_YAML.read_text(encoding="utf-8")) or {}
    skills = catalog.get("library", {}).get("skills", [])
    expected: list[tuple[str, str]] = []
    for entry in skills:
        source = entry.get("source", "")
        if not source.startswith(SOURCE_PREFIX):
            continue
        path = source.removeprefix(SOURCE_PREFIX)
        if path.startswith("skills/") and path.endswith("/SKILL.md"):
            expected.append((path, entry["name"]))
    return sorted(expected)


def gh_api(path: str) -> dict:
    """Call gh api and return parsed JSON."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(
            f"gh api failed for {path}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def decode_content(api_response: dict) -> str:
    """Decode base64-encoded file content from GitHub API response."""
    raw = api_response.get("content", "")
    # GitHub returns content with newlines
    raw = raw.replace("\n", "")
    return base64.b64decode(raw).decode("utf-8", errors="replace")


def get_frontmatter(content: str) -> str:
    """Extract YAML frontmatter block from a file.

    Returns the text between the opening and closing '---' delimiters,
    or an empty string if no valid frontmatter is present.
    """
    if not content.startswith("---"):
        return ""
    parts = content.split("---", 2)
    return parts[1] if len(parts) >= 2 else ""


class TestAllArtefactsExist:
    """Test 1: All PERSONAL skills exist at current catalog source paths."""

    @pytest.mark.parametrize("path,name", expected_skill_files())
    def test_skill_file_exists(self, path, name):
        """Each SKILL.md must be accessible via gh api."""
        data = gh_api(path)
        assert data["type"] == "file", f"{name} SKILL.md is not a file: {data}"
        assert data["size"] > 0, f"{name} SKILL.md is empty"


class TestFrontmatterPreserved:
    """Test 2: Each SKILL.md has frontmatter with description: field."""

    @pytest.mark.parametrize("path,name", expected_skill_files())
    def test_skill_has_description(self, path, name):
        """Each skill file must have description: in its YAML frontmatter block."""
        data = gh_api(path)
        content = decode_content(data)
        assert content.startswith("---"), (
            f"{name}: SKILL.md does not start with YAML frontmatter (---)"
        )
        frontmatter = get_frontmatter(content)
        assert frontmatter, (
            f"{name}: SKILL.md has no parseable YAML frontmatter block"
        )
        assert "description:" in frontmatter, (
            f"{name}: SKILL.md missing 'description:' field in frontmatter"
        )


class TestSmokeInstallable:
    """Test 3 & 4: mm-cli and home-infra smoke tests — accessible + valid frontmatter."""

    def test_mm_cli_smoke(self):
        """mm-cli SKILL.md must be accessible and have name: + description: in frontmatter."""
        path = "skills/mm-cli/SKILL.md"
        data = gh_api(path)
        content = decode_content(data)
        frontmatter = get_frontmatter(content)
        assert frontmatter, "mm-cli SKILL.md has no parseable YAML frontmatter block"
        assert "name:" in frontmatter, "mm-cli SKILL.md missing 'name:' field in frontmatter"
        assert "description:" in frontmatter, "mm-cli SKILL.md missing 'description:' field in frontmatter"
        # Verify name value appears in the file
        assert "mm-cli" in content, "mm-cli SKILL.md doesn't reference mm-cli"

    def test_home_infra_smoke(self):
        """home-infra SKILL.md must be accessible and have name: + description: in frontmatter."""
        path = "skills/home-infra/SKILL.md"
        data = gh_api(path)
        content = decode_content(data)
        frontmatter = get_frontmatter(content)
        assert frontmatter, "home-infra SKILL.md has no parseable YAML frontmatter block"
        assert "name:" in frontmatter, "home-infra SKILL.md missing 'name:' field in frontmatter"
        assert "description:" in frontmatter, "home-infra SKILL.md missing 'description:' field in frontmatter"
        assert "home-infra" in content, "home-infra SKILL.md doesn't reference home-infra"

    def test_mm_cli_e2e_install(self, tmp_path):
        """Simulate /library use mm-cli — clone source, install to target, verify."""
        import shutil

        # Clone source repo
        src_dir = tmp_path / "library-core"
        result = subprocess.run(
            ["gh", "repo", "clone", REPO, str(src_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gh repo clone failed: {result.stderr.strip()}"
        )
        # Simulate install: copy skill directory to target (mirrors what /library use does)
        skill_src = src_dir / "skills" / "mm-cli"
        skill_dst = tmp_path / "installed-skills" / "mm-cli"
        assert skill_src.exists(), f"mm-cli skill not found at {skill_src}"
        shutil.copytree(str(skill_src), str(skill_dst))
        # Verify install
        installed_skill_md = skill_dst / "SKILL.md"
        assert installed_skill_md.exists(), "SKILL.md not found after install"
        content = installed_skill_md.read_text(encoding="utf-8")
        frontmatter = get_frontmatter(content)
        assert frontmatter, "Installed mm-cli SKILL.md has no parseable YAML frontmatter"
        assert "description:" in frontmatter, (
            "Installed mm-cli SKILL.md missing 'description:' in frontmatter after install"
        )

    def test_home_infra_e2e_install(self, tmp_path):
        """Simulate /library use home-infra — clone source, install to target, verify."""
        import shutil

        # Clone source repo
        src_dir = tmp_path / "library-core"
        result = subprocess.run(
            ["gh", "repo", "clone", REPO, str(src_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gh repo clone failed: {result.stderr.strip()}"
        )
        # Simulate install: copy skill directory to target (mirrors what /library use does)
        skill_src = src_dir / "skills" / "home-infra"
        skill_dst = tmp_path / "installed-skills" / "home-infra"
        assert skill_src.exists(), f"home-infra skill not found at {skill_src}"
        shutil.copytree(str(skill_src), str(skill_dst))
        # Verify install
        installed_skill_md = skill_dst / "SKILL.md"
        assert installed_skill_md.exists(), "SKILL.md not found after install"
        content = installed_skill_md.read_text(encoding="utf-8")
        frontmatter = get_frontmatter(content)
        assert frontmatter, "Installed home-infra SKILL.md has no parseable YAML frontmatter"
        assert "description:" in frontmatter, (
            "Installed home-infra SKILL.md missing 'description:' in frontmatter after install"
        )


class TestMigrationEvidence:
    """Test 5: Migration evidence is committed with the platform catalog."""

    def test_migration_changelog_entry_exists(self):
        """The release record must retain the CL-4mt migration evidence."""
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "*(CL-4mt)* Add changelog entry for personal artefacts migration" in changelog

    def test_migration_architecture_record_exists(self):
        """The retirement ADR must retain the migration dependency record."""
        adr = (REPO_ROOT / "docs" / "adr" / "sussdorff-plugins-removal.md").read_text(
            encoding="utf-8"
        )
        assert "Wave 1 of the Library migration (CL-sxt, CL-4mt, CL-2x4)" in adr
