"""Digest-bound executable admission (CL-n7ex AC5, AC6).

ADR-0011 `Executable admission`: discovery is non-executing and selection into a
Workspace is not permission to run. Admission is recorded against the **content
digest**, never the name or version, so replaced content cannot inherit the
decision made about the bytes somebody actually reviewed.

A root that reaches a `pending` or `refused` executable item fails the whole
resolution before mutation. Silently skipping it is the failure mode this gate
exists to prevent: the operator would get a partially resolved selection and no
signal that the executable member was dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.executable_admission import (  # noqa: E402
    ExecutableAdmissionLedger,
    InertContentNotAdmissible,
    ResolutionRefused,
    content_digest,
    gate_resolution,
    validated_digest,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)

PROVIDER = "provider-under-test"
GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source="upstream LICENSE (MIT), verified 2026-08-08",
)


def _item(upstream_id: str, library_type: str, **overrides: object) -> NormalizedItem:
    base = dict(
        provider_identity=PROVIDER,
        upstream_id=upstream_id,
        upstream_name=upstream_id.rsplit("/", 1)[-1],
        collection_membership=("bundle",),
        upstream_revision=None,
        library_type=library_type,
        library_name=upstream_id.rsplit("/", 1)[-1],
        classification={"type_basis": "marker-file"},
        runtime_compatibility=("unknown",),
        rights=GRANTED,
        provider_availability=ProviderAvailability(
            state="available", observed_at="2026-08-09T09:00:00Z"
        ),
        executable_admission="pending" if library_type == "workflow" else "inert",
    )
    base.update(overrides)
    return NormalizedItem(**base)  # type: ignore[arg-type]


def _admit(ledger: ExecutableAdmissionLedger, identity: str, digest: str) -> None:
    ledger.admit(
        identity,
        digest,
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=("filesystem:write", "network:none"),
        decided_at="2026-08-09T09:00:00Z",
        evidence="reviewed the workflow body and its declared permission surface",
    )


# -- AC5: admission is bound to the normalized content digest ----------------


def test_digest_change_returns_pending() -> None:
    """Changing the content returns the item to `pending`, evidence and all."""
    ledger = ExecutableAdmissionLedger()
    identity = f"{PROVIDER}#flows/deploy"
    original = {"WORKFLOW.md": b"steps: one\n", "lib/run.py": b"print('one')\n"}
    digest = content_digest(original)

    assert ledger.state_for(identity, digest, library_type="workflow") == "pending"

    record = ledger.admit(
        identity,
        digest,
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=("filesystem:write",),
        decided_at="2026-08-09T09:00:00Z",
        evidence="reviewed the workflow body",
    )
    assert record.content_digest == digest
    assert record.reviewer == "malte.sussdorff@cognovis.de"
    assert record.permission_surface == ("filesystem:write",)
    assert ledger.state_for(identity, digest, library_type="workflow") == "admitted"

    # One byte of the non-marker file is enough. Admission follows the bytes.
    changed = {"WORKFLOW.md": b"steps: one\n", "lib/run.py": b"print('two')\n"}
    changed_digest = content_digest(changed)
    assert changed_digest != digest
    assert ledger.state_for(identity, changed_digest, library_type="workflow") == "pending"

    # The original decision is retained; re-admission is a new decision.
    assert ledger.state_for(identity, digest, library_type="workflow") == "admitted"
    assert ledger.record_for(identity, changed_digest) is None

    # Neither the name nor the version carries the decision.
    other = f"{PROVIDER}#flows/deploy-v2"
    assert ledger.state_for(other, digest, library_type="workflow") == "pending"


def test_content_digest_is_order_and_boundary_stable() -> None:
    """Path order does not change the digest; moving a byte across files does."""
    assert content_digest({"a": b"1", "b": b"2"}) == content_digest({"b": b"2", "a": b"1"})
    assert content_digest({"ab": b"", "c": b"x"}) != content_digest({"a": b"", "bc": b"x"})
    assert content_digest({"a": b"12", "b": b""}) != content_digest({"a": b"1", "b": b"2"})
    assert content_digest({"a": b"x"}).startswith("sha256:")

    with pytest.raises(ValueError):
        content_digest({})


def test_a_digest_shaped_string_is_not_a_digest() -> None:
    """Only the exact form is a content identity; a prefix is not enough."""
    assert validated_digest(content_digest({"a": b"x"}))

    for value in ("sha256:not-a-digest", "sha256:" + "F" * 64, "deadbeef", ""):
        with pytest.raises(ValueError):
            validated_digest(value)

    ledger = ExecutableAdmissionLedger()
    with pytest.raises(ValueError):
        ledger.admit(
            f"{PROVIDER}#flows/deploy",
            "sha256:not-a-digest",
            library_type="workflow",
            reviewer="x reviewer",
            permission_surface=(),
            decided_at="2026-08-09T09:00:00Z",
            evidence="filed against bytes that do not exist",
        )


def test_refused_admission_is_recorded_and_stays_refused() -> None:
    ledger = ExecutableAdmissionLedger()
    identity = f"{PROVIDER}#flows/deploy"
    digest = content_digest({"WORKFLOW.md": b"rm -rf /\n"})

    ledger.refuse(
        identity,
        digest,
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=("filesystem:write",),
        decided_at="2026-08-09T09:00:00Z",
        evidence="the workflow deletes outside its worktree",
    )

    assert ledger.state_for(identity, digest, library_type="workflow") == "refused"

    # A repeated admit does not quietly undo a deliberate refusal.
    with pytest.raises(ValueError):
        _admit(ledger, identity, digest)
    assert ledger.state_for(identity, digest, library_type="workflow") == "refused"

    # Reversing it is available, but only as an explicit act with its own evidence.
    ledger.admit(
        identity,
        digest,
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=("filesystem:write",),
        decided_at="2026-08-09T10:00:00Z",
        evidence="re-reviewed after the destructive command was removed upstream",
        supersedes=True,
    )
    assert ledger.state_for(identity, digest, library_type="workflow") == "admitted"


def test_a_recorded_decision_is_never_silently_rewritten() -> None:
    """The audit trail is the record: who vouched for these bytes, and why."""
    ledger = ExecutableAdmissionLedger()
    identity = f"{PROVIDER}#flows/deploy"
    digest = content_digest({"WORKFLOW.md": b"deploy\n"})
    _admit(ledger, identity, digest)

    with pytest.raises(ValueError) as refusal:
        ledger.admit(
            identity,
            digest,
            library_type="workflow",
            reviewer="somebody.else@example.com",
            permission_surface=(),
            decided_at="2026-08-09T11:00:00Z",
            evidence="rubber-stamped without reading it",
        )
    assert "already recorded" in str(refusal.value)
    assert ledger.record_for(identity, digest).reviewer == "malte.sussdorff@cognovis.de"


def test_pending_item_fails_resolution() -> None:
    """A pending or refused executable fails the whole resolution before mutation."""
    ledger = ExecutableAdmissionLedger()
    admitted_id = f"{PROVIDER}#flows/admitted"
    pending_id = f"{PROVIDER}#flows/pending"
    inert_id = f"{PROVIDER}#prompts/notes"

    contents = {
        admitted_id: {"WORKFLOW.md": b"admitted\n"},
        pending_id: {"WORKFLOW.md": b"pending\n"},
        inert_id: {"NOTES.md": b"notes\n"},
    }
    _admit(ledger, admitted_id, content_digest(contents[admitted_id]))

    selection = [
        _item("flows/admitted", "workflow"),
        _item("flows/pending", "workflow"),
        _item("prompts/notes", "prompt"),
    ]
    mutations: list[object] = []

    with pytest.raises(ResolutionRefused) as refusal:
        gate_resolution(selection, ledger, contents, mutate=mutations.append)

    assert mutations == [], "the whole resolution fails before any mutation"
    assert refusal.value.refusals == ((pending_id, "pending"),)
    assert pending_id in str(refusal.value)
    # The refusal is not a filtered selection: the admitted members are not
    # resolved either.
    assert not hasattr(refusal.value, "resolved")

    # A refused member fails the resolution in the same way a pending one does.
    refusing_ledger = ExecutableAdmissionLedger(ledger.records())
    refusing_ledger.refuse(
        pending_id,
        content_digest(contents[pending_id]),
        library_type="workflow",
        reviewer="malte.sussdorff@cognovis.de",
        permission_surface=(),
        decided_at="2026-08-09T09:00:00Z",
        evidence="not reviewed for this scope",
    )
    with pytest.raises(ResolutionRefused) as second:
        gate_resolution(selection, refusing_ledger, contents, mutate=mutations.append)
    assert second.value.refusals == ((pending_id, "refused"),)
    assert mutations == []

    # With every executable member admitted, the resolution proceeds once.
    _admit(ledger, pending_id, content_digest(contents[pending_id]))
    resolved = gate_resolution(selection, ledger, contents, mutate=mutations.append)
    assert [item.executable_admission for item in resolved] == [
        "admitted",
        "admitted",
        "inert",
    ]
    # The mutation receives the exact content the gate digested, so the reviewed
    # bytes and the materialized bytes cannot be two different things.
    assert mutations == [contents]


def test_changed_content_is_not_resolvable_under_an_old_admission() -> None:
    """The gate digests the content it will materialize, not a supplied claim."""
    ledger = ExecutableAdmissionLedger()
    identity = f"{PROVIDER}#flows/deploy"
    reviewed = {"WORKFLOW.md": b"safe steps\n"}
    _admit(ledger, identity, content_digest(reviewed))

    selection = [_item("flows/deploy", "workflow")]
    mutations: list[object] = []

    changed = {identity: {"WORKFLOW.md": b"rm -rf /\n"}}
    with pytest.raises(ResolutionRefused) as refusal:
        gate_resolution(selection, ledger, changed, mutate=mutations.append)

    assert mutations == []
    assert refusal.value.refusals == ((identity, "pending"),)

    resolved = gate_resolution(
        selection, ledger, {identity: reviewed}, mutate=mutations.append
    )
    assert [item.executable_admission for item in resolved] == ["admitted"]
    assert mutations == [{identity: reviewed}]


def test_resolution_fails_when_executable_content_is_absent() -> None:
    """Content we cannot digest is `pending`, never an implicit pass."""
    ledger = ExecutableAdmissionLedger()
    selection = [_item("flows/deploy", "workflow")]
    mutations: list[object] = []

    with pytest.raises(ResolutionRefused):
        gate_resolution(selection, ledger, {}, mutate=mutations.append)
    assert mutations == []


# -- AC6: inert content never inherits executable trust ----------------------


def test_inert_does_not_inherit() -> None:
    """Sharing a bundle, collection, or provider grants nothing."""
    ledger = ExecutableAdmissionLedger()
    executable_id = f"{PROVIDER}#bundle/deploy"
    inert_id = f"{PROVIDER}#bundle/notes"
    sibling_id = f"{PROVIDER}#bundle/publish"

    executable_digest = content_digest({"WORKFLOW.md": b"deploy\n"})
    inert_digest = content_digest({"NOTES.md": b"notes\n"})
    sibling_digest = content_digest({"WORKFLOW.md": b"publish\n"})
    _admit(ledger, executable_id, executable_digest)

    # Same bundle, same collection, same provider -- and still inert.
    assert ledger.state_for(inert_id, inert_digest, library_type="prompt") == "inert"
    assert ledger.state_for(inert_id, executable_digest, library_type="prompt") == "inert"
    assert ledger.state_for(inert_id, inert_digest, library_type="standard") == "inert"

    # A second executable in the same bundle inherits nothing either.
    assert ledger.state_for(sibling_id, sibling_digest, library_type="workflow") == "pending"

    # Inert content cannot be admitted at all: there is no executable trust to grant.
    with pytest.raises(InertContentNotAdmissible):
        ledger.admit(
            inert_id,
            inert_digest,
            library_type="prompt",
            reviewer="malte.sussdorff@cognovis.de",
            permission_surface=(),
            decided_at="2026-08-09T09:00:00Z",
            evidence="looks harmless enough",
        )
    assert ledger.record_for(inert_id, inert_digest) is None


def test_inert_members_never_block_a_resolution() -> None:
    """Inert content is neither trusted by association nor gated by it."""
    ledger = ExecutableAdmissionLedger()
    mutations: list[object] = []
    selection = [_item("prompts/a", "prompt"), _item("standards/b", "standard")]

    resolved = gate_resolution(selection, ledger, {}, mutate=mutations.append)

    assert mutations == [{}]
    assert [item.executable_admission for item in resolved] == ["inert", "inert"]
