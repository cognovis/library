# Verification Gates

## Focused Python Tests

- Run all Python through `uv`.
- Test handlers and application services directly for domain behavior and failure cases.
- Use the official in-memory `Client(server, raise_exceptions=True)` for MCP surface tests.
- Assert tool, resource, and prompt discovery; typed inputs; structured results; expected errors; and deterministic ordering.
- Add a default modern-client test and `Client(server, mode="legacy")` coverage for every promised legacy behavior.
- Test every explicit handle across independent requests and, when relevant, separate worker processes.

## Transport and Deployment

- Exercise the deployed transport, not only the in-memory client.
- For Streamable HTTP, prove that an arbitrary worker can serve consecutive modern requests.
- If legacy sessions remain enabled, prove sticky routing or single-worker ownership. If `stateless_http=True`, prove that no required legacy flow needs a back-channel.
- Verify lifespan startup and cleanup under the actual ASGI or process runner.

## Official Conformance

Run the server at its real MCP URL and execute the frozen final-spec requirement set:

`npx @modelcontextprotocol/conformance server --url <mcp-url> --requirements 2026-07-28`

Also run the active suite when practical to expose checks added after the release. Any expected-failure baseline must be committed, narrowly scoped to a check where possible, and reported as a gap rather than a pass.

## Compatibility Evidence

Record separate evidence for:

1. A current client using protocol `2026-07-28`.
2. A named legacy client or the SDK legacy mode using a handshake-era protocol.
3. The official `2026-07-28` conformance requirement set.

Do not infer client compatibility from server startup, Inspector discovery, or unit tests. If no legacy support is required, record that product decision instead of claiming compatibility.
