"""Catalog provenance coverage for CL-uoyu."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
CATALOG_IDENTITY = "https://github.com/example/catalog-a"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.installers.simple_file import install_simple_file  # noqa: E402
from lib.lockfile import compute_checksum, load_lockfile  # noqa: E402
from lib.sync_audit import cmd_audit_impl  # noqa: E402


def _catalog(*, include_entry: bool) -> dict:
    entries = []
    if include_entry:
        entries.append({"name": "fixture", "source": "/tmp/fixture.md"})
    return {
        "catalog_identity": CATALOG_IDENTITY,
        "default_dirs": {"prompts": [{"default": ".claude/commands/"}]},
        "library": {"prompts": entries},
    }


def _lock_entry(
    project: Path,
    *,
    catalog_identity: str | None,
) -> dict:
    target = project / ".claude" / "commands" / "fixture.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture\n", encoding="utf-8")
    entry = {
        "name": "fixture",
        "type": "prompt",
        "marketplace": "local",
        "source": "/tmp/fixture.md",
        "source_commit": "local",
        "cache_path": "",
        "install_target": str(target),
        "install_timestamp": "2026-07-20T08:00:00Z",
        "checksum_sha256": compute_checksum(target),
        "content_sha256": compute_checksum(target),
        "checksum_type": "file",
        "install_mode": "vendor",
        "license": "unknown",
        "bridge_symlinks": [],
    }
    if catalog_identity is not None:
        entry["catalog_identity"] = catalog_identity
    return entry


def _write_lockfile(project: Path, entry: dict) -> None:
    (project / ".library.lock").write_text(
        yaml.safe_dump({"installed": [entry]}, sort_keys=False),
        encoding="utf-8",
    )


def test_install_records_catalog_identity_after_lockfile_reload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    source = tmp_path / "fixture.md"
    home.mkdir()
    project.mkdir()
    source.write_text("fixture\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    catalog = _catalog(include_entry=True)
    catalog["library"]["prompts"][0]["source"] = str(source)

    install_simple_file(
        catalog=catalog,
        primitive_name="prompt",
        name="fixture",
        repo_root=project,
        scope="project",
    )

    reloaded = load_lockfile(project / ".library.lock")
    assert reloaded["installed"][0]["catalog_identity"] == CATALOG_IDENTITY


def test_audit_reports_same_catalog_orphan_with_removal_command(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_lockfile(
        project,
        _lock_entry(project, catalog_identity=CATALOG_IDENTITY),
    )

    result = cmd_audit_impl(
        _catalog(include_entry=False),
        "prompt",
        project,
        skip_upstream=True,
    )

    assert result["status"] == "drift"
    audited = result["entries"][0]
    assert audited["catalog_status"] == "orphaned"
    assert audited["catalog_identity"] == CATALOG_IDENTITY
    assert audited["removal_command"] == (
        "library prompt remove fixture --scope project"
    )


def test_audit_leaves_foreign_catalog_entry_clean(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_lockfile(
        project,
        _lock_entry(
            project,
            catalog_identity="https://github.com/example/catalog-b",
        ),
    )

    result = cmd_audit_impl(
        _catalog(include_entry=False),
        "prompt",
        project,
        skip_upstream=True,
    )

    assert result["status"] == "clean"
    assert result["entries"][0]["catalog_status"] == "foreign"
    assert "removal_command" not in result["entries"][0]


def test_foreign_same_name_ignores_current_catalog_upstream_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_lockfile(
        project,
        _lock_entry(
            project,
            catalog_identity="https://github.com/example/catalog-b",
        ),
    )

    monkeypatch.setattr(
        "lib.status.cmd_status_impl",
        lambda **_kwargs: {
            "entries": [
                {
                    "name": "fixture",
                    "primitive": "prompt",
                    "upstream_status": "behind",
                }
            ]
        },
    )
    result = cmd_audit_impl(
        _catalog(include_entry=True),
        "prompt",
        project,
    )

    audited = result["entries"][0]
    assert result["status"] == "clean"
    assert audited["catalog_status"] == "foreign"
    assert audited["upstream_status"] == "unknown"
    assert audited["drift"] is False


def test_audit_reports_legacy_entry_as_undetermined(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_lockfile(project, _lock_entry(project, catalog_identity=None))

    result = cmd_audit_impl(
        _catalog(include_entry=False),
        "prompt",
        project,
        skip_upstream=True,
    )

    assert result["status"] == "clean"
    audited = result["entries"][0]
    assert audited["catalog_status"] == "undetermined"
    assert audited["catalog_reason"] == "catalog_identity_missing"
    assert "removal_command" not in audited


def test_human_and_json_audit_name_orphan_catalog_and_removal_command(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    project.joinpath("library.yaml").write_text(
        yaml.safe_dump(_catalog(include_entry=False), sort_keys=False),
        encoding="utf-8",
    )
    _write_lockfile(
        project,
        _lock_entry(project, catalog_identity=CATALOG_IDENTITY),
    )
    env = {**os.environ, "HOME": str(home)}
    command = [
        sys.executable,
        str(LIBRARY_PY),
        "audit",
        "--scope",
        "project",
        "--project",
        str(project),
        "--no-upstream",
    ]

    human = subprocess.run(
        command,
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )
    structured = subprocess.run(
        [*command, "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )

    assert human.returncode == 2, human.stderr
    assert "ORPHANED from https://github.com/example/catalog-a" in human.stdout
    assert "library prompt remove fixture --scope project" in human.stdout
    assert structured.returncode == 2, structured.stderr
    audited = json.loads(structured.stdout)["entries"][0]
    assert audited["catalog_status"] == "orphaned"
    assert audited["removal_command"] == (
        "library prompt remove fixture --scope project"
    )
