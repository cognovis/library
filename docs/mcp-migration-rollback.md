# Rollback: capabilities.yaml MCP Migration (ADR-0007 Phase 6)

## What was migrated

The following entries in `capabilities.yaml` were migrated from `tools: [Bash] + skills`
to `mcpServers: [cognovis-tools]` in bead CL-ugwe.6 (2026-05-29):

| Capability | Before | After (CL-ugwe.6, 2026-05-29) |
|---|---|---|
| `manage_beads` | `tools: [Bash, Read, Grep, Glob]` + `skills: [beads]` | `tools: []` + `mcpServers: [cognovis-tools]` + `skills: [beads]` |
| `inspect_git` | `tools: [Bash, Read, Grep, Glob]` | added `mcpServers: [cognovis-tools]` (Bash tools retained) |

`send_email` was NOT migrated — cognovis-tools has no mail tools.

**CL-ugwe.6 correction (CL-j92j, this bead):** the `manage_beads` "After" shape above
(`tools: []` + `mcpServers: [cognovis-tools]`) was a bug, not a valid end state — see
"Why `mcpServers:` alone is not enough" below. The corrected shape, in place since
CL-j92j, is:

```yaml
manage_beads:
  claude:
    tools:
      - mcp__cognovis-tools__bead_show
      - mcp__cognovis-tools__bead_ready
      - mcp__cognovis-tools__bead_list
      - mcp__cognovis-tools__bead_search
      - mcp__cognovis-tools__bead_repos
      - mcp__cognovis-tools__bead_create
      - mcp__cognovis-tools__bead_claim
      - mcp__cognovis-tools__bead_update
      - mcp__cognovis-tools__bead_update_notes
      - mcp__cognovis-tools__bead_review_write
      - mcp__cognovis-tools__bead_close
      - mcp__cognovis-tools__bead_dep_add
      - mcp__cognovis-tools__bead_dep_remove
      - mcp__cognovis-tools__bead_dolt_sync
    mcpServers: [cognovis-tools]
    skills: [beads]
```

## Why `mcpServers:` alone is not enough

Registering `mcpServers: [cognovis-tools]` makes the MCP *server* available to the
harness, but in Claude Code that does **not** grant any callable tool from it. A
Claude agent can only call `mcp__<server>__<tool>` when that exact name is listed in
its `tools:` frontmatter allowlist — `scripts/build-agent.py`'s `apply_capabilities()`
-> `_set_tools()` does an ordered-union merge of each declared capability's
`claude.tools` entries and never grants anything implicitly from `mcpServers:`
registration alone. An explicit empty `tools: []` therefore means "server reachable,
zero tools callable" — every agent that declared `manage_beads` between CL-ugwe.6
and CL-j92j had no working bead_* tools despite the server being registered. This is
the same shape as the existing `query_memory` (`mcp__open-brain__*`) and
`search_searxng` (`mcp__searxng__searxng_web_search`) capabilities, which list their
tools explicitly for the same reason.

## Companion: `read_beads` read-only capability (CL-j92j)

`manage_beads` is a single coarse capability that grants the full 14-tool mutating
set. Two of its historical consumers in the `cognovis-core` sibling repo —
`effort-classifier` and `wave-monitor` — do not need mutation access per their own
documented contracts (`effort-classifier` returns JSON only and never calls a
`bead_*` tool; `wave-monitor` has an explicit `## Design Constraints` line: "No
Write tool — wave-monitor is read-only. Cannot mutate bead state."). Sharing
`manage_beads` therefore over-granted them the 9 mutating tools.

CL-j92j adds a least-privilege sibling capability, `read_beads`, to
`capabilities.yaml`. It grants only the 5 read-only typed tools and none of the 9
mutating ones:

```yaml
read_beads:
  claude:
    tools:
      - mcp__cognovis-tools__bead_show
      - mcp__cognovis-tools__bead_ready
      - mcp__cognovis-tools__bead_list
      - mcp__cognovis-tools__bead_search
      - mcp__cognovis-tools__bead_repos
    mcpServers: [cognovis-tools]
    skills: [beads]
  codex:
    mcp_servers: [cognovis-tools]
    skills: [beads]
    sandbox_mode: read-only
```

**Scope split:** CL-j92j (this bead, `meta` repo) lands the `read_beads` capability
and its hermetic regression tests only. It does **not** reassign any agent. The
companion bead **`clc-zbj4`** (in the `cognovis-core` repo, a separate bead
tracker) migrates `effort-classifier` and `wave-monitor` from `manage_beads` to
`read_beads`. Until `clc-zbj4` lands, those two agents still declare `manage_beads`
and still receive the full 14-tool set — the least-privilege gap is not closed
until both beads ship. The 5 genuinely orchestration-class consumers
(`bead-orchestrator`, `quick-fix`, `session-close`, `wave-orchestrator`,
`bead-author`) correctly keep `manage_beads`.

To roll back `read_beads`: remove the `read_beads` entry from `capabilities.yaml`
and its hermetic tests in `tests/test_build_agent.py`
(`test_read_beads_capability_registry_is_read_only_typed_tools`,
`test_build_agent_grants_read_beads_read_only_tools_end_to_end`). Note that
`clc-zbj4`, if already landed, depends on `read_beads` existing — coordinate the
rollback across both repos.

## Prerequisites for the migrated capabilities to work

Before an agent using `manage_beads` can operate:

1. The cognovis-tools MCP server must be installed and registered in each harness config.
   - Source: `cognovis-core/mcp-servers/cognovis-tools/`
   - Registration: see `library.yaml` entry for `cognovis-tools` (install.mcp section)
   - Run `/library use cognovis-tools` or follow `cookbook/add-mcp.md` to register

2. The agent's generated `tools:` frontmatter must list the specific
   `mcp__cognovis-tools__bead_*` tool names it needs (see the corrected
   `manage_beads` shape above) — registering the server is necessary but not
   sufficient.

3. Verify the server is reachable: it should appear in `tools/list` including `bead_show`,
   `bead_claim`, `bead_close`.

## How to roll back

To revert the capabilities.yaml migration:

```bash
# Option 1: git revert the commit
git revert <commit-sha-of-migration>

# Option 2: manual revert — restore manage_beads entry
# In capabilities.yaml, replace:
#   manage_beads:
#     claude:
#       tools: [mcp__cognovis-tools__bead_show, ...]  # full list above
#       mcpServers: [cognovis-tools]
#       skills: [beads]
# With:
#   manage_beads:
#     claude:
#       tools: [Bash, Read, Grep, Glob]
#       skills: [beads]
#
# And remove mcpServers from the claude binding and mcp_servers from the codex binding.
# Also remove mcpServers/mcp_servers from inspect_git binding.
```

## Smoke test

Regression coverage (run instead of a manual check):

```bash
COGNOVIS_CORE=/path/to/cognovis-core uv run pytest \
  tests/test_build_agent.py tests/test_cognovis_agent_fleet_capabilities.py -k manage_beads
```

This asserts, against the real `capabilities.yaml` and the real
`cognovis-core/agents/*.md` sources:

- `manage_beads.claude.tools` is non-empty and exposes every typed
  `mcp__cognovis-tools__bead_*` tool (fails if it regresses to `[]`).
- `bead-orchestrator`, `quick-fix`, and `session-close` build with the full typed
  tool set, including `bead_update_notes` and `bead_close`.
- `review-agent` and `verification-agent` do not declare `manage_beads` and gain
  no `mcp__cognovis-tools__bead_*` tool (role-leakage regression fixture included).

For a live check in a Claude Code session with `cognovis-tools` registered and the
typed tool present in that session's `tools:` allowlist:

```
mcp__cognovis-tools__bead_show(bead_id="CL-ugwe")
# Expected: Envelope with bead data
```
