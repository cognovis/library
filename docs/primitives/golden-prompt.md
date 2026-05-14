# Golden-Prompt

> Primitive reference extracted from the agent composition model in [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A markdown document containing the base behavioral layer for composed
agent prompts. A golden-prompt is prepended to an agent persona at install/sync time
when the agent declares `golden_prompt_extends: <name>`.

**Key constitutive feature.** Base prompt layer: golden-prompts encode common safety,
confirmation, content-isolation, and operating-policy guidance that should apply to a
family of agents without duplicating that text in every agent file.

**Storage.** `.agents/golden-prompts/<name>.md` (project-local) or
`~/.agents/golden-prompts/<name>.md` (user-global).

**Loading.** Golden-prompts are not runtime tools and are not auto-selected by the
model. The Library composer reads them during agent install/sync and writes the fully
composed prompt to the harness-specific installed agent file.

**Composition role.** Golden-prompts are Layer 1 in the three-layer agent prompt model:

```
Layer 1: Golden-Prompt
  └── Shared behavioral base for a family of agents.

Layer 2: Agent Persona
  └── The agent's own purpose, tool grants, and domain expertise.

Layer 3: Model-Standard (optional)
  └── Model-specific overlays such as verbosity or tool-use tuning.
```

**Catalog format.** Golden-prompts live under `golden_prompts:` in `library.yaml`:

```yaml
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
