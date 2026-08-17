"""The `mcp-content` reference marketplace: transport only, and revisionless.

CL-mvet AC5, AC6, and AC7.

The provider is access-controlled, and this slice deliberately implements **no
credential handling**: no acquisition, no storage, no token exchange, no
transmission. The adapter takes a credential *reference* and a caller-owned
transport, which is what makes AC6 structural rather than a promise -- a module
that never receives a secret cannot write one anywhere. The transport in these
tests holds a token exactly the way a real client would, so the assertion that
the token reaches no artifact is a real one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.foreign_cache import TofuDrift  # noqa: E402
from lib.providers.mcp_content import (  # noqa: E402
    CredentialReferenceRequired,
    CredentialValueRefused,
    McpContentProvider,
    ProviderUnauthenticated,
)
from lib.providers.reference_rights import EXECUTIVE_CIRCLE_IDENTITY  # noqa: E402
from lib.providers.rights import ProjectionRefused, RightsPresentation  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    install_marketplace_item,
    marketplace_inventory,
)

from foreign_admission_support import admitting  # noqa: E402

#: The secret a real subscriber client would hold. It exists in these tests only
#: so that "the token reaches no artifact" is checkable rather than assumed.
SUBSCRIBER_TOKEN = "ec-live-2f5a9c41d7e84b0fa6c3e19b7d520148"

CREDENTIAL_REFERENCE = "executive-circle-subscriber"

#: The public repository ADR-0011 records as explicitly NOT this provider. It is
#: never a fallback when the endpoint is unreachable.
NOT_THIS_PROVIDER = "https://github.com/NateBJones-Projects/OB1"

#: The provider's own vocabulary, as `CL-r8rr` recorded it: two typed
#: collections, a readable `asset_id` for the Library identity, and an opaque
#: UUID as the only key the fetch tools accept. This suite is about credential
#: isolation and rights rather than about the transport, but its fixture speaks
#: the tools the server actually serves -- a fixture that answered a vocabulary
#: no server has would prove those properties about nothing.
KIT_ASSET_ID = "decision-brief"
KIT_UUID = "b4e2f6a0-1c3d-4e5f-8a9b-0c1d2e3f4a5b"
KIT_ID = f"prompt-kits/{KIT_ASSET_ID}"
KIT_CONTENT = "---\ntitle: Decision Brief\n---\n\nFrame the decision.\n"


class SubscriberTransport:
    """A token-bearing MCP client, exactly as an operator's own client would be.

    The token lives here, in the caller's transport, and is never handed to the
    adapter. That separation is the credential isolation ADR-0011 requires, and
    it is why this slice needs no credential-handling code to satisfy AC6.
    """

    def __init__(self, token: str, content: str | None = None) -> None:
        self._token = token
        self._content = KIT_CONTENT if content is None else content
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def call(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        self.calls.append((tool, dict(arguments)))
        assert self._token, "a real client authenticates; this one records that it did"
        if tool == "list_prompt_kits":
            return [
                {
                    "id": KIT_UUID,
                    "asset_id": KIT_ASSET_ID,
                    "name": "decision-brief",
                    "status": "published",
                    "audience_access": "standard",
                }
            ]
        if tool == "list_guides":
            return []
        if tool == "get_prompt_kit":
            if arguments.get("id") != KIT_UUID:
                raise KeyError(arguments.get("id"))
            return {
                "id": KIT_UUID,
                "asset_id": KIT_ASSET_ID,
                "asset_type": "promptkit",
                "content": self._content,
            }
        raise AssertionError(f"unexpected tool call: {tool}")


def _entry() -> dict[str, object]:
    return {
        "name": "executive-circle",
        "source": EXECUTIVE_CIRCLE_IDENTITY,
        "type": "git",
        "provider_kind": "mcp-content",
        "auth_ref": CREDENTIAL_REFERENCE,
        "auth_scope": "prompt-kits:read",
    }


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


def _presenter(recorder: list[str]):
    """An operator presenter that records what it was shown before accepting."""

    def present(presentation: RightsPresentation):
        recorder.append(presentation.statement)
        return presentation.acknowledge(
            operator="test-operator", acknowledged_at="2026-08-09T12:00:00Z"
        )

    return present


def _install(tmp_path: Path, transport: SubscriberTransport, shown: list[str]):
    provider, result = marketplace_inventory(_entry(), mcp_transport=transport)
    item = result.inventory.resolve(f"{EXECUTIVE_CIRCLE_IDENTITY}#{KIT_ID}")
    # `CL-lt51`: this kit is a foreign steward's Prompt, which is
    # model-instructing content and therefore admission-required. The suite is
    # about credential isolation and rights, so it records the decision for
    # exactly the bytes it retrieves.
    fetched = provider.fetch(item.upstream_id, item.upstream_revision)
    # The operator's review of these bytes is not part of the install's transport
    # budget, so the extra read that produced them is not counted against it.
    # What the surrounding assertions are about is which tools the *install*
    # calls and what reaches disk.
    transport.calls.clear()
    outcome = install_marketplace_item(
        item,
        provider=provider,
        state=_state(tmp_path),
        scope="project",
        target="machine_local",
        target_root=tmp_path / "machine-local" / "decision-brief",
        present=_presenter(shown),
        ledger=admitting(
            item.qualified_identity(),
            {entry.path: entry.content for entry in fetched.files},
            item.library_type,
        ),
    )
    return provider, item, outcome


def _all_artifact_text(tmp_path: Path) -> str:
    """Every byte this install wrote anywhere under the test root."""
    chunks: list[str] = []
    for path in sorted(tmp_path.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(errors="replace"))
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# AC5 — MCP transport produces a typed receipt only
# ---------------------------------------------------------------------------


def test_prompt_receipt_without_mcp_edge(tmp_path: Path) -> None:
    """A prompt kit fetched over MCP produces a **Prompt** receipt and nothing else.

    ADR-0011 states it as an invariant: the transport that delivered an artifact
    contributes nothing to that artifact's type, scope, dependencies, or
    ownership. So the assertions are about what does *not* exist as much as what
    does -- no `mcp:` dependency edge, no global ownership edge, no harness MCP
    registration anywhere the install wrote.
    """
    transport = SubscriberTransport(SUBSCRIBER_TOKEN)
    shown: list[str] = []
    _, item, outcome = _install(tmp_path, transport, shown)

    assert item.library_type == "prompt", (
        "the receipt is for the fetched item's own type, not for the transport"
    )
    assert outcome.receipt.library_type == "prompt"
    assert outcome.receipt.library_name == "decision-brief"
    assert outcome.receipt.provider_identity == EXECUTIVE_CIRCLE_IDENTITY

    receipt = outcome.receipt.to_dict()
    assert "dependencies" not in receipt
    assert "owns" not in receipt and "ownership" not in receipt

    # An `mcp:` **edge** is a value that is itself an MCP identity. The provider
    # identity is the one such value a receipt legitimately carries, so the check
    # is on values rather than on the substring: the recorded rights evidence
    # says the words "MCP endpoint" in prose, and flagging that would train a
    # reader to ignore this assertion.
    def _edges(value: object) -> list[str]:
        if isinstance(value, str):
            return [value] if value.startswith("mcp:") else []
        if isinstance(value, dict):
            return [edge for item in value.values() for edge in _edges(item)]
        if isinstance(value, (list, tuple)):
            return [edge for item in value for edge in _edges(item)]
        return []

    assert _edges(receipt) == [EXECUTIVE_CIRCLE_IDENTITY], (
        "the only MCP identity a receipt carries is the provider it came from; "
        "the transport creates no dependency edge of its own"
    )

    # No harness MCP registration and no global ownership edge: the install wrote
    # a cache object, a receipt store, a pin store, and the projected files, and
    # nothing else at all.
    written = {
        path.relative_to(tmp_path).parts[0]
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert written <= {"cache", "project", "global", "machine-local"}
    assert not list((tmp_path / "global").rglob("*.foreign-receipts.json")) or all(
        json.loads(path.read_text()).get("receipts") == []
        for path in (tmp_path / "global").rglob("*.foreign-receipts.json")
    ), "a project-scope install creates no global ownership edge"

    tools = [tool for tool, _ in transport.calls]
    assert tools.count("get_prompt_kit") == 1, (
        "the install fetches the item it is installing, once"
    )
    assert set(tools) <= {"list_prompt_kits", "list_guides", "get_prompt_kit"}


def test_the_provider_is_not_substituted_when_unreachable() -> None:
    """An unreachable token-scoped provider is a refusal, never a fallback.

    ADR-0011 records a distinct public repository that is explicitly not this
    provider. The availability answer must name the credential reference and must
    not name that repository, because a helpful substitution here would attach one
    party's content to another party's identity.
    """
    provider = McpContentProvider(
        server_name="executive-circle", auth_ref=CREDENTIAL_REFERENCE, transport=None
    )
    availability = provider.availability()
    assert availability.state == "unavailable"
    assert CREDENTIAL_REFERENCE in (availability.reason or "")
    assert NOT_THIS_PROVIDER not in (availability.reason or "")

    # Normalizing an unreachable token-scoped provider is a typed refusal that
    # names the credential reference. An empty inventory would have been the
    # dangerous alternative: indistinguishable from a provider that genuinely
    # serves nothing, and one reconciliation away from marking every installed
    # item upstream-vanished.
    with pytest.raises(ProviderUnauthenticated) as refusal:
        marketplace_inventory(_entry(), mcp_transport=None)
    assert CREDENTIAL_REFERENCE in str(refusal.value)
    assert NOT_THIS_PROVIDER not in str(refusal.value)


# ---------------------------------------------------------------------------
# AC6 — credentials never enter artifacts
# ---------------------------------------------------------------------------


def test_no_credential_in_cache_or_receipt(tmp_path: Path) -> None:
    """The subscriber token appears in no cache object, receipt, or projection.

    Checked over **every file the install wrote**, not over the fields someone
    remembered to look at: a credential that leaks into a diagnostic string in
    the receipt history is just as leaked as one in the cache.
    """
    transport = SubscriberTransport(SUBSCRIBER_TOKEN)
    shown: list[str] = []
    provider, _, outcome = _install(tmp_path, transport, shown)

    artifacts = _all_artifact_text(tmp_path)
    assert SUBSCRIBER_TOKEN not in artifacts
    assert SUBSCRIBER_TOKEN not in json.dumps(outcome.receipt.to_dict())
    assert SUBSCRIBER_TOKEN not in "\n".join(shown)

    # What IS recorded is the reference and its scope, and only that.
    requirement = provider.auth_requirements()[0]
    assert requirement.reference == CREDENTIAL_REFERENCE
    assert requirement.scope == "prompt-kits:read"
    assert requirement.required is True
    assert SUBSCRIBER_TOKEN not in json.dumps(
        {"reference": requirement.reference, "scope": requirement.scope}
    )


def test_a_credential_value_cannot_take_a_reference_slot() -> None:
    """`auth_ref` is a name. Free text or a pasted secret is refused."""
    with pytest.raises(CredentialReferenceRequired):
        McpContentProvider(server_name="executive-circle", auth_ref="")

    with pytest.raises(CredentialValueRefused):
        McpContentProvider(
            server_name="executive-circle",
            auth_ref="Bearer ec-live-2f5a9c41d7e84b0fa6c3e19b7d520148 for the api",
        )


# ---------------------------------------------------------------------------
# AC7 — revisionless content is pin-only and projection-blocked
# ---------------------------------------------------------------------------


def test_tofu_pin_and_blocked_projection(tmp_path: Path) -> None:
    """Revisionless: TOFU-pinned, no polling, committed projection blocked.

    Four claims in one place because they are one property seen from four sides.
    """
    transport = SubscriberTransport(SUBSCRIBER_TOKEN)
    provider, result = marketplace_inventory(_entry(), mcp_transport=transport)
    item = result.inventory.resolve(f"{EXECUTIVE_CIRCLE_IDENTITY}#{KIT_ID}")

    # 1. Revisionless: the adapter declares no revision capability, so the item
    #    carries no upstream revision and cannot be asked for one.
    assert "revision_of" not in provider.capabilities()
    assert item.upstream_revision is None
    with pytest.raises(ValueError, match="revisionless"):
        provider.fetch(KIT_ID, "0" * 40)

    # 2. Committed projection is blocked by default, and the refusal names the
    #    rights state that caused it.
    assert item.rights.fetch_authorization == "granted"
    assert item.rights.install_rights == "unknown"
    assert item.projection_eligibility["project_committed"] == "blocked"
    with pytest.raises(ProjectionRefused) as refusal:
        install_marketplace_item(
            item,
            provider=provider,
            state=_state(tmp_path / "committed"),
            scope="project",
            target="project_committed",
            target_root=tmp_path / "committed" / "vendored",
        )
    message = str(refusal.value)
    assert "install_rights" in message and "unknown" in message

    # 3. First use pins the normalized digest; the pin is a record of what was
    #    first seen, not a proof of upstream authenticity.
    shown: list[str] = []
    _, _, outcome = _install(tmp_path / "local", transport, shown)
    assert outcome.pin is not None
    assert "first-use-pinned" in outcome.events
    assert outcome.receipt.upstream_revision is None
    assert shown and "install_rights" in shown[0], (
        "the rights state is displayed before the machine-local mutation"
    )

    # 4. A re-fetch that disagrees with the pin is fail-closed drift naming both
    #    digests. It never re-pins and never overwrites.
    moved = SubscriberTransport(SUBSCRIBER_TOKEN, content="different bytes\n")
    drifted_provider, drifted = marketplace_inventory(_entry(), mcp_transport=moved)
    drifted_item = drifted.inventory.resolve(f"{EXECUTIVE_CIRCLE_IDENTITY}#{KIT_ID}")
    with pytest.raises(TofuDrift) as drift:
        install_marketplace_item(
            drifted_item,
            provider=drifted_provider,
            state=_state(tmp_path / "local"),
            scope="project",
            target="machine_local",
            target_root=tmp_path / "local" / "machine-local" / "decision-brief",
            present=_presenter([]),
        )
    assert outcome.pin.normalized_content_digest in str(drift.value)
