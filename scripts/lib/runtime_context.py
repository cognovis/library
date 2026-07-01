"""
runtime_context.py - Runtime environment detection for library lifecycle commands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


GAS_CITY_ENV_KEYS = (
    "GC_CITY",
    "GC_CITY_ROOT",
    "GC_SESSION_ID",
    "GASCITY_CITY",
    "GASCITY_CITY_ROOT",
    "GASCITY_SESSION_ID",
)

GAS_CITY_RUNTIME_RISK = "gas_city_global_runtime"

GLOBAL_RUNTIME_PRIMITIVES = frozenset(
    {
        "agent",
        "agent-base",
        "guardrail",
        "mcp",
        "model-standard",
        "prompt",
        "script",
        "skill",
        "standard",
        "workflow",
    }
)


def detect_gas_city_context(
    *,
    cwd: Path | None = None,
    project_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a small, non-secret description of the active Gas City context."""
    environment = env if env is not None else os.environ
    current_dir = (cwd or Path.cwd()).expanduser().resolve()
    env_hits = sorted(key for key in GAS_CITY_ENV_KEYS if environment.get(key))
    city_root = _find_city_root(project_root) or _find_city_root(current_dir)

    active = bool(city_root or env_hits)
    source = "none"
    if city_root and env_hits:
        source = "filesystem+environment"
    elif city_root:
        source = "filesystem"
    elif env_hits:
        source = "environment"

    return {
        "active": active,
        "city_root": str(city_root) if city_root else "",
        "source": source,
        "env": env_hits,
    }


def is_global_runtime_risk(
    *,
    primitive: str | None,
    scope: str,
    gas_city_context: Mapping[str, Any] | None,
) -> bool:
    """Return whether an installed entry is global runtime surface in Gas City."""
    if not gas_city_context or not gas_city_context.get("active"):
        return False
    if scope != "global":
        return False
    return (primitive or "") in GLOBAL_RUNTIME_PRIMITIVES


def gas_city_runtime_warning(count: int, *, sync: bool = False) -> str:
    """Return the user-facing warning for global runtime bleed-through."""
    action = "skipped" if sync else "found"
    suffix = "; pass --include-global-runtime to sync them anyway" if sync else ""
    return (
        f"Gas City context detected; {action} {count} global runtime entries "
        f"that can bleed into provider sessions{suffix}"
    )


def _find_city_root(start: Path | None) -> Path | None:
    if start is None:
        return None

    try:
        current = start.expanduser().resolve()
    except OSError:
        current = start.expanduser()

    candidates = [current, *current.parents]
    for candidate in candidates:
        if (candidate / "city.toml").is_file() and (candidate / ".gc").is_dir():
            return candidate
    return None
