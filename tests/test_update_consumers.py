from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "update-consumers.py"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("update_consumers", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load_module()


def write_manifest(tmp_path: Path, root: Path, source: Path) -> Path:
    manifest = {
        "version": 1,
        "consumers": [
            {
                "name": "fixture",
                "root": str(root),
                "library_entries": [
                    {
                        "primitive": "standard",
                        "name": "seed-data-parity",
                        "scope": "project",
                        "harness": "all",
                    }
                ],
                "managed_files": [
                    {
                        "source": str(source),
                        "target": "scripts/refinement/check-seed-data-parity.py",
                        "mode": "0755",
                    }
                ],
            }
        ],
    }
    path = tmp_path / "consumer-projects.yml"
    path.write_text(yaml.safe_dump(manifest))
    return path


def ok_runner(calls: list[list[str]]):
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"status":"dry-run","operations":[]}',
            stderr="",
        )

    return run


def test_dry_run_reports_missing_file_without_mutating_target(tmp_path: Path) -> None:
    root = tmp_path / "consumer"
    root.mkdir()
    source = tmp_path / "source.py"
    source.write_text("print('new')\n")
    manifest = write_manifest(tmp_path, root, source)
    calls: list[list[str]] = []

    result = M.run_update(
        manifest_path=manifest,
        library_cli=tmp_path / "scripts" / "library.py",
        apply=False,
        runner=ok_runner(calls),
    )

    target = root / "scripts/refinement/check-seed-data-parity.py"
    assert result["status"] == "ok"
    assert result["mode"] == "dry-run"
    assert result["planned_changed_files"] == [str(target)]
    assert not target.exists()
    assert calls
    assert "--dry-run" in calls[0]
    assert calls[0][1:5] == [
        str(tmp_path / "scripts" / "library.py"),
        "standard",
        "sync",
        "seed-data-parity",
    ]


def test_apply_copies_changed_file_and_runs_sync_without_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "consumer"
    root.mkdir()
    target = root / "scripts/refinement/check-seed-data-parity.py"
    target.parent.mkdir(parents=True)
    target.write_text("old\n")
    source = tmp_path / "source.py"
    source.write_text("new\n")
    manifest = write_manifest(tmp_path, root, source)
    calls: list[list[str]] = []

    result = M.run_update(
        manifest_path=manifest,
        library_cli=tmp_path / "scripts" / "library.py",
        apply=True,
        runner=ok_runner(calls),
    )

    assert result["status"] == "ok"
    assert result["mode"] == "apply"
    assert result["changed_files"] == [str(target)]
    assert target.read_text() == "new\n"
    assert M.file_mode(target) == "0755"
    assert "--dry-run" not in calls[0]


def test_missing_consumer_root_reports_error_without_running_sync(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("new\n")
    missing_root = tmp_path / "missing"
    manifest = write_manifest(tmp_path, missing_root, source)
    calls: list[list[str]] = []

    result = M.run_update(
        manifest_path=manifest,
        library_cli=tmp_path / "scripts" / "library.py",
        apply=False,
        runner=ok_runner(calls),
    )

    assert result["status"] == "error"
    assert "consumer root does not exist" in result["errors"][0]
    assert calls == []


def test_json_report_contains_per_consumer_actions(tmp_path: Path) -> None:
    root = tmp_path / "consumer"
    root.mkdir()
    source = tmp_path / "source.py"
    source.write_text("new\n")
    manifest = write_manifest(tmp_path, root, source)

    result = M.run_update(
        manifest_path=manifest,
        library_cli=tmp_path / "scripts" / "library.py",
        apply=False,
        runner=ok_runner([]),
    )

    assert set(result) >= {
        "status",
        "mode",
        "manifest",
        "consumers",
        "changed_files",
        "planned_changed_files",
        "errors",
    }
    consumer = result["consumers"][0]
    assert consumer["name"] == "fixture"
    assert consumer["library_actions"][0]["primitive"] == "standard"
    assert consumer["file_actions"][0]["status"] == "missing"


def test_unknown_consumer_filter_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "consumer"
    root.mkdir()
    source = tmp_path / "source.py"
    source.write_text("new\n")
    manifest = write_manifest(tmp_path, root, source)

    result = M.run_update(
        manifest_path=manifest,
        selected_consumers=["absent"],
        library_cli=tmp_path / "scripts" / "library.py",
        apply=False,
        runner=ok_runner([]),
    )

    assert result["status"] == "error"
    assert result["errors"] == ["unknown consumers: absent"]
    assert result["consumers"] == []
