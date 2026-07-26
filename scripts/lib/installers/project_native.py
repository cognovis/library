"""Install project-only harness-native Pi assets and Just modules."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..cache import compute_cache_path
from ..catalog import get_catalog_identity, lookup_entry
from ..errors import InstallError
from ..lockfile import (
    compute_checksum,
    find_lockfile,
    get_entry,
    load_lockfile,
    make_entry,
    remove_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..source import parse_source, resolve_marketplace
from .simple_file import _cleanup_temp, _fetch_file_source

PROJECT_NATIVE_TARGETS = {
    "pi-extension": Path(".agents/pi/extensions"),
    "pi-profile": Path(".agents/pi/profiles"),
    "just-module": Path(".agents/just"),
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def require_project_native_request(primitive: str, name: str, scope: str) -> None:
    """Reject unsupported scope or unsafe names before filesystem mutation."""
    if primitive not in PROJECT_NATIVE_TARGETS:
        raise InstallError(f"Unknown project-native primitive: {primitive}")
    if scope != "project":
        raise InstallError(f"{primitive} is project-only and cannot use {scope} scope.")
    if not _SAFE_NAME.fullmatch(name) or name in {".", ".."}:
        raise InstallError(
            f"Invalid {primitive} name '{name}': names must be a single safe filename segment."
        )


def _extension(entry: dict[str, Any], name: str) -> str:
    source = entry.get("source") or ""
    if not source:
        raise InstallError(f"'{name}' has no source field.")
    parsed = parse_source(source)
    source_path = (
        parsed.local_path
        if parsed.is_local()
        else (Path(parsed.file_path) if parsed.file_path else None)
    )
    suffix = source_path.suffix if source_path is not None else ""
    if not suffix:
        raise InstallError(f"'{name}' source must reference a file with an extension.")
    return suffix


def _target(repo_root: Path, primitive: str, name: str, suffix: str) -> Path:
    root = repo_root.resolve()
    base = (root / PROJECT_NATIVE_TARGETS[primitive]).resolve()
    if not base.is_relative_to(root):
        raise InstallError(
            f"Refusing {primitive} '{name}': fixed target resolves outside {root}."
        )
    target = base / f"{name}{suffix}"
    if target.parent != base:
        raise InstallError(f"Invalid {primitive} target for '{name}'.")
    return target


def install_project_native_file(
    catalog: dict,
    primitive: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Install a project-local Pi extension, Pi profile, or Just module."""
    if install_mode not in {"vendor", "symlink"}:
        raise InstallError(f"Unknown install mode: {install_mode}")
    entry = lookup_entry(catalog, primitive, name, fuzzy=True)
    item_name = entry.get("name", name)
    require_project_native_request(primitive, item_name, scope)
    suffix = _extension(entry, item_name)
    target = _target(repo_root, primitive, item_name, suffix)
    lockfile_path = find_lockfile(repo_root, global_scope=False)
    marketplace = resolve_marketplace(catalog, entry)

    if dry_run:
        return dry_run_result(
            [
                {
                    "operation": "materialize_cache",
                    "path": f"~/.local/share/library/{primitive}s/{marketplace}/{item_name}@<sha>/",
                    "details": "copy source -> Layer-B cache",
                },
                {
                    "operation": "vendor_file"
                    if install_mode == "vendor"
                    else "create_symlink",
                    "path": str(target),
                    "details": f"install {primitive} '{item_name}'",
                    "existing_target": target.exists() or target.is_symlink(),
                },
                {
                    "operation": "write_lockfile",
                    "path": str(lockfile_path),
                    "details": f"upsert entry '{item_name}'",
                },
            ],
            summary=f"Would install {primitive} '{item_name}' to {target}",
            target_paths=[str(target)],
            harness_routing=None,
            conflict_policy="overwrite",
            lockfile_changes=[
                {"path": str(lockfile_path), "operation": "upsert", "entry": item_name}
            ],
            requires_user_confirmation=False,
        )

    source = entry["source"]
    source_file, source_commit, temp_root = _fetch_file_source(
        parse_source(source), item_name
    )
    try:
        if not source_file.is_file() or source_file.suffix != suffix:
            raise InstallError(
                f"{primitive} '{item_name}' source must resolve to one file."
            )
        cache_path = compute_cache_path(
            primitive, marketplace, item_name, source_commit
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))
        cache_path.mkdir(parents=True)
        cached_file = cache_path / f"{item_name}{suffix}"
        shutil.copy2(str(source_file), str(cached_file))

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        if install_mode == "vendor":
            shutil.copy2(str(cached_file), str(target))
        else:
            target.symlink_to(cached_file)

        checksum = compute_checksum(target.resolve() if target.is_symlink() else target)
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(
            lock_data,
            make_entry(
                name=item_name,
                primitive_type=primitive,
                catalog_identity=get_catalog_identity(catalog),
                marketplace=marketplace,
                source=source,
                source_commit=source_commit,
                cache_path=str(cache_path) + "/",
                install_target=str(target),
                checksum_sha256=checksum,
                content_sha256=checksum,
                install_mode=install_mode,
                license_id=entry.get("license", "unknown"),
            ),
        )
        save_lockfile(lockfile_path, lock_data)
        return success(
            data={
                "name": item_name,
                "install_target": str(target),
                "cache": str(cache_path),
                "source_commit": source_commit,
                "install_mode": install_mode,
            },
            message=f"{primitive.title()} '{item_name}' installed at {target}",
        )
    finally:
        _cleanup_temp(temp_root)


def remove_project_native_file(
    primitive: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove a project-native file from its lockfile-recorded target."""
    require_project_native_request(primitive, name, scope)
    lockfile_path = find_lockfile(repo_root, global_scope=False)
    lock_data = load_lockfile(lockfile_path)
    locked = get_entry(lock_data, name, primitive_type=primitive)
    target = Path(locked["install_target"]) if locked else None
    root = repo_root.resolve()
    expected_base = (root / PROJECT_NATIVE_TARGETS[primitive]).resolve()
    if not expected_base.is_relative_to(root):
        raise InstallError(
            f"Refusing to remove {primitive} '{name}': target resolves outside {root}."
        )
    if target is not None and target.parent.resolve() != expected_base:
        raise InstallError(
            f"Refusing to remove {primitive} '{name}' outside {expected_base}."
        )

    if dry_run:
        operations = []
        if target is not None and (target.exists() or target.is_symlink()):
            operations.append(
                {
                    "operation": "delete",
                    "path": str(target),
                    "details": f"remove {target}",
                }
            )
        operations.append(
            {
                "operation": "remove_lockfile_entry",
                "path": str(lockfile_path),
                "details": f"remove '{name}'",
            }
        )
        return dry_run_result(operations, summary=f"Would remove {primitive} '{name}'")

    removed = []
    if target is not None and (target.exists() or target.is_symlink()):
        target.unlink()
        removed.append(str(target))
    remove_entry(lock_data, name, primitive_type=primitive)
    save_lockfile(lockfile_path, lock_data)
    return success(
        data={"name": name, "removed_files": removed},
        message=f"{primitive.title()} '{name}' removed.",
    )
