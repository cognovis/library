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
  --scope       project only (global desired state is retired)
  --target-project
                Project root for project-scoped writes
  --harness     claude_code, codex, pi, or all (where applicable)

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
  library standard use english-only --scope project
  library skill use dolt --dry-run --json
  library skill use dolt --symlink --json
  library search firecrawl
  library catalog match --primitive-type=standard --topics=python,uv --writable-only
  library installed --diff-catalog
"""

from __future__ import annotations

import argparse
import io
from importlib.resources import files
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import contextmanager, redirect_stdout
from hashlib import sha256
from pathlib import Path
from typing import Mapping, NamedTuple

# Make `lib` importable when running as a script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TOOL_ROOT = SCRIPT_DIR.parent
CANONICAL_PLATFORM_CATALOG_IDENTITY = "https://github.com/cognovis/library"
CANONICAL_BASE_WORKSPACE_REFERENCE = "library-platform:cognovis-base"

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
    EXIT_DECISION_REQUIRED,
    EXIT_SUCCESS,
    LibraryError,
)
from lib.lockfile import (
    find_lockfile,
    load_lockfile,
    resolve_lockfile_path,
    restore_cache_path_source_commit,
    restore_unchanged_install_timestamps,
    root_id,
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
from lib.source import WORKSPACE_SOURCE_COMMIT, ParsedSource, parse_source
from lib.sync_audit import (
    classify_catalog_provenance,
    cmd_audit_impl,
    cmd_sync_impl,
    reinstall_entry,
)


VALID_PRIMITIVES = all_primitive_names()
VALID_VERBS = ["list", "use", "remove", "sync", "search", "audit"]
DEFAULT_LIFECYCLE_SCOPE = "project"
PROJECT_ONLY_SCOPE_ERROR = (
    "Global Library desired state is not supported; use the current Git repository."
)


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
            "--untrack",
            action="store_true",
            help=(
                "Remove tracked Library-managed project installs from the Git "
                "index while keeping working-tree files"
            ),
        )
        use_p.add_argument(
            "--symlink",
            action="store_true",
            help="Install Layer C as a symlink into the cache instead of a vendored copy",
        )
        use_p.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
            help="Scope (project only)",
        )
        use_p.add_argument(
            "--target-project", "--project",
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
                "pi",
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
                "pi",
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
                "pi",
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
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize the current Git repository with cognovis-base",
    )
    init_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Git worktree top-level to initialize (default: current repository)",
    )
    init_parser.add_argument("--json", action="store_true", help="Output JSON")

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Provision or inspect the enumerated global product bootstrap"
    )
    bootstrap_verb_sub = bootstrap_parser.add_subparsers(dest="verb", metavar="verb")
    for verb, help_text in (
        ("install", "Install global bootstrap entrypoints and singleton configuration"),
        ("status", "Inspect global bootstrap entrypoints and singleton configuration"),
        ("remove", "Remove bootstrap targets proven by the product manifest"),
    ):
        item = bootstrap_verb_sub.add_parser(verb, help=help_text)
        item.add_argument("--json", action="store_true", help="Output JSON")
    cutover_parser = bootstrap_verb_sub.add_parser(
        "cutover-skills",
        help="Back up and remove verified legacy global Skill projections",
    )
    cutover_parser.add_argument(
        "--repository",
        action="append",
        type=Path,
        required=True,
        help="Exact canonical Beads repository to verify (repeat for every repository)",
    )
    cutover_parser.add_argument(
        "--fleet-manifest",
        type=Path,
        required=True,
        help="Operator-approved exact fleet with branch and published commit proofs",
    )
    cutover_parser.add_argument(
        "--backup",
        type=Path,
        required=True,
        help="New directory that will receive the recoverable cutover backup",
    )
    cutover_parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the backup and remove verified global Skill projections",
    )
    cutover_parser.add_argument("--json", action="store_true", help="Output JSON")

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
        choices=["project", "global"],
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
        choices=["project", "global"],
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
        choices=["project", "global"],
        default="project",
        help="Scope to show (default: project)",
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
        "--untrack",
        action="store_true",
        help=(
            "Remove tracked Library-managed project installs from the Git index "
            "while keeping working-tree files"
        ),
    )
    top_sync_parser.add_argument(
        "--scope",
        choices=["project", "global"],
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
        choices=["claude_code", "codex", "pi", "all"],
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
    _add_admission_verbs(subparsers)

    return parser


def _add_admission_verbs(subparsers: argparse._SubParsersAction) -> None:
    """The operator act that decides whether foreign executable content may run.

    `CL-n7ex` delivered the digest-bound ledger and the gate that reads it, and
    no way to write a decision into it, so every externally sourced Workflow, Pi
    extension, hook, guardrail, and script was refused permanently. This group
    is that missing act, and it is deliberately small and deliberately tedious:

    - a decision names **bytes**, never a name or a version, so `--digest` is
      required (or `--receipt`, which resolves one and shows it before writing);
    - there is no `--all` and no bulk verb, because a surface that admits many
      things at once is a surface people use to admit things they did not read;
    - `--operator` and `--reason` are required, and a grant states its permission
      surface even when that surface is empty.

    The verb words come from `lib.providers.executable_admission`, which is also
    where the install-time refusal renders the command it tells operators to run.
    """
    from lib.providers.executable_admission import (
        ADMISSION_COMMAND,
        DENY_VERB,
        GRANT_VERB,
        LIST_VERB,
        SHOW_VERB,
    )

    admission_parser = subparsers.add_parser(
        ADMISSION_COMMAND,
        help="Record and audit executable-admission decisions for foreign content",
    )
    verb_sub = admission_parser.add_subparsers(
        dest="verb", metavar="verb", help="Admission action"
    )

    for verb, description in (
        (GRANT_VERB, "Admit exactly these bytes to run in this scope"),
        (DENY_VERB, "Refuse exactly these bytes; the refusal stands until superseded"),
    ):
        decide_parser = verb_sub.add_parser(verb, help=description)
        subject = decide_parser.add_mutually_exclusive_group(required=True)
        subject.add_argument(
            "--digest",
            help=(
                "The sha256 content digest this decision is about. A decision "
                "never transfers to different bytes"
            ),
        )
        subject.add_argument(
            "--receipt",
            help=(
                "A foreign receipt id whose digest and identity are resolved and "
                "displayed before anything is recorded"
            ),
        )
        decide_parser.add_argument(
            "--identity",
            help="Qualified identity (<provider>#<upstream id>); implied by --receipt",
        )
        decide_parser.add_argument(
            "--type",
            dest="library_type",
            help="Library type of the artifact; implied by --receipt",
        )
        decide_parser.add_argument(
            "--operator",
            required=True,
            help=(
                "The declared identity of whoever is deciding. Recorded, never "
                "verified: authenticating an operator is credential handling"
            ),
        )
        decide_parser.add_argument(
            "--reason",
            required=True,
            help="What you reviewed and what it led you to decide",
        )
        decide_parser.add_argument(
            "--permission",
            action="append",
            dest="permissions",
            default=None,
            help=(
                "One permission this artifact requests; repeatable. Required for a "
                "grant unless --no-permissions states that it requests none"
            ),
        )
        decide_parser.add_argument(
            "--no-permissions",
            action="store_true",
            help="State that this artifact requests no permissions at all",
        )
        decide_parser.add_argument(
            "--supersede",
            action="store_true",
            help=(
                "Replace an existing decision for these exact bytes. Both stay in "
                "the ledger history"
            ),
        )
        decide_parser.add_argument(
            "--scope",
            choices=["project", "global"],
            default="project",
            help="Receipt scope searched by --receipt",
        )
        decide_parser.add_argument(
            "--project",
            type=Path,
            default=None,
            help="Project root whose receipts --receipt searches",
        )
        decide_parser.add_argument("--json", action="store_true", help="Output JSON")

    show_parser = verb_sub.add_parser(
        SHOW_VERB, help="Show the decisions recorded for one identity, with history"
    )
    show_parser.add_argument("--identity", required=True, help="Qualified identity")
    show_parser.add_argument("--digest", default=None, help="Narrow to one digest")
    show_parser.add_argument("--json", action="store_true", help="Output JSON")

    list_parser = verb_sub.add_parser(
        LIST_VERB, help="List every executable-admission decision that stands"
    )
    list_parser.add_argument("--json", action="store_true", help="Output JSON")


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

    _add_marketplace_update_verbs(verb_sub)

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


def _add_marketplace_update_verbs(verb_sub: argparse._SubParsersAction) -> None:
    """The `CL-lt51` update flow: fetch and summarize, then a human decides.

    The split between the verbs is the control. `update` fetches into the
    quarantine, scans, reviews, and writes a decision packet -- it changes no pin,
    no admission decision, and no projected byte, so an agent may run it.
    `update-approve` raises a pin and admits bytes, so an agent may not: the
    `.dcg/packs/library-pin-raise-guard.yaml` guard blocks it in an agent shell
    and the packet renders the exact command for the human to run instead.
    """
    from lib.providers.update_admission import (
        UPDATE_APPROVE_VERB,
        UPDATE_LIST_VERB,
        UPDATE_REJECT_VERB,
        UPDATE_SHOW_VERB,
        UPDATE_VERB,
    )

    update_parser = verb_sub.add_parser(
        UPDATE_VERB,
        help=(
            "Fetch a provider's current state into the update quarantine and "
            "produce a decision packet. Changes no pin and no projection"
        ),
    )
    update_parser.add_argument("name", help="Registered marketplace name")
    update_parser.add_argument(
        "--selector", default=None, help="Provider-native selector passed to enumerate"
    )
    update_parser.add_argument(
        "--item",
        action="append",
        dest="upstream_ids",
        default=None,
        help=(
            "Limit the update to these upstream ids; repeatable. The default is "
            "every item already pinned for this provider"
        ),
    )
    update_parser.add_argument(
        "--review-model",
        default=None,
        help="Exact adapter model id for the review stage",
    )
    update_parser.add_argument(
        "--review-agent", default=None, help="Agent-shell adapter for the review stage"
    )
    update_parser.add_argument(
        "--review-verdict-file",
        type=Path,
        default=None,
        help=(
            "Replay an already-recorded verdict artifact instead of dispatching a "
            "reviewer. The verdict must name this change set or it is refused"
        ),
    )
    update_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    update_parser.add_argument("--json", action="store_true", help="Output JSON")

    show_parser = verb_sub.add_parser(
        UPDATE_SHOW_VERB, help="Show one decision packet and its recommendation"
    )
    show_parser.add_argument("packet_id", help="Packet id from `marketplace update`")
    show_parser.add_argument(
        "--content",
        action="store_true",
        help="Also print the full post-update content of every changed item",
    )
    show_parser.add_argument("--json", action="store_true", help="Output JSON")

    list_parser = verb_sub.add_parser(
        UPDATE_LIST_VERB, help="List update packets and any decision recorded about them"
    )
    list_parser.add_argument("--json", action="store_true", help="Output JSON")

    approve_parser = verb_sub.add_parser(
        UPDATE_APPROVE_VERB,
        help=(
            "Adopt some or all of one packet: raise the pin, record the admission "
            "decision, and project. A human act; blocked in an agent shell"
        ),
    )
    approve_parser.add_argument("packet_id", help="Packet id from `marketplace update`")
    approve_parser.add_argument(
        "--operator",
        required=True,
        help=(
            "The declared identity of whoever is deciding. Recorded, never "
            "verified: authenticating an operator is credential handling"
        ),
    )
    approve_parser.add_argument(
        "--reason", required=True, help="What you read in this packet and why you accept it"
    )
    approve_parser.add_argument(
        "--item",
        action="append",
        dest="selected",
        default=None,
        help=(
            "Adopt only this qualified identity; repeatable. The default adopts "
            "every changed item in the packet"
        ),
    )
    approve_parser.add_argument(
        "--against-recommendation",
        action="store_true",
        help=(
            "Adopt although the packet does not recommend it. Required in that "
            "case, so overruling the packet is never accidental"
        ),
    )
    approve_parser.add_argument(
        "--scope", choices=["project", "global"], default="project"
    )
    approve_parser.add_argument(
        "--target",
        choices=["project_committed", "machine_local"],
        default="machine_local",
        help="Projection target for the adopted revision",
    )
    approve_parser.add_argument(
        "--target-root", default=None, help="Directory the adopted items are projected into"
    )
    approve_parser.add_argument(
        "--accept-rights",
        action="store_true",
        help="Acknowledge the rights statement printed before any mutation",
    )
    approve_parser.add_argument("--json", action="store_true", help="Output JSON")

    reject_parser = verb_sub.add_parser(
        UPDATE_REJECT_VERB,
        help="Record that this packet was declined. Changes nothing else at all",
    )
    reject_parser.add_argument("packet_id", help="Packet id from `marketplace update`")
    reject_parser.add_argument("--operator", required=True, help="Who is deciding")
    reject_parser.add_argument("--reason", required=True, help="Why the update is declined")
    reject_parser.add_argument("--json", action="store_true", help="Output JSON")


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
        choices=["claude_code", "codex", "pi", "all"],
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
        choices=["claude_code", "codex", "pi", "all"],
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
        choices=["claude_code", "codex", "pi", "all"],
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
    """Return the sole supported desired-state scope.

    Catalog metadata may retain historical ``default_scope`` values as migration
    evidence, but it cannot create a second, user-global desired state.
    """
    return "project"


def _resolve_command_scope(
    catalog: dict,
    primitive: str,
    name: str,
    explicit_scope: str | None,
) -> str:
    """Resolve public CLI scope while enforcing primitive filesystem invariants."""
    if primitive == "mcp":
        return "project"
    if primitive in {"pi-extension", "pi-profile", "just-module"}:
        if explicit_scope == "global":
            raise LibraryError(
                f"{primitive} is project-only and cannot use global scope."
            )
        return "project"
    if explicit_scope is not None:
        return explicit_scope
    return "project"


MCP_LIFECYCLE_RETIRED_ERROR = (
    "MCP registration lifecycle is retired. The supported OpenBrain singleton is "
    "managed by `library bootstrap install`; `library mcp remove <name> --scope "
    "project` only removes a legacy project lock record."
)


def _retired_mcp_lifecycle_result(*, json_mode: bool) -> int:
    """Report that public MCP registration cannot recreate global desired state."""
    if json_mode:
        print_json(error_result(MCP_LIFECYCLE_RETIRED_ERROR, EXIT_FAILURE))
    else:
        print(f"Error: {MCP_LIFECYCLE_RETIRED_ERROR}", file=sys.stderr)
    return EXIT_FAILURE


def _check_harness_support(entry: dict, harness: str) -> str | None:
    """Return an error message when the entry rejects the target harness."""
    harness_map = {
        "claude": "claude_code",
        "claude_code": "claude_code",
        "codex": "codex",
        "pi": "pi",
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

    if primitive == "mcp":
        return _retired_mcp_lifecycle_result(json_mode=use_json)

    try:
        scope = _resolve_command_scope(catalog, primitive, name, explicit_scope)
    except LibraryError as exc:
        if use_json:
            print_json(error_result(str(exc), exc.exit_code))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code

    if scope == "project":
        _preflight_managed_project(args, repo_root, allow_missing_lock=True)

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

    # Resolve transitive dependencies before installing
    if not dry_run:
        captured = io.StringIO()
        output_context = redirect_stdout(captured) if use_json else _null_context()
        with output_context:
            exit_code = _install_with_deps(
                args, repo_root, catalog, primitive, name, scope, harness, use_json
            )
        if exit_code != 0 or scope != "project":
            if use_json:
                print(captured.getvalue(), end="")
            return exit_code
        gitignore_result = _reconcile_project_gitignore(
            repo_root, untrack=getattr(args, "untrack", False)
        )
        warning = _tracked_install_warning(gitignore_result)
        if use_json:
            install_output = captured.getvalue().strip()
            try:
                result = json.loads(install_output)
            except json.JSONDecodeError:
                result = success({"install_output": install_output})
            result["gitignore"] = gitignore_result
            if warning:
                result.setdefault("warnings", []).append(warning)
            print_json(result)
        else:
            _print_gitignore_result(gitignore_result, warning=warning)
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


@contextmanager
def _null_context():
    """Context-manager equivalent of doing nothing, without another import."""
    yield


def _reconcile_project_gitignore(
    repo_root: Path, *, untrack: bool = False
) -> dict:
    from lib.gitignore import reconcile_project_gitignore

    return reconcile_project_gitignore(repo_root, untrack=untrack)


def _tracked_install_warning(gitignore_result: dict) -> str | None:
    tracked = gitignore_result.get("tracked_paths") or []
    if not tracked:
        return None
    return (
        f"{len(tracked)} Library-managed project path(s) are already tracked by "
        "Git; rerun with --untrack to remove them from the index while keeping "
        "the working-tree files"
    )


def _print_gitignore_result(
    gitignore_result: dict, *, warning: str | None = None
) -> None:
    """Render the managed ignore and explicit index changes for humans."""
    if gitignore_result.get("updated"):
        print(f"Updated Library-managed ignores in {gitignore_result['path']}")
    for path in gitignore_result.get("tracked_paths") or []:
        print(f"  [tracked-managed-path] {path}")
    for path in gitignore_result.get("untracked_paths") or []:
        print(f"  [untracked-from-index] {path}")
    if warning:
        print(f"Warning: {warning}")


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

    planned_targets, planned_target_error = _validate_project_install_plan(
        args,
        repo_root,
        catalog,
        install_order,
        dependency_scope,
        harness,
    )
    if planned_target_error is not None:
        if use_json:
            print_json(
                error_result(
                    str(planned_target_error), planned_target_error.exit_code
                )
            )
        else:
            print(f"Error: {planned_target_error}", file=sys.stderr)
        return planned_target_error.exit_code

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
        if dep_scope == "project":
            revalidation_error = _revalidate_project_member_targets(
                repo_root,
                dep_prim,
                dep_name,
                planned_targets.get((dep_prim, dep_name), []),
            )
            if revalidation_error is not None:
                if use_json:
                    print_json(
                        error_result(
                            str(revalidation_error), revalidation_error.exit_code
                        )
                    )
                else:
                    print(f"Error: {revalidation_error}", file=sys.stderr)
                return revalidation_error.exit_code
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


def _validate_project_install_plan(
    args: argparse.Namespace,
    repo_root: Path,
    catalog: dict,
    install_order: list[tuple[str, str]],
    dependency_scope: Callable[[str, str], str],
    harness: str,
) -> tuple[dict[tuple[str, str], list[str]], LibraryError | None]:
    """Dry-plan the complete project closure and validate every recorded target."""
    from lib.gitignore import validate_planned_project_target

    install_mode = "symlink" if getattr(args, "symlink", False) else "vendor"
    planned_targets: dict[tuple[str, str], list[str]] = {}
    for dep_primitive, dep_name in install_order:
        if dependency_scope(dep_primitive, dep_name) != "project":
            continue
        captured = io.StringIO()
        with redirect_stdout(captured):
            exit_code = _dispatch_use(
                args,
                repo_root,
                catalog,
                dep_primitive,
                dep_name,
                "project",
                harness,
                True,
                True,
                install_mode,
            )
        try:
            plan = json.loads(captured.getvalue())
        except json.JSONDecodeError:
            return planned_targets, LibraryError(
                f"Could not inspect planned targets for {dep_primitive}:{dep_name}"
            )
        if exit_code != 0:
            message = (
                plan.get("message")
                or plan.get("reason")
                or "Install planning failed"
            )
            return planned_targets, LibraryError(str(message))
        targets = plan.get("target_paths")
        if not isinstance(targets, list) or not targets:
            return planned_targets, LibraryError(
                f"Installer plan for {dep_primitive}:{dep_name} did not declare target_paths"
            )
        normalized_targets: list[str] = []
        for target in targets:
            try:
                normalized_targets.append(
                    validate_planned_project_target(target, repo_root)
                )
            except LibraryError as exc:
                return planned_targets, LibraryError(
                    f"Unsafe target for {dep_primitive}:{dep_name}: {exc}"
                )
        planned_targets[(dep_primitive, dep_name)] = normalized_targets

    if install_mode == "symlink":
        members = list(planned_targets.items())
        for (ancestor_member, ancestor_targets) in members:
            for ancestor in ancestor_targets:
                ancestor_path = Path(ancestor.rstrip("/"))
                for descendant_member, descendant_targets in members:
                    if descendant_member == ancestor_member:
                        continue
                    for descendant in descendant_targets:
                        descendant_path = Path(descendant.rstrip("/"))
                        nested_under_ancestor = (
                            descendant_path != ancestor_path
                            and descendant_path.is_relative_to(ancestor_path)
                        )
                        if nested_under_ancestor:
                            ancestor_label = ":".join(ancestor_member)
                            descendant_label = ":".join(descendant_member)
                            return planned_targets, LibraryError(
                                "Unsafe planned symlink ancestor interaction: "
                                f"{ancestor_label} target {ancestor} contains "
                                f"{descendant_label} target {descendant}"
                            )
    return planned_targets, None


def _revalidate_project_member_targets(
    repo_root: Path,
    primitive: str,
    name: str,
    targets: list[str],
) -> LibraryError | None:
    """Recheck one precomputed member plan against current filesystem state."""
    from lib.gitignore import validate_planned_project_target

    for target in targets:
        try:
            validate_planned_project_target(target, repo_root)
        except LibraryError as exc:
            return LibraryError(f"Unsafe target for {primitive}:{name}: {exc}")
    return None


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
        # The project form remains a narrow migration-only lock-record cleanup.
        if explicit_scope != "project":
            return _retired_mcp_lifecycle_result(json_mode=use_json)
        scope = "project"
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

    health = _repository_health(repo_root, offline=offline)
    health_states = {item.get("status") for item in health.values()}
    if "decision_required" in health_states:
        health_status = "decision_required"
        health_exit = EXIT_DECISION_REQUIRED
    elif "repair_available" in health_states or "missing" in health_states:
        health_status = "repair_available"
        health_exit = EXIT_DRIFT
    else:
        health_status = "healthy"
        health_exit = EXIT_SUCCESS

    status = (
        "repair_available"
        if health_status == "healthy" and overall == "behind"
        else health_status
    )
    combined_result = {
        "status": status,
        "entries": all_entries,
        "overall": status if status != "healthy" else overall,
        "upstream_overall": overall,
        "health": health,
    }
    if warnings:
        combined_result["warnings"] = warnings

    if use_json:
        print_json(combined_result)
    else:
        if health_status == "decision_required":
            print("Status: DECISION REQUIRED")
        elif status == "repair_available":
            print("Status: REPAIR AVAILABLE")
        elif overall == "current":
            print(f"Status: HEALTHY ({len(all_entries)} entries)")
        else:
            print(f"Status: UNKNOWN ({len(all_entries)} entries checked)")
        if overall == "behind":
            behind_count = sum(
                1 for e in all_entries if e.get("needs_refresh", e.get("behind"))
            )
            print(
                f"BEHIND ({behind_count}/{len(all_entries)} entries need update)"
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
        for warning in warnings:
            print(f"Warning: {warning}")

    if health_exit != EXIT_SUCCESS:
        return health_exit
    return EXIT_DRIFT if overall == "behind" else EXIT_SUCCESS


def _repository_health(
    repo_root: Path | None, *, offline: bool = False
) -> dict[str, dict]:
    """Inspect one repository without installing, adopting, or deleting content."""
    if repo_root is None:
        missing = {"status": "missing", "reason": "current directory is not a Git worktree"}
        return {
            "desired_state": missing,
            "projections": {"status": "not_applicable", "missing": [], "drifted": []},
            "git_hygiene": {"status": "repair_available", "reason": missing["reason"]},
            "bootstrap": _bootstrap_health(),
            "unmanaged_primitives": {"status": "not_applicable", "paths": []},
        }

    lock_path = repo_root / ".library.lock"
    if not lock_path.exists():
        return {
            "desired_state": {"status": "missing", "requested_roots": [], "receipts": 0},
            "projections": {"status": "clean", "missing": [], "drifted": []},
            "git_hygiene": {"status": "repair_available", "reason": ".library.lock is missing"},
            "bootstrap": _bootstrap_health(),
            "unmanaged_primitives": _unmanaged_primitive_health(repo_root, []),
        }

    try:
        lock = load_lockfile(lock_path)
        from lib.gitignore import BEGIN_MARKER, END_MARKER, managed_project_paths

        managed_paths = managed_project_paths(repo_root)
    except LibraryError as exc:
        return {
            "desired_state": {"status": "repair_available", "reason": str(exc)},
            "projections": {"status": "repair_available", "missing": [], "drifted": []},
            "git_hygiene": {"status": "repair_available", "reason": str(exc)},
            "bootstrap": _bootstrap_health(),
            "unmanaged_primitives": {"status": "not_applicable", "paths": []},
        }

    project_receipts = [
        receipt
        for receipt in lock.get("receipts", [])
        if isinstance(receipt, dict) and receipt.get("scope") == "project"
    ]
    receipt_paths = [
        str(target.get("path"))
        for receipt in project_receipts
        for target in receipt.get("targets", [])
        if isinstance(target, dict) and isinstance(target.get("path"), str)
    ]
    projection_missing, projection_drifted = _projection_health(repo_root, project_receipts)
    requested_ids = {
        str(root.get("id", ""))
        for root in lock.get("requested_roots", [])
        if isinstance(root, dict)
    }
    orphaned = sorted(
        str(receipt.get("id", ""))
        for receipt in project_receipts
        if not set(str(owner) for owner in receipt.get("owners_cache", [])) & requested_ids
    )
    resolution_blockers: list[str] = []
    try:
        from lib.workspace import build_workspace_plan

        status_catalog = _status_catalog(repo_root)
        fresh_plan = build_workspace_plan(
            catalog=status_catalog,
            lock=lock,
            repo_root=repo_root,
            scope="project",
            pin_verifier=_workspace_pin_verifier(status_catalog, offline=offline),
        )
        resolution_blockers = sorted(set(fresh_plan.get("blockers", [])))
    except (LibraryError, OSError) as exc:
        resolution_blockers = [str(exc)]
    gitignore = repo_root / ".gitignore"
    gitignore_content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    managed_entries = _managed_gitignore_entries(gitignore_content, BEGIN_MARKER, END_MARKER)
    from lib.gitignore import _escape_gitignore_path

    expected_entries = [f"/{_escape_gitignore_path(path)}" for path in managed_paths]
    stale_managed_paths = sorted(
        entry.removeprefix("/") for entry in managed_entries if entry not in expected_entries
    )
    missing_managed_paths = sorted(
        entry.removeprefix("/") for entry in expected_entries if entry not in managed_entries
    )
    tracked_managed_paths = _tracked_paths(repo_root, managed_paths)
    gitignore_clean = (
        managed_entries == expected_entries
        and not stale_managed_paths
        and not missing_managed_paths
    )
    projection_problem = bool(projection_missing or projection_drifted or orphaned)
    desired_problem = bool(orphaned or resolution_blockers)
    return {
        "desired_state": {
            "status": "repair_available" if desired_problem else "healthy",
            "requested_roots": [str(root.get("id", "")) for root in lock.get("requested_roots", [])],
            "receipts": len(lock.get("receipts", [])),
            "freshness": "stale" if resolution_blockers else "current",
            "resolution_blockers": resolution_blockers,
            "pending_reconciliation": projection_problem or bool(resolution_blockers),
        },
        "projections": {
            "status": "repair_available" if projection_problem else "clean",
            "missing": projection_missing,
            "drifted": projection_drifted,
            "conflicting": [],
            "orphaned": orphaned,
        },
        "git_hygiene": {
            "status": "clean" if gitignore_clean else "repair_available",
            "managed_paths": managed_paths,
            "missing_managed_paths": missing_managed_paths,
            "stale_managed_paths": stale_managed_paths,
            "tracked_managed_paths": tracked_managed_paths,
            "authoritative_lock": {"schema_version": lock.get("schema_version"), "tracked": _is_tracked(repo_root, ".library.lock")},
        },
        "bootstrap": _bootstrap_health(),
        "unmanaged_primitives": _unmanaged_primitive_health(repo_root, receipt_paths),
    }


def _status_catalog(repo_root: Path) -> dict:
    """Load the same repository-selected catalog that lifecycle status observes."""
    # A consumer repository owns desired state but does not carry the Library
    # catalog. Resolve its nearest catalog when present, otherwise use the
    # catalog bundled with the installed control plane.
    del repo_root
    catalog_root = _resolve_catalog_root()
    return load_catalog(catalog_root)


def _projection_health(repo_root: Path, receipts: list[dict]) -> tuple[list[str], list[str]]:
    """Return missing and tampered project targets from exact receipt evidence."""
    missing: list[str] = []
    drifted: list[str] = []
    for receipt in receipts:
        for target in receipt.get("targets", []):
            if not isinstance(target, dict) or not isinstance(target.get("path"), str):
                continue
            path_value = target["path"].rstrip("/")
            path = repo_root / path_value
            if not path.exists() and not path.is_symlink():
                missing.append(path_value)
                continue
            expected_digest = target.get("content_sha256")
            if expected_digest and path.is_file():
                actual_digest = sha256(path.read_bytes()).hexdigest()
                if actual_digest != expected_digest:
                    drifted.append(path_value)
            elif target.get("kind") == "symlink" and path.is_symlink():
                if target.get("link_target") != str(path.readlink()):
                    drifted.append(path_value)
    return sorted(set(missing)), sorted(set(drifted))


def _managed_gitignore_entries(content: str, begin_marker: str, end_marker: str) -> list[str]:
    """Read only the one well-formed managed block, without changing it."""
    lines = content.splitlines()
    if lines.count(begin_marker) != 1 or lines.count(end_marker) != 1:
        return []
    begin = lines.index(begin_marker)
    end = lines.index(end_marker)
    if end <= begin:
        return []
    return lines[begin + 1 : end]


def _tracked_paths(repo_root: Path, paths: list[str]) -> list[str]:
    """Return receipt-derived managed paths already present in the Git index."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", *paths],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted(item.decode(errors="surrogateescape") for item in result.stdout.split(b"\0") if item)


def _is_tracked(repo_root: Path, path: str) -> bool:
    """Return whether one repository-relative path is tracked by Git."""
    return subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
        check=False,
    ).returncode == 0


def _bootstrap_manifest_path(home: Path) -> Path:
    """Return the product-owned manifest for the bootstrap allowlist."""
    return home / ".config" / "library" / "bootstrap.json"


def _bootstrap_health(home: Path | None = None) -> dict[str, object]:
    """Report the exact bootstrap contract without treating it as desired state."""
    home = home or Path.home()
    manifest_path = _bootstrap_manifest_path(home)
    required_commands = ("library", "cld", "cdx")
    missing = [name for name in required_commands if shutil.which(name) is None]
    if not manifest_path.is_file():
        missing.append("bootstrap_manifest")
        return {"status": "repair_available", "missing": missing}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        missing.append("bootstrap_manifest")
        return {"status": "repair_available", "missing": missing}
    for key, record in (manifest.get("targets") or {}).items():
        if not _bootstrap_manifest_target_matches(record):
            missing.append(key)
    return {"status": "ready" if not missing else "repair_available", "missing": sorted(set(missing))}


def _bootstrap_paths(home: Path) -> dict[str, Path]:
    """Return every mutable target in the intentionally small bootstrap contract."""
    return {
        "agents_entrypoint": home / ".agents" / "AGENTS.md",
        "claude_entrypoint": home / ".claude" / "CLAUDE.md",
        "launcher_runtime": home / ".agents" / "orchestrator-config.yml",
        "openbrain_claude": home / ".claude.json",
        "openbrain_codex": home / ".codex" / "config.toml",
        "openbrain_pi": home / ".pi" / "settings.json",
    }


def _bootstrap_instruction_content() -> str:
    return "# Library bootstrap entrypoint\n\n@~/.agents/AGENTS.md\n"


def _bootstrap_agents_content() -> str:
    return "# Library bootstrap\n\nThis file is product bootstrap state, not Library desired state.\n"


def _bootstrap_runtime_content() -> str:
    return "# Product-owned launcher runtime configuration.\nversion: 1\n"


def _bootstrap_codex_content() -> str:
    return "[mcp_servers.open-brain]\nurl = \"https://open-brain.sussdorff.org/mcp\"\n"


def _bootstrap_openbrain_descriptor() -> dict[str, str]:
    """Return the stable HTTP descriptor shared by bootstrap MCP projections."""
    return {"type": "http", "url": "https://open-brain.sussdorff.org/mcp"}


def _bootstrap_openbrain_descriptor_matches(
    descriptor: object, *, require_type: bool
) -> bool:
    """Accept the stable OpenBrain descriptor and Library's migration receipt."""
    if not isinstance(descriptor, dict):
        return False
    expected = _bootstrap_openbrain_descriptor()
    if not require_type:
        expected = {"url": expected["url"]}
    normalized = {key: value for key, value in descriptor.items() if key != "_origin"}
    return normalized == expected


def _bootstrap_json_content(container_key: str) -> str:
    """Render a new JSON MCP config when no operator config exists."""
    return json.dumps(
        {container_key: {"open-brain": _bootstrap_openbrain_descriptor()}},
        indent=2,
    ) + "\n"


def _bootstrap_content() -> dict[str, str]:
    """Return exact initial content for every bootstrap-owned path."""
    return {
        "agents_entrypoint": _bootstrap_agents_content(),
        "claude_entrypoint": _bootstrap_instruction_content(),
        "launcher_runtime": _bootstrap_runtime_content(),
        "openbrain_claude": _bootstrap_json_content("mcpServers"),
        "openbrain_codex": _bootstrap_codex_content(),
        "openbrain_pi": _bootstrap_json_content("mcpServers"),
    }


def _bootstrap_merge_json_mcp(path: Path, container_key: str) -> bool:
    """Add OpenBrain to one JSON config without replacing operator-owned entries."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_bootstrap_json_content(container_key), encoding="utf-8")
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    entries = payload.setdefault(container_key, {})
    if not isinstance(entries, dict):
        return False
    descriptor = _bootstrap_openbrain_descriptor()
    existing = entries.get("open-brain")
    if existing is None:
        entries["open-brain"] = descriptor
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return True
    return _bootstrap_openbrain_descriptor_matches(existing, require_type=True)


def _bootstrap_json_mcp_is_compatible(path: Path, container_key: str) -> bool:
    """Return whether an existing JSON config can receive OpenBrain unchanged."""
    if not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    entries = payload.get(container_key)
    if entries is None:
        return True
    if not isinstance(entries, dict):
        return False
    existing = entries.get("open-brain")
    return existing is None or _bootstrap_openbrain_descriptor_matches(
        existing, require_type=True
    )


def _bootstrap_merge_codex_mcp(path: Path) -> bool:
    """Add OpenBrain to Codex TOML without replacing operator-owned config."""
    try:
        import tomlkit
    except ImportError:
        return False
    if path.exists():
        try:
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
        except (OSError, tomlkit.exceptions.ParseError):
            return False
    else:
        document = tomlkit.document()
    servers = document.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table()
        document["mcp_servers"] = servers
    existing = servers.get("open-brain")
    if existing is not None:
        return _bootstrap_openbrain_descriptor_matches(existing, require_type=False)
    entry = tomlkit.table()
    entry["url"] = "https://open-brain.sussdorff.org/mcp"
    servers["open-brain"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(document), encoding="utf-8")
    return True


def _bootstrap_codex_mcp_is_compatible(path: Path) -> bool:
    """Return whether an existing Codex config can receive OpenBrain unchanged."""
    if not path.exists():
        return True
    try:
        import tomlkit
    except ImportError:
        return False
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.ParseError):
        return False
    servers = document.get("mcp_servers")
    if servers is None:
        return True
    if not isinstance(servers, dict):
        return False
    existing = servers.get("open-brain")
    return existing is None or _bootstrap_openbrain_descriptor_matches(
        existing, require_type=False
    )


def _bootstrap_manifest_target_matches(record: dict[str, object]) -> bool:
    """Return whether one manifest target still has its bootstrap-owned state."""
    path = Path(str(record.get("path") or ""))
    kind = str(record.get("kind") or "file")
    if not path.is_file():
        return False
    if kind == "operator_file":
        key = str(record.get("contract") or "")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return False
        if key == "agents_entrypoint":
            return bool(content.strip())
        if key == "claude_entrypoint":
            return "@~/.agents/AGENTS.md" in content
        if key == "launcher_runtime":
            try:
                import yaml

                parsed = yaml.safe_load(content)
            except yaml.YAMLError:
                return False
            return isinstance(parsed, dict) and bool(parsed)
        return False
    if kind == "file":
        return sha256(path.read_bytes()).hexdigest() == str(record.get("sha256") or "")
    if kind == "json_mcp":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        entries = payload.get(str(record.get("container") or ""), {})
        return isinstance(entries, dict) and _bootstrap_openbrain_descriptor_matches(
            entries.get("open-brain"), require_type=True
        )
    if kind == "toml_mcp":
        try:
            import tomlkit
        except ImportError:
            return False
        try:
            payload = tomlkit.parse(path.read_text(encoding="utf-8"))
        except (OSError, tomlkit.exceptions.ParseError):
            return False
        entries = payload.get("mcp_servers", {})
        return isinstance(entries, dict) and _bootstrap_openbrain_descriptor_matches(
            entries.get("open-brain"), require_type=False
        )
    return False


def _bootstrap_install_conflicts(paths: dict[str, Path]) -> list[str]:
    """Preflight every bootstrap target before writing any target."""
    conflicts: list[str] = []
    for key in ("agents_entrypoint", "claude_entrypoint", "launcher_runtime"):
        path = paths[key]
        if path.exists() and not path.is_file():
            conflicts.append(key)
    if not _bootstrap_json_mcp_is_compatible(paths["openbrain_claude"], "mcpServers"):
        conflicts.append("openbrain_claude")
    if not _bootstrap_codex_mcp_is_compatible(paths["openbrain_codex"]):
        conflicts.append("openbrain_codex")
    if not _bootstrap_json_mcp_is_compatible(paths["openbrain_pi"], "mcpServers"):
        conflicts.append("openbrain_pi")
    return conflicts


def _write_bootstrap_manifest(home: Path, paths: dict[str, Path]) -> Path:
    """Persist exact byte receipts for targets safely created by bootstrap."""
    manifest_path = _bootstrap_manifest_path(home)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    targets: dict[str, dict[str, str]] = {}
    for key, path in paths.items():
        if key == "openbrain_claude":
            targets[key] = {"path": str(path), "kind": "json_mcp", "container": "mcpServers"}
        elif key == "openbrain_pi":
            targets[key] = {"path": str(path), "kind": "json_mcp", "container": "mcpServers"}
        elif key == "openbrain_codex":
            targets[key] = {"path": str(path), "kind": "toml_mcp"}
        elif key in {"agents_entrypoint", "claude_entrypoint", "launcher_runtime"}:
            targets[key] = {
                "path": str(path),
                "kind": "operator_file",
                "contract": key,
            }
        else:
            targets[key] = {
                "path": str(path),
                "kind": "file",
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "targets": targets}, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _cutover_prerequisites(
    repository_paths: list[Path], fleet_manifest_path: Path
) -> dict[str, object]:
    """Inspect every machine and repository prerequisite without mutating state."""
    from lib.global_skill_cutover import (
        inspect_repositories,
        inspect_source_registry,
        load_approved_fleet,
    )

    bootstrap_health = _bootstrap_health(Path.home())
    if bootstrap_health["status"] != "ready":
        return {
            "status": "blocked",
            "stage": "bootstrap",
            "bootstrap": bootstrap_health,
            "repositories": [],
        }

    try:
        fleet = load_approved_fleet(fleet_manifest_path)
    except LibraryError as exc:
        return {
            "status": "blocked",
            "stage": "fleet-approval",
            "reason": str(exc),
            "repositories": [],
        }
    supplied = [str(path.expanduser().resolve()) for path in repository_paths]
    approved_entries = fleet["repositories"]
    approved_paths = [str(item["path"]) for item in approved_entries]
    missing_approved = sorted(set(approved_paths) - set(supplied))
    unapproved = sorted(set(supplied) - set(approved_paths))
    if (
        missing_approved
        or unapproved
        or len(supplied) != len(set(supplied))
        or len(supplied) != len(approved_paths)
    ):
        return {
            "status": "blocked",
            "stage": "fleet-approval",
            "fleet_manifest": fleet,
            "missing_approved_repositories": missing_approved,
            "unapproved_repositories": unapproved,
            "repositories": [],
        }
    approvals = {str(item["path"]): item for item in approved_entries}
    repositories = inspect_repositories(repository_paths, approvals=approvals)
    if any(item["status"] != "ready" for item in repositories):
        return {
            "status": "blocked",
            "stage": "repository-health",
            "repositories": repositories,
        }

    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    ).expanduser()
    source_registry = inspect_source_registry(config_home)
    if source_registry["status"] != "ready":
        return {
            "status": "blocked",
            "stage": "catalog-sources",
            "catalog_sources": source_registry,
            "repositories": repositories,
        }

    catalog_root = _resolve_catalog_root()
    catalog = load_catalog(catalog_root)
    skill_entries = get_entries(catalog, "skill")
    skill_names = [str(entry.get("name") or "") for entry in skill_entries]
    catalog_skill_count = len(set(skill_names))
    if (
        len(skill_entries) != 110
        or catalog_skill_count != 110
        or any(not name for name in skill_names)
    ):
        return {
            "status": "blocked",
            "stage": "catalog",
            "catalog_skill_count": catalog_skill_count,
            "catalog_skill_entries": len(skill_entries),
            "repositories": repositories,
        }

    for item in repositories:
        repository = Path(item["path"])
        lock = load_lockfile(repository / ".library.lock")
        has_default_workspace = any(
            root.get("type") == "workspace"
            and root.get("name") == "cognovis-base"
            and root.get("scope", "project") == "project"
            for root in lock.get("requested_roots", [])
            if isinstance(root, dict)
        )
        workspace_catalog = _select_workspace_catalog(
            argparse.Namespace(reference="cognovis-base", verb="status"),
            repo_root=repository,
            catalog_root=catalog_root,
            catalog=catalog,
        )
        workspace_output = io.StringIO()
        with redirect_stdout(workspace_output):
            workspace_exit = _workspace_status(
                argparse.Namespace(
                    reference="cognovis-base",
                    scope="project",
                    target_project=repository,
                    harness="all",
                    all_workspaces=False,
                    json=True,
                ),
                repository,
                workspace_catalog,
            )
        workspace_result = json.loads(workspace_output.getvalue())
        health = _repository_health(repository)
        health_problem = next(
            (
                (name, state)
                for name, state in health.items()
                if state.get("status")
                not in {"healthy", "clean", "ready", "not_applicable"}
            ),
            None,
        )
        if not has_default_workspace:
            item["status"] = "blocked"
            item["reason"] = "cognovis-base is not registered"
        elif workspace_exit != EXIT_SUCCESS:
            item["status"] = "blocked"
            item["reason"] = (
                "cognovis-base Workspace status is "
                f"{workspace_result.get('status', 'blocked')}"
            )
        elif health["git_hygiene"].get("tracked_managed_paths"):
            item["status"] = "blocked"
            item["reason"] = "Library-managed projection targets are tracked by Git"
        elif health_problem is not None:
            name, state = health_problem
            item["status"] = "blocked"
            item["reason"] = str(
                state.get("reason") or f"repository {name} is {state.get('status')}"
            )
        else:
            item["workspace_status"] = str(workspace_result["status"])
            item["repository_status"] = "healthy"

    if any(item["status"] != "ready" for item in repositories):
        return {
            "status": "blocked",
            "stage": "repository-health",
            "repositories": repositories,
        }
    return {
        "status": "ready",
        "stage": "ready",
        "repositories": repositories,
        "catalog_sources": source_registry,
        "catalog_skill_count": catalog_skill_count,
        "fleet_manifest": fleet,
    }


def _cutover_prerequisite_error(payload: dict[str, object]) -> str:
    """Render one stable transaction-boundary prerequisite failure."""
    stage = str(payload.get("stage") or "unknown")
    details = [
        f"{item.get('path')}: {item.get('reason')}"
        for item in payload.get("repositories", [])
        if isinstance(item, dict) and item.get("status") != "ready"
    ]
    if not details:
        missing = payload.get("missing_approved_repositories") or []
        unapproved = payload.get("unapproved_repositories") or []
        if missing:
            details.append("missing approved repositories: " + ", ".join(missing))
        if unapproved:
            details.append("unapproved repositories: " + ", ".join(unapproved))
    if not details:
        details.append(
            str(
                payload.get("reason")
                or payload.get("catalog_sources")
                or payload.get("bootstrap")
                or stage
            )
        )
    return f"Cutover prerequisites changed at {stage}: " + "; ".join(details)


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Provision only the ADR-0012 bootstrap allowlist under the current HOME."""
    if args.verb == "cutover-skills":
        from lib.global_skill_cutover import (
            execute_cutover,
            inspect_skill_receipts,
            load_cutover_lock,
        )

        prerequisites = _cutover_prerequisites(
            list(args.repository), args.fleet_manifest
        )
        if prerequisites["status"] != "ready":
            if getattr(args, "json", False):
                print_json(prerequisites)
            else:
                print("Global Skill cutover: BLOCKED")
                if prerequisites.get("reason"):
                    print(f"  {prerequisites['reason']}")
                for path in prerequisites.get("missing_approved_repositories", []):
                    print(f"  missing approved repository: {path}")
                for path in prerequisites.get("unapproved_repositories", []):
                    print(f"  unapproved repository: {path}")
                for item in prerequisites.get("repositories", []):
                    if item.get("status") == "ready":
                        continue
                    print(f"  {item['path']}: {item['reason']}")
            return EXIT_DRIFT

        repositories = prerequisites["repositories"]
        source_registry = prerequisites["catalog_sources"]
        catalog_skill_count = prerequisites["catalog_skill_count"]
        fleet_manifest = prerequisites["fleet_manifest"]
        global_lock_path = find_lockfile(global_scope=True)
        lock = load_cutover_lock(global_lock_path)
        skills = inspect_skill_receipts(lock, Path.home())
        blocked_skills = [item for item in skills if item["status"] != "ready"]
        if blocked_skills:
            payload = {
                "status": "blocked",
                "stage": "receipt-ownership",
                "repositories": repositories,
                "skills": skills,
            }
            if getattr(args, "json", False):
                print_json(payload)
            else:
                print("Global Skill cutover: BLOCKED")
                for item in blocked_skills:
                    print(f"  {item['id']}: {item['reason']}")
            return EXIT_DRIFT
        if not getattr(args, "apply", False):
            payload = {
                "status": "dry-run",
                "stage": "ready",
                "repositories": repositories,
                "skills": skills,
                "catalog_skill_count": catalog_skill_count,
                "catalog_sources": source_registry,
                "fleet_manifest": fleet_manifest,
                "backup": str(args.backup.expanduser().resolve()),
            }
            if getattr(args, "json", False):
                print_json(payload)
            else:
                print("Global Skill cutover: READY")
            return EXIT_SUCCESS

        latest_prerequisites = prerequisites
        approved_fleet_sha = str(fleet_manifest["sha256"])

        def recheck_cutover_prerequisites() -> None:
            nonlocal latest_prerequisites
            latest_prerequisites = _cutover_prerequisites(
                list(args.repository), args.fleet_manifest
            )
            if latest_prerequisites["status"] != "ready":
                raise LibraryError(_cutover_prerequisite_error(latest_prerequisites))
            latest_fleet = latest_prerequisites["fleet_manifest"]
            if str(latest_fleet["sha256"]) != approved_fleet_sha:
                raise LibraryError(
                    "Approved fleet manifest changed after cutover preflight"
                )

        try:
            cutover = execute_cutover(
                lock_path=global_lock_path,
                home=Path.home(),
                backup=args.backup,
                preflight=recheck_cutover_prerequisites,
            )
        except LibraryError as exc:
            payload = {
                "status": "blocked",
                "stage": "transaction",
                "message": str(exc),
                "repositories": repositories,
                "skills": skills,
            }
            if getattr(args, "json", False):
                print_json(payload)
            else:
                print(f"Global Skill cutover: BLOCKED\n  {exc}")
            return EXIT_DRIFT
        repositories = latest_prerequisites["repositories"]
        source_registry = latest_prerequisites["catalog_sources"]
        catalog_skill_count = latest_prerequisites["catalog_skill_count"]
        fleet_manifest = latest_prerequisites["fleet_manifest"]
        payload = {
            "status": "ok",
            "stage": "complete",
            "repositories": repositories,
            "skills": skills,
            "catalog_skill_count": catalog_skill_count,
            "catalog_sources": source_registry,
            "fleet_manifest": fleet_manifest,
            **cutover,
        }
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print("Global Skill cutover: COMPLETE")
        return EXIT_SUCCESS

    home = Path.home()
    paths = _bootstrap_paths(home)
    content = _bootstrap_content()
    conflicts: list[str] = []
    if args.verb == "install":
        conflicts = _bootstrap_install_conflicts(paths)
        if conflicts:
            payload = {
                "status": "repair_available",
                "bootstrap": {key: str(path) for key, path in paths.items()},
                "conflicts": conflicts,
                "missing": [],
            }
            if getattr(args, "json", False):
                print_json(payload)
            else:
                print("Bootstrap: REPAIR AVAILABLE")
                for key in conflicts:
                    print(f"  conflict: {key}")
            return EXIT_DRIFT
        for key in ("agents_entrypoint", "claude_entrypoint", "launcher_runtime"):
            path = paths[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content[key], encoding="utf-8")
        _bootstrap_merge_json_mcp(paths["openbrain_claude"], "mcpServers")
        _bootstrap_merge_codex_mcp(paths["openbrain_codex"])
        _bootstrap_merge_json_mcp(paths["openbrain_pi"], "mcpServers")
        _write_bootstrap_manifest(home, paths)
    elif args.verb == "status":
        health = _bootstrap_health(home)
        payload = {
            "status": health["status"],
            "bootstrap": health,
            "bootstrap_targets": {key: str(path) for key, path in paths.items()},
            "missing": health["missing"],
            "conflicts": [],
        }
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print("Bootstrap: " + ("READY" if health["status"] == "ready" else "REPAIR AVAILABLE"))
            for key in health["missing"]:
                print(f"  missing: {key}")
        return EXIT_SUCCESS if health["status"] == "ready" else EXIT_DRIFT
    elif args.verb == "remove":
        manifest_path = _bootstrap_manifest_path(home)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            conflicts.append("bootstrap_manifest")
        else:
            for key, record in (manifest.get("targets") or {}).items():
                if not _bootstrap_manifest_target_matches(record):
                    conflicts.append(str(key))
            if not conflicts:
                for record in (manifest.get("targets") or {}).values():
                    path = Path(str(record["path"]))
                    kind = str(record.get("kind") or "file")
                    if kind == "file":
                        path.unlink()
                    elif kind == "operator_file":
                        # These bootstrap entrypoints are operator-authored state
                        # once created, so product cleanup never deletes them.
                        continue
                    elif kind == "json_mcp":
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        entries = payload.get(str(record["container"]), {})
                        if _bootstrap_openbrain_descriptor_matches(
                            entries.get("open-brain"), require_type=True
                        ):
                            del entries["open-brain"]
                            if not entries:
                                payload.pop(str(record["container"]), None)
                            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    elif kind == "toml_mcp":
                        import tomlkit

                        payload = tomlkit.parse(path.read_text(encoding="utf-8"))
                        entries = payload.get("mcp_servers", {})
                        if _bootstrap_openbrain_descriptor_matches(
                            entries.get("open-brain"), require_type=False
                        ):
                            del entries["open-brain"]
                            if not entries:
                                del payload["mcp_servers"]
                            path.write_text(tomlkit.dumps(payload), encoding="utf-8")
                manifest_path.unlink()
    missing = [] if args.verb == "remove" and not conflicts else [
        key for key, path in paths.items() if not path.is_file()
    ]
    payload = {
        "status": "ok" if not missing and not conflicts else "repair_available",
        "bootstrap": {key: str(path) for key, path in paths.items()},
        "missing": missing,
        "conflicts": conflicts,
    }
    if getattr(args, "json", False):
        print_json(payload)
    else:
        print("Bootstrap: " + ("READY" if not missing else "REPAIR AVAILABLE"))
        for key, path in paths.items():
            print(f"  {key}: {path}")
    return EXIT_SUCCESS if not missing and not conflicts else EXIT_DRIFT


def _unmanaged_primitive_health(repo_root: Path, receipt_paths: list[str]) -> dict[str, object]:
    """List supported-harness content not owned by a project receipt."""
    owned = [Path(path.rstrip("/")) for path in receipt_paths]
    file_targets = (
        (repo_root / ".agents" / "skills", "**/SKILL.md"),
        (repo_root / ".claude" / "skills", "**/SKILL.md"),
        (repo_root / ".claude" / "agents", "**/*.md"),
        (repo_root / ".codex" / "agents", "**/*.toml"),
        (repo_root / ".claude" / "commands", "**/*.md"),
        (repo_root / ".agents" / "scripts", "**/*.py"),
        (repo_root / ".agents" / "model-standards", "**/*.md"),
        (repo_root / ".agents" / "agent-bases", "**/*.md"),
    )
    bundle_roots = (
        repo_root / ".agents" / "standards",
        repo_root / ".claude" / "hooks",
        repo_root / ".codex" / "hooks",
        repo_root / ".claude" / "workflows",
        repo_root / ".agents" / "pi" / "extensions",
        repo_root / ".agents" / "pi" / "profiles",
        repo_root / ".agents" / "just",
    )

    def is_owned_or_tracked(relative: Path, target: Path) -> bool:
        if any(
            relative.is_relative_to(path) or path.is_relative_to(relative)
            for path in owned
        ):
            return True
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--", str(relative)],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.rstrip(b"\0"))

    found: set[str] = set()
    for base, pattern in file_targets:
        if not base.exists():
            continue
        for target in base.glob(pattern):
            if not target.is_file():
                continue
            relative = target.relative_to(repo_root)
            if not is_owned_or_tracked(relative, target):
                found.add(relative.as_posix())
    for root in bundle_roots:
        if not root.is_dir():
            continue
        for target in root.iterdir():
            if not target.is_file() and not target.is_dir():
                continue
            relative = target.relative_to(repo_root)
            if is_owned_or_tracked(relative, target):
                continue
            rendered = relative.as_posix()
            found.add(rendered + "/" if target.is_dir() else rendered)
    return {"status": "decision_required" if found else "clean", "paths": sorted(found)}


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
    # The admission axis is deferred to the cache transaction, which digests the
    # bytes it will write, consults the operator's durable ledger, and refuses
    # with the exact remedy command. Every other axis is judged here, as before.
    decision = evaluate_item(item, context, admission_pending_is_blocking=False)
    if decision.admission_state != "installable":
        # Every applicable explanation, not the first one. These used to be a
        # fallback for "no block reason was recorded", which was correct while
        # only one thing could be wrong at a time. Since `CL-lt51` an unpromoted
        # item also carries the deferred admission reason, and a diagnostic that
        # named only the admission would send the operator to record a decision
        # that still would not install the item.
        reasons = [reason.describe() for reason in decision.block_reasons]
        maturity = str(item.classification.get("maturity") or "stable")
        if not context.admits_maturity(maturity):
            reasons.append(
                f"maturity {maturity!r} is not promoted by this scope; promoting it "
                f"is an explicit decision (admitted maturities: "
                f"{list(context.admitted_maturities)})"
            )
        elif is_unclassified(item.library_type):
            reasons.append(
                "the member fits no existing Library primitive type, so there is "
                "no type to install it as; it is listed, not installable"
            )
        elif not reasons:
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


# -- foreign update admission (ADR-0011, CL-lt51) -----------------------------


def _update_store(repo_root: Path | None):
    from lib.providers.update_admission import UpdatePacketStore

    return UpdatePacketStore(_foreign_state(repo_root).update_root())


def _update_candidates(provider, result, args) -> list:
    """Which items this update fetches.

    The default is every item this provider already has a pin for, because an
    update is about content the operator already holds. `--item` narrows it, and
    an explicitly named item with no pin is a legitimate first import.
    """
    inventory = list(result.inventory)
    by_upstream = {item.upstream_id: item for item in inventory}
    requested = getattr(args, "upstream_ids", None)
    if requested:
        missing = [value for value in requested if value not in by_upstream]
        if missing:
            raise LibraryError(
                f"{provider.identity()} does not list these items: {sorted(missing)}"
            )
        return [by_upstream[value] for value in requested]

    state = _foreign_state(getattr(args, "_repo_root", None))
    pinned = {pin.qualified_identity for pin in state.pin_store().pins()}
    candidates = [item for item in inventory if item.qualified_identity() in pinned]
    if not candidates:
        raise LibraryError(
            f"No item from {provider.identity()} is pinned in this scope, so there "
            "is nothing to update. Name the items to import for the first time with "
            "--item <upstream id>, or install one through `library marketplace "
            "install` first."
        )
    return candidates


def _review_stage(args, repo_root: Path | None):
    """The review stage this update runs, from the operator's flags."""
    import json as _json

    from lib.providers.update_review_acpx import (
        DEFAULT_AGENT,
        DEFAULT_MODEL,
        acpx_review,
        recorded_review,
    )

    verdict_file = getattr(args, "review_verdict_file", None)
    if verdict_file is not None:
        return recorded_review(_json.loads(Path(verdict_file).read_text(encoding="utf-8")))
    state = _foreign_state(repo_root)
    # No workspace is passed: the reviewer of unadmitted foreign instructions runs
    # powerless and in an empty directory the dispatcher allocates. See
    # `update_review_acpx.REVIEW_PERMISSIONS`.
    return acpx_review(
        artifacts=state.update_root() / "review-artifacts",
        agent=getattr(args, "review_agent", None) or DEFAULT_AGENT,
        model=getattr(args, "review_model", None) or DEFAULT_MODEL,
    )


def _packet_payload(packet, *, content: bool = False, contents=None) -> dict:
    payload = packet.to_dict()
    if content and contents is not None:
        payload["content"] = {
            identity: {
                path: value.decode("utf-8", errors="replace")
                for path, value in sorted(files.items())
            }
            for identity, files in sorted(contents.items())
        }
    return payload


def _print_packet(packet, *, contents=None, show_content: bool = False) -> None:
    print(f"Update packet {packet.packet_id}")
    print(f"  source: {packet.provider_identity}")
    print(f"  observed: {packet.change_set.observed_at}")
    print(f"  change set: {packet.change_set.digest()}")
    if not packet.change_set.items:
        print("  nothing changed against the admitted baseline")
    for item in packet.change_set.items:
        markers = packet.scans.get(item.qualified_identity)
        rendered = (
            ", ".join(f"{name} x{count}" for name, count in sorted(markers.counts().items()))
            if markers is not None and markers.counts()
            else "no risk markers"
        )
        print(
            f"  {item.change:>8}  {item.qualified_identity} "
            f"({item.byte_size} bytes, {len(item.content or {})} member(s)) — {rendered}"
        )
    if packet.review is not None:
        print(f"  reviewer: {packet.review.reviewer} answered {packet.review.verdict!r}")
        print(f"    {packet.review.summary}")
        for finding in packet.review.findings:
            print(f"    [{finding.severity}] {finding.identifier}: {finding.detail}")
    else:
        print(f"  reviewer: no verdict — {packet.review_unavailable_detail}")
    print(f"  recommendation: {packet.recommendation}")
    print(f"    {packet.recommendation_basis}")
    print(
        "  The recommendation is advice. Nothing is adopted until you decide, and "
        "the scanner reduces risk rather than detecting intent."
    )
    print("  Approve:")
    print(f"    {packet.approval_command()}")
    print("  Decline:")
    print(f"    {packet.rejection_command()}")
    if show_content and contents:
        for identity, files in sorted(contents.items()):
            for path, value in sorted(files.items()):
                print(f"\n----- {identity} :: {path} -----")
                print(value.decode("utf-8", errors="replace"))


def cmd_marketplace_update(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
    """Fetch, quarantine, scan, review, and summarize. Adopt nothing."""
    from lib.providers.update_admission import UpdateFetchFailed, prepare_update
    from lib.providers.wiring import marketplace_inventory

    entry = _marketplace_entry(catalog, args.name)
    provider, result = marketplace_inventory(entry, selector=args.selector)
    setattr(args, "_repo_root", repo_root)
    items = _update_candidates(provider, result, args)

    try:
        packet = prepare_update(
            provider=provider,
            items=items,
            state=_foreign_state(repo_root),
            review=_review_stage(args, repo_root),
            observed_at=_utc_now(),
        )
    except UpdateFetchFailed as exc:
        raise LibraryError(str(exc), exit_code=3) from exc

    if args.json:
        print_json(success(_packet_payload(packet)))
        return EXIT_SUCCESS
    _print_packet(packet)
    return EXIT_SUCCESS


def cmd_marketplace_update_show(args: argparse.Namespace, repo_root: Path | None) -> int:
    store = _update_store(repo_root)
    try:
        packet, contents = store.load(args.packet_id)
    except KeyError as exc:
        raise LibraryError(str(exc), exit_code=3) from exc
    decisions = store.decisions(args.packet_id)
    if args.json:
        payload = _packet_payload(packet, content=args.content, contents=contents)
        payload["decisions"] = list(decisions)
        print_json(success(payload))
        return EXIT_SUCCESS
    _print_packet(packet, contents=contents, show_content=args.content)
    for row in decisions:
        print(
            f"  decided: {row['decision']} by {row['operator']} at {row['decided_at']}"
        )
    return EXIT_SUCCESS


def cmd_marketplace_update_list(args: argparse.Namespace, repo_root: Path | None) -> int:
    store = _update_store(repo_root)
    rows = []
    for packet_id in store.packet_ids():
        packet, _ = store.load(packet_id)
        decisions = store.decisions(packet_id)
        rows.append(
            {
                "packet_id": packet_id,
                "provider_identity": packet.provider_identity,
                "created_at": packet.created_at,
                "changed_items": len(packet.change_set.items),
                "recommendation": packet.recommendation,
                "review_status": packet.review_status,
                "decision": decisions[-1]["decision"] if decisions else None,
            }
        )
    if args.json:
        print_json(success({"packets": rows}))
        return EXIT_SUCCESS
    if not rows:
        print("No update packets in the quarantine.")
        return EXIT_SUCCESS
    for row in rows:
        state = row["decision"] or "undecided"
        print(
            f"{row['packet_id']}: {row['changed_items']} changed item(s), "
            f"recommends {row['recommendation']}, {state}"
        )
    return EXIT_SUCCESS


def cmd_marketplace_update_approve(
    args: argparse.Namespace, repo_root: Path | None, catalog: dict
) -> int:
    """Raise the pin, record the decision, and project. The human transition."""
    from lib.providers.rights import RightsPresentation
    from lib.providers.update_admission import approve_packet
    from lib.providers.wiring import marketplace_inventory, resolution_observations

    store = _update_store(repo_root)
    try:
        packet, _ = store.load(args.packet_id)
    except KeyError as exc:
        raise LibraryError(str(exc), exit_code=3) from exc

    entry = None
    from lib.catalog import get_marketplaces

    for candidate in get_marketplaces(catalog):
        if isinstance(candidate, dict) and candidate.get("source") == packet.provider_identity:
            entry = candidate
            break
        if isinstance(candidate, dict) and candidate.get("name") == packet.provider_identity:
            entry = candidate
            break
    if entry is None:
        raise LibraryError(
            f"No registered marketplace serves {packet.provider_identity}; approving "
            "an update needs its provider, because raising a pin requires a current "
            "observation of the source that stands behind the bytes."
        )
    provider, result = marketplace_inventory(entry)
    items = {item.qualified_identity(): item for item in result.inventory}

    shown: list[str] = []

    def present(presentation: RightsPresentation):
        shown.append(presentation.statement)
        print(presentation.statement)
        if not args.accept_rights:
            raise LibraryError(
                "This target requires an explicit operator opt-in for the rights "
                "state shown above. Re-run with --accept-rights to accept it.",
                exit_code=3,
            )
        return presentation.acknowledge(
            operator=args.operator, acknowledged_at=_utc_now()
        )

    default_root = (repo_root or Path.cwd()) / ".agents" / "foreign"
    target_root = Path(args.target_root).expanduser() if args.target_root else default_root

    try:
        outcome = approve_packet(
            packet_id=args.packet_id,
            state=_foreign_state(repo_root),
            items=items,
            operator=args.operator,
            reason=args.reason,
            availability=resolution_observations([provider]),
            decided_at=_utc_now(),
            target=args.target,
            target_root=target_root,
            scope=args.scope,
            selected=tuple(args.selected) if args.selected else None,
            against_recommendation=bool(args.against_recommendation),
            present=present,
        )
    except ValueError as exc:
        raise LibraryError(str(exc), exit_code=3) from exc

    payload = {
        "packet_id": outcome.packet_id,
        "approved": list(outcome.approved),
        "declined": list(outcome.declined),
        "receipts": list(outcome.receipts),
        "decision": dict(outcome.decision),
        "rights_statement_shown": bool(shown),
    }
    if args.json:
        print_json(success(payload))
        return EXIT_SUCCESS
    print(f"Approved {len(outcome.approved)} item(s) from {outcome.packet_id}")
    for identity in outcome.approved:
        print(f"  adopted: {identity}")
    for identity in outcome.declined:
        print(f"  left as it was: {identity}")
    return EXIT_SUCCESS


def cmd_marketplace_update_reject(args: argparse.Namespace, repo_root: Path | None) -> int:
    from lib.providers.update_admission import reject_packet

    try:
        row = reject_packet(
            packet_id=args.packet_id,
            state=_foreign_state(repo_root),
            operator=args.operator,
            reason=args.reason,
            decided_at=_utc_now(),
        )
    except (KeyError, ValueError) as exc:
        raise LibraryError(str(exc), exit_code=3) from exc
    if args.json:
        print_json(success({"decision": row}))
        return EXIT_SUCCESS
    print(f"Declined {args.packet_id}.")
    print("  Pins, admission decisions, and projected bytes are unchanged.")
    return EXIT_SUCCESS


# -- executable admission (ADR-0011, CL-2wqz) ---------------------------------


def _admission_row(record: dict) -> dict:
    """One decision as an operator reads it.

    `reviewer` and `evidence` are the ledger's field names, from the ADR's
    "reviewer identity and recorded evidence". At the CLI they are the operator
    and the reason they gave, and calling them that here is the difference
    between an audit line somebody understands and one they skim.
    """
    return {
        "qualified_identity": record["qualified_identity"],
        "content_digest": record["content_digest"],
        "state": record["state"],
        "operator": record["reviewer"],
        "reason": record["evidence"],
        "permission_surface": list(record["permission_surface"]),
        "decided_at": record["decided_at"],
        "superseded": bool(record.get("superseded", False)),
    }


def _admission_store(args: argparse.Namespace):
    """The durable decision store, located without loading a catalog.

    An admission decision is about bytes this machine already holds, so it needs
    no catalog, no network, and no provider. Requiring one would make the remedy
    for a refused install depend on more working infrastructure than the install
    itself.
    """
    return _foreign_state(_resolve_lifecycle_project_root(args)).admission_ledger_store()


def _admission_subject(args: argparse.Namespace) -> tuple[str, str, str, str | None]:
    """Resolve which bytes this decision is about, from a digest or a receipt.

    Returns `(identity, digest, library_type, resolved_from)`. A `--receipt`
    reference is resolved here and the caller displays what it resolved to
    **before** the write, because a name reference that quietly binds different
    bytes than the operator had in mind is the exact failure digest-binding
    exists to prevent.
    """
    from lib.providers.executable_admission import validated_digest

    if args.receipt:
        if args.identity or args.library_type:
            raise LibraryError(
                "--receipt already names the identity and type of the bytes it "
                "resolves; pass --digest instead to decide about different ones",
                exit_code=3,
            )
        state = _foreign_state(_resolve_lifecycle_project_root(args))
        receipt = state.receipt_store(args.scope).get(args.receipt)
        if receipt is None:
            raise LibraryError(
                f"no foreign receipt {args.receipt!r} in the {args.scope} scope; a "
                "decision is never recorded against a reference nothing resolves",
                exit_code=3,
            )
        return (
            receipt.qualified_identity(),
            receipt.projected_content_digest,
            receipt.library_type,
            receipt.id,
        )
    if not args.identity or not args.library_type:
        raise LibraryError(
            "--digest needs the --identity and --type of the artifact it belongs "
            "to; a digest alone does not say what the bytes are",
            exit_code=3,
        )
    try:
        digest = validated_digest(args.digest)
    except ValueError as exc:
        raise LibraryError(str(exc), exit_code=3) from exc
    return args.identity, digest, args.library_type, None


def cmd_admission_decide(args: argparse.Namespace, state_name: str) -> int:
    """Record one grant or one denial, about exactly one set of bytes."""
    from lib.providers.executable_admission import (
        ADMITTED,
        InertContentNotAdmissible,
        REFUSED,
    )

    identity, digest, library_type, resolved_from = _admission_subject(args)
    permissions = list(args.permissions or [])
    if state_name == ADMITTED and not permissions and not args.no_permissions:
        raise LibraryError(
            "a grant states the permission surface the artifact requests; pass "
            "--permission for each one, or --no-permissions to state that it "
            "requests none. An unstated surface is not the same claim as an "
            "empty one",
            exit_code=3,
        )
    if permissions and args.no_permissions:
        raise LibraryError(
            "--no-permissions states that this artifact requests none, which "
            "contradicts the --permission entries given with it",
            exit_code=3,
        )

    if resolved_from is not None and not args.json:
        # Shown before the write, never reported after it.
        print(f"Resolved {resolved_from} to:")
        print(f"  identity: {identity}")
        print(f"  type:     {library_type}")
        print(f"  digest:   {digest}")

    try:
        record = _admission_store(args).decide(
            state_name,
            identity,
            digest,
            library_type=library_type,
            reviewer=args.operator,
            permission_surface=tuple(permissions),
            decided_at=_utc_now(),
            evidence=args.reason,
            supersedes=args.supersede,
        )
    except InertContentNotAdmissible as exc:
        raise LibraryError(str(exc), exit_code=3) from exc
    except ValueError as exc:
        raise LibraryError(str(exc), exit_code=3) from exc

    row = _admission_row(record.to_dict())
    if args.json:
        print_json(
            success({"decision": row, "resolved_from": resolved_from})
        )
        return EXIT_SUCCESS
    verb = "Admitted" if state_name == ADMITTED else "Refused"
    print(f"{verb} {identity}")
    print(f"  digest:   {digest}")
    print(f"  operator: {row['operator']}")
    print(f"  reason:   {row['reason']}")
    print(f"  decided:  {row['decided_at']}")
    if state_name == REFUSED:
        print("  This refusal stands until it is explicitly superseded.")
    return EXIT_SUCCESS


def cmd_admission_show(args: argparse.Namespace) -> int:
    """Every decision recorded for one identity, superseded ones included."""
    store = _admission_store(args)
    history = [_admission_row(row) for row in store.audit(args.identity, args.digest)]
    standing = [row for row in history if not row["superseded"]]
    if args.json:
        print_json(
            success(
                {
                    "qualified_identity": args.identity,
                    "decisions": standing,
                    "history": history,
                }
            )
        )
        return EXIT_SUCCESS
    if not history:
        print(f"No executable-admission decision recorded for {args.identity}.")
        return EXIT_SUCCESS
    for row in history:
        marker = " (superseded)" if row["superseded"] else ""
        print(f"{row['state']}{marker}: {row['content_digest']}")
        print(f"  operator: {row['operator']}")
        print(f"  reason:   {row['reason']}")
        print(f"  decided:  {row['decided_at']}")
        print(f"  permissions requested: {row['permission_surface'] or 'none declared'}")
    return EXIT_SUCCESS


def cmd_admission_list(args: argparse.Namespace) -> int:
    """Every decision that currently stands, across every identity."""
    store = _admission_store(args)
    rows = [
        _admission_row(row) for row in store.audit() if not row.get("superseded", False)
    ]
    if args.json:
        print_json(success({"decisions": rows}))
        return EXIT_SUCCESS
    if not rows:
        print("No executable-admission decisions are recorded on this machine.")
        return EXIT_SUCCESS
    for row in rows:
        print(f"{row['state']}: {row['qualified_identity']}")
        print(f"  {row['content_digest']} — {row['operator']} — {row['decided_at']}")
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
        "orphaned": [],
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

                catalog_provenance = classify_catalog_provenance(entry, catalog, s)
                if catalog_provenance["catalog_status"] == "orphaned":
                    all_skipped.append(entry_label)
                    skipped_by_status["orphaned"].append(entry_label)
                    warnings.append(
                        f"skipped orphaned entry {entry_label}; remove it with "
                        f"`{catalog_provenance['removal_command']}`"
                    )
                    continue

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
    orphaned_skipped = len(skipped_by_status["orphaned"])
    if still_unknown:
        warnings.append(
            f"skipped {unknown_skipped} entries with unknown upstream status; "
            "use --force to refresh them"
        )

    gitignore_result = None
    if not dry_run and not all_failed and "project" in scopes_to_check and repo_root:
        try:
            gitignore_result = _reconcile_project_gitignore(
                repo_root, untrack=getattr(args, "untrack", False)
            )
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        tracked_warning = _tracked_install_warning(gitignore_result)
        if tracked_warning:
            warnings.append(tracked_warning)

    result = {
        "status": "dry-run" if dry_run else "ok",
        "refreshed": all_refreshed,
        "reconciled_dependencies": all_reconciled_dependencies,
        "skipped": all_skipped,
        "skipped_by_status": skipped_by_status,
        "unknown_skipped": unknown_skipped,
        "orphaned_skipped": orphaned_skipped,
        "failed": all_failed,
        "total_refreshed": len(all_refreshed),
        "total_skipped": len(all_skipped),
    }
    if warnings:
        result["warnings"] = warnings
    if gitignore_result is not None:
        result["gitignore"] = gitignore_result

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
            if gitignore_result is not None:
                _print_gitignore_result(gitignore_result)
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
    """Resolve a catalog entry to locally inspectable source content.

    An entry with no `source` resolves to nothing. That reads as obvious and was
    not what the code did: `Path("")` is `Path(".")`, which exists, so a
    sourceless entry resolved to the *current directory* and its "content" was
    every file in the project. Review reached it through a `runtime-config` entry,
    whose schema has no `source` at all, and the whole-closure coverage check
    accepted the member because it appeared to have content.
    """
    raw_source = str(entry.get("source") or "").strip()
    if not raw_source:
        return None
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
    library_metadata = entry.get("metadata", {}).get("library", {})
    file_bundle = library_metadata.get("skill_bundle") == "file"
    if (
        primitive == "skill"
        and source.is_file()
        and source.name.lower() == "skill.md"
        and not file_bundle
    ):
        return source.parent
    return source if source.exists() else None


def _workspace_pin_verifier(catalog: dict, *, offline: bool = False):
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
        return source_revision(
            entry.identity,
            catalog=catalog,
            expected_revision=entry.pin.value,
            allow_remote=not offline,
        )

    return verify


def _read_source_files(source: Path) -> dict[str, bytes]:
    """One member's complete content, keyed relative to its source root.

    A file source is one member named by its own file name; a directory source is
    every file beneath it. Symlinks are skipped rather than followed: a member
    whose content is decided by a link target is content this Library did not
    read, and the gate would be digesting a name.
    """
    files: dict[str, bytes] = {}
    if source.is_file():
        files[source.name] = source.read_bytes()
        return files
    for path in sorted(source.rglob("*")):
        if path.is_file() and not path.is_symlink():
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def _workspace_pinned_source_files(
    catalog: dict, entry: dict, primitive: str, pin: str
) -> dict[str, bytes] | None:
    """Read one Workspace member from the exact declared catalog commit."""
    import subprocess

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
    repo = Path(str(source_catalog["local_path"])).expanduser().resolve()
    raw_source = str(entry.get("source") or "")
    direct = Path(raw_source).expanduser()
    if direct.exists():
        try:
            relative = direct.resolve().relative_to(repo).as_posix()
        except ValueError:
            # The admitted-content catalog deliberately points outside the
            # source checkout. Its bytes are already frozen and must not be
            # looked up in the original repository again.
            return None
    else:
        marker = "/blob/" if "/blob/" in raw_source else "/tree/"
        if marker not in raw_source:
            return None
        suffix = raw_source.split(marker, 1)[1]
        _revision, separator, relative = suffix.partition("/")
        if not separator:
            return None
    if not relative:
        raise LibraryError(
            f"{root_id(primitive, entry.get('name'))} has no repository-relative "
            "source path"
        )
    library_metadata = entry.get("metadata", {}).get("library", {})
    if (
        primitive == "skill"
        and relative.lower().endswith("/skill.md")
        and library_metadata.get("skill_bundle") != "file"
    ):
        relative = relative.rsplit("/", 1)[0]
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", pin, "--", relative],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:
        raise LibraryError(
            f"{root_id(primitive, entry.get('name'))} cannot list declared "
            f"commit {pin}: {listing.stderr.strip()}"
        )
    paths = [line for line in listing.stdout.splitlines() if line]
    if not paths:
        raise LibraryError(
            f"{root_id(primitive, entry.get('name'))} is absent from declared "
            f"commit {pin}"
        )
    prefix = relative.rstrip("/") + "/"
    files: dict[str, bytes] = {}
    for path in paths:
        blob = subprocess.run(
            ["git", "show", f"{pin}:{path}"],
            cwd=repo,
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            raise LibraryError(
                f"{root_id(primitive, entry.get('name'))} cannot read {path} "
                f"from declared commit {pin}"
            )
        key = path[len(prefix) :] if path.startswith(prefix) else Path(path).name
        files[key] = blob.stdout
    return files


def _admitted_entry_source(entry: dict, resolved: Path, member_root: Path) -> Path:
    """Where a bound entry must point so its installer reads the admitted bytes.

    The publication mirrors what `_read_source_files` produced, so the mapping is
    the inverse of that function: a file source becomes the one published file; a
    directory source becomes the published root, unless the entry itself named a
    file inside it -- which is how a skill entry names `SKILL.md` while the member
    is the directory around it.

    This is a derivation, so `_workspace_admitted_catalog` verifies its result
    against the admitted digest instead of trusting it.
    """
    if resolved.is_file():
        return member_root / resolved.name
    named = Path(str(entry.get("source") or "")).name
    if named and (member_root / named).is_file():
        return member_root / named
    return member_root


#: The one catalog entry field the Workspace mutation gate reads content from.
_ADMITTED_SOURCE_FIELD = "source"

#: Catalog entry keys that carry no content an installer could read: identity,
#: description, dependency and capability declarations, and metadata. A v2
#: Workspace member may carry these beside its `source`; anything else is refused.
#:
#: This is an allowlist, and the direction matters. Wave 1 of the review broke a
#: denylist by naming `sources` on an `agent`; wave 2 broke the extended denylist
#: by naming `base` on a `runtime-config`, whose schema has no `source` at all.
#: A denylist has to predict every field an installer will ever resolve content
#: from, and the two rounds of it were wrong in the same way twice. An allowlist
#: fails the other direction: an entry field nobody has classified refuses the
#: member until someone does, and adding a content-bearing field to an installer
#: cannot silently widen what a Workspace mutation will write.
_INERT_ENTRY_KEYS = frozenset(
    {
        "aliases",
        "author",
        "capability",
        "category",
        "compatibility",
        "default_scope",
        "deprecated",
        "description",
        "harness",
        "homepage",
        "keywords",
        "kind",
        "license",
        "maturity",
        "metadata",
        "name",
        "notes",
        "replaced_by",
        "requires",
        "runtime",
        "scope",
        "skill_class",
        "status",
        "summary",
        "tags",
        "title",
        "type",
        "version",
    }
)


def _unadmitted_entry_keys(entry: Mapping) -> list[str]:
    """Entry keys the gate has not classified as free of installer content.

    Review demonstrated the cost of guessing twice. An `agent` entry carrying both
    `source` and `sources.claude` had its `source` digested and admitted while
    `_resolve_agent_targets` read `sources.claude` and installed bytes no operator
    ever saw, with the command reporting `applied`. A `runtime-config` entry then
    did the same through `base`, a field the first repair had no reason to name.

    So the question asked here is not "does this field look like a source" but
    "is this field known to carry none". Adding a key to `_INERT_ENTRY_KEYS` is a
    statement that no installer resolves content from it.
    """
    return sorted(
        str(key)
        for key in entry
        if str(key) != _ADMITTED_SOURCE_FIELD and str(key) not in _INERT_ENTRY_KEYS
    )


def _workspace_admitted_catalog(catalog: dict, closure, items, published, contents) -> dict:
    """A catalog whose resolved members resolve to the admitted publication.

    ADR-0011's mutation gate freezes and digests a snapshot and then authorizes a
    mutation. Until `CL-st5s` the mutation was performed by installers that
    resolved their own source, so the gate's decision and the installer's read
    were two reads of a mutable thing and the platform compared them afterwards.
    A comparison reports a difference once the bytes are published; the ADR
    recorded exactly that as an open residual.

    Binding removes the second read. The installers are unchanged -- they still
    resolve a catalog entry to a local source -- but for a v2 mutation that source
    is the admitted publication, which only the gate's own writer produced and
    whose bytes were hashed at their final paths. An edit to the catalog checkout
    during the mutation is not detected, because there is nothing to detect: no
    installer can reach it.

    What is deliberately *not* rebound is provenance. The lock still records the
    catalog's own source and the pin the resolution verified; see
    `_workspace_restore_member_provenance`.

    Raises:
        LibraryError: when a member cannot be bound, or when a bound member does
            not resolve to the exact bytes the gate admitted.
    """
    import copy

    from lib.providers.executable_admission import content_digest

    bound = copy.deepcopy(catalog)
    by_upstream = {item.upstream_id: item for item in items}
    for node in closure.nodes:
        if node.role != "artifact":
            continue
        item = by_upstream.get(f"{node.primitive}/{node.name}")
        if item is None:
            raise LibraryError(
                f"{root_id(node.primitive, node.name)} was resolved but has no "
                "admitted content; a Workspace mutation covers the whole closure "
                "or none of it",
                exit_code=3,
            )
        member_root = published.get(item.qualified_identity())
        if member_root is None:
            raise LibraryError(
                f"{item.qualified_identity()} was admitted but not published; the "
                "installer would fall back to the source the gate did not read",
                exit_code=3,
            )
        entry = lookup_entry(
            bound, node.primitive, node.name, fuzzy=False, source_catalog=node.catalog_name
        )
        unadmitted = _unadmitted_entry_keys(entry)
        if unadmitted:
            raise LibraryError(
                f"{root_id(node.primitive, node.name)} declares entry fields that "
                f"are not known to be free of installer content: {unadmitted}. The "
                f"Workspace mutation gate digested and admitted only its "
                f"{_ADMITTED_SOURCE_FIELD!r}, so an installer resolving content "
                "from one of these would write bytes no operator decided about. "
                "The member is refused rather than partly bound",
                exit_code=3,
            )
        resolved = _workspace_local_source(catalog, entry, node.primitive)
        if resolved is None:
            raise LibraryError(
                f"{root_id(node.primitive, node.name)} has no locally readable "
                "source to bind to its admitted content",
                exit_code=3,
            )
        entry["source"] = str(_admitted_entry_source(entry, resolved, member_root))
        rebound = _workspace_local_source(bound, entry, node.primitive)
        observed = _read_source_files(rebound) if rebound is not None else {}
        # Against the gate's own frozen mapping, not against the publication. The
        # publication is what is being checked, so checking it against itself
        # would confirm that a tampered file equals the tampered file.
        admitted = dict(contents.get(item.qualified_identity()) or {})
        if not observed or not admitted or content_digest(observed) != content_digest(admitted):
            raise LibraryError(
                f"{root_id(node.primitive, node.name)} does not resolve to the "
                "admitted bytes after binding; the mutation is refused rather than "
                "run against content nobody admitted",
                exit_code=3,
            )
    return bound


@contextmanager
def _admitted_publication_root(repo_root: Path):
    """A per-operation home for the gate's published bytes, removed afterwards.

    Inside the project, so the publication and the targets it feeds share a
    filesystem, and so a crash leaves it where an operator will find it rather
    than in a temporary directory the system may already have cleared. It is not
    a second copy of the catalog: the installers materialize their own cache from
    it, and it is removed when the operation ends however it ends.
    """
    import uuid

    container = Path(repo_root) / ".library" / "admitted"
    root = container / uuid.uuid4().hex
    try:
        yield root
    finally:
        # This operation's directory only. Removing the shared container would
        # take a concurrent operation's publication with it -- the project lock
        # serializes one scope, not two.
        shutil.rmtree(root, ignore_errors=True)
        for path in (container, container.parent):
            try:
                path.rmdir()
            except OSError:
                # Still holds something, or never existed. Either way it is not
                # this operation's to remove.
                break


def _workspace_member_provenance(catalog: dict, closure) -> dict:
    """Each member's catalog source and the pin its resolution verified."""
    provenance: dict[tuple[str, str], tuple[str, str]] = {}
    for node in closure.nodes:
        if node.role != "artifact":
            continue
        entry = lookup_entry(
            catalog, node.primitive, node.name, fuzzy=False, source_catalog=node.catalog_name
        )
        source = str(entry.get("source") or "")
        if source:
            provenance[(node.primitive, node.name)] = (
                source,
                str(node.pin.value if node.pin else ""),
            )
    return provenance


def _workspace_restore_member_provenance(lock: dict, closure, sources: dict) -> None:
    """Record the catalog the member came from, not the snapshot it was read from.

    A v2 member is installed from the admitted publication, so the installer
    honestly records where it read the bytes. That is not what the lock is for:
    `source` answers "which catalog is this from" and `source_commit` answers "at
    which revision", and both are known exactly -- the resolution verified the pin
    before the closure existed. Writing the pin here is stronger than what a
    non-v2 install records, which is whatever HEAD the local checkout happened to
    be on when the installer read it.
    """
    for (primitive, name), (source, commit) in sources.items():
        member_id = root_id(primitive, name)
        for entry in lock.get("installed", []):
            if entry.get("type") == primitive and entry.get("name") == name:
                entry["source"] = source
                if commit:
                    entry["source_commit"] = commit
                    entry["cache_path"] = restore_cache_path_source_commit(
                        str(entry.get("cache_path") or ""), commit
                    )
        for receipt in lock.get("receipts", []):
            if receipt.get("id") == member_id and commit:
                receipt["source"] = source
                receipt["definition_commit"] = commit
                receipt["source_commit"] = commit
                receipt["cache_path"] = restore_cache_path_source_commit(
                    str(receipt.get("cache_path") or ""), commit
                )


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
        FIRST_PARTY,
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
        pinned = (
            _workspace_pinned_source_files(
                catalog, entry, node.primitive, node.pin.value
            )
            if node.pin
            else None
        )
        files = pinned if pinned is not None else _read_source_files(source)
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
                node.primitive,
                "workspace-resolution",
                None,
                None,
                (node.catalog_name,),
                # A Workspace closure resolves entries out of *registered source
                # catalogs* -- this repository and its steward catalogs. That is
                # the first-party side of `CL-lt51`'s boundary, and stating it
                # here is what keeps the model-instructing admission requirement
                # from blocking the platform on its own Skills. A foreign item
                # never reaches this function; it arrives through
                # `install_foreign_item`, which records `foreign` itself.
                stewardship=FIRST_PARTY,
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
            executable_admission=executable_admission_for(node.primitive, FIRST_PARTY),
        )
        items.append(item)
        contents[item.qualified_identity()] = files

    return items, contents


def _workspace_admission_remedies(refusal, items, contents) -> list[str]:
    """The command that would decide each executable member the gate refused.

    Rendered at the CLI boundary rather than inside `gate_resolution`: the gate's
    job is to fail the whole resolution before any mutation, and it keeps doing
    exactly that. What it cannot know is which program the operator ran, so the
    remedy is composed here from the same registration the refusal names.
    """
    from lib.providers.executable_admission import (
        admission_command_line,
        content_digest,
    )

    by_identity = {item.qualified_identity(): item for item in items}
    remedies: list[str] = []
    for identity, state in refusal.refusals:
        item = by_identity.get(identity)
        files = contents.get(identity)
        if item is None or not files:
            continue
        remedies.append(
            f"{identity} is {state}; record a decision about these exact bytes: "
            + admission_command_line(
                identity,
                content_digest(files),
                item.library_type,
                supersede=state == "refused",
            )
        )
    return remedies


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
    targets: set[str] = set()
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
            targets.add(str(path))
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
        "targets": sorted(targets),
    }


def _workspace_capture_rollback(
    rollback_root: Path, paths: list[str], state_files: list[Path]
) -> list[tuple[Path, Path | None]]:
    """Capture exact pre-mutation state for one Workspace transaction."""
    if rollback_root.is_symlink() or rollback_root.exists():
        raise LibraryError(
            f"Workspace rollback capture requires an absent root: {rollback_root}"
        )
    captured: list[tuple[Path, Path | None]] = []
    for index, target in enumerate([*(Path(path) for path in paths), *state_files]):
        backup = rollback_root / str(index)
        if target.is_symlink():
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.symlink_to(target.readlink())
        elif target.is_dir():
            shutil.copytree(target, backup, symlinks=True)
        elif target.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        else:
            backup = None
        captured.append((target, backup))
    return captured


@contextmanager
def _workspace_transaction_guard(
    lock_path: Path, repo_root: Path
) -> None:
    """Recover a failed Workspace transaction only from integrity-bound state."""
    try:
        yield
    except BaseException as exc:
        from lib.workspace import recover_workspace_journal, workspace_journal_path

        if workspace_journal_path(lock_path).exists():
            try:
                recover_workspace_journal(lock_path, repo_root)
            except LibraryError as recovery_exc:
                raise LibraryError(
                    "Workspace transaction failed and automatic recovery refused "
                    f"unsafe state: {recovery_exc}"
                ) from exc
        raise


@contextmanager
def _workspace_source_commit_override(source_commit: str | None):
    """Scope one admitted member's verified cache revision to its installer."""
    if not source_commit:
        yield
        return
    token = WORKSPACE_SOURCE_COMMIT.set(source_commit)
    try:
        yield
    finally:
        WORKSPACE_SOURCE_COMMIT.reset(token)


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
    artifact_pins = {
        (node.primitive, node.name): node.pin.value
        for node in closure.nodes
        if node.role == "artifact" and node.pin
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
    from lib.providers.executable_admission import ResolutionRefused
    from lib.workspace import (
        assert_published_admitted,
        checkpoint_workspace_use,
        clear_workspace_journal,
        gate_workspace_mutation,
        prepare_workspace_rollback,
        publish_admitted_members,
        recover_workspace_journal,
        begin_workspace_use_mutation,
        workspace_journal_path,
        workspace_path_state,
        workspace_write_lock,
        write_workspace_journal,
    )

    rollback = None
    rollback_root = None
    if not workspace_journal_path(lock_path).exists():
        rollback_root = prepare_workspace_rollback(lock_path)
    with (
        workspace_write_lock(lock_path),
        _admitted_publication_root(repo_root) as admitted_root,
        _workspace_transaction_guard(lock_path, repo_root),
    ):
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
        member_failure: list[tuple[str, int, str]] = []
        if rollback_root is None:
            rollback_root = prepare_workspace_rollback(lock_path)
        journal_base = {
            "operation": "use",
            "phase": "capturing",
            "reference": args.reference,
            "scope": args.scope,
            "definition_commit": definition_commit,
            "artifacts": [
                f"{primitive}:{name}" for primitive, name in closure.artifacts
            ],
            "rollback": [],
        }
        write_workspace_journal(lock_path, journal_base)
        rollback = _workspace_capture_rollback(
            rollback_root,
            locked_collision["targets"],
            [lock_path, repo_root / ".gitignore"],
        )
        write_workspace_journal(
            lock_path,
            {
                "operation": "use",
                "phase": "ready",
                "reference": args.reference,
                "scope": args.scope,
                "definition_commit": definition_commit,
                "artifacts": [
                    f"{primitive}:{name}" for primitive, name in closure.artifacts
                ],
                "rollback": [
                    {
                        "target": str(target),
                        "backup": str(backup) if backup is not None else None,
                        "target_state": workspace_path_state(target),
                        "backup_state": (
                            workspace_path_state(backup)
                            if backup is not None
                            else None
                        ),
                    }
                    for target, backup in rollback
                ],
            },
        )
        member_provenance: dict[tuple[str, str], tuple[str, str]] = {}
        #: The normalized items the mutation gate admitted. Only a cross-catalog
        #: closure produces them, and only that path publishes and binds.
        admitted_items: list = []

        def _install_members(frozen_content=None) -> None:
            """Install every resolved member, recording the first that failed.

            The failure is recorded rather than returned because this callable is
            invoked by the admission gate, which owns its own return value. A
            returned code would be swallowed there and the run would report
            success over a member that never installed.

            `frozen_content` is the exact immutable content the gate digested and
            admitted, and for a v2 mutation it is the **only** content an
            installer can reach. It is published atomically into an
            admitted-content root, that publication is hashed at its final paths,
            and the catalog the installers run against is bound to it. Slice 6
            compared the admitted snapshot against a second read of the source
            instead, which reported an edit only once its bytes were already
            written; there is nothing left to compare, because there is no second
            read.
            """
            installed_catalog = catalog
            published: dict[str, Path] = {}
            if frozen_content is not None:
                items_now = admitted_items
                published = publish_admitted_members(
                    admitted_root, items_now, frozen_content
                )
                assert_published_admitted(published, frozen_content)
                installed_catalog = _workspace_admitted_catalog(
                    catalog, closure, items_now, published, frozen_content
                )
                member_provenance.update(
                    _workspace_member_provenance(catalog, closure)
                )
            for primitive, name in closure.artifacts:
                begin_workspace_use_mutation(lock_path)
                output_buffer = io.StringIO()
                with (
                    _workspace_source_commit_override(artifact_pins.get((primitive, name))),
                    redirect_stdout(output_buffer),
                ):
                    rc = _dispatch_use(
                        args,
                        repo_root,
                        installed_catalog,
                        primitive,
                        name,
                        args.scope,
                        args.harness,
                        False,
                        True,
                        "vendor",
                        source_catalog=artifact_sources[(primitive, name)],
                    )
                checkpoint_workspace_use(lock_path, repo_root)
                if rc != 0:
                    member_failure.append(
                        (f"{primitive}:{name}", rc, output_buffer.getvalue().strip())
                    )
                    return
            if published:
                # After the last installer, over the same published paths. An
                # installer that rewrote the content it was reading from would
                # otherwise leave a projection nobody admitted.
                assert_published_admitted(published, frozen_content)

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
            admitted_items.extend(items)
            admission = _foreign_state(repo_root).admission_ledger_store()
            try:
                # The operator's own decisions, not an empty ledger. Slice 6
                # constructed one inline, which made every executable member of a
                # cross-catalog Workspace permanently unresolvable: the gate was
                # correct and the ledger it consulted could not be written to by
                # anything.
                #
                # The gate and the mutation it authorizes run inside
                # `decisions()`, which holds the same lock a `library admission`
                # write takes. A snapshot read here was demonstrably not enough:
                # review superseded the grant with a refusal while the members
                # were being installed, and the admitted bytes were written
                # anyway. The gate itself is untouched -- what changed is how
                # long the answer it was given is guaranteed to still be true.
                with admission.decisions() as decisions:
                    gate_workspace_mutation(
                        closure,
                        items,
                        decisions,
                        contents,
                        mutate=_install_members,
                    )
            except ResolutionRefused as exc:
                result.update(
                    {
                        "status": "blocked",
                        "blockers": [
                            str(exc),
                            *_workspace_admission_remedies(exc, items, contents),
                        ],
                    }
                )
                _print_workspace_result(result, json_mode=args.json)
                return 3
        else:
            _install_members()

        if member_failure:
            member, rc, message = member_failure[0]
            recover_workspace_journal(lock_path, repo_root)
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
        _workspace_restore_member_provenance(lock, closure, member_provenance)
        restore_unchanged_install_timestamps(lock, current_lock)
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
        begin_workspace_use_mutation(lock_path)
        save_lockfile(lock_path, lock)
        checkpoint_workspace_use(lock_path, repo_root)
        if getattr(args, "reconcile_gitignore", False):
            begin_workspace_use_mutation(lock_path)
            result["gitignore"] = _reconcile_project_gitignore(repo_root)
            checkpoint_workspace_use(lock_path, repo_root)
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

    # ADR-0012 has one mutation boundary: no public command may route desired
    # state through the retired user-global lock. Keep this before catalog,
    # repository, lockfile, and installer resolution so JSON and human callers
    # receive the same deterministic result without any observable mutation.
    if getattr(args, "scope", None) in {"global", "both"}:
        if getattr(args, "json", False):
            print_json(error_result(PROJECT_ONLY_SCOPE_ERROR, EXIT_FAILURE))
        else:
            print(f"Error: {PROJECT_ONLY_SCOPE_ERROR}", file=sys.stderr)
        return EXIT_FAILURE

    # No subcommand given
    if not args.primitive:
        parser.print_help()
        return EXIT_FAILURE

    if args.primitive == "init":
        use_json = getattr(args, "json", False)
        try:
            repo_root = _strict_project_git_root(args)
            catalog_root = _resolve_catalog_root()
            catalog = load_catalog(catalog_root)
            try:
                from lib.workspace import resolve_workspace

                workspace = resolve_workspace(
                    catalog, CANONICAL_BASE_WORKSPACE_REFERENCE
                )
            except LibraryError:
                workspace = None
            if (
                workspace is None
                or workspace.catalog_identity != CANONICAL_PLATFORM_CATALOG_IDENTITY
            ):
                catalog = load_catalog(_tool_catalog_root())
                workspace = resolve_workspace(
                    catalog, CANONICAL_BASE_WORKSPACE_REFERENCE
                )
            if workspace.catalog_identity != CANONICAL_PLATFORM_CATALOG_IDENTITY:
                raise LibraryError(
                    "Canonical Workspace 'cognovis-base' is unavailable in the selected catalog.",
                    exit_code=EXIT_NOT_FOUND,
                )
            init_args = argparse.Namespace(
                reference=CANONICAL_BASE_WORKSPACE_REFERENCE,
                scope="project",
                target_project=repo_root,
                harness="all",
                dry_run=False,
                replace_with_catalog_content=False,
                reconcile_gitignore=True,
                json=use_json,
            )
            return _workspace_use(init_args, repo_root, catalog)
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code

    if args.primitive == "bootstrap":
        if not getattr(args, "verb", None):
            parser.parse_args(["bootstrap", "--help"])
            return EXIT_FAILURE
        return cmd_bootstrap(args)

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
        try:
            sync_scope = getattr(args, "scope", DEFAULT_LIFECYCLE_SCOPE)
            if sync_scope in {"project", "both"}:
                repo_root = _strict_project_git_root(args)
                _preflight_managed_project(args, repo_root, allow_missing_lock=False)
            else:
                repo_root = _resolve_lifecycle_project_root(args)
        except LibraryError as exc:
            if getattr(args, "json", False):
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
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
            if verb == "update":
                return cmd_marketplace_update(args, repo_root, catalog)
            if verb == "update-show":
                return cmd_marketplace_update_show(args, repo_root)
            if verb == "update-list":
                return cmd_marketplace_update_list(args, repo_root)
            if verb == "update-approve":
                return cmd_marketplace_update_approve(args, repo_root, catalog)
            if verb == "update-reject":
                return cmd_marketplace_update_reject(args, repo_root)
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

    # Top-level executable-admission decisions (ADR-0011, CL-2wqz). No catalog is
    # loaded: the decision is about bytes this machine already holds, and the
    # remedy for a refused install must not need more infrastructure than the
    # install did.
    from lib.providers.executable_admission import (
        ADMISSION_COMMAND,
        ADMITTED,
        DENY_VERB,
        GRANT_VERB,
        LIST_VERB,
        REFUSED,
        SHOW_VERB,
    )

    if args.primitive == ADMISSION_COMMAND:
        verb = getattr(args, "verb", None)
        if not verb:
            parser.parse_args([ADMISSION_COMMAND, "--help"])
            return EXIT_FAILURE
        use_json = getattr(args, "json", False)
        try:
            if verb == GRANT_VERB:
                return cmd_admission_decide(args, ADMITTED)
            if verb == DENY_VERB:
                return cmd_admission_decide(args, REFUSED)
            if verb == SHOW_VERB:
                return cmd_admission_show(args)
            if verb == LIST_VERB:
                return cmd_admission_list(args)
        except LibraryError as exc:
            if use_json:
                print_json(error_result(str(exc), exc.exit_code))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return exc.exit_code
        print("Error: Unknown admission verb.", file=sys.stderr)
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
        return _tool_catalog_root()


def _tool_catalog_root() -> Path:
    """Return the tool's catalog without falling back to the caller's CWD."""
    source_catalog = TOOL_ROOT.resolve()
    if (source_catalog / "library.yaml").is_file():
        return source_catalog
    packaged_catalog = Path(str(files("scripts").joinpath("library.yaml")))
    if packaged_catalog.is_file():
        return packaged_catalog.parent
    raise LibraryError("Library tool catalog is unavailable")


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

    tool_catalog_root = _tool_catalog_root()
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


def _strict_project_git_root(args: argparse.Namespace) -> Path:
    """Resolve the one root shared by Git, lockfile, installs, and .gitignore."""
    explicit = getattr(args, "project", None)
    if explicit is None:
        explicit = getattr(args, "target_project", None)
    candidate = explicit.expanduser().resolve() if explicit is not None else Path.cwd()
    git_root = _find_git_root(candidate)
    if git_root is None:
        raise LibraryError("Project installs require a Git worktree top-level")
    if explicit is not None and candidate != git_root:
        raise LibraryError(
            f"--project must name the Git worktree top-level exactly: {git_root}"
        )
    return git_root


def _preflight_managed_project(
    args: argparse.Namespace, repo_root: Path, *, allow_missing_lock: bool
) -> None:
    """Reject divergent roots and invalid receipt inventories before mutation."""
    strict_root = _strict_project_git_root(args)
    if repo_root.resolve() != strict_root:
        raise LibraryError("Project root must equal the Git worktree top-level")
    lockfile = strict_root / ".library.lock"
    if allow_missing_lock and not lockfile.exists():
        return
    from lib.gitignore import managed_project_paths

    managed_project_paths(strict_root)


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
