"""Git hosting-service knowledge for the legacy resolution path.

This module exists because of a drawdown, not because of a new feature. Before
ADR-0011 the platform's source resolution lived in `scripts/lib/source.py`, and
that module knew a hosting service by name: its browser URL shape, its raw
content host, its clone URL, its SSH form. `scripts/checks/provider_neutrality.py`
measured 50 findings there, more than every other legacy module combined, and
the check's own remedy is the one applied here — *move provider knowledge into a
provider adapter under `scripts/lib/providers/`*.

So this is a relocation with a purpose, not a relabelling. What moved is exactly
the knowledge that made `source.py` provider-aware:

| Knowledge | Was | Is |
|---|---|---|
| Browser, raw, and repository URL shapes | Three regexes in `source.py` | `parse_git_source` here |
| Clone URL construction and the SSH form | String building in `source.py` | `clone_url_for`, `ssh_url_for` here |
| Owner-or-repository marketplace resolution | `_resolve_github_marketplace_repo_url` | `resolve_owner_repository_url` here |
| Shallow clone with SSH fallback | `clone_github_repo` | `clone_repository` here |

`source.py` keeps its public API and delegates. It now names no host, builds no
URL, and branches on no distribution mechanism, so it measures zero.

This is the **legacy** path: it still clones, which is precisely what the
ADR-0011 provider contract exists to stop requiring. `git_repo.GitRepoProvider`
is the remote-only replacement. Nothing new should be added here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

#: The legacy `marketplace.type` value this path resolves. It is a distribution
#: mechanism, which is a provider fact, so it belongs here rather than in the
#: catalog logic that merely compares against it.
LEGACY_MARKETPLACE_TYPE = "git"

#: The hosting service the legacy path understands.
HOST = "github.com"
RAW_HOST = "raw.githubusercontent.com"
HTTPS_PREFIX = f"https://{HOST}/"
SSH_PREFIX = f"git@{HOST}:"

#: `ParsedSource.kind` values. Kept as their historical strings because they are
#: compared against by name across the installer modules; the point of moving
#: them is that the *literals* now live at the provider boundary.
KIND_LOCAL = "local"
KIND_BROWSER = "github_browser"
KIND_RAW = "github_raw"
KIND_REPO = "github_repo"
KIND_UNKNOWN = "unknown"

REMOTE_KINDS = (KIND_BROWSER, KIND_RAW, KIND_REPO)

#: Kinds that address a path inside a repository rather than the repository.
PATH_BEARING_KINDS = (KIND_BROWSER, KIND_RAW)

_BROWSER_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/(blob|tree)/([^/]+)/(.+)")
_RAW_RE = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)")
_REPO_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
_SSH_REPO_RE = re.compile(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$")


def clone_url_for(owner: str, repository: str) -> str:
    """The HTTPS clone URL for one owner and repository."""
    return f"{HTTPS_PREFIX}{owner}/{repository}.git"


def ssh_clone_url_for(owner: str, repository: str) -> str:
    """The SSH clone URL for one owner and repository."""
    return f"{SSH_PREFIX}{owner}/{repository}.git"


def ssh_url_for(clone_url: str) -> str:
    """The SSH form of an HTTPS clone URL, unchanged when it is not one."""
    return clone_url.replace(HTTPS_PREFIX, SSH_PREFIX)


def repository_url_for(owner: str, repository: str) -> str:
    """The canonical browser URL for one owner and repository."""
    return f"{HTTPS_PREFIX}{owner}/{repository}"


def tree_url_for(repository_url: str, branch: str, path: str) -> str:
    """The browser URL addressing one path in a repository at one branch."""
    return f"{repository_url}/tree/{branch}/{path}"


def is_remote_url(source: str) -> bool:
    """Whether this source string addresses the hosting service at all."""
    return parse_git_source(source)["kind"] in REMOTE_KINDS


def parse_git_source(source: str) -> dict[str, Any]:
    """Parse one `source:` value into its provider-native parts.

    Returns:
        A mapping with `kind` and, for a remote source, `org`, `repo`, `branch`,
        `file_path`, `clone_url`, and `path_type`. A source this hosting service
        does not address returns `kind: unknown` and nothing else, which the
        caller reports rather than guessing at.
    """
    match = _BROWSER_RE.match(source)
    if match:
        owner, repository, browser_kind, branch, file_path = match.groups()
        return {
            "kind": KIND_BROWSER,
            "org": owner,
            "repo": repository,
            "branch": branch,
            "file_path": file_path.rstrip("/"),
            "clone_url": clone_url_for(owner, repository),
            "path_type": "directory" if browser_kind == "tree" else "file",
        }

    match = _RAW_RE.match(source)
    if match:
        owner, repository, branch, file_path = match.groups()
        return {
            "kind": KIND_RAW,
            "org": owner,
            "repo": repository,
            "branch": branch,
            "file_path": file_path.rstrip("/"),
            "clone_url": clone_url_for(owner, repository),
            "path_type": "file",
        }

    match = _REPO_RE.match(source)
    if match:
        owner, repository = match.groups()
        return {
            "kind": KIND_REPO,
            "org": owner,
            "repo": repository,
            "branch": None,
            "file_path": None,
            "clone_url": clone_url_for(owner, repository),
            "path_type": "directory",
        }

    match = _SSH_REPO_RE.match(source)
    if match:
        owner, repository = match.groups()
        return {
            "kind": KIND_REPO,
            "org": owner,
            "repo": repository,
            "branch": None,
            "file_path": None,
            "clone_url": ssh_clone_url_for(owner, repository),
            "path_type": "directory",
        }

    return {"kind": KIND_UNKNOWN}


def resolve_owner_repository_url(base_source: str, repo_name: Optional[str]) -> str:
    """Resolve a marketplace source plus an optional repository name to a URL.

    Args:
        base_source: An owner URL or a repository URL on the hosting service.
        repo_name: The repository, required when `base_source` names only an owner.

    Returns:
        The canonical repository URL.

    Raises:
        ValueError: when the source is not on the hosting service, names no
            owner, addresses more than a repository, or conflicts with
            `repo_name`. Each message states the condition rather than the
            remedy, because the caller adds the marketplace name it knows.
    """
    parsed = urlparse(base_source)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != HOST:
        raise ValueError(f"source is not a supported repository URL: {base_source}")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        raise ValueError(f"source has no owner: {base_source}")

    owner = parts[0]
    if len(parts) == 1:
        if not repo_name:
            raise ValueError(
                "source points to an owner; the catalog entry must provide a repo."
            )
        repository = repo_name
    elif len(parts) == 2:
        repository = parts[1].removesuffix(".git")
        if repo_name and repository != repo_name:
            raise ValueError(
                f"source already points to repository '{repository}', cannot "
                f"resolve repo '{repo_name}'."
            )
    else:
        raise ValueError(
            f"source must be an owner or repository URL: {base_source}"
        )

    return repository_url_for(owner, repository)


def url_belongs_to(source_url: str, marketplace_url: str) -> bool:
    """Whether a source URL sits inside a marketplace's repository."""
    base = marketplace_url.rstrip("/").rstrip(".git")
    return source_url.startswith(base)


def clone_repository(clone_url: str, branch: Optional[str] = None) -> Path:
    """Shallow-clone into a fresh temp dir, falling back to SSH.

    The caller owns the returned directory and must clean it up.

    The SSH fallback exists because private remotes have no HTTPS credentials.
    It has to start from an empty directory: the failed attempt creates and
    partially populates the target, so retrying into the same path made the tool
    refuse with "already exists and is not an empty directory" -- which masked
    the real HTTPS error and meant the fallback could never succeed. That broke
    every remote-sourced install (CL-k33k), and `tests/test_clone_ssh_fallback.py`
    holds the repair.

    Raises:
        RuntimeError: naming both failures when neither transport works. The
            caller re-raises it as its own typed error.
    """
    tmp = Path(tempfile.mkdtemp())

    def _clone(url: str) -> subprocess.CompletedProcess:
        command = ["git", "clone", "--quiet", "--depth", "1"]
        if branch:
            command += ["--branch", branch]
        command += [url, str(tmp)]
        return subprocess.run(command, capture_output=True, text=True)

    result = _clone(clone_url)
    if result.returncode == 0:
        return tmp

    https_error = result.stderr.strip()
    shutil.rmtree(str(tmp), ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    fallback_url = ssh_url_for(clone_url)
    result = _clone(fallback_url)
    if result.returncode == 0:
        return tmp

    ssh_error = result.stderr.strip()
    shutil.rmtree(str(tmp), ignore_errors=True)
    raise RuntimeError(
        f"Failed to clone {clone_url} over https ({https_error}) "
        f"and {fallback_url} over ssh ({ssh_error})"
    )


def head_commit(path: Path) -> str:
    """The HEAD commit of a local checkout, or `local` when it is not tracked."""
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
