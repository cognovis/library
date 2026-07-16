"""
runtime_config.py — Compose, deploy, and audit the runtime-config primitive.

A runtime-config primitive is a GENERATED artifact, not a copied file. It is
composed from a routing BASE plus a global-only OVERLAY via a deterministic
section-level merge and written to a single target file (for example
``~/.agents/orchestrator-config.yml``).

Contract:
  - ``library runtime-config use`` / ``library sync`` regenerate the target
    reproducibly from the checked-in base + overlay sources (idempotent).
  - ``library audit`` compares the deployed file against a freshly composed
    rendering and reports drift when they diverge (hand-edits or source moves).

Section-level merge semantics:
  Every top-level key present in the overlay replaces (or adds) the same
  top-level key in the base. Base-only sections are preserved untouched. The
  overlay is intended to carry only global-only sections (e.g. ``bead_claim`` /
  ``effort_classifier``) that must not appear in project-level configs.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML

from .catalog import lookup_entry
from .errors import InstallError
from .lockfile import (
    find_lockfile,
    load_lockfile,
    make_entry,
    save_lockfile,
    upsert_entry,
)
from .output import dry_run_result, success
from .paths import resolve_install_paths
from .primitives import get_primitive
from .source import parse_source, resolve_marketplace


PRIMITIVE_NAME = "runtime-config"


def _yaml() -> YAML:
    """Return a round-trip YAML handler configured for deterministic output.

    Round-trip mode preserves comments and key order from the source documents,
    which keeps the deployed config human-readable while remaining reproducible.
    A wide line width prevents ruamel from reflowing long inline comments.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.map_indent = 2
    yaml.sequence_indent = 4
    yaml.sequence_dash_offset = 2
    return yaml


def compose_runtime_config(base_text: str, overlay_text: str) -> str:
    """Compose a runtime-config from a base and an overlay via section merge.

    Args:
        base_text: The routing baseline YAML document.
        overlay_text: The global-only overlay YAML document. May be empty.

    Returns:
        The composed YAML document as text. Deterministic and idempotent:
        re-composing the output against the same overlay yields identical bytes.
    """
    yaml = _yaml()
    base = yaml.load(base_text)
    if base is None:
        raise InstallError("runtime-config base source is empty or not valid YAML.")

    overlay = yaml.load(overlay_text) if overlay_text and overlay_text.strip() else None
    if overlay is not None:
        for key in overlay:
            base[key] = overlay[key]

    buf = io.StringIO()
    yaml.dump(base, buf)
    return buf.getvalue()


def _read_source_text(source_str: str, label: str) -> tuple[str, str]:
    """Fetch a single source file's text and its commit SHA.

    Reuses the simple-file fetch path so local paths and GitHub blob URLs both
    resolve. Returns ``(text, commit_sha)``.
    """
    if not source_str:
        raise InstallError(f"runtime-config is missing the '{label}' source field.")

    # Local import to avoid a module import cycle (simple_file imports lockfile,
    # which this module also uses at import time).
    from .installers.simple_file import _cleanup_temp, _fetch_file_source

    parsed = parse_source(source_str)
    source_file, commit, temp_root = _fetch_file_source(parsed, label)
    try:
        path = Path(source_file)
        if not path.is_file():
            raise InstallError(
                f"runtime-config '{label}' source did not resolve to a file: {source_str}"
            )
        return path.read_text(encoding="utf-8"), commit
    finally:
        _cleanup_temp(temp_root)


def _resolve_entry(catalog: dict, name: str) -> dict[str, Any]:
    entry = lookup_entry(catalog, PRIMITIVE_NAME, name)
    if not entry.get("base"):
        raise InstallError(
            f"runtime-config '{entry.get('name', name)}' has no 'base' source field."
        )
    return entry


def resolve_target_path(
    catalog: dict,
    entry: dict[str, Any],
    scope: str,
    repo_root: Path,
) -> Path:
    """Resolve the deploy target file for a runtime-config entry.

    The target directory comes from ``default_dirs.runtime_configs`` for the
    given scope; the filename is the entry's ``deploy_filename`` or ``<name>.yml``.
    """
    prim = get_primitive(PRIMITIVE_NAME)
    if prim is None:  # pragma: no cover - registry always has the primitive
        raise InstallError("runtime-config primitive is not registered.")

    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(
            f"Cannot determine deploy directory for runtime-config "
            f"'{entry.get('name')}' (scope={scope}). Check "
            f"default_dirs.runtime_configs in library.yaml."
        )

    filename = entry.get("deploy_filename") or f"{entry.get('name')}.yml"
    return canonical_base / filename


def compose_for_entry(
    catalog: dict,
    entry: dict[str, Any],
) -> tuple[str, str, str]:
    """Fetch sources and compose the runtime-config for an entry.

    Returns ``(composed_text, base_commit, overlay_commit)``.
    """
    base_text, base_commit = _read_source_text(entry.get("base", ""), "base")
    overlay_source = entry.get("global_overlay", "")
    if overlay_source:
        overlay_text, overlay_commit = _read_source_text(overlay_source, "global_overlay")
    else:
        overlay_text, overlay_commit = "", "none"

    composed = compose_runtime_config(base_text, overlay_text)
    return composed, base_commit, overlay_commit


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def install_runtime_config(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "global",
    dry_run: bool = False,
    harness: str = "all",
    install_mode: str = "vendor",
    target_override: Optional[Path] = None,
) -> dict[str, Any]:
    """Compose and deploy a runtime-config, then record it in the lockfile.

    Args:
        catalog: Parsed library.yaml dict.
        name: Entry name.
        repo_root: Project root (for lockfile resolution).
        scope: 'global' (default) or 'project'.
        dry_run: If True, return planned ops without writing.
        harness: Unused (single-target primitive); accepted for dispatch parity.
        install_mode: Unused (always vendored); accepted for parity.
        target_override: Deploy to this path instead of the resolved default.
            Used by tests to avoid touching the live global config.

    Returns:
        Operation result dict.
    """
    entry = _resolve_entry(catalog, name)
    item_name = entry.get("name", name)
    target = target_override or resolve_target_path(catalog, entry, scope, repo_root)

    if dry_run:
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops = [
            {
                "operation": "compose",
                "path": str(target),
                "details": (
                    f"compose runtime-config '{item_name}' from base + global_overlay"
                ),
            },
            {
                "operation": "write_lockfile",
                "path": str(lockfile_path),
                "details": f"upsert entry '{item_name}'",
            },
        ]
        return dry_run_result(
            ops,
            summary=f"Would compose runtime-config '{item_name}' to {target}",
            target_paths=[str(target)],
            conflict_policy="overwrite",
        )

    composed, base_commit, overlay_commit = compose_for_entry(catalog, entry)
    content_sha = _sha256_text(composed)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    target.write_text(composed, encoding="utf-8")

    marketplace = resolve_marketplace(catalog, entry) or "unknown"
    lockfile_entry = make_entry(
        name=item_name,
        primitive_type=PRIMITIVE_NAME,
        marketplace=marketplace,
        source=entry.get("base", ""),
        source_commit=base_commit,
        cache_path="",
        install_target=str(target),
        checksum_sha256=content_sha,
        content_sha256=content_sha,
        checksum_type="file",
        install_mode="vendor",
        license_id=entry.get("license", "unknown"),
    )
    # Record the overlay provenance so status/debugging can see both inputs.
    lockfile_entry["overlay_source"] = entry.get("global_overlay", "")
    lockfile_entry["overlay_commit"] = overlay_commit

    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
    lock_data = load_lockfile(lockfile_path)
    upsert_entry(lock_data, lockfile_entry)
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={
            "name": item_name,
            "install_target": str(target),
            "content_sha256": content_sha,
            "base_commit": base_commit,
            "overlay_commit": overlay_commit,
        },
        message=f"Runtime-config '{item_name}' composed at {target}",
    )


def audit_runtime_config(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "global",
    target_override: Optional[Path] = None,
) -> dict[str, Any]:
    """Compare the deployed runtime-config against a freshly composed rendering.

    Returns a dict with keys:
      name, primitive, scope, drift (bool), status ('clean'|'drift'|'missing'),
      expected_sha, actual_sha, install_target.
    """
    entry = _resolve_entry(catalog, name)
    item_name = entry.get("name", name)
    target = target_override or resolve_target_path(catalog, entry, scope, repo_root)

    composed, _base_commit, _overlay_commit = compose_for_entry(catalog, entry)
    expected_sha = _sha256_text(composed)

    result: dict[str, Any] = {
        "name": item_name,
        "primitive": PRIMITIVE_NAME,
        "scope": scope,
        "expected_sha": expected_sha,
        "install_target": str(target),
    }

    if not target.exists():
        result.update({"drift": True, "status": "missing", "actual_sha": ""})
        return result

    actual_text = target.read_text(encoding="utf-8")
    actual_sha = _sha256_text(actual_text)
    result["actual_sha"] = actual_sha

    if actual_sha != expected_sha:
        result.update({"drift": True, "status": "drift"})
    else:
        result.update({"drift": False, "status": "clean"})
    return result
