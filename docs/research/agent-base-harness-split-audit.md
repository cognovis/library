# Agent Base Harness Split Audit

CL-13p split the generic `cognovis-base` Layer 1 prompt into per-harness files:

- `claude-agent-base.md`
- `codex-agent-base.md`

`agent_base: auto` is the preferred logical selector. The composer maps that
selector to the correct per-harness file for `--harness=claude` and
`--harness=codex`, then falls back to `cognovis-base.md` for one release if the
per-harness file is not installed.

## Rule Disposition

| Old generic rule | New location | Replacement enforcement or rationale |
|---|---|---|
| Block raw `dolt push --force` | Dropped from Claude base; retained as runtime policy | Claude Code hooks and shell guardrails own command vetoes. |
| Block `bd init`, `bd init --force`, `dolt init` on existing projects | Dropped from Claude base; retained as runtime policy | Claude Code hooks and shell guardrails own command vetoes. |
| Require confirmation for `bd close` | Dropped from Claude base | Beads workflow and session-close protocol own bead closure. |
| Require confirmation for mail/email dispatch | Dropped from Claude base | Mail tools and user-confirmation flows own outbound side effects. |
| Require confirmation for external MCP creates | Dropped from Claude base | MCP tool policy and action-boundary/judge-layer flows own side-effect authorization. |
| Require confirmation for destructive git/filesystem/database operations | Dropped from Claude base; retained as runtime policy | Hooks, shell guardrails, sandboxing, and approval policy own command gating. |
| Source code language is English | Retained in both bases | Generative behavior; runtime cannot enforce comments, identifiers, and log text. |
| Use beads instead of TODO trackers | Retained in both bases | Workflow behavior; runtime cannot reliably infer task-tracking intent. |
| Route untrusted external content through content-processor flow | Retained in both bases | Generative behavior; runtime cannot classify every content boundary. |
| Flag payment, PII, auth/access, and compliance-sensitive work | Retained in both bases | Risk-recognition behavior; runtime cannot fully classify domain risk. |
| Honor declared agent tool grants | Retained in both bases; load-bearing in Codex | Claude has per-agent tool declarations; Codex still needs prompt-level honoring for broader built-ins. |
| Do not remove capabilities out of fear of AI misuse | Retained in both bases | Product judgment; runtime cannot enforce design intent. |
| Push to remote before session completion | Dropped from base | Beads/session-close workflow owns session lifecycle. |
| Tool constraints encoding section | Collapsed into one bullet per base | The detailed enforcement story belongs in primitive docs and builder logic. |
| Composition notes | Dropped from base | Installer/composer docs own implementation details. |

## Harness Notes

Claude Code should rely on hooks, permissions, and per-agent `tools:` /
`disallowedTools:` for enforceable controls. Its base prompt carries only the
shared behavioral rules the runtime cannot enforce.

Codex should rely on sandboxing, approval policy, hooks, rules, and MCP tool
filters where available. Its base prompt retains explicit behavioral tool-grant
honoring because Codex does not have Claude-style built-in tool allowlists for
all agent invocations.
