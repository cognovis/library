# Agent Base (Agent Base Prompt)

> Primitive reference extracted from the agent composition model in [PRIMITIVES.md](../PRIMITIVES.md).

> **What this primitive is — and isn't.** An agent-base is the shared
> **agent-level** base layer that the Library prepends to an agent persona at
> install time. It is **not** the orchestrator's system prompt (the prompt
> Claude Code / Codex itself loads at session start). The two layers live in
> different contexts and are configured by different mechanisms:
>
> | Layer | Primitive | Whose context |
> |---|---|---|
> | Orchestrator system prompt | [System-Prompt](system-prompt.md) | Top-level `cld` / `cdx` session |
> | **Agent system prompt — Layer 1 (base)** | **Agent Base** (this doc) | Each spawned subagent |
> | Agent system prompt — Layer 2 (persona) | [Agent](agent.md) | Each spawned subagent |
> | Agent system prompt — Layer 3 (model overlay) | [Model-Standard](model-standard.md) | Each spawned subagent |
>
> Subagents do **not** inherit the orchestrator's system prompt (per
> `code.claude.com/docs/en/sub-agents`), so the agent base prompt is what
> supplies cross-cutting safety, confirmation, and operating-policy rules to
> spawned agents.

**Definition.** A markdown document containing the base behavioral layer for
composed **agent system prompts**. An agent-base is prepended to an agent
persona at install/sync time when the agent declares
`agent_base_extends: <name>`.

**Key constitutive feature.** Agent base prompt layer: agent-bases encode
common safety, confirmation, content-isolation, and operating-policy guidance
that should apply to a family of agents without duplicating that text in every
agent file. The corresponding rules for the **orchestrator** session live in
the [system-prompt](system-prompt.md) override mechanism instead.

**Storage.** `.agents/agent-bases/<name>.md` (project-local) or
`~/.agents/agent-bases/<name>.md` (user-global).

**Loading.** Agent-bases are not runtime tools and are not auto-selected by the
model. The Library composer reads them during agent install/sync and writes the
fully composed prompt to the harness-specific installed agent file.

**Composition role.** Agent-bases are Layer 1 of the three-layer **agent
system prompt** model (the prompt the harness sees when an agent runs — not
the orchestrator's prompt):

```
Composed agent system prompt =

  Layer 1: Agent Base (this primitive)
    └── Shared behavioral base for a family of agents.

  Layer 2: Agent Persona
    └── The agent's own purpose, tool grants, and domain expertise.

  Layer 3: Model-Standard (optional)
    └── Model-specific overlays such as verbosity or tool-use tuning.
```

Composition happens **once at install time** by the Library composer
(`scripts/compose-agent.py`). The harness reads the fully-composed result
as the agent's system prompt — there is no runtime composition.

**Catalog format.** Agent-bases live under `library.agent_bases` in `library.yaml`:

```yaml
library:
  agent_bases:
    - name: cognovis-base
      description: >-
        Deprecated logical Layer 1 alias. Composer resolves this name to the
        per-harness Claude or Codex agent base when those files are installed.
      source: https://github.com/cognovis/library-core/blob/main/agent-bases/cognovis-base.md
      requires:
        - agent-base:claude-agent-base
        - agent-base:codex-agent-base
    - name: claude-agent-base
      description: Claude Code Layer 1 agent base.
      source: https://github.com/cognovis/library-core/blob/main/agent-bases/claude-agent-base.md
    - name: codex-agent-base
      description: Codex Layer 1 agent base.
      source: https://github.com/cognovis/library-core/blob/main/agent-bases/codex-agent-base.md
```

The catalog key and install target are `agent_bases` / `agent-base`. Source
repositories should store these files under `agent-bases/`; the composer keeps a
one-release runtime fallback for already-installed `golden-prompts/` directories.

**When to choose it.** Create an agent-base when:

- the same base behavioral policy must apply to multiple agents;
- the behavior belongs below every persona, not inside one specialized agent;
- model-specific differences are handled separately by model-standards.

**Counter-examples.**

- Do NOT put one agent's domain expertise in an agent-base; that belongs in the
  agent persona.
- Do NOT put model-specific tuning in an agent-base; that belongs in a
  model-standard.
- Do NOT use an agent-base as an invocable workflow; that is a skill or command.
