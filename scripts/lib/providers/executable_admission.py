"""Digest-bound executable admission (ADR-0011 `Executable admission`).

Discovery is non-executing, and selection into a Workspace is not permission to
run. An externally sourced executable artifact requires an explicit admission
decision by the scope operator -- never by a provider, an upstream manifest, or
a Workspace author who is not the operator of that scope.

| Element | Decision |
|---|---|
| Recorded state | Bound to the **content digest**, not to the name or version |
| Required evidence | Reviewer identity, the exact reviewed digest, and the declared permission surface |
| Invalidation | Any digest change returns the item to `pending`; re-admission is a new decision |
| Composition | A root that reaches a `pending` or `refused` executable item fails the whole resolution before mutation |

Two failure modes this shape exists to prevent, both of which look fine in a
test that only checks the happy path:

- **Name-bound admission.** Admitting "the deploy workflow" and then following
  a moved upstream reference re-runs bytes nobody reviewed under a decision
  somebody made about different bytes. `state_for` therefore keys on
  `(identity, digest)` and returns `pending` for an unrecognized digest even
  when a record exists for the same identity.
- **Silent skipping.** Dropping an unadmitted executable and resolving the rest
  gives the operator a selection that is quietly missing a member. The gate
  raises instead, before any mutation, and never returns a filtered selection.

A missing digest is `pending`, not an implicit pass: "we could not compute what
this is" must never be more permissive than "we computed it and nobody reviewed
it".

**Digest boundary with the cache slice.** `content_digest` is the admission
binding only. Cache identity, materialization keys, and offline verification are
`CL-y5z4`; that slice may adopt this function or supersede it with a broader
cache key, and if it does, the admission binding follows the same bytes it does
today. What must not change is the *binding*: admission follows content.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .classification import EXECUTABLE_TYPES
from .inventory import EXECUTABLE_ADMISSION_STATES, NormalizedItem

DIGEST_PREFIX = "sha256:"

INERT = "inert"
ADMITTED = "admitted"
PENDING = "pending"
REFUSED = "refused"


class InertContentNotAdmissible(ValueError):
    """Inert content cannot be admitted, because it holds no executable trust.

    Refusing the call rather than recording a harmless-looking decision is what
    keeps a bundle from acquiring executable trust one inert member at a time.
    """


class ResolutionRefused(RuntimeError):
    """A resolution reached an executable item that is not admitted.

    Carries every offending item, so an operator sees the whole gap in one
    refusal instead of discovering it one re-run at a time. It deliberately
    carries **no** partial resolution: a caller that could reach for one would
    be doing exactly the silent skip this gate forbids.
    """

    def __init__(self, refusals: Sequence[tuple[str, str]]) -> None:
        rendered = ", ".join(f"{identity} ({state})" for identity, state in refusals)
        super().__init__(
            "resolution failed before any mutation: executable admission is not "
            f"granted for {rendered}"
        )
        self.refusals = tuple(refusals)


def content_digest(files: Mapping[str, bytes]) -> str:
    """The normalized content digest of one item's complete content.

    Every path and every byte is covered, and both are length-framed, so moving
    a byte across the path/content boundary or across two files changes the
    digest. Without framing, `{"ab": b"", "c": b"x"}` and `{"a": b"", "bc":
    b"x"}` would hash identically, and an item could be rearranged into a
    previously admitted digest.

    Args:
        files: Item-relative path to content, as a complete item.

    Returns:
        `sha256:<hex>`.

    Raises:
        ValueError: when the item has no files. An empty item has no content to
            bind a decision to, and treating it as a stable digest would let
            "nothing" be admitted once and reused.
    """
    if not files:
        raise ValueError("an item with no files has no content digest to bind")
    digest = hashlib.sha256()
    for path in sorted(files):
        content = files[path]
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError(f"content for {path!r} must be bytes")
        encoded_path = path.encode("utf-8")
        digest.update(str(len(encoded_path)).encode("ascii") + b":" + encoded_path)
        digest.update(str(len(content)).encode("ascii") + b":" + bytes(content))
    return f"{DIGEST_PREFIX}{digest.hexdigest()}"


def is_executable_type(library_type: str) -> bool:
    """Whether this Library type requires an executable-admission decision."""
    return library_type in EXECUTABLE_TYPES


@dataclass(frozen=True)
class AdmissionRecord:
    """One executable-admission decision, bound to the bytes it was made about."""

    qualified_identity: str
    content_digest: str
    state: str
    reviewer: str
    permission_surface: tuple[str, ...]
    decided_at: str
    evidence: str

    def __post_init__(self) -> None:
        if self.state not in (ADMITTED, REFUSED):
            raise ValueError("an admission record is either admitted or refused")
        for name in ("qualified_identity", "content_digest", "reviewer", "decided_at", "evidence"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"AdmissionRecord.{name} is required")
        if not self.content_digest.startswith(DIGEST_PREFIX):
            raise ValueError(
                f"AdmissionRecord.content_digest must be a {DIGEST_PREFIX} digest"
            )
        object.__setattr__(self, "permission_surface", tuple(self.permission_surface))

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualified_identity": self.qualified_identity,
            "content_digest": self.content_digest,
            "state": self.state,
            "reviewer": self.reviewer,
            "permission_surface": list(self.permission_surface),
            "decided_at": self.decided_at,
            "evidence": self.evidence,
        }


class ExecutableAdmissionLedger:
    """Executable-admission decisions, keyed by identity **and** content digest."""

    def __init__(self, records: Iterable[AdmissionRecord] = ()) -> None:
        self._records: dict[tuple[str, str], AdmissionRecord] = {}
        for record in records:
            self._store(record)

    def _store(self, record: AdmissionRecord, *, supersedes: bool = False) -> AdmissionRecord:
        key = (record.qualified_identity, record.content_digest)
        existing = self._records.get(key)
        if existing is not None and existing.state != record.state and not supersedes:
            raise ValueError(
                f"{record.qualified_identity} at {record.content_digest} is already "
                f"recorded as {existing.state}; reversing that decision is an "
                "explicit act (pass supersedes=True), never an overwrite"
            )
        self._records[key] = record
        return record

    def _decide(
        self,
        state: str,
        qualified_identity: str,
        content_digest_value: str,
        *,
        library_type: str,
        reviewer: str,
        permission_surface: Sequence[str],
        decided_at: str,
        evidence: str,
        supersedes: bool = False,
    ) -> AdmissionRecord:
        if not is_executable_type(library_type):
            raise InertContentNotAdmissible(
                f"{qualified_identity} is {library_type!r}, which is inert; inert "
                "content holds no executable trust to grant or withhold"
            )
        return self._store(
            AdmissionRecord(
                qualified_identity=qualified_identity,
                content_digest=content_digest_value,
                state=state,
                reviewer=reviewer,
                permission_surface=tuple(permission_surface),
                decided_at=decided_at,
                evidence=evidence,
            ),
            supersedes=supersedes,
        )

    def admit(
        self,
        qualified_identity: str,
        content_digest_value: str,
        *,
        library_type: str,
        reviewer: str,
        permission_surface: Sequence[str],
        decided_at: str,
        evidence: str,
        supersedes: bool = False,
    ) -> AdmissionRecord:
        """Admit exactly these bytes, on recorded reviewer evidence.

        Args:
            supersedes: Reverse a recorded refusal for these exact bytes. An
                operator may change their mind, but not by accident: the
                default refuses, so a repeated `admit` in an automated path
                cannot quietly undo a refusal somebody made deliberately.

        Raises:
            InertContentNotAdmissible: for a non-executable type.
            ValueError: when these bytes are recorded as refused and
                `supersedes` is not set.
        """
        return self._decide(
            ADMITTED,
            qualified_identity,
            content_digest_value,
            library_type=library_type,
            reviewer=reviewer,
            permission_surface=permission_surface,
            decided_at=decided_at,
            evidence=evidence,
            supersedes=supersedes,
        )

    def refuse(
        self,
        qualified_identity: str,
        content_digest_value: str,
        *,
        library_type: str,
        reviewer: str,
        permission_surface: Sequence[str] = (),
        decided_at: str,
        evidence: str,
        supersedes: bool = False,
    ) -> AdmissionRecord:
        """Refuse exactly these bytes, on recorded reviewer evidence."""
        return self._decide(
            REFUSED,
            qualified_identity,
            content_digest_value,
            library_type=library_type,
            reviewer=reviewer,
            permission_surface=permission_surface,
            decided_at=decided_at,
            evidence=evidence,
            supersedes=supersedes,
        )

    def record_for(
        self, qualified_identity: str, content_digest_value: str
    ) -> AdmissionRecord | None:
        """The decision recorded for exactly these bytes, if there is one."""
        return self._records.get((qualified_identity, content_digest_value))

    def records(self) -> tuple[AdmissionRecord, ...]:
        return tuple(self._records.values())

    def state_for(
        self,
        qualified_identity: str,
        content_digest_value: str | None,
        *,
        library_type: str,
    ) -> str:
        """The `executable_admission` state for one item at one content digest.

        Inert types short-circuit before the ledger is consulted at all, so no
        record, sibling, collection, or provider can lend them executable trust.
        """
        if not is_executable_type(library_type):
            return INERT
        if not content_digest_value:
            return PENDING
        record = self.record_for(qualified_identity, content_digest_value)
        if record is None:
            return PENDING
        return record.state


def executable_admission_for_item(
    item: NormalizedItem,
    ledger: ExecutableAdmissionLedger,
    digests: Mapping[str, str],
) -> str:
    """The admission state for one normalized item under one ledger."""
    return ledger.state_for(
        item.qualified_identity(),
        digests.get(item.qualified_identity()),
        library_type=item.library_type,
    )


def gate_resolution(
    items: Sequence[NormalizedItem],
    ledger: ExecutableAdmissionLedger,
    digests: Mapping[str, str],
    *,
    mutate: Callable[[], Any] | None = None,
) -> tuple[NormalizedItem, ...]:
    """Resolve a selection only when every executable member is admitted.

    Args:
        items: The selected items, in resolution order.
        ledger: The scope operator's admission decisions.
        digests: Qualified identity to content digest for the resolved content.
        mutate: The callable that writes. Called once, after the gate passes.

    Returns:
        The items with their evaluated `executable_admission` state.

    Raises:
        ResolutionRefused: when any executable member is `pending` or `refused`.
            Raised before `mutate` runs, and no member is resolved.
    """
    states = [(item, executable_admission_for_item(item, ledger, digests)) for item in items]
    refusals = [
        (item.qualified_identity(), state)
        for item, state in states
        if state in (PENDING, REFUSED)
    ]
    if refusals:
        raise ResolutionRefused(refusals)

    resolved = tuple(
        item if item.executable_admission == state else _with_admission(item, state)
        for item, state in states
    )
    if mutate is not None:
        mutate()
    return resolved


def _with_admission(item: NormalizedItem, state: str) -> NormalizedItem:
    if state not in EXECUTABLE_ADMISSION_STATES:
        raise ValueError(f"unknown executable admission state: {state!r}")
    payload = item.to_dict()
    payload["executable_admission"] = state
    return NormalizedItem.from_dict(payload)
