"""
lockfile.py — Project .library.lock and global ~/.config/library/global.lock management.

Schema: see docs/lockfile-format.md and docs/schema/lockfile.schema.json.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required: pip install PyYAML") from exc

from .errors import LockfileError
from .providers.state_files import atomic_write_text, exclusive_lock

# Default lockfile name at project root
LOCKFILE_NAME = ".library.lock"


# Global lockfile path (XDG-compliant).
#
# Resolved at import for callers that read the constant directly, but
# `find_lockfile()` re-resolves from the current HOME whenever this still holds
# the import-time default. A test isolating itself with
# `monkeypatch.setenv("HOME", tmp_path)` runs *after* this module is imported, so
# a constant frozen at import silently sends global-scope installs into the
# operator's real lockfile (CL-t71i: a pytest fixture entry was found in
# ~/.config/library/global.lock, dated 2026-07-17, pointing at a long-deleted
# tmpdir). Tests that patch this attribute directly still win -- see
# `_global_lockfile_path()`.
def _default_global_lockfile() -> Path:
    return Path.home() / ".config" / "library" / "global.lock"


GLOBAL_LOCKFILE = _default_global_lockfile()
_IMPORT_TIME_GLOBAL_LOCKFILE = GLOBAL_LOCKFILE


def _global_lockfile_path() -> Path:
    """Return the global lockfile path, honoring HOME changes made after import.

    An explicit override of the module attribute takes precedence: several test
    modules monkeypatch `lockfile.GLOBAL_LOCKFILE` to redirect writes, and that
    intent must not be overruled by re-resolving from the environment.
    """
    if GLOBAL_LOCKFILE != _IMPORT_TIME_GLOBAL_LOCKFILE:
        return GLOBAL_LOCKFILE
    return _default_global_lockfile()


LEGACY_PRIMITIVE_TYPES = {
    "golden-prompt": "agent-base",
}

LOCKFILE_SCHEMA_VERSION = 2


def resolve_lockfile_path(path_value: str | Path, project_root: Path) -> Path:
    """Resolve a persisted lockfile path against its project root.

    Project-scoped lockfiles use repository-relative paths so they remain
    portable after a checkout is moved. Global entries and legacy project
    entries may still be absolute. Readers must use this helper instead of
    allowing ``Path`` to resolve relative values against the process CWD.
    """
    path = Path(str(path_value).rstrip("/")).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def root_id(primitive_type: str, name: str) -> str:
    """Return the stable identity for one direct artifact root."""
    return f"{canonical_lockfile_type(primitive_type)}:{name}"


def _empty_v2_lock() -> dict[str, Any]:
    """Return a new in-memory v2 lock with the compatibility projection."""
    return {
        "schema_version": LOCKFILE_SCHEMA_VERSION,
        "migration": {"prune_ack_required": False},
        "requested_roots": [],
        "receipts": [],
        "prerequisites": [],
        "installed": [],
    }


def _entry_scope(entry: dict[str, Any], fallback_scope: str) -> str:
    """Return explicit install scope without inferring it from absolute paths."""
    scope = str(entry.get("scope") or fallback_scope)
    if scope not in {"project", "global"}:
        raise LockfileError(f"Invalid lockfile entry scope {scope!r}")
    return scope


def _requested_root_from_entry(
    entry: dict[str, Any], *, fallback_scope: str
) -> dict[str, Any]:
    primitive_type = str(canonical_lockfile_type(entry.get("type")) or "")
    result: dict[str, Any] = {
        "id": root_id(primitive_type, str(entry.get("name") or "")),
        "type": primitive_type,
        "name": str(entry.get("name") or ""),
        "scope": _entry_scope(entry, fallback_scope),
        "catalog_identity": str(entry.get("catalog_identity") or "unknown"),
        "resolved_version": str(entry.get("version") or "legacy"),
        "definition_commit": str(entry.get("source_commit") or "legacy"),
    }
    return result


def _initial_targets(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Build an exact target inventory when materialized content is available."""
    if entry.get("type") in {"guardrail", "mcp", "runtime-config"}:
        return []
    target = str(entry.get("install_target") or "").rstrip("/")
    if not target:
        return []
    target_path = Path(target).expanduser()
    items: list[dict[str, Any]] = []
    if target_path.is_symlink():
        items.append(
            {
                "path": target,
                "kind": "symlink",
                "link_target": str(target_path.readlink()),
            }
        )
    elif target_path.is_file():
        items.append(
            {
                "path": target,
                "kind": "file",
                "content_sha256": compute_checksum(target_path),
            }
        )
    elif target_path.is_dir():
        items.append({"path": str(target_path), "kind": "directory"})
        for child in sorted(target_path.rglob("*")):
            if child.is_symlink():
                items.append(
                    {
                        "path": str(child),
                        "kind": "symlink",
                        "link_target": str(child.readlink()),
                    }
                )
            elif child.is_dir():
                items.append({"path": str(child), "kind": "directory"})
            elif child.is_file():
                items.append(
                    {
                        "path": str(child),
                        "kind": "file",
                        "content_sha256": compute_checksum(child),
                    }
                )
    else:
        kind = "directory" if entry.get("checksum_type") == "directory" else "file"
        item: dict[str, Any] = {"path": target, "kind": kind}
        if kind == "file" and entry.get("content_sha256"):
            item["content_sha256"] = entry["content_sha256"]
        items.append(item)

    for bridge in entry.get("bridge_symlinks") or []:
        raw_path, separator, raw_target = str(bridge).partition(" -> ")
        if separator and raw_path.strip() and raw_target.strip():
            bridge_path = Path(raw_path.strip()).expanduser()
            if any(item.get("path") == str(bridge_path) for item in items):
                continue
            if bridge_path.is_symlink():
                items.append(
                    {
                        "path": str(bridge_path),
                        "kind": "symlink",
                        "link_target": str(bridge_path.readlink()),
                    }
                )
            elif bridge_path.is_file():
                items.append(
                    {
                        "path": str(bridge_path),
                        "kind": "file",
                        "content_sha256": compute_checksum(bridge_path),
                    }
                )
                handler_root_name = f"{entry.get('name', '')}-handlers"
                handler_root = next(
                    (
                        ancestor
                        for ancestor in bridge_path.parents
                        if ancestor.name == handler_root_name
                    ),
                    None,
                )
                if handler_root is not None:
                    directory = bridge_path.parent
                    while directory.is_relative_to(handler_root):
                        if not any(
                            item.get("path") == str(directory) for item in items
                        ):
                            items.append({"path": str(directory), "kind": "directory"})
                        if directory == handler_root:
                            break
                        directory = directory.parent
            elif bridge_path.is_dir():
                items.append({"path": str(bridge_path), "kind": "directory"})
                for child in sorted(bridge_path.rglob("*")):
                    if child.is_symlink():
                        items.append(
                            {
                                "path": str(child),
                                "kind": "symlink",
                                "link_target": str(child.readlink()),
                            }
                        )
                    elif child.is_dir():
                        items.append({"path": str(child), "kind": "directory"})
                    elif child.is_file():
                        items.append(
                            {
                                "path": str(child),
                                "kind": "file",
                                "content_sha256": compute_checksum(child),
                            }
                        )
    return items


def _receipt_from_entry(
    entry: dict[str, Any],
    *,
    fallback_scope: str,
    verified: bool,
    prune_blocked_reason: str | None,
) -> dict[str, Any]:
    """Convert the legacy-compatible install shape into a v2 receipt."""
    primitive_type = str(canonical_lockfile_type(entry.get("type")) or "")
    name = str(entry.get("name") or "")
    receipt = dict(entry)
    receipt.update(
        {
            "id": root_id(primitive_type, name),
            "type": primitive_type,
            "name": name,
            "scope": _entry_scope(entry, fallback_scope),
            "catalog_identity": str(entry.get("catalog_identity") or "unknown"),
            "resolved_version": str(entry.get("version") or "legacy"),
            "verified": verified,
            "adopted": False,
            "prune_blocked_reason": prune_blocked_reason,
            "targets": _initial_targets(entry),
            "owners_cache": [root_id(primitive_type, name)],
        }
    )
    return receipt


def _legacy_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the deprecated installed entry derived from one receipt."""
    excluded = {
        "id",
        "scope",
        "resolved_version",
        "verified",
        "adopted",
        "prune_blocked_reason",
        "targets",
        "owners_cache",
    }
    return {key: value for key, value in receipt.items() if key not in excluded}


def migrate_lockfile_v2(data: dict[str, Any], *, scope: str = "project") -> bool:
    """Normalize a legacy or partial lock to the authoritative v2 model."""
    migrate_lockfile_primitive_types(data)
    declared_version = data.get("schema_version")
    if declared_version is not None and declared_version != LOCKFILE_SCHEMA_VERSION:
        raise LockfileError(
            f"Unsupported lockfile schema_version {declared_version!r}; "
            f"this Library supports {LOCKFILE_SCHEMA_VERSION}"
        )
    if data.get("schema_version") == LOCKFILE_SCHEMA_VERSION:
        changed = False
        for key, default in (
            ("requested_roots", []),
            ("receipts", []),
            ("prerequisites", []),
        ):
            if not isinstance(data.get(key), list):
                data[key] = default
                changed = True
        if not isinstance(data.get("migration"), dict):
            data["migration"] = {"prune_ack_required": False}
            changed = True
        if not isinstance(data.get("installed"), list):
            data["installed"] = [
                _legacy_projection(receipt)
                for receipt in data["receipts"]
                if isinstance(receipt, dict)
            ]
            changed = True
        for collection in ("requested_roots", "receipts"):
            for item in data[collection]:
                if isinstance(item, dict) and item.get("scope") not in {
                    "project",
                    "global",
                }:
                    item["scope"] = scope
                    changed = True
        return changed

    installed = data.get("installed")
    if not isinstance(installed, list):
        installed = []
    receipts = [
        _receipt_from_entry(
            entry,
            fallback_scope=scope,
            verified=False,
            prune_blocked_reason="legacy-unverified",
        )
        for entry in installed
        if isinstance(entry, dict)
    ]
    data.clear()
    data.update(
        {
            "schema_version": LOCKFILE_SCHEMA_VERSION,
            "migration": {"prune_ack_required": bool(receipts)},
            "requested_roots": [
                _requested_root_from_entry(entry, fallback_scope=scope)
                for entry in installed
                if isinstance(entry, dict)
            ],
            "receipts": receipts,
            "prerequisites": [],
            "installed": [
                dict(entry) for entry in installed if isinstance(entry, dict)
            ],
        }
    )
    return True


def canonical_lockfile_type(primitive_type: str | None) -> str | None:
    """Return the canonical lockfile primitive type for legacy aliases."""
    if primitive_type is None:
        return None
    return LEGACY_PRIMITIVE_TYPES.get(primitive_type, primitive_type)


def migrate_lockfile_primitive_types(data: dict[str, Any]) -> bool:
    """Migrate legacy lockfile primitive type strings in memory.

    Returns True when at least one entry changed.
    """
    changed = False
    installed = data.get("installed", [])
    if not isinstance(installed, list):
        data["installed"] = []
        return changed

    for entry in installed:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        canonical_type = canonical_lockfile_type(entry_type)
        if canonical_type != entry_type:
            entry["type"] = canonical_type
            changed = True
        composed_layers = entry.get("composed_layers")
        if isinstance(composed_layers, dict) and "golden_prompt" in composed_layers:
            if "agent_base" not in composed_layers:
                composed_layers["agent_base"] = composed_layers["golden_prompt"]
            del composed_layers["golden_prompt"]
            changed = True

    return changed


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
        return _global_lockfile_path()
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
        return _empty_v2_lock()

    try:
        with lockfile_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise LockfileError(f"Invalid YAML in {lockfile_path}: {exc}") from exc

    if data is None:
        return _empty_v2_lock()

    if not isinstance(data, dict):
        raise LockfileError(f"{lockfile_path} must be a YAML mapping.")

    scope = (
        "global"
        if lockfile_path.expanduser().absolute()
        == _global_lockfile_path().expanduser().absolute()
        else "project"
    )
    migrate_lockfile_v2(data, scope=scope)

    return data


def _project_relative_path(value: str, project_root: Path) -> str:
    """Serialize an absolute project-owned path relative to its lock root."""
    raw = str(value)
    trailing_slash = raw.endswith("/")
    candidate = Path(raw.rstrip("/")).expanduser()
    if not candidate.is_absolute():
        return raw
    normalized_root = Path(os.path.abspath(project_root))
    normalized_candidate = Path(os.path.abspath(candidate))
    try:
        relative = normalized_candidate.relative_to(normalized_root).as_posix()
    except ValueError:
        return raw
    return f"{relative}/" if trailing_slash else relative


def _portable_project_lock(data: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Return a portable serialization without changing the runtime lock."""
    portable = deepcopy(data)
    for collection in ("receipts", "installed"):
        for entry in portable.get(collection) or []:
            if not isinstance(entry, dict) or entry.get("scope") != "project":
                continue
            install_target = entry.get("install_target")
            if isinstance(install_target, str) and install_target:
                entry["install_target"] = _project_relative_path(
                    install_target, project_root
                )
            bridges: list[str] = []
            for bridge in entry.get("bridge_symlinks") or []:
                raw_path, separator, raw_target = str(bridge).partition(" -> ")
                if not separator:
                    bridges.append(str(bridge))
                    continue
                portable_path = _project_relative_path(raw_path.strip(), project_root)
                portable_target = _project_relative_path(
                    raw_target.strip(), project_root
                )
                bridges.append(f"{portable_path} -> {portable_target}")
            if "bridge_symlinks" in entry:
                entry["bridge_symlinks"] = bridges
            for target in entry.get("targets") or []:
                if isinstance(target, dict) and isinstance(target.get("path"), str):
                    target["path"] = _project_relative_path(
                        target["path"], project_root
                    )
    return portable


def save_lockfile(lockfile_path: Path, data: dict[str, Any]) -> None:
    """Write lockfile data to disk indivisibly for readers.

    The document is serialized in full before anything on disk changes, and the
    finished text replaces the lockfile by rename. Writing into the lockfile
    itself (`open(path, "w")`) truncated it first, so a reader that arrived
    mid-write, or a second writer that had opened the same path, saw a partial
    document: CL-1f36 recorded a half-written `install_timestamp` inside another
    entry's target list, after which every later `library` call failed with
    "Invalid YAML".

    Atomicity keeps readers safe; it does not make the surrounding
    load-modify-save a transaction. Callers that modify the lock must hold
    `mutate_lockfile`.

    Args:
        lockfile_path: Path to write.
        data: Dict with 'installed' list.

    Raises:
        LockfileError: On write failure.
    """
    scope = (
        "global"
        if lockfile_path.expanduser().absolute()
        == _global_lockfile_path().expanduser().absolute()
        else "project"
    )
    migrate_lockfile_v2(data, scope=scope)
    serialized = (
        _portable_project_lock(data, lockfile_path.parent)
        if scope == "project"
        else data
    )
    document = yaml.dump(
        serialized,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    try:
        atomic_write_text(lockfile_path, document)
    except OSError as exc:
        raise LockfileError(f"Failed to write {lockfile_path}: {exc}") from exc


# One in-process transaction registry per thread. `flock` is held per open file
# description, so a second acquisition inside the same process would block on
# itself; installers legitimately nest (an agent install writes the lock inside
# a Workspace mutation that already holds it), so an active transaction is
# recorded here and a nested one reuses it instead of acquiring again.
_TRANSACTIONS = threading.local()


def _transaction_states() -> dict[str, dict[str, Any]]:
    states = getattr(_TRANSACTIONS, "states", None)
    if states is None:
        states = {}
        _TRANSACTIONS.states = states
    return states


def _guard_path(lockfile_path: Path) -> Path:
    """Return the canonical path that identifies one lockfile's guard.

    Symlinks are resolved so two spellings of the same file cannot take two
    different guards and believe they are alone. On macOS that is the ordinary
    case, not an exotic one: `/var/...` and `/private/var/...` name the same
    lockfile.
    """
    return Path(os.path.realpath(str(Path(lockfile_path).expanduser())))


@contextlib.contextmanager
def lockfile_transaction(lockfile_path: Path) -> Iterator[None]:
    """Hold one lockfile's cross-process write guard for a whole critical section.

    The guard is an advisory `flock` on a sidecar beside the lockfile, so it
    survives the rename that every save performs. It serializes cooperating
    Library processes -- a sync, an install, and a Workspace mutation -- and is
    no defense against a process that writes the lockfile without it.
    """
    guard = _guard_path(lockfile_path)
    key = str(guard)
    states = _transaction_states()
    if key in states:
        yield
        return

    with exclusive_lock(guard):
        states[key] = {"data": None}
        try:
            yield
        finally:
            states.pop(key, None)


@contextlib.contextmanager
def mutate_lockfile(lockfile_path: Path) -> Iterator[dict[str, Any]]:
    """Load, modify, and save one lockfile as a single guarded transaction.

    Atomic replacement is not an atomic transaction: it makes a write
    indivisible for readers and does nothing for the read that decided what to
    write. Two unguarded writers each loaded the lock, and each saved a snapshot
    taken before the other's save, so completed installs lost their receipts
    while their content stayed on disk (CL-1f36). Every read-modify-write of a
    lockfile must go through here.

    The lockfile is saved when the block exits normally. An exception leaves the
    lockfile exactly as it was, so a failed install never publishes a partial
    receipt.
    """
    key = str(_guard_path(lockfile_path))
    path = Path(lockfile_path)
    with lockfile_transaction(path):
        state = _transaction_states()[key]
        if state["data"] is not None:
            # Nested inside an active mutation: share its document so the outer
            # save cannot overwrite what this block just changed.
            yield state["data"]
            return
        data = load_lockfile(path)
        state["data"] = data
        try:
            yield data
            save_lockfile(path, data)
        finally:
            state["data"] = None


def upsert_entry(
    data: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Insert or update a lockfile entry by name and primitive type.

    If an entry with the same `name` and `type` exists, it is replaced in
    place. Otherwise a new entry is appended. This allows cross-primitive name
    collisions such as `skill:session-close` and `agent:session-close`.

    Args:
        data: Parsed lockfile dict (mutated in place).
        entry: Entry dict conforming to lockfile schema.

    Returns:
        The updated data dict.
    """
    entry_scope = _entry_scope(entry, "project")
    migrate_lockfile_v2(data, scope=entry_scope)
    installed = data.setdefault("installed", [])
    name = entry["name"]
    primitive_type = canonical_lockfile_type(entry.get("type"))
    entry["type"] = primitive_type

    for i, existing in enumerate(installed):
        if existing.get("name") == name and existing.get("type") == primitive_type:
            installed[i] = entry
            break
    else:
        installed.append(entry)

    direct_root = _requested_root_from_entry(entry, fallback_scope=entry_scope)
    requested_roots = data.setdefault("requested_roots", [])
    for index, existing_root in enumerate(requested_roots):
        if existing_root.get("id") == direct_root["id"]:
            requested_roots[index] = direct_root
            break
    else:
        requested_roots.append(direct_root)

    receipt = _receipt_from_entry(
        entry,
        fallback_scope=entry_scope,
        verified=True,
        prune_blocked_reason=None,
    )
    receipts = data.setdefault("receipts", [])
    for index, existing_receipt in enumerate(receipts):
        if existing_receipt.get("id") == receipt["id"]:
            receipt["owners_cache"] = list(
                existing_receipt.get("owners_cache") or receipt["owners_cache"]
            )
            receipt["adopted"] = bool(existing_receipt.get("adopted", False))
            receipts[index] = receipt
            break
    else:
        receipts.append(receipt)
    return data


def remove_entry(
    data: dict[str, Any],
    name: str,
    primitive_type: str | None = None,
) -> bool:
    """Remove matching entries from the lockfile.

    When `primitive_type` is provided, remove only that primitive. When omitted,
    keep the historical behavior and remove every entry with the given name.

    Returns:
        True if an entry was removed, False if name was not found.
    """
    migrate_lockfile_v2(data)
    installed = data.get("installed", [])
    primitive_type = canonical_lockfile_type(primitive_type)
    original_len = len(installed)
    matching_ids = {
        root_id(str(e.get("type") or ""), str(e.get("name") or ""))
        for e in installed
        if e.get("name") == name
        and (primitive_type is None or e.get("type") == primitive_type)
    }
    before_roots = len(data.get("requested_roots", []))
    data["requested_roots"] = [
        root
        for root in data.get("requested_roots", [])
        if root.get("id") not in matching_ids
    ]
    # Primitive removal is an explicit physical removal operation. Explanatory
    # owners_cache data must never decide retention; the next Workspace plan
    # recomputes reachability and reports the missing receipt as an addition.
    retained_receipt_ids: set[str] = set()
    data["installed"] = [
        e
        for e in installed
        if root_id(str(e.get("type") or ""), str(e.get("name") or ""))
        in retained_receipt_ids
        or not (
            e.get("name") == name
            and (primitive_type is None or e.get("type") == primitive_type)
        )
    ]
    data["receipts"] = [
        receipt
        for receipt in data.get("receipts", [])
        if receipt.get("id") not in matching_ids
        or receipt.get("id") in retained_receipt_ids
    ]
    return (
        len(data["installed"]) < original_len
        or len(data["requested_roots"]) < before_roots
    )


def get_entry(
    data: dict[str, Any],
    name: str,
    primitive_type: str | None = None,
) -> Optional[dict[str, Any]]:
    """Return the lockfile entry for the given name/type, or None."""
    primitive_type = canonical_lockfile_type(primitive_type)
    for entry in data.get("installed", []):
        if entry.get("name") == name and (
            primitive_type is None or entry.get("type") == primitive_type
        ):
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
        raise FileNotFoundError(
            f"compute_directory_hash: path does not exist: {dir_path}"
        )
    h = hashlib.sha256()
    for f in sorted(dir_path.rglob("*")):
        if f.is_file():
            rel = f.relative_to(dir_path)
            h.update(str(rel).encode())
            h.update(b"\0")  # separator
            h.update(compute_checksum(f).encode())
            h.update(b"\0")  # separator
    return h.hexdigest()


def make_entry(
    *,
    name: str,
    primitive_type: str,
    catalog_identity: str | None = None,
    marketplace: str,
    source: str,
    source_commit: str,
    cache_path: str,
    install_target: str,
    checksum_sha256: str,
    license_id: str = "unknown",
    bridge_symlinks: Optional[list[str]] = None,
    checksum_type: str = "file",
    install_mode: str = "vendor",
    content_sha256: Optional[str] = None,
    scope: str = "project",
    version: str | None = None,
) -> dict[str, Any]:
    """Build a lockfile entry dict conforming to the lockfile schema.

    Args:
        name: Item name.
        primitive_type: 'skill', 'agent', 'prompt', 'guardrail'.
        catalog_identity: Stable identity of the catalog that produced the entry.
            ``None`` is reserved for legacy or unbound in-memory callers.
        marketplace: Source marketplace identifier.
        source: Source URL or local path.
        source_commit: Git commit SHA or 'local'.
        cache_path: Absolute Layer-B cache path string.
        install_target: Relative (project) or absolute (global) install dir with trailing slash.
        checksum_sha256: SHA-256 hex digest of primary artifact.
        license_id: SPDX license identifier.
        bridge_symlinks: List of bridge symlink description strings.
        checksum_type: Checksum strategy for checksum_sha256.
        install_mode: 'vendor' for real copied files, or 'symlink' for cache links.
        content_sha256: SHA-256 hex digest of the local installed content.

    Returns:
        Complete entry dict.
    """
    entry = {
        "name": name,
        "type": canonical_lockfile_type(primitive_type),
        "marketplace": marketplace,
        "source": source,
        "source_commit": source_commit,
        "cache_path": cache_path,
        "install_target": install_target,
        "install_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checksum_sha256": checksum_sha256,
        "checksum_type": checksum_type,
        "content_sha256": content_sha256 or checksum_sha256,
        "install_mode": install_mode,
        "license": license_id,
        "bridge_symlinks": bridge_symlinks or [],
        "scope": scope,
    }
    if version is not None:
        entry["version"] = version
    if catalog_identity:
        entry["catalog_identity"] = catalog_identity
    return entry
