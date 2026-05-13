"""
Shared core for the standards-drift-check SessionStart hook.

Bead: CL-c2d — Standards compose-on-install

Scans markdown files for <!-- BEGIN STANDARD:<name> ... hash:<X> --> markers,
locates the cached source file, and compares hashes to detect drift.

Called by harness-specific wrappers (claude-code.py, codex-cli.py).

Fail-open: any per-file or per-block error is recorded in the result with
status='error' and never raises. The hook always exits 0.

Target runtime: <50ms for typical projects.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_LENGTH = 12  # Must match agents-md-block.py

# Files to scan per project + global.
# Does NOT follow @-imports — each composed file is its own scan target.
_PROJECT_SCAN_FILES = ("AGENTS.md", "CLAUDE.md")
_GLOBAL_SCAN_FILES = (
    Path.home() / ".agents" / "AGENTS.md",
    Path.home() / ".claude" / "CLAUDE.md",
)

# Pattern matching the BEGIN marker line for any STANDARD block.
_MARKER_RE = re.compile(
    r"<!-- BEGIN STANDARD:(?P<name>[^\s>]+)\s+v:(?P<version>[^\s>]+)\s+hash:(?P<hash>[0-9a-f]+)\s*-->"
)


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:HASH_LENGTH]


# ---------------------------------------------------------------------------
# Cache resolution
# ---------------------------------------------------------------------------

def _find_cache_file(name: str, project_root: Path) -> Path | None:
    """Locate the cached standard source file.

    Search order:
      1. <project_root>/.agents/standards/<name>/<name>.md
      2. ~/.agents/standards/<name>/<name>.md
    """
    candidates = [
        project_root / ".agents" / "standards" / name / f"{name}.md",
        Path.home() / ".agents" / "standards" / name / f"{name}.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Block body extraction
# ---------------------------------------------------------------------------

def _extract_body(file_text: str, name: str) -> str | None:
    """Extract the body between BEGIN and END markers for the named standard.

    Returns the body string (including trailing newline) or None if not found.
    """
    end_marker = f"<!-- END STANDARD:{name} -->"
    # Find the BEGIN marker line for this standard
    for m in _MARKER_RE.finditer(file_text):
        if m.group("name") != name:
            continue
        # Find the position after the marker line's newline
        start_of_body = file_text.index("\n", m.end()) + 1
        end_pos = file_text.find(end_marker, start_of_body)
        if end_pos == -1:
            return None
        return file_text[start_of_body:end_pos]
    return None


# ---------------------------------------------------------------------------
# Single-file scanner
# ---------------------------------------------------------------------------

def scan_file(path: Path, project_root: Path) -> list[dict[str, Any]]:
    """Scan a single file for STANDARD markers and check each for drift.

    Returns a list of result dicts, one per STANDARD block found:
      {
        "name": str,
        "status": "ok" | "drift" | "cache-missing" | "malformed" | "error",
        "block_hash": str | None,
        "cache_hash": str | None,
        "file": str,
        "message": str,
      }
    """
    results: list[dict[str, Any]] = []

    if not path.exists():
        return results

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return results  # fail-open: unreadable file → skip

    for m in _MARKER_RE.finditer(text):
        name = m.group("name")
        marker_hash = m.group("hash")

        if not marker_hash or len(marker_hash) < 8:
            results.append({
                "name": name,
                "status": "malformed",
                "block_hash": None,
                "cache_hash": None,
                "file": str(path),
                "message": f"Malformed hash in marker for STANDARD:{name}",
            })
            continue

        try:
            cache_file = _find_cache_file(name, project_root)
            if cache_file is None:
                results.append({
                    "name": name,
                    "status": "cache-missing",
                    "block_hash": marker_hash,
                    "cache_hash": None,
                    "file": str(path),
                    "message": f"Cache file not found for STANDARD:{name}",
                })
                continue

            cache_content = cache_file.read_text(encoding="utf-8")
            cache_hash = _compute_hash(cache_content)

            if cache_hash != marker_hash:
                results.append({
                    "name": name,
                    "status": "drift",
                    "block_hash": marker_hash,
                    "cache_hash": cache_hash,
                    "file": str(path),
                    "message": (
                        f"STANDARD:{name} block:{marker_hash} != cache:{cache_hash}"
                    ),
                })
            else:
                results.append({
                    "name": name,
                    "status": "ok",
                    "block_hash": marker_hash,
                    "cache_hash": cache_hash,
                    "file": str(path),
                    "message": "ok",
                })

        except Exception as exc:
            results.append({
                "name": name,
                "status": "error",
                "block_hash": marker_hash,
                "cache_hash": None,
                "file": str(path),
                "message": str(exc),
            })

    return results


# ---------------------------------------------------------------------------
# Warning formatter
# ---------------------------------------------------------------------------

def format_warning(result: dict[str, Any]) -> str:
    """Return the single-line warning string for a drifted/missing standard."""
    name = result["name"]
    block_hash = result.get("block_hash", "?")
    cache_hash = result.get("cache_hash", "?")
    status = result["status"]

    if status == "drift":
        return (
            f"[standards] drift detected: {name} (block:{block_hash} != cache:{cache_hash}). "
            f"Run `/library standard sync {name}` to reconcile."
        )
    elif status == "cache-missing":
        return (
            f"[standards] cache missing: {name} (block:{block_hash}, cache not found). "
            f"Run `/library standard sync {name}` to reconcile."
        )
    else:
        return f"[standards] {status}: {name} — {result.get('message', '')}"


# ---------------------------------------------------------------------------
# Main scan entry-point for harness adapters
# ---------------------------------------------------------------------------

def run_drift_check(cwd: Path) -> list[str]:
    """Scan all standard files and return warning lines for drift/missing.

    Called by harness adapters (claude-code.py, codex-cli.py).
    Returns list of warning strings (empty if all clean).
    Fail-open: never raises.
    """
    warnings: list[str] = []

    # Project files
    for rel in _PROJECT_SCAN_FILES:
        p = cwd / rel
        try:
            for result in scan_file(p, cwd):
                if result["status"] not in ("ok",):
                    warnings.append(format_warning(result))
        except Exception:
            pass  # fail-open

    # Global files
    for p in _GLOBAL_SCAN_FILES:
        try:
            for result in scan_file(p, cwd):
                if result["status"] not in ("ok",):
                    warnings.append(format_warning(result))
        except Exception:
            pass  # fail-open

    return warnings
