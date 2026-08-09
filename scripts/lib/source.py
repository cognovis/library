"""
source.py — Catalog `source` parsing and marketplace resolution.

This module answers "what does this catalog entry's `source` field address, and
which marketplace does it belong to". It is the **legacy** resolution path: it
predates the ADR-0011 provider capability contract and still resolves content by
cloning, which is what `providers.git_repo` exists to stop requiring.

It carries no hosting-service knowledge any more. Every URL shape, host name,
clone form, and SSH fallback moved to `providers/git_url.py` under the ADR-0011
drawdown (slice 6, `CL-mvet`), which is the remedy
`scripts/checks/provider_neutrality.py` names for exactly this: provider
knowledge belongs in a provider adapter. What is left here is catalog logic —
which marketplace an entry names, and which path inside it — and that is
genuinely this module's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .catalog import get_marketplaces
from .errors import SourceError
from .providers.git_url import (
    KIND_LOCAL,
    KIND_UNKNOWN,
    LEGACY_MARKETPLACE_TYPE,
    PATH_BEARING_KINDS,
    REMOTE_KINDS,
    clone_repository,
    head_commit,
    parse_git_source,
    resolve_owner_repository_url,
    tree_url_for,
    url_belongs_to,
)


@dataclass
class ParsedSource:
    """Parsed representation of a library entry source field."""

    kind: str
    """One of the `providers.git_url` kind values, `local`, or `unknown`."""

    raw: str
    """Original source string."""

    # Remote-repository fields
    org: Optional[str] = None
    repo: Optional[str] = None
    branch: Optional[str] = None
    file_path: Optional[str] = None  # path within repo
    clone_url: Optional[str] = None
    path_type: str = "unknown"
    """Source path hint: 'file', 'directory', or 'unknown'."""

    # Local-specific fields
    local_path: Optional[Path] = None

    def is_remote_repository(self) -> bool:
        """Whether this source addresses a remote repository."""
        return self.kind in REMOTE_KINDS

    def addresses_path_in_repository(self) -> bool:
        """Whether this source addresses a path inside a repository."""
        return self.kind in PATH_BEARING_KINDS

    def is_local(self) -> bool:
        return self.kind == KIND_LOCAL

    def parent_dir_in_repo(self) -> Optional[str]:
        """Return the directory containing the file within the repo."""
        if self.file_path:
            p = self.file_path.rsplit("/", 1)
            return p[0] if len(p) > 1 else ""
        return None


def parse_source(source: str) -> ParsedSource:
    """Parse a `source:` field value into a ParsedSource.

    Supports an absolute or home-relative local path, and the remote repository
    URL shapes `providers.git_url` understands. An unrecognized value returns
    `kind: unknown` rather than a guess.
    """
    if not source:
        raise SourceError("Source field is empty.")

    if source.startswith("/") or source.startswith("~"):
        local = Path(source).expanduser()
        if local.is_dir():
            path_type = "directory"
        elif local.is_file():
            path_type = "file"
        else:
            path_type = "unknown"
        return ParsedSource(
            kind=KIND_LOCAL,
            raw=source,
            local_path=local,
            path_type=path_type,
        )

    parsed = parse_git_source(source)
    if parsed["kind"] == KIND_UNKNOWN:
        return ParsedSource(kind=KIND_UNKNOWN, raw=source)
    return ParsedSource(
        kind=parsed["kind"],
        raw=source,
        org=parsed["org"],
        repo=parsed["repo"],
        branch=parsed["branch"],
        file_path=parsed["file_path"],
        clone_url=parsed["clone_url"],
        path_type=parsed["path_type"],
    )


def resolve_marketplace(
    catalog_data: dict,
    entry: dict,
) -> Optional[str]:
    """Resolve marketplace name for a catalog entry.

    Checks entry's `from_marketplace` field and matches against
    `sources.marketplaces` in library.yaml, with legacy root fallback.

    Returns:
        Marketplace name string, `local` for local paths, or `unknown` if not
        resolvable.
    """
    marketplaces = get_marketplaces(catalog_data)
    marketplace_names = {
        m.get("id") or m.get("name"): m for m in marketplaces if isinstance(m, dict)
    }

    # Check from_marketplace field
    if entry.get("from_marketplace"):
        mp_name = entry["from_marketplace"]
        if mp_name in marketplace_names or mp_name:
            return mp_name

    source = entry.get("source") or ""
    if source.startswith("/") or source.startswith("~"):
        return KIND_LOCAL

    # Try to match the source URL against registered marketplace clone URLs
    for mp in marketplaces:
        if not isinstance(mp, dict):
            continue
        clone_url = mp.get("clone_url") or mp.get("repo") or ""
        if clone_url and url_belongs_to(source, clone_url):
            return mp.get("id") or mp.get("name") or "unknown"

    return "unknown"


def resolve_marketplace_source(
    catalog_data: dict,
    entry: dict,
    *,
    default_branch: str = "main",
) -> Optional[str]:
    """Resolve a from_marketplace catalog entry to a repository tree URL."""
    marketplace_name = entry.get("from_marketplace")
    source_path = entry.get("path")
    if not marketplace_name or not source_path:
        return None

    marketplace = _find_marketplace(catalog_data, marketplace_name)
    if marketplace is None:
        raise SourceError(
            f"Catalog entry '{entry.get('name')}' references unknown marketplace "
            f"'{marketplace_name}'."
        )

    marketplace_type = marketplace.get("type", LEGACY_MARKETPLACE_TYPE)
    if marketplace_type != LEGACY_MARKETPLACE_TYPE:
        raise SourceError(
            f"Marketplace '{marketplace_name}' uses unsupported type "
            f"'{marketplace_type}' for direct installs."
        )

    base_source = (
        marketplace.get("source")
        or marketplace.get("clone_url")
        or marketplace.get("repo")
        or ""
    )
    if not base_source:
        raise SourceError(f"Marketplace '{marketplace_name}' has no source URL.")

    try:
        repo_url = resolve_owner_repository_url(base_source, entry.get("repo"))
    except ValueError as exc:
        raise SourceError(f"Marketplace '{marketplace_name}' {exc}") from exc

    branch = (
        entry.get("branch")
        or entry.get("ref")
        or marketplace.get("branch")
        or marketplace.get("default_branch")
        or default_branch
    )
    normalized_path = str(source_path).strip("/")
    if not normalized_path:
        raise SourceError(
            f"Catalog entry '{entry.get('name')}' has an empty marketplace path."
        )

    return tree_url_for(repo_url, branch, normalized_path)


def _find_marketplace(catalog_data: dict, marketplace_name: str) -> Optional[dict]:
    """Find a marketplace by id or name."""
    for marketplace in get_marketplaces(catalog_data):
        if not isinstance(marketplace, dict):
            continue
        if marketplace_name in (marketplace.get("id"), marketplace.get("name")):
            return marketplace
    return None


def clone_source_repo(clone_url: str, branch: Optional[str] = None) -> Path:
    """Shallow-clone `clone_url` into a fresh temp dir, falling back to SSH.

    Returns the temp directory. The caller owns it and must clean it up.

    Raises:
        SourceError: naming both transport failures when neither works.
    """
    try:
        return clone_repository(clone_url, branch)
    except RuntimeError as exc:
        raise SourceError(str(exc)) from exc


def get_local_commit_sha(path: Path) -> str:
    """Return the git HEAD commit SHA for a local path, or 'local'."""
    return head_commit(path)
