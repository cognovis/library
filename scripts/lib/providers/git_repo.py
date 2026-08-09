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

from .decompose import (
    AmbiguousItemLayout,
    ItemLayout,
    LAYOUTS,
    MARKER_LAYOUT,
    ROOT_ITEM_ID,
    decompose_tree,
)

from .contract import (
    AuthRequirement,
    Availability,
    FetchedFile,
    FetchedItem,
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

#: Re-exported so existing importers keep working after the decomposition rules
#: moved to `decompose`. They are that module's definitions, not this one's.
__all__ = [
    "AmbiguousItemLayout",
    "GitRepoProvider",
    "HttpTransport",
    "LICENSE_FILENAMES",
    "ProviderInventoryIncomplete",
    "ProviderTransportError",
    "ROOT_ITEM_ID",
    "UrllibTransport",
]

#: Basenames that carry a repository's licensing evidence, in preference order.
LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")


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
    #: `marker` (one item per marker directory) or `bundle` (also one item per
    #: remaining file). Registration chooses it; nothing here infers it, because
    #: a repository that happens to contain no marker file is not thereby a
    #: bundle -- it may simply be a repository with nothing to install.
    layout: str = MARKER_LAYOUT

    def __post_init__(self) -> None:
        self._owner, self._repository = _split_repository(self.repository_url)
        self._identity = f"https://{urlparse(self.repository_url).netloc}/{self._owner}/{self._repository}"
        if self.layout not in LAYOUTS:
            raise ValueError(
                f"unknown layout {self.layout!r} for {self._identity}; "
                f"expected {list(LAYOUTS)}"
            )
        self._commit: str | None = None
        self._trees: dict[str, dict[str, dict[str, Any]]] = {}
        self._layouts: dict[str, dict[str, ItemLayout]] = {}
        self._items: tuple[ProviderItem, ...] | None = None

    # -- Required capabilities ------------------------------------------------

    def identity(self) -> str:
        return self._identity

    def capabilities(self) -> frozenset[str]:
        """Every capability except per-item rights, which this provider cannot have.

        One repository publishes one licence for everything it contains, so
        `rights_evidence` is the complete answer and a per-item variant would be
        the same answer repeated. Declaring `item_rights_evidence` here would
        tell a consumer to ask a question this provider has no second answer to.
        """
        return REQUIRED_CAPABILITIES | (
            OPTIONAL_CAPABILITIES - {"item_rights_evidence"}
        )

    def current_revision(self) -> str:
        """The commit this adapter's ref currently resolves to.

        Repository-level and item-free, which is what a pin verification asks:
        "has this source moved", not "where is this item".
        """
        return self._resolve_commit()

    def member_manifest(
        self, upstream_id: str, revision: str | None = None
    ) -> Sequence[str]:
        """The item-relative paths this item consists of, read from the tree.

        Read from the tree of the revision being asked about, not from a fetch:
        the point of the manifest is to be an independent list the retrieval is
        checked against, and a manifest derived from the retrieval would agree
        with it by construction.
        """
        commit = revision or self._resolve_commit()
        layout = self._layout(commit).get(upstream_id)
        if layout is None:
            raise KeyError(
                f"{self._identity} has no item {upstream_id!r} at revision {commit}"
            )
        return tuple(sorted(layout.relative(path) for path in layout.member_paths))

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

    def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
        """Every file the item consists of, at a pinned revision.

        An item is a directory here, and the reference provider's skills carry
        more than their marker file (`implement` ships `agents/openai.yaml`).
        Fetching only the marker would hand a downstream cache an incomplete
        item while reporting success.

        Raises:
            KeyError: when the provider does not list that item.
        """
        self._entry(upstream_id)  # refuse an item this provider does not list
        commit = revision or self._resolve_commit()

        # Paths and blob identities come from the tree of the revision actually
        # being fetched, never from the adapter's ref. The decomposition is
        # recomputed there too: an item's member set is a property of a tree, and
        # reusing the ref's member list would report one revision's files under
        # another revision's identity.
        entries = self._tree_entries(commit)
        layout = self._layout(commit).get(upstream_id)
        if layout is None:
            raise ProviderInventoryIncomplete(
                f"{self._identity} has no item {upstream_id!r} at revision {commit}"
            )

        files = []
        for path in layout.member_paths:
            url = f"{self.raw_base}/{self._owner}/{self._repository}/{commit}/{path}"
            files.append(
                FetchedFile(
                    path=layout.relative(path),
                    content=self.transport.get_bytes(url, self._headers()),
                    upstream_content_identity=entries[path].get("sha"),
                )
            )
        return FetchedItem(
            upstream_id=upstream_id,
            revision=commit,
            files=tuple(files),
            primary_path=layout.relative(layout.primary_path),
        )

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
        """Classify the Library type from tree metadata alone.

        No content bytes are fetched, which is the point of the capability and
        also its limit: `classification.skill_class` is an upstream frontmatter
        property, so it is not answered here and no substitute value is
        invented. A caller that needs it asks `normalize_inventory` for content
        inspection and pays the recorded cost.
        """
        entry = self._entry(upstream_id)
        layout = self._layout()[upstream_id]
        return ItemDescription(
            upstream_id=upstream_id,
            library_type=layout.library_type,
            classification={
                "type_basis": layout.type_basis,
                "upstream_path": entry["path"],
            },
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

    def _tree_entries(self, commit: str | None = None) -> dict[str, dict[str, Any]]:
        """The blob entries of one commit's tree.

        Keyed by commit, not cached for the adapter as a whole. A tree cached
        against the adapter's ref would answer questions about a *different*
        revision when a caller pins one explicitly, so a pinned fetch could
        return the ref's file list and the ref's blob identities while
        reporting the pinned revision. That is fabricated provenance, and it is
        why the cache key here is the commit.
        """
        commit = commit or self._resolve_commit()
        cached = self._trees.get(commit)
        if cached is not None:
            return cached
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
        entries = {
            str(entry["path"]): entry
            for entry in payload["tree"]
            if entry.get("type") == "blob"
        }
        self._trees[commit] = entries
        return entries

    def _layout(self, commit: str | None = None) -> dict[str, ItemLayout]:
        """The decomposed items of one commit's tree, keyed by upstream id."""
        commit = commit or self._resolve_commit()
        cached = self._layouts.get(commit)
        if cached is not None:
            return cached
        try:
            items = decompose_tree(
                sorted(self._tree_entries(commit)),
                layout=self.layout,
                root_name=self._repository,
            )
        except AmbiguousItemLayout as exc:
            raise AmbiguousItemLayout(f"{self._identity}: {exc}") from exc
        resolved = {item.upstream_id: item for item in items}
        self._layouts[commit] = resolved
        return resolved

    def _enumerate_all(self) -> tuple[ProviderItem, ...]:
        if self._items is not None:
            return self._items
        self._items = tuple(
            ProviderItem(
                upstream_id=item.upstream_id,
                upstream_name=item.upstream_name,
                collection_membership=item.collection_membership,
                content_hint=item.primary_path,
            )
            for item in self._layout().values()
        )
        return self._items

    def _entry(self, upstream_id: str) -> dict[str, Any]:
        for item in self._enumerate_all():
            if item.upstream_id == upstream_id:
                return self._tree_entries()[str(item.content_hint)]
        raise KeyError(f"{self._identity} has no item {upstream_id!r}")
