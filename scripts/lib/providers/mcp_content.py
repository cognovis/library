"""The reference `mcp-content` provider adapter: MCP as transport, nothing more.

ADR-0011 `MCP as transport is not the MCP primitive` states the single most
confusable point in the architecture as an invariant: **the transport that
delivered an artifact contributes nothing to that artifact's type, scope,
dependencies, or ownership.** A prompt kit that arrives over MCP produces a
Prompt receipt for the prompt's own type and scope. It never creates an `mcp:`
dependency edge, a global ownership edge, or a harness MCP registration. If the
fetched artifact genuinely needs a running server at use time, that server is a
separate global prerequisite the artifact declares — never something implied by
how its bytes travelled.

This adapter is therefore deliberately small. It lists, describes, and fetches,
and it does nothing else. There is no code path from here to the MCP installer,
the harness MCP configuration, or the dependency graph.

## Credentials

This adapter holds **no credential value and no credential-bearing field**. It
carries a credential *reference* — a name that points at provider configuration
someone else owns — and returns it through `auth_requirements()` with its scope,
which is exactly what ADR-0011 `Credential isolation` permits and all it
permits.

Resolving that reference into a connection stays outside this module. `CL-r8rr`
added a transport (`providers.mcp_http`) and put its construction in the CLI,
which is the layer that owns the operator's configuration; the adapter still
receives a caller-owned transport and still has no field a credential value
belongs in. An operator with no registered endpoint gets a typed `unavailable`
availability naming the credential reference. That is a refusal, never a
fallback, and in particular never a substitution of some other public source for
this one.

## Collection profiles

A content server's tool vocabulary is a property of that server. The default
profile is the generic one (`list_content` / `get_content`, a `files` mapping
with a `primary_path`); `SERVER_PROFILES` records the named vocabulary of a
server that publishes several typed collections instead.

Selecting a profile by server name inside this module is deliberate, and it is
the narrowest place the knowledge can live. The alternative considered was a new
`library.yaml` marketplace field, which would put one server's internal tool
names into a schema every catalog shares and every future provider would have to
read past. `reference_rights.py` is the recorded precedent: naming a provider is
legitimate at the adapter boundary and nowhere else, and the provider-neutrality
check treats this directory as the sanctioned location for exactly this. A
caller may still pass `collections=` explicitly, so the selection is a default
rather than a hard-wiring.

## Revisionlessness

The provider declares no `revision_of`, so it is revisionless under ADR-0011
`Trust on first use`: its content is TOFU-pinned, a re-fetch that disagrees with
the pin is fail-closed drift, and there is no digest-polling freshness. A pin is
a record of what was first seen, not a proof of upstream authenticity, and this
module does not let a caller pretend otherwise: `fetch` refuses a requested
revision outright rather than accepting one and ignoring it.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .classification import library_type_for
from .contract import (
    AuthRequirement,
    Availability,
    FetchedFile,
    FetchedItem,
    ItemDescription,
    ProviderItem,
    REQUIRED_CAPABILITIES,
    RightsEvidence,
    SourceProvider,
)
from .mcp_http import McpTransportError, redact_endpoints

#: URN scheme for a non-URL provider identity (ADR-0011 `Consumers of provider
#: identity`). The bare server name is a display alias only.
IDENTITY_SCHEME = "mcp"

#: A credential *reference* is a name. This is a shape floor, not a secret
#: detector.
#:
#: Review demonstrated the first version's limit: `sk-prod-0123456789abcdef` is
#: identifier-shaped, so it was accepted as a reference and echoed verbatim in a
#: diagnostic. The floor below is raised to catch the shapes a pasted credential
#: actually has — a known issuer prefix, or a long unbroken run of token
#: characters — and it is deliberately *stated* as a floor rather than dressed up
#: as detection: no shape rule can tell a secret from a name, and a caller who
#: chooses a reference that looks exactly like a plausible identifier will pass.
#: What the design does guarantee is elsewhere: this adapter has no field a
#: credential value belongs in and no code that reads one.
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,39}$")

#: Issuer prefixes common enough that a reference starting with one is far more
#: likely to be a pasted credential than a configuration key.
_CREDENTIAL_PREFIXES = (
    "sk-",
    "sk_",
    "pk-",
    "pk_",
    "rk_",
    "ghp_",
    "gho_",
    "ghs_",
    "github_pat_",
    "glpat-",
    "xox",
    "eyj",
    "bearer",
    "basic ",
    "token-",
    "secret-",
)

#: An unbroken run of token characters this long is a value, not a name. Real
#: references are hyphenated or dotted words.
_OPAQUE_RUN_RE = re.compile(r"[A-Za-z0-9]{20,}")


class CredentialReferenceRequired(ValueError):
    """An `mcp-content` provider was constructed without a credential reference.

    ADR-0011 `Provider kinds` records this provider kind's auth as required and
    token-scoped. A registration with no reference could not state which
    credential governs the fetch, and `fetch_authorization` would then rest on
    nothing while looking configured.
    """


class CredentialValueRefused(ValueError):
    """Something other than a credential reference was supplied as one.

    Never let a value take a reference's place. A credential reference is
    recorded in inventory, receipts, and diagnostics; a value in that field
    would be written to every one of them.
    """


class ProviderUnauthenticated(RuntimeError):
    """The provider is token-scoped and no transport is configured for it.

    A typed availability fact. It is not a reason to read some other source: the
    reference provider has a distinct public repository that is explicitly not
    it, and substituting one for the other would attach one party's content to
    another party's identity.
    """


class McpResponseInvalid(RuntimeError):
    """The provider answered with something that is not the declared shape."""


class McpTransport(Protocol):
    """The typed MCP tool-call seam.

    Whoever supplies this owns the connection and therefore owns the credential.
    That separation is the point: this adapter cannot leak a secret it was never
    given.
    """

    def call(self, tool: str, arguments: Mapping[str, Any]) -> Any: ...


#: Recorded for an item whose collection publishes an audience axis that this
#: particular item does not carry.
#:
#: The profiled server publishes `audience_access` on prompt kits and not on
#: guides. Filling the gap with `standard` would be the single most convenient
#: falsehood available here: it reads as a published fact, it is the permissive
#: value, and nobody upstream ever said it. Omitting the key entirely would be
#: honest but indistinguishable from a collection that has no audience axis at
#: all, so the absence is recorded as a value of its own.
AUDIENCE_NOT_PUBLISHED = "not-published"


@dataclass(frozen=True)
class ContentCollection:
    """One enumerable collection of a content server, declared rather than probed.

    A profile is data. Nothing in this adapter discovers a tool by calling it and
    catching the failure -- that is the exception-driven capability probing the
    provider contract exists to forbid.

    Args:
        name: The Library-facing collection name, and the first segment of every
            `upstream_id` it produces. Empty for the single unnamed collection of
            the generic default profile, whose ids stay unqualified.
        list_tool: The enumeration tool.
        fetch_tool: The single-item tool.
        id_field: The listing field carrying the id the Library records. A
            readable, stable asset id is preferred over an opaque UUID, because
            it is what ends up in receipts, pins, and operator commands.
        fetch_key_field: The listing field carrying the value `fetch` sends. It
            is frequently *not* `id_field`: the profiled server rejects anything
            but its UUID, while the UUID is the worse identity to record.
        content_field: The payload field carrying the item's whole content as
            text. `None` means the payload is a `files` mapping instead.
        primary_path: The item-relative path the collection's content is
            projected at, and the marker path `describe` classifies from. It is
            not currently a *discriminator*: `PROMPT.md`, `GUIDE.md`, and the
            payload-driven default all reach `prompt` through the same `.md`
            extension default, so today it decides the filename an operator sees
            and the path a receipt records, not the Library type. It is declared
            per collection anyway because a collection whose primary path becomes
            a marker file -- `SKILL.md`, say -- would classify differently
            without any other change here. `None` means the payload names its own
            `primary_path`.
        audience_field: The listing field carrying the audience axis, when the
            collection publishes one. `None` means the concept does not exist
            here, and no audience key is recorded at all.
        limit: The enumeration limit to request, which is the server's own
            maximum. A listing that comes back at or above this size may be
            truncated, and the provider reports that as `degraded` together with
            the count it actually observed.
    """

    name: str
    list_tool: str
    fetch_tool: str
    id_field: str = "id"
    fetch_key_field: str = "id"
    content_field: str | None = None
    primary_path: str | None = None
    audience_field: str | None = None
    limit: int | None = None

    def qualify(self, asset_id: str) -> str:
        """The Library-facing upstream id for one listed asset."""
        return f"{self.name}/{asset_id}" if self.name else asset_id

    def arguments(self) -> dict[str, Any]:
        """The enumeration arguments, which carry the cap when one is declared."""
        return {} if self.limit is None else {"limit": self.limit}


#: The generic vocabulary, used by every server this module does not profile.
#: `list_tool`/`fetch_tool` on the provider configure exactly this collection.
DEFAULT_LIST_TOOL = "list_content"
DEFAULT_FETCH_TOOL = "get_content"

#: Named tool vocabularies, keyed by MCP server name. See the module docstring
#: for why this selection lives in the adapter and not in `library.yaml`.
#:
#: The profiled server caps every listing at 100 entries and exposes no offset,
#: so `limit` is the server's maximum rather than a Library preference.
SERVER_PROFILES: Mapping[str, tuple[ContentCollection, ...]] = {
    "executive-circle": (
        ContentCollection(
            name="prompt-kits",
            list_tool="list_prompt_kits",
            fetch_tool="get_prompt_kit",
            id_field="asset_id",
            fetch_key_field="id",
            content_field="content",
            primary_path="PROMPT.md",
            audience_field="audience_access",
            limit=100,
        ),
        ContentCollection(
            name="guides",
            list_tool="list_guides",
            fetch_tool="get_guide",
            id_field="asset_id",
            fetch_key_field="id",
            content_field="content",
            # Guides do not publish `audience_access` today. The field is still
            # declared, so an item that starts carrying one is recorded rather
            # than dropped, and one that does not records the absence explicitly.
            audience_field="audience_access",
            primary_path="GUIDE.md",
            limit=100,
        ),
    ),
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refuse_credential_shape(reference: str) -> None:
    """Refuse a value where a credential reference belongs.

    The reference is recorded in inventory, receipts, and diagnostics, so a value
    placed here would be written into all of them. Three checks, each catching a
    shape the previous one let through:

    1. it has to be name-shaped and short;
    2. it must not start with a known credential issuer prefix;
    3. it must not contain a long unbroken run of token characters.

    None of this detects a secret. It refuses the shapes a pasted credential
    actually has, and the module docstring states the limit plainly.
    """
    if not _REFERENCE_RE.fullmatch(reference):
        raise CredentialValueRefused(
            "auth_ref must be the NAME of a credential reference, not a credential "
            "value or free text. It is recorded in inventory, receipts, and "
            "diagnostics, so a value placed here would be written to all of them"
        )
    lowered = reference.lower()
    if lowered.startswith(_CREDENTIAL_PREFIXES):
        raise CredentialValueRefused(
            f"auth_ref {reference[:6]!r}... begins like a credential value rather "
            "than a configuration key. Name the reference the credential is stored "
            "under; the value itself belongs only in provider configuration"
        )
    if _OPAQUE_RUN_RE.search(reference):
        raise CredentialValueRefused(
            "auth_ref contains a long unbroken run of token characters, which is "
            "the shape of a value rather than of a name. Name the reference the "
            "credential is stored under"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpResponseInvalid(f"{label} is required and must be text")
    return value.strip()


@dataclass
class McpContentProvider(SourceProvider):
    """One token-scoped MCP content provider, revisionless and transport-only."""

    server_name: str
    #: The named credential reference. A name, never a value.
    auth_ref: str = ""
    auth_scope: str = "content:read"
    #: The MCP client. `None` means no configured access, which is a typed
    #: availability answer rather than an error at construction: a provider an
    #: operator has registered but not authenticated is a legitimate state, and
    #: registration installs nothing.
    transport: McpTransport | None = None
    #: The generic vocabulary. These configure the single collection of the
    #: default profile only; a server with a named profile declares its tools in
    #: `SERVER_PROFILES` and ignores these.
    list_tool: str = DEFAULT_LIST_TOOL
    fetch_tool: str = DEFAULT_FETCH_TOOL
    #: An explicit collection profile, overriding the one this server's name
    #: selects. `None` selects `SERVER_PROFILES[server_name]` when it exists and
    #: the generic default profile otherwise.
    collections: tuple[ContentCollection, ...] | None = None

    def __post_init__(self) -> None:
        name = _text(self.server_name, "server_name")
        self._identity = f"{IDENTITY_SCHEME}:{name}"
        reference = str(self.auth_ref or "").strip()
        if not reference:
            raise CredentialReferenceRequired(
                f"{self._identity} is a token-scoped provider and requires a named "
                "credential reference; a registration with none cannot say which "
                "credential authorizes a fetch"
            )
        _refuse_credential_shape(reference)
        self.auth_ref = reference
        if self.collections is None:
            self.collections = SERVER_PROFILES.get(
                name,
                (
                    ContentCollection(
                        name="",
                        list_tool=self.list_tool,
                        fetch_tool=self.fetch_tool,
                    ),
                ),
            )
        self.collections = tuple(self.collections)
        if not self.collections:
            raise ValueError(
                f"{self._identity} was given an empty collection profile; a "
                "provider that enumerates nothing is not a provider"
            )
        self._items: tuple[ProviderItem, ...] | None = None
        self._descriptions: dict[str, dict[str, Any]] = {}
        self._collection_of: dict[str, ContentCollection] = {}
        self._fetch_keys: dict[str, str] = {}
        #: `(collection name, observed count, declared cap)` for every listing
        #: that came back at or above its declared limit, so truncation is
        #: reportable. The observed count is carried separately because the
        #: trigger is `observed >= cap`, not `observed == cap`: a server that
        #: answered 150 against a declared cap of 100 would otherwise have the
        #: sentence "returned the server maximum of 100 entries" written into a
        #: receipt, which is a false record of what was observed.
        self._capped: tuple[tuple[str, int, int], ...] = ()

    # -- Required capabilities ------------------------------------------------

    def identity(self) -> str:
        return self._identity

    def capabilities(self) -> frozenset[str]:
        """Required capabilities, plus `describe` and `rights_evidence`.

        `revision_of` is absent by design: the provider has no immutable upstream
        revision, which makes it revisionless and pin-only. `verify` is absent
        because the provider publishes no native integrity proof, so the Library
        normalized digest is the only one. `item_rights_evidence` is absent
        because one subscription governs the whole endpoint.
        """
        return REQUIRED_CAPABILITIES | {"describe", "rights_evidence"}

    def enumerate(self, selector: Any = None) -> Sequence[ProviderItem]:
        """List the provider's items, one typed tool call per declared collection.

        Args:
            selector: Optional collection name. Only items in it are returned.
        """
        items = self._enumerate_all()
        if not selector:
            return items
        wanted = str(selector).strip("/")
        return tuple(item for item in items if wanted in item.collection_membership)

    def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
        """Complete content for one item. Revisionless, so pin-only.

        Raises:
            ValueError: when a revision is requested. This provider has none, and
                accepting the argument to ignore it would let a caller believe it
                pinned something.
            KeyError: when the provider does not list that item.
        """
        if revision is not None:
            raise ValueError(
                f"{self._identity} is revisionless: it has no immutable upstream "
                f"revision to fetch {upstream_id!r} at. Its continuity is a "
                "trust-on-first-use pin over the normalized content digest"
            )
        self._description(upstream_id)  # refuse an item this provider does not list
        collection = self._collection_of[upstream_id]
        payload = self._call(
            collection.fetch_tool, {"id": self._fetch_keys[upstream_id]}
        )
        if not isinstance(payload, Mapping):
            raise McpResponseInvalid(
                f"{collection.fetch_tool} must answer with an object carrying the "
                f"item's complete files, got {type(payload).__name__}"
            )
        if collection.content_field:
            return self._fetch_content_field(upstream_id, collection, payload)
        files = payload.get("files")
        if not isinstance(files, Mapping) or not files:
            raise McpResponseInvalid(
                f"{collection.fetch_tool} must answer with a non-empty `files` "
                "mapping of item-relative path to content; a marker file alone is "
                "not an item"
            )
        primary = _text(payload.get("primary_path"), "primary_path")
        members = []
        for path in sorted(files):
            content = files[path]
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, (bytes, bytearray)):
                raise McpResponseInvalid(
                    f"content for {path!r} must be text or bytes, got "
                    f"{type(content).__name__}"
                )
            members.append(FetchedFile(path=str(path), content=bytes(content)))
        return FetchedItem(
            upstream_id=upstream_id,
            revision=None,
            files=tuple(members),
            primary_path=primary,
        )

    def _fetch_content_field(
        self,
        upstream_id: str,
        collection: ContentCollection,
        payload: Mapping[str, Any],
    ) -> FetchedItem:
        """One asset object whose whole content is a single text field.

        The item is one file at the collection's declared primary path. There is
        no media or attachment tool on this profile, so an item that references
        an upload is text-only and stays text-only -- recorded here rather than
        discovered later as a missing file.
        """
        content = payload.get(collection.content_field or "")
        if isinstance(content, (bytes, bytearray)):
            content = bytes(content)
        elif isinstance(content, str):
            content = content.encode("utf-8")
        else:
            raise McpResponseInvalid(
                f"{collection.fetch_tool} answered for {upstream_id!r} with no "
                f"{collection.content_field!r} text; an item with no content is "
                "not an item, and caching an empty one would pin nothing"
            )
        if not content.strip():
            raise McpResponseInvalid(
                f"{collection.fetch_tool} answered for {upstream_id!r} with empty "
                f"{collection.content_field!r}; an empty item would be pinned, "
                "receipted, and projected as though it were content"
            )
        primary = collection.primary_path or "CONTENT.md"
        return FetchedItem(
            upstream_id=upstream_id,
            revision=None,
            files=(FetchedFile(path=primary, content=content),),
            primary_path=primary,
        )

    def auth_requirements(self) -> Sequence[AuthRequirement]:
        """The named credential reference and its scope. Never a value."""
        return (
            AuthRequirement(
                reference=self.auth_ref, scope=self.auth_scope, required=True
            ),
        )

    def availability(self) -> Availability:
        """Reachability of the token-scoped endpoint, as a typed observation."""
        if self.transport is None:
            return Availability(
                state="unavailable",
                observed_at=_now(),
                reason=(
                    f"no configured access for credential reference "
                    f"{self.auth_ref!r} (scope {self.auth_scope!r}); this provider "
                    "is token-scoped and unauthenticated access is a refusal, not a "
                    "reason to read a different source"
                ),
            )
        try:
            self._enumerate_all()
        except (
            ProviderUnauthenticated,
            McpResponseInvalid,
            McpTransportError,
            OSError,
        ) as exc:
            # The failures an *endpoint* can produce, named exactly. A bare
            # `except Exception` here was worse than untidy: a `TypeError` from a
            # defect in this adapter would have been reported as a benign
            # `unavailable` observation and then written verbatim into a foreign
            # receipt, so a bug in this file would have been persisted as a fact
            # about somebody else's server. A programming error propagates.
            #
            # Redacted even though the transport already redacts: the transport
            # is caller-owned, so this module cannot assume the one it was handed
            # is the one that promises to.
            return Availability(
                state="unavailable",
                observed_at=_now(),
                reason=redact_endpoints(f"{self._identity} is unavailable: {exc}"),
            )
        if self._capped:
            # `degraded`, not `unavailable`: the items that did enumerate are
            # real and installable, and the admission gate blocks only on
            # `unavailable`. What must not happen is a listing of exactly the cap
            # being read as a complete inventory -- against which one
            # reconciliation would mark every unlisted installed item vanished.
            truncated = "; ".join(
                f"collection {name!r} returned {observed} entries against a declared "
                f"cap of {cap}"
                for name, observed, cap in self._capped
            )
            return Availability(
                state="degraded",
                observed_at=_now(),
                reason=(
                    f"{truncated}. The endpoint exposes no offset, so enumeration "
                    "may be truncated and this inventory must not be read as the "
                    "provider's complete listing"
                ),
            )
        return Availability(state="available", observed_at=_now())

    # -- Optional capabilities ------------------------------------------------

    def describe(self, upstream_id: str) -> ItemDescription:
        """Classify from the listing's own metadata, with no content fetch.

        The Library type is derived from the item's primary path exactly as it
        is for any other provider. The transport contributes nothing to it —
        which is the invariant this whole adapter exists to hold.

        A collection that publishes an audience axis carries it into
        `classification`, from where `normalize.normalize_inventory` copies it
        onto the normalized item. It is recorded, never enforced: which audience
        an item is published to is upstream's statement, and what a scope may do
        with the item is the rights and admission gates' decision.
        """
        listed = self._description(upstream_id)
        collection = self._collection_of[upstream_id]
        primary = collection.primary_path or str(
            listed.get("primary_path") or listed.get("name") or upstream_id
        )
        library_type, basis = library_type_for(primary)
        classification = {"type_basis": basis, "upstream_path": primary}
        if collection.name:
            classification["upstream_collection"] = collection.name
        if collection.audience_field:
            audience = listed.get(collection.audience_field)
            classification["audience_access"] = (
                audience.strip()
                if isinstance(audience, str) and audience.strip()
                else AUDIENCE_NOT_PUBLISHED
            )
        return ItemDescription(
            upstream_id=upstream_id,
            library_type=library_type,
            classification=classification,
            runtime_compatibility=tuple(listed.get("runtime_compatibility") or ("unknown",)),
        )

    def rights_evidence(self) -> RightsEvidence:
        """Whether the provider publishes a licence pointer of its own."""
        if self.transport is None:
            return RightsEvidence(
                located=False,
                detail=(
                    "the provider is unreachable without configured access, so no "
                    "licensing evidence could be looked for"
                ),
            )
        return RightsEvidence(
            located=False,
            detail=(
                "no published licence or redistribution grant is served by this "
                "endpoint; a subscriber credential proves the endpoint will serve "
                "bytes and proves nothing about redistributing them"
            ),
        )

    # -- Internals ------------------------------------------------------------

    def _call(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        if self.transport is None:
            raise ProviderUnauthenticated(
                f"{self._identity} requires credential reference {self.auth_ref!r} "
                f"(scope {self.auth_scope!r}) and no access is configured"
            )
        return self.transport.call(tool, dict(arguments))

    def _enumerate_all(self) -> tuple[ProviderItem, ...]:
        if self._items is not None:
            return self._items
        items: list[ProviderItem] = []
        descriptions: dict[str, dict[str, Any]] = {}
        collection_of: dict[str, ContentCollection] = {}
        fetch_keys: dict[str, str] = {}
        capped: list[tuple[str, int]] = []

        for collection in self.collections or ():
            payload = self._call(collection.list_tool, collection.arguments())
            if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
                raise McpResponseInvalid(
                    f"{collection.list_tool} must answer with a list of items, got "
                    f"{type(payload).__name__}"
                )
            entries = list(payload)
            if collection.limit is not None and len(entries) >= collection.limit:
                capped.append(
                    (
                        collection.name or self.server_name,
                        len(entries),
                        collection.limit,
                    )
                )
            for entry in entries:
                if not isinstance(entry, Mapping):
                    raise McpResponseInvalid(
                        f"each item {collection.list_tool} lists must be an object"
                    )
                asset_id = _text(
                    entry.get(collection.id_field), f"item {collection.id_field}"
                )
                upstream_id = collection.qualify(asset_id)
                if upstream_id in descriptions:
                    # Silently keeping the last one would bind a pin, a receipt,
                    # and a projection to whichever entry happened to be listed
                    # second, and nothing downstream could tell that had happened.
                    raise McpResponseInvalid(
                        f"{self._identity} listed {upstream_id!r} more than once; a "
                        "duplicate identity cannot be resolved to one item, and "
                        "keeping the later one would silently overwrite the earlier"
                    )
                fetch_keys[upstream_id] = _text(
                    entry.get(collection.fetch_key_field),
                    f"item {collection.fetch_key_field}",
                )
                name = _text(
                    entry.get("name") or asset_id.rsplit("/", 1)[-1], "item name"
                )
                if collection.name:
                    membership: tuple[str, ...] = (collection.name,)
                else:
                    membership = tuple(str(part) for part in entry.get("collection") or ())
                content_hint = collection.primary_path or str(
                    entry.get("primary_path") or name
                )
                items.append(
                    ProviderItem(
                        upstream_id=upstream_id,
                        upstream_name=name,
                        collection_membership=membership,
                        content_hint=content_hint,
                    )
                )
                descriptions[upstream_id] = dict(entry)
                collection_of[upstream_id] = collection

        self._items = tuple(items)
        self._descriptions = descriptions
        self._collection_of = collection_of
        self._fetch_keys = fetch_keys
        self._capped = tuple(capped)
        return self._items

    def _description(self, upstream_id: str) -> Mapping[str, Any]:
        self._enumerate_all()
        try:
            return self._descriptions[upstream_id]
        except KeyError as exc:
            raise KeyError(f"{self._identity} has no item {upstream_id!r}") from exc
