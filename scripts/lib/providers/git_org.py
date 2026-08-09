"""The reference `git-org` provider adapter: an allowlist, then per-repository work.

ADR-0011 `Provider kinds`: `git-org` is **not** "a Git repo with a wildcard".
Organization-level enumeration without an allowlist is refused, because it makes
the inventory a function of someone else's repository creation — an upstream
party could add a repository and have its content appear in a Library catalog.
The allowlist is Library-owned configuration, and this adapter cannot be
constructed without one.

Two properties follow from that and are the reason this is an adapter of its own
rather than a loop over `GitRepoProvider`:

- **Revision identity is per repository.** An organization has no commit. Every
  item's `upstream_revision` is the commit of the repository that carries it.
- **Rights are per repository.** ADR-0011 records the reference organization's
  grant as per repository and names one repository in the same organization with
  no observed `LICENSE`. This adapter therefore declares `item_rights_evidence`,
  which is what makes a consumer ask per item instead of letting one repository's
  grant cover a sibling that has none.

The organization listing is still fetched, even though the allowlist alone would
bound the inventory. Fetching it is what lets the adapter say that a repository
exists upstream and is deliberately absent, rather than merely never looking; it
is also what turns an allowlist typo into a loud refusal instead of a quietly
smaller inventory.

Provider knowledge lives here and only here.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .contract import (
    AuthRequirement,
    Availability,
    FetchedItem,
    ItemDescription,
    ProviderItem,
    REQUIRED_CAPABILITIES,
    RightsEvidence,
    SourceProvider,
)
from .decompose import BUNDLE_LAYOUT, LAYOUTS, ROOT_ITEM_ID
from .git_repo import (
    DEFAULT_API_BASE,
    DEFAULT_RAW_BASE,
    GitRepoProvider,
    HttpTransport,
    ProviderInventoryIncomplete,
    ProviderTransportError,
    UrllibTransport,
)

#: How many repositories one listing request asks for. A full page is treated as
#: a truncated answer (ADR-0011 Invariant 8) rather than as the whole listing.
LISTING_PAGE_SIZE = 100


class AllowlistRequired(ValueError):
    """A `git-org` provider was constructed without a Library-owned allowlist."""


class AllowlistUnserved(RuntimeError):
    """An allowlisted repository is not among the ones the organization serves.

    Silently dropping it would shrink the inventory without a word, and the
    shrink is indistinguishable from the upstream repository having been made
    private or renamed. Both are facts an operator needs; neither is an empty
    listing.
    """


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_organization(organization_url: str) -> tuple[str, str]:
    parsed = urlparse(organization_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 1:
        raise ValueError(
            "a git-org provider needs an organization or owner URL, got "
            f"{organization_url!r}"
        )
    return parsed.netloc, parts[0]


@dataclass
class GitOrgProvider(SourceProvider):
    """One organization, bounded by a Library-owned repository allowlist."""

    organization_url: str
    allowlist: Sequence[str] = ()
    transport: HttpTransport = field(default_factory=UrllibTransport)
    api_base: str = DEFAULT_API_BASE
    raw_base: str = DEFAULT_RAW_BASE
    #: Per-repository ref or commit. A repository with no entry uses
    #: `default_ref`. Revision identity is per repository, so this is a mapping
    #: rather than one value.
    refs: Mapping[str, str] = field(default_factory=dict)
    default_ref: str = "main"
    layout: str = BUNDLE_LAYOUT
    auth_ref: str | None = None
    auth_scope: str = "contents:read"
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._host, self._organization = _split_organization(self.organization_url)
        self._identity = f"https://{self._host}/{self._organization}"
        allowlist = tuple(str(name).strip() for name in self.allowlist)
        if not allowlist or any(not name for name in allowlist):
            raise AllowlistRequired(
                f"{self._identity} is an organization provider and requires a "
                "non-empty allowlist of repository names: without one the inventory "
                "would be a function of someone else's repository creation"
            )
        duplicates = sorted({name for name in allowlist if allowlist.count(name) > 1})
        if duplicates:
            raise AllowlistRequired(
                f"allowlist entries must be distinct; {duplicates} appears more than once"
            )
        if self.layout not in LAYOUTS:
            raise ValueError(
                f"unknown layout {self.layout!r} for {self._identity}; "
                f"expected {list(LAYOUTS)}"
            )
        self.allowlist = allowlist
        self._allowed = allowlist
        self._repositories: dict[str, GitRepoProvider] = {}
        self._listing: tuple[str, ...] | None = None
        self._items: tuple[ProviderItem, ...] | None = None

    # -- Required capabilities ------------------------------------------------

    def identity(self) -> str:
        return self._identity

    def capabilities(self) -> frozenset[str]:
        """The full contract, including per-item rights.

        `describe` and `revision_of` are per repository, and `item_rights_evidence`
        is the capability that makes a consumer resolve rights per repository
        instead of applying one organization-wide answer.
        """
        return REQUIRED_CAPABILITIES | {
            "describe",
            "revision_of",
            "verify",
            "rights_evidence",
            "item_rights_evidence",
            "member_manifest",
        }

    def enumerate(self, selector: Any = None) -> Sequence[ProviderItem]:
        """Every item of every allowlisted repository, and nothing else.

        Args:
            selector: Optional repository name or `<repository>/<prefix>` path.
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
        """Complete content for one item, from the repository that carries it."""
        repository, member = self._split(upstream_id)
        fetched = self._provider(repository).fetch(member, revision)
        # The organization's identity for this item is the qualified one; a
        # repository-relative id would collide across repositories the moment
        # two of them ship a member with the same path.
        return FetchedItem(
            upstream_id=upstream_id,
            revision=fetched.revision,
            files=fetched.files,
            primary_path=fetched.primary_path,
        )

    def auth_requirements(self) -> Sequence[AuthRequirement]:
        """The named credential reference, when this source declares one."""
        if not self.auth_ref:
            return ()
        return (AuthRequirement(reference=self.auth_ref, scope=self.auth_scope),)

    def availability(self) -> Availability:
        """Aggregate availability over the allowlist, with the reason named.

        A partly reachable organization is `degraded`, never `available`: an
        inventory missing one repository's items looks exactly like that
        repository having been emptied, and ADR-0011 forbids presenting a reduced
        listing as a complete one.
        """
        try:
            self._organization_listing()
        except (ProviderTransportError, ProviderInventoryIncomplete) as exc:
            return Availability(state="unavailable", observed_at=_now(), reason=str(exc))
        unreachable: list[str] = []
        for repository in self._allowed:
            state = self._provider(repository).availability()
            if state.state != "available":
                unreachable.append(f"{repository}: {state.reason or state.state}")
        if not unreachable:
            return Availability(state="available", observed_at=_now())
        if len(unreachable) == len(self._allowed):
            return Availability(
                state="unavailable",
                observed_at=_now(),
                reason="; ".join(unreachable),
            )
        return Availability(
            state="degraded",
            observed_at=_now(),
            reason="; ".join(unreachable),
        )

    # -- Optional capabilities ------------------------------------------------

    def describe(self, upstream_id: str) -> ItemDescription:
        """Classify from the owning repository's tree metadata alone."""
        repository, member = self._split(upstream_id)
        description = self._provider(repository).describe(member)
        classification = dict(description.classification)
        classification["upstream_repository"] = repository
        return ItemDescription(
            upstream_id=upstream_id,
            library_type=description.library_type,
            classification=classification,
            runtime_compatibility=description.runtime_compatibility,
            content_identity=description.content_identity,
        )

    def revision_of(self, upstream_id: str) -> str:
        """The commit of the repository that carries this item.

        Per repository, not per organization: an organization has no revision,
        and recording one repository's commit against another's item would be
        fabricated provenance that reads as a clean pin.
        """
        repository, member = self._split(upstream_id)
        return self._provider(repository).revision_of(member)

    def member_manifest(
        self, upstream_id: str, revision: str | None = None
    ) -> Sequence[str]:
        """The owning repository's manifest for this item."""
        repository, member = self._split(upstream_id)
        return self._provider(repository).member_manifest(member, revision)

    def verify(self, content: bytes, expected: str) -> bool:
        """Provider-native integrity proof, identical across repositories."""
        return self._provider(self._allowed[0]).verify(content, expected)

    def rights_evidence(self) -> RightsEvidence:
        """An organization publishes no licence of its own.

        `located=False` here is the honest answer and is a different fact from
        an adapter that cannot look: the per-repository answer is where the
        evidence actually is, and this adapter declares `item_rights_evidence`
        so a consumer asks there.
        """
        return RightsEvidence(
            located=False,
            detail=(
                "an organization has no licence of its own; licensing evidence is "
                "recorded per repository and resolved through item_rights_evidence"
            ),
        )

    def item_rights_evidence(self, upstream_id: str) -> RightsEvidence:
        """The licensing evidence of the repository that carries this item."""
        repository, _ = self._split(upstream_id)
        evidence = self._provider(repository).rights_evidence()
        if evidence.located:
            return evidence
        return RightsEvidence(
            located=False,
            detail=(
                f"no licence file in the pinned tree of {repository!r}; a sibling "
                "repository's grant is not this repository's grant"
            ),
        )

    # -- Internals ------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return dict(self.headers)

    def _organization_listing(self) -> tuple[str, ...]:
        """Every repository name the organization currently serves."""
        if self._listing is not None:
            return self._listing
        errors: list[str] = []
        for owner_kind in ("orgs", "users"):
            url = (
                f"{self.api_base}/{owner_kind}/{self._organization}"
                f"/repos?per_page={LISTING_PAGE_SIZE}"
            )
            try:
                payload = self.transport.get_json(url, self._headers())
            except ProviderTransportError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(payload, list):
                raise ProviderTransportError(f"unexpected repository listing from {url}")
            if len(payload) >= LISTING_PAGE_SIZE:
                raise ProviderInventoryIncomplete(
                    f"{self._identity} filled a listing page at {url}; a paginated "
                    "listing is not a complete one, and an incomplete listing cannot "
                    "state that a repository is absent"
                )
            names = tuple(
                str(entry.get("name"))
                for entry in payload
                if isinstance(entry, dict) and entry.get("name")
            )
            missing = sorted(set(self._allowed) - set(names))
            if missing:
                raise AllowlistUnserved(
                    f"{self._identity} does not serve allowlisted repositories "
                    f"{missing}; the allowlist is Library-owned configuration and a "
                    "silently smaller inventory is not an answer"
                )
            self._listing = names
            return self._listing
        raise ProviderTransportError(
            f"no repository listing for {self._identity}: {'; '.join(errors)}"
        )

    def _provider(self, repository: str) -> GitRepoProvider:
        if repository not in self._allowed:
            raise KeyError(
                f"{repository!r} is not on the allowlist for {self._identity}; "
                f"this provider contributes only {list(self._allowed)}"
            )
        cached = self._repositories.get(repository)
        if cached is not None:
            return cached
        provider = GitRepoProvider(
            repository_url=f"{self._identity}/{repository}",
            ref=str(self.refs.get(repository) or self.default_ref),
            transport=self.transport,
            api_base=self.api_base,
            raw_base=self.raw_base,
            auth_ref=self.auth_ref,
            auth_scope=self.auth_scope,
            headers=self.headers,
            layout=self.layout,
        )
        self._repositories[repository] = provider
        return provider

    def _split(self, upstream_id: str) -> tuple[str, str]:
        repository, separator, member = str(upstream_id).partition("/")
        if not repository:
            raise KeyError(f"{upstream_id!r} names no repository in {self._identity}")
        if repository not in self._allowed:
            raise KeyError(
                f"{upstream_id!r} names repository {repository!r}, which is not on "
                f"the allowlist for {self._identity}"
            )
        return repository, member if separator else ROOT_ITEM_ID

    def _qualify(self, repository: str, member: str) -> str:
        return repository if member == ROOT_ITEM_ID else f"{repository}/{member}"

    def _enumerate_all(self) -> tuple[ProviderItem, ...]:
        if self._items is not None:
            return self._items
        # The listing is read first so an allowlist entry the organization does
        # not serve refuses here, before any inventory is produced.
        self._organization_listing()
        items: list[ProviderItem] = []
        for repository in self._allowed:
            for item in self._provider(repository).enumerate():
                items.append(
                    ProviderItem(
                        upstream_id=self._qualify(repository, item.upstream_id),
                        upstream_name=item.upstream_name,
                        # The repository is the outermost collection: without it
                        # two repositories' identically named members would look
                        # like one collection's duplicates.
                        collection_membership=(repository, *item.collection_membership),
                        content_hint=item.content_hint,
                    )
                )
        self._items = tuple(items)
        return self._items

    def organization_repositories(self) -> tuple[str, ...]:
        """Every repository the organization serves, allowlisted or not.

        Public because "what did the allowlist exclude" is an operator question
        and an inventory that simply never mentions a repository cannot answer it.
        """
        return self._organization_listing()

    def excluded_repositories(self) -> tuple[str, ...]:
        """Repositories the organization serves that the allowlist does not admit."""
        return tuple(
            name for name in self._organization_listing() if name not in self._allowed
        )
