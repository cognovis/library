#!/usr/bin/env python3
"""
test_personal_migration.py — Tests for CL-4mt: personal artefacts in sussdorff/library-core

Tests:
  1. All 13 personal artefacts exist at correct skeleton paths in sussdorff/library-core
  2. Each SKILL.md / AGENT.md has frontmatter with description: field
  3. mm-cli smoke: SKILL.md accessible and has correct frontmatter (installable)
  4. home-infra smoke: SKILL.md accessible and has correct frontmatter (installable)
  5. Migration commit exists on origin/main of sussdorff/library-core

Run with:
    python3 -m pytest tests/test_personal_migration.py -v
"""

import base64
import json
import subprocess
import sys

import pytest

REPO = "sussdorff/library-core"

# All 13 artefacts: (path_in_repo, display_name)
EXPECTED_SKILL_FILES = [
    (".claude/skills/business/ai-readiness/SKILL.md", "ai-readiness"),
    (".claude/skills/business/amazon/SKILL.md", "amazon"),
    (".claude/skills/business/career-check/SKILL.md", "career-check"),
    (".claude/skills/business/google-invoice/SKILL.md", "google-invoice"),
    (".claude/skills/business/mm-cli/SKILL.md", "mm-cli"),
    (".claude/skills/content/linkedin/SKILL.md", "linkedin"),
    (".claude/skills/content/transcribe/SKILL.md", "transcribe"),
    (".claude/skills/infra/hetzner-cloud/SKILL.md", "hetzner-cloud"),
    (".claude/skills/infra/home-infra/SKILL.md", "home-infra"),
    (".claude/skills/infra/local-vm/SKILL.md", "local-vm"),
    (".claude/skills/infra/paperless-cli/SKILL.md", "paperless-cli"),
    (".claude/skills/infra/piler-cli/SKILL.md", "piler-cli"),
]

AGENT_FILE = ".claude/agents/home.md"

MIGRATION_COMMIT_PREFIX = "feat(CL-4mt):"


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
    """Test 1: All 13 PERSONAL artefacts exist at correct skeleton paths."""

    @pytest.mark.parametrize("path,name", EXPECTED_SKILL_FILES)
    def test_skill_file_exists(self, path, name):
        """Each SKILL.md must be accessible via gh api."""
        data = gh_api(path)
        assert data["type"] == "file", f"{name} SKILL.md is not a file: {data}"
        assert data["size"] > 0, f"{name} SKILL.md is empty"

    def test_agent_home_exists(self):
        """home.md agent must exist at .claude/agents/home.md."""
        data = gh_api(AGENT_FILE)
        assert data["type"] == "file", f"home.md is not a file: {data}"
        assert data["size"] > 0, "home.md is empty"


class TestFrontmatterPreserved:
    """Test 2: Each SKILL.md / AGENT.md has frontmatter with description: field."""

    @pytest.mark.parametrize("path,name", EXPECTED_SKILL_FILES)
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

    def test_agent_has_description(self):
        """Agent home.md must have description: in its YAML frontmatter block."""
        data = gh_api(AGENT_FILE)
        content = decode_content(data)
        assert content.startswith("---"), (
            "home.md does not start with YAML frontmatter (---)"
        )
        frontmatter = get_frontmatter(content)
        assert frontmatter, (
            "home.md has no parseable YAML frontmatter block"
        )
        assert "description:" in frontmatter, (
            "home.md missing 'description:' field in frontmatter"
        )


class TestSmokeInstallable:
    """Test 3 & 4: mm-cli and home-infra smoke tests — accessible + valid frontmatter."""

    def test_mm_cli_smoke(self):
        """mm-cli SKILL.md must be accessible and have name: + description: in frontmatter."""
        path = ".claude/skills/business/mm-cli/SKILL.md"
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
        path = ".claude/skills/infra/home-infra/SKILL.md"
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
        skill_src = src_dir / ".claude" / "skills" / "business" / "mm-cli"
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
        skill_src = src_dir / ".claude" / "skills" / "infra" / "home-infra"
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


class TestMigrationCommit:
    """Test 5: Migration commit exists on origin/main of sussdorff/library-core."""

    def test_migration_commit_exists(self):
        """The CL-4mt migration commit must appear in the repo commit history."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPO}/commits",
                "--jq",
                f'[.[] | select(.commit.message | startswith("{MIGRATION_COMMIT_PREFIX}"))] | length',
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"gh api failed: {result.stderr}"
        count = int(result.stdout.strip())
        assert count >= 1, (
            f"No commit starting with '{MIGRATION_COMMIT_PREFIX}' found in "
            f"{REPO} commit history"
        )

    def test_migration_commit_sha_format(self):
        """Migration commit SHA must be a valid 40-char hex string."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPO}/commits",
                "--jq",
                f'[.[] | select(.commit.message | startswith("{MIGRATION_COMMIT_PREFIX}"))] | .[0].sha',
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"gh api failed: {result.stderr}"
        sha = result.stdout.strip().strip('"')
        assert len(sha) == 40, f"Migration commit SHA has unexpected length: {sha!r}"
        assert all(c in "0123456789abcdef" for c in sha.lower()), (
            f"SHA is not valid hex: {sha!r}"
        )
