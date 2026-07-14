# MCP-Server

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A capability provider accessed via the Model Context
Protocol (MCP). MCP servers expose tools, resources, and prompts to any
MCP-compatible client without requiring shell access.

**Key constitutive feature.** Protocol-mediated capability: MCP servers run
as separate processes (or remote services) and expose a typed tool API over
a standard protocol. The server itself owns its tool catalog — clients
discover tools, schemas, and descriptions via the MCP `tools/list` call at
connection. The Library catalog (`library.yaml`) registers the server; it
does **not** duplicate the per-tool data.

**Trigger semantics.** MCP tools appear in the model's tool list alongside
native tools. The model calls them the same way it calls Bash or Read — by
generating a tool-use block. The MCP server responds with a tool result.

---

## Two species of MCP server

Established by [ADR-0007](../adr/library-tool-surface-mcp.md). The two
species share registration, install model, and protocol. They differ in who
owns the backing implementation and in the decision rule for choosing MCP
over a CLI + Skill.

The `mcp_server_entry.species` field in `library.yaml` is the discriminator
(optional; defaults to `external-capability`).

| | `external-capability` | `library-tool-surface` |
|---|---|---|
| **Provider** | Third-party process or remote service | First-party Library |
| **Examples** | `open-brain`, `executive-circle`, `pencil`, `heypresto` | `cognovis-tools` (planned) |
| **Backs** | Remote data / encrypted formats / vendor APIs | Library Scripts and a closed enum of CLI verbs |
| **Why MCP and not CLI** | Protocol is the only access path (encrypted formats, remote service) or the only path that works across harnesses including web/mobile | Eliminates flag-guessing failures on high-frequency CLIs; provides typed, server-validated invocation |

### Species 1: `external-capability` (default)

**When to choose it.** Use an external MCP server when:

- The target harness has no shell access (claude.ai web, Claude iOS) and the
  capability requires external data or tool execution.
- An existing MCP server already provides the capability (no need to wrap
  in a skill).
- The capability must be accessible to both coding and non-coding harnesses
  and you want a single implementation.

**Decision rule (harness-dependent).**

| Harness | Shell access | Recommendation |
|---------|-------------|----------------|
| Claude Code | YES | Prefer CLI + Skill. MCP adds process overhead without benefit when shell is available **and** the capability is already covered by a CLI. INFERRED — architectural principle. |
| Codex CLI | YES | Same as Claude Code: prefer CLI + Skill. INFERRED. |
| claude.ai web | NO | MCP-Server is the only path for external tool access. NORMATIVE. |
| Claude iOS | NO | MCP-Server is the only path for external tool access. NORMATIVE. |

**Counter-examples.**
- Do NOT default to MCP for Claude Code / Codex when an existing CLI already
  covers the capability — a CLI tool + skill is simpler, faster, and easier
  to debug.
- Do NOT build an external MCP server to replace a skill that only coding
  harnesses use.

**Worked examples.**

| MCP Server | Why it is external-capability |
|-----------|------------------------------|
| `executive-circle` MCP | Content library for web/iOS users who have no shell access. The CLI equivalent (`crwl`) exists for coding harnesses. |
| `pencil` MCP | Design tool for non-coding harnesses. `.pen` files are encrypted and must be accessed via MCP tools. |

### Species 2: `library-tool-surface`

**Definition.** A first-party MCP server published by the Library to provide a
typed invocation boundary for Library-owned operations and Scripts. It is
justified only when the server owns a material contract that cannot be obtained
as reliably from an existing stable CLI plus a Skill.

**When to choose it.** Use a library-tool-surface server when:

- The server can enforce a real trust boundary, atomic protocol, shared
  concurrency invariant, or provider-neutral lifecycle that direct callers
  cannot bypass within the supported execution model.
- A Library Script is invoked from many call sites with structured arguments
  and benefits from a typed contract instead of a shell recipe.
- The dangerous-agent class (long-running, high-blast-radius) needs a path
  to graduate to `Bash` denied without losing the operations they perform
  today — see ADR-0007 Phase 7.

**Decision rule.** Prefer an existing stable, public CLI plus a Skill when the
MCP tool would only validate parameters and shell out to the same CLI. Repeated
flag mistakes alone do not justify a daemon, correlated failure domain, and
duplicate wrapper implementation. Choose a library-tool-surface server only
when its typed boundary owns an independently valuable invariant or provides an
access path unavailable to the supported harnesses.

**Backing implementation.** A library-tool-surface tool MUST be backed by:

- a Library [Script](script.md) (Python, `json-envelope` output contract); OR
- a closed enum of CLI verbs (e.g. `git merge`, `gh run watch`)
  invoked through a server-internal wrapper that validates arguments
  server-side.

The catalog of backing scripts and CLI verbs is owned by the server, not by
`library.yaml`. The MCP `tools/list` call is the runtime source of truth for
what the server exposes.

**Closed-catalog invariant.** A library-tool-surface tool that accepts an
identifier referencing another script (e.g. a hypothetical
`library.exec(script_id, args)`) MUST constrain `script_id` to a closed
enum sourced from `library.scripts` or the server's own internal registry.
Accepting arbitrary paths or interpreter targets is structurally equivalent
to a `Bash` tool and forfeits the safety properties that justify the
species. Adding a new `script_id` is a catalog edit, not a runtime decision.

**Counter-examples.**
- Do NOT wrap a stable CLI such as `bd` solely to avoid teaching its public
  commands. Keep deterministic lifecycle plumbing in scripts or handlers and
  let agents use the CLI through a focused Skill.
- Do NOT expose commit/pull/push or similar deterministic pipeline steps as
  agent-facing tools merely because they can be typed.
- Do NOT add a typed tool that accepts an arbitrary `path` or `command`
  argument. That re-creates `Bash` with extra steps.
- Do NOT skip server-side schema validation. The point of the species is
  that the agent cannot get the call wrong; that property requires
  enforcement, not convention.
- Do NOT duplicate the server's tool catalog in `library.yaml`. The MCP
  protocol's `tools/list` is the discovery surface; mirroring it creates
  two sources of truth that drift.

**Worked examples.**

| MCP Server | Why it is library-tool-surface |
|-----------|-------------------------------|
| `cognovis-tools` | First-party server for provider-session, Git, log, release, and closed-registry Script operations. Its retired `bead_*` family is the counter-example that established the stable-CLI rule above; Beads uses direct `bd`. |

---

## Catalog shape (both species)

A single `mcp_server_entry` in `library.yaml` registers either species. The
only species-discriminating field is `species` (optional, defaults to
`external-capability`):

```yaml
mcp_servers:
  - name: cognovis-tools
    description: First-party Library tool surface for high-frequency CLIs
    source: https://github.com/cognovis/cognovis-core/tree/main/mcp-servers/cognovis-tools
    species: library-tool-surface
    coding_strategy: mcp
    install:
      mcp:
        claude_code: { ... }
        codex: { ... }
```

Per-tool schemas, per-tool descriptions, and per-tool backing-Script
bindings are NOT catalog fields. They live in the server process and are
returned via `tools/list` at connection.

## Deployment model

Both species follow ADR-0002's deployment-target model. Server source lives
in its source-of-truth repo (a library-core repo for first-party, an
external repo for third-party). The Library installer (`/library use`)
writes the per-harness MCP registration pointing at the source location. No
server code is vendored into the consumer project; only registration.

A `library-tool-surface` server registers into the supported launcher harnesses.
For `cognovis-tools`, that set is exactly Claude Code (`~/.claude.json`), Codex
(`~/.codex/config.toml`), and Cursor Agent (`~/.cursor/mcp.json`). Per
ADR-0007, **registration is decoupled from orchestration role**: registering
the server means agents running in that harness can call its typed tools; it
does NOT make the harness an orchestration runner. Full bead orchestration
runs only under Claude Code and Codex; Cursor Agent is an implementation-surface
consumer that registers the server so its agents do not flag-guess CLIs.

---
