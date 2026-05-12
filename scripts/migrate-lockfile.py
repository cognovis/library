#!/usr/bin/env python3
"""
migrate-lockfile.py — CL-yx2: Extend existing .library.lock files with new ADR-0003 fields.

Adds two new required fields to every lockfile entry that is missing them:
  - marketplace: derived from the entry's source URL (or from library.yaml.marketplaces)
  - cache_path:  set to empty string "" (pending next `library sync` to materialize)

Usage:
    # Migrate a single lockfile:
    python3 scripts/migrate-lockfile.py .library.lock

    # Migrate multiple lockfiles:
    python3 scripts/migrate-lockfile.py .library.lock ~/.config/library/global.lock

    # Dry-run (show what would change, don't write):
    python3 scripts/migrate-lockfile.py --dry-run .library.lock

    # Load marketplace mappings from library.yaml in a custom location:
    python3 scripts/migrate-lockfile.py --library-yaml /path/to/library.yaml .library.lock

Output:
    Prints a summary of entries updated per file.
    Exits 0 on success, 1 on any error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Marketplace URL pattern mappings (hardcoded fallback)
# ---------------------------------------------------------------------------
# Ordered: longest/most-specific patterns first to avoid prefix collisions.

HARDCODED_URL_PATTERNS: list[tuple[str, str]] = [
    # cognovis
    (r"https://github\.com/cognovis/samurai-skills/", "cognovis-samurai"),
    (r"https://github\.com/cognovis/library-core/", "cognovis-core"),
    (r"https://github\.com/cognovis/", "cognovis-core"),
    # sussdorff
    (r"https://github\.com/sussdorff/library-core/", "sussdorff-core"),
    (r"https://github\.com/sussdorff/", "sussdorff-core"),
    # anthropic / anthropics
    (r"https://github\.com/anthropics?/", "anthropic-official"),
    # third-party
    (r"https://github\.com/disler/", "disler"),
    (r"https://github\.com/pbakaus/", "pbakaus"),
    (r"https://github\.com/ThadeNorigar/", "thadenorigar"),
]


def derive_marketplace_from_url(source: str) -> str:
    """Derive a marketplace name from a source URL using hardcoded patterns.

    Returns 'local' for local filesystem paths, 'unknown' if no pattern matches.
    """
    # Local paths: starts with / or ~ or relative path (no ://)
    if source.startswith("/") or source.startswith("~") or "://" not in source:
        return "local"

    for pattern, marketplace in HARDCODED_URL_PATTERNS:
        if re.search(pattern, source, re.IGNORECASE):
            return marketplace

    return "unknown"


# ---------------------------------------------------------------------------
# library.yaml marketplace loader
# ---------------------------------------------------------------------------

def load_marketplace_map(library_yaml_path: Path) -> dict[str, str]:
    """Load URL → marketplace name mappings from library.yaml.marketplaces.

    Returns a dict mapping source_prefix → marketplace_name.
    Returns empty dict if the file cannot be read.
    """
    if not library_yaml_path.exists():
        return {}

    try:
        with library_yaml_path.open() as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        print(f"Warning: could not load {library_yaml_path}: {exc}", file=sys.stderr)
        return {}

    marketplaces = data.get("marketplaces", [])
    if not isinstance(marketplaces, list):
        return {}

    result: dict[str, str] = {}
    for mp in marketplaces:
        if not isinstance(mp, dict):
            continue
        name = mp.get("name", "")
        source = mp.get("source", "")
        if name and source:
            result[source.rstrip("/")] = name

    return result


def derive_marketplace(
    source: str,
    marketplace_map: dict[str, str],
) -> str:
    """Derive marketplace name, preferring library.yaml mappings over hardcoded patterns."""
    # Try library.yaml mappings (longest prefix match wins)
    if marketplace_map:
        best_prefix = ""
        best_name = ""
        for prefix, name in marketplace_map.items():
            if source.startswith(prefix) and len(prefix) > len(best_prefix):
                best_prefix = prefix
                best_name = name
        if best_name:
            return best_name

    # Fall back to hardcoded patterns
    return derive_marketplace_from_url(source)


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def migrate_lockfile(
    lockfile_path: Path,
    marketplace_map: dict[str, str],
    dry_run: bool = False,
) -> int:
    """Migrate a single lockfile. Returns the number of entries updated."""
    if not lockfile_path.exists():
        print(f"WARNING: {lockfile_path} does not exist — skipping.", file=sys.stderr)
        return 0

    with lockfile_path.open() as f:
        data = yaml.safe_load(f) or {}

    installed = data.get("installed", [])
    if not isinstance(installed, list):
        print(f"ERROR: {lockfile_path}: 'installed' is not a list.", file=sys.stderr)
        return 0

    updated = 0
    for entry in installed:
        if not isinstance(entry, dict):
            continue

        changed = False
        source = entry.get("source", "")

        # Add marketplace if missing
        if "marketplace" not in entry:
            entry["marketplace"] = derive_marketplace(source, marketplace_map)
            changed = True

        # Add cache_path if missing (set to empty string — populated on next sync)
        if "cache_path" not in entry:
            entry["cache_path"] = ""
            changed = True

        if changed:
            updated += 1
            if dry_run:
                print(
                    f"  [DRY-RUN] {entry.get('name', '?')}: "
                    f"marketplace={entry.get('marketplace')!r}, "
                    f"cache_path={entry.get('cache_path')!r}"
                )

    if updated == 0:
        print(f"{lockfile_path}: no changes needed (all entries already have new fields).")
        return 0

    if not dry_run:
        with lockfile_path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"{lockfile_path}: updated {updated} entries (marketplace + cache_path added).")
    else:
        print(f"{lockfile_path}: {updated} entries would be updated (dry-run, no changes written).")

    return updated


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate-lockfile",
        description=(
            "Migrate existing .library.lock files to include the new ADR-0003 fields: "
            "marketplace and cache_path."
        ),
    )
    parser.add_argument(
        "lockfiles",
        nargs="+",
        metavar="LOCKFILE",
        help="One or more .library.lock files to migrate (e.g. .library.lock or "
             "~/.config/library/global.lock).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would change but do not write any files.",
    )
    parser.add_argument(
        "--library-yaml",
        metavar="PATH",
        default=None,
        help="Path to library.yaml to use for marketplace URL mappings. "
             "Defaults to library.yaml in the current directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve library.yaml path for marketplace map
    if args.library_yaml:
        library_yaml_path = Path(args.library_yaml).expanduser().resolve()
    else:
        library_yaml_path = Path.cwd() / "library.yaml"

    marketplace_map = load_marketplace_map(library_yaml_path)
    if marketplace_map:
        print(
            f"Loaded {len(marketplace_map)} marketplace(s) from {library_yaml_path}."
        )
    else:
        print(
            f"No library.yaml marketplaces found at {library_yaml_path} — "
            "using hardcoded URL patterns."
        )

    total_updated = 0
    errors = 0

    for lockfile_str in args.lockfiles:
        lockfile_path = Path(lockfile_str).expanduser().resolve()
        try:
            n = migrate_lockfile(lockfile_path, marketplace_map, dry_run=args.dry_run)
            total_updated += n
        except Exception as exc:
            print(f"ERROR migrating {lockfile_path}: {exc}", file=sys.stderr)
            errors += 1

    print(
        f"\nMigration complete: {total_updated} entries updated across "
        f"{len(args.lockfiles)} file(s)."
    )
    if errors:
        print(f"Errors: {errors}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
