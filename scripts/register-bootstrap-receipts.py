#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Record exact global receipts for the irreducible Library bootstrap."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.lockfile import (
    compute_directory_hash,
    find_lockfile,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)


BOOTSTRAP_SKILLS = {
    "library": ".",
    "skill-forge": "skills/skill-forge",
    "agent-forge": "skills/agent-forge",
    "standard-forge": "skills/standard-forge",
    "script-forge": "skills/script-forge",
    "hook-forge": "skills/hook-forge",
}
HARNESS_SKILL_DIRS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".opencode/skills",
)


def source_commit(meta_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(meta_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "local"


def matching_links(home: Path, name: str, source: Path) -> list[Path]:
    matches: list[Path] = []
    for relative_root in HARNESS_SKILL_DIRS:
        candidate = home / relative_root / name
        if candidate.is_symlink() and candidate.resolve() == source.resolve():
            matches.append(candidate)
    return sorted(matches)


def register(meta_root: Path, home: Path) -> list[str]:
    lock_path = find_lockfile(global_scope=True)
    lock = load_lockfile(lock_path)
    commit = source_commit(meta_root)
    registered: list[str] = []
    for name, relative_source in BOOTSTRAP_SKILLS.items():
        source = (meta_root / relative_source).resolve()
        links = matching_links(home, name, source)
        if not links:
            continue
        entry = make_entry(
            name=name,
            primitive_type="skill",
            catalog_identity="https://github.com/cognovis/library",
            marketplace="platform-bootstrap",
            source=str(source),
            source_commit=commit,
            cache_path="",
            install_target=str(links[0]),
            checksum_sha256=compute_directory_hash(source),
            checksum_type="directory",
            content_sha256=compute_directory_hash(source),
            install_mode="symlink",
            license_id="proprietary",
            bridge_symlinks=[f"{link} -> {source}" for link in links[1:]],
        )
        upsert_entry(lock, entry)
        receipt = next(
            item for item in lock["receipts"] if item["id"] == f"skill:{name}"
        )
        receipt["adopted"] = True
        receipt["bootstrap_owned"] = True
        registered.append(name)
    save_lockfile(lock_path, lock)
    return registered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta-root", type=Path, required=True)
    args = parser.parse_args()
    registered = register(args.meta_root.resolve(), Path.home())
    print("Bootstrap receipts: " + (", ".join(registered) if registered else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
