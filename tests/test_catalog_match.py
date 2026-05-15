"""Tests for source catalog routing metadata and inventory refresh."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"


def run_library(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run library.py and return the completed process."""
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
    )


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def assert_valid(data: dict) -> None:
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = list(validator.iter_errors(data))
    if errors:
        messages = "\n".join(
            f"[{'/'.join(str(part) for part in error.absolute_path)}] {error.message}"
            for error in errors
        )
        raise AssertionError(messages)


def minimal_library(source_root: Path) -> str:
    return f"""
default_dirs:
  skills:
    - default: .agents/skills/
  standards:
    - default: .agents/standards/
sources:
  catalogs:
    - name: test-core
      source: https://github.com/example/core
      description: Test source catalog.
      visibility: private
      owner: example
      audience: team
      local_path: {source_root}
      writable: true
      content_types:
        - standards
        - skills
      scope:
        topics:
          - python
          - uv
  marketplaces: []
library:
  skills: []
  agents: []
  prompts: []
  standards:
    - name: old-python-uv
      description: Old generated entry.
      source: https://github.com/example/core/blob/main/standards/old-python-uv.md
"""


def test_schema_accepts_catalog_routing_metadata(tmp_path: Path) -> None:
    data = yaml.safe_load(minimal_library(tmp_path / "source"))
    assert_valid(data)


def test_library_yaml_sources_have_routing_metadata() -> None:
    data = yaml.safe_load(LIBRARY_PATH.read_text())
    by_name = {
        entry["name"]: entry
        for registry in ("catalogs", "marketplaces")
        for entry in data["sources"].get(registry, [])
    }

    for name in (
        "sussdorff-library-core",
        "cognovis-library-core",
        "open-brain",
        "cognovis-samurai",
        "anthropic-official",
    ):
        entry = by_name[name]
        assert "local_path" in entry
        assert "writable" in entry
        assert entry.get("scope", {}).get("topics")


def test_catalog_match_returns_writable_standard_candidate() -> None:
    result = run_library(
        "catalog",
        "match",
        "--primitive-type=standard",
        "--topics=python,uv",
        "--writable-only",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    matches = data["matches"]

    assert matches
    assert all(match["writable"] for match in matches)
    assert all("standards" in match["content_types"] for match in matches)
    assert matches[0]["score"] > 0
    assert any(match["name"] == "cognovis-library-core" for match in matches)


def test_catalog_sync_dry_run_scans_local_inventory(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    standards_dir = source_root / "standards"
    standards_dir.mkdir(parents=True)
    (standards_dir / "python-uv.md").write_text(
        "---\nname: python-uv\ndescription: Python uv standard.\n---\n# Python uv\n"
    )
    (tmp_path / "library.yaml").write_text(minimal_library(source_root))

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=standard",
        "--json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["status"] == "dry-run"
    assert data["generated"]["standard"] == 1
    assert data["entries"][0]["name"] == "python-uv"


def test_catalog_sync_write_refreshes_generated_entries(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    standards_dir = source_root / "standards"
    standards_dir.mkdir(parents=True)
    (standards_dir / "python-uv.md").write_text(
        "---\nname: python-uv\ndescription: Python uv standard.\n---\n# Python uv\n"
    )
    (tmp_path / "library.yaml").write_text(minimal_library(source_root))

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=standard",
        "--write",
        "--json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    names = [entry["name"] for entry in refreshed["library"]["standards"]]

    assert data["status"] == "ok"
    assert names == ["python-uv"]


def test_catalog_sync_write_preserves_remote_only_marketplace_entries(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    skill_dir = source_root / "skills" / "local-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: local-skill\ndescription: Local generated skill.\n---\n# Local Skill\n"
    )
    catalog = f"""
default_dirs:
  skills:
    - default: .agents/skills/
sources:
  catalogs:
    - name: test-core
      source: https://github.com/example/core
      description: Test source catalog.
      local_path: {source_root}
      writable: true
      content_types:
        - skills
      scope:
        topics:
          - local
  marketplaces:
    - name: public-marketplace
      source: https://github.com/example-public
      description: Remote-only public marketplace.
      type: git
      local_path: null
      writable: false
      content_types:
        - skills
      scope:
        topics:
          - public
library:
  skills:
    - name: old-local-skill
      description: Old generated entry.
      source: https://github.com/example/core/blob/main/skills/old-local-skill/SKILL.md
    - name: remote-skill
      description: Remote marketplace skill.
      from_marketplace: public-marketplace
      repo: remote-skill
      path: skills/remote-skill
  agents: []
  prompts: []
"""
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library("catalog", "sync", "--primitive-type=skill", "--write", "--json", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    names = {entry["name"] for entry in refreshed["library"]["skills"]}

    assert names == {"local-skill", "remote-skill"}
