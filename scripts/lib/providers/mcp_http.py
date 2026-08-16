"""A minimal streamable-HTTP MCP client, and nothing else (`CL-r8rr`).

This module supplies the transport `mcp_content.McpContentProvider` deliberately
does not own: the MCP initialization lifecycle, then `tools/call`, over plain
HTTP POST against a stateless streamable-HTTP endpoint. It performs **no contract
mapping**. It returns whatever the tool answered, parsed, and leaves every
question about what that payload means to the adapter above it.

## Why the standard library rather than the `mcp` SDK

The SDK's `streamablehttp_client` is asynchronous and session-oriented. Adopting
it would push an anyio event loop and a `ClientSession` lifecycle into a
synchronous CLI in order to talk to an endpoint that keeps no session at all --
it returns no `Mcp-Session-Id` and requires none. The whole client the profile
needs is one POST with a few headers plus SSE line parsing, so the dependency
would buy machinery this caller cannot use and cost a runtime requirement on
every operator's machine. `urllib.request` and `json` are enough, and the bead
asks for a minimal transport.

## The endpoint is the credential

For the one registered provider of this kind the subscriber token is a **path
segment of the URL**. That inverts the usual assumption that a URL is safe to
print: here, echoing the endpoint is echoing the secret.

Three defenses, each closing a hole review found in the previous one:

1. **Refuse an endpoint that cannot be used safely.** The constructor requires an
   absolute `https://` URL. `https` specifically, because this module's whole
   premise is that the URL is the credential: an `http://` registration would put
   the subscriber token on the wire in cleartext on every call, and accepting one
   would be this module transmitting a secret insecurely rather than an operator
   misconfiguring one. The refusal names neither the value nor its shape.
2. **Never interpolate what the endpoint contains.** Diagnostics name the
   caller-supplied `identity` (`mcp:<server>`). Every string this module folds in
   from an exception or from a server's own response passes through
   `_redact`, which strips URL-shaped substrings *and* this instance's own
   endpoint, host, and long path segments -- because a server that echoes back
   only the credential-bearing path segment leaks it just as thoroughly as one
   that echoes a whole URL, and the URL-shaped floor alone does not catch that.
   Exception chaining is suppressed so a traceback cannot reprint what a message
   removed.
3. **Close the generic serialization path.** `__repr__` prints the identity, and
   pickling and copying raise `CredentialSerializationRefused`.
4. **Do not declare the secret as a field.** `dataclasses.asdict` walks declared
   fields through `getattr` and has no hook to refuse -- but it walks
   `dataclasses.fields`, which skips `InitVar` pseudo-fields and never sees an
   attribute that was only assigned. The endpoint is therefore an `InitVar`
   validated into a plain attribute in `__post_init__`, and `_secrets` -- which
   holds the whole endpoint and its host, and so leaked exactly as much -- is
   assigned the same way. `asdict` reproduces neither.

The precise, checkable claim -- rather than the "stored in exactly one field"
guarantee an earlier revision asserted and review falsified -- is this: the
endpoint reaches the network and nothing else. It is interpolated into no message
here, written to no file here, returned by no method here, and reproduced by no
`repr`, `pickle`, `copy`, or `asdict`. What is deliberately *not* claimed is
inaccessibility: `getattr(client, "endpoint")` still answers, because the
transport has to use the value it holds. A caller naming the attribute is
reaching for the credential on purpose, which was never what these defenses are
about; what they close is the value escaping on its own through a generic path
nobody wrote a line of code to invoke.

A note on what is *not* true, because a load-bearing comment that is false is
worse than no comment: `str(HTTPError(...))` is `HTTP Error 402: Payment
Required` and `str(URLError(...))` is `<urlopen error [Errno 61] Connection
refused>` -- neither embeds the URL by default (verified against CPython
3.14). The defense is still required, because `HTTPError.url` carries it,
`URLError.reason` can carry a host, and `urllib.request.Request` raises
`ValueError: unknown url type: '<the value>'` with the value verbatim.
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

#: The MCP protocol revisions this client implements. A server may negotiate down
#: to a revision it prefers; this client accepts only what it actually speaks,
#: and adding an entry here is a deliberate act with framing consequences.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18",)

#: The revision this client asks for at `initialize`.
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

#: What this client calls itself to a server. A name, carrying nothing about the
#: operator or the machine.
CLIENT_NAME = "library"

#: Anything URL-shaped is replaced wholesale. The token is inside the URL, so
#: removing the path is not enough -- the whole value goes.
_URL_RE = re.compile(r"https?://\S+")

_REDACTED = "<endpoint>"

#: A path segment at least this long is treated as possibly credential-bearing
#: and is stripped from any interpolated text.
#:
#: A floor, and deliberately stated as one. Redacting *every* segment would strip
#: `api`, `mcp`, and `v1` from diagnostics that merely use those words, making
#: the messages unreadable in exchange for guarding strings no credential
#: resembles; leaving long segments alone would miss exactly the shape a
#: subscriber token has. Neither rule can tell a secret from a word, so this one
#: picks the boundary where an opaque value stops looking like English.
_MIN_REDACTABLE_SEGMENT = 8

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

#: The header a client must echo once a protocol revision has been negotiated.
PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"


class McpTransportError(RuntimeError):
    """Base class for every failure this transport reports.

    The subclasses exist because the failures are **distinct facts** a caller may
    reasonably treat differently: an unreachable endpoint is an availability
    observation, an HTTP status is the endpoint refusing at the protocol edge, a
    JSON-RPC error is the server rejecting the call, and a failed tool result is
    the server answering the call with a refusal. Collapsing them into one type
    would force every consumer to parse a message to tell them apart.
    """


class McpEndpointUnreachable(McpTransportError):
    """The endpoint could not be reached at all: DNS, TCP, TLS, or timeout."""


class McpEndpointInvalid(McpTransportError):
    """The endpoint is not a usable absolute `https://` URL.

    Separate from `McpEndpointUnreachable` because nothing was attempted: this is
    a registration this client refuses to dial, not a dial that failed.
    """


class McpHttpError(McpTransportError):
    """The endpoint answered with a non-2xx HTTP status."""


class McpProtocolError(McpTransportError):
    """The body was not the declared framing, or carried no matching response."""


class McpRpcError(McpTransportError):
    """The server answered with a JSON-RPC `error` object."""


class McpToolFailed(McpTransportError):
    """The tool ran and reported failure through `isError: true`.

    Distinct from `McpRpcError` on purpose: the call was well-formed and was
    dispatched. "This item does not exist" is not "this request was invalid".
    """


class CredentialSerializationRefused(TypeError):
    """Something tried to serialize or copy a transport that holds a credential.

    A `TypeError` because that is what `pickle` and `copy` already expect from an
    object that declines to be reproduced, so the refusal arrives as a normal
    failure of those protocols rather than as an exotic one.
    """


class ConflictingRegistration(RuntimeError):
    """Two harness registrations name the same MCP server with different URLs.

    One of them is stale. Picking either silently would mean a fetch, a pin, and
    a receipt could all be attributed to an endpoint the operator believed they
    had replaced, so this is a refusal that names the files and never the values.
    """


def redact_endpoints(text: str) -> str:
    """Every URL-shaped substring replaced, because the token lives in the URL.

    The module-level floor, available to callers that hold no endpoint of their
    own. A transport instance additionally strips its *own* endpoint and path
    segments -- see `StreamableHttpMcpTransport._redact`.
    """
    return _URL_RE.sub(_REDACTED, str(text))


def terminal_envelope(
    body: str, *, expected_id: Any = None, context: str = "the response"
) -> Mapping[str, Any]:
    """The JSON-RPC **response** a streamable-HTTP body carries.

    Both framings the profile admits are accepted, because both are legal for the
    same endpoint and a client that assumed one would break on a server version
    that chose the other:

    - `text/event-stream`, where the `data:` lines of one event are concatenated
      into that event's single payload, per the SSE specification. A body carries
      progress notifications and keep-alive comments alongside the response, so
      every event is read and non-JSON events are skipped.
    - `application/json`, where the whole body is the envelope.

    Correlation, not position, is what makes the answer the right one. When
    `expected_id` is supplied the response must carry `jsonrpc: "2.0"` and
    exactly that id; a body that carries only some other request's response is
    refused rather than accepted because it happened to be last. "The terminal
    response wins" survives only as the tie-breaker it should always have been:
    it picks among responses that already matched.

    Raises:
        McpProtocolError: when the body carries no matching JSON-RPC response.
    """
    responses = [
        payload
        for payload in _payloads(body)
        if isinstance(payload, Mapping) and ("result" in payload or "error" in payload)
    ]
    if not responses:
        raise McpProtocolError(
            f"{context} carried no JSON-RPC response envelope; the body was "
            "neither an SSE stream carrying one nor a JSON-RPC object"
        )
    if expected_id is None:
        return responses[-1]

    matching = [
        payload
        for payload in responses
        if payload.get("id") == expected_id and payload.get("jsonrpc") == "2.0"
    ]
    if not matching:
        # Naming the ids is safe -- they are this client's own counter and the
        # server's echo of it -- and it is the one fact that distinguishes a
        # stale or misrouted response from a malformed one.
        seen = sorted(
            {repr(payload.get("id")) for payload in responses}
        )
        raise McpProtocolError(
            f"{context} carried no JSON-RPC 2.0 response for request id "
            f"{expected_id!r} (the body answered {', '.join(seen) or 'nothing'}), "
            "so it answers some other request and is refused rather than read as "
            "this one's"
        )
    return matching[-1]


def _payloads(body: str) -> list[Any]:
    """Every JSON document the body carries, in the order it carries them.

    One event yields at most one payload. The SSE specification concatenates an
    event's `data:` lines into a single data buffer, so a per-line fallback would
    accept a malformed stream -- two half-written envelopes on separate lines --
    as though it were two valid ones. An event whose joined payload is not JSON
    is skipped.
    """
    if not body.strip():
        return []
    if not any(line.startswith("data:") for line in body.splitlines()):
        parsed = _try_json(body.strip())
        return [parsed[0]] if parsed else []

    payloads: list[Any] = []
    for block in _blocks(body):
        data = [line.split(":", 1)[1].lstrip() for line in block if line.startswith("data:")]
        if not data:
            continue
        joined = _try_json("\n".join(data))
        if joined:
            payloads.append(joined[0])
    return payloads


def _blocks(body: str) -> list[list[str]]:
    """SSE events, split on the blank line that terminates each one."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.strip():
            current.append(line)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _try_json(text: str) -> tuple[Any] | None:
    """The parsed document in a one-tuple, or `None`.

    A one-tuple rather than the value, because `null` is a valid JSON document
    and a bare `None` return could not be told apart from a parse failure.
    """
    try:
        return (json.loads(text),)
    except (TypeError, ValueError):
        return None


def _urlopen(request: urllib.request.Request, timeout: float) -> tuple[int, str]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read().decode("utf-8", errors="replace")


@dataclass(repr=False)
class StreamableHttpMcpTransport:
    """One stateless streamable-HTTP MCP endpoint, as a synchronous tool-call seam.

    Satisfies `mcp_content.McpTransport`. The endpoint is held here, which is what
    lets the adapter above stay a module that never receives a secret.

    Args:
        endpoint: The full endpoint URL, which must be absolute and `https`. For
            a subscriber-scoped server this URL **is** the credential; see the
            module docstring for exactly what is and is not guaranteed about it.
        identity: What diagnostics from this transport name instead of the
            endpoint, conventionally `mcp:<server-name>`. Redacted on the way in,
            so a caller that passes the URL by mistake still leaks nothing.
        client_version: What this client reports about itself at `initialize`. A
            courtesy for the server's logs, not a contract, so it is a plain
            string rather than something read off the installed distribution --
            nothing here behaves differently for any value of it.
        opener: The HTTP seam, `(Request, timeout) -> (status, body)`. Injectable
            so tests never open a socket.

    Raises:
        McpEndpointInvalid: when the endpoint is not an absolute `https://` URL.
    """

    #: An `InitVar`, not a field, and that is the whole of the fourth defense.
    #: `dataclasses.fields` -- and therefore `asdict` -- skips `InitVar`
    #: pseudo-fields, so the validated value is assigned to a plain instance
    #: attribute below and every reader of `self.endpoint` is unaffected. It is
    #: declared first because an `InitVar` still takes a positional slot in the
    #: generated `__init__`, so every existing construction site keeps working.
    endpoint: InitVar[str]
    identity: str = "mcp endpoint"
    client_name: str = CLIENT_NAME
    client_version: str = "2.0.0"
    protocol_version: str = PROTOCOL_VERSION
    timeout: float = 30.0
    opener: Callable[[urllib.request.Request, float], tuple[int, str]] = _urlopen
    _next_id: int = field(default=0, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)
    _negotiated_version: str = field(default="", init=False, repr=False)

    def __post_init__(self, endpoint: str) -> None:
        self.endpoint = self._validated_endpoint(endpoint)
        self.identity = redact_endpoints(str(self.identity or "mcp endpoint")).strip()
        # Undeclared for the same reason as `endpoint`: `_own_secrets` puts the
        # whole endpoint and its netloc in here, so a declared field would have
        # reproduced through `asdict` everything the `InitVar` just kept out.
        self._secrets: tuple[str, ...] = self._own_secrets()

    @staticmethod
    def _validated_endpoint(value: Any) -> str:
        """An absolute `https://` endpoint, or a refusal that quotes nothing.

        Every branch refuses without naming the value. The failure mode this
        closes is precise: `urllib.request.Request` raises `ValueError: unknown
        url type: '<the value>'` for a schemeless string, that text is not
        URL-shaped so the module-level redaction floor does not match it, and on
        the availability path such a string is persisted into a foreign receipt.
        """
        if not isinstance(value, str) or not value.strip():
            raise McpEndpointInvalid(
                "a streamable-HTTP transport requires an endpoint; an absent "
                "registration is the caller's typed unavailability, not an empty URL"
            )
        candidate = value.strip()
        split = urllib.parse.urlsplit(candidate)
        if not split.scheme or not split.netloc:
            raise McpEndpointInvalid(
                "the registered endpoint is not an absolute URL (it carries no "
                "scheme and host). Its value is withheld here because for this "
                "provider kind the URL is the subscriber credential"
            )
        if split.scheme.lower() != "https":
            raise McpEndpointInvalid(
                f"the registered endpoint uses the {split.scheme.lower()!r} scheme; "
                "this transport requires https, because the subscriber token is a "
                "path segment of the URL and any other scheme would put it on the "
                "wire in cleartext on every call"
            )
        return candidate

    def _own_secrets(self) -> tuple[str, ...]:
        """This endpoint's own substrings that must never appear in a message.

        Longest first, so replacing the whole URL wins over replacing its host.
        """
        split = urllib.parse.urlsplit(self.endpoint)
        parts = {self.endpoint, split.netloc}
        parts.update(
            segment
            for segment in split.path.split("/")
            if len(segment) >= _MIN_REDACTABLE_SEGMENT
        )
        if split.query:
            parts.add(split.query)
        return tuple(sorted((part for part in parts if part), key=len, reverse=True))

    def _redact(self, text: Any) -> str:
        """Any text this transport interpolates, with its own endpoint removed.

        The module-level floor catches a whole URL. This catches what that floor
        cannot: a server that echoes back only the credential-bearing path
        segment, or only the host, which is a leak of exactly the same value.
        """
        redacted = redact_endpoints(text)
        for secret in self._secrets:
            redacted = redacted.replace(secret, _REDACTED)
        return redacted

    def __repr__(self) -> str:
        """The identity, never the endpoint.

        The generated dataclass repr would print every field, and a repr reaches
        places no message does: a failing assertion, a debugger, a traceback
        frame summary. Since the endpoint is the credential, the default repr
        would be a leak nobody wrote a line of code to cause.
        """
        return f"{type(self).__name__}(identity={self.identity!r})"

    def __reduce__(self) -> Any:
        """Refuse to be pickled or copied.

        `pickle` and `copy` both route through here, and both would otherwise
        reproduce the endpoint verbatim into a byte string or a second object --
        a credential crossing a process boundary or landing in a cache because
        something upstream serialized a structure that happened to contain a
        transport. Nothing in this platform needs to serialize one, so the
        generic path is closed rather than made careful.
        """
        raise CredentialSerializationRefused(
            f"{type(self).__name__} holds a credential-bearing endpoint and "
            "refuses to be serialized or copied; pass the live object, or "
            "re-resolve the registration where it is needed"
        )

    # -- The `McpTransport` seam ---------------------------------------------

    def call(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        """Call one tool and return its payload, parsed.

        The session is initialized lazily on the first call: a transport built
        for a provider whose availability is never asked opens no connection.

        Returns:
            The tool result's text content parsed as JSON, or the raw text when
            it is not JSON. Contract mapping belongs to the adapter, so nothing
            about the payload's shape is assumed here.
        """
        self._initialize()
        result = self._request(
            "tools/call",
            {"name": str(tool), "arguments": dict(arguments)},
            context=f"tool {tool!r}",
        )
        return self._tool_payload(str(tool), result)

    # -- Internals ------------------------------------------------------------

    def _initialize(self) -> None:
        """The MCP initialization lifecycle, in full.

        Three steps, and the last two are not optional decoration: the server
        this bead targets tolerates their absence, but a conforming server need
        not, and a client that skips them is relying on one implementation's
        leniency.

        1. `initialize`, declaring the revision this client speaks;
        2. validate the revision the server negotiated back, refusing one this
           client does not implement rather than continuing on a framing it has
           not been written against;
        3. the `notifications/initialized` notification, after which every
           request carries the negotiated revision in `MCP-Protocol-Version`.
        """
        if self._initialized:
            return
        result = self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
            context="initialize",
        )
        self._negotiated_version = self._negotiated(result)
        # Set before the notification, so the notification itself carries the
        # header a conforming server expects on every post-initialize request.
        self._initialized = True
        try:
            self._notify("notifications/initialized", {})
        except McpTransportError:
            self._initialized = False
            raise

    def _negotiated(self, result: Any) -> str:
        """The protocol revision the server chose, validated against what we speak."""
        if not isinstance(result, Mapping):
            raise McpProtocolError(
                f"{self.identity}: initialize answered "
                f"{type(result).__name__} where the profile declares a result object"
            )
        version = result.get("protocolVersion")
        if not isinstance(version, str) or not version.strip():
            raise McpProtocolError(
                f"{self.identity}: initialize returned no protocolVersion, so no "
                "revision was negotiated and every later request would be guessing"
            )
        version = version.strip()
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise McpProtocolError(
                f"{self.identity}: the server negotiated MCP revision {version!r}, "
                f"which this client does not implement (it speaks "
                f"{list(SUPPORTED_PROTOCOL_VERSIONS)})"
            )
        return version

    def _headers(self) -> dict[str, str]:
        headers = dict(_HEADERS)
        if self._negotiated_version:
            headers[PROTOCOL_VERSION_HEADER] = self._negotiated_version
        return headers

    def _notify(self, method: str, params: Mapping[str, Any]) -> None:
        """Send a JSON-RPC notification, which has no id and expects no response.

        The body is not parsed. A notification's acknowledgement is legitimately
        `202 Accepted` with nothing in it, and running that through the envelope
        parser would turn correct server behavior into a protocol error.
        """
        envelope = {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        status, _ = self._post(
            json.dumps(envelope).encode("utf-8"), context=f"notification {method!r}"
        )
        if not 200 <= status < 300:
            raise McpHttpError(
                f"{self.identity}: notification {method!r} answered HTTP {status}"
            )

    def _request(self, method: str, params: Mapping[str, Any], *, context: str) -> Any:
        self._next_id += 1
        request_id = self._next_id
        envelope = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        status, body = self._post(json.dumps(envelope).encode("utf-8"), context=context)
        if not 200 <= status < 300:
            raise McpHttpError(f"{self.identity}: {context} answered HTTP {status}")
        try:
            response = terminal_envelope(
                body, expected_id=request_id, context=f"{context}: the response"
            )
        except McpProtocolError as exc:
            raise McpProtocolError(f"{self.identity}: {self._redact(exc)}") from None
        error = response.get("error")
        if error is not None:
            message = (
                error.get("message") if isinstance(error, Mapping) else None
            ) or "no message"
            code = error.get("code") if isinstance(error, Mapping) else None
            raise McpRpcError(
                f"{self.identity}: {context} was rejected with JSON-RPC error "
                f"{code}: {self._redact(message)}"
            )
        return response.get("result")

    def _post(self, body: bytes, *, context: str) -> tuple[int, str]:
        try:
            # Built inside the `try`: for a schemeless endpoint this raises
            # `ValueError` carrying the value verbatim, and that text is not
            # URL-shaped, so letting it escape would defeat every other defense
            # here. The constructor already refuses such an endpoint; this is the
            # second line, because the dataclass field stays writable.
            request = urllib.request.Request(
                self.endpoint, data=body, headers=self._headers(), method="POST"
            )
            return self.opener(request, self.timeout)
        except urllib.error.HTTPError as exc:
            # `from None` throughout: a chained exception carries `.url`, and a
            # traceback would print what the message removed.
            raise McpHttpError(
                f"{self.identity}: {context} answered HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, OSError) as exc:
            raise McpEndpointUnreachable(
                f"{self.identity}: the endpoint could not be reached for {context} "
                f"({self._redact(exc)})"
            ) from None
        except ValueError as exc:
            raise McpEndpointInvalid(
                f"{self.identity}: the endpoint is not a usable URL for {context} "
                f"({self._redact(exc)})"
            ) from None

    def _tool_payload(self, tool: str, result: Any) -> Any:
        """The payload one `tools/call` result carries, or a typed failure."""
        if not isinstance(result, Mapping):
            raise McpProtocolError(
                f"tool {tool!r} answered with {type(result).__name__} where the "
                "streamable-HTTP profile declares a tool result object"
            )
        text = _result_text(result)
        if result.get("isError"):
            raise McpToolFailed(
                f"tool {tool!r} reported failure: "
                f"{self._redact(text or 'no detail was returned')}"
            )
        if text is None:
            structured = result.get("structuredContent")
            if structured is not None:
                return structured
            raise McpProtocolError(
                f"tool {tool!r} answered with neither text content nor structured "
                "content, so it returned nothing this caller can read"
            )
        parsed = _try_json(text)
        return parsed[0] if parsed else text


def _result_text(result: Mapping[str, Any]) -> str | None:
    """The concatenated `text` blocks of a tool result, or `None` when it has none."""
    content = result.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return None
    parts = [
        block["text"]
        for block in content
        if isinstance(block, Mapping) and isinstance(block.get("text"), str)
    ]
    return "".join(parts) if parts else None


# -- endpoint resolution -------------------------------------------------------


def _default_codex_config() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _default_cursor_config() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _default_claude_config() -> Path:
    return Path.home() / ".claude.json"


def registered_endpoint(
    server_name: str,
    *,
    codex_config: Path | str | None = None,
    cursor_config: Path | str | None = None,
    claude_config: Path | str | None = None,
) -> str | None:
    """The endpoint the operator has already registered for one MCP server.

    The credential is the operator's, held in the harness MCP registrations they
    already maintain. Nothing is stored, exchanged, or written here: this reads
    what is on disk and hands it to the caller that owns the connection.

    Every configuration path is an explicit argument **with a default**, and the
    honest statement of what that buys is narrower than an earlier revision
    claimed: it does not make it impossible for a test to read the operator's
    real configuration, because a caller that omits the paths reads exactly that
    -- which is what the CLI does, deliberately, as the one caller whose job is
    to resolve the live registration. What it buys is that every *other* caller
    can be given fixture paths, and the tests in this repository pass them.

    Args:
        server_name: The MCP server key, as registered.
        codex_config: `~/.codex/config.toml` by default.
        cursor_config: `~/.cursor/mcp.json` by default.
        claude_config: `~/.claude.json` by default.

    Returns:
        The registered URL, or `None` when no consulted registration names this
        server. `None` is the honest answer: the caller turns it into a typed
        `unavailable` availability rather than guessing an endpoint.

    Raises:
        ConflictingRegistration: when two consulted files register this server
            with different URLs. One of them is stale, and choosing silently
            would attribute a fetch, a pin, and a receipt to an endpoint the
            operator may believe they replaced.

    All sources are read even though the first hit would answer the question,
    precisely so a disagreement is detected rather than ordered away. Sources
    that agree resolve to their shared value in the documented precedence:
    Codex, then Cursor, then Claude.

    A malformed or unreadable registration is skipped rather than raised: the
    operator's Cursor file being invalid JSON is not a reason for the whole
    inventory command to fail, and the visible consequence of skipping every
    source is the same typed refusal as registering nothing.
    """
    name = str(server_name).strip()
    if not name:
        return None
    sources = (
        (codex_config if codex_config is not None else _default_codex_config(), _toml_url),
        (cursor_config if cursor_config is not None else _default_cursor_config(), _json_url),
        (claude_config if claude_config is not None else _default_claude_config(), _json_url),
    )
    found: list[tuple[Path, str]] = []
    for path, reader in sources:
        resolved = Path(path).expanduser()
        url = reader(resolved, name)
        if url:
            found.append((resolved, url))
    if not found:
        return None
    distinct = {url for _, url in found}
    if len(distinct) > 1:
        # Paths, never values. The whole point of the refusal is that one of the
        # values is a live credential and the other may also be one.
        locations = ", ".join(str(path) for path, _ in found)
        raise ConflictingRegistration(
            f"MCP server {name!r} is registered with {len(distinct)} different "
            f"endpoints across {locations}; one of them is stale. Their values are "
            "withheld because for this provider kind the URL is the subscriber "
            "credential. Reconcile the registrations and re-run"
        )
    return found[0][1]


def _toml_url(path: Path, server_name: str) -> str | None:
    """`[mcp_servers.<name>] url` from a Codex CLI configuration."""
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, ValueError):
        return None
    return _server_url(document.get("mcp_servers"), server_name)


def _json_url(path: Path, server_name: str) -> str | None:
    """`mcpServers[<name>].url` from a JSON harness configuration."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(document, Mapping):
        return None
    return _server_url(document.get("mcpServers"), server_name)


def _server_url(registry: Any, server_name: str) -> str | None:
    if not isinstance(registry, Mapping):
        return None
    server = registry.get(server_name)
    if not isinstance(server, Mapping):
        return None
    url = server.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None
