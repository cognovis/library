# Agent Golden Prompt Composition: Design + Prototype

> **Bead:** CL-9b1 | **Epic:** CL-36o (Multi-Harness Library) | **Date:** 2026-04-30
> **Status:** NORMATIVE — this document is the design decision record for the three-layer
> agent composition model and MODEL-STANDARD primitive.
>
> **Depends on:**
> - `docs/PRIMITIVES.md` §10 Model-Standard — defines the MODEL-STANDARD primitive
> - `docs/research/standards-loading.md` (CL-v56) — loader contract reused for model-standards
> - `docs/research/agents-format-mapping.md` (CL-11p) — field mapping extended for new frontmatter

---

## Executive Summary

Today every agent inherits the harness's system prompt (Anthropic's Claude Code prompt,
OpenAI's Codex prompt, etc.). This makes agents harness-dependent: the same agent behaves
differently in Claude Code vs. Codex because the harness system prompt varies.

**Decision**: Implement a three-layer Agent Golden Prompt composition model, resolved at
install time by the Library, writing the composed prompt to the harness-native location.

```
Effective Agent System Prompt = compose(
  Layer 1: Cognovis Base Golden Prompt,
  Layer 2: Agent Persona,
  Layer 3: Model-Standard(s) for the agent's declared model
)
```

---

## The Three Layers

### Layer 1: Cognovis Base Golden Prompt

**File:** `.agents/golden-prompts/cognovis-base.md`

**Purpose:** Global behavioral rules, safety checks, confirmation gates, content isolation,
and tool constraint encoding. Applies to ALL agents regardless of harness or model.

**Why it exists:**
- The harness system prompt (Anthropic's) changes on vendor update cadence, silently altering
  agent behavior. The Cognovis Base Golden Prompt is under our control.
- Cross-harness portability: a Codex agent with no Claude Code ancestor needs the same safety
  rules. Encoding them in a Library-owned file lets us inject them during Codex TOML generation.
- Token efficiency: the harness prompt contains many things agents don't need (Bash safety rules
  already enforced by guardrails, etc.). The Cognovis Base is intentionally smaller.

**Content:** Safety checks (Dolt push pattern, `bd init` block, payment/PII stop), confirmation
gates (bd close, git push --force, etc.), content isolation rule (untrusted content via
content-processor), core behavioral rules (English source code, task tracking via bd, no emoji),
tool constraint encoding, session close protocol.

**Extends pattern:**
- `golden_prompt_extends: cognovis-base` — use Cognovis Base as Layer 1 (default for all agents)
- `golden_prompt_extends: from-scratch` — skip Layer 1 entirely (rare; only for test/isolated agents)

### Layer 2: Agent Persona

**File:** Agent's own `.md` (e.g., `.claude/agents/changelog-updater.md`)

**Purpose:** Agent-specific instructions: purpose, tool grants, workflow steps, domain expertise.

**This layer is not changed by the composition model.** Existing agent files continue to work as-is.
Adding `golden_prompt_extends` and `model_standards` frontmatter fields opts the agent into
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
  golden_prompt_extends = frontmatter field value from source_agent_file (default: cognovis-base)
  model_standards       = frontmatter field value from source_agent_file (default: [])
  model                 = frontmatter model field from source_agent_file (used for alias lookup)

ALGORITHM:
  1. Load Layer 1:
       path = .agents/golden-prompts/<golden_prompt_extends>.md
       L1   = read(path)
     Skip if golden_prompt_extends = from-scratch OR path not found (warn)

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
                    # golden_prompt_extends: <value>
                    # model_standards: <list>
     OpenCode:    target = .opencode/agents/<name>.md (installed copy)
     Pi:          export composed string from TypeScript extension module

  IMPORTANT: The source_agent_file is NEVER overwritten. On repeat installs,
  Layer 2 always reads the original unmodified agent persona body from the source.
  Only the INSTALLED COPY (target) is written with the composed prompt.
```

**Tool constraint encoding in composed prompt:** Because Codex ignores per-agent tool
frontmatter (`tools:` list) at the sandbox level, the Cognovis Base Golden Prompt (Layer 1)
includes a "Tool Constraints" section that instructs the agent to honor its declared tool
list behaviorally. The Library composer additionally SHOULD inject the agent's effective
tool grant as a prose statement at the top of the composed prompt for Codex targets.

---

## File Conventions

| Artifact | Path | Scope |
|----------|------|-------|
| Cognovis Base Golden Prompt | `.agents/golden-prompts/cognovis-base.md` | Library-global |
| Additional golden prompts | `.agents/golden-prompts/<name>.md` | Library-global |
| Model-standards | `.agents/model-standards/<model-name>.md` | Project-local or user-global |
| Agent definition (source) | `.claude/agents/<name>.md` | Claude Code |
| Codex TOML (derived) | `.codex/agents/<name>.toml` | Codex |

**Loader:** Both `.agents/standards/` AND `.agents/model-standards/` use the same
`scripts/standards-loader.sh`. Model-standards use the `--load-model-standard <name>`
operation which resolves from `.agents/model-standards/`. See `docs/research/standards-loading.md`
for the full loader contract.

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
golden_prompt_extends: cognovis-base
model_standards: []
---
```

### Cross-Harness Validation

**Claude Code path:**
- `golden_prompt_extends: cognovis-base` → Layer 1 = `.agents/golden-prompts/cognovis-base.md`
- `model_standards: []` → Layer 3 = empty (no model-standard for haiku yet)
- Composed body = `cognovis-base.md` content + agent persona body
- Written to: `.claude/agents/changelog-updater.md` body (harness-native)
- Claude Code reads the body directly — composition is transparent

**Codex path (forward translation):**
- `golden_prompt_extends: cognovis-base` → added as comment: `# golden_prompt_extends: cognovis-base`
- `model_standards: []` → added as comment: `# model_standards: []`
- `developer_instructions` = composed body (Layer 1 + Layer 2, same as Claude Code)
- `sandbox_mode` = inferred from tools list: [Bash, Read, Edit] → `workspace-write`
  (Edit requires write access; Bash is present)
- `model` = `haiku` → vocabulary lookup required (gpt-4.1-mini or equivalent when targeting OpenAI)

**Graceful degradation (fields unknown to harness):**
- Codex ignores unknown frontmatter fields silently. `golden_prompt_extends` and
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
  Decision deferred. Current implementation: single-extends only (`golden_prompt_extends` is a scalar).
  Multiple inheritance via `model_standards` list is already supported (each entry is a file).

- **Harness drift:** When Anthropic adds something useful to the Claude Code system prompt,
  how do we decide whether to incorporate it into `cognovis-base.md`?
  Not addressed in this bead. Manual review process assumed.

- **from-scratch testing:** Agents that set `golden_prompt_extends: from-scratch` bypass Layer 1.
  This is useful for test agents that should NOT follow Cognovis safety rules.
  Implementation: if `golden_prompt_extends: from-scratch`, skip Layer 1 entirely.

- **haiku model-standard:** `changelog-updater` declares `model_standards: []` because
  `claude-haiku.md` is not yet defined. Create it as a follow-up when haiku behavioral
  patterns are documented.

---

## Cross-References

- `docs/PRIMITIVES.md` §10 — MODEL-STANDARD primitive definition and composition algorithm
- `docs/research/standards-loading.md` (CL-v56) — loader contract (reused for model-standards)
- `docs/research/agents-format-mapping.md` (CL-11p) — field mapping with new composition fields
- `.agents/golden-prompts/cognovis-base.md` — Cognovis Base Golden Prompt source
- `.agents/model-standards/` — model-standard file directory
- `scripts/standards-loader.sh` — loader script (`--load-model-standard` operation)
- `tests/smoke/run-smoke.sh` `smoke_golden_prompts()` — structural validation
