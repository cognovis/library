#!/usr/bin/env python3
"""
agents-md-block.py — Compose standards blocks into AGENTS.md / CLAUDE.md at install time.

Bead: CL-c2d — Standards compose-on-install

Subcommands:
  insert   Write a <!-- BEGIN STANDARD:<name> --> block. Idempotent if content unchanged.
  update   Replace existing block with new content and updated hash.
  remove   Delete the block (idempotent if not present).
  check    Exit 0 if block present and hash matches; exit 1 otherwise.

Marker format (aligns with BEADS-INTEGRATION convention):
  <!-- BEGIN STANDARD:<name> v:<version> hash:<sha256-12> -->
  <content body>
  <!-- END STANDARD:<name> -->

Hash: sha256 over the literal content body (not including markers), first 12 hex chars.

Usage:
  agents-md-block.py insert --name=<name> --file=<target> --content=<source>
  agents-md-block.py update --name=<name> --file=<target> --content=<source>
  agents-md-block.py remove --name=<name> --file=<target>
  agents-md-block.py check  --name=<name> --file=<target> --content=<source>

Exit codes:
  0 — success (or block-present for check)
  1 — check failed (missing or drift)
  2 — invalid arguments or I/O error
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKER_VERSION = "1"
HASH_LENGTH = 12  # chars — matches BEADS-INTEGRATION standard (standardised from 8→12 in CL-c2d)


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def compute_hash(content: str) -> str:
    """Return sha256 of content (utf-8 encoded), first HASH_LENGTH hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:HASH_LENGTH]


# ---------------------------------------------------------------------------
# Marker construction
# ---------------------------------------------------------------------------

def begin_marker(name: str, version: str, content_hash: str) -> str:
    return f"<!-- BEGIN STANDARD:{name} v:{version} hash:{content_hash} -->"


def end_marker(name: str) -> str:
    return f"<!-- END STANDARD:{name} -->"


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------

def _block_pattern(name: str) -> re.Pattern[str]:
    """Return a compiled regex that matches the full named block (including markers)."""
    # Non-greedy match between BEGIN and END markers; DOTALL so '.' matches newlines.
    escaped = re.escape(f"<!-- BEGIN STANDARD:{name}")
    end_escaped = re.escape(end_marker(name))
    return re.compile(
        rf"{escaped}[^\n]*\n.*?{end_escaped}",
        re.DOTALL,
    )


def _find_block(text: str, name: str) -> re.Match[str] | None:
    """Return the regex match for the named block, or None if not found."""
    return _block_pattern(name).search(text)


def _extract_hash_from_marker(begin_line: str) -> str | None:
    """Extract the hash value from a BEGIN marker line."""
    m = re.search(r"hash:([0-9a-f]+)", begin_line)
    return m.group(1) if m else None


def _extract_body_from_block(block_text: str, name: str) -> str:
    """Return the content body (between markers) from a matched block.

    The body includes the trailing newline that precedes the END marker,
    matching exactly what build_block() stores (body is always terminated
    with \\n before the END marker line).
    """
    # Strip the first line (BEGIN marker) and the last line (END marker).
    # The remaining text, including its trailing newline before END, is the body.
    begin_end = begin_marker(name, MARKER_VERSION, "")  # placeholder — we just need to find the first \n
    first_newline = block_text.index("\n")
    last_marker = "\n" + end_marker(name)
    end_pos = block_text.rfind(last_marker)
    if end_pos == -1:
        # Fallback: split by lines
        lines = block_text.split("\n")
        body_lines = lines[1:-1]
        return "\n".join(body_lines) + "\n"
    # body = text between first \n and the \n that starts the END marker
    return block_text[first_newline + 1:end_pos + 1]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def read_file(path: Path) -> str:
    """Read file; return empty string if it does not exist."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_file(path: Path, text: str) -> None:
    """Write text to path, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_block(name: str, content: str) -> str:
    """Return the full block text (BEGIN marker + content + END marker)."""
    h = compute_hash(content)
    begin = begin_marker(name, MARKER_VERSION, h)
    end = end_marker(name)
    # Ensure content ends with exactly one newline before END marker
    body = content if content.endswith("\n") else content + "\n"
    return f"{begin}\n{body}{end}"


def cmd_insert(name: str, target: Path, content_path: Path) -> int:
    """Insert standard block into target file. Idempotent if content unchanged."""
    content = content_path.read_text(encoding="utf-8")
    file_text = read_file(target)

    existing = _find_block(file_text, name)
    if existing:
        # Check if hash matches; if so, nothing to do.
        block_text = existing.group(0)
        first_line = block_text.split("\n", 1)[0]
        existing_hash = _extract_hash_from_marker(first_line)
        current_hash = compute_hash(content)
        if existing_hash == current_hash:
            # Idempotent — no change needed.
            return 0
        # Content changed — behave like update.
        new_block = build_block(name, content)
        new_text = _block_pattern(name).sub(new_block, file_text, count=1)
        write_file(target, new_text)
        return 0

    # Block not present — append.
    new_block = build_block(name, content)
    separator = "\n" if file_text and not file_text.endswith("\n\n") else ""
    if file_text and not file_text.endswith("\n"):
        separator = "\n" + separator
    new_text = file_text + separator + new_block + "\n"
    write_file(target, new_text)
    return 0


def cmd_update(name: str, target: Path, content_path: Path) -> int:
    """Replace existing block with updated content and hash.

    If block does not exist, inserts it (same as insert).
    """
    return cmd_insert(name, target, content_path)


def cmd_remove(name: str, target: Path) -> int:
    """Remove the named block from target file. Idempotent if not present."""
    if not target.exists():
        return 0
    file_text = target.read_text(encoding="utf-8")
    existing = _find_block(file_text, name)
    if not existing:
        return 0

    # Remove the block and any immediately surrounding blank line.
    block_text = existing.group(0)
    new_text = file_text.replace(block_text, "")
    # Clean up double blank lines left by removal.
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    new_text = new_text.rstrip("\n") + "\n" if new_text.strip() else ""
    write_file(target, new_text)
    return 0


def cmd_check(name: str, target: Path, content_path: Path) -> int:
    """Check block presence and hash. Exit 0 if OK; exit 1 if missing or drifted.

    Drift is detected two ways:
    1. Block body hash != hash embedded in the BEGIN marker (block was manually edited).
    2. Content-file hash != hash embedded in the BEGIN marker (source file was updated).

    Either condition triggers exit 1 with a drift message.
    """
    if not target.exists():
        print(f"check: MISSING — {target} does not exist", file=sys.stderr)
        return 1

    content = content_path.read_text(encoding="utf-8")
    file_text = target.read_text(encoding="utf-8")
    existing = _find_block(file_text, name)

    if not existing:
        print(f"check: MISSING — block STANDARD:{name} not found in {target}", file=sys.stderr)
        return 1

    block_text = existing.group(0)
    first_line = block_text.split("\n", 1)[0]
    marker_hash = _extract_hash_from_marker(first_line)

    # Compute hash of what is actually in the block body right now.
    body = _extract_body_from_block(block_text, name)
    block_body_hash = compute_hash(body)

    # Compute hash of the supplied content file.
    content_hash = compute_hash(content)

    # Drift: block body was manually edited (block_body_hash != marker_hash)
    if marker_hash != block_body_hash:
        print(
            f"check: DRIFT — STANDARD:{name} block body mismatch "
            f"(marker:{marker_hash} != actual:{block_body_hash}). "
            f"Run `/library standard sync {name}` to reconcile.",
            file=sys.stderr,
        )
        return 1

    # Drift: source file has newer content than what was installed (content_hash != marker_hash)
    if content_hash != marker_hash:
        print(
            f"check: DRIFT — STANDARD:{name} source updated "
            f"(block:{marker_hash} != cache:{content_hash}). "
            f"Run `/library standard sync {name}` to reconcile.",
            file=sys.stderr,
        )
        return 1

    print(f"check: OK — STANDARD:{name} hash:{content_hash}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agents-md-block.py",
        description="Manage STANDARD blocks in AGENTS.md / CLAUDE.md files.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    for verb in ("insert", "update"):
        p = sub.add_parser(verb, help=f"{verb} a STANDARD block")
        p.add_argument("--name", required=True, help="Standard name (e.g. english-only)")
        p.add_argument("--file", required=True, type=Path, help="Target markdown file")
        p.add_argument("--content", required=True, type=Path, help="Source content file")

    p_remove = sub.add_parser("remove", help="Remove a STANDARD block")
    p_remove.add_argument("--name", required=True, help="Standard name")
    p_remove.add_argument("--file", required=True, type=Path, help="Target markdown file")

    p_check = sub.add_parser("check", help="Check block presence and hash (exit 1 on drift/missing)")
    p_check.add_argument("--name", required=True, help="Standard name")
    p_check.add_argument("--file", required=True, type=Path, help="Target markdown file")
    p_check.add_argument("--content", required=True, type=Path, help="Source content file (for hash comparison)")

    args = parser.parse_args(argv)

    try:
        if args.subcommand in ("insert", "update"):
            return cmd_insert(args.name, args.file, args.content)
        elif args.subcommand == "remove":
            return cmd_remove(args.name, args.file)
        elif args.subcommand == "check":
            return cmd_check(args.name, args.file, args.content)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
