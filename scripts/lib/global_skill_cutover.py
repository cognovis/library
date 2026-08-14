"""Guarded cutover from legacy global Skills to repository-local Workspaces."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

from .errors import LibraryError
from .lockfile import compute_checksum
from .providers.local_git import canonical_checkout_problem
from .providers.state_files import atomic_write_text, exclusive_lock
from .workspace import workspace_path_state


def load_approved_fleet(manifest_path: Path) -> dict[str, object]:
    """Load the operator-approved exact fleet and its published Git proofs."""
    path = manifest_path.expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryError(f"Approved fleet manifest is unreadable: {path}") from exc
    approval = payload.get("approval") if isinstance(payload, dict) else None
    repositories = payload.get("repositories") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("bead_id") != "CL-31po"
        or not isinstance(approval, dict)
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
        or not isinstance(repositories, list)
        or not repositories
    ):
        raise LibraryError(f"Approved fleet manifest is invalid: {path}")

    normalized: list[dict[str, str]] = []
    seen: set[Path] = set()
    for item in repositories:
        if not isinstance(item, dict):
            raise LibraryError(f"Approved fleet manifest is invalid: {path}")
        repository = Path(str(item.get("path") or "")).expanduser()
        branch = str(item.get("branch") or "").strip()
        commit = str(item.get("published_commit") or "").strip().lower()
        remote = str(item.get("remote") or "").strip()
        if (
            not repository.is_absolute()
            or not branch
            or not remote
            or len(commit) != 40
            or any(character not in "0123456789abcdef" for character in commit)
        ):
            raise LibraryError(f"Approved fleet manifest is invalid: {path}")
        repository = repository.resolve()
        if repository in seen:
            raise LibraryError(
                f"Approved fleet manifest lists a repository more than once: {repository}"
            )
        seen.add(repository)
        normalized.append(
            {
                "path": str(repository),
                "branch": branch,
                "published_commit": commit,
                "remote": remote,
            }
        )
    return {
        "path": str(path),
        "sha256": compute_checksum(path),
        "approved_by": str(approval["approved_by"]),
        "approved_at": str(approval["approved_at"]),
        "repositories": normalized,
    }


def inspect_repositories(
    repositories: list[Path],
    *,
    approvals: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Return canonical-checkout blockers before any cutover state is created."""
    results: list[dict[str, str]] = []
    seen: set[Path] = set()
    for supplied in repositories:
        repository = supplied.expanduser().resolve()
        reason: str | None = None
        approval: dict[str, str] | None = None
        if repository in seen:
            reason = "repository is listed more than once"
        elif not (repository / ".beads" / "config.yaml").is_file():
            reason = ".beads/config.yaml is missing"
        else:
            approval = approvals.get(str(repository)) if approvals is not None else None
            if approvals is not None and approval is None:
                reason = "repository is absent from the approved fleet manifest"
            else:
                reason = canonical_checkout_problem(
                    repository,
                    expected_branch=(approval or {}).get("branch"),
                    expected_commit=(approval or {}).get("published_commit"),
                    expected_remote=(approval or {}).get("remote"),
                )
            if reason is None and not (repository / ".library.lock").is_file():
                reason = ".library.lock is missing"
        seen.add(repository)
        results.append(
            {
                "path": str(repository),
                "status": "blocked" if reason else "ready",
                **(
                    {
                        "branch": str(approval["branch"]),
                        "published_commit": str(approval["published_commit"]),
                        "remote": str(approval["remote"]),
                    }
                    if not reason and approval is not None
                    else {}
                ),
                **({"reason": reason} if reason else {}),
            }
        )
    return results


def _bounded_target(path: Path, home: Path) -> Path | None:
    """Return an exact deletion path only inside a recognized Skill root."""
    if not path.is_absolute():
        return None
    target = path.parent.resolve() / path.name
    roots = (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "skills",
        home / ".pi" / "skills",
        home / ".cursor" / "skills",
        home / ".opencode" / "skills",
    )
    canonical_roots = [root.resolve() for root in roots]
    return (
        target if any(target.is_relative_to(root) for root in canonical_roots) else None
    )


def managed_skill_roots(home: Path) -> tuple[Path, ...]:
    """Return supported and retired historical roots accepted for cutover evidence."""
    return tuple(
        (home / relative).resolve()
        for relative in (
            ".agents/skills",
            ".claude/skills",
            ".codex/skills",
            ".pi/skills",
            ".cursor/skills",
            ".opencode/skills",
        )
    )


def inspect_skill_receipts(lock: dict, home: Path) -> list[dict[str, str]]:
    """Verify exact global Skill ownership without changing the lock or targets."""
    results: list[dict[str, str]] = []
    owned_paths: dict[Path, str] = {}
    receipts = [
        receipt
        for receipt in lock.get("receipts", [])
        if isinstance(receipt, dict) and receipt.get("type") == "skill"
    ]
    for receipt in receipts:
        receipt_id = str(receipt.get("id") or "")
        skill_name = str(receipt.get("name") or "")
        reason: str | None = None
        targets = receipt.get("targets") or []
        if receipt.get("scope") != "global":
            reason = "receipt scope is not global"
        elif receipt_id != f"skill:{receipt.get('name', '')}":
            reason = "receipt identity does not match its Skill name"
        elif receipt.get("verified") is not True:
            reason = "receipt is not verified"
        elif not isinstance(targets, list) or not targets:
            reason = "receipt has no exact target inventory"

        resolved: list[tuple[dict, Path]] = []
        if reason is None:
            for target in targets:
                if not isinstance(target, dict):
                    reason = "receipt target inventory is invalid"
                    break
                path = _bounded_target(
                    Path(str(target.get("path") or "")).expanduser(), home
                )
                if path is None:
                    reason = f"target is outside managed Skill roots: {target.get('path', '')}"
                    break
                previous_owner = owned_paths.get(path)
                if previous_owner is not None and previous_owner != receipt_id:
                    reason = f"target is also owned by {previous_owner}: {path}"
                    break
                owned_paths[path] = receipt_id
                resolved.append((target, path))

        inventory_paths = {path for _target, path in resolved}
        install_target: Path | None = None
        if reason is None:
            install_target = _bounded_target(
                Path(str(receipt.get("install_target") or "").rstrip("/")).expanduser(),
                home,
            )
            if install_target is None or install_target not in inventory_paths:
                reason = "install target is absent from the exact target inventory"
            elif (
                install_target.name != skill_name
                or install_target.parent not in managed_skill_roots(home)
            ):
                reason = (
                    f"install target does not match the Skill name: {install_target}"
                )
        if reason is None:
            for bridge in receipt.get("bridge_symlinks") or []:
                raw_path, separator, raw_target = str(bridge).partition(" -> ")
                bridge_path = _bounded_target(Path(raw_path).expanduser(), home)
                matching = next(
                    (
                        target
                        for target, path in resolved
                        if path == bridge_path
                        and target.get("kind") == "symlink"
                        and str(target.get("link_target") or "") == raw_target
                    ),
                    None,
                )
                if not separator or bridge_path is None:
                    reason = (
                        f"bridge is absent from the exact target inventory: {bridge}"
                    )
                    break
                if (
                    bridge_path.name != skill_name
                    or bridge_path.parent not in managed_skill_roots(home)
                ):
                    reason = f"bridge does not match the Skill name: {bridge_path}"
                    break
                if matching is None:
                    reason = (
                        f"bridge is absent from the exact target inventory: {bridge}"
                    )
                    break

        if reason is None and install_target is not None:
            declared_bridges = {
                _bounded_target(
                    Path(str(bridge).partition(" -> ")[0]).expanduser(), home
                )
                for bridge in receipt.get("bridge_symlinks") or []
            }
            uncovered = sorted(
                (
                    path
                    for path in inventory_paths
                    if not path.is_relative_to(install_target)
                    and path not in declared_bridges
                ),
                key=str,
            )
            if uncovered:
                reason = f"target is not covered by the install target or a bridge: {uncovered[0]}"
        if reason is None:
            unrecorded_projection = next(
                (
                    root / skill_name
                    for root in managed_skill_roots(home)
                    if (
                        (root / skill_name).exists() or (root / skill_name).is_symlink()
                    )
                    and (root / skill_name) not in inventory_paths
                ),
                None,
            )
            if unrecorded_projection is not None:
                reason = f"unrecorded Skill projection at {unrecorded_projection}"

        if reason is None:
            for target, path in resolved:
                kind = str(target.get("kind") or "")
                if kind == "directory":
                    if not path.is_dir() or path.is_symlink():
                        reason = f"directory drift at {path}"
                        break
                    actual_nested = {
                        child.parent.resolve() / child.name for child in path.rglob("*")
                    }
                    recorded_nested = {
                        recorded
                        for recorded in inventory_paths
                        if recorded != path and recorded.is_relative_to(path)
                    }
                    if actual_nested != recorded_nested:
                        reason = f"unrecorded nested content at {path}"
                        break
                elif kind == "symlink":
                    if not path.is_symlink() or str(path.readlink()) != str(
                        target.get("link_target") or ""
                    ):
                        reason = f"symlink drift at {path}"
                        break
                elif kind == "file":
                    expected = str(target.get("content_sha256") or "")
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or not expected
                        or compute_checksum(path) != expected
                    ):
                        reason = f"content drift at {path}"
                        break
                else:
                    reason = f"unsupported target kind at {path}"
                    break

        results.append(
            {
                "id": receipt_id,
                "status": "blocked" if reason else "ready",
                **({"reason": reason} if reason else {}),
            }
        )
    return results


def inspect_source_registry(config_home: Path) -> dict[str, object]:
    """Verify the installer-managed catalog checkout registry used for pin checks."""
    registry = config_home / "library" / "catalog-sources.json"
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "blocked",
            "reason": f"catalog source registry is unavailable: {registry}",
        }
    catalogs = payload.get("catalogs")
    if (
        payload.get("schema_version") != 1
        or not isinstance(catalogs, list)
        or not catalogs
    ):
        return {
            "status": "blocked",
            "reason": f"catalog source registry is invalid: {registry}",
        }
    for item in catalogs:
        if not isinstance(item, dict):
            return {
                "status": "blocked",
                "reason": f"catalog source registry is invalid: {registry}",
            }
        checkout = Path(str(item.get("checkout") or "")).expanduser()
        if not checkout.is_absolute() or not checkout.is_dir():
            return {
                "status": "blocked",
                "reason": f"registered catalog checkout is unavailable: {checkout}",
            }
    return {"status": "ready", "path": str(registry), "catalogs": len(catalogs)}


def load_cutover_lock(lock_path: Path) -> dict:
    """Load the v2 migration inventory without normalizing unrelated receipts."""
    try:
        payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LibraryError(f"Global migration lock is unreadable: {lock_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise LibraryError(
            f"Global migration lock is not schema version 2: {lock_path}"
        )
    for collection in ("requested_roots", "receipts", "installed"):
        if not isinstance(payload.get(collection), list):
            raise LibraryError(
                f"Global migration lock has invalid {collection}: {lock_path}"
            )
    return payload


def _candidate_roots(lock: dict, home: Path) -> list[Path]:
    roots: set[Path] = set()
    for receipt in lock.get("receipts", []):
        if not isinstance(receipt, dict) or receipt.get("type") != "skill":
            continue
        install_target = _bounded_target(
            Path(str(receipt.get("install_target") or "").rstrip("/")).expanduser(),
            home,
        )
        if install_target is None:
            raise LibraryError(
                f"Skill receipt has an unbounded install target: {receipt.get('id', '')}"
            )
        roots.add(install_target)
        for bridge in receipt.get("bridge_symlinks") or []:
            raw_path, separator, _raw_target = str(bridge).partition(" -> ")
            bridge_path = _bounded_target(Path(raw_path).expanduser(), home)
            if not separator or bridge_path is None:
                raise LibraryError(
                    f"Skill receipt has an unbounded bridge: {receipt.get('id', '')}"
                )
            roots.add(bridge_path)
    return sorted(roots, key=lambda path: str(path))


def _copy_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(source.readlink())
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise LibraryError(f"Cutover target disappeared before backup: {source}")


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        raise LibraryError(f"Cutover target has an unsupported type: {path}")


def _restore_path(backup: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        _remove_path(destination)
    _copy_path(backup, destination)


def _without_skills(lock: dict) -> dict:
    result = json.loads(json.dumps(lock))
    for collection in ("requested_roots", "receipts", "installed"):
        result[collection] = [
            item
            for item in result.get(collection, [])
            if not isinstance(item, dict) or item.get("type") != "skill"
        ]
    return result


def execute_cutover(
    *,
    lock_path: Path,
    home: Path,
    backup: Path,
    preflight: Callable[[], None],
) -> dict[str, object]:
    """Back up and transactionally remove every verified global Skill receipt."""
    expanded_backup = Path(os.path.abspath(backup.expanduser()))
    backup = expanded_backup.parent.resolve() / expanded_backup.name
    if backup.exists() or backup.is_symlink():
        raise LibraryError(f"Cutover backup destination already exists: {backup}")
    if not backup.parent.is_dir():
        raise LibraryError(f"Cutover backup parent does not exist: {backup.parent}")

    with exclusive_lock(lock_path):
        preflight()
        lock = load_cutover_lock(lock_path)
        inspections = inspect_skill_receipts(lock, home)
        blocked = [item for item in inspections if item["status"] != "ready"]
        if blocked:
            raise LibraryError(
                "Global Skill ownership changed before backup: "
                + "; ".join(f"{item['id']}: {item['reason']}" for item in blocked)
            )
        skill_ids = [str(item["id"]) for item in inspections]
        targets = _candidate_roots(lock, home)
        overlapping_target = next(
            (
                target
                for target in targets
                if backup == target
                or backup.is_relative_to(target)
                or target.is_relative_to(backup)
            ),
            None,
        )
        if overlapping_target is not None:
            raise LibraryError(
                "Cutover backup destination overlaps a Skill removal target: "
                f"{overlapping_target}"
            )
        original_lock = lock_path.read_bytes()
        retained_before = {
            collection: [
                item
                for item in lock.get(collection, [])
                if not isinstance(item, dict) or item.get("type") != "skill"
            ]
            for collection in ("requested_roots", "receipts", "installed")
        }
        try:
            backup.mkdir()
            backup_lock = backup / "global.lock"
            shutil.copy2(lock_path, backup_lock)
            manifest_targets: list[dict[str, object]] = []
            for index, source in enumerate(targets):
                captured = backup / "targets" / f"{index:04d}"
                _copy_path(source, captured)
                source_state = workspace_path_state(source)
                backup_state = workspace_path_state(captured)
                if source_state != backup_state:
                    raise LibraryError(
                        f"Cutover backup integrity check failed: {source}"
                    )
                manifest_targets.append(
                    {
                        "source": str(source),
                        "backup": str(captured),
                        "source_state": source_state,
                        "backup_state": backup_state,
                    }
                )
            lock_state = workspace_path_state(lock_path)
            backup_lock_state = workspace_path_state(backup_lock)
            if lock_state != backup_lock_state:
                raise LibraryError(
                    f"Cutover global lock backup integrity check failed: {lock_path}"
                )
            manifest = {
                "schema_version": 1,
                "global_lock": {
                    "source": str(lock_path),
                    "backup": str(backup_lock),
                    "source_state": lock_state,
                    "backup_state": backup_lock_state,
                },
                "targets": manifest_targets,
                "skill_receipts": skill_ids,
            }
            atomic_write_text(
                backup / "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
        except (LibraryError, OSError) as exc:
            raise LibraryError(
                f"Global Skill backup failed before removal; global state retained: {exc}"
            ) from exc

        preflight()
        final_inspections = inspect_skill_receipts(lock, home)
        final_blocked = [
            item for item in final_inspections if item["status"] != "ready"
        ]
        if final_blocked:
            raise LibraryError(
                "Global Skill ownership changed after backup: "
                + "; ".join(f"{item['id']}: {item['reason']}" for item in final_blocked)
            )

        try:
            for target in targets:
                _remove_path(target)
            final_lock = _without_skills(lock)
            atomic_write_text(
                lock_path,
                yaml.safe_dump(final_lock, sort_keys=False),
            )
            persisted = load_cutover_lock(lock_path)
            remaining = [
                item
                for item in persisted.get("receipts", [])
                if isinstance(item, dict) and item.get("type") == "skill"
            ]
            if remaining:
                raise LibraryError("Global Skill receipts remain after cutover")
            retained_after = {
                collection: [
                    item
                    for item in persisted.get(collection, [])
                    if not isinstance(item, dict) or item.get("type") != "skill"
                ]
                for collection in ("requested_roots", "receipts", "installed")
            }
            if retained_after != retained_before:
                raise LibraryError("Non-Skill global receipts changed during cutover")
            remaining_targets = [
                str(target)
                for target in targets
                if target.exists() or target.is_symlink()
            ]
            if remaining_targets:
                raise LibraryError(
                    "Global Skill projections remain after cutover: "
                    + ", ".join(remaining_targets)
                )
        except BaseException as exc:
            restoration_errors: list[str] = []
            for item in reversed(manifest_targets):
                try:
                    _restore_path(Path(str(item["backup"])), Path(str(item["source"])))
                except Exception as restore_exc:
                    restoration_errors.append(str(restore_exc))
            try:
                atomic_write_text(lock_path, original_lock.decode("utf-8"))
            except Exception as restore_exc:
                restoration_errors.append(str(restore_exc))
            if restoration_errors:
                raise LibraryError(
                    "Global Skill cutover failed and restoration was incomplete: "
                    + "; ".join(restoration_errors)
                ) from exc
            raise LibraryError(
                f"Global Skill cutover failed; original state restored: {exc}"
            ) from exc

    return {
        "backup": str(backup),
        "removed_skill_receipts": skill_ids,
        "global_skill_receipts": 0,
    }
