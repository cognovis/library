from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.manager_inventory import (
    ConsumerUpdaterInventoryAdapter,
    ProjectToolingInventoryAdapter,
    collect_managed_paths,
)


class _FakeInventory:
    name = "fixture-manager"

    def managed_paths(self) -> set[Path]:
        return {Path("/tmp/example"), Path("/tmp/another")}


def test_collect_managed_paths_preserves_manager_identity() -> None:
    assert collect_managed_paths([_FakeInventory()]) == {
        "/tmp/example": "fixture-manager",
        "/tmp/another": "fixture-manager",
    }


def test_legacy_project_manager_adapters_report_exact_targets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = tmp_path / "consumer-projects.yml"
    manifest.write_text(
        "version: 1\n"
        "consumers:\n"
        "  - name: fixture\n"
        f"    root: {project}\n"
        "    managed_files:\n"
        "      - source: source.py\n"
        "        target: scripts/managed.py\n"
    )
    catalog = {
        "project_tooling": [
            {
                "name": "gitignore-policy",
                "target_kind": "gitignore_patch",
                "target_path": ".gitignore",
            }
        ]
    }

    managed = collect_managed_paths(
        [
            ProjectToolingInventoryAdapter(catalog, project),
            ConsumerUpdaterInventoryAdapter(manifest, project),
        ]
    )

    assert managed == {
        str((project / ".gitignore").resolve()): "project-tooling",
        str((project / "scripts/managed.py").resolve()): "consumer-updater",
    }
