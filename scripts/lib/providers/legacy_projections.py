"""Disposition of already-materialized projections (CL-m6cc, AC5-AC8).

ADR-0011 `Legacy Projection Disposition` records the concrete state this module
answers to: 23 skill directories and 4 workflow specs are materialized on the
operator's machine with **no lockfile receipt at all**. With zero receipts there
is no recorded provenance, so the original survey could only match names -- and
its own text says so one paragraph before concluding that nothing is currently
non-compliant. The `CL-2p73` review routed that contradiction here, and this
module resolves it in the only honest direction: **provenance is re-derived by
content digest, and a name is decoration.**

The consequences follow mechanically rather than by judgement:

- An unattributed projection has `unknown` redistribution rights, and `unknown`
  is non-compliant. Not condemned -- non-compliant means it may not be
  re-materialized until its digest resolves, and it keeps every byte it has.
- A non-compliant projection is blocked at the **plan** phase of any projection
  activation, so both a later sync and a later repair refuse before writing.
- Remediation is an operator act with two named paths, and neither of them can
  run without a confirmation this module issued from a statement it rendered.

Nothing here deletes or moves anything on its own. `apply_remediation` is the
one function that can, it is not reachable from the migration module, and it
refuses without a confirmation bound to a presentation it just created.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .cache_transaction import (
    CompletenessEvidence,
    InstallOutcome,
    install_foreign_item,
)
from .contract import FetchedFile, FetchedItem
from .foreign_cache import normalized_content_digest
from .inventory import (
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from .receipts import ForeignReceipt, ReceiptStore
from .state_files import atomic_write_text

INVENTORY_SCHEMA = "cognovis.legacy-projection-inventory.v1"
NON_COMPLIANCE_SCHEMA = "cognovis.legacy-projection-non-compliance.v1"

#: Three provenance states, ordered by the strength of the evidence behind them.
#:
#: - `attributed`: the projection's normalized content digest matches a digest a
#:   provider actually served. This is what the bytes say.
#: - `receipt-declared`: an existing lock receipt claims this path, with a
#:   catalog identity and a source. This is what the Library believes it
#:   installed, and it is much stronger than a name and weaker than a digest.
#: - `unattributed`: neither. Nothing local can say where these bytes came from.
#:
#: The middle state is named separately rather than folded into `attributed`
#: precisely so the two can never be read as the same evidence -- which is the
#: conflation the `CL-2p73` review objected to, one level up.
PROVENANCE_STATES: tuple[str, ...] = (
    "attributed",
    "receipt-declared",
    "unattributed",
)
COMPLIANCE_STATES: tuple[str, ...] = ("compliant", "non-compliant")
RECEIPT_STATES: tuple[str, ...] = ("receipted", "unreceipted")

#: The two remediation paths ADR-0011 names, in the order it names them. The
#: list is closed: a third path would be a policy change, not a convenience.
REMEDIATION_PATHS: tuple[str, ...] = (
    "operator-confirmed-removal",
    "relocate-machine-local",
)

#: Why an unattributed projection's rights are unresolved. Routed verbatim from
#: the `CL-2p73` review (gpt-5.6-sol advisory A1): every legacy entry is recorded
#: as rights-unresolved-pending-digest-attribution until its digest resolves.
PENDING_DIGEST_ATTRIBUTION = "rights-unresolved-pending-digest-attribution"

#: ADR-0006 keeps Workflow executor authority. A receipt backfill writes a
#: receipt for bytes that were already there; it selects no executor and changes
#: none, and the request records that as a checked field rather than a promise.
EXECUTOR_AUTHORITY = "adr-0006"

_NO_DIGEST_MATCH = (
    "no provider content digest matches this projection; a shared name is not "
    "provenance, and a Library-shaped directory without a Library receipt is "
    "not Library-owned"
)


class RematerializationBlocked(RuntimeError):
    """A non-compliant projection may not be written by sync or repair."""


class RemediationRefused(RuntimeError):
    """A remediation was attempted without a confirmation that authorizes it."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value


# -- the inventory --------------------------------------------------------------


@dataclass(frozen=True)
class LegacyProjection:
    """One materialized thing on a harness path, described by its bytes."""

    path: str
    name: str
    kind: str
    content_digest: str
    member_count: int
    member_paths: tuple[str, ...] = ()
    link_target: str | None = None
    resolved_path: str | None = None

    def __post_init__(self) -> None:
        _text(self.path, "LegacyProjection.path")
        _text(self.name, "LegacyProjection.name")
        if self.kind not in ("directory", "file", "symlink"):
            raise ValueError(f"unknown projection kind: {self.kind!r}")
        _text(self.content_digest, "LegacyProjection.content_digest")
        object.__setattr__(self, "member_paths", tuple(self.member_paths))

    def claims(self) -> tuple[str, ...]:
        """Every path a receipt could name for this projection."""
        return (self.path, *self.member_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "content_digest": self.content_digest,
            "member_count": self.member_count,
            "link_target": self.link_target,
            "resolved_path": self.resolved_path,
        }


def _content_of(path: Path) -> dict[str, bytes]:
    """The files one projection is made of, keyed by their relative paths."""
    if path.is_file():
        return {path.name: path.read_bytes()}
    files: dict[str, bytes] = {}
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        files[str(candidate.relative_to(path))] = candidate.read_bytes()
    return files


def scan_projection(path: Path) -> LegacyProjection:
    """Describe one projection by reading its bytes.

    A symlink is followed **for its content** and recorded with its literal
    target, because eleven of the inventoried entries are Library-shaped bridges
    into `~/.agents/skills`, and their content is what a digest can attribute.
    The link itself is still recorded, so the shape stays visible as the
    non-evidence it is.
    """
    target = Path(path)
    link_target = os.readlink(target) if target.is_symlink() else None
    resolved = target.resolve() if link_target is not None else target
    files = _content_of(resolved)
    if link_target is not None:
        kind = "symlink"
    elif target.is_dir():
        kind = "directory"
    else:
        kind = "file"
    return LegacyProjection(
        path=str(target),
        name=target.name,
        kind=kind,
        content_digest=normalized_content_digest(files),
        member_count=len(files),
        member_paths=tuple(str(target / relative) for relative in sorted(files)),
        link_target=link_target,
        resolved_path=str(resolved) if link_target is not None else None,
    )


def scan_projections(
    roots: Sequence[Path], *, include: Callable[[Path], bool] | None = None
) -> tuple[LegacyProjection, ...]:
    """Every projection directly under each root, in name order."""
    found: list[LegacyProjection] = []
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir(), key=lambda item: item.name):
            if include is not None and not include(entry):
                continue
            found.append(scan_projection(entry))
    return tuple(sorted(found, key=lambda item: (item.name, item.path)))


# -- attribution and classification ---------------------------------------------


@dataclass(frozen=True)
class ProvenanceAttribution:
    """Where a projection's bytes came from, or the fact that nobody knows."""

    state: str
    evidence_source: str
    provider_identity: str | None = None
    upstream_id: str | None = None

    def __post_init__(self) -> None:
        if self.state not in PROVENANCE_STATES:
            raise ValueError(f"unknown provenance state: {self.state!r}")
        _text(self.evidence_source, "ProvenanceAttribution.evidence_source")
        if self.state != "unattributed" and not (
            self.provider_identity and self.upstream_id
        ):
            raise ValueError(
                "a resolved provenance names the provider and the upstream item it "
                "resolved to; an anonymous attribution attributes nothing"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "evidence_source": self.evidence_source,
            "provider_identity": self.provider_identity,
            "upstream_id": self.upstream_id,
        }


@dataclass(frozen=True)
class DeclaredProvenance:
    """What an existing lock receipt claims about one projected path.

    A declaration is provenance, not permission. It says which catalog the
    Library believes served these bytes; whether that catalog granted anything
    is still answered by the recorded rights, and a catalog with no rights
    record resolves to `unknown` like any other.
    """

    receipt_id: str
    provider_identity: str
    evidence_source: str
    upstream_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.receipt_id, "DeclaredProvenance.receipt_id")
        _text(self.provider_identity, "DeclaredProvenance.provider_identity")
        # A declaration with no named source is not evidence. `CL-n7ex` made a
        # resolved grant refuse construction without one; a provenance claim
        # that could be created empty reintroduces that hole one layer up.
        _text(self.evidence_source, "DeclaredProvenance.evidence_source")


def attribute_by_digest(
    projection: LegacyProjection,
    *,
    digest_index: Mapping[str, tuple[str, str]],
) -> ProvenanceAttribution:
    """Attribute one projection by content digest, and by nothing else.

    The function takes no name, so there is no parameter through which a caller
    could reintroduce name matching. That is deliberate: the ADR's own survey
    matched names and then drew a rights conclusion from it, and this signature
    is what makes that mistake unavailable rather than discouraged.
    """
    matched = digest_index.get(projection.content_digest)
    if matched is None:
        return ProvenanceAttribution(
            state="unattributed", evidence_source=_NO_DIGEST_MATCH
        )
    provider_identity, upstream_id = matched
    return ProvenanceAttribution(
        state="attributed",
        evidence_source=(
            f"normalized content digest {projection.content_digest} matches "
            f"{provider_identity}#{upstream_id}"
        ),
        provider_identity=provider_identity,
        upstream_id=upstream_id,
    )


@dataclass(frozen=True)
class ProjectionClassification:
    """One projection's redistribution state, receipt state, and disposition."""

    projection: LegacyProjection
    attribution: ProvenanceAttribution
    redistribution_state: str
    redistribution_evidence: str
    receipt_status: str
    compliance: str
    pending_reason: str | None
    remediation: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.compliance not in COMPLIANCE_STATES:
            raise ValueError(f"unknown compliance state: {self.compliance!r}")
        if self.receipt_status not in RECEIPT_STATES:
            raise ValueError(f"unknown receipt status: {self.receipt_status!r}")
        if self.redistribution_state not in ("granted", "denied", "unknown"):
            raise ValueError(
                f"unknown redistribution state: {self.redistribution_state!r}"
            )
        object.__setattr__(self, "remediation", tuple(self.remediation))

    def blocks_rematerialization(self) -> bool:
        """Whether any later sync or repair must refuse to write this projection."""
        return self.compliance == "non-compliant"

    def replace_projection(
        self, projection: LegacyProjection
    ) -> "ProjectionClassification":
        """The same disposition, applied to another materialized path.

        One classified set of bytes can be installed at more than one path -- a
        repair target and the projection an operator sees are two of them -- and
        the disposition follows the bytes, not the location.
        """
        return replace(self, projection=projection)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.projection.to_dict(),
            "provenance_state": self.attribution.state,
            "provenance_evidence": self.attribution.evidence_source,
            "provider_identity": self.attribution.provider_identity,
            "upstream_id": self.attribution.upstream_id,
            "redistribution_state": self.redistribution_state,
            "redistribution_evidence": self.redistribution_evidence,
            "receipt_status": self.receipt_status,
            "compliance": self.compliance,
            "pending_reason": self.pending_reason,
            "remediation": list(self.remediation),
        }


def classify_projection(
    projection: LegacyProjection,
    *,
    attribution: ProvenanceAttribution,
    rights_for: Callable[[str], Rights | None],
    receipt_status: str,
    declared: DeclaredProvenance | None = None,
) -> ProjectionClassification:
    """Resolve one projection's redistribution state and its disposition.

    `unattributed` resolves to `unknown`, and `unknown` is non-compliant. That
    is the correction routed from the `CL-2p73` review: the present state of the
    inventoried projections is unresolved, not clean, and treating an
    unattributed projection as compliant would be the permissive reading of
    `unknown` that Invariant 13 exists to forbid.

    A digest match outranks a lock receipt's declaration. A receipt states what
    the Library believes it installed; a digest states what is actually there,
    and when the two disagree the bytes decide -- otherwise a receipt would keep
    vouching for content replaced underneath it.
    """
    if receipt_status not in RECEIPT_STATES:
        raise ValueError(f"unknown receipt status: {receipt_status!r}")

    if attribution.state == "unattributed" and declared is not None:
        attribution = ProvenanceAttribution(
            state="receipt-declared",
            evidence_source=declared.evidence_source,
            provider_identity=declared.provider_identity,
            upstream_id=declared.upstream_id or declared.receipt_id,
        )

    if attribution.state == "unattributed":
        return ProjectionClassification(
            projection=projection,
            attribution=attribution,
            redistribution_state="unknown",
            redistribution_evidence=attribution.evidence_source,
            receipt_status=receipt_status,
            compliance="non-compliant",
            pending_reason=PENDING_DIGEST_ATTRIBUTION,
            remediation=REMEDIATION_PATHS,
        )

    rights = rights_for(str(attribution.provider_identity))
    if rights is None:
        return ProjectionClassification(
            projection=projection,
            attribution=attribution,
            redistribution_state="unknown",
            redistribution_evidence=(
                f"no rights are recorded for {attribution.provider_identity!r}; "
                "discovery is not permission"
            ),
            receipt_status=receipt_status,
            compliance="non-compliant",
            pending_reason=None,
            remediation=REMEDIATION_PATHS,
        )

    grant = rights.grant("redistribution_rights")
    compliant = grant.state == "granted"
    return ProjectionClassification(
        projection=projection,
        attribution=attribution,
        redistribution_state=grant.state,
        redistribution_evidence=(
            grant.evidence_source or rights.evidence_source or "none recorded"
        ),
        receipt_status=receipt_status,
        compliance="compliant" if compliant else "non-compliant",
        pending_reason=None,
        remediation=() if compliant else REMEDIATION_PATHS,
    )


def receipt_index_for(stores: Sequence[ReceiptStore]) -> dict[str, str]:
    """Every path an active receipt claims, mapped to that receipt's id.

    Planned targets count. A receipt that crashed between declaring its targets
    and finalizing them still describes the paths it is responsible for, and
    reporting those paths as unreceipted would recreate the unattributable state
    on the recovery path.
    """
    index: dict[str, str] = {}
    for store in stores:
        for receipt in store.all():
            for target in receipt.targets:
                index[target.path] = receipt.id
            for path in receipt.planned_targets:
                index.setdefault(path, receipt.id)
    return index


def classify_inventory(
    projections: Sequence[LegacyProjection],
    *,
    digest_index: Mapping[str, tuple[str, str]],
    rights_for: Callable[[str], Rights | None],
    receipt_index: Mapping[str, str],
    declared_provenance: Mapping[str, DeclaredProvenance] | None = None,
) -> tuple[ProjectionClassification, ...]:
    """Classify a whole inventory: digest attribution, rights, receipt status."""
    declarations = dict(declared_provenance or {})
    classified: list[ProjectionClassification] = []
    for projection in projections:
        receipted = any(claim in receipt_index for claim in projection.claims())
        declared = next(
            (declarations[claim] for claim in projection.claims() if claim in declarations),
            None,
        )
        classified.append(
            classify_projection(
                projection,
                attribution=attribute_by_digest(projection, digest_index=digest_index),
                rights_for=rights_for,
                receipt_status="receipted" if receipted else "unreceipted",
                declared=declared,
            )
        )
    return tuple(classified)


def inventory_document(
    classifications: Sequence[ProjectionClassification], *, observed_at: str
) -> dict[str, Any]:
    """The AC5 inventory, derived from the classification rather than written.

    A hand-maintained inventory drifts from the machine it describes, and the
    ADR's own name-matched survey is the worked example of what that costs.
    """
    _text(observed_at, "observed_at")
    entries = [item.to_dict() for item in classifications]
    return {
        "schema": INVENTORY_SCHEMA,
        "observed_at": observed_at,
        "counts": {
            "total": len(entries),
            "compliant": sum(1 for item in entries if item["compliance"] == "compliant"),
            "non_compliant": sum(
                1 for item in entries if item["compliance"] == "non-compliant"
            ),
            "receipted": sum(
                1 for item in entries if item["receipt_status"] == "receipted"
            ),
            "unreceipted": sum(
                1 for item in entries if item["receipt_status"] == "unreceipted"
            ),
            "attributed": sum(
                1 for item in entries if item["provenance_state"] == "attributed"
            ),
            "unattributed": sum(
                1 for item in entries if item["provenance_state"] == "unattributed"
            ),
        },
        "entries": entries,
    }


# -- the re-materialization block ------------------------------------------------


@dataclass(frozen=True)
class BlockedProjection:
    """One non-compliant projection, and why writing it is refused."""

    path: str
    name: str
    content_digest: str
    redistribution_state: str
    reason: str
    recorded_at: str
    remediation: tuple[str, ...] = REMEDIATION_PATHS

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "content_digest": self.content_digest,
            "redistribution_state": self.redistribution_state,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
            "remediation": list(self.remediation),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BlockedProjection":
        return cls(
            path=data["path"],
            name=data["name"],
            content_digest=data["content_digest"],
            redistribution_state=data["redistribution_state"],
            reason=data["reason"],
            recorded_at=data["recorded_at"],
            remediation=tuple(data.get("remediation") or REMEDIATION_PATHS),
        )


class NonComplianceRegister:
    """Durable record of the projections no sync or repair may write.

    The store fails closed on damage. `payload.get("entries") or []` would read
    a corrupt register as "nothing is blocked", which silently restores
    re-materialization for every non-compliant projection -- the one failure
    this register exists to prevent. `CL-uliw` found the identical defect in the
    receipt store, where a `null` receipts list authorized a deletion.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, BlockedProjection]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping) or payload.get("schema") != NON_COMPLIANCE_SCHEMA:
            raise ValueError(
                f"unexpected non-compliance register schema: {payload.get('schema')!r}"
                if isinstance(payload, Mapping)
                else "a non-compliance register is a mapping"
            )
        records = payload.get("entries", [])
        if not isinstance(records, list) or not all(
            isinstance(record, Mapping) for record in records
        ):
            raise ValueError(
                "the non-compliance register's entries must be a list of records; a "
                "damaged register is never read as an empty one, because an empty "
                "one re-permits every blocked projection"
            )
        return {record["path"]: BlockedProjection.from_dict(record) for record in records}

    def record(
        self, classification: ProjectionClassification, *, recorded_at: str
    ) -> BlockedProjection:
        """Register one non-compliant classification. Compliant ones are refused."""
        _text(recorded_at, "recorded_at")
        if not classification.blocks_rematerialization():
            raise ValueError(
                "only a non-compliant projection is registered; recording a "
                "compliant one would make the register indistinguishable from a "
                "list of everything installed"
            )
        entry = BlockedProjection(
            path=classification.projection.path,
            name=classification.projection.name,
            content_digest=classification.projection.content_digest,
            redistribution_state=classification.redistribution_state,
            reason=classification.pending_reason or classification.redistribution_evidence,
            recorded_at=recorded_at,
            remediation=classification.remediation,
        )
        entries = self._load()
        entries[entry.path] = entry
        self._save(entries)
        return entry

    def _save(self, entries: Mapping[str, BlockedProjection]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.path,
            json.dumps(
                {
                    "schema": NON_COMPLIANCE_SCHEMA,
                    "entries": [entries[key].to_dict() for key in sorted(entries)],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    def blocked(self) -> tuple[BlockedProjection, ...]:
        entries = self._load()
        return tuple(entries[key] for key in sorted(entries))

    def matches(
        self, *, paths: Sequence[str] = (), digest: str | None = None
    ) -> tuple[BlockedProjection, ...]:
        """Every registered block one write would collide with.

        A registered path matches its own value **and any path beneath it**: a
        blocked directory whose members would be rewritten member by member is
        the same act as rewriting the directory, and matching only exact strings
        would let it through.
        """
        wanted = [Path(item) for item in paths]
        found: list[BlockedProjection] = []
        for entry in self.blocked():
            registered = Path(entry.path)
            if digest is not None and entry.content_digest == digest:
                found.append(entry)
                continue
            for candidate in wanted:
                if candidate == registered or _is_within(candidate, registered) or _is_within(
                    registered, candidate
                ):
                    found.append(entry)
                    break
        return tuple(found)

    def is_blocked(self, *, path: str | None = None, digest: str | None = None) -> bool:
        return bool(
            self.matches(paths=[path] if path is not None else [], digest=digest)
        )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def guard_rematerialization(
    register: NonComplianceRegister | None,
    *,
    paths: Sequence[str] = (),
    digest: str | None = None,
) -> None:
    """Refuse to write anything a non-compliance register blocks.

    Raises:
        RematerializationBlocked: naming the projection, its redistribution
            state, and its remediation paths, because a refusal an operator
            cannot act on is an outage.
    """
    if register is None:
        return
    hits = register.matches(paths=paths, digest=digest)
    if not hits:
        return
    detail = "; ".join(
        f"{entry.path} (redistribution: {entry.redistribution_state}; {entry.reason})"
        for entry in hits
    )
    raise RematerializationBlocked(
        "this projection is recorded non-compliant and may not be re-materialized "
        f"by sync or repair: {detail}. Remediate it explicitly -- "
        f"{', or '.join(REMEDIATION_PATHS)} -- neither of which runs on its own."
    )


# -- remediation ------------------------------------------------------------------


@dataclass(frozen=True)
class RemediationOption:
    """One named way out, and whether taking it destroys bytes."""

    path_id: str
    description: str
    destructive: bool


_OPTIONS: tuple[RemediationOption, ...] = (
    RemediationOption(
        path_id="operator-confirmed-removal",
        description=(
            "remove this projection from the harness path. The bytes are gone and "
            "may not be re-fetchable"
        ),
        destructive=True,
    ),
    RemediationOption(
        path_id="relocate-machine-local",
        description=(
            "move this projection to an allowed machine-local location, where an "
            "unresolved redistribution state does not put it into a tree others "
            "receive"
        ),
        destructive=False,
    ),
)


@dataclass(frozen=True)
class RemediationConfirmation:
    """An operator's acceptance of exactly one presented remediation statement."""

    token: str
    statement_digest: str
    subject: str
    choice: str
    operator: str
    confirmed_at: str

    def __post_init__(self) -> None:
        for name in (
            "token",
            "statement_digest",
            "subject",
            "choice",
            "operator",
            "confirmed_at",
        ):
            _text(getattr(self, name), f"RemediationConfirmation.{name}")
        if self.choice not in REMEDIATION_PATHS:
            raise ValueError(f"unknown remediation path: {self.choice!r}")


@dataclass(frozen=True)
class RemediationPresentation:
    """A rendered remediation statement, issued here and good exactly once.

    The token cannot be guessed and cannot be obtained without this module
    having rendered `statement`, which is what turns "shown before mutation"
    from a convention into a fact. It is the shape `CL-n7ex` reached after
    review broke a boolean flag and then broke a digest-only token.
    """

    statement: str
    statement_digest: str
    subject: str
    token: str

    def confirm(
        self, *, operator: str, choice: str, confirmed_at: str
    ) -> RemediationConfirmation:
        return RemediationConfirmation(
            token=self.token,
            statement_digest=self.statement_digest,
            subject=self.subject,
            choice=choice,
            operator=operator,
            confirmed_at=confirmed_at,
        )


@dataclass(frozen=True)
class RemediationPlan:
    """What may be done about one non-compliant projection, and by whom."""

    subject: str
    name: str
    content_digest: str
    redistribution_state: str
    pending_reason: str | None
    options: tuple[RemediationOption, ...]
    statement: str

    def statement_digest(self) -> str:
        return hashlib.sha256(self.statement.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RemediationOutcome:
    """What one confirmed remediation actually did."""

    choice: str
    subject: str
    operator: str
    confirmed_at: str
    destination: str | None = None
    removed: tuple[str, ...] = ()


def plan_remediation(classification: ProjectionClassification) -> RemediationPlan:
    """The explicit remediation paths for one non-compliant projection.

    Raises:
        ValueError: for a compliant projection. Offering a removal path for
            content nothing is wrong with is how a safety mechanism becomes a
            tidy-up button.
    """
    if not classification.blocks_rematerialization():
        raise ValueError(
            "a compliant projection has nothing to remediate; there is no path "
            "from this module to removing content that is not in question"
        )
    projection = classification.projection
    lines = [
        f"subject: {projection.path}",
        f"content digest: {projection.content_digest}",
        f"redistribution rights: {classification.redistribution_state}",
        f"evidence source: {classification.redistribution_evidence}",
    ]
    if classification.pending_reason:
        lines.append(f"state: {classification.pending_reason}")
    lines.append(
        "this projection is retained and is blocked from re-materialization. "
        "Choose one remediation path:"
    )
    lines.extend(
        f"  {option.path_id}: {option.description}"
        + ("  [destroys bytes]" if option.destructive else "")
        for option in _OPTIONS
    )
    return RemediationPlan(
        subject=projection.path,
        name=projection.name,
        content_digest=projection.content_digest,
        redistribution_state=classification.redistribution_state,
        pending_reason=classification.pending_reason,
        options=_OPTIONS,
        statement="\n".join(lines),
    )


def apply_remediation(
    plan: RemediationPlan,
    *,
    choice: str,
    confirm: Callable[[RemediationPresentation], RemediationConfirmation] | None,
    relocate_root: Path | None = None,
) -> RemediationOutcome:
    """Perform one remediation, or refuse it. There is no automatic path.

    Args:
        confirm: Receives the rendered presentation and returns the operator's
            confirmation of it. This is the **only** way to authorize either
            path. A non-interactive policy flow supplies a confirmer that records
            the statement and confirms it; it still cannot confirm something it
            was not given.

    Raises:
        RemediationRefused: with no confirmer, with a confirmation that is not
            one of ours, with one that belongs to an earlier presentation, and
            with one whose choice, subject, or statement does not match.
    """
    if choice not in REMEDIATION_PATHS:
        raise RemediationRefused(f"unknown remediation path: {choice!r}")
    if confirm is None:
        raise RemediationRefused(
            f"{choice} requires an explicit operator confirmation of the displayed "
            "remediation statement. Supply a confirmer; a confirmation cannot "
            "exist without one, and nothing is removed or moved without it."
        )

    presentation = RemediationPresentation(
        statement=plan.statement,
        statement_digest=plan.statement_digest(),
        subject=plan.subject,
        # Fresh per call, so a confirmation authorizes exactly one act. A
        # replayed confirmation carries an earlier token and is refused.
        token=secrets.token_hex(16),
    )
    confirmation = confirm(presentation)
    if not isinstance(confirmation, RemediationConfirmation):
        raise RemediationRefused(
            "a remediation confirmation must be a RemediationConfirmation issued "
            "from the presented statement"
        )
    if confirmation.token != presentation.token:
        raise RemediationRefused(
            "the confirmation does not belong to the statement that was just "
            "presented, so it authorizes nothing"
        )
    if confirmation.statement_digest != presentation.statement_digest:
        raise RemediationRefused(
            "the operator confirmed a different statement than this plan displays"
        )
    if confirmation.subject != plan.subject:
        raise RemediationRefused(
            f"the confirmation names {confirmation.subject!r}, not {plan.subject!r}; "
            "one confirmation never covers a projection the operator did not see"
        )
    if confirmation.choice != choice:
        raise RemediationRefused(
            f"the operator confirmed {confirmation.choice!r}, not {choice!r}"
        )

    subject = Path(plan.subject)
    if choice == "relocate-machine-local":
        if relocate_root is None:
            raise RemediationRefused(
                "relocation needs the machine-local root to move this projection "
                "into; the destination is operator policy and has no default"
            )
        destination = Path(relocate_root) / plan.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(subject), str(destination))
        return RemediationOutcome(
            choice=choice,
            subject=plan.subject,
            operator=confirmation.operator,
            confirmed_at=confirmation.confirmed_at,
            destination=str(destination),
        )

    if subject.is_symlink() or subject.is_file():
        subject.unlink()
    elif subject.is_dir():
        shutil.rmtree(subject)
    return RemediationOutcome(
        choice=choice,
        subject=plan.subject,
        operator=confirmation.operator,
        confirmed_at=confirmation.confirmed_at,
        removed=(plan.subject,),
    )


# -- receipt backfill --------------------------------------------------------------


@dataclass(frozen=True)
class ReceiptBackfillRequest:
    """One unreceipted projection, and the catalog content that will receipt it."""

    projection: LegacyProjection
    content: Mapping[str, bytes]
    provider_identity: str
    library_type: str
    rights: Rights
    #: A backfill writes a receipt for content the catalog serves. It selects no
    #: executor and changes none: ADR-0006 keeps Workflow executor authority, and
    #: this is a checked field rather than a sentence in a docstring.
    preserves_executor_authority: bool = True
    executor_authority: str = EXECUTOR_AUTHORITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", dict(self.content))
        if not self.content:
            raise ValueError(
                "a backfill needs catalog content; a receipt written without a "
                "source reproduces nothing and restates the defect as a document"
            )
        if self.preserves_executor_authority is not True:
            raise ValueError("a receipt backfill never changes executor authority")


@dataclass(frozen=True)
class ReceiptBackfillOutcome:
    """Which projections gained a receipt, and the authority that did not move."""

    receipted: tuple[str, ...]
    outcomes: tuple[InstallOutcome, ...] = ()
    executor_authority_changed: bool = False


def plan_receipt_backfill(
    projections: Sequence[LegacyProjection],
    *,
    catalog_lookup: Callable[[LegacyProjection], Mapping[str, bytes] | None],
    provider_identity: str,
    library_type: str,
    rights: Rights,
) -> tuple[ReceiptBackfillRequest, ...]:
    """Plan a receipt for every projection the catalog can actually reproduce.

    A projection the catalog does not know is skipped, not adopted. Adoption
    would record whatever is on disk as authoritative, and the whole reason
    these projections are a defect is that nobody can say what produced the
    bytes on disk.
    """
    requests: list[ReceiptBackfillRequest] = []
    for projection in projections:
        content = catalog_lookup(projection)
        if not content:
            continue
        requests.append(
            ReceiptBackfillRequest(
                projection=projection,
                content=content,
                provider_identity=provider_identity,
                library_type=library_type,
                rights=rights,
            )
        )
    return tuple(sorted(requests, key=lambda item: item.projection.name))


def _backfill_item(
    request: ReceiptBackfillRequest, *, observed_at: str
) -> NormalizedItem:
    return NormalizedItem(
        provider_identity=request.provider_identity,
        upstream_id=f"{request.library_type}/{request.projection.name}",
        upstream_name=request.projection.name,
        collection_membership=(request.library_type,),
        upstream_revision=None,
        library_type=request.library_type,
        library_name=request.projection.name,
        classification={"origin": "first-party-catalog"},
        runtime_compatibility=("claude-code",),
        rights=request.rights,
        provider_availability=ProviderAvailability(
            state="available",
            observed_at=observed_at,
            reason="first-party catalog content is served locally",
        ),
        admission_state="installable",
        trust_state="first-party",
        projection_eligibility={
            "project_committed": "allowed",
            "machine_local": "allowed",
        },
    )


def apply_receipt_backfill(
    requests: Sequence[ReceiptBackfillRequest],
    *,
    state: Any,
    scope: str,
    target_root: Path,
    observed_at: str,
    receipt_store: ReceiptStore | None = None,
    non_compliance: NonComplianceRegister | None = None,
) -> ReceiptBackfillOutcome:
    """Re-materialize each planned projection so a receipt exists for it.

    The ordered install transaction is reused unchanged, so the receipt is
    written before the projection is activated. A failure while writing the
    receipt therefore leaves the previous bytes in place rather than an active
    projection nothing describes -- which is the exact state these four
    projections are in today.
    """
    _text(observed_at, "observed_at")
    from .wiring import filesystem_activation  # local: wiring imports this module

    store = receipt_store if receipt_store is not None else state.receipt_store(scope)
    receipted: list[str] = []
    outcomes: list[InstallOutcome] = []
    for request in requests:
        item = _backfill_item(request, observed_at=observed_at)
        content = dict(request.content)
        guard_rematerialization(
            non_compliance,
            paths=[str(Path(target_root) / member) for member in sorted(content)],
            digest=normalized_content_digest(content),
        )
        outcome = install_foreign_item(
            item,
            retrieve=lambda captured=content, captured_item=item: FetchedItem(
                upstream_id=captured_item.upstream_id,
                revision=None,
                files=tuple(
                    FetchedFile(path=path, content=payload)
                    for path, payload in sorted(captured.items())
                ),
                primary_path=sorted(captured)[0],
            ),
            object_store=state.object_store(),
            pin_store=state.pin_store(),
            receipt_store=store,
            target="machine_local",
            activate=filesystem_activation(
                Path(target_root), non_compliance=non_compliance
            ),
            observed_at=observed_at,
            completeness=CompletenessEvidence.from_manifest(
                sorted(content),
                detail="first-party catalog entry declares this item's members",
            ),
        )
        outcomes.append(outcome)
        receipted.append(request.projection.name)
    return ReceiptBackfillOutcome(
        receipted=tuple(sorted(receipted)),
        outcomes=tuple(outcomes),
        executor_authority_changed=False,
    )


__all__ = [
    "COMPLIANCE_STATES",
    "EXECUTOR_AUTHORITY",
    "INVENTORY_SCHEMA",
    "NON_COMPLIANCE_SCHEMA",
    "PENDING_DIGEST_ATTRIBUTION",
    "PROVENANCE_STATES",
    "RECEIPT_STATES",
    "REMEDIATION_PATHS",
    "BlockedProjection",
    "DeclaredProvenance",
    "LegacyProjection",
    "NonComplianceRegister",
    "ProjectionClassification",
    "ProvenanceAttribution",
    "ReceiptBackfillOutcome",
    "ReceiptBackfillRequest",
    "RematerializationBlocked",
    "RemediationConfirmation",
    "RemediationOption",
    "RemediationOutcome",
    "RemediationPlan",
    "RemediationPresentation",
    "RemediationRefused",
    "apply_receipt_backfill",
    "apply_remediation",
    "attribute_by_digest",
    "classify_inventory",
    "classify_projection",
    "guard_rematerialization",
    "inventory_document",
    "plan_receipt_backfill",
    "plan_remediation",
    "receipt_index_for",
    "scan_projection",
    "scan_projections",
]
