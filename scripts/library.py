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
    EXIT_FAILURE,
    EXIT_NOT_FOUND,
    LibraryError,
)
from lib.output import (
    format_list_output,
    format_search_output,
    print_json,
    blocked_result,
    dry_run_result,
    success,
    error_result,
)
from lib.primitives import PRIMITIVES, all_primitive_names, get_primitive


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
        version="library.py 1.0.0 (CL-0bl)",
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

        # audit
        audit_p = verb_sub.add_parser("audit", help="Detect drift in installed entries")
        audit_p.add_argument("--json", action="store_true", help="Output JSON")
        audit_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
        )

    # Top-level search (cross-primitive)
    search_parser = subparsers.add_parser(
        "search",
        help="Search across all primitives",
    )
    search_parser.add_argument("query", nargs="?", default=None, help="Search keyword")
    search_parser.add_argument("--json", action="store_true", help="Output JSON")

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
    primitive = args.primitive

    if name is None:
        msg = f"usage: library.py {primitive} use <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    # Dispatch to primitive-specific installer
    if primitive == "skill":
        return _use_skill(args, repo_root, catalog, name, scope, dry_run, use_json)
    elif primitive == "standard":
        return _use_standard(args, repo_root, catalog, name, scope, dry_run, use_json)
    else:
        # Other primitives: emit "not yet implemented" result
        msg = (
            f"'{primitive} use' is not yet implemented in the Python CLI. "
            f"Use the /library skill wrapper or a dedicated installer script."
        )
        if primitive == "mcp":
            msg = (
                "MCP installs are handled by scripts/install-mcp.py. "
                "Run: python3 scripts/install-mcp.py <name>"
            )
        elif primitive == "guardrail":
            msg = (
                "Hook-manifest guardrails are handled by scripts/install-hook.py. "
                "Run: python3 scripts/install-hook.py <name>"
            )

        result = blocked_result(msg, suggestion=msg)
        if use_json:
            print_json(result)
        else:
            print(f"Blocked: {result['reason']}")
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
    name = getattr(args, "name", None)

    if name is None:
        msg = f"usage: library.py {args.primitive} remove <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    msg = f"'{args.primitive} remove' is not yet fully implemented. Use /library skill to remove."
    result = blocked_result(msg)
    if use_json:
        print_json(result)
    else:
        print(f"Blocked: {msg}")
    return EXIT_FAILURE


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
    msg = "'sync' reads .library.lock and re-installs. Not yet implemented in Python CLI."
    result = blocked_result(msg, suggestion="Use /library sync skill wrapper for now.")
    if use_json:
        print_json(result)
    else:
        print(f"Blocked: {msg}")
    return EXIT_FAILURE


def cmd_audit(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> audit"""
    use_json = getattr(args, "json", False)
    msg = "'audit' checksums installed items. Not yet implemented in Python CLI."
    result = blocked_result(msg)
    if use_json:
        print_json(result)
    else:
        print(f"Blocked: {msg}")
    return EXIT_FAILURE


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


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
