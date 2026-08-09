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

Resolving that reference into a token, storing one, exchanging one, or putting
one on the wire is **not implemented here and is out of this slice's scope**: it
is credential handling and requires a human security review before any such code
is written. The consequence is stated rather than hidden: an operator who has
not supplied a transport gets a typed `unavailable` availability naming the
credential reference. That is a refusal, never a fallback, and in particular
never a substitution of some other public source for this one.

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
    list_tool: str = "list_content"
    fetch_tool: str = "get_content"

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
        self._items: tuple[ProviderItem, ...] | None = None
        self._descriptions: dict[str, dict[str, Any]] = {}

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
        """List the provider's items through one typed tool call.

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
        payload = self._call(self.fetch_tool, {"id": upstream_id})
        if not isinstance(payload, Mapping):
            raise McpResponseInvalid(
                f"{self.fetch_tool} must answer with an object carrying the item's "
                f"complete files, got {type(payload).__name__}"
            )
        files = payload.get("files")
        if not isinstance(files, Mapping) or not files:
            raise McpResponseInvalid(
                f"{self.fetch_tool} must answer with a non-empty `files` mapping of "
                "item-relative path to content; a marker file alone is not an item"
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
        except (ProviderUnauthenticated, McpResponseInvalid) as exc:
            return Availability(state="unavailable", observed_at=_now(), reason=str(exc))
        except Exception as exc:  # noqa: BLE001 - any transport failure is one fact
            return Availability(
                state="unavailable",
                observed_at=_now(),
                reason=f"transport failure for {self._identity}: {exc}",
            )
        return Availability(state="available", observed_at=_now())

    # -- Optional capabilities ------------------------------------------------

    def describe(self, upstream_id: str) -> ItemDescription:
        """Classify from the listing's own metadata, with no content fetch.

        The Library type is derived from the item's primary path exactly as it
        is for any other provider. The transport contributes nothing to it —
        which is the invariant this whole adapter exists to hold.
        """
        listed = self._description(upstream_id)
        primary = str(listed.get("primary_path") or listed.get("name") or upstream_id)
        library_type, basis = library_type_for(primary)
        return ItemDescription(
            upstream_id=upstream_id,
            library_type=library_type,
            classification={"type_basis": basis, "upstream_path": primary},
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
        payload = self._call(self.list_tool, {})
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise McpResponseInvalid(
                f"{self.list_tool} must answer with a list of items, got "
                f"{type(payload).__name__}"
            )
        items: list[ProviderItem] = []
        descriptions: dict[str, dict[str, Any]] = {}
        for entry in payload:
            if not isinstance(entry, Mapping):
                raise McpResponseInvalid("each listed item must be an object")
            upstream_id = _text(entry.get("id"), "item id")
            name = _text(entry.get("name") or upstream_id.rsplit("/", 1)[-1], "item name")
            membership = tuple(str(part) for part in entry.get("collection") or ())
            items.append(
                ProviderItem(
                    upstream_id=upstream_id,
                    upstream_name=name,
                    collection_membership=membership,
                    content_hint=str(entry.get("primary_path") or name),
                )
            )
            descriptions[upstream_id] = dict(entry)
        self._items = tuple(items)
        self._descriptions = descriptions
        return self._items

    def _description(self, upstream_id: str) -> Mapping[str, Any]:
        self._enumerate_all()
        try:
            return self._descriptions[upstream_id]
        except KeyError as exc:
            raise KeyError(f"{self._identity} has no item {upstream_id!r}") from exc
