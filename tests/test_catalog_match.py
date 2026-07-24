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


def run_library(
    *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
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
      metadata:
        library:
          source_catalog: test-core
          inventory: convention-scan
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


def test_catalog_sync_scans_only_top_level_skill_dirs(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    real_skill = source_root / "skills" / "real-skill"
    real_skill.mkdir(parents=True)
    (real_skill / "skill.md").write_text(
        "---\nname: real-skill\ndescription: Real lowercase skill.\n---\n# Real Skill\n"
    )
    fixture_skill = (
        source_root / "skills" / "owner" / "tests" / "fixtures" / "skills" / "my-skill"
    )
    fixture_skill.mkdir(parents=True)
    (fixture_skill / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Fixture skill.\n---\n# Fixture Skill\n"
    )
    (tmp_path / "library.yaml").write_text(minimal_library(source_root))

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=skill",
        "--json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    names = {entry["name"] for entry in data["entries"]}

    assert names == {"real-skill"}
    assert data["entries"][0]["source"].endswith("/skills/real-skill/skill.md")


def test_catalog_sync_uses_agent_file_stem_over_frontmatter_name(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    agent_dir = source_root / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "playwright-tester.md").write_text(
        "---\nname: frontmatter-agent\ndescription: Playwright testing agent.\n---\n# Playwright Tester\n"
    )
    catalog = minimal_library(source_root).replace(
        "        - standards\n        - skills\n",
        "        - standards\n        - skills\n        - agents\n",
    )
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=agent",
        "--json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["entries"][0]["name"] == "playwright-tester"


def test_catalog_sync_projects_agent_handlers_and_standard_dependencies(
    tmp_path: Path,
) -> None:
    """Convention-scanned agents deliver their private runtime dependencies."""
    source_root = tmp_path / "source"
    agent_dir = source_root / "agents"
    handlers_dir = agent_dir / "diff-risk-classifier-handlers"
    handlers_dir.mkdir(parents=True)
    (handlers_dir / "diff_risk.py").write_text("print('detector')\n")
    (agent_dir / "diff-risk-classifier.md").write_text(
        "---\nname: diff-risk-classifier\ndescription: Classifies diff risk.\n"
        "requires_standards:\n  - seam-contract\nrequires:\n  - agent:review-gates\n"
        "---\n# Diff Risk Classifier\n"
    )
    catalog = minimal_library(source_root).replace(
        "        - standards\n        - skills\n",
        "        - standards\n        - skills\n        - agents\n",
    )
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library(
        "catalog", "sync", "--source=test-core", "--primitive-type=agent", "--json", cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)["entries"][0]
    assert entry["handlers"] == ["agents/diff-risk-classifier-handlers"]
    assert entry["requires"] == ["agent:review-gates", "standard:seam-contract"]


def test_catalog_sync_scans_legacy_agent_base_source_directory(tmp_path: Path) -> None:
    """Inventory sync maps current agent-base catalog entries from golden-prompts sources."""
    source_root = tmp_path / "source"
    legacy_dir = source_root / "golden-prompts"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "cognovis-base.md").write_text(
        "---\nname: cognovis-base\ndescription: Cognovis base Layer 1.\n---\n# Cognovis Base\n"
    )
    catalog = f"""
default_dirs:
  agent_bases:
    - default: .agents/agent-bases/
sources:
  catalogs:
    - name: test-core
      source: https://github.com/example/core
      description: Test source catalog.
      local_path: {source_root}
      writable: true
      content_types:
        - agent_bases
      scope:
        topics:
          - agents
  marketplaces: []
library:
  skills: []
  agents: []
  prompts: []
  agent_bases: []
"""
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=agent-base",
        "--json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["generated"]["agent-base"] == 1
    assert data["entries"][0]["name"] == "cognovis-base"
    assert data["entries"][0]["source"].endswith("/golden-prompts/cognovis-base.md")


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


def test_regression_catalog_sync_refreshes_generated_agent_dependencies(
    tmp_path: Path,
) -> None:
    """Generated requires must not stay stale when an agent contract changes."""
    source_root = tmp_path / "source"
    agents_dir = source_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "bead-orchestrator.md").write_text(
        "---\nname: bead-orchestrator\ndescription: Orchestrates beads.\n"
        "requires:\n  - agent:bead-spec-reviewer\n---\n# Bead Orchestrator\n"
    )
    (agents_dir / "bead-spec-reviewer.md").write_text(
        "---\nname: bead-spec-reviewer\ndescription: Reviews bead specs.\n"
        "---\n# Bead Spec Reviewer\n"
    )
    catalog = (
        minimal_library(source_root)
        .replace("        - standards", "        - standards\n        - agents", 1)
        .replace(
            "  agents: []",
            "  agents:\n"
            "    - name: bead-orchestrator\n"
            "      description: Stale orchestrator.\n"
            "      source: https://github.com/example/core/blob/main/agents/bead-orchestrator.md\n"
            "      requires:\n"
            "        - agent:bead-context\n"
            "      metadata:\n"
            "        library:\n"
            "          source_catalog: test-core\n"
            "          inventory: convention-scan",
        )
    )
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library(
        "catalog",
        "sync",
        "--source=test-core",
        "--primitive-type=agent",
        "--write",
        "--json",
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    agents = {entry["name"]: entry for entry in refreshed["library"]["agents"]}
    assert set(agents) == {"bead-orchestrator", "bead-spec-reviewer"}
    assert agents["bead-spec-reviewer"]["metadata"]["library"]["plane"] == "dev"
    assert agents["bead-orchestrator"]["requires"] == ["agent:bead-spec-reviewer"]


def test_catalog_sync_write_preserves_curated_source_entries(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    standards_dir = source_root / "standards"
    standards_dir.mkdir(parents=True)
    (standards_dir / "python-uv.md").write_text(
        "---\nname: python-uv\ndescription: Python uv standard.\n---\n# Python uv\n"
    )
    catalog = minimal_library(source_root).replace(
        "    - name: old-python-uv\n"
        "      description: Old generated entry.\n"
        "      source: https://github.com/example/core/blob/main/standards/old-python-uv.md\n"
        "      metadata:\n"
        "        library:\n"
        "          source_catalog: test-core\n"
        "          inventory: convention-scan\n",
        "    - name: curated-standard\n"
        "      description: Curated source entry.\n"
        "      source: https://github.com/example/core/blob/main/standards/manual.md\n"
        "      tags:\n"
        "        - curated\n",
    )
    (tmp_path / "library.yaml").write_text(catalog)

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
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    by_name = {entry["name"]: entry for entry in refreshed["library"]["standards"]}

    assert set(by_name) == {"curated-standard", "python-uv"}
    assert by_name["curated-standard"]["tags"] == ["curated"]


def test_catalog_sync_write_does_not_add_name_collision_against_kept_entries(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    standards_dir = source_root / "standards"
    standards_dir.mkdir(parents=True)
    (standards_dir / "agentic-primitives.md").write_text(
        "# Source Agentic Primitives\n"
    )
    catalog = minimal_library(source_root).replace(
        "    - name: old-python-uv\n"
        "      description: Old generated entry.\n"
        "      source: https://github.com/example/core/blob/main/standards/old-python-uv.md\n"
        "      metadata:\n"
        "        library:\n"
        "          source_catalog: test-core\n"
        "          inventory: convention-scan\n",
        "    - name: agentic-primitives\n"
        "      description: Platform-owned standard.\n"
        "      source: https://github.com/example/platform/blob/main/standards/agentic-primitives.md\n",
    )
    (tmp_path / "library.yaml").write_text(catalog)

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
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    standards = refreshed["library"]["standards"]

    assert [entry["name"] for entry in standards] == ["agentic-primitives"]
    assert (
        standards[0]["source"]
        == "https://github.com/example/platform/blob/main/standards/agentic-primitives.md"
    )


def test_catalog_sync_scans_standard_bundles_and_leaf_standards(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    trigger_bundle = source_root / "standards" / "workflow"
    trigger_bundle.mkdir(parents=True)
    (trigger_bundle / "_triggers.yml").write_text("triggers: []\n")
    (trigger_bundle / "bead-hygiene.md").write_text("# Bead Hygiene\n")
    leaf_group = source_root / "standards" / "judge-layer"
    leaf_group.mkdir(parents=True)
    (leaf_group / "README.md").write_text("# Judge Layer README\n")
    (leaf_group / "action-proposal.md").write_text("# Action Proposal\n")
    (source_root / "standards" / "root-standard.md").write_text("# Root Standard\n")
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
    by_name = {entry["name"]: entry for entry in data["entries"]}

    assert set(by_name) == {"action-proposal", "root-standard", "workflow"}
    assert by_name["workflow"]["source"].endswith("/tree/main/standards/workflow/")
    assert "README" not in by_name


def test_catalog_sync_write_preserves_remote_only_marketplace_entries(
    tmp_path: Path,
) -> None:
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
      metadata:
        library:
          source_catalog: test-core
          inventory: convention-scan
    - name: remote-skill
      description: Remote marketplace skill.
      from_marketplace: public-marketplace
      repo: remote-skill
      path: skills/remote-skill
  agents: []
  prompts: []
"""
    (tmp_path / "library.yaml").write_text(catalog)

    result = run_library(
        "catalog", "sync", "--primitive-type=skill", "--write", "--json", cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    refreshed = yaml.safe_load((tmp_path / "library.yaml").read_text())
    names = {entry["name"] for entry in refreshed["library"]["skills"]}

    assert names == {"local-skill", "remote-skill"}
