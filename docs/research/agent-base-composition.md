# Agent Base Prompt Composition: Design + Prototype

> **Bead:** CL-9b1 | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-30
> **Status:** NORMATIVE — this document is the design decision record for the three-layer
> agent composition model and MODEL-STANDARD primitive.
>
> **Depends on:**
> - `docs/primitives/model-standard.md` — defines the MODEL-STANDARD primitive
> - `scripts/standards-loader.sh` — loader used for model-standards
> - `docs/research/agents-format-mapping.md` (CL-11p) — field mapping extended for new frontmatter

---

## Executive Summary

> **Terminology note (2026-05-15).** This document uses the current term
> "agent base prompt" for agent system prompt Layer 1; see
> [system-prompt.md](../primitives/system-prompt.md) for the
> orchestrator/agent distinction and [agent-base.md](../primitives/agent-base.md)
> for the agent-level primitive.

> **Premise correction (2026-05-15).** An earlier version of this doc claimed
> that "every agent inherits the harness's system prompt." That is **wrong**
> for Claude Code and at best misleading for Codex. Per the upstream Claude
> Code docs (`code.claude.com/docs/en/sub-agents`): *"Subagents receive only
> this system prompt (plus basic environment details like working directory),
> **not the full Claude Code system prompt**."* A Codex named-agent invoked via
> nickname starts a fresh session whose `developer_instructions` likewise
> replace, not extend, the parent session's developer prompt. Agents start
> essentially **blank** — that is the actual motivation for the composition
> model below.

A subagent starts with only its own system prompt (the body of its agent file)
plus minimal environment details. It does **not** inherit cross-cutting safety
rules, confirmation gates, or operating policies from the harness or from the
parent orchestrator session. Without a composition mechanism, every agent has
to re-inline that material verbatim.

**Decision**: Implement a three-layer agent system prompt composition model,
resolved at install time by the Library, writing the composed prompt to the
harness-native location. This gives every agent a shared, Library-controlled
base layer without duplicating it across files.

```
Composed Agent System Prompt = compose(
  Layer 1: Cognovis Base (agent base prompt, a.k.a. "agent base prompt"),
  Layer 2: Agent Persona,
  Layer 3: Model-Standard(s) for the agent's declared model
)
```

This composed string is what the harness sees as the **agent's** system prompt
when the agent runs. It is unrelated to the **orchestrator's** system prompt —
that is the vendor's Claude Code / Codex prompt and is configured separately
(see [system-prompt.md](../primitives/system-prompt.md)).

---

## The Three Layers

### Layer 1: Per-Harness Cognovis Agent Base Prompt

**Files:** `.agents/agent-bases/claude-agent-base.md` and
`.agents/agent-bases/codex-agent-base.md`. The logical
`agent_base_extends: cognovis-base` value resolves to one of these files by
target harness, with `.agents/agent-bases/cognovis-base.md` retained as a
one-release fallback alias.

**Purpose:** Cross-cutting behavioral rules that the target harness cannot
fully enforce at runtime. Applies to all composed agents for that harness.

**Why it exists:**
- Agents do not inherit the harness or orchestrator system prompt (see the
  premise correction above), so cross-cutting safety, confirmation, and
  operating rules have to be supplied to each agent explicitly. The Cognovis
  Base centralizes that material in one Library-owned file rather than
  re-inlining it in every agent persona.
- Cross-harness portability: a Codex agent and a Claude Code agent need the
  same safety baseline, but not the same runtime-enforcement prose. Encoding
  one slim base per harness lets the composer inject only the behavior the
  target harness cannot enforce directly.
- Drift control: when the Anthropic or OpenAI harness prompt changes, the
  agents do not silently pick it up — but our base prompt is also not silently
  pinned to the harness. We update the Cognovis Base deliberately, on review.

**Content:** English source code, beads task tracking, content isolation,
risk flagging, tool-grant honoring, and product-capability discipline. Runtime
command gates and destructive-action blocks belong in harness policy, hooks,
rules, permissions, sandboxing, or judge-layer flows.

**Extends pattern:**
- `agent_base_extends: cognovis-base` — use Cognovis Base as Layer 1 (default for all agents)
- `agent_base_extends: from-scratch` — skip Layer 1 entirely (rare; only for test/isolated agents)

### Layer 2: Agent Persona

**File:** Agent's own `.md` (e.g., `.claude/agents/changelog-updater.md`)

**Purpose:** Agent-specific instructions: purpose, tool grants, workflow steps, domain expertise.

**This layer is not changed by the composition model.** Existing agent files continue to work as-is.
Adding `agent_base_extends` and `model_standards` frontmatter fields opts the agent into
the composition model — without those fields, the agent is treated as "from-scratch" (no composition).

### Layer 3: Model-Standard

**Files:** `.agents/model-standards/<model-name>.md`

**Purpose:** Model-specific behavioral guidance that adjusts the agent's behavior for the
specific model's strengths and quirks.

**Why separate from Layer 2:**
- Embedding model-specific guidance in the agent persona locks the persona to one model.
  Swapping from `sonnet` to `opus` would require editing every agent file.
- Model-standards are reusable: 20 agents running on sonnet all benefit from the same
  conciseness guidance without 20 duplicated sections.

**Declared in frontmatter:**
```yaml
model_standards: [claude-sonnet-4-6]
```

If `model_standards` is empty or absent, Layer 3 is skipped.

---

## Install-Time Composition Algorithm

Composition happens ONCE when the agent is installed via `/library use`. The harness
receives the fully-composed prompt — there is no runtime composition.

```
INPUT:
  source_agent_file = library copy of agent (e.g., plugin-bundle/agents/<name>.md)
                      This is the SOURCE — it is NEVER overwritten by composition.
  agent_base_extends = frontmatter field value from source_agent_file (default: cognovis-base)
  model_standards       = frontmatter field value from source_agent_file (default: [])
  model                 = frontmatter model field from source_agent_file (used for alias lookup)

ALGORITHM:
  1. Load Layer 1:
       if agent_base_extends = cognovis-base and harness is claude:
         preferred = claude-agent-base
       else if agent_base_extends = cognovis-base and harness is codex:
         preferred = codex-agent-base
       else:
         preferred = agent_base_extends

       Search project-local and user-global agent-bases dirs for:
         a) .agents/agent-bases/<preferred>.md
         b) .agents/agent-bases/<agent_base_extends>.md

       L1 = read(first match)
     Skip if agent_base_extends = from-scratch OR path not found (warn)

  2. Load Layer 2:
       L2 = body of source_agent_file (content below the --- frontmatter marker)
       NOTE: This reads the SOURCE file body. The SOURCE is never modified. The
       COMPOSED prompt is always written to a SEPARATE target path (see step 5).

  3. Load Layer 3:
     a) If model_standards is non-empty: for each name in model_standards:
          path  = standards-loader.sh --load-model-standard <name>
          L3[i] = content (empty if not found, with warning)
     b) If model_standards is empty AND model is set: try alias-based lookup:
          path  = standards-loader.sh --load-model-standard <model>
          (the loader resolves via alias scanning if direct filename lookup fails)
          L3[0] = content (empty if not found — silently skip, model alias unknown)
     c) L3 = concat(L3[i], separator="---")

  4. Compose:
       composed = L1 + "\n---\n" + L2 + (L3 if L3 is non-empty: "\n---\n" + L3)

  5. Write composed prompt to SEPARATE target path (never the source):
     Claude Code: target = .claude/agents/<name>.md (installed copy)
                  Write: frontmatter from source (unchanged) + composed body
     Codex:       target = .codex/agents/<name>.toml
                  developer_instructions = composed
                  add composition metadata as comment headers:
                    # agent_base_extends: <value>
                    # model_standards: <list>
     OpenCode:    target = .opencode/agents/<name>.md (installed copy)
     Pi:          export composed string from TypeScript extension module

  IMPORTANT: The source_agent_file is NEVER overwritten. On repeat installs,
  Layer 2 always reads the original unmodified agent persona body from the source.
  Only the INSTALLED COPY (target) is written with the composed prompt.
```

**Tool constraint encoding in composed prompt:** Because Codex ignores per-agent tool
frontmatter (`tools:` list) at the sandbox level, the Cognovis Base Agent Base Prompt (Layer 1)
includes a "Tool Constraints" section that instructs the agent to honor its declared tool
list behaviorally. The Library composer additionally SHOULD inject the agent's effective
tool grant as a prose statement at the top of the composed prompt for Codex targets.

---

## File Conventions

| Artifact | Path | Scope |
|----------|------|-------|
| Claude Agent Base Prompt | `.agents/agent-bases/claude-agent-base.md` | Library-global |
| Codex Agent Base Prompt | `.agents/agent-bases/codex-agent-base.md` | Library-global |
| Cognovis Base alias fallback | `.agents/agent-bases/cognovis-base.md` | Library-global |
| Additional agent base prompts | `.agents/agent-bases/<name>.md` | Library-global |
| Model-standards | `.agents/model-standards/<model-name>.md` | Project-local or user-global |
| Agent definition (source) | `.claude/agents/<name>.md` | Claude Code |
| Codex TOML (derived) | `.codex/agents/<name>.toml` | Codex |

**Loader:** `.agents/model-standards/` uses `scripts/standards-loader.sh`.
Model-standards use the `--load-model-standard <name>` operation which resolves
from `.agents/model-standards/`.

---

## Prototype Agent Migration: changelog-updater

**Source:** `~/code/claude-code-plugins/beads-workflow/agents/changelog-updater.md`

### Before (pre-CL-9b1)

```yaml
---
name: changelog-updater
description: Aktualisiert CHANGELOG.md basierend auf geschlossenen Beads
model: haiku
tools:
  - Bash
  - Read
  - Edit
---
```

### After (post-CL-9b1 migration)

```yaml
---
name: changelog-updater
description: Aktualisiert CHANGELOG.md basierend auf geschlossenen Beads
model: haiku
tools:
  - Bash
  - Read
  - Edit
agent_base_extends: cognovis-base
model_standards: []
---
```

### Cross-Harness Validation

**Claude Code path:**
- `agent_base_extends: cognovis-base` → Layer 1 = `.agents/agent-bases/claude-agent-base.md`
- `model_standards: []` → Layer 3 = empty (no model-standard for haiku yet)
- Composed body = `claude-agent-base.md` content + agent persona body
- Written to: `.claude/agents/changelog-updater.md` body (harness-native)
- Claude Code reads the body directly — composition is transparent

**Codex path (forward translation):**
- `agent_base_extends: cognovis-base` → added as comment: `# agent_base_extends: cognovis-base`
- `model_standards: []` → added as comment: `# model_standards: []`
- `developer_instructions` = composed body (Codex Layer 1 + Layer 2)
- `sandbox_mode` = inferred from tools list: [Bash, Read, Edit] → `workspace-write`
  (Edit requires write access; Bash is present)
- `model` = `haiku` → vocabulary lookup required (gpt-4.1-mini or equivalent when targeting OpenAI)

**Graceful degradation (fields unknown to harness):**
- Codex ignores unknown frontmatter fields silently. `agent_base_extends` and
  `model_standards` in the Claude Code `.md` frontmatter are unknown to Codex and
  are dropped on forward translation (not written to TOML). The composition result
  is already inlined in `developer_instructions`.
- NORMATIVE: confirmed from agents-format-mapping.md field table (CL-11p) + this bead.

---

## Model-Standards Created (CL-9b1)

| File | Model | Guidance |
|------|-------|----------|
| `.agents/model-standards/claude-sonnet-4-6.md` | Claude Sonnet 4.6 | Conciseness and directness: no preamble, no recapping, direct tool calls, match response length to complexity |
| `.agents/model-standards/claude-opus-4-7.md` | Claude Opus 4.7 | Thinking budget: use extended thinking (~5000 tokens) for complex analysis, enumerate alternatives, distinguish NORMATIVE vs INFERRED claims |

---

## Open Questions

- **Extension chains:** Does the composition model support `cognovis-base → cognovis-strict → team-specific`?
  Decision deferred. Current implementation: single-extends only (`agent_base_extends` is a scalar).
  Multiple inheritance via `model_standards` list is already supported (each entry is a file).

- **Harness drift:** When Anthropic adds something useful to the Claude Code
  orchestrator system prompt, how do we decide whether to incorporate it into
  `claude-agent-base.md` or `codex-agent-base.md`? Note that the orchestrator prompt change does not
  automatically reach agents (agents do not inherit it), so any inclusion is
  a deliberate copy-down decision, not a propagation. Not addressed in this
  bead. Manual review process assumed.

- **from-scratch testing:** Agents that set `agent_base_extends: from-scratch` bypass Layer 1.
  This is useful for test agents that should NOT follow Cognovis safety rules.
  Implementation: if `agent_base_extends: from-scratch`, skip Layer 1 entirely.

- **haiku model-standard:** `changelog-updater` declares `model_standards: []` because
  `claude-haiku.md` is not yet defined. Create it as a follow-up when haiku behavioral
  patterns are documented.

---

## Cross-References

- `docs/primitives/model-standard.md` — MODEL-STANDARD primitive definition and composition algorithm
- `docs/primitives/agent-base.md` — AGENT-BASE primitive definition
- `docs/research/agents-format-mapping.md` (CL-11p) — field mapping with new composition fields
- `.agents/agent-bases/claude-agent-base.md` and `.agents/agent-bases/codex-agent-base.md` — per-harness Layer 1 sources
- `.agents/model-standards/` — model-standard file directory
- `scripts/standards-loader.sh` — loader script (`--load-model-standard` operation)
- `tests/smoke/run-smoke.sh` `smoke_agent_bases()` — structural validation
