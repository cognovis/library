"""Install project-only harness-native Pi assets and Just modules."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..cache import compute_cache_path
from ..catalog import get_catalog_identity, lookup_entry
from ..errors import InstallError
from ..lockfile import (
    compute_checksum,
    compute_directory_hash,
    find_lockfile,
    get_entry,
    load_lockfile,
    make_entry,
    remove_entry,
    resolve_lockfile_path,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..source import parse_source, resolve_marketplace
from .simple_file import _cleanup_temp, _fetch_file_source

PROJECT_NATIVE_TARGETS = {
    "pi-extension": Path(".agents/pi/extensions"),
    "pi-profile": Path(".agents/pi/profiles"),
    "just-module": Path(".agents/just"),
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# `just` only discovers a justfile in the invocation directory or one of its
# parents, and it resolves recipe-relative paths against the directory holding
# the *root* justfile. A generated aggregator that lives under .agents/just/ is
# therefore never found from the repository root, and even when passed via
# --justfile it runs with .agents/just/ as the working directory, which breaks
# the repository-root-relative paths every just-module recipe is written
# against. The aggregator stays where it is (Library owns that file) and a
# managed import block in the root justfile provides the entry point.
JUST_ROOT_BLOCK_BEGIN = "# >>> library:just-modules >>>"
JUST_ROOT_BLOCK_END = "# <<< library:just-modules <<<"
_ROOT_JUSTFILE_NAMES = ("justfile", "Justfile", ".justfile", "JUSTFILE")
_DEFAULT_ROOT_JUSTFILE = "Justfile"


def require_project_native_request(primitive: str, name: str, scope: str) -> None:
    """Reject unsupported scope or unsafe names before filesystem mutation."""
    if primitive not in PROJECT_NATIVE_TARGETS:
        raise InstallError(f"Unknown project-native primitive: {primitive}")
    if scope != "project":
        raise InstallError(f"{primitive} is project-only and cannot use {scope} scope.")
    if not _SAFE_NAME.fullmatch(name) or name in {".", ".."}:
        raise InstallError(
            f"Invalid {primitive} name '{name}': names must be a single safe filename segment."
        )


def _extension(entry: dict[str, Any], name: str) -> str:
    source = entry.get("source") or ""
    if not source:
        raise InstallError(f"'{name}' has no source field.")
    parsed = parse_source(source)
    source_path = (
        parsed.local_path
        if parsed.is_local()
        else (Path(parsed.file_path) if parsed.file_path else None)
    )
    suffix = source_path.suffix if source_path is not None else ""
    if not suffix:
        raise InstallError(f"'{name}' source must reference a file with an extension.")
    return suffix


def _is_bundle(entry: dict[str, Any], primitive: str) -> bool:
    bundle = entry.get("bundle", False)
    if not isinstance(bundle, bool):
        raise InstallError(f"'{entry.get('name')}' bundle must be a boolean.")
    if bundle and primitive != "pi-extension":
        raise InstallError("Only pi-extension entries can be installed as bundles.")
    return bundle


def _target(
    repo_root: Path,
    primitive: str,
    name: str,
    suffix: str,
    *,
    bundle: bool,
) -> Path:
    root = repo_root.resolve()
    base = (root / PROJECT_NATIVE_TARGETS[primitive]).resolve()
    if not base.is_relative_to(root):
        raise InstallError(
            f"Refusing {primitive} '{name}': fixed target resolves outside {root}."
        )
    target = base / (name if bundle else f"{name}{suffix}")
    if target.parent != base:
        raise InstallError(f"Invalid {primitive} target for '{name}'.")
    return target


def _remove_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(str(target))


def _aggregator_import_path() -> str:
    """Return the root-justfile import path for the generated aggregator."""
    return (PROJECT_NATIVE_TARGETS["just-module"] / "Justfile").as_posix()


def find_root_justfile(repo_root: Path) -> Path | None:
    """Return the existing root justfile, honouring every name `just` accepts."""
    root = repo_root.resolve()
    for name in _ROOT_JUSTFILE_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _managed_block() -> str:
    # `import?` keeps the root justfile valid when the aggregator is absent,
    # which is the state right after the last just-module is removed.
    return (
        f"{JUST_ROOT_BLOCK_BEGIN}\n"
        "# Managed by Library. Edits inside this block are overwritten.\n"
        f"import? '{_aggregator_import_path()}'\n"
        f"{JUST_ROOT_BLOCK_END}\n"
    )


def _imports_aggregator(text: str) -> bool:
    """Report whether a justfile already imports the generated aggregator."""
    pattern = re.compile(
        r"^\s*import\??\s+['\"](?:\./)?"
        + re.escape(_aggregator_import_path())
        + r"['\"]",
        re.MULTILINE,
    )
    return bool(pattern.search(text))


def _strip_managed_block(text: str) -> str:
    """Drop the managed import block, leaving hand-written content untouched."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == JUST_ROOT_BLOCK_BEGIN:
            inside = True
            continue
        if stripped == JUST_ROOT_BLOCK_END:
            inside = False
            continue
        if not inside:
            kept.append(line)
    return "".join(kept)


def _write_root_justfile_entrypoint(repo_root: Path, has_modules: bool) -> None:
    """Keep the root justfile's managed import block in sync with the lockfile.

    Without this the aggregator is unreachable: `just <recipe>` from the
    repository root fails with "no justfile found".
    """
    root = repo_root.resolve()
    existing = find_root_justfile(root)
    target = existing if existing is not None else root / _DEFAULT_ROOT_JUSTFILE
    if target.resolve().parent != root:
        raise InstallError(f"Refusing to write root justfile outside {root}.")

    current = existing.read_text() if existing is not None else ""
    remainder = _strip_managed_block(current)

    if not has_modules:
        if existing is None:
            return
        if current == remainder:
            return
        if remainder.strip():
            existing.write_text(remainder)
        else:
            existing.unlink()
        return

    # A hand-maintained import already wires the aggregator up: leave the file
    # byte-identical rather than adding a duplicate import.
    if _imports_aggregator(remainder):
        if current != remainder:
            existing.write_text(remainder)  # type: ignore[union-attr]
        return

    if not remainder.strip():
        target.write_text(_managed_block())
        return
    if remainder.endswith("\n\n"):
        separator = ""
    elif remainder.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    target.write_text(remainder + separator + _managed_block())


def _write_just_aggregator(repo_root: Path, lock_data: dict[str, Any]) -> None:
    root = repo_root.resolve()
    base = (root / PROJECT_NATIVE_TARGETS["just-module"]).resolve()
    if not base.is_relative_to(root):
        raise InstallError(f"Refusing to write Just aggregator outside {root}.")
    imports: list[str] = []
    for locked in lock_data.get("installed", []):
        if locked.get("type") != "just-module":
            continue
        target = resolve_lockfile_path(
            str(locked.get("install_target", "")), root
        )
        if target.parent.resolve() != base or target.suffix != ".just":
            raise InstallError(
                f"Refusing unsafe Just module target in lockfile: {target}."
            )
        imports.append(f"import '{target.name}'")
    aggregator = base / "Justfile"
    if not imports:
        if aggregator.exists():
            aggregator.unlink()
        _write_root_justfile_entrypoint(root, has_modules=False)
        return
    base.mkdir(parents=True, exist_ok=True)
    aggregator.write_text(
        "# Generated by Library from installed just-module entries.\n"
        + "\n".join(sorted(imports))
        + "\n"
    )
    _write_root_justfile_entrypoint(root, has_modules=True)


def install_project_native_file(
    catalog: dict,
    primitive: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Install a project-local Pi extension, Pi profile, or Just module."""
    if install_mode not in {"vendor", "symlink"}:
        raise InstallError(f"Unknown install mode: {install_mode}")
    entry = lookup_entry(catalog, primitive, name, fuzzy=True)
    item_name = entry.get("name", name)
    require_project_native_request(primitive, item_name, scope)
    bundle = _is_bundle(entry, primitive)
    suffix = "" if bundle else _extension(entry, item_name)
    target = _target(repo_root, primitive, item_name, suffix, bundle=bundle)
    lockfile_path = find_lockfile(repo_root, global_scope=False)
    marketplace = resolve_marketplace(catalog, entry)

    if dry_run:
        return dry_run_result(
            [
                {
                    "operation": "materialize_cache",
                    "path": f"~/.local/share/library/{primitive}s/{marketplace}/{item_name}@<sha>/",
                    "details": "copy source -> Layer-B cache",
                },
                {
                    "operation": (
                        "vendor_directory"
                        if bundle and install_mode == "vendor"
                        else "vendor_file"
                        if install_mode == "vendor"
                        else "create_symlink"
                    ),
                    "path": str(target),
                    "details": f"install {primitive} '{item_name}'",
                    "existing_target": target.exists() or target.is_symlink(),
                },
                {
                    "operation": "write_lockfile",
                    "path": str(lockfile_path),
                    "details": f"upsert entry '{item_name}'",
                },
                *(
                    [
                        {
                            "operation": "write_just_aggregator",
                            "path": str(
                                repo_root
                                / PROJECT_NATIVE_TARGETS["just-module"]
                                / "Justfile"
                            ),
                            "details": f"include Just module '{item_name}'",
                        },
                        {
                            "operation": "write_just_root_entrypoint",
                            "path": str(
                                find_root_justfile(repo_root)
                                or repo_root / _DEFAULT_ROOT_JUSTFILE
                            ),
                            "details": (
                                "add managed import of "
                                f"{_aggregator_import_path()} to the root justfile"
                            ),
                        },
                    ]
                    if primitive == "just-module"
                    else []
                ),
            ],
            summary=f"Would install {primitive} '{item_name}' to {target}",
            target_paths=[str(target)],
            harness_routing=None,
            conflict_policy="overwrite",
            lockfile_changes=[
                {"path": str(lockfile_path), "operation": "upsert", "entry": item_name}
            ],
            requires_user_confirmation=False,
        )

    source = entry["source"]
    source_file, source_commit, temp_root = _fetch_file_source(
        parse_source(source), item_name
    )
    try:
        if bundle:
            if not source_file.is_dir():
                raise InstallError(
                    f"{primitive} '{item_name}' bundle source must resolve to one directory."
                )
            entrypoint = entry.get("entrypoint", "index.ts")
            if (
                not isinstance(entrypoint, str)
                or Path(entrypoint).name != entrypoint
                or entrypoint in {".", ".."}
            ):
                raise InstallError(
                    f"{primitive} '{item_name}' entrypoint must be one safe filename."
                )
            if not (source_file / entrypoint).is_file():
                raise InstallError(
                    f"{primitive} '{item_name}' bundle has no entrypoint {entrypoint}."
                )
        elif not source_file.is_file() or source_file.suffix != suffix:
            raise InstallError(
                f"{primitive} '{item_name}' source must resolve to one file."
            )
        cache_path = compute_cache_path(
            primitive, marketplace, item_name, source_commit
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))
        cache_path.mkdir(parents=True)
        cached_artifact = cache_path / (item_name if bundle else f"{item_name}{suffix}")
        if bundle:
            shutil.copytree(str(source_file), str(cached_artifact))
        else:
            shutil.copy2(str(source_file), str(cached_artifact))

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            _remove_target(target)
        if install_mode == "vendor":
            if bundle:
                shutil.copytree(str(cached_artifact), str(target))
            else:
                shutil.copy2(str(cached_artifact), str(target))
        else:
            target.symlink_to(cached_artifact, target_is_directory=bundle)

        installed = target.resolve() if target.is_symlink() else target
        checksum = (
            compute_directory_hash(installed)
            if bundle
            else compute_checksum(installed)
        )
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(
            lock_data,
            make_entry(
                name=item_name,
                primitive_type=primitive,
                catalog_identity=get_catalog_identity(catalog),
                marketplace=marketplace,
                source=source,
                source_commit=source_commit,
                cache_path=str(cache_path) + "/",
                install_target=str(target),
                checksum_sha256=checksum,
                content_sha256=checksum,
                checksum_type="directory" if bundle else "file",
                install_mode=install_mode,
                license_id=entry.get("license", "unknown"),
                scope=scope,
                version=str(entry.get("version")) if entry.get("version") is not None else None,
            ),
        )
        save_lockfile(lockfile_path, lock_data)
        if primitive == "just-module":
            _write_just_aggregator(repo_root, lock_data)
        return success(
            data={
                "name": item_name,
                "install_target": str(target),
                "cache": str(cache_path),
                "source_commit": source_commit,
                "install_mode": install_mode,
            },
            message=f"{primitive.title()} '{item_name}' installed at {target}",
        )
    finally:
        _cleanup_temp(temp_root)


def remove_project_native_file(
    primitive: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove a project-native file from its lockfile-recorded target."""
    require_project_native_request(primitive, name, scope)
    lockfile_path = find_lockfile(repo_root, global_scope=False)
    lock_data = load_lockfile(lockfile_path)
    locked = get_entry(lock_data, name, primitive_type=primitive)
    root = repo_root.resolve()
    target = (
        resolve_lockfile_path(str(locked["install_target"]), root)
        if locked
        else None
    )
    expected_base = (root / PROJECT_NATIVE_TARGETS[primitive]).resolve()
    if not expected_base.is_relative_to(root):
        raise InstallError(
            f"Refusing to remove {primitive} '{name}': target resolves outside {root}."
        )
    if target is not None and target.parent.resolve() != expected_base:
        raise InstallError(
            f"Refusing to remove {primitive} '{name}' outside {expected_base}."
        )

    if dry_run:
        operations = []
        if target is not None and (target.exists() or target.is_symlink()):
            operations.append(
                {
                    "operation": "delete",
                    "path": str(target),
                    "details": f"remove {target}",
                }
            )
        operations.append(
            {
                "operation": "remove_lockfile_entry",
                "path": str(lockfile_path),
                "details": f"remove '{name}'",
            }
        )
        return dry_run_result(operations, summary=f"Would remove {primitive} '{name}'")

    removed = []
    if target is not None and (target.exists() or target.is_symlink()):
        _remove_target(target)
        removed.append(str(target))
    remove_entry(lock_data, name, primitive_type=primitive)
    save_lockfile(lockfile_path, lock_data)
    if primitive == "just-module":
        _write_just_aggregator(repo_root, lock_data)
    return success(
        data={"name": name, "removed_files": removed},
        message=f"{primitive.title()} '{name}' removed.",
    )
