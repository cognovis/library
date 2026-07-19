"""
installers/agent.py — Agent install/remove logic.

Agents are deployed as composed .md files for Claude Code and .toml files for
Codex at the configured agent directories.

Single-source Markdown agents are built by scripts/build-agent.py into
harness-native Claude .md and Codex .toml artifacts. Legacy dual-source agents
remain supported; their Claude Markdown source is composed by scripts/compose-agent.py
when it references agent_base, agent_base_extends, golden_prompt_extends, or model_standards.
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
    if harness == "cursor":
        return error_result(
            f"Agent install for harness '{harness}' is not supported. "
            "Cursor agents (.cursor/agents/) are not currently implemented by the library installer. "
            "Use harness 'claude_code', 'codex', or 'opencode' instead."
        )

    prim = get_primitive("agent")

    # 1. Catalog lookup
    entry = lookup_entry(catalog, "agent", name)
    agent_name = entry.get("name", name)
    handler_paths = _declared_handler_paths(entry, agent_name)

    # 2. Resolve sources and install targets for the requested harness.
    targets, harness_missing = _resolve_agent_targets(
        catalog=catalog,
        entry=entry,
        prim=prim,
        agent_name=agent_name,
        repo_root=repo_root,
        scope=scope,
        harness=harness,
    )
    marketplace = resolve_marketplace(catalog, entry)

    # 3. Dry-run mode.
    if dry_run:
        ops: list[dict[str, Any]] = []
        target_paths: list[str] = []
        for target in targets:
            target_paths.append(str(target["install_target"]))
            ops.extend(
                plan_cache_writes(
                    primitive_type="agent",
                    marketplace=marketplace,
                    name=target["cache_name"],
                    source_commit="<commit-sha>",
                    install_target=target["install_target"],
                    bridge_path=None,
                )
            )
            for handler_path in handler_paths:
                handler_target = _handler_install_target(
                    target["install_target"].parent,
                    agent_name,
                    handler_path,
                )
                target_paths.append(str(handler_target))
                ops.append({
                    "operation": "vendor_handler",
                    "path": str(handler_target),
                    "details": (
                        f"install private handler asset '{handler_path}' "
                        f"to {handler_target}"
                    ),
                })
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append({
            "operation": "write_lockfile",
            "path": str(lockfile_path),
            "details": f"upsert entry '{agent_name}' in {lockfile_path.name}",
        })
        result = dry_run_result(
            ops,
            summary=f"Would install agent '{agent_name}' to "
                    + ", ".join(str(t["install_target"]) for t in targets),
            target_paths=target_paths,
            harness_routing=harness,
            conflict_policy="overwrite",
            lockfile_changes=[
                {
                    "path": str(lockfile_path),
                    "operation": "upsert",
                    "entry": agent_name,
                }
            ],
            requires_user_confirmation=False,
        )
        if harness_missing:
            result["harness_missing"] = harness_missing
        return result

    # 4. Materialize every requested harness target.
    installed: list[dict[str, Any]] = []
    scripts_root = Path(__file__).resolve().parents[2]
    compose_script = scripts_root / "compose-agent.py"
    build_script = scripts_root / "build-agent.py"

    for target in targets:
        parsed = parse_source(target["source"])
        source_file, source_commit, temp_root = _fetch_agent_source(parsed, agent_name)
        try:
            handler_assets = _validate_handler_assets(
                source_file.parent,
                handler_paths,
                agent_name,
            )
            cache_path = compute_cache_path(
                "agent",
                marketplace,
                target["cache_name"],
                source_commit,
            )

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if cache_path.exists():
                shutil.rmtree(str(cache_path))
            cache_path.mkdir(parents=True, exist_ok=True)

            source_copy = cache_path / source_file.name
            shutil.copy2(str(source_file), str(source_copy))

            if target.get("build_from_unified"):
                cached_file = _try_build_agent(
                    build_script=build_script,
                    source_file=source_copy,
                    output_dir=cache_path,
                    harness=target["harness"],
                    agent_name=agent_name,
                )
            else:
                agent_filename = source_file.name
                if not agent_filename.endswith(target["extension"]):
                    agent_filename = f"{agent_name}{target['extension']}"

                cached_file = cache_path / agent_filename
                if source_copy != cached_file:
                    shutil.copy2(str(source_copy), str(cached_file))

                if target["harness"] == "claude_code" and compose_script.exists():
                    _try_compose(compose_script, cached_file, agent_name)

            install_target = target["install_target"]
            install_target.parent.mkdir(parents=True, exist_ok=True)
            if install_target.is_symlink():
                install_target.unlink()
            elif install_target.exists():
                install_target.unlink()

            shutil.copy2(str(cached_file), str(install_target))
            checksum = compute_checksum(cached_file)
            # Reinstalling must be idempotent: clear any previously-installed
            # handler directory before copying the currently-declared set, so
            # handlers that were removed or renamed since the last install do
            # not linger on disk. This unconditional clear also covers the case
            # where `handlers` was dropped entirely. Mirrors the cache_path
            # rmtree convention above and the target-clearing in
            # _copy_handler_asset.
            handler_root = install_target.parent / f"{agent_name}-handlers"
            if handler_root.is_symlink():
                handler_root.unlink()
            elif handler_root.is_dir():
                shutil.rmtree(str(handler_root))
            elif handler_root.exists():
                handler_root.unlink()
            installed_handlers: list[dict[str, Path]] = []
            for handler_asset in handler_assets:
                handler_cache_path = cache_path / "handler-assets" / handler_asset["relative_path"]
                _copy_handler_asset(handler_asset["source_path"], handler_cache_path)
                handler_target = _handler_install_target(
                    install_target.parent,
                    agent_name,
                    handler_asset["relative_path"],
                )
                _copy_handler_asset(handler_cache_path, handler_target)
                installed_handlers.append({
                    "source_path": handler_asset["source_path"],
                    "cache_path": handler_cache_path,
                    "install_target": handler_target,
                })
            installed.append({
                "harness": target["harness"],
                "source": target["source"],
                "source_commit": source_commit,
                "cache_path": cache_path,
                "cached_file": cached_file,
                "install_target": install_target,
                "checksum": checksum,
                "handlers": installed_handlers,
            })
        finally:
            _cleanup_source(temp_root)

    if not installed:
        raise InstallError(f"Agent '{agent_name}' had no installable targets.")

    primary = next(
        (item for item in installed if item["harness"] == "claude_code"),
        installed[0],
    )
    bridge_symlinks = [
        f"{item['install_target']} -> {item['cached_file']}"
        for item in installed
        if item is not primary
    ]
    for item in installed:
        bridge_symlinks.extend(
            f"{handler['install_target']} -> {handler['cache_path']}"
            for handler in item["handlers"]
        )

    lockfile_entry = make_entry(
        name=agent_name,
        primitive_type="agent",
        marketplace=marketplace,
        source=primary["source"],
        source_commit=primary["source_commit"],
        cache_path=str(primary["cache_path"]) + "/",
        install_target=str(primary["install_target"]),
        checksum_sha256=primary["checksum"],
        content_sha256=primary["checksum"],
        install_mode="vendor",
        license_id=entry.get("license", "unknown"),
        bridge_symlinks=bridge_symlinks,
    )
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    upsert_entry(lock_data, lockfile_entry)
    save_lockfile(lockfile_path, lock_data)

    result = success(
        data={
            "name": agent_name,
            "install_target": str(primary["install_target"]),
            "installed_targets": [
                {
                    "harness": item["harness"],
                    "path": str(item["install_target"]),
                    "source_commit": item["source_commit"],
                    "handlers": [
                        str(handler["install_target"])
                        for handler in item["handlers"]
                    ],
                }
                for item in installed
            ],
            "cache": str(primary["cache_path"]),
            "source_commit": primary["source_commit"],
        },
        message="Agent '{}' installed at {}".format(
            agent_name,
            ", ".join(str(item["install_target"]) for item in installed),
        ),
    )
    if harness_missing:
        result["harness_missing"] = harness_missing
    return result


def _declared_handler_paths(entry: dict, agent_name: str) -> list[Path]:
    """Return validated relative handler paths declared by an agent entry."""
    raw_handlers = entry.get("handlers", [])
    if raw_handlers is None:
        raw_handlers = []
    if not isinstance(raw_handlers, list):
        raise InstallError(f"Agent '{agent_name}' handlers must be a list of relative paths.")

    handlers: list[Path] = []
    for raw_handler in raw_handlers:
        if not isinstance(raw_handler, str) or not raw_handler.strip():
            raise InstallError(
                f"Agent '{agent_name}' handlers must contain non-empty relative paths."
            )
        handler_path = Path(raw_handler)
        if handler_path.is_absolute():
            raise InstallError(
                f"Handler asset '{raw_handler}' for agent '{agent_name}' must be a relative path."
            )
        if any(part == ".." for part in handler_path.parts):
            raise InstallError(
                f"Handler asset '{raw_handler}' for agent '{agent_name}' resolves outside "
                "the agent source directory."
            )
        handlers.append(handler_path)
    return handlers


def _validate_handler_assets(
    source_dir: Path,
    handler_paths: list[Path],
    agent_name: str,
) -> list[dict[str, Path]]:
    """Validate declared handler assets and return source paths to copy."""
    resolved_source_dir = source_dir.resolve()
    handler_assets: list[dict[str, Path]] = []
    for handler_path in handler_paths:
        resolved_handler = (resolved_source_dir / handler_path).resolve()
        if not resolved_handler.is_relative_to(resolved_source_dir):
            raise InstallError(
                f"Handler asset '{handler_path}' for agent '{agent_name}' resolves outside "
                "the agent source directory."
            )
        if not resolved_handler.exists():
            raise InstallError(
                f"Handler asset '{handler_path}' for agent '{agent_name}' does not exist."
            )
        handler_assets.append({
            "relative_path": handler_path,
            "source_path": resolved_handler,
        })
    return handler_assets


def _handler_install_target(
    agent_base: Path,
    agent_name: str,
    handler_path: Path,
) -> Path:
    """Return the harness-native install target for a private handler asset."""
    return agent_base / f"{agent_name}-handlers" / handler_path


def _copy_handler_asset(source_path: Path, install_target: Path) -> None:
    """Copy a private handler file or directory to a clean target path."""
    install_target.parent.mkdir(parents=True, exist_ok=True)
    if install_target.is_symlink():
        install_target.unlink()
    elif install_target.is_dir():
        shutil.rmtree(str(install_target))
    elif install_target.exists():
        install_target.unlink()

    if source_path.is_dir():
        shutil.copytree(str(source_path), str(install_target))
    else:
        shutil.copy2(str(source_path), str(install_target))


def _resolve_agent_targets(
    *,
    catalog: dict,
    entry: dict,
    prim: Any,
    agent_name: str,
    repo_root: Path,
    scope: str,
    harness: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return install target specs for the requested agent harness."""
    sources_map = entry.get("sources") or {}
    harness_missing: list[str] = []

    def target(
        harness_name: str,
        source: str,
        extension: str,
        cache_suffix: str = "",
        build_from_unified: bool = False,
    ) -> dict[str, Any]:
        base = _resolve_agent_base(catalog, prim, scope, repo_root, harness_name)
        return {
            "harness": harness_name,
            "source": source,
            "extension": extension,
            "cache_name": f"{agent_name}{cache_suffix}",
            "install_target": base / f"{agent_name}{extension}",
            "build_from_unified": build_from_unified,
        }

    if harness == "all" and sources_map:
        targets: list[dict[str, Any]] = []
        if sources_map.get("claude"):
            targets.append(target("claude_code", sources_map["claude"], ".md"))
        if sources_map.get("codex"):
            targets.append(target("codex", sources_map["codex"], ".toml", "-codex"))
        if sources_map.get("opencode"):
            targets.append(target("opencode", sources_map["opencode"], ".md", "-opencode"))
        if targets:
            return targets, harness_missing

    if harness == "codex" and sources_map.get("codex"):
        return [target("codex", sources_map["codex"], ".toml", "-codex")], harness_missing

    if harness == "opencode" and sources_map.get("opencode"):
        return [target("opencode", sources_map["opencode"], ".md", "-opencode")], harness_missing

    if not sources_map and entry.get("source"):
        source = entry["source"]
        if harness == "all":
            return [
                target("claude_code", source, ".md", build_from_unified=True),
                target("codex", source, ".toml", "-codex", build_from_unified=True),
            ], harness_missing
        if harness == "codex":
            return [target("codex", source, ".toml", "-codex", build_from_unified=True)], harness_missing
        if harness == "opencode":
            return [target("opencode", source, ".md", "-opencode", build_from_unified=True)], harness_missing
        return [target("claude_code", source, ".md", build_from_unified=True)], harness_missing

    try:
        source = _resolve_agent_source(entry, harness)
    except SourceError:
        harness_missing = _harness_missing_sources(entry, harness)
        try:
            source = _resolve_agent_source(entry, "all")
        except SourceError as exc:
            raise InstallError(
                f"Agent '{agent_name}' has no source for harness '{harness}'."
            ) from exc

    if harness != "all":
        harness_missing = _harness_missing_sources(entry, harness)

    if harness == "opencode":
        return [target("opencode", source, ".md", "-opencode")], harness_missing

    return [target("claude_code", source, ".md")], harness_missing


def _resolve_agent_base(
    catalog: dict,
    prim: Any,
    scope: str,
    repo_root: Path,
    harness: str,
) -> Path:
    """Resolve the base install directory for a harness-native agent."""
    if harness == "codex":
        codex_path = _resolve_codex_agent_base(catalog, scope, repo_root)
        if codex_path is not None:
            return codex_path
        return (Path.home() / ".codex" / "agents") if scope == "global" else (repo_root / ".codex" / "agents")
    if harness == "opencode":
        opencode_path = _resolve_opencode_agent_base(catalog, scope, repo_root)
        if opencode_path is not None:
            return opencode_path
        return (Path.home() / ".opencode" / "agents") if scope == "global" else (repo_root / ".opencode" / "agents")

    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for agent (scope={scope}). "
            "Check default_dirs.agents in library.yaml."
        )
    return canonical_base


def _resolve_codex_agent_base(
    catalog: dict,
    scope: str,
    repo_root: Path,
) -> Path | None:
    """Resolve default_dirs.agents default_codex/global_codex, if configured."""
    default_dirs = catalog.get("default_dirs", {}) or {}
    dirs_for_type = default_dirs.get("agents", []) or []
    home = Path.home()
    for entry in dirs_for_type:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            if scope == "project" and key == "default_codex":
                return _expand_agent_path(value, home, repo_root)
            if scope == "global" and key == "global_codex":
                return _expand_agent_path(value, home, repo_root)
    return None


def _resolve_opencode_agent_base(
    catalog: dict,
    scope: str,
    repo_root: Path,
) -> Path | None:
    """Resolve default_dirs.agents default_opencode/global_opencode, if configured."""
    default_dirs = catalog.get("default_dirs", {}) or {}
    dirs_for_type = default_dirs.get("agents", []) or []
    home = Path.home()
    for entry in dirs_for_type:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            if scope == "project" and key == "default_opencode":
                return _expand_agent_path(value, home, repo_root)
            if scope == "global" and key == "global_opencode":
                return _expand_agent_path(value, home, repo_root)
    return None


def _expand_agent_path(raw: str, home: Path, root: Path) -> Path:
    """Expand a configured agent path."""
    if raw.startswith("~/"):
        return home / raw[2:]
    if raw.startswith("/"):
        return Path(raw)
    return root / raw


def _is_safe_agent_name(name: str) -> bool:
    """Return True when ``name`` is a single safe path component.

    A safe agent name has no path separators ('/' or '\\') and is not a
    '.'/'..' traversal segment, so it cannot escape the per-harness agent
    directory when interpolated into install-target or handler-root paths
    (e.g. ``base / f"{name}.md"`` or ``install_target.parent /
    f"{name}-handlers"``). Guarding this prevents a removal name such as
    ``../shared`` from causing ``shutil.rmtree()`` to delete a directory
    outside the exact per-harness agent handler directory.
    """
    if not name or not name.strip():
        return False
    if "/" in name or "\\" in name:
        return False
    if name in (".", ".."):
        return False
    # Belt-and-suspenders: a safe name must be exactly one path component
    # with no traversal segment.
    parts = Path(name).parts
    return parts == (name,) and not any(part == ".." for part in parts)


def _recorded_bridge_targets(
    lock_entry: dict | None,
    allowed_roots: list[Path],
    repo_root: Path,
) -> tuple[list[Path], list[str]]:
    """Split lockfile-recorded bridge paths into removable and skipped.

    The lockfile records what was actually installed, including harness bridges
    that the conventional path computation does not reproduce (a Codex `.toml`
    beside a Claude `.md`). Removing only the conventional paths orphans those
    bridges, and because the lockfile entry disappears with the removal, nothing
    records the leftover afterwards -- it is invisible to `audit` and to a
    second `remove` while the harness still offers the agent.

    A path outside every allowed root is never deleted: an operator may have
    pointed a bridge somewhere of their own, and this function is not entitled
    to guess.
    """
    removable: list[Path] = []
    skipped: list[str] = []
    for bridge in (lock_entry or {}).get("bridge_symlinks", []) or []:
        raw_target = str(bridge).split(" -> ", 1)[0].strip()
        if not raw_target:
            continue
        path = Path(raw_target.rstrip("/"))
        if not path.is_absolute():
            path = repo_root / path
        if not any(path.is_relative_to(root) for root in allowed_roots):
            skipped.append(f"{path} (outside managed agent directories)")
            continue
        if not (path.exists() or path.is_symlink()):
            skipped.append(f"{path} (already absent)")
            continue
        removable.append(path)
    return removable, skipped


def remove_agent(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "claude_code",
) -> dict[str, Any]:
    """Remove an installed agent.

    Args:
        catalog: Parsed library.yaml dict.
        name: Agent name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness for removal ('claude_code', 'codex', 'opencode', 'all').
            Use 'all' to remove from every supported harness.

    Returns:
        Operation result dict.
    """
    # Mirror install_agent: cursor agent install is not supported, so remove is not either.
    if harness == "cursor":
        return error_result(
            f"Agent remove for harness 'cursor' is not supported. "
            "Cursor agents (.cursor/agents/) are not implemented by the library installer."
        )

    # Refuse unsafe names before building any install-target or handler-root
    # paths. Without this guard a name containing a path separator or a '..'
    # segment (e.g. '../shared') would be interpolated into handler_root and
    # let shutil.rmtree() delete a directory outside the per-harness agent dir.
    if not _is_safe_agent_name(name):
        return error_result(
            f"Agent remove refused: '{name}' is not a valid agent name "
            "(must be a single path component with no '/', '\\', or '..')."
        )

    prim = get_primitive("agent")
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    # Build the list of install targets to remove.
    if harness == "all":
        harness_targets = []
        for h in ("claude_code", "codex", "opencode"):
            base = _resolve_agent_base(catalog, prim, scope, repo_root, h)
            ext = ".toml" if h == "codex" else ".md"
            harness_targets.append(base / f"{name}{ext}")
    else:
        extension = ".toml" if harness == "codex" else ".md"
        canonical_base = _resolve_agent_base(catalog, prim, scope, repo_root, harness)
        harness_targets = [canonical_base / f"{name}{extension}"]

    # Every managed agent directory, regardless of the requested harness: a
    # bridge recorded in the lockfile belongs to this install even when the
    # caller only asked about one harness.
    allowed_roots = [
        _resolve_agent_base(catalog, prim, scope, repo_root, h)
        for h in ("claude_code", "codex", "opencode")
    ]
    lock_entry = get_entry(load_lockfile(lockfile_path), name, primitive_type="agent")
    bridge_targets, skipped_bridges = _recorded_bridge_targets(
        lock_entry, allowed_roots, repo_root
    )

    if dry_run:
        # Preview every harness target this remove would attempt to delete,
        # regardless of current existence. This mirrors install_agent's dry-run
        # (which lists all planned writes) so '--harness all' visibly routes to
        # every supported harness directory even when nothing is installed yet.
        ops = []
        for install_target in harness_targets:
            handler_root = install_target.parent / f"{name}-handlers"
            ops.append({
                "operation": "delete",
                "path": str(install_target),
                "details": f"remove {install_target}",
            })
            ops.append({
                "operation": "delete",
                "path": str(handler_root),
                "details": f"remove {handler_root}",
            })
        # The plan must list what the real removal deletes, or the preview is
        # not a preview.
        for bridge_path in bridge_targets:
            ops.append({
                "operation": "delete",
                "path": str(bridge_path),
                "details": f"remove lockfile-recorded bridge {bridge_path}",
            })
        for skipped in skipped_bridges:
            ops.append({
                "operation": "skip",
                "path": skipped.split(" (")[0],
                "details": f"leave bridge alone: {skipped}",
            })
        ops.append({
            "operation": "remove_lockfile_entry",
            "path": str(lockfile_path),
            "details": f"remove '{name}'",
        })
        return dry_run_result(ops, summary=f"Would remove agent '{name}'")

    removed_files = []
    for install_target in harness_targets:
        handler_root = install_target.parent / f"{name}-handlers"
        if install_target.is_symlink():
            install_target.unlink()
            removed_files.append(str(install_target))
        elif install_target.exists():
            install_target.unlink()
            removed_files.append(str(install_target))
        if handler_root.is_symlink():
            handler_root.unlink()
            removed_files.append(str(handler_root))
        elif handler_root.is_dir():
            shutil.rmtree(str(handler_root))
            removed_files.append(str(handler_root))
        elif handler_root.exists():
            handler_root.unlink()
            removed_files.append(str(handler_root))

    for bridge_path in bridge_targets:
        if bridge_path.is_symlink():
            bridge_path.unlink()
            removed_files.append(str(bridge_path))
        elif bridge_path.is_dir():
            shutil.rmtree(str(bridge_path))
            removed_files.append(str(bridge_path))
        elif bridge_path.exists():
            bridge_path.unlink()
            removed_files.append(str(bridge_path))

    lock_data = load_lockfile(lockfile_path)
    entry_removed = remove_entry(lock_data, name, primitive_type="agent")
    save_lockfile(lockfile_path, lock_data)

    if not entry_removed and not removed_files:
        # Reporting success here sends the operator away believing the state
        # changed. The most common cause is a scope mismatch: `remove` defaults
        # to project scope while the entry is installed globally.
        return error_result(
            f"Agent '{name}' is not installed in scope '{scope}' "
            f"(lockfile {lockfile_path}); nothing was removed."
        )

    return success(
        data={
            "name": name,
            "removed_files": removed_files,
            "skipped_bridges": skipped_bridges,
        },
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


def _try_build_agent(
    *,
    build_script: Path,
    source_file: Path,
    output_dir: Path,
    harness: str,
    agent_name: str,
) -> Path:
    """Run build-agent.py and return the harness-native built file."""
    if not build_script.exists():
        raise InstallError(
            f"build-agent.py not found at {build_script}; cannot build unified agent '{agent_name}'."
        )

    build_harness = {"claude_code": "claude"}.get(harness, harness)
    result = subprocess.run(
        [
            "python3",
            str(build_script),
            str(source_file),
            f"--harness={build_harness}",
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise InstallError(
            f"Failed to build unified agent '{agent_name}' for {harness}: {result.stderr.strip()}"
        )

    extension = ".toml" if build_harness == "codex" else ".md"
    built_file = output_dir / f"{agent_name}{extension}"
    if not built_file.exists():
        raise InstallError(
            f"Unified agent build for '{agent_name}' did not produce {built_file}."
        )
    return built_file


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
