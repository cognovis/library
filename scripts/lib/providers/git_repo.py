"""The reference `git-repo` provider adapter: remote-only, no local checkout.

This adapter is the proof that ADR-0011's `enumerate` floor is reachable
without cloning. It lists a repository's tree at a ref through the host's Git
data API, classifies items from marker files at any depth, and fetches content
bytes from the raw content host. It never runs `git`, never creates a temporary
directory, and never writes to the filesystem — the module deliberately imports
neither `subprocess` nor `tempfile`, so a regression is an import away from
being visible in review.

Provider knowledge lives here and only here. The resolver, cache, and Workspace
layers consume the normalized inventory, and `scripts/checks/provider_neutrality.py`
fails CI if provider knowledge leaks into them.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from .classification import ITEM_MARKERS, library_type_for
from .contract import (
    AuthRequirement,
    Availability,
    ItemDescription,
    OPTIONAL_CAPABILITIES,
    ProviderItem,
    REQUIRED_CAPABILITIES,
    RightsEvidence,
    SourceProvider,
)

DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_RAW_BASE = "https://raw.githubusercontent.com"
DEFAULT_TIMEOUT = 30
_HEX40 = 40

#: Basenames that carry a repository's licensing evidence, in preference order.
LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")

#: Upstream id for an item whose marker file sits at the repository root. The
#: upstream id is a repository-relative directory, and the root directory has no
#: name; `.` is that directory's name and keeps the id non-empty and unique.
ROOT_ITEM_ID = "."


class ProviderTransportError(RuntimeError):
    """The provider could not be reached or answered with an error."""


class ProviderInventoryIncomplete(RuntimeError):
    """The provider returned a truncated listing.

    ADR-0011 Invariant 8: a reduced or truncated inventory is never presented as
    a complete one. A partial tree would silently drop items and, downstream,
    make an installed item look upstream-vanished.
    """


class HttpTransport(Protocol):
    """The transport seam. Injecting it is what makes this adapter testable."""

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any: ...

    def get_bytes(self, url: str, headers: Mapping[str, str] | None = None) -> bytes: ...


class UrllibTransport:
    """A minimal read-only HTTP transport. Sends no credentials of its own."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def _open(self, url: str, headers: Mapping[str, str] | None) -> bytes:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderTransportError(f"{exc.code} for {url}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderTransportError(f"transport failure for {url}: {exc}") from exc

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        payload = self._open(url, {"Accept": "application/vnd.github+json", **(headers or {})})
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderTransportError(f"non-JSON response from {url}") from exc

    def get_bytes(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        return self._open(url, headers)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_repository(repository_url: str) -> tuple[str, str]:
    parsed = urlparse(repository_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError(
            "a git-repo provider needs an owner/repository URL, got "
            f"{repository_url!r}"
        )
    return parts[0], parts[1].removesuffix(".git")


@dataclass
class GitRepoProvider(SourceProvider):
    """One remote Git repository, enumerated at a ref without a checkout."""

    repository_url: str
    ref: str = "main"
    transport: HttpTransport = field(default_factory=UrllibTransport)
    api_base: str = DEFAULT_API_BASE
    raw_base: str = DEFAULT_RAW_BASE
    auth_ref: str | None = None
    auth_scope: str = "contents:read"
    #: Extra request headers, for example an operator-resolved authorization
    #: header. Credentials are the caller's to resolve; this adapter records the
    #: named reference and never reads a credential store itself.
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._owner, self._repository = _split_repository(self.repository_url)
        self._identity = f"https://{urlparse(self.repository_url).netloc}/{self._owner}/{self._repository}"
        self._commit: str | None = None
        self._entries: dict[str, dict[str, Any]] | None = None
        self._items: tuple[ProviderItem, ...] | None = None

    # -- Required capabilities ------------------------------------------------

    def identity(self) -> str:
        return self._identity

    def capabilities(self) -> frozenset[str]:
        """This adapter offers the full contract, including every optional part."""
        return REQUIRED_CAPABILITIES | OPTIONAL_CAPABILITIES

    def enumerate(self, selector: Any = None) -> Sequence[ProviderItem]:
        """List every marker-identified item in the tree, at any depth.

        Args:
            selector: Optional path prefix. Only items beneath it are returned.
        """
        items = self._enumerate_all()
        if not selector:
            return items
        prefix = str(selector).strip("/")
        return tuple(
            item
            for item in items
            if item.upstream_id == prefix or item.upstream_id.startswith(f"{prefix}/")
        )

    def fetch(self, upstream_id: str, revision: str | None = None) -> bytes:
        """Content bytes of the item's marker file at a pinned revision.

        Raises:
            KeyError: when the provider does not list that item.
        """
        entry = self._entry(upstream_id)
        commit = revision or self._resolve_commit()
        url = f"{self.raw_base}/{self._owner}/{self._repository}/{commit}/{entry['path']}"
        return self.transport.get_bytes(url, self._headers())

    def auth_requirements(self) -> Sequence[AuthRequirement]:
        """The named credential reference, when this source declares one."""
        if not self.auth_ref:
            return ()
        return (AuthRequirement(reference=self.auth_ref, scope=self.auth_scope),)

    def availability(self) -> Availability:
        """Resolve the ref; reachability of the ref is the availability answer."""
        try:
            self._resolve_commit()
        except ProviderTransportError as exc:
            return Availability(
                state="unavailable", observed_at=_now(), reason=str(exc)
            )
        return Availability(state="available", observed_at=_now())

    # -- Optional capabilities ------------------------------------------------

    def describe(self, upstream_id: str) -> ItemDescription:
        """Classify from tree metadata alone. No content bytes are fetched."""
        entry = self._entry(upstream_id)
        library_type, basis = library_type_for(entry["path"])
        return ItemDescription(
            upstream_id=upstream_id,
            library_type=library_type,
            classification={"type_basis": basis, "upstream_path": entry["path"]},
            runtime_compatibility=("unknown",),
            content_identity=entry.get("sha"),
        )

    def revision_of(self, upstream_id: str) -> str:
        """The commit the enumeration was pinned to.

        Repository-level, not per item: a Git commit is the immutable identity
        at which this item was observed, and a per-path last-commit lookup would
        cost one request per item without changing what is pinned.
        """
        self._entry(upstream_id)
        return self._resolve_commit()

    def verify(self, content: bytes, expected: str) -> bool:
        """Provider-native integrity proof: the Git blob object hash."""
        header = f"blob {len(content)}\0".encode("utf-8")
        return hashlib.sha1(header + content).hexdigest() == expected

    def rights_evidence(self) -> RightsEvidence:
        """Point at the repository's licence file when the tree carries one."""
        entries = self._tree_entries()
        for filename in LICENSE_FILENAMES:
            if filename in entries:
                commit = self._resolve_commit()
                return RightsEvidence(
                    located=True,
                    source=f"{self._identity}/blob/{commit}/{filename}",
                    detail="upstream licence file observed in the pinned tree",
                )
        return RightsEvidence(
            located=False,
            detail="no licence file in the pinned tree; rights remain unrecorded",
        )

    # -- Internals ------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return dict(self.headers)

    def _resolve_commit(self) -> str:
        if self._commit is not None:
            return self._commit
        ref = self.ref.strip()
        if len(ref) == _HEX40 and all(char in "0123456789abcdef" for char in ref.lower()):
            self._commit = ref.lower()
            return self._commit
        url = f"{self.api_base}/repos/{self._owner}/{self._repository}/git/ref/heads/{ref}"
        payload = self.transport.get_json(url, self._headers())
        try:
            commit = payload["object"]["sha"]
        except (TypeError, KeyError) as exc:
            raise ProviderTransportError(f"no commit for ref {ref!r} at {url}") from exc
        self._commit = str(commit)
        return self._commit

    def _tree_entries(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        commit = self._resolve_commit()
        url = (
            f"{self.api_base}/repos/{self._owner}/{self._repository}"
            f"/git/trees/{commit}?recursive=1"
        )
        payload = self.transport.get_json(url, self._headers())
        if not isinstance(payload, dict) or "tree" not in payload:
            raise ProviderTransportError(f"unexpected tree response from {url}")
        if payload.get("truncated"):
            raise ProviderInventoryIncomplete(
                f"the provider truncated the listing for {self._identity} at {commit}; "
                "a partial inventory is never presented as a complete one"
            )
        self._entries = {
            str(entry["path"]): entry
            for entry in payload["tree"]
            if entry.get("type") == "blob"
        }
        return self._entries

    def _enumerate_all(self) -> tuple[ProviderItem, ...]:
        if self._items is not None:
            return self._items
        items: list[ProviderItem] = []
        for path in sorted(self._tree_entries()):
            basename = path.rsplit("/", 1)[-1].lower()
            if basename not in ITEM_MARKERS:
                continue
            if "/" not in path:
                # A marker at the repository root means the repository *is* the
                # item. Skipping it would drop an item silently, which is the
                # failure mode the truncation guard above also exists to prevent.
                items.append(
                    ProviderItem(
                        upstream_id=ROOT_ITEM_ID,
                        upstream_name=self._repository,
                        collection_membership=(),
                        content_hint=path,
                    )
                )
                continue
            directory = path.rsplit("/", 1)[0]
            segments = directory.split("/")
            items.append(
                ProviderItem(
                    upstream_id=directory,
                    upstream_name=segments[-1],
                    collection_membership=tuple(segments[:-1]),
                    content_hint=path,
                )
            )
        self._items = tuple(items)
        return self._items

    def _entry(self, upstream_id: str) -> dict[str, Any]:
        for item in self._enumerate_all():
            if item.upstream_id == upstream_id:
                return self._tree_entries()[str(item.content_hint)]
        raise KeyError(f"{self._identity} has no item {upstream_id!r}")
