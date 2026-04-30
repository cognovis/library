# Architecture

This repo (`cognovis/library`) is a fork of [`disler/the-library`](https://github.com/disler/the-library) extended for Cognovis multi-harness use.

## Goal

One **catalog** (this repo) that distributes skills/agents/prompts/hooks across
**multiple harnesses** (Claude Code, OpenAI Codex CLI, future: Pi) via a
**per-repo on-demand pull** model — not deploy-all.

## The 4-layer Agentic Stack

Each layer builds on the one below (terminology from disler / IndyDevDan):

| # | Layer | Purpose | Claude Code path | Codex path |
|---|-------|---------|------------------|------------|
| 1 | **Skills** | Capability | `.claude/skills/<n>/SKILL.md` | `.agents/skills/<n>/SKILL.md` |
| 2 | **Agents** | Scale + parallelism | `.claude/agents/<n>.md` (YAML frontmatter) | `~/.codex/agents/<n>.toml` (TOML) |
| 3 | **Prompts** | Orchestration | `.claude/commands/<n>.md` (slash cmds) | TBD — research bead `CL-qzw` |
| 4 | **Justfile** | Terminal access (non-interactive) | `claude --dangerously-skip-permissions ...` | `codex exec ...` |

**Layer 1 (Skills)** is portable — both tools implement the open agent skills standard,
SKILL.md format is identical. Only install paths differ.

**Layer 2 (Agents)** is the hardest — formats and field sets diverge. Translation spec
is bead `CL-11p`.

**Layer 3 (Prompts)** is unverified for Codex — bead `CL-qzw` researches it.

**Layer 4 (Justfile)** is tool-agnostic shell — only the wrapped CLI invocation
differs. The `cdx` wrapper (bead `CL-tap`) parallels `cld`.

## The 4-stage operational workflow

1. **Build** — skills/agents live in their natural value-generating repo (no central
   monorepo enforced).
2. **Catalog** — `library add <github-url>` registers a pointer in `library.yaml`. Catalog is
   pointers-only, not content.
3. **Distribute** — `library use <name>` pulls the referenced item into the current
   repo's `.claude/skills/` or `.agents/skills/` (or `~/.claude/skills/` if "global").
   Each repo pulls only what it needs.
4. **Use** — invoked normally once in place. Same as any native skill/agent.

Plus the return path: `library push <name>` sends local edits back upstream;
`library sync` pulls latest for all installed items.

## Repo split

| Repo | Purpose | Visibility |
|------|---------|-----------|
| `cognovis/library` (this) | Catalog. `/library` skill + `library.yaml` + `justfile`. Multi-harness extensions on top of disler/the-library. | Private |
| `sussdorff/library-core` | Malte's personal agentic content (created in `CL-1rr`) | Private |
| `cognovis/library-core` | Cognovis team-shared agentic content (created in `CL-1rr`) | Private |
| `cognovis/library-public` (future) | Things to share externally | Public (later) |

Third-party content (e.g. disler's, Anthropic's official, Adrian/ThadeNorigar's) stays at source
and is referenced via the **marketplaces** category — never mirrored into our content repos.

## Marketplaces

A marketplace is just a GitHub org or repo that publishes one or more skills/agents.
Registered via `library add-marketplace <github-url>`. Catalog entries can reference
a marketplace instead of a direct source. Already-known candidates:

- `disler` — many public skill repos
- `anthropics/claude-plugins-official` — Anthropic's curated directory
- `cognovis/samurai-skills` — already a marketplace, ours
- `ThadeNorigar` — private (contains K2SO and others)

Marketplace work is bead `CL-7ii`.

## Why per-repo on-demand vs. deploy-all

We evaluated [BMAD-METHOD v6](https://github.com/bmad-code-org/BMAD-METHOD) (which uses a
deploy-all `npx bmad-method install --tools claude-code` pattern) and decided against it.
Reason: our project portfolio is heterogeneous (medical, business, infra, content) and a
medical project should not get the LinkedIn skill installed by default.

The Library's catalog + on-demand `/library use` is a better fit for that diversity.
BMAD remains useful as a reference for skill/agent authoring patterns.

## Why not Pi?

[Pi agent](https://pi.dev) (Mario Zechner) is a different layer entirely — it replaces
Claude Code with a minimalist TypeScript runtime that exposes 25+ hook points. Our work
is on the orthogonal axis: portable artifacts ON TOP OF mainstream tools. Pi could become
a third installer target later (it implements its own skill loading); not in scope now.

## Decision log (this session)

- Catalog repo named `cognovis/library` (not `cognovis/agentic-library`) following
  IndyDevDan's `idd-library` convention
- Issue prefix `CL`, Dolt DB `beads_library`
- The Library's `--dangerously-skip-permissions` justfile pattern is intentional —
  it's the production workflow for non-interactive terminal access. Not an anti-pattern.
- Codex has first-class subagents (`default`/`worker`/`explorer` built-ins + custom TOML)
  — verified after my earlier wrong claim that "Codex has no subagent concept"
- Hooks are cross-cutting (not on the 4-layer stack) but still distributable; treated as
  a fourth artifact type in `library.yaml` (bead `CL-xcm`)
- `dev-tools/agents/codex-guide.md` was added to `claude-code-plugins` (v2026.04.32) for
  ground-truth Codex doc queries during this work

## Reference research

- [disler/the-library](https://github.com/disler/the-library) — what we forked
- [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) —
  canonical Claude Code hooks reference, required reading for `CL-xcm`
- [disler/pi-vs-claude-code](https://github.com/disler/pi-vs-claude-code) — Pi vs Claude Code
  comparison
- [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) — alternative
  pattern (deploy-all), useful for authoring conventions
- [Codex subagents docs](https://developers.openai.com/codex/subagents) — TOML format,
  built-ins, `spawn_agents_on_csv`, `max_threads`, `max_depth`
- [Codex skills docs](https://developers.openai.com/codex/skills) — confirms shared
  SKILL.md format with Claude Code (open agent skills standard)

## Primitive Definitions

### Decision rule for new artifacts

When adding a new capability to the stack, answer these four questions in order:

1. **Should the model auto-decide to use it?** → **Skill**
   The model picks it up from context without user intervention. Use when the
   capability is context-sensitive and reusable across projects.

2. **Should only the user invoke it?** → **Command**
   The user types `/name` explicitly. Use when the workflow requires deliberate
   intent, accepts user-supplied arguments, or would be dangerous if auto-triggered.

3. **Does it need its own context window or restricted tool permissions?** → **Agent**
   Each invocation gets a fresh context and its own tool grant. Use when the subtask
   needs isolation, parallelism, or a different permission set than the parent.

4. **Must it run regardless of what the model wants?** → **Guardrail / Hook**
   Runs outside the LLM loop at harness lifecycle events. The model cannot skip or
   suppress it. Use for enforcement, audit logging, and mandatory context injection.

If the answer is "none of the above", the capability is likely a bundling concern
(Plugin), a discovery surface (Marketplace), injected context (Standard or
Model-Standard), or an external protocol provider (MCP-Server) — see the full
decision tree in [docs/PRIMITIVES.md](PRIMITIVES.md).

### Harness portability matrix

Not all primitives travel equally well across harnesses. The table below shows which
primitive types are portable and where per-harness translation or adaptation is
required.

| Primitive | Claude Code | Codex CLI | Pi | OpenCode | Portability |
|-----------|-------------|-----------|-----|----------|-------------|
| **Skill** | `.claude/skills/<n>/SKILL.md` | `.agents/skills/<n>/SKILL.md` | own skill loader | TBD | **Portable** — shared SKILL.md format (Open Agent Skills Standard); only install path differs |
| **Agent** | YAML frontmatter `.claude/agents/<n>.md` | TOML `~/.codex/agents/<n>.toml` | N/A | TBD | **Per-harness translation** — same concept, divergent formats; translation spec: bead `CL-11p` |
| **Command / Prompt** | `.claude/commands/<n>.md` (slash cmds) | Deprecated in Codex — use skills instead | N/A | TBD | **Per-harness** — Claude Code has first-class slash commands; Codex deprecated custom prompts (bead `CL-qzw`) |
| **Guardrail / Hook** | `hooks.json` + 13 lifecycle events | 3 events only (SessionStart, SessionEnd, Stop) | different event model | TBD | **Harness-specific** — shared concept, incompatible event sets; not cross-portable without an adapter (bead `CL-xcm`) |
| **Standard** | SessionStart hook injection via `standards/index.yml` | Future: `.agents/standards/<n>.md` file convention | TBD | TBD | **Library-managed** — not an invocation primitive; injected as context by the harness |
| **MCP-Server** | Per-harness config (`mcp_servers` in settings.json) | Per-harness config | N/A | TBD | **Library-managed** — per-harness provisioning; protocol is standard but config is not portable |
| **Plugin** | Bundle installed via `/install-plugin` | N/A (no plugin mechanism yet) | N/A | TBD | **Claude Code only** today — atomically installs skills + commands + hooks |
| **Marketplace** | `library add-marketplace <url>` in catalog | Same catalog | Same catalog | Same catalog | **Catalog-level** — harness-agnostic; the catalog is portable, installed artifacts may not be |

**Reading the table:**
- *Portable* means the same artifact file works across all harnesses that support the primitive.
- *Per-harness translation* means the concept is supported everywhere but the file format must be converted.
- *Harness-specific* means the implementation is tied to one harness's event model or config syntax.
- *Library-managed* means the Library (not the model or user) provisions these as dependencies.

For full definitions, per-harness NORMATIVE/INFERRED claim labels, a full decision
tree, and worked examples from real codebase items, see [docs/PRIMITIVES.md](PRIMITIVES.md).

## Open beads

See `bd ready` and `bd show CL-36o` for the active epic + sub-beads.
