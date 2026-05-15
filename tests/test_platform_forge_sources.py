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


def _library_entries() -> dict[str, dict[str, object]]:
    data = yaml.safe_load((REPO_ROOT / "library.yaml").read_text())
    entries = data["library"]["skills"]
    return {entry["name"]: entry for entry in entries}


def test_platform_forge_source_urls_match_checked_in_files() -> None:
    entries = _library_entries()

    for name in FORGE_NAMES:
        source = str(entries[name]["source"])
        expected = f"https://github.com/cognovis/library/blob/main/skills/{name}/SKILL.md"
        assert source == expected
        assert (REPO_ROOT / "skills" / name / "SKILL.md").is_file()


def test_platform_forges_install_and_sync_from_local_catalog(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    skill_entries = "\n".join(
        f"""    - name: {name}
      description: Platform forge fixture for {name}
      source: {REPO_ROOT / "skills" / name / "SKILL.md"}
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
