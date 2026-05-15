# System-Prompt

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** The **orchestrator-level** system prompt and built-in tool set
that the harness CLI (`claude` / `codex`) loads when a top-level session starts.
This is what fills the "System prompt" + "System tools" buckets shown in
`/context` — it is NOT the same as an agent's system prompt.

**Why a separate primitive.** Documentation and code historically conflated two
distinct prompts:

| Layer | Whose prompt? | Whose tool set? | Composed how? |
|---|---|---|---|
| **Orchestrator system prompt** (this primitive) | The top-level `cld` / `cdx` session | Built-in harness tools (Bash, Read, Edit, …) + MCP tools | Vendor default, optionally overridden at CLI launch |
| **Agent system prompt** (see [Agent](agent.md), [Golden-Prompt](golden-prompt.md), [Model-Standard](model-standard.md)) | A subagent spawned via the `Agent` tool / nickname | Per-agent `tools:` grant in frontmatter / TOML | Install-time three-layer composition by the Library |

A subagent does **not** inherit the orchestrator's system prompt. Quoting the
upstream Claude Code docs (`code.claude.com/docs/en/sub-agents`):

> "Subagents receive only this system prompt (plus basic environment details
> like working directory), not the full Claude Code system prompt."

That sentence is the load-bearing reason the two layers must be documented as
separate primitives.

**Default content (vendor-controlled).**

- **Claude Code:** Anthropic's Claude Code system prompt — tone/style, "doing
  tasks" rules, executing-actions-with-care rules, auto-memory system docs,
  MCP-server `instructions:` blobs, and SessionStart hook injections (rules.d,
  beads PRIME, etc.). Roughly **10 k tokens** baseline plus whatever your hooks
  inject.
- **Codex:** OpenAI's Codex CLI prompt + AGENTS.md (loaded as user-instructions
  append) + `~/.codex/config.toml` settings.

**System tools (also vendor-controlled by default).**

- The schemas for every built-in tool the orchestrator can call (`Bash`,
  `Read`, `Edit`, `Write`, `Agent`, `Skill`, `ToolSearch`, `AskUserQuestion`,
  …). Roughly **10 k tokens** baseline before MCP tools are added on top.
- MCP tools can be loaded eagerly or deferred (Claude Code's
  `enableDeferredTools` setting). Deferred tools are surfaced by name only
  until fetched via `ToolSearch`.

**Override mechanisms (Claude Code).**

The Claude Code CLI exposes flags that the Library's `cld` wrapper can chain
to slim or replace the orchestrator prompt and its tool set:

| Flag | Effect |
|---|---|
| `--system-prompt <text>` | Fully replace the default system prompt with a literal string. With this flag set, `--exclude-dynamic-system-prompt-sections` is ignored — you must include cwd/env/git context yourself. |
| `--system-prompt-file <path>` | Same as `--system-prompt` but reads the prompt from a file. |
| `--append-system-prompt <text>` / `--append-system-prompt-file <path>` | Keep the default and append. |
| `--tools <list>` | Whitelist built-in tools by name (e.g. `"Bash,Read,Edit"`). Removes schemas for everything else — actual context savings, not just a permission gate. `""` disables all tools; `"default"` is everything. |
| `--allowedTools` / `--disallowedTools` | Permission gates only. Tool schemas remain loaded. |
| `--disable-slash-commands` | Drop the entire skills list from context. |
| `--bare` | Minimal mode: skip hooks, LSP, plugin sync, auto-memory, background prefetches, CLAUDE.md auto-discovery. Sets `CLAUDE_CODE_SIMPLE=1`. Use with explicit `--system-prompt`, `--mcp-config`, `--settings`, etc. |
| `--exclude-dynamic-system-prompt-sections` | Move per-machine sections (cwd, env, git, memory paths) into the first user message for better cache reuse. Ignored when `--system-prompt` is set. |

**Override mechanisms (Codex).** Equivalents are less precisely documented;
verify against the Codex CLI before relying on them.

**cld registry mechanism (Library-managed).**

The `cld` wrapper resolves an optional system-prompt override via
`system-prompts/registry.yml` at the Library root. When a working directory
matches an `entries:` rule, `cld` injects `--system-prompt-file <path>` (or
`--append-system-prompt-file <path>` if `mode: append`):

```yaml
# system-prompts/registry.yml
entries:
  - match: /Users/<you>/code/<repo>
    file: slim-default.md
    mode: replace

default:
  file: slim-default.md
  mode: append
```

If the file or registry is missing, the block is skipped silently and the
vendor default is used. The lib lives at `bin/lib/cld-system-prompt.zsh`.

**Storage.**

| Artifact | Path |
|---|---|
| Registry | `<library-root>/system-prompts/registry.yml` |
| Prompt files | `<library-root>/system-prompts/<name>.md` |
| Loader | `<library-root>/bin/lib/cld-system-prompt.zsh` |

**Trigger semantics.** Resolution happens once at `cld` launch (or `cdx` for
Codex, once equivalents are wired). There is no runtime composition. The
orchestrator session lives with the resolved prompt until it ends — the prompt
is not re-resolved when the user runs `/clear`, `/compact`, or `--resume`.

**When to override.**

- You want to reduce the orchestrator's baseline token cost (the floor is the
  vendor prompt + tool schemas — often ~20 k before any user content).
- You want to enforce project-specific orchestrator behavior that the vendor
  prompt does not provide (e.g. a house style for tool-call narration).
- You want to standardize tone or output format across many top-level sessions
  in the same repo without relying on `CLAUDE.md` discoverability.

**Counter-examples.**

- Do NOT use this primitive to add agent-level instructions. Use [Golden-Prompt
  (Agent Base Prompt)](golden-prompt.md) — those are composed into the agent's
  own system prompt at install time.
- Do NOT use this primitive to add cross-cutting safety rules that should
  apply to every spawned subagent. Those agents do not inherit the
  orchestrator's system prompt, so a system-prompt override does not reach
  them. Encode the rules in the agent base prompt instead.
- Do NOT replace the system prompt to remove vendor safety rules — those
  often interact with the harness's permission and hook systems in
  undocumented ways. Strip-and-replace is for ergonomics, not for jailbreaking.

**Status of the cld registry mechanism (2026-05-15).**

Wired in `bin/cld` but inert in this checkout: `system-prompts/` directory
and `registry.yml` do not exist, so the injection block at `bin/cld:156-200`
no-ops and the vendor default is used. To activate, create
`system-prompts/registry.yml` plus at least one prompt file.

**Cross-references.**

- [Agent](agent.md) — the OTHER primitive that has a system prompt (agent-level)
- [Golden-Prompt](golden-prompt.md) — Layer 1 of the agent system prompt
- [Model-Standard](model-standard.md) — Layer 3 of the agent system prompt
- `bin/cld` (lines 156-200) — orchestrator prompt injection wiring
- `bin/lib/cld-system-prompt.zsh` — registry resolver
