# Python SDK v2 Authoring Contract

## Project Baseline

- Use a supported Python version and manage Python commands and dependencies with `uv`.
- Depend on the official `mcp` SDK v2 line with an explicit compatible range; do not leave a v1-compatible floor such as `mcp[cli]>=1.0.0`.
- Import the high-level server as `from mcp.server import MCPServer` unless a documented advanced API requires a narrower module path.
- Give the server an explicit stable name and version. Prefer keyword arguments beyond the first name argument because v2 changed constructor positions.

## Server Surface

- Represent model-controlled actions as tools, application-controlled context as resources, and user-selected templates as prompts.
- Derive schemas from precise Python type annotations and document handler behavior with concise docstrings.
- Prefer typed return models or structured SDK results over hand-built JSON-RPC payloads.
- Keep side effects behind narrow application services that can be tested without starting a transport.
- Use lifespan state or injected dependencies for database pools, HTTP clients, and caches. Close them through the lifespan boundary.
- Keep tool and list ordering deterministic where the application controls it.
- Set SDK `cache_hints` deliberately for cacheable list and read results. Use private scope for authenticated, tenant-specific, or per-user data; use public scope only when sharing the result across callers is safe.

## Transport Selection

- Use stdio for local subprocess servers. Keep `mcp.run()` under `if __name__ == "__main__":`, reserve stdout for the protocol, and send operator output through logging to stderr.
- Use Streamable HTTP for deployed servers. Configure transport arguments on `run()` or `streamable_http_app()`, not on `MCPServer`.
- For a stdio server that promises legacy compatibility, verify both modern `server/discover` and the handshake-era path; rely on the SDK client's auto probe and fallback instead of implementing negotiation in application code.

## Stateless Boundary

Assume each modern request can reach any worker. Do not keep correctness-critical cross-request data only in a process-local session object. Persist durable state externally or return an opaque handle that the client supplies on the next call.

`streamable_http_app()` serves modern and legacy protocol eras. The modern 2026-07-28 path is sessionless. The `stateless_http` option changes only the legacy path: enabling it removes legacy back-channels, so server-initiated requests fail and legacy notifications are dropped. Choose it only after examining those legacy behaviors.

Multi-process deployments need two additional shared boundaries. When MRTR or `Resolve(...)` can retry on another worker, configure `RequestStateSecurity` with the same key ring and the same audience across replicas; a stable shared server name supplies that audience unless it is set explicitly. When subscriptions must cross processes, implement `SubscriptionBus` over an external pub/sub backend and pass it to every replica; the SDK's in-memory bus does not cross process boundaries.

## Protocol Features

- Use SDK-supported multi-round-trip request abstractions rather than server-initiated request code for modern interactive flows.
- Use the SDK subscription APIs for modern change notifications; if legacy notification delivery is required, test and implement the documented dual-era calls.
- Do not add deprecated Roots, Sampling, Logging, HTTP+SSE, or Dynamic Client Registration to new servers unless a documented compatibility requirement justifies it.
- Keep authorization and application state conceptually separate from protocol sessions.
