# MCP-Server

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** An external capability provider accessed via the Model Context
Protocol (MCP). MCP servers expose tools, resources, and prompts to any MCP-compatible
client without requiring shell access.

**Key constitutive feature.** Protocol-mediated external capability: MCP servers run
as separate processes (or remote services) and expose a typed tool API over a standard
protocol. They are the primary extensibility mechanism for harnesses that have no
shell access.

**Trigger semantics.** MCP tools appear in the model's tool list alongside native
tools. The model calls them the same way it calls Bash or Read — by generating a
tool-use block. The MCP server responds with a tool result.

**Decision rule (harness-dependent).**

| Harness | Shell access | Recommendation |
|---------|-------------|----------------|
| Claude Code | YES | Prefer CLI + Skill. MCP adds process overhead without benefit when shell is available. INFERRED — architectural principle. |
| Codex CLI | YES | Same as Claude Code: prefer CLI + Skill. INFERRED. |
| claude.ai web | NO | MCP-Server is the only path for external tool access. NORMATIVE. |
| Claude iOS | NO | MCP-Server is the only path for external tool access. NORMATIVE. |

**When to choose it.** Use an MCP server when:
- The target harness has no shell access (web, mobile) and the capability requires
  external data or tool execution.
- An existing MCP server already provides the capability (no need to wrap in a skill).
- The capability must be accessible to both coding and non-coding harnesses and you
  want a single implementation.

**Counter-examples.**
- Do NOT default to MCP for Claude Code / Codex — when you have shell access, a CLI
  tool + skill is simpler, faster, and easier to debug.
- Do NOT build an MCP server to replace a skill that only coding harnesses use.

**Worked examples.**

| MCP Server | Why it is an MCP server |
|-----------|------------------------|
| `executive-circle` MCP | Content library for web/iOS users who have no shell access. The CLI equivalent (`crwl`) exists for coding harnesses. |
| `pencil` MCP | Design tool for non-coding harnesses. `.pen` files are encrypted and must be accessed via MCP tools. |

---
