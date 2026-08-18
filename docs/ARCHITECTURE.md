# Architecture

This repo (`cognovis/library`) is a fork of [`disler/the-library`](https://github.com/disler/the-library) extended for Cognovis multi-harness use.

## Goal

One **platform and aggregate catalog index** (this repo) that resolves content
from several catalog sources and distributes skills, agents, prompts, hooks,
workflows, and project-native bridge artifacts across the supported harnesses
(Claude Code, OpenAI Codex CLI, and Pi) via a
**per-repo desired-state pull** model — not deploy-all.

## Library Workspace control plane

[ADR-0010](adr/workspace-desired-state-reconciliation.md) adds a desired-state
control plane above artifact installation. A **Library Workspace** is a
metadata-only catalog primitive that names typed requested roots for one Git
repository. It has no harness file of its own.

The lockfile owns the deep behavior:

```text
requested roots (direct artifact primitives + Workspaces)
                         |
                         | fresh complete resolution
                         v
                 materialized receipts
                         |
                         | explicit --prune --apply
                         v
         clean + verified + ownerless receipts only
```

Ownership is universal rather than Workspace-private. A shared receipt survives
while any requested root reaches it. Persisted owner edges explain a plan but
never replace fresh resolution. ADR-0012 removes the global primitive lock and
global Workspace lobby. The only machine-global state is its explicit bootstrap
allowlist: the `library`, `cld`, and `cdx` executables, global instruction
entrypoints, launcher runtime configuration, and the OpenBrain MCP singleton.
Project-owned receipt paths are serialized relative to the project lock root, so
a committed desired state survives worktree cleanup and repository relocation.
Global targets and Layer-B cache provenance remain absolute.

Workspace selection is many-to-many. One project may register several
orthogonal Workspaces, and one Workspace may be reused by many projects. A
v1 Workspace contains only same-catalog artifact roots; nested Workspace and
cross-catalog manifest roots are deferred. Cross-catalog composition registers
several Workspaces directly in one scope. Composition is an unordered set union
with no exclusion or override semantics. Strict functional coupling remains in
primitive `requires:` metadata. The Library does not add a Package or generic
bundle root between those two relationships.

The evidence-backed initial cuts and repository mapping are recorded in
[ADR-0010](adr/workspace-desired-state-reconciliation.md) and
[ADR-0011](adr/heterogeneous-marketplace-workspaces.md). In
particular, `library/meta` directly composes `library-authoring` and
`python-cli`; `cognovis-pi` consumes `library-authoring` while keeping Pi
extensions, profiles, and Just modules as separately selected Pi-owned
primitives. `fhir-ig-authoring` remains conditional on proving that at least
two independent roots remain after its entrypoint `requires:` audit.

Installation scope is separate from model-context scope. Workspace members keep
their Skill, Standard, Agent, Hook, Workflow, or Script load semantics, so an
installed lobby is not automatically resident in every prompt.

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
2. **Catalog** — a reviewed catalog change registers the source pointer and
   metadata in `library.yaml`. Catalog is pointers-only, not content.
3. **Distribute** — `library <primitive> use <name>` pulls the referenced item
   into the current Git repository as a vendored copy by default. For skills,
   that is `.agents/skills/` with a Claude bridge under `.claude/skills/`.
   Layer-B cache paths are per-machine resolver inputs, not committed runtime
   targets. Each repo pulls only what it needs.
4. **Use** — invoked normally once in place. Same as any native skill/agent.

A Workspace adds an optional desired-state route across stages 2 and 3:

- a marketplace publishes a small versioned Workspace manifest containing typed
  roots;
- `library workspace list`, `show`, and `use <catalog>:<name> --dry-run` provide
  discovery and a no-write first-contact plan;
- `library workspace use <catalog>:<name>` registers that root and applies
  additions;
- `library workspace status` and `explain` expose the freshly resolved ownership
  plan; and
- `library workspace sync --prune --apply` can retire only exact, verified,
  ownerless Library receipts. Ordinary `library sync` remains non-pruning.

Migrated direct roots can be demoted in bulk to Workspace ownership through a
lock-only plan-and-apply operation. It never deletes files; physical deletion
remains a separate prune decision.

The Workspace route replaces hand-maintained bootstrap capability lists,
legacy consumer primitive refresh lists, and new `project_tooling`
distribution entries. The irreducible bootstrap still installs the Library
engine and conversational entrypoint because they must exist before a Workspace
can be resolved. Platform forge Skills move to `library-authoring` rather than
remaining ambient bootstrap or lobby content. During migration the older
managers remain protected owners; their files are never adopted or pruned
implicitly.

The return path is normal source development in the owning catalog repository,
followed by review and publication. Deployed files are not pushed back as source.
`library sync` refreshes installed roots conservatively.

### Project-self-contained installs

Consumer projects should commit the project-local `.agents/` tree:

```text
<consumer-project>/
├── .library.lock             # requested roots + receipts after lockfile v2
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

## Launchers (cld/cdx/cra)

The launchers are owned by the `harness-cli` repository (distribution
`cognovis-harness-cli`, installed via `uv tool`). The legacy launcher sources in
this repository (`scripts/bin/cld`, `scripts/bin/cdx`, `bin/` compatibility
copies) were retired under CL-iv72. The behavioral contract below is preserved
by `harness-cli` and documented here as the integration boundary.

**Deployment:** `uv tool install` owns the packaged Library control plane.
`install.sh --fresh` is the machine bootstrap entrypoint: it prepares portable
platform and core catalog checkouts in the XDG Library data directory, registers
them for pinned Workspace resolution, delegates executable installation to
`uv tool install`, and reconciles the enumerated bootstrap. It creates no global
Library Skill projection. Plain `install.sh` remains the checkout-local upgrade
route.

**Bead modes:** Both launchers are single-bead launchers with three exclusive bead-dispatch flags:

| Flag | Description |
|------|-------------|
| `-b`/`--bead <id>` | Full bead orchestrator run with session-close |
| `-bq`/`--bead-quick <id>` | Quick-fix run (lighter orchestration) |
| `-br`/`--bead-review <id>` | Thin adapter to the current Bead review path. Bead state is read with public `bd` commands and reviewer execution uses ACPX. Claude defaults to Opus and accepts an explicit `--model`; Codex accepts `-m`/`--model`. Bypass flags are rejected. Mutually exclusive with `-b`/`-bq`. |

The review client is the trust boundary: bead-authored fields are serialized into a
bounded, provenance-tagged untrusted-data envelope; provider output must contain one
terminal typed result record with a supported verdict. No metadata write occurs on a
malformed response or failed provider turn. The MCP transport is pinned to the local
loopback endpoint.

**Coordinator callbacks** (`--coordinator-workspace workspace:<n> --coordinator-surface surface:<n>`): Both flags must be supplied together for `-b`/`-bq` runs. When present, a best-effort `cmux trigger-flash` signaling contract is injected into the first prompt so a coordinator pane is notified on blocking questions, terminal state, and the Phase 16 session-close event. Callback identity travels only via CLI parameters, never environment variables. Partial or malformed pairs fail with exit 2 before any harness launch. `scripts/coordinator_callback.py` (CL-t32e) provides a standalone, tested exactly-once delivery executor for this contract (atomic lock + state file per `(run_id, event)`); wiring the launchers to this executor is scoped to CL-gzvu (`cld`) and CL-eqiq (`cdx`) in `harness-cli`, which will replace the best-effort prompt-injected contract described above with calls to this executor.

**Route profiles** (`--route-profile NAME`): Both launchers accept an optional `--route-profile` flag
that selects a named profile from `orchestrator-config.yml`. The selected name is passed explicitly as a
`route_profile` parameter to the deterministic `phase0-claim.py` preflight and threaded through the bead-orchestrator prompt text so
downstream workflow entries resolve the matching `execution_plan` (slots, adapter, model, reasoning_effort,
timeout). Built-in profiles: `cld-default`, `cdx-default`, `cdx-composer`. When omitted, `cld` passes
`cld-default` and `cdx` passes `cdx-composer` as code-defined launcher defaults.

**Forced tiers** (`--force-tier TIER`): `cld -b` and `cld -bq` pass the optional administrative override
as the `force_tier` parameter to the deterministic `phase0-claim.py` preflight. Supported tiers are `quick`, `gsd`, `paul`,
and `mcp`; the legacy `phase0-claim.py` path is not used by these launchers. GSD and PAUL use the named
profile's full execution plan, while PAUL additionally enables architecture review and UAT. The typed
path rejects `solo` because the unified orchestrator has no active-context implementation path yet.
`--force-tier quick` is an administrative eligibility bypass and is not equivalent to bare `-bq`, which
requests strict quick and fails closed when the bead is ineligible.

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
| `cognovis/cognovis-pi` | Pi extensions, runtime profiles, and repository-local Just bridge modules | Private |
| `cognovis/library-public` (future) | Things to share externally | Public (later) |

Third-party content (e.g. disler's, Anthropic's official, Adrian/ThadeNorigar's) stays at source
and is referenced through the source registry — never mirrored into our content repos.

## Catalog sources and external marketplaces

A catalog source is a repository that publishes Library primitives or Workspace
manifests. Historical documents call this a *source-provider marketplace*. An
external harness marketplace is a different distribution mechanism and is not a
Library ownership scope.

External sources can be registered via `library add-marketplace <github-url>`.
Catalog entries can reference a registered source instead of a direct URL.
Already-known candidates:

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

## Pi relationship

Pi is now an active harness and catalog source, not a deferred alternative.
Portable Skills retain their own format where Pi supports them; Pi-specific
extensions, profiles, and Just modules are explicit project-native bridge
primitives from `cognovis/cognovis-pi`. They can be selected directly or through
a Workspace, while their runtime profile semantics remain distinct from Workspace
desired state. A Pi profile chooses how a Pi run executes; a Workspace chooses
which Library-owned capabilities are present. Bundled extensions that declare
`pi_package: true` are also registered in project-local `.pi/settings.json`, so
an ordinary `pi` session loads packages such as `solo-workbench`; Just remains a
separate launcher surface rather than the Pi package installer.

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

| Primitive | Claude Code | Codex CLI | Pi | Portability |
|-----------|-------------|-----------|-----|-------------|
| **Skill** | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | own skill loader | **Portable** — shared SKILL.md format (Open Agent Skills Standard); only install path differs |
| **Agent** | YAML frontmatter `.claude/agents/<name>.md` | TOML `.codex/agents/<name>.toml` (per-repo) | N/A | **Per-harness translation** — same concept, divergent formats; translation spec: bead `CL-11p` |
| **Command / Prompt** | `.claude/commands/<name>.md` (slash cmds) | Not supported in Codex — use skills instead | N/A | **Per-harness** — Claude Code has first-class slash commands; Codex custom prompt targets are not used by the Library (bead `CL-qzw`) |
| **Guardrail / Hook** | `.claude/settings.json` `hooks` section (scripts in `.claude/hooks/`) + 15 lifecycle events | 3 events only (SessionStart, SessionEnd, Stop) | different event model | **Harness-specific** — shared concept, incompatible event sets; not cross-portable without an adapter (bead `CL-xcm`) |
| **Standard** | Loaded by consuming skills/agents via `requires_standards` | `.agents/standards/<name>/` file convention | TBD | **Library-managed** — not an invocation primitive; installed as dependency content, never auto-injected |
| **MCP-Server** | supported configuration | supported configuration | project-native ownership | **Library-managed** — configuration is harness-specific. |
| **Plugin** | External harness bundle installed via `/install-plugin` | `codex plugin` + `.codex-plugin/plugin.json` | N/A | **Per-harness** — both harnesses support their own plugin formats; this is not a Library Package or requested-root type |
| **Marketplace** | `library add-marketplace <url>` in catalog | Same catalog | Same catalog | **Catalog-level** — harness-agnostic; the catalog is portable, installed artifacts may not be |
| **Workspace** | Library CLI metadata; members project individually | Same | Same | **Metadata-portable** — no harness artifact; resolved members inherit their own portability |

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
| [ADR-0005](adr/library-plane-vocabulary.md) | Library catalog plane vocabulary and Gas City PackV2 projection boundaries | Accepted |
| [ADR-0006](adr/workflow-primitive.md) | Workflow as a first-class Library primitive | Accepted |
| [ADR-0007](adr/library-tool-surface-mcp.md) | Library tool surface as a second species of MCP server | Proposed |
| [ADR-0008](adr/git-hook-chain-existing-composition.md) | Chain-safe composition for existing Git hooks | Accepted |
| [ADR-0009](adr/intentional-release-lifecycle.md) | Intentional Library release lifecycle | Accepted |
| [ADR-0010](adr/workspace-desired-state-reconciliation.md) | Universal Library ownership and Workspace desired-state reconciliation | Accepted; implementation tracked by CL-r7n6 |
| [ADR: library.yaml information model](adr/library-yaml-information-model.md) | Root section ownership, primitive catalog nesting, and source registry nesting | Accepted |

## Open beads

See `bd ready` and `bd show CL-36o` for the active epic + sub-beads.
