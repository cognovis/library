from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import LockfileError
from lib.lockfile import load_lockfile, save_lockfile


def _legacy_entry() -> dict:
    return {
        "name": "python-dev",
        "type": "skill",
        "marketplace": "cognovis-library-core",
        "catalog_identity": "https://github.com/cognovis/library-core",
        "source": "https://github.com/cognovis/library-core/blob/main/skills/python-dev/SKILL.md",
        "source_commit": "a" * 40,
        "cache_path": "/tmp/cache/python-dev",
        "install_target": ".agents/skills/python-dev/",
        "install_timestamp": "2026-08-05T10:00:00Z",
        "checksum_sha256": "b" * 64,
        "checksum_type": "directory",
        "content_sha256": "b" * 64,
        "install_mode": "vendor",
        "license": "proprietary",
        "bridge_symlinks": [],
    }


def test_v1_load_migrates_to_v2_without_deletion_authority(tmp_path: Path) -> None:
    path = tmp_path / ".library.lock"
    path.write_text(yaml.safe_dump({"installed": [_legacy_entry()]}))

    lock = load_lockfile(path)

    assert lock["schema_version"] == 2
    assert lock["migration"] == {"prune_ack_required": True}
    assert lock["requested_roots"][0]["id"] == "skill:python-dev"
    assert lock["receipts"][0]["verified"] is False
    assert lock["receipts"][0]["prune_blocked_reason"] == "legacy-unverified"
    assert lock["installed"][0]["name"] == "python-dev"


def test_project_lock_migration_keeps_absolute_install_targets_project_scoped(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".library.lock"
    entry = _legacy_entry()
    entry["install_target"] = str(
        tmp_path / ".agents" / "skills" / "python-dev"
    )
    path.write_text(yaml.safe_dump({"installed": [entry]}))

    lock = load_lockfile(path)

    assert lock["requested_roots"][0]["scope"] == "project"
    assert lock["receipts"][0]["scope"] == "project"


def test_v2_save_keeps_installed_as_derived_compatibility_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".library.lock"
    path.write_text(yaml.safe_dump({"installed": [_legacy_entry()]}))
    lock = load_lockfile(path)

    save_lockfile(path, lock)
    persisted = yaml.safe_load(path.read_text())

    assert persisted["schema_version"] == 2
    assert persisted["requested_roots"][0]["id"] == "skill:python-dev"
    assert persisted["receipts"][0]["name"] == "python-dev"
    assert persisted["installed"][0]["name"] == "python-dev"


def test_project_lock_save_serializes_project_targets_relative_to_lock_root(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".library.lock"
    cache = tmp_path.parent / "cache" / "python-dev"
    install_target = tmp_path / ".agents" / "skills" / "python-dev"
    bridge = tmp_path / ".claude" / "skills" / "python-dev"
    entry = _legacy_entry()
    entry.update(
        {
            "scope": "project",
            "cache_path": str(cache),
            "install_target": f"{install_target}/",
            "bridge_symlinks": [
                f"{bridge} -> {install_target}",
                f"{bridge}-cache -> {cache}",
            ],
        }
    )
    lock = {
        "schema_version": 2,
        "migration": {"prune_ack_required": False},
        "requested_roots": [],
        "receipts": [
            {
                **entry,
                "id": "skill:python-dev",
                "resolved_version": "1.0.0",
                "verified": True,
                "adopted": False,
                "prune_blocked_reason": None,
                "targets": [
                    {
                        "path": str(install_target / "SKILL.md"),
                        "kind": "file",
                        "content_sha256": "b" * 64,
                    },
                    {
                        "path": str(bridge),
                        "kind": "symlink",
                        "link_target": "../../.agents/skills/python-dev",
                    },
                ],
                "owners_cache": ["workspace:python-cli"],
            }
        ],
        "prerequisites": [],
        "installed": [entry],
    }

    save_lockfile(path, lock)
    persisted = yaml.safe_load(path.read_text())

    receipt = persisted["receipts"][0]
    installed = persisted["installed"][0]
    assert receipt["install_target"] == ".agents/skills/python-dev/"
    assert installed["install_target"] == ".agents/skills/python-dev/"
    assert receipt["targets"][0]["path"] == ".agents/skills/python-dev/SKILL.md"
    assert receipt["targets"][1]["path"] == ".claude/skills/python-dev"
    assert receipt["bridge_symlinks"] == [
        ".claude/skills/python-dev -> .agents/skills/python-dev",
        f".claude/skills/python-dev-cache -> {cache}",
    ]
    assert receipt["cache_path"] == str(cache)
    assert lock["receipts"][0]["install_target"] == f"{install_target}/"


def test_newer_lockfile_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / ".library.lock"
    path.write_text(yaml.safe_dump({"schema_version": 3, "installed": []}))

    with pytest.raises(LockfileError, match="Unsupported lockfile schema_version"):
        load_lockfile(path)
