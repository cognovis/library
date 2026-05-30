# Model-Standard

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A markdown document containing model-specific behavioral guidance
injected for an agent persona on a given model (e.g., conciseness guidance for
Sonnet, extended thinking budget configuration for Opus). Model-standards are a
sub-type of standards scoped to a particular model's characteristics.

**Key constitutive feature.** Model-scoped behavioral overlay: unlike general
standards (which apply to any model), a model-standard is keyed to a specific model
ID and adjusts the agent's behavior for that model's strengths and limitations.

**Storage.** `.agents/model-standards/<model-name>.md` (project-local) or
`~/.agents/model-standards/<model-name>.md` (user-global).
Example: `.agents/model-standards/claude-sonnet-4-6.md`

**Loading.** Model-standards use project-local > user-global precedence and are
inlined by the Library composer into the composed **agent system prompt** —
that is, the prompt the harness sees when the agent runs, distinct from the
[orchestrator system prompt](system-prompt.md) of the top-level `cld` / `cdx`
session.

**Path resolution (same precedence rules as Standards):**

| Priority | Path | Scope |
|----------|------|-------|
| 1 (wins) | `.agents/model-standards/<name>.md` | Project-local |
| 2 | `~/.agents/model-standards/<name>.md` | User-global |

**Trigger semantics.** Injected at agent install/sync time when the agent's
frontmatter specifies a `model` field matching this model-standard's filename.
The three-layer composition is applied in order (see Agent System Prompt
Composition below).

**Agent System Prompt Composition (three layers).**

> This composes the **agent's** system prompt — the prompt the harness sees
> when a spawned subagent runs. It does **not** modify the orchestrator's
> system prompt. Subagents do not inherit the orchestrator prompt at all
> (per `code.claude.com/docs/en/sub-agents`: *"Subagents receive only this
> system prompt … not the full Claude Code system prompt."*).

When the Library installs an agent, the **composed agent system prompt** is
built from three layers in order:

```
Layer 1: Cognovis Base (agent-base)
  └── Global behavioral rules, safety checks, confirmation gates,
      content isolation, core skill access. Applies to all agents.
      Without this layer, agents start blank — the harness gives them
      no inherited base.

Layer 2: Agent Persona
  └── The agent's own body (from .claude/agents/<name>.md or
      .codex/agents/<name>.toml developer_instructions). Defines the
      agent's specific purpose, tool grants, and domain expertise.

Layer 3: Model-Standard (optional)
  └── Model-specific overlays: verbosity tuning, thinking budget,
      output format adjustments, known model quirks to work around.
      Applied only when the agent's `model` field matches a known
      model-standard.
```

**Decision-rule frontmatter fields.**

```yaml
# In an agent's frontmatter (.claude/agents/<name>.md):
agent_base: auto                       # choose the harness-appropriate base prompt
model: claude-sonnet-4-6               # triggers model-standard lookup
model_standards: [conciseness, tool-use-efficiency]  # optional explicit overrides
```

**Composition algorithm (install-time, NOT runtime).**

The Library executes this composition once when the agent is installed or synced.
There is no runtime composition — the harness receives the fully-composed prompt.

Source and target are always SEPARATE paths. The source agent file (library copy) is
never overwritten — the composed prompt is written to the installed copy only.

```
1. Load Layer 1: resolve .agents/agent-bases/<agent_base>.md
   (skip if agent_base=from-scratch or file not found). The logical `auto`
   value resolves to claude-agent-base or codex-agent-base for those harnesses
   before falling back to cognovis-base.md.

2. Load Layer 2: read the SOURCE agent file body (library copy, never the installed copy)
   This reads the original unmodified persona. Repeat installs always read the same source.

3. Load Layer 3:
   a) If model_standards is non-empty: load each name via
         standards-loader.sh --load-model-standard <name>
      Concatenate results in declaration order.
   b) If model_standards is empty AND model is set: attempt alias-based lookup via
         standards-loader.sh --load-model-standard <model>
      (the loader resolves by alias if direct filename lookup fails; silent skip on miss)

4. Compose: Layer1 + "\n---\n" + Layer2 + ("\n---\n" + Layer3 if Layer3 non-empty)

5. Write composed prompt to INSTALLED copy (separate from source):
   - Claude Code: .claude/agents/<name>.md body (keep frontmatter from source)
   - Codex: developer_instructions in .codex/agents/<name>.toml
     (add composition metadata as header comments)
   - OpenCode: .opencode/agents/<name>.md body
   - Pi: export as TypeScript string from the extension module
```

**Tool constraint encoding.** Per-agent tool grants (`tools:`, `disallowedTools:`) are
NOT enforced by all harnesses at the sandbox level (Codex global sandbox semantics
ignore per-agent tool constraints). Therefore, the Library MUST encode the agent's
effective tool grant in the composed system prompt body, not rely on frontmatter alone.
The Codex agent base retains explicit behavioral tool-grant honoring for this
reason; Claude Code primarily relies on per-agent tool declarations and runtime
permissions.

**Canonical source locations (CL-9b1).**

- Agent base prompts: `.agents/agent-bases/<name>.md`
  - Claude base: `.agents/agent-bases/claude-agent-base.md`
  - Codex base: `.agents/agent-bases/codex-agent-base.md`
  - Cognovis alias fallback: `.agents/agent-bases/cognovis-base.md`
- Model standards: `.agents/model-standards/<model-name>.md`
  - Sonnet conciseness: `.agents/model-standards/claude-sonnet-4-6.md`
  - Opus thinking budget: `.agents/model-standards/claude-opus-4-8.md`

**When to choose it.** Create a model-standard when:
- A specific model has known behaviors (verbosity, thinking defaults, tool-call
  patterns) that require project-wide adjustment.
- Different agents in the system run on different models and need model-aware
  behavioral tuning without duplicating guidance in every agent file.

**Counter-examples.**
- Do NOT put model-specific guidance in the agent persona file — that locks the
  persona to one model and makes model-swapping harder.
- Do NOT create a model-standard for a behavior that applies to all models — that
  belongs in the base agent base prompt or a general standard.
- Do NOT introduce a parallel loader for model-standards — reuse
  `scripts/standards-loader.sh --load-model-standard <name>` (same contract).

---
