#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.0",
#     "mcp>=1.27.1,<2",
#     "pyyaml>=6.0",
#     "ruamel.yaml>=0.18",
#     "tomlkit>=0.13",
# ]
# ///
"""
library — Deterministic Library engine CLI.

Canonical command grammar:
  library <primitive> <verb> [name-or-query] [options]

Supported primitives: skill, agent, prompt, script, standard, guardrail, mcp,
                      model-standard, agent-base, workflow

Supported verbs: list, use, remove, sync, search, audit

Options:
  --json        Machine-readable JSON output
  --dry-run     Show planned operations without mutating files
  --scope       project (default) or global
  --target-project
                Project root for project-scoped writes
  --harness     claude_code, codex, cursor, opencode, antigravity, or all (where applicable)

Exit codes:
  0  success
  1  general failure / validation error
  2  not found
  3  ambiguous match (multiple results)
  4  dependency not installed
  5  (reserved for future use)

Usage examples:
  library skill list
  library skill list --json
  library standard use english-only --scope global
  library skill use dolt --dry-run --json
  library skill use dolt --symlink --json
  library search firecrawl
  library catalog match --primitive-type=standard --topics=python,uv --writable-only
  library installed --diff-catalog
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import NamedTuple

# Make `lib` importable when running as a script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TOOL_ROOT = SCRIPT_DIR.parent

from lib.catalog import (
    find_repo_root,
    get_catalog_identity,
    get_entries,
    load_catalog,
    lookup_entry,
    normalize_catalog_identity,
    search_all,
)
from lib.errors import (
    EXIT_AMBIGUOUS,
    EXIT_DEPENDENCY_MISSING,
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_NOT_FOUND,
    EXIT_SUCCESS,
    LibraryError,
)
from lib.lockfile import (
    find_lockfile,
    load_lockfile,
    resolve_lockfile_path,
    save_lockfile,
)
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
from lib.source import ParsedSource, parse_source
from lib.sync_audit import cmd_audit_impl, cmd_sync_impl, reinstall_entry


VALID_PRIMITIVES = all_primitive_names()
VALID_VERBS = ["list", "use", "remove", "sync", "search", "audit"]
DEFAULT_LIFECYCLE_SCOPE = "both"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the library CLI."""
    parser = argparse.ArgumentParser(
        prog="library",
        description=(
            "Deterministic library engine — manages skills, agents, standards, and more.\n\n"
            "Canonical grammar: library <primitive> <verb> [name] [options]\n\n"
            f"Supported primitives: {', '.join(VALID_PRIMITIVES)}\n"
            f"Supported verbs: {', '.join(VALID_VERBS)}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="library 2.0.0 (CL-8ph)",
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

        if prim_name == "workspace":
            _add_workspace_verbs(verb_sub)
            continue

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
        use_p.add_argument(
            "name", nargs="?", default=None, help="Entry name or keyword"
        )
        use_p.add_argument("--json", action="store_true", help="Output JSON")
        use_p.add_argument(
            "--dry-run", action="store_true", help="Show planned writes, no mutation"
        )
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
            choices=[
                "claude_code",
                "codex",
                "cursor",
                "opencode",
                "antigravity",
                "all",
            ],
            default="all",
            help="Target harness (default: all)",
        )
        use_p.add_argument(
            "--target",
            type=Path,
            default=None,
            help=(
                "Override the deploy target file (runtime-config only). "
                "Use to compose to a temp path instead of the live config."
            ),
        )

        # remove
        remove_p = verb_sub.add_parser("remove", help="Remove an installed entry")
        remove_p.add_argument("name", nargs="?", default=None, help="Entry name")
        remove_p.add_argument("--json", action="store_true", help="Output JSON")
        remove_p.add_argument(
            "--dry-run", action="store_true", help="Show planned removals"
        )
        remove_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default=None,
            help=(
                "Scope (MCP defaults to global; MCP project scope removes only a "
                "legacy lock record; other primitives default to project)"
            ),
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
        remove_p.add_argument(
            "--harness",
            choices=[
                "claude_code",
                "codex",
                "cursor",
                "opencode",
                "antigravity",
                "all",
            ],
            default="claude_code",
            help="Target harness for harness-specific removals (default: claude_code)",
        )

        # search
        search_p = verb_sub.add_parser("search", help="Search within this primitive")
        search_p.add_argument("query", nargs="?", default=None, help="Search keyword")
        search_p.add_argument("--json", action="store_true", help="Output JSON")

        # sync
        sync_p = verb_sub.add_parser(
            "sync", help="Re-pull installed entries from lockfile"
        )
        sync_p.add_argument(
            "name", nargs="?", default=None, help="Installed entry name"
        )
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
            choices=[
                "claude_code",
                "codex",
                "cursor",
                "opencode",
                "antigravity",
                "all",
            ],
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
    top_sync_parser.add_argument(
        "--dry-run", action="store_true", help="Show planned syncs"
    )
    top_sync_parser.add_argument(
        "--force", action="store_true", help="Re-install all, even if current"
    )
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
        choices=["claude_code", "codex", "cursor", "opencode", "antigravity", "all"],
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

    _add_marketplace_verbs(subparsers)

    return parser


def _add_marketplace_verbs(subparsers: argparse._SubParsersAction) -> None:
    """The ADR-0011 foreign-content surface.

    This is the production caller the provider slices were built for. Before it,
    the capability contract, the durable cache transaction, the rights gate and
    the retention planner all existed and nothing invoked them.
    """
    marketplace_parser = subparsers.add_parser(
        "marketplace",
        help="Inspect and install content from registered source providers",
    )
    verb_sub = marketplace_parser.add_subparsers(
        dest="verb", metavar="verb", help="Marketplace action"
    )

    list_parser = verb_sub.add_parser("list", help="List registered source providers")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")

    inventory_parser = verb_sub.add_parser(
        "inventory", help="Normalize one provider's inventory (installs nothing)"
    )
    inventory_parser.add_argument("name", help="Registered marketplace name")
    inventory_parser.add_argument(
        "--selector", default=None, help="Provider-native selector passed to enumerate"
    )
    inventory_parser.add_argument(
        "--admitted-maturity",
        action="append",
        dest="admitted_maturities",
        default=None,
        help=(
            "Maturity this scope promotes to installable; repeatable. Default is "
            "the stable maturity alone"
        ),
    )
    inventory_parser.add_argument("--json", action="store_true", help="Output JSON")

    install_parser = verb_sub.add_parser(
        "install", help="Install one foreign item through the durable cache transaction"
    )
    install_parser.add_argument("name", help="Registered marketplace name")
    install_parser.add_argument("upstream_id", help="Upstream item id to install")
    install_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    install_parser.add_argument(
        "--target",
        choices=["project_committed", "machine_local"],
        default="machine_local",
        help=(
            "Projection target. A committed project projection needs granted "
            "redistribution rights; the machine-local one is gitignored"
        ),
    )
    install_parser.add_argument(
        "--target-root", default=None, help="Directory the item is projected into"
    )
    install_parser.add_argument(
        "--accept-rights",
        action="store_true",
        help=(
            "Acknowledge the rights statement this command prints before it "
            "mutates anything. Required for an opt-in-required target"
        ),
    )
    install_parser.add_argument("--json", action="store_true", help="Output JSON")

    status_parser = verb_sub.add_parser(
        "status", help="Report foreign receipts and their cache state"
    )
    status_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    status_parser.add_argument("--json", action="store_true", help="Output JSON")

    gc_parser = verb_sub.add_parser(
        "gc", help="Plan (or perform) automatic collection of unreferenced objects"
    )
    gc_parser.add_argument(
        "--evidence-max-age-days",
        type=float,
        required=True,
        help=(
            "How old a source observation or re-fetch proof may be and still "
            "describe the present. Required, with no default: it is operator "
            "policy, and stale evidence deletes the last copy of pinned bytes"
        ),
    )
    gc_parser.add_argument(
        "--apply", action="store_true", help="Delete what the plan proved collectable"
    )
    gc_parser.add_argument("--json", action="store_true", help="Output JSON")


def _add_workspace_verbs(verb_sub: argparse._SubParsersAction) -> None:
    """Add the explicit metadata-only Workspace command surface."""
    list_parser = verb_sub.add_parser("list", help="List Workspace definitions")
    list_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    list_parser.add_argument("--json", action="store_true")

    show_parser = verb_sub.add_parser("show", help="Show one Workspace and its closure")
    show_parser.add_argument("reference")
    show_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    show_parser.add_argument("--json", action="store_true")

    validate_parser = verb_sub.add_parser(
        "validate", help="Validate a manifest or catalog reference"
    )
    validate_parser.add_argument("reference")
    validate_parser.add_argument("--json", action="store_true")

    use_parser = verb_sub.add_parser("use", help="Register and materialize a Workspace")
    use_parser.add_argument("reference")
    use_parser.add_argument("--scope", choices=["project", "global"], required=True)
    use_parser.add_argument("--target-project", type=Path, default=None)
    use_parser.add_argument(
        "--harness",
        choices=["claude_code", "codex", "cursor", "opencode", "antigravity", "all"],
        default="all",
    )
    use_parser.add_argument("--dry-run", action="store_true")
    use_parser.add_argument("--replace-with-catalog-content", action="store_true")
    use_parser.add_argument("--json", action="store_true")

    status_parser = verb_sub.add_parser(
        "status", help="Plan selected-scope Workspace reconciliation"
    )
    status_parser.add_argument("reference", nargs="?")
    status_parser.add_argument("--all", action="store_true", dest="all_workspaces")
    status_parser.add_argument("--scope", choices=["project", "global"], required=True)
    status_parser.add_argument("--target-project", type=Path, default=None)
    status_parser.add_argument(
        "--harness",
        choices=["claude_code", "codex", "cursor", "opencode", "antigravity", "all"],
        default="all",
    )
    status_parser.add_argument("--json", action="store_true")

    explain_parser = verb_sub.add_parser(
        "explain", help="Explain ownership of one receipt"
    )
    explain_parser.add_argument("member")
    explain_parser.add_argument("--scope", choices=["project", "global"], required=True)
    explain_parser.add_argument("--target-project", type=Path, default=None)
    explain_parser.add_argument("--json", action="store_true")

    sync_parser = verb_sub.add_parser("sync", help="Reconcile registered Workspaces")
    sync_parser.add_argument("reference", nargs="?")
    sync_parser.add_argument("--all", action="store_true", dest="all_workspaces")
    sync_parser.add_argument("--scope", choices=["project", "global"], required=True)
    sync_parser.add_argument("--target-project", type=Path, default=None)
    sync_parser.add_argument(
        "--harness",
        choices=["claude_code", "codex", "cursor", "opencode", "antigravity", "all"],
        default="all",
    )
    sync_parser.add_argument("--verify-receipts", action="store_true")
    sync_parser.add_argument("--prune", action="store_true")
    sync_parser.add_argument("--apply", action="store_true")
    sync_parser.add_argument("--acknowledge-plan")
    sync_parser.add_argument("--json", action="store_true")

    recover_parser = verb_sub.add_parser(
        "recover", help="Inspect or recover an incomplete Workspace transaction"
    )
    recover_parser.add_argument("--scope", choices=["project", "global"], required=True)
    recover_parser.add_argument("--target-project", type=Path, default=None)
    recover_parser.add_argument("--discard", action="store_true")
    recover_parser.add_argument("--acknowledge-plan")
    recover_parser.add_argument("--json", action="store_true")

    adopt_parser = verb_sub.add_parser(
        "adopt", help="Adopt or demote an existing member"
    )
    adopt_parser.add_argument("reference")
    adopt_parser.add_argument("member", nargs="?")
    adopt_parser.add_argument("--definition-commit")
    adopt_parser.add_argument("--from-direct", action="store_true")
    adopt_parser.add_argument("--all-reachable", action="store_true")
    adopt_parser.add_argument("--scope", choices=["project", "global"], required=True)
    adopt_parser.add_argument("--target-project", type=Path, default=None)
    adopt_parser.add_argument("--apply", action="store_true")
    adopt_parser.add_argument("--acknowledge-plan")
    adopt_parser.add_argument("--json", action="store_true")

    remove_parser = verb_sub.add_parser("remove", help="Unregister a Workspace root")
    remove_parser.add_argument("reference")
    remove_parser.add_argument("--scope", choices=["project", "global"], required=True)
    remove_parser.add_argument("--target-project", type=Path, default=None)
    remove_parser.add_argument("--json", action="store_true")


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
    try:
        entry = lookup_entry(catalog, primitive, name, fuzzy=True)
        default_scope = entry.get("default_scope", "project")
        if default_scope == "global":
            return "global"
        # 'ask' and 'project' both fall back to project for CLI invocations
        return "project"
    except Exception:
        return "project"


def _resolve_command_scope(
    catalog: dict,
    primitive: str,
    name: str,
    explicit_scope: str | None,
) -> str:
    """Resolve public CLI scope while enforcing primitive filesystem invariants."""
    if primitive == "mcp":
        if explicit_scope == "project":
            raise LibraryError(
                "MCP registrations are user-global and cannot use project scope. "
                "Omit --scope or pass --scope global."
            )
        return "global"
    if primitive in {"pi-extension", "pi-profile", "just-module"}:
        if explicit_scope == "global":
            raise LibraryError(
                f"{primitive} is project-only and cannot use global scope."
            )
        return "project"
    if explicit_scope is not None:
        return explicit_scope
    return _resolve_default_scope(catalog, primitive, name)


def _check_harness_support(entry: dict, harness: str) -> str | None:
    """Return an error message when the entry rejects the target harness."""
    harness_map = {
        "claude": "claude_code",
        "claude_code": "claude_code",
        "codex": "codex",
        "cursor": "cursor",
        "opencode": "opencode",
        "gemini": "gemini",
    }
    normalized = harness_map.get(harness)
    if normalized is None:
        return None

    support = (
        entry.get("metadata", {})
        .get("library", {})
        .get("harness_support", {})
        .get(normalized)
    )
    if support == "not-supported":
        return (
            f"This primitive is marked harness_support.{normalized}: "
            f"not-supported and cannot be installed for the {harness} harness."
        )
    return None


def _check_runtime_requirements(entry: dict) -> str | None:
    """Return an error message when declared runtime binaries are absent from PATH."""
    # The schema declares runtime_requirements at the top level of an entry
    # (#/$defs/runtime_requirements via $ref), distinct from harness_support which
    # lives under metadata.library. Read the schema-canonical top-level location only.
    runtime_requirements = entry.get("runtime_requirements", {})
    binaries = runtime_requirements.get("binaries", [])
    missing = [binary for binary in binaries if shutil.which(binary) is None]
    if missing:
        return (
            f"Missing required runtime binaries: {', '.join(missing)}. "
            "Install them before using this primitive."
        )
    return None


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
        msg = f"usage: library {primitive} use <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        scope = _resolve_command_scope(catalog, primitive, name, explicit_scope)
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    # Guard: check harness_support on the main entry BEFORE installing any dependencies.
    # This prevents partial mutations (dep installs) when the requested entry itself
    # does not support the target harness.
    if harness not in ("all", None):
        try:
            _main_entry = lookup_entry(catalog, primitive, name, fuzzy=True)
            _harness_error = _check_harness_support(_main_entry, harness)
            if _harness_error:
                if use_json:
                    print_json(error_result(_harness_error))
                else:
                    print(f"Error: {_harness_error}", file=sys.stderr)
                return EXIT_FAILURE
        except Exception:
            pass  # lookup failures are handled downstream

    # Reject unsupported harness/primitive combinations BEFORE any dependency
    # install or dry-run dispatch. This enforces AC8 ("fail before
    # dry-run/real-install side effects"): otherwise the per-installer checks
    # (agent.py, mcp_installer.py, guardrail_installer.py) only fire after
    # _install_with_deps has already materialized dependencies.
    #
    # cursor: no agent/mcp/guardrail support. opencode: no mcp/guardrail
    # support, but opencode agents ARE supported via the agent installer's
    # sources_map (see agent.py _resolve_agent_source), so they must not be
    # rejected here.
    CURSOR_UNSUPPORTED_PRIMITIVES = {"agent", "mcp", "guardrail"}
    OPENCODE_UNSUPPORTED_PRIMITIVES = {"mcp", "guardrail"}
    cursor_rejected = harness == "cursor" and primitive in CURSOR_UNSUPPORTED_PRIMITIVES
    opencode_rejected = (
        harness == "opencode" and primitive in OPENCODE_UNSUPPORTED_PRIMITIVES
    )
    if cursor_rejected or opencode_rejected:
        msg = (
            f"{primitive.capitalize()} install for harness '{harness}' is not supported. "
            f"{primitive.capitalize()} configuration for Cursor and OpenCode is not managed by this installer. "
            "Use harness 'claude_code' or 'codex' instead."
        )
        if use_json:
            print_json(error_result(msg, EXIT_FAILURE))
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
    return _dispatch_use(
        args,
        repo_root,
        catalog,
        primitive,
        name,
        scope,
        harness,
        dry_run,
        use_json,
        install_mode,
    )


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
        main_entry = lookup_entry(catalog, primitive, name, fuzzy=True)
    except LibraryError as exc:
        result = error_result(str(exc), exc.exit_code)
        if use_json:
            print_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    harness_error = _check_harness_support(main_entry, harness)
    if harness_error:
        if use_json:
            print_json(error_result(harness_error, EXIT_FAILURE))
        else:
            print(f"Error: {harness_error}", file=sys.stderr)
        return EXIT_FAILURE

    # Pre-flight compatibility and runtime checks for the requested entry (not
    # its deps). Run before dependency resolution/installation so fuzzy queries
    # cannot mutate dependencies before a main-entry gate fails.
    try:
        from lib.compat import check_compatibility_gate, CompatibilityError

        check_compatibility_gate(main_entry, harness)
    except CompatibilityError as _compat_exc:
        if use_json:
            print_json(error_result(str(_compat_exc), _compat_exc.exit_code))
        else:
            print(f"Error: {_compat_exc}", file=sys.stderr)
        return _compat_exc.exit_code

    runtime_error = _check_runtime_requirements(main_entry)
    if runtime_error:
        if use_json:
            print_json(error_result(runtime_error, EXIT_FAILURE))
        else:
            print(f"Error: {runtime_error}", file=sys.stderr)
        return EXIT_FAILURE

    resolved_name = main_entry.get("name", name)
    root_key = (primitive, resolved_name)

    def dependency_scope(dep_primitive: str, dep_name: str) -> str:
        if (dep_primitive, dep_name) == root_key:
            return scope
        return _resolve_command_scope(
            catalog, dep_primitive, dep_name, explicit_scope=None
        )

    try:
        install_order = resolve_requires(
            catalog, primitive, resolved_name, repo_root, scope
        )
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

    # Pre-flight runtime and catalog-contract gate for the FULL resolved install
    # order. Runtime requirements must fail before any install/dependency
    # mutation occurs; otherwise a missing binary on a later dependency would
    # only surface after earlier dependencies in install_order have already been
    # installed. Check every entry up front so the dependency graph install is
    # all-or-nothing. The same pass records which already-installed members
    # diverge from the active catalog contract, so the install loop below can
    # refresh them instead of skipping them.
    contract_drift_by_member: dict[tuple[str, str], str] = {}
    for dep_prim, dep_name in install_order:
        dep_scope = dependency_scope(dep_prim, dep_name)
        if dep_prim in {"pi-extension", "pi-profile", "just-module"}:
            from lib.installers.project_native import require_project_native_request

            try:
                require_project_native_request(dep_prim, dep_name, dep_scope)
            except LibraryError as exc:
                if use_json:
                    print_json(error_result(str(exc), exc.exit_code))
                else:
                    print(f"Error: {exc}", file=sys.stderr)
                return exc.exit_code
        try:
            dep_entry = lookup_entry(catalog, dep_prim, dep_name, fuzzy=False)
        except LibraryError:
            dep_entry = {}
        dep_runtime_error = _check_runtime_requirements(dep_entry)
        if dep_runtime_error:
            if use_json:
                print_json(error_result(dep_runtime_error, EXIT_FAILURE))
            else:
                print(f"Error: {dep_runtime_error}", file=sys.stderr)
            return EXIT_FAILURE

        # Catalog-contract gate. A member installed at an older contract must be
        # refreshed. When it cannot be refreshed from the active catalog — it
        # drifted but declares no installable source, or its declared source
        # cannot be resolved at all — fail here rather than install the root on
        # top of a member `use` can never repair. The blocker check is
        # deliberately independent of whether a drift reason was produced: an
        # unresolvable source also means we could not compare the contract in
        # the first place, so silence there would be indistinguishable from
        # "current".
        if not is_already_installed(dep_name, repo_root, dep_scope, dep_prim):
            continue
        verdict = _catalog_contract_drift(
            catalog, repo_root, dep_scope, dep_prim, dep_name
        )
        if verdict.blocker_reason:
            drift_error = (
                f"Dependency {dep_prim}:{dep_name} is already installed but "
                f"cannot be refreshed from the active catalog: "
                f"{verdict.blocker_reason}. Run `library {dep_prim} sync "
                f"{dep_name}` first, then retry `library {primitive} use "
                f"{resolved_name}`."
            )
            if use_json:
                print_json(error_result(drift_error, EXIT_FAILURE))
            else:
                print(f"Error: {drift_error}", file=sys.stderr)
            return EXIT_FAILURE
        if verdict.drift_reason:
            contract_drift_by_member[(dep_prim, dep_name)] = verdict.drift_reason

    # Install each entry in dependency order (deps first, main last)
    for dep_prim, dep_name in install_order:
        dep_scope = dependency_scope(dep_prim, dep_name)
        # Already-installed handling. is_already_installed() only checks
        # (lockfile_has_entry AND install_target_exists) — it does NOT detect:
        #   (a) catalog HEAD has moved beyond the lockfile's pinned source_commit
        #       ("upstream drift"), or
        #   (b) the deployed dir content no longer matches the lockfile's
        #       content_sha256 ("local tamper" — e.g. someone ran a manual cp,
        #       a partial-write left bad files, or another tool overwrote it).
        #   (c) an agent's declared private handler set changed while the
        #       primary installed prompt file stayed byte-identical.
        #   (d) the ACTIVE catalog moved the entry to a new source or bumped its
        #       declared version ("catalog contract drift" — the stale closure
        #       member case). This one takes precedence over the skip path
        #       because upstream_status is computed against the OLD source and
        #       therefore reports 'current'/'unknown' for a stale member.
        # Without these checks `use` silently no-ops in these cases, leaving
        # deployed files stale or broken.
        if is_already_installed(dep_name, repo_root, dep_scope, dep_prim):
            upstream_status = _check_upstream_status_for_entry(
                catalog, repo_root, dep_scope, dep_prim, dep_name
            )
            local_drift = _has_local_tamper(repo_root, dep_scope, dep_prim, dep_name)
            handler_drift = _has_agent_handler_declaration_drift(
                catalog, repo_root, dep_scope, dep_prim, dep_name, harness
            )
            # Reuse the pre-flight verdict; recomputing it here would re-read
            # the lockfile for every member.
            contract_drift = contract_drift_by_member.get((dep_prim, dep_name))
            if contract_drift:
                if not use_json:
                    print(
                        f"[refresh] {dep_prim}:{dep_name} diverges from the active "
                        f"catalog ({contract_drift}) — reinstalling",
                        file=sys.stderr,
                    )
                # Fall through to reinstall
            elif upstream_status == "behind":
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
            elif handler_drift:
                if not use_json:
                    print(
                        f"[refresh] {dep_prim}:{dep_name} declared handlers changed — reinstalling",
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
            args,
            repo_root,
            catalog,
            dep_prim,
            dep_name,
            dep_scope,
            harness,
            False,
            use_json,
            install_mode,
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


class _CatalogSources(NamedTuple):
    """How an active catalog entry resolves to installable source strings.

    Three states must stay distinguishable, because collapsing them hides a
    stale closure member behind a clean-looking skip:
      * no source intent     -> candidates empty, unresolvable_reason None
        (e.g. `distribution:`-only entries such as mcp/runtime-config); the
        entry never claimed to be installable from a source, so it is neither
        drift nor a failure.
      * resolvable intent    -> candidates non-empty; compare them normally.
      * unresolvable intent  -> candidates empty, unresolvable_reason set; the
        entry claims a source we cannot produce, so the member can neither be
        verified against the active catalog nor refreshed from it.
    """

    candidates: list[str]
    unresolvable_reason: str | None


class _CatalogContractVerdict(NamedTuple):
    """Verdict for one already-installed closure member vs. the active catalog.

    `drift_reason` set  -> reinstall the member from the active catalog.
    `blocker_reason` set -> the member cannot be refreshed automatically; the
    caller must fail before installing anything and demand an explicit sync.
    """

    drift_reason: str | None
    blocker_reason: str | None


_NO_CONTRACT_VERDICT = _CatalogContractVerdict(None, None)


def _normalize_source(value: str) -> str:
    """Normalize a source string for equality comparison."""
    text = str(value).strip()
    if text.startswith("~"):
        text = str(Path(text).expanduser())
    return text.rstrip("/")


def _catalog_entry_sources(catalog: dict, entry: dict) -> _CatalogSources:
    """Return every source string the active catalog entry could resolve to.

    Mirrors how the installers resolve a source (_resolve_entry_source in
    lib/installers/skill.py, plus the raw entry['source'] recorded by
    lib/installers/project_native.py) so a legitimate multi-harness or
    marketplace entry is never mistaken for a moved one. A marketplace that
    cannot be resolved — unknown marketplace, a schema-valid but non-git
    marketplace type, a marketplace without a source URL — is reported as an
    unresolvable intent rather than being silently dropped.
    """
    candidates: list[str] = []
    direct = entry.get("source")
    if isinstance(direct, str) and direct.strip():
        candidates.append(direct)
    sources_map = entry.get("sources") or {}
    if isinstance(sources_map, dict):
        for value in sources_map.values():
            if isinstance(value, str) and value.strip():
                candidates.append(value)

    unresolvable_reason: str | None = None
    # `from_marketplace` is the marketplace source intent. A bare `path` is not:
    # it can never produce a marketplace source on its own, so treating it as
    # intent would block entries that never claimed to be marketplace-backed.
    if entry.get("from_marketplace"):
        marketplace_source = None
        try:
            from lib.source import resolve_marketplace_source

            marketplace_source = resolve_marketplace_source(catalog, entry)
        except Exception as exc:
            # Any resolution failure is a signal, not noise: record it so the
            # caller can fail closed instead of treating it as "no drift".
            unresolvable_reason = str(exc)
        if marketplace_source:
            candidates.append(marketplace_source)
            unresolvable_reason = None
        elif unresolvable_reason is None:
            unresolvable_reason = (
                f"catalog entry '{entry.get('name')}' declares a marketplace "
                "source that resolves to nothing"
            )

    # An entry that already yields a usable source is installable regardless of
    # a secondary marketplace failure, so it is not blocked.
    if candidates:
        unresolvable_reason = None
    return _CatalogSources(candidates, unresolvable_reason)


def _catalog_contract_drift(
    catalog: dict,
    repo_root: Path,
    scope: str,
    primitive: str,
    name: str,
) -> _CatalogContractVerdict:
    """Compare an installed entry against the ACTIVE catalog contract.

    `_check_upstream_status_for_entry` only compares the lockfile's recorded
    source against that same source's HEAD, so it cannot see the case where the
    ACTIVE catalog moved the entry to a different source or bumped its declared
    version. Without this check an older direct install of a closure member
    survives a root install and the root loads against an incompatible member.

    Tolerant only of the genuinely unknowable cases (no lockfile, no lockfile
    entry, catalog lookup miss) — those return the empty verdict. A source that
    the active catalog cannot resolve is NOT unknowable: it is returned as a
    blocker so the caller fails closed.
    """
    from lib.lockfile import get_entry

    try:
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        if not lockfile_path.exists():
            return _NO_CONTRACT_VERDICT
        lock_entry = get_entry(load_lockfile(lockfile_path), name, primitive)
    except (LibraryError, OSError):
        # A missing/unreadable lockfile tells us nothing about the contract.
        return _NO_CONTRACT_VERDICT
    if lock_entry is None:
        return _NO_CONTRACT_VERDICT
    try:
        entry = lookup_entry(catalog, primitive, name, fuzzy=False)
    except LibraryError:
        return _NO_CONTRACT_VERDICT

    sources = _catalog_entry_sources(catalog, entry)
    if sources.unresolvable_reason:
        return _CatalogContractVerdict(
            None,
            "its active catalog source cannot be resolved "
            f"({sources.unresolvable_reason})",
        )

    drift_reason: str | None = None

    # Version drift. Only a minority of catalog entries declare a version, so
    # this check stays narrow: it fires only when the catalog states one.
    catalog_version = entry.get("version")
    if catalog_version is not None:
        locked_version = lock_entry.get("version")
        if str(locked_version or "") != str(catalog_version):
            drift_reason = (
                f"catalog declares version {catalog_version}, installed "
                f"version is {locked_version or 'unrecorded'}"
            )

    # Source drift. An empty candidate set means the entry declares no source
    # intent at all, which tells us nothing about the contract and is therefore
    # never drift on its own.
    locked_source = str(lock_entry.get("source") or "").strip()
    if drift_reason is None and locked_source and sources.candidates:
        normalized = {_normalize_source(item) for item in sources.candidates}
        if _normalize_source(locked_source) not in normalized:
            drift_reason = (
                f"catalog source is {sources.candidates[0]}, installed from "
                f"{locked_source}"
            )

    if drift_reason and not sources.candidates:
        # Drifted, but nothing to reinstall from.
        return _CatalogContractVerdict(
            drift_reason,
            f"{drift_reason}, and its catalog entry declares no installable source",
        )
    return _CatalogContractVerdict(drift_reason, None)


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

        target = resolve_lockfile_path(install_target_str, repo_root)
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


def _has_agent_handler_declaration_drift(
    catalog: dict,
    repo_root: Path,
    scope: str,
    primitive: str,
    name: str,
    harness: str,
) -> bool:
    """Return True iff declared agent handlers differ from lockfile records."""
    if primitive != "agent":
        return False

    try:
        from lib.installers.agent import (
            _declared_handler_paths,
            _handler_install_target,
            _resolve_agent_targets,
        )
        from lib.lockfile import get_entry

        entry = lookup_entry(catalog, primitive, name, fuzzy=False)
        agent_name = entry.get("name", name)
        declared_handlers = _declared_handler_paths(entry, agent_name)

        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        if not lockfile_path.exists():
            return False
        lock_data = load_lockfile(lockfile_path)
        lock_entry = get_entry(lock_data, name, primitive)
        if lock_entry is None:
            return False

        prim = get_primitive("agent")
        targets, _harness_missing = _resolve_agent_targets(
            catalog=catalog,
            entry=entry,
            prim=prim,
            agent_name=agent_name,
            repo_root=repo_root,
            scope=scope,
            harness=harness,
        )

        expected_handlers: set[str] = set()
        handler_roots: list[Path] = []
        for target in targets:
            agent_base = target["install_target"].parent
            handler_root = agent_base / f"{agent_name}-handlers"
            handler_roots.append(handler_root)
            for handler_path in declared_handlers:
                expected_handlers.add(
                    str(_handler_install_target(agent_base, agent_name, handler_path))
                )

        recorded_handlers = _recorded_agent_handler_targets(
            lock_entry,
            handler_roots,
            repo_root,
        )
        return expected_handlers != recorded_handlers
    except Exception:
        # Best-effort like the upstream/local-tamper checks: if handler drift
        # detection itself cannot run, do not force a reinstall.
        return False


def _recorded_agent_handler_targets(
    lock_entry: dict,
    handler_roots: list[Path],
    repo_root: Path,
) -> set[str]:
    """Return lockfile-recorded handler targets under the requested harness roots."""
    recorded: set[str] = set()
    for bridge in lock_entry.get("bridge_symlinks", []) or []:
        raw_target = str(bridge).split(" -> ", 1)[0].strip()
        if not raw_target:
            continue
        path = Path(raw_target.rstrip("/"))
        if not path.is_absolute():
            path = repo_root / path
        if any(path.is_relative_to(root) for root in handler_roots):
            recorded.add(str(path))
    return recorded


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
    resolve_project_native_dependencies: bool = True,
    source_catalog: str | None = None,
) -> int:
    """Dispatch to the correct primitive installer."""
    if source_catalog is not None:
        import copy

        bound_catalog = copy.deepcopy(catalog)
        primitive_info = get_primitive(primitive)
        if primitive_info is None:
            raise LibraryError(f"Unknown primitive {primitive!r}")
        section: dict = bound_catalog
        key_parts = primitive_info.yaml_key.split("/")
        for key in key_parts[:-1]:
            selected = section.get(key)
            if not isinstance(selected, dict):
                raise LibraryError(
                    f"Catalog has no canonical section for primitive {primitive}"
                )
            section = selected
        entries = section.get(key_parts[-1])
        if not isinstance(entries, list):
            raise LibraryError(
                f"Catalog has no canonical entry list for primitive {primitive}"
            )
        section[key_parts[-1]] = [
            item
            for item in entries
            if str(
                (item.get("metadata") or {}).get("library", {}).get("source_catalog")
                or ""
            )
            == source_catalog
        ]
        catalog = bound_catalog
    entry = lookup_entry(
        catalog,
        primitive,
        name,
        fuzzy=True,
        source_catalog=source_catalog,
    )
    harness_error = _check_harness_support(entry, harness)
    if harness_error:
        if use_json:
            print_json(error_result(harness_error, EXIT_FAILURE))
        else:
            print(f"Error: {harness_error}", file=sys.stderr)
        return EXIT_FAILURE

    runtime_error = _check_runtime_requirements(entry)
    if runtime_error:
        if use_json:
            print_json(error_result(runtime_error, EXIT_FAILURE))
        else:
            print(f"Error: {runtime_error}", file=sys.stderr)
        return EXIT_FAILURE

    # Compatibility pre-install gate (CL-d7e): check compatibility field before
    # dispatching to any primitive installer.
    try:
        from lib.compat import check_compatibility_gate, CompatibilityError

        check_compatibility_gate(entry, harness)
    except CompatibilityError as _compat_exc:
        if use_json:
            print_json(error_result(str(_compat_exc), _compat_exc.exit_code))
        else:
            print(f"Error: {_compat_exc}", file=sys.stderr)
        return _compat_exc.exit_code
    if primitive == "skill":
        return _use_skill(
            args,
            repo_root,
            catalog,
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "standard":
        return _use_standard(
            args, repo_root, catalog, name, scope, dry_run, use_json, install_mode
        )
    elif primitive == "agent":
        return _use_agent(
            args, repo_root, catalog, name, scope, dry_run, use_json, harness
        )
    elif primitive == "prompt":
        return _use_simple_file(
            args,
            repo_root,
            catalog,
            "prompt",
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "script":
        from lib.installers.uv_tool import is_uv_tool_entry

        if is_uv_tool_entry(entry):
            return _use_uv_tool(
                repo_root,
                catalog,
                name,
                scope,
                dry_run,
                use_json,
                harness,
                install_mode,
            )
        return _use_simple_file(
            args,
            repo_root,
            catalog,
            "script",
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "model-standard":
        return _use_simple_file(
            args,
            repo_root,
            catalog,
            "model-standard",
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "agent-base":
        return _use_simple_file(
            args,
            repo_root,
            catalog,
            "agent-base",
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "workflow":
        return _use_simple_file(
            args,
            repo_root,
            catalog,
            "workflow",
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive in {"pi-extension", "pi-profile", "just-module"}:
        return _use_project_native(
            args,
            repo_root,
            catalog,
            primitive,
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
            resolve_dependencies=resolve_project_native_dependencies,
        )
    elif primitive == "runtime-config":
        return _use_runtime_config(
            args,
            repo_root,
            catalog,
            name,
            scope,
            dry_run,
            use_json,
            harness,
            install_mode,
        )
    elif primitive == "mcp":
        return _use_mcp(
            args, repo_root, catalog, name, scope, dry_run, use_json, harness
        )
    elif primitive == "guardrail":
        return _use_guardrail(
            args, repo_root, catalog, name, scope, dry_run, use_json, harness
        )
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
    harness: str,
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
        return (
            0 if result.get("status") in ("ok", "dry-run", "blocked") else EXIT_FAILURE
        )
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
                print(
                    f"Warning: harness source missing for: {', '.join(result['harness_missing'])}"
                )
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
    """Install a prompt, script, model-standard, agent-base, or workflow."""
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


def _use_uv_tool(
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
    install_mode: str,
) -> int:
    """Install a directory-backed Python Script primitive with uv tool."""
    from lib.installers.uv_tool import install_uv_tool

    try:
        result = install_uv_tool(
            catalog=catalog,
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


def _use_project_native(
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
    *,
    resolve_dependencies: bool = True,
) -> int:
    """Install one project-only Pi or Just artifact."""
    from lib.installers.project_native import install_project_native_file
    from lib.resolver import resolve_requires

    try:
        if dry_run and resolve_dependencies:
            main_entry = lookup_entry(catalog, primitive, name, fuzzy=True)
            resolved_name = main_entry.get("name", name)
            install_order = resolve_requires(
                catalog, primitive, resolved_name, repo_root, scope
            )
            operations: list[dict] = []
            target_paths: list[str] = []
            lockfile_changes: list[dict] = []
            for dependency_primitive, dependency_name in install_order:
                captured_stdout = io.StringIO()
                with redirect_stdout(captured_stdout):
                    dependency_exit = _dispatch_use(
                        args,
                        repo_root,
                        catalog,
                        dependency_primitive,
                        dependency_name,
                        scope,
                        harness,
                        True,
                        True,
                        install_mode,
                        resolve_project_native_dependencies=False,
                    )
                try:
                    dependency_result = json.loads(captured_stdout.getvalue())
                except json.JSONDecodeError as exc:
                    raise LibraryError(
                        f"Invalid dry-run result for "
                        f"{dependency_primitive}:{dependency_name}."
                    ) from exc
                if dependency_exit != 0:
                    if use_json:
                        print_json(dependency_result)
                    else:
                        _print_human_result(dependency_result)
                    return dependency_exit
                operations.extend(dependency_result.get("operations", []))
                target_paths.extend(dependency_result.get("target_paths", []))
                lockfile_changes.extend(dependency_result.get("lockfile_changes", []))
            result = dry_run_result(
                operations,
                summary=(
                    f"Would install {primitive} '{resolved_name}' and "
                    f"{len(install_order) - 1} required dependencies"
                ),
                target_paths=target_paths,
                harness_routing=None,
                conflict_policy="overwrite",
                lockfile_changes=lockfile_changes,
                requires_user_confirmation=False,
            )
            result["dependency_order"] = [
                f"{dependency_primitive}:{dependency_name}"
                for dependency_primitive, dependency_name in install_order
            ]
        else:
            result = install_project_native_file(
                catalog=catalog,
                primitive=primitive,
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


def _use_runtime_config(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    name: str,
    scope: str,
    dry_run: bool,
    use_json: bool,
    harness: str,
    install_mode: str,
) -> int:
    """Compose and deploy a runtime-config (base + global overlay)."""
    from lib.runtime_config import install_runtime_config

    target_override = getattr(args, "target", None)
    try:
        result = install_runtime_config(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
            install_mode=install_mode,
            target_override=Path(target_override) if target_override else None,
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
    for key in [
        "CLAUDE_SETTINGS_FILE",
        "CODEX_CONFIG_FILE",
        "OPENCODE_CONFIG_FILE",
        "GEMINI_SETTINGS_FILE",
        "CURSOR_MCP_FILE",
    ]:
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
            print(
                f"  [{op.get('operation', '?')}] {op.get('details', op.get('path', ''))}"
            )
    elif status == "blocked":
        print(f"Blocked: {result.get('reason', '')}")
        if result.get("suggestion"):
            print(f"  Suggestion: {result['suggestion']}")
    elif status == "error":
        print(f"Error: {result.get('message', 'unknown error')}", file=sys.stderr)
    else:
        print(f"Result: {result}")


def _safe_receipted_remove(
    *,
    primitive: str,
    name: str,
    scope: str,
    repo_root: Path,
    catalog: dict,
    dry_run: bool,
    harness: str,
) -> dict | None:
    """Remove a v2 receipt through the ownership-aware exact-target transaction."""
    from lib.lockfile import root_id
    from lib.manager_inventory import collect_managed_paths, workspace_manager_adapters
    from lib.workspace import (
        apply_plan_ownership,
        apply_post_prune_lock,
        build_workspace_plan,
        clear_workspace_journal,
        prepare_prune_plan,
        recover_workspace_journal,
        select_prune_candidates,
        workspace_allowed_roots,
        workspace_write_lock,
        write_workspace_journal,
    )

    receipt_id = root_id(primitive, name)
    lock_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    preview = load_lockfile(lock_path)
    preview_receipt = next(
        (
            receipt
            for receipt in preview.get("receipts", [])
            if receipt.get("id") == receipt_id and receipt.get("scope", scope) == scope
        ),
        None,
    )
    if preview_receipt is None:
        return None

    with workspace_write_lock(lock_path):
        recover_workspace_journal(lock_path, repo_root)
        lock = load_lockfile(lock_path)
        receipt = next(
            (
                item
                for item in lock.get("receipts", [])
                if item.get("id") == receipt_id and item.get("scope", scope) == scope
            ),
            None,
        )
        if receipt is None:
            raise LibraryError(
                f"Receipt {receipt_id} changed while remove was acquiring its lock"
            )
        working = json.loads(json.dumps(lock))
        working["requested_roots"] = [
            root
            for root in working.get("requested_roots", [])
            if not (
                root.get("id") == receipt_id
                and root.get("type") != "workspace"
                and root.get("scope", scope) == scope
            )
        ]
        plan = build_workspace_plan(
            catalog,
            working,
            repo_root,
            scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        requested_roots_by_id = {
            str(root.get("id") or ""): root
            for root in working.get("requested_roots", [])
        }
        cached_owners = set(receipt.get("owners_cache") or []) - {receipt_id}
        reachability_blockers: list[str] = []
        for blocker in plan.get("blockers") or []:
            blocked_owner = blocker.split(": ", 1)[0]
            blocked_root = requested_roots_by_id.get(blocked_owner)
            if blocked_root and (
                blocked_root.get("type") == "workspace"
                or blocked_owner in cached_owners
            ):
                reachability_blockers.append(blocker)
        if reachability_blockers:
            raise LibraryError(
                "Remove blocked because Workspace reachability is incomplete: "
                + "; ".join(reachability_blockers)
            )
        plan["blockers"] = []
        owners = next(
            (
                item.get("owners") or []
                for item in plan.get("receipts", [])
                if item.get("id") == receipt_id
            ),
            [],
        )
        if owners:
            result = {
                "status": "dry-run" if dry_run else "ok",
                "message": (
                    f"Direct root '{receipt_id}' removed; installed content is retained "
                    "because it remains Workspace-reachable."
                ),
                "name": name,
                "removed_files": [],
                "retained_by": sorted(owners),
            }
            if dry_run:
                return result
            write_workspace_journal(
                lock_path,
                {
                    "operation": "remove",
                    "member": receipt_id,
                    "retained_by": sorted(owners),
                },
            )
            apply_plan_ownership(
                working,
                plan,
                prerequisite_statuses=_workspace_prerequisite_statuses(plan),
            )
            save_lockfile(lock_path, working)
            clear_workspace_journal(lock_path)
            return result

        if primitive == "script":
            try:
                script_entry = lookup_entry(catalog, primitive, name, fuzzy=True)
            except LibraryError:
                script_entry = {}
            from lib.installers.uv_tool import is_uv_tool_entry

            if is_uv_tool_entry(script_entry):
                if dry_run:
                    return _dispatch_remove(
                        primitive, catalog, name, repo_root, scope, True, harness
                    )
                write_workspace_journal(
                    lock_path,
                    {
                        "operation": "remove",
                        "member": receipt_id,
                        "external_manager": "uv-tool",
                    },
                )
                try:
                    return _dispatch_remove(
                        primitive, catalog, name, repo_root, scope, False, harness
                    )
                finally:
                    clear_workspace_journal(lock_path)

        catalog_entry_exists = any(
            entry.get("name") == name for entry in get_entries(catalog, primitive)
        )
        if not catalog_entry_exists and (
            not receipt.get("verified") or not receipt.get("targets")
        ):
            retained_paths = [
                str(target.get("path") or "")
                for target in receipt.get("targets") or []
                if target.get("path")
            ]
            result = success(
                data={
                    "name": name,
                    "removed_files": [],
                    "retained_orphan_paths": retained_paths,
                },
                message=(
                    f"Orphaned receipt '{receipt_id}' removed from Library state; "
                    "unverified or targetless filesystem content was retained."
                ),
            )
            if dry_run:
                return {
                    "status": "dry-run",
                    "summary": result["message"],
                    "operations": [
                        {
                            "operation": "retain",
                            "path": path,
                            "details": "unverified orphan content is not deleted",
                        }
                        for path in retained_paths
                    ],
                }
            write_workspace_journal(
                lock_path,
                {"operation": "remove", "member": receipt_id, "orphan": True},
            )
            apply_post_prune_lock(working, {receipt_id})
            apply_plan_ownership(
                working,
                plan,
                prerequisite_statuses=_workspace_prerequisite_statuses(plan),
            )
            save_lockfile(lock_path, working)
            clear_workspace_journal(lock_path)
            return result

        if not receipt.get("targets"):
            if dry_run:
                return _dispatch_remove(
                    primitive,
                    catalog,
                    name,
                    repo_root,
                    scope,
                    True,
                    harness,
                )
            write_workspace_journal(
                lock_path,
                {"operation": "remove", "member": receipt_id, "targetless": True},
            )
            try:
                return _dispatch_remove(
                    primitive,
                    catalog,
                    name,
                    repo_root,
                    scope,
                    False,
                    harness,
                )
            finally:
                clear_workspace_journal(lock_path)

        selected = select_prune_candidates(plan, {receipt_id})
        managed = collect_managed_paths(
            workspace_manager_adapters(
                catalog=catalog,
                project_root=repo_root,
                platform_root=TOOL_ROOT,
                scope=scope,
            )
        )
        prepared = prepare_prune_plan(
            working,
            selected,
            repo_root,
            selected["digest"],
            managed_paths=managed,
            allowed_roots=workspace_allowed_roots(catalog, repo_root, scope),
        )
        if dry_run:
            return {
                "status": "dry-run",
                "summary": f"Would safely remove '{receipt_id}'",
                "operations": [
                    {
                        "operation": "delete",
                        "path": item["path"],
                        "details": "delete exact verified Library target",
                    }
                    for item in prepared["targets"]
                ]
                + [
                    {
                        "operation": "delete",
                        "path": directory,
                        "details": "remove exact empty Library directory",
                    }
                    for directory in prepared["directories"]
                ],
            }
        write_workspace_journal(
            lock_path,
            {
                "operation": "prune",
                "scope": scope,
                "digest": selected["digest"],
                **prepared,
            },
        )
        apply_post_prune_lock(working, set(prepared["candidate_ids"]))
        apply_plan_ownership(
            working,
            selected,
            prerequisite_statuses=_workspace_prerequisite_statuses(selected),
        )
        save_lockfile(lock_path, working)
        deleted = recover_workspace_journal(lock_path, repo_root)
        for directory in prepared["directories"]:
            if not (Path(directory).exists() or Path(directory).is_symlink()):
                deleted.append(directory)
        if primitive in {"pi-extension", "pi-profile", "just-module"}:
            cleanup = _dispatch_remove(
                primitive,
                catalog,
                name,
                repo_root,
                scope,
                False,
                harness,
            )
            if cleanup.get("status") != "ok":
                raise LibraryError(
                    f"Post-reconciliation cleanup failed for {receipt_id}: {cleanup}"
                )
            for removed_path in cleanup.get("removed_files") or []:
                if removed_path not in deleted:
                    deleted.append(removed_path)
        return success(
            data={"name": name, "removed_files": deleted},
            message=f"'{receipt_id}' removed through exact receipt reconciliation.",
        )


def cmd_remove(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Handle: <primitive> remove [name] [--dry-run]"""
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    name = getattr(args, "name", None)
    explicit_scope = getattr(args, "scope", None)
    harness = getattr(args, "harness", "claude_code")
    primitive = args.primitive

    if name is None:
        msg = f"usage: library {primitive} remove <name>"
        if use_json:
            print_json(error_result(msg))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return EXIT_FAILURE

    if primitive == "mcp":
        # Project scope is a migration-only lock-record cleanup for MCP.
        scope = explicit_scope or "global"
    elif primitive in {"pi-extension", "pi-profile", "just-module"}:
        try:
            scope = _resolve_command_scope(catalog, primitive, name, explicit_scope)
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
    elif primitive == "script":
        try:
            script_entry = lookup_entry(catalog, primitive, name, fuzzy=True)
        except LibraryError:
            script_entry = {}
        from lib.installers.uv_tool import is_uv_tool_entry

        scope = (
            _resolve_command_scope(catalog, primitive, name, explicit_scope)
            if is_uv_tool_entry(script_entry)
            else explicit_scope or "project"
        )
    else:
        # Preserve historical remove semantics regardless of catalog default_scope.
        scope = explicit_scope or "project"

    try:
        result = _safe_receipted_remove(
            primitive=primitive,
            name=name,
            scope=scope,
            repo_root=repo_root,
            catalog=catalog,
            dry_run=dry_run,
            harness=harness,
        )
        if result is None:
            result = _dispatch_remove(
                primitive, catalog, name, repo_root, scope, dry_run, harness
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


def _dispatch_remove(
    primitive: str,
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str,
    dry_run: bool,
    harness: str = "claude_code",
) -> dict:
    """Dispatch remove to the correct primitive handler."""
    if primitive == "skill":
        from lib.installers.remove import remove_skill

        return remove_skill(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
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

        return remove_agent(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            harness=harness,
        )
    elif primitive == "prompt":
        from lib.installers.simple_file import remove_simple_file

        return remove_simple_file(
            catalog=catalog,
            primitive_name="prompt",
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive == "script":
        entry = lookup_entry(catalog, primitive, name, fuzzy=True)
        from lib.installers.uv_tool import is_uv_tool_entry, remove_uv_tool

        if is_uv_tool_entry(entry):
            return remove_uv_tool(
                catalog=catalog,
                name=name,
                repo_root=repo_root,
                scope=scope,
                dry_run=dry_run,
            )
        from lib.installers.simple_file import remove_simple_file

        return remove_simple_file(
            catalog=catalog,
            primitive_name="script",
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive == "model-standard":
        from lib.installers.simple_file import remove_simple_file

        return remove_simple_file(
            catalog=catalog,
            primitive_name="model-standard",
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive == "agent-base":
        from lib.installers.simple_file import remove_simple_file

        return remove_simple_file(
            catalog=catalog,
            primitive_name="agent-base",
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive == "workflow":
        from lib.installers.simple_file import remove_simple_file

        return remove_simple_file(
            catalog=catalog,
            primitive_name="workflow",
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive in {"pi-extension", "pi-profile", "just-module"}:
        from lib.installers.project_native import remove_project_native_file

        return remove_project_native_file(
            primitive=primitive,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
    elif primitive == "mcp":
        from lib.installers.mcp_installer import (
            remove_mcp,
            remove_project_mcp_lock_record,
        )

        if scope == "project":
            return remove_project_mcp_lock_record(
                name=name,
                repo_root=repo_root,
                dry_run=dry_run,
            )
        import os

        env_overrides: dict = {}
        for key in [
            "CLAUDE_SETTINGS_FILE",
            "CODEX_CONFIG_FILE",
            "OPENCODE_CONFIG_FILE",
        ]:
            if key in os.environ:
                env_overrides[key] = os.environ[key]
        return remove_mcp(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
            env_overrides=env_overrides if env_overrides else None,
        )
    elif primitive == "guardrail":
        from lib.installers.guardrail_installer import remove_guardrail

        return remove_guardrail(
            catalog=catalog,
            name=name,
            repo_root=repo_root,
            scope=scope,
            dry_run=dry_run,
        )
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
        msg = "usage: library search <keyword>  or  library <primitive> search <keyword>"
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
            _print_synced_source_commits(result)
        return 0 if result.get("status") in ("ok", "dry-run") else EXIT_FAILURE
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


def _print_synced_source_commits(result: dict) -> None:
    """List each synced entry with the commit it was actually built from.

    Sources are cloned from their catalog remote, so a local checkout that is
    ahead of that remote syncs the older published content while still
    reporting success. Printing the resolved commit is what makes that visible
    instead of leaving the caller with an unexplained stale install.
    """
    entries = (result.get("data") or {}).get("synced_entries") or []
    for entry in entries:
        commit = entry.get("source_commit")
        label = f"{entry.get('type', '?')}:{entry.get('name', '?')}"
        print(f"  {label} @ {commit[:8] if commit else 'unknown'}")


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
                print(
                    f"Audit: DRIFT detected in {len(drift_entries)}/{len(entries)} entries"
                )
                for e in drift_entries:
                    kind = e.get("drift_kind", "?")
                    print(f"  DRIFT [{kind}]: {e['primitive']}:{e['name']}")
                    if e.get("catalog_status") == "orphaned":
                        _print_catalog_provenance_issue(e)
                    _print_agent_frontmatter_issue(e)
            else:
                print(f"Audit: {status}")
            for e in entries:
                if e.get("catalog_status") == "undetermined":
                    _print_catalog_provenance_issue(e)
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


def cmd_audit_all(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
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
            print(
                f"Audit: DRIFT detected in {len(drift_entries)}/{len(all_entries)} entries"
            )
            for e in drift_entries:
                print(f"  DRIFT: {e['primitive']}:{e['name']}")
                if e.get("catalog_status") == "orphaned":
                    _print_catalog_provenance_issue(e)
                _print_agent_frontmatter_issue(e)
        for e in all_entries:
            if e.get("catalog_status") == "undetermined":
                _print_catalog_provenance_issue(e)
        for warning in warnings:
            print(f"Warning: {warning}")

    return EXIT_DRIFT if any_drift else 0


def _print_catalog_provenance_issue(entry: dict) -> None:
    """Print actionable catalog provenance audit context."""
    catalog_status = entry.get("catalog_status")
    if catalog_status == "orphaned":
        print(
            f"    ORPHANED from {entry.get('catalog_identity', 'unknown')}: "
            "entry is no longer listed by its catalog"
        )
        print(f"    remove: {entry.get('removal_command', '')}")
    elif catalog_status == "undetermined":
        print(
            f"  UNDETERMINED: {entry.get('primitive', 'item')}:{entry.get('name', '')} "
            "has no usable catalog identity; not classified as orphaned"
        )


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
    if any_behind or any(e.get("needs_refresh", e.get("behind")) for e in all_entries):
        overall = "behind"
    elif (
        all(e.get("upstream_status") == "current" for e in all_entries) and all_entries
    ):
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
            behind_count = sum(
                1 for e in all_entries if e.get("needs_refresh", e.get("behind"))
            )
            print(
                f"Status: BEHIND ({behind_count}/{len(all_entries)} entries need update)"
            )
            for e in all_entries:
                if e.get("behind"):
                    installed = e.get("installed_sha", "?")[:8]
                    remote = str(e.get("remote_sha", "?"))[:8]
                    print(
                        f"  BEHIND: {e['primitive']}:{e['name']} ({installed} -> {remote})"
                    )
                elif e.get("needs_refresh"):
                    installed = str(e.get("installed_sha", "?"))[:8]
                    runtime = str(e.get("runtime_revision") or "missing")[:8]
                    print(
                        f"  RUNTIME: {e['primitive']}:{e['name']} "
                        f"({runtime} != {installed}; {e.get('runtime_status', 'unknown')})"
                    )
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
    print(
        format_table(
            rows,
            [
                "Name",
                "Registry",
                "Writable",
                "Score",
                "Confidence",
                "Selection",
                "Topics",
            ],
        )
    )
    return 0


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _foreign_state(repo_root: Path | None):
    """Locate every durable store the foreign-content path writes to.

    Both receipt scopes are located, always. `ReferenceIndex` refuses a partial
    scope set by construction, and that refusal is the point: a collector that
    reads one scope answers "unreferenced" for objects the other scope is
    holding.
    """
    from lib.cache import _LIBRARY_HOME
    from lib.lockfile import GLOBAL_LOCKFILE, LOCKFILE_NAME
    from lib.providers.wiring import ForeignState

    project_root = repo_root or Path.cwd()
    return ForeignState.for_locks(
        cache_root=_LIBRARY_HOME / "foreign",
        project_lock=project_root / LOCKFILE_NAME,
        global_lock=Path(GLOBAL_LOCKFILE),
    )


def _marketplace_entry(catalog: dict, name: str) -> dict:
    from lib.catalog import get_marketplaces

    for entry in get_marketplaces(catalog):
        if isinstance(entry, dict) and str(entry.get("name")) == name:
            return entry
    raise LibraryError(f"No registered marketplace named '{name}'.")


def cmd_marketplace_list(args: argparse.Namespace, catalog: dict) -> int:
    from lib.catalog import get_marketplaces

    rows = [
        {
            "name": entry.get("name"),
            "source": entry.get("source"),
            "provider_kind": entry.get("provider_kind"),
            "allowlist": entry.get("allowlist") or [],
            "auth_ref": entry.get("auth_ref"),
        }
        for entry in get_marketplaces(catalog)
        if isinstance(entry, dict)
    ]
    if args.json:
        print_json(success({"marketplaces": rows}))
        return EXIT_SUCCESS
    for row in rows:
        kind = row["provider_kind"] or "legacy (no provider_kind)"
        print(f"{row['name']}: {kind}")
        print(f"  source: {row['source']}")
        if row["allowlist"]:
            print(f"  allowlist: {', '.join(row['allowlist'])}")
        if row["auth_ref"]:
            print(f"  credential reference: {row['auth_ref']}")
    return EXIT_SUCCESS


def cmd_marketplace_inventory(args: argparse.Namespace, catalog: dict) -> int:
    from lib.providers.admission import AdmissionContext, evaluate_inventory
    from lib.providers.wiring import marketplace_inventory

    entry = _marketplace_entry(catalog, args.name)
    _, result = marketplace_inventory(entry, selector=args.selector)
    context = AdmissionContext(
        admitted_maturities=tuple(args.admitted_maturities)
        if args.admitted_maturities
        else AdmissionContext().admitted_maturities
    )
    report = evaluate_inventory(result.inventory, context)

    rows = [
        {
            "qualified_identity": item.qualified_identity(),
            "library_type": item.library_type,
            "library_name": item.library_name,
            "upstream_name": item.upstream_name,
            "collection": list(item.collection_membership),
            "revision": item.upstream_revision,
            "maturity": item.classification.get("maturity"),
            "admission_state": item.admission_state,
            "block_reasons": [reason.describe() for reason in item.block_reasons],
            "rights": item.rights.to_dict(),
        }
        for item in report.inventory
    ]
    payload = {
        "provider_identity": result.provider_identity,
        "availability": result.provider_availability.to_dict(),
        "absent_capabilities": list(result.absent_capabilities),
        "costs": [cost.path for cost in result.costs],
        "items": rows,
    }
    if args.json:
        print_json(success(payload))
        return EXIT_SUCCESS
    print(f"{result.provider_identity} ({result.provider_availability.state})")
    for row in rows:
        marker = {"installable": "+", "discoverable": "-", "blocked": "x"}[
            row["admission_state"]
        ]
        print(f"  {marker} {row['library_type']}:{row['library_name']} [{row['maturity']}]")
        for reason in row["block_reasons"]:
            print(f"      {reason}")
    return EXIT_SUCCESS


def cmd_marketplace_install(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
    from lib.providers.admission import AdmissionContext, evaluate_item
    from lib.providers.classification import is_unclassified
    from lib.providers.rights import ProjectionRefused, RightsPresentation
    from lib.providers.wiring import install_marketplace_item, marketplace_inventory

    entry = _marketplace_entry(catalog, args.name)
    provider, result = marketplace_inventory(entry)
    identity = f"{provider.identity()}#{args.upstream_id}"
    try:
        item = result.inventory.resolve(identity)
    except KeyError as exc:
        raise LibraryError(str(exc)) from exc

    # Only `installable` installs. Accepting `discoverable` would silently undo
    # both non-promotion rules the inventory enforces: an `in-progress` item is
    # discoverable precisely because promoting it is an explicit scope decision,
    # and an unclassified member is discoverable precisely because the Library
    # has no type to install it as. Rejecting only `blocked` treated both as
    # installable and projected them.
    context = AdmissionContext()
    decision = evaluate_item(item, context)
    if decision.admission_state != "installable":
        reasons = [reason.describe() for reason in decision.block_reasons]
        if not reasons:
            maturity = str(item.classification.get("maturity") or "stable")
            if not context.admits_maturity(maturity):
                reasons = [
                    f"maturity {maturity!r} is not promoted by this scope; promoting it "
                    f"is an explicit decision (admitted maturities: "
                    f"{list(context.admitted_maturities)})"
                ]
            elif is_unclassified(item.library_type):
                reasons = [
                    "the member fits no existing Library primitive type, so there is "
                    "no type to install it as; it is listed, not installable"
                ]
            else:
                reasons = [
                    "no projection target is eligible under the recorded rights"
                ]
        payload = {
            "status": decision.admission_state,
            "qualified_identity": identity,
            "reasons": reasons,
        }
        if args.json:
            print_json(error_result(json.dumps(payload), 3))
        else:
            print(f"Not installable ({decision.admission_state}): {identity}", file=sys.stderr)
            for reason in reasons:
                print(f"  {reason}", file=sys.stderr)
        return 3

    shown: list[str] = []

    def present(presentation: RightsPresentation):
        # Displayed before the mutation, never discovered afterwards. The
        # acknowledgement carries this presentation's own token, so it cannot be
        # produced without the statement having been rendered here.
        shown.append(presentation.statement)
        print(presentation.statement)
        if not args.accept_rights:
            raise LibraryError(
                "This target requires an explicit operator opt-in for the rights "
                "state shown above. Re-run with --accept-rights to accept it.",
                exit_code=3,
            )
        return presentation.acknowledge(
            operator=os.environ.get("USER", "operator"),
            acknowledged_at=_utc_now(),
        )

    default_root = (
        (repo_root or Path.cwd()) / ".agents" / "foreign" / item.library_type / item.library_name
    )
    target_root = Path(args.target_root).expanduser() if args.target_root else default_root

    try:
        outcome = install_marketplace_item(
            item,
            provider=provider,
            state=_foreign_state(repo_root),
            scope=args.scope,
            target=args.target,
            target_root=target_root,
            present=present,
        )
    except ProjectionRefused as exc:
        if args.json:
            print_json(error_result(str(exc), 3))
        else:
            print(f"Refused: {exc}", file=sys.stderr)
        return 3

    payload = {
        "status": "installed",
        "qualified_identity": identity,
        "receipt_id": outcome.receipt.id,
        "cache_object": str(outcome.cache_object.path),
        "completeness_evidence": outcome.receipt.completeness_evidence,
        "events": list(outcome.events),
        "targets": [target.path for target in outcome.receipt.targets],
        "rights_statement_shown": bool(shown),
    }
    if args.json:
        print_json(success(payload))
    else:
        print(f"Installed {identity}")
        print(f"  receipt: {outcome.receipt.id}")
        print(f"  completeness: {outcome.receipt.completeness_evidence}")
        for target in outcome.receipt.targets:
            print(f"  target: {target.path}")
    return EXIT_SUCCESS


def cmd_marketplace_status(args: argparse.Namespace, repo_root: Path | None) -> int:
    state = _foreign_state(repo_root)
    store = state.receipt_store(args.scope)
    rows = [
        {
            "id": receipt.id,
            "qualified_identity": receipt.qualified_identity(),
            "library_type": receipt.library_type,
            "library_name": receipt.library_name,
            "upstream_state": receipt.upstream_state,
            "verified": receipt.verified,
            "revision": receipt.upstream_revision,
            "completeness_evidence": receipt.completeness_evidence,
            "targets": [target.path for target in receipt.targets],
        }
        for receipt in store.all()
    ]
    if args.json:
        print_json(success({"scope": args.scope, "receipts": rows}))
        return EXIT_SUCCESS
    if not rows:
        print(f"No foreign receipts in the {args.scope} scope.")
        return EXIT_SUCCESS
    for row in rows:
        # Local integrity and remote freshness are never merged into one "ok".
        print(f"{row['id']}: {row['qualified_identity']}")
        print(
            f"  upstream: {row['upstream_state']}; local integrity recorded: "
            f"{row['verified']}; remote freshness: unknown until re-observed"
        )
    return EXIT_SUCCESS


def cmd_marketplace_gc(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
    from datetime import timedelta

    from lib.catalog import get_marketplaces
    from lib.providers.wiring import build_provider, collect, resolution_observations

    providers = []
    for entry in get_marketplaces(catalog):
        if isinstance(entry, dict) and entry.get("provider_kind"):
            try:
                providers.append(build_provider(entry))
            except Exception as exc:  # noqa: BLE001 - an unbuildable source is unobserved
                print(
                    f"Warning: {entry.get('name')} could not be observed: {exc}",
                    file=sys.stderr,
                )

    observations = resolution_observations(providers)
    state = _foreign_state(repo_root)
    outcome = collect(
        state,
        observations=observations,
        evidence_max_age=timedelta(days=args.evidence_max_age_days),
        apply=args.apply,
    )

    decisions = outcome.plan.decisions if args.apply else outcome.decisions
    rows = [
        {
            "cache_key_digest": decision.key_digest,
            "qualified_identity": decision.qualified_identity,
            "collectable": decision.collectable,
            "reason": decision.reason or decision.detail,
        }
        for decision in decisions
    ]
    payload = {
        "applied": bool(args.apply),
        "observed_sources": sorted(observations),
        "evidence_max_age_days": args.evidence_max_age_days,
        "decisions": rows,
    }
    if args.json:
        print_json(success(payload))
        return EXIT_SUCCESS
    print(
        f"Observed {len(observations)} source(s); evidence window "
        f"{args.evidence_max_age_days} day(s)."
    )
    for row in rows:
        state_text = "collectable" if row["collectable"] else "retained"
        print(f"  {row['cache_key_digest'][:16]}: {state_text} — {row['reason']}")
    return EXIT_SUCCESS


def cmd_catalog_sync(
    args: argparse.Namespace, catalog_root: Path, catalog: dict
) -> int:
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
        print(
            f"Catalog sync: wrote {total} generated entries to {result.get('written')}"
        )
    else:
        print(f"Catalog sync dry-run: generated {total} entries")
    for primitive_name, count in generated.items():
        print(f"  {primitive_name}: {count}")
    for source in result.get("sources", []):
        if source.get("status") != "scanned":
            print(
                f"  skipped {source.get('name')}: {source.get('reason', source.get('status'))}"
            )
    return 0


def _missing_sync_dependencies(
    catalog: dict,
    installed: list[dict],
    repo_root: Path,
    scope: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return materialization gaps and non-fatal catalog reconciliation warnings."""
    from lib.resolver import is_already_installed, resolve_requires

    current_identity = get_catalog_identity(catalog)
    missing: list[tuple[str, str]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()

    for entry in installed:
        primitive = str(entry.get("type") or "")
        name = str(entry.get("name") or "")
        if not primitive or not name:
            continue

        recorded_identity = entry.get("catalog_identity")
        if (
            isinstance(recorded_identity, str)
            and current_identity is not None
            and normalize_catalog_identity(recorded_identity) != current_identity
        ):
            continue

        try:
            lookup_entry(catalog, primitive, name, fuzzy=False)
        except LibraryError:
            # Foreign and retired legacy entries cannot safely acquire dependencies
            # from the catalog currently driving this sync.
            continue

        root = (primitive, name)
        try:
            install_order = resolve_requires(catalog, primitive, name, repo_root, scope)
        except LibraryError as exc:
            warnings.append(
                f"could not reconcile dependencies for {primitive}:{name}: {exc}"
            )
            continue

        for dependency in install_order:
            if dependency == root or dependency in seen:
                continue
            seen.add(dependency)
            dependency_primitive, dependency_name = dependency
            dependency_entry = lookup_entry(
                catalog,
                dependency_primitive,
                dependency_name,
                fuzzy=False,
            )
            if scope == "project" and dependency_entry.get("default_scope") == "global":
                continue
            if not is_already_installed(
                dependency_name,
                repo_root,
                scope,
                dependency_primitive,
            ):
                missing.append(dependency)

    return missing, warnings


def cmd_sync_all(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
    """Handle: sync [--force] [--dry-run] [--scope=...] [--json]

    Top-level sync that iterates ALL primitives across all scopes.
    By default refreshes entries whose upstream source is behind or whose
    supervised runtime does not match the installed revision. With --force,
    re-installs all entries regardless.
    """
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    scope = getattr(args, "scope", "both")
    harness = getattr(args, "harness", "all")

    scopes_to_check = _scopes_to_check(scope)

    all_refreshed = []
    all_reconciled_dependencies = []
    all_skipped = []
    all_failed = []
    skipped_by_status: dict[str, list[str]] = {
        "current": [],
        "path_unchanged": [],
        "unknown": [],
        "other": [],
    }
    warnings: list[str] = []
    remote_cache: dict[tuple[str, str], str | None] = {}
    path_repo_cache: dict[tuple[str, str, str], Path | None] = {}

    with tempfile.TemporaryDirectory(prefix="library-sync-paths-") as temp_dir:
        path_check_root = Path(temp_dir)

        for s in scopes_to_check:
            if s == "project" and repo_root is None:
                if scope == "project":
                    warnings.append(_missing_project_warning())
                continue
            # Get upstream status to determine what needs syncing. This is a
            # repository-level check; a second path-aware filter below prevents
            # refreshing every installed entry from a marketplace when only one
            # source path changed.
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
                        (e["name"], e.get("primitive", e.get("type", ""))): e
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

            sync_root = repo_root or Path.cwd()
            missing_dependencies, reconciliation_warnings = _missing_sync_dependencies(
                catalog, installed, sync_root, s
            )
            warnings.extend(reconciliation_warnings)

            locked_by_key = {
                (entry.get("type"), entry.get("name")): entry for entry in installed
            }
            for dependency_type, dependency_name in missing_dependencies:
                dependency_label = f"{dependency_type}:{dependency_name}"
                if dry_run:
                    all_reconciled_dependencies.append(dependency_label)
                    continue
                locked_dependency = locked_by_key.get(
                    (dependency_type, dependency_name), {}
                )
                try:
                    reinstall_entry(
                        catalog,
                        {
                            "name": dependency_name,
                            "type": dependency_type,
                            "install_mode": locked_dependency.get(
                                "install_mode", "vendor"
                            ),
                        },
                        sync_root,
                        s,
                        harness,
                    )
                    all_reconciled_dependencies.append(dependency_label)
                except Exception as exc:
                    all_failed.append(
                        {
                            "name": dependency_name,
                            "type": dependency_type,
                            "error": str(exc),
                        }
                    )
                    if not use_json:
                        print(f"  ERROR: {dependency_name}: {exc}", file=sys.stderr)

            for entry in installed:
                entry_name = entry.get("name", "")
                entry_type = entry.get("type", "")
                entry_label = f"{entry_type}:{entry_name}"
                key = (entry_name, entry_type)

                status_entry = status_by_key.get(key, {})
                upstream_status = status_entry.get("upstream_status", "unknown")
                runtime_needs_refresh = bool(status_entry.get("needs_refresh"))
                should_refresh = (
                    force or upstream_status == "behind" or runtime_needs_refresh
                )
                if (
                    upstream_status == "behind"
                    and not force
                    and not runtime_needs_refresh
                ):
                    path_changed = _entry_source_path_changed(
                        entry=entry,
                        remote_sha=status_entry.get("remote_sha"),
                        temp_root=path_check_root,
                        repo_cache=path_repo_cache,
                    )
                    if path_changed is False:
                        should_refresh = False
                        upstream_status = "path_unchanged"
                    elif path_changed is None:
                        # Unknown means conservative behavior: refresh. This
                        # preserves old correctness for repo-only sources or
                        # remotes that cannot be diffed by path.
                        should_refresh = True

                should_skip = not should_refresh

                if dry_run:
                    if should_skip:
                        all_skipped.append(entry_label)
                        skipped_by_status[
                            upstream_status
                            if upstream_status in skipped_by_status
                            else "other"
                        ].append(entry_label)
                    else:
                        all_refreshed.append(entry_label)
                    continue

                if should_skip:
                    all_skipped.append(entry_label)
                    skipped_by_status[
                        upstream_status
                        if upstream_status in skipped_by_status
                        else "other"
                    ].append(entry_label)
                    continue

                # Re-install this entry
                try:
                    reinstall_entry(catalog, entry, repo_root, s, harness)
                    all_refreshed.append(entry_label)
                except (LibraryError, Exception) as exc:
                    all_failed.append(
                        {
                            "name": entry.get("name", ""),
                            "type": entry.get("type", ""),
                            "error": str(exc),
                        }
                    )
                    if not use_json:
                        print(f"  ERROR: {entry.get('name')}: {exc}", file=sys.stderr)

    # An entry whose source and install target are both gone is not an upstream
    # question -- it is unresolvable. Folding it into the generic warning is how
    # a stray test fixture survived months of syncs while reading like a network
    # problem (CL-t71i).
    unresolvable, still_unknown = _classify_unknown_entries(
        skipped_by_status["unknown"], installed, repo_root=repo_root
    )
    for label, source, target in unresolvable:
        primitive, _, entry_name = label.partition(":")
        warnings.append(
            f"unresolvable entry {label}: neither its source ({source}) nor its "
            f"install target ({target}) exists. Remove it with "
            f"`library {primitive} remove {entry_name} --scope global`."
        )
    unknown_skipped = len(still_unknown)
    if still_unknown:
        warnings.append(
            f"skipped {unknown_skipped} entries with unknown upstream status; "
            "use --force to refresh them"
        )

    result = {
        "status": "dry-run" if dry_run else "ok",
        "refreshed": all_refreshed,
        "reconciled_dependencies": all_reconciled_dependencies,
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
            f"Would reconcile {len(all_reconciled_dependencies)} dependencies, "
            f"refresh {len(all_refreshed)} entries, and "
            f"skip {len(all_skipped)} entries not reported behind"
        )

    if use_json:
        print_json(result)
    else:
        if dry_run:
            print(f"Dry-run: {result['summary']}")
            for label in all_reconciled_dependencies:
                print(f"  [would-install-dependency] {label}")
            for label in all_refreshed:
                print(f"  [would-refresh] {label}")
            for status_name, labels in skipped_by_status.items():
                for label in labels:
                    print(f"  [skip-{status_name}] {label}")
        else:
            print(
                f"Synced: {len(all_reconciled_dependencies)} dependencies reconciled, "
                f"{len(all_refreshed)} refreshed, {len(all_skipped)} skipped (not behind)"
            )
        for warning in warnings:
            print(f"Warning: {warning}")

    if all_failed:
        return EXIT_FAILURE
    return 0


def _classify_unknown_entries(
    unknown_labels: list[str],
    installed: list[dict],
    *,
    repo_root: Path | None = None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Split unknown-status labels into unresolvable and genuinely unknown.

    Unresolvable means both the recorded local source and the recorded install
    target no longer exist. Portable project targets are resolved against
    ``repo_root``; remote sources stay an upstream question. Anything else
    remains ``unknown upstream status``.
    """
    by_label = {
        f"{item.get('type', '')}:{item.get('name', '')}": item for item in installed
    }
    unresolvable: list[tuple[str, str, str]] = []
    still_unknown: list[str] = []
    for label in unknown_labels:
        entry = by_label.get(label, {})
        source = str(entry.get("source") or "")
        target = str(entry.get("install_target") or "")
        source_gone = source.startswith("/") and not Path(source).exists()
        target_path = (
            resolve_lockfile_path(target, repo_root)
            if target and repo_root is not None
            else Path(target)
        )
        target_gone = bool(target) and (
            target.startswith("/") or repo_root is not None
        ) and not target_path.exists()
        if source_gone and target_gone:
            unresolvable.append((label, source, target))
        else:
            still_unknown.append(label)
    return unresolvable, still_unknown


def _entry_source_path_changed(
    *,
    entry: dict,
    remote_sha: str | None,
    temp_root: Path,
    repo_cache: dict[tuple[str, str, str], Path | None],
) -> bool | None:
    """Return whether an installed entry's source path changed upstream.

    `library status` is intentionally repository-level and cheap. Bulk sync
    needs a narrower decision so one marketplace commit does not reinstall
    every installed primitive from that repo. `None` means the path check could
    not be performed and callers should keep conservative repo-level behavior.
    """
    source = str(entry.get("source") or "")
    installed_sha = str(entry.get("source_commit") or "")
    if not source or not installed_sha or installed_sha == "local" or not remote_sha:
        return None

    parsed = parse_source(source)
    if not parsed.is_remote_repository() or not parsed.clone_url:
        return None

    source_path = _entry_git_source_scope(entry, parsed)
    if not source_path:
        return None

    repo_dir = _ensure_remote_diff_repo(
        clone_url=parsed.clone_url,
        old_sha=installed_sha,
        new_sha=remote_sha,
        temp_root=temp_root,
        repo_cache=repo_cache,
    )
    if repo_dir is None:
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "diff",
                "--quiet",
                installed_sha,
                remote_sha,
                "--",
                source_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    return None


def _entry_git_source_scope(entry: dict, parsed: ParsedSource) -> str | None:
    """Return the git path that determines whether an entry needs refresh."""
    if not parsed.file_path:
        return None
    if parsed.path_type == "directory":
        return parsed.file_path
    if entry.get("type") == "skill":
        return parsed.parent_dir_in_repo() or parsed.file_path
    return parsed.file_path


def _ensure_remote_diff_repo(
    *,
    clone_url: str,
    old_sha: str,
    new_sha: str,
    temp_root: Path,
    repo_cache: dict[tuple[str, str, str], Path | None],
) -> Path | None:
    cache_key = (clone_url, old_sha, new_sha)
    if cache_key in repo_cache:
        return repo_cache[cache_key]

    repo_dir = temp_root / f"repo-{len(repo_cache)}"
    try:
        init = subprocess.run(
            ["git", "init", "--quiet", str(repo_dir)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if init.returncode != 0:
            repo_cache[cache_key] = None
            return None
        remote = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "add", "origin", clone_url],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if remote.returncode != 0:
            repo_cache[cache_key] = None
            return None
        if not _fetch_commit_for_diff(repo_dir, old_sha):
            repo_cache[cache_key] = None
            return None
        if not _fetch_commit_for_diff(repo_dir, new_sha):
            repo_cache[cache_key] = None
            return None
    except (OSError, subprocess.TimeoutExpired):
        repo_cache[cache_key] = None
        return None

    repo_cache[cache_key] = repo_dir
    return repo_dir


def _fetch_commit_for_diff(repo_dir: Path, commit_sha: str) -> bool:
    commands = [
        [
            "git",
            "-C",
            str(repo_dir),
            "fetch",
            "--quiet",
            "--no-tags",
            "--filter=blob:none",
            "--depth=1",
            "origin",
            commit_sha,
        ],
        [
            "git",
            "-C",
            str(repo_dir),
            "fetch",
            "--quiet",
            "--no-tags",
            "--depth=1",
            "origin",
            commit_sha,
        ],
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True
    return False


def _print_workspace_result(result: dict, *, json_mode: bool) -> None:
    """Render one Workspace result without leaking nested installer output."""
    if json_mode:
        print_json(result)
        return
    status = result.get("status", "ok")
    operation = result.get("operation", "workspace")
    print(f"Workspace {operation}: {status}")
    for key in ("reference", "scope", "digest"):
        if result.get(key) is not None:
            print(f"  {key}: {result[key]}")
    for key in (
        "additions",
        "updates",
        "replacements",
        "prune_candidates",
        "protected",
        "adoption_candidates",
        "collisions",
        "blockers",
        "follow_up",
    ):
        values = result.get(key)
        if values:
            print(f"  {key}:")
            for value in values:
                rendered = (
                    json.dumps(value, sort_keys=True)
                    if isinstance(value, dict)
                    else value
                )
                print(f"    - {rendered}")
    workspaces = result.get("workspaces")
    if workspaces:
        print("  workspaces:")
        for workspace in workspaces:
            if not isinstance(workspace, dict):
                print(f"    - {workspace}")
                continue
            details = [
                str(workspace.get(key))
                for key in ("version", "status")
                if workspace.get(key)
            ]
            suffix = f" ({', '.join(details)})" if details else ""
            print(f"    - {workspace.get('reference', workspace.get('id'))}{suffix}")
    for key in ("closure", "prerequisites", "owners", "deleted"):
        values = result.get(key)
        if values:
            print(f"  {key}:")
            for value in values:
                print(f"    - {_render_workspace_value(value)}")


def _render_workspace_value(value: object) -> str:
    """Render a structured Workspace detail as stable human-readable text."""
    if not isinstance(value, dict):
        return str(value)
    identifier = value.get("id")
    if not identifier:
        return json.dumps(value, sort_keys=True)
    details = []
    if value.get("catalog_identity"):
        details.append(f"catalog: {value['catalog_identity']}")
    if value.get("resolved_version"):
        details.append(f"version: {value['resolved_version']}")
    requested_by = value.get("requested_by")
    if isinstance(requested_by, list) and requested_by:
        requesters = ", ".join(str(item) for item in requested_by)
        details.append(f"requested by: {requesters}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{identifier}{suffix}"


def _registered_workspace_inventory(lock: dict, scope: str) -> list[dict]:
    """Return the registered Workspace roots selected by a status operation."""
    inventory = []
    for root in lock.get("requested_roots", []):
        if root.get("type") != "workspace" or root.get("scope", scope) != scope:
            continue
        catalog_name = str(root.get("catalog_name") or "")
        name = str(root.get("name") or "")
        reference = str(
            root.get("requested_ref")
            or (f"{catalog_name}:{name}" if catalog_name else name)
        )
        inventory.append(
            {
                "id": str(root.get("id") or ""),
                "reference": reference,
                "version": str(root.get("resolved_version") or ""),
                "status": "registered",
                "scope": str(root.get("scope") or scope),
                "catalog_identity": str(root.get("catalog_identity") or ""),
            }
        )
    return sorted(inventory, key=lambda item: (item["reference"], item["id"]))


def _workspace_definition_commit(catalog: dict, workspace) -> str:
    """Resolve the source catalog pin for a convention-scanned Workspace."""
    from lib.catalog import get_catalogs

    metadata = workspace.entry.get("metadata")
    if isinstance(metadata, dict):
        library_metadata = metadata.get("library")
        if isinstance(library_metadata, dict):
            recorded = library_metadata.get("source_commit")
            if isinstance(recorded, str) and recorded.strip():
                return recorded.strip()
    for source in get_catalogs(catalog):
        if source.get("name") != workspace.catalog_name:
            continue
        local_path = source.get("local_path")
        if not local_path:
            break
        result = subprocess.run(
            ["git", "-C", str(Path(str(local_path)).expanduser()), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise LibraryError(
        f"Workspace {workspace.catalog_name}:{workspace.name} has no resolvable definition commit"
    )


def _workspace_lock(repo_root: Path, scope: str) -> tuple[Path, dict]:
    path = find_lockfile(repo_root, global_scope=(scope == "global"))
    return path, load_lockfile(path)


def _workspace_prerequisite_blockers(plan: dict) -> list[str]:
    """Return missing or provenance-incompatible global prerequisites."""
    if not plan.get("prerequisites"):
        return []
    global_lock = load_lockfile(find_lockfile(global_scope=True))
    global_receipts = {
        str(receipt.get("id") or ""): receipt
        for receipt in global_lock.get("receipts", [])
    }
    blockers: list[str] = []
    for item in plan.get("prerequisites", []):
        receipt = global_receipts.get(str(item["id"]))
        if receipt is None:
            blockers.append(
                f"{item['id']} is required globally; run "
                f"library {item['id'].split(':', 1)[0]} use "
                f"{item['id'].split(':', 1)[1]} --scope global"
            )
            continue
        expected_identity = normalize_catalog_identity(
            str(item.get("catalog_identity") or "")
        )
        actual_identity = normalize_catalog_identity(
            str(receipt.get("catalog_identity") or "")
        )
        expected_version = str(item.get("resolved_version") or "")
        actual_version = str(receipt.get("resolved_version") or "")
        if expected_identity and actual_identity != expected_identity:
            blockers.append(
                f"{item['id']} global prerequisite has incompatible catalog provenance"
            )
        elif expected_version and actual_version != expected_version:
            blockers.append(
                f"{item['id']} global prerequisite version {actual_version or 'unknown'} "
                f"is incompatible with required version {expected_version}"
            )
    return blockers


def _workspace_prerequisite_statuses(plan: dict) -> dict[str, str]:
    """Return persisted prerequisite states from the authoritative global lock."""
    return {
        str(item["id"]): (
            "ready"
            if not _workspace_prerequisite_blockers({"prerequisites": [item]})
            else "missing-or-incompatible"
        )
        for item in plan.get("prerequisites", [])
    }


def _workspace_local_source(catalog: dict, entry: dict, primitive: str) -> Path | None:
    """Resolve a catalog entry to locally inspectable source content."""
    raw_source = str(entry.get("source") or "")
    direct = Path(raw_source).expanduser()
    if direct.exists():
        source = direct
    else:
        source_name = str(
            entry.get("metadata", {}).get("library", {}).get("source_catalog") or ""
        )
        source_catalog = next(
            (
                item
                for item in catalog.get("sources", {}).get("catalogs", [])
                if item.get("name") == source_name and item.get("local_path")
            ),
            None,
        )
        if source_catalog is None:
            return None
        marker = "/blob/" if "/blob/" in raw_source else "/tree/"
        if marker not in raw_source:
            return None
        suffix = raw_source.split(marker, 1)[1]
        _revision, separator, relative = suffix.partition("/")
        if not separator:
            return None
        source = Path(str(source_catalog["local_path"])).expanduser() / relative
    if primitive == "skill" and source.is_file() and source.name.lower() == "skill.md":
        return source.parent
    return source if source.exists() else None


def _workspace_pin_verifier(catalog: dict):
    """Answer what each declared Workspace catalog currently serves.

    ADR-0011 slice 5 shipped cross-catalog resolution that refused to produce a
    closure without this seam, and had no production implementation of it. This
    is that implementation: it reads the source through the provider layer, so
    the Workspace layer still knows nothing about how a source is read.

    A pin that cannot be answered is a refusal, not a pass. `assert_declared_pins`
    treats a raised exception as an unverified pin and refuses the whole closure,
    which is the fail-closed half of the same guarantee.
    """
    from lib.providers.wiring import source_revision

    def verify(entry) -> str:
        if entry.pin.kind != "commit":
            raise LibraryError(
                f"Workspace catalog {entry.identity} declares a "
                f"{entry.pin.kind!r} pin; this platform verifies commit pins "
                "against their source and refuses to report an unverified pin "
                "as verified"
            )
        return source_revision(entry.identity, catalog=catalog)

    return verify


def _workspace_normalized_members(
    catalog: dict, closure, repo_root: Path
) -> tuple[list, dict[str, dict[str, bytes]]]:
    """Normalize a resolved closure's members into inventory items and content.

    The Workspace layer resolves *catalog entries*; the admission gate judges
    *normalized items* bound to their exact bytes. This is the translation
    between the two, and it is deliberately strict: a member whose local content
    cannot be read produces no item, which makes the gate's whole-closure
    coverage check refuse the mutation rather than let a member through
    undigested.
    """
    from lib.providers.classification import (
        classification_for,
        executable_admission_for,
        library_name_for,
    )
    from lib.providers.inventory import NormalizedItem, ProviderAvailability, Rights

    observed_at = _utc_now()
    items: list = []
    contents: dict[str, dict[str, bytes]] = {}

    for node in closure.nodes:
        if node.role != "artifact":
            continue
        entry = lookup_entry(
            catalog,
            node.primitive,
            node.name,
            fuzzy=False,
            source_catalog=node.catalog_name,
        )
        source = _workspace_local_source(catalog, entry, node.primitive)
        if source is None:
            continue
        files: dict[str, bytes] = {}
        if source.is_file():
            files[source.name] = source.read_bytes()
        else:
            for path in sorted(source.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    files[path.relative_to(source).as_posix()] = path.read_bytes()
        if not files:
            continue

        item = NormalizedItem(
            provider_identity=node.catalog_identity or node.catalog_name,
            upstream_id=f"{node.primitive}/{node.name}",
            upstream_name=node.name,
            collection_membership=(node.catalog_name,),
            upstream_revision=node.pin.value if node.pin else None,
            library_type=node.primitive,
            library_name=library_name_for(node.name),
            classification=classification_for(
                node.primitive, "workspace-resolution", None, None, (node.catalog_name,)
            ),
            runtime_compatibility=("unknown",),
            rights=Rights(
                fetch_authorization="granted",
                install_rights="granted",
                redistribution_rights="granted",
                derivative_rights="granted",
                evidence_source=(
                    "first-party catalog content resolved from a registered source "
                    f"catalog ({node.catalog_identity or node.catalog_name}) at "
                    f"{observed_at}"
                ),
            ),
            provider_availability=ProviderAvailability(
                state="available", observed_at=observed_at
            ),
            executable_admission=executable_admission_for(node.primitive),
        )
        items.append(item)
        contents[item.qualified_identity()] = files

    return items, contents


def _workspace_gated_content_drift(
    catalog: dict, closure, repo_root: Path, admitted
) -> list[str]:
    """Members whose source no longer matches the content the gate admitted.

    The admission gate freezes and digests an immutable snapshot, and hands it to
    the mutation. The legacy installers cannot consume that snapshot — they
    resolve their own source — so without this comparison the gate binds a
    decision to bytes nobody guarantees are the ones written. Review demonstrated
    it end to end: editing a member's source between the snapshot and the install
    produced a successful run whose installed file contained the edited bytes.

    Returns:
        The qualified identities whose current content differs, in a stable
        order. Empty means every admitted member still matches its source.
    """
    from lib.providers.executable_admission import content_digest

    _, current = _workspace_normalized_members(catalog, closure, repo_root)
    drifted: list[str] = []
    for identity, files in dict(admitted).items():
        observed = current.get(identity)
        if observed is None or content_digest(dict(observed)) != content_digest(dict(files)):
            drifted.append(identity)
    for identity in current:
        if identity not in dict(admitted):
            drifted.append(identity)
    return sorted(set(drifted))


def _workspace_content_matches(source: Path, target: Path) -> bool:
    """Return whether an unreceipted target is byte-exact catalog content."""
    from lib.lockfile import compute_checksum

    if source.is_file() and target.is_file() and not target.is_symlink():
        return compute_checksum(source) == compute_checksum(target)
    if not source.is_dir() or not target.is_dir() or target.is_symlink():
        return False

    def inventory(root: Path) -> dict[str, tuple[str, str]]:
        result: dict[str, tuple[str, str]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", str(path.readlink()))
            elif path.is_file():
                result[relative] = ("file", compute_checksum(path))
        return result

    return inventory(source) == inventory(target)


def _workspace_collision_analysis(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    artifacts: tuple[tuple[str, str, str | None], ...],
    lock: dict,
) -> dict[str, list[str]]:
    """Preflight existing and externally managed targets before mutation."""
    from lib.manager_inventory import (
        canonical_manager_path,
        collect_managed_paths,
        workspace_manager_adapters,
    )

    owned_paths: set[Path] = set()
    for entry in lock.get("installed", []):
        raw_target = str(entry.get("install_target") or "").rstrip("/")
        if raw_target:
            path = Path(raw_target)
            owned_paths.add(
                canonical_manager_path(path if path.is_absolute() else repo_root / path)
            )
        for bridge in entry.get("bridge_symlinks") or []:
            raw_bridge = str(bridge).partition(" -> ")[0].strip()
            if raw_bridge:
                path = Path(raw_bridge)
                owned_paths.add(
                    canonical_manager_path(
                        path if path.is_absolute() else repo_root / path
                    )
                )
    managed = collect_managed_paths(
        workspace_manager_adapters(
            catalog=catalog,
            project_root=repo_root,
            platform_root=TOOL_ROOT,
            scope=args.scope,
        )
    )
    blockers: list[str] = []
    replacements: list[str] = []
    planned_owners: dict[Path, str] = {}
    for primitive, name, source_catalog in artifacts:
        catalog_entry = lookup_entry(
            catalog,
            primitive,
            name,
            fuzzy=False,
            source_catalog=source_catalog,
        )
        local_source = _workspace_local_source(catalog, catalog_entry, primitive)
        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer):
            rc = _dispatch_use(
                args,
                repo_root,
                catalog,
                primitive,
                name,
                args.scope,
                args.harness,
                True,
                True,
                "vendor",
                source_catalog=source_catalog,
            )
        if rc != 0:
            blockers.append(f"Cannot plan {primitive}:{name}")
            continue
        try:
            planned = json.loads(output_buffer.getvalue())
        except json.JSONDecodeError:
            blockers.append(
                f"Installer plan for {primitive}:{name} is not machine-readable"
            )
            continue
        for raw_target in planned.get("target_paths") or []:
            path = canonical_manager_path(Path(str(raw_target)))
            member_id = f"{primitive}:{name}"
            prior_owner = planned_owners.get(path)
            if prior_owner and prior_owner != member_id:
                blockers.append(
                    f"Target collision at {path}: {prior_owner} and {member_id}"
                )
                continue
            planned_owners[path] = member_id
            manager = managed.get(str(path))
            if manager:
                blockers.append(f"{path} is managed by {manager}")
                continue
            if not (path.exists() or path.is_symlink()):
                continue
            if path in owned_paths:
                continue
            if any(
                owned_path.is_dir() and path.is_relative_to(owned_path)
                for owned_path in owned_paths
            ):
                continue
            if (
                getattr(args, "replace_with_catalog_content", False)
                and local_source is not None
                and _workspace_content_matches(local_source, path)
            ):
                replacements.append(str(path))
                continue
            blockers.append(
                f"{path} already exists without a matching Library receipt; "
                "project-authored or externally owned content is protected"
            )
    return {
        "blockers": sorted(set(blockers)),
        "replacements": sorted(set(replacements)),
    }


def _workspace_use(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    from lib.workspace import (
        apply_plan_ownership,
        make_workspace_requested_root,
        resolve_workspace,
        resolve_workspace_closure,
        upsert_workspace_root,
    )

    workspace = resolve_workspace(catalog, args.reference)
    closure = resolve_workspace_closure(
        catalog,
        workspace,
        repo_root,
        args.scope,
        pin_verifier=_workspace_pin_verifier(catalog),
    )
    artifact_sources = {
        (primitive, name): source_catalog
        for primitive, name, source_catalog in closure.artifact_bindings
    }
    definition_commit = _workspace_definition_commit(catalog, workspace)
    lock_path, lock = _workspace_lock(repo_root, args.scope)
    requested_root = make_workspace_requested_root(
        workspace, args.scope, definition_commit, args.reference
    )
    preview_lock = json.loads(json.dumps(lock))
    upsert_workspace_root(preview_lock, requested_root)
    from lib.workspace import build_workspace_plan

    preview = build_workspace_plan(
        catalog,
        preview_lock,
        repo_root,
        args.scope,
        pin_verifier=_workspace_pin_verifier(catalog),
    )
    prerequisite_blockers = _workspace_prerequisite_blockers(preview)
    if prerequisite_blockers:
        preview["blockers"].extend(prerequisite_blockers)
    collision = _workspace_collision_analysis(
        args,
        repo_root,
        catalog,
        closure.artifact_bindings,
        lock,
    )
    preview["blockers"].extend(collision["blockers"])
    result = {
        "status": "blocked"
        if preview["blockers"]
        else ("dry-run" if args.dry_run else "planned"),
        "operation": "use",
        "reference": f"{workspace.catalog_name}:{workspace.name}",
        "catalog_identity": workspace.catalog_identity,
        "definition_commit": definition_commit,
        "scope": args.scope,
        "artifacts": [f"{primitive}:{name}" for primitive, name in closure.artifacts],
        "replacements": collision["replacements"],
        **{
            key: preview[key]
            for key in (
                "additions",
                "updates",
                "prune_candidates",
                "blockers",
                "digest",
            )
        },
    }
    if args.dry_run or preview["blockers"]:
        _print_workspace_result(result, json_mode=args.json)
        return 3 if preview["blockers"] else 0

    from lib.catalog import get_catalogs
    from lib.providers.executable_admission import (
        ExecutableAdmissionLedger,
        ResolutionRefused,
    )
    from lib.workspace import (
        clear_workspace_journal,
        gate_workspace_mutation,
        recover_workspace_journal,
        workspace_write_lock,
        write_workspace_journal,
    )

    with workspace_write_lock(lock_path):
        recover_workspace_journal(lock_path, repo_root)
        current_lock = load_lockfile(lock_path)
        locked_preview = json.loads(json.dumps(current_lock))
        upsert_workspace_root(locked_preview, requested_root)
        locked_plan = build_workspace_plan(
            catalog,
            locked_preview,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        locked_prerequisite_blockers = _workspace_prerequisite_blockers(locked_plan)
        if locked_prerequisite_blockers:
            result.update(
                {
                    "status": "blocked",
                    "blockers": locked_prerequisite_blockers,
                }
            )
            _print_workspace_result(result, json_mode=args.json)
            return 3
        locked_collision = _workspace_collision_analysis(
            args,
            repo_root,
            catalog,
            closure.artifact_bindings,
            current_lock,
        )
        if locked_collision["blockers"]:
            result.update(
                {
                    "status": "blocked",
                    "blockers": locked_collision["blockers"],
                    "replacements": locked_collision["replacements"],
                }
            )
            _print_workspace_result(result, json_mode=args.json)
            return 3
        preexisting_direct_ids = {
            str(root.get("id") or "")
            for root in current_lock.get("requested_roots", [])
            if root.get("type") != "workspace"
        }
        write_workspace_journal(
            lock_path,
            {
                "operation": "use",
                "reference": args.reference,
                "scope": args.scope,
                "definition_commit": definition_commit,
                "artifacts": [
                    f"{primitive}:{name}" for primitive, name in closure.artifacts
                ],
            },
        )
        member_failure: list[tuple[str, int, str]] = []

        def _install_members(frozen_content=None) -> None:
            """Install every resolved member, recording the first that failed.

            The failure is recorded rather than returned because this callable is
            invoked by the admission gate, which owns its own return value. A
            returned code would be swallowed there and the run would report
            success over a member that never installed.

            `frozen_content` is the exact immutable content the gate digested and
            admitted. The legacy installers cannot be handed bytes -- they resolve
            their own source -- so the binding is enforced instead of assumed:
            every member's source is re-read and compared against the admitted
            snapshot immediately before anything is written, and again after the
            last member is installed. A source that changed inside that window
            fails the whole operation, because the decision was made about
            different bytes than the ones on disk.
            """
            if frozen_content is not None:
                drifted = _workspace_gated_content_drift(
                    catalog, closure, repo_root, frozen_content
                )
                if drifted:
                    raise LibraryError(
                        "Workspace source content changed after the admission gate "
                        f"digested it: {drifted}. The gate admitted different bytes "
                        "than the installer would read, so nothing is written",
                        exit_code=3,
                    )
            for primitive, name in closure.artifacts:
                if frozen_content is not None:
                    # Per member, immediately before its own installer runs, so
                    # the unguarded window is one installer's read rather than
                    # the whole loop. It does not become zero: the installers
                    # resolve their own source, so a change made and undone
                    # inside a single read stays invisible. That residual is
                    # recorded in the ADR rather than papered over.
                    drifted = _workspace_gated_content_drift(
                        catalog, closure, repo_root, frozen_content
                    )
                    if drifted:
                        raise LibraryError(
                            "Workspace source content changed while its members were "
                            f"being installed: {drifted}. The gate admitted different "
                            "bytes than the installer would read; nothing further is "
                            "written",
                            exit_code=3,
                        )
                output_buffer = io.StringIO()
                with redirect_stdout(output_buffer):
                    rc = _dispatch_use(
                        args,
                        repo_root,
                        catalog,
                        primitive,
                        name,
                        args.scope,
                        args.harness,
                        False,
                        True,
                        "vendor",
                        source_catalog=artifact_sources[(primitive, name)],
                    )
                if rc != 0:
                    member_failure.append(
                        (f"{primitive}:{name}", rc, output_buffer.getvalue().strip())
                    )
                    return
            if frozen_content is not None:
                drifted = _workspace_gated_content_drift(
                    catalog, closure, repo_root, frozen_content
                )
                if drifted:
                    raise LibraryError(
                        "Workspace source content changed while its members were "
                        f"being installed: {drifted}. What was installed is not what "
                        "the gate admitted; re-run to install the current content",
                        exit_code=3,
                    )

        if closure.cross_catalog:
            # ADR-0011 slice 5 refused to materialize a v2 closure because three
            # things were missing: the declared pin verified against its source,
            # the members normalized into inventory items, and the executable
            # admission gate in the write path. All three are here now, so the
            # refusal is replaced by the gate it was standing in for.
            #
            # The gate is the single door from a completed resolution to a
            # mutation. It refuses a selection that is not exactly this closure,
            # then refuses any executable member with no admission decision for
            # its current bytes -- failing the whole resolution rather than
            # skipping the member.
            items, contents = _workspace_normalized_members(catalog, closure, repo_root)
            try:
                gate_workspace_mutation(
                    closure,
                    items,
                    ExecutableAdmissionLedger(),
                    contents,
                    mutate=_install_members,
                )
            except ResolutionRefused as exc:
                result.update({"status": "blocked", "blockers": [str(exc)]})
                _print_workspace_result(result, json_mode=args.json)
                return 3
        else:
            _install_members()

        if member_failure:
            member, rc, message = member_failure[0]
            _print_workspace_result(
                {
                    **result,
                    "status": "failed",
                    "failed_member": member,
                    "installer_output": message,
                },
                json_mode=args.json,
            )
            return rc

        lock = load_lockfile(lock_path)
        closure_ids = {f"{primitive}:{name}" for primitive, name in closure.artifacts}
        source_identities = {
            str(source.get("name") or ""): normalize_catalog_identity(
                str(source.get("source") or "")
            )
            for source in get_catalogs(catalog)
            if source.get("name") and source.get("source")
        }
        for primitive, name in closure.artifacts:
            entry = lookup_entry(
                catalog,
                primitive,
                name,
                fuzzy=False,
                source_catalog=artifact_sources[(primitive, name)],
            )
            source_name = str(
                entry.get("metadata", {}).get("library", {}).get("source_catalog") or ""
            )
            source_identity = source_identities.get(source_name)
            if not source_identity:
                continue
            member_id = f"{primitive}:{name}"
            for receipt in lock.get("receipts", []):
                if receipt.get("id") == member_id:
                    receipt["catalog_identity"] = source_identity
            for installed_entry in lock.get("installed", []):
                if (
                    installed_entry.get("type") == primitive
                    and installed_entry.get("name") == name
                ):
                    installed_entry["catalog_identity"] = source_identity
        lock["requested_roots"] = [
            root
            for root in lock.get("requested_roots", [])
            if root.get("type") == "workspace"
            or str(root.get("id") or "") not in closure_ids
            or str(root.get("id") or "") in preexisting_direct_ids
        ]
        upsert_workspace_root(lock, requested_root)
        applied_plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        apply_plan_ownership(
            lock,
            applied_plan,
            prerequisite_statuses=_workspace_prerequisite_statuses(applied_plan),
        )
        save_lockfile(lock_path, lock)
        clear_workspace_journal(lock_path)
    result.update(
        {
            "status": "applied",
            "additions": applied_plan["additions"],
            "prune_candidates": applied_plan["prune_candidates"],
            "digest": applied_plan["digest"],
        }
    )
    _print_workspace_result(result, json_mode=args.json)
    return 0


def _workspace_status(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    from lib.manager_inventory import collect_managed_paths, workspace_manager_adapters
    from lib.workspace import (
        build_workspace_plan,
        inspect_workspace_receipts,
        resolve_workspace,
        resolve_workspace_closure,
        workspace_allowed_roots,
        workspace_journal_path,
        workspace_root_id,
    )

    lock_path, lock = _workspace_lock(repo_root, args.scope)
    if args.reference:
        workspace = resolve_workspace(catalog, args.reference)
        selected_id = workspace_root_id(workspace.catalog_identity, workspace.name)
        if not any(
            root.get("id") == selected_id for root in lock.get("requested_roots", [])
        ):
            raise LibraryError(
                f"Workspace {args.reference} is not registered", exit_code=2
            )
    plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
    plan["blockers"].extend(_workspace_prerequisite_blockers(plan))
    status_artifacts: list[tuple[str, str, str | None]] = []
    seen_artifacts: set[tuple[str, str, str | None]] = set()
    for root in lock.get("requested_roots", []):
        if (
            root.get("type") != "workspace"
            or root.get("scope", args.scope) != args.scope
        ):
            continue
        try:
            registered = resolve_workspace(
                catalog,
                str(
                    root.get("requested_ref")
                    or f"{root.get('catalog_name', '')}:{root.get('name', '')}"
                ),
            )
            closure = resolve_workspace_closure(
                catalog,
                registered,
                repo_root,
                args.scope,
                pin_verifier=_workspace_pin_verifier(catalog),
            )
        except LibraryError:
            continue
        for bound in closure.artifact_bindings:
            if bound not in seen_artifacts:
                status_artifacts.append(bound)
                seen_artifacts.add(bound)
    collision = _workspace_collision_analysis(
        args, repo_root, catalog, tuple(status_artifacts), lock
    )
    plan["blockers"].extend(collision["blockers"])
    managed = collect_managed_paths(
        workspace_manager_adapters(
            catalog=catalog,
            project_root=repo_root,
            platform_root=TOOL_ROOT,
            scope=args.scope,
        )
    )
    plan["blockers"].extend(
        inspect_workspace_receipts(
            lock,
            plan,
            repo_root,
            managed_paths=managed,
            allowed_roots=workspace_allowed_roots(catalog, repo_root, args.scope),
        )
    )
    if workspace_journal_path(lock_path).exists():
        plan["blockers"].append(
            f"Incomplete Workspace transaction journal: {workspace_journal_path(lock_path)}"
        )
    protected = [
        {
            "id": item["id"],
            "reason": item.get("prune_blocked_reason") or "receipt is unverified",
            "action": (
                f"library workspace sync --all --scope {args.scope} --verify-receipts"
            ),
        }
        for item in plan["receipts"]
        if item.get("prune_blocked_reason") or not item.get("verified")
    ]
    adoption_candidates = [
        {
            "id": item["id"],
            "direct_root": item["id"],
            "workspace_roots": sorted(
                owner
                for owner in item.get("owners") or []
                if owner.startswith("workspace:")
            ),
            "action": "library workspace adopt <workspace> --from-direct --apply",
        }
        for item in plan["receipts"]
        if item["id"] in (item.get("owners") or [])
        and any(owner.startswith("workspace:") for owner in item.get("owners") or [])
    ]
    result = {
        "operation": "status",
        "status": "converged",
        "collisions": collision["blockers"],
        "adoption_candidates": adoption_candidates,
        **plan,
        "workspaces": _registered_workspace_inventory(lock, args.scope),
    }
    if plan["blockers"] or protected:
        result["status"] = "blocked"
        result["protected"] = protected
        exit_code = 3
    elif plan["additions"] or plan["updates"] or plan["prune_candidates"]:
        result["status"] = "changes-pending"
        exit_code = 2
    else:
        exit_code = 0
    _print_workspace_result(result, json_mode=args.json)
    return exit_code


def _workspace_sync(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    from lib.manager_inventory import collect_managed_paths, workspace_manager_adapters
    from lib.workspace import (
        apply_post_prune_lock,
        build_workspace_plan,
        prepare_prune_plan,
        recover_workspace_journal,
        workspace_allowed_roots,
        workspace_write_lock,
        write_workspace_journal,
    )

    lock_path, lock = _workspace_lock(repo_root, args.scope)
    if args.prune and args.verify_receipts:
        raise LibraryError("--verify-receipts and --prune are separate operations")
    if args.prune:
        plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        plan["blockers"].extend(_workspace_prerequisite_blockers(plan))
        result = {"operation": "sync-prune", "status": "preview", **plan}
        if not args.apply:
            _print_workspace_result(result, json_mode=args.json)
            return 3 if plan["blockers"] else 0
        with workspace_write_lock(lock_path):
            recover_workspace_journal(lock_path, repo_root)
            lock = load_lockfile(lock_path)
            plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
            plan["blockers"].extend(_workspace_prerequisite_blockers(plan))
            managed = collect_managed_paths(
                workspace_manager_adapters(
                    catalog=catalog,
                    project_root=repo_root,
                    platform_root=TOOL_ROOT,
                    scope=args.scope,
                )
            )
            prepared = prepare_prune_plan(
                lock,
                plan,
                repo_root,
                args.acknowledge_plan or "",
                managed_paths=managed,
                allowed_roots=workspace_allowed_roots(catalog, repo_root, args.scope),
            )
            write_workspace_journal(
                lock_path,
                {
                    "operation": "prune",
                    "scope": args.scope,
                    "digest": plan["digest"],
                    "candidate_ids": prepared["candidate_ids"],
                    "targets": prepared["targets"],
                    "directories": prepared["directories"],
                    "allowed_roots": prepared["allowed_roots"],
                },
            )
            apply_post_prune_lock(lock, set(prepared["candidate_ids"]))
            save_lockfile(lock_path, lock)
            deleted = recover_workspace_journal(lock_path, repo_root)
        result.update({"status": "applied", "deleted": deleted})
        _print_workspace_result(result, json_mode=args.json)
        return 0

    selected_workspace_id: str | None = None
    if args.reference:
        from lib.workspace import resolve_workspace, workspace_root_id

        selected = resolve_workspace(catalog, args.reference)
        selected_workspace_id = workspace_root_id(
            selected.catalog_identity, selected.name
        )
    references = []
    for root in lock.get("requested_roots", []):
        if (
            root.get("type") != "workspace"
            or root.get("scope", args.scope) != args.scope
        ):
            continue
        reference = str(root.get("requested_ref") or "")
        if selected_workspace_id and root.get("id") != selected_workspace_id:
            continue
        references.append(reference)
    if args.reference and not references:
        raise LibraryError(f"Workspace {args.reference} is not registered", exit_code=2)
    if not references and not args.verify_receipts:
        raise LibraryError("No registered Workspaces in selected scope", exit_code=2)
    applied: list[str] = []
    for reference in references:
        use_args = argparse.Namespace(
            reference=reference,
            scope=args.scope,
            harness=args.harness,
            dry_run=False,
            replace_with_catalog_content=False,
            json=True,
        )
        with redirect_stdout(io.StringIO()):
            rc = _workspace_use(use_args, repo_root, catalog)
        if rc != 0:
            return rc
        applied.append(reference)
    verified_receipts: list[str] = []
    if args.verify_receipts:
        from lib.catalog import get_catalogs

        with workspace_write_lock(lock_path):
            recover_workspace_journal(lock_path, repo_root)
            lock = load_lockfile(lock_path)
            direct_ids = {
                str(root.get("id") or "")
                for root in lock.get("requested_roots", [])
                if root.get("type") != "workspace"
                and root.get("scope", args.scope) == args.scope
            }
            pending = [
                receipt
                for receipt in lock.get("receipts", [])
                if receipt.get("scope", args.scope) == args.scope
                and not receipt.get("verified")
                and receipt.get("id") in direct_ids
            ]
            source_names = {
                normalize_catalog_identity(str(source.get("source") or "")): str(
                    source.get("name") or ""
                )
                for source in get_catalogs(catalog)
                if source.get("name") and source.get("source")
            }
            source_identities = {
                str(source.get("name") or ""): normalize_catalog_identity(
                    str(source.get("source") or "")
                )
                for source in get_catalogs(catalog)
                if source.get("name") and source.get("source")
            }
            verified_identities: dict[str, str] = {}
            for receipt in pending:
                receipt_id = str(receipt.get("id") or "")
                primitive, separator, name = receipt_id.partition(":")
                if not separator:
                    raise LibraryError(f"Invalid receipt identity {receipt_id!r}")
                source_catalog = source_names.get(
                    normalize_catalog_identity(
                        str(receipt.get("catalog_identity") or "")
                    )
                )
                if source_catalog is None:
                    exact_entries = [
                        entry
                        for entry in get_entries(catalog, primitive)
                        if entry.get("name") == name
                    ]
                    exact_sources = {
                        str(
                            (entry.get("metadata") or {})
                            .get("library", {})
                            .get("source_catalog")
                            or ""
                        )
                        for entry in exact_entries
                    }
                    exact_sources.discard("")
                    if len(exact_sources) == 1:
                        source_catalog = next(iter(exact_sources))
                    elif len(exact_entries) > 1:
                        raise LibraryError(
                            f"Receipt verification is ambiguous for {receipt_id}; "
                            "its source catalog cannot be proven"
                        )
                output_buffer = io.StringIO()
                with redirect_stdout(output_buffer):
                    rc = _dispatch_use(
                        args,
                        repo_root,
                        catalog,
                        primitive,
                        name,
                        args.scope,
                        args.harness,
                        False,
                        True,
                        "vendor",
                        source_catalog=source_catalog,
                    )
                if rc != 0:
                    raise LibraryError(
                        f"Receipt verification failed for {receipt_id}: "
                        f"{output_buffer.getvalue().strip()}"
                    )
                verified_receipts.append(receipt_id)
                if source_catalog and source_identities.get(source_catalog):
                    verified_identities[receipt_id] = source_identities[source_catalog]
            lock = load_lockfile(lock_path)
            for receipt in lock.get("receipts", []):
                identity = verified_identities.get(str(receipt.get("id") or ""))
                if identity:
                    receipt["catalog_identity"] = identity
            for installed_entry in lock.get("installed", []):
                installed_id = (
                    f"{installed_entry.get('type', '')}:"
                    f"{installed_entry.get('name', '')}"
                )
                identity = verified_identities.get(installed_id)
                if identity:
                    installed_entry["catalog_identity"] = identity
            remaining_unverified = [
                receipt
                for receipt in lock.get("receipts", [])
                if receipt.get("scope", args.scope) == args.scope
                and not receipt.get("verified")
            ]
            if not remaining_unverified and isinstance(lock.get("migration"), dict):
                lock["migration"]["prune_ack_required"] = False
            if verified_identities or (
                not remaining_unverified and isinstance(lock.get("migration"), dict)
            ):
                save_lockfile(lock_path, lock)

    result = {
        "operation": "sync",
        "status": "applied",
        "scope": args.scope,
        "workspaces": applied,
        "verified_receipts": verified_receipts,
    }
    _print_workspace_result(result, json_mode=args.json)
    return 0


def _workspace_adopt(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    from lib.manager_inventory import collect_managed_paths, workspace_manager_adapters
    from lib.workspace import (
        apply_direct_root_demotion,
        apply_plan_ownership,
        build_direct_root_demotion_plan,
        build_workspace_plan,
        clear_workspace_journal,
        recover_workspace_journal,
        resolve_workspace,
        workspace_allowed_roots,
        workspace_root_id,
        workspace_write_lock,
        write_workspace_journal,
        verify_receipt_targets,
    )

    workspace = resolve_workspace(catalog, args.reference)
    owner_id = workspace_root_id(workspace.catalog_identity, workspace.name)
    lock_path, preview_lock = _workspace_lock(repo_root, args.scope)
    if not any(
        root.get("id") == owner_id for root in preview_lock.get("requested_roots", [])
    ):
        raise LibraryError(f"Workspace {args.reference} is not registered")
    if args.from_direct and not args.apply:
        plan = build_direct_root_demotion_plan(
            catalog,
            preview_lock,
            repo_root,
            args.scope,
            args.reference,
            member=args.member,
            all_reachable=args.all_reachable,
        )
        _print_workspace_result(
            {"operation": "adopt-from-direct", "status": "preview", **plan},
            json_mode=args.json,
        )
        return 0

    with workspace_write_lock(lock_path):
        recover_workspace_journal(lock_path, repo_root)
        lock = load_lockfile(lock_path)
        if not any(
            root.get("id") == owner_id for root in lock.get("requested_roots", [])
        ):
            raise LibraryError(f"Workspace {args.reference} is not registered")
        if args.from_direct:
            plan = build_direct_root_demotion_plan(
                catalog,
                lock,
                repo_root,
                args.scope,
                args.reference,
                member=args.member,
                all_reachable=args.all_reachable,
            )
            write_workspace_journal(
                lock_path,
                {"operation": "adopt", "kind": "from-direct", **plan},
            )
            apply_direct_root_demotion(lock, plan, args.acknowledge_plan or "")
            refreshed = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
            apply_plan_ownership(
                lock,
                refreshed,
                prerequisite_statuses=_workspace_prerequisite_statuses(refreshed),
            )
            save_lockfile(lock_path, lock)
            clear_workspace_journal(lock_path)
            _print_workspace_result(
                {"operation": "adopt-from-direct", "status": "applied", **plan},
                json_mode=args.json,
            )
            return 0
        if not args.member or not args.definition_commit:
            raise LibraryError(
                "Filesystem adoption requires a member and --definition-commit"
            )
        receipt = next(
            (
                item
                for item in lock.get("receipts", [])
                if item.get("id") == args.member
            ),
            None,
        )
        if receipt is None or not receipt.get("verified"):
            raise LibraryError("Adoption requires an existing verified Library receipt")
        current_definition_commit = _workspace_definition_commit(catalog, workspace)
        if args.definition_commit != current_definition_commit:
            raise LibraryError(
                "Adoption definition pin does not match the selected catalog Workspace"
            )
        managed = collect_managed_paths(
            workspace_manager_adapters(
                catalog=catalog,
                project_root=repo_root,
                platform_root=TOOL_ROOT,
                scope=args.scope,
            )
        )
        verify_receipt_targets(
            receipt,
            repo_root,
            managed_paths=managed,
            allowed_roots=workspace_allowed_roots(catalog, repo_root, args.scope),
        )
        plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        if owner_id not in next(
            (item["owners"] for item in plan["receipts"] if item["id"] == args.member),
            [],
        ):
            raise LibraryError(f"Member {args.member} is not reached by Workspace")
        write_workspace_journal(
            lock_path,
            {
                "operation": "adopt",
                "kind": "filesystem",
                "member": args.member,
                "definition_commit": args.definition_commit,
            },
        )
        receipt["adopted"] = True
        receipt["definition_commit"] = args.definition_commit
        apply_plan_ownership(
            lock,
            plan,
            prerequisite_statuses=_workspace_prerequisite_statuses(plan),
        )
        save_lockfile(lock_path, lock)
        clear_workspace_journal(lock_path)
    _print_workspace_result(
        {"operation": "adopt", "status": "applied", "member": args.member},
        json_mode=args.json,
    )
    return 0


def _workspace_remove(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    from lib.workspace import (
        apply_plan_ownership,
        build_workspace_plan,
        clear_workspace_journal,
        recover_workspace_journal,
        remove_workspace_root,
        resolve_workspace,
        workspace_write_lock,
        write_workspace_journal,
    )

    workspace = resolve_workspace(catalog, args.reference)
    lock_path, _lock = _workspace_lock(repo_root, args.scope)
    with workspace_write_lock(lock_path):
        recover_workspace_journal(lock_path, repo_root)
        lock = load_lockfile(lock_path)
        if not remove_workspace_root(lock, workspace.catalog_identity, workspace.name):
            raise LibraryError(
                f"Workspace {args.reference} is not registered", exit_code=2
            )
        plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        apply_plan_ownership(
            lock,
            plan,
            prerequisite_statuses=_workspace_prerequisite_statuses(plan),
        )
        write_workspace_journal(
            lock_path,
            {
                "operation": "remove",
                "reference": args.reference,
                "digest": plan["digest"],
            },
        )
        save_lockfile(lock_path, lock)
        clear_workspace_journal(lock_path)
    _print_workspace_result(
        {
            "operation": "remove",
            "status": "unregistered",
            "reference": args.reference,
            "follow_up": [
                f"library workspace sync --all --scope {args.scope} --prune",
                (
                    f"library workspace sync --all --scope {args.scope} --prune "
                    f"--apply --acknowledge-plan {plan['digest']}"
                ),
            ],
            **plan,
        },
        json_mode=args.json,
    )
    return 0


def _workspace_recover(args: argparse.Namespace, repo_root: Path) -> int:
    from lib.workspace import (
        discard_workspace_journal,
        recover_workspace_journal,
        workspace_journal_digest,
        workspace_journal_path,
        workspace_write_lock,
    )

    lock_path, _lock = _workspace_lock(repo_root, args.scope)
    journal_path = workspace_journal_path(lock_path)
    digest = workspace_journal_digest(lock_path)
    if digest is None:
        _print_workspace_result(
            {
                "operation": "recover",
                "status": "clean",
                "scope": args.scope,
                "deleted": [],
            },
            json_mode=args.json,
        )
        return 0
    if args.discard:
        with workspace_write_lock(lock_path):
            discarded = discard_workspace_journal(
                lock_path, args.acknowledge_plan or ""
            )
        _print_workspace_result(
            {
                "operation": "recover",
                "status": "discarded",
                "scope": args.scope,
                "journal": str(journal_path),
                "journal_digest": discarded,
            },
            json_mode=args.json,
        )
        return 0
    try:
        with workspace_write_lock(lock_path):
            deleted = recover_workspace_journal(lock_path, repo_root)
    except LibraryError as exc:
        _print_workspace_result(
            {
                "operation": "recover",
                "status": "blocked",
                "scope": args.scope,
                "journal": str(journal_path),
                "journal_digest": digest,
                "blockers": [str(exc)],
                "discard_command": (
                    "library workspace recover "
                    f"--scope {args.scope} --discard --acknowledge-plan {digest}"
                ),
            },
            json_mode=args.json,
        )
        return 3
    _print_workspace_result(
        {
            "operation": "recover",
            "status": "recovered",
            "scope": args.scope,
            "deleted": deleted,
        },
        json_mode=args.json,
    )
    return 0


def cmd_workspace(args: argparse.Namespace, repo_root: Path, catalog: dict) -> int:
    """Dispatch the explicit Workspace lifecycle commands."""
    from lib.workspace import (
        build_workspace_plan,
        resolve_workspace,
        resolve_workspace_closure,
        validate_workspace_manifest,
    )

    if args.verb == "list":
        identities = []
        for entry in get_entries(catalog, "workspace"):
            metadata = entry.get("metadata", {}).get("library", {})
            identities.append(
                {
                    "reference": f"{metadata.get('source_catalog', '')}:{entry.get('name', '')}",
                    "name": entry.get("name"),
                    "version": entry.get("version"),
                    "status": entry.get("status", "experimental"),
                    "description": entry.get("description"),
                }
            )
        _print_workspace_result(
            {
                "operation": "list",
                "status": "ok",
                "scope": args.scope,
                "workspaces": identities,
            },
            json_mode=args.json,
        )
        return 0
    if args.verb == "show":
        workspace = resolve_workspace(catalog, args.reference)
        closure = resolve_workspace_closure(
        catalog,
        workspace,
        repo_root,
        args.scope,
        pin_verifier=_workspace_pin_verifier(catalog),
    )
        result = {
            "operation": "show",
            "status": "ok",
            "reference": f"{workspace.catalog_name}:{workspace.name}",
            "catalog_identity": workspace.catalog_identity,
            "scope": args.scope,
            "manifest": workspace.entry,
            "closure": [f"{primitive}:{name}" for primitive, name in closure.artifacts],
            "prerequisites": [
                f"{primitive}:{name}" for primitive, name in closure.prerequisites
            ],
        }
        _print_workspace_result(result, json_mode=args.json)
        return 0
    if args.verb == "validate":
        path = Path(args.reference).expanduser()
        if path.exists():
            import yaml

            manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
            validate_workspace_manifest(manifest)
            reference = str(path)
        else:
            workspace = resolve_workspace(catalog, args.reference)
            validate_workspace_manifest(workspace.entry)
            reference = f"{workspace.catalog_name}:{workspace.name}"
        _print_workspace_result(
            {"operation": "validate", "status": "valid", "reference": reference},
            json_mode=args.json,
        )
        return 0
    if args.verb == "use":
        return _workspace_use(args, repo_root, catalog)
    if args.verb == "status":
        return _workspace_status(args, repo_root, catalog)
    if args.verb == "explain":
        _lock_path, lock = _workspace_lock(repo_root, args.scope)
        plan = build_workspace_plan(
            catalog,
            lock,
            repo_root,
            args.scope,
            pin_verifier=_workspace_pin_verifier(catalog),
        )
        receipt = next(
            (item for item in plan["receipts"] if item["id"] == args.member), None
        )
        if receipt is None:
            raise LibraryError(f"Receipt {args.member} is not installed", exit_code=2)
        _print_workspace_result(
            {"operation": "explain", "status": "ok", "scope": args.scope, **receipt},
            json_mode=args.json,
        )
        return 0
    if args.verb == "sync":
        return _workspace_sync(args, repo_root, catalog)
    if args.verb == "recover":
        return _workspace_recover(args, repo_root)
    if args.verb == "adopt":
        return _workspace_adopt(args, repo_root, catalog)
    if args.verb == "remove":
        return _workspace_remove(args, repo_root, catalog)
    raise LibraryError(f"Unknown Workspace verb {args.verb}")


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
        return cmd_status(args, repo_root, catalog)

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
    # Top-level foreign-content commands (ADR-0011)
    if args.primitive == "marketplace":
        verb = getattr(args, "verb", None)
        if not verb:
            parser.parse_args(["marketplace", "--help"])
            return EXIT_FAILURE
        use_json = getattr(args, "json", False)
        try:
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
            repo_root = _resolve_lifecycle_project_root(args) or catalog_root
            if verb == "list":
                return cmd_marketplace_list(args, catalog)
            if verb == "inventory":
                return cmd_marketplace_inventory(args, catalog)
            if verb == "install":
                return cmd_marketplace_install(args, repo_root, catalog)
            if verb == "status":
                return cmd_marketplace_status(args, repo_root)
            if verb == "gc":
                return cmd_marketplace_gc(args, repo_root, catalog)
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            # A provider refusal is a typed fact, not a stack trace. Every one of
            # them names what was refused and why, so the message is the report.
            message = f"{type(exc).__name__}: {exc}"
            if type(exc).__name__ == "ProviderUnauthenticated":
                # Stated rather than left as a puzzle: this CLI has no way to
                # supply a token-scoped provider's client, because resolving a
                # credential reference into a session is credential handling and
                # is held for a human security review. The provider is reachable
                # only through a caller that owns the connection.
                message = (
                    f"{message}\n"
                    "This command cannot supply a client for a token-scoped "
                    "provider: resolving a credential reference into a session is "
                    "credential handling, which is deliberately not implemented "
                    "here. Registration, inventory schema, rights, and receipts "
                    "for this provider all work; only the transport is missing, "
                    "and no other source is substituted for it."
                )
            if use_json:
                print_json(error_result(message, EXIT_FAILURE))
            else:
                print(f"Error: {message}", file=sys.stderr)
            return EXIT_FAILURE

        print("Error: Unknown marketplace verb.", file=sys.stderr)
        return EXIT_FAILURE

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

    if args.primitive == "workspace":
        verb = getattr(args, "verb", None)
        if not verb:
            parser.parse_args(["workspace", "--help"])
            return EXIT_FAILURE
        try:
            catalog_root = _resolve_catalog_root()
            repo_root = _resolve_target_root(args, catalog_root)
            catalog = load_catalog(catalog_root)
            catalog = _select_workspace_catalog(
                args,
                repo_root=repo_root,
                catalog_root=catalog_root,
                catalog=catalog,
            )
            return cmd_workspace(args, repo_root, catalog)
        except LibraryError as exc:
            if getattr(args, "json", False):
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code

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
        print(
            f"Error: Unknown verb '{verb}'. Valid verbs: {', '.join(VALID_VERBS)}",
            file=sys.stderr,
        )
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


def _select_workspace_catalog(
    args: argparse.Namespace,
    *,
    repo_root: Path,
    catalog_root: Path,
    catalog: dict,
) -> dict:
    """Use the tool catalog when a consumer catalog cannot resolve locked Workspaces.

    Catalog repositories can also consume Workspaces. In that case their local
    ``library.yaml`` remains authoritative for their own primitive commands, but
    it must not hide Workspace definitions published through the Library tool's
    consolidated catalog.
    """
    references = _workspace_references_for_command(args, repo_root)
    verb = str(getattr(args, "verb", ""))
    if not references and verb == "list" and get_entries(catalog, "workspace"):
        return catalog
    if references and all(
        _workspace_reference_resolves(catalog, reference)
        for reference in references
    ):
        return catalog

    tool_catalog_root = find_repo_root(TOOL_ROOT)
    if tool_catalog_root.resolve() == catalog_root.resolve():
        return catalog
    tool_catalog = load_catalog(tool_catalog_root)
    if not references:
        return tool_catalog if verb == "list" else catalog
    if all(
        _workspace_reference_resolves(tool_catalog, reference)
        for reference in references
    ):
        return tool_catalog
    return catalog


def _workspace_reference_resolves(catalog: dict, reference: str) -> bool:
    """Return whether one Workspace reference resolves in a catalog."""
    from lib.workspace import resolve_workspace

    try:
        resolve_workspace(catalog, reference)
    except LibraryError:
        return False
    return True


def _workspace_references_for_command(
    args: argparse.Namespace, repo_root: Path
) -> list[str]:
    """Return Workspace references needed to execute the selected command."""
    verb = str(getattr(args, "verb", ""))
    direct = getattr(args, "reference", None)
    if verb == "validate" and direct and Path(str(direct)).expanduser().exists():
        return []
    if direct and verb in {
        "show",
        "validate",
        "use",
        "status",
        "sync",
        "adopt",
        "remove",
    }:
        return [str(direct)]
    if verb not in {"status", "sync", "explain"}:
        return []

    scope = str(getattr(args, "scope", "project"))
    lock = load_lockfile(
        find_lockfile(repo_root, global_scope=(scope == "global"))
    )
    references: list[str] = []
    for root in lock.get("requested_roots", []):
        if root.get("type") != "workspace":
            continue
        requested_ref = str(root.get("requested_ref") or "")
        if requested_ref:
            references.append(requested_ref)
    return references


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
