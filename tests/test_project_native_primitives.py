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


def _run_for_target(
    project: Path, cwd: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(project / "home")
    return subprocess.run(
        [
            sys.executable,
            str(LIBRARY),
            *args,
            "--target-project",
            str(project),
            "--json",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "consumer"
    sources = tmp_path / "sources"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
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
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    source.mkdir(parents=True)
    (source / "index.ts").write_text('export { value } from "./lib/value.ts";\n')
    (source / "lib").mkdir()
    (source / "lib" / "value.ts").write_text('export const value = "ready";\n')
    (source / "prompts").mkdir()
    (source / "prompts" / "system.md").write_text("Use the managed profile.\n")
    (source / "package.json").write_text(
        json.dumps(
            {
                "name": "@example/pi-workbench",
                "private": True,
                "pi": {"extensions": ["./index.ts"]},
            }
        )
        + "\n"
    )
    catalog = {
        "library": {
            "pi_extensions": [
                {
                    "name": "workbench",
                    "source": str(source),
                    "bundle": True,
                    "entrypoint": "index.ts",
                    "pi_package": True,
                }
            ]
        }
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    return project


def _mixed_dependency_project(tmp_path: Path) -> Path:
    project = tmp_path / "mixed-consumer"
    sources = tmp_path / "mixed-sources"
    skill_source = sources / "helper"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    skill_source.mkdir(parents=True)
    (skill_source / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Mixed dependency fixture.\n---\n"
    )
    (sources / "workbench.just").write_text("workbench:\n    @echo mixed-ready\n")
    catalog = {
        "default_dirs": {
            "skills": [
                {"default": ".agents/skills/"},
                {"claude_bridge": ".claude/skills/"},
            ]
        },
        "library": {
            "skills": [{"name": "helper", "source": str(skill_source)}],
            "just_modules": [
                {
                    "name": "workbench",
                    "source": str(sources / "workbench.just"),
                    "requires": ["skill:helper"],
                }
            ],
        },
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
        "pi-extension:fusion-context",
        "pi-extension:fusion-harness",
        "pi-profile:fusion-workhorse",
        "pi-profile:fusion-sota",
        "just-module:fusion-harness",
    ]
    assert {
        Path(path).relative_to(project).as_posix() for path in payload["target_paths"]
    } == {
        ".agents/pi/extensions/acpx-workbench",
        ".agents/pi/extensions/fusion-context",
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


# Regression CL-1w5g: consumer repositories must see the aggregate Solo catalog root.
def test_fix_CL_1w5g_consumer_resolves_solo_workbench_closure(tmp_path: Path) -> None:
    project = tmp_path / "solo-consumer"
    project.mkdir()
    initialized = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert initialized.returncode == 0, initialized.stderr

    result = _run(project, "pi-extension", "use", "solo-workbench", "--dry-run")

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry-run"
    assert payload["dependency_order"][-1] == "pi-extension:solo-workbench"
    assert any(
        operation["operation"] == "register_pi_package"
        and operation["path"] == str(project / ".pi/settings.json")
        for operation in payload["operations"]
    )
    assert set(payload["dependency_order"]) == {
        "pi-extension:fusion-harness",
        "pi-extension:cognovis-bead-harness",
        "pi-extension:native-pack",
        "pi-extension:acpx-session-view",
        "pi-extension:fusion-context",
        "pi-profile:fusion-sota",
        "pi-extension:acpx-workbench",
        "pi-profile:pi-workbench",
        "pi-extension:docker-lifecycle-guard",
        "pi-profile:bead-high-assurance",
        "pi-profile:native-pack-standard",
        "pi-extension:solo-workbench",
    }
    assert not (project / ".agents").exists()
    assert not (project / ".library.lock").exists()


def test_project_native_dry_run_resolves_fuzzy_root_name_like_apply(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    planned = _run(project, "just-module", "use", "workb", "--dry-run")
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert json.loads(planned.stdout)["dependency_order"][-1] == (
        "just-module:workbench"
    )
    assert not (project / ".agents").exists()

    installed = _run(project, "just-module", "use", "workb")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (project / ".agents/just/workbench.just").is_file()


def test_project_native_dry_run_and_apply_support_mixed_dependencies(
    tmp_path: Path,
) -> None:
    project = _mixed_dependency_project(tmp_path)

    planned = _run(project, "just-module", "use", "workbench", "--dry-run")
    assert planned.returncode == 0, planned.stderr or planned.stdout
    payload = json.loads(planned.stdout)
    assert payload["dependency_order"] == [
        "skill:helper",
        "just-module:workbench",
    ]
    assert {
        Path(path).relative_to(project).as_posix() for path in payload["target_paths"]
    } >= {
        ".agents/skills/helper",
        ".agents/just/workbench.just",
    }
    assert not (project / ".agents").exists()
    assert not (project / ".library.lock").exists()

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (project / ".agents/skills/helper/SKILL.md").is_file()
    assert (project / ".agents/just/workbench.just").is_file()


def test_sync_reconciles_missing_project_native_dependencies(tmp_path: Path) -> None:
    project = _project(tmp_path)
    initialized = subprocess.run(
        ["git", "init", "--quiet"], cwd=project, capture_output=True, text=True
    )
    assert initialized.returncode == 0, initialized.stderr
    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout

    lock_path = project / ".library.lock"
    lock = yaml.safe_load(lock_path.read_text())
    lock["installed"] = [
        entry for entry in lock["installed"] if entry["type"] != "pi-extension"
    ]
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
    (project / ".agents/pi/extensions/workbench.ts").unlink()

    planned = _run(project, "sync", "--dry-run")
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert json.loads(planned.stdout)["reconciled_dependencies"] == [
        "pi-extension:workbench"
    ]
    assert not (project / ".agents/pi/extensions/workbench.ts").exists()
    assert all(
        entry["type"] != "pi-extension"
        for entry in yaml.safe_load(lock_path.read_text())["installed"]
    )

    synced = _run(project, "sync")
    assert synced.returncode == 0, synced.stderr or synced.stdout
    payload = json.loads(synced.stdout)
    assert payload["reconciled_dependencies"] == ["pi-extension:workbench"]
    assert (project / ".agents/pi/extensions/workbench.ts").is_file()
    repaired_lock = yaml.safe_load(lock_path.read_text())
    assert any(
        entry["type"] == "pi-extension" and entry["name"] == "workbench"
        for entry in repaired_lock["installed"]
    )


def test_project_native_dependency_lifecycle_and_just_import(tmp_path: Path) -> None:
    project = _project(tmp_path)
    justfile = project / "Justfile"
    root_checksum = hashlib.sha256(justfile.read_bytes()).hexdigest()

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (project / ".agents/pi/extensions/workbench.ts").is_file()
    assert (project / ".agents/pi/profiles/development.json").is_file()
    assert (project / ".agents/just/workbench.just").is_file()
    assert "import 'workbench.just'" in (project / ".agents/just/Justfile").read_text()
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


def test_project_native_remove_resolves_portable_targets_from_other_cwd(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout

    removed = _run_for_target(
        project, elsewhere, "just-module", "remove", "workbench"
    )

    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert not (project / ".agents/just/workbench.just").exists()
    assert not (project / ".agents/just/Justfile").exists()


def test_just_module_bootstraps_missing_root_justfile(tmp_path: Path) -> None:
    """A project without a root justfile still gets a runnable entry point.

    `just` only discovers a justfile in the invocation directory or a parent,
    so the generated .agents/just/Justfile is unreachable on its own.
    """
    project = _project(tmp_path)
    (project / "Justfile").unlink()

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    root = project / "Justfile"
    assert root.is_file()
    assert "import? '.agents/just/Justfile'" in root.read_text()

    if shutil.which("just"):
        listed = subprocess.run(
            ["just", "--list"], cwd=project, capture_output=True, text=True
        )
        assert listed.returncode == 0, listed.stderr
        assert "workbench" in listed.stdout

        # Recipes are written against repository-root-relative paths, so the
        # working directory must be the repository root, not .agents/just.
        (project / ".agents/just/workbench.just").write_text("workbench:\n    @pwd\n")
        ran = subprocess.run(
            ["just", "workbench"], cwd=project, capture_output=True, text=True
        )
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout.strip() == str(project.resolve())
        restored = _run(project, "just-module", "sync", "workbench")
        assert restored.returncode == 0, restored.stderr or restored.stdout

    removed = _run(project, "just-module", "remove", "workbench")
    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert not root.exists()


def test_just_module_preserves_hand_written_root_justfile(tmp_path: Path) -> None:
    project = _project(tmp_path)
    root = project / "Justfile"
    root.write_text("set positional-arguments\n\nbuild:\n    @echo building\n")

    installed = _run(project, "just-module", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    text = root.read_text()
    assert "build:\n    @echo building\n" in text
    assert "import? '.agents/just/Justfile'" in text
    assert text.count("import?") == 1

    # Re-installing must not stack duplicate managed blocks.
    again = _run(project, "just-module", "use", "workbench")
    assert again.returncode == 0, again.stderr or again.stdout
    assert root.read_text() == text

    removed = _run(project, "just-module", "remove", "workbench")
    assert removed.returncode == 0, removed.stderr or removed.stdout
    survivor = root.read_text()
    assert "build:\n    @echo building\n" in survivor
    assert "import?" not in survivor


def test_pi_extension_bundle_lifecycle(tmp_path: Path) -> None:
    project = _bundle_project(tmp_path)
    target = project / ".agents/pi/extensions/workbench"
    settings_path = project / ".pi/settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps({"theme": "dark", "packages": ["npm:existing-package"]}) + "\n"
    )

    installed = _run(project, "pi-extension", "use", "workbench")
    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (target / "index.ts").is_file()
    assert (target / "lib/value.ts").is_file()
    assert (target / "prompts/system.md").is_file()
    settings = json.loads(settings_path.read_text())
    assert settings == {
        "theme": "dark",
        "packages": [
            "npm:existing-package",
            "../.agents/pi/extensions/workbench",
        ],
    }

    lock = yaml.safe_load((project / ".library.lock").read_text())
    assert lock["installed"][0]["checksum_type"] == "directory"
    assert lock["installed"][0]["install_target"] == ".agents/pi/extensions/workbench"

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
    assert json.loads(settings_path.read_text())["packages"] == [
        "npm:existing-package",
        "../.agents/pi/extensions/workbench",
    ]

    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "packages": [
                    "npm:existing-package",
                    "../.agents/pi/extensions/workbench",
                ],
            }
        )
        + "\n"
    )
    removed = _run(project, "pi-extension", "remove", "workbench")
    assert removed.returncode == 0, removed.stderr or removed.stdout
    assert not target.exists()
    assert json.loads(settings_path.read_text()) == {
        "theme": "dark",
        "packages": ["npm:existing-package"],
    }


def test_pi_extension_bundle_dry_run_reports_pi_registration(tmp_path: Path) -> None:
    project = _bundle_project(tmp_path)

    result = _run(project, "pi-extension", "use", "workbench", "--dry-run")

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert any(
        operation["operation"] == "register_pi_package"
        and operation["path"] == str(project / ".pi/settings.json")
        for operation in payload["operations"]
    )
    assert not (project / ".pi").exists()


def test_pi_package_bundle_requires_matching_manifest_before_mutation(
    tmp_path: Path,
) -> None:
    project = _bundle_project(tmp_path)
    source_manifest = tmp_path / "sources/workbench/package.json"
    source_manifest.write_text(json.dumps({"name": "broken", "pi": {}}) + "\n")

    result = _run(project, "pi-extension", "use", "workbench")

    assert result.returncode != 0
    assert "non-empty pi.extensions" in json.loads(result.stdout)["message"]
    assert not (project / ".agents").exists()
    assert not (project / ".pi").exists()
    assert not (project / ".library.lock").exists()


def test_pi_extension_bundle_requires_safe_entrypoint(tmp_path: Path) -> None:
    project = _bundle_project(tmp_path)
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    catalog["library"]["pi_extensions"][0]["entrypoint"] = "../outside.ts"
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))

    result = _run(project, "pi-extension", "use", "workbench")
    assert result.returncode != 0
    assert "safe filename" in json.loads(result.stdout)["message"]
    assert not (project / ".agents").exists()


def test_project_native_rejects_a_scope_flag_before_mutation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = _run(project, "pi-extension", "use", "workbench", "--scope", "global")
    assert result.returncode != 0
    assert json.loads(result.stdout)["message"] == (
        "`--scope` is not a Library option: Library manages the current Git "
        "repository only. Re-run the command without `--scope`."
    )
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


# Regression CL-2i17: a root install must not retain an older direct install of
# one of its own dependencies.
def _stale_closure_catalog(
    sources: Path,
    *,
    dep_version: str,
    dep_has_source: bool = True,
    with_root: bool = False,
) -> dict:
    old_dep: dict = {"name": "old-dep", "version": dep_version}
    if dep_has_source:
        old_dep["source"] = str(sources / "old-dep.ts")
    extensions: list[dict] = [
        old_dep,
        {
            "name": "steady-dep",
            "source": str(sources / "steady-dep.ts"),
            "version": "1.0.0",
        },
    ]
    if with_root:
        extensions.append(
            {
                "name": "new-root",
                "source": str(sources / "new-root.ts"),
                "requires": ["pi-extension:old-dep", "pi-extension:steady-dep"],
            }
        )
    return {"library": {"pi_extensions": extensions}}


def _stale_closure_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "stale-consumer"
    sources = tmp_path / "stale-sources"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    sources.mkdir()
    (sources / "old-dep.ts").write_text("export const dep = 1;\n")
    (sources / "steady-dep.ts").write_text("export const steady = true;\n")
    (sources / "new-root.ts").write_text("export const root = true;\n")
    (project / "library.yaml").write_text(
        yaml.safe_dump(
            _stale_closure_catalog(sources, dep_version="1.0.0"), sort_keys=False
        )
    )
    return project, sources


def _lock_entries(project: Path) -> dict[str, dict]:
    lock = yaml.safe_load((project / ".library.lock").read_text())
    return {f"{e['type']}:{e['name']}": e for e in lock.get("installed", [])}


def _requested_roots(project: Path) -> dict[str, dict]:
    lock = yaml.safe_load((project / ".library.lock").read_text())
    return {root["id"]: root for root in lock.get("requested_roots", [])}


def _tree_snapshot(project: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(project).as_posix()] = path.read_text()
    return snapshot


def test_root_install_refreshes_stale_project_native_dependency(
    tmp_path: Path,
) -> None:
    """Old/new mixed closure: the stale direct root is refreshed, the current one is not."""
    project, sources = _stale_closure_project(tmp_path)
    extensions = project / ".agents" / "pi" / "extensions"

    for dependency in ("old-dep", "steady-dep"):
        installed = _run(project, "pi-extension", "use", dependency)
        assert installed.returncode == 0, installed.stderr or installed.stdout

    assert (extensions / "old-dep.ts").read_text() == "export const dep = 1;\n"
    before = _lock_entries(project)
    old_before = before["pi-extension:old-dep"]
    steady_before = before["pi-extension:steady-dep"]
    roots_before = _requested_roots(project)
    assert old_before["version"] == "1.0.0"
    assert roots_before["pi-extension:old-dep"]["resolved_version"] == "1.0.0"

    # The active catalog moves old-dep to 2.0.0 with new content and publishes a
    # root that requires it; steady-dep keeps its contract.
    (sources / "old-dep.ts").write_text("export const dep = 2;\n")
    (project / "library.yaml").write_text(
        yaml.safe_dump(
            _stale_closure_catalog(sources, dep_version="2.0.0", with_root=True),
            sort_keys=False,
        )
    )

    result = _run(project, "pi-extension", "use", "new-root")
    assert result.returncode == 0, result.stderr or result.stdout

    # The stale member is refreshed: deployed bytes AND lockfile provenance.
    after = _lock_entries(project)
    old_after = after["pi-extension:old-dep"]
    assert (extensions / "old-dep.ts").read_text() == "export const dep = 2;\n"
    assert old_after["version"] == "2.0.0"
    assert (
        old_after["content_sha256"]
        == hashlib.sha256(b"export const dep = 2;\n").hexdigest()
    )
    assert old_after["content_sha256"] != old_before["content_sha256"]
    assert old_after["install_timestamp"] >= old_before["install_timestamp"]

    # The contract-current member is untouched: no churn, provenance identical.
    assert (extensions / "steady-dep.ts").read_text() == "export const steady = true;\n"
    assert after["pi-extension:steady-dep"] == steady_before

    # The root is installed after its dependencies.
    assert (extensions / "new-root.ts").is_file()
    assert "pi-extension:new-root" in after

    # The refreshed dependency keeps its direct-root ownership and scope.
    assert old_after["scope"] == "project"
    roots_after = _requested_roots(project)
    assert roots_after["pi-extension:old-dep"]["scope"] == "project"
    assert roots_after["pi-extension:old-dep"]["resolved_version"] == "2.0.0"


def test_unrefreshable_stale_project_native_dependency_blocks_root_install(
    tmp_path: Path,
) -> None:
    """A stale member the catalog cannot supply fails before any mutation."""
    project, sources = _stale_closure_project(tmp_path)
    installed = _run(project, "pi-extension", "use", "old-dep")
    assert installed.returncode == 0, installed.stderr or installed.stdout

    # old-dep is bumped but the active catalog no longer declares a source for
    # it, so it can neither be verified nor refreshed.
    (project / "library.yaml").write_text(
        yaml.safe_dump(
            _stale_closure_catalog(
                sources, dep_version="2.0.0", dep_has_source=False, with_root=True
            ),
            sort_keys=False,
        )
    )
    before = _tree_snapshot(project)

    result = _run(project, "pi-extension", "use", "new-root")

    assert result.returncode != 0, result.stdout
    message = result.stdout + result.stderr
    assert "old-dep" in message
    assert "has no source field" in message

    # Pre-root non-mutation: nothing installed, nothing rewritten.
    assert not (project / ".agents" / "pi" / "extensions" / "new-root.ts").exists()
    assert _tree_snapshot(project) == before
    assert "pi-extension:new-root" not in _lock_entries(project)
