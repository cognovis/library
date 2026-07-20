"""
installers/standard.py — Standard install logic.

Installs a standard by:
1. Copying the standard file to the standards directory (Layer B cache)
2. Creating a canonical vendored copy (Layer C) by default
3. Writing the lockfile entry
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any, Optional

from ..cache import (
    compute_cache_path,
    create_harness_symlink,
    materialize_install_target,
    materialize_vendor_copy,
    plan_cache_writes,
)
from ..catalog import get_catalog_identity, lookup_entry
from ..errors import InstallError, SourceError
from ..lockfile import (
    compute_checksum,
    compute_directory_hash,
    find_lockfile,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import blocked_result, dry_run_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive
from ..source import get_local_commit_sha, parse_source, resolve_marketplace


def _parse_standard_category(file_path: str) -> tuple[str, str] | tuple[None, None]:
    """Parse category and filename from a standards/ path.

    Handles paths like:
      standards/workflow/bead-hygiene.md
      some/prefix/standards/workflow/bead-hygiene.md

    Returns (category, filename) or (None, None) if the pattern is not found.
    """
    if not file_path:
        return None, None
    parts = file_path.split("/")
    for i, part in enumerate(parts):
        if part == "standards" and i + 2 < len(parts):
            category = parts[i + 1]
            filename = parts[i + 2]
            if category and filename:
                return category, filename
    return None, None


def install_standard(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    tool_root: Optional[Path] = None,
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Install a standard from the catalog.

    Args:
        catalog: Parsed library.yaml dict.
        name: Standard name or fuzzy query.
        repo_root: Project root directory.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        tool_root: Repository root that provides helper scripts.
        install_mode: 'vendor' (default) or 'symlink'.

    Returns:
        Operation result dict.
    """
    if install_mode not in ("vendor", "symlink"):
        raise InstallError(f"Unknown install mode for standard '{name}': {install_mode}")

    prim = get_primitive("standard")

    # 1. Catalog lookup
    entry = lookup_entry(catalog, "standard", name)
    standard_name = entry.get("name", name)
    source_str = entry.get("source", "")

    if not source_str:
        return blocked_result(
            f"Standard '{standard_name}' has no source field — cannot install.",
            suggestion="Add a 'source:' field to the library.yaml entry.",
        )

    # 2. Parse source
    parsed = parse_source(source_str)
    marketplace = resolve_marketplace(catalog, entry)

    # 3. Determine paths
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]

    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for standard '{standard_name}' (scope={scope}). "
            "Check default_dirs.standards in library.yaml."
        )

    # For single-file (blob/raw) sources, compute the category-mirror install path.
    # For directory (tree) sources, keep the old per-name subdir behavior.
    is_single_file = parsed.path_type == "file"
    canonical_install: Path
    is_file_install = False

    if is_single_file and parsed.file_path:
        category, filename = _parse_standard_category(parsed.file_path)
        if category is not None and filename is not None:
            # Category-mirror path: <base>/<category>/<filename>
            canonical_install = canonical_base / category / filename
            is_file_install = True
        else:
            # Fallback: cannot parse category — use old per-name subdir with warning
            warnings.warn(
                f"Cannot parse category from standard source path '{parsed.file_path}'. "
                f"Falling back to per-name subdir for standard '{standard_name}'.",
                UserWarning,
                stacklevel=2,
            )
            canonical_install = canonical_base / standard_name
    else:
        # Bundle (directory) source: old per-name subdir behavior unchanged
        canonical_install = canonical_base / standard_name

    # For dry-run, use canonical_install as the reported target
    canonical_dir = canonical_install

    # 4. Dry-run mode
    if dry_run:
        ops = plan_cache_writes(
            primitive_type="standard",
            marketplace=marketplace,
            name=standard_name,
            source_commit="<commit-sha>",
            install_target=canonical_dir,
            bridge_path=None,
            install_mode=install_mode,
        )
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append(
            {
                "operation": "write_lockfile",
                "path": str(lockfile_path),
                "details": f"upsert entry '{standard_name}' in {lockfile_path.name}",
            }
        )
        return dry_run_result(
            ops,
            summary=f"Would install standard '{standard_name}' to {canonical_dir}",
            target_paths=[str(canonical_dir)],
            harness_routing=None,
            conflict_policy="overwrite",
            lockfile_changes=[
                {
                    "path": str(lockfile_path),
                    "operation": "upsert",
                    "entry": standard_name,
                }
            ],
            requires_user_confirmation=False,
        )

    # 5. Fetch source
    source_dir, source_commit, temp_root = _fetch_standard_source(parsed, standard_name)

    try:
        cache_path = compute_cache_path("standard", marketplace, standard_name, source_commit)

        # 5b. Materialize: copy source file/dir to cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))

        if source_dir.is_file():
            cache_path.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_dir), str(cache_path / source_dir.name))
        else:
            shutil.copytree(str(source_dir), str(cache_path))

        # 6. Create canonical install (Layer C)
        if is_file_install:
            # Single-file: install directly to the category-mirror file path
            cache_file = cache_path / canonical_install.name
            if install_mode == "symlink":
                create_harness_symlink(canonical_install, cache_file)
            else:
                materialize_vendor_copy(cache_file, canonical_install)
        else:
            materialize_install_target(canonical_dir, cache_path, install_mode=install_mode)

        # 7. Write lockfile — hash local installed content
        if is_file_install:
            try:
                checksum = compute_checksum(canonical_install)
            except OSError:
                checksum = "0" * 64
            lockfile_entry = make_entry(
                name=standard_name,
                primitive_type="standard",
                catalog_identity=get_catalog_identity(catalog),
                marketplace=marketplace,
                source=source_str,
                source_commit=source_commit,
                cache_path=str(cache_path) + "/",
                install_target=str(canonical_install),
                checksum_sha256=checksum,
                checksum_type="file",
                content_sha256=checksum,
                install_mode=install_mode,
                license_id=entry.get("license", "unknown"),
            )
        else:
            try:
                checksum = compute_directory_hash(canonical_dir)
            except OSError:
                checksum = "0" * 64
            lockfile_entry = make_entry(
                name=standard_name,
                primitive_type="standard",
                catalog_identity=get_catalog_identity(catalog),
                marketplace=marketplace,
                source=source_str,
                source_commit=source_commit,
                cache_path=str(cache_path) + "/",
                install_target=str(canonical_dir) + "/",
                checksum_sha256=checksum,
                checksum_type="directory",
                content_sha256=checksum,
                install_mode=install_mode,
                license_id=entry.get("license", "unknown"),
            )

        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        # 8. Migration: remove old per-name subdir if it still exists and is different
        #    from the new category-mirror parent directory
        if is_file_install:
            old_path = canonical_base / standard_name
            if old_path != canonical_install.parent and old_path.exists():
                if old_path.is_symlink():
                    old_path.unlink()
                elif old_path.is_dir():
                    shutil.rmtree(str(old_path), ignore_errors=True)
                # else: it's a file — leave it alone (unexpected, not our install)

        result_data: dict[str, Any] = {
            "name": standard_name,
            "canonical": str(canonical_install),
            "cache": str(cache_path),
            "source_commit": source_commit,
            "install_mode": install_mode,
        }

        msg = f"Standard '{standard_name}' installed at {canonical_install}"

        return success(data=result_data, message=msg)

    finally:
        if temp_root is not None:
            shutil.rmtree(str(temp_root), ignore_errors=True)


def _fetch_standard_source(
    parsed, standard_name: str
) -> tuple[Path, str, Optional[Path]]:
    """Fetch the standard source file/dir.

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
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(tmp),
        )
        commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        # Navigate to the file or directory within the repo. Standards may be
        # single files (GitHub blob/raw URL) or folder-form bundles (tree URL).
        if parsed.file_path:
            source_path = tmp / parsed.file_path
            if not source_path.exists():
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(
                    f"Standard source path does not exist in {clone_url}: {parsed.file_path}"
                )
            if parsed.path_type == "directory" and not source_path.is_dir():
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(
                    f"Standard source path is not a directory for tree URL: {parsed.file_path}"
                )
            if parsed.path_type == "file" and not source_path.is_file():
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(
                    f"Standard source path is not a file for blob/raw URL: {parsed.file_path}"
                )
            return source_path, commit, tmp
        return tmp, commit, tmp

    raise SourceError(f"Cannot fetch source: unsupported source kind '{parsed.kind}'")


def _find_primary_artifact(cache_path: Path, name: str) -> Path:
    """Find the primary artifact file in the cache directory."""
    # Try <name>.md first, then any .md file
    candidates = [
        cache_path / f"{name}.md",
        cache_path / "SKILL.md",
        cache_path / "STANDARD.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    md_files = list(cache_path.glob("*.md"))
    if md_files:
        return md_files[0]

    return cache_path / f"{name}.md"
