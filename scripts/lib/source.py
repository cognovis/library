"""
source.py — Local/GitHub source parsing, temp clone, tree-SHA/source provenance.

Handles parsing catalog `source` and `sources` fields, fetching content from
GitHub repos, and computing source commit SHAs.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .errors import SourceError


@dataclass
class ParsedSource:
    """Parsed representation of a library entry source field."""

    kind: str
    """'local', 'github_browser', 'github_raw', or 'unknown'."""

    raw: str
    """Original source string."""

    # GitHub-specific fields
    org: Optional[str] = None
    repo: Optional[str] = None
    branch: Optional[str] = None
    file_path: Optional[str] = None  # path within repo
    clone_url: Optional[str] = None

    # Local-specific fields
    local_path: Optional[Path] = None

    def is_github(self) -> bool:
        return self.kind in ("github_browser", "github_raw")

    def is_local(self) -> bool:
        return self.kind == "local"

    def parent_dir_in_repo(self) -> Optional[str]:
        """Return the directory containing the file within the repo."""
        if self.file_path:
            p = self.file_path.rsplit("/", 1)
            return p[0] if len(p) > 1 else ""
        return None


def parse_source(source: str) -> ParsedSource:
    """Parse a `source:` field value into a ParsedSource.

    Supports:
    - /absolute/local/path
    - ~/home/relative/path
    - https://github.com/org/repo/blob/branch/path/to/file
    - https://raw.githubusercontent.com/org/repo/branch/path/to/file
    """
    if not source:
        raise SourceError("Source field is empty.")

    # Local path
    if source.startswith("/") or source.startswith("~"):
        local = Path(source).expanduser()
        return ParsedSource(kind="local", raw=source, local_path=local)

    # GitHub browser URL
    m = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)",
        source,
    )
    if m:
        org, repo, branch, file_path = m.groups()
        return ParsedSource(
            kind="github_browser",
            raw=source,
            org=org,
            repo=repo,
            branch=branch,
            file_path=file_path,
            clone_url=f"https://github.com/{org}/{repo}.git",
        )

    # GitHub raw URL
    m = re.match(
        r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)",
        source,
    )
    if m:
        org, repo, branch, file_path = m.groups()
        return ParsedSource(
            kind="github_raw",
            raw=source,
            org=org,
            repo=repo,
            branch=branch,
            file_path=file_path,
            clone_url=f"https://github.com/{org}/{repo}.git",
        )

    # Unrecognized
    return ParsedSource(kind="unknown", raw=source)


def resolve_marketplace(
    catalog_data: dict,
    entry: dict,
) -> Optional[str]:
    """Resolve marketplace name for a catalog entry.

    Checks entry's `from_marketplace` field and matches against
    the `marketplaces` section of library.yaml.

    Returns:
        Marketplace name string (e.g. 'cognovis-core'), or 'local' for local paths,
        or 'unknown' if not resolvable.
    """
    marketplaces = catalog_data.get("marketplaces", []) or []
    marketplace_names = {
        m.get("id") or m.get("name"): m for m in marketplaces if isinstance(m, dict)
    }

    # Check from_marketplace field
    if entry.get("from_marketplace"):
        mp_name = entry["from_marketplace"]
        if mp_name in marketplace_names or mp_name:
            return mp_name

    # Check source field for known GitHub orgs
    source = entry.get("source") or ""
    if source.startswith("/") or source.startswith("~"):
        return "local"

    # Try to match source URL against registered marketplace clone URLs
    for mp in marketplaces:
        if not isinstance(mp, dict):
            continue
        clone_url = mp.get("clone_url") or mp.get("repo") or ""
        if clone_url and _url_matches_marketplace(source, clone_url):
            return mp.get("id") or mp.get("name") or "unknown"

    # Fallback
    return "unknown"


def _url_matches_marketplace(source_url: str, marketplace_url: str) -> bool:
    """Check if a source URL belongs to a marketplace's repo."""
    # Strip .git suffix for comparison
    mp = marketplace_url.rstrip("/").rstrip(".git")
    return source_url.startswith(mp)


def get_local_commit_sha(path: Path) -> str:
    """Return the git HEAD commit SHA for a local path, or 'local' if not git-tracked."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(path.parent if path.is_file() else path),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "local"
