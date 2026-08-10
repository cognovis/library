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

**The operator act (`CL-2wqz`).** Slice 2 shipped this state and no way to write
it, so every externally sourced executable artifact was refused permanently: the
gate was correct and nothing could ever pass it. `AdmissionLedgerStore` is the
durable, cross-process form of the ledger, and the `ADMISSION_COMMAND` constants
below are the single place the CLI words are written down -- the shipped parser
registers from them and the install-time refusal renders a command from them, so
a renamed subcommand cannot leave a diagnostic pointing at nothing.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence, Union

from .classification import EXECUTABLE_TYPES
from .inventory import (
    EVIDENCE_PLACEHOLDERS,
    EXECUTABLE_ADMISSION_STATES,
    MIN_EVIDENCE_LENGTH,
    NormalizedItem,
)
from .state_files import atomic_write_text, exclusive_lock

DIGEST_PREFIX = "sha256:"
_DIGEST_RE = re.compile(rf"^{DIGEST_PREFIX}[0-9a-f]{{64}}$")

INERT = "inert"
ADMITTED = "admitted"
PENDING = "pending"
REFUSED = "refused"

#: The CLI words that record an executable-admission decision. They live beside
#: the state they write so that the registration and the refusal diagnostic have
#: one source: `scripts/library.py` builds its subparsers from these values, and
#: `admission_refusal` renders its remedy from the same ones.
ADMISSION_COMMAND = "admission"
GRANT_VERB = "grant"
DENY_VERB = "deny"
SHOW_VERB = "show"
LIST_VERB = "list"

#: Schema of the durable decision file.
ADMISSION_LEDGER_SCHEMA = "cognovis.executable-admission-ledger.v1"

#: What a rendered remedy command puts where the operator's own words belong.
#: Refused on the way in, so pasting the template unchanged records nothing.
OPERATOR_PLACEHOLDER = "<your operator identity>"
REASON_PLACEHOLDER = "<why you reviewed these exact bytes and trust them>"
PERMISSION_PLACEHOLDER = "<a permission this artifact requests>"


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
    snapshot = frozen_content(files)
    digest = hashlib.sha256()
    for path in sorted(snapshot):
        content = snapshot[path]
        encoded_path = path.encode("utf-8")
        digest.update(str(len(encoded_path)).encode("ascii") + b":" + encoded_path)
        digest.update(str(len(content)).encode("ascii") + b":" + content)
    return f"{DIGEST_PREFIX}{digest.hexdigest()}"


def frozen_content(files: Mapping[str, bytes]) -> Mapping[str, bytes]:
    """An immutable bytes-only snapshot of one item's content.

    Digesting a live mapping and later handing that same object to a mutation is
    a time-of-check-to-time-of-use hole, and review walked straight through it:
    a stateful mapping returned reviewed bytes while being hashed and an
    unreviewed payload when the mutation read it. Everything downstream of the
    gate works on the snapshot, so the bytes that were digested are the bytes
    that get written.
    """
    if not files:
        raise ValueError("an item with no files has no content digest to bind")
    snapshot: dict[str, bytes] = {}
    for path in sorted(files):
        content = files[path]
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError(f"content for {path!r} must be bytes")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("content paths must be non-empty text")
        snapshot[path] = bytes(content)
    return MappingProxyType(snapshot)


def validated_digest(value: str) -> str:
    """A digest in this module's exact form, or a refusal.

    Accepting `sha256:not-a-digest` was demonstrated in review: any string that
    started with the prefix was recorded as if it were a reviewed content
    identity, so a decision could be filed against bytes that do not exist.
    """
    if not isinstance(value, str) or not _DIGEST_RE.match(value):
        raise ValueError(
            f"{value!r} is not a content digest; expected {DIGEST_PREFIX} followed "
            "by 64 lowercase hex characters"
        )
    return value


def is_executable_type(library_type: str) -> bool:
    """Whether this Library type requires an executable-admission decision."""
    return library_type in EXECUTABLE_TYPES


def _is_template(value: str) -> bool:
    """Whether this text is a rendered placeholder rather than an answer.

    A remedy command has to be complete enough to read, which means it carries
    placeholders where the operator's own words belong. Recording one verbatim
    would file a decision whose stated reason is the instruction to state a
    reason, so the placeholder shape is refused on the way in.
    """
    stripped = value.strip()
    return stripped.startswith("<") and stripped.endswith(">")


def validated_operator(value: str) -> str:
    """The declared identity of the operator making this decision, or a refusal.

    The identity is a **declared string**, exactly as `CL-n7ex` left it: nothing
    here authenticates it, because verifying an operator is credential handling
    and is held behind a human security review. What this refuses is an absent
    or template answer, which is the difference between a weak attribution and
    no attribution at all.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "an admission decision records who made it; pass the operator identity"
        )
    if _is_template(value):
        raise ValueError(
            f"{value!r} is the placeholder from a rendered remedy command, not an "
            "operator identity; record who is deciding"
        )
    return value.strip()


def validated_decided_at(value: str) -> str:
    """When this decision was made, as a real instant, or a refusal.

    An unparseable timestamp is not a cosmetic defect in an audit record. "When
    was this admitted, and was that before or after the incident" is the first
    question anyone asks of one, and a field holding `{'not': 'a timestamp'}`
    stringified answers it with something that reads like an answer.

    Parsing is not enough on its own, and review said so: `fromisoformat` accepts
    the calendar date `2026-08-09` and the naive `2026-08-09T15:00:00`, and
    neither is an instant. A date cannot be ordered against a time on the same
    day, and a naive value cannot be ordered against the UTC timestamps this CLI
    writes without guessing whose local clock it came from. Both are refused, so
    an admission ledger orders.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("an admission decision records when it was made")
    candidate = value.strip()
    try:
        moment = _dt.datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{value!r} is not an ISO-8601 instant; an admission decision has to "
            "say when it was made in a form that can be ordered against other "
            "events"
        ) from exc
    if "T" not in candidate and " " not in candidate:
        raise ValueError(
            f"{value!r} is a calendar date, not an instant; a date cannot be "
            "ordered against the other events of the same day"
        )
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            f"{value!r} carries no UTC offset, so it names a moment on somebody's "
            "local clock rather than an instant; record it with a 'Z' or an "
            "explicit offset"
        )
    return candidate


def validated_reason(value: str) -> str:
    """The operator's stated reason for this decision, or a refusal.

    The floor is the one `inventory.BlockReason` already applies to block-reason
    evidence, adopted rather than forked: long enough to be a sentence, not one
    of the phrases that admit they say nothing, and never a rendered template.
    It checks shape and not truth -- no validator can tell a considered reason
    from a fluent one, and pretending otherwise would be the more dangerous
    claim.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("an admission decision records why it was made")
    stripped = value.strip()
    if _is_template(stripped):
        raise ValueError(
            f"{stripped!r} is the placeholder from a rendered remedy command; the "
            "reason has to be your own words, so the template is refused"
        )
    if (
        len(stripped) < MIN_EVIDENCE_LENGTH
        or " " not in stripped
        or stripped.lower().rstrip(".") in EVIDENCE_PLACEHOLDERS
    ):
        raise ValueError(
            f"the reason {value!r} is a placeholder; record what you reviewed and "
            "what it led you to decide"
        )
    return stripped


def admission_command_line(
    qualified_identity: str,
    content_digest_value: str,
    library_type: str,
    *,
    verb: str = GRANT_VERB,
    supersede: bool = False,
) -> str:
    """The exact command that records one decision, rendered from the CLI words.

    Rendered here rather than written out at the refusal site, because a
    diagnostic that names a command is only useful while the command still
    exists. `scripts/library.py` registers `ADMISSION_COMMAND` and its verbs
    from these same constants, and the test parses this string back through the
    shipped parser, so a rename breaks the build instead of the operator.
    """
    words = [
        "library",
        ADMISSION_COMMAND,
        verb,
        "--identity",
        shlex.quote(qualified_identity),
        "--digest",
        content_digest_value,
        "--type",
        library_type,
        "--operator",
        shlex.quote(OPERATOR_PLACEHOLDER),
        "--reason",
        shlex.quote(REASON_PLACEHOLDER),
    ]
    if verb == GRANT_VERB:
        words += ["--permission", shlex.quote(PERMISSION_PLACEHOLDER)]
    if supersede:
        words.append("--supersede")
    return " ".join(words)


def admission_refusal(
    qualified_identity: str,
    content_digest_value: str,
    library_type: str,
    state: str,
) -> str:
    """The install-time refusal for an executable artifact nobody decided about.

    It carries the digest it refused and both commands that would change the
    answer. Before `CL-2wqz` this message named the state and stopped there,
    which was accurate and useless: there was no command to name, so an operator
    reading it had no way forward at all.
    """
    already_decided = state == REFUSED
    grant = admission_command_line(
        qualified_identity,
        content_digest_value,
        library_type,
        verb=GRANT_VERB,
        supersede=already_decided,
    )
    deny = admission_command_line(
        qualified_identity,
        content_digest_value,
        library_type,
        verb=DENY_VERB,
        supersede=already_decided,
    )
    standing = (
        "a recorded refusal stands until it is explicitly superseded"
        if already_decided
        else "nothing has decided about these bytes yet"
    )
    return (
        f"{qualified_identity} is an executable artifact whose admission state is "
        f"{state!r} for these exact bytes ({content_digest_value}). The content is "
        "cached and receipted; caching is not installing, and no harness path "
        f"receives it until the scope operator decides -- {standing}. Record the "
        "decision and re-run the install:\n"
        f"  {grant}\n"
        f"  {deny}\n"
        "Both need your own operator identity and your own reason; the "
        "placeholders above are refused, and a grant that requests no permissions "
        "declares that with --no-permissions."
    )


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
        validated_digest(self.content_digest)
        # Enforced on the record rather than at the CLI, because a control that
        # every call site has to remember is already off somewhere. The ledger
        # is the authority for executable trust; a decision it holds with no
        # attributable operator and no stated reason is an audit trail that
        # looks complete and proves nothing.
        validated_operator(self.reviewer)
        validated_reason(self.evidence)
        validated_decided_at(self.decided_at)
        surface = tuple(self.permission_surface)
        # An empty surface is a legitimate declaration: this artifact requests
        # nothing. A blank *entry* is not -- it is a declaration shaped like one,
        # and ADR-0011 requires the permission surface the artifact requests to
        # be recorded evidence, not padding.
        for entry in surface:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(
                    "AdmissionRecord.permission_surface entries must each name a "
                    "requested permission; record an empty surface for an artifact "
                    "that requests none"
                )
        object.__setattr__(self, "permission_surface", surface)

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
        if not isinstance(record, AdmissionRecord):
            # The ledger is the authority for executable trust, so anything that
            # merely looks like a record is not one. Review filed a duck-typed
            # object carrying `state="admitted"` and nothing else, and the gate
            # materialized executable content on it.
            raise TypeError(
                "an executable-admission ledger holds validated AdmissionRecord "
                f"values, not {type(record).__name__}"
            )
        key = (record.qualified_identity, record.content_digest)
        existing = self._records.get(key)
        if existing is not None and not supersedes:
            # Any existing decision for these exact bytes is protected, not only
            # a contradicting one. Review observed that a repeated `admit` with a
            # different reviewer silently rewrote who had vouched for the
            # content -- the audit trail is the point of the record.
            raise ValueError(
                f"{record.qualified_identity} at {record.content_digest} is already "
                f"recorded as {existing.state} by {existing.reviewer}; replacing "
                "that decision is an explicit act (pass supersedes=True), never an "
                "overwrite"
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

    @contextlib.contextmanager
    def decisions(self) -> Iterator["ExecutableAdmissionLedger"]:
        """This ledger, held still for the length of one mutation.

        An in-memory ledger has no other writer to be raced by, so holding it
        still is nothing. The method exists so that a caller about to write
        executable bytes can ask *any* admission authority for the decisions
        that stand right now, without knowing whether it is holding a snapshot
        or a durable store -- see `AdmissionLedgerStore.decisions`, where the
        same call is a real lock.
        """
        yield self

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
        record = self.record_for(qualified_identity, validated_digest(content_digest_value))
        if record is None:
            return PENDING
        return record.state


class AdmissionLedgerStore:
    """The scope operator's admission decisions, durable across processes.

    `ExecutableAdmissionLedger` is the in-memory authority and stays exactly
    that: one current decision per `(identity, digest)` key. This store is the
    file it is read from and written to, and it differs in one deliberate way --
    it is **append-only**. A superseding decision does not replace the record it
    supersedes, it follows it, because the whole reason a decision is protected
    from silent overwrite is that somebody may later need to see what was
    decided before and by whom.

    Writes are one locked load-modify-save, for the reason `state_files`
    documents: atomic replacement makes a write indivisible for readers and does
    nothing for the read that decided what to write. Two operators deciding at
    once would otherwise each save a history that omits the other's decision.

    A malformed file refuses rather than reading as an empty ledger. "We cannot
    parse the decisions" must never be more permissive than "there are none".
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != ADMISSION_LEDGER_SCHEMA:
            raise ValueError(
                f"unexpected executable-admission ledger schema at {self.path}: "
                f"{payload.get('schema') if isinstance(payload, dict) else type(payload).__name__}"
            )
        decisions = payload.get("decisions")
        if not isinstance(decisions, list) or not all(
            isinstance(entry, dict) for entry in decisions
        ):
            raise ValueError(
                f"executable-admission decisions at {self.path} must be a list of "
                "records; a malformed ledger is never read as an empty one"
            )
        return decisions

    def _save(self, decisions: Sequence[Mapping[str, Any]]) -> None:
        atomic_write_text(
            self.path,
            json.dumps(
                {"schema": ADMISSION_LEDGER_SCHEMA, "decisions": list(decisions)},
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    @staticmethod
    def _text(entry: Mapping[str, Any], field: str) -> str:
        """One stored text field, refused rather than coerced.

        `str(value)` looked like defensive parsing and was the opposite of it:
        review hand-edited a ledger whose `reviewer` was the integer `12345` and
        whose `decided_at` was an object, and both arrived as perfectly
        well-formed strings that satisfied every downstream check. A record that
        was never written by this store is not a record, and the gate consults
        this file.
        """
        value = entry.get(field)
        if not isinstance(value, str):
            raise ValueError(
                f"executable-admission entry field {field!r} must be text, not "
                f"{type(value).__name__}; a malformed decision is refused rather "
                "than coerced into a valid-looking one"
            )
        return value

    @classmethod
    def _record(cls, entry: Mapping[str, Any]) -> AdmissionRecord:
        # Every stored entry is revalidated on the way out, through the same
        # constructor the writer used. A file is editable by anyone who can
        # reach it, and this store is the only thing between an edited file and
        # the gate that consults it.
        if "permission_surface" not in entry:
            # Absence is not the empty declaration. The CLI makes an operator
            # choose between naming permissions and stating with
            # `--no-permissions` that the artifact requests none, and a
            # truncated or hand-edited record that simply drops the field would
            # otherwise arrive as the second of those -- an evidence claim
            # nobody made, on a record that still authorizes execution.
            raise ValueError(
                "executable-admission entry is missing 'permission_surface'; an "
                "absent declaration is not the same claim as an empty one, and a "
                "decision with no recorded surface is not a decision this store "
                "wrote"
            )
        surface = entry["permission_surface"]
        if not isinstance(surface, list) or not all(
            isinstance(item, str) for item in surface
        ):
            # A bare string satisfies `tuple(...)` by decomposing into its
            # characters, which review turned into a sixteen-entry permission
            # surface that looked deliberate.
            raise ValueError(
                "executable-admission entry field 'permission_surface' must be a "
                "list of permission names; a bare string is not one"
            )
        return AdmissionRecord(
            qualified_identity=cls._text(entry, "qualified_identity"),
            content_digest=cls._text(entry, "content_digest"),
            state=cls._text(entry, "state"),
            reviewer=cls._text(entry, "reviewer"),
            permission_surface=tuple(surface),
            decided_at=cls._text(entry, "decided_at"),
            evidence=cls._text(entry, "evidence"),
        )

    def records(self) -> tuple[AdmissionRecord, ...]:
        """Every decision ever recorded here, in the order it was recorded."""
        return tuple(self._record(entry) for entry in self._load())

    @staticmethod
    def _standing(records: Iterable[AdmissionRecord]) -> tuple[AdmissionRecord, ...]:
        """The last decision recorded for each key.

        The history holds every decision, so it holds several for a superseded
        key. `ExecutableAdmissionLedger` refuses duplicates by construction --
        correctly, since it models what stands -- so the history is folded here
        rather than handed to it raw.
        """
        standing: dict[tuple[str, str], AdmissionRecord] = {}
        for record in records:
            standing[(record.qualified_identity, record.content_digest)] = record
        return tuple(standing.values())

    def current(self) -> tuple[AdmissionRecord, ...]:
        """The decision that stands for each `(identity, digest)` key."""
        return self._standing(self.records())

    def ledger(self) -> ExecutableAdmissionLedger:
        """The in-memory ledger the gate consults, built from what stands now.

        This is a **snapshot**. Anything that will write executable bytes on the
        strength of it must take those bytes' decision from `decisions()`
        instead, because "what stood when we started" and "what stands now" are
        different questions and only the second one authorizes a write.
        """
        return ExecutableAdmissionLedger(self.current())

    @contextlib.contextmanager
    def decisions(self) -> Iterator[ExecutableAdmissionLedger]:
        """The decisions that stand right now, held still until the block ends.

        This is the linearization point for admission, and review demonstrated
        why one is needed. An install loaded the ledger, paused in its provider
        fetch, and a `deny` for those exact bytes was recorded and returned
        success in the meantime; the install then projected the artifact anyway,
        because it was still holding the grant it read on the way in. An
        operator whose denial completed had every reason to believe it had taken
        effect.

        The lock is the same one `decide` takes, so a decision recorded during
        this block waits for it, and the decision this block reads is the one
        that stands for the whole of it. It is held across a local write of one
        item's files -- deliberately not across retrieval, which is the slow
        part and needs no decision to be frozen.
        """
        with exclusive_lock(self.path):
            yield self.ledger()

    def audit(
        self, qualified_identity: str | None = None, content_digest_value: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Every recorded decision, each marked with whether it still stands.

        `superseded` is derived from position rather than stored, so it cannot
        disagree with the history it describes.
        """
        records = self.records()
        last_index: dict[tuple[str, str], int] = {}
        for index, record in enumerate(records):
            last_index[(record.qualified_identity, record.content_digest)] = index
        rows = []
        for index, record in enumerate(records):
            key = (record.qualified_identity, record.content_digest)
            if qualified_identity is not None and record.qualified_identity != qualified_identity:
                continue
            if content_digest_value is not None and record.content_digest != content_digest_value:
                continue
            row = record.to_dict()
            row["superseded"] = last_index[key] != index
            rows.append(row)
        return tuple(rows)

    def decide(
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
        """Record one decision, through the in-memory ledger's own rules.

        The validation, the inert refusal, and the refusal to overwrite an
        existing decision without an explicit supersede are not re-implemented
        here: the standing decisions are loaded into an `ExecutableAdmissionLedger`
        and the write goes through `admit`/`refuse`. A second copy of those rules
        is a second place for them to drift.
        """
        if state not in (ADMITTED, REFUSED):
            raise ValueError("an admission decision is either admitted or refused")
        with exclusive_lock(self.path):
            entries = self._load()
            ledger = ExecutableAdmissionLedger(
                self._standing(self._record(entry) for entry in entries)
            )
            write = ledger.admit if state == ADMITTED else ledger.refuse
            record = write(
                qualified_identity,
                content_digest_value,
                library_type=library_type,
                reviewer=reviewer,
                permission_surface=tuple(permission_surface),
                decided_at=decided_at,
                evidence=evidence,
                supersedes=supersedes,
            )
            entries.append(record.to_dict())
            self._save(entries)
        return record


class FirstPartyAdmission:
    """Admission for content the Library itself serves, named byte by byte.

    ADR-0011's executable-admission decision governs an **externally sourced**
    executable artifact: the operator is being asked whether to trust somebody
    else's code. The Library re-materializing its own catalog's workflow specs is
    not that case, and requiring an operator decision for it would not make the
    backfill safer, it would make it impossible.

    This is nevertheless not a blanket exemption, and it is deliberately awkward
    to reach for. It is never a default, it is never inferred from a field on the
    item -- the producer of an item does not get to say it is first-party -- and
    it is constructed with the exact `(identity, digest)` pairs its caller is
    about to install. Anything else is `pending`, so handing this authority to an
    unrelated install waves nothing through.
    """

    def __init__(self, admitted: Mapping[str, str]) -> None:
        self._admitted = {
            str(identity): validated_digest(digest)
            for identity, digest in dict(admitted).items()
        }

    @contextlib.contextmanager
    def decisions(self) -> Iterator["FirstPartyAdmission"]:
        """This authority is a fixed set, so holding it still is nothing."""
        yield self

    def state_for(
        self,
        qualified_identity: str,
        content_digest_value: str | None,
        *,
        library_type: str,
    ) -> str:
        if not is_executable_type(library_type):
            return INERT
        if not content_digest_value:
            return PENDING
        expected = self._admitted.get(qualified_identity)
        if expected is None or expected != validated_digest(content_digest_value):
            return PENDING
        return ADMITTED


def executable_admission_for_item(
    item: NormalizedItem,
    ledger: ExecutableAdmissionLedger,
    contents: Mapping[str, Mapping[str, bytes]],
) -> str:
    """The admission state for one normalized item under one ledger.

    The digest is computed here from the item's content. A caller-supplied
    digest map was the earlier shape and review broke it: the gate checked one
    digest while the mutation wrote other bytes, so the reviewed content and the
    materialized content were never the same object.
    """
    identity = item.qualified_identity()
    files = contents.get(identity)
    digest = content_digest(files) if files else None
    return ledger.state_for(identity, digest, library_type=item.library_type)


def snapshot_contents(
    contents: Mapping[str, Mapping[str, bytes]],
) -> dict[str, Mapping[str, bytes]]:
    """Freeze every item's content once, before anything is digested."""
    return {identity: frozen_content(files) for identity, files in contents.items()}


def gate_resolution(
    items: Sequence[NormalizedItem],
    ledger: ExecutableAdmissionLedger,
    contents: Mapping[str, Mapping[str, bytes]],
    *,
    mutate: Callable[[Mapping[str, Mapping[str, bytes]]], Any] | None = None,
) -> tuple[NormalizedItem, ...]:
    """Resolve a selection only when every executable member is admitted.

    Args:
        items: The selected items, in resolution order.
        ledger: The scope operator's admission decisions.
        contents: Qualified identity to the complete content that will be
            materialized. The gate digests exactly these bytes, so the content
            it checks and the content it hands to `mutate` cannot diverge.
        mutate: The callable that writes. Called once, after the gate passes,
            with the verified content -- not with content of its own choosing.

    Returns:
        The items with their evaluated `executable_admission` state.

    Raises:
        ResolutionRefused: when any executable member is `pending` or `refused`.
            Raised before `mutate` runs, and no member is resolved.
    """
    # Freeze first, then digest, then mutate -- all three against one snapshot.
    verified_contents = snapshot_contents(contents)
    states = [
        (item, executable_admission_for_item(item, ledger, verified_contents))
        for item in items
    ]
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
        verified = MappingProxyType(
            {
                item.qualified_identity(): verified_contents[item.qualified_identity()]
                for item, _ in states
                if item.qualified_identity() in verified_contents
            }
        )
        mutate(verified)
    return resolved


def _with_admission(item: NormalizedItem, state: str) -> NormalizedItem:
    if state not in EXECUTABLE_ADMISSION_STATES:
        raise ValueError(f"unknown executable admission state: {state!r}")
    payload = item.to_dict()
    payload["executable_admission"] = state
    return NormalizedItem.from_dict(payload)


#: Anything that can answer "which decisions stand right now, and hold that
#: answer still while I write" through `decisions()`. A caller about to project
#: executable bytes takes this type rather than a ledger, so a snapshot and a
#: durable store are interchangeable at the call site and only the store pays
#: for the lock.
AdmissionAuthority = Union[
    ExecutableAdmissionLedger, AdmissionLedgerStore, FirstPartyAdmission
]
