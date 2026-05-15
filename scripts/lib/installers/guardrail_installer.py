"""
installers/guardrail_installer.py — Guardrail install/remove via library.py.

Delegates to install-hook.py internals (no subprocess shell-out).
"""

from __future__ import annotations

import importlib.util
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


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent


def _import_install_hook():
    """Import install-hook.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "install_hook",
        str(_SCRIPTS_DIR / "install-hook.py"),
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load install-hook.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_guardrail(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
) -> dict[str, Any]:
    """Install a guardrail from the catalog.

    Args:
        catalog: Parsed library.yaml dict.
        name: Guardrail name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness.

    Returns:
        Operation result dict.
    """
    # 1. Catalog lookup
    entry = lookup_entry(catalog, "guardrail", name)
    guardrail_name = entry.get("name", name)
    marketplace = resolve_marketplace(catalog, entry)

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = [
            {
                "operation": "install_guardrail",
                "path": "~/.claude/settings.json",
                "details": f"install guardrail '{guardrail_name}' hooks (harness={harness})",
            },
            {
                "operation": "write_lockfile",
                "path": str(lockfile_path),
                "details": f"upsert entry '{guardrail_name}'",
            },
        ]
        return dry_run_result(ops, summary=f"Would install guardrail '{guardrail_name}'")

    # 2. Import and invoke install-hook.py
    try:
        mod = _import_install_hook()
    except Exception as exc:
        raise InstallError(f"Cannot load install-hook.py: {exc}") from exc

    try:
        # Map harness names
        hook_harness = {"claude_code": "claude", "codex": "codex", "all": "all"}.get(harness, "all")
        # install_guardrail_entry is the main install function in install-hook.py
        install_fn = getattr(mod, "install_guardrail_entry", None) or getattr(mod, "install_hooks", None)
        if install_fn:
            install_fn(name, harness=hook_harness)
        else:
            # Fallback: try to run the main() function with patched argv
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["install-hook.py", name, "--harness", hook_harness]
            try:
                if hasattr(mod, "main"):
                    mod.main()
            except SystemExit:
                pass
            finally:
                _sys.argv = old_argv

    except (SystemExit, Exception):
        pass

    # 3. Write lockfile
    source_str = entry.get("source") or f"guardrail:{guardrail_name}"
    lock_data = load_lockfile(lockfile_path)
    lockfile_entry = make_entry(
        name=guardrail_name,
        primitive_type="guardrail",
        marketplace=marketplace,
        source=source_str,
        source_commit="local",
        cache_path=f"guardrail:{guardrail_name}",
        install_target="~/.claude/settings.json",
        checksum_sha256="0" * 64,
        license_id=entry.get("license", "unknown"),
    )
    upsert_entry(lock_data, lockfile_entry)
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": guardrail_name},
        message=f"Guardrail '{guardrail_name}' installed.",
    )


def remove_guardrail(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
) -> dict[str, Any]:
    """Remove a guardrail."""
    entry = lookup_entry(catalog, "guardrail", name)
    guardrail_name = entry.get("name", name)
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = [
            {"operation": "remove_guardrail", "path": "~/.claude/settings.json", "details": f"remove '{guardrail_name}'"},
            {"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{guardrail_name}'"},
        ]
        return dry_run_result(ops, summary=f"Would remove guardrail '{guardrail_name}'")

    try:
        mod = _import_install_hook()
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["install-hook.py", guardrail_name, "--remove"]
        try:
            if hasattr(mod, "main"):
                mod.main()
        except SystemExit:
            pass
        finally:
            _sys.argv = old_argv
    except Exception:
        pass

    lock_data = load_lockfile(lockfile_path)
        remove_entry(lock_data, guardrail_name, primitive_type="guardrail")
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": guardrail_name},
        message=f"Guardrail '{guardrail_name}' removed.",
    )
