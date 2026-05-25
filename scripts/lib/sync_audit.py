"""
sync_audit.py — Sync and audit implementations for the library CLI.

sync: Reads the lockfile and re-installs every entry via the matching primitive installer.
audit: Computes content checksums for installed entries and compares against lockfile.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .errors import EXIT_NOT_FOUND, InstallError, LibraryError
from .installers.standard import _parse_standard_category
from .lockfile import (
    compute_checksum,
    compute_directory_hash,
    find_lockfile,
    get_entry,
    load_lockfile,
)
from .output import dry_run_result, success
from .paths import resolve_install_paths
from .primitives import get_primitive
from .source import parse_source


def _check_standard_path_drift(
    entry: dict[str, Any],
    catalog: dict[str, Any],
    repo_root: Path,
    scope: str,
) -> bool:
    """Return True if a standard entry's install_target doesn't match the expected category-mirror path.

    Returns False if:
    - entry type is not 'standard'
    - source is not a single-file URL (path_type != 'file')
    - category cannot be parsed from the source path
    - any exception occurs (audit path must never raise)
    """
    try:
        if entry.get("type") != "standard":
            return False

        source_str = entry.get("source", "")
        if not source_str:
            return False

        parsed = parse_source(source_str)

        if parsed.path_type != "file":
            return False

        if not parsed.file_path:
            return False

        category, filename = _parse_standard_category(parsed.file_path)
        if category is None or filename is None:
            return False

        prim = get_primitive("standard")
        if prim is None:
            return False

        install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
        canonical_base = install_paths.get("canonical")
        if canonical_base is None:
            return False

        expected_install_target = canonical_base / category / filename
        actual_resolved = _entry_path(entry.get("install_target", "").rstrip("/"), repo_root)

        return actual_resolved != expected_install_target

    except (OSError, ValueError, AttributeError, KeyError, ImportError):
        return False


def cmd_sync_impl(
    catalog: dict,
    primitive: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    target_name: str | None = None,
) -> dict[str, Any]:
    """Sync: re-install entries of a given primitive from the lockfile.

    Args:
        catalog: Parsed library.yaml dict.
        primitive: Primitive type to sync ('skill', 'agent', etc.), or 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness.
        target_name: Optional installed entry name to refresh.

    Returns:
        Operation result dict with list of synced entries.
    """
    primitive_info = (
        get_primitive(primitive)
        if primitive not in ("all", "search", None)
        else None
    )
    if primitive_info is not None:
        primitive = primitive_info.name

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    installed = lock_data.get("installed", [])

    if target_name is not None:
        primitive_type = primitive if primitive and primitive not in ("all", "search") else None
        entry = get_entry(lock_data, target_name, primitive_type=primitive_type)
        if entry is None:
            label = f"{primitive}:{target_name}" if primitive_type else target_name
            raise LibraryError(
                f"{label} is not installed in {scope} scope.",
                exit_code=EXIT_NOT_FOUND,
            )
        entries = [entry]
    elif primitive and primitive not in ("all", "search"):
        entries = [e for e in installed if e.get("type") == primitive]
    else:
        entries = list(installed)

    if dry_run:
        ops = []
        for entry in entries:
            ops.append({
                "operation": "reinstall",
                "path": entry.get("install_target", ""),
                "details": f"re-install {entry.get('type', '?')}:{entry.get('name', '?')}",
            })
        return dry_run_result(
            ops,
            summary=f"Would sync {len(entries)} entries from lockfile",
        )

    synced = []
    failed = []
    for entry in entries:
        entry_name = entry.get("name", "")
        entry_type = entry.get("type", "")
        try:
            reinstall_entry(catalog, entry, repo_root, scope, harness)
            synced.append(f"{entry_type}:{entry_name}")
        except Exception as exc:
            failed.append({"name": entry_name, "type": entry_type, "error": str(exc)})

    return success(
        data={
            "synced": synced,
            "failed": failed,
            "total": len(entries),
        },
        message=f"Synced {len(synced)}/{len(entries)} entries.",
    )


def reinstall_entry(
    catalog: dict,
    entry: dict,
    repo_root: Path,
    scope: str,
    harness: str,
) -> None:
    """Re-install a single lockfile entry."""
    entry_name = entry.get("name", "")
    entry_type = entry.get("type", "")
    install_mode = entry.get("install_mode", "vendor")

    if entry_type == "skill":
        from .installers.skill import install_skill
        install_skill(
            catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, install_mode=install_mode
        )
    elif entry_type == "agent":
        from .installers.agent import install_agent
        install_agent(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "prompt":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="prompt", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "script":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="script", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "standard":
        from .installers.standard import install_standard
        install_standard(
            catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, install_mode=install_mode
        )
    elif entry_type == "model-standard":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="model-standard", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "agent-base":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="agent-base", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "workflow":
        from .installers.simple_file import install_simple_file
        install_simple_file(catalog=catalog, primitive_name="workflow", name=entry_name,
                           repo_root=repo_root, scope=scope, harness=harness, install_mode=install_mode)
    elif entry_type == "mcp":
        from .installers.mcp_installer import install_mcp
        install_mcp(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    elif entry_type == "guardrail":
        from .installers.guardrail_installer import install_guardrail
        install_guardrail(catalog=catalog, name=entry_name, repo_root=repo_root, scope=scope, harness=harness)
    # Unknown types are silently skipped


def cmd_audit_impl(
    catalog: dict,
    primitive: str,
    repo_root: Path,
    scope: str = "project",
    drift_only: bool = False,
    skip_upstream: bool = False,
) -> dict[str, Any]:
    """Audit: compute checksums and compare against lockfile + check upstream drift.

    Returns a result with status 'clean' or 'drift'.
    Schema: {"status": "clean"|"drift", "entries": [...]}

    Each entry has a "status" field and a "drift_kind" field:
      - status:
        - "drift": local-tamper, upstream-behind, or both
        - "clean": no drift
        - "unknown": entry without checksum_type, or path not found
      - drift_kind (present when status="drift"):
        - "local":    installed files differ from lockfile content_sha
        - "upstream": catalog source has moved beyond lockfile source_commit
        - "both":     both local-tamper and upstream-behind

    With drift_only=True, only entries with status="drift" are included in output.

    Exit codes (returned as metadata for the CLI layer):
      - 0: all clean (or no entries)
      - 2: drift detected
      - 1: error

    Args:
        catalog: Parsed library.yaml dict.
        primitive: Primitive type to audit, or all if 'all'.
        repo_root: Project root.
        scope: 'project' or 'global'.
        drift_only: If True, filter output to only drifted entries.
        skip_upstream: If True, do not perform the network-bound git ls-remote
            checks. Use in tests or offline contexts. Local-tamper checks still run.

    Returns:
        Audit result dict with stable schema.
    """
    primitive_info = (
        get_primitive(primitive)
        if primitive not in ("all", "search", None)
        else None
    )
    if primitive_info is not None:
        primitive = primitive_info.name

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    installed = lock_data.get("installed", [])

    # Filter to primitive
    if primitive and primitive not in ("all", "search"):
        entries = [e for e in installed if e.get("type") == primitive]
    else:
        entries = list(installed)

    if not entries:
        return {
            "status": "clean",
            "entries": [],
        }

    # Pre-compute upstream status for all entries in one batch so we share the
    # remote_cache across git ls-remote calls (one network request per repo).
    # cmd_status_impl handles offline gracefully — if a probe fails, the entry
    # gets upstream_status="unknown" and we don't flag drift on that axis.
    upstream_by_key: dict[tuple[str, str], str] = {}
    if not skip_upstream:
        try:
            from .status import cmd_status_impl  # local import to avoid cycle

            status_result = cmd_status_impl(
                catalog=catalog,
                primitive=primitive if primitive else "all",
                repo_root=repo_root,
                scope=scope,
                offline=False,
            )
            for status_entry in status_result.get("entries", []):
                key = (status_entry.get("name", ""), status_entry.get("primitive", ""))
                upstream_by_key[key] = status_entry.get("upstream_status", "unknown")
        except Exception:
            # Upstream probe is best-effort. Network failures must not break audit
            # of local-tamper drift; we report upstream as "unknown" for everything.
            upstream_by_key = {}

    audit_entries = []
    any_drift = False

    for entry in entries:
        entry_name = entry.get("name", "")
        expected_sha = entry.get("content_sha256") or entry.get("checksum_sha256", "")
        checksum_type = entry.get("checksum_type", None)
        cache_path_str = entry.get("cache_path", "").rstrip("/")
        install_target_str = entry.get("install_target", "")

        actual_sha = ""
        drift = False
        entry_status = "unknown"

        # Entries without checksum_type report unknown, never drift unless an
        # additional health check below finds a broken installed artifact.
        if checksum_type is None:
            entry_status = "unknown"
        elif checksum_type == "file":
            # For file-type: check single file
            for path_str in [install_target_str, cache_path_str]:
                if not path_str:
                    continue
                p = _entry_path(path_str, repo_root)
                if p.is_symlink():
                    p = p.resolve()
                if p.is_file():
                    try:
                        actual_sha = compute_checksum(p)
                    except OSError:
                        actual_sha = ""
                    break
                elif p.is_dir():
                    primary = _find_primary_artifact(p, entry_name)
                    if primary and primary.exists():
                        try:
                            actual_sha = compute_checksum(primary)
                        except OSError:
                            actual_sha = ""
                    break

            if expected_sha and actual_sha and expected_sha != actual_sha:
                drift = True
                any_drift = True
                entry_status = "drift"
            elif actual_sha:
                entry_status = "clean"
            else:
                entry_status = "unknown"

        elif checksum_type == "directory":
            # Directory-based checksum: hash the local installed directory first.
            # This detects drift in vendored project copies even when the cache
            # still matches upstream.
            dir_path = None
            for path_str in [install_target_str, cache_path_str]:
                if not path_str:
                    continue
                p = _entry_path(path_str, repo_root)
                if p.is_symlink():
                    p = p.resolve()
                if p.is_dir():
                    dir_path = p
                    break

            if dir_path is not None:
                try:
                    actual_sha = compute_directory_hash(dir_path)
                except (FileNotFoundError, OSError):
                    actual_sha = ""
                    entry_status = "unknown"

                if expected_sha and actual_sha and expected_sha != actual_sha:
                    drift = True
                    any_drift = True
                    entry_status = "drift"
                elif actual_sha:
                    entry_status = "clean"
                else:
                    entry_status = "unknown"
            else:
                entry_status = "unknown"
        else:
            # Unknown checksum_type: report unknown
            entry_status = "unknown"

        # Upstream-drift check: did the catalog source move beyond what's pinned
        # in the lockfile? This is independent of local-tamper drift.
        entry_type = entry.get("type", "")
        upstream_status = upstream_by_key.get((entry_name, entry_type), "unknown")
        upstream_behind = upstream_status == "behind"

        audit_entry = {
            "name": entry_name,
            "primitive": entry_type,
            "scope": scope,
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "drift": drift,
            "status": entry_status,
            "upstream_status": upstream_status,
        }

        # Promote to "drift" if upstream has moved. Track drift_kind so consumers
        # can tell why (local tamper vs upstream behind vs both — different fixes).
        if upstream_behind:
            audit_entry["drift"] = True
            audit_entry["status"] = "drift"
            audit_entry["drift_kind"] = "both" if drift else "upstream"
            any_drift = True
        elif drift:
            audit_entry["drift_kind"] = "local"

        agent_frontmatter_issue = _audit_claude_agent_frontmatter(
            entry=entry,
            repo_root=repo_root,
            scope=scope,
        )
        if agent_frontmatter_issue:
            audit_entry["agent_frontmatter_issue"] = agent_frontmatter_issue
            audit_entry["repair_hint"] = agent_frontmatter_issue["repair_hint"]
            audit_entry["drift"] = True
            audit_entry["status"] = "drift"
            # Preserve drift_kind from upstream check; otherwise mark as local.
            audit_entry.setdefault("drift_kind", "local")
            any_drift = True

        # Path conformance check: single-file standards should be at category-mirror paths.
        # When path drift co-occurs with upstream drift, upgrade drift_kind to "both"
        # so that the user can see there are two separate issues. setdefault() is wrong
        # here: it silently discards the path-drift signal when "upstream" is already set.
        if _check_standard_path_drift(entry, catalog, repo_root, scope):
            audit_entry["drift"] = True
            audit_entry["status"] = "drift"
            any_drift = True
            if audit_entry.get("drift_kind") == "upstream":
                audit_entry["drift_kind"] = "both"
            else:
                audit_entry.setdefault("drift_kind", "local")

        audit_entries.append(audit_entry)

    # Apply drift_only filter: exclude non-drifted entries
    if drift_only:
        audit_entries = [e for e in audit_entries if e.get("drift") is True]

    return {
        "status": "drift" if any_drift else "clean",
        "entries": audit_entries,
    }


def _find_primary_artifact(cache_dir: Path, name: str) -> Path | None:
    """Find the primary artifact in a cache directory."""
    candidates = [
        cache_dir / f"{name}.md",
        cache_dir / "SKILL.md",
        cache_dir / "STANDARD.md",
        cache_dir / "agent.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    md_files = list(cache_dir.rglob("*.md"))
    return md_files[0] if md_files else None


def _audit_claude_agent_frontmatter(
    entry: dict[str, Any],
    repo_root: Path,
    scope: str,
) -> dict[str, str] | None:
    """Return a frontmatter issue for an installed Claude agent, if any."""
    if entry.get("type") != "agent":
        return None

    entry_name = entry.get("name", "")
    agent_path = _resolve_agent_markdown_path(
        entry.get("install_target", ""),
        entry_name,
        repo_root,
    )
    if agent_path is None:
        return None

    try:
        text = agent_path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return _agent_frontmatter_issue(
            code="missing_frontmatter",
            message="Claude agent file does not start with YAML frontmatter.",
            path=agent_path,
            name=entry_name,
            scope=scope,
        )

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return _agent_frontmatter_issue(
            code="invalid_frontmatter",
            message="Claude agent frontmatter has no closing delimiter.",
            path=agent_path,
            name=entry_name,
            scope=scope,
        )

    frontmatter_text = "\n".join(lines[1:closing_index])
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}

    description = frontmatter.get("description") if isinstance(frontmatter, dict) else None
    if not description:
        return _agent_frontmatter_issue(
            code="missing_description",
            message="Claude agent frontmatter is missing a description field.",
            path=agent_path,
            name=entry_name,
            scope=scope,
        )

    return None


def _resolve_agent_markdown_path(
    install_target: str,
    entry_name: str,
    repo_root: Path,
) -> Path | None:
    """Resolve an installed Claude agent markdown file from a lockfile target."""
    if not install_target:
        return None

    target = _entry_path(install_target, repo_root)
    if target.is_symlink():
        target = target.resolve()

    if target.is_file() and target.suffix == ".md":
        return target
    if not target.is_dir():
        return None

    primary = _find_primary_artifact(target, entry_name)
    if primary and primary.suffix == ".md":
        return primary
    return None


def _agent_frontmatter_issue(
    code: str,
    message: str,
    path: Path,
    name: str,
    scope: str,
) -> dict[str, str]:
    """Build a stable Claude agent frontmatter issue payload."""
    return {
        "code": code,
        "message": message,
        "path": str(path),
        "repair_hint": (
            f"library agent sync {name} --scope {scope} --harness claude_code"
        ),
    }


def _entry_path(path_str: str, repo_root: Path) -> Path:
    """Resolve a lockfile path relative to repo_root when needed."""
    path = Path(path_str.rstrip("/"))
    if path.is_absolute():
        return path
    return repo_root / path
