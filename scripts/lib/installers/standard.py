"""
installers/standard.py — Standard install logic.

Installs a standard by:
1. Copying the standard file to the standards directory (Layer B cache)
2. Creating a canonical symlink (Layer C)
3. If scripts/agents-md-block.py exists: composing a block into AGENTS.md
4. Writing the lockfile entry

If scripts/agents-md-block.py does NOT exist, emits a blocked/not-implemented
result but still performs the cache+symlink steps.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..cache import compute_cache_path, plan_cache_writes
from ..catalog import lookup_entry
from ..errors import InstallError, SourceError
from ..lockfile import (
    compute_checksum,
    find_lockfile,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import blocked_result, dry_run_result, success
from ..paths import resolve_install_paths, resolve_standards_agents_md
from ..primitives import get_primitive
from ..source import get_local_commit_sha, parse_source, resolve_marketplace


def install_standard(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install a standard from the catalog.

    Args:
        catalog: Parsed library.yaml dict.
        name: Standard name or fuzzy query.
        repo_root: Project root directory.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.

    Returns:
        Operation result dict.
    """
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

    canonical_dir = canonical_base / standard_name

    # Check for agents-md-block.py
    agents_md_script = repo_root / "scripts" / "agents-md-block.py"
    agents_md_available = agents_md_script.exists()
    agents_md_target = resolve_standards_agents_md(catalog, scope=scope, repo_root=repo_root)

    # 4. Dry-run mode
    if dry_run:
        ops = plan_cache_writes(
            primitive_type="standard",
            marketplace=marketplace,
            name=standard_name,
            source_commit="<commit-sha>",
            install_target=canonical_dir,
            bridge_path=None,
        )
        if agents_md_available and agents_md_target:
            ops.append(
                {
                    "operation": "inject_agents_md_block",
                    "path": str(agents_md_target),
                    "details": (
                        f"compose marker block for '{standard_name}' "
                        f"into {agents_md_target}"
                    ),
                }
            )
        else:
            ops.append(
                {
                    "operation": "agents_md_block_blocked",
                    "path": str(agents_md_target) if agents_md_target else "AGENTS.md",
                    "details": (
                        "scripts/agents-md-block.py not found — "
                        "AGENTS.md injection step will be skipped"
                    ),
                }
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
            summary=(
                f"Would install standard '{standard_name}' to {canonical_dir}"
                + (
                    f", inject AGENTS.md block via agents-md-block.py"
                    if agents_md_available
                    else " (AGENTS.md injection blocked: agents-md-block.py not found)"
                )
            ),
        )

    # 5. Fetch source
    source_dir, source_commit = _fetch_standard_source(parsed, standard_name)

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

        # 6. Create canonical symlink
        canonical_dir.parent.mkdir(parents=True, exist_ok=True)
        if canonical_dir.is_symlink():
            canonical_dir.unlink()
        elif canonical_dir.is_dir():
            shutil.rmtree(str(canonical_dir))
        canonical_dir.symlink_to(cache_path)

        # 7. AGENTS.md block injection
        agents_md_result = None
        if agents_md_available and agents_md_target:
            result = subprocess.run(
                ["python3", str(agents_md_script), standard_name, "--target", str(agents_md_target)],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            agents_md_result = {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }

        # 8. Write lockfile
        primary_artifact = _find_primary_artifact(cache_path, standard_name)
        checksum = compute_checksum(primary_artifact) if primary_artifact.exists() else "0" * 64

        lockfile_entry = make_entry(
            name=standard_name,
            primitive_type="standard",
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=str(cache_path) + "/",
            install_target=str(canonical_dir) + "/",
            checksum_sha256=checksum,
            license_id=entry.get("license", "unknown"),
        )

        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        result_data: dict[str, Any] = {
            "name": standard_name,
            "canonical": str(canonical_dir),
            "cache": str(cache_path),
            "source_commit": source_commit,
        }

        msg = f"Standard '{standard_name}' installed at {canonical_dir}"

        if not agents_md_available:
            result_data["agents_md_blocked"] = (
                "scripts/agents-md-block.py not found — AGENTS.md injection skipped"
            )
            msg += ". Note: AGENTS.md block injection requires scripts/agents-md-block.py"
        elif agents_md_result:
            result_data["agents_md"] = agents_md_result

        return success(data=result_data, message=msg)

    finally:
        # Clean up temp clone if applicable
        if hasattr(source_dir, "_is_temp"):
            try:
                shutil.rmtree(str(source_dir if source_dir.is_dir() else source_dir.parent))
            except OSError:
                pass


def _fetch_standard_source(parsed, standard_name: str) -> tuple[Path, str]:
    """Fetch the standard source file/dir."""
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.exists():
            raise InstallError(f"Local source path does not exist: {parsed.raw}")
        commit = get_local_commit_sha(local)
        return local, commit

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

        # Navigate to the file within the repo
        if parsed.file_path:
            source_file = tmp / parsed.file_path
            if source_file.exists():
                source_file._is_temp = True  # type: ignore[attr-defined]
                return source_file, commit
        source_dir = tmp
        source_dir._is_temp = True  # type: ignore[attr-defined]
        return source_dir, commit

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
