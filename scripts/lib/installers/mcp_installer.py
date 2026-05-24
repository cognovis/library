"""
installers/mcp_installer.py — MCP server install/remove via library.py.

Uses install-mcp.py's harness-specific write functions directly (no subprocess
delegation). The catalog entry is passed in from library.py, so there is no
re-read of library.yaml — tests can use tmpdir fixtures.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from ..catalog import lookup_entry
from ..errors import InstallError
from ..lockfile import (
    find_lockfile,
    load_lockfile,
    make_entry,
    remove_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..source import resolve_marketplace
from ..source import parse_source
from ..status import get_remote_sha


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent


def _import_install_mcp():
    """Import install-mcp.py as a module (it's not a package)."""
    spec = importlib.util.spec_from_file_location(
        "install_mcp",
        str(_SCRIPTS_DIR / "install-mcp.py"),
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load install-mcp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_mcp(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    env_overrides: dict | None = None,
) -> dict[str, Any]:
    """Install an MCP server from the catalog.

    Uses install-mcp.py's write functions directly (no subprocess delegation).

    Args:
        catalog: Parsed library.yaml dict.
        name: MCP server name.
        repo_root: Project root.
        scope: 'project' or 'global' (for lockfile).
        dry_run: If True, return planned ops without mutating.
        harness: Target harness ('claude_code', 'codex', 'opencode', 'all').
        env_overrides: Optional env var overrides (for testing).

    Returns:
        Operation result dict.
    """
    # 1. Catalog lookup — use catalog passed in (not re-reading disk)
    entry = lookup_entry(catalog, "mcp", name)
    mcp_name = entry.get("name", name)
    marketplace = resolve_marketplace(catalog, entry)

    # 2. Dry-run
    if dry_run:
        harnesses = _selected_mcp_harnesses(entry, harness)
        target_paths = [_mcp_config_path(repo_root, scope, selected) for selected in harnesses]
        ops = [
            {
                "operation": "install_mcp_server",
                "path": str(path),
                "details": f"add '{mcp_name}' to MCP config (harness={selected})",
            }
            for selected, path in zip(harnesses, target_paths)
        ]
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append({
            "operation": "write_lockfile",
            "path": str(lockfile_path),
            "details": f"upsert entry '{mcp_name}'",
        })
        return dry_run_result(
            ops,
            summary=f"Would install MCP server '{mcp_name}' (harness={harness})",
            target_paths=[str(path) for path in target_paths],
            harness_routing=harness,
            conflict_policy="overwrite",
            lockfile_changes=[
                {
                    "path": str(lockfile_path),
                    "operation": "upsert",
                    "entry": mcp_name,
                }
            ],
            requires_user_confirmation=False,
        )

    # 3. Load install-mcp.py module for its write helpers
    try:
        mod = _import_install_mcp()
    except Exception as exc:
        raise InstallError(f"Cannot load install-mcp.py: {exc}") from exc

    # 4. Apply env overrides (config file paths for testing)
    saved_env: dict = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

    try:
        # 5. Determine which harnesses to install using catalog entry (not re-loaded library)
        mcp_harness = harness
        install_block = entry.get("install", {}) or {}
        mcp_block = install_block.get("mcp", {}) or {}

        if mcp_harness == "all":
            harnesses_to_install = [h for h in ["claude_code", "codex", "opencode", "claude_ai", "claude_ios"]
                                     if mcp_block.get(h)]
            if not harnesses_to_install:
                harnesses_to_install = ["claude_code"]
        else:
            harnesses_to_install = [mcp_harness]

        installed_harnesses = []
        for h in harnesses_to_install:
            block = mcp_block.get(h)
            if block is None:
                continue
            rc = _install_to_harness(mod, mcp_name, block, h, dry_run=False)
            if rc == 0:
                installed_harnesses.append(h)

        # 6. Write lockfile
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        source_str = entry.get("source") or f"mcp:{mcp_name}"
        source_commit = _resolve_source_commit(mcp_name, entry.get("source"))
        lockfile_entry = make_entry(
            name=mcp_name,
            primitive_type="mcp",
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=f"mcp:{mcp_name}",
            install_target=",".join(installed_harnesses) or "none",
            checksum_sha256="0" * 64,
            license_id=entry.get("license", "unknown"),
        )
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        return success(
            data={
                "name": mcp_name,
                "installed_harnesses": installed_harnesses,
            },
            message=f"MCP server '{mcp_name}' installed for: {', '.join(installed_harnesses) or 'none'}",
        )

    finally:
        # Restore env
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _resolve_source_commit(name: str, source: str | None) -> str:
    """Resolve the upstream commit SHA for an MCP source URL."""
    if not source:
        return "local"

    try:
        parsed = parse_source(source)
    except Exception:
        print(
            f"Warning: could not capture upstream SHA for mcp:{name}: {source}",
            file=sys.stderr,
        )
        return "local"

    if parsed.kind not in ("github_browser", "github_raw", "github_repo"):
        return "local"

    clone_url = parsed.clone_url
    if not clone_url:
        print(
            f"Warning: could not capture upstream SHA for mcp:{name}: {source}",
            file=sys.stderr,
        )
        return "local"

    ref = parsed.branch or "HEAD"
    remote_sha = get_remote_sha(clone_url, ref)
    if remote_sha is None:
        print(
            f"Warning: could not capture upstream SHA for mcp:{name}: {source}",
            file=sys.stderr,
        )
        return "local"

    return remote_sha


def _selected_mcp_harnesses(entry: dict, harness: str) -> list[str]:
    """Return concrete MCP harnesses targeted by a dry-run request."""
    if harness != "all":
        return [harness]

    mcp_block = ((entry.get("install") or {}).get("mcp") or {})
    selected = [
        candidate
        for candidate in ["claude_code", "codex", "opencode"]
        if mcp_block.get(candidate)
    ]
    return selected or ["claude_code"]


def _mcp_config_path(repo_root: Path, scope: str, harness: str) -> Path:
    """Return the harness config path a dry-run will report."""
    if scope == "project":
        if harness == "codex":
            return repo_root / ".codex" / "config.toml"
        if harness == "opencode":
            return repo_root / ".config" / "opencode" / "opencode.json"
        return repo_root / ".claude" / "settings.json"

    if harness == "codex":
        return Path.home() / ".codex" / "config.toml"
    if harness == "opencode":
        return Path.home() / ".config" / "opencode" / "opencode.json"
    return Path.home() / ".claude" / "settings.json"


def remove_mcp(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    env_overrides: dict | None = None,
) -> dict[str, Any]:
    """Remove an MCP server."""
    entry = lookup_entry(catalog, "mcp", name)
    mcp_name = entry.get("name", name)
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = [
            {"operation": "remove_mcp_server", "path": "~/.claude/settings.json",
             "details": f"remove '{mcp_name}'"},
            {"operation": "remove_lockfile_entry", "path": str(lockfile_path),
             "details": f"remove '{mcp_name}'"},
        ]
        return dry_run_result(ops, summary=f"Would remove MCP server '{mcp_name}'")

    try:
        mod = _import_install_mcp()
    except Exception as exc:
        raise InstallError(f"Cannot load install-mcp.py: {exc}") from exc

    saved_env: dict = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

    try:
        if harness == "all":
            harnesses = ["claude_code", "codex", "opencode"]
        else:
            harnesses = [harness]

        removed_harnesses = []
        for h in harnesses:
            rc = _remove_from_harness(mod, mcp_name, h)
            if rc == 0:
                removed_harnesses.append(h)

        lock_data = load_lockfile(lockfile_path)
        remove_entry(lock_data, mcp_name, primitive_type="mcp")
        save_lockfile(lockfile_path, lock_data)

        return success(
            data={"name": mcp_name, "removed_harnesses": removed_harnesses},
            message=f"MCP server '{mcp_name}' removed.",
        )

    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _install_to_harness(mod, name: str, block: dict, harness: str, dry_run: bool) -> int:
    """Install to a specific harness using install-mcp.py helpers."""
    try:
        if harness == "claude_code":
            fn = getattr(mod, "install_claude_code", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False)
        elif harness == "codex":
            fn = getattr(mod, "install_codex", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False)
        elif harness == "opencode":
            fn = getattr(mod, "install_opencode", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False)
        elif harness in ("claude_ai", "claude_ios"):
            fn = getattr(mod, "install_url_only", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False, harness=harness)
    except SystemExit as e:
        return int(str(e)) if str(e).isdigit() else 1
    except Exception:
        pass
    return 0


def _remove_from_harness(mod, name: str, harness: str) -> int:
    """Remove from a specific harness using install-mcp.py helpers."""
    try:
        if harness == "claude_code":
            fn = getattr(mod, "install_claude_code", None)
            if fn:
                return fn(name, {}, dry_run=False, remove=True)
        elif harness == "codex":
            fn = getattr(mod, "install_codex", None)
            if fn:
                return fn(name, {}, dry_run=False, remove=True)
        elif harness == "opencode":
            fn = getattr(mod, "install_opencode", None)
            if fn:
                return fn(name, {}, dry_run=False, remove=True)
    except (SystemExit, Exception):
        pass
    return 0
