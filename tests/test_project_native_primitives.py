"""Lifecycle coverage for the temporary project-native Library bridge."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY = REPO_ROOT / "scripts" / "library.py"


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(project / "home")
    return subprocess.run(
        [sys.executable, str(LIBRARY), *args, "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "consumer"
    sources = tmp_path / "sources"
    project.mkdir()
    sources.mkdir()
    (sources / "workbench.ts").write_text("export const workbench = true;\n")
    (sources / "development.json").write_text('{"profile":"development"}\n')
    (sources / "workbench.just").write_text("workbench:\n    @echo workbench-ready\n")
    (project / "Justfile").write_text("import '.agents/just/workbench.just'\n")
    catalog = {
        "library": {
            "pi_extensions": [
                {"name": "workbench", "source": str(sources / "workbench.ts")}
            ],
            "pi_profiles": [
                {
                    "name": "development",
                    "source": str(sources / "development.json"),
                    "requires": ["pi-extension:workbench"],
                }
            ],
            "just_modules": [
                {
                    "name": "workbench",
                    "source": str(sources / "workbench.just"),
                    "requires": ["pi-profile:development"],
                }
            ],
        }
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    return project


def test_project_native_dependency_lifecycle_and_just_import(tmp_path: Path) -> None:
    project = _project(tmp_path)
    justfile = project / "Justfile"
    root_checksum = hashlib.sha256(justfile.read_bytes()).hexdigest()

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (project / ".agents/pi/extensions/workbench.ts").is_file()
    assert (project / ".agents/pi/profiles/development.json").is_file()
    assert (project / ".agents/just/workbench.just").is_file()
    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert [entry["type"] for entry in lock["installed"]] == [
        "pi-extension",
        "pi-profile",
        "just-module",
    ]
    assert hashlib.sha256(justfile.read_bytes()).hexdigest() == root_checksum

    if shutil.which("just"):
        listed = subprocess.run(
            ["just", "--list"], cwd=project, capture_output=True, text=True
        )
        assert listed.returncode == 0, listed.stderr
        assert "workbench" in listed.stdout

    audit = _run(project, "just-module", "audit", "--no-upstream")
    assert audit.returncode == 0, audit.stderr or audit.stdout
    assert json.loads(audit.stdout)["status"] == "clean"

    profile = project / ".agents/pi/profiles/development.json"
    profile.unlink()
    drift = _run(project, "pi-profile", "audit", "--no-upstream")
    assert drift.returncode == 2
    assert json.loads(drift.stdout)["status"] == "drift"
    restored = _run(project, "pi-profile", "sync", "development")
    assert restored.returncode == 0, restored.stderr or restored.stdout
    assert profile.is_file()

    source = tmp_path / "sources/workbench.just"
    source.write_text("workbench:\n    @echo updated-workbench\n")
    synced = _run(project, "just-module", "sync", "workbench")
    assert synced.returncode == 0, synced.stderr or synced.stdout
    assert "updated-workbench" in (project / ".agents/just/workbench.just").read_text()
    assert hashlib.sha256(justfile.read_bytes()).hexdigest() == root_checksum

    removed = _run(project, "just-module", "remove", "workbench")
    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert not (project / ".agents/just/workbench.just").exists()


def test_project_native_rejects_global_scope_before_mutation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = _run(project, "pi-extension", "use", "workbench", "--scope", "global")
    assert result.returncode != 0
    assert "project-only" in json.loads(result.stdout)["message"]
    assert not (project / ".agents").exists()
    assert not (project / ".library.lock").exists()


def test_project_native_rejects_traversal_before_mutation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["pi_extensions"].append(
        {
            "name": "../escape",
            "source": catalog["library"]["pi_extensions"][0]["source"],
        }
    )
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))

    result = _run(project, "pi-extension", "use", "../escape")
    assert result.returncode != 0
    assert "safe filename segment" in json.loads(result.stdout)["message"]
    assert not (project / ".agents").exists()
    assert not (project / ".library.lock").exists()


def test_project_native_rejects_symlink_escape_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)

    result = _run(project, "pi-extension", "use", "workbench")
    assert result.returncode != 0
    assert "resolves outside" in json.loads(result.stdout)["message"]
    assert list(outside.iterdir()) == []
    assert not (project / ".library.lock").exists()
