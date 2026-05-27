---
adr: "0007"
title: "Library tool surface as a second species of MCP server"
status: proposed
date: 2026-05-27
bead: "CL-ugwe"
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0002", "0005", "0006"]
---

# ADR-0007: Library tool surface as a second species of MCP server

## Status

Proposed. Decisions describe the architectural split and the catalog delta only;
the `cognovis-tools` server implementation and the `capabilities.yaml`
migration are sequenced as follow-up beads (see Consequences).

## Context

The MCP-Server primitive (`docs/primitives/mcp-server.md`) today treats every
MCP server as an **external capability provider**: a third-party process the
Library happens to consume (`open-brain`, `executive-circle`, `pencil`,
`heypresto`). The doc's decision rule reads:

> | Claude Code | YES shell | Prefer CLI + Skill. MCP adds process overhead without benefit when shell is available. INFERRED |
> | Codex CLI | YES shell | Same as Claude Code: prefer CLI + Skill. INFERRED |
>
> *Do NOT default to MCP for Claude Code / Codex — when you have shell access, a CLI tool + skill is simpler, faster, and easier to debug.*

That advice is correct for the external case: there is no reason to install an
MCP server when a CLI (`crwl`, `bd`, `git`) and a skill already exist.

It is wrong for a different case that the Library has not previously named: a
**first-party MCP server that exists to be the typed invocation surface over
Library-owned CLIs and Scripts**. Empirical signal driving this:

1. **Flag-guessing is the dominant agent failure mode for high-frequency CLIs.**
   Across the fleet, every newly-spawned agent re-derives `bd create`,
   `bd update`, `bd close`, and `git` invocations from skill prose, gets a
   flag wrong, errors, asks for help, retries. The agent has no procedural
   memory of the correct invocation — only fuzzy prose.

2. **The "skill teaches how to call a CLI" pattern is the script primitive's
   own declared anti-pattern.** `docs/primitives/script.md` already states:
   *"A 200-line shell pipeline embedded in a skill's prompt is a smell. The
   model will hallucinate flags, get argument order wrong, and produce
   non-reproducible results."* The same logic applies to a 5-line `bd create`
   recipe — only the magnitude differs.

3. **The session-close pattern shows the gap structurally.** Phase 16 of
   `bead-orchestrator` does not dispatch `session-close-runner.py` even when
   the route profile names it; instead it spawns the LLM agent, which then
   re-orchestrates handlers in ad-hoc Bash. The runner exists; the agent
   re-invents its pipeline anyway. The procedural knowledge has nowhere
   structural to live except prose.

4. **The L4/L5 safety argument from `disler/bash-damage-from-within` applies
   to long-running, high-blast-radius agents in this codebase.** Long-running
   agents amplify per-turn destructive-call probability multiplicatively;
   `bd dolt push`, `git push`, `mail-send`, and Collmex bookings have real
   production blast radius. Removing Bash from those agents requires a
   typed-tool path to do what the agent currently does in shell.

The reliability case (no more flag-guessing) and the safety case (no more
Bash funnel for dangerous agents) emerge from the same structural change:
typed tools, server-side enforcement, closed catalog.

## Decision

### Decision 1: MCP-Server is one primitive with two species

The `mcp-server` primitive is split into two species, both first-class:

| Species | `external-capability` | `library-tool-surface` |
|---|---|---|
| Provider | Third-party process or remote service | First-party Library |
| Examples | `open-brain`, `executive-circle`, `pencil`, `heypresto` | `cognovis-tools` (planned) |
| Backs | Remote data / encrypted formats / vendor APIs | Library Scripts and a closed enum of CLI verbs |
| Decision rule | Use when harness lacks shell **or** capability is external to the Library | Use to eliminate flag-guessing on high-frequency CLIs; valid even when shell is available |
| Catalog truth | Server registration + connection config | Server registration + connection config |
| Tool catalog | Owned by the server, discovered via MCP `tools/list` | Owned by the server, discovered via MCP `tools/list` |

The "prefer CLI + Skill" rule in `docs/primitives/mcp-server.md` is moved
into the `external-capability` section. It does not apply to
`library-tool-surface` servers — those servers **are** the skill's invocation
channel; suggesting "use a CLI + skill instead" is circular.

### Decision 2: `library.yaml` registers the server; the server publishes the tools

The MCP protocol's `tools/list` call is the source of truth for a server's
tool catalog. The Library catalog (`library.yaml`) does **not** mirror per-tool
data. It registers exactly what every MCP entry already registers today:
name, description, source, launch hints, harness install metadata.

The only catalog delta is one optional discriminator:

```yaml
mcp_servers:
  - name: cognovis-tools
    description: First-party Library tool surface for high-frequency CLIs
    source: https://github.com/cognovis/cognovis-core/tree/main/mcp-servers/cognovis-tools
    species: library-tool-surface    # NEW — discriminator only; defaults to external-capability when absent
    coding_strategy: mcp
    install:
      mcp:
        claude_code: { ... }
        codex: { ... }
```

`species` is an optional enum (`external-capability` | `library-tool-surface`).
Omitting it preserves today's behavior (external). The field exists solely so
`docs/primitives/mcp-server.md`, `library validate`, and downstream consumers
can apply the right decision rule and any species-specific install policy.

Per-tool schemas, per-tool backing-Script bindings, and per-tool
descriptions all live in the server process and are returned via `tools/list`
on connection. The catalog does not duplicate them.

### Decision 3: Tools backed by Library Scripts; catalog is closed

A `library-tool-surface` server SHOULD back each typed tool by a Library
Script (Python, `json-envelope` output contract per
`docs/primitives/script.md`) or a closed enum of CLI verbs. The server is the
only place that maps a typed tool to its backing implementation; that mapping
is **not** a catalog field.

The closed-catalog property is what carries the disler L5 safety argument
forward: an `mcp__cognovis-tools__library.exec` tool whose `script_id`
parameter accepts arbitrary paths is structurally equivalent to a Bash tool
with extra steps. The server MUST enforce that `script_id` is a closed enum
sourced from `library.scripts` (or its own internal registry); adding a new
script_id is a catalog edit, not a runtime decision. This invariant is owned
by the server, not by `library.yaml`.

### Decision 4: Deployment follows ADR-0002

`library-tool-surface` servers follow the same source-of-truth /
deployment-target split established in ADR-0002: server source lives in
`cognovis-core/mcp-servers/<name>/`; the installer (`/library use`) writes
the per-harness MCP registration into `~/.claude/.mcp.json` /
`~/.codex/config.toml` pointing back to the cloned source. No vendoring of
server code into the consumer project; only registration.

## Rationale

### Why a species discriminator instead of a new primitive

The two species share everything that matters at the catalog and harness
levels: registration shape, connection protocol, install model, discovery
mechanism. They differ only in decision rule and in who owns the backing
implementation. That is metadata, not a new primitive. Introducing a 14th
primitive would create churn in the Quick Decision Tree, the portability
matrix, the schema, and the `requires_*` dependency keys, for no structural
benefit. A `species` field on the existing primitive is the minimal change
that lets the decision-rule prose diverge.

### Why the catalog does not list the tools

The Model Context Protocol defines `tools/list` as the discovery surface for
a server's tool catalog, schemas, and descriptions. Duplicating that data in
`library.yaml` creates two sources of truth that drift the moment a tool is
added to the server without a catalog edit. Static validation of tool
existence belongs in the server's own tests; runtime discovery is the
protocol's job. The catalog's job is to register the server, not to mirror
its API.

### Why this is reliability-first, not safety-first

The proximate driver is procedural reliability for agent invocations of
high-frequency CLIs. The disler L4/L5 safety argument is a follow-on benefit
available once the tool surface exists: dangerous agents
(`bead-orchestrator`, `session-close`, `wave-orchestrator`) can graduate to
`Bash` denied + `mcp__cognovis-tools__*` allowed as a separate step. Framing
this ADR as "build the typed surface first; graduate dangerous agents to L5
later" keeps the work bead-shaped instead of conflating two timelines.

## Alternatives Considered

### Alternative A: Treat first-party MCP as an instance of the existing primitive without a species split

Rejected. The current decision rule ("prefer CLI + Skill") would either need
to be deleted (which is wrong for the external case) or carve out an
unnamed exception (which is what `species` makes explicit). Naming the
species is cheaper than narrating around it.

### Alternative B: Catalog every tool in `library.yaml`

Rejected. Duplicates `tools/list`. Creates a drift surface. Forces every new
server tool to be a coordinated edit across the server repo and the catalog
repo. The MCP protocol already solves this — let it.

### Alternative C: Build first-party MCP as a `script` projection layer instead

Rejected. Scripts are Python-only and run no model; they are the *backing*
for typed tools, not a substitute for the protocol surface. The MCP tool
surface is what makes the typed contract appear in the model's tool list.

### Alternative D: Wait for native-format tool dispatch (e.g. Workflow's `agent()` leaves)

Rejected. Workflow's leaves can already call typed MCP tools today; this
ADR is what makes those tools exist. The two ADRs (0006 workflow, 0007
library-tool-surface MCP) compose; they do not block each other.

## Migration Sequence

Sequenced as follow-up beads. None executed inside this ADR.

### Phase 1: Doc and schema revisions (this commit)

1. `docs/primitives/mcp-server.md` — introduce the two-species split. Move
   "prefer CLI + Skill" into the external-capability section. Add the
   `library-tool-surface` section with its decision rule.
2. `docs/primitives/script.md` — note that scripts can be projected as typed
   MCP tools by a library-tool-surface server.
3. `docs/primitives/skill.md` — add anti-pattern: teaching CLI flag syntax
   in skill prose when a typed MCP tool exists for the intent.
4. `docs/PRIMITIVES.md` — update the MCP branch of the Quick Decision Tree
   to ask "first-party library tool surface or external capability?" and
   record the species split.
5. `docs/schema/library.schema.json` — add the optional `species` field on
   `mcp_server_entry`.
6. `docs/ARCHITECTURE.md` — list this ADR.

### Phase 2: Build `cognovis-tools` skeleton

Bead-scoped. Skeleton MCP server in
`cognovis-core/mcp-servers/cognovis-tools/`, FastMCP or equivalent,
exposing the first family of typed tools (`bead.create`, `bead.show`,
`bead.ready`, `bead.claim`, `bead.update`, `bead.close`, `bead.remember`).
Each tool backed by a Python Script per `docs/primitives/script.md`. Server
enforces `bead-hygiene` validation server-side.

### Phase 3: Register `cognovis-tools` in `library.yaml`

Bead-scoped. Add the `mcp_servers` entry with `species: library-tool-surface`
and per-harness install metadata. Installer extension (if any) is part of
this bead.

### Phase 4: `git.*` family

Bead-scoped. Add `git.workspace`, `git.changes`, `git.commits_since`,
`git.merge_from_main`, `git.merge_feature`, `git.commit(paths, type, description)`
to `cognovis-tools`. Wrap existing handlers under
`cognovis-core/skills/session-close/handlers/`.

### Phase 5: `library.exec` for catalog scripts

Bead-scoped. Add `library.exec(script_id, args, context?)` with `script_id`
constrained to a closed enum from `library.scripts` plus skill-bundled
scripts. Establish the metrics integration (`insert_agent_call` on every
invocation).

### Phase 6: Capabilities migration

Bead-scoped. Migrate `manage_beads`, `send_email`, future entries in
`meta/capabilities.yaml` from `tools: [Bash] + skills: [<name>]` to
`mcpServers: [cognovis-tools]`. Coarse server-level scoping (Option A in
the ADR conversation) is the starting shape; per-prefix scoping is
deferred.

### Phase 7 (separate epic): L5 graduation for dangerous agents

Out of scope for this ADR. Once the tool surface covers
`bead-orchestrator`, `session-close`, and `wave-orchestrator` invocations,
those agents' `.claude/settings.json` can deny `Bash` and rely on
`mcp__cognovis-tools__*`. That is the disler L5 destination and is filed
under its own epic.

## Consequences

- **`mcp-server.md` decision rule diverges per species.** The "prefer CLI +
  Skill" advice no longer applies uniformly. Future authors of MCP entries
  must declare `species` (or accept the `external-capability` default) and
  follow the corresponding decision rule.
- **`library.yaml` schema gains one optional field.** The discriminator is
  the only schema delta. No per-tool data is added to the catalog.
- **Server is the authoritative tool catalog.** `library validate` checks
  the registration; tool-level correctness is checked by the server's own
  tests and by the MCP handshake at runtime.
- **Skills shrink.** Skills covering intents that map onto typed tools
  drop their flag-level prose and become intent-routing layers. The
  `skill.md` anti-pattern enforces this direction.
- **Disler L5 path becomes a graduation step, not a prerequisite.** Once
  `cognovis-tools` covers the dangerous-agent invocation surface, those
  agents can deny `Bash` independently. The reliability work and the
  safety work share the same structural foundation but are sequenced
  separately.
- **First-party MCP server lifecycle is new.** Unlike static skills,
  agents, and standards, an MCP server is a long-running process the
  harness launches. Installer behavior for `library-tool-surface` servers
  is a follow-up bead (Phase 3); it is not assumed to be identical to the
  external-MCP install path.

## Rollback Plan

| Scenario | Recovery action |
|----------|-----------------|
| `species` field rejected by older `library validate` consumers | Field is optional with default `external-capability`; older consumers that ignore unknown fields continue to work. If strict consumers exist, gate behind a `library.yaml` minor-version bump. |
| `cognovis-tools` server proves unstable in practice | Skills retain their CLI-prose paths in parallel during Phase 2–5; capability migration (Phase 6) is the cut-over point. Roll back by reverting the capabilities.yaml migration; the server can stay registered but unused. |
| L5 graduation regresses an agent | Re-enable Bash for that agent in `.claude/settings.json`. The MCP surface remains; the deny rule is the toggle. |

## Success Criteria

1. `docs/primitives/mcp-server.md` carries both species with their decision
   rules clearly separated.
2. `docs/PRIMITIVES.md` decision tree branches on species at the MCP node.
3. `docs/schema/library.schema.json` declares the optional `species` enum on
   `mcp_server_entry` and validates accordingly.
4. This ADR is linked from `docs/ARCHITECTURE.md`.
5. Phase 2–7 follow-up beads exist and are sequenced.

## Cross-References

- [ADR-0002](canonical-library-architecture.md) — deployment-target model
  used unchanged for `library-tool-surface` server registration.
- [ADR-0005](library-plane-vocabulary.md) — plane/projection vocabulary;
  `cognovis-tools` is `tier:core`, plane `dev`.
- [ADR-0006](workflow-primitive.md) — workflow leaves can call typed MCP
  tools; this ADR is what makes those tools exist.
- `docs/primitives/mcp-server.md` — primary downstream doc revision.
- `docs/primitives/script.md` — scripts back typed MCP tools.
- `docs/primitives/skill.md` — anti-pattern added: do not teach CLI flag
  syntax when a typed tool exists.
- External: `disler/bash-damage-from-within` — L4/L5 framing for the
  graduation step in Phase 7.
