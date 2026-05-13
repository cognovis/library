"""
test_agents_md_block.py — Tests for scripts/agents-md-block.py

Bead: CL-c2d
Tests:
  1. Fresh insert writes correct markers and content
  2. Idempotent re-insert (same content) does nothing
  3. Update changes content and hash
  4. Remove leaves no trace of markers or content
  5. Check exit 0 when block present + hash matches
  6. Check exit 1 when block missing
  7. Check exit 1 when hash mismatch (drift)
  8. Insert to non-existent file creates it
  9. Hash is sha256 first 12 chars of content body
  10. Multiple standards in one file — remove only removes the target

Run with:
    python3 -m pytest tests/test_agents_md_block.py -v
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "agents-md-block.py"


def _hash(content: str) -> str:
    """Compute sha256 hash of content, first 12 chars."""
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run agents-md-block.py with given args. Returns (rc, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Test 1: Fresh insert writes correct markers and content
# ---------------------------------------------------------------------------

def test_insert_fresh(tmp_path: Path) -> None:
    """Insert into an empty file creates the BEGIN/END markers."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# My Agents\n\nSome preamble.\n")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    rc, out, err = run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert rc == 0, f"insert failed: {err}"

    result = target.read_text()
    assert "<!-- BEGIN STANDARD:english-only" in result
    assert "<!-- END STANDARD:english-only -->" in result
    assert "All code must be in English." in result


def test_insert_fresh_marker_has_version_and_hash(tmp_path: Path) -> None:
    """Marker line contains v: and hash: fields."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_file = tmp_path / "english-only.md"
    body = "All code must be in English.\n"
    content_file.write_text(body)

    rc, _, _ = run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert rc == 0

    result = target.read_text()
    expected_hash = _hash(body)
    assert f"hash:{expected_hash}" in result
    assert "v:1" in result


# ---------------------------------------------------------------------------
# Test 2: Idempotent re-insert
# ---------------------------------------------------------------------------

def test_insert_idempotent(tmp_path: Path) -> None:
    """Re-inserting same content does not duplicate the block."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    first_text = target.read_text()

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    second_text = target.read_text()

    assert first_text == second_text
    assert second_text.count("<!-- BEGIN STANDARD:english-only") == 1


# ---------------------------------------------------------------------------
# Test 3: Update changes content and hash
# ---------------------------------------------------------------------------

def test_update_changes_content(tmp_path: Path) -> None:
    """Update replaces the block body and updates the hash in the marker."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_v1 = tmp_path / "english-only-v1.md"
    content_v1.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_v1}"])

    content_v2 = tmp_path / "english-only-v2.md"
    new_body = "All code must be in English. Comments too.\n"
    content_v2.write_text(new_body)

    rc, _, err = run(["update", "--name=english-only", f"--file={target}", f"--content={content_v2}"])
    assert rc == 0, f"update failed: {err}"

    result = target.read_text()
    assert "Comments too." in result
    assert _hash(new_body) in result
    # Old hash should not be present
    assert _hash("All code must be in English.\n") not in result


# ---------------------------------------------------------------------------
# Test 4: Remove leaves no trace
# ---------------------------------------------------------------------------

def test_remove_leaves_no_trace(tmp_path: Path) -> None:
    """Remove deletes the BEGIN/END block entirely; surrounding content stays."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# Preamble\n\nBefore content.\n")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert "<!-- BEGIN STANDARD:english-only" in target.read_text()

    rc, _, err = run(["remove", "--name=english-only", f"--file={target}"])
    assert rc == 0, f"remove failed: {err}"

    result = target.read_text()
    assert "<!-- BEGIN STANDARD:english-only" not in result
    assert "<!-- END STANDARD:english-only -->" not in result
    assert "All code must be in English." not in result
    # Preamble should still be present
    assert "Before content." in result


def test_remove_nonexistent_is_ok(tmp_path: Path) -> None:
    """Remove a block that does not exist exits 0 (idempotent)."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# Nothing here\n")

    rc, _, _ = run(["remove", "--name=english-only", f"--file={target}"])
    assert rc == 0


# ---------------------------------------------------------------------------
# Test 5: Check exit 0 when block present and hash matches
# ---------------------------------------------------------------------------

def test_check_pass(tmp_path: Path) -> None:
    """check exits 0 when block is present and hash matches."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])

    rc, out, _ = run(["check", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert rc == 0


# ---------------------------------------------------------------------------
# Test 6: Check exit 1 when block missing
# ---------------------------------------------------------------------------

def test_check_missing_block(tmp_path: Path) -> None:
    """check exits 1 when block does not exist in file."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# Nothing here\n")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    rc, _, _ = run(["check", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert rc == 1


# ---------------------------------------------------------------------------
# Test 7: Check exit 1 when hash mismatch (drift)
# ---------------------------------------------------------------------------

def test_check_drift(tmp_path: Path) -> None:
    """check exits 1 when block exists but content has drifted."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_v1 = tmp_path / "english-only.md"
    content_v1.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_v1}"])

    # Manually mutate the block content to simulate drift
    text = target.read_text()
    text = text.replace("All code must be in English.", "All code must be in GERMAN.")
    target.write_text(text)

    rc, out, _ = run(["check", "--name=english-only", f"--file={target}", f"--content={content_v1}"])
    assert rc == 1
    assert "drift" in out.lower() or "mismatch" in out.lower() or rc == 1


# ---------------------------------------------------------------------------
# Test 8: Insert to non-existent file creates it
# ---------------------------------------------------------------------------

def test_insert_creates_file(tmp_path: Path) -> None:
    """Insert creates the target file if it does not exist."""
    target = tmp_path / "NEW_AGENTS.md"
    assert not target.exists()

    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    rc, _, err = run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])
    assert rc == 0, f"insert failed: {err}"
    assert target.exists()
    assert "<!-- BEGIN STANDARD:english-only" in target.read_text()


# ---------------------------------------------------------------------------
# Test 9: Hash is sha256 first 12 chars of content body
# ---------------------------------------------------------------------------

def test_hash_length_12(tmp_path: Path) -> None:
    """The embedded hash is exactly 12 hex chars."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")
    content_file = tmp_path / "english-only.md"
    content_file.write_text("All code must be in English.\n")

    run(["insert", "--name=english-only", f"--file={target}", f"--content={content_file}"])

    text = target.read_text()
    import re
    match = re.search(r"hash:([0-9a-f]+)", text)
    assert match, "No hash found in marker"
    assert len(match.group(1)) == 12


# ---------------------------------------------------------------------------
# Test 10: Multiple standards — remove only removes target
# ---------------------------------------------------------------------------

def test_remove_only_target(tmp_path: Path) -> None:
    """Removing one standard leaves other standards intact."""
    target = tmp_path / "AGENTS.md"
    target.write_text("")

    for name, body in [("english-only", "All code in English.\n"), ("no-emoji", "No emojis in code.\n")]:
        cf = tmp_path / f"{name}.md"
        cf.write_text(body)
        run(["insert", f"--name={name}", f"--file={target}", f"--content={cf}"])

    assert "<!-- BEGIN STANDARD:english-only" in target.read_text()
    assert "<!-- BEGIN STANDARD:no-emoji" in target.read_text()

    run(["remove", "--name=english-only", f"--file={target}"])

    result = target.read_text()
    assert "<!-- BEGIN STANDARD:english-only" not in result
    assert "<!-- BEGIN STANDARD:no-emoji" in result
    assert "No emojis in code." in result
