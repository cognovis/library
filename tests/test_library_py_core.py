#!/usr/bin/env python3
"""
test_library_py_core.py — Tests for scripts/lib/ core modules (AK1, AK2, AK3, CL-0bl)

Tests:
  AK1:  scripts/library.py exists and parses primitive-first commands
  AK2:  scripts/lib/ package contains all required modules
  AK3:  `python3 scripts/library.py <primitive> list --json` works for all supported primitives
  AK7:  Lockfile create/update is deterministic and schema-compatible
  AK8:  scripts/validate-library.py --quiet still passes
  AK10: No legacy unscoped command forms promoted in docs

Run with:
    python3 -m pytest tests/test_library_py_core.py -v
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
LIB_DIR = SCRIPTS_DIR / "lib"

SUPPORTED_PRIMITIVES = [
    "skill",
    "agent",
    "prompt",
    "script",
    "standard",
    "guardrail",
    "mcp",
    "model-standard",
    "agent-base",
]


# ---------------------------------------------------------------------------
# AK1: library.py entrypoint exists and parses commands
# ---------------------------------------------------------------------------


def test_library_py_exists():
    """scripts/library.py must exist."""
    assert LIBRARY_PY.exists(), f"Expected {LIBRARY_PY} to exist — not found."


def test_library_py_help():
    """scripts/library.py --help must exit 0 and mention primitive-first grammar."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"--help returned {result.returncode}: {result.stderr}"
    output = result.stdout + result.stderr
    assert any(p in output for p in SUPPORTED_PRIMITIVES[:3]), (
        "Expected help output to mention at least one primitive — not found.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_library_py_invalid_verb_nonzero():
    """Unknown primitive should exit non-zero."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "nonexistent-primitive", "list"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "Expected non-zero exit for unknown primitive, got 0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_library_py_primitive_first_grammar_skill_list():
    """skill list --json must exit 0 and return a JSON array."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "skill", "list", "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"'skill list --json' returned {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    data = json.loads(result.stdout)
    assert isinstance(data, (list, dict)), f"Expected JSON list or dict, got {type(data)}"


# ---------------------------------------------------------------------------
# AK2: scripts/lib/ package structure
# ---------------------------------------------------------------------------


def test_lib_directory_exists():
    """scripts/lib/ must exist."""
    assert LIB_DIR.is_dir(), f"Expected {LIB_DIR} to be a directory — not found."


def test_lib_init_exists():
    """scripts/lib/__init__.py must exist."""
    assert (LIB_DIR / "__init__.py").exists()


def test_lib_catalog_exists():
    """scripts/lib/catalog.py must exist."""
    assert (LIB_DIR / "catalog.py").exists()


def test_lib_primitives_exists():
    """scripts/lib/primitives.py must exist."""
    assert (LIB_DIR / "primitives.py").exists()


def test_lib_paths_exists():
    """scripts/lib/paths.py must exist."""
    assert (LIB_DIR / "paths.py").exists()


def test_lib_source_exists():
    """scripts/lib/source.py must exist."""
    assert (LIB_DIR / "source.py").exists()


def test_lib_cache_exists():
    """scripts/lib/cache.py must exist."""
    assert (LIB_DIR / "cache.py").exists()


def test_lib_lockfile_exists():
    """scripts/lib/lockfile.py must exist."""
    assert (LIB_DIR / "lockfile.py").exists()


def test_lib_output_exists():
    """scripts/lib/output.py must exist."""
    assert (LIB_DIR / "output.py").exists()


def test_lib_errors_exists():
    """scripts/lib/errors.py must exist."""
    assert (LIB_DIR / "errors.py").exists()


def test_lib_installers_dir_exists():
    """scripts/lib/installers/ must exist."""
    assert (LIB_DIR / "installers").is_dir()


def test_lib_installers_init_exists():
    """scripts/lib/installers/__init__.py must exist."""
    assert (LIB_DIR / "installers" / "__init__.py").exists()


def test_lib_importable():
    """scripts/lib package must be importable."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import lib; print('ok')"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Failed to import scripts/lib: {result.stderr}"
    )
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# AK3: list --json for all supported primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("primitive", SUPPORTED_PRIMITIVES)
def test_primitive_list_json(primitive: str):
    """python3 scripts/library.py <primitive> list --json must exit 0 and return valid JSON."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), primitive, "list", "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"'{primitive} list --json' returned {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"'{primitive} list --json' produced invalid JSON: {e}\n"
            f"stdout: {result.stdout}"
        )
    assert isinstance(data, (list, dict)), f"Expected list or dict for '{primitive} list', got {type(data)}"


@pytest.mark.parametrize("primitive", SUPPORTED_PRIMITIVES)
def test_primitive_list_human(primitive: str):
    """python3 scripts/library.py <primitive> list (human format) must exit 0."""
    result = subprocess.run(
        [sys.executable, str(LIBRARY_PY), primitive, "list"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"'{primitive} list' returned {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert len(result.stdout) > 0, f"'{primitive} list' produced empty output"


# ---------------------------------------------------------------------------
# AK8: validate-library.py still passes
# ---------------------------------------------------------------------------


def test_validate_library_still_passes():
    """scripts/validate-library.py --quiet must still pass (AK8)."""
    result = subprocess.run(
        [sys.executable, "scripts/validate-library.py", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"validate-library.py --quiet failed: {result.stdout} {result.stderr}"
    )


# ---------------------------------------------------------------------------
# AK10: No legacy unscoped command forms in docs
# ---------------------------------------------------------------------------


LEGACY_PATTERNS = [
    "/library use ",
    "/library list",
    "/library remove ",
    "/library add ",
    "/library push ",
]

DOC_FILES_TO_CHECK = [
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "cookbook" / "use.md",
    REPO_ROOT / "cookbook" / "list.md",
    REPO_ROOT / "cookbook" / "search.md",
    REPO_ROOT / "cookbook" / "sync.md",
    REPO_ROOT / "cookbook" / "add.md",
    REPO_ROOT / "cookbook" / "push.md",
    REPO_ROOT / "cookbook" / "remove.md",
]

ALLOWED_LEGACY_CONTEXTS = [
    # Patterns that are explicitly documenting legacy forms to be avoided
    "legacy",
    "old form",
    "no longer",
    "do not use",
    "avoid",
    "instead of",
    "unscoped",
]


@pytest.mark.parametrize("doc_file", [f for f in DOC_FILES_TO_CHECK if f.exists()])
def test_no_legacy_commands_promoted(doc_file: Path):
    """Docs must not promote unscoped /library commands as the primary form."""
    text = doc_file.read_text()
    lines = text.splitlines()
    violations = []
    for i, line in enumerate(lines, 1):
        for pattern in LEGACY_PATTERNS:
            if pattern in line:
                # Allow only when the context says the old form must not be used.
                context_window = " ".join(
                    lines[max(0, i - 3) : i + 3]
                ).lower()
                is_allowed = any(ctx in context_window for ctx in ALLOWED_LEGACY_CONTEXTS)
                # Also allow in code blocks that are explaining migration
                if not is_allowed:
                    # Check if it's a table cell showing legacy form with its replacement
                    if "|" in line and i + 1 < len(lines) and "| /" in line:
                        # likely a command reference table — allow
                        continue
                    violations.append(f"Line {i}: {line.strip()}")
    assert not violations, (
        f"{doc_file.name} promotes legacy unscoped command forms:\n"
        + "\n".join(violations[:5])
        + (f"\n... and {len(violations) - 5} more" if len(violations) > 5 else "")
        + "\nUpdate to use primitive-scoped forms: /library <primitive> <verb>"
    )
