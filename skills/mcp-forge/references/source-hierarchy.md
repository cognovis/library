# Source Hierarchy

Use sources in this order. A lower source may add a checklist but may not override a higher one.

1. [MCP specification 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) for protocol behavior.
2. [Official Python SDK v1-to-v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/) for code changes.
3. [Official Python SDK documentation](https://py.sdk.modelcontextprotocol.io/) for current APIs, testing, transports, deployment, and legacy clients.
4. [Official MCP conformance framework](https://github.com/modelcontextprotocol/conformance) for protocol evidence.
5. [efaimo-ai/mcp-stateless-migration](https://github.com/efaimo-ai/mcp-stateless-migration) only as a supplemental audit checklist.

## Final Specification Guard

The release candidate frozen on 2026-05-21 is not normative. Reject guidance that places server identity in a top-level `DiscoverResult.serverInfo`; the final location is `_meta["io.modelcontextprotocol/serverInfo"]`. Reject RC error codes `HeaderMismatch -32001`, `MissingRequiredClientCapability -32003`, and `UnsupportedProtocolVersion -32004`; the final reserved codes are `-32020`, `-32021`, and `-32022`. Resource-not-found now uses JSON-RPC Invalid Params `-32602`, not `-32002`.

The SDK is the wire implementation. Server application code should not manually add protocol-version metadata, reimplement `server/discover`, synthesize `resultType`, manage `Mcp-Session-Id`, or reproduce version routing already owned by SDK v2.

## Meaning of Stateless

Stateless MCP removes protocol-level initialization and sessions for the 2026-07-28 path. It does not ban PostgreSQL, OAuth state, user records, caches, queues, or domain memory. Cross-call workflows must use explicit application identifiers or server-minted handles passed as normal arguments. Request-local context must not be mistaken for durable state.
