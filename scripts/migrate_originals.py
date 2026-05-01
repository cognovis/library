#!/usr/bin/env python3
"""
migrate_originals.py — Migrate ORIGINAL artefacts from claude-code-plugins to cognovis/library-core.

Usage:
    python3 scripts/migrate_originals.py [--dry-run] [--library-core PATH] [--source PATH]

Arguments:
    --dry-run: Print what would be done without copying
    --library-core: Path to library-core clone (default: /tmp/cognovis-library-core)
    --source: Path to claude-code-plugins (default: /Users/malte/code/claude-code-plugins)
    --audit: Path to audit JSON (default: docs/audit/skills-origin.json)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def source_path_for(source_root: Path, artifact: dict) -> Path:
    """Return absolute source path for an artifact."""
    return source_root / artifact["path"]


def dest_path_for(artifact: dict, library_core: Path) -> Path | None:
    """Compute the destination path for an artifact in library-core.

    Returns None if the artifact type has no defined destination.
    """
    path = artifact["path"]
    current_type = artifact["current_type"]
    path_parts = path.split("/")

    if current_type == "skill":
        # path: <category>/skills/<name>/SKILL.md
        skill_name = path_parts[-2]
        return library_core / ".claude" / "skills" / skill_name

    elif current_type == "agent":
        # path: <category>/agents/<filename>.md
        filename = path_parts[-1]
        return library_core / ".claude" / "agents" / filename

    elif current_type in ("guardrail", "hook"):
        # path: <category>/hooks/<filename>
        filename = path_parts[-1]
        return library_core / ".claude" / "hooks" / filename

    elif current_type == "command":
        # path: .claude/commands/<filename>
        filename = path_parts[-1]
        return library_core / ".claude" / "commands" / filename

    elif current_type == "plugin":
        # path: <category>/plugins/<name>  (directory, no trailing file)
        plugin_name = path_parts[-1]
        return library_core / "plugins" / plugin_name

    return None


def bridge_symlink_for(artifact: dict, library_core: Path) -> tuple[Path, Path] | None:
    """Return (symlink_path, target_dir) for the bridge symlink, or None.

    Skills get a bridge symlink: .agents/skills/<name> -> ../../.claude/skills/<name>
    """
    if artifact["current_type"] == "skill":
        path_parts = artifact["path"].split("/")
        skill_name = path_parts[-2]
        link = library_core / ".agents" / "skills" / skill_name
        target = library_core / ".claude" / "skills" / skill_name
        return link, target
    return None


# ---------------------------------------------------------------------------
# Copy helpers
# ---------------------------------------------------------------------------


def copy_skill(src_dir: Path, dest_dir: Path, dry_run: bool) -> None:
    """Copy entire skill directory using shutil.copytree (overwrite if exists)."""
    if dry_run:
        print(f"  [DRY-RUN] copytree {src_dir} -> {dest_dir}")
        return
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)


def copy_single_file(src: Path, dest: Path, dry_run: bool) -> None:
    """Copy a single file to dest (creates parent dirs)."""
    if dry_run:
        print(f"  [DRY-RUN] copy {src} -> {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def copy_plugin(src_dir: Path, dest_dir: Path, dry_run: bool) -> None:
    """Copy entire plugin directory."""
    if dry_run:
        print(f"  [DRY-RUN] copytree {src_dir} -> {dest_dir}")
        return
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)


def create_bridge_symlink(link: Path, target: Path, dry_run: bool) -> None:
    """Create a relative symlink from link to target."""
    # Compute relative target from link's parent (Python 3.12+ pathlib, walk_up=True)
    try:
        rel_target = str(Path(target).relative_to(link.parent, walk_up=True))
    except (TypeError, ValueError):
        # Fallback for older Python or cross-drive paths
        rel_target = str(target)

    if dry_run:
        print(f"  [DRY-RUN] symlink {link} -> {rel_target}")
        return

    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(rel_target)


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------


def migrate(
    audit_path: Path,
    library_core: Path,
    source_root: Path,
    dry_run: bool,
) -> int:
    """Run the migration. Returns 0 on success, 1 on critical failure."""
    # Read audit JSON
    with audit_path.open() as fh:
        data = json.load(fh)

    artifacts = [
        a
        for a in data["artifacts"]
        if a["origin"] == "ORIGINAL"
        and a["migration_action"] == "move_to_cognovis_library_core"
    ]

    print(f"Found {len(artifacts)} ORIGINAL artefacts to migrate.")

    copied = 0
    skipped = 0
    warnings: list[str] = []

    for artifact in artifacts:
        path_str = artifact["path"]
        current_type = artifact["current_type"]

        src = source_path_for(source_root, artifact)
        dest = dest_path_for(artifact, library_core)

        if dest is None:
            warnings.append(f"No dest mapping for type '{current_type}': {path_str}")
            skipped += 1
            continue

        # Check source existence
        if current_type == "skill":
            # Source is the directory containing SKILL.md
            src_dir = src.parent  # src points to SKILL.md, parent is the skill dir
            if not src_dir.exists():
                warnings.append(f"Source directory not found (skipping): {src_dir}")
                skipped += 1
                continue
            print(f"  skill: {path_str} -> {dest}")
            copy_skill(src_dir, dest, dry_run)

            # Create bridge symlink
            bridge = bridge_symlink_for(artifact, library_core)
            if bridge:
                link, target = bridge
                create_bridge_symlink(link, target, dry_run)

        elif current_type == "agent":
            if not src.exists():
                warnings.append(f"Source file not found (skipping): {src}")
                skipped += 1
                continue
            print(f"  agent: {path_str} -> {dest}")
            copy_single_file(src, dest, dry_run)

            # Also copy to .codex/agents/ for Codex bridge
            codex_dest = library_core / ".codex" / "agents" / dest.name
            copy_single_file(src, codex_dest, dry_run)

        elif current_type in ("guardrail", "hook"):
            if not src.exists():
                warnings.append(f"Source file not found (skipping): {src}")
                skipped += 1
                continue
            print(f"  hook: {path_str} -> {dest}")
            copy_single_file(src, dest, dry_run)

        elif current_type == "command":
            if not src.exists():
                warnings.append(f"Source file not found (skipping): {src}")
                skipped += 1
                continue
            print(f"  command: {path_str} -> {dest}")
            copy_single_file(src, dest, dry_run)

        elif current_type == "plugin":
            src_dir = src  # src already computed as source_root / artifact["path"]
            if not src_dir.exists():
                warnings.append(f"Plugin source not found (skipping): {src_dir}")
                skipped += 1
                continue
            print(f"  plugin: {path_str} -> {dest}")
            copy_plugin(src_dir, dest, dry_run)

        else:
            warnings.append(f"Unknown type '{current_type}': {path_str}")
            skipped += 1
            continue

        copied += 1

    # Print summary
    print()
    print("━" * 60)
    print("Summary:")
    print(f"  Copied:   {copied}")
    print(f"  Skipped:  {skipped}")
    print(f"  Warnings: {len(warnings)}")
    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(f"  WARNING: {w}")
    print("━" * 60)

    # Return 1 if any items were skipped (to surface the gap)
    return 1 if skipped > 0 else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate ORIGINAL artefacts to cognovis/library-core"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without copying",
    )
    parser.add_argument(
        "--library-core",
        type=Path,
        default=Path(os.environ.get("LIBRARY_CORE", "/tmp/cognovis-library-core")),
        help="Path to library-core clone (override with LIBRARY_CORE env var)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("SOURCE_PLUGINS", "/Users/malte/code/claude-code-plugins")),
        help="Path to claude-code-plugins source (override with SOURCE_PLUGINS env var)",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("docs/audit/skills-origin.json"),
        help="Path to audit JSON",
    )
    args = parser.parse_args()

    # Validate inputs
    if not args.audit.exists():
        print(f"ERROR: Audit JSON not found: {args.audit}", file=sys.stderr)
        sys.exit(1)

    if not args.library_core.exists():
        print(f"ERROR: library-core path not found: {args.library_core}", file=sys.stderr)
        sys.exit(1)

    if not args.source.exists():
        print(f"ERROR: source path not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    exit_code = migrate(
        audit_path=args.audit,
        library_core=args.library_core,
        source_root=args.source,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
