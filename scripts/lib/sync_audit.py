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

from .errors import EXIT_NOT_FOUND, LibraryError
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


_PLATFORM_ROOT = Path(__file__).resolve().parents[2]


def _library_skill_targets() -> tuple[Path, ...]:
    """Return bootstrap-managed Library skill targets for present harnesses."""
    home = Path.home()
    candidates = (
        home / ".claude" / "skills" / "library",
        home / ".codex" / "skills" / "library",
        home / ".agents" / "skills" / "library",
        home / ".opencode" / "skills" / "library",
    )
    return tuple(candidate for candidate in candidates if candidate.parent.parent.is_dir())


def _library_surface_hash(root: Path) -> str:
    """Hash the Library skill plus its deterministic Python control plane."""
    files = [root / "SKILL.md", root / "scripts" / "library.py"]
    lib_root = root / "scripts" / "lib"
    if lib_root.is_dir():
        files.extend(sorted(lib_root.rglob("*.py")))

    digest = hashlib.sha256()
    for file_path in files:
        if not file_path.is_file():
            digest.update(str(file_path.relative_to(root)).encode())
            digest.update(b"\0missing\0")
            continue
        digest.update(str(file_path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(compute_checksum(file_path).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _audit_library_bootstrap() -> list[dict[str, Any]]:
    """Report diverged or missing bootstrap-installed Library skill surfaces."""
    source_path = _PLATFORM_ROOT / "SKILL.md"
    if not source_path.is_file():
        return []

    expected_sha = _library_surface_hash(_PLATFORM_ROOT)
    findings: list[dict[str, Any]] = []
    for target_root in _library_skill_targets():
        try:
            actual_sha = _library_surface_hash(target_root) if target_root.is_dir() else ""
        except OSError:
            actual_sha = ""
        if actual_sha == expected_sha:
            continue
        findings.append({
            "name": "library",
            "primitive": "skill",
            "scope": "global",
            "expected_sha": expected_sha,
            "actual_sha": actual_sha,
            "source_path": str(_PLATFORM_ROOT),
            "install_target": str(target_root),
            "drift": True,
            "status": "drift",
            "drift_kind": "local",
            "reason": (
                "library_bootstrap_content_mismatch"
                if actual_sha
                else "library_bootstrap_target_missing"
            ),
            "upstream_status": "unknown",
        })
    return findings


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

    if scope == "project" and any(entry.get("type") == "mcp" for entry in entries):
        from .installers.mcp_installer import require_global_mcp_scope

        require_global_mcp_scope(scope, "sync")

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
    elif entry_type == "runtime-config":
        from .runtime_config import install_runtime_config
        install_runtime_config(catalog=catalog, name=entry_name, repo_root=repo_root,
                               scope=scope, harness=harness, install_mode=install_mode)
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
        - "unknown": path not found or checksum type is unsupported
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

    bootstrap_findings = (
        _audit_library_bootstrap()
        if primitive in ("all", "search", None)
        else []
    )

    if not entries and not bootstrap_findings:
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

    audit_entries = list(bootstrap_findings)
    any_drift = bool(bootstrap_findings)

    for entry in entries:
        entry_name = entry.get("name", "")
        expected_sha = entry.get("content_sha256") or entry.get("checksum_sha256", "")
        checksum_type = entry.get("checksum_type", None)
        cache_path_str = entry.get("cache_path", "").rstrip("/")
        install_target_str = entry.get("install_target", "")

        actual_sha = ""
        drift = False
        entry_status = "unknown"

        legacy_checksum_type_missing = checksum_type is None

        # A tracked entry without checksum metadata cannot prove integrity.
        # Report actionable drift so recurring audits cannot silently pass it.
        if checksum_type is None:
            drift = True
            any_drift = True
            entry_status = "drift"
        elif checksum_type == "file":
            # For file-type: check single file.
            # Detect missing install target first: a lockfile path that ends with
            # a known single-file extension (*.js, *.md, *.py, *.toml) that does
            # not exist is explicitly drift, not "unknown".
            _install_p = _entry_path(install_target_str, repo_root) if install_target_str else None
            if (
                _install_p is not None
                and _install_p.suffix in (".js", ".md", ".py", ".toml", ".yml", ".yaml")
                and not _install_p.exists()
                and not _install_p.is_symlink()
            ):
                drift = True
                any_drift = True
                entry_status = "missing"
            else:
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
        if legacy_checksum_type_missing:
            audit_entry["reason"] = "legacy_checksum_type_missing"

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

        # An agent that resolves a handler at runtime is broken without it, and
        # the failure only surfaces when the agent runs. ci-monitor and release
        # were both installed without their handlers, and nothing reported it
        # (CL-b6oy).
        handler_issue = _check_missing_agent_handlers(entry, catalog, scope)
        if handler_issue:
            audit_entry["missing_handlers"] = handler_issue["missing"]
            audit_entry["repair_hint"] = handler_issue["repair_hint"]
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


def _catalog_entry_for(entry: dict, catalog: dict) -> dict | None:
    """Return the catalog entry matching an installed lockfile entry, or None."""
    primitive = entry.get("type", "")
    name = entry.get("name", "")
    if not primitive or not name:
        return None
    plural = f"{primitive}s" if not primitive.endswith("s") else primitive
    library = catalog.get("library", {}) or {}
    for key in (plural, primitive):
        for candidate in library.get(key, []) or []:
            if isinstance(candidate, dict) and candidate.get("name") == name:
                return candidate
    return None


def _check_missing_agent_handlers(
    entry: dict,
    catalog: dict,
    scope: str,
) -> dict[str, Any] | None:
    """Report handler assets an installed agent declares but does not have.

    The agent markdown resolves these paths at runtime, so a missing handler is a
    broken agent that looks installed.

    Completeness is judged against the Layer-B cache the lockfile points at, not
    against "the directory has something in it". A directory holding only an
    unrelated leftover used to pass while the handler scripts were gone -- a
    false negative on exactly the partial rot this check exists to catch
    (CL-8a7z).
    """
    if entry.get("type") != "agent":
        return None
    catalog_entry = _catalog_entry_for(entry, catalog)
    if not catalog_entry:
        return None
    declared = catalog_entry.get("handlers") or []
    if not declared:
        return None
    install_target = entry.get("install_target", "")
    if not install_target:
        return None
    name = entry.get("name", "")
    handler_root = Path(install_target).parent / f"{name}-handlers"

    if not handler_root.is_dir() or not any(handler_root.iterdir()):
        return {
            "missing": [str(handler_root)],
            "repair_hint": (
                f"Agent '{name}' declares handler assets but {handler_root} is missing or "
                f"empty; the agent resolves that path at runtime. Reinstall with "
                f"`library agent use {name} --scope {scope}`."
            ),
        }

    missing_files = _missing_recorded_handler_files(entry, handler_root)
    if not missing_files:
        return None
    return {
        "missing": missing_files,
        "repair_hint": (
            f"Agent '{name}' is missing handler files that were installed with it: "
            f"{', '.join(missing_files)}. Reinstall with "
            f"`library agent use {name} --scope {scope}`."
        ),
    }


def _missing_recorded_handler_files(entry: dict, handler_root: Path) -> list[str]:
    """Return handler files recorded for this install that are absent on disk.

    The lockfile records each handler target as `<install path> -> <cache path>`,
    and the cache holds the exact tree that was installed. Comparing against it
    catches a directory that survived while its contents did not.

    An entry recorded before handler targets were tracked, or whose cache is
    gone, yields nothing: this check reports rot it can prove, and does not
    accuse history it cannot inspect.
    """
    missing: list[str] = []
    for bridge in entry.get("bridge_symlinks", []) or []:
        raw = str(bridge)
        if " -> " not in raw:
            continue
        target_str, _, cache_str = raw.partition(" -> ")
        target = Path(target_str.strip().rstrip("/"))
        cache = Path(cache_str.strip().rstrip("/"))
        try:
            if not target.is_relative_to(handler_root) and target != handler_root:
                continue
        except ValueError:
            continue
        if not cache.is_dir():
            continue
        for cached_file in sorted(cache.rglob("*")):
            if not cached_file.is_file():
                continue
            relative = cached_file.relative_to(cache)
            installed = target / relative
            if not installed.exists():
                missing.append(str(installed))
    return missing


def _find_primary_artifact(cache_dir: Path, name: str) -> Path | None:
    """Find the primary artifact in a cache directory."""
    candidates = [
        cache_dir / f"{name}.md",
        cache_dir / f"{name}.js",
        cache_dir / f"{name}.py",
        cache_dir / "SKILL.md",
        cache_dir / "STANDARD.md",
        cache_dir / "agent.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Prefer .md files; fall back to .js/.py when only a workflow or script is cached
    md_files = sorted(cache_dir.rglob("*.md"))
    if md_files:
        return md_files[0]
    js_files = sorted(cache_dir.rglob("*.js"))
    if js_files:
        return js_files[0]
    return None


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
