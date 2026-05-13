"""
test_standards_drift_check.py — Tests for hooks/standards-drift-check/

Bead: CL-c2d
Tests:
  1. No drift — no output, exit 0
  2. Single drifted standard — one warning line, exit 0 (fail-open)
  3. Multiple standards — only drifted ones emit warnings
  4. Missing cache file — warning with "cache missing" note
  5. Malformed marker — skipped silently (fail-open)
  6. File not present — no error, exit 0
  7. _core.scan_file returns structured results

Run with:
    python3 -m pytest tests/test_standards_drift_check.py -v
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_CORE = REPO_ROOT / "hooks" / "standards-drift-check" / "_core.py"

# Load _core module dynamically for unit testing
import importlib.util


def load_core():
    spec = importlib.util.spec_from_file_location("drift_core", str(HOOK_CORE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def make_standard_block(name: str, body: str, corrupt_hash: str | None = None) -> str:
    """Build a proper STANDARD block."""
    h = corrupt_hash if corrupt_hash else _hash(body)
    return f"<!-- BEGIN STANDARD:{name} v:1 hash:{h} -->\n{body}<!-- END STANDARD:{name} -->\n"


# ---------------------------------------------------------------------------
# Test 1: No drift — no output, exit 0
# ---------------------------------------------------------------------------

def test_no_drift(tmp_path: Path) -> None:
    """scan_file returns no drifted items when block hash matches cache."""
    core = load_core()

    body = "All code must be in English.\n"
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(make_standard_block("english-only", body))

    cache_dir = tmp_path / ".agents" / "standards" / "english-only"
    cache_dir.mkdir(parents=True)
    (cache_dir / "english-only.md").write_text(body)

    results = core.scan_file(agents_md, tmp_path)
    drifted = [r for r in results if r["status"] != "ok"]
    assert len(drifted) == 0


# ---------------------------------------------------------------------------
# Test 2: Single drifted standard — warning emitted
# ---------------------------------------------------------------------------

def test_single_drift(tmp_path: Path) -> None:
    """scan_file returns one drifted item when cache content differs."""
    core = load_core()

    body_installed = "All code must be in English.\n"
    body_cache = "All code must be in English. AND comments.\n"  # updated cache

    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(make_standard_block("english-only", body_installed))

    cache_dir = tmp_path / ".agents" / "standards" / "english-only"
    cache_dir.mkdir(parents=True)
    (cache_dir / "english-only.md").write_text(body_cache)

    results = core.scan_file(agents_md, tmp_path)
    drifted = [r for r in results if r["status"] == "drift"]
    assert len(drifted) == 1
    assert drifted[0]["name"] == "english-only"


# ---------------------------------------------------------------------------
# Test 3: Multiple standards — only drifted ones emit warnings
# ---------------------------------------------------------------------------

def test_multiple_standards_partial_drift(tmp_path: Path) -> None:
    """Only the drifted standard is flagged; the clean one is OK."""
    core = load_core()

    body_english = "All code must be in English.\n"
    body_no_emoji = "No emojis in code.\n"
    body_no_emoji_updated = "No emojis in code or docs.\n"

    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        make_standard_block("english-only", body_english)
        + "\n"
        + make_standard_block("no-emoji", body_no_emoji)
    )

    for name, cache_body in [("english-only", body_english), ("no-emoji", body_no_emoji_updated)]:
        d = tmp_path / ".agents" / "standards" / name
        d.mkdir(parents=True)
        (d / f"{name}.md").write_text(cache_body)

    results = core.scan_file(agents_md, tmp_path)
    statuses = {r["name"]: r["status"] for r in results}
    assert statuses.get("english-only") == "ok"
    assert statuses.get("no-emoji") == "drift"


# ---------------------------------------------------------------------------
# Test 4: Missing cache file — warning with "cache missing" note
# ---------------------------------------------------------------------------

def test_missing_cache(tmp_path: Path) -> None:
    """When cache file is absent, status is 'cache-missing'."""
    core = load_core()

    body = "All code must be in English.\n"
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(make_standard_block("english-only", body))
    # Intentionally do NOT create cache dir

    results = core.scan_file(agents_md, tmp_path)
    assert len(results) == 1
    assert results[0]["status"] == "cache-missing"
    assert results[0]["name"] == "english-only"


# ---------------------------------------------------------------------------
# Test 5: Malformed marker — skipped silently
# ---------------------------------------------------------------------------

def test_malformed_marker_skipped(tmp_path: Path) -> None:
    """A marker without a valid hash field is skipped without error."""
    core = load_core()

    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "<!-- BEGIN STANDARD:bad-entry v:1 -->\nSome content.\n<!-- END STANDARD:bad-entry -->\n"
    )

    results = core.scan_file(agents_md, tmp_path)
    # Should either skip or report an error — must not raise an exception
    # If it reports something, it should not be "drift" (no hash to compare)
    for r in results:
        assert r["status"] in ("ok", "cache-missing", "malformed", "error")


# ---------------------------------------------------------------------------
# Test 6: File not present — no error, returns empty list
# ---------------------------------------------------------------------------

def test_missing_file(tmp_path: Path) -> None:
    """scan_file returns [] if the target file does not exist."""
    core = load_core()
    results = core.scan_file(tmp_path / "NONEXISTENT.md", tmp_path)
    assert results == []


# ---------------------------------------------------------------------------
# Test 7: Warning format matches expected pattern
# ---------------------------------------------------------------------------

def test_warning_format(tmp_path: Path) -> None:
    """format_warning produces the documented warning line format."""
    core = load_core()

    result = {
        "name": "english-only",
        "status": "drift",
        "block_hash": "abc123456789",
        "cache_hash": "def987654321",
        "file": str(tmp_path / "AGENTS.md"),
    }
    warning = core.format_warning(result)
    assert "[standards]" in warning
    assert "english-only" in warning
    assert "drift" in warning.lower()
    assert "/library standard sync english-only" in warning
