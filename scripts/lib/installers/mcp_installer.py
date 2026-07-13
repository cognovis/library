"""
installers/mcp_installer.py — MCP server install/remove via library.py.

Uses install-mcp.py's harness-specific write functions directly (no subprocess
delegation). The catalog entry is passed in from library.py, so there is no
re-read of library.yaml — tests can use tmpdir fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
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
from ..output import dry_run_result, success
from ..source import resolve_marketplace
from ..source import parse_source
from ..status import get_remote_sha
from .mcp_supervised_service import (
    ensure_supervised_service,
    stop_supervised_service,
    stdio_rollback_snippet,
    supervised_service_dry_run_ops,
    uninstall_supervised_service,
)


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent

# Harnesses whose config files install-mcp.py can write, in install order.
_WRITABLE_MCP_HARNESSES = ["claude_code", "codex", "opencode", "antigravity", "cursor"]
# Full set for an "all" install: writable configs plus URL-only (manual) harnesses.
_ALL_MCP_HARNESSES = _WRITABLE_MCP_HARNESSES + ["claude_ai", "claude_ios"]


def _snapshot_config(path: Path) -> str | None:
    if path.is_file():
        return path.read_text()
    return None


def _restore_config(path: Path, snapshot: str | None) -> None:
    if snapshot is None:
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot)


def _retired_registration_specs(
    entry: dict,
    harness: str,
    env_overrides: dict | None = None,
    *,
    rollback_stdio: bool = False,
) -> list[tuple[dict, Path]]:
    """Resolve legacy JSON registrations retired by an all-harness migration."""
    if harness != "all" and not rollback_stdio:
        return []
    install = entry.get("install", {}) or {}
    resolved: list[tuple[dict, Path]] = []
    for spec in install.get("retired_mcp_registrations", []) or []:
        env_name = spec.get("config_path_env")
        raw_path = (env_overrides or {}).get(env_name) if env_name else None
        raw_path = raw_path or (os.environ.get(env_name) if env_name else None)
        raw_path = raw_path or spec.get("config_path")
        if not raw_path:
            raise InstallError("Retired MCP registration is missing config_path.")
        resolved.append((spec, Path(raw_path).expanduser()))
    return resolved


def _matches_legacy_stdio(existing: Any, descriptors: list[dict]) -> bool:
    if not isinstance(existing, dict) or existing.get("_origin") is not None:
        return False
    return any(existing == descriptor for descriptor in descriptors)


def _remove_retired_json_registration(
    *,
    path: Path,
    top_level_key: str,
    name: str,
    legacy_descriptors: list[dict],
) -> bool:
    """Remove one owned or exact-known legacy registration from a JSON config."""
    if not path.is_file() or not path.read_text().strip():
        return False
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise InstallError(f"Cannot migrate retired MCP config {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise InstallError(f"Cannot migrate retired MCP config {path}: root must be an object.")
    container = config.get(top_level_key, {})
    if not isinstance(container, dict):
        raise InstallError(
            f"Cannot migrate retired MCP config {path}: {top_level_key} must be an object."
        )
    existing = container.get(name)
    if existing is None:
        return False
    origin = f"library:mcp:{name}"
    owned = isinstance(existing, dict) and existing.get("_origin") == origin
    if not owned and not _matches_legacy_stdio(existing, legacy_descriptors):
        raise InstallError(
            f"Retired MCP registration {top_level_key}.{name} in {path} is not "
            "library-owned or an exact known legacy descriptor; remove it manually."
        )
    del container[name]
    if container:
        config[top_level_key] = container
    else:
        config.pop(top_level_key, None)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return True


def _project_path_from_deploy(deploy_path: Path | None, mcp_subdir: str | None) -> Path | None:
    if deploy_path is None:
        return None
    if mcp_subdir:
        return deploy_path / mcp_subdir
    return deploy_path


def _harness_block_for_install(
    entry: dict,
    harness: str,
    *,
    rollback_stdio: bool,
    project_path: Path | None,
) -> dict | None:
    install_block = entry.get("install", {}) or {}
    mcp_block = install_block.get("mcp", {}) or {}
    block = mcp_block.get(harness)
    if block is None:
        return None
    if not rollback_stdio:
        legacy = (entry.get("supervised_local_service") or {}).get(
            "legacy_stdio_descriptors", []
        )
        return {**block, "_legacy_descriptors": legacy} if legacy else block
    if project_path is None:
        raise InstallError("Cannot resolve stdio rollback without a deploy project path.")
    rollback = stdio_rollback_snippet(entry, project_path)
    return {
        **block,
        "snippet": rollback,
    }


def _rollback_harnesses_to_stdio(
    mod,
    entry: dict,
    mcp_name: str,
    harnesses: list[str],
    project_path: Path,
) -> list[str]:
    restored: list[str] = []
    for harness in harnesses:
        block = _harness_block_for_install(
            entry,
            harness,
            rollback_stdio=True,
            project_path=project_path,
        )
        if block is None:
            continue
        path = _mcp_config_path(harness)
        if path is None:
            continue
        rc = _install_to_harness(mod, mcp_name, block, harness, dry_run=False)
        if rc == 0:
            restored.append(harness)
    return restored


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
    _ssh_m = re.match(r"git@[^:]+:([^/]+)/([^/]+?)(?:\.git)?$", clone_url)
    _https_m = re.match(r"https://[^/]+/([^/]+)/([^/]+?)(?:\.git)?$", clone_url)
    if _ssh_m:
        deploy_dir_name = f"{_ssh_m.group(1)}-{_ssh_m.group(2)}"
    elif _https_m:
        deploy_dir_name = f"{_https_m.group(1)}-{_https_m.group(2)}"
    else:
        # Fallback: last two path components
        _parts = clone_url.rstrip("/").rstrip(".git").rsplit("/", 2)
        deploy_dir_name = "-".join(p.rstrip(".git") for p in _parts[-2:])
    deploy_root = Path.home() / ".local" / "share" / "library"
    if entry.get("supervised_local_service"):
        # A supervised runtime must never share the mutable developer/source
        # clone used by other Library operations. A dedicated clone makes
        # updates atomic for this service and prevents local source edits from
        # silently leaving the daemon on stale code.
        deploy_path = deploy_root / "mcp-servers" / mcp_name / deploy_dir_name
    else:
        deploy_path = deploy_root / deploy_dir_name

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
            detail = result.stderr.strip() or result.stdout.strip()
            raise InstallError(
                f"Failed to update MCP server source at {deploy_path}: {detail}. "
                "Refusing to continue with a potentially stale runtime; no harness "
                "registration has been written."
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
    rollback_stdio: bool = False,
) -> dict[str, Any]:
    """Install an MCP server from the catalog.

    Per ADR-0002 deploy-clone model: clones/updates the MCP server source repo to
    the deploy path and verifies launchability BEFORE writing any harness registration.
    Supervised entries additionally install/start/health-check the loopback daemon before
    HTTP registrations are written. Any service or harness failure restores prior config
    snapshots and rolls back to the preserved stdio descriptor when available.
    """
    entry = lookup_entry(catalog, "mcp", name)
    mcp_name = entry.get("name", name)
    marketplace = resolve_marketplace(catalog, entry)
    supervised = entry.get("supervised_local_service")
    project_path = None

    clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, mcp_name)
    if clone_url and deploy_path:
        deploy_path = ensure_mcp_deploy_clone(
            clone_url=clone_url,
            mcp_subdir=mcp_subdir or "",
            deploy_path=deploy_path,
            dry_run=dry_run,
        )
        project_path = _project_path_from_deploy(deploy_path, mcp_subdir)

    harnesses = _selected_mcp_harnesses(entry, harness)
    retired_specs = _retired_registration_specs(
        entry,
        harness,
        env_overrides,
        rollback_stdio=rollback_stdio,
    )

    if dry_run:
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
        if supervised and project_path and not rollback_stdio:
            ops.extend(supervised_service_dry_run_ops(entry, project_path))
        elif rollback_stdio and project_path:
            ops.append({
                "operation": "rollback_stdio",
                "path": str(project_path),
                "details": "restore preserved stdio descriptor for declared harnesses",
            })
        for spec, path in retired_specs:
            target_paths.append(path)
            ops.append({
                "operation": "remove_retired_mcp_registration",
                "path": str(path),
                "details": (
                    f"remove owned '{mcp_name}' registration from "
                    f"{spec['top_level_key']}"
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
            transport = "stdio" if rollback_stdio else "http"
            ops.append(
                {
                    "operation": "install_mcp_server",
                    "path": str(path),
                    "details": (
                        f"add '{mcp_name}' to MCP config "
                        f"(harness={selected}, transport={transport})"
                    ),
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

    saved_env: dict = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

    try:
        mod = _import_install_mcp()
    except Exception as exc:
        for key, previous in saved_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        raise InstallError(f"Cannot load install-mcp.py: {exc}") from exc

    service_info: dict[str, Any] | None = None
    writable_harnesses = [h for h in harnesses if _mcp_config_path(h) is not None]
    snapshots: dict[Path, str | None] = {}

    try:
        for h in writable_harnesses:
            path = _mcp_config_path(h)
            if path is not None:
                snapshots[path] = _snapshot_config(path)
        for _, path in retired_specs:
            snapshots.setdefault(path, _snapshot_config(path))

        if supervised and project_path and not rollback_stdio:
            service_info = ensure_supervised_service(entry, project_path, dry_run=False)

        install_block = entry.get("install", {}) or {}
        mcp_block = install_block.get("mcp", {}) or {}
        harnesses_to_install = harnesses
        if harness == "all" and not mcp_block:
            harnesses_to_install = ["claude_code"]

        installed_harnesses: list[str] = []
        for h in harnesses_to_install:
            block = _harness_block_for_install(
                entry,
                h,
                rollback_stdio=rollback_stdio,
                project_path=project_path,
            )
            if block is None:
                continue
            rc = _install_to_harness(mod, mcp_name, block, h, dry_run=False)
            if rc != 0:
                raise InstallError(f"Failed to install MCP server '{mcp_name}' for harness '{h}'.")
            if _mcp_config_path(h) is not None:
                installed_harnesses.append(h)

        retired_registrations_removed: list[str] = []
        legacy_descriptors = (supervised or {}).get("legacy_stdio_descriptors", [])
        for spec, path in retired_specs:
            if _remove_retired_json_registration(
                path=path,
                top_level_key=spec["top_level_key"],
                name=mcp_name,
                legacy_descriptors=legacy_descriptors,
            ):
                retired_registrations_removed.append(str(path))

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

        # A successful stdio rollback must also deactivate the shared daemon.
        # Stop only after every selected harness has been rewritten so a
        # partial config failure leaves the previously active service intact
        # while the byte-exact snapshots are restored below.
        if supervised and project_path and rollback_stdio and harness == "all":
            stop_supervised_service(entry, project_path, dry_run=False)

        return success(
            data={
                "name": mcp_name,
                "installed_harnesses": installed_harnesses,
                "retired_registrations_removed": retired_registrations_removed,
                "deploy_path": str(deploy_path) if deploy_path else None,
                "service": service_info,
                "transport": "stdio" if rollback_stdio else "http",
            },
            message=(
                f"MCP server '{mcp_name}' installed for: "
                f"{', '.join(installed_harnesses) or 'none'}"
            ),
        )

    except Exception:
        for path, snapshot in snapshots.items():
            _restore_config(path, snapshot)
        if (
            supervised
            and project_path
            and service_info is not None
            and service_info.get("action") == "install"
        ):
            try:
                uninstall_supervised_service(entry, project_path, dry_run=False)
            except Exception as cleanup_error:
                print(
                    "[mcp-supervised] WARNING: could not remove newly installed "
                    f"service after registration rollback: {cleanup_error}",
                    file=sys.stderr,
                )
        # Restore the byte-exact pre-install registration state. During the
        # normal migration this is the existing stdio descriptor. Synthesizing
        # a second fallback here would corrupt prior custom or healthy config.
        raise

    finally:
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
    mcp_block = ((entry.get("install") or {}).get("mcp") or {})
    if harness != "all":
        if mcp_block and not mcp_block.get(harness):
            raise InstallError(
                f"MCP server {entry.get('name')!r} does not declare harness {harness!r}."
            )
        return [harness]

    declared = [
        candidate
        for candidate in _ALL_MCP_HARNESSES
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
    if harness == "antigravity":
        return Path(
            os.environ.get(
                "GEMINI_SETTINGS_FILE",
                str(Path.home() / ".gemini" / "config" / "mcp_config.json"),
            )
        )
    if harness == "cursor":
        return Path(
            os.environ.get(
                "CURSOR_MCP_FILE",
                str(Path.home() / ".cursor" / "mcp.json"),
            )
        )
    if harness == "claude_code":
        # User-scoped MCP lives in ~/.claude.json `mcpServers`, not settings.json.
        return Path(
            os.environ.get(
                "CLAUDE_SETTINGS_FILE",
                str(Path.home() / ".claude.json"),
            )
        )
    raise InstallError(f"Unsupported MCP harness: {harness}")


def remove_mcp(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    env_overrides: dict | None = None,
) -> dict[str, Any]:
    """Remove an MCP server and any owned supervised service state."""
    entry = lookup_entry(catalog, "mcp", name)
    mcp_name = entry.get("name", name)
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    clone_url, mcp_subdir, deploy_path = _derive_deploy_path(entry, mcp_name)
    project_path = _project_path_from_deploy(deploy_path, mcp_subdir)
    supervised = entry.get("supervised_local_service")

    if dry_run:
        ops = [
            {
                "operation": "remove_mcp_server",
                "path": "~/.claude/settings.json",
                "details": f"remove '{mcp_name}'",
            },
            {
                "operation": "remove_lockfile_entry",
                "path": str(lockfile_path),
                "details": f"remove '{mcp_name}'",
            },
        ]
        if supervised and project_path:
            ops.append({
                "operation": "supervised_service_uninstall",
                "path": str(project_path),
                "details": f"stop and uninstall owned daemon for '{mcp_name}'",
            })
        return dry_run_result(ops, summary=f"Would remove MCP server '{mcp_name}'")

    saved_env: dict = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v

    try:
        mod = _import_install_mcp()
    except Exception as exc:
        raise InstallError(f"Cannot load install-mcp.py: {exc}") from exc

    try:
        if harness == "all":
            harnesses = list(_WRITABLE_MCP_HARNESSES)
        else:
            harnesses = [harness]

        removed_harnesses = []
        for h in harnesses:
            rc = _remove_from_harness(mod, mcp_name, h)
            if rc == 0:
                removed_harnesses.append(h)

        if supervised and project_path:
            uninstall_supervised_service(entry, project_path, dry_run=False)

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
        elif harness == "antigravity":
            fn = getattr(mod, "install_antigravity", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False)
        elif harness == "cursor":
            fn = getattr(mod, "install_cursor", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False)
        elif harness in ("claude_ai", "claude_ios"):
            fn = getattr(mod, "install_url_only", None)
            if fn:
                return fn(name, block, dry_run=dry_run, remove=False, harness=harness)
    except SystemExit as e:
        return int(str(e)) if str(e).isdigit() else 1
    except Exception:
        return 1
    return 1


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
        elif harness == "antigravity":
            fn = getattr(mod, "install_antigravity", None)
            if fn:
                return fn(name, {}, dry_run=False, remove=True)
        elif harness == "cursor":
            fn = getattr(mod, "install_cursor", None)
            if fn:
                return fn(name, {}, dry_run=False, remove=True)
        elif harness in ("claude_ai", "claude_ios"):
            fn = getattr(mod, "install_url_only", None)
            if fn:
                return fn(
                    name,
                    {},
                    dry_run=False,
                    remove=True,
                    harness=harness,
                )
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception:
        return 1
    return 1
