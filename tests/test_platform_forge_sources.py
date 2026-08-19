from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
FORGE_NAMES = (
    "skill-forge",
    "agent-forge",
    "standard-forge",
    "script-forge",
    "hook-forge",
)
CORE_STANDARD_PATHS = {
    "agentic-primitives": "standards/agentic-primitives/agentic-primitives.md",
    "primitive-placement": "standards/agentic-primitives/primitive-placement.md",
}
CORE_STANDARD_REQUIRES = {
    f"standard:{name}" for name in CORE_STANDARD_PATHS
}
CORE_CHECKOUTS = (
    Path("/Users/malte/code/.worktrees/cognovis-core/clc-1wis"),
    Path("/Users/malte/code/library/cognovis-core"),
)


def _core_root() -> Path:
    for candidate in CORE_CHECKOUTS:
        if (candidate / "skills" / "agent-forge" / "SKILL.md").is_file():
            return candidate
    raise AssertionError(f"moved forge skills not found in {CORE_CHECKOUTS}")


def _library_entries(section: str) -> dict[str, dict[str, object]]:
    data = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    entries = data["library"][section]
    return {entry["name"]: entry for entry in entries}


def test_platform_forge_source_urls_match_checked_in_files() -> None:
    entries = _library_entries("skills")
    core_root = _core_root()

    for name in FORGE_NAMES:
        source = str(entries[name]["source"])
        expected = (
            f"https://github.com/cognovis/library-core/blob/main/skills/{name}/SKILL.md"
        )
        assert source == expected
        assert (core_root / "skills" / name / "SKILL.md").is_file()


def test_platform_standard_source_urls_match_checked_in_files() -> None:
    entries = _library_entries("standards")
    core_root = _core_root()

    for name, path in CORE_STANDARD_PATHS.items():
        entry = entries[name]
        source = str(entry["source"])
        expected = f"https://github.com/cognovis/library-core/blob/main/{path}"
        metadata = entry["metadata"]["library"]

        assert source == expected
        assert metadata["steward"] == "cognovis-library-core"
        assert metadata["source_catalog"] == "cognovis-library-core"
        assert (core_root / path).is_file()


def test_platform_forge_requirements_resolve_to_platform_standard_sources() -> None:
    skill_entries = _library_entries("skills")
    standard_entries = _library_entries("standards")

    for forge_name in FORGE_NAMES:
        requires = set(skill_entries[forge_name].get("requires", []))
        assert CORE_STANDARD_REQUIRES <= requires

    for standard_name in CORE_STANDARD_PATHS:
        entry = standard_entries[standard_name]
        assert "cognovis/library-core" in str(entry["source"])
        assert "github.com/cognovis/library/" not in str(entry["source"])


def test_platform_forges_install_and_sync_from_local_catalog(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    core_root = _core_root()
    skill_entries = "\n".join(
        f"""    - name: {name}
      description: Platform forge fixture for {name}
      source: {core_root / "skills" / name / "SKILL.md"}
"""
        for name in FORGE_NAMES
    )
    (project / "library.yaml").write_text(
        f"""default_dirs:
  skills:
    - default: .agents/skills/
    - claude_bridge: .claude/skills/

library:
  skills:
{skill_entries}
  agents: []
  prompts: []
  standards: []
"""
    )

    for name in FORGE_NAMES:
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "skill", "use", name, "--json"],
            cwd=project,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (project / ".agents" / "skills" / name / "SKILL.md").is_file()

    sync_result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "skill", "sync", "--json"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert sync_result.returncode == 0, sync_result.stderr
    sync_payload = json.loads(sync_result.stdout)
    assert sync_payload["status"] == "ok"
    assert sorted(sync_payload["data"]["synced"]) == sorted(f"skill:{name}" for name in FORGE_NAMES)


def test_platform_standards_install_and_sync_from_local_catalog(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    core_root = _core_root()
    standard_entries = "\n".join(
        f"""    - name: {name}
      description: Platform standard fixture for {name}
      source: {core_root / path}
"""
        for name, path in CORE_STANDARD_PATHS.items()
    )
    (project / "library.yaml").write_text(
        f"""default_dirs:
  standards:
    - default: .agents/standards/

library:
  skills: []
  agents: []
  prompts: []
  standards:
{standard_entries}
"""
    )

    for name, path in CORE_STANDARD_PATHS.items():
        result = subprocess.run(
            [sys.executable, str(LIBRARY_PY), "standard", "use", name, "--json"],
            cwd=project,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (project / ".agents" / "standards" / name / Path(path).name).is_file()

    sync_result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "standard", "sync", "--json"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert sync_result.returncode == 0, sync_result.stderr
    sync_payload = json.loads(sync_result.stdout)
    assert sync_payload["status"] == "ok"
    assert sorted(sync_payload["data"]["synced"]) == sorted(
        f"standard:{name}" for name in CORE_STANDARD_PATHS
    )
