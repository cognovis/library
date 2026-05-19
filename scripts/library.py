#!/usr/bin/env python3
"""
library.py — Deterministic library engine CLI.

Canonical command grammar:
  python3 scripts/library.py <primitive> <verb> [name-or-query] [options]

Supported primitives: skill, agent, prompt, script, standard, guardrail, mcp,
                      model-standard, agent-base

Supported verbs: list, use, remove, sync, search, audit

Options:
  --json        Machine-readable JSON output
  --dry-run     Show planned operations without mutating files
  --scope       project (default) or global
  --target-project
                Project root for project-scoped writes
  --harness     claude_code, codex, opencode, or all (where applicable)

Exit codes:
  0  success
  1  general failure / validation error
  2  not found
  3  ambiguous match (multiple results)
  4  dependency not installed
  5  (reserved for future use)

Usage examples:
  python3 scripts/library.py skill list
  python3 scripts/library.py skill list --json
  python3 scripts/library.py standard use english-only --scope global
  python3 scripts/library.py skill use dolt --dry-run --json
  python3 scripts/library.py skill use dolt --symlink --json
  python3 scripts/library.py search firecrawl
  python3 scripts/library.py catalog match --primitive-type=standard --topics=python,uv --writable-only
  python3 scripts/library.py installed --diff-catalog
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Make `lib` importable when running as a script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TOOL_ROOT = SCRIPT_DIR.parent

from lib.catalog import find_repo_root, get_entries, load_catalog, search_all
from lib.errors import (
    EXIT_AMBIGUOUS,
    EXIT_DEPENDENCY_MISSING,
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_NOT_FOUND,
    LibraryError,
)
from lib.lockfile import find_lockfile, load_lockfile
from lib.installed import cmd_installed_impl, format_installed_output
from lib.output import (
    format_list_output,
    format_search_output,
    format_table,
    print_json,
    dry_run_result,
    success,
    error_result,
)
from lib.primitives import PRIMITIVES, all_primitive_names, get_primitive
from lib.status import cmd_status_impl
from lib.sync_audit import cmd_audit_impl, cmd_sync_impl, reinstall_entry


VALID_PRIMITIVES = all_primitive_names()
VALID_VERBS = ["list", "use", "remove", "sync", "search", "audit"]
DEFAULT_LIFECYCLE_SCOPE = "both"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the library CLI."""
    parser = argparse.ArgumentParser(
        prog="library.py",
        description=(
            "Deterministic library engine — manages skills, agents, standards, and more.\n\n"
            "Canonical grammar: python3 scripts/library.py <primitive> <verb> [name] [options]\n\n"
            f"Supported primitives: {', '.join(VALID_PRIMITIVES)}\n"
            f"Supported verbs: {', '.join(VALID_VERBS)}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="library.py 2.0.0 (CL-8ph)",
    )

    subparsers = parser.add_subparsers(
        dest="primitive",
        metavar="primitive",
        help="Primitive type to operate on",
    )

    # Add a subparser for each primitive + the cross-cutting `search` command
    for prim_name in VALID_PRIMITIVES:
        prim = get_primitive(prim_name)
        prim_parser = subparsers.add_parser(
            prim_name,
            aliases=prim.aliases if prim else (),
            help=prim.description if prim else f"{prim_name} primitives",
        )
        prim_parser.set_defaults(primitive=prim_name)

        verb_sub = prim_parser.add_subparsers(
            dest="verb",
            metavar="verb",
            help="Action to perform",
        )

        # list
        list_p = verb_sub.add_parser("list", help="List catalog entries")
        list_p.add_argument("--json", action="store_true", help="Output JSON")
        list_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
            help="Scope (default: project)",
        )

        # use
        use_p = verb_sub.add_parser("use", help="Install a catalog entry")
        use_p.add_argument("name", nargs="?", default=None, help="Entry name or keyword")
        use_p.add_argument("--json", action="store_true", help="Output JSON")
        use_p.add_argument("--dry-run", action="store_true", help="Show planned writes, no mutation")
        use_p.add_argument(
            "--symlink",
            action="store_true",
            help="Install Layer C as a symlink into the cache instead of a vendored copy",
        )
        use_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default=None,
            help="Scope (project or global; default: from catalog entry's default_scope, fallback project)",
        )
        use_p.add_argument(
            "--target-project",
            type=Path,
            default=None,
            help=(
                "Project root for project-scoped writes "
                "(default: current git root or cwd)"
            ),
        )
        use_p.add_argument(
            "--harness",
            choices=["claude_code", "codex", "opencode", "all"],
            default="all",
            help="Target harness (default: all)",
        )

        # remove
        remove_p = verb_sub.add_parser("remove", help="Remove an installed entry")
        remove_p.add_argument("name", nargs="?", default=None, help="Entry name")
        remove_p.add_argument("--json", action="store_true", help="Output JSON")
        remove_p.add_argument("--dry-run", action="store_true", help="Show planned removals")
        remove_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
        )
        remove_p.add_argument(
            "--target-project",
            type=Path,
            default=None,
            help=(
                "Project root for project-scoped writes "
                "(default: current git root or cwd)"
            ),
        )

        # search
        search_p = verb_sub.add_parser("search", help="Search within this primitive")
        search_p.add_argument("query", nargs="?", default=None, help="Search keyword")
        search_p.add_argument("--json", action="store_true", help="Output JSON")

        # sync
        sync_p = verb_sub.add_parser("sync", help="Re-pull installed entries from lockfile")
        sync_p.add_argument("name", nargs="?", default=None, help="Installed entry name")
        sync_p.add_argument("--json", action="store_true", help="Output JSON")
        sync_p.add_argument("--dry-run", action="store_true", help="Show planned syncs")
        sync_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
        )
        sync_p.add_argument(
            "--target-project",
            type=Path,
            default=None,
            help=(
                "Project root for project-scoped writes "
                "(default: current git root or cwd)"
            ),
        )
        sync_p.add_argument(
            "--harness",
            choices=["claude_code", "codex", "opencode", "all"],
            default="all",
        )

        # audit
        audit_p = verb_sub.add_parser("audit", help="Detect drift in installed entries")
        audit_p.add_argument("--json", action="store_true", help="Output JSON")
        audit_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
        )
        audit_p.add_argument(
            "--drift-only",
            action="store_true",
            help="Only show drifted entries; exit 2 if any drift, 0 if clean",
        )
        audit_p.add_argument(
            "--no-upstream",
            action="store_true",
            help=(
                "Skip the upstream-drift check (git ls-remote). Use in offline "
                "or CI contexts. Local-tamper drift is still detected."
            ),
        )
        audit_p.add_argument(
            "--target-project",
            type=Path,
            default=None,
            help=(
                "Project root for project-scoped writes "
                "(default: current git root or cwd)"
            ),
        )

    # Top-level search (cross-primitive)
    search_parser = subparsers.add_parser(
        "search",
        help="Search across all primitives",
    )
    search_parser.add_argument("query", nargs="?", default=None, help="Search keyword")
    search_parser.add_argument("--json", action="store_true", help="Output JSON")

    # Top-level audit (cross-primitive)
    top_audit_parser = subparsers.add_parser(
        "audit",
        help="Detect drift in all installed entries across primitives",
    )
    top_audit_parser.add_argument("--json", action="store_true", help="Output JSON")
    top_audit_parser.add_argument(
        "--scope",
        choices=["project", "global", "both"],
        default=DEFAULT_LIFECYCLE_SCOPE,
        help=f"Scope to audit (default: {DEFAULT_LIFECYCLE_SCOPE})",
    )
    top_audit_parser.add_argument(
        "--drift-only",
        action="store_true",
        help="Only show drifted entries; exit 2 if any drift, 0 if clean",
    )
    top_audit_parser.add_argument(
        "--no-upstream",
        action="store_true",
        help=(
            "Skip the upstream-drift check (git ls-remote). Use in offline "
            "or CI contexts. Local-tamper drift is still detected."
        ),
    )
    top_audit_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Explicit project root for project-scope reads",
    )

    # Top-level status (cross-primitive, checks upstream SHAs without cloning)
    status_parser = subparsers.add_parser(
        "status",
        help="Check upstream status for all installed entries (no clone required)",
    )
    status_parser.add_argument("--json", action="store_true", help="Output JSON")
    status_parser.add_argument(
        "--scope",
        choices=["project", "global", "both"],
        default=DEFAULT_LIFECYCLE_SCOPE,
        help=f"Scope to check (default: {DEFAULT_LIFECYCLE_SCOPE})",
    )
    status_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Explicit project root for project-scope reads",
    )
    status_parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not query upstream remotes; report upstream as unknown",
    )

    # Top-level installed (cross-primitive, cross-scope installed view)
    installed_parser = subparsers.add_parser(
        "installed",
        help="Show installed entries across project and global scopes",
    )
    installed_parser.add_argument("--json", action="store_true", help="Output JSON")
    installed_parser.add_argument(
        "--scope",
        choices=["project", "global", "both"],
        default="both",
        help="Scope to show (default: both)",
    )
    installed_parser.add_argument(
        "--primitive",
        dest="primitive_filter",
        choices=VALID_PRIMITIVES,
        default=None,
        help="Filter to one primitive type",
    )
    installed_parser.add_argument(
        "--diff-catalog",
        action="store_true",
        help="Compare installed entries against the resolved library.yaml catalog",
    )
    installed_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Explicit project root for project-scope reads",
    )
    installed_parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not query upstream remotes; report upstream as unknown",
    )

    # Top-level sync (cross-primitive, with skip-on-current logic)
    top_sync_parser = subparsers.add_parser(
        "sync",
        help="Sync all installed entries across primitives (skip if already current)",
    )
    top_sync_parser.add_argument("--json", action="store_true", help="Output JSON")
    top_sync_parser.add_argument("--dry-run", action="store_true", help="Show planned syncs")
    top_sync_parser.add_argument("--force", action="store_true", help="Re-install all, even if current")
    top_sync_parser.add_argument(
        "--scope",
        choices=["project", "global", "both"],
        default=DEFAULT_LIFECYCLE_SCOPE,
        help=f"Scope to sync (default: {DEFAULT_LIFECYCLE_SCOPE})",
    )
    top_sync_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Explicit project root for project-scope reads and writes",
    )
    top_sync_parser.add_argument(
        "--harness",
        choices=["claude_code", "codex", "opencode", "all"],
        default="all",
    )

    # Top-level catalog source commands
    catalog_parser = subparsers.add_parser(
        "catalog",
        help="Query and refresh source catalog metadata",
    )
    catalog_verb_sub = catalog_parser.add_subparsers(
        dest="verb",
        metavar="verb",
        help="Catalog source action",
    )

    catalog_match_parser = catalog_verb_sub.add_parser(
        "match",
        help="Rank source catalogs for promotion routing",
    )
    catalog_match_parser.add_argument(
        "--primitive-type",
        required=True,
        choices=VALID_PRIMITIVES,
        help="Primitive type to route, e.g. standard or skill",
    )
    catalog_match_parser.add_argument(
        "--topics",
        default="",
        help="Comma-separated topic tags to match against source scope",
    )
    catalog_match_parser.add_argument(
        "--writable-only",
        action="store_true",
        help="Only consider writable source catalogs",
    )
    catalog_match_parser.add_argument("--json", action="store_true", help="Output JSON")

    catalog_sync_parser = catalog_verb_sub.add_parser(
        "sync",
        help="Convention-scan local source checkouts and refresh catalog entries",
    )
    catalog_sync_parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        default=None,
        help="Source catalog name to scan; may be repeated",
    )
    catalog_sync_parser.add_argument(
        "--primitive-type",
        choices=VALID_PRIMITIVES,
        default=None,
        help="Limit refresh to one primitive type",
    )
    catalog_sync_parser.add_argument(
        "--write",
        action="store_true",
        help="Write refreshed entries to library.yaml; default is dry-run",
    )
    catalog_sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview generated entries without mutating library.yaml",
    )
    catalog_sync_parser.add_argument("--json", action="store_true", help="Output JSON")

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> list [--json]"""
    entries = get_entries(catalog, args.primitive)
    use_json = getattr(args, "json", False)
    format_list_output(args.primitive, entries, json_mode=use_json)
    return 0


def _resolve_default_scope(catalog: dict, primitive: str, name: str) -> str:
    """Return scope from catalog entry's default_scope field, falling back to 'project'.

    Uses the same lookup semantics (fuzzy=True) as the installer so that keyword
    queries and exact names both resolve to the same entry and scope.
    """
    from lib.catalog import lookup_entry
    try:
        entry = lookup_entry(catalog, primitive, name, fuzzy=True)
        default_scope = entry.get("default_scope", "project")
        if default_scope == "global":
            return "global"
        # 'ask' and 'project' both fall back to project for CLI invocations
        return "project"
    except Exception:
        return "project"


def cmd_use(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> use [name] [--dry-run] [--json]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    name = getattr(args, "name", None)
    explicit_scope = args.scope  # None if --scope not passed (default=None now)
    harness = getattr(args, "harness", "all")
    install_mode = "symlink" if getattr(args, "symlink", False) else "vendor"
    primitive = args.primitive

    if name is None:
        msg = f"usage: library.py {primitive} use <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    # Resolve scope: explicit --scope takes priority; otherwise use catalog entry's default_scope
    if explicit_scope is not None:
        scope = explicit_scope
    else:
        scope = _resolve_default_scope(catalog, primitive, name)

    # Resolve transitive dependencies before installing
    if not dry_run:
        exit_code = _install_with_deps(
            args, repo_root, catalog, primitive, name, scope, harness, use_json
        )
        return exit_code

    # Dry-run: just show the target entry's planned ops (no dep resolution for dry-run)
    return _dispatch_use(args, repo_root, catalog, primitive, name, scope, harness, dry_run, use_json, install_mode)


def _install_with_deps(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    primitive: str,
    name: str,
    scope: str,
    harness: str,
    use_json: bool,
) -> int:
    """Resolve requires: and install all deps before the main entry."""
    from lib.resolver import resolve_requires, is_already_installed, CycleError
    from lib.errors import DependencyMissingError

    try:
        install_order = resolve_requires(catalog, primitive, name, repo_root, scope)
    except CycleError as exc:
        result = error_result(str(exc), exc.exit_code)
        if use_json:
            print_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except DependencyMissingError as exc:
        result = error_result(str(exc), exc.exit_code)
        if use_json:
            print_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except LibraryError as exc:
        result = error_result(str(exc), exc.exit_code)
        if use_json:
            print_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    # Install each entry in dependency order (deps first, main last)
    for dep_prim, dep_name in install_order:
        # Already-installed handling. is_already_installed() only checks
        # (lockfile_has_entry AND install_target_exists) — it does NOT detect:
        #   (a) catalog HEAD has moved beyond the lockfile's pinned source_commit
        #       ("upstream drift"), or
        #   (b) the deployed dir content no longer matches the lockfile's
        #       content_sha256 ("local tamper" — e.g. someone ran a manual cp,
        #       a partial-write left bad files, or another tool overwrote it).
        # Without these checks `use` silently no-ops in both cases, leaving
        # deployed files stale or broken.
        if is_already_installed(dep_name, repo_root, scope, dep_prim):
            upstream_status = _check_upstream_status_for_entry(
                catalog, repo_root, scope, dep_prim, dep_name
            )
            local_drift = _has_local_tamper(repo_root, scope, dep_prim, dep_name)
            if upstream_status == "behind":
                if not use_json:
                    print(
                        f"[refresh] {dep_prim}:{dep_name} is behind upstream — reinstalling",
                        file=sys.stderr,
                    )
                # Fall through to reinstall
            elif local_drift:
                if not use_json:
                    print(
                        f"[refresh] {dep_prim}:{dep_name} deployed files diverge from lockfile (local tamper) — reinstalling",
                        file=sys.stderr,
                    )
                # Fall through to reinstall
            else:
                if not use_json:
                    print(
                        f"[skip] {dep_prim}:{dep_name} already installed (upstream: {upstream_status})",
                        file=sys.stderr,
                    )
                continue
        install_mode = "symlink" if getattr(args, "symlink", False) else "vendor"
        rc = _dispatch_use(
            args, repo_root, catalog, dep_prim, dep_name, scope, harness, False, use_json, install_mode
        )
        if rc != 0:
            return rc

    return 0


def _check_upstream_status_for_entry(
    catalog: dict,
    repo_root: Path,
    scope: str,
    primitive: str,
    name: str,
) -> str:
    """Return upstream_status for a single (primitive, name) entry.

    Returns one of 'current', 'behind', 'unknown'. Wraps cmd_status_impl with
    network/IO failure tolerance so a `library use` call never hard-fails on
    a transient git ls-remote error.
    """
    try:
        from lib.status import cmd_status_impl

        result = cmd_status_impl(
            catalog=catalog,
            primitive=primitive,
            repo_root=repo_root,
            scope=scope,
            offline=False,
        )
        for entry in result.get("entries", []):
            if entry.get("name") == name and entry.get("primitive") == primitive:
                return entry.get("upstream_status", "unknown")
    except Exception:
        # Best-effort: a status probe failure must not block `use`. Treat as
        # unknown so the short-circuit path (skip with explicit message) wins
        # rather than silently no-opping.
        pass
    return "unknown"


def _has_local_tamper(
    repo_root: Path,
    scope: str,
    primitive: str,
    name: str,
) -> bool:
    """Return True iff the installed dir/file no longer matches lockfile checksum.

    Catches the case where someone manually edited / `cp`'d / partially wrote
    the deployed files, leaving them out of sync with the lockfile. `use` then
    auto-refreshes from cache. Mirrors the local-tamper logic in
    cmd_audit_impl but for a single entry, with failure tolerance.
    """
    try:
        from lib.lockfile import (
            compute_checksum,
            compute_directory_hash,
            find_lockfile,
            get_entry,
            load_lockfile,
        )

        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        if not lockfile_path.exists():
            return False
        lock_data = load_lockfile(lockfile_path)
        entry = get_entry(lock_data, name, primitive)
        if entry is None:
            return False

        expected_sha = entry.get("content_sha256") or entry.get("checksum_sha256", "")
        checksum_type = entry.get("checksum_type")
        install_target_str = entry.get("install_target", "")
        if not (expected_sha and checksum_type and install_target_str):
            return False

        target = Path(install_target_str.rstrip("/"))
        if target.is_symlink():
            target = target.resolve()
        if not target.exists():
            return False

        if checksum_type == "directory" and target.is_dir():
            actual = compute_directory_hash(target)
        elif checksum_type == "file" and target.is_file():
            actual = compute_checksum(target)
        else:
            return False

        return actual != expected_sha
    except Exception:
        # Best-effort: any failure means we don't know — be conservative and
        # don't trigger a refresh just because the check itself broke.
        return False


def _dispatch_use(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    primitive: str,
    name: str,
    scope: str,
    harness: str,
    dry_run: bool,
    use_json: bool,
    install_mode: str = "vendor",
) -> int:
    """Dispatch to the correct primitive installer."""
    if primitive == "skill":
        return _use_skill(args, repo_root, catalog, name, scope, dry_run, use_json, install_mode)
    elif primitive == "standard":
        return _use_standard(args, repo_root, catalog, name, scope, dry_run, use_json, install_mode)
    elif primitive == "agent":
        return _use_agent(args, repo_root, catalog, name, scope, dry_run, use_json, harness)
    elif primitive == "prompt":
        return _use_simple_file(args, repo_root, catalog, "prompt", name, scope, dry_run, use_json, harness, install_mode)
    elif primitive == "script":
        return _use_simple_file(args, repo_root, catalog, "script", name, scope, dry_run, use_json, harness, install_mode)
    elif primitive == "model-standard":
        return _use_simple_file(args, repo_root, catalog, "model-standard", name, scope, dry_run, use_json, harness, install_mode)
    elif primitive == "agent-base":
        return _use_simple_file(args, repo_root, catalog, "agent-base", name, scope, dry_run, use_json, harness, install_mode)
    elif primitive == "mcp":
        return _use_mcp(args, repo_root, catalog, name, scope, dry_run, use_json, harness)
    elif primitive == "guardrail":
        return _use_guardrail(args, repo_root, catalog, name, scope, dry_run, use_json, harness)
    else:
        msg = f"'{primitive} use' is not supported."
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE


def _use_skill(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    install_mode: str,
) -> int:
    """Install a skill (three-layer cache + vendored copy + bridge + lockfile)."""
    from lib.installers.skill import install_skill

    try:
        result = install_skill(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            install_mode=install_mode,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _use_standard(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    install_mode: str,
) -> int:
    """Install a standard (vendored copy + lockfile)."""
    from lib.installers.standard import install_standard

    try:
        result = install_standard(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            tool_root=TOOL_ROOT,
            install_mode=install_mode,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run", "blocked") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _use_agent(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
) -> int:
    """Install an agent."""
    from lib.installers.agent import install_agent

    try:
        result = install_agent(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
            if result.get("harness_missing"):
                print(f"Warning: harness source missing for: {', '.join(result['harness_missing'])}")
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _use_simple_file(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    primitive: str,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
    install_mode: str,
) -> int:
    """Install a prompt, model-standard, or agent-base."""
    from lib.installers.simple_file import install_simple_file

    try:
        result = install_simple_file(
            catalog=catalog,
            primitive_name=primitive,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
            install_mode=install_mode,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _use_mcp(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
) -> int:
    """Install an MCP server."""
    from lib.installers.mcp_installer import install_mcp

    # Pass any env overrides from the environment (for testing)
    import os
    env_overrides: dict = {}
    for key in ["CLAUDE_SETTINGS_FILE", "CODEX_CONFIG_FILE", "OPENCODE_CONFIG_FILE"]:
        if key in os.environ:
            env_overrides[key] = os.environ[key]

    try:
        result = install_mcp(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
            env_overrides=env_overrides if env_overrides else None,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _use_guardrail(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
) -> int:
    """Install a guardrail."""
    from lib.installers.guardrail_installer import install_guardrail

    try:
        result = install_guardrail(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _print_human_result(result: dict) -> None:
    """Print a human-readable summary of an operation result."""
    status = result.get("status", "unknown")
    if status == "ok":
        msg = result.get("message", "Done.")
        print(f"OK: {msg}")
    elif status == "dry-run":
        ops = result.get("operations", [])
        summary = result.get("summary", "")
        if summary:
            print(f"Dry-run: {summary}")
        for op in ops:
            print(f"  [{op.get('operation', '?')}] {op.get('details', op.get('path', ''))}")
    elif status == "blocked":
        print(f"Blocked: {result.get('reason', '')}")
        if result.get("suggestion"):
            print(f"  Suggestion: {result['suggestion']}")
    elif status == "error":
        print(f"Error: {result.get('message', 'unknown error')}", file=sys.stderr)
    else:
        print(f"Result: {result}")


def cmd_remove(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> remove [name] [--dry-run]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    name = getattr(args, "name", None)
    scope = getattr(args, "scope", "project")
    primitive = args.primitive

    if name is None:
        msg = f"usage: library.py {primitive} remove <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        result = _dispatch_remove(primitive, catalog, name, repo_root, scope, dry_run)
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _dispatch_remove(
    primitive: str,
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str,
    dry_run: bool,
) -> dict:
    """Dispatch remove to the correct primitive handler."""
    if primitive == "skill":
        from lib.installers.remove import remove_skill
        return remove_skill(catalog=catalog, name=name, repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "standard":
        from lib.installers.remove import remove_standard
        return remove_standard(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            tool_root=TOOL_ROOT,
        )
    elif primitive == "agent":
        from lib.installers.agent import remove_agent
        return remove_agent(catalog=catalog, name=name, repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "prompt":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="prompt", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "script":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="script", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "model-standard":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="model-standard", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "agent-base":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="agent-base", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "mcp":
        from lib.installers.mcp_installer import remove_mcp
        import os
        env_overrides: dict = {}
        for key in ["CLAUDE_SETTINGS_FILE", "CODEX_CONFIG_FILE", "OPENCODE_CONFIG_FILE"]:
            if key in os.environ:
                env_overrides[key] = os.environ[key]
        return remove_mcp(catalog=catalog, name=name, repo_root=repo_root, scope=scope,
                          dry_run=dry_run, env_overrides=env_overrides if env_overrides else None)
    elif primitive == "guardrail":
        from lib.installers.guardrail_installer import remove_guardrail
        return remove_guardrail(catalog=catalog, name=name, repo_root=repo_root, scope=scope, dry_run=dry_run)
    else:
        from lib.errors import EXIT_FAILURE
        from lib.output import error_result as _err
        return _err(f"'{primitive} remove' is not supported.", EXIT_FAILURE)


def cmd_search(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: [<primitive>] search [query] [--json]

    When called as a top-level 'search' command, searches all primitives.
    When called as '<primitive> search', filters to that primitive.
    """
    use_json = getattr(args, "json", False)
    query = getattr(args, "query", None)

    if query is None:
        msg = "usage: library.py search <keyword>  or  library.py <primitive> search <keyword>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    results = search_all(catalog, query)

    # If we're in primitive-specific search mode, filter
    if hasattr(args, "primitive") and args.primitive not in (None, "search"):
        results = [r for r in results if r.get("primitive") == args.primitive]

    format_search_output(results, query, json_mode=use_json)
    return 0


def cmd_sync(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> sync [name] [--dry-run]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    name = getattr(args, "name", None)
    scope = getattr(args, "scope", "project")
    harness = getattr(args, "harness", "all")
    primitive = args.primitive

    try:
        result = cmd_sync_impl(
            catalog=catalog,
            primitive=primitive,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
            target_name=name,
        )
        if use_json:
            print_json(result)
        else:
            _print_human_result(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def cmd_audit(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> audit [--drift-only] [--no-upstream]"""
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")
    drift_only = getattr(args, "drift_only", False)
    skip_upstream = getattr(args, "no_upstream", False)
    primitive = args.primitive

    try:
        result = cmd_audit_impl(
            catalog=catalog,
            primitive=primitive,
            repo_root=repo_root,
            scope=scope,
            drift_only=drift_only,
            skip_upstream=skip_upstream,
        )
        if use_json:
            print_json(result)
        else:
            status = result.get("status", "?")
            entries = result.get("entries", [])
            drift_entries = [e for e in entries if e.get("drift")]
            if status == "clean":
                print(f"Audit: CLEAN ({len(entries)} entries checked)")
            elif status == "drift":
                print(f"Audit: DRIFT detected in {len(drift_entries)}/{len(entries)} entries")
                for e in drift_entries:
                    kind = e.get("drift_kind", "?")
                    print(f"  DRIFT [{kind}]: {e['primitive']}:{e['name']}")
                    _print_agent_frontmatter_issue(e)
            else:
                print(f"Audit: {status}")
        # Exit 2 if drift detected, 0 if clean
        return EXIT_DRIFT if result.get("status") == "drift" else 0
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def cmd_audit_all(args: argparse.Namespace, repo_root: Path | None, catalog: dict) -> int:
    """Handle: audit [--scope=...] [--drift-only] [--json]

    Top-level audit command that checks all primitives across the given scope(s).
    """
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")
    drift_only = getattr(args, "drift_only", False)
    skip_upstream = getattr(args, "no_upstream", False)

    scopes_to_check = _scopes_to_check(scope)

    all_entries = []
    any_drift = False
    warnings: list[str] = []

    for s in scopes_to_check:
        if s == "project" and repo_root is None:
            if scope == "project":
                warnings.append(_missing_project_warning())
            continue
        try:
            result = cmd_audit_impl(
                catalog=catalog,
                primitive="all",
                repo_root=repo_root or Path.cwd(),
                scope=s,
                drift_only=drift_only,
                skip_upstream=skip_upstream,
            )
            all_entries.extend(result.get("entries", []))
            if result.get("status") == "drift":
                any_drift = True
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code

    overall_status = "drift" if any_drift else "clean"
    combined_result = {
        "status": overall_status,
        "entries": all_entries,
    }
    if warnings:
        combined_result["warnings"] = warnings

    if use_json:
        print_json(combined_result)
    else:
        drift_entries = [e for e in all_entries if e.get("drift")]
        if overall_status == "clean":
            print(f"Audit: CLEAN ({len(all_entries)} entries checked)")
        else:
            print(f"Audit: DRIFT detected in {len(drift_entries)}/{len(all_entries)} entries")
            for e in drift_entries:
                print(f"  DRIFT: {e['primitive']}:{e['name']}")
                _print_agent_frontmatter_issue(e)
        for warning in warnings:
            print(f"Warning: {warning}")

    return EXIT_DRIFT if any_drift else 0


def _print_agent_frontmatter_issue(entry: dict) -> None:
    """Print extra context for Claude agent frontmatter audit failures."""
    issue = entry.get("agent_frontmatter_issue")
    if not issue:
        return
    print(f"    {issue.get('code', 'frontmatter')}: {issue.get('path', '')}")
    print(f"    repair: {issue.get('repair_hint', '')}")


def cmd_status(args: argparse.Namespace, repo_root: Path | None, catalog: dict) -> int:
    """Handle: status [--scope=...] [--json]

    Top-level status command that checks upstream SHAs for all installed entries
    without cloning.
    """
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")
    offline = getattr(args, "offline", False)

    scopes_to_check = _scopes_to_check(scope)

    all_entries = []
    any_behind = False
    warnings: list[str] = []
    remote_cache: dict[tuple[str, str], str | None] = {}

    for s in scopes_to_check:
        if s == "project" and repo_root is None:
            if scope == "project":
                warnings.append(_missing_project_warning())
            continue
        try:
            result = cmd_status_impl(
                catalog=catalog,
                primitive="all",
                repo_root=repo_root or Path.cwd(),
                scope=s,
                offline=offline,
                remote_cache=remote_cache,
            )
            all_entries.extend(result.get("entries", []))
            if result.get("overall") == "behind":
                any_behind = True
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code

    # Compute combined overall
    if any_behind or any(e.get("behind") for e in all_entries):
        overall = "behind"
    elif all(e.get("upstream_status") == "current" for e in all_entries) and all_entries:
        overall = "current"
    elif not all_entries:
        overall = "current"
    else:
        overall = "unknown"

    combined_result = {
        "status": "ok",
        "entries": all_entries,
        "overall": overall,
    }
    if warnings:
        combined_result["warnings"] = warnings

    if use_json:
        print_json(combined_result)
    else:
        if overall == "current":
            print(f"Status: ALL CURRENT ({len(all_entries)} entries)")
        elif overall == "behind":
            behind_count = sum(1 for e in all_entries if e.get("behind"))
            print(f"Status: BEHIND ({behind_count}/{len(all_entries)} entries need update)")
            for e in all_entries:
                if e.get("behind"):
                    installed = e.get("installed_sha", "?")[:8]
                    remote = str(e.get("remote_sha", "?"))[:8]
                    print(f"  BEHIND: {e['primitive']}:{e['name']} ({installed} -> {remote})")
        else:
            print(f"Status: UNKNOWN ({len(all_entries)} entries checked)")
        for warning in warnings:
            print(f"Warning: {warning}")

    return EXIT_DRIFT if overall == "behind" else 0


def cmd_installed(args: argparse.Namespace) -> int:
    """Handle: installed [--scope=...] [--primitive=...] [--diff-catalog] [--json]."""
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "both")
    primitive_filter = getattr(args, "primitive_filter", None)
    include_catalog_diff = getattr(args, "diff_catalog", False)
    offline = getattr(args, "offline", False)
    repo_root = _resolve_lifecycle_project_root(args)

    catalog: dict | None = None
    warnings: list[str] = []
    catalog_root: Path | None = None
    if scope == "project" and repo_root is None:
        warnings.append(_missing_project_warning())
    if include_catalog_diff:
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
        except LibraryError:
            warnings.append(
                "catalog not found at current parents or "
                f"{TOOL_ROOT / 'library.yaml'}; catalog diff omitted"
            )

    try:
        result = cmd_installed_impl(
            repo_root=repo_root,
            scope=scope,
            primitive_filter=primitive_filter,
            catalog=catalog,
            include_catalog_diff=include_catalog_diff,
            offline=offline,
        )
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    if warnings:
        result["warnings"] = warnings
    if include_catalog_diff and catalog_root is not None:
        result["catalog_source"] = str(catalog_root / "library.yaml")

    if use_json:
        print_json(result)
    else:
        print(format_installed_output(result))
    return 0


def cmd_catalog_match(args: argparse.Namespace, catalog: dict) -> int:
    """Handle: catalog match --primitive-type=... --topics=..."""
    from lib.catalog_inventory import match_catalogs

    use_json = getattr(args, "json", False)
    try:
        result = match_catalogs(
            catalog,
            getattr(args, "primitive_type"),
            getattr(args, "topics", ""),
            writable_only=getattr(args, "writable_only", False),
        )
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    if use_json:
        print_json(result)
        return 0

    matches = result.get("matches", [])
    if not matches:
        print("No catalog matches.")
        return 0

    rows = [
        {
            "Name": match.get("name", ""),
            "Registry": match.get("registry", ""),
            "Writable": "yes" if match.get("writable") else "no",
            "Score": str(match.get("score", 0)),
            "Confidence": str(match.get("confidence", 0)),
            "Selection": match.get("selection", ""),
            "Topics": ",".join(match.get("matched_topics", [])),
        }
        for match in matches
    ]
    print(format_table(rows, ["Name", "Registry", "Writable", "Score", "Confidence", "Selection", "Topics"]))
    return 0


def cmd_catalog_sync(args: argparse.Namespace, catalog_root: Path, catalog: dict) -> int:
    """Handle: catalog sync [--source=...] [--write] [--json]."""
    from lib.catalog_inventory import sync_catalog_inventory

    use_json = getattr(args, "json", False)
    write = getattr(args, "write", False)
    dry_run = getattr(args, "dry_run", False)
    if write and dry_run:
        msg = "catalog sync accepts either --write or --dry-run, not both"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        result = sync_catalog_inventory(
            catalog,
            catalog_root,
            source_names=getattr(args, "sources", None),
            primitive_type=getattr(args, "primitive_type", None),
            write=write,
        )
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    if use_json:
        print_json(result)
        return 0

    status = result.get("status", "dry-run")
    generated = result.get("generated", {})
    total = result.get("total_generated", 0)
    if status == "ok":
        print(f"Catalog sync: wrote {total} generated entries to {result.get('written')}")
    else:
        print(f"Catalog sync dry-run: generated {total} entries")
    for primitive_name, count in generated.items():
        print(f"  {primitive_name}: {count}")
    for source in result.get("sources", []):
        if source.get("status") != "scanned":
            print(f"  skipped {source.get('name')}: {source.get('reason', source.get('status'))}")
    return 0


def cmd_sync_all(args: argparse.Namespace, repo_root: Path | None, catalog: dict) -> int:
    """Handle: sync [--force] [--dry-run] [--scope=...] [--json]

    Top-level sync that iterates ALL primitives across all scopes.
    By default refreshes only entries where upstream_status == 'behind'.
    With --force, re-installs all entries regardless.
    """
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    scope = getattr(args, "scope", "both")
    harness = getattr(args, "harness", "all")

    scopes_to_check = _scopes_to_check(scope)

    all_refreshed = []
    all_skipped = []
    all_failed = []
    skipped_by_status: dict[str, list[str]] = {
        "current": [],
        "unknown": [],
        "other": [],
    }
    warnings: list[str] = []
    remote_cache: dict[tuple[str, str], str | None] = {}

    for s in scopes_to_check:
        if s == "project" and repo_root is None:
            if scope == "project":
                warnings.append(_missing_project_warning())
            continue
        # Get upstream status to determine what needs syncing
        if not force:
            try:
                status_result = cmd_status_impl(
                    catalog=catalog,
                    primitive="all",
                    repo_root=repo_root or Path.cwd(),
                    scope=s,
                    remote_cache=remote_cache,
                )
                status_by_key = {
                    (e["name"], e.get("primitive", e.get("type", "")))
                    : e.get("upstream_status", "unknown")
                    for e in status_result.get("entries", [])
                }
            except LibraryError as exc:
                warnings.append(f"status check failed for {s} scope: {exc}")
                status_by_key = {}
        else:
            status_by_key = {}

        lockfile_path = find_lockfile(repo_root, global_scope=(s == "global"))
        lock_data = load_lockfile(lockfile_path)
        installed = lock_data.get("installed", [])

        for entry in installed:
            entry_name = entry.get("name", "")
            entry_type = entry.get("type", "")
            entry_label = f"{entry_type}:{entry_name}"
            key = (entry_name, entry_type)

            upstream_status = status_by_key.get(key, "unknown")
            should_refresh = force or upstream_status == "behind"
            should_skip = not should_refresh

            if dry_run:
                if should_skip:
                    all_skipped.append(entry_label)
                    skipped_by_status[
                        upstream_status if upstream_status in skipped_by_status else "other"
                    ].append(entry_label)
                else:
                    all_refreshed.append(entry_label)
                continue

            if should_skip:
                all_skipped.append(entry_label)
                skipped_by_status[
                    upstream_status if upstream_status in skipped_by_status else "other"
                ].append(entry_label)
                continue

            # Re-install this entry
            try:
                reinstall_entry(catalog, entry, repo_root, s, harness)
                all_refreshed.append(entry_label)
            except (LibraryError, Exception) as exc:
                all_failed.append({
                    "name": entry.get("name", ""),
                    "type": entry.get("type", ""),
                    "error": str(exc),
                })
                if not use_json:
                    print(f"  ERROR: {entry.get('name')}: {exc}", file=sys.stderr)

    unknown_skipped = len(skipped_by_status["unknown"])
    if unknown_skipped:
        warnings.append(
            f"skipped {unknown_skipped} entries with unknown upstream status; "
            "use --force to refresh them"
        )

    result = {
        "status": "dry-run" if dry_run else "ok",
        "refreshed": all_refreshed,
        "skipped": all_skipped,
        "skipped_by_status": skipped_by_status,
        "unknown_skipped": unknown_skipped,
        "failed": all_failed,
        "total_refreshed": len(all_refreshed),
        "total_skipped": len(all_skipped),
    }
    if warnings:
        result["warnings"] = warnings

    if dry_run:
        result["summary"] = (
            f"Would refresh {len(all_refreshed)} entries, "
            f"skip {len(all_skipped)} entries not reported behind"
        )

    if use_json:
        print_json(result)
    else:
        if dry_run:
            print(f"Dry-run: {result['summary']}")
            for label in all_refreshed:
                print(f"  [would-refresh] {label}")
            for status_name, labels in skipped_by_status.items():
                for label in labels:
                    print(f"  [skip-{status_name}] {label}")
        else:
            print(f"Synced: {len(all_refreshed)} refreshed, {len(all_skipped)} skipped (not behind)")
        for warning in warnings:
            print(f"Warning: {warning}")

    if all_failed:
        return EXIT_FAILURE
    return 0


VERB_HANDLERS = {
    "list": cmd_list,
    "use": cmd_use,
    "remove": cmd_remove,
    "search": cmd_search,
    "sync": cmd_sync,
    "audit": cmd_audit,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point for the library CLI.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # No subcommand given
    if not args.primitive:
        parser.print_help()
        return EXIT_FAILURE

    # Top-level search
    if args.primitive == "search":
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
        except LibraryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        return cmd_search(args, catalog_root, catalog)

    # Top-level audit (cross-primitive)
    if args.primitive == "audit":
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        repo_root = _resolve_lifecycle_project_root(args)
        return cmd_audit_all(args, repo_root, catalog)

    # Top-level status (cross-primitive, no clone)
    if args.primitive == "status":
        repo_root = _resolve_lifecycle_project_root(args)
        return cmd_status(args, repo_root, {})

    # Top-level installed (cross-primitive, no catalog required unless diffing)
    if args.primitive == "installed":
        return cmd_installed(args)

    # Top-level sync (cross-primitive)
    if args.primitive == "sync":
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        repo_root = _resolve_lifecycle_project_root(args)
        return cmd_sync_all(args, repo_root, catalog)

    # Top-level catalog source commands
    if args.primitive == "catalog":
        verb = getattr(args, "verb", None)
        if not verb:
            parser.parse_args(["catalog", "--help"])
            return EXIT_FAILURE
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code

        if verb == "match":
            return cmd_catalog_match(args, catalog)
        if verb == "sync":
            return cmd_catalog_sync(args, catalog_root, catalog)

        print("Error: Unknown catalog verb.", file=sys.stderr)
        return EXIT_FAILURE

    # Validate primitive
    prim_info = get_primitive(args.primitive)
    if prim_info is None:
        print(
            f"Error: Unknown primitive '{args.primitive}'. "
            f"Valid: {', '.join(VALID_PRIMITIVES)}",
            file=sys.stderr,
        )
        return EXIT_FAILURE

    # Check verb
    verb = getattr(args, "verb", None)
    if not verb:
        # Print help for this primitive's subparser
        parser.parse_args([args.primitive, "--help"])
        return EXIT_FAILURE

    # Load catalog
    try:
        catalog_root = _resolve_catalog_root()
        repo_root = _resolve_target_root(args, catalog_root)
        catalog = load_catalog(catalog_root)
    except LibraryError as exc:
        use_json = getattr(args, "json", False)
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    # Dispatch
    handler = VERB_HANDLERS.get(verb)
    if handler is None:
        print(f"Error: Unknown verb '{verb}'. Valid verbs: {', '.join(VALID_VERBS)}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        return handler(args, repo_root, catalog)
    except LibraryError as exc:
        use_json = getattr(args, "json", False)
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


def _resolve_catalog_root() -> Path:
    """Return the root containing the library catalog used for lookup."""
    try:
        return find_repo_root()
    except LibraryError:
        return find_repo_root(TOOL_ROOT)


def _scopes_to_check(scope: str) -> list[str]:
    """Return concrete scopes for a lifecycle command."""
    return ["project", "global"] if scope == "both" else [scope]


def _resolve_lifecycle_project_root(args: argparse.Namespace) -> Path | None:
    """Return a trusted project root for read-only lifecycle commands.

    Project-scope lockfiles are only considered when the user is inside a git
    worktree or explicitly passes --project. This avoids treating stray
    .library.lock files in arbitrary directories as project state.
    """
    explicit_project = getattr(args, "project", None)
    if explicit_project is not None:
        return explicit_project.expanduser().resolve()
    return _find_git_root(Path.cwd())


def _missing_project_warning() -> str:
    return (
        "project scope skipped because the current directory is not inside a "
        "git worktree; pass --project <path> to inspect a project lockfile"
    )


def _resolve_target_root(args: argparse.Namespace, catalog_root: Path) -> Path:
    """Return the project root used for project-scoped writes."""
    scope = getattr(args, "scope", "project")
    if scope == "global":
        return catalog_root

    explicit_target = getattr(args, "target_project", None)
    if explicit_target is not None:
        return explicit_target.expanduser().resolve()

    return _find_git_root(Path.cwd()) or Path.cwd().resolve()


def _find_git_root(start: Path) -> Path | None:
    """Return the git worktree root containing start, if any."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=str(start),
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


if __name__ == "__main__":
    sys.exit(main())
