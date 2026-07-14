# Beads MCP migration retirement

The former Beads capability migration was retired on 2026-07-14 by
`clc-jzu5`. This document replaces the obsolete operational rollback recipe;
do not restore the retired `manage_beads` or `read_beads` capabilities.

## Current state

- Bead reads and mutations use the public `bd` CLI directly.
- Skills provide concise lifecycle guidance and deterministic scripts own
  routing, claiming, author checks, review-cache writes, and closeout.
- `cognovis-tools` remains registered for its provider-session, Git, log,
  release, and closed-registry execution families.
- The server publishes no `bead_*` tools.
- DCG does not block or redirect direct `bd` commands.

## Why the previous migration was retired

The typed Bead tools ultimately invoked the same `bd` CLI available to every
human and process. Without fleet-wide Bash denial, the wrapper was not a trust
boundary. It duplicated a stabilizing upstream interface while adding daemon
liveness, version skew, correlated configuration failures, and substantial
first-party source and test maintenance.

The earlier least-privilege split between read and mutation capabilities solved
a local allowlist problem inside that wrapper architecture. Removing the Bead
tool family removes the need for both capabilities entirely.

## Recovery

If a direct Bead workflow fails:

1. Run the failing `bd` command directly and inspect its output.
2. Run `bd prime` for the current workflow contract.
3. Repair the focused Skill, deterministic helper, hook, or Session Close
   handler that owns the failing step.
4. Do not reintroduce an MCP wrapper unless a new ADR demonstrates an
   independently valuable, non-bypassable boundary.

The historical migration and its corrections remain recorded in ADR-0007 and
the Git history.
