"""
installers/skill.py — Skill install/remove logic.

Implements the three-layer cache model (ADR-0003):
  Layer A: Source (catalog entry source URL or local path)
  Layer B: Cache (~/.local/share/library/skills/<marketplace>/<name>@<14hex>/)
  Layer C: Harness (.agents/skills/<name>/ symlink -> Layer B)

For Claude Code: adds a bridge symlink at .claude/skills/<name>/ -> Layer B.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..cache import (
    compute_cache_path,
    create_harness_symlink,
    materialize_cache,
    plan_cache_writes,
)
from ..catalog import lookup_entry
from ..errors import InstallError, NotFoundError, SourceError
from ..lockfile import (
    compute_checksum,
    find_lockfile,
    get_entry,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive
from ..source import ParsedSource, get_local_commit_sha, parse_source, resolve_marketplace
from .harness_materializer import materialize_harness_fields


def install_skill(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install a skill from the catalog.

    Steps:
    1. Look up entry in catalog
    2. Resolve source (local path or GitHub URL)
    3. Compute cache path (Layer B)
    4. If dry_run: return planned operations without mutating
    5. Materialize cache (copy source dir -> Layer B)
    6. Create canonical symlink (Layer C -> Layer B)
    7. Create Claude bridge symlink (Layer C' -> Layer B)
    8. Write lockfile entry

    Args:
        catalog: Parsed library.yaml dict.
        name: Skill name or fuzzy query.
        repo_root: Project root directory.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.

    Returns:
        Operation result dict.
    """
    prim = get_primitive("skill")

    # 1. Catalog lookup
    entry = lookup_entry(catalog, "skill", name)
    skill_name = entry.get("name", name)
    source_str = _resolve_entry_source(entry)

    # 2. Parse source
    parsed = parse_source(source_str)
    marketplace = resolve_marketplace(catalog, entry)

    # 3. Determine paths
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    bridge_base = install_paths["bridge"]

    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for skill '{skill_name}' (scope={scope}). "
            "Check default_dirs.skills in library.yaml."
        )

    canonical_dir = canonical_base / skill_name
    bridge_dir = (bridge_base / skill_name) if bridge_base else None

    # 4. Dry-run mode
    if dry_run:
        ops = plan_cache_writes(
            primitive_type="skill",
            marketplace=marketplace,
            name=skill_name,
            source_commit="<commit-sha>",
            install_target=canonical_dir,
            bridge_path=bridge_dir,
        )
        # Add lockfile write op
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append(
            {
                "operation": "write_lockfile",
                "path": str(lockfile_path),
                "details": f"upsert entry '{skill_name}' in {lockfile_path.name}",
            }
        )
        # Add harness materialization ops (always_apply / globs)
        harness = materialize_harness_fields(entry, skill_name, "skill", repo_root, dry_run=True)
        ops.extend(harness["operations"])
        return dry_run_result(
            ops,
            summary=(
                f"Would install skill '{skill_name}' to {canonical_dir}"
                + (f" with bridge {bridge_dir}" if bridge_dir else "")
            ),
        )

    # 5. Fetch source and get commit SHA
    source_dir, source_commit, temp_root = _fetch_source_dir(parsed, skill_name)

    try:
        # Recompute cache_path with real commit SHA
        cache_path = compute_cache_path("skill", marketplace, skill_name, source_commit)

        # 5b. Materialize cache (Layer B)
        materialize_cache(source_dir, cache_path)

        # 6. Create canonical symlink (Layer C -> Layer B)
        create_harness_symlink(canonical_dir, cache_path)

        # 7. Create Claude bridge symlink
        bridge_symlink_strs: list[str] = []
        if bridge_dir:
            create_harness_symlink(bridge_dir, cache_path)
            bridge_symlink_strs.append(f"{bridge_dir} -> {cache_path}")

        # 8. Write lockfile
        primary_artifact = cache_path / "SKILL.md"
        if not primary_artifact.exists():
            # Fallback: find any .md file in the cache
            md_files = list(cache_path.glob("*.md"))
            primary_artifact = md_files[0] if md_files else cache_path / "SKILL.md"

        if primary_artifact.exists():
            checksum = compute_checksum(primary_artifact)
        else:
            checksum = "0" * 64

        install_target_str = str(canonical_dir) + "/"
        lockfile_entry = make_entry(
            name=skill_name,
            primitive_type="skill",
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=str(cache_path) + "/",
            install_target=install_target_str,
            checksum_sha256=checksum,
            license_id=entry.get("license", "unknown"),
            bridge_symlinks=bridge_symlink_strs,
        )

        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        # 9. Harness materialization (always_apply / globs)
        harness = materialize_harness_fields(entry, skill_name, "skill", repo_root)
        for w in harness.get("warnings", []):
            print(f"WARNING: {w}", file=sys.stderr)

        return success(
            data={
                "name": skill_name,
                "canonical": str(canonical_dir),
                "bridge": str(bridge_dir) if bridge_dir else None,
                "cache": str(cache_path),
                "source_commit": source_commit,
                "harness_ops": harness.get("operations", []),
            },
            message=(
                f"Skill '{skill_name}' installed at {canonical_dir}"
                + (f" with bridge {bridge_dir}" if bridge_dir else "")
            ),
        )
    finally:
        if temp_root is not None:
            shutil.rmtree(str(temp_root), ignore_errors=True)


def _resolve_entry_source(entry: dict) -> str:
    """Extract a single source string from a catalog entry."""
    if entry.get("source"):
        return entry["source"]

    # Handle sources: map (multi-harness)
    sources_map = entry.get("sources", {}) or {}
    if sources_map.get("claude"):
        return sources_map["claude"]
    if sources_map.get("codex"):
        return sources_map["codex"]

    # Handle from_marketplace + repo + path
    if entry.get("from_marketplace") and entry.get("repo") and entry.get("path"):
        # Build a plausible GitHub URL from the marketplace reference
        # We do NOT fabricate URLs — use what's in the catalog
        raise SourceError(
            f"Skill '{entry.get('name')}' uses from_marketplace reference. "
            "Direct install not yet supported for marketplace-resolved entries. "
            "Use /library skill use via the skill wrapper."
        )

    raise SourceError(
        f"Skill '{entry.get('name')}' has no resolvable source field."
    )


def _fetch_source_dir(
    parsed: ParsedSource, skill_name: str
) -> tuple[Path, str, Optional[Path]]:
    """Fetch the skill source directory.

    Returns (dir_path, commit_sha, temp_root). `temp_root` is the temp
    clone directory the caller must clean up, or None for local sources.

    For local sources: returns the parent directory.
    For GitHub sources: clones to a temp dir, navigates to the skill subdir.
    """
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.exists():
            raise InstallError(
                f"Local source path does not exist: {parsed.raw}"
            )
        # The source is the SKILL.md file — we want the parent directory
        source_dir = local.parent if local.is_file() else local
        commit = get_local_commit_sha(source_dir)
        return source_dir, commit, None

    if parsed.is_github():
        # Clone to temp dir
        tmp = Path(tempfile.mkdtemp())

        # Try HTTPS first, fall back to SSH
        clone_url = parsed.clone_url or ""
        result = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", clone_url, str(tmp)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try SSH
            ssh_url = clone_url.replace("https://github.com/", "git@github.com:")
            result = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", ssh_url, str(tmp)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(
                    f"Failed to clone {clone_url}: {result.stderr.strip()}"
                )

        # Get commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(tmp),
        )
        commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        # Navigate to the skill directory within the repo
        parent_dir = parsed.parent_dir_in_repo()
        skill_dir = tmp / (parent_dir or "") if parent_dir else tmp
        if not skill_dir.exists():
            skill_dir = tmp
        return skill_dir, commit, tmp

    raise SourceError(f"Cannot fetch source: unsupported source kind '{parsed.kind}'")
