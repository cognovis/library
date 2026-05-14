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
| 1 | **Skills** | Capability | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` |
| 2 | **Agents** | Scale + parallelism | `.claude/agents/<name>.md` (YAML frontmatter) | `.codex/agents/<name>.toml` (TOML) — per-repo; `~/.codex/agents/<name>.toml` is global/personal |
| 3 | **Prompts** | Orchestration | `.claude/commands/<name>.md` (slash cmds) | TBD — research bead `CL-qzw` |
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
2. **Catalog** — `/library <primitive> add <github-url>` registers a pointer in
   `library.yaml`. Catalog is pointers-only, not content.
3. **Distribute** — `/library <primitive> use <name>` pulls the referenced item into
   the primitive's canonical location as a vendored copy by default. For skills,
   that is `.agents/skills/` project-local or `~/.agents/skills/` global, with a
   Claude bridge under `.claude/skills/` or `~/.claude/skills/`. Layer-B cache
   paths are per-machine resolver inputs, not committed runtime targets. Each
   repo pulls only what it needs.
4. **Use** — invoked normally once in place. Same as any native skill/agent.

Plus the return path: `/library <primitive> push <name>` sends local edits back upstream;
`library sync` pulls latest for all installed items.

### Project-self-contained installs

Consumer projects should commit the project-local `.agents/` tree:

```text
<consumer-project>/
├── .agents/
│   ├── skills/<name>/SKILL.md
│   ├── standards/<name>/<name>.md
│   ├── agents/
│   └── prompts/
├── .claude/skills/        # ignored bridge symlinks
└── .claude/worktrees/     # ignored worktree directories
```

Marketplace repos are the exception. In this `meta/` repo and the library-core
marketplaces, source content lives under top-level `skills/`, `standards/`,
`agents/`, and `prompts/`; `.agents/` remains an ignored install destination.

## Launchers (cld/cdx)

Per **ADR-0002 Decision 2**, the canonical source for all CLI launchers is `cognovis-library/bin/`:

| File | Description |
|------|-------------|
| `bin/cld` | Claude Code launcher — full-featured zsh wrapper (~500 lines) |
| `bin/cdx` | Codex CLI launcher — zsh wrapper, parallel to `cld` (bead `CL-tap`) |

**Deployment:** `bash scripts/install-bin.sh` creates symlinks from `~/.local/bin/{cld,cdx}` into `bin/`.
The installer is idempotent and uses `ln -sfn` so updates to this repo are immediately reflected.

`~/.local/bin/` must be in `$PATH`. The `~/.claude/scripts/` PATH entry has been removed from `~/.zshrc`
(only `CMUX_BUNDLED_CLI_PATH` pointing to `~/.claude/scripts/cmux-shim.sh` remains).
Note: the PATH change takes effect in **new shells only** — existing terminals that were launched before the edit still
carry the old `~/.claude/scripts/` entry in their inherited environment. Open a new shell to verify AK5.

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

The Library's catalog + on-demand `/library <primitive> use <name>` is a better
fit for that diversity. BMAD remains useful as a reference for skill/agent
authoring patterns.

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
| **Skill** | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | own skill loader | TBD | **Portable** — shared SKILL.md format (Open Agent Skills Standard); only install path differs |
| **Agent** | YAML frontmatter `.claude/agents/<name>.md` | TOML `.codex/agents/<name>.toml` (per-repo; `~/.codex/agents/<name>.toml` for global/personal) | N/A | TBD | **Per-harness translation** — same concept, divergent formats; translation spec: bead `CL-11p` |
| **Command / Prompt** | `.claude/commands/<name>.md` (slash cmds) | Not supported in Codex — use skills instead | N/A | TBD | **Per-harness** — Claude Code has first-class slash commands; Codex custom prompt targets are not used by the Library (bead `CL-qzw`) |
| **Guardrail / Hook** | `.claude/settings.json` `hooks` section (scripts in `.claude/hooks/`) + 15 lifecycle events | 3 events only (SessionStart, SessionEnd, Stop) | different event model | TBD | **Harness-specific** — shared concept, incompatible event sets; not cross-portable without an adapter (bead `CL-xcm`) |
| **Standard** | Loaded by consuming skills/agents via `requires_standards` | `.agents/standards/<name>/` file convention | TBD | TBD | **Library-managed** — not an invocation primitive; installed as dependency content, never auto-injected |
| **MCP-Server** | `mcpServers` in `.mcp.json` (or `--mcp-config`) | `mcp_servers` TOML in `~/.codex/config.toml` | N/A | TBD | **Library-managed** — per-harness provisioning; protocol is standard but config syntax is not portable |
| **Plugin** | Bundle installed via `/install-plugin` | `codex plugin` + `.codex-plugin/plugin.json` | N/A | TBD | **Per-harness** — both harnesses now support plugins; bundle formats and install commands differ |
| **Marketplace** | `library add-marketplace <url>` in catalog | Same catalog | Same catalog | Same catalog | **Catalog-level** — harness-agnostic; the catalog is portable, installed artifacts may not be |

**Reading the table:**
- *Portable* means the same artifact file works across all harnesses that support the primitive.
- *Per-harness translation* means the concept is supported everywhere but the file format must be converted.
- *Harness-specific* means the implementation is tied to one harness's event model or config syntax.
- *Library-managed* means the Library (not the model or user) provisions these as dependencies.

For full definitions, per-harness NORMATIVE/INFERRED claim labels, a full decision
tree, and worked examples from real codebase items, see [docs/PRIMITIVES.md](PRIMITIVES.md).

## Architecture Decision Records

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](adr/sussdorff-plugins-removal.md) | Replace sussdorff-plugins marketplace with per-project /library use | Superseded by ADR-0002 |
| [ADR-0002](adr/canonical-library-architecture.md) | Library-core repos as canonical source; harness dirs as deployment targets; marketplace removal | Accepted |
| [ADR-0003](adr/three-layer-cache-architecture.md) | Three-layer skill deployment: Source/Cache/Harness Symlink + marketplace-symmetric primitives | Accepted |
| [ADR-0004](adr/frontmatter-dependency-resolution.md) | Frontmatter-driven dependency resolution for library primitives | Accepted |

## Open beads

See `bd ready` and `bd show CL-36o` for the active epic + sub-beads.
