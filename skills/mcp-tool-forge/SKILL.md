---
name: mcp-tool-forge
description: >-
  Author and validate new tools for the cognovis-tools MCP server (library-tool-surface species).
  Use when adding a new MCP tool family, validating an existing tool against the json-envelope
  contract, or creating a reference template. Triggers on: mcp tool, cognovis-tools tool,
  new tool family, tool template, json envelope, library-tool-surface.
requires_standards: [agentic-primitives, development, english-only, no-emoji]
---

# MCP Tool Forge

Author new `cognovis-tools` MCP tools as typed, registry-backed Library tool-surface
entries with the shared json-envelope contract.

## Inputs

- Tool family, verb, and intended backing implementation.
- Parameter names, types, defaults, and validation rules.
- Whether the operation reads state, writes state, or wraps a subprocess.
- Metrics context source for `run_id` and `bead_id` when the caller provides it.

## Outputs

- A typed tool function returning `Envelope`.
- A closed registry entry for the tool family and exported function.
- Direct unit tests that call the tool function without starting the MCP server.

## Tool Naming

- Use logical tool names in `family.verb` form. Python exports use `family_verb`
  because MCP adapters expose Python identifiers, for example `bead_show`,
  `git_commit`, and `library_exec`.
- The `family` segment uses lowercase Python-identifier spelling with underscores
  when needed.
- Family groups are closed catalog entries in the server registry. Add or update a
  registry entry before exposing a new family or verb.
- Do not add ad hoc verbs by dynamically registering functions at runtime.

## Input Schema

- Every parameter must have a concrete type annotation.
- Required parameters use non-`Optional` types and no default.
- Optional parameters use `Optional[T] = default`.
- Do not use `**kwargs`, arbitrary command strings, arbitrary paths, or untyped
  dictionary payloads when a typed parameter list can express the schema.
- Validate enum-like values server-side before invoking backing scripts or CLIs.

## Envelope Contract

Every tool must return `Envelope` and must use the shared helpers from
`envelope.py`.

```text
started_at = perf_counter()

def _run() -> Envelope:
    return make_envelope(
        status="ok",
        summary="One-line result.",
        data={"key": "value"},
        errors=[],
        next_steps=[],
        started_at=started_at,
    )

return tool_envelope(_run)
```

- Capture `started_at = perf_counter()` before defining or calling `_run()`.
- Use `make_envelope(status, summary, data, errors, next_steps, started_at)` for
  all success, partial, and expected-error results.
- Use `tool_envelope(_run)` so unexpected exceptions become `status="error"`
  envelopes instead of escaping the MCP server.
- Keep `summary` one line, put machine-readable results in `data`, and put
  actionable remediation in `next_steps`.
- `errors` entries use `{"code": str, "message": str}`.

## Exit-Code Map

Translate subprocess results into envelopes at the tool boundary.

| Subprocess return code | Envelope status | Required envelope fields |
|---|---|---|
| `0` | `ok` | `data` contains parsed stdout or a compact command result; `errors=[]`. |
| Non-zero | `error` | `errors` contains a stable code such as `SUBPROCESS_FAILED`, the return code, and stderr/stdout context. |
| Mixed multi-step result | `partial` only when the tool intentionally supports partial completion | `data` lists completed steps; `errors` lists failed steps; `next_steps` explains recovery. |

Do not let `subprocess.run(..., check=True)` raise before you can build the
contract envelope. Use `check=False` and map the return code explicitly.

## Idempotency

- Read tools must always be idempotent.
- Write tools should be idempotent unless the operation is inherently append-only
  or externally irreversible.
- Use check-before-write: inspect current state, compare with the desired state,
  and return `status="ok"` when the desired state is already present.
- For append-only tools, require a caller-visible idempotency key or document why
  the operation cannot be retried safely.

## run_id and bead_id Context

When the MCP context provides a run identifier, usually through
`CCP_ORCHESTRATOR_RUN_ID`, record metrics with `insert_agent_call()`.

```text
run_id = os.environ.get("CCP_ORCHESTRATOR_RUN_ID")
bead_id = os.environ.get("BEAD_ID", "")
if run_id:
    insert_agent_call(
        run_id=run_id,
        bead_id=bead_id,
        phase_label="mcp-tool",
        agent_label="cognovis-tools",
        model="local",
        iteration=1,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=0,
        duration_ms=duration_ms,
        exit_code=exit_code,
    )
```

- Metrics failures should be visible in logs but should not change the tool's
  envelope unless the tool's primary purpose is metrics recording.
- Propagate `bead_id` when available so run-level metrics remain attributable.

## Closed script_id Rule

The `library.exec` tool family must accept `script_id` only from a closed enum of
registered script names. A `script_id` is not a path, shell command, interpreter
target, or free-form string. Register new script IDs in the server's script
registry before any tool can call them.

## Tests Required

Every tool must ship unit tests.

- Import the tool function directly; do not start FastMCP or an MCP inspector for
  unit coverage.
- Call the function with typed parameters and mocked subprocess or filesystem
  dependencies.
- Assert the envelope shape: `status`, `summary`, `data`, `errors`, `next_steps`,
  and `meta.duration_ms`.
- Assert the expected `status` and key `data` fields for happy paths and expected
  failure paths.
- Run targeted tests with `uv run --with pytest pytest <test-file>`.

## Do NOT

- Do NOT accept arbitrary command, path, interpreter, or `script_id` strings.
- Do NOT bypass the shared envelope helpers.
- Do NOT expose a family or verb that has no closed registry entry.
- Do NOT treat MCP server startup as a substitute for direct unit tests.

## Resources

| File | Purpose |
|------|---------|
| `docs/primitives/mcp-server.md` | Defines the `library-tool-surface` species and closed-catalog invariant. |
| `docs/adr/library-tool-surface-mcp.md` | ADR-0007 rationale for typed Library tool surfaces. |
| `/Users/malte/code/library/cognovis-core/mcp-servers/cognovis-tools/tools/_template/` | Reference tool, registry entry, and direct-call unit test template. |
