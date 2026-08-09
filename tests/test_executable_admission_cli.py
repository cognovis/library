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
        store.ledger().state_for(IDENTITY, digest, library_type="workflow")
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

    unknown_type = _run(
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
    )
    assert unknown_type.returncode == 3
    assert "inert" in (unknown_type.stderr + unknown_type.stdout).lower()
