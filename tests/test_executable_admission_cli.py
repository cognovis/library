"""Recording an executable-admission decision through the `library` CLI (CL-2wqz).

`CL-n7ex` delivered the digest-bound ledger and the gate that consults it, and
delivered no way to write a decision into it. Everything executable that comes
from outside was therefore refused forever: the state existed, the operator act
that changes it did not.

What is asserted here is the operator act end to end, not a data structure:

- a decision recorded by the CLI survives the process that recorded it, and the
  next install of exactly those bytes passes the admission check;
- an undecided or denied artifact stays refused, and the refusal hands over the
  exact command that would record the decision -- rendered from the same values
  the CLI registers, and parsed back by the real parser so the two cannot drift;
- a decision follows the bytes: different content is undecided again, and
  replacing a decision is an explicit supersede that keeps both in history.

The CLI half runs as a subprocess with an isolated `XDG_DATA_HOME`, because
`library` resolves its data home once at import and an in-process call would
write into the operator's real library state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.cache_transaction import TransactionAborted  # noqa: E402
from lib.providers.contract import FetchedFile, FetchedItem  # noqa: E402
from lib.providers.executable_admission import (  # noqa: E402
    ADMISSION_COMMAND,
    DENY_VERB,
    GRANT_VERB,
    AdmissionLedgerStore,
    admission_command_line,
    content_digest,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.wiring import ForeignState, install_marketplace_item  # noqa: E402

LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"

NOW = "2026-08-09T15:00:00Z"
PROVIDER = "provider-under-test"
UPSTREAM_ID = "workflows/deploy"
IDENTITY = f"{PROVIDER}#{UPSTREAM_ID}"
OPERATOR = "malte.sussdorff@cognovis.de"
REASON = "read the deploy workflow body and its declared filesystem writes"

GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source="upstream LICENSE (MIT) read on 2026-08-09",
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)

ORIGINAL = {"WORKFLOW.md": b"steps:\n  - deploy\n", "run.py": b"print('deploy')\n"}
CHANGED = {"WORKFLOW.md": b"steps:\n  - deploy\n", "run.py": b"print('rm -rf')\n"}


# -- fixtures -----------------------------------------------------------------


class _Provider:
    """Just enough source to drive one install of one executable item."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = dict(files)

    def identity(self) -> str:
        return PROVIDER

    def fetch(self, upstream_id: str, revision: str | None) -> FetchedItem:
        return FetchedItem(
            upstream_id=upstream_id,
            revision=revision,
            files=tuple(
                FetchedFile(path=path, content=content)
                for path, content in sorted(self.files.items())
            ),
            primary_path=sorted(self.files)[0],
        )

    def capabilities(self) -> frozenset[str]:
        return frozenset()


def _item(revision: str | None = None) -> NormalizedItem:
    return NormalizedItem(
        provider_identity=PROVIDER,
        upstream_id=UPSTREAM_ID,
        upstream_name="deploy",
        collection_membership=("workflows",),
        upstream_revision=revision,
        library_type="workflow",
        library_name="deploy",
        classification={"type_basis": "marker-file"},
        runtime_compatibility=("claude-code",),
        rights=GRANTED,
        provider_availability=AVAILABLE,
        admission_state="installable",
        trust_state="unreviewed",
        executable_admission="pending",
        projection_eligibility={
            "project_committed": "allowed",
            "machine_local": "allowed",
        },
    )


def _home(tmp_path: Path) -> Path:
    """An isolated operator home for the CLI subprocess."""
    home = tmp_path.resolve() / "home"
    (home / "data").mkdir(parents=True, exist_ok=True)
    return home


def _state_for_home(tmp_path: Path) -> ForeignState:
    """The same durable state the CLI writes into, addressed from the test."""
    home = _home(tmp_path)
    return ForeignState.for_locks(
        cache_root=home / "data" / "library" / "foreign",
        project_lock=tmp_path.resolve() / "project" / ".library.lock",
        global_lock=tmp_path.resolve() / "global" / "global.lock",
    )


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home = _home(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    environment["XDG_DATA_HOME"] = str(home / "data")
    return subprocess.run(
        [sys.executable, str(LIBRARY_PY), *args],
        cwd=tmp_path.resolve(),
        env=environment,
        capture_output=True,
        text=True,
    )


def _grant(tmp_path: Path, digest: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        tmp_path,
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--identity",
        IDENTITY,
        "--digest",
        digest,
        "--type",
        "workflow",
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--permission",
        "filesystem:write",
        *extra,
    )


def _install(state: ForeignState, files: Mapping[str, bytes], revision: str | None = None):
    """Install through the marketplace install path, supplying no ledger.

    No ledger is passed on purpose: the shipped CLI passes none either, so this
    is the call the operator's `library marketplace install` actually makes.
    """
    return install_marketplace_item(
        _item(revision),
        provider=_Provider(files),
        state=state,
        scope="project",
        target="machine_local",
        target_root=state.cache_root.parent / "projection",
        observed_at=NOW,
    )


# -- AC1: a recorded grant is durable, auditable, and admits the install -------


def test_grant_is_durable_across_processes_and_auditable(tmp_path: Path) -> None:
    """AC1. One process records; another reads back operator, reason, and time."""
    digest = content_digest(ORIGINAL)

    recorded = _grant(tmp_path, digest)
    assert recorded.returncode == 0, recorded.stderr
    assert digest in recorded.stdout

    audit = _run(tmp_path, ADMISSION_COMMAND, "show", "--identity", IDENTITY, "--json")
    assert audit.returncode == 0, audit.stderr
    decisions = json.loads(audit.stdout)["data"]["decisions"]
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["state"] == "admitted"
    assert decision["content_digest"] == digest
    assert decision["qualified_identity"] == IDENTITY
    assert decision["operator"] == OPERATOR
    assert decision["reason"] == REASON
    assert decision["decided_at"].endswith("Z")
    assert decision["permission_surface"] == ["filesystem:write"]

    listed = _run(tmp_path, ADMISSION_COMMAND, "list", "--json")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["data"]["decisions"] == decisions

    # The decision is durable state, not a process fact: a store opened directly
    # on the same path answers the same thing.
    store = AdmissionLedgerStore(_state_for_home(tmp_path).admission_ledger_path)
    assert (
        store.ledger().state_for(IDENTITY, digest, library_type="workflow", stewardship="foreign")
        == "admitted"
    )


def test_recorded_grant_admits_the_install_and_absence_refuses_it(
    tmp_path: Path,
) -> None:
    """AC1. Undecided refuses; the recorded grant installs the same bytes."""
    state = _state_for_home(tmp_path)
    digest = content_digest(ORIGINAL)

    with pytest.raises(TransactionAborted) as refused:
        _install(state, ORIGINAL)
    assert refused.value.step == "project"

    assert _grant(tmp_path, digest).returncode == 0

    outcome = _install(state, ORIGINAL)
    assert outcome.receipt.executable_admission == "admitted"
    assert outcome.receipt.targets
    for target in outcome.receipt.targets:
        assert Path(target.path).is_file()


# -- AC2: refusal stays refused, and names the command that would change it ----


def test_install_refusal_names_the_exact_admission_command(tmp_path: Path) -> None:
    """AC2. The diagnostic carries a command the shipped parser accepts.

    The command is rendered from the same constants the CLI registers, and it is
    parsed back here by the real parser. A renamed subcommand therefore breaks
    this test rather than shipping a refusal that points at nothing.
    """
    import shlex

    state = _state_for_home(tmp_path)
    with pytest.raises(TransactionAborted) as refused:
        _install(state, ORIGINAL)

    message = str(refused.value)
    expected = admission_command_line(
        IDENTITY, content_digest(ORIGINAL), "workflow", verb=GRANT_VERB
    )
    assert expected in message
    assert DENY_VERB in message

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import library as library_cli

    words = shlex.split(expected)
    assert words[0] == "library"
    parsed = library_cli.build_parser().parse_args(words[1:])
    assert parsed.primitive == ADMISSION_COMMAND
    assert parsed.verb == GRANT_VERB
    assert parsed.identity == IDENTITY
    assert parsed.digest == content_digest(ORIGINAL)


def test_recorded_denial_is_not_overridden_by_re_running_install(
    tmp_path: Path,
) -> None:
    """AC2. A denial persists; re-running the install does not wear it down."""
    state = _state_for_home(tmp_path)
    digest = content_digest(ORIGINAL)

    denied = _run(
        tmp_path,
        ADMISSION_COMMAND,
        DENY_VERB,
        "--identity",
        IDENTITY,
        "--digest",
        digest,
        "--type",
        "workflow",
        "--operator",
        OPERATOR,
        "--reason",
        "the workflow deletes paths outside its own worktree",
    )
    assert denied.returncode == 0, denied.stderr

    for _ in range(3):
        with pytest.raises(TransactionAborted) as refused:
            _install(state, ORIGINAL)
        assert "refused" in str(refused.value)

    audit = _run(tmp_path, ADMISSION_COMMAND, "show", "--identity", IDENTITY, "--json")
    decisions = json.loads(audit.stdout)["data"]["decisions"]
    assert [decision["state"] for decision in decisions] == ["refused"]


# -- AC3: the decision follows the bytes, and replacing one is explicit --------


def test_decision_does_not_transfer_across_a_content_change(tmp_path: Path) -> None:
    """AC3. New bytes are undecided again, whatever the old bytes were told.

    The two installs are pinned to different upstream revisions, which is what a
    content change looks like from a source that has one. It also keeps the
    trust-on-first-use pin out of the way: revisionless drift refuses one layer
    earlier, and the claim under test is about the admission decision.
    """
    state = _state_for_home(tmp_path)
    assert _grant(tmp_path, content_digest(ORIGINAL)).returncode == 0

    assert _install(state, ORIGINAL, "r1").receipt.executable_admission == "admitted"

    with pytest.raises(TransactionAborted) as refused:
        _install(state, CHANGED, "r2")
    assert "pending" in str(refused.value)
    assert content_digest(CHANGED) in str(refused.value)
    # The decision made about the first revision's bytes still stands for those
    # bytes; it simply never applied to the new ones.
    assert _install(state, ORIGINAL, "r1").receipt.executable_admission == "admitted"


def test_recording_over_a_decision_requires_supersede_and_retains_history(
    tmp_path: Path,
) -> None:
    """AC3. A second decision for the same bytes is refused without the flag."""
    digest = content_digest(ORIGINAL)
    assert _grant(tmp_path, digest).returncode == 0

    conflict = _run(
        tmp_path,
        ADMISSION_COMMAND,
        DENY_VERB,
        "--identity",
        IDENTITY,
        "--digest",
        digest,
        "--type",
        "workflow",
        "--operator",
        OPERATOR,
        "--reason",
        "a second look found an unreviewed network call in the workflow",
    )
    assert conflict.returncode == 3
    assert "supersede" in (conflict.stderr + conflict.stdout)

    superseded = _run(
        tmp_path,
        ADMISSION_COMMAND,
        DENY_VERB,
        "--identity",
        IDENTITY,
        "--digest",
        digest,
        "--type",
        "workflow",
        "--operator",
        OPERATOR,
        "--reason",
        "a second look found an unreviewed network call in the workflow",
        "--supersede",
    )
    assert superseded.returncode == 0, superseded.stderr

    audit = _run(
        tmp_path,
        ADMISSION_COMMAND,
        "show",
        "--identity",
        IDENTITY,
        "--json",
    )
    payload = json.loads(audit.stdout)["data"]
    assert [decision["state"] for decision in payload["decisions"]] == ["refused"]
    # Both decisions are retained: the audit trail is the point of the record.
    assert [entry["state"] for entry in payload["history"]] == ["admitted", "refused"]
    assert payload["history"][0]["superseded"] is True
    assert payload["history"][1]["superseded"] is False


# -- Pre-mortem: no rubber stamp, no bulk grant, no name-bound decision --------


def test_reason_operator_and_permission_surface_are_required(tmp_path: Path) -> None:
    """A decision nobody explained is not a decision."""
    digest = content_digest(ORIGINAL)
    base = [
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--identity",
        IDENTITY,
        "--digest",
        digest,
        "--type",
        "workflow",
    ]

    missing_reason = _run(tmp_path, *base, "--operator", OPERATOR, "--permission", "x")
    assert missing_reason.returncode != 0
    assert "reason" in (missing_reason.stderr + missing_reason.stdout).lower()

    missing_operator = _run(tmp_path, *base, "--reason", REASON, "--permission", "x")
    assert missing_operator.returncode != 0

    placeholder = _run(
        tmp_path,
        *base,
        "--operator",
        OPERATOR,
        "--reason",
        "n/a",
        "--permission",
        "filesystem:write",
    )
    assert placeholder.returncode == 3
    assert "placeholder" in (placeholder.stderr + placeholder.stdout).lower()

    # The rendered remedy command is a template, not a working incantation: its
    # placeholder reason is refused exactly like any other one.
    import shlex

    rendered = shlex.split(admission_command_line(IDENTITY, digest, "workflow"))
    pasted = _run(tmp_path, *rendered[1:])
    assert pasted.returncode == 3

    # A grant that declares no permission surface has to say so, because an
    # unstated surface is not the same claim as "this artifact requests none".
    unstated = _run(tmp_path, *base, "--operator", OPERATOR, "--reason", REASON)
    assert unstated.returncode != 0

    stated = _run(
        tmp_path,
        *base,
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--no-permissions",
    )
    assert stated.returncode == 0, stated.stderr


def test_a_name_reference_resolves_and_displays_the_digest_it_records(
    tmp_path: Path,
) -> None:
    """A name reference resolves to a digest that is shown before it is recorded."""
    state = _state_for_home(tmp_path)
    with pytest.raises(TransactionAborted):
        _install(state, ORIGINAL)

    # The refused install left a receipt: the bytes are cached, not installed.
    receipt = state.receipt_store("project").all()[0]
    digest = content_digest(ORIGINAL)

    resolved = _run(
        tmp_path,
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--receipt",
        receipt.id,
        "--scope",
        "project",
        "--project",
        str(tmp_path.resolve() / "project"),
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--permission",
        "filesystem:write",
        "--json",
    )
    assert resolved.returncode == 0, resolved.stderr
    payload = json.loads(resolved.stdout)["data"]
    assert payload["resolved_from"] == receipt.id
    assert payload["decision"]["content_digest"] == digest
    assert payload["decision"]["qualified_identity"] == IDENTITY

    assert _install(state, ORIGINAL).receipt.executable_admission == "admitted"


# -- wave-1 review regressions ------------------------------------------------
#
# Each of these reproduces an adversarial reviewer's proof of concept against the
# delivered code. They are kept as tests rather than as notes because the second
# reviewer of this wave could not run -- the kimi route is not configured on this
# machine -- and a proof of concept that only ever ran once is not a control.


def test_an_omitted_ledger_never_trusts_the_items_own_admission_claim(
    tmp_path: Path,
) -> None:
    """Wave-1 F1. The producer of an item is not an authority over running it.

    Review constructed an external `workflow` carrying
    `executable_admission="admitted"`, called `install_foreign_item` with no
    ledger, and watched it project: the omitted ledger fell back to the item's
    own field, so whoever produced the item decided whether it could execute.
    """
    from lib.providers.cache_transaction import (
        CompletenessEvidence,
        ProjectionActivation,
        install_foreign_item,
    )
    from lib.providers.foreign_cache import (
        IDENTITY_TRANSFORMATION,
        ObjectStore,
        TofuPinStore,
    )
    from lib.providers.receipts import ReceiptStore

    claimed = NormalizedItem.from_dict(
        {**_item().to_dict(), "executable_admission": "admitted"}
    )
    assert claimed.executable_admission == "admitted"

    written: list[str] = []
    activation = ProjectionActivation(
        plan=lambda content: sorted(content),
        apply=lambda content: written.extend(sorted(content)) or [],
    )

    with pytest.raises(TransactionAborted) as refused:
        install_foreign_item(
            claimed,
            retrieve=lambda: _Provider(ORIGINAL).fetch(UPSTREAM_ID, None),
            object_store=ObjectStore(tmp_path / "cache"),
            pin_store=TofuPinStore(tmp_path / "pins.json"),
            receipt_store=ReceiptStore(tmp_path / "receipts.json"),
            target="machine_local",
            activate=activation,
            observed_at=NOW,
            completeness=CompletenessEvidence.from_manifest(sorted(ORIGINAL)),
            transformation=IDENTITY_TRANSFORMATION,
        )
    assert refused.value.step == "project"
    assert "pending" in str(refused.value)
    assert written == []


def test_a_denial_recorded_during_an_install_is_not_overtaken_by_it(
    tmp_path: Path,
) -> None:
    """Wave-1 F2. A completed denial is never followed by a projection.

    Review recorded a grant, paused the provider inside `fetch` so the install
    was holding a ledger it had already read, recorded a superseding denial that
    returned success, and released the fetch: the artifact was projected under
    the superseded grant. An operator whose `deny` completed had every reason to
    believe it had taken effect.
    """
    import threading

    from lib.providers.executable_admission import AdmissionLedgerStore

    state = _state_for_home(tmp_path)
    digest = content_digest(ORIGINAL)
    assert _grant(tmp_path, digest).returncode == 0

    retrieving = threading.Event()
    denied = threading.Event()

    class _PausingProvider(_Provider):
        def fetch(self, upstream_id: str, revision: str | None) -> FetchedItem:
            retrieving.set()
            assert denied.wait(timeout=30)
            return super().fetch(upstream_id, revision)

    outcome: list[object] = []

    def _run_install() -> None:
        try:
            outcome.append(
                install_marketplace_item(
                    _item(),
                    provider=_PausingProvider(ORIGINAL),
                    state=state,
                    scope="project",
                    target="machine_local",
                    target_root=state.cache_root.parent / "projection",
                    observed_at=NOW,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - the refusal is the result
            outcome.append(exc)

    installer = threading.Thread(target=_run_install)
    installer.start()
    try:
        assert retrieving.wait(timeout=30)
        AdmissionLedgerStore(state.admission_ledger_path).decide(
            "refused",
            IDENTITY,
            digest,
            library_type="workflow",
            reviewer=OPERATOR,
            permission_surface=(),
            decided_at="2026-08-09T16:00:00Z",
            evidence="a second reading found an unreviewed destructive command",
            supersedes=True,
        )
        assert (
            state.admission_ledger().state_for(
                IDENTITY, digest, library_type="workflow", stewardship="foreign"
            )
            == "refused"
        )
    finally:
        denied.set()
        installer.join(timeout=60)

    assert not installer.is_alive()
    assert isinstance(outcome[0], TransactionAborted), outcome[0]
    assert "refused" in str(outcome[0])
    assert not (state.cache_root.parent / "projection").exists()


def test_a_denial_recorded_after_the_receipt_still_stops_the_projection(
    tmp_path: Path,
) -> None:
    """Wave-1 F2, at the narrowest window there is.

    The previous test denies while the install is still retrieving, which the
    early check catches. This one denies after the receipt is durable and while
    the projection is being planned -- the last moment at which a re-read could
    still be overtaken. The decisions are held still across the activation
    itself, so the denial either lands before the write and refuses it, or waits
    for a write that was authorized when it happened.
    """
    import threading

    from lib.providers.cache_transaction import (
        CompletenessEvidence,
        ProjectionActivation,
        install_foreign_item,
    )
    from lib.providers.foreign_cache import (
        IDENTITY_TRANSFORMATION,
        ObjectStore,
        TofuPinStore,
    )
    from lib.providers.receipts import ReceiptStore

    state = _state_for_home(tmp_path)
    store = state.admission_ledger_store()
    digest = content_digest(ORIGINAL)
    assert _grant(tmp_path, digest).returncode == 0

    planning = threading.Event()
    denied = threading.Event()
    written: list[str] = []

    def _plan(content):
        planning.set()
        assert denied.wait(timeout=30)
        return sorted(content)

    def _apply(content):
        written.extend(sorted(content))
        return []

    outcome: list[object] = []

    def _run_install() -> None:
        try:
            outcome.append(
                install_foreign_item(
                    _item(),
                    retrieve=lambda: _Provider(ORIGINAL).fetch(UPSTREAM_ID, None),
                    object_store=ObjectStore(tmp_path / "cache"),
                    pin_store=TofuPinStore(tmp_path / "pins.json"),
                    receipt_store=ReceiptStore(tmp_path / "receipts.json"),
                    target="machine_local",
                    activate=ProjectionActivation(plan=_plan, apply=_apply),
                    observed_at=NOW,
                    completeness=CompletenessEvidence.from_manifest(sorted(ORIGINAL)),
                    transformation=IDENTITY_TRANSFORMATION,
                    ledger=store,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - the refusal is the result
            outcome.append(exc)

    installer = threading.Thread(target=_run_install)
    installer.start()
    try:
        assert planning.wait(timeout=30)
        store.decide(
            "refused",
            IDENTITY,
            digest,
            library_type="workflow",
            reviewer=OPERATOR,
            permission_surface=(),
            decided_at="2026-08-09T16:30:00Z",
            evidence="withdrawn after a second reading of the deploy step",
            supersedes=True,
        )
    finally:
        denied.set()
        installer.join(timeout=60)

    assert not installer.is_alive()
    assert isinstance(outcome[0], TransactionAborted), outcome[0]
    assert "refused" in str(outcome[0])
    assert written == []


def test_a_hand_edited_ledger_entry_is_refused_rather_than_coerced(
    tmp_path: Path,
) -> None:
    """Wave-1 F3. Malformed durable state fails closed, it is not repaired.

    Review hand-wrote a ledger whose `reviewer` was the integer 12345, whose
    `decided_at` was an object, whose `evidence` was a list, and whose
    permission surface was a bare string. Every one of them was coerced by
    `str()`/`tuple()` into a well-formed record, and the gate answered
    `admitted` over it -- with a permission surface of sixteen single
    characters.
    """
    from lib.providers.executable_admission import (
        ADMISSION_LEDGER_SCHEMA,
        AdmissionLedgerStore,
    )

    store = AdmissionLedgerStore(tmp_path / "executable-admission.json")
    digest = content_digest(ORIGINAL)
    base = {
        "qualified_identity": IDENTITY,
        "content_digest": digest,
        "state": "admitted",
        "reviewer": OPERATOR,
        "permission_surface": ["filesystem:write"],
        "decided_at": NOW,
        "evidence": REASON,
    }

    def _write(entry: dict) -> None:
        store.path.write_text(
            json.dumps({"schema": ADMISSION_LEDGER_SCHEMA, "decisions": [entry]}),
            encoding="utf-8",
        )

    for field, value in (
        ("reviewer", 12345),
        ("decided_at", {"not": "a timestamp"}),
        ("evidence", ["not", "an operator sentence but coerced into one"]),
        ("permission_surface", "filesystem:write"),
        ("state", None),
    ):
        _write({**base, field: value})
        with pytest.raises(ValueError) as refused:
            store.ledger()
        assert field in str(refused.value)

    # A timestamp that is a string but not an instant is refused too: the field
    # exists to be ordered against other events.
    _write({**base, "decided_at": "some time last week"})
    with pytest.raises(ValueError):
        store.ledger()

    _write(base)
    assert store.ledger().state_for(IDENTITY, digest, library_type="workflow", stewardship="foreign") == (
        "admitted"
    )


# -- wave-2 review regressions ------------------------------------------------


def test_repair_does_not_reinstall_bytes_whose_grant_was_superseded(
    tmp_path: Path,
) -> None:
    """Wave-2 F1. Cache integrity is not admission.

    Review granted a workflow, installed it, superseded the grant with a
    refusal, deleted the projection, and repaired it: the refused bytes were
    written back from the verified cache. Repair is the write path an
    enforcement check written for `install` quietly misses -- it makes no remote
    claim and reads as recovery.
    """
    from lib.providers.inventory import ProviderAvailability
    from lib.providers.wiring import repair_projection

    state = _state_for_home(tmp_path)
    digest = content_digest(ORIGINAL)
    assert _grant(tmp_path, digest).returncode == 0

    outcome = _install(state, ORIGINAL)
    projected = [Path(target.path) for target in outcome.receipt.targets]
    assert projected and all(path.is_file() for path in projected)

    assert (
        _run(
            tmp_path,
            ADMISSION_COMMAND,
            DENY_VERB,
            "--identity",
            IDENTITY,
            "--digest",
            digest,
            "--type",
            "workflow",
            "--operator",
            OPERATOR,
            "--reason",
            "a later reading found the deploy step writes outside its worktree",
            "--supersede",
        ).returncode
        == 0
    )

    for path in projected:
        path.unlink()

    with pytest.raises(TransactionAborted) as refused:
        repair_projection(
            receipt=state.receipt_store("project").get(outcome.receipt.id),
            state=state,
            scope="project",
            target_root=state.cache_root.parent / "projection",
            availability=ProviderAvailability(state="available", observed_at=NOW),
            observed_at=NOW,
        )
    assert "refused" in str(refused.value)
    assert not any(path.exists() for path in projected)


def test_a_workspace_mutation_holds_its_decisions_for_its_whole_write(
    tmp_path: Path,
) -> None:
    """Wave-2 F2. A snapshot read before the write is not enough.

    Review took the snapshot `library workspace use` used to hand the gate,
    superseded the grant with a refusal while the members were being installed,
    and the admitted bytes were written anyway. The CLI now runs the gate and
    its mutation inside `decisions()`, which holds the same lock a
    `library admission` write takes -- so this test asserts the property the
    caller relies on: a decision recorded while a mutation holds the decisions
    cannot land in the middle of it.
    """
    import threading

    store = _state_for_home(tmp_path).admission_ledger_store()
    digest = content_digest(ORIGINAL)
    assert _grant(tmp_path, digest).returncode == 0

    mutating = threading.Event()
    released = threading.Event()
    landed = threading.Event()
    seen: list[str] = []

    def _record_denial() -> None:
        store.decide(
            "refused",
            IDENTITY,
            digest,
            library_type="workflow",
            reviewer=OPERATOR,
            permission_surface=(),
            decided_at="2026-08-09T17:00:00Z",
            evidence="withdrawn while the workspace members were installing",
            supersedes=True,
        )
        landed.set()

    with store.decisions() as decisions:
        assert (
            decisions.state_for(IDENTITY, digest, library_type="workflow", stewardship="foreign") == "admitted"
        )
        writer = threading.Thread(target=_record_denial)
        writer.start()
        try:
            mutating.set()
            # The denial cannot complete while the mutation holds the decisions.
            assert not landed.wait(timeout=1.0)
            seen.append(decisions.state_for(IDENTITY, digest, library_type="workflow", stewardship="foreign"))
        finally:
            released.set()
    writer.join(timeout=30)

    assert seen == ["admitted"]
    assert landed.is_set()
    assert (
        store.ledger().state_for(IDENTITY, digest, library_type="workflow", stewardship="foreign") == "refused"
    )


def test_a_missing_permission_surface_is_not_an_empty_declaration(
    tmp_path: Path,
) -> None:
    """Wave-2 F3. An absent claim is not the claim that nothing was requested."""
    from lib.providers.executable_admission import (
        ADMISSION_LEDGER_SCHEMA,
        AdmissionLedgerStore,
    )

    store = AdmissionLedgerStore(tmp_path / "executable-admission.json")
    entry = {
        "qualified_identity": IDENTITY,
        "content_digest": content_digest(ORIGINAL),
        "state": "admitted",
        "reviewer": OPERATOR,
        "decided_at": NOW,
        "evidence": REASON,
    }
    store.path.write_text(
        json.dumps({"schema": ADMISSION_LEDGER_SCHEMA, "decisions": [entry]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as refused:
        store.ledger()
    assert "permission_surface" in str(refused.value)


def test_a_decision_timestamp_has_to_name_an_instant(tmp_path: Path) -> None:
    """Wave-2 F4. A date and a naive local time are not instants.

    `datetime.fromisoformat` accepts both, and neither can be ordered against
    the UTC timestamps the CLI writes -- which is the only thing the field is
    for.
    """
    from lib.providers.executable_admission import (
        ADMISSION_LEDGER_SCHEMA,
        AdmissionLedgerStore,
        validated_decided_at,
    )

    for rejected in ("2026-08-09", "2026-08-09T15:00:00", "some time last week"):
        with pytest.raises(ValueError):
            validated_decided_at(rejected)
    for accepted in ("2026-08-09T15:00:00Z", "2026-08-09T17:00:00+02:00"):
        assert validated_decided_at(accepted) == accepted

    store = AdmissionLedgerStore(tmp_path / "executable-admission.json")
    store.path.write_text(
        json.dumps(
            {
                "schema": ADMISSION_LEDGER_SCHEMA,
                "decisions": [
                    {
                        "qualified_identity": IDENTITY,
                        "content_digest": content_digest(ORIGINAL),
                        "state": "admitted",
                        "reviewer": OPERATOR,
                        "permission_surface": ["filesystem:write"],
                        "decided_at": "2026-08-09",
                        "evidence": REASON,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        store.ledger()


def test_there_is_no_bulk_grant_surface(tmp_path: Path) -> None:
    """No `--all`, and no way to admit an identity without naming its bytes."""
    for flag in ("--all", "--every", "--recursive"):
        rejected = _run(
            tmp_path,
            ADMISSION_COMMAND,
            GRANT_VERB,
            flag,
            "--operator",
            OPERATOR,
            "--reason",
            REASON,
        )
        assert rejected.returncode != 0

    without_digest = _run(
        tmp_path,
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--identity",
        IDENTITY,
        "--type",
        "workflow",
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--permission",
        "filesystem:write",
    )
    assert without_digest.returncode != 0

    malformed = _grant(tmp_path, "sha256:not-a-real-digest")
    assert malformed.returncode == 3
    assert "digest" in (malformed.stderr + malformed.stdout).lower()

    # A type that is inert under every stewardship still cannot be decided about.
    # `CL-lt51` narrowed this set rather than removing it: a Skill is now
    # decidable because a foreign steward's Skill instructs a model, while an
    # MCP-Server registration instructs nothing and holds no trust to grant.
    inert_type = _run(
        tmp_path,
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--identity",
        f"{PROVIDER}#servers/helper",
        "--digest",
        content_digest(ORIGINAL),
        "--type",
        "mcp-server",
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--no-permissions",
    )
    assert inert_type.returncode == 3
    assert "inert" in (inert_type.stderr + inert_type.stdout).lower()


def test_a_foreign_skill_can_be_decided_about_at_the_cli(tmp_path: Path) -> None:
    """AC1: the operator act reaches model-instructing content too (`CL-lt51`).

    Before this bead the same command answered "that is inert", which left an
    operator who wanted to record their review of an upstream Skill with nothing
    to record it in -- the `CL-2wqz` failure mode, one content class over.
    """
    granted = _run(
        tmp_path,
        ADMISSION_COMMAND,
        GRANT_VERB,
        "--identity",
        f"{PROVIDER}#skills/helper",
        "--digest",
        content_digest(ORIGINAL),
        "--type",
        "skill",
        "--operator",
        OPERATOR,
        "--reason",
        REASON,
        "--no-permissions",
        "--json",
    )
    assert granted.returncode == 0, granted.stderr
    payload = json.loads(granted.stdout)["data"]["decision"]
    assert payload["state"] == "admitted"
    assert payload["content_digest"] == content_digest(ORIGINAL)


# -- CL-9mfy: the install gate judges the target the operator requested --------
#
# These drive `library marketplace install` in process rather than as a
# subprocess, because what is under test is the pre-transaction gate's decision
# and every durable store the command writes to is reachable from
# `_foreign_state`. Substituting that one seam isolates the run exactly as the
# subprocess `XDG_DATA_HOME` does above, while keeping the shipped parser, exit
# codes, and JSON payload.

MARKETPLACE = "provider-under-test"
UNKNOWN_ID = "skills/unlicensed"
UNKNOWN_IDENTITY = f"{PROVIDER}#{UNKNOWN_ID}"
UNKNOWN_FILES = {"SKILL.md": b"---\nname: unlicensed\n---\nan upstream skill\n"}

#: What a subscriber endpoint records: the token proves the fetch and says
#: nothing about installing or redistributing what it served.
UNKNOWN_RIGHTS = Rights(
    fetch_authorization="granted",
    evidence_source="subscriber endpoint token, 2026-08-09",
    grant_evidence={"install_rights": "no published installation grant"},
)


def _catalog() -> dict:
    return {
        "sources": {
            "catalogs": [],
            "marketplaces": [
                {
                    "name": MARKETPLACE,
                    "source": "https://example.invalid/provider-under-test",
                    "provider_kind": "git-repo",
                }
            ],
        }
    }


def _unknown_item(**overrides: object) -> NormalizedItem:
    """A foreign Skill whose recorded `install_rights` are unknown."""
    base = dict(
        provider_identity=PROVIDER,
        upstream_id=UNKNOWN_ID,
        upstream_name="unlicensed",
        collection_membership=("skills",),
        upstream_revision=None,
        library_type="skill",
        library_name="unlicensed",
        classification={"type_basis": "marker-file"},
        runtime_compatibility=("unknown",),
        rights=UNKNOWN_RIGHTS,
        provider_availability=AVAILABLE,
    )
    base.update(overrides)
    return NormalizedItem(**base)  # type: ignore[arg-type]


def _marketplace_install(
    tmp_path: Path,
    monkeypatch: "pytest.MonkeyPatch",
    item: NormalizedItem,
    files: Mapping[str, bytes],
    *,
    target: str,
    accept_rights: bool,
    admit: bool = True,
) -> tuple[int, str, str]:
    """Run one `library marketplace install` against a stubbed provider."""
    import contextlib
    import io

    import library as library_cli
    from lib.providers import wiring
    from lib.providers.inventory import NormalizedInventory
    from lib.providers.normalize import NormalizationResult

    state = _state_for_home(tmp_path)
    if admit:
        # The admission axis is not what these tests are about, so the decision
        # the transaction requires is recorded for these exact bytes -- and for
        # nothing else, so a regression in that gate still fails here.
        state.admission_ledger_store().decide(
            "admitted",
            item.qualified_identity(),
            content_digest(files),
            library_type=item.library_type,
            reviewer=OPERATOR,
            permission_surface=(),
            decided_at=NOW,
            evidence=REASON,
        )

    provider = _Provider(files)
    result = NormalizationResult(
        inventory=NormalizedInventory([item]),
        costs=(),
        absent_capabilities=(),
        provider_identity=PROVIDER,
        provider_availability=AVAILABLE,
    )
    project_root = tmp_path.resolve() / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        wiring, "marketplace_inventory", lambda entry, **kwargs: (provider, result)
    )
    monkeypatch.setattr(library_cli, "load_catalog", lambda root: _catalog())
    monkeypatch.setattr(library_cli, "_resolve_catalog_root", lambda: project_root)
    monkeypatch.setattr(library_cli, "_foreign_state", lambda repo_root: state)

    argv = [
        "marketplace",
        "install",
        MARKETPLACE,
        item.upstream_id,
        "--target",
        target,
        "--target-root",
        str(project_root / "projection"),
        "--json",
    ]
    if accept_rights:
        argv.append("--accept-rights")

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = library_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_an_unknown_rights_item_installs_machine_local_after_the_opt_in(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """AC1. The requested target decides, so the presenter is reachable.

    Before `CL-9mfy` this refused with `Not installable (blocked)`: the rights
    reason that blocks the *committed* projection decided the summary state for a
    machine-local install too, so the operator opt-in presenter this command
    carries could never run for the one class of item it was written for.
    """
    code, out, err = _marketplace_install(
        tmp_path,
        monkeypatch,
        _unknown_item(),
        UNKNOWN_FILES,
        target="machine_local",
        accept_rights=True,
    )

    assert code == 0, err or out
    # The presenter writes its statement to stdout ahead of the result payload,
    # so the rendered statement is read here rather than assumed: this is the
    # operator seeing the rights state before anything is written.
    assert "operator-opt-in-required" in out
    payload = json.loads(out[out.index("{") :])["data"]
    assert payload["status"] == "installed"
    assert payload["qualified_identity"] == UNKNOWN_IDENTITY
    # And the acknowledgement carries that statement's own token, which is why
    # the command can record that it was shown at all.
    assert payload["rights_statement_shown"] is True
    assert payload["targets"]
    for path in payload["targets"]:
        assert Path(path).is_file()
    # The durable cache transaction completed, not only the projection.
    assert payload["receipt_id"]
    assert Path(payload["cache_object"]).exists()


def test_the_same_install_without_the_opt_in_is_refused_by_the_presenter(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """AC1, the other half. Reaching the presenter is not passing it.

    The refusal is the presenter's own and names the flag that accepts the rights
    statement it just printed -- a different outcome from the pre-`CL-9mfy`
    `Not installable` refusal, which printed no statement at all.
    """
    code, out, err = _marketplace_install(
        tmp_path,
        monkeypatch,
        _unknown_item(),
        UNKNOWN_FILES,
        target="machine_local",
        accept_rights=False,
    )

    assert code == 3
    assert "--accept-rights" in (out + err)
    assert "Not installable" not in (out + err)
    assert not (tmp_path.resolve() / "project" / "projection").exists()


def test_the_committed_projection_of_the_same_item_is_still_refused(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """AC2. The target-aware gate still refuses the target that has no grant."""
    code, out, err = _marketplace_install(
        tmp_path,
        monkeypatch,
        _unknown_item(),
        UNKNOWN_FILES,
        target="project_committed",
        accept_rights=True,
    )

    assert code == 3
    message = out + err
    assert "install_rights" in message
    assert "unknown" in message
    assert not (tmp_path.resolve() / "project" / "projection").exists()


@pytest.mark.parametrize(
    "overrides, expected",
    [
        (
            {
                "provider_availability": ProviderAvailability(
                    state="unavailable",
                    observed_at=NOW,
                    reason="endpoint returned 503",
                )
            },
            "content-unavailable",
        ),
        (
            {
                "classification": {
                    "type_basis": "marker-file",
                    "maturity": "in-progress",
                    "maturity_basis": "collection:in-progress",
                }
            },
            "maturity",
        ),
    ],
)
@pytest.mark.parametrize("target", ["machine_local", "project_committed"])
def test_a_non_rights_block_is_refused_for_every_target(
    tmp_path: Path,
    monkeypatch: "pytest.MonkeyPatch",
    overrides: Mapping[str, object],
    expected: str,
    target: str,
) -> None:
    """AC3. Naming a target relaxes the rights axis and nothing else.

    Both items also carry unknown rights, so an item the operator could opt into
    machine-locally is still refused while something other than rights is wrong
    with it.
    """
    code, out, err = _marketplace_install(
        tmp_path,
        monkeypatch,
        _unknown_item(**overrides),
        UNKNOWN_FILES,
        target=target,
        accept_rights=True,
    )

    assert code == 3
    assert expected in (out + err)
    assert not (tmp_path.resolve() / "project" / "projection").exists()
