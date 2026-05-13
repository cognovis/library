"""
lockfile.py — Project .library.lock and global ~/.config/library/global.lock management.

Schema: see docs/lockfile-format.md and docs/schema/lockfile.schema.json.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required: pip install PyYAML") from exc

from .errors import LockfileError


# Default lockfile name at project root
LOCKFILE_NAME = ".library.lock"

# Global lockfile path (XDG-compliant)
GLOBAL_LOCKFILE = Path.home() / ".config" / "library" / "global.lock"


def find_lockfile(
    project_root: Optional[Path] = None, *, global_scope: bool = False
) -> Path:
    """Return the lockfile path for project or global scope.

    Args:
        project_root: Project root for project-scoped lockfile. Defaults to cwd.
        global_scope: If True, return the global lockfile path.

    Returns:
        Path to the lockfile (may not exist yet).
    """
    if global_scope:
        return GLOBAL_LOCKFILE
    root = project_root or Path.cwd()
    return root / LOCKFILE_NAME


def load_lockfile(lockfile_path: Path) -> dict[str, Any]:
    """Load and parse the lockfile.

    Returns:
        Dict with key 'installed' (list of entries). Returns empty structure if
        the file does not exist.

    Raises:
        LockfileError: If the file exists but is invalid YAML.
    """
    if not lockfile_path.exists():
        return {"installed": []}

    try:
        with lockfile_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise LockfileError(f"Invalid YAML in {lockfile_path}: {exc}") from exc

    if data is None:
        return {"installed": []}

    if not isinstance(data, dict):
        raise LockfileError(f"{lockfile_path} must be a YAML mapping.")

    if "installed" not in data:
        data["installed"] = []

    return data


def save_lockfile(lockfile_path: Path, data: dict[str, Any]) -> None:
    """Write lockfile data to disk.

    Args:
        lockfile_path: Path to write.
        data: Dict with 'installed' list.

    Raises:
        LockfileError: On write failure.
    """
    try:
        lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        with lockfile_path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except OSError as exc:
        raise LockfileError(f"Failed to write {lockfile_path}: {exc}") from exc


def upsert_entry(
    data: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Insert or update a lockfile entry by name.

    If an entry with the same `name` exists, it is replaced in place.
    Otherwise a new entry is appended.

    Args:
        data: Parsed lockfile dict (mutated in place).
        entry: Entry dict conforming to lockfile schema.

    Returns:
        The updated data dict.
    """
    installed = data.setdefault("installed", [])
    name = entry["name"]

    for i, existing in enumerate(installed):
        if existing.get("name") == name:
            installed[i] = entry
            return data

    installed.append(entry)
    return data


def remove_entry(data: dict[str, Any], name: str) -> bool:
    """Remove the entry with the given name from the lockfile.

    Returns:
        True if an entry was removed, False if name was not found.
    """
    installed = data.get("installed", [])
    original_len = len(installed)
    data["installed"] = [e for e in installed if e.get("name") != name]
    return len(data["installed"]) < original_len


def get_entry(data: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    """Return the lockfile entry for the given name, or None."""
    for entry in data.get("installed", []):
        if entry.get("name") == name:
            return entry
    return None


def compute_checksum(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file.

    Args:
        file_path: Path to the file.

    Returns:
        64-character lowercase hex string.
    """
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_directory_hash(dir_path: Path) -> str:
    """Merkle-style hash over all files in a directory (sorted, recursive).

    The hash is deterministic: same file contents at same relative paths always
    produce the same digest, regardless of absolute location on disk.

    Args:
        dir_path: Path to the directory to hash.

    Returns:
        64-character lowercase SHA-256 hex string.

    Raises:
        FileNotFoundError: If dir_path does not exist.
    """
    if not dir_path.exists():
        raise FileNotFoundError(f"compute_directory_hash: path does not exist: {dir_path}")
    h = hashlib.sha256()
    for f in sorted(dir_path.rglob("*")):
        if f.is_file():
            rel = f.relative_to(dir_path)
            h.update(str(rel).encode())
            h.update(b"\0")          # separator
            h.update(compute_checksum(f).encode())
            h.update(b"\0")          # separator
    return h.hexdigest()


def make_entry(
    *,
    name: str,
    primitive_type: str,
    marketplace: str,
    source: str,
    source_commit: str,
    cache_path: str,
    install_target: str,
    checksum_sha256: str,
    license_id: str = "unknown",
    bridge_symlinks: Optional[list[str]] = None,
    checksum_type: str = "file",
) -> dict[str, Any]:
    """Build a lockfile entry dict conforming to the lockfile schema.

    Args:
        name: Item name.
        primitive_type: 'skill', 'agent', 'prompt', 'guardrail'.
        marketplace: Source marketplace identifier.
        source: Source URL or local path.
        source_commit: Git commit SHA or 'local'.
        cache_path: Absolute Layer-B cache path string.
        install_target: Relative (project) or absolute (global) install dir with trailing slash.
        checksum_sha256: SHA-256 hex digest of primary artifact.
        license_id: SPDX license identifier.
        bridge_symlinks: List of bridge symlink description strings.

    Returns:
        Complete entry dict.
    """
    return {
        "name": name,
        "type": primitive_type,
        "marketplace": marketplace,
        "source": source,
        "source_commit": source_commit,
        "cache_path": cache_path,
        "install_target": install_target,
        "install_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checksum_sha256": checksum_sha256,
        "checksum_type": checksum_type,
        "license": license_id,
        "bridge_symlinks": bridge_symlinks or [],
    }
