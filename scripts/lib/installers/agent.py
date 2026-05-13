"""
installers/agent.py — Agent install/remove logic.

Agents are deployed as composed .md files (and optionally .toml for Codex)
at ~/.claude/agents/<name>.md (global) or <project>/.claude/agents/<name>.md
(project scope).

Composition is performed by scripts/compose-agent.py if the agent frontmatter
references golden_prompt_extends or model_standards. If compose-agent.py is not
found, the raw file is copied as-is.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..cache import compute_cache_path, materialize_cache, plan_cache_writes
from ..catalog import lookup_entry
from ..errors import InstallError, NotFoundError, SourceError
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
from ..output import dry_run_result, error_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive
from ..source import ParsedSource, get_local_commit_sha, parse_source, resolve_marketplace


def _resolve_agent_source(entry: dict, harness: str = "all") -> str:
    """Extract source string for the requested harness."""
    # Multi-harness sources map
    sources_map = entry.get("sources") or {}
    if sources_map:
        if harness == "claude_code" and sources_map.get("claude"):
            return sources_map["claude"]
        if harness == "codex" and sources_map.get("codex"):
            return sources_map["codex"]
        if harness == "opencode" and sources_map.get("opencode"):
            return sources_map["opencode"]
        # For "all" or any unmatched harness, prefer claude source
        if sources_map.get("claude"):
            return sources_map["claude"]
        if sources_map.get("codex"):
            return sources_map["codex"]
        first = next(iter(sources_map.values()), None)
        if first:
            return first

    # Single source field
    if entry.get("source"):
        return entry["source"]

    raise SourceError(
        f"Agent '{entry.get('name')}' has no resolvable source field."
    )


def _harness_missing_sources(entry: dict, harness: str) -> list[str]:
    """Return list of harness names that are declared but missing for this harness request."""
    if harness == "all":
        return []
    sources_map = entry.get("sources") or {}
    if not sources_map:
        return []
    harness_key = {"claude_code": "claude", "codex": "codex", "opencode": "opencode"}.get(harness, harness)
    if sources_map and harness_key not in sources_map:
        return [entry.get("name", "unknown")]
    return []


def install_agent(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
) -> dict[str, Any]:
    """Install an agent from the catalog.

    Args:
        catalog: Parsed library.yaml dict.
        name: Agent name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness ('claude_code', 'codex', 'opencode', 'all').

    Returns:
        Operation result dict.
    """
    prim = get_primitive("agent")

    # 1. Catalog lookup
    entry = lookup_entry(catalog, "agent", name)
    agent_name = entry.get("name", name)

    # 2. Resolve source for the requested harness
    harness_missing: list[str] = []
    try:
        source_str = _resolve_agent_source(entry, harness)
    except SourceError:
        # If specific harness has no source, fall back to any available
        harness_missing = _harness_missing_sources(entry, harness)
        try:
            source_str = _resolve_agent_source(entry, "all")
        except SourceError as exc:
            raise InstallError(f"Agent '{agent_name}' has no source for harness '{harness}'.") from exc

    # 3. Parse source
    parsed = parse_source(source_str)
    marketplace = resolve_marketplace(catalog, entry)

    # 4. Determine install paths
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]

    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for agent '{agent_name}' (scope={scope}). "
            "Check default_dirs.agents in library.yaml."
        )

    # 5. Dry-run mode
    if dry_run:
        ops = plan_cache_writes(
            primitive_type="agent",
            marketplace=marketplace,
            name=agent_name,
            source_commit="<commit-sha>",
            install_target=canonical_base / f"{agent_name}.md",
            bridge_path=None,
        )
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append({
            "operation": "write_lockfile",
            "path": str(lockfile_path),
            "details": f"upsert entry '{agent_name}' in {lockfile_path.name}",
        })
        result = dry_run_result(
            ops,
            summary=f"Would install agent '{agent_name}' to {canonical_base}",
        )
        if harness_missing:
            result["harness_missing"] = harness_missing
        return result

    # 6. Fetch source
    source_file, source_commit, temp_root = _fetch_agent_source(parsed, agent_name)

    try:
        cache_path = compute_cache_path("agent", marketplace, agent_name, source_commit)

        # 6b. Materialize cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))
        cache_path.mkdir(parents=True, exist_ok=True)

        # Determine agent filename
        agent_filename = source_file.name
        if not agent_filename.endswith(".md"):
            agent_filename = f"{agent_name}.md"

        # Copy source file to cache
        cached_file = cache_path / agent_filename
        shutil.copy2(str(source_file), str(cached_file))

        # 7. Run compose-agent.py if available
        compose_script = repo_root / "scripts" / "compose-agent.py"
        if compose_script.exists():
            _try_compose(compose_script, cached_file, agent_name)

        # 8. Install to target location
        canonical_base.mkdir(parents=True, exist_ok=True)
        install_target = canonical_base / f"{agent_name}.md"
        if install_target.is_symlink():
            install_target.unlink()
        elif install_target.exists():
            install_target.unlink()

        # Copy (not symlink) the composed file — agents are typically single files
        shutil.copy2(str(cached_file), str(install_target))

        # 9. Write lockfile
        checksum = compute_checksum(cached_file)
        lockfile_entry = make_entry(
            name=agent_name,
            primitive_type="agent",
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=str(cache_path) + "/",
            install_target=str(install_target),
            checksum_sha256=checksum,
            license_id=entry.get("license", "unknown"),
        )
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        result = success(
            data={
                "name": agent_name,
                "install_target": str(install_target),
                "cache": str(cache_path),
                "source_commit": source_commit,
            },
            message=f"Agent '{agent_name}' installed at {install_target}",
        )
        if harness_missing:
            result["harness_missing"] = harness_missing
        return result

    finally:
        _cleanup_source(temp_root)


def remove_agent(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove an installed agent.

    Args:
        catalog: Parsed library.yaml dict.
        name: Agent name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.

    Returns:
        Operation result dict.
    """
    prim = get_primitive("agent")
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]

    if canonical_base is None:
        raise InstallError(f"Cannot determine install path for agent '{name}' (scope={scope}).")

    install_target = canonical_base / f"{name}.md"

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = []
        if install_target.exists() or install_target.is_symlink():
            ops.append({"operation": "delete", "path": str(install_target), "details": f"remove {install_target}"})
        ops.append({"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{name}'"})
        return dry_run_result(ops, summary=f"Would remove agent '{name}'")

    removed_files = []
    if install_target.is_symlink():
        install_target.unlink()
        removed_files.append(str(install_target))
    elif install_target.exists():
        install_target.unlink()
        removed_files.append(str(install_target))

    lock_data = load_lockfile(lockfile_path)
    remove_entry(lock_data, name)
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": name, "removed_files": removed_files},
        message=f"Agent '{name}' removed.",
    )


def _try_compose(compose_script: Path, agent_file: Path, agent_name: str) -> None:
    """Run compose-agent.py on the agent file in-place (best-effort)."""
    try:
        result = subprocess.run(
            ["python3", str(compose_script), str(agent_file), "--harness=claude"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            agent_file.write_text(result.stdout)
    except (subprocess.SubprocessError, OSError):
        pass  # compose is optional


def _fetch_agent_source(
    parsed: ParsedSource, agent_name: str
) -> tuple[Path, str, Optional[Path]]:
    """Fetch the agent source file.

    Returns (file_path, commit_sha, temp_root). `temp_root` is the directory
    that must be cleaned up after use, or None when the source is local.
    """
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.exists():
            raise InstallError(f"Local source path does not exist: {parsed.raw}")
        source_file = local if local.is_file() else _find_agent_file(local, agent_name)
        commit = get_local_commit_sha(source_file)
        return source_file, commit, None

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
                return source_file, commit, tmp

        # Fallback: look for agent file in repo root
        agent_file = _find_agent_file(tmp, agent_name)
        return agent_file, commit, tmp

    raise SourceError(f"Cannot fetch agent source: unsupported source kind '{parsed.kind}'")


def _find_agent_file(directory: Path, agent_name: str) -> Path:
    """Find the agent .md file in a directory."""
    candidates = [
        directory / f"{agent_name}.md",
        directory / "agent.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    md_files = list(directory.glob("*.md"))
    if md_files:
        return md_files[0]
    return directory / f"{agent_name}.md"


def _cleanup_source(temp_root: Optional[Path]) -> None:
    """Remove the temp clone dir, if one was created."""
    if temp_root is None:
        return
    shutil.rmtree(str(temp_root), ignore_errors=True)
