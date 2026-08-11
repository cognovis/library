# Python SDK v1-to-v2 Migration

## Inventory Before Editing

Run `uv run path/to/mcp-forge/scripts/audit_mcp_v1.py path/to/target-repo` for the deterministic migration-signal inventory. Then record the current `mcp` constraint and lockfile version, Python version, server and client entrypoints, `FastMCP` subclasses, low-level handlers, transports, lifespan ownership, auth providers, and tests. Review constructor candidates manually because syntax alone cannot determine positional argument intent.

Classify every stateful value as request-local, process-local cache, durable application state, legacy transport session state, or an accidental protocol-session dependency. Only the last category must be redesigned for stateless correctness.

## Ordered Migration

1. Raise the project to the official Python SDK v2 dependency line and refresh the lockfile with `uv`.
2. Apply mechanical import and type moves, including `FastMCP` to `MCPServer`, `mcp.server.fastmcp.*` to `mcp.server.mcpserver.*`, and `McpError` to `MCPError`. Keep using the permanent `mcp.types` alias; import `mcp_types` directly only when a project depends on `mcp-types` without the SDK.
3. Review constructor calls. v2 inserted `title` and `description` before `instructions`; convert optional positional arguments to keywords and preserve explicit identity.
4. Port server APIs and subclasses. Decorators remain familiar, but context, direct call helpers, transport arguments, lifespan entry, and low-level handlers changed; follow the matching official guide section instead of guessing.
5. Port any embedded client code, then transport and authorization configuration.
6. Preserve the documented session-manager ownership. Construct each `streamable_http_app()` before accessing its `mcp.session_manager`. A standalone application carries its own lifespan, but a mounted sub-application's lifespan never runs; after construction, the host application's lifespan must enter `mcp.session_manager.run()` for every mounted server.
7. Replace server-initiated modern flows with SDK multi-round-trip abstractions. Keep legacy-specific back-channel behavior only when a named supported client requires it.
8. Address strict schema validation, snake_case model fields, removed extra-field preservation, new error types, and deprecations surfaced by tests.

## Protocol Audit

Verify the final 2026-07-28 wire behavior through the SDK: no modern initialize handshake or protocol session, per-request protocol and capability metadata, `server/discover`, required `resultType`, `subscriptions/listen`, required Streamable HTTP method/name headers, final error codes, and no SSE resumability. Do not patch those features into application handlers.

Audit application-visible changes separately: choose `ttlMs` and `cacheScope` through SDK cache hints; remove dependencies on `ping`, `logging/setLevel`, and `notifications/roots/list_changed`; and do not emit `notifications/message` unless the request opted in with `io.modelcontextprotocol/logLevel`. SDK v2 does not implement the new `io.modelcontextprotocol/tasks` extension. Drop a v1 Tasks dependency unless the product explicitly accepts a custom extension implementation, wire-level ownership, and dedicated interoperability tests.

## Compatibility

The SDK v2 Streamable HTTP application routes both modern and handshake-era clients by protocol version. Test both. A legacy client may still require sticky routing because its session record is process-local. `stateless_http=True` avoids that legacy session at the cost of legacy back-channels; it does not make the already-sessionless modern path more stateless.
