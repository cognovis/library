"""External-manager inventory adapters used by global Workspace safety checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import yaml

from .errors import LibraryError


def canonical_manager_path(path: Path) -> Path:
    """Canonicalize ownership paths without following a final symlink."""
    absolute = path.expanduser().absolute()
    return absolute.parent.resolve() / absolute.name


class ManagerInventoryAdapter(Protocol):
    """Read-only adapter for paths owned by another configuration manager."""

    name: str

    def managed_paths(self) -> set[Path]:
        """Return absolute managed destination paths."""


class ChezmoiInventoryAdapter:
    """Read the destination inventory exposed by chezmoi."""

    name = "chezmoi"

    def managed_paths(self) -> set[Path]:
        executable = shutil.which("chezmoi")
        if executable is None:
            return set()
        result = subprocess.run(
            [
                executable,
                "managed",
                "--format=json",
                "--path-style=absolute",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if result.returncode != 0:
            raise LibraryError(
                f"chezmoi inventory failed: {result.stderr.strip() or 'unknown error'}"
            )
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise LibraryError("chezmoi inventory returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise LibraryError("chezmoi inventory must be a JSON list")
        return {canonical_manager_path(Path(str(item))) for item in payload}


class ProjectToolingInventoryAdapter:
    """Project targets still writable by the transitional project_tooling engine."""

    name = "project-tooling"

    def __init__(
        self, catalog: dict, project_root: Path, *, profile: str = "consumer"
    ) -> None:
        self.catalog = catalog
        self.project_root = project_root.resolve()
        self.profile = profile

    def managed_paths(self) -> set[Path]:
        paths: set[Path] = set()
        for entry in self.catalog.get("project_tooling") or []:
            profiles = entry.get("profiles") or []
            if profiles and self.profile not in profiles:
                continue
            if entry.get("target_kind") == "git_hook":
                result = subprocess.run(
                    ["git", "rev-parse", "--git-path", "hooks"],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                hook_name = entry.get("hook_name")
                if result.returncode != 0 or not hook_name:
                    continue
                hooks = Path(result.stdout.strip())
                if not hooks.is_absolute():
                    hooks = self.project_root / hooks
                paths.add(canonical_manager_path(hooks / str(hook_name)))
                continue
            target = entry.get("target_path")
            if target:
                paths.add(canonical_manager_path(self.project_root / str(target)))
        return paths


class ConsumerUpdaterInventoryAdapter:
    """Managed-file targets declared for one consumer project."""

    name = "consumer-updater"

    def __init__(self, manifest_path: Path, project_root: Path) -> None:
        self.manifest_path = manifest_path
        self.project_root = project_root.resolve()

    def managed_paths(self) -> set[Path]:
        if not self.manifest_path.exists():
            return set()
        try:
            payload = yaml.safe_load(self.manifest_path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise LibraryError(
                f"consumer updater inventory failed: {self.manifest_path}"
            ) from exc
        paths: set[Path] = set()
        for consumer in payload.get("consumers") or []:
            raw_root = str(consumer.get("root") or "")
            expanded_root = Path(
                os.path.expandvars(os.path.expanduser(raw_root))
            ).resolve()
            if expanded_root != self.project_root:
                continue
            for item in consumer.get("managed_files") or []:
                target = item.get("target")
                if target:
                    paths.add(canonical_manager_path(self.project_root / str(target)))
        return paths


def workspace_manager_adapters(
    *, catalog: dict, project_root: Path, platform_root: Path, scope: str
) -> list[ManagerInventoryAdapter]:
    """Return every manager adapter relevant to the selected Workspace scope."""
    if scope == "global":
        return [ChezmoiInventoryAdapter()]
    return [
        ProjectToolingInventoryAdapter(catalog, project_root),
        ConsumerUpdaterInventoryAdapter(
            platform_root / "consumer-projects.yml", project_root
        ),
    ]


def collect_managed_paths(
    adapters: list[ManagerInventoryAdapter] | None = None,
) -> dict[str, str]:
    """Return absolute path to manager-name ownership claims."""
    selected = adapters if adapters is not None else [ChezmoiInventoryAdapter()]
    managed: dict[str, str] = {}
    for adapter in selected:
        for path in adapter.managed_paths():
            managed[str(canonical_manager_path(path))] = adapter.name
    return managed
