"""The `git-org` reference marketplace: an allowlist, per-repository everything.

CL-mvet AC3, AC4, and AC8. The evidence runs against
`tests/fixtures/provider_git_org/disler-organization.json`, a capture built from
local checkouts at the exact commits `indydevdan-pi-repos.md` pins;
`test_capture_matches_live_organization` re-verifies it against the live provider
under `NETWORK_TESTS=1`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.primitives import all_primitive_names  # noqa: E402
from lib.providers.admission import AdmissionContext, evaluate_inventory  # noqa: E402
from lib.providers.classification import UNCLASSIFIED  # noqa: E402
from lib.providers.decompose import BUNDLE_LAYOUT  # noqa: E402
from lib.providers.git_org import AllowlistRequired, GitOrgProvider  # noqa: E402
from lib.providers.git_repo import ProviderTransportError  # noqa: E402
from lib.providers.reference_rights import (  # noqa: E402
    ORGANIZATION_ALLOWLIST,
    ORGANIZATION_IDENTITY,
)
from lib.providers.registration import RegistrationError, validate_provider_entry  # noqa: E402
from lib.providers.wiring import ProviderBuildError, build_provider, marketplace_inventory  # noqa: E402

from foreign_admission_support import (  # noqa: E402
    admitting_inventory,
    stand_in_contents,
)

FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "provider_git_org" / "disler-organization.json"
)

#: The organization repository ADR-0011 names as carrying no observed LICENSE.
#: It is deliberately NOT on the Library allowlist; the ADR records that if it
#: were added, its rights would resolve to `unknown`.
UNLICENSED_REPOSITORY = "live-bench"
LICENSED_REPOSITORY = "planf3"


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


def _recording() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def _entry(allowlist: tuple[str, ...] = ORGANIZATION_ALLOWLIST) -> dict[str, object]:
    return {
        "name": "pi-reference-org",
        "source": ORGANIZATION_IDENTITY,
        "type": "git",
        "provider_kind": "git-org",
        "allowlist": list(allowlist),
        "layout": BUNDLE_LAYOUT,
    }


def _provider(allowlist: tuple[str, ...] = ORGANIZATION_ALLOWLIST) -> GitOrgProvider:
    return build_provider(_entry(allowlist), http_transport=RecordedTransport(_recording()))


# ---------------------------------------------------------------------------
# AC3 — the allowlist bounds organization enumeration
# ---------------------------------------------------------------------------


def test_allowlist_bounds_inventory() -> None:
    """A repository the organization serves but the allowlist omits is absent.

    The organization listing is read in the same run, so the assertion is not
    "we never looked": the excluded repository is demonstrably visible upstream
    and is demonstrably not in the inventory. Without reading the listing, an
    allowlist that bounds nothing would pass this test too.
    """
    provider = _provider()

    served = provider.organization_repositories()
    assert UNLICENSED_REPOSITORY in served, (
        "the capture records a repository upstream serves and the Library excludes"
    )
    assert set(ORGANIZATION_ALLOWLIST).issubset(served)

    _, result = marketplace_inventory(
        _entry(), http_transport=RecordedTransport(_recording())
    )
    repositories = {item.collection_membership[0] for item in result.inventory}
    assert repositories == set(ORGANIZATION_ALLOWLIST)
    assert UNLICENSED_REPOSITORY not in repositories
    assert provider.excluded_repositories() == (UNLICENSED_REPOSITORY,)

    for item in result.inventory:
        assert not item.upstream_id.startswith(f"{UNLICENSED_REPOSITORY}/")


def test_rejects_missing_allowlist() -> None:
    """Organization enumeration without an allowlist is refused at every door.

    Three doors, because closing one leaves the other two open: the catalog
    validator an operator's file passes through, the adapter constructor, and the
    provider factory production code calls.
    """
    entry = _entry()
    entry.pop("allowlist")
    with pytest.raises(RegistrationError, match="allowlist"):
        validate_provider_entry(entry)

    with pytest.raises(AllowlistRequired):
        GitOrgProvider(organization_url=ORGANIZATION_IDENTITY, allowlist=())

    with pytest.raises(ProviderBuildError, match="allowlist"):
        build_provider(entry, http_transport=RecordedTransport(_recording()))

    empty = _entry(allowlist=())
    empty["allowlist"] = []
    with pytest.raises(RegistrationError, match="allowlist"):
        validate_provider_entry(empty)


def test_an_unserved_allowlist_entry_is_a_refusal_not_a_smaller_inventory() -> None:
    """A typo in the allowlist fails loudly instead of shrinking the inventory."""
    from lib.providers.git_org import AllowlistUnserved

    provider = _provider(allowlist=(LICENSED_REPOSITORY, "planf4"))
    with pytest.raises(AllowlistUnserved, match="planf4"):
        provider.enumerate()


# ---------------------------------------------------------------------------
# AC4 — rights resolve per repository
# ---------------------------------------------------------------------------


def test_per_repository_rights() -> None:
    """A repository with no observed licence does not inherit a sibling's grant.

    Both repositories are in **one** inventory from **one** provider whose
    recorded rights are fully granted. That is the whole point: an
    organization-wide grant would make every item here `granted`, and the only
    thing separating them is the per-repository licensing evidence.
    """
    entry = _entry(allowlist=(LICENSED_REPOSITORY, UNLICENSED_REPOSITORY))
    _, result = marketplace_inventory(entry, http_transport=RecordedTransport(_recording()))

    licensed = [
        item
        for item in result.inventory
        if item.collection_membership[0] == LICENSED_REPOSITORY
    ]
    unlicensed = [
        item
        for item in result.inventory
        if item.collection_membership[0] == UNLICENSED_REPOSITORY
    ]
    assert licensed and unlicensed

    for item in licensed:
        assert item.rights.install_rights == "granted"
        assert item.rights.redistribution_rights == "granted"
        assert item.rights.derivative_rights == "granted"
        assert LICENSED_REPOSITORY in (item.rights.evidence_source or ""), (
            "a resolved grant names the repository whose licence resolved it"
        )

    for item in unlicensed:
        assert item.rights.install_rights == "unknown"
        assert item.rights.redistribution_rights == "unknown"
        assert item.rights.derivative_rights == "unknown"
        evidence = item.rights.evidence_source or ""
        assert UNLICENSED_REPOSITORY in evidence
        assert LICENSED_REPOSITORY not in evidence, (
            "the sibling's evidence must not travel with the item that has none"
        )
        assert item.rights.grant_evidence == {}, (
            "evidence that justified a grant no longer held describes nothing"
        )

    report = evaluate_inventory(result.inventory, AdmissionContext())
    for item in report.inventory:
        if item.collection_membership[0] != UNLICENSED_REPOSITORY:
            continue
        if item.library_type == UNCLASSIFIED:
            continue
        assert item.admission_state == "blocked"
        assert "license-unknown" in item.block_reason_values()
        assert item.projection_eligibility["project_committed"] == "blocked"


def test_fetch_authorization_is_not_a_licence_question() -> None:
    """A missing LICENSE relaxes the licence-derived grants and nothing else.

    ADR-0011 separates the two directions of the same confusion: a subscriber
    token proves fetchability and says nothing about redistribution, and
    symmetrically an absent licence says nothing about fetchability. Downgrading
    `fetch_authorization` here would be inventing a fact in the other direction.
    """
    entry = _entry(allowlist=(UNLICENSED_REPOSITORY,))
    _, result = marketplace_inventory(entry, http_transport=RecordedTransport(_recording()))
    item = next(iter(result.inventory))
    assert item.rights.fetch_authorization == "granted"
    assert item.rights.install_rights == "unknown"


# ---------------------------------------------------------------------------
# AC8 — a mixed bundle decomposes into existing typed primitives
# ---------------------------------------------------------------------------


def test_bundle_decomposition() -> None:
    """A mixed repository decomposes into existing types, and no new one.

    The reference bundle really is mixed: it ships an Agent-Skills skill, loose
    prompt documents, and files that are neither -- images, a spec rendered as
    HTML, a licence. Each member is classified individually, and the members that
    fit no existing type are recorded as unclassified rather than pushed onto the
    nearest type or into a new generic one.
    """
    entry = _entry(allowlist=(LICENSED_REPOSITORY,))
    _, result = marketplace_inventory(entry, http_transport=RecordedTransport(_recording()))
    report = evaluate_inventory(result.inventory, AdmissionContext())

    by_type: dict[str, list[str]] = {}
    for item in report.inventory:
        by_type.setdefault(item.library_type, []).append(item.upstream_id)

    assert "skill" in by_type, "the bundle's Agent-Skills skill is typed as one"
    assert "prompt" in by_type, "its loose prompt documents are typed individually"
    assert UNCLASSIFIED in by_type, "and its non-primitive members are not forced"

    known = set(all_primitive_names())
    for library_type in by_type:
        assert library_type in known or library_type == UNCLASSIFIED, (
            f"{library_type!r} is neither an existing Library primitive nor the "
            "recorded absence of one; ADR-0011 refuses a generic bundle type"
        )

    for item in report.inventory:
        if item.library_type != UNCLASSIFIED:
            continue
        assert item.admission_state == "discoverable", (
            "an unclassified member is shown, not blocked: nothing was observed "
            "about it that a block reason could carry"
        )
        assert item.block_reasons == ()
        assert item.classification["classification_state"] == UNCLASSIFIED
        assert set(item.projection_eligibility.values()) == {"blocked"}, (
            "and never installable: 'install this, we do not know what it is' is "
            "how a generic catch-all primitive gets created by accident"
        )

    # `CL-lt51`: this is a foreign steward, so its Skill is admission-required
    # and discovery -- which fetches no whole item -- reports it as blocked on
    # exactly that. With the decision recorded it is installable, which is the
    # claim this test is making: decomposition produced a real, installable Skill
    # rather than a member the Library could not type.
    skill = next(item for item in report.inventory if item.library_type == "skill")
    assert skill.block_reason_values() == ("executable-admission-pending",)
    decided = evaluate_inventory(
        result.inventory,
        AdmissionContext(),
        ledger=admitting_inventory(result.inventory),
        contents=stand_in_contents(result.inventory),
    )
    assert decided.decisions[skill.qualified_identity()].admission_state == "installable"
    assert skill.upstream_id.endswith(f"/{LICENSED_REPOSITORY}") or "/" in skill.upstream_id


def test_pi_extensions_decompose_as_pi_extensions() -> None:
    """A Pi extension module is typed as the existing `pi-extension` primitive."""
    entry = _entry(allowlist=("pi-vs-claude-code",))
    _, result = marketplace_inventory(entry, http_transport=RecordedTransport(_recording()))
    extensions = [item for item in result.inventory if item.library_type == "pi-extension"]
    assert extensions, "the reference bundle ships Pi extensions"
    for item in extensions:
        assert item.classification["type_basis"] == "collection-layout:extensions"
        assert item.executable_admission == "pending", (
            "an extension loads code, so it is executable and undecided until a "
            "scope operator decides for its exact bytes"
        )


# ---------------------------------------------------------------------------
# Capture provenance
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("NETWORK_TESTS") != "1",
    reason="set NETWORK_TESTS=1 to re-verify the capture against the live provider",
)
def test_capture_matches_live_organization() -> None:
    """The recorded capture still matches what the live organization serves."""
    from lib.providers.git_repo import UrllibTransport

    recording = _recording()
    live = GitOrgProvider(
        organization_url=ORGANIZATION_IDENTITY,
        allowlist=ORGANIZATION_ALLOWLIST,
        transport=UrllibTransport(),
        layout=BUNDLE_LAYOUT,
    )
    served = set(live.organization_repositories())
    recorded = {
        str(entry["name"])
        for entry in recording["json"][
            f"https://api.github.com/users/{ORGANIZATION_IDENTITY.rsplit('/', 1)[-1]}"
            "/repos?per_page=100"
        ]
    }
    assert recorded <= served, f"the capture records repositories upstream no longer serves: {recorded - served}"
    for repository, commit in recording["capture"]["commits"].items():
        if repository not in ORGANIZATION_ALLOWLIST:
            continue
        assert live.revision_of(f"{repository}/LICENSE") == commit, (
            f"{repository} has moved since the capture; rebuild it with "
            "tests/fixtures/provider_git_org/build_capture.py"
        )
