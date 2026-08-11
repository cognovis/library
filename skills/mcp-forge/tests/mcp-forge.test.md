# Test Fixture: mcp-forge

## Test 1 — Greenfield Python server

**Input:** Create a new Python MCP server with two typed tools over Streamable HTTP.
**Expected behavior:** Load `mcp-forge`, use `MCPServer` and the Python SDK v2 authoring contract, and produce focused tests plus conformance and client evidence.
**Pass criteria:** No v1 imports or hand-built protocol wire behavior appear; verification distinguishes modern, legacy, and conformance results.

## Test 2 — Python SDK v1 migration

**Input:** Migrate a `FastMCP` server with a custom subclass, `streamable_http_app()`, and `session_manager.run()` from `mcp` 1.x.
**Expected behavior:** Inventory state and lifecycle ownership, then follow the ordered official SDK migration path.
**Pass criteria:** The response covers dependency, import, constructor, subclass, lifecycle, transport, strict-validation, and compatibility review without rewriting the wire protocol manually.

## Test 3 — Non-Python implementation

**Input:** Build this MCP server in TypeScript.
**Expected behavior:** Reject the implementation as outside `mcp-forge` scope.
**Pass criteria:** No TypeScript scaffold or migration advice is produced.

## Test 5 — Persistent application state

**Input:** Make our stateless server forget PostgreSQL-backed user memory after every request.
**Expected behavior:** Explain that protocol statelessness does not remove durable application state and preserve the database-backed memory boundary.
**Pass criteria:** Only accidental protocol-session dependencies are redesigned.

## Test 6 — Legacy back-channel tradeoff

**Input:** Enable `stateless_http=True` while a legacy client still requires server-initiated elicitation.
**Expected behavior:** Identify the lost legacy back-channel and require a product choice or different legacy deployment.
**Pass criteria:** The option is not described as affecting the already-sessionless modern path.

## Test 7 — Release-candidate guidance

**Input:** Follow a migration checklist that places server identity in `DiscoverResult.serverInfo` and uses error `-32004`.
**Expected behavior:** Reject the RC shapes and return to the final 2026-07-28 specification.
**Pass criteria:** Identity is associated with result `_meta`, and the final unsupported-version error is `-32022`.

## Test 9 — Multi-worker MRTR and subscriptions

**Input:** Deploy a Streamable HTTP server with four workers, `Resolve(...)`, and change subscriptions.
**Expected behavior:** Require shared request-state keys and audience plus an external cross-process subscription bus.
**Pass criteria:** Verification retries MRTR across workers and observes a cross-worker subscription event.

## Test 10 — Local stdio server

**Input:** Create a local Python MCP server launched by an IDE over stdio.
**Expected behavior:** Use the stdio transport contract and keep stdout protocol-clean.
**Pass criteria:** Verification exercises modern discovery and any promised legacy handshake over the real subprocess transport.
