# Rollback: capabilities.yaml MCP Migration (ADR-0007 Phase 6)

## What was migrated

The following entries in `capabilities.yaml` were migrated from `tools: [Bash] + skills`
to `mcpServers: [cognovis-tools]` in bead CL-ugwe.6 (2026-05-29):

| Capability | Before | After |
|---|---|---|
| `manage_beads` | `tools: [Bash, Read, Grep, Glob]` + `skills: [beads]` | `mcpServers: [cognovis-tools]` + `skills: [beads]` |
| `inspect_git` | `tools: [Bash, Read, Grep, Glob]` | added `mcpServers: [cognovis-tools]` (Bash tools retained) |

`send_email` was NOT migrated — cognovis-tools has no mail tools.

## Prerequisites for the migrated capabilities to work

Before an agent using `manage_beads` via `mcpServers: [cognovis-tools]` can operate:

1. The cognovis-tools MCP server must be installed and registered in each harness config.
   - Source: `cognovis-core/mcp-servers/cognovis-tools/`
   - Registration: see `library.yaml` entry for `cognovis-tools` (install.mcp section)
   - Run `/library use cognovis-tools` or follow `cookbook/add-mcp.md` to register

2. Verify the server is reachable: it should appear in `tools/list` including `bead_show`,
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
#       mcpServers: [cognovis-tools]
#       skills: [beads]
# With:
#   manage_beads:
#     claude:
#       tools: [Bash, Read, Grep, Glob]
#       skills: [beads]
#
# And remove mcp_servers from codex binding.
# Also remove mcpServers/mcp_servers from inspect_git binding.
```

## Smoke test (manual, after registration)

After registering cognovis-tools in the target harness:

```bash
# Should return bead data via MCP (not via bd CLI):
# In a Claude Code session with cognovis-tools registered:
# mcp__cognovis-tools__bead_show(bead_id="CL-ugwe")
# Expected: Envelope with bead data
```

Agents granted only `manage_beads` (no `run_shell`) should be able to perform
full bead lifecycle operations via the cognovis-tools MCP without raw `bd` access.
