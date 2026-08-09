"""Install directory-backed Python Script primitives with ``uv tool``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..cache import compute_cache_path
from ..catalog import get_catalog_identity, lookup_entry
from ..errors import InstallError
from ..lockfile import (
    compute_directory_hash,
    find_lockfile,
    load_lockfile,
    make_entry,
    remove_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..source import (
    ParsedSource,
    clone_source_repo,
    get_local_commit_sha,
    parse_source,
    resolve_marketplace,
)

UV_TIMEOUT_SECONDS = 600


def install_uv_tool(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "global",
    dry_run: bool = False,
    harness: str = "all",
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Install one directory-backed Script primitive as a global uv tool."""
    del harness
    if scope != "global":
        raise InstallError(f"uv-tool Script '{name}' requires global scope.")
    if install_mode != "vendor":
        raise InstallError(f"uv-tool Script '{name}' does not support symlink mode.")

    entry = lookup_entry(catalog, "script", name)
    item_name = str(entry.get("name") or name)
    distribution = _distribution(entry, item_name)
    source = str(entry.get("source") or "")
    if not source:
        raise InstallError(f"Script '{item_name}' has no source field.")

    marketplace = resolve_marketplace(catalog, entry) or "unknown"
    bin_dir = _uv_bin_dir()
    executable_paths = [bin_dir / value for value in distribution["executables"]]
    lockfile_path = find_lockfile(repo_root, global_scope=True)
    cache_preview = compute_cache_path("script", marketplace, item_name, "<sha>")

    if dry_run:
        operations = [
            {
                "operation": "materialize_cache",
                "path": str(cache_preview),
                "details": "copy the Python distribution into the immutable Library cache",
            },
            {
                "operation": "uv_tool_install",
                "path": str(executable_paths[0]),
                "details": (
                    f"install {distribution['package_name']} with uv tool and expose "
                    f"{', '.join(distribution['executables'])}"
                ),
            },
            {
                "operation": "write_lockfile",
                "path": str(lockfile_path),
                "details": f"upsert entry '{item_name}'",
            },
        ]
        return dry_run_result(
            operations,
            summary=f"Would install uv-tool Script '{item_name}'",
            target_paths=executable_paths,
            harness_routing=None,
            conflict_policy="overwrite",
            lockfile_changes=[
                {
                    "path": str(lockfile_path),
                    "operation": "upsert",
                    "entry": item_name,
                }
            ],
        )

    source_root, source_commit, temp_root = _fetch_distribution_source(
        parse_source(source), item_name
    )
    try:
        pyproject = source_root / "pyproject.toml"
        if not pyproject.is_file():
            raise InstallError(
                f"uv-tool Script '{item_name}' source has no pyproject.toml: {source_root}"
            )

        cache_path = compute_cache_path("script", marketplace, item_name, source_commit)
        if cache_path.exists():
            shutil.rmtree(cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, cache_path)

        command = ["uv", "tool", "install", "--force", str(cache_path)]
        installed = _run_uv(command)
        if installed.returncode != 0:
            detail = installed.stderr.strip() or installed.stdout.strip()
            raise InstallError(
                f"uv tool install failed for Script '{item_name}': {detail or 'unknown error'}"
            )

        missing = [str(path) for path in executable_paths if not path.is_file()]
        if missing:
            raise InstallError(
                f"uv-tool Script '{item_name}' did not install declared executables: "
                + ", ".join(missing)
            )

        primary = executable_paths[0]
        checksum = compute_directory_hash(cache_path)
        receipt = make_entry(
            name=item_name,
            primitive_type="script",
            catalog_identity=get_catalog_identity(catalog),
            marketplace=marketplace,
            source=source,
            source_commit=source_commit,
            cache_path=str(cache_path),
            install_target=str(primary),
            checksum_sha256=checksum,
            content_sha256=checksum,
            checksum_type="directory",
            install_mode="vendor",
            license_id=str(entry.get("license") or "unknown"),
            scope="global",
            version=str(entry.get("version"))
            if entry.get("version") is not None
            else None,
        )
        lock = load_lockfile(lockfile_path)
        upsert_entry(lock, receipt)
        save_lockfile(lockfile_path, lock)

        return success(
            data={
                "name": item_name,
                "package_name": distribution["package_name"],
                "executables": [str(path) for path in executable_paths],
                "install_target": str(primary),
                "cache": str(cache_path),
                "source_commit": source_commit,
                "install_mode": "uv-tool",
            },
            message=f"uv-tool Script '{item_name}' installed",
        )
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def remove_uv_tool(
    catalog: dict,
    name: str,
    repo_root: Path,
    scope: str = "global",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove a receipted uv-tool Script primitive."""
    if scope != "global":
        raise InstallError(f"uv-tool Script '{name}' requires global scope.")
    entry = lookup_entry(catalog, "script", name)
    item_name = str(entry.get("name") or name)
    distribution = _distribution(entry, item_name)
    lockfile_path = find_lockfile(repo_root, global_scope=True)

    if dry_run:
        return dry_run_result(
            [
                {
                    "operation": "uv_tool_uninstall",
                    "path": distribution["package_name"],
                    "details": f"uninstall uv tool package {distribution['package_name']}",
                },
                {
                    "operation": "remove_lockfile_entry",
                    "path": str(lockfile_path),
                    "details": f"remove '{item_name}'",
                },
            ],
            summary=f"Would remove uv-tool Script '{item_name}'",
        )

    removed = _run_uv(["uv", "tool", "uninstall", distribution["package_name"]])
    if removed.returncode != 0:
        detail = removed.stderr.strip() or removed.stdout.strip()
        raise InstallError(
            f"uv tool uninstall failed for Script '{item_name}': {detail or 'unknown error'}"
        )
    lock = load_lockfile(lockfile_path)
    remove_entry(lock, item_name, "script")
    save_lockfile(lockfile_path, lock)
    return success(
        data={"name": item_name, "package_name": distribution["package_name"]},
        message=f"uv-tool Script '{item_name}' removed",
    )


def is_uv_tool_entry(entry: dict[str, Any]) -> bool:
    """Return whether a Script entry uses the uv-tool distribution format."""
    distribution = entry.get("distribution")
    return isinstance(distribution, dict) and distribution.get("kind") == "uv-tool"


def _distribution(entry: dict[str, Any], name: str) -> dict[str, Any]:
    distribution = entry.get("distribution")
    if not is_uv_tool_entry(entry):
        raise InstallError(f"Script '{name}' is not a uv-tool distribution.")
    package_name = distribution.get("package_name")
    executables = distribution.get("executables")
    if not isinstance(package_name, str) or not package_name:
        raise InstallError(f"uv-tool Script '{name}' has no package_name.")
    if (
        not isinstance(executables, list)
        or not executables
        or any(not isinstance(value, str) or not value for value in executables)
    ):
        raise InstallError(f"uv-tool Script '{name}' has no valid executables list.")
    return {"package_name": package_name, "executables": executables}


def _uv_bin_dir() -> Path:
    result = _run_uv(["uv", "tool", "dir", "--bin"])
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip()
        raise InstallError(f"Cannot resolve the uv tool executable directory: {detail}")
    return Path(result.stdout.strip()).expanduser().resolve()


def _run_uv(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=UV_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallError(
            f"uv command timed out after {UV_TIMEOUT_SECONDS} seconds: {' '.join(argv[:3])}"
        ) from exc
    except OSError as exc:
        raise InstallError(f"Cannot execute uv: {exc}") from exc


def _fetch_distribution_source(
    parsed: ParsedSource, name: str
) -> tuple[Path, str, Path | None]:
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.is_dir():
            raise InstallError(f"uv-tool Script '{name}' source is not a directory.")
        return local, get_local_commit_sha(local), None

    if parsed.is_remote_repository():
        try:
            temporary = clone_source_repo(parsed.clone_url or "", branch=parsed.branch)
        except Exception as exc:
            raise InstallError(str(exc)) from exc
        source_root = temporary / parsed.file_path if parsed.file_path else temporary
        if not source_root.is_dir():
            shutil.rmtree(temporary, ignore_errors=True)
            raise InstallError(f"uv-tool Script '{name}' source is not a directory.")
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temporary,
            capture_output=True,
            text=True,
            check=False,
        )
        commit = revision.stdout.strip() if revision.returncode == 0 else "unknown"
        return source_root, commit, temporary

    raise InstallError(f"Cannot fetch uv-tool Script '{name}' from {parsed.raw}")
