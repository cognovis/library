from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.manager_inventory import (
    ConsumerUpdaterInventoryAdapter,
    ProjectToolingInventoryAdapter,
    canonical_manager_path,
    collect_managed_paths,
)


class _FakeInventory:
    name = "fixture-manager"

    def managed_paths(self) -> set[Path]:
        return {Path("/tmp/example"), Path("/tmp/another")}


def test_collect_managed_paths_preserves_manager_identity() -> None:
    assert collect_managed_paths([_FakeInventory()]) == {
        str(canonical_manager_path(Path("/tmp/example"))): "fixture-manager",
        str(canonical_manager_path(Path("/tmp/another"))): "fixture-manager",
    }


def test_collect_managed_paths_resolves_symlinked_ancestors_only(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    class _SymlinkedInventory:
        name = "chezmoi"

        def managed_paths(self) -> set[Path]:
            return {alias_parent / "managed.md"}

    assert collect_managed_paths([_SymlinkedInventory()]) == {
        str(real_parent / "managed.md"): "chezmoi"
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


def test_project_tooling_inventory_uses_consumer_profile_by_default(
    tmp_path: Path,
) -> None:
    catalog = {
        "project_tooling": [
            {
                "name": "consumer-file",
                "target_path": "consumer.md",
                "profiles": ["consumer"],
            },
            {
                "name": "marketplace-file",
                "target_path": "marketplace.md",
                "profiles": ["marketplace"],
            },
        ]
    }

    paths = ProjectToolingInventoryAdapter(catalog, tmp_path).managed_paths()

    assert paths == {(tmp_path / "consumer.md").resolve()}
