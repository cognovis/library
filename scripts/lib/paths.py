"""
paths.py — Resolve default_dirs, project/global scope, and AGENTS.md targets.

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
    """
    default_dirs = data.get("default_dirs", {}) or {}
    subdir_key = primitive.install_subdir
    if subdir_key is None:
        # e.g. mcp — no standard directory
        return {"canonical": None, "bridge": None}

    dirs_for_type = default_dirs.get(subdir_key, []) or []
    if not dirs_for_type:
        # Try underscore variant (library.yaml uses model_standards, golden_prompts with underscores)
        underscore_key = subdir_key.replace("-", "_")
        dirs_for_type = default_dirs.get(underscore_key, []) or []

    canonical: Optional[Path] = None
    bridge: Optional[Path] = None
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
            elif scope == "global":
                if key == "global":
                    canonical = path
                elif key == "global_claude_bridge":
                    bridge = path

    return {"canonical": canonical, "bridge": bridge}


def _expand_path(raw: str, home: Path, root: Path) -> Path:
    """Expand ~ and make absolute relative to repo root."""
    if raw.startswith("~/"):
        return home / raw[2:]
    if raw.startswith("/"):
        return Path(raw)
    # Relative path — resolve against repo root
    return root / raw


def resolve_standards_agents_md(
    data: dict[str, Any],
    *,
    scope: str = "project",
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    """Return the AGENTS.md target path for standards injection.

    For project scope: AGENTS.md at repo_root.
    For global scope: ~/.agents/standards/ AGENTS.md parent.

    Returns:
        Path to AGENTS.md, or None if it cannot be determined.
    """
    root = repo_root or Path.cwd()
    home = Path.home()

    if scope == "project":
        candidate = root / "AGENTS.md"
        return candidate
    else:
        # Global: ~/.agents/standards/ -> parent AGENTS.md is ~/.agents/AGENTS.md
        return home / ".agents" / "AGENTS.md"
