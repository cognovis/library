---
adr: "0004"
title: "Library architecture cleanup — frontmatter deps, harness-neutral source layout, remote-only sources, installable command"
status: accepted
date: 2026-05-12
bead: CL-bgo
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0002", "0003"]
---

# ADR-0004: Frontmatter-driven dependency resolution + harness-neutral source layout for library primitives

## Status

Accepted.

## Context

ADR-0002 established `cognovis/library-core` and `sussdorff/library-core`
as canonical source repos. ADR-0003 established the three-layer
deployment pipeline (Source → Cache → Harness-Symlink), marketplace-
symmetric primitives, lockfiles, and adapter pattern.

Neither answers the question:

> When I `/library use bead-orchestrator`, what else must install
> automatically — and where is the dependency declaration?

### The gap discovered today (2026-05-12)

After CL-ast removed the `sussdorff-plugins` marketplace, the
`beads-workflow` plugin's **10 agents** were copied to
`~/.claude/agents/beads-workflow/` as a bridge. Its **15 skills**
(`factory-check`, `plan`, `impl`, `epic-init`, `wave-orchestrator`,
`bead-metrics`, `compound`, `intake`, `refactor-note`, `retro`,
`review-conventions`, `wave-reviewer`, `workplan`, `bd-release-notes`,
`create`) were **not** migrated.

Result: the agents exist but their skill calls fail. From an arbitrary
project (e.g. `polaris`) the `/beads`, `/plan`, `/impl`,
`/wave-orchestrator`, `/factory-check` slash-commands are missing. The
orchestrator agent can still be spawned via the `Agent()` tool, but
its internal `Skill(...)` invocations have nothing to dispatch to.

This is a **phantom-install failure mode**: a primitive is installed
without its declared dependencies, and the failure surfaces only at
runtime, in a specific session, in a specific phase of an
orchestrator's lifecycle. It is invisible to `ls ~/.claude/agents`.

### Why this gap exists structurally

1. `library.yaml` already has a `requires:` field per entry, with
   typed references (`skill:name`, `agent:name`, `prompt:name`). The
   cookbook (`cookbook/use.md`, Step 4) documents recursive
   resolution. The infrastructure is there.

2. **Of the 108 entries in `library.yaml`, fewer than 5 have a
   non-empty `requires:`.** The mechanism is unused. Most entries
   were created via marketplace-plugin migration where dependencies
   were implicit in the plugin bundle.

3. ADR-0002 removed the bundle mechanism (plugin marketplaces). The
   bundle's implicit dep-coupling vanished with it. No replacement
   was specified.

4. ADR-0003's "Lifecycle example — the `beads` skill" walks through
   one isolated skill. It does not address transitive deps —
   intentionally, to keep ADR-0003 focused on physical deployment.

### What we need

A single contract that answers:

- **Where does a primitive declare its dependencies?**
- **What are the dependency types and reference syntax?**
- **How does `/library use` resolve them?**
- **How do we prevent drift between declaration and reality?**

## Decision

### Decision 1: Frontmatter `requires:` is the authoritative declaration

Every primitive carries `requires:` in its YAML frontmatter as the
**source-of-truth** for its dependencies.

```yaml
---
name: bead-orchestrator
description: Autonomous orchestrator for single-bead implementation...
model: opus
requires:
  - skill:factory-check
  - skill:plan
  - skill:impl
  - skill:compound
  - agent:review-agent
  - agent:verification-agent
  - agent:quick-fix
  - agent:changelog-updater
---

# Bead Orchestrator

...body...
```

Rationale: same pattern as `package.json`, `Cargo.toml`,
`pyproject.toml`. Metadata lives next to the artefact, not in a
central registry that must be kept in sync manually.

### Decision 2: Typed reference syntax

A dependency reference is a string `<type>:<name>`:

| Type | Meaning |
|------|---------|
| `skill:<name>` | Required Skill (must be installed and discoverable to the harness) |
| `agent:<name>` | Required subagent (spawned via `Agent(subagent_type=...)`) |
| `prompt:<name>` | Required slash-command (e.g. `/beads`, `/library use`) |
| `hook:<name>` | Required guardrail/hook (settings.json registration mandatory) |
| `mcp:<name>` | Required MCP server (config snippet must be present in harness) |

The type prefix is **mandatory**. Bare names are not allowed. The
resolver uses the type to look up the entry in the correct
`library.yaml` section (`library.skills`, `library.agents`,
`library.prompts`, `library.guardrails`, `library.mcp_servers`, and the
other `library.*` primitive arrays).

### Decision 3: `library.yaml` entries mirror frontmatter; validator catches drift

`library.yaml` may carry a `requires:` array at the entry level for
indexing and offline lookup. **It must equal** the array in the
file's frontmatter at install time.

`validate-library.py` performs the drift check:

1. For each entry with `source:` or `from_marketplace:` + `path:`,
   resolve the artefact URL.
2. Fetch the file (via the ADR-0003 cache, if available; otherwise
   live).
3. Parse YAML frontmatter.
4. Compare `requires:` arrays as sorted sets.
5. Mismatch → validator error with diff output.

This catches the failure mode where an agent silently grows a new
skill dependency in its body but the registry isn't updated.

### Decision 4: No `bundle` primitive type

There is no `library.bundles:` section. A "bundle" — a curated
collection of primitives that install together — is **a top-level
primitive whose `requires:` array enumerates the members**.

Example: the `beads-workflow` collection is the `bead-orchestrator`
agent itself, which `requires:` its 15 skills + 5 sibling agents.
`/library use bead-orchestrator` from a clean polaris installs the
full closure.

If we ever need a non-agent, non-skill "bundle as such," we add a
sentinel entry (e.g. an empty `agent:beads-workflow-meta`) whose only
purpose is to carry the `requires:` array. The graph remains the
single source of truth; bundles are syntactic sugar over the graph.

Rationale: every additional primitive type increases schema surface,
validator complexity, and resolver branching. The graph already
expresses bundles without a new type. See "Alternatives Considered"
for the rejected `library.bundles:` proposal.

### Decision 5: `/library use` resolves transitively, idempotently

Updated `/library use <name>` semantics:

1. **Look up entry** in `library.yaml` (existing Step 2 from
   `cookbook/use.md`).
2. **Fetch the artefact** to the ADR-0003 cache.
3. **Parse frontmatter** and extract `requires:` (taking precedence
   over the library.yaml mirror in case of disagreement — frontmatter
   is authoritative).
4. **Resolve each dependency recursively** before continuing with
   the parent install. Cycle detection: maintain a visited set; if a
   cycle is detected, fail with a clear error pointing at the cycle.
5. **Install the parent** (per ADR-0003 mechanics: cache symlink to
   harness).
6. **Update the lockfile** (per ADR-0003 Decision 4) with the full
   transitive closure, not just the requested name.

Idempotency: each step checks "already installed and at the right
version per lockfile" and skips if so. Force re-install: explicit
flag `--reinstall`.

### Decision 6: Source repos use a harness-neutral top-level layout

Library-core source repos (`cognovis/library-core`, `sussdorff/library-core`,
any future first-party source-provider marketplace) **do not** use the
`.claude/` directory convention at the top level. That convention is a
**harness-deployment-target** path (the place a harness expects to find
content on a developer machine); it does not belong at the source-of-
truth level where content is authored.

Canonical source layout:

```
<library-core-repo>/
├── skills/                     # one subdir per Skill (SKILL.md inside)
│   ├── beads/SKILL.md
│   ├── factory-check/SKILL.md
│   └── ...
├── agents/                     # one file per Agent
│   ├── bead-orchestrator.md    # Claude-format agent (YAML+Markdown)
│   └── ...                     # Codex .toml agents may sit as siblings;
│                               # extension carries the harness contract.
├── prompts/                    # slash-commands (was: .claude/commands/)
│   └── library.md
├── hooks/                      # guardrail scripts + per-hook README/json
│   ├── block-destructive-bash.py
│   └── ...
├── .claude/                    # OPTIONAL — only THIS repo's own harness config
│                               # (settings.json for working IN this repo
│                               # with Claude Code), never library content.
└── README.md / library.yaml / etc.
```

Rules:

1. **Skill files (`SKILL.md`)** are harness-neutral by design
   (agentskills.io standard). One file under `skills/<name>/` works
   for Claude Code and Codex CLI; deployment-time symlinks point both
   harnesses at the same bytes.
2. **Agent files** are harness-specific in format
   (Claude uses `.md` with YAML frontmatter; Codex uses `.toml`). They
   sit as siblings in `agents/` and the file extension identifies the
   target harness. A primitive that ships for both harnesses has
   `agents/<name>.md` and `agents/<name>.toml` side by side. The
   library.yaml entry references whichever extension is canonical for
   the marketplace's harness coverage.
3. **`.claude/` at the source level is reserved for the source repo's
   OWN harness config** — i.e. when you run Claude Code in the
   `cognovis-core` checkout to edit library content, `.claude/settings.json`
   may exist to configure that working session. It is not library
   content and is not surfaced through `library.yaml`. Same logic for
   `.codex/` if needed.
4. **Plugin-style nesting** (`plugins/<plugin-name>/{agents,skills,hooks}`)
   is removed. ADR-0002 ended the Claude Code plugin-marketplace
   mechanism; the previous nested layout has no remaining purpose. All
   content lives at the top-level harness-neutral roots.
5. **library.yaml `source:` URLs** point to the harness-neutral paths
   (e.g. `https://github.com/cognovis/library-core/blob/main/skills/factory-check/SKILL.md`,
   not `/.claude/skills/factory-check/...`). The resolver does not need
   the harness prefix because the path no longer carries one.
6. **default_dirs in `library.yaml`** keep their harness-suffixed
   keys (`project_claude`, `project_codex`, etc., per ADR-0003
   Decision 6) — those describe where to *deploy*, not where to read
   *from*.

Rationale: the marketplace is a source-of-truth for content that is
deployed to (potentially many) harnesses. Encoding one harness's
deployment-path convention into the source repo creates a false
asymmetry — it looks like Claude is privileged when in fact the
content is identical across harnesses for Skills (which dominate by
count). Renaming the source-side directories removes the asymmetry
and matches every established package-manager convention
(`src/` in npm/Cargo, `lib/` in Ruby, `pkg/` in Go): source-side
neutral, deployment-side environment-specific.

This decision is executed as part of the same migration that lands
this ADR (Phase 2 below), not deferred to a separate ADR. Every
existing `library.yaml` entry has its `source:` URL rewritten in the
same commit that does the directory moves.

### Decision 7: `source:` fields in `library.yaml` MUST be remote URLs

Every `source:` entry in `library.yaml` must resolve to a remote git
URL (typically `https://github.com/<org>/<repo>/blob/...`). Local
filesystem paths (e.g. `/Users/malte/code/library/cognovis-core/skills/...`)
are forbidden in committed `library.yaml`.

Rationale:

- `cognovis-core`, `sussdorff-core`, and `library/meta` are **development
  repos**. Their working trees are uncommitted-edit zones. A `/library
  use X` that reads the dev checkout pulls work-in-progress into the
  user's harness — invisible breakage waiting to happen.
- Remote-only sources mean every install passes the canonical pipeline:
  commit → push → CI (lint, schema, drift-check) → merge to `main` → only
  then visible to `/library use`.
- A failing CI on a marketplace repo blocks downstream installs by
  construction. There is no "I shipped a broken skill by accident
  because I edited it locally."
- This is the package-manager-CI norm (npm publish requires push to
  registry, Cargo crates require crates.io push, etc.). Local dev
  checkouts are not registries.

Enforcement:

- `validate-library.py` rejects any `source:` that does not start with
  `https://`.
- `/library use` rejects local-path sources at runtime with a clear
  error pointing the user at the source repo's CI status.
- The `cookbook/use.md` "Source Format" section is updated: only
  `https://` URLs are documented; local-fs example is removed.

Required infrastructure (executed as follow-up beads, not in this ADR):

- GitHub Actions workflow per source-provider marketplace repo
  (`cognovis-core`, `sussdorff-core`, `library-meta`):
  - `validate-library.py` schema check
  - Frontmatter parse + `requires:` recursion (cycle detection)
  - Drift check (library.yaml mirror vs. frontmatter, Decision 3)
  - SKILL.md format lint (agentskills.io conformance)
- Branch protection on `main`: PR + green CI required.

### Decision 8: The library command is installable software, bootstrapped from `meta`

The library is a **command-line tool with harness adapters**, not a
Claude Code skill that happens to also work in other places.

The canonical home of the library command is the `meta` repo
(this repository). It carries:

- `bin/library` — the executable CLI (zsh, mirrors the `bin/cld`,
  `bin/cdx` pattern from ADR-0002 Decision 2).
- `SKILL.md` — Claude Code surface (slash-command bridge that shells
  to `bin/library`).
- Codex / OpenCode / Pi surfaces analogously, each shelling to
  `bin/library`.
- `install.sh` — bootstrap installer.

`install.sh` semantics:

1. Detect XDG paths (`~/.local/bin/`, `~/.local/share/library/`,
   `~/.config/library/`); create if missing.
2. `ln -sfn $(realpath meta)/bin/library ~/.local/bin/library`
   (idempotent symlink, same pattern as `scripts/install-bin.sh`
   for cld/cdx).
3. For each detected harness (`~/.claude/`, `~/.codex/`,
   `~/.opencode/`, `~/.pi/` — present-iff-directory-exists): create
   a slash-command/skill entry that shells to `~/.local/bin/library`.
   Concretely: `~/.claude/skills/library` → `meta/SKILL.md` (symlink);
   Codex analogous. Platform-owned primitive forges are seeded the same
   way: `skill-forge`, `agent-forge`, `standard-forge`, `script-forge`,
   and `hook-forge` point at `meta/skills/<name>/`.
4. After step 3, `library` works from any shell, and `/library`
   works from any present harness.
5. **Self-hosted update path**: once installed, the library updates
   itself via `library update library` (which re-runs `install.sh`
   from the latest remote `meta` HEAD). The bootstrap is one-shot;
   subsequent updates are through the library itself.

Recovery semantics — if `~/.claude/` or `~/.codex/` is deleted:

1. The library command at `~/.local/bin/library` continues to work
   (it lives outside the harness dirs).
2. `library install --reattach` re-creates the slash-command entries
   for any current harness dirs.
3. If `~/.local/bin/library` itself was lost, the user goes back to
   the meta checkout (`cd ~/code/library/meta && bash install.sh`)
   and re-bootstraps.

Why this matters:

- Today the library is reached through `~/.claude/skills/library →
  /Users/malte/code/cognovis-library` (broken symlink per the
  2026-05-12 audit). The library's reachability depends on a
  particular harness's working state. Decoupling fixes this.
- A marketplace cannot have its installer depend on the same harness
  it installs into. That circular dependency falls apart the first
  time a harness gets wiped.
- "It's a command, not a skill" is the same logic that put `cld` and
  `cdx` in `cognovis-library/bin/` per ADR-0002 — the same logic
  applies one level up to the library itself.

### Decision 9: Backwards compatibility — empty `requires:` is legal

Existing entries without `requires:` continue to work. Frontmatter
without `requires:` means "no declared dependencies." The validator
warns (not errors) for entries that obviously should have
dependencies (e.g. an agent file whose body contains
`Agent(subagent_type=...)` calls but declares no `agent:`
dependencies). Warning, not error, because the heuristic is
imperfect — the user decides when to accept the suggestion.

## Alternatives Considered

### Option A: `library.yaml` as sole source-of-truth

Reject reason: drift risk. The agent file's body is the actual code
that gets executed; if its dependencies aren't expressed where the
agent is read and edited, the registry inevitably drifts. Anybody
who adds a new `Skill(...)` call in the agent body must remember to
update `library.yaml` — a manual sync step that does not survive
contact with reality.

### Option B: Parse agent/skill body for `Skill(...)` and `Agent(...)` calls

Reject reason: brittle. Skill names can be constructed dynamically
(`Skill(skill_name)` where `skill_name` is a variable),
slash-commands can be referenced in prose (`"Use /factory-check
to..."`), and hook references rarely appear in body text at all. The
parser would need to be a partial Python/Markdown interpreter to
distinguish "uses this skill" from "mentions this skill in
documentation."

A linter pass that **suggests** missing `requires:` based on body
scanning is acceptable as a developer convenience (mentioned in
Decision 6 warning). It is not the authoritative source.

### Option C: Introduce a `library.bundles:` primitive

Schema:

```yaml
library:
  bundles:
    - name: beads-workflow
      description: Full bead implementation workflow
      members:
        - "agent:bead-orchestrator"
        - "agent:wave-orchestrator"
        - ...
```

Reject reason: redundancy. A bundle is a graph node with members.
The existing `requires:` field expresses exactly that. Introducing
`library.bundles:` doubles the schema, doubles the validator, and
forces resolver branching ("is this a bundle or a primitive?") for
zero new expressive power.

The use case "I want to express a grouping that is not itself an
installable primitive" is handled by Decision 4's sentinel-entry
escape hatch.

### Option D: Per-primitive `installs:` field declaring what gets pulled along

Inverse direction: instead of `bead-orchestrator` declaring it
`requires:` skill `factory-check`, the `factory-check` skill could
declare it `installs_with: [agent:bead-orchestrator]`.

Reject reason: wrong directionality. A skill should not know about
every agent that uses it. The dependency direction is "consumer
declares producer," matching every established package-manager
convention.

## Migration Sequence

### Phase 0: ADR-0004 accepted

This document. Bead CL-bgo. Status set to `accepted` once the
acceptance criteria are met.

### Phase 1: Harness-neutral source layout migration + library bootstrap

Executed as part of accepting this ADR (Decisions 6 + 7 + 8):

1. **`cognovis/library-core` restructure** (Decision 6):
   - `git mv .claude/{skills,agents,commands,hooks} <top-level>/`
     with `commands → prompts`.
   - `git mv .agents/standards standards/` (new 5th top-level slot).
   - `git rm -r .agents/skills/` (broken-symlink Codex farm; obsolete
     under ADR-0003 cache-layer model).
   - Remove `plugins/{beads-workflow,architecture-trinity}/` subtrees
     (previous plugin layout; content folded into top-level
     `skills/agents/hooks/`).
   - `.claude/settings.json` (and `.codex/`) retained as THIS repo's
     own harness config; not surfaced via library.yaml.
2. **`sussdorff/library-core` restructure**: same as cognovis-core.
3. **Schema extension** (`docs/schema/library.schema.json`):
   `typed_dependency.pattern` extended from
   `^(skill|agent|prompt):.+$` to `^(skill|agent|prompt|hook|mcp):.+$`
   per Decision 2.
4. **`library.yaml` URL rewrite** (Decision 7):
   - `/.claude/skills/X/SKILL.md` → `/skills/X/SKILL.md`
   - `/.claude/agents/X.md` → `/agents/X.md`
   - `/.claude/commands/X.md` → `/prompts/X.md`
   - `/.claude/hooks/X` → `/hooks/X`
   - `/.agents/standards/X.md` → `/standards/X.md`
   - validate-library.py passes.
5. **Library bootstrap installer** (Decision 8): `install.sh` at the
   `meta` repo root, idempotent symlinks, harness-detection, future
   slot for `bin/library` CLI.
6. **15 beads-workflow skills registered** in `library.yaml`
   (bd-release-notes, bead-metrics, compound, create, epic-init,
   factory-check, impl, intake, plan, refactor-note, retro,
   review-conventions, wave-dispatch, wave-reviewer, workplan); their
   frontmatter carries `requires:` (Decision 1).

### Phase 2: Validator + cookbook update

- Extend `validate-library.py` with the drift check from Decision 3.
- Update `cookbook/use.md` Step 4 to read frontmatter as authoritative,
  with the library.yaml mirror as fallback for offline lookup.
- Add Step 4a (cycle detection per Decision 5).
- Add Step 4b (lockfile transitive-closure update per Decision 5).

### Phase 3: Beads-workflow as proof case

Migrate the 25 `beads-workflow` primitives (10 agents + 15 skills)
from `~/code/library/cognovis-core/plugins/beads-workflow/` to
`~/code/library/cognovis-core/.claude/{agents,skills}/`. For each:

- Read the file body.
- Infer dependencies from `Skill(...)` calls and
  `Agent(subagent_type=...)` spawns.
- Write the `requires:` array in the file's frontmatter.
- Register in `library.yaml` with mirrored `requires:`.

Then in a clean polaris checkout:

```bash
cd ~/code/polaris
claude "/library use bead-orchestrator"
```

…must install the agent **and** its full closure (15 skills + 5
sibling agents) with zero further commands. Acceptance test for the
migration.

### Phase 4: Backfill remaining entries (opportunistic, P3)

The remaining ~80 library.yaml entries get `requires:` populated as
they are touched, edited, or installed. No big-bang migration. The
validator warning from Decision 6 surfaces missing declarations as
they become relevant.

## Empirical state

| Fact | Value | Source |
|------|-------|--------|
| Total `library.yaml` entries | 108 | `library.yaml` |
| Entries with non-empty `requires:` | < 5 | grep `requires:` |
| `beads-workflow` agents currently in `~/.claude/agents/` | 10 | `ls ~/.claude/agents/beads-workflow/` |
| `beads-workflow` skills currently in `~/.claude/skills/` | 0 | `ls ~/.claude/skills/` |
| `beads-workflow` skills in previous plugin layout | 15 | `~/code/library/cognovis-core/plugins/beads-workflow/skills/` |
| Cookbook step for recursive install | exists, unused | `cookbook/use.md` Step 4 |

The infrastructure for recursive install **predates this ADR**. The
ADR formalizes the contract that makes it actually work.

## Consequences

### Positive

- Single-command install for any primitive: `/library use X` brings
  the closure.
- Drift between declaration and reality is impossible to commit
  silently — validator catches it.
- New collaborators install `bead-orchestrator` and get a working
  bead workflow without reading 8 docs.
- Bundles emerge from the graph; no extra schema.

### Negative

- Every existing primitive that has real dependencies must be
  audited and have `requires:` populated. Manual one-time cost
  (~100 entries, ~½ day).
- Validator now fetches files at validation time. Slower than pure
  static check. Mitigation: use the ADR-0003 cache; only fetch on
  cache miss.

### Neutral

- The `library.yaml` `requires:` mirror is now technically redundant
  with frontmatter, but kept for offline lookup and validator
  performance. The drift check ensures it stays accurate.

## Rollback Plan

If frontmatter-driven resolution proves untenable:

1. Treat `library.yaml` `requires:` as authoritative (Option A).
2. Disable the validator drift check.
3. Revert `cookbook/use.md` Step 4 to read library.yaml only.

The ADR-0003 deployment mechanics are unaffected — only the
dependency-resolution semantics revert. Existing installs continue
to work because frontmatter is **additional** metadata, not
replacing anything that the harness depends on.

## Open Questions

- **Version constraints in `requires:`?** Today: bare names only.
  Future: `skill:factory-check@>=2.0` syntax (NPM-style) if version
  conflicts ever become an issue. Deferred — current empirical state
  is single global version per primitive, no conflict potential.

- **Mobile-only deps** (`coding_strategy: cli` vs `mobile_strategy:
  mcp` from MCP server entries) — does a coding harness install
  `mcp:open-brain` if a skill `requires:` it? Today: assumes harness
  + dep type are compatible; resolver skips with a note if not.
  Refinement deferred to a follow-up if it becomes a real issue.

- **Optional dependencies** (`requires_optional:` or `suggests:` à
  la Debian)? Deferred — empirical use-case not present yet.

## References

- ADR-0002 (CL-7na): canonical-library-architecture.md — source of
  truth + deployment target split.
- ADR-0003 (CL-lti): three-layer-cache-architecture.md — physical
  deployment pipeline.
- Decision bead: CL-bgo
- Existing infrastructure: `cookbook/use.md` Step 4 (recursive
  install workflow) and `library.yaml` `requires:` field.
