"""
compat.py — Compatibility pre-install gate for library primitives.

Parses the `compatibility` field from catalog entries (agentskills.io standard,
e.g. ``"claude_code>=4.0"``) and aborts with EXIT_DEPENDENCY_MISSING if the
current harness does not satisfy the declared requirement.

Best-effort version detection: when the harness version cannot be determined,
a warning is emitted to stderr and installation proceeds (AC4).
"""

from __future__ import annotations

import re
import subprocess
import sys
import warnings
from typing import Tuple, Optional

from .errors import EXIT_DEPENDENCY_MISSING, LibraryError

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class CompatibilityError(LibraryError):
    """Raised when a catalog entry's compatibility requirement is not satisfied."""

    def __init__(self, requirement: str, harness: str, current_version: str) -> None:
        super().__init__(
            f"Compatibility requirement not satisfied: '{requirement}'. "
            f"Current {harness} version: {current_version}. "
            "Upgrade the harness or use a compatible primitive.",
            exit_code=EXIT_DEPENDENCY_MISSING,
        )
        self.requirement = requirement
        self.harness = harness
        self.current_version = current_version


# ---------------------------------------------------------------------------
# Version utilities
# ---------------------------------------------------------------------------

_OPERATOR_PATTERN = re.compile(
    r"^([a-z_][a-z0-9_-]*)(>=|<=|==|!=|>|<)(.+)$"
)

_VERSION_PART = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_compatibility(compat_str: str) -> Tuple[str, str, str]:
    """Parse a compatibility string into ``(harness, operator, version)``.

    Supports operators: ``>=``, ``<=``, ``==``, ``!=``, ``>``, ``<``.
    Harness identifier is ``[a-z_][a-z0-9_-]*``.

    Raises:
        ValueError: If the string does not match the expected format.
    """
    if not compat_str:
        raise ValueError("Empty compatibility string.")
    m = _OPERATOR_PATTERN.match(compat_str.strip())
    if m is None:
        raise ValueError(
            f"Cannot parse compatibility string '{compat_str}'. "
            "Expected format: <harness><op><version> (e.g. 'claude_code>=4.0')."
        )
    return m.group(1), m.group(2), m.group(3)


def _parse_version_tuple(version_str: str) -> Tuple[int, int, int]:
    """Convert a version string to an (major, minor, patch) int tuple."""
    m = _VERSION_PART.match(version_str.strip())
    if m is None:
        return (0, 0, 0)
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) is not None else 0
    patch = int(m.group(3)) if m.group(3) is not None else 0
    return (major, minor, patch)


def _compare_versions(current: str, operator: str, required: str) -> bool:
    """Return True if ``current <operator> required``."""
    cur = _parse_version_tuple(current)
    req = _parse_version_tuple(required)
    if operator == ">=":
        return cur >= req
    if operator == "<=":
        return cur <= req
    if operator == "==":
        return cur == req
    if operator == "!=":
        return cur != req
    if operator == ">":
        return cur > req
    if operator == "<":
        return cur < req
    return True  # unknown operator — pass through


# ---------------------------------------------------------------------------
# Harness version detection
# ---------------------------------------------------------------------------

#: Map harness identifier → (command, version-extraction regex)
_HARNESS_VERSION_COMMANDS: dict[str, tuple[list[str], str]] = {
    "claude_code": (["claude", "--version"], r"(\d+\.\d+[\.\d]*)"),
    "codex": (["codex", "--version"], r"(\d+\.\d+[\.\d]*)"),
    "opencode": (["opencode", "--version"], r"(\d+\.\d+[\.\d]*)"),
    "cursor": (["cursor", "--version"], r"(\d+\.\d+[\.\d]*)"),
}


def detect_harness_version(harness: str) -> Optional[str]:
    """Return the current version string for *harness*, or ``None`` if unknown.

    This function is best-effort: it never raises; failures are silently
    suppressed so that a missing or non-versioned binary does not block
    installation.
    """
    spec = _HARNESS_VERSION_COMMANDS.get(harness)
    if spec is None:
        return None
    cmd, pattern = spec
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
        m = re.search(pattern, output)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# Gate function
# ---------------------------------------------------------------------------


def check_compatibility_gate(
    entry: dict,
    harness: str,
) -> None:
    """Check the ``compatibility`` field of a catalog *entry* against *harness*.

    Behaviour:
    - ``compatibility`` absent → no-op (backward-compatible).
    - ``compatibility`` targets a different harness → no-op (only the declared
      harness is checked; installing for ``codex`` with a ``claude_code>=4.0``
      constraint is allowed).
    - Version detection fails → emit a warning to stderr and proceed (AC4).
    - Version constraint unsatisfied → raise :class:`CompatibilityError`
      (exit code 4).

    Args:
        entry:   Catalog entry dict (must have a ``"compatibility"`` key to
                 trigger a check).
        harness: The harness being targeted (e.g. ``"claude_code"``).

    Raises:
        CompatibilityError: If the current harness version does not satisfy
            the declared requirement.
    """
    compat_str = entry.get("compatibility")
    if not compat_str:
        return

    try:
        req_harness, operator, req_version = parse_compatibility(compat_str)
    except ValueError:
        # Malformed compatibility string — warn and skip (do not block install).
        print(
            f"Warning: cannot parse compatibility string '{compat_str}' "
            f"for '{entry.get('name', '?')}' — skipping check.",
            file=sys.stderr,
        )
        return

    # Only check when the constraint targets the active harness.
    # Normalize: "all" harness triggers the check for any constraint.
    if req_harness != harness and harness != "all":
        return

    current_version = detect_harness_version(req_harness)

    if current_version is None:
        # Best-effort: version unknown — warn and proceed (AC4).
        print(
            f"Warning: cannot determine version of '{req_harness}' — "
            f"skipping compatibility check for '{compat_str}'.",
            file=sys.stderr,
        )
        return

    if not _compare_versions(current_version, operator, req_version):
        raise CompatibilityError(
            requirement=compat_str,
            harness=req_harness,
            current_version=current_version,
        )
