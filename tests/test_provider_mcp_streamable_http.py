"""The streamable-HTTP transport for the `mcp-content` provider (`CL-r8rr`).

The subscriber endpoint of the profiled content server **is** the credential:
the token is a path segment of the URL. So the suite's central assertion is not
that some field is redacted, it is that a sentinel URL carrying a sentinel token
reaches no message, no diagnostic, no serialization, and no file the install
writes. The sentinel exists here for exactly that reason -- a leak that cannot be
observed is a leak nobody notices.

The recorded SSE bodies under `fixtures/provider_mcp_streamable_http/` carry the
real response *framing* and the real listing *shape* with synthetic content.
They contain no endpoint and no token.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import pickle
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.foreign_cache import TofuDrift  # noqa: E402
from lib.providers.mcp_content import (  # noqa: E402
    AUDIENCE_NOT_PUBLISHED,
    ContentCollection,
    McpContentProvider,
    McpResponseInvalid,
    ProviderUnauthenticated,
    SERVER_PROFILES,
)
from lib.providers.mcp_http import (  # noqa: E402
    ConflictingRegistration,
    CredentialSerializationRefused,
    McpEndpointInvalid,
    McpEndpointUnreachable,
    McpHttpError,
    McpProtocolError,
    McpRpcError,
    McpToolFailed,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_HEADER,
    SUPPORTED_PROTOCOL_VERSIONS,
    StreamableHttpMcpTransport,
    redact_endpoints,
    registered_endpoint,
    terminal_envelope,
)
from lib.providers.reference_rights import EXECUTIVE_CIRCLE_IDENTITY  # noqa: E402
from lib.providers.rights import RightsPresentation  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    install_marketplace_item,
    marketplace_inventory,
    mcp_server_name,
)

from foreign_admission_support import admitting  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "provider_mcp_streamable_http"

#: A synthetic subscriber URL whose path segment is a synthetic token. It stands
#: in for the shape of the real credential so that "the credential reaches no
#: artifact" is a checkable claim rather than an assumption. Nothing here is real.
SENTINEL_TOKEN = "sentinel-a1b2c3-not-a-real-subscriber-token"
SENTINEL_HOST = "content.invalid"
SENTINEL_ENDPOINT = f"https://{SENTINEL_HOST}/api/mcp/subscriber/{SENTINEL_TOKEN}"

SERVER_NAME = "executive-circle"
PROVIDER_IDENTITY = EXECUTIVE_CIRCLE_IDENTITY
CREDENTIAL_REFERENCE = "executive-circle-subscriber"

KIT_UUID = "3f6c1c9e-0b5a-4c21-9d7e-1a2b3c4d5e6f"
KIT_ASSET = "20260805_948_promptkit_1"
KIT_UPSTREAM_ID = f"prompt-kits/{KIT_ASSET}"
SUPERSEDED_UPSTREAM_ID = "prompt-kits/20260806_949_promptkit_2"
GUIDE_UUID = "11111111-2222-3333-4444-555555555555"
GUIDE_UPSTREAM_ID = "guides/20260807_950_guide_1"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def frame(envelope: Mapping[str, Any]) -> str:
    """One SSE `message` event carrying a JSON-RPC envelope."""
    return "event: message\ndata: " + json.dumps(envelope, separators=(",", ":")) + "\n\n"


def recorded_payload(name: str) -> Any:
    """The tool payload a recorded fixture carries, as the transport returns it."""
    envelope = terminal_envelope(fixture(name))
    return json.loads(envelope["result"]["content"][0]["text"])


def tool_body(payload: Any, request_id: int = 42) -> str:
    """A recorded-shape tool result carrying a caller-supplied payload."""
    return frame(
        {
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(payload, separators=(",", ":"))}
                ]
            },
            "jsonrpc": "2.0",
            "id": request_id,
        }
    )


class RecordedEndpoint:
    """An opener replaying recorded SSE bodies, keyed by JSON-RPC method and tool.

    It is the seam the real transport is driven through, so the framing, the
    envelope correlation, and the contract mapping are all exercised together
    rather than each against its own convenient stub.

    It **restamps the response id to the id it was sent**, because that is what a
    JSON-RPC server does. A recorded fixture necessarily froze whatever id the
    probe happened to use, and asserting against that frozen number would test
    the recording rather than the client; restamping keeps the recorded framing
    and shape while letting correlation be exercised honestly. The one test that
    needs a *mismatched* id posts a body directly instead of going through here.
    """

    def __init__(self, bodies: Mapping[str, str] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self._bodies = dict(bodies or {})

    def __call__(self, request: Any, timeout: float) -> tuple[int, str]:
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        self.headers.append(dict(request.headers))
        method = payload["method"]
        if method == "notifications/initialized":
            assert "id" not in payload, "a notification carries no id"
            # 202 with an empty body is the conforming answer, and it must not be
            # parsed as a response envelope.
            return 202, ""
        if method == "initialize":
            return 200, self._restamped(fixture("initialize.sse"), payload["id"])
        assert method == "tools/call", method
        tool = payload["params"]["name"]
        body = self._bodies.get(tool) or fixture(f"{tool}.sse")
        return 200, self._restamped(body, payload["id"])

    @staticmethod
    def _restamped(body: str, request_id: Any) -> str:
        """The recorded body with every response id set to the requested one."""
        rebuilt = []
        for line in body.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("data:"):
                document = stripped.split(":", 1)[1].strip()
                try:
                    parsed = json.loads(document)
                except ValueError:
                    rebuilt.append(line)
                    continue
                if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                    parsed["id"] = request_id
                    ending = "\n" if line.endswith("\n") else ""
                    rebuilt.append(
                        "data: " + json.dumps(parsed, separators=(",", ":")) + ending
                    )
                    continue
            rebuilt.append(line)
        return "".join(rebuilt)

    def methods(self) -> list[str]:
        return [item["method"] for item in self.requests]

    def tool_calls(self) -> list[tuple[str, Mapping[str, Any]]]:
        return [
            (item["params"]["name"], item["params"]["arguments"])
            for item in self.requests
            if item["method"] == "tools/call"
        ]


def transport(bodies: Mapping[str, str] | None = None) -> tuple[Any, RecordedEndpoint]:
    endpoint = RecordedEndpoint(bodies)
    return (
        StreamableHttpMcpTransport(
            SENTINEL_ENDPOINT, identity=PROVIDER_IDENTITY, opener=endpoint
        ),
        endpoint,
    )


def entry() -> dict[str, object]:
    return {
        "name": SERVER_NAME,
        "source": PROVIDER_IDENTITY,
        "type": "git",
        "provider_kind": "mcp-content",
        "auth_ref": CREDENTIAL_REFERENCE,
        "auth_scope": "prompt-kits:read",
    }


def foreign_state(tmp_path: Path) -> ForeignState:
    project_lock = tmp_path / "project" / ".library.lock"
    global_lock = tmp_path / "global" / "global.lock"
    project_lock.parent.mkdir(parents=True, exist_ok=True)
    global_lock.parent.mkdir(parents=True, exist_ok=True)
    return ForeignState.for_locks(
        cache_root=tmp_path / "cache",
        project_lock=project_lock,
        global_lock=global_lock,
    )


def accepting(recorder: list[str]):
    def present(presentation: RightsPresentation):
        recorder.append(presentation.statement)
        return presentation.acknowledge(
            operator="test-operator", acknowledged_at="2026-08-16T12:00:00Z"
        )

    return present


# ---------------------------------------------------------------------------
# Seam 1 -- SSE framing
# ---------------------------------------------------------------------------


def test_the_terminal_response_envelope_is_taken() -> None:
    """All `data:` lines are read; the terminal *response* wins.

    The recorded body carries a comment line, two progress notifications, and one
    result whose JSON is split across two `data:` lines. A parser that took the
    first envelope would return a notification, and one that took the literally
    last event would return one too -- both would be a response that never came.
    """
    envelope = terminal_envelope(fixture("framing.sse"))
    assert envelope["id"] == 9
    assert envelope["result"]["content"][0]["text"] == "[]"


def test_a_plain_json_body_parses() -> None:
    """`application/json` is legal framing for the same profile, so it parses too."""
    envelope = terminal_envelope(fixture("plain_result.json"))
    assert envelope["id"] == 8
    assert "result" in envelope


def test_a_body_with_no_response_envelope_is_a_protocol_error() -> None:
    with pytest.raises(McpProtocolError):
        terminal_envelope('event: message\ndata: {"jsonrpc":"2.0"}\n\n')


def test_one_event_yields_one_payload_so_split_json_is_not_two_envelopes() -> None:
    """Per SSE, an event's `data:` lines concatenate into one payload.

    The removed per-line fallback accepted each line on its own, which turned a
    stream carrying two *halves* of an envelope into two valid-looking ones. Here
    each line is independently valid JSON and only the joined document is the
    response -- a parser with the fallback would return the second line's object.
    """
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"half":"one"}}\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"half":"two"}}\n\n'
    )
    with pytest.raises(McpProtocolError):
        # The join is not valid JSON, so the event is skipped entirely rather
        # than mined for whichever line happened to parse.
        terminal_envelope(body)


# ---------------------------------------------------------------------------
# Seam 2 -- failures are distinct typed facts, and none of them names the endpoint
# ---------------------------------------------------------------------------


def test_a_tool_error_result_names_the_tool_and_not_the_endpoint() -> None:
    client, _ = transport({"get_prompt_kit": fixture("tool_error.sse")})
    with pytest.raises(McpToolFailed) as failure:
        client.call("get_prompt_kit", {"id": KIT_UUID})
    message = str(failure.value)
    assert "get_prompt_kit" in message
    assert SENTINEL_TOKEN not in message and SENTINEL_ENDPOINT not in message


def test_a_server_that_echoes_only_the_credential_path_segment_is_redacted() -> None:
    """The URL-shaped floor does not catch a bare path segment. This does.

    Reproduced by review: a server whose error text quotes only the token segment
    of the path -- no scheme, no host -- leaks exactly the credential, and
    `https?://\\S+` matches none of it.
    """
    echoing = tool_body([], 1).replace(
        '"text":"[]"',
        f'"text":"not found under /api/mcp/subscriber/{SENTINEL_TOKEN}"',
    )
    # Make it an error result so the echoed text reaches an exception message.
    echoing = echoing.replace('"result":{', '"result":{"isError":true,', 1)
    client, _ = transport({"get_prompt_kit": echoing})
    with pytest.raises(McpToolFailed) as failure:
        client.call("get_prompt_kit", {"id": KIT_UUID})
    message = str(failure.value)
    assert SENTINEL_TOKEN not in message
    assert SENTINEL_HOST not in message


def test_a_jsonrpc_error_names_the_tool_and_not_the_endpoint() -> None:
    client, _ = transport({"list_prompt_kits": fixture("rpc_error.sse")})
    with pytest.raises(McpRpcError) as failure:
        client.call("list_prompt_kits", {"limit": 100})
    message = str(failure.value)
    assert "list_prompt_kits" in message
    assert SENTINEL_TOKEN not in message and SENTINEL_ENDPOINT not in message


def test_a_non_2xx_status_is_its_own_typed_fact() -> None:
    """An HTTP status failure is not a connection failure and not a tool failure."""

    def refusing(request: Any, timeout: float) -> tuple[int, str]:
        raise HTTPError(SENTINEL_ENDPOINT, 402, "Payment Required", {}, None)

    client = StreamableHttpMcpTransport(
        SENTINEL_ENDPOINT, identity=PROVIDER_IDENTITY, opener=refusing
    )
    with pytest.raises(McpHttpError) as failure:
        client.call("list_prompt_kits", {"limit": 100})
    message = str(failure.value)
    assert "402" in message and PROVIDER_IDENTITY in message
    assert SENTINEL_TOKEN not in message and SENTINEL_ENDPOINT not in message


# ---------------------------------------------------------------------------
# Seam 3 -- AC3: unreachable is a typed refusal, and it leaks nothing
# ---------------------------------------------------------------------------


def unreachable_transport() -> Any:
    def failing(request: Any, timeout: float) -> tuple[int, str]:
        # A `URLError` whose reason text embeds the URL. CPython's own default
        # text does not, but a reason can carry a host, so the defense is real.
        raise URLError(f"[Errno 61] Connection refused while opening {SENTINEL_ENDPOINT}")

    return StreamableHttpMcpTransport(
        SENTINEL_ENDPOINT, identity=PROVIDER_IDENTITY, opener=failing
    )


def test_a_connection_failure_is_typed_and_carries_no_endpoint() -> None:
    with pytest.raises(McpEndpointUnreachable) as failure:
        unreachable_transport().call("list_prompt_kits", {"limit": 100})
    message = str(failure.value)
    assert PROVIDER_IDENTITY in message
    assert SENTINEL_TOKEN not in message and SENTINEL_ENDPOINT not in message


def test_an_unreachable_endpoint_reports_unavailable_and_substitutes_nothing() -> None:
    """AC3. The provider says `unavailable` and names the credential reference."""
    provider = McpContentProvider(
        server_name=SERVER_NAME,
        auth_ref=CREDENTIAL_REFERENCE,
        transport=unreachable_transport(),
    )
    availability = provider.availability()
    assert availability.state == "unavailable"
    reason = availability.reason or ""
    assert PROVIDER_IDENTITY in reason
    assert SENTINEL_TOKEN not in reason and SENTINEL_ENDPOINT not in reason
    assert "github.com" not in reason, (
        "an unreachable token-scoped provider is a refusal, never a fallback to "
        "some other source"
    )


def test_an_adapter_defect_is_not_reported_as_provider_unavailability() -> None:
    """A `TypeError` from this adapter must propagate, not become a receipt fact.

    The bare `except Exception` this replaced turned a bug in the Library into an
    `unavailable` observation about somebody else's server, and that observation
    is persisted into foreign receipts.
    """

    class Defective:
        def call(self, tool: str, arguments: Mapping[str, Any]) -> Any:
            raise TypeError("a defect in the caller, not a fact about the endpoint")

    provider = McpContentProvider(
        server_name=SERVER_NAME, auth_ref=CREDENTIAL_REFERENCE, transport=Defective()
    )
    with pytest.raises(TypeError):
        provider.availability()


def test_redaction_removes_a_url_from_any_message() -> None:
    assert SENTINEL_TOKEN not in redact_endpoints(
        f"failed to open {SENTINEL_ENDPOINT} after 3 tries"
    )
    assert redact_endpoints("no url here") == "no url here"


# ---------------------------------------------------------------------------
# Credential containment: the endpoint must not be usable, printable, or copyable
# ---------------------------------------------------------------------------


def test_a_schemeless_endpoint_is_refused_without_quoting_it() -> None:
    """`Request` would raise `ValueError` carrying the value, and it is not URL-shaped.

    That text therefore survives `redact_endpoints`, and on the availability path
    it is persisted into a foreign receipt. Refused at construction instead.
    """
    schemeless = f"{SENTINEL_HOST}/api/mcp/subscriber/{SENTINEL_TOKEN}"
    with pytest.raises(McpEndpointInvalid) as refusal:
        StreamableHttpMcpTransport(schemeless, identity=PROVIDER_IDENTITY)
    message = str(refusal.value)
    assert SENTINEL_TOKEN not in message and SENTINEL_HOST not in message


def test_a_plaintext_endpoint_is_refused() -> None:
    """The token is a path segment, so `http` would transmit it in cleartext."""
    with pytest.raises(McpEndpointInvalid) as refusal:
        StreamableHttpMcpTransport(
            f"http://{SENTINEL_HOST}/api/mcp/subscriber/{SENTINEL_TOKEN}",
            identity=PROVIDER_IDENTITY,
        )
    message = str(refusal.value)
    assert "https" in message
    assert SENTINEL_TOKEN not in message and SENTINEL_HOST not in message


def test_a_mutated_endpoint_is_still_refused_at_the_post() -> None:
    """The dataclass field stays writable, so the second line has to hold too."""
    client, _ = transport()
    client.endpoint = f"{SENTINEL_HOST}/no-scheme/{SENTINEL_TOKEN}"
    with pytest.raises(McpEndpointInvalid) as refusal:
        client.call("list_prompt_kits", {"limit": 100})
    message = str(refusal.value)
    assert SENTINEL_TOKEN not in message and SENTINEL_HOST not in message


def test_the_transport_repr_carries_the_identity_and_not_the_endpoint() -> None:
    """A repr reaches a failing assertion and a traceback frame, so it is checked."""
    client, _ = transport()
    printed = repr(client)
    assert PROVIDER_IDENTITY in printed
    assert SENTINEL_TOKEN not in printed and SENTINEL_ENDPOINT not in printed


def test_pickling_or_copying_the_transport_is_refused() -> None:
    """Both reproduce the endpoint verbatim, so the generic path is closed."""
    client, _ = transport()
    with pytest.raises(CredentialSerializationRefused):
        pickle.dumps(client)
    with pytest.raises(CredentialSerializationRefused):
        copy.deepcopy(client)
    with pytest.raises(CredentialSerializationRefused):
        copy.copy(client)


def test_asdict_remains_the_one_documented_way_out() -> None:
    """Stated rather than papered over: `asdict` walks fields and has no hook.

    This test exists so the gap is a recorded fact with a name, not a surprise.
    If a later change closes it, this test fails and the docstring gets fixed.
    """
    client, _ = transport()
    assert SENTINEL_TOKEN in json.dumps(dataclasses.asdict(client), default=str), (
        "asdict still reproduces the endpoint; the module docstring says so"
    )


# ---------------------------------------------------------------------------
# Protocol conformance: lifecycle and response correlation
# ---------------------------------------------------------------------------


def test_the_full_initialization_lifecycle_is_performed_once() -> None:
    """`initialize`, then `notifications/initialized`, then the tool calls.

    The current endpoint tolerates a missing notification; a conforming server
    need not, and a client that skips it is relying on one implementation's
    leniency.
    """
    client, endpoint = transport()
    client.call("list_prompt_kits", {"limit": 100})
    client.call("list_guides", {"limit": 100})

    methods = endpoint.methods()
    assert methods == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
    ]
    assert methods.count("initialize") == 1, "the handshake is per transport, not per call"


def test_the_negotiated_protocol_version_is_echoed_on_every_later_request() -> None:
    client, endpoint = transport()
    client.call("list_prompt_kits", {"limit": 100})

    # urllib capitalizes header names it stores.
    header = PROTOCOL_VERSION_HEADER.capitalize()
    assert header not in endpoint.headers[0], (
        "no revision is negotiated yet when initialize is sent"
    )
    for sent in endpoint.headers[1:]:
        assert sent.get(header) == PROTOCOL_VERSION


def test_an_unsupported_negotiated_revision_is_refused() -> None:
    """A server may negotiate down; this client refuses what it does not speak."""
    negotiated = fixture("initialize.sse").replace(PROTOCOL_VERSION, "1999-01-01")
    endpoint = RecordedEndpoint()
    client = StreamableHttpMcpTransport(
        SENTINEL_ENDPOINT, identity=PROVIDER_IDENTITY, opener=endpoint
    )
    endpoint._bodies = {}
    original = endpoint.__call__

    def negotiating(request: Any, timeout: float) -> tuple[int, str]:
        payload = json.loads(request.data.decode("utf-8"))
        if payload["method"] == "initialize":
            endpoint.requests.append(payload)
            endpoint.headers.append(dict(request.headers))
            return 200, RecordedEndpoint._restamped(negotiated, payload["id"])
        return original(request, timeout)

    client.opener = negotiating
    with pytest.raises(McpProtocolError) as refusal:
        client.call("list_prompt_kits", {"limit": 100})
    assert "1999-01-01" in str(refusal.value)
    assert list(SUPPORTED_PROTOCOL_VERSIONS)[0] in str(refusal.value)


def test_an_initialize_without_a_protocol_version_is_refused() -> None:
    stripped = fixture("initialize.sse").replace(
        f'"protocolVersion":"{PROTOCOL_VERSION}",', ""
    )
    client, endpoint = transport()
    client.opener = lambda request, timeout: (
        200,
        RecordedEndpoint._restamped(
            stripped, json.loads(request.data.decode("utf-8"))["id"]
        ),
    )
    with pytest.raises(McpProtocolError) as refusal:
        client.call("list_prompt_kits", {"limit": 100})
    assert "protocolVersion" in str(refusal.value)


def test_a_response_for_a_different_request_id_is_refused() -> None:
    """Correlation, not position, is what makes an answer the right answer.

    Taking the terminal response unconditionally would accept a stale or
    misrouted body as this request's answer.
    """
    with pytest.raises(McpProtocolError) as refusal:
        terminal_envelope(fixture("mismatched_id.sse"), expected_id=2)
    message = str(refusal.value)
    assert "2" in message

    # And the same through the real client, which sends id 2 for its first tool
    # call while the fixture answers id 99.
    client, _ = transport()
    client.opener = _uncorrelated_opener()
    with pytest.raises(McpProtocolError):
        client.call("list_prompt_kits", {"limit": 100})


def _uncorrelated_opener():
    """An opener that answers initialize correctly and then misroutes."""
    inner = RecordedEndpoint()

    def opener(request: Any, timeout: float) -> tuple[int, str]:
        payload = json.loads(request.data.decode("utf-8"))
        if payload["method"] in ("initialize", "notifications/initialized"):
            return inner(request, timeout)
        return 200, fixture("mismatched_id.sse")

    return opener


def test_a_response_missing_the_jsonrpc_version_is_refused() -> None:
    body = frame({"id": 7, "result": {"content": []}})
    with pytest.raises(McpProtocolError):
        terminal_envelope(body, expected_id=7)


# ---------------------------------------------------------------------------
# Seam 4 -- endpoint resolution from the operator's harness registrations
# ---------------------------------------------------------------------------


def codex_config(tmp_path: Path, url: str) -> Path:
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[mcp_servers.other]\n"
        'url = "https://example.invalid/other"\n'
        "\n"
        f"[mcp_servers.{SERVER_NAME}]\n"
        f'url = "{url}"\n'
    )
    return path


def cursor_config(tmp_path: Path, url: str) -> Path:
    path = tmp_path / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {SERVER_NAME: {"url": url}}}))
    return path


def claude_config(tmp_path: Path, url: str) -> Path:
    path = tmp_path / "claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {SERVER_NAME: {"url": url}}}))
    return path


def test_the_endpoint_resolves_from_any_harness_registration(tmp_path: Path) -> None:
    absent = tmp_path / "absent"
    from_codex = registered_endpoint(
        SERVER_NAME,
        codex_config=codex_config(tmp_path / "codex", SENTINEL_ENDPOINT),
        cursor_config=absent / "mcp.json",
        claude_config=absent / "claude.json",
    )
    assert from_codex == SENTINEL_ENDPOINT

    from_cursor = registered_endpoint(
        SERVER_NAME,
        codex_config=absent / "config.toml",
        cursor_config=cursor_config(tmp_path / "cursor", SENTINEL_ENDPOINT),
        claude_config=absent / "claude.json",
    )
    assert from_cursor == SENTINEL_ENDPOINT

    from_claude = registered_endpoint(
        SERVER_NAME,
        codex_config=absent / "config.toml",
        cursor_config=absent / "mcp.json",
        claude_config=claude_config(tmp_path / "claude", SENTINEL_ENDPOINT),
    )
    assert from_claude == SENTINEL_ENDPOINT


def test_agreeing_registrations_resolve_to_their_shared_value(tmp_path: Path) -> None:
    """All sources are read even after a hit, so a disagreement can be seen."""
    assert (
        registered_endpoint(
            SERVER_NAME,
            codex_config=codex_config(tmp_path / "codex", SENTINEL_ENDPOINT),
            cursor_config=cursor_config(tmp_path / "cursor", SENTINEL_ENDPOINT),
            claude_config=claude_config(tmp_path / "claude", SENTINEL_ENDPOINT),
        )
        == SENTINEL_ENDPOINT
    )


def test_disagreeing_registrations_are_refused_naming_paths_only(tmp_path: Path) -> None:
    """One of them is stale; picking silently would misattribute a pin and receipt."""
    stale = f"https://{SENTINEL_HOST}/api/mcp/subscriber/stale-0000-token-value"
    codex = codex_config(tmp_path / "codex", SENTINEL_ENDPOINT)
    cursor = cursor_config(tmp_path / "cursor", stale)
    with pytest.raises(ConflictingRegistration) as refusal:
        registered_endpoint(
            SERVER_NAME,
            codex_config=codex,
            cursor_config=cursor,
            claude_config=tmp_path / "absent" / "claude.json",
        )
    message = str(refusal.value)
    assert str(codex) in message and str(cursor) in message
    assert SENTINEL_TOKEN not in message and "stale-0000-token-value" not in message


def test_codex_wins_the_documented_precedence(tmp_path: Path) -> None:
    """Precedence only decides among sources that agree; it never hides a conflict."""
    absent = tmp_path / "absent"
    assert (
        registered_endpoint(
            SERVER_NAME,
            codex_config=codex_config(tmp_path / "codex", SENTINEL_ENDPOINT),
            cursor_config=cursor_config(tmp_path / "cursor", SENTINEL_ENDPOINT),
            claude_config=absent / "claude.json",
        )
        == SENTINEL_ENDPOINT
    )


def test_an_unregistered_server_resolves_to_nothing(tmp_path: Path) -> None:
    """Absence is `None`, never a guessed or partial endpoint."""
    assert (
        registered_endpoint(
            "not-registered",
            codex_config=codex_config(tmp_path / "codex", SENTINEL_ENDPOINT),
            cursor_config=cursor_config(tmp_path / "cursor", SENTINEL_ENDPOINT),
            claude_config=tmp_path / "absent" / "claude.json",
        )
        is None
    )
    assert (
        registered_endpoint(
            SERVER_NAME,
            codex_config=tmp_path / "absent" / "config.toml",
            cursor_config=tmp_path / "absent" / "mcp.json",
            claude_config=tmp_path / "absent" / "claude.json",
        )
        is None
    )


def test_a_malformed_registration_is_skipped_without_echoing_it(tmp_path: Path) -> None:
    broken = tmp_path / "config.toml"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("this is not toml = = =\n")
    assert (
        registered_endpoint(
            SERVER_NAME,
            codex_config=broken,
            cursor_config=cursor_config(tmp_path / "cursor", SENTINEL_ENDPOINT),
            claude_config=tmp_path / "absent" / "claude.json",
        )
        == SENTINEL_ENDPOINT
    )


def test_one_server_name_derivation_serves_both_callers() -> None:
    """The transport key and the provider identity must come from one rule.

    They diverged: one fell back to the entry's `source`, the other to its
    `name`, so an entry whose source carried no separator could open a connection
    against a server the receipt did not name.
    """
    assert mcp_server_name({"source": "mcp:executive-circle", "name": "other"}) == (
        "executive-circle"
    )
    assert mcp_server_name({"source": "bare-source", "name": "other"}) == "bare-source"
    provider = McpContentProvider(
        server_name=mcp_server_name({"source": "mcp:executive-circle"}),
        auth_ref=CREDENTIAL_REFERENCE,
    )
    assert provider.identity() == PROVIDER_IDENTITY


# ---------------------------------------------------------------------------
# Seam 5 -- AC1 unit half: the profiled contract mapping
# ---------------------------------------------------------------------------


def test_both_collections_enumerate_with_audience_access(tmp_path: Path) -> None:
    """AC1. Kits and guides normalize, and `audience_access` reaches the item."""
    client, endpoint = transport()
    _, result = marketplace_inventory(entry(), mcp_transport=client)
    items = {item.upstream_id: item for item in result.inventory}

    assert set(items) == {
        KIT_UPSTREAM_ID,
        SUPERSEDED_UPSTREAM_ID,
        GUIDE_UPSTREAM_ID,
    }
    assert [tool for tool, _ in endpoint.tool_calls()] == [
        "list_prompt_kits",
        "list_guides",
    ], "each collection is listed exactly once per provider instance"
    assert all(
        arguments == {"limit": 100} for _, arguments in endpoint.tool_calls()
    ), "the server's own maximum is what is asked for"

    kit = items[KIT_UPSTREAM_ID]
    assert kit.provider_identity == PROVIDER_IDENTITY
    assert kit.library_type == "prompt"
    assert kit.classification["audience_access"] == "standard"
    assert kit.collection_membership == ("prompt-kits",)
    assert items[SUPERSEDED_UPSTREAM_ID].classification["audience_access"] == (
        "executive_circle"
    )
    assert "SUPERSEDED" in items[SUPERSEDED_UPSTREAM_ID].upstream_name, (
        "a listing is not a recommendation; the admission gate decides "
        "installability, so upstream's own junk stays visible"
    )


def test_a_guide_records_that_audience_access_was_not_published() -> None:
    """Guides publish no `audience_access`; the absence is recorded, not invented."""
    client, _ = transport()
    _, result = marketplace_inventory(entry(), mcp_transport=client)
    guide = result.inventory.resolve(f"{PROVIDER_IDENTITY}#{GUIDE_UPSTREAM_ID}")
    assert guide.classification["audience_access"] == AUDIENCE_NOT_PUBLISHED
    assert guide.classification["audience_access"] != "standard", (
        "reading an absent field as the permissive value would grant an audience "
        "nobody published"
    )


def test_fetch_sends_the_uuid_and_projects_the_markdown() -> None:
    """`upstream_id` is the readable asset id; the fetch key is the server's UUID."""
    client, endpoint = transport()
    provider = McpContentProvider(
        server_name=SERVER_NAME, auth_ref=CREDENTIAL_REFERENCE, transport=client
    )
    fetched = provider.fetch(KIT_UPSTREAM_ID)

    assert ("get_prompt_kit", {"id": KIT_UUID}) in endpoint.tool_calls(), (
        "the fetch key is the UUID; the readable asset id is rejected upstream"
    )
    assert fetched.paths() == ("PROMPT.md",)
    assert fetched.primary_path == "PROMPT.md"
    assert b"Frame the decision" in fetched.primary
    assert fetched.revision is None

    guide = provider.fetch(GUIDE_UPSTREAM_ID)
    assert ("get_guide", {"id": GUIDE_UUID}) in endpoint.tool_calls()
    assert guide.paths() == ("GUIDE.md",)


def test_an_empty_content_field_is_refused() -> None:
    client, _ = transport(
        {"get_prompt_kit": tool_body({**recorded_payload("get_prompt_kit.sse"), "content": ""})}
    )
    provider = McpContentProvider(
        server_name=SERVER_NAME, auth_ref=CREDENTIAL_REFERENCE, transport=client
    )
    with pytest.raises(McpResponseInvalid):
        provider.fetch(KIT_UPSTREAM_ID)


def test_a_duplicate_upstream_id_is_refused_rather_than_overwritten() -> None:
    duplicated = recorded_payload("list_prompt_kits.sse")
    duplicated[1] = {**duplicated[1], "asset_id": duplicated[0]["asset_id"]}
    client, _ = transport({"list_prompt_kits": tool_body(duplicated)})
    provider = McpContentProvider(
        server_name=SERVER_NAME, auth_ref=CREDENTIAL_REFERENCE, transport=client
    )
    with pytest.raises(McpResponseInvalid) as refusal:
        provider.enumerate()
    assert KIT_UPSTREAM_ID in str(refusal.value)


def test_the_default_profile_is_unchanged() -> None:
    """An unprofiled server keeps the generic vocabulary and payload shape."""
    provider = McpContentProvider(server_name="example", auth_ref="example-token-ref")
    assert provider.list_tool == "list_content"
    assert provider.fetch_tool == "get_content"
    assert [collection.name for collection in provider.collections] == [""]
    assert provider.collections[0].limit is None


# ---------------------------------------------------------------------------
# Seam 6 -- an enumeration at the server's cap is degraded, not complete
# ---------------------------------------------------------------------------


def capped_profile(limit: int) -> tuple[ContentCollection, ...]:
    kits, _ = SERVER_PROFILES[SERVER_NAME]
    return (replace(kits, limit=limit),)


def test_a_listing_at_the_cap_is_degraded_and_names_it() -> None:
    client, _ = transport()
    provider = McpContentProvider(
        server_name=SERVER_NAME,
        auth_ref=CREDENTIAL_REFERENCE,
        transport=client,
        collections=capped_profile(2),
    )
    availability = provider.availability()
    assert availability.state == "degraded"
    reason = availability.reason or ""
    assert "prompt-kits" in reason and "2" in reason
    assert len(provider.enumerate()) == 2, (
        "a capped listing stays installable; what changes is that the truncation "
        "is visible instead of read as completeness"
    )


def test_the_cap_reason_records_what_was_observed_not_the_declared_cap() -> None:
    """The trigger is `observed >= cap`, so the two numbers can differ.

    A server answering more than its declared cap would otherwise have the
    sentence "returned the server maximum of 1 entries" written into a receipt --
    a false record of an observation.
    """
    client, _ = transport()
    provider = McpContentProvider(
        server_name=SERVER_NAME,
        auth_ref=CREDENTIAL_REFERENCE,
        transport=client,
        collections=capped_profile(1),
    )
    reason = provider.availability().reason or ""
    assert "2 entries" in reason, "the observed count is what was seen"
    assert "cap of 1" in reason, "the declared cap is what was asked for"


def test_a_listing_below_the_cap_is_available() -> None:
    client, _ = transport()
    provider = McpContentProvider(
        server_name=SERVER_NAME,
        auth_ref=CREDENTIAL_REFERENCE,
        transport=client,
        collections=capped_profile(50),
    )
    assert provider.availability().state == "available"


def test_the_profile_asks_the_server_for_the_limit_it_declares() -> None:
    """A declared cap is only meaningful if it is what goes on the wire.

    This replaces an assertion that compared the profile constant with itself and
    could not fail except by intentional edit.
    """
    client, endpoint = transport()
    provider = McpContentProvider(
        server_name=SERVER_NAME, auth_ref=CREDENTIAL_REFERENCE, transport=client
    )
    provider.enumerate()
    requested = {tool: arguments.get("limit") for tool, arguments in endpoint.tool_calls()}
    declared = {
        collection.list_tool: collection.limit
        for collection in SERVER_PROFILES[SERVER_NAME]
    }
    assert requested == declared
    assert set(requested.values()) == {100}, "the server's documented maximum"


# ---------------------------------------------------------------------------
# Seam 7 and 8 -- AC2: the durable cache transaction, and no credential in it
# ---------------------------------------------------------------------------


def install(tmp_path: Path, bodies: Mapping[str, str] | None = None):
    client, _ = transport(bodies)
    provider, result = marketplace_inventory(entry(), mcp_transport=client)
    item = result.inventory.resolve(f"{PROVIDER_IDENTITY}#{KIT_UPSTREAM_ID}")
    fetched = provider.fetch(item.upstream_id, item.upstream_revision)
    shown: list[str] = []
    outcome = install_marketplace_item(
        item,
        provider=provider,
        state=foreign_state(tmp_path),
        scope="project",
        target="machine_local",
        target_root=tmp_path / "machine-local" / item.library_name,
        present=accepting(shown),
        ledger=admitting(
            item.qualified_identity(),
            {member.path: member.content for member in fetched.files},
            item.library_type,
        ),
    )
    return item, outcome, shown


def test_the_install_pins_receipts_and_fails_closed_on_drift(tmp_path: Path) -> None:
    """AC2. TOFU pin recorded, foreign receipt written, differing bytes refused."""
    item, outcome, shown = install(tmp_path, None)

    assert outcome.pin is not None
    assert "first-use-pinned" in outcome.events
    assert outcome.receipt.provider_identity == PROVIDER_IDENTITY
    assert outcome.receipt.library_type == "prompt"
    assert outcome.receipt.upstream_revision is None
    assert shown, "the rights state is displayed before the machine-local mutation"

    drifted_body = tool_body(
        {**recorded_payload("get_prompt_kit.sse"), "content": "different bytes\n"}
    )
    drifted_client, _ = transport({"get_prompt_kit": drifted_body})
    drifted_provider, drifted_result = marketplace_inventory(
        entry(), mcp_transport=drifted_client
    )
    drifted_item = drifted_result.inventory.resolve(item.qualified_identity())
    with pytest.raises(TofuDrift) as drift:
        install_marketplace_item(
            drifted_item,
            provider=drifted_provider,
            state=foreign_state(tmp_path),
            scope="project",
            target="machine_local",
            target_root=tmp_path / "machine-local" / item.library_name,
            present=accepting([]),
        )
    assert outcome.pin.normalized_content_digest in str(drift.value)


def test_no_endpoint_or_token_reaches_anything_the_install_wrote(tmp_path: Path) -> None:
    """Seam 8. Checked over every byte written, not over remembered fields."""
    _, outcome, shown = install(tmp_path, None)

    written = [path for path in sorted(tmp_path.rglob("*")) if path.is_file()]
    assert written, "the install wrote something, so the check has something to check"
    artifacts = "\n".join(path.read_text(errors="replace") for path in written)
    for secret in (SENTINEL_TOKEN, SENTINEL_ENDPOINT, SENTINEL_HOST):
        assert secret not in artifacts
        assert secret not in json.dumps(outcome.receipt.to_dict())
        assert secret not in "\n".join(shown)

    # What a receipt does carry is the provider identity, which is a name.
    assert PROVIDER_IDENTITY in json.dumps(outcome.receipt.to_dict())


# ---------------------------------------------------------------------------
# The CLI reports the typed observation instead of failing the whole command
# ---------------------------------------------------------------------------


def _library_module():
    import importlib

    return importlib.import_module("library")


def _catalog() -> dict[str, Any]:
    return {"sources": {"catalogs": [], "marketplaces": [entry()]}}


def _inventory_args(**overrides: Any) -> argparse.Namespace:
    defaults = {
        "name": SERVER_NAME,
        "selector": None,
        "admitted_maturities": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_an_unreachable_provider_reports_availability_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`normalize_inventory` calls `enumerate` right after `availability()`.

    That call was unprotected, so the command died with a transport error line
    instead of showing the typed `unavailable` observation the ADR promises.
    """
    library = _library_module()
    monkeypatch.setattr(
        library,
        "_marketplace_transport",
        lambda entry: {"mcp_transport": unreachable_transport()},
    )
    code = library.cmd_marketplace_inventory(_inventory_args(), _catalog())
    assert code != 0, "an unreachable provider is a refusal, not an empty inventory"

    printed = capsys.readouterr().err
    assert PROVIDER_IDENTITY in printed
    assert "unavailable" in printed
    assert SENTINEL_TOKEN not in printed and SENTINEL_ENDPOINT not in printed


def test_the_unreachable_report_is_structured_under_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    library = _library_module()
    monkeypatch.setattr(
        library,
        "_marketplace_transport",
        lambda entry: {"mcp_transport": unreachable_transport()},
    )
    code = library.cmd_marketplace_inventory(_inventory_args(json=True), _catalog())
    assert code != 0

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "error"
    payload = json.loads(envelope["message"])
    assert payload["provider_identity"] == PROVIDER_IDENTITY
    assert payload["availability"]["state"] == "unavailable"
    assert payload["items"] == [], (
        "no items, and explicitly not an empty successful listing"
    )
    assert SENTINEL_TOKEN not in json.dumps(payload)


def test_an_unregistered_provider_reports_the_same_typed_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No registration means no transport, which is `ProviderUnauthenticated`."""
    library = _library_module()
    monkeypatch.setattr(library, "_marketplace_transport", lambda entry: {})
    code = library.cmd_marketplace_inventory(_inventory_args(), _catalog())
    assert code != 0
    printed = capsys.readouterr().err
    assert PROVIDER_IDENTITY in printed
    assert CREDENTIAL_REFERENCE in printed


def test_the_unauthenticated_hint_names_the_key_and_the_files_not_a_value() -> None:
    """The old hint said transport was "deliberately not implemented"; it is now."""
    library = _library_module()
    hint = library._mcp_registration_hint(entry())
    assert SERVER_NAME in hint
    for path in library._MCP_REGISTRATION_PATHS:
        assert path in hint
    assert "not implemented" not in hint
    assert SENTINEL_TOKEN not in hint and SENTINEL_ENDPOINT not in hint
