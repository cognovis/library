"""
paths.py — Resolve default_dirs and project/global scope.

Reads the `default_dirs` section of library.yaml to derive installation paths
for each primitive type in project-local and global scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .primitives import PrimitiveInfo


def resolve_install_paths(
    data: dict[str, Any],
    primitive: PrimitiveInfo,
    *,
    scope: str = "project",
    repo_root: Optional[Path] = None,
) -> dict[str, Optional[Path]]:
    """Resolve canonical and bridge installation paths for a primitive.

    Args:
        data: Parsed library.yaml dict (for default_dirs lookup).
        primitive: Primitive info.
        scope: 'project' or 'global'.
        repo_root: Project root directory (for relative path resolution).

    Returns:
        Dict with keys:
          canonical  — canonical install directory (Layer C, symlink target)
          bridge     — Claude harness bridge path (None if not applicable)
          cursor_bridge        — Cursor project bridge path when configured
          global_cursor_bridge — Cursor global bridge path when configured
    """
    default_dirs = data.get("default_dirs", {}) or {}
    subdir_key = primitive.install_subdir
    if subdir_key is None:
        # e.g. mcp — no standard directory
        return {
            "canonical": None,
            "bridge": None,
            "cursor_bridge": None,
            "global_cursor_bridge": None,
        }

    dirs_for_type = default_dirs.get(subdir_key, []) or []
    if not dirs_for_type:
        # Try underscore variant (library.yaml uses model_standards, agent_bases with underscores)
        underscore_key = subdir_key.replace("-", "_")
        dirs_for_type = default_dirs.get(underscore_key, []) or []

    canonical: Optional[Path] = None
    bridge: Optional[Path] = None
    cursor_bridge: Optional[Path] = None
    global_cursor_bridge: Optional[Path] = None
    home = Path.home()
    root = repo_root or Path.cwd()

    for entry in dirs_for_type:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            path = _expand_path(value, home, root)
            if scope == "project":
                if key == "default":
                    canonical = path
                elif key == "claude_bridge":
                    bridge = path
                elif key == "cursor_bridge":
                    cursor_bridge = path
            elif scope == "global":
                if key == "global":
                    canonical = path
                elif key == "global_claude_bridge":
                    bridge = path
                elif key == "global_cursor_bridge":
                    global_cursor_bridge = path

    return {
        "canonical": canonical,
        "bridge": bridge,
        "cursor_bridge": cursor_bridge,
        "global_cursor_bridge": global_cursor_bridge,
    }


def _expand_path(raw: str, home: Path, root: Path) -> Path:
    """Expand ~ and make absolute relative to repo root."""
    if raw.startswith("~/"):
        return home / raw[2:]
    if raw.startswith("/"):
        return Path(raw)
    # Relative path — resolve against repo root
    return root / raw
