# Layer 2 (Agents): Format Translation Spec — Claude Code `.md` ↔ Codex `.toml`

> **Bead:** CL-11p | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-30
> **Scope:** Layer 2 agent format translation. Covers field-by-field mapping, canonical source rationale, forward and reverse translation algorithms, and a worked sample (researcher agent).

---

## Executive Summary

**Layer 2 parity: ACHIEVABLE, with defined lossy fields.** Both harnesses support named agents with a system prompt and model selection, but the field sets diverge significantly:

| Dimension | Claude Code | Codex CLI | Verdict |
|-----------|------------|-----------|---------|
| Format | YAML frontmatter + Markdown body | TOML | Translation required |
| Canonical source | `.claude/agents/<name>.md` | `~/.codex/agents/<name>.toml` | Claude Code is canonical (NORMATIVE — per existing sync infrastructure) |
| Tool scoping | Per-agent allowlist (`tools:`) and blocklist (`disallowedTools:`) | Coarse `sandbox_mode` + `mcp_servers` | **Lossy** — granular → coarse |
| MCP integration | Per-agent `mcpServers:` frontmatter list | Global `~/.codex/config.toml`, no per-agent override | **Lossy** — explicit → inherited |
| System prompt | Inline Markdown body below `---` | `developer_instructions` TOML string | **1:1** — structural transform only |
| Model | `haiku`, `sonnet`, `opus` | `gpt-5.4`, `gpt-5.5`, etc. | **Vocabulary gap** — requires mapping table |
| Reasoning effort | No equivalent | `model_reasoning_effort: high/xhigh/medium/low` | **Codex-only** — dropped on reverse |
| Color hint | `color: cyan` | No equivalent | **Claude-only** — dropped on forward |
| Invocation targeting | `system_prompt_file:` (external file) | Always inline in `developer_instructions` | **Lossy** — must inline on forward |
| Aliases | No equivalent | `nickname_candidates` (array of strings) | **Codex-only** — dropped on reverse |

**Implication for library:** Forward translation (Claude → Codex) is the primary path. Three fields are lossy but non-breaking. The `sync-codex-agents` script already implements this pattern; this document formalizes the spec it should follow.

---

## 1. Install Paths (feeds CL-6hg)

| Tool | Project-local | User-global |
|------|---------------|-------------|
| **Claude Code** | `.claude/agents/<name>.md` | `~/.claude/agents/<name>.md` |
| **Codex CLI** | `.codex/agents/<name>.toml` | `~/.codex/agents/<name>.toml` |

**Tracked source pattern** (from existing `.toml` comment headers, NORMATIVE — confirmed in three production agents):

```toml
# Tracked source: dev-tools/codex-agents/<name>.toml (git)
# Repo export: .codex/agents/<name>.toml (git, synced by sync-codex-agents)
# Installed copy: ~/.codex/agents/<name>.toml (local, synced by sync-codex-agents)
# Source of truth: beads-workflow/agents/<name>.md (Claude version)
# Drift tracking: compare developer_instructions against the Claude system prompt
```

---

## 2. Field-by-Field Mapping Table

Every Claude Code frontmatter field vs. its Codex TOML counterpart.

| Claude Code field | Type | Codex TOML field | Type | Mapping | Notes |
|-------------------|------|------------------|------|---------|-------|
| `name` | string | `name` | string | **1:1** | Identical semantics. NORMATIVE. |
| `description` | string / block scalar | `description` | multi-line string | **1:1** | Content identical; formatting differs (YAML block scalar → TOML multi-line string). |
| `model` | string (`haiku`, `sonnet`, `opus`) | `model` | string (`gpt-5.4`, `gpt-5.5`) | **Vocabulary gap** | No universal mapping — requires explicit lookup table (see §4). INFERRED — model identifiers are harness-specific. |
| `tools` | comma-separated string | `sandbox_mode` | string enum | **Lossy forward** | Claude tool allowlists are granular per-tool. Codex sandbox modes are coarse (`read-only` / `workspace-write` / `danger-full-access`). Fine-grained tool grants cannot be preserved. NORMATIVE — confirmed from bead-orchestrator.toml and session-close.toml Tool Capability Gaps sections. |
| `disallowedTools` | comma-separated string | `sandbox_mode` | string enum | **Lossy forward** | Block-list semantics have no direct Codex equivalent. Must infer `sandbox_mode` from presence of write-capable tools in the blocklist. If `Write, Edit` are blocked, consider `read-only`. INFERRED — architectural best-guess. |
| `mcpServers` | YAML list of server names | *(inherited from global config)* | N/A | **Lossy forward** | Claude Code allows per-agent MCP server scoping. Codex inherits from `~/.codex/config.toml` globally — no per-agent `mcp_servers` override field exists (NORMATIVE — confirmed from all three production agents). Translation: document as comment; no runtime enforcement. |
| `color` | string (`blue`, `cyan`, `green`, etc.) | *(no equivalent)* | — | **Claude-only — dropped** | UI color hint. No Codex equivalent. Drop silently on forward translation. NORMATIVE — field not present in any observed Codex TOML. |
| `system_prompt_file` | string (path) | *(no equivalent)* | — | **Lossy forward** | Claude Code can load the system prompt body from an external file. Codex always inlines the system prompt in `developer_instructions`. On translation: read the referenced file and inline its content. NORMATIVE — Codex TOML has no file-reference field. |
| *(body — below `---`)* | Markdown text | `developer_instructions` | multi-line string | **1:1** | Structural transform only: Markdown body → TOML multi-line string. If `system_prompt_file` is set in frontmatter, the body may be a stub — the file content is the authoritative system prompt and must be inlined instead. |
| *(no equivalent)* | — | `nickname_candidates` | array of strings | **Codex-only** | Natural-language aliases for agent invocation matching. No Claude Code equivalent. Preserved on round-trip as a comment in the `.md` frontmatter or dropped. NORMATIVE — confirmed in all three production agents. |
| *(no equivalent)* | — | `model_reasoning_effort` | string (`high`, `xhigh`, `medium`, `low`) | **Codex-only** | Chain-of-thought depth control. No Claude Code equivalent. Dropped on reverse translation. NORMATIVE — confirmed in all three production agents. |
| *(no equivalent)* | — | `sandbox_mode` | string enum | **Codex-only (primary)** | No Claude Code equivalent. Set on forward translation based on tool analysis (see §4). NORMATIVE. |
| *(no equivalent)* | — | `mcp_servers` (TOML table) | table | **Codex-only (optional)** | Per-agent MCP server override. Rarely used — all three production agents omit it, inheriting global config. NORMATIVE. |

### Summary: Fields by Category

**1:1 (lossless):**
- `name`, `description`, body → `developer_instructions`

**Lossy — Claude Code → Codex (forward):**
- `tools` → `sandbox_mode` (granular → coarse)
- `disallowedTools` → `sandbox_mode` (no direct equivalent)
- `mcpServers` → comment block only (no enforcement; global `config.toml` inheritance assumed)
- `color` → (dropped silently)
- `system_prompt_file` → (must inline; file reference lost)

**Vocabulary gap:**
- `model` → model identifier requires lookup table

**Codex-only (no reverse mapping):**
- `nickname_candidates`
- `model_reasoning_effort`
- `sandbox_mode` (primary field; inferred on forward translation)

---

## 3. Recommended Canonical Source Format

**The Claude Code `.md` file is the canonical source.** The Codex `.toml` is the derived artifact.

### Why Claude Code is canonical (NORMATIVE — per sync infrastructure)

1. **Existing practice confirms it.** All three production agents (`bead-orchestrator`, `session-close`, `wave-orchestrator`) contain the comment:
   ```
   # Source of truth: beads-workflow/agents/<name>.md (Claude version)
   ```
   This is not aspirational — it is the established operational pattern.

2. **Richer field set.** Claude Code frontmatter supports fields (`color`, `mcpServers`, `disallowedTools`, `system_prompt_file`) that have no Codex equivalent. Choosing Codex as canonical would permanently lose these fields on round-trip.

3. **Platform primacy.** Claude Code is the primary development harness. Codex is a secondary harness targeted for portability. Canonical source follows the primary development context.

4. **Drift detection direction.** The sync script compares `developer_instructions` against the Claude system prompt — i.e., it treats the Claude body as the reference and Codex as the derivative. Reversing this would require inverting all existing tooling.

### Extended Frontmatter Pattern for Canonical `.md` Files

When a Claude Code agent has a Codex counterpart, the following extended frontmatter fields SHOULD be added to the `.md` file to preserve Codex-only metadata for round-trip fidelity:

```yaml
---
name: bead-orchestrator
description: >-
  Autonomous orchestrator for single-bead implementation...
tools: Read, Write, Edit, Bash, Grep, Glob, Agent
model: sonnet
color: purple

# Codex-specific metadata (preserved for sync-codex-agents round-trip)
codex_model: gpt-5.4
codex_model_reasoning_effort: high
codex_sandbox_mode: workspace-write
codex_nickname_candidates:
  - implement bead
  - bead implement
  - run bead
  - orchestrate bead
---
```

The `codex_*` prefix namespace isolates Codex-specific fields from Claude Code frontmatter, preventing Claude Code from attempting to interpret them. INFERRED — this pattern is not yet in use but follows the extended frontmatter convention.

---

## 4. Forward Translation Algorithm: Claude Code `.md` → Codex `.toml`

This is the primary translation direction. The `sync-codex-agents` script SHOULD follow these steps.

### Step 1: Read the canonical source

```bash
# Parse the .md file
CLAUDE_MD="beads-workflow/agents/<name>.md"
```

Split at `---` delimiters:
- Frontmatter: YAML between first and second `---`
- Body: Markdown text after second `---`

If `system_prompt_file` is set in frontmatter, read the referenced file — that is the authoritative body content, not the inline stub. If the referenced file is not readable at translation time, fall back to the inline body content. Log a warning that the external file reference semantics are lost.

### Step 2: Map direct fields

| Claude Code | Codex TOML | Action |
|------------|------------|--------|
| `name` | `name` | Copy verbatim |
| `description` | `description` | Copy verbatim; convert YAML block scalar to TOML multi-line string |
| body / `system_prompt_file` content | `developer_instructions` | Copy verbatim as TOML multi-line string |

### Step 3: Map model

Use the following lookup table. INFERRED — no official mapping exists. The `sonnet → gpt-5.4` mapping is observed in three production agents; `haiku` and `opus` mappings are best-guess and have no observed precedent:

| Claude Code `model` | Codex `model` | Notes |
|--------------------|--------------|-------|
| `haiku` | `gpt-5.4` | Haiku = lightweight; mapped to `gpt-5.4` (same as sonnet). This reflects current practice — may be revisited as Codex model identifiers stabilize and a distinct lightweight model becomes available. |
| `sonnet` | `gpt-5.4` | Default production model |
| `opus` | `gpt-5.5` | Heavy reasoning tasks; map to most capable Codex model |
| *(unset)* | `gpt-5.4` | Default |

Emit a translation comment in the generated TOML:
```toml
# model translated from Claude 'sonnet' → Codex 'gpt-5.4' (see agents-format-mapping.md §4)
model = "gpt-5.4"
```

### Step 4: Derive `sandbox_mode`

Codex's `sandbox_mode` is the primary access-control mechanism. Derive it from Claude Code fields using this decision tree:

```
1. If `tools` contains `Write` or `Edit`:
   → sandbox_mode = "workspace-write"

2. Else if `disallowedTools` contains `Write` and `Edit` (both blocked):
   → sandbox_mode = "read-only"

3. Else if `tools` contains only Read-family tools (Read, Grep, Glob, Bash*):
   → sandbox_mode = "read-only"
   (* Bash with read-only ops — conservative default)

4. Else if no `tools` field is set:
   → sandbox_mode = "workspace-write"  # default; safe for most agents
   (emit warning: "No tools field — defaulting to workspace-write")

5. `danger-full-access`: NEVER auto-emit. Require explicit `codex_sandbox_mode` in frontmatter.
```

**Lossy trade-off note:** Tool-level granularity is permanently lost. A Claude Code agent that allows `Read, Bash, Grep` but not `Write` maps to `read-only`, which correctly prohibits writes but also prohibits running arbitrary shell commands that could do anything. The Codex sandbox does not distinguish read-only bash from write-capable bash. Document this in the generated TOML as a comment.

### Step 5: Handle `mcpServers`

No per-agent `mcp_servers` override is supported in Codex (NORMATIVE — confirmed from all three production agents). Generate a comment block:

```toml
# MCP servers declared in Claude source: searxng, executive-circle, heypresto, open-brain
# Codex does not support per-agent mcp_servers — inherits from ~/.codex/config.toml
# Verify these servers are configured globally before using this agent in Codex.
```

### Step 6: Handle Codex-only fields

Check the Claude `.md` frontmatter for `codex_*` extended fields:

| Extended field | TOML field |
|---------------|------------|
| `codex_model_reasoning_effort` | `model_reasoning_effort` |
| `codex_sandbox_mode` | `sandbox_mode` (overrides Step 4 derivation) |
| `codex_nickname_candidates` | `nickname_candidates` |

If no `codex_*` fields are present, apply defaults:
- `model_reasoning_effort`: derive from model → `high` for opus, `high` for sonnet, `medium` for haiku. INFERRED.
- `nickname_candidates`: generate from `name` and first sentence of `description`. INFERRED.

### Step 7: Drop non-translatable fields

The following Claude Code fields have no Codex equivalent. Drop silently:

- `color` — UI-only hint, no runtime effect
- `system_prompt_file` path — content was already inlined in Step 1
- `disallowedTools` — block-list semantics encoded in `sandbox_mode` (Step 4)
- `tools` — granular list encoded in `sandbox_mode` (Step 4)

### Step 8: Write the TOML header

Prepend the tracking comment header:

```toml
# Tracked source: dev-tools/codex-agents/<name>.toml (git)
# Repo export: .codex/agents/<name>.toml (git, synced by sync-codex-agents)
# Installed copy: ~/.codex/agents/<name>.toml (local, synced by sync-codex-agents)
# Source of truth: <claude-source-path> (Claude version)
# Drift tracking: compare developer_instructions against the Claude system prompt
# Last synced: <YYYY-MM-DD> from version <calver-tag>
```

### Step 9: Assemble the TOML file

```toml
<header comments from Step 8>

name = "<name>"
description = """
<description>
"""
nickname_candidates = [<from Step 6>]
model = "<model from Step 3>"
model_reasoning_effort = "<from Step 6>"
sandbox_mode = "<from Step 4 or Step 6>"

<mcp comment block from Step 5>

developer_instructions = """
<body content from Step 1>
"""
```

---

## 5. Reverse Translation Algorithm: Codex `.toml` → Claude Code `.md`

Less common. Use this when a Codex agent has diverged from its canonical `.md` source and you need to backport changes.

**Warning:** Reverse translation is inherently lossy in the opposite direction — Codex-only fields (`nickname_candidates`, `model_reasoning_effort`) have no Claude Code frontmatter equivalent unless the extended `codex_*` pattern is in use.

### Step 1: Parse the TOML

Extract all fields. Identify which were originally derived vs. extended.

### Step 2: Map direct fields

| Codex TOML field | Claude Code | Action |
|-----------------|------------|--------|
| `name` | `name` | Copy verbatim |
| `description` | `description` | Copy verbatim; convert TOML multi-line to YAML block scalar |
| `developer_instructions` | body | Write as Markdown body below `---` |

### Step 3: Reverse-map model

| Codex `model` | Claude Code `model` | Notes |
|--------------|-------------------|-------|
| `gpt-5.4` | `sonnet` (default) | Both `haiku` and `sonnet` forward to `gpt-5.4`, so the reverse is always `sonnet`. A `haiku` selection can only be preserved if `codex_model: haiku` is set in the extended frontmatter. |
| `gpt-5.5` | `opus` | |
| *(any other)* | `sonnet` (default; emit warning) | |

### Step 4: Handle Codex-only fields

If `nickname_candidates` or `model_reasoning_effort` are present, add them as `codex_*` extended frontmatter fields to preserve them:

```yaml
codex_model_reasoning_effort: high
codex_nickname_candidates:
  - implement bead
  - bead implement
```

This preserves round-trip fidelity for future forward translations.

### Step 5: Reconstruct tool fields

`sandbox_mode` cannot be reliably reverse-mapped to a granular `tools` list. Apply conservative defaults:

| `sandbox_mode` | Claude Code fields |
|---------------|-------------------|
| `read-only` | `tools: Read, Grep, Glob` |
| `workspace-write` | `tools: Read, Write, Edit, Bash, Grep, Glob` |
| `danger-full-access` | `tools: Read, Write, Edit, Bash, Grep, Glob` + emit warning |

Emit a comment noting the reconstruction is approximate.

### Step 6: Write the `.md` file

```markdown
---
name: <name>
description: >-
  <description>
tools: <from Step 5>
model: <from Step 3>
<codex_* fields from Step 4>
---

<developer_instructions content>
```

---

## 6. Sample Translation: `researcher` Agent

### 6a. Claude Code Source (canonical)

File: `~/.claude/plugins/cache/sussdorff-plugins/core/latest/agents/researcher.md`

```yaml
---
name: researcher
description: >-
  Web research agent that uses SearXNG for search and summarize skill for deep
  content extraction. Optimized for multi-source research tasks where quality
  and speed matter more than token cost. Returns structured research summaries.
disallowedTools: Write, Edit, Agent
model: sonnet
system_prompt_file: malte/system-prompts/agents/researcher.md
color: cyan
mcpServers:
  - searxng
  - executive-circle
  - heypresto
  - open-brain
---

# Research Agent

Specialized agent for web research tasks. Uses a structured search pipeline
optimized for speed and result quality over token efficiency.

## Tool Routing (MANDATORY)
...
```

**Observed fields:**
- `name`: researcher
- `description`: 2-line description
- `disallowedTools`: Write, Edit, Agent
- `model`: sonnet
- `system_prompt_file`: external file reference (body is a stub or the full prompt)
- `color`: cyan (UI hint)
- `mcpServers`: 4 servers listed

**Note:** The body present in the `.md` file is a candidate system prompt — `system_prompt_file` references an alternate (possibly personalized) path at `malte/system-prompts/agents/researcher.md`. Because that file is not accessible in this translation context, the inline body is used as a fallback per the algorithm's fallback rule (§4 Step 1). In production, the external file should be resolved first.

### 6b. Translation Walkthrough (Step by Step)

**Step 1 — Parse:**
- Frontmatter: parsed above
- Body: "# Research Agent\n\nSpecialized agent for web research tasks..." (full content)
- External file `malte/system-prompts/agents/researcher.md` is not accessible in this translation context → fall back to inline body per §4 Step 1 fallback rule; warning: external file reference semantics are lost

**Step 2 — Direct fields:**
- `name: researcher` → `name = "researcher"`
- `description` block scalar → `description = """..."""`

**Step 3 — Model:**
- `sonnet` → `gpt-5.4`
- Emit translation comment

**Step 4 — Derive `sandbox_mode`:**
- `disallowedTools: Write, Edit, Agent` — both write tools blocked
- Decision tree: path 2 applies → `sandbox_mode = "read-only"`
- `Agent` is also blocked but sandbox_mode has no agent-spawning concept; note as comment

**Step 5 — MCP servers:**
- `searxng, executive-circle, heypresto, open-brain` → comment block only; no TOML field emitted

**Step 6 — Codex-only fields:**
- No `codex_*` fields in source frontmatter
- `model_reasoning_effort`: sonnet maps to `high` (INFERRED default)
- `nickname_candidates`: generated from name + description → `["research", "web research", "investigate", "research topic"]`

**Step 7 — Dropped fields:**
- `color: cyan` — dropped silently
- `system_prompt_file` path — content inlined
- `disallowedTools` — encoded in sandbox_mode

### 6c. Resulting Codex TOML

```toml
# Tracked source: dev-tools/codex-agents/researcher.toml (git)
# Repo export: .codex/agents/researcher.toml (git, synced by sync-codex-agents)
# Installed copy: ~/.codex/agents/researcher.toml (local, synced by sync-codex-agents)
# Source of truth: core/agents/researcher.md (Claude version)
# Drift tracking: compare developer_instructions against the Claude system prompt
# Last synced: 2026-04-30

name = "researcher"
description = """
Web research agent that uses SearXNG for search and summarize skill for deep
content extraction. Optimized for multi-source research tasks where quality
and speed matter more than token cost. Returns structured research summaries.
"""
nickname_candidates = ["research", "web research", "investigate", "research topic"]

# model translated from Claude 'sonnet' → Codex 'gpt-5.4' (see agents-format-mapping.md §4)
model = "gpt-5.4"

# model_reasoning_effort: INFERRED from model mapping (sonnet → high)
model_reasoning_effort = "high"

# sandbox_mode: derived from disallowedTools=[Write, Edit, Agent]
# Write and Edit are both blocked → read-only
# Note: 'Agent' (subagent spawning) is blocked in Claude; Codex has no equivalent
# sandbox control — document-only, not enforced by sandbox_mode.
sandbox_mode = "read-only"

# MCP servers declared in Claude source: searxng, executive-circle, heypresto, open-brain
# Codex does not support per-agent mcp_servers — inherits from ~/.codex/config.toml
# Verify these servers are configured globally before using this agent in Codex.

developer_instructions = """
# Research Agent

Specialized agent for web research tasks. Uses a structured search pipeline
optimized for speed and result quality over token efficiency.

## Tool Routing (MANDATORY)

### Search: SearXNG ONLY

```
mcp__searxng__searxng_web_search
```

- NEVER use built-in `WebSearch` (blocked)
- Run 2-4 search queries with different phrasings to get broad coverage
- Extract the top 3-5 most relevant URLs from search results

### Content Extraction: Summarize Skill ONLY

For any URL where you need more than the search snippet:

```
Skill(skill="summarize", args="<URL>")
```

- NEVER use `WebFetch` for research content — it returns raw HTML that wastes context
- `WebFetch` is ONLY acceptable for structured data endpoints (JSON APIs, RSS feeds)
- Use `summarize` for all web pages, articles, documentation sites

### Pipeline

1. **Search** — 2-4 SearXNG queries with varied phrasing
2. **Triage** — Review snippets, pick 3-5 most relevant URLs
3. **Extract** — `summarize` skill on each selected URL
4. **Synthesize** — Combine findings into structured output

## Output Format

Return a structured summary with:

```markdown
## Research: <Topic>

### Key Findings
- Finding 1 (source)
- Finding 2 (source)
- ...

### Details
<Organized by subtopic, not by source>

### Sources
- [Title](URL) — one-line description of what this source contributed
```

## What NOT to Do

- Don't fetch every URL from search results — triage first
- Don't return raw search snippets as findings — synthesize
- Don't use WebFetch for HTML pages — always use summarize
- Don't run more than 6 summarize calls — diminishing returns
- Don't include irrelevant tangential findings — stay focused on the query

## Scope

This agent handles research ONLY. It does not:
- Write code
- Create files (except its output)
- Modify the codebase
- Create beads or tasks

## Tool / Capability Gaps (Codex)

### Named tool calls
- **Claude**: Uses named harness tools (`Read`, `Bash`, `Grep`, `Glob`) — blocked tools
  enforced at the harness level via `disallowedTools`.
- **Codex**: No per-agent tool blocklist. `sandbox_mode = "read-only"` prevents filesystem
  writes but does not block specific MCP tools. Agent scoping is the primary guardrail.

### MCP invocation prefix
- **Claude**: MCP tools invoked with harness prefix: `mcp__searxng__searxng_web_search`
- **Codex**: Plain tool name via MCP integration: `searxng_web_search` (server: searxng).
  Verify server naming in `~/.codex/config.toml`.

### Subagent spawning
- **Claude**: `Agent` tool is explicitly blocked via `disallowedTools`.
- **Codex**: No `Agent` tool concept at the field level — the constraint is implicit in
  `sandbox_mode = "read-only"` (read-only agents conventionally do not spawn subagents).
"""
```

### 6d. Annotated Lossy Fields

| Field | Value in Source | Result in TOML | Loss Type |
|-------|----------------|----------------|-----------|
| `color: cyan` | UI hint | Dropped | **Non-breaking** — no runtime effect |
| `disallowedTools: Write, Edit, Agent` | Per-tool blocklist | Encoded as `sandbox_mode = "read-only"` | **Structural loss** — `Agent` blocking is document-only in Codex |
| `mcpServers: [searxng, ...]` | Explicit scope | Comment only | **Enforcement loss** — global inheritance cannot per-agent scope |
| `system_prompt_file: malte/...` | External file path | Inlined | **Reference lost** — personalized overlay not preserved |
| `model: sonnet` | Claude model alias | `gpt-5.4` | **Vocabulary mapping** — functionality preserved |

---

## 7. Gap Analysis: What Cannot Be Translated

### Irreversible losses (Claude → Codex)

1. **Per-tool granularity.** A Claude agent with `tools: Read, Bash, Grep` (no Write) maps to `sandbox_mode = "read-only"` — which is broadly correct but loses the ability to distinguish "read-only bash" from "no bash at all." NORMATIVE — confirmed from Codex sandbox documentation.

2. **Agent spawning blocklist.** `disallowedTools: Agent` prevents subagent spawning in Claude. Codex has no equivalent prohibition — `max_depth` in global config is the only depth control, not per-agent. NORMATIVE — confirmed in bead-orchestrator.toml Tool Capability Gaps section.

3. **MCP server scoping.** `mcpServers: [searxng]` in Claude limits which MCP servers the agent can call. Codex provides no per-agent MCP allowlist — all servers in `config.toml` are available to all agents. NORMATIVE — confirmed from all three production agents.

4. **External system prompt file.** `system_prompt_file` enables personalization overlays (user-specific instructions in a separate file). Codex always inlines. The file reference and its layering semantics are lost.

### Irreversible losses (Codex → Claude)

1. **`nickname_candidates`.** Natural-language alias matching has no Claude Code equivalent. Aliases trigger agent invocation in Codex (`"implement bead"` → bead-orchestrator). Round-trip via `codex_nickname_candidates` extended field preserves the data but not the runtime behavior. NORMATIVE — Claude Code uses `Agent(subagent_type=<name>)` for explicit invocation.

2. **`model_reasoning_effort`.** Chain-of-thought depth control has no Claude Code equivalent field. Claude Code manages reasoning depth via model selection (`sonnet` vs `opus`) rather than a separate effort parameter. NORMATIVE — confirmed in Codex documentation.

3. **`haiku` → `gpt-5.4` → `sonnet` round-trip model loss.** Because both `haiku` and `sonnet` forward-translate to `gpt-5.4`, the reverse mapping always produces `sonnet`. An agent originally configured with `model: haiku` silently loses its model selection on round-trip. This can only be prevented if `codex_model: haiku` is set in the Claude source's extended frontmatter — in that case, §5 Step 3 should use the `codex_model` value as the reverse-mapping target. INFERRED — no observed production agent uses `haiku`.

---

## 8. Recommendations for `sync-codex-agents`

1. **Implement the Step 4 derivation logic** for `sandbox_mode` — avoid hard-coding it per agent.

2. **Validate the model lookup table** (Step 3) when new Claude or Codex models are released. Treat the mapping as soft configuration, not hardcoded logic.

3. **Preserve Codex-only fields** in the Claude source using the `codex_*` extended frontmatter pattern (§3). This prevents losing `nickname_candidates` and `model_reasoning_effort` on re-sync.

4. **Emit a Tool Capability Gaps section** in the generated `developer_instructions` for every translated agent. This documents harness-specific behavior differences inline, next to the content that is affected. All three production agents follow this pattern (NORMATIVE).

5. **Track drift** between `developer_instructions` and the canonical Claude body. A SHA or last-synced timestamp in the comment header enables tooling to detect when the Claude source has changed and the TOML needs re-sync.

6. **Do NOT automatically emit `danger-full-access`** in `sandbox_mode`. Require explicit `codex_sandbox_mode: danger-full-access` in the Claude frontmatter as a human authorization gate.

---

## Sources

### Observed TOML files (NORMATIVE — primary sources for this doc)

- `~/.codex/agents/bead-orchestrator.toml` — production agent, full Tool Capability Gaps section
- `~/.codex/agents/session-close.toml` — production agent, Codex-Claude divergence documented inline
- `~/.codex/agents/wave-orchestrator.toml` — production agent, cmux/cld differences documented

### Observed Claude agent files (NORMATIVE)

- `~/.claude/plugins/cache/sussdorff-plugins/core/latest/agents/researcher.md` — sample translation subject

### Cross-references

- `docs/ARCHITECTURE.md` — Layer 2 overview and sync infrastructure context
- `docs/PRIMITIVES.md` — Agent primitive definition (§3); NORMATIVE/INFERRED label convention
- `docs/research/codex-prompts.md` — Layer 3 translation research (CL-qzw); cross-tool observations reused

### Bead context

- `CL-11p` — this bead
- `CL-qzw` — Codex Layer 3 research (confirms Codex sandbox_mode semantics and MCP behavior)
- `CL-6hg` — `library.yaml` default_dirs (consumes install path table from §1)
- `CL-06x` — `/library use` tool-awareness cookbook (consumes translation algorithm from §4)

---

### Debrief

**Key decisions:**

1. The `codex_*` extended frontmatter pattern (§3) is new — not yet implemented in the codebase. It is the cleanest way to preserve Codex-only metadata in the canonical Claude source without polluting Claude Code's field space.

2. The `sandbox_mode` derivation decision tree (§4, Step 4) required judgment calls: blocking `Write, Edit` → `read-only` is correct, but blocking `Agent` has no Codex equivalent. Documented as a comment in the generated TOML — runtime enforcement cannot be preserved.

3. The `system_prompt_file` field in `researcher.md` creates an ambiguity: the external file at `malte/system-prompts/agents/researcher.md` may be the deployed system prompt, but it was not accessible during this translation. The inline body was used as a fallback per §4 Step 1. In production, the external file should be resolved first. The file-reference semantics are a personalization feature that cannot be translated.

**Challenges:**

- MCP tool invocation prefix differs between harnesses (`mcp__searxng__searxng_web_search` in Claude vs. plain `searxng_web_search` in Codex). This is a cross-cutting concern that affects agent instructions, not just metadata. The Tool Capability Gaps pattern (from production agents) is the right place to document this.

- Model vocabulary gap has no authoritative mapping. The table in §4 Step 3 is INFERRED from observed practice. A future bead should establish a formal model equivalence table when Codex model identifiers stabilize.

**Surprising findings:**

- All three production Codex agents have no `mcp_servers` TOML section — they rely entirely on global inheritance. This is simpler than expected but means the per-agent MCP scoping in Claude Code is silently dropped in every existing sync, not just the researcher.

- The `nickname_candidates` field is present in all three production agents but has no formal documentation in this codebase. It is the primary invocation mechanism for Codex agents (analogous to `Agent(subagent_type=<name>)` in Claude) and deserves more attention in the sync tooling.

**Follow-up items:**

- CL-06x (`/library use` cookbook): consume translation algorithm from §4 for auto-generating TOML from Claude `.md` source during library install.
- Establish formal model equivalence table when Codex model identifiers stabilize.
- Implement `codex_*` extended frontmatter convention in existing canonical agent files (bead-orchestrator, session-close, wave-orchestrator).
- Add `sync-codex-agents` script to the beads-workflow package that implements the algorithm in §4.
