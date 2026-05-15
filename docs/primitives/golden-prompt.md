# Golden-Prompt (Agent Base Prompt)

> Primitive reference extracted from the agent composition model in [PRIMITIVES.md](../PRIMITIVES.md).

> **What this primitive is — and isn't.** A golden-prompt is the shared
> **agent-level** base layer that the Library prepends to an agent persona at
> install time. It is **not** the orchestrator's system prompt (the prompt
> Claude Code / Codex itself loads at session start). The two layers live in
> different contexts and are configured by different mechanisms:
>
> | Layer | Primitive | Whose context |
> |---|---|---|
> | Orchestrator system prompt | [System-Prompt](system-prompt.md) | Top-level `cld` / `cdx` session |
> | **Agent system prompt — Layer 1 (base)** | **Golden-Prompt** (this doc) | Each spawned subagent |
> | Agent system prompt — Layer 2 (persona) | [Agent](agent.md) | Each spawned subagent |
> | Agent system prompt — Layer 3 (model overlay) | [Model-Standard](model-standard.md) | Each spawned subagent |
>
> Subagents do **not** inherit the orchestrator's system prompt (per
> `code.claude.com/docs/en/sub-agents`), so the agent base prompt is what
> supplies cross-cutting safety, confirmation, and operating-policy rules to
> spawned agents.

**Definition.** A markdown document containing the base behavioral layer for
composed **agent system prompts**. A golden-prompt is prepended to an agent
persona at install/sync time when the agent declares
`golden_prompt_extends: <name>`.

**Key constitutive feature.** Agent base prompt layer: golden-prompts encode
common safety, confirmation, content-isolation, and operating-policy guidance
that should apply to a family of agents without duplicating that text in every
agent file. The corresponding rules for the **orchestrator** session live in
the [system-prompt](system-prompt.md) override mechanism instead.

**Storage.** `.agents/golden-prompts/<name>.md` (project-local) or
`~/.agents/golden-prompts/<name>.md` (user-global).

**Loading.** Golden-prompts are not runtime tools and are not auto-selected by the
model. The Library composer reads them during agent install/sync and writes the fully
composed prompt to the harness-specific installed agent file.

**Composition role.** Golden-prompts are Layer 1 of the three-layer **agent
system prompt** model (the prompt the harness sees when an agent runs — not
the orchestrator's prompt):

```
Composed agent system prompt =

  Layer 1: Golden-Prompt (this primitive)
    └── Shared behavioral base for a family of agents.

  Layer 2: Agent Persona
    └── The agent's own purpose, tool grants, and domain expertise.

  Layer 3: Model-Standard (optional)
    └── Model-specific overlays such as verbosity or tool-use tuning.
```

Composition happens **once at install time** by the Library composer
(`scripts/compose-agent.py`). The harness reads the fully-composed result
as the agent's system prompt — there is no runtime composition.

**Catalog format.** Golden-prompts live under `library.golden_prompts` in `library.yaml`:

```yaml
library:
  golden_prompts:
    - name: cognovis-base
      description: >-
        Layer 1 of the three-layer agent composition model. Safety, confirmation
        gates, content isolation, source-language, session-close protocol.
      source: https://github.com/cognovis/library-core/blob/main/golden-prompts/cognovis-base.md
```

**When to choose it.** Create a golden-prompt when:

- the same base behavioral policy must apply to multiple agents;
- the behavior belongs below every persona, not inside one specialized agent;
- model-specific differences are handled separately by model-standards.

**Counter-examples.**

- Do NOT put one agent's domain expertise in a golden-prompt; that belongs in the
  agent persona.
- Do NOT put model-specific tuning in a golden-prompt; that belongs in a
  model-standard.
- Do NOT use a golden-prompt as an invocable workflow; that is a skill or command.
