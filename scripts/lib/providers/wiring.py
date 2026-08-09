"""Production wiring: the call sites that turn the provider core into a feature.

Slices 1-5 delivered a provider contract, a rights and admission model, a
durable cache transaction, retention, and cross-catalog resolution — and every
one of them shipped with **no production caller**. This module is where that
boundary closes. It is the single place that knows how to turn a
`sources.marketplaces` entry into a live adapter, and the single place that
supplies the four things the cache and retention contracts refuse to work
without:

| Obligation | Routed from | Supplied here |
|---|---|---|
| `CompletenessEvidence`, stated not defaulted | `CL-y5z4` | `completeness_for` — a source-read manifest when the adapter declares one, an explicit adapter declaration with its reason when it does not |
| Two-phase `ProjectionActivation(plan, apply)` | `CL-y5z4` | `filesystem_activation` — plan lists paths without touching them, apply creates exactly those |
| A `ReferenceIndex` over **both** receipt scopes | `CL-uliw` | `reference_index` — a partial scope set is a typed refusal, never a degraded check |
| One source-scoped `ResolutionEvidence` per provider, an explicit `evidence_max_age`, and a durable purge ledger | `CL-uliw` | `resolution_observations`, `collect`, `ForeignState.purge_ledger_path` |

`build_provider` holds the one legitimate `provider_kind` branch in the
platform. It is legitimate *here* because this directory is the sanctioned home
for provider knowledge: a factory has to name the kinds it can build, and the
alternative — a registry keyed on a string that some core module dereferences —
would move the same branch somewhere it does not belong while looking cleaner.

Receipts are addressed from their lock scope, not from a second configuration
entry: `receipt_store_for(lock_path)` reads and writes
`<lock path>.foreign-receipts.json`, so "which foreign receipts belong to this
scope" is answerable from the lock path with no scan.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .admission import AdmissionContext, AdmissionReport, evaluate_inventory
from .cache_transaction import (
    CompletenessEvidence,
    InstallOutcome,
    ProjectionActivation,
    install_foreign_item,
)
from .contract import SourceProvider
from .executable_admission import ExecutableAdmissionLedger
from .foreign_cache import IDENTITY_TRANSFORMATION, ObjectStore, TofuPinStore, Transformation
from .inventory import NormalizedItem, Rights
from .normalize import NormalizationResult, normalize_inventory
from .offline import ResolutionEvidence
from .placement import curated_skill_classes
from .receipts import ReceiptStore, ReceiptTarget
from .reference_rights import rights_for
from .retention import (
    GarbageCollectionResult,
    PurgeLedger,
    ReceiptScope,
    ReferenceIndex,
    RefetchProof,
    REQUIRED_SCOPES,
    collect_garbage,
    plan_garbage_collection,
)

#: The suffix a lock scope's foreign receipts live under, beside the lock.
FOREIGN_RECEIPT_SUFFIX = ".foreign-receipts.json"

#: Registry of provider kinds this platform can build. The keys are the ADR-0011
#: `Provider kinds` values; the builders live in this package.
PROVIDER_KINDS = ("git-repo", "git-org", "mcp-content")


class ProviderBuildError(ValueError):
    """A marketplace entry could not be turned into a provider adapter."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def receipt_store_for(lock_path: Path) -> ReceiptStore:
    """The foreign-receipt store bound to one lock scope."""
    path = Path(lock_path)
    return ReceiptStore(path.with_name(f"{path.name}{FOREIGN_RECEIPT_SUFFIX}"))


# -- provider construction ----------------------------------------------------


def build_provider(
    entry: Mapping[str, Any],
    *,
    http_transport: Any = None,
    mcp_transport: Any = None,
) -> SourceProvider:
    """Build the adapter one `sources.marketplaces` entry declares.

    Args:
        entry: A validated marketplace entry.
        http_transport: Transport for the Git-backed kinds. The adapter's own
            default is used when omitted.
        mcp_transport: The MCP client for a token-scoped content provider.
            Whoever supplies it owns the connection and therefore the credential;
            nothing in this package resolves, stores, or transmits one.

    Raises:
        ProviderBuildError: when the entry declares no provider kind, an unknown
            one, or a kind whose required configuration is missing.
    """
    kind = str(entry.get("provider_kind") or "").strip()
    if not kind:
        raise ProviderBuildError(
            f"marketplace {entry.get('name')!r} declares no provider_kind; the "
            "legacy type-driven path installs nothing through the provider contract"
        )
    source = str(entry.get("source") or "").strip()
    if not source:
        raise ProviderBuildError(f"marketplace {entry.get('name')!r} has no source")

    auth_ref = entry.get("auth_ref")
    layout = str(entry.get("layout") or "").strip()

    if kind == "git-repo":
        from .git_repo import GitRepoProvider
        from .decompose import MARKER_LAYOUT

        options: dict[str, Any] = {
            "repository_url": source,
            "ref": str(entry.get("branch") or entry.get("ref") or "main"),
            "auth_ref": auth_ref,
            "layout": layout or MARKER_LAYOUT,
        }
        if http_transport is not None:
            options["transport"] = http_transport
        return GitRepoProvider(**options)

    if kind == "git-org":
        from .git_org import AllowlistRequired, GitOrgProvider
        from .decompose import BUNDLE_LAYOUT

        allowlist = entry.get("allowlist")
        if not isinstance(allowlist, (list, tuple)) or not allowlist:
            raise ProviderBuildError(
                f"marketplace {entry.get('name')!r} is an organization provider and "
                "requires a non-empty allowlist"
            )
        options = {
            "organization_url": source,
            "allowlist": tuple(str(name) for name in allowlist),
            "refs": dict(entry.get("refs") or {}),
            "default_ref": str(entry.get("branch") or entry.get("ref") or "main"),
            "auth_ref": auth_ref,
            "layout": layout or BUNDLE_LAYOUT,
        }
        if http_transport is not None:
            options["transport"] = http_transport
        try:
            return GitOrgProvider(**options)
        except AllowlistRequired as exc:
            raise ProviderBuildError(str(exc)) from exc

    if kind == "mcp-content":
        from .mcp_content import (
            CredentialReferenceRequired,
            CredentialValueRefused,
            McpContentProvider,
        )

        # The canonical identity is a URN, so the entry's source carries the
        # scheme and the server name is what follows it.
        _, _, server_name = source.partition(":")
        try:
            return McpContentProvider(
                server_name=server_name or source,
                auth_ref=str(auth_ref or ""),
                auth_scope=str(entry.get("auth_scope") or "content:read"),
                transport=mcp_transport,
            )
        except (CredentialReferenceRequired, CredentialValueRefused) as exc:
            raise ProviderBuildError(str(exc)) from exc

    raise ProviderBuildError(
        f"marketplace {entry.get('name')!r} declares provider_kind {kind!r}; this "
        f"platform builds {list(PROVIDER_KINDS)}"
    )


def source_revision(
    identity: str,
    *,
    catalog: Mapping[str, Any],
    http_transport: Any = None,
) -> str:
    """What one registered source currently serves, as a commit.

    This is the seam a cross-catalog resolution needs to verify its declared
    pins. It is provider work by definition -- reading what a source serves is
    the one thing the Workspace layer must not know how to do -- and it takes an
    identity rather than a `DeclaredCatalog` so that this module never imports
    the Workspace layer that imports it.

    A source with a local checkout is answered from that checkout's HEAD, which
    is what "what does this source serve" means on a machine where the source is
    a sibling working tree. A remote-only source is answered from its ref, with
    no clone.

    Raises:
        LookupError: when the identity is not a registered source. An
            unregistered source has no answer, and no answer is never a
            verified pin.
    """
    from .git_url import head_commit

    normalized = str(identity).rstrip("/").removesuffix(".git")
    for source in (
        *(catalog.get("sources", {}) or {}).get("catalogs", []),
        *(catalog.get("sources", {}) or {}).get("marketplaces", []),
    ):
        if not isinstance(source, Mapping):
            continue
        candidate = str(source.get("source") or "").rstrip("/").removesuffix(".git")
        if candidate != normalized:
            continue
        local_path = source.get("local_path")
        if local_path:
            path = Path(str(local_path)).expanduser()
            if path.is_dir():
                revision = head_commit(path)
                if revision != "local":
                    return revision
                raise LookupError(
                    f"{identity} has a local checkout at {path} that is not a "
                    "tracked working tree, so it serves no commit to verify against"
                )
        from .git_repo import GitRepoProvider

        options: dict[str, Any] = {
            "repository_url": str(source.get("source")),
            "ref": str(source.get("branch") or source.get("default_branch") or "main"),
        }
        if http_transport is not None:
            options["transport"] = http_transport
        return GitRepoProvider(**options).current_revision()

    raise LookupError(
        f"{identity} is not a registered source on this machine, so nothing can "
        "say what it currently serves"
    )


def recorded_rights(entry: Mapping[str, Any], provider_identity: str) -> Rights:
    """The rights this source records, from the catalog entry or the ADR record.

    The catalog entry wins: an operator's own recorded evidence is the more
    specific statement. The researched reference values are the fallback, and an
    unlisted provider with no catalog rights lands on the all-`unknown` default,
    which blocks a committed projection.
    """
    declared = entry.get("rights")
    if isinstance(declared, Mapping) and declared:
        return Rights.from_dict(dict(declared))
    return rights_for(provider_identity) or Rights()


# -- inventory ----------------------------------------------------------------


def marketplace_inventory(
    entry: Mapping[str, Any],
    *,
    http_transport: Any = None,
    mcp_transport: Any = None,
    selector: Any = None,
    inspect_content: bool = False,
    trust_state: str = "unreviewed",
) -> tuple[SourceProvider, NormalizationResult]:
    """Normalize one registered marketplace's inventory through its adapter."""
    provider = build_provider(
        entry, http_transport=http_transport, mcp_transport=mcp_transport
    )
    identity = provider.identity()
    result = normalize_inventory(
        provider,
        selector=selector,
        rights=recorded_rights(entry, identity),
        trust_state=trust_state,
        inspect_content=inspect_content,
        curated_skill_classes=curated_skill_classes(identity),
    )
    return provider, result


def admitted_inventory(
    result: NormalizationResult,
    context: AdmissionContext,
    *,
    ledger: ExecutableAdmissionLedger | None = None,
    contents: Mapping[str, Mapping[str, bytes]] | None = None,
) -> AdmissionReport:
    """Evaluate a normalized inventory against one scope policy."""
    return evaluate_inventory(
        result.inventory, context, ledger=ledger, contents=contents
    )


# -- install call site --------------------------------------------------------


def completeness_for(
    provider: SourceProvider, item: NormalizedItem
) -> CompletenessEvidence:
    """State how this retrieval's completeness is established, never defaulting.

    A source that can list an item's members supplies a manifest, and the install
    checks the retrieval against it. A source that cannot gets an adapter
    declaration carrying the reason — which is the weakest claim in the
    vocabulary and is therefore never allowed to be the silent one.
    """
    declared = provider.capabilities()
    if "member_manifest" in declared:
        paths = tuple(provider.member_manifest(item.upstream_id, item.upstream_revision))
        if paths:
            return CompletenessEvidence.from_manifest(
                paths,
                detail=(
                    f"member list read from {provider.identity()} at revision "
                    f"{item.upstream_revision or 'none (revisionless source)'}"
                ),
            )
    return CompletenessEvidence.adapter_declared(
        f"{provider.identity()} does not declare member_manifest, so no independent "
        "member list exists to check the retrieval against; completeness rests on "
        "the adapter's own contract that FetchedItem is complete"
    )


def filesystem_activation(target_root: Path) -> ProjectionActivation:
    """A two-phase filesystem projection into one directory.

    `plan` computes the paths from the projected content and touches nothing;
    `apply` creates exactly those and returns them with their install-time
    digests. A single "write it and tell me what you wrote" callable cannot be
    made recoverable, because the only record of what exists is produced after it
    already exists.
    """
    root = Path(target_root)

    def _paths(content: Mapping[str, bytes]) -> list[str]:
        return sorted(str(root / relative) for relative in content)

    def plan(content: Mapping[str, bytes]) -> Sequence[str]:
        return _paths(content)

    def apply(content: Mapping[str, bytes]) -> Sequence[ReceiptTarget]:
        created: list[ReceiptTarget] = []
        for relative in sorted(content):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = content[relative]
            path.write_bytes(payload)
            created.append(
                ReceiptTarget(
                    path=str(path),
                    kind="file",
                    # The digest of what was written, taken from the bytes that
                    # were written -- not re-read from disk, which would record
                    # whatever a concurrent writer left there instead.
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        return created

    return ProjectionActivation(plan=plan, apply=apply)


def install_marketplace_item(
    item: NormalizedItem,
    *,
    provider: SourceProvider,
    state: "ForeignState",
    scope: str,
    target: str,
    target_root: Path,
    ledger: ExecutableAdmissionLedger | None = None,
    transformation: Transformation = IDENTITY_TRANSFORMATION,
    present: Callable[[Any], Any] | None = None,
    observed_at: str | None = None,
) -> InstallOutcome:
    """Install one normalized item through the ordered cache transaction.

    Every obligation the transaction refuses to work without is supplied here
    rather than defaulted: stated completeness evidence, and a two-phase
    projection whose applied paths must equal its declared plan.
    """
    return install_foreign_item(
        item,
        retrieve=lambda: provider.fetch(item.upstream_id, item.upstream_revision),
        object_store=state.object_store(),
        pin_store=state.pin_store(),
        receipt_store=state.receipt_store(scope),
        target=target,
        activate=filesystem_activation(target_root),
        observed_at=observed_at or _now(),
        completeness=completeness_for(provider, item),
        transformation=transformation,
        ledger=ledger,
        present=present,
    )


# -- durable state ------------------------------------------------------------


@dataclass(frozen=True)
class ForeignState:
    """Every durable location the foreign-content path writes to.

    One value rather than five arguments, because the failure mode is a caller
    that supplies four of them correctly. In particular the purge ledger has no
    default: the acknowledgement is written *before* the bytes are removed, so a
    ledger nobody configured is a purge with no record of intent.
    """

    cache_root: Path
    pin_path: Path
    purge_ledger_path: Path
    #: Receipt store location per scope name. Every scope in
    #: `retention.REQUIRED_SCOPES` must be present and at a distinct location.
    receipt_paths: Mapping[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cache_root", Path(self.cache_root))
        object.__setattr__(self, "pin_path", Path(self.pin_path))
        object.__setattr__(self, "purge_ledger_path", Path(self.purge_ledger_path))
        paths = {str(name): Path(value) for name, value in self.receipt_paths.items()}
        missing = sorted(set(REQUIRED_SCOPES) - set(paths))
        if missing:
            raise ValueError(
                f"foreign state must locate every receipt scope; {missing} is not "
                "configured. A partial scope set answers 'unreferenced' for objects "
                "another scope is holding"
            )
        object.__setattr__(self, "receipt_paths", paths)

    @classmethod
    def for_locks(
        cls,
        *,
        cache_root: Path,
        project_lock: Path,
        global_lock: Path,
    ) -> "ForeignState":
        """Locate every store from the two lock paths that own them."""
        root = Path(cache_root)
        return cls(
            cache_root=root,
            pin_path=root / "tofu-pins.json",
            purge_ledger_path=root / "purge-ledger.json",
            receipt_paths={
                "project": Path(f"{project_lock}{FOREIGN_RECEIPT_SUFFIX}"),
                "global": Path(f"{global_lock}{FOREIGN_RECEIPT_SUFFIX}"),
            },
        )

    def object_store(self) -> ObjectStore:
        return ObjectStore(self.cache_root)

    def pin_store(self) -> TofuPinStore:
        self.pin_path.parent.mkdir(parents=True, exist_ok=True)
        return TofuPinStore(self.pin_path)

    def receipt_store(self, scope: str) -> ReceiptStore:
        try:
            path = self.receipt_paths[scope]
        except KeyError as exc:
            raise KeyError(
                f"unknown receipt scope {scope!r}; this state locates "
                f"{sorted(self.receipt_paths)}"
            ) from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        return ReceiptStore(path)

    def purge_ledger(self) -> PurgeLedger:
        self.purge_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        return PurgeLedger(self.purge_ledger_path)


def reference_index(state: ForeignState) -> ReferenceIndex:
    """A reference check over **every** required receipt scope.

    Built from the state rather than assembled at each call site, because the
    check is only ever run immediately before deleting something and a call site
    that forgot a scope would answer "unreferenced" for an object another lock is
    holding.
    """
    return ReferenceIndex(
        [
            ReceiptScope(name=name, store=state.receipt_store(name))
            for name in sorted(state.receipt_paths)
        ]
    )


def resolution_observations(
    providers: Sequence[SourceProvider],
    *,
    complete: bool = True,
) -> dict[str, ResolutionEvidence]:
    """One source-scoped observation per provider identity.

    An object whose own source was not observed is retained by the collector:
    one source's listing says nothing about another's items, and review
    demonstrated one source's complete listing marking another's receipts
    upstream-vanished.
    """
    observations: dict[str, ResolutionEvidence] = {}
    for provider in providers:
        identity = provider.identity()
        availability = provider.availability()
        listed: set[str] = set()
        conclusive = complete and availability.state == "available"
        if conclusive:
            try:
                listed = {
                    f"{identity}#{item.upstream_id}" for item in provider.enumerate()
                }
            except Exception:  # noqa: BLE001 - a failed listing is an inconclusive one
                conclusive = False
        observations[identity] = ResolutionEvidence(
            provider_identity=identity,
            availability=_provider_availability(availability),
            listed_identities=frozenset(listed),
            complete=conclusive,
        )
    return observations


def _provider_availability(availability: Any):
    from .inventory import ProviderAvailability

    return ProviderAvailability(
        state=availability.state,
        observed_at=availability.observed_at,
        reason=availability.reason,
    )


def collect(
    state: ForeignState,
    *,
    observations: Mapping[str, ResolutionEvidence],
    evidence_max_age: timedelta,
    refetch_proofs: Sequence[RefetchProof] = (),
    observed_at: str | None = None,
    apply: bool = False,
) -> GarbageCollectionResult | Any:
    """Plan, and optionally perform, automatic collection.

    Args:
        evidence_max_age: How old a source observation or re-fetch proof may be
            and still describe the present. **Required, with no default**: how
            stale a re-fetch proof may be is operator policy, and the failure it
            prevents is silent — review supplied an observation and a proof that
            agreed with each other and were both twenty-six years old, and the
            last copy of a revisionless object's pinned bytes was deleted.
        apply: When false, the plan is returned and nothing is deleted.
    """
    moment = observed_at or _now()
    if not apply:
        return plan_garbage_collection(
            object_store=state.object_store(),
            references=reference_index(state),
            observations=dict(observations),
            refetch_proofs=tuple(refetch_proofs),
            observed_at=moment,
            evidence_max_age=evidence_max_age,
        )
    return collect_garbage(
        object_store=state.object_store(),
        references=reference_index(state),
        observations=dict(observations),
        refetch_proofs=tuple(refetch_proofs),
        observed_at=moment,
        evidence_max_age=evidence_max_age,
        pin_store=state.pin_store(),
    )
