#!/usr/bin/env python3
"""Controlled updater for projects that consume Library-managed primitives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "consumer-projects.yml"
DEFAULT_LIBRARY_CLI = REPO_ROOT / "scripts" / "library.py"

Runner = Callable[..., subprocess.CompletedProcess[str]]


def expand_path(value: str, *, base: Path) -> Path:
    """Expand ~, environment variables, and manifest-relative paths."""
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and validate a consumer update manifest."""
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    consumers = raw.get("consumers")
    if not isinstance(consumers, list):
        raise ValueError(f"{path}: consumers must be a list")
    for index, consumer in enumerate(consumers):
        if not isinstance(consumer, dict):
            raise ValueError(f"{path}: consumers[{index}] must be a mapping")
        for key in ("name", "root"):
            if not isinstance(consumer.get(key), str) or not consumer[key]:
                raise ValueError(f"{path}: consumers[{index}].{key} must be a string")
        entries = consumer.get("library_entries", [])
        files = consumer.get("managed_files", [])
        if not isinstance(entries, list):
            raise ValueError(f"{path}: consumers[{index}].library_entries must be a list")
        if not isinstance(files, list):
            raise ValueError(f"{path}: consumers[{index}].managed_files must be a list")
    return raw


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}"


def planned_file_action(
    *,
    source: Path,
    target: Path,
    mode: str | None,
) -> dict[str, Any]:
    """Return the file action needed to reconcile source and target."""
    action: dict[str, Any] = {
        "source": str(source),
        "target": str(target),
        "status": "current",
        "changed": False,
        "reason": "",
    }
    if not source.is_file():
        action.update(
            {
                "status": "error",
                "reason": "source_missing",
                "changed": False,
            }
        )
        return action
    if not target.exists():
        action.update({"status": "missing", "reason": "target_missing", "changed": True})
        return action
    if not target.is_file():
        action.update({"status": "error", "reason": "target_not_file", "changed": False})
        return action
    if sha256_file(source) != sha256_file(target):
        action.update({"status": "stale", "reason": "content_diff", "changed": True})
        return action
    if mode and file_mode(target) != mode:
        action.update({"status": "stale", "reason": "mode_diff", "changed": True})
        return action
    return action


def apply_file_action(action: dict[str, Any], *, mode: str | None) -> None:
    """Apply a planned managed-file action."""
    if not action.get("changed"):
        return
    if action.get("status") == "error":
        return
    source = Path(action["source"])
    target = Path(action["target"])
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if mode:
        target.chmod(int(mode, 8))


def _run(
    runner: Runner,
    command: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def default_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(*args, **kwargs)


def sync_entry(
    *,
    entry: dict[str, Any],
    consumer_root: Path,
    library_cli: Path,
    apply: bool,
    runner: Runner,
) -> dict[str, Any]:
    primitive = entry.get("primitive") or entry.get("type")
    name = entry.get("name")
    scope = entry.get("scope", "project")
    harness = entry.get("harness", "all")
    action: dict[str, Any] = {
        "primitive": primitive,
        "name": name,
        "scope": scope,
        "status": "planned" if not apply else "ok",
        "changed": bool(apply),
        "command": [],
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }
    if not isinstance(primitive, str) or not isinstance(name, str):
        action.update({"status": "error", "stderr": "entry requires primitive and name"})
        return action

    command = [
        sys.executable,
        str(library_cli),
        primitive,
        "sync",
        name,
        "--scope",
        str(scope),
        "--target-project",
        str(consumer_root),
        "--harness",
        str(harness),
        "--json",
    ]
    if not apply:
        command.append("--dry-run")
    action["command"] = command

    result = _run(runner, command, cwd=library_cli.parent.parent)
    action["exit_code"] = result.returncode
    action["stdout"] = result.stdout
    action["stderr"] = result.stderr
    if result.returncode != 0:
        action["status"] = "error"
        action["changed"] = False
    return action


def update_consumer(
    *,
    consumer: dict[str, Any],
    manifest_dir: Path,
    library_cli: Path,
    apply: bool,
    runner: Runner,
) -> dict[str, Any]:
    root = expand_path(consumer["root"], base=manifest_dir)
    report: dict[str, Any] = {
        "name": consumer["name"],
        "root": str(root),
        "status": "ok",
        "library_actions": [],
        "file_actions": [],
        "changed_files": [],
        "planned_changed_files": [],
        "errors": [],
    }

    if not root.is_dir():
        report["status"] = "error"
        report["errors"].append(f"consumer root does not exist: {root}")
        return report

    for entry in consumer.get("library_entries", []):
        action = sync_entry(
            entry=entry,
            consumer_root=root,
            library_cli=library_cli,
            apply=apply,
            runner=runner,
        )
        report["library_actions"].append(action)
        if action["status"] == "error":
            report["status"] = "error"
            report["errors"].append(
                f"library sync failed for {action.get('primitive')}:{action.get('name')}"
            )

    for item in consumer.get("managed_files", []):
        if not isinstance(item, dict):
            report["status"] = "error"
            report["errors"].append("managed_files entries must be mappings")
            continue
        source_raw = item.get("source")
        target_raw = item.get("target")
        mode = item.get("mode")
        if not isinstance(source_raw, str) or not isinstance(target_raw, str):
            report["status"] = "error"
            report["errors"].append("managed file requires source and target")
            continue
        if mode is not None and not isinstance(mode, str):
            report["status"] = "error"
            report["errors"].append(f"managed file mode must be a string: {target_raw}")
            continue
        source = expand_path(source_raw, base=manifest_dir)
        target = root / target_raw
        action = planned_file_action(source=source, target=target, mode=mode)
        if apply:
            apply_file_action(action, mode=mode)
        report["file_actions"].append(action)
        if action["status"] == "error":
            report["status"] = "error"
            report["errors"].append(f"{action['reason']}: {target}")
        elif action["changed"]:
            if apply:
                report["changed_files"].append(str(target))
            else:
                report["planned_changed_files"].append(str(target))

    return report


def run_update(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    selected_consumers: list[str] | None = None,
    library_cli: Path = DEFAULT_LIBRARY_CLI,
    apply: bool = False,
    runner: Runner = default_runner,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    manifest_dir = manifest_path.parent
    selected = set(selected_consumers or [])
    consumers = [
        consumer
        for consumer in manifest["consumers"]
        if not selected or consumer["name"] in selected
    ]
    result: dict[str, Any] = {
        "status": "ok",
        "mode": "apply" if apply else "dry-run",
        "manifest": str(manifest_path),
        "consumers": [],
        "changed_files": [],
        "planned_changed_files": [],
        "errors": [],
    }
    missing_names = sorted(selected - {consumer["name"] for consumer in manifest["consumers"]})
    if missing_names:
        result["status"] = "error"
        result["errors"].append("unknown consumers: " + ", ".join(missing_names))

    for consumer in consumers:
        consumer_report = update_consumer(
            consumer=consumer,
            manifest_dir=manifest_dir,
            library_cli=library_cli,
            apply=apply,
            runner=runner,
        )
        result["consumers"].append(consumer_report)
        result["changed_files"].extend(consumer_report["changed_files"])
        result["planned_changed_files"].extend(consumer_report["planned_changed_files"])
        if consumer_report["status"] == "error":
            result["status"] = "error"
            result["errors"].extend(
                f"{consumer_report['name']}: {error}"
                for error in consumer_report["errors"]
            )
    return result


def format_human(result: dict[str, Any]) -> str:
    lines = [
        f"Consumer update {result['mode']}: {result['status']}",
    ]
    for consumer in result["consumers"]:
        lines.append(f"- {consumer['name']}: {consumer['status']}")
        for action in consumer["library_actions"]:
            lines.append(
                f"  library {action.get('primitive')}:{action.get('name')} "
                f"-> {action.get('status')} (exit {action.get('exit_code')})"
            )
        for action in consumer["file_actions"]:
            label = "would-update" if result["mode"] == "dry-run" else "updated"
            if not action.get("changed"):
                label = action["status"]
            lines.append(f"  file {label}: {action['target']}")
    if result.get("errors"):
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in result["errors"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--consumer", action="append", default=[])
    parser.add_argument("--library-cli", type=Path, default=DEFAULT_LIBRARY_CLI)
    parser.add_argument("--apply", action="store_true", help="Mutate consumer working trees")
    parser.add_argument("--json", action="store_true", help="Print a JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_update(
            manifest_path=args.manifest,
            selected_consumers=args.consumer,
            library_cli=args.library_cli,
            apply=args.apply,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        result = {
            "status": "error",
            "mode": "apply" if args.apply else "dry-run",
            "manifest": str(args.manifest),
            "consumers": [],
            "changed_files": [],
            "planned_changed_files": [],
            "errors": [str(exc)],
        }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_human(result))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
