"""
collisions.py - Name-collision guards for flat file primitives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

COLLISION_OPTIONS = [
    "--replace",
    "--merge-into=<canonical-repo>",
    "--skip",
]


def find_installed_entry(
    lock_data: dict[str, Any],
    name: str,
    primitive_type: str,
) -> dict[str, Any] | None:
    """Return the matching installed entry, constrained by primitive type."""
    for entry in lock_data.get("installed", []) or []:
        if entry.get("name") != name:
            continue
        if entry.get("type") == primitive_type:
            return entry
    return None


def has_source_collision(
    *,
    lock_data: dict[str, Any],
    name: str,
    primitive_type: str,
    install_target: Path,
    incoming_source: str,
    incoming_marketplace: str | None,
) -> tuple[bool, dict[str, Any] | None]:
    """Detect a same-name install target owned by another source.

    Same-marketplace refreshes intentionally remain last-write-wins. A target
    without a lockfile entry is treated as an unknown source and therefore
    requires an explicit resolution flag before overwrite.
    """
    if not (install_target.exists() or install_target.is_symlink()):
        return False, None

    existing = find_installed_entry(lock_data, name, primitive_type)
    if existing is None:
        return True, None

    existing_source = existing.get("source")
    existing_marketplace = existing.get("marketplace")
    if existing_source == incoming_source:
        return False, existing
    if (
        existing_marketplace
        and incoming_marketplace
        and existing_marketplace == incoming_marketplace
        and incoming_marketplace not in {"local", "unknown"}
    ):
        return False, existing

    return True, existing


def collision_result(
    *,
    primitive_type: str,
    name: str,
    install_target: Path,
    existing: dict[str, Any] | None,
    incoming_source: str,
) -> dict[str, Any]:
    """Build the standard blocked collision response."""
    existing_source = "<untracked>"
    if existing is not None:
        existing_source = str(existing.get("source") or "<unknown>")

    return {
        "status": "blocked",
        "reason": (
            f"Name collision detected for {primitive_type} '{name}' at "
            f"{install_target}. Existing source: {existing_source}. "
            f"Requested source: {incoming_source}."
        ),
        "suggestion": (
            "Choose an explicit resolution: --replace to overwrite, "
            "--merge-into=<canonical-repo> to reconcile into the canonical "
            "source, or --skip to leave the existing install unchanged."
        ),
        "options": COLLISION_OPTIONS,
        "data": {
            "name": name,
            "primitive": primitive_type,
            "install_target": str(install_target),
            "existing_source": existing_source,
            "incoming_source": incoming_source,
        },
    }


def skip_collision_result(
    *,
    primitive_type: str,
    name: str,
    install_target: Path,
    merge_into: str | None = None,
) -> dict[str, Any]:
    """Return an OK response for explicit skip or manual merge resolution."""
    data: dict[str, Any] = {
        "name": name,
        "primitive": primitive_type,
        "install_target": str(install_target),
        "skipped": True,
    }
    if merge_into:
        data["merge_into"] = merge_into
        message = (
            f"{primitive_type.title()} '{name}' install skipped. Merge the new "
            f"content into {merge_into}, then reinstall from that canonical source."
        )
    else:
        message = (
            f"{primitive_type.title()} '{name}' install skipped; existing install "
            "left unchanged."
        )
    return {"status": "ok", "data": data, "message": message}
