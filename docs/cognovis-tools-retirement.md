# cognovis-tools retirement inventory

Bead `CL-tbsz` retires the private `cognovis-tools` MCP server and its authoring
surface. Historical ADR and changelog references remain as provenance only.

## Caller disposition

| Former contract | Demonstrated callers | Disposition |
|---|---|---|
| Bead read/write tools | Bead orchestration, Session Close, billing review | Public `bd` commands and the Beads MCP server |
| Provider-session tools | Bead implementation and review agents | ACPX dispatch and session handling |
| Release tools | `cognovis-release` | Deterministic `release_metadata.py` helper using public `bd` |
| Bounded log tools | `cognovis-release` | Deterministic `safe_log.py` helper with root checks and redaction |
| Git and generic script execution | No independently required caller | Removed; callers use existing public CLIs and owned scripts |
| Caller-identity and review-gate transport | Legacy orchestration paths | Removed with the private gateway; current review contracts are transport-neutral |

## Ownership removed

- The marketplace server implementation and server-only tests are deleted.
- The platform catalog entry, capability bindings, migration checks, installer
  special cases, and model-registry projector are deleted.
- `mcp-tool-forge` is retired without a replacement.
- The remaining Beads and ACPX guardrails are renamed to `agent-shell-safety`;
  their safety contracts do not depend on an MCP server.

## Decommission verification

Source and replacement tests passed before decommissioning. The Library-managed
remove path then removed the Claude Code, Codex, Cursor, OpenCode, and
Antigravity registrations, stopped and uninstalled the daemon, and removed the
global lock receipt. The runtime clone was moved recoverably to the macOS Trash.
The loopback health endpoint no longer accepts connections. The renamed
`agent-shell-safety` packs and hook registrations passed installer verification,
including the ACPX availability probe; obsolete private-server pack names and
hook origins are absent. Final command evidence is also recorded on `CL-tbsz`.
