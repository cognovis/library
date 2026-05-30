"""
installers/mcp_installer.py — MCP server install/remove via library.py.

Uses install-mcp.py's harness-specific write functions directly (no subprocess
delegation). The catalog entry is passed in from library.py, so there is no
re-read of library.yaml — tests can use tmpdir fixtures.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
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
from ..output import dry_run_result, error_result, success
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


def _derive_deploy_path(entry: dict, mcp_name: str) -> tuple[str | None, str | None, Path | None]:
    """Derive the deploy path, clone URL, and mcp_subdir from a catalog entry.

    Returns (clone_url, mcp_subdir, deploy_path) or (None, None, None) if the
    source is not a GitHub URL pointing to a file inside a repo subtree.

    The deploy path convention follows the existing cognovis-library-core pattern:
        ~/.local/share/library/<org>-<repo>/
    where <org>-<repo> is derived from the GitHub clone URL.

    The mcp_subdir is the directory within the repo that contains the MCP server
    (i.e., the parent directory of pyproject.toml in the source URL).
    """
    source_str = entry.get("source")
    if not source_str:
        return None, None, None

    try:
        parsed = parse_source(source_str)
    except Exception:
        return None, None, None

    if not parsed.is_github() or not parsed.clone_url:
        return None, None, None

    # Derive <org>-<repo> slug from clone URL
    # e.g. https://github.com/cognovis/library-core.git -> cognovis-library-core
    clone_url = parsed.clone_url
    slug = clone_url.rstrip("/").rstrip(".git").rsplit("/", 2)[-2:]
    deploy_dir_name = "-".join(s.rstrip(".git") for s in slug)
    deploy_path = Path.home() / ".local" / "share" / "library" / deploy_dir_name

    # Derive mcp_subdir from file_path: only apply deploy-clone for pyproject.toml sources.
    # pyproject.toml sources indicate a uv-based library-tool-surface MCP server that needs
    # to be run with `uv run --project <deploy_path>/<mcp_subdir>`. Other source types
    # (mcp.yaml, etc.) are launched differently and do not need a local deploy clone.
    if not parsed.file_path:
        return None, None, None

    fp = parsed.file_path.rstrip("/")
    if not (fp.endswith("/pyproject.toml") or fp == "pyproject.toml"):
        # Not a pyproject.toml source — no deploy clone needed
        return None, None, None

    mcp_subdir = str(Path(fp).parent) if "/" in fp else ""

    return clone_url, mcp_subdir, deploy_path


def ensure_mcp_deploy_clone(
    clone_url: str,
    mcp_subdir: str,
    deploy_path: Path,
    dry_run: bool = False,
) -> Path:
    """Clone or update the MCP server source repo to the deploy path and verify launchability.

    This implements the ADR-0002 deploy-clone model for MCP servers: the source repo is
    cloned to the deploy path before the harness registration is written, ensuring the
    launch command in the registration always points to a real directory.

    Args:
        clone_url: Git clone URL for the source repo.
        mcp_subdir: Path within the repo to the MCP server (must contain pyproject.toml).
        deploy_path: Local filesystem path where the repo is cloned.
        dry_run: If True, skip cloning and return deploy_path without mutation.

    Returns:
        deploy_path (same as input) on success.

    Raises:
        InstallError: When the clone fails, or when mcp_subdir/pyproject.toml is missing
            after cloning. In either case no registration has been written.
    """
    if dry_run:
        # Dry-run: report the planned clone without touching the filesystem
        return deploy_path

    # If the deploy path already has a .git dir, update in place instead of cloning
    git_dir = deploy_path / ".git"
    if git_dir.is_dir():
        # Repo already present — pull latest
        result = subprocess.run(
            ["git", "-C", str(deploy_path), "pull", "--ff-only", "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Pull failed (e.g. diverged history). Log a warning but do not abort —
            # the existing clone is still usable for the current deploy.
            print(
                f"[mcp-deploy] WARNING: git pull failed for {deploy_path}: "
                f"{result.stderr.strip() or result.stdout.strip()}",
                file=sys.stderr,
            )
    else:
        # Fresh clone
        deploy_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", clone_url, str(deploy_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise InstallError(
                f"Failed to clone MCP server source from {clone_url} to {deploy_path}: {stderr}"
            )

    # Verify that the mcp_subdir contains pyproject.toml (launchability check)
    if mcp_subdir:
        pyproject = deploy_path / mcp_subdir / "pyproject.toml"
    else:
        pyproject = deploy_path / "pyproject.toml"

    if not pyproject.is_file():
        raise InstallError(
            f"MCP server source at {deploy_path / (mcp_subdir or '')} is missing pyproject.toml. "
            f"The deploy clone at {deploy_path} exists but the entry point cannot be verified. "
            f"No harness registration will be written."
        )

    return deploy_path


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

    Per ADR-0002 deploy-clone model: clones/updates the MCP server source repo to
    the deploy path and verifies launchability BEFORE writing any harness registration.
    If the deploy clone cannot be established, raises InstallError without writing any
    dangling registration.

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

    Raises:
        InstallError: When the deploy clone cannot be established (clone fails or
            entry point missing). No registration is written in this case.
    """
    if harness in ("cursor", "opencode"):
        return error_result(
            f"MCP server install for harness '{harness}' is not supported. "
            "MCP configuration for Cursor and OpenCode is not managed by this installer."
        )

    # 1. Catalog lookup — use catalog passed in (not re-reading disk)
    entry = lookup_entry(catalog, "mcp", name)
    mcp_name = entry.get("name", name)
    marketplace = resolve_marketplace(catalog, entry)

    # 2. Derive deploy path and ensure the source repo clone is present and launchable.
    # This MUST happen before any harness registration is written (no dangling registration).
    clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, mcp_name)
    if clone_url and deploy_path:
        # ensure_mcp_deploy_clone raises InstallError on failure — no registration written
        ensure_mcp_deploy_clone(
            clone_url=clone_url,
            mcp_subdir=mcp_subdir or "",
            deploy_path=deploy_path,
            dry_run=dry_run,
        )

    # 3. Dry-run
    if dry_run:
        harnesses = _selected_mcp_harnesses(entry, harness)
        ops: list[dict[str, Any]] = []
        target_paths: list[Path] = []
        if clone_url and deploy_path:
            ops.append({
                "operation": "clone_mcp_source",
                "path": str(deploy_path),
                "details": (
                    f"clone/update '{clone_url}' to {deploy_path} "
                    f"(subdir={mcp_subdir or '/'})"
                ),
            })
        for selected in harnesses:
            path = _mcp_config_path(selected)
            if path is None:
                ops.append(
                    {
                        "operation": "install_mcp_server",
                        "path": None,
                        "details": (
                            f"emit manual install URL for '{mcp_name}' "
                            f"(harness={selected}; no file write)"
                        ),
                    }
                )
                continue
            target_paths.append(path)
            ops.append(
                {
                    "operation": "install_mcp_server",
                    "path": str(path),
                    "details": f"add '{mcp_name}' to MCP config (harness={selected})",
                }
            )
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

    # 4. Apply env overrides (config file paths for testing) BEFORE loading install-mcp.py.
    # install-mcp.py reads config paths from env vars at module-import time, so overrides
    # must be set before exec_module runs. This is the same semantics as the original code
    # but with steps reordered to ensure test fixtures take effect.
    saved_env: dict = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

    # 5. Load install-mcp.py module for its write helpers (after env overrides are applied)
    try:
        mod = _import_install_mcp()
    except Exception as exc:
        raise InstallError(f"Cannot load install-mcp.py: {exc}") from exc

    try:
        # 6. Determine which harnesses to install using catalog entry (not re-loaded library)
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

        # 7. Write lockfile
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
                "deploy_path": str(deploy_path) if deploy_path else None,
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
    """Return concrete MCP harnesses targeted by a dry-run request.

    Mirrors install-mcp.py's real install behavior: for `--harness all`,
    iterate over every harness declared in the entry's install.mcp block,
    including url-only harnesses (claude_ai, claude_ios). Real install
    falls back to claude_code only when no harnesses are declared.
    """
    if harness != "all":
        return [harness]

    mcp_block = ((entry.get("install") or {}).get("mcp") or {})
    declared = [
        candidate
        for candidate in ["claude_code", "codex", "opencode", "claude_ai", "claude_ios"]
        if mcp_block.get(candidate)
    ]
    return declared or ["claude_code"]


def _mcp_config_path(harness: str) -> Path | None:
    """Return the harness config path the real install will write.

    install-mcp.py always writes to global paths (no project-scope variant);
    project-local config files are not consulted by the actual install. The
    paths honor the same environment variable overrides install-mcp.py uses
    so dry-run output matches what the real install will touch under test
    fixtures.

    Returns None for URL-only harnesses (claude_ai, claude_ios) which never
    write a file — the real install emits a manual install URL instead.
    """
    if harness in ("claude_ai", "claude_ios"):
        return None
    if harness == "codex":
        return Path(
            os.environ.get(
                "CODEX_CONFIG_FILE",
                str(Path.home() / ".codex" / "config.toml"),
            )
        )
    if harness == "opencode":
        return Path(
            os.environ.get(
                "OPENCODE_CONFIG_FILE",
                str(Path.home() / ".config" / "opencode" / "opencode.json"),
            )
        )
    # claude_code (default)
    return Path(
        os.environ.get(
            "CLAUDE_SETTINGS_FILE",
            str(Path.home() / ".claude" / "settings.json"),
        )
    )


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
