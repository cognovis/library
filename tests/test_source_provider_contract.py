"""Source provider capability contract (CL-coif AC1, AC2, AC7).

ADR-0011 `Source Provider Contract`: every capability is explicitly declared, a
consumer asks `capabilities()` and degrades deterministically, and `enumerate`
is remote-only with no local checkout.

The `git-repo` evidence runs against a recorded capture of the live provider
(`tests/fixtures/provider_git_repo/`). `test_git_repo_live_enumeration_matches_recording`
re-fetches the real provider when `NETWORK_TESTS=1` and fails if the recording
has drifted, so the offline evidence stays bound to reality instead of to a
hand-written fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers import contract as contract_module  # noqa: E402
from lib.providers.contract import (  # noqa: E402
    AuthRequirement,
    Availability,
    CapabilityNotDeclared,
    FetchedFile,
    FetchedItem,
    ItemDescription,
    OPTIONAL_CAPABILITIES,
    ProviderItem,
    REQUIRED_CAPABILITIES,
    SourceProvider,
    validate_capability_declaration,
)
from lib.providers.git_repo import GitRepoProvider  # noqa: E402
from lib.providers.normalize import normalize_inventory  # noqa: E402
from lib.providers.registration import (  # noqa: E402
    RegistrationError,
    register_provider,
)
from lib.providers.wiring import source_revision  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "provider_git_repo"
MATTPOCOCK = "https://github.com/mattpocock/skills"


class RecordedTransport:
    """Replays a recorded provider capture and records every requested URL."""

    def __init__(self, recording: dict[str, object]) -> None:
        self._json = recording["json"]
        self._bytes = recording.get("bytes", {})
        self.requests: list[str] = []

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> object:
        self.requests.append(url)
        try:
            return self._json[url]
        except KeyError as exc:  # pragma: no cover - a recording gap is a test bug
            raise AssertionError(f"no recorded response for {url}") from exc

    def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        self.requests.append(url)
        try:
            return self._bytes[url].encode("utf-8")
        except KeyError as exc:  # pragma: no cover
            raise AssertionError(f"no recorded body for {url}") from exc


def _recording() -> dict[str, object]:
    return json.loads((FIXTURE_DIR / "mattpocock-skills.json").read_text())


def _provider(transport: RecordedTransport | None = None) -> GitRepoProvider:
    transport = transport or RecordedTransport(_recording())
    return GitRepoProvider(
        repository_url=MATTPOCOCK,
        ref="main",
        transport=transport,
    )


def test_remote_source_verifies_the_declared_commit_instead_of_branch_head() -> None:
    declared = "1" * 40
    branch_head = "2" * 40
    identity = "https://github.com/acme/kit"
    commit_url = f"https://api.github.com/repos/acme/kit/commits/{declared}"
    transport = RecordedTransport(
        {
            "json": {
                "https://api.github.com/repos/acme/kit/git/ref/heads/main": {
                    "object": {"sha": branch_head}
                },
                commit_url: {"sha": declared},
            }
        }
    )
    catalog = {
        "sources": {
            "catalogs": [
                {
                    "name": "fixture",
                    "source": identity,
                    "default_branch": "main",
                }
            ]
        }
    }

    verified = source_revision(
        identity,
        catalog=catalog,
        http_transport=transport,
        expected_revision=declared,
    )

    assert verified == declared
    assert transport.requests == [commit_url]


def test_remote_source_refuses_network_when_remote_access_is_disabled() -> None:
    declared = "1" * 40
    identity = "https://github.com/acme/kit"
    transport = RecordedTransport({"json": {}})
    catalog = {
        "sources": {
            "catalogs": [
                {
                    "name": "fixture",
                    "source": identity,
                    "default_branch": "main",
                }
            ]
        }
    }

    with pytest.raises(LookupError, match="offline verification"):
        source_revision(
            identity,
            catalog=catalog,
            http_transport=transport,
            expected_revision=declared,
            allow_remote=False,
        )

    assert transport.requests == []


# ---------------------------------------------------------------------------
# AC1 — remote-only enumeration of a nested layout
# ---------------------------------------------------------------------------


def test_git_repo_enumerates_nested_layout_without_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nested `skills/<category>/<name>/SKILL.md` layout, with no checkout.

    The fixed shallow scan the platform used before could not reach these paths.
    "No local checkout" is enforced, not asserted: any subprocess call or temp
    directory creation during enumeration fails the test, and the working
    directory must be untouched afterwards.
    """

    def _no_subprocess(*args: object, **kwargs: object) -> None:
        raise AssertionError("a provider must not shell out to reach a remote source")

    def _no_tempdir(*args: object, **kwargs: object) -> None:
        raise AssertionError("a provider must not materialize a local checkout")

    monkeypatch.setattr(subprocess, "run", _no_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _no_subprocess)
    monkeypatch.setattr(subprocess, "check_output", _no_subprocess)
    monkeypatch.setattr(tempfile, "mkdtemp", _no_tempdir)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _no_tempdir)
    monkeypatch.chdir(tmp_path)

    transport = RecordedTransport(_recording())
    provider = _provider(transport)

    items = provider.enumerate()

    assert list(tmp_path.iterdir()) == []
    assert transport.requests, "enumeration must reach the provider over its transport"

    by_id = {item.upstream_id: item for item in items}
    nested = by_id["skills/engineering/implement"]
    assert nested.upstream_name == "implement"
    assert nested.collection_membership == ("skills", "engineering")

    # Every item sits at depth 3, which is exactly what a shallow scan misses.
    assert all(item.upstream_id.count("/") == 2 for item in items)
    assert {item.collection_membership[1] for item in items} == {
        "engineering",
        "in-progress",
        "misc",
        "productivity",
    }
    assert len(items) == 35

    # describe() classifies without fetching content bytes.
    description = provider.describe("skills/engineering/implement")
    assert description.library_type == "skill"
    assert description.content_identity  # the tree's blob sha
    assert not any("/blobs/" in url for url in transport.requests)


def test_git_repo_normalizes_the_live_layout_into_inventory() -> None:
    """enumerate + describe produce complete normalized items (AC1 with AC3)."""
    provider = _provider()
    result = normalize_inventory(provider)

    item = result.inventory.resolve(f"{MATTPOCOCK}#skills/engineering/implement")
    assert item.provider_identity == MATTPOCOCK
    assert item.upstream_name == "implement"
    assert item.collection_membership == ("skills", "engineering")
    assert item.library_type == "skill"
    assert item.library_name == "implement"
    assert item.upstream_revision == "84fdeffd12f2ee307994d1eb6feb48173b6e0502"
    assert item.rights.fetch_authorization in {"granted", "denied", "unknown"}
    assert item.provider_availability.state == "available"
    assert result.costs == ()
    assert len(result.inventory) == 35


def _synthetic_recording(tree: list[dict], *, truncated: bool = False) -> dict:
    commit = "0" * 40
    return {
        "json": {
            "https://api.github.com/repos/acme/kit/git/ref/heads/main": {
                "object": {"sha": commit}
            },
            f"https://api.github.com/repos/acme/kit/git/trees/{commit}?recursive=1": {
                "sha": commit,
                "truncated": truncated,
                "tree": tree,
            },
        },
        "bytes": {},
    }


def _synthetic_provider(recording: dict) -> GitRepoProvider:
    return GitRepoProvider(
        repository_url="https://github.com/acme/kit",
        ref="main",
        transport=RecordedTransport(recording),
    )


def test_git_repo_lists_a_root_level_item_instead_of_dropping_it() -> None:
    """A marker at the repository root means the repository is the item."""
    provider = _synthetic_provider(
        _synthetic_recording(
            [
                {"path": "SKILL.md", "type": "blob", "sha": "abc"},
                {"path": "docs/README.md", "type": "blob", "sha": "def"},
            ]
        )
    )
    items = provider.enumerate()
    assert [(item.upstream_id, item.upstream_name) for item in items] == [(".", "kit")]
    assert items[0].collection_membership == ()


def test_git_repo_refuses_a_truncated_listing() -> None:
    """A partial inventory is never presented as a complete one."""
    from lib.providers.git_repo import ProviderInventoryIncomplete

    provider = _synthetic_provider(
        _synthetic_recording(
            [{"path": "skills/a/SKILL.md", "type": "blob", "sha": "abc"}], truncated=True
        )
    )
    with pytest.raises(ProviderInventoryIncomplete):
        provider.enumerate()


def test_git_repo_verifies_content_with_the_provider_native_hash() -> None:
    """`verify` is a Git object hash, not the Library normalized digest."""
    import hashlib

    provider = _provider()
    content = b"# body\n"
    blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode("utf-8") + content).hexdigest()
    assert provider.verify(content, blob_sha) is True
    assert provider.verify(content + b"tampered", blob_sha) is False


def test_git_repo_reports_unavailable_instead_of_raising() -> None:
    """Provider outage is a recorded state, not an exception in the consumer."""
    from lib.providers.git_repo import ProviderTransportError

    class DeadTransport:
        def get_json(self, url: str, headers: dict[str, str] | None = None) -> object:
            raise ProviderTransportError("connection refused")

        def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
            raise ProviderTransportError("connection refused")

    provider = GitRepoProvider(
        repository_url="https://github.com/acme/kit", ref="main", transport=DeadTransport()
    )
    availability = provider.availability()
    assert availability.state == "unavailable"
    assert "connection refused" in (availability.reason or "")


def test_git_repo_rights_evidence_reports_a_located_licence() -> None:
    provider = _provider()
    evidence = provider.rights_evidence()
    assert evidence.located is True
    assert evidence.source and evidence.source.endswith("/LICENSE")

    without_licence = _synthetic_provider(
        _synthetic_recording([{"path": "skills/a/SKILL.md", "type": "blob", "sha": "abc"}])
    )
    absent = without_licence.rights_evidence()
    assert absent.located is False
    assert absent.source is None


def test_git_repo_fetch_returns_the_complete_item_at_a_pinned_commit() -> None:
    """Complete means every file of the item, not just its marker file.

    `implement` ships `SKILL.md` **and** `agents/openai.yaml`. Returning only
    the marker would hand a cache an incomplete item while reporting success.
    """
    transport = RecordedTransport(_recording())
    provider = _provider(transport)
    fetched = provider.fetch("skills/engineering/implement")

    assert fetched.paths() == ("SKILL.md", "agents/openai.yaml")
    assert fetched.primary_path == "SKILL.md"
    assert fetched.primary.startswith(b"---\n")
    assert fetched.revision == "84fdeffd12f2ee307994d1eb6feb48173b6e0502"
    assert all(file.upstream_content_identity for file in fetched.files)
    assert all(
        "84fdeffd12f2ee307994d1eb6feb48173b6e0502" in url
        for url in transport.requests
        if "raw.githubusercontent" in url
    )


def test_git_repo_fetch_honors_an_explicit_revision() -> None:
    """A caller that pins a revision gets that revision, not the current ref."""
    recording = _recording()
    sha = "84fdeffd12f2ee307994d1eb6feb48173b6e0502"
    provider = _provider(RecordedTransport(recording))
    fetched = provider.fetch("skills/engineering/implement", sha)
    assert fetched.revision == sha


def test_git_repo_fetch_reads_the_tree_of_the_requested_revision() -> None:
    """File list and blob identities come from the fetched revision's tree.

    A tree cached against the adapter's ref would let a pinned fetch report
    revision B while structurally describing revision A: A's file list, A's blob
    shas. That is fabricated provenance, so the tree is keyed by commit.
    """
    ref_commit = "a" * 40
    pinned_commit = "b" * 40
    recording = {
        "json": {
            "https://api.github.com/repos/acme/kit/git/ref/heads/main": {
                "object": {"sha": ref_commit}
            },
            f"https://api.github.com/repos/acme/kit/git/trees/{ref_commit}?recursive=1": {
                "truncated": False,
                "tree": [{"path": "skills/one/SKILL.md", "type": "blob", "sha": "sha-at-a"}],
            },
            f"https://api.github.com/repos/acme/kit/git/trees/{pinned_commit}?recursive=1": {
                "truncated": False,
                "tree": [
                    {"path": "skills/one/SKILL.md", "type": "blob", "sha": "sha-at-b"},
                    {"path": "skills/one/extra.md", "type": "blob", "sha": "extra-at-b"},
                ],
            },
        },
        "bytes": {
            f"https://raw.githubusercontent.com/acme/kit/{pinned_commit}/skills/one/SKILL.md": "a",
            f"https://raw.githubusercontent.com/acme/kit/{pinned_commit}/skills/one/extra.md": "b",
        },
    }
    provider = _synthetic_provider(recording)
    fetched = provider.fetch("skills/one", pinned_commit)

    assert fetched.revision == pinned_commit
    assert fetched.paths() == ("SKILL.md", "extra.md")
    assert {file.upstream_content_identity for file in fetched.files} == {
        "sha-at-b",
        "extra-at-b",
    }


def test_git_repo_refuses_an_ambiguous_root_and_nested_layout() -> None:
    """A repository-level item and nested items would own the same bytes."""
    from lib.providers.git_repo import AmbiguousItemLayout

    provider = _synthetic_provider(
        _synthetic_recording(
            [
                {"path": "SKILL.md", "type": "blob", "sha": "root"},
                {"path": "skills/one/SKILL.md", "type": "blob", "sha": "nested"},
            ]
        )
    )
    with pytest.raises(AmbiguousItemLayout):
        provider.enumerate()


def test_skill_class_is_curated_and_never_guessed_from_upstream() -> None:
    """No upstream field distinguishes navigator from procedure.

    ADR-0011 classifies `implement` as `procedure` and `ask-matt` as
    `navigator`, and both ship `disable-model-invocation: true`. A rule derived
    from that flag therefore misclassifies one of the ADR's own examples, so
    `skill_class` is Library-curated and absent when uncurated.
    """
    ask_matt = f"{MATTPOCOCK}#skills/engineering/ask-matt"
    implement = f"{MATTPOCOCK}#skills/engineering/implement"

    uncurated = normalize_inventory(_provider()).inventory.resolve(ask_matt)
    assert uncurated.library_type == "skill"
    assert "skill_class" not in uncurated.classification
    assert uncurated.classification["skill_class_source"] == "not-curated"
    assert uncurated.classification["content_inspected"] == "no"

    curated = {
        "skills/engineering/ask-matt": "navigator",
        "skills/engineering/implement": "procedure",
    }
    ask_matt_result = normalize_inventory(
        _provider(),
        selector="skills/engineering/ask-matt",
        inspect_content=True,
        curated_skill_classes=curated,
    )
    implement_result = normalize_inventory(
        _provider(),
        selector="skills/engineering/implement",
        inspect_content=True,
        curated_skill_classes=curated,
    )
    curated_result = ask_matt_result
    curated_ask_matt = ask_matt_result.inventory.resolve(ask_matt)
    curated_implement = implement_result.inventory.resolve(implement)

    assert curated_ask_matt.classification["skill_class"] == "navigator"
    assert curated_implement.classification["skill_class"] == "procedure"
    assert curated_ask_matt.classification["skill_class_source"] == "library-curated"

    # The upstream flag is recorded as the fact it is, and it is identical for
    # both items -- which is exactly why it cannot be the discriminator.
    assert curated_ask_matt.classification["upstream_model_invocation"] == "disabled"
    assert curated_implement.classification["upstream_model_invocation"] == "disabled"
    assert {cost.path for cost in curated_result.costs} == {"content-inspection"}


def test_curated_skill_class_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError, match="skill_class must be one of"):
        normalize_inventory(
            _provider(),
            curated_skill_classes={"skills/engineering/ask-matt": "router"},
        )


def test_normalization_resolves_the_revision_before_it_fetches() -> None:
    """Classification bytes and the recorded revision come from the same pin."""
    order: list[str] = []

    class OrderingProvider(MinimalProvider):
        def capabilities(self) -> frozenset[str]:
            return frozenset(REQUIRED_CAPABILITIES) | {"revision_of"}

        def revision_of(self, upstream_id: str) -> str:
            order.append("revision_of")
            return "rev-1"

        def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
            order.append(f"fetch:{revision}")
            return FetchedItem(
                upstream_id=upstream_id,
                revision=revision,
                files=(FetchedFile(path="anchor.md", content=b"body\n"),),
                primary_path="anchor.md",
            )

    result = normalize_inventory(OrderingProvider())
    assert order == ["revision_of", "fetch:rev-1"]
    assert next(iter(result.inventory)).upstream_revision == "rev-1"


def test_normalization_refuses_content_from_another_revision() -> None:
    """A provider that substitutes a revision fails closed."""
    from lib.providers.normalize import ProvenanceMismatch

    class DriftingProvider(MinimalProvider):
        def capabilities(self) -> frozenset[str]:
            return frozenset(REQUIRED_CAPABILITIES) | {"revision_of"}

        def revision_of(self, upstream_id: str) -> str:
            return "rev-1"

        def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
            return FetchedItem(
                upstream_id=upstream_id,
                revision="rev-2",
                files=(FetchedFile(path="anchor.md", content=b"body\n"),),
                primary_path="anchor.md",
            )

    with pytest.raises(ProvenanceMismatch):
        normalize_inventory(DriftingProvider())


def test_normalization_refuses_a_fetch_with_no_revision_proof() -> None:
    """Omitting the revision is not a pass; it is the absence of proof."""
    from lib.providers.normalize import ProvenanceMismatch

    class SilentProvider(MinimalProvider):
        def capabilities(self) -> frozenset[str]:
            return frozenset(REQUIRED_CAPABILITIES) | {"revision_of"}

        def revision_of(self, upstream_id: str) -> str:
            return "rev-1"

        def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
            return FetchedItem(
                upstream_id=upstream_id,
                revision=None,
                files=(FetchedFile(path="anchor.md", content=b"body\n"),),
                primary_path="anchor.md",
            )

    with pytest.raises(ProvenanceMismatch):
        normalize_inventory(SilentProvider())


def test_normalization_refuses_content_belonging_to_another_item() -> None:
    """The bytes must belong to the item whose record will carry them."""
    from lib.providers.normalize import ProvenanceMismatch

    class SwappingProvider(MinimalProvider):
        def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
            return FetchedItem(
                upstream_id="kits/somewhere-else",
                revision=revision,
                files=(FetchedFile(path="anchor.md", content=b"body\n"),),
                primary_path="anchor.md",
            )

    with pytest.raises(ProvenanceMismatch):
        normalize_inventory(SwappingProvider())


@pytest.mark.skipif(
    os.environ.get("NETWORK_TESTS") != "1",
    reason="set NETWORK_TESTS=1 to re-verify the recording against the live provider",
)
def test_git_repo_live_enumeration_matches_recording() -> None:
    """The recorded capture still matches the live provider (no local checkout).

    Two directions are checked, because a one-directional subset assertion can
    hold forever while the recording quietly becomes a museum piece:

    - every recorded item still exists upstream (the recording is not stale);
    - the pinned commit still resolves, and the item set at that pin is exactly
      what was recorded (the capture is faithful, not merely compatible).

    New upstream items are reported, not failed: the recording is a pinned
    capture, and upstream growth is not a defect in this repository. The
    scheduled `provider-liveness` CI job runs this test so the check does not
    depend on a person remembering to.
    """
    from lib.providers.git_repo import UrllibTransport

    recording = _recording()
    pinned = recording["capture"]["commit"]

    live_head = GitRepoProvider(
        repository_url=MATTPOCOCK, ref="main", transport=UrllibTransport()
    )
    assert live_head.availability().state == "available"

    live_ids = {item.upstream_id for item in live_head.enumerate()}
    recorded_ids = {item.upstream_id for item in _provider().enumerate()}
    assert recorded_ids <= live_ids, (
        "the recording references items that no longer exist upstream: "
        f"{sorted(recorded_ids - live_ids)}"
    )
    assert "skills/engineering/implement" in live_ids

    live_at_pin = GitRepoProvider(
        repository_url=MATTPOCOCK, ref=pinned, transport=UrllibTransport()
    )
    assert {item.upstream_id for item in live_at_pin.enumerate()} == recorded_ids

    new_upstream = sorted(live_ids - recorded_ids)
    if new_upstream:
        print(f"upstream has {len(new_upstream)} item(s) newer than the recording: {new_upstream}")


# ---------------------------------------------------------------------------
# AC2 — declared-absence behavior
# ---------------------------------------------------------------------------


class MinimalProvider(SourceProvider):
    """A provider declaring only the required floor.

    It does not declare `revision_of`, `verify`, `rights_evidence`, or
    `describe`. Calling an undeclared capability is a programming error here,
    never a control-flow signal: the consumer must read `capabilities()` first.
    """

    identity_value = "urn:test:minimal"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def identity(self) -> str:
        return self.identity_value

    def capabilities(self) -> frozenset[str]:
        return frozenset(REQUIRED_CAPABILITIES)

    def enumerate(self, selector: object = None) -> tuple[ProviderItem, ...]:
        self.calls.append("enumerate")
        return (
            ProviderItem(
                upstream_id="kits/anchor",
                upstream_name="Anchor Kit",
                collection_membership=("kits",),
                content_hint="anchor.md",
            ),
        )

    def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
        self.calls.append("fetch")
        return FetchedItem(
            upstream_id=upstream_id,
            revision=revision,
            files=(FetchedFile(path="anchor.md", content=b"---\nname: anchor\n---\nbody\n"),),
            primary_path="anchor.md",
        )

    def auth_requirements(self) -> tuple[AuthRequirement, ...]:
        return ()

    def availability(self) -> Availability:
        return Availability(state="available", observed_at="2026-08-08T20:00:00Z")


class LyingProvider(MinimalProvider):
    """Declares a capability it never implements."""

    def capabilities(self) -> frozenset[str]:
        return frozenset(REQUIRED_CAPABILITIES) | {"revision_of"}


class BrokenProvider(LyingProvider):
    """Declares and overrides a capability whose implementation is broken."""

    def revision_of(self, upstream_id: str) -> str:
        raise CapabilityNotDeclared("this adapter's revision support is broken")


def test_optional_capability_absence_is_declared() -> None:
    """Consumers degrade from `capabilities()`, never from an exception."""
    provider = MinimalProvider()
    declared = provider.capabilities()

    assert OPTIONAL_CAPABILITIES.isdisjoint(declared)
    validate_capability_declaration(provider)

    result = normalize_inventory(provider)
    item = result.inventory.resolve(f"{provider.identity_value}#kits/anchor")

    # revision_of absent -> revisionless provider, recorded as null.
    assert item.upstream_revision is None
    # rights_evidence absent -> rights stay unknown with no invented evidence.
    assert item.rights.to_dict() == {
        "fetch_authorization": "unknown",
        "install_rights": "unknown",
        "redistribution_rights": "unknown",
        "derivative_rights": "unknown",
        "evidence_source": None,
        # Per-grant evidence (CL-n7ex) is empty for the same reason the shared
        # source is None: nothing was located, so nothing is invented.
        "grant_evidence": {},
    }
    # verify absent -> the Library normalized digest is the only integrity proof.
    assert "verify" in result.absent_capabilities
    assert set(result.absent_capabilities) == {
        "describe",
        "revision_of",
        "verify",
        "rights_evidence",
        # Slice 6 (CL-mvet) adds per-item rights evidence as a declared optional
        # capability. A provider that does not declare it is stating that one
        # rights answer covers every item it lists.
        "item_rights_evidence",
        # Slice 6 also adds the member manifest: a source-read list of an item's
        # files. Its absence means an install's completeness rests on the
        # adapter's own declaration, recorded as the weakest evidence rather
        # than as the quiet default.
        "member_manifest",
    }
    # describe absent -> the costlier fetch-then-classify path, recorded as cost.
    assert [cost.capability for cost in result.costs] == ["describe"]
    assert result.costs[0].path == "fetch-then-classify"
    assert provider.calls == ["enumerate", "fetch"]

    # No consumer reached an undeclared capability, and doing so is an error
    # rather than a silently caught signal.
    with pytest.raises(CapabilityNotDeclared):
        provider.revision_of("kits/anchor")


def test_normalization_never_catches_capability_errors() -> None:
    """A broken capability surfaces from normalization; it is not swallowed."""
    with pytest.raises(CapabilityNotDeclared):
        normalize_inventory(BrokenProvider())


def test_capability_declaration_is_validated_against_the_adapter() -> None:
    """A declaration that outruns the implementation is refused up front."""
    validate_capability_declaration(_provider())
    with pytest.raises(ValueError, match="declared but not implemented"):
        validate_capability_declaration(LyingProvider())
    with pytest.raises(ValueError, match="declared but not implemented"):
        normalize_inventory(LyingProvider())


def test_normalization_reads_no_provider_identity_to_decide_behavior() -> None:
    """The normalizer's source must contain no provider name or kind branch."""
    from lib.providers import normalize as normalize_module

    source = Path(normalize_module.__file__).read_text()
    for token in ("github", "mattpocock", "git-repo", "git-org", "mcp-content"):
        assert token not in source.lower(), token


def test_git_repo_declares_every_capability_it_implements() -> None:
    provider = _provider()
    declared = provider.capabilities()
    assert REQUIRED_CAPABILITIES <= declared
    assert {"describe", "revision_of", "verify", "rights_evidence"} <= declared
    assert isinstance(provider.describe("skills/engineering/implement"), ItemDescription)
    assert provider.auth_requirements() == ()
    assert contract_module.CAPABILITIES == REQUIRED_CAPABILITIES | OPTIONAL_CAPABILITIES


# ---------------------------------------------------------------------------
# AC7 — registration installs nothing
# ---------------------------------------------------------------------------


def _tree(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*")}


def test_registration_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration answers "where content may be found" and mutates nothing else."""
    home = tmp_path / "home"
    cache_root = home / ".local" / "share" / "library"
    project = tmp_path / "project"
    for path in (cache_root, project):
        path.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.chdir(project)

    catalog: dict[str, object] = {"sources": {"marketplaces": []}}
    before_cache = _tree(cache_root)
    before_project = _tree(project)

    outcome = register_provider(
        catalog,
        {
            "name": "mattpocock",
            "source": MATTPOCOCK,
            "type": "git",
            "provider_kind": "git-repo",
            "rights": {
                "fetch_authorization": "granted",
                "install_rights": "granted",
                "redistribution_rights": "granted",
                "derivative_rights": "granted",
                "evidence_source": "upstream LICENSE (MIT)",
            },
        },
    )

    assert outcome.provider_identity == MATTPOCOCK
    assert outcome.cache_objects == ()
    assert outcome.receipts == ()
    assert outcome.projections == ()
    assert catalog["sources"]["marketplaces"][0]["name"] == "mattpocock"

    assert _tree(cache_root) == before_cache
    assert _tree(project) == before_project
    assert not (project / ".library.lock").exists()
    assert not (home / ".config" / "library" / "global.lock").exists()


def test_registration_refuses_an_unknown_provider_kind() -> None:
    with pytest.raises(RegistrationError):
        register_provider(
            {"sources": {"marketplaces": []}},
            {
                "name": "unknown-kind",
                "source": "https://example.invalid/x",
                "type": "git",
                "provider_kind": "carrier-pigeon",
            },
        )


def test_registration_refuses_a_git_org_without_an_allowlist() -> None:
    entry = {
        "name": "disler",
        "source": "https://github.com/disler",
        "type": "git",
        "provider_kind": "git-org",
    }
    with pytest.raises(RegistrationError):
        register_provider({"sources": {"marketplaces": []}}, entry)

    allowed = dict(entry, allowlist=["pi-vs-claude-code"])
    catalog: dict[str, object] = {"sources": {"marketplaces": []}}
    assert register_provider(catalog, allowed).marketplace["allowlist"] == [
        "pi-vs-claude-code"
    ]


def test_registration_refuses_a_duplicate_provider_identity() -> None:
    catalog: dict[str, object] = {"sources": {"marketplaces": []}}
    entry = {
        "name": "mattpocock",
        "source": MATTPOCOCK,
        "type": "git",
        "provider_kind": "git-repo",
    }
    register_provider(catalog, entry)
    with pytest.raises(RegistrationError):
        register_provider(catalog, dict(entry, name="mattpocock-alias"))
