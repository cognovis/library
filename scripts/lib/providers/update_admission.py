"""Foreign marketplace updates behind a human gate (ADR-0011, `CL-lt51`).

**Human Decision HD-5, Malte Sussdorff, 2026-08-10.** Model-instructing content
from a non-first-party steward -- a Skill, a Prompt, an Agent, a Standard -- is
admission-required rather than inert, because in an agent harness such content is
*executed by the model*, and its realistic attack is prompt injection delivered
through an upstream update to something somebody already trusted. Trust binds to
the pin, not to the steward.

That decision makes an update a decision point rather than a refresh, and this
module is that decision point. Its shape, and the reason for each part:

| Step | Rule | Why |
|---|---|---|
| Fetch | Into the quarantine under the cache root, never a projection | A fetch is not an install, and an update the operator has not seen must reach no harness path |
| Change set | Against the **pinned and admitted** state, full content on first import | The baseline is what the operator decided about, not merely what is pinned |
| Scan | Deterministic risk markers, pure function of bytes | Recorded evidence a second machine can reproduce |
| Review | A typed verdict bound to the change-set digest | An opinion about *this* change, not a reusable blessing |
| Recommendation | Advice, computed, never a transition | Written next to the decision, never into it |
| Decision | The human, and only the human | See below |

Four failures this module is built to make impossible, each of which looks
harmless in a happy-path test:

- **The reviewer becoming the decider.** No verdict value adopts anything.
  `recommendation_for` computes advice; `approve_packet` requires an operator, a
  reason, and -- when it disagrees with the advice -- an explicit
  `against_recommendation`. A packet's `decision` is `None` until a human writes
  one, and it is stored in a separate append-only record so the packet itself
  stays the immutable evidence it was.
- **A clean scan skipping the gate.** There is no path from "no markers" to
  "adopted". A scan with no findings and a `clean` verdict produces the *string*
  `adopt` in a field an operator reads.
- **An unavailable reviewer becoming a skipped review.** `ReviewUnavailable` is
  recorded as `review_status: unavailable` and forces the recommendation to
  `reject`. The one thing it must never do is leave the packet looking reviewed.
- **Approving one thing and installing another.** Approval installs the bytes
  stored in the packet, re-digested against the packet's own record first. It
  never re-fetches: upstream can move between the review and the decision, and a
  re-fetch would install content nobody read.

**The agent boundary (`.dcg/packs/library-pin-raise-guard.yaml`).** An agent may
prepare a packet -- fetch, scan, review, summarize -- and may not approve one.
The guard blocks the approval verb and every admission grant in an agent shell,
and `DecisionPacket.approval_command` renders the exact command the agent hands
its human instead. The two halves are one control: the agent is stopped *and*
told what to say.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .cache_transaction import (
    CompletenessEvidence,
    install_foreign_item,
)
from .classification import FOREIGN, requires_admission
from .contract import FetchedFile, FetchedItem
from .executable_admission import (
    ADMITTED,
    content_digest,
    frozen_content,
    validated_digest,
    validated_operator,
    validated_reason,
)
from .foreign_cache import TofuPinStore, normalized_member_path
from .inventory import NormalizedItem
from .offline import OfflineRefusal, ResolutionEvidence
from .state_files import atomic_write_text, exclusive_lock
from .update_scanner import ScanReport, merged_counts, scan_content

#: The recorded forms this module owns.
PACKET_SCHEMA = "cognovis.marketplace-update-packet.v1"
REVIEW_VERDICT_SCHEMA = "cognovis.marketplace-update-review-verdict.v1"
DECISION_LEDGER_SCHEMA = "cognovis.marketplace-update-decisions.v1"

#: How one item changed between the admitted baseline and the fetched state.
CHANGES = ("added", "modified", "removed")

#: What the packet recommends. Advice, in a field beside the decision.
RECOMMENDATIONS = ("adopt", "partial", "reject")

#: What a reviewer may answer. Deliberately three values and no numeric score: a
#: score invites a threshold, and a threshold is an automatic decision.
REVIEW_VERDICTS = ("clean", "concerns", "reject")

#: Whether a reviewer answered at all. `unavailable` is a first-class outcome
#: rather than an exception the caller may swallow.
REVIEW_STATUSES = ("completed", "unavailable")

#: What a human recorded about a packet.
DECISIONS = ("approved", "rejected")

#: The CLI words, written down once so the guard pack, the rendered approval
#: command, and the shipped parser cannot drift apart.
UPDATE_COMMAND = "marketplace"
UPDATE_VERB = "update"
UPDATE_APPROVE_VERB = "update-approve"
UPDATE_REJECT_VERB = "update-reject"
UPDATE_SHOW_VERB = "update-show"
UPDATE_LIST_VERB = "update-list"

#: What a rendered approval command puts where the human's own words belong.
OPERATOR_PLACEHOLDER = "<your operator identity>"
REASON_PLACEHOLDER = "<what you read in this packet and why you accept it>"

#: How much of a unified diff a packet carries per item before it is truncated.
#: The full post-update content is stored beside it either way, so truncating the
#: diff loses nothing an operator cannot get -- it only keeps the summary a
#: summary.
DIFF_LINE_LIMIT = 400


class UpdateFetchFailed(RuntimeError):
    """The update could not retrieve the current upstream state.

    No packet exists after this, and nothing changed. A half-fetched update is
    the one state that would let an operator decide about content that is partly
    the old revision, so the fetch is staged and published as a whole or not at
    all.
    """


class AlreadyDecided(ValueError):
    """This packet already carries a human decision.

    A `ValueError` so that the CLI's existing refusal path reports it, and a
    named type so that the approval flow can tell "somebody decided this while I
    was working" apart from every other way an approval can be refused.
    """

    def __init__(self, packet_id: str, previous: Mapping[str, Any]) -> None:
        super().__init__(
            f"update packet {packet_id} was already {previous.get('decision')} by "
            f"{previous.get('operator')} at {previous.get('decided_at')}; re-run the "
            "update to produce a fresh packet for a fresh decision"
        )
        self.packet_id = packet_id
        self.previous = dict(previous)


class ReviewUnavailable(RuntimeError):
    """The review stage could not produce a verdict.

    Not an error the caller handles by proceeding as though the review passed.
    `prepare_update` records it on the packet and the recommendation becomes
    `reject`, because "we could not get it reviewed" must never read the same as
    "it was reviewed and was fine".
    """


# -- the change set -----------------------------------------------------------


@dataclass(frozen=True)
class ChangedItem:
    """One item's difference between the admitted baseline and upstream now."""

    qualified_identity: str
    upstream_id: str
    library_type: str
    library_name: str
    change: str
    pinned_digest: str | None
    fetched_digest: str | None
    byte_size: int
    diff: str
    #: The complete post-update content. `None` only for a removal, which has
    #: none. ADR-0011 requires the whole item and not just the change: a line
    #: that is dangerous only next to a line it did not change with is invisible
    #: to a diff.
    content: Mapping[str, bytes] | None = None

    def __post_init__(self) -> None:
        if self.change not in CHANGES:
            raise ValueError(f"a change is one of {list(CHANGES)}, got {self.change!r}")
        if self.change != "removed" and not self.content:
            raise ValueError(
                "a changed item carries its complete post-update content; a packet "
                "that shows only a diff cannot be reviewed for context"
            )
        if self.content is not None:
            object.__setattr__(self, "content", frozen_content(self.content))
        if self.fetched_digest is not None:
            validated_digest(self.fetched_digest)
        if self.pinned_digest is not None:
            validated_digest(self.pinned_digest)

    def summary(self) -> dict[str, Any]:
        """The item as the packet records it, without its bytes."""
        return {
            "qualified_identity": self.qualified_identity,
            "upstream_id": self.upstream_id,
            "library_type": self.library_type,
            "library_name": self.library_name,
            "change": self.change,
            "pinned_digest": self.pinned_digest,
            "fetched_digest": self.fetched_digest,
            "byte_size": self.byte_size,
            "member_count": len(self.content or {}),
            "diff": self.diff,
        }


@dataclass(frozen=True)
class ChangeSet:
    """Everything that differs, for one provider, at one observation."""

    provider_identity: str
    observed_at: str
    first_import: bool
    items: tuple[ChangedItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))

    def digest(self) -> str:
        """The identity of this change set, for binding a verdict to it.

        Covers the provider, every changed identity, its direction of change, and
        both digests. A reviewer's verdict names this value, so a verdict about a
        different change -- or about the same items in a different state -- is
        refused rather than reused.
        """
        payload = json.dumps(
            {
                "provider_identity": self.provider_identity,
                "first_import": self.first_import,
                "items": [
                    {
                        "qualified_identity": item.qualified_identity,
                        "change": item.change,
                        "pinned_digest": item.pinned_digest,
                        "fetched_digest": item.fetched_digest,
                    }
                    for item in sorted(self.items, key=lambda entry: entry.qualified_identity)
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def identities(self) -> tuple[str, ...]:
        return tuple(sorted(item.qualified_identity for item in self.items))


def _unified_diff(before: Mapping[str, bytes] | None, after: Mapping[str, bytes]) -> str:
    """A readable diff, or a stated reason there is none.

    Binary members are named rather than rendered. A diff of undecodable bytes is
    noise that pushes the members a human could have read off the screen.
    """
    lines: list[str] = []
    paths = sorted(set(after) | set(before or {}))
    for path in paths:
        old = (before or {}).get(path)
        new = after.get(path)
        try:
            old_text = old.decode("utf-8").splitlines(keepends=True) if old is not None else []
            new_text = new.decode("utf-8").splitlines(keepends=True) if new is not None else []
        except UnicodeDecodeError:
            lines.append(f"--- {path}\n+++ {path}\n(binary member; compare by digest)\n")
            continue
        lines.extend(
            difflib.unified_diff(
                old_text,
                new_text,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            )
        )
    if len(lines) > DIFF_LINE_LIMIT:
        kept = lines[:DIFF_LINE_LIMIT]
        kept.append(
            f"... diff truncated after {DIFF_LINE_LIMIT} lines; the packet stores the "
            "complete post-update content of every changed item\n"
        )
        lines = kept
    return "".join(lines)


def build_change_set(
    *,
    provider_identity: str,
    observed_at: str,
    fetched: Mapping[str, tuple[NormalizedItem, Mapping[str, bytes]]],
    baseline: Mapping[str, tuple[str, Mapping[str, bytes] | None]],
) -> ChangeSet:
    """Compare the fetched state against the admitted baseline.

    Args:
        fetched: Qualified identity to `(item, complete content)` as retrieved.
        baseline: Qualified identity to `(admitted digest, admitted content or
            None)`. Only identities the operator has actually *decided* about
            belong here; a pin with no standing admission is not a baseline,
            because the operator never accepted those bytes and there is nothing
            for the packet to present a change against.

    Returns:
        The change set. `first_import` is true when nothing in the fetched set
        has an admitted baseline, which is when the packet has to carry whole
        items rather than differences.
    """
    items: list[ChangedItem] = []
    for identity in sorted(fetched):
        item, content = fetched[identity]
        digest = content_digest(content)
        recorded = baseline.get(identity)
        if recorded is not None and recorded[0] == digest:
            continue
        items.append(
            ChangedItem(
                qualified_identity=identity,
                upstream_id=item.upstream_id,
                library_type=item.library_type,
                library_name=item.library_name,
                change="modified" if recorded is not None else "added",
                pinned_digest=recorded[0] if recorded is not None else None,
                fetched_digest=digest,
                byte_size=sum(len(value) for value in content.values()),
                diff=_unified_diff(recorded[1] if recorded is not None else None, content),
                content=dict(content),
            )
        )
    for identity in sorted(set(baseline) - set(fetched)):
        recorded = baseline[identity]
        items.append(
            ChangedItem(
                qualified_identity=identity,
                upstream_id=identity.partition("#")[2],
                library_type="unknown",
                library_name=identity.rsplit("/", 1)[-1],
                change="removed",
                pinned_digest=recorded[0],
                fetched_digest=None,
                byte_size=0,
                diff="",
                content=None,
            )
        )
    return ChangeSet(
        provider_identity=provider_identity,
        observed_at=observed_at,
        first_import=not any(entry.pinned_digest for entry in items) and not baseline,
        items=tuple(items),
    )


def admitted_baseline(
    *,
    identities: Sequence[str],
    pin_store: TofuPinStore,
    ledger,
    library_types: Mapping[str, str],
) -> dict[str, tuple[str, None]]:
    """The state the operator has both pinned **and** admitted.

    A pin alone is not a baseline. A pin records what was first observed; an
    admitted decision records what the operator accepted. Presenting an update as
    a *difference* against bytes nobody decided about would hide the part of the
    content that was never reviewed inside a diff's unchanged context, which is
    the review-quality failure this whole flow exists to avoid. An identity with a
    pin and no standing admission therefore appears in the packet as a first
    import, whole.
    """
    baseline: dict[str, tuple[str, None]] = {}
    for identity in identities:
        pin = pin_store.pin_for(identity)
        if pin is None:
            continue
        digest = pin.normalized_content_digest
        library_type = library_types.get(identity, "unknown")
        if not requires_admission(library_type, FOREIGN):
            # Inert content needs no decision, so what is pinned *is* the
            # baseline: there was never a decision to be missing.
            baseline[identity] = (digest, None)
            continue
        state = ledger.state_for(
            identity, digest, library_type=library_type, stewardship=FOREIGN
        )
        if state != ADMITTED:
            continue
        baseline[identity] = (digest, None)
    return baseline


# -- the review stage ---------------------------------------------------------


@dataclass(frozen=True)
class ReviewFinding:
    """One thing a reviewer wants the deciding human to see."""

    identifier: str
    severity: str
    qualified_identity: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "severity": self.severity,
            "qualified_identity": self.qualified_identity,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewFinding":
        return cls(
            identifier=str(data["id"]),
            severity=str(data["severity"]),
            qualified_identity=str(data.get("qualified_identity") or ""),
            detail=str(data["detail"]),
        )


@dataclass(frozen=True)
class ReviewVerdict:
    """One reviewer's answer about exactly one change set."""

    reviewer: str
    verdict: str
    change_set_digest: str
    summary: str
    reviewed_at: str
    findings: tuple[ReviewFinding, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in REVIEW_VERDICTS:
            raise ValueError(
                f"a review verdict is one of {list(REVIEW_VERDICTS)}, got {self.verdict!r}"
            )
        for name in ("reviewer", "summary", "reviewed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ReviewVerdict.{name} is required")
        validated_digest(self.change_set_digest)
        object.__setattr__(self, "findings", tuple(self.findings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REVIEW_VERDICT_SCHEMA,
            "reviewer": self.reviewer,
            "verdict": self.verdict,
            "change_set_digest": self.change_set_digest,
            "summary": self.summary,
            "reviewed_at": self.reviewed_at,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewVerdict":
        if data.get("schema") != REVIEW_VERDICT_SCHEMA:
            raise ValueError(
                f"unexpected review verdict schema {data.get('schema')!r}; expected "
                f"{REVIEW_VERDICT_SCHEMA}"
            )
        return cls(
            reviewer=str(data["reviewer"]),
            verdict=str(data["verdict"]),
            change_set_digest=str(data["change_set_digest"]),
            summary=str(data["summary"]),
            reviewed_at=str(data["reviewed_at"]),
            findings=tuple(ReviewFinding.from_dict(entry) for entry in data.get("findings", ())),
        )

    def digest(self) -> str:
        """A content digest of this verdict, so the ledger can bind evidence."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: What a review stage is: something that answers about one change set, given a
#: file holding the prompt that describes it. Injected rather than imported, so
#: the transport -- `acpx-dispatch`, another adapter, or a stub -- stays outside
#: this module's contract, exactly as it stays outside the Bead loop's.
ReviewDispatch = Callable[[ChangeSet, Path], ReviewVerdict]


def validated_review_verdict(value: Any, *, change_set_digest: str) -> ReviewVerdict:
    """A verdict about **this** change set, or a refusal.

    Subject drift is the failure that makes a review stage decorative: a verdict
    produced for an earlier fetch, replayed against a newer one, is a blessing
    for content the reviewer never saw.
    """
    verdict = value if isinstance(value, ReviewVerdict) else ReviewVerdict.from_dict(value)
    if verdict.change_set_digest != change_set_digest:
        raise ValueError(
            "the reviewer's verdict names a different change set: recorded "
            f"{verdict.change_set_digest}, this update is {change_set_digest}"
        )
    return verdict


def review_prompt(change_set: ChangeSet, packet_id: str) -> str:
    """The prompt text a review stage is handed, as a file.

    Plain code-review language on purpose. Adversarial framing -- "attack",
    "bypass", "proof of concept" -- has repeatedly tripped provider content
    filters mid-run on this repository's review dispatches, and a refused review
    is an unavailable one.
    """
    lines = [
        f"# Review of marketplace update {packet_id}",
        "",
        f"Source: {change_set.provider_identity}",
        f"Observed at: {change_set.observed_at}",
        f"Change set: {change_set.digest()}",
        "",
        "This is content a coding agent loads into a model's context and follows as",
        "instructions. Read the complete post-update body of every item below, not",
        "only the diff, and answer whether adopting it would change what the agent",
        "does in ways the operator would not expect.",
        "",
        "Answer with one JSON object of this exact shape:",
        "",
        "```json",
        json.dumps(
            {
                "schema": REVIEW_VERDICT_SCHEMA,
                "reviewer": "<your model id>",
                "verdict": "clean | concerns | reject",
                "change_set_digest": change_set.digest(),
                "summary": "<one paragraph>",
                "reviewed_at": "<ISO-8601 instant with offset>",
                "findings": [
                    {
                        "id": "F1",
                        "severity": "blocking | advisory",
                        "qualified_identity": "<the item>",
                        "detail": "<what you found and where>",
                    }
                ],
            },
            indent=2,
        ),
        "```",
        "",
    ]
    for item in change_set.items:
        lines += [
            f"## {item.qualified_identity} ({item.change})",
            "",
            f"- type: {item.library_type}",
            f"- previous digest: {item.pinned_digest or 'none (first import)'}",
            f"- new digest: {item.fetched_digest or 'none (removed upstream)'}",
            f"- size: {item.byte_size} bytes across {len(item.content or {})} member(s)",
            "",
        ]
        if item.diff:
            lines += ["### Change", "", "```diff", item.diff.rstrip("\n"), "```", ""]
        for path in sorted(item.content or {}):
            body = item.content[path]
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                text = f"({len(body)} bytes that are not valid UTF-8 text)"
            lines += [f"### Full content after update: {path}", "", "```", text, "```", ""]
    return "\n".join(lines)


# -- the recommendation -------------------------------------------------------


def recommendation_for(
    *,
    change_set: ChangeSet,
    scan_counts: Mapping[str, int],
    review_status: str,
    verdict: ReviewVerdict | None,
) -> tuple[str, str]:
    """Advice, and the sentence that explains it. Never a transition.

    The ordering is deliberately conservative and the reasons are written out,
    because the value of this function is that a human can disagree with it
    knowing exactly what it weighed.
    """
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"a review status is one of {list(REVIEW_STATUSES)}")
    if not change_set.items:
        return (
            "reject",
            "Nothing changed: the fetched state matches the admitted baseline for "
            "every item, so there is nothing to adopt.",
        )
    if review_status != "completed" or verdict is None:
        return (
            "reject",
            "No reviewer verdict was produced for this change set. A review that "
            "could not run is not a review that passed, so nothing is recommended "
            "for adoption; re-run the update when the reviewer is reachable, or "
            "decide on the scanner findings and the full content yourself.",
        )
    if verdict.verdict == "reject":
        return (
            "reject",
            f"The reviewer answered {verdict.verdict!r}: {verdict.summary}",
        )
    total_markers = sum(scan_counts.values())
    if verdict.verdict == "concerns" or total_markers:
        rendered = ", ".join(f"{name} x{count}" for name, count in sorted(scan_counts.items()))
        return (
            "partial",
            (
                f"The reviewer answered {verdict.verdict!r}"
                + (f" and the scanner flagged {rendered}" if rendered else "")
                + ". Adopt per item after reading the full post-update content of "
                "each one; the scanner reduces risk and does not detect intent, so "
                "its silence about an item is not a finding in that item's favour."
            ),
        )
    return (
        "adopt",
        (
            "The reviewer answered 'clean' and the scanner flagged nothing. This is "
            "a recommendation and not a decision: the scanner is risk reduction "
            "rather than detection, and adopting is still your act."
        ),
    )


# -- the packet ---------------------------------------------------------------


@dataclass(frozen=True)
class DecisionPacket:
    """Everything a human needs to decide one update, and nothing that decides it."""

    packet_id: str
    provider_identity: str
    created_at: str
    change_set: ChangeSet
    scans: Mapping[str, ScanReport]
    review: ReviewVerdict | None
    review_status: str
    review_unavailable_detail: str
    recommendation: str
    recommendation_basis: str
    #: Always `None` on a packet. The human's decision lives in the append-only
    #: decision record beside it, so the packet stays the immutable evidence the
    #: decision was made against.
    decision: None = None

    def __post_init__(self) -> None:
        if self.recommendation not in RECOMMENDATIONS:
            raise ValueError(f"a recommendation is one of {list(RECOMMENDATIONS)}")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"a review status is one of {list(REVIEW_STATUSES)}")
        if self.decision is not None:
            raise ValueError(
                "a decision packet never carries a decision; the human's decision is "
                "recorded separately so the packet stays the evidence it was decided "
                "against"
            )
        object.__setattr__(self, "scans", dict(self.scans))

    @property
    def scan_counts(self) -> dict[str, int]:
        return merged_counts(list(self.scans.values()))

    def scan_digest_for(self, qualified_identity: str) -> str:
        return self.scans[qualified_identity].digest()

    def fingerprint(self) -> str:
        """What makes this packet *this* packet, independent of its id.

        The change set, the scan of each item, and the reviewer's verdict. Two
        runs over an unchanged upstream state agree on the first and can differ
        on the last, which is why the id is allocated against this value rather
        than against the change set alone.
        """
        payload = json.dumps(
            {
                "change_set": self.change_set.digest(),
                "scans": {
                    identity: report.digest()
                    for identity, report in sorted(self.scans.items())
                },
                "review": self.review.digest() if self.review is not None else None,
                "review_status": self.review_status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def approval_command(self) -> str:
        """The exact command a human runs to approve this packet.

        Rendered from the CLI words this module owns, for the same reason the
        executable-admission refusal renders its remedy: a diagnostic that names
        a command is useful only while the command still exists. It is also the
        second half of the agent guard -- an agent whose approval attempt the dcg
        pack blocks hands this string to its human unchanged.
        """
        import shlex

        return " ".join(
            [
                "library",
                UPDATE_COMMAND,
                UPDATE_APPROVE_VERB,
                self.packet_id,
                "--operator",
                shlex.quote(OPERATOR_PLACEHOLDER),
                "--reason",
                shlex.quote(REASON_PLACEHOLDER),
            ]
        )

    def rejection_command(self) -> str:
        """The exact command a human runs to reject this packet."""
        import shlex

        return " ".join(
            [
                "library",
                UPDATE_COMMAND,
                UPDATE_REJECT_VERB,
                self.packet_id,
                "--operator",
                shlex.quote(OPERATOR_PLACEHOLDER),
                "--reason",
                shlex.quote(REASON_PLACEHOLDER),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PACKET_SCHEMA,
            "packet_id": self.packet_id,
            "fingerprint": self.fingerprint(),
            "provider_identity": self.provider_identity,
            "created_at": self.created_at,
            "change_set": {
                "digest": self.change_set.digest(),
                "provider_identity": self.change_set.provider_identity,
                "observed_at": self.change_set.observed_at,
                "first_import": self.change_set.first_import,
                "items": [item.summary() for item in self.change_set.items],
            },
            "scans": {
                identity: report.to_dict() for identity, report in sorted(self.scans.items())
            },
            "scan_counts": self.scan_counts,
            "review": self.review.to_dict() if self.review is not None else None,
            "review_status": self.review_status,
            "review_unavailable_detail": self.review_unavailable_detail,
            "recommendation": self.recommendation,
            "recommendation_basis": self.recommendation_basis,
            "decision": None,
            "approval_command": self.approval_command(),
            "rejection_command": self.rejection_command(),
        }


def _packet_id(provider_identity: str, change_set: ChangeSet) -> str:
    """A deterministic name for one change set from one provider.

    Deterministic so that re-running an update over the same upstream state
    republishes the same packet rather than accumulating near-duplicates an
    operator has to tell apart.
    """
    slug = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in provider_identity.lower()
    ).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:48] or "provider"
    return f"{slug}@{change_set.digest()[len('sha256:') : len('sha256:') + 16]}"


# -- the quarantine store -----------------------------------------------------


def _verify_packet(
    packet: "DecisionPacket",
    contents: Mapping[str, Mapping[str, bytes]],
    *,
    recorded: Mapping[str, Any],
) -> None:
    """Every claim a packet makes about itself, checked against its own bytes.

    Wave-1 review edited a stored packet so that its scanner report named
    `sha256:aaaa...` and carried no markers, and its reviewer verdict named
    `sha256:bbbb...`, while the item bytes and the item digest were untouched.
    Both loaded, the approval succeeded, and the admission ledger then recorded
    those two digests as the "digest-bound scanner and verdict evidence" for
    content neither of them had looked at. The packet was evidence in name only.

    The checks below are the ones that make a packet self-verifying, and each is
    a separate way the file can lie:

    - the recorded change-set digest matches the change set that was rebuilt;
    - each item's stored bytes reproduce the digest the item claims;
    - each scan names the bytes it sat next to **and recomputes from them**, so a
      report whose findings were deleted is refused rather than believed;
    - the verdict names this change set, not another one;
    - the fingerprint matches, so `available_packet_id` cannot be steered.

    A malformed packet is refused, never repaired. That is the same rule
    `AdmissionLedgerStore` applies to a hand-edited ledger, and for the same
    reason: this file is what stands between an edited disk and an operator
    believing a decision was reviewed.
    """
    if recorded.get("change_set", {}).get("digest") != packet.change_set.digest():
        raise ValueError(
            f"update packet {packet.packet_id} records change-set digest "
            f"{recorded.get('change_set', {}).get('digest')!r}, but its items "
            f"describe {packet.change_set.digest()}; a packet that disagrees with "
            "itself is refused rather than reconciled"
        )
    for item in packet.change_set.items:
        identity = item.qualified_identity
        if item.change == "removed":
            continue
        stored = contents.get(identity)
        if not stored:
            raise ValueError(
                f"update packet {packet.packet_id} holds no content for {identity}, "
                "which its change set says was added or modified"
            )
        actual = content_digest(stored)
        if actual != item.fetched_digest:
            raise ValueError(
                f"the stored content for {identity} does not reproduce the digest "
                f"packet {packet.packet_id} recorded: packet {item.fetched_digest}, "
                f"stored {actual}"
            )
        report = packet.scans.get(identity)
        if report is None:
            raise ValueError(
                f"update packet {packet.packet_id} carries no scan for {identity}; "
                "an unscanned item is not evidence a decision can be recorded "
                "against"
            )
        if report.content_digest != actual:
            raise ValueError(
                f"the scan recorded for {identity} names {report.content_digest} and "
                f"the stored content is {actual}; a scan of other bytes is not this "
                "item's scan"
            )
        if report != scan_content(stored):
            raise ValueError(
                f"the scan recorded for {identity} does not recompute from the "
                "stored content; the scanner is a pure function of the bytes, so a "
                "report that cannot be reproduced was edited"
            )
    if packet.review is not None and (
        packet.review.change_set_digest != packet.change_set.digest()
    ):
        raise ValueError(
            f"the reviewer verdict in packet {packet.packet_id} names change set "
            f"{packet.review.change_set_digest}, and this packet is "
            f"{packet.change_set.digest()}; a verdict about another change is not a "
            "review of this one"
        )
    if recorded.get("fingerprint") != packet.fingerprint():
        raise ValueError(
            f"update packet {packet.packet_id} records fingerprint "
            f"{recorded.get('fingerprint')!r} and computes {packet.fingerprint()}"
        )


class UpdatePacketStore:
    """Packets, their content, and the decisions recorded about them.

    It lives under the cache root, because a fetched update is cached content:
    lawfully retrieved bytes that no harness path receives. It is deliberately
    *not* the object store -- an object there is a thing the Library holds for an
    install, and an unapproved update is not that. Keeping them apart is also
    what makes rejection free: a rejected packet's bytes never entered the store
    that installs from, so there is nothing to unwind.

    Publication is a two-phase write, in the shape `ObjectStore` established: the
    packet is assembled under a staging directory and moved into place with a
    single rename, so a failed fetch leaves either nothing or a whole packet.
    """

    PACKETS_DIRECTORY = "packets"
    STAGING_DIRECTORY = "staging"
    CONTENT_DIRECTORY = "content"
    PACKET_FILE = "packet.json"
    PROMPT_FILE = "review-prompt.md"
    DECISIONS_FILE = "decisions.json"

    def __init__(self, base: Path) -> None:
        self.base = Path(base)

    @property
    def packets_root(self) -> Path:
        return self.base / self.PACKETS_DIRECTORY

    @property
    def staging_root(self) -> Path:
        return self.base / self.STAGING_DIRECTORY

    @property
    def decisions_path(self) -> Path:
        return self.base / self.DECISIONS_FILE

    def path_for(self, packet_id: str) -> Path:
        """One packet's directory, proven to stay beneath the quarantine root."""
        candidate = (self.packets_root / packet_id).resolve()
        root = self.packets_root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(
                f"packet id {packet_id!r} resolves outside the update quarantine: "
                f"{candidate}"
            )
        return candidate

    def _content_root(self, packet_id: str, qualified_identity: str) -> Path:
        # The identity is a URL-ish string, so it is hashed rather than used as a
        # path. A provider that names an item `../../etc` gets a hex directory.
        key = hashlib.sha256(qualified_identity.encode("utf-8")).hexdigest()[:32]
        return self.path_for(packet_id) / self.CONTENT_DIRECTORY / key

    def content_path(self, packet_id: str, qualified_identity: str, member: str) -> Path:
        return self._content_root(packet_id, qualified_identity) / normalized_member_path(member)

    def packet_ids(self) -> tuple[str, ...]:
        if not self.packets_root.is_dir():
            return ()
        return tuple(
            sorted(
                entry.name
                for entry in self.packets_root.iterdir()
                if (entry / self.PACKET_FILE).is_file()
            )
        )

    def staged_entries(self) -> tuple[str, ...]:
        if not self.staging_root.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in self.staging_root.iterdir()))

    def available_packet_id(self, base_id: str, fingerprint: str) -> str:
        """A packet id that will not overwrite somebody else's evidence.

        Wave-1 review filed three ways the first version of this store lost
        evidence, and they share one cause: a deterministic id was treated as
        permission to replace what already lived there. It is not. Re-running an
        update over an unchanged upstream state produces the same change set and
        therefore the same base id, but *not* the same packet -- the reviewer
        answers again, and the second answer would have silently replaced the
        first under a packet id somebody may already have rejected.

        So: an existing packet with the same id and the same fingerprint is that
        packet, and this returns it unchanged. An existing packet with a
        different fingerprint is different evidence, and this allocates a fresh
        id beside it rather than over it.
        """
        candidate = base_id
        suffix = 1
        while True:
            existing = self.path_for(candidate) / self.PACKET_FILE
            if not existing.is_file():
                return candidate
            try:
                stored = json.loads(existing.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = {}
            if stored.get("fingerprint") == fingerprint:
                return candidate
            suffix += 1
            candidate = f"{base_id}-{suffix}"

    def write(
        self,
        packet: DecisionPacket,
        contents: Mapping[str, Mapping[str, bytes]],
        prompt: str,
    ) -> Path:
        """Publish one packet atomically, or publish nothing.

        Never deletes an existing packet. `available_packet_id` has already
        guaranteed that this id is either free or holds this exact packet, so a
        collision here is a concurrent writer that got there first -- and its
        packet is as good as ours, since the id binds to the fingerprint.
        """
        staged = self.staging_root / f"{os.getpid()}-{uuid.uuid4().hex}"
        try:
            content_root = staged / self.CONTENT_DIRECTORY
            content_root.mkdir(parents=True)
            for identity, files in sorted(contents.items()):
                key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
                for member, payload in sorted(files.items()):
                    destination = content_root / key / normalized_member_path(member)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(bytes(payload))
                (content_root / key / "identity.txt").write_text(identity, encoding="utf-8")
            (staged / self.PACKET_FILE).write_text(
                json.dumps(packet.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (staged / self.PROMPT_FILE).write_text(prompt, encoding="utf-8")
            final = self.path_for(packet.packet_id)
            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(staged, final)
            except OSError:
                if not (final / self.PACKET_FILE).is_file():
                    raise
                # Somebody published this exact packet while we were staging it.
                # Theirs is ours: the id was allocated against the fingerprint.
            return final
        finally:
            shutil.rmtree(staged, ignore_errors=True)
            if self.staging_root.is_dir() and not any(self.staging_root.iterdir()):
                self.staging_root.rmdir()

    def load(self, packet_id: str) -> tuple[DecisionPacket, dict[str, dict[str, bytes]]]:
        """One packet and the content it recorded, read back from disk."""
        directory = self.path_for(packet_id)
        payload_path = directory / self.PACKET_FILE
        if not payload_path.is_file():
            raise KeyError(f"no update packet {packet_id!r} in {self.packets_root}")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if payload.get("schema") != PACKET_SCHEMA:
            raise ValueError(
                f"unexpected update packet schema {payload.get('schema')!r}; expected "
                f"{PACKET_SCHEMA}"
            )
        contents: dict[str, dict[str, bytes]] = {}
        content_root = directory / self.CONTENT_DIRECTORY
        if content_root.is_dir():
            for key_dir in sorted(content_root.iterdir()):
                marker = key_dir / "identity.txt"
                if not marker.is_file():
                    continue
                identity = marker.read_text(encoding="utf-8")
                files: dict[str, bytes] = {}
                for path in sorted(key_dir.rglob("*")):
                    if path.is_file() and path.name != "identity.txt":
                        files[str(path.relative_to(key_dir))] = path.read_bytes()
                contents[identity] = files

        items = []
        for entry in payload["change_set"]["items"]:
            identity = entry["qualified_identity"]
            items.append(
                ChangedItem(
                    qualified_identity=identity,
                    upstream_id=entry["upstream_id"],
                    library_type=entry["library_type"],
                    library_name=entry["library_name"],
                    change=entry["change"],
                    pinned_digest=entry["pinned_digest"],
                    fetched_digest=entry["fetched_digest"],
                    byte_size=entry["byte_size"],
                    diff=entry["diff"],
                    content=contents.get(identity) if entry["change"] != "removed" else None,
                )
            )
        change_set = ChangeSet(
            provider_identity=payload["change_set"]["provider_identity"],
            observed_at=payload["change_set"]["observed_at"],
            first_import=payload["change_set"]["first_import"],
            items=tuple(items),
        )
        packet = DecisionPacket(
            packet_id=payload["packet_id"],
            provider_identity=payload["provider_identity"],
            created_at=payload["created_at"],
            change_set=change_set,
            scans={
                identity: ScanReport.from_dict(report)
                for identity, report in payload["scans"].items()
            },
            review=(
                ReviewVerdict.from_dict(payload["review"])
                if payload.get("review") is not None
                else None
            ),
            review_status=payload["review_status"],
            review_unavailable_detail=payload.get("review_unavailable_detail", ""),
            recommendation=payload["recommendation"],
            recommendation_basis=payload["recommendation_basis"],
        )
        _verify_packet(packet, contents, recorded=payload)
        return packet, contents

    # -- decisions ------------------------------------------------------------

    def decisions(self, packet_id: str | None = None) -> tuple[dict[str, Any], ...]:
        """Every decision recorded here, oldest first."""
        if not self.decisions_path.is_file():
            return ()
        payload = json.loads(self.decisions_path.read_text(encoding="utf-8"))
        if payload.get("schema") != DECISION_LEDGER_SCHEMA:
            raise ValueError(
                f"unexpected update-decision schema {payload.get('schema')!r}; a "
                "malformed decision record is refused rather than read as empty"
            )
        rows = tuple(payload.get("decisions") or ())
        if packet_id is None:
            return rows
        return tuple(row for row in rows if row.get("packet_id") == packet_id)

    def record_decision(
        self,
        *,
        packet_id: str,
        decision: str,
        operator: str,
        reason: str,
        decided_at: str,
        change_set_digest: str,
        detail: Mapping[str, Any] | None = None,
        allow_second: bool = False,
    ) -> dict[str, Any]:
        """Append one human decision about one packet, and only one.

        Append-only for the reason the admission ledger is: somebody later needs
        to see that this packet was rejected on Monday and by whom, even after a
        newer packet for the same source was approved on Tuesday.

        **The check and the append are one locked operation.** Wave-1 review ran
        two synchronized rejections of the same packet and both succeeded,
        because the "has this been decided?" read happened outside the lock the
        append took. Two decision rows for one packet is not an audit trail, it
        is two people each believing theirs was the decision.

        Args:
            allow_second: Only for recording what an interrupted approval managed
                to adopt before it failed. It never bypasses the check for a
                fresh decision; see `claim_decision`.
        """
        if decision not in DECISIONS:
            raise ValueError(f"a packet decision is one of {list(DECISIONS)}")
        row = {
            "packet_id": packet_id,
            "decision": decision,
            "operator": validated_operator(operator),
            "reason": validated_reason(reason),
            "decided_at": decided_at,
            "change_set_digest": change_set_digest,
            "detail": dict(detail or {}),
        }
        with exclusive_lock(self.decisions_path):
            existing = list(self.decisions())
            if not allow_second:
                previous = next(
                    (
                        entry
                        for entry in reversed(existing)
                        if entry.get("packet_id") == packet_id
                    ),
                    None,
                )
                if previous is not None:
                    raise AlreadyDecided(packet_id, previous)
            existing.append(row)
            atomic_write_text(
                self.decisions_path,
                json.dumps(
                    {"schema": DECISION_LEDGER_SCHEMA, "decisions": existing},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        return row


# -- preparing an update ------------------------------------------------------


def prepare_update(
    *,
    provider,
    items: Sequence[NormalizedItem],
    state,
    review: ReviewDispatch,
    observed_at: str,
    selector: str | None = None,
) -> DecisionPacket:
    """Fetch, quarantine, scan, review, and summarize one provider's update.

    Nothing here writes a pin, an admission decision, a receipt, or a projected
    byte. The only durable effect is the packet, and a failure before it is
    published leaves not even that.

    Raises:
        UpdateFetchFailed: when any item's retrieval did not complete. The whole
            update aborts: a packet built from the items that happened to arrive
            would present a partial upstream state as the upstream state.
        ValueError: when the reviewer answers about a different change set.
    """
    store = UpdatePacketStore(state.update_root())
    fetched: dict[str, tuple[NormalizedItem, dict[str, bytes]]] = {}
    for item in items:
        identity = item.qualified_identity()
        try:
            result = provider.fetch(item.upstream_id, item.upstream_revision)
        except Exception as exc:  # noqa: BLE001 - every transport failure is one fact
            raise UpdateFetchFailed(
                f"the update could not retrieve {identity}: {exc}. Nothing was "
                "written and no packet exists; re-run the update when the source "
                "answers."
            ) from exc
        if not isinstance(result, FetchedItem):
            raise UpdateFetchFailed(
                f"retrieval of {identity} did not produce a complete FetchedItem; a "
                "partial listing cannot state whether the item is whole"
            )
        fetched[identity] = (item, {entry.path: entry.content for entry in result.files})

    library_types = {item.qualified_identity(): item.library_type for item in items}
    # The baseline covers every identity this provider has pinned, not only the
    # ones that were fetched. Wave-1 review found the earlier version restricting
    # it to the fetched set, which made `build_change_set`'s `removed` branch
    # unreachable: an item the operator had admitted and the steward had since
    # withdrawn simply vanished from the packet, so the packet was not "exactly
    # the change set between the pinned admitted state and the fetched state".
    # An upstream disappearance is one of the more important things an operator
    # can be told about, and ADR-0011 already has a durable state for it.
    prefix = f"{provider.identity()}#"
    library_types.update(_recorded_library_types(state))
    pinned = sorted(
        pin.qualified_identity
        for pin in state.pin_store().pins()
        if pin.qualified_identity.startswith(prefix)
    )
    # Two passes: what the operator admitted, and only then the bytes behind it.
    # Looking the content up first would mean reading a cache object for an
    # identity whose decision might not stand, which is a diff against bytes
    # nobody accepted.
    admitted = admitted_baseline(
        identities=sorted(set(fetched) | set(pinned)),
        pin_store=state.pin_store(),
        ledger=state.admission_ledger_store().ledger(),
        library_types=library_types,
    )
    cached = _cached_baseline_content(
        state, {identity: digest for identity, (digest, _) in admitted.items()}
    )
    baseline = {
        identity: (digest, cached.get(identity))
        for identity, (digest, _) in admitted.items()
    }
    change_set = build_change_set(
        provider_identity=provider.identity(),
        observed_at=observed_at,
        fetched=fetched,
        baseline=baseline,
    )

    scans = {
        item.qualified_identity: scan_content(item.content)
        for item in change_set.items
        if item.content
    }

    packet_id = _packet_id(provider.identity(), change_set)
    prompt = review_prompt(change_set, packet_id)

    review_status = "completed"
    unavailable_detail = ""
    verdict: ReviewVerdict | None = None
    if change_set.items:
        prompt_path = store.staging_root / f"prompt-{uuid.uuid4().hex}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        try:
            answered = review(change_set, prompt_path)
            verdict = validated_review_verdict(
                answered, change_set_digest=change_set.digest()
            )
        except ReviewUnavailable as exc:
            review_status = "unavailable"
            unavailable_detail = str(exc)
        finally:
            prompt_path.unlink(missing_ok=True)
    else:
        # Nothing to review. Recorded as unavailable rather than clean, because
        # "there was nothing to look at" is not a reviewer's approval.
        review_status = "unavailable"
        unavailable_detail = "there is no change to review"

    recommendation, basis = recommendation_for(
        change_set=change_set,
        scan_counts=merged_counts(list(scans.values())),
        review_status=review_status,
        verdict=verdict,
    )
    packet = DecisionPacket(
        packet_id=packet_id,
        provider_identity=provider.identity(),
        created_at=observed_at,
        change_set=change_set,
        scans=scans,
        review=verdict,
        review_status=review_status,
        review_unavailable_detail=unavailable_detail,
        recommendation=recommendation,
        recommendation_basis=basis,
    )
    # The base id is deterministic over the change set, so the same upstream
    # state is recognizable across runs. It is only *taken* when it is free or
    # already holds this exact packet: a second run over an unchanged change set
    # produces a second review, and replacing the first one -- possibly one
    # somebody had already rejected -- is how the evidence a decision was made
    # against disappears.
    final_id = store.available_packet_id(packet_id, packet.fingerprint())
    if final_id != packet_id:
        packet = replace(packet, packet_id=final_id)
    store.write(
        packet,
        {item.qualified_identity: dict(item.content) for item in change_set.items if item.content},
        prompt,
    )
    return packet


def _recorded_library_types(state) -> dict[str, str]:
    """Each installed identity's Library type, from its receipt.

    An identity that vanished upstream is not in the fetched inventory, so its
    type is not on any item this run holds. `admitted_baseline` needs it to ask
    whether that identity required a decision at all, and the receipt is where
    the Library wrote it down.
    """
    recorded: dict[str, str] = {}
    for scope in sorted(state.receipt_paths):
        try:
            receipts = state.receipt_store(scope).all()
        except (KeyError, OSError, ValueError):
            continue
        for receipt in receipts:
            recorded.setdefault(receipt.qualified_identity(), receipt.library_type)
    return recorded


def _cached_baseline_content(
    state, baseline_digests: Mapping[str, str]
) -> dict[str, dict[str, bytes]]:
    """The admitted revision's bytes, where the cache still holds them.

    Used only to render a diff, and matched on the **admitted digest** rather
    than on the identity alone: several receipts can describe the same identity
    at different revisions, and diffing against whichever one happened to be read
    first would show an operator a change that never happened.

    An absent or damaged object is not an error here. The packet carries the
    whole post-update content either way, which is the part ADR-0011 requires;
    the diff is the convenience on top of it. What this must never do is return
    *unverified* bytes, so the integrity report is checked rather than ignored.
    """
    from .cache_transaction import cache_key_for_receipt
    from .foreign_cache import CacheObjectCorrupt, CacheObjectMissing

    content: dict[str, dict[str, bytes]] = {}
    for scope in sorted(state.receipt_paths):
        for receipt in state.receipt_store(scope).all():
            identity = receipt.qualified_identity()
            if identity in content:
                continue
            if baseline_digests.get(identity) != receipt.normalized_content_digest:
                continue
            try:
                snapshot, report = state.object_store().read_verified(
                    cache_key_for_receipt(receipt)
                )
            except (CacheObjectMissing, CacheObjectCorrupt, KeyError, OSError):
                continue
            if report.verified:
                content[identity] = dict(snapshot)
    return content


# -- deciding -----------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalOutcome:
    """What one approval did, per item."""

    packet_id: str
    approved: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    decision: Mapping[str, Any] = field(default_factory=dict)


def _already_decided(store: UpdatePacketStore, packet_id: str) -> dict[str, Any] | None:
    rows = store.decisions(packet_id)
    return rows[-1] if rows else None


def approve_packet(
    *,
    packet_id: str,
    state,
    items: Mapping[str, NormalizedItem],
    operator: str,
    reason: str,
    availability: Mapping[str, ResolutionEvidence],
    decided_at: str,
    target: str,
    target_root: Path,
    scope: str = "project",
    selected: Sequence[str] | None = None,
    against_recommendation: bool = False,
    present: Callable[[Any], Any] | None = None,
) -> ApprovalOutcome:
    """Adopt some or all of one packet, on one human's recorded decision.

    Args:
        selected: The qualified identities to adopt. `None` adopts every changed
            item. Per-item adoption exists because a first import's packet can be
            large enough that an all-or-nothing grant is the same rubber stamp
            the whole flow is built to avoid.
        against_recommendation: Required when the packet does not recommend
            adopting what is being adopted. A human may overrule the packet; they
            may not do it by accident.

    The order per item is: verify the stored bytes against the packet, record the
    admission decision, raise the pin, and only then install. Recording before
    pinning means a crash between them leaves a decision about bytes that are not
    yet pinned -- which refuses the next install -- rather than a pin to bytes
    nobody decided about, which would admit them.

    Raises:
        ValueError: for an unknown packet, a packet already decided, a tampered
            packet, or an approval that contradicts the recommendation without
            saying so.
        OfflineRefusal: when the source cannot currently be observed. Raising a
            pin is a re-pin, and ADR-0011 `Offline Semantics` refuses one without
            a complete, source-scoped observation: an unreachable source cannot
            authorize substituting the bytes it stands behind.
    """
    store = UpdatePacketStore(state.update_root())
    packet, contents = store.load(packet_id)
    # An early, cheap refusal for the ordinary case. It is not the guarantee --
    # `record_decision` holds the check and the append under one lock, so a
    # decision recorded while this approval is working still refuses it there.
    previous = _already_decided(store, packet_id)
    if previous is not None:
        raise AlreadyDecided(packet_id, previous)

    changed = {item.qualified_identity: item for item in packet.change_set.items}
    chosen = tuple(selected) if selected is not None else tuple(sorted(changed))
    unknown = sorted(set(chosen) - set(changed))
    if unknown:
        raise ValueError(f"these identities are not in packet {packet_id}: {unknown}")

    adopts_everything = set(chosen) == set(changed)
    if packet.recommendation == "reject" and not against_recommendation:
        raise ValueError(
            f"this packet recommends 'reject': {packet.recommendation_basis} "
            "Approving it anyway is allowed and is an explicit act: pass "
            "--against-recommendation with your reason."
        )
    if (
        packet.recommendation == "partial"
        and adopts_everything
        and len(changed) > 1
        and not against_recommendation
    ):
        raise ValueError(
            f"this packet recommends 'partial': {packet.recommendation_basis} "
            "Adopting every item at once is allowed and is an explicit act: name "
            "the items with --item, or pass --against-recommendation."
        )

    operator_identity = validated_operator(operator)
    operator_reason = validated_reason(reason)

    # -- pre-flight ----------------------------------------------------------
    #
    # Wave-1 review approved a packet whose re-pin then failed offline, and found
    # the new digest already recorded as `admitted` with no decision row anywhere
    # -- a standing grant for bytes the operator did not adopt. Every condition
    # that can refuse this approval is therefore checked before the first durable
    # write, so a refusal is a refusal rather than a half-adoption.
    pin_store = state.pin_store()
    installable: list[tuple[str, ChangedItem, NormalizedItem, Mapping[str, bytes], str]] = []
    for identity in chosen:
        entry = changed[identity]
        if entry.change == "removed":
            # An upstream removal is not something to install. It is reported in
            # the packet and recorded in the decision, and retiring the receipt
            # stays ADR-0011's explicit named removal -- its own operator act,
            # with its own receipt history and its own degraded-source rules.
            continue
        item = items.get(identity)
        if item is None:
            raise ValueError(
                f"approving {identity} needs its normalized item; the packet records "
                "what changed, not the rights and availability an install evaluates"
            )
        stored = contents.get(identity)
        if not stored:
            raise ValueError(f"packet {packet_id} holds no content for {identity}")
        actual = content_digest(stored)
        if actual != entry.fetched_digest:
            raise ValueError(
                f"the stored content for {identity} no longer reproduces the digest "
                f"this packet recorded: packet {entry.fetched_digest}, stored "
                f"{actual}. Nothing was approved; re-run the update."
            )
        existing = pin_store.pin_for(identity)
        if existing is None or existing.normalized_content_digest != actual:
            # Any pin write, first or subsequent. Review found the first-import
            # branch skipping this entirely, so an operator could adopt a brand
            # new item from a source that had since gone dark -- while the
            # docstring promised the opposite. Adoption is the trust act: if the
            # source cannot be observed now, it cannot stand behind the bytes now.
            _require_current_observation(identity, item.provider_identity, availability)
        installable.append((identity, entry, item, stored, actual))

    # -- durable, per item ---------------------------------------------------
    approved: list[str] = []
    receipts: list[str] = []
    ledger = state.admission_ledger_store()
    try:
        for identity, entry, item, stored, actual in installable:
            # Pin first, then admit. A crash between the two leaves bytes pinned
            # and undecided, which refuses the next install; the reverse leaves a
            # standing grant for bytes nobody adopted, which is the record that
            # lies.
            existing = pin_store.pin_for(identity)
            if existing is None:
                pin_store.pin(identity, actual, observed_at=decided_at)
            elif existing.normalized_content_digest != actual:
                pin_store.repin(
                    identity,
                    actual,
                    operator=operator_identity,
                    acknowledged_drift=(existing.normalized_content_digest, actual),
                    decided_at=decided_at,
                    availability=availability[item.provider_identity],
                )

            evidence = (
                f"{operator_reason} [update packet {packet_id}; change set "
                f"{packet.change_set.digest()}; scan "
                f"{packet.scan_digest_for(identity)}; review "
                f"{packet.review.digest() if packet.review else 'unavailable'}]"
            )
            ledger.decide(
                ADMITTED,
                identity,
                actual,
                library_type=item.library_type,
                reviewer=operator_identity,
                permission_surface=(),
                decided_at=decided_at,
                evidence=evidence,
                supersedes=True,
            )

            outcome = install_foreign_item(
                item,
                # The reviewed bytes, not a re-fetch. Upstream may have moved
                # between the packet and this decision, and the human approved
                # the packet.
                retrieve=lambda stored=stored, item=item: FetchedItem(
                    upstream_id=item.upstream_id,
                    revision=item.upstream_revision,
                    files=tuple(
                        FetchedFile(path=path, content=payload)
                        for path, payload in sorted(stored.items())
                    ),
                    primary_path=sorted(stored)[0],
                ),
                object_store=state.object_store(),
                pin_store=pin_store,
                receipt_store=state.receipt_store(scope),
                target=target,
                activate=_activation(
                    projection_root_for(
                        state, scope=scope, identity=identity, item=item,
                        target_root=Path(target_root),
                    )
                ),
                observed_at=decided_at,
                completeness=CompletenessEvidence.from_manifest(
                    sorted(stored),
                    "the packet stores the complete content the reviewer read and the "
                    "operator approved",
                ),
                ledger=ledger,
                present=present,
            )
            approved.append(identity)
            receipts.append(outcome.receipt.id)
    except BaseException:
        # Whatever went wrong, what was already adopted is adopted. Recording it
        # is the difference between a packet that reads "undecided" over three
        # live grants and one that names exactly what happened.
        if approved:
            store.record_decision(
                packet_id=packet_id,
                decision="approved",
                operator=operator_identity,
                reason=operator_reason,
                decided_at=decided_at,
                change_set_digest=packet.change_set.digest(),
                detail={
                    "approved": list(approved),
                    "declined": sorted(set(changed) - set(approved)),
                    "recommendation": packet.recommendation,
                    "against_recommendation": bool(against_recommendation),
                    "receipts": list(receipts),
                    "interrupted": True,
                },
                allow_second=True,
            )
        raise

    decision = store.record_decision(
        packet_id=packet_id,
        decision="approved",
        operator=operator_identity,
        reason=operator_reason,
        decided_at=decided_at,
        change_set_digest=packet.change_set.digest(),
        detail={
            "approved": approved,
            "declined": sorted(set(changed) - set(approved)),
            "recommendation": packet.recommendation,
            "against_recommendation": bool(against_recommendation),
            "receipts": receipts,
        },
    )
    return ApprovalOutcome(
        packet_id=packet_id,
        approved=tuple(approved),
        declined=tuple(sorted(set(changed) - set(approved))),
        receipts=tuple(receipts),
        decision=decision,
    )


def _require_current_observation(
    identity: str,
    provider_identity: str,
    availability: Mapping[str, ResolutionEvidence],
) -> ResolutionEvidence:
    """A current, complete, source-scoped observation, or a refusal.

    `TofuPinStore.repin` enforces this for a replacement pin and cannot enforce
    it for a first one, because a first pin is ordinarily written during an
    install of bytes that just arrived. Approval is different: the bytes arrived
    when the packet was built, and the decision is being taken now.
    """
    observation = availability.get(provider_identity)
    if observation is None:
        raise ValueError(
            f"pinning {identity} needs a current, source-scoped observation of "
            f"{provider_identity}; approval never pins on a recorded observation "
            "from the time of the fetch"
        )
    reason = observation.degraded_reason()
    if reason is not None:
        raise OfflineRefusal(
            "approve-update",
            "would-substitute-pinned-content",
            f"{provider_identity} cannot currently be resolved ({reason}), so it "
            f"cannot stand behind the bytes being adopted for {identity}",
        )
    return observation


def projection_root_for(
    state,
    *,
    scope: str,
    identity: str,
    item: NormalizedItem,
    target_root: Path,
) -> Path:
    """Where one approved item's projection goes.

    Two rules, and wave-1 review demonstrated the cost of having neither: the
    first version handed every approved item the same directory, so two Skills
    that each ship a `SKILL.md` overwrote one another and an all-items approval
    could not project the set it had just admitted.

    1. **An update lands where the item already lives.** If a receipt in this
       scope describes this identity and names its targets, their common parent
       is the root. Choosing a fresh path instead would leave the previously
       installed copy on disk, unreferenced by the new receipt and still loaded
       by the harness -- the old bytes winning over the approved ones.
    2. **Otherwise, one directory per item**, under the caller's root and keyed
       by the Library type and name, which is the same shape
       `library marketplace install` defaults to.
    """
    try:
        receipts = state.receipt_store(scope).all()
    except (KeyError, OSError, ValueError):
        receipts = ()
    roots: list[Path] = []
    for receipt in receipts:
        if receipt.qualified_identity() != identity:
            continue
        parents = {Path(entry.path).parent for entry in receipt.targets}
        if len(parents) == 1:
            roots.append(next(iter(parents)))
    if roots:
        return roots[-1]
    return Path(target_root) / item.library_type / item.library_name


def _activation(target_root: Path):
    from .wiring import filesystem_activation

    return filesystem_activation(Path(target_root))


def reject_packet(
    *,
    packet_id: str,
    state,
    operator: str,
    reason: str,
    decided_at: str,
) -> dict[str, Any]:
    """Record that a human declined one packet.

    It writes exactly one thing: the decision row. Pins, admission decisions,
    receipts, cache objects, and projected bytes are untouched, which is what
    makes "no" cheap enough to be the honest answer.
    """
    store = UpdatePacketStore(state.update_root())
    packet, _ = store.load(packet_id)
    return store.record_decision(
        packet_id=packet_id,
        decision="rejected",
        operator=operator,
        reason=reason,
        decided_at=decided_at,
        change_set_digest=packet.change_set.digest(),
        detail={"recommendation": packet.recommendation},
    )


__all__ = [
    "CHANGES",
    "AlreadyDecided",
    "DECISIONS",
    "DECISION_LEDGER_SCHEMA",
    "PACKET_SCHEMA",
    "RECOMMENDATIONS",
    "REVIEW_STATUSES",
    "REVIEW_VERDICTS",
    "REVIEW_VERDICT_SCHEMA",
    "UPDATE_APPROVE_VERB",
    "UPDATE_COMMAND",
    "UPDATE_LIST_VERB",
    "UPDATE_REJECT_VERB",
    "UPDATE_SHOW_VERB",
    "UPDATE_VERB",
    "ApprovalOutcome",
    "ChangeSet",
    "ChangedItem",
    "DecisionPacket",
    "ReviewDispatch",
    "ReviewFinding",
    "ReviewUnavailable",
    "ReviewVerdict",
    "UpdateFetchFailed",
    "UpdatePacketStore",
    "admitted_baseline",
    "approve_packet",
    "build_change_set",
    "prepare_update",
    "projection_root_for",
    "recommendation_for",
    "reject_packet",
    "review_prompt",
    "validated_review_verdict",
]
