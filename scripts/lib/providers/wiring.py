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
import errno
import hashlib
import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .admission import AdmissionContext, AdmissionReport, evaluate_inventory
from .cache_transaction import (
    CompletenessEvidence,
    IncompleteRetrieval,
    InstallOutcome,
    ProjectionActivation,
    install_foreign_item,
    reinstall_from_cache,
)
from .contract import SourceProvider
from .executable_admission import AdmissionLedgerStore, ExecutableAdmissionLedger
from .foreign_cache import (
    IDENTITY_TRANSFORMATION,
    ObjectStore,
    TofuPinStore,
    Transformation,
    normalized_content_digest,
)
from .inventory import NormalizedItem, Rights
from .legacy_projections import NonComplianceRegister, guard_rematerialization
from .normalize import NormalizationResult, normalize_inventory
from .offline import ResolutionEvidence
from .placement import curated_skill_classes
from .receipts import ReceiptStore, ReceiptTarget
from .rights import evaluate_cache_retention, project
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
        if not paths:
            # A declared capability that answers "no members" is a broken adapter,
            # not an absent capability. Downgrading to the adapter's own word here
            # discarded the manifest AND recorded the false reason that the
            # provider does not declare it, so a nonempty retrieval installed
            # against a manifest it never had to match.
            raise IncompleteRetrieval(
                f"{provider.identity()} declares member_manifest and returned no "
                f"members for {item.qualified_identity()}; an item with no members "
                "cannot be retrieved completely, and an empty manifest is a defect "
                "in the adapter rather than an absent capability"
            )
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


class ProjectionEscape(RuntimeError):
    """A projection path resolves outside the target root it declared.

    The planned/applied comparison is a **string** comparison, so a path that
    traverses a symlink out of the root satisfies it perfectly while the bytes
    land somewhere else entirely. Review demonstrated it: a pre-existing
    `target/link` symlink turned a declared `target/link/escaped.txt` into a
    write outside the root, with a matching plan and an accepted receipt.
    """


def _contained_path(root: Path, relative: str) -> Path:
    """Resolve one member path and refuse anything that leaves `root`.

    Containment is checked against the **real** path, because the declared path
    is exactly what an escape keeps intact. Every existing component between the
    root and the file is checked for being a symlink, since one of those is the
    whole mechanism, and the final containment check catches the rest.
    """
    real_root = Path(os.path.realpath(root))
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise ProjectionEscape(
            f"projection member {relative!r} is not a contained relative path"
        )
    candidate = root / relative
    current = root
    for part in Path(relative).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ProjectionEscape(
                f"projection path {relative!r} traverses the symlink {current}; a "
                "declared path that resolves elsewhere satisfies the plan check "
                "while the bytes land outside the target root"
            )
    if candidate.is_symlink():
        raise ProjectionEscape(
            f"projection target {candidate} is an existing symlink; writing "
            "through it would place the bytes outside the target root"
        )
    resolved_parent = Path(os.path.realpath(candidate.parent))
    if resolved_parent != real_root and real_root not in resolved_parent.parents:
        raise ProjectionEscape(
            f"projection path {relative!r} resolves to {resolved_parent}, which is "
            f"outside the declared target root {real_root}"
        )
    return candidate


def _write_beneath(root: Path, relative: str, payload: bytes) -> Path:
    """Create one file strictly beneath `root`, resolving nothing by name.

    Checking a path and then writing it cannot be made safe by checking harder.
    Whatever the check saw, any component can be replaced before the write opens
    it — review demonstrated it twice, first on the final component and then, once
    `O_NOFOLLOW` closed that, on an intermediate directory replaced inside the
    `os.open` call itself.

    The fix is to stop naming the path at all after the first component. Every
    directory is opened relative to the descriptor of the one above it, with
    `O_NOFOLLOW` and `O_DIRECTORY`, and the file is created relative to the last
    of those descriptors. A component swapped for a symlink after it has been
    opened changes nothing: the descriptor already refers to the real directory,
    and a component swapped *before* it is opened fails the `O_NOFOLLOW` open.
    There is no window between resolution and use because the resolution is the
    use.

    Returns:
        The path that was written, for the receipt.

    Raises:
        ProjectionEscape: when any component is or becomes a symlink.
    """
    parts = Path(relative).parts
    if not parts:
        raise ProjectionEscape("a projection member needs a path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    # The root is the destination the caller declared, so it is created and
    # followed deliberately. Everything below it is opened no-follow: the
    # containment guarantee is "beneath this root", not "this root exists".
    root.mkdir(parents=True, exist_ok=True)
    descriptors: list[int] = [os.open(root, os.O_RDONLY | directory)]
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=descriptors[-1])
            except FileExistsError:
                pass
            try:
                descriptors.append(
                    os.open(
                        part,
                        os.O_RDONLY | directory | nofollow,
                        dir_fd=descriptors[-1],
                    )
                )
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
                    raise ProjectionEscape(
                        f"projection path {relative!r} traverses {part!r}, which is "
                        "not a real directory beneath the target root; the write is "
                        "refused rather than redirected"
                    ) from exc
                raise
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | nofollow
        try:
            target = os.open(parts[-1], flags, 0o644, dir_fd=descriptors[-1])
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise ProjectionEscape(
                    f"projection target {relative!r} is a symlink; the write is "
                    "refused rather than redirected"
                ) from exc
            raise
        try:
            handle = os.fdopen(target, "wb")
        except BaseException:
            # `fdopen` takes ownership only once it succeeds, so a failure here
            # leaves the descriptor ours to close.
            os.close(target)
            raise
        with handle:
            handle.write(payload)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    return root.joinpath(*parts)


def filesystem_activation(
    target_root: Path, *, non_compliance: "NonComplianceRegister | None" = None
) -> ProjectionActivation:
    """A two-phase filesystem projection into one directory.

    `plan` computes the paths from the projected content and touches nothing;
    `apply` creates exactly those and returns them with their install-time
    digests. A single "write it and tell me what you wrote" callable cannot be
    made recoverable, because the only record of what exists is produced after it
    already exists.

    Both phases enforce containment, not just `apply`: a plan that declares a
    path it may not write is already wrong, and refusing at plan time means
    nothing has been created when the refusal happens.

    `non_compliance` is the `CL-m6cc` re-materialization block, and it is checked
    in both phases for the same reason. Every path that reaches disk goes through
    this activation -- install and repair alike -- so a legacy projection whose
    redistribution state is `unknown` or `denied` is refused here regardless of
    which caller asked, and refused before a byte is written.
    """
    root = Path(target_root)

    def plan(content: Mapping[str, bytes]) -> Sequence[str]:
        planned = sorted(str(_contained_path(root, relative)) for relative in content)
        guard_rematerialization(
            non_compliance, paths=planned, digest=normalized_content_digest(content)
        )
        return planned

    def apply(content: Mapping[str, bytes]) -> Sequence[ReceiptTarget]:
        guard_rematerialization(
            non_compliance,
            paths=sorted(str(root / relative) for relative in content),
            digest=normalized_content_digest(content),
        )
        # Every path is shape-checked before any byte is written, so a member
        # that could not be contained refuses the whole activation rather than
        # leaving the earlier members installed. The containment that matters is
        # then enforced by `_write_beneath`, which never resolves a component by
        # name a second time: a check whose result is used later is a check that
        # can be invalidated in between, and review invalidated this one twice.
        for relative in content:
            _contained_path(root, relative)
        created: list[ReceiptTarget] = []
        for relative in sorted(content):
            payload = content[relative]
            path = _write_beneath(root, relative, payload)
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


def _composed_blocks(
    state: "ForeignState", supplied: NonComplianceRegister | None
) -> NonComplianceRegister | ComposedNonCompliance:
    """The state's register, plus any the caller added. Never instead of.

    A caller-supplied register began as a *replacement* for the state's, which
    made the state register a default rather than an invariant: passing an empty
    register turned every block off, and review named that as the residual left
    by the F1 repair. Composition is the fix — a caller may add blocks and can
    never remove one, so the shipped enforcement is not something a call site
    can opt out of.
    """
    bound = state.non_compliance_register()
    if supplied is None or supplied.path == bound.path:
        return bound
    return ComposedNonCompliance((bound, supplied))


@dataclass(frozen=True)
class ComposedNonCompliance:
    """Several registers read as one. Any of them blocking is blocking."""

    registers: tuple[NonComplianceRegister, ...]

    def matches(self, *, paths: Sequence[str] = (), digest: str | None = None):
        found: list[Any] = []
        for register in self.registers:
            found.extend(register.matches(paths=paths, digest=digest))
        return tuple(found)

    def is_blocked(self, *, path: str | None = None, digest: str | None = None) -> bool:
        return bool(self.matches(paths=[path] if path is not None else [], digest=digest))

    def blocked(self):
        found: list[Any] = []
        for register in self.registers:
            found.extend(register.blocked())
        return tuple(found)


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
    non_compliance: NonComplianceRegister | None = None,
) -> InstallOutcome:
    """Install one normalized item through the ordered cache transaction.

    Every obligation the transaction refuses to work without is supplied here
    rather than defaulted: stated completeness evidence, and a two-phase
    projection whose applied paths must equal its declared plan.

    **Durable retention is gated before anything is retrieved.** ADR-0011
    `Caching is not installing` governs keeping an offline copy by
    `install_rights`, not by `fetch_authorization`: `denied` forbids durable
    retention outright and leaves only transient retrieval, and `unknown` makes
    it an operator-acknowledged act under the same shown-first opt-in as a
    machine-local projection. The cache transaction evaluates only the
    *projection* decision, and it materializes the object and writes the receipt
    before it gets there — so review found `install_rights="denied"` leaving a
    cache object and a receipt behind a refused projection. The retention
    decision therefore has to be made here, before the transaction starts.

    **A non-compliant legacy projection is refused before anything is fetched.**
    `CL-m6cc` records projections whose redistribution state is `unknown` or
    `denied`; they may not be re-materialized by any later sync. The activation
    enforces that per member path, and this earlier check enforces it for the
    target root as a whole, so the refusal costs no retrieval.

    **The admission ledger is located, not passed.** `ledger` defaults to the
    operator's durable decisions in `state`, and a caller that supplies one is
    substituting a different operator's ledger deliberately. The alternative --
    `None` meaning "trust the item's own `executable_admission` field" -- put the
    decision in the hands of whoever produced the item, which is exactly the
    producer-asserted trust `admission.evaluate_item` already refuses to
    consult. Before `CL-2wqz` the shipped CLI passed nothing at all here, so the
    ledger the gate consulted was never the one an operator could write to.
    """
    if ledger is None:
        ledger = state.admission_ledger()
    blocks = _composed_blocks(state, non_compliance)
    guard_rematerialization(blocks, paths=[str(Path(target_root))])
    retention = evaluate_cache_retention(item.rights, subject=item.qualified_identity())
    project(retention, lambda: None, present=present)
    return install_foreign_item(
        item,
        retrieve=lambda: provider.fetch(item.upstream_id, item.upstream_revision),
        object_store=state.object_store(),
        pin_store=state.pin_store(),
        receipt_store=state.receipt_store(scope),
        target=target,
        activate=filesystem_activation(target_root, non_compliance=blocks),
        observed_at=observed_at or _now(),
        completeness=completeness_for(provider, item),
        transformation=transformation,
        ledger=ledger,
        present=present,
    )


def repair_projection(
    *,
    receipt: Any,
    state: "ForeignState",
    scope: str,
    target_root: Path,
    availability: Any,
    non_compliance: NonComplianceRegister | None = None,
    observed_at: str | None = None,
) -> Any:
    """Reinstall one receipt's projection from the verified cache.

    Repair is the second production path that writes projected bytes, and it is
    the one an enforcement check written for `install` quietly misses: it makes
    no remote claim, needs no rights re-evaluation, and reads as recovery rather
    than as installation. ADR-0011 `Legacy Projection Disposition` says a
    non-compliant projection cannot be re-materialized by future sync **or
    repair**, so the block is checked here against the receipt's own recorded
    and planned targets, and again inside the activation.
    """
    blocks = _composed_blocks(state, non_compliance)
    guard_rematerialization(
        blocks,
        paths=[
            str(Path(target_root)),
            *[target.path for target in receipt.targets],
            *receipt.planned_targets,
        ],
        digest=receipt.projected_content_digest,
    )
    return reinstall_from_cache(
        receipt=receipt,
        object_store=state.object_store(),
        receipt_store=state.receipt_store(scope),
        availability=availability,
        activate=filesystem_activation(target_root, non_compliance=blocks),
        observed_at=observed_at or _now(),
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
    #: Where the `CL-m6cc` non-compliant-projection register lives. Derived from
    #: the cache root rather than configured separately, and **not** optional:
    #: review found the register implemented as an optional keyword that the
    #: shipped CLI never passed, so the durable block existed and the one caller
    #: that could honor it did not. A control whose enforcement depends on every
    #: call site remembering an argument is a control that is already off
    #: somewhere. A caller now acquires the block by locating its stores.
    non_compliance_path: Path | None = None
    #: Where the `CL-2wqz` executable-admission decisions live. Derived from the
    #: cache root for the same reason as the register above, and addressed from
    #: the cache rather than from a lock: admission is the scope operator's
    #: decision about *bytes*, and those bytes are held once here no matter which
    #: project's lock happens to reference them.
    admission_ledger_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cache_root", Path(self.cache_root))
        object.__setattr__(self, "pin_path", Path(self.pin_path))
        object.__setattr__(self, "purge_ledger_path", Path(self.purge_ledger_path))
        object.__setattr__(
            self,
            "non_compliance_path",
            Path(self.non_compliance_path)
            if self.non_compliance_path is not None
            else Path(self.cache_root) / "non-compliant-projections.json",
        )
        object.__setattr__(
            self,
            "admission_ledger_path",
            Path(self.admission_ledger_path)
            if self.admission_ledger_path is not None
            else Path(self.cache_root) / "executable-admission.json",
        )
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
            non_compliance_path=root / "non-compliant-projections.json",
            admission_ledger_path=root / "executable-admission.json",
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

    def admission_ledger_store(self) -> AdmissionLedgerStore:
        """The durable store of this operator's executable-admission decisions."""
        self.admission_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        return AdmissionLedgerStore(self.admission_ledger_path)

    def admission_ledger(self) -> ExecutableAdmissionLedger:
        """The decisions that stand right now, as the gate consults them."""
        return self.admission_ledger_store().ledger()

    def non_compliance_register(self) -> NonComplianceRegister:
        """The register of projections no sync or repair may write.

        Always present, never optional. An empty or absent register blocks
        nothing, which is the correct pre-migration state; a *damaged* one
        refuses, which is the fail-closed state.
        """
        return NonComplianceRegister(self.non_compliance_path)


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
