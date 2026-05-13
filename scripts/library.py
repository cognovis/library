#!/usr/bin/env python3
"""
library.py — Deterministic library engine CLI.

Canonical command grammar:
  python3 scripts/library.py <primitive> <verb> [name-or-query] [options]

Supported primitives: skill, agent, prompt, standard, guardrail, mcp,
                      model-standard, golden-prompt

Supported verbs: list, use, remove, sync, search, audit

Options:
  --json        Machine-readable JSON output
  --dry-run     Show planned operations without mutating files
  --scope       project (default) or global
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
  python3 scripts/library.py search firecrawl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `lib` importable when running as a script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

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
from lib.output import (
    format_list_output,
    format_search_output,
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
            help=prim.description if prim else f"{prim_name} primitives",
        )

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
            "--scope",
            choices=["project", "global"],
            default="project",
            help="Scope (default: project)",
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

        # search
        search_p = verb_sub.add_parser("search", help="Search within this primitive")
        search_p.add_argument("query", nargs="?", default=None, help="Search keyword")
        search_p.add_argument("--json", action="store_true", help="Output JSON")

        # sync
        sync_p = verb_sub.add_parser("sync", help="Re-pull all installed entries from lockfile")
        sync_p.add_argument("--json", action="store_true", help="Output JSON")
        sync_p.add_argument("--dry-run", action="store_true", help="Show planned syncs")
        sync_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
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
        default="project",
        help="Scope to audit (default: project)",
    )
    top_audit_parser.add_argument(
        "--drift-only",
        action="store_true",
        help="Only show drifted entries; exit 2 if any drift, 0 if clean",
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
        default="project",
        help="Scope to check (default: project)",
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
        default="both",
        help="Scope to sync (default: both)",
    )
    top_sync_parser.add_argument(
        "--harness",
        choices=["claude_code", "codex", "opencode", "all"],
        default="all",
    )

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


def cmd_use(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> use [name] [--dry-run] [--json]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    name = getattr(args, "name", None)
    scope = getattr(args, "scope", "project")
    harness = getattr(args, "harness", "all")
    primitive = args.primitive

    if name is None:
        msg = f"usage: library.py {primitive} use <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    # Resolve transitive dependencies before installing
    if not dry_run:
        exit_code = _install_with_deps(
            args, repo_root, catalog, primitive, name, scope, harness, use_json
        )
        return exit_code

    # Dry-run: just show the target entry's planned ops (no dep resolution for dry-run)
    return _dispatch_use(args, repo_root, catalog, primitive, name, scope, harness, dry_run, use_json)


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
        # Skip if already installed (lockfile-aware)
        if is_already_installed(dep_name, repo_root, scope):
            continue
        rc = _dispatch_use(args, repo_root, catalog, dep_prim, dep_name, scope, harness, False, use_json)
        if rc != 0:
            return rc

    return 0


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
) -> int:
    """Dispatch to the correct primitive installer."""
    if primitive == "skill":
        return _use_skill(args, repo_root, catalog, name, scope, dry_run, use_json)
    elif primitive == "standard":
        return _use_standard(args, repo_root, catalog, name, scope, dry_run, use_json)
    elif primitive == "agent":
        return _use_agent(args, repo_root, catalog, name, scope, dry_run, use_json, harness)
    elif primitive == "prompt":
        return _use_simple_file(args, repo_root, catalog, "prompt", name, scope, dry_run, use_json, harness)
    elif primitive == "model-standard":
        return _use_simple_file(args, repo_root, catalog, "model-standard", name, scope, dry_run, use_json, harness)
    elif primitive == "golden-prompt":
        return _use_simple_file(args, repo_root, catalog, "golden-prompt", name, scope, dry_run, use_json, harness)
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
) -> int:
    """Install a skill (three-layer cache + symlink + bridge + lockfile)."""
    from lib.installers.skill import install_skill

    try:
        result = install_skill(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
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
) -> int:
    """Install a standard (AGENTS.md block + lockfile)."""
    from lib.installers.standard import install_standard

    try:
        result = install_standard(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
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
) -> int:
    """Install a prompt, model-standard, or golden-prompt."""
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
        return remove_standard(catalog=catalog, name=name, repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "agent":
        from lib.installers.agent import remove_agent
        return remove_agent(catalog=catalog, name=name, repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "prompt":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="prompt", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "model-standard":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="model-standard", name=name,
                                  repo_root=repo_root, scope=scope, dry_run=dry_run)
    elif primitive == "golden-prompt":
        from lib.installers.simple_file import remove_simple_file
        return remove_simple_file(catalog=catalog, primitive_name="golden-prompt", name=name,
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
    """Handle: <primitive> sync [--dry-run]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
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
    """Handle: <primitive> audit [--drift-only]"""
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")
    drift_only = getattr(args, "drift_only", False)
    primitive = args.primitive

    try:
        result = cmd_audit_impl(
            catalog=catalog,
            primitive=primitive,
            repo_root=repo_root,
            scope=scope,
            drift_only=drift_only,
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
                    print(f"  DRIFT: {e['primitive']}:{e['name']}")
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


def cmd_audit_all(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: audit [--scope=...] [--drift-only] [--json]

    Top-level audit command that checks all primitives across the given scope(s).
    """
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")
    drift_only = getattr(args, "drift_only", False)

    scopes_to_check = ["project", "global"] if scope == "both" else [scope]

    all_entries = []
    any_drift = False

    for s in scopes_to_check:
        try:
            result = cmd_audit_impl(
                catalog=catalog,
                primitive="all",
                repo_root=repo_root,
                scope=s,
                drift_only=drift_only,
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

    return EXIT_DRIFT if any_drift else 0


def cmd_status(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: status [--scope=...] [--json]

    Top-level status command that checks upstream SHAs for all installed entries
    without cloning.
    """
    use_json = getattr(args, "json", False)
    scope = getattr(args, "scope", "project")

    scopes_to_check = []
    if scope == "both":
        scopes_to_check = ["project", "global"]
    else:
        scopes_to_check = [scope]

    all_entries = []
    any_behind = False

    for s in scopes_to_check:
        try:
            result = cmd_status_impl(
                catalog=catalog,
                primitive="all",
                repo_root=repo_root,
                scope=s,
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

    return EXIT_DRIFT if overall == "behind" else 0


def cmd_sync_all(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: sync [--force] [--dry-run] [--scope=...] [--json]

    Top-level sync that iterates ALL primitives across all scopes.
    By default skips entries where upstream_status == 'current'.
    With --force, re-installs all entries regardless.
    """
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    scope = getattr(args, "scope", "both")
    harness = getattr(args, "harness", "all")

    scopes_to_check = ["project", "global"] if scope == "both" else [scope]

    all_refreshed = []
    all_skipped = []
    all_failed = []

    for s in scopes_to_check:
        # Get upstream status to determine what needs syncing
        if not force:
            try:
                status_result = cmd_status_impl(
                    catalog=catalog,
                    primitive="all",
                    repo_root=repo_root,
                    scope=s,
                )
                current_set = {
                    (e["name"], e.get("primitive", e.get("type", "")))
                    for e in status_result.get("entries", [])
                    if e.get("upstream_status") == "current"
                }
            except LibraryError:
                current_set = set()
        else:
            current_set = set()

        lockfile_path = find_lockfile(repo_root, global_scope=(s == "global"))
        lock_data = load_lockfile(lockfile_path)
        installed = lock_data.get("installed", [])

        for entry in installed:
            entry_name = entry.get("name", "")
            entry_type = entry.get("type", "")
            entry_label = f"{entry_type}:{entry_name}"
            key = (entry_name, entry_type)

            should_skip = (not force) and (key in current_set)

            if dry_run:
                if should_skip:
                    all_skipped.append(entry_label)
                else:
                    all_refreshed.append(entry_label)
                continue

            if should_skip:
                all_skipped.append(entry_label)
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

    result = {
        "status": "dry-run" if dry_run else "ok",
        "refreshed": all_refreshed,
        "skipped": all_skipped,
        "failed": all_failed,
        "total_refreshed": len(all_refreshed),
        "total_skipped": len(all_skipped),
    }

    if dry_run:
        result["summary"] = (
            f"Would refresh {len(all_refreshed)} entries, "
            f"skip {len(all_skipped)} already-current entries"
        )

    if use_json:
        print_json(result)
    else:
        if dry_run:
            print(f"Dry-run: {result['summary']}")
            for label in all_refreshed:
                print(f"  [would-refresh] {label}")
            for label in all_skipped:
                print(f"  [skip-current]  {label}")
        else:
            print(f"Synced: {len(all_refreshed)} refreshed, {len(all_skipped)} skipped (current)")

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
            repo_root = find_repo_root()
            catalog = load_catalog(repo_root)
        except LibraryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        return cmd_search(args, repo_root, catalog)

    # Top-level audit (cross-primitive)
    if args.primitive == "audit":
        try:
            repo_root = find_repo_root()
            catalog = load_catalog(repo_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        return cmd_audit_all(args, repo_root, catalog)

    # Top-level status (cross-primitive, no clone)
    if args.primitive == "status":
        try:
            repo_root = find_repo_root()
            catalog = load_catalog(repo_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        return cmd_status(args, repo_root, catalog)

    # Top-level sync (cross-primitive)
    if args.primitive == "sync":
        try:
            repo_root = find_repo_root()
            catalog = load_catalog(repo_root)
        except LibraryError as exc:
            use_json = getattr(args, "json", False)
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        return cmd_sync_all(args, repo_root, catalog)

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
        repo_root = find_repo_root()
        catalog = load_catalog(repo_root)
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


if __name__ == "__main__":
    sys.exit(main())
