"""The `git-repo` reference marketplace, installed through the generic contract.

CL-mvet AC1 and AC2. Both run against the recorded capture of the live provider
in `tests/fixtures/provider_git_repo/`, which
`tests/test_source_provider_contract.py::test_git_repo_live_enumeration_matches_recording`
re-verifies against the real source under `NETWORK_TESTS=1`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.admission import AdmissionContext, evaluate_inventory  # noqa: E402
from lib.providers.classification import UNCLASSIFIED  # noqa: E402
from lib.providers.git_repo import ProviderTransportError  # noqa: E402
from lib.providers.reference_rights import SKILLS_REPO_IDENTITY  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    install_marketplace_item,
    marketplace_inventory,
)

from foreign_admission_support import (  # noqa: E402
    admitting,
    admitting_inventory,
    stand_in_contents,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "provider_git_repo" / "mattpocock-skills.json"


class RecordedTransport:
    """Replays the recorded capture; an unrecorded URL is a transport failure."""

    def __init__(self, recording: dict[str, object]) -> None:
        self._json = recording["json"]
        self._bytes = recording.get("bytes", {})
        self.requests: list[str] = []

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> object:
        self.requests.append(url)
        if url not in self._json:
            raise ProviderTransportError(f"404 for {url}")
        return self._json[url]

    def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        self.requests.append(url)
        if url not in self._bytes:
            raise ProviderTransportError(f"404 for {url}")
        return self._bytes[url].encode("utf-8")


def _entry() -> dict[str, object]:
    """The marketplace entry an operator registers for this provider."""
    return {
        "name": "matt-pocock-skills",
        "source": SKILLS_REPO_IDENTITY,
        "type": "git",
        "provider_kind": "git-repo",
        "branch": "main",
    }


def _transport() -> RecordedTransport:
    return RecordedTransport(json.loads(FIXTURE.read_text()))


def _state(tmp_path: Path) -> ForeignState:
    project_lock = tmp_path / "project" / ".library.lock"
    global_lock = tmp_path / "global" / "global.lock"
    project_lock.parent.mkdir(parents=True, exist_ok=True)
    global_lock.parent.mkdir(parents=True, exist_ok=True)
    return ForeignState.for_locks(
        cache_root=tmp_path / "cache",
        project_lock=project_lock,
        global_lock=global_lock,
    )


# ---------------------------------------------------------------------------
# AC1 — nested-layout install preserves identity and classification
# ---------------------------------------------------------------------------


def test_installs_nested_skills(tmp_path: Path) -> None:
    """`implement` and `ask-matt` install from `skills/engineering/<name>/`.

    The two ADR-0011 Placement Records are asserted end to end: the upstream
    name is preserved verbatim, the curated `skill_class` is `procedure` and
    `navigator` respectively -- which no upstream field distinguishes, since both
    ship the same `disable-model-invocation` flag -- and the install goes through
    the real cache transaction, producing a cache object, a durable receipt, and
    a projection, in that order.
    """
    provider, result = marketplace_inventory(_entry(), http_transport=_transport())
    state = _state(tmp_path)

    for upstream_id, name, skill_class in (
        ("skills/engineering/implement", "implement", "procedure"),
        ("skills/engineering/ask-matt", "ask-matt", "navigator"),
    ):
        item = result.inventory.resolve(f"{SKILLS_REPO_IDENTITY}#{upstream_id}")

        assert item.upstream_name == name, "upstream identity is preserved verbatim"
        assert item.library_type == "skill"
        assert item.library_name == name
        assert item.collection_membership == ("skills", "engineering")
        assert item.classification["skill_class"] == skill_class
        assert item.classification["skill_class_source"] == "library-curated"
        assert item.classification["maturity"] == "stable"
        assert item.upstream_revision is not None, "a git-repo source is revisioned"

        # `CL-lt51`: these are a foreign steward's Skills, so the install needs
        # the operator's recorded decision about the exact bytes it retrieves.
        fetched = provider.fetch(item.upstream_id, item.upstream_revision)
        outcome = install_marketplace_item(
            item,
            provider=provider,
            state=state,
            scope="project",
            target="project_committed",
            target_root=tmp_path / "projection" / name,
            ledger=admitting(
                item.qualified_identity(),
                {entry.path: entry.content for entry in fetched.files},
            ),
        )

        # The transaction's own order, not a rewording of it.
        assert outcome.events == (
            "retrieved",
            "content-verified",
            "cache-object-materialized",
            "receipt-durable",
            "projection-activated",
        )
        # Completeness was established from a source-read manifest, not from the
        # adapter's word: this item ships more than its marker file.
        assert outcome.receipt.completeness_evidence == "member-manifest"
        installed = sorted(
            Path(target.path).relative_to(tmp_path / "projection" / name).as_posix()
            for target in outcome.receipt.targets
        )
        assert "SKILL.md" in installed
        assert "agents/openai.yaml" in installed, (
            "an item is a directory: fetching only the marker would install a "
            "fragment while reporting success"
        )
        assert outcome.receipt.library_type == "skill", (
            "the receipt is for the fetched item's own type"
        )


def test_installed_skills_carry_no_unclassified_members(tmp_path: Path) -> None:
    """A marker-layout source produces no unclassified item.

    The guard exists because the unclassified state is deliberately reachable
    now: if the marker layout started emitting loose files, this repository's
    skills would quietly become uninstallable rather than loudly wrong.
    """
    _, result = marketplace_inventory(_entry(), http_transport=_transport())
    assert [item for item in result.inventory if item.library_type == UNCLASSIFIED] == []


# ---------------------------------------------------------------------------
# AC2 — maturity is classification, not a default filter
# ---------------------------------------------------------------------------


def test_in_progress_remains_discoverable() -> None:
    """`skills/in-progress/**` classifies as in-progress and stays discoverable.

    Three separate claims, because collapsing any two of them is a distinct bug:

    1. The items are **in the inventory**. Filtering them out would make the
       inventory disagree with the source it describes.
    2. Their maturity is recorded as `in-progress`, with the collection that
       produced it named.
    3. They are `discoverable` and not `installable`, even though this provider's
       rights are fully granted -- so the non-promotion comes from maturity, not
       from a rights refusal that would have hidden the difference.
    """
    _, result = marketplace_inventory(_entry(), http_transport=_transport())
    report = evaluate_inventory(result.inventory, AdmissionContext())

    in_progress = [
        item
        for item in report.inventory
        if item.collection_membership[:2] == ("skills", "in-progress")
    ]
    stable = [
        item
        for item in report.inventory
        if item.collection_membership[:2] == ("skills", "engineering")
    ]
    assert in_progress, "the recorded capture carries in-progress items"
    assert stable, "and stable ones to compare them against"

    # `CL-lt51` added a fourth claim to the picture: this is a foreign steward,
    # and a foreign steward's Skill is admission-required, so *every* item here
    # carries the admission-pending reason at discovery time -- discovery does
    # not fetch whole items, and the decision binds to bytes. Maturity is still
    # the axis under test, and it is still visible: it is recorded on the
    # classification and it is the only thing that differs between the two
    # groups' block reasons.
    for item in in_progress:
        assert item.classification["maturity"] == "in-progress"
        assert item.classification["maturity_basis"] == "collection:in-progress"
        assert item.block_reason_values() == ("executable-admission-pending",), (
            "not promoting is still not blocking: no reason here asserts anything "
            "observed about this item's rights, runtime, or availability"
        )
        assert item.rights.install_rights == "granted", (
            "the non-promotion is maturity, not rights"
        )

    for item in stable:
        assert item.classification["maturity"] == "stable"
        assert item.block_reason_values() == ("executable-admission-pending",)

    # And with the decision recorded for the exact bytes, maturity is once more
    # the only thing separating the two groups.
    decided = evaluate_inventory(
        result.inventory,
        AdmissionContext(),
        ledger=admitting_inventory(result.inventory),
        contents=stand_in_contents(result.inventory),
    )
    for item in decided.inventory:
        if item.collection_membership[:2] == ("skills", "in-progress"):
            assert item.admission_state == "discoverable"
            assert item.block_reasons == ()
        elif item.collection_membership[:2] == ("skills", "engineering"):
            assert item.admission_state == "installable"


def test_promoting_in_progress_is_an_explicit_scope_decision() -> None:
    """A scope that admits `in-progress` installs it; the default never does.

    Evaluated with the admission decisions recorded, because `CL-lt51` makes a
    foreign steward's Skill admission-required and this test is about the
    maturity axis: without the decisions both scopes would answer `blocked` and
    the promotion would be invisible.
    """
    _, result = marketplace_inventory(_entry(), http_transport=_transport())
    decided = dict(
        ledger=admitting_inventory(result.inventory),
        contents=stand_in_contents(result.inventory),
    )

    default_report = evaluate_inventory(result.inventory, AdmissionContext(), **decided)
    promoted_report = evaluate_inventory(
        result.inventory,
        AdmissionContext(admitted_maturities=("stable", "in-progress")),
        **decided,
    )

    identity = next(
        item.qualified_identity()
        for item in result.inventory
        if item.collection_membership[:2] == ("skills", "in-progress")
    )
    assert default_report.decisions[identity].admission_state == "discoverable"
    assert promoted_report.decisions[identity].admission_state == "installable"


def test_a_scope_cannot_admit_an_unknown_maturity() -> None:
    """The maturity vocabulary is closed; an invented one is refused."""
    with pytest.raises(ValueError, match="admitted_maturities"):
        AdmissionContext(admitted_maturities=("stable", "battle-tested"))
