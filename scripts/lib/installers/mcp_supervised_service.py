"""Supervised loopback MCP service lifecycle helpers for catalog entries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import InstallError

_HEALTHY_STATE = "healthy"


def expand_argv(command_block: dict[str, Any]) -> list[str]:
    """Expand a catalog argv_command into a subprocess argv list."""
    command = str(command_block["command"])
    args = [os.path.expanduser(str(arg)) for arg in command_block.get("args", [])]
    return [command, *args]


def resolve_project_path(project_path: Path, command_block: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of command_block with deploy project paths normalized."""
    resolved = deepcopy(command_block)
    project = str(project_path)
    normalized_args: list[str] = []
    for arg in resolved.get("args", []):
        expanded = os.path.expanduser(str(arg))
        if expanded.endswith("/mcp-servers/cognovis-tools"):
            normalized_args.append(project)
        else:
            normalized_args.append(expanded)
    resolved["args"] = normalized_args
    return resolved


def resolve_supervised_service(
    entry: dict[str, Any],
    project_path: Path,
) -> dict[str, Any]:
    """Resolve supervised_local_service commands against the deploy clone project path."""
    raw = entry.get("supervised_local_service")
    if not raw:
        raise InstallError("Entry is missing supervised_local_service metadata.")

    resolved = deepcopy(raw)
    for key in ("install", "start", "health_check", "restart", "stop", "uninstall"):
        resolved[key] = resolve_project_path(project_path, resolved[key])
    rollback = deepcopy(resolved["stdio_rollback"])
    rollback["args"] = [
        str(project_path)
        if os.path.expanduser(str(arg)).endswith("/mcp-servers/cognovis-tools")
        else os.path.expanduser(str(arg))
        for arg in rollback.get("args", [])
    ]
    resolved["stdio_rollback"] = rollback
    return resolved


def run_argv_command(
    command_block: dict[str, Any],
    *,
    check: bool = False,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a catalog argv_command."""
    argv = expand_argv(command_block)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def parse_daemon_status(stdout: str) -> dict[str, Any]:
    """Parse cognovis-tools-daemon JSON status output."""
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_healthy_status(stdout: str) -> bool:
    payload = parse_daemon_status(stdout)
    return payload.get("state") == _HEALTHY_STATE


def service_status(command_block: dict[str, Any]) -> dict[str, Any]:
    """Return parsed daemon status from the catalog health_check command."""
    result = run_argv_command(command_block, check=False)
    payload = parse_daemon_status(result.stdout)
    payload["exit_code"] = result.returncode
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()
    return payload


def ensure_supervised_service(
    entry: dict[str, Any],
    project_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install or restart the supervised service and verify health before registration."""
    service = resolve_supervised_service(entry, project_path)

    if dry_run:
        current = service_status(service["health_check"])
        action = "restart" if current.get("state") == _HEALTHY_STATE else "install"
        return {
            "action": action,
            "project_path": str(project_path),
            "url": service["url"],
            "dry_run": True,
        }

    current = service_status(service["health_check"])
    previous_version = current.get("version")

    if current.get("state") == _HEALTHY_STATE:
        restart = run_argv_command(service["restart"], check=False)
        if restart.returncode != 0:
            raise InstallError(
                "Supervised MCP service restart failed before registration: "
                f"{restart.stderr.strip() or restart.stdout.strip()}"
            )
        action = "restart"
    else:
        install = run_argv_command(service["install"], check=False)
        if install.returncode != 0:
            raise InstallError(
                "Supervised MCP service install failed before registration: "
                f"{install.stderr.strip() or install.stdout.strip()}"
            )
        action = "install"

    after = service_status(service["health_check"])
    if after.get("state") != _HEALTHY_STATE:
        _attempt_stdio_fallback(entry, project_path)
        raise InstallError(
            "Supervised MCP service is not healthy after "
            f"{action}: {after.get('message') or after.get('stderr') or 'unknown error'}"
        )

    if action == "restart" and previous_version and after.get("version") == previous_version:
        raise InstallError(
            "Supervised MCP service restart did not advance the version sentinel."
        )

    return {
        "action": action,
        "project_path": str(project_path),
        "url": service["url"],
        "version": after.get("version"),
        "state": after.get("state"),
    }


def stop_supervised_service(entry: dict[str, Any], project_path: Path, *, dry_run: bool = False) -> None:
    service = resolve_supervised_service(entry, project_path)
    if dry_run:
        return
    run_argv_command(service["stop"], check=False)


def uninstall_supervised_service(
    entry: dict[str, Any],
    project_path: Path,
    *,
    dry_run: bool = False,
) -> None:
    service = resolve_supervised_service(entry, project_path)
    if dry_run:
        return
    run_argv_command(service["stop"], check=False)
    run_argv_command(service["uninstall"], check=False)


def stdio_rollback_snippet(entry: dict[str, Any], project_path: Path) -> dict[str, Any]:
    """Return the preserved stdio descriptor for harness registration rollback."""
    service = resolve_supervised_service(entry, project_path)
    return deepcopy(service["stdio_rollback"])


def supervised_service_dry_run_ops(
    entry: dict[str, Any],
    project_path: Path,
) -> list[dict[str, Any]]:
    """Return dry-run operations for supervised service lifecycle."""
    service = resolve_supervised_service(entry, project_path)
    current = service_status(service["health_check"])
    lifecycle = "restart" if current.get("state") == _HEALTHY_STATE else "install"
    ops = [
        {
            "operation": "supervised_service",
            "path": str(project_path),
            "details": f"{lifecycle} supervised MCP service at {service['url']}",
        },
        {
            "operation": "supervised_service_health",
            "path": service.get("health_url") or service["url"],
            "details": "verify daemon status reports healthy with version sentinel",
        },
    ]
    return ops


def _attempt_stdio_fallback(entry: dict[str, Any], project_path: Path) -> None:
    """Best-effort stop when service activation fails. Registration rollback is caller-owned."""
    try:
        service = resolve_supervised_service(entry, project_path)
        run_argv_command(service["stop"], check=False)
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"[mcp-supervised] WARNING: stop during fallback failed: {exc}", file=sys.stderr)
