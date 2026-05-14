"""
installers/simple_file.py — Generic single-file installer for prompt, model-standard,
and golden-prompt primitives.

All three follow the same pattern:
  1. Fetch source file
  2. Cache it in Layer B (~/.local/share/library/<type>s/<marketplace>/<name>@<sha>/)
  3. Copy to the install target by default (or symlink with --symlink)
  4. Write lockfile entry

Remove reverses steps 3 and 4.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..cache import compute_cache_path
from ..catalog import lookup_entry
from ..errors import InstallError, SourceError
from ..lockfile import (
    compute_checksum,
    find_lockfile,
    load_lockfile,
    make_entry,
    remove_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive
from ..source import get_local_commit_sha, parse_source, resolve_marketplace, ParsedSource


def install_simple_file(
    catalog: dict,
    primitive_name: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Generic install for prompt, model-standard, golden-prompt.

    Args:
        catalog: Parsed library.yaml dict.
        primitive_name: One of 'prompt', 'model-standard', 'golden-prompt'.
        name: Entry name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness (used for determining install sub-path for prompts).
        install_mode: 'vendor' (default) or 'symlink'.

    Returns:
        Operation result dict.
    """
    if install_mode not in ("vendor", "symlink"):
        raise InstallError(f"Unknown install mode for {primitive_name} '{name}': {install_mode}")

    prim = get_primitive(primitive_name)
    if prim is None:
        raise InstallError(f"Unknown primitive: {primitive_name}")

    # 1. Catalog lookup
    entry = lookup_entry(catalog, primitive_name, name)
    item_name = entry.get("name", name)
    source_str = entry.get("source") or ""
    if not source_str:
        # Try sources map
        sources_map = entry.get("sources") or {}
        source_str = sources_map.get("claude") or sources_map.get("codex") or ""
    if not source_str:
        raise InstallError(f"'{primitive_name} {item_name}' has no source field.")

    # 2. Parse source
    parsed = parse_source(source_str)
    marketplace = resolve_marketplace(catalog, entry)

    # 3. Determine install paths
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for {primitive_name} '{item_name}' (scope={scope}). "
            f"Check default_dirs.{prim.install_subdir} in library.yaml."
        )

    # Determine install filename
    if primitive_name == "prompt":
        install_filename = f"{item_name}.md"
    elif primitive_name == "model-standard":
        install_filename = f"{item_name}.md"
    elif primitive_name == "golden-prompt":
        install_filename = f"{item_name}.md"
    else:
        install_filename = f"{item_name}.md"

    install_target = canonical_base / install_filename

    # 4. Dry-run mode
    if dry_run:
        ops = [
            {
                "operation": "materialize_cache",
                "path": f"~/.local/share/library/{primitive_name}s/{marketplace}/{item_name}@<sha>/",
                "details": f"copy source -> Layer-B cache",
            },
            {
                "operation": "vendor_file" if install_mode == "vendor" else "create_symlink",
                "path": str(install_target),
                "details": f"install {primitive_name} '{item_name}' to {install_target}",
            },
        ]
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append({
            "operation": "write_lockfile",
            "path": str(lockfile_path),
            "details": f"upsert entry '{item_name}'",
        })
        return dry_run_result(ops, summary=f"Would install {primitive_name} '{item_name}' to {install_target}")

    # 5. Fetch source
    source_file, source_commit, temp_root = _fetch_file_source(parsed, item_name)

    try:
        cache_path = compute_cache_path(
            f"{primitive_name}",
            marketplace,
            item_name,
            source_commit,
        )

        # 5b. Materialize cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))
        cache_path.mkdir(parents=True, exist_ok=True)

        cached_file_name = source_file.name if source_file.is_file() else f"{item_name}.md"
        cached_file = cache_path / cached_file_name
        if source_file.is_file():
            shutil.copy2(str(source_file), str(cached_file))
        else:
            shutil.copytree(str(source_file), str(cache_path / item_name))
            cached_file = cache_path / item_name / f"{item_name}.md"

        # 6. Install to target
        canonical_base.mkdir(parents=True, exist_ok=True)
        if install_target.is_symlink():
            install_target.unlink()
        elif install_target.exists():
            install_target.unlink()

        if cached_file.exists():
            if install_mode == "vendor":
                shutil.copy2(str(cached_file), str(install_target))
            else:
                install_target.symlink_to(cached_file)
        else:
            if install_mode == "vendor":
                shutil.copytree(str(cache_path), str(install_target))
            else:
                install_target.parent.mkdir(parents=True, exist_ok=True)
                install_target.symlink_to(cache_path)

        # 7. Write lockfile
        primary = install_target if install_target.exists() else cached_file
        checksum = compute_checksum(primary) if primary.is_file() else "0" * 64

        lockfile_entry = make_entry(
            name=item_name,
            primitive_type=primitive_name,
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=str(cache_path) + "/",
            install_target=str(install_target),
            checksum_sha256=checksum,
            content_sha256=checksum,
            install_mode=install_mode,
            license_id=entry.get("license", "unknown"),
        )
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        return success(
            data={
                "name": item_name,
                "install_target": str(install_target),
                "cache": str(cache_path),
                "source_commit": source_commit,
                "install_mode": install_mode,
            },
            message=f"{primitive_name.title()} '{item_name}' installed at {install_target}",
        )

    finally:
        _cleanup_temp(temp_root)


def remove_simple_file(
    catalog: dict,
    primitive_name: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generic remove for prompt, model-standard, golden-prompt."""
    prim = get_primitive(primitive_name)
    if prim is None:
        raise InstallError(f"Unknown primitive: {primitive_name}")

    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(f"Cannot determine install path for {primitive_name} '{name}'.")

    install_target = canonical_base / f"{name}.md"
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = []
        if install_target.exists() or install_target.is_symlink():
            ops.append({"operation": "delete", "path": str(install_target), "details": f"remove {install_target}"})
        ops.append({"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{name}'"})
        return dry_run_result(ops, summary=f"Would remove {primitive_name} '{name}'")

    removed_files = []
    for candidate in [install_target, canonical_base / name]:
        if candidate.is_symlink():
            candidate.unlink()
            removed_files.append(str(candidate))
        elif candidate.exists():
            if candidate.is_dir():
                shutil.rmtree(str(candidate))
            else:
                candidate.unlink()
            removed_files.append(str(candidate))

    lock_data = load_lockfile(lockfile_path)
    remove_entry(lock_data, name)
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": name, "removed_files": removed_files},
        message=f"{primitive_name.title()} '{name}' removed.",
    )


def _fetch_file_source(
    parsed: ParsedSource, name: str
) -> tuple[Path, str, Optional[Path]]:
    """Fetch source file.

    Returns (path, commit_sha, temp_root). `temp_root` is the directory
    that must be cleaned up after use, or None when the source is local.
    """
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.exists():
            raise InstallError(f"Local source path does not exist: {parsed.raw}")
        commit = get_local_commit_sha(local)
        return local, commit, None

    if parsed.is_github():
        tmp = Path(tempfile.mkdtemp())
        clone_url = parsed.clone_url or ""
        result = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", clone_url, str(tmp)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            ssh_url = clone_url.replace("https://github.com/", "git@github.com:")
            result = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", ssh_url, str(tmp)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(f"Failed to clone {clone_url}: {result.stderr.strip()}")

        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp)
        )
        commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        if parsed.file_path:
            source_file = tmp / parsed.file_path
            if source_file.exists():
                return source_file, commit, tmp

        for candidate in [tmp / f"{name}.md", tmp / "SKILL.md", tmp / "agent.md"]:
            if candidate.exists():
                return candidate, commit, tmp

        return tmp, commit, tmp

    raise SourceError(f"Cannot fetch source: unsupported kind '{parsed.kind}'")


def _cleanup_temp(temp_root: Optional[Path]) -> None:
    """Remove the temp clone dir, if one was created."""
    if temp_root is None:
        return
    shutil.rmtree(str(temp_root), ignore_errors=True)
