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
    (project / "Justfile").write_text(
        "set positional-arguments\n\nimport? '.agents/just/Justfile'\n"
    )
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


def _bundle_project(tmp_path: Path) -> Path:
    project = tmp_path / "consumer"
    source = tmp_path / "sources" / "workbench"
    project.mkdir()
    source.mkdir(parents=True)
    (source / "index.ts").write_text('export { value } from "./lib/value.ts";\n')
    (source / "lib").mkdir()
    (source / "lib" / "value.ts").write_text('export const value = "ready";\n')
    (source / "prompts").mkdir()
    (source / "prompts" / "system.md").write_text("Use the managed profile.\n")
    catalog = {
        "library": {
            "pi_extensions": [
                {
                    "name": "workbench",
                    "source": str(source),
                    "bundle": True,
                    "entrypoint": "index.ts",
                }
            ]
        }
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    return project


def test_canonical_fusion_dry_run_resolves_complete_closure_without_mutation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "fusion-consumer"
    project.mkdir()
    initialized = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert initialized.returncode == 0, initialized.stderr
    before = sorted(path.relative_to(project) for path in project.rglob("*"))

    result = _run(
        project,
        "just-module",
        "use",
        "fusion-harness",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry-run"
    assert payload["dependency_order"] == [
        "pi-extension:acpx-workbench",
        "pi-profile:pi-workbench",
        "just-module:pi-workbench",
        "pi-extension:fusion-harness",
        "pi-profile:fusion-workhorse",
        "pi-profile:fusion-sota",
        "just-module:fusion-harness",
    ]
    assert {
        Path(path).relative_to(project).as_posix()
        for path in payload["target_paths"]
    } == {
        ".agents/pi/extensions/acpx-workbench",
        ".agents/pi/extensions/fusion-harness",
        ".agents/pi/profiles/pi-workbench.json",
        ".agents/pi/profiles/fusion-workhorse.json",
        ".agents/pi/profiles/fusion-sota.json",
        ".agents/just/pi-workbench.just",
        ".agents/just/fusion-harness.just",
    }
    assert sorted(path.relative_to(project) for path in project.rglob("*")) == before
    assert not (project / "library.yaml").exists()
    assert not (project / "Justfile").exists()


def test_project_native_dependency_lifecycle_and_just_import(tmp_path: Path) -> None:
    project = _project(tmp_path)
    justfile = project / "Justfile"
    root_checksum = hashlib.sha256(justfile.read_bytes()).hexdigest()

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (project / ".agents/pi/extensions/workbench.ts").is_file()
    assert (project / ".agents/pi/profiles/development.json").is_file()
    assert (project / ".agents/just/workbench.just").is_file()
    assert "import 'workbench.just'" in (
        project / ".agents/just/Justfile"
    ).read_text()
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
    assert not (project / ".agents/just/Justfile").exists()


def test_pi_extension_bundle_lifecycle(tmp_path: Path) -> None:
    project = _bundle_project(tmp_path)
    target = project / ".agents/pi/extensions/workbench"

    installed = _run(project, "pi-extension", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (target / "index.ts").is_file()
    assert (target / "lib/value.ts").is_file()
    assert (target / "prompts/system.md").is_file()

    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert lock["installed"][0]["checksum_type"] == "directory"
    assert lock["installed"][0]["install_target"] == str(target)

    audit = _run(project, "pi-extension", "audit", "--no-upstream")
    assert audit.returncode == 0, audit.stderr or audit.stdout
    assert json.loads(audit.stdout)["status"] == "clean"

    (target / "lib/value.ts").write_text('export const value = "drift";\n')
    drift = _run(project, "pi-extension", "audit", "--no-upstream")
    assert drift.returncode == 2
    assert json.loads(drift.stdout)["status"] == "drift"

    restored = _run(project, "pi-extension", "sync", "workbench")
    assert restored.returncode == 0, restored.stderr or restored.stdout
    assert '"ready"' in (target / "lib/value.ts").read_text()

    removed = _run(project, "pi-extension", "remove", "workbench")
    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert not target.exists()


def test_pi_extension_bundle_requires_safe_entrypoint(tmp_path: Path) -> None:
    project = _bundle_project(tmp_path)
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["pi_extensions"][0]["entrypoint"] = "../outside.ts"
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))

    result = _run(project, "pi-extension", "use", "workbench")
    assert result.returncode != 0
    assert "safe filename" in json.loads(result.stdout)["message"]
    assert not (project / ".agents").exists()


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


def test_pi_extension_bundle_rejects_symlink_escape_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    project = _bundle_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)

    result = _run(project, "pi-extension", "use", "workbench")
    assert result.returncode != 0
    assert "resolves outside" in json.loads(result.stdout)["message"]
    assert list(outside.iterdir()) == []
    assert not (project / ".library.lock").exists()
