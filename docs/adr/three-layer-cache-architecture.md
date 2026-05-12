---
adr: "0003"
title: "Three-layer skill deployment: Source/Cache/Harness Symlink + marketplace-symmetric primitives"
status: accepted
date: 2026-05-12
accepted_date: 2026-05-13
bead: CL-lti
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0002"]
---

# ADR-0003: Three-layer skill deployment + marketplace-symmetric primitives

## Status

Accepted on 2026-05-13 after two Codex Adversarial Review rounds.

## Context

ADR-0002 established the source/deployment split:

- `cognovis/library-core` and `sussdorff/library-core` are the canonical
  source for own skills/agents/prompts/hooks/standards.
- `~/.claude/` and `~/.codex/` are deployment targets — no source, no
  hand-edits.
- Distribution happens via `/library use <name>`.

ADR-0002 did **not** specify how the deployment mechanism works. The
current implementation of `/library use` copies files from a library-core
checkout into the harness directories (`~/.claude/skills/<name>/`,
`~/.codex/skills/<name>/`, or per-project equivalents). This has three
unresolved problems:

### Problem 1: Duplicate content, drift surface

A `cp`-based deployment produces N physical copies of every SKILL.md
across the filesystem (one per harness directory plus the source).
Any divergence between them is silent and only surfaces when an agent
behaves inconsistently across harnesses. The codex-skills sync hook
(`sync-codex-skills`, CCP-y6n) was added specifically to plaster over
this drift — i.e. the architecture forces a reconciliation step that
should not exist.

### Problem 2: Naive symlink-into-source is destructive

The intuitive fix — symlink `~/.claude/skills/beads` directly to
`~/code/library/cognovis-core/.claude/skills/beads/` — makes every
in-progress edit live for every running agent session. The skill
development loop becomes "edit one byte, instantly affect any
running orchestrator." This is unacceptable.

The user feedback that crystallized this ADR: "Skill-Entwicklung
darf nicht automatisch Skill-Deployment bedeuten. Das wäre tödlich."

### Problem 3: Asymmetric handling of own vs. third-party sources

`library.yaml` today contains 108 entries with direct `source:
https://github.com/cognovis/library-core/...` URLs, plus 5
`marketplaces:` entries, plus 1 skill (`impeccable`) using the
`from_marketplace:` pattern. Own content is special-cased as
"direct source," while third-party content is "from marketplace."
This complicates the resolver, blocks symmetric tooling, and makes
it harder to register additional marketplaces (skills.sh,
anthropics/skills, …) on equal footing.

### Empirical state

| Fact | Value | Source |
|------|-------|--------|
| Entries with `source: github.com/cognovis/library-core/...` | 94 | `library.yaml` |
| Entries with `source: github.com/sussdorff/...` | 14 | `library.yaml` |
| Entries with `from_marketplace:` pattern | 1 (`impeccable`) | `library.yaml` |
| Registered `marketplaces:` entries | 5 | `library.yaml` |
| Skills physically deployed to `~/.codex/skills/` today | 71 | `ls ~/.codex/skills` |
| `~/.codex/skills/` vs `library.yaml.default_dirs.global_codex` (`~/.agents/skills/`) | divergent | filesystem vs config |
| Sync hook to keep claude and codex in step | `sync-codex-skills --user` | CCP-y6n |

The `~/.codex/skills/` vs `~/.agents/skills/` divergence is a symptom:
two paths exist because two deployment passes happen, instead of one
canonical structure that both harnesses observe.

## Decision

### Decision 1: Three-layer deployment architecture (skills only)

**Scope**: this ADR specifies deployment for **skills**. Agents,
prompts, hooks, and standards are NOT in scope. Per the harness
portability matrix in `docs/ARCHITECTURE.md`, only skills are
byte-identical across Claude Code and Codex (Open Agent Skills
Standard, identical `SKILL.md`). Agents use divergent formats
(Claude YAML-frontmatter Markdown vs Codex TOML), hooks are
harness-specific (Claude's 13 lifecycle events vs Codex's 3),
and standards/prompts are injected differently. Those primitives
need their own deployment ADR with a per-primitive compile or
adapter step. ADR-0003 establishes the model; future ADRs extend
it where the cross-harness symmetry holds.

Skills flow through three distinct layers. Each layer has a
single, clear responsibility.

```
Layer A — SOURCE (development, git-versioned)
  Examples:
    ~/code/library/cognovis-core/.claude/skills/<name>/
    ~/code/library/sussdorff-core/.claude/skills/<name>/
    Third-party: anthropics/skills, disler/the-library, skills.sh, …

  Purpose: develop here. Edit, commit, push, normal git workflow.
  Constraint: NEVER linked directly from a harness path.

         │  library use <name>  (fetch + materialize)
         ▼

Layer B — CACHE (immutable from user perspective, version-pinned)
  Path: ~/.local/share/library/skills/<marketplace>/<name>@<version>/

  Purpose: a known-good, version-pinned copy of the skill ready
  for use. One materialized copy per (marketplace, name, version).
  Not git. Updated only by `library use`, `library upgrade`, or
  `library pin`. User-facing tools treat cache entries as
  read-only — `library edit <name>` opens the Source checkout
  (Layer A), never the cache.

         │  ln -sfn  (idempotent)
         ▼

Layer C — HARNESS (symlinks; what each coding agent observes)
  ~/.claude/skills/<name>           ──► Layer B
  ~/.agents/skills/<name>           ──► Layer B    (Codex CLI; per OpenAI docs)
  ~/.pi/skills/<name>               ──► Layer B    (when applicable)
  <project>/.claude/skills/<name>   ──► Layer B    (project-scoped, Claude)
  <project>/.agents/skills/<name>   ──► Layer B    (project-scoped, Codex)
```

**The harness directories remain unchanged in name and location.**
Coding-agent binaries are hardcoded to look in `.claude/skills/`
and `.agents/skills/` (the latter per the published OpenAI Codex
skill docs); ADR-0003 does not relocate them. What changes is
that entries under those directories are symbolic links into a
shared cache, not physical directories.

**Source/Cache decoupling is the central guarantee.** An edit in
Layer A does not become observable in Layer B or Layer C until an
explicit promotion step (`library upgrade <name>`). The skill
development loop in `cognovis-core` stays safe and reversible;
running agent sessions are unaffected by mid-flight changes to
the source.

**Cache immutability is the second guarantee.** A user editing
`~/.local/share/library/skills/.../SKILL.md` directly would
mutate the cache, not the source — and the next
`library upgrade` would overwrite the change. Tooling enforces
this: `library edit <name>` resolves to the Source checkout in
the library-core repo, never to the cache. Cache entries are
created with chmod ugo-w after materialization on best-effort
basis (advisory, not security).

### Decision 2: Marketplace-symmetric primitive

**Terminology note — "marketplace" disambiguation**: ADR-0002
retired *Claude Code plugin marketplaces*
(`sussdorff/claude-code-plugins`, `cognovis/claude-code-plugins`) —
the bundle-distribution mechanism native to Claude Code. ADR-0003
introduces *source-provider marketplaces* — entries in
`library.yaml.marketplaces:` that describe **where the library
fetches a skill from**. Same word, different referent. The
plugin-marketplace concept stays retired; the source-provider
marketplace is what this ADR specifies. ADR-0002 has been updated
with the same clarification (see the corresponding note there).
Alternatives considered: rename to `source_providers` or
`registries`. Rejected because (a) `marketplace:` is already
established in `library.yaml` for third-party sources and renaming
would break the existing 5 entries, and (b) the user-facing
concept is unchanged — "a place skills come from" — only ADR-0002's
narrower usage needed clarification.

`library.yaml` exposes a single primitive — the **marketplace** —
and treats `cognovis-core` and `sussdorff-core` as marketplaces of
the same kind as `anthropics/skills`, `disler`, `skills.sh`, etc.

Concrete schema change:

```yaml
marketplaces:
  - name: cognovis-core            # NEW — own team content
    source: https://github.com/cognovis/library-core
    type: git
  - name: sussdorff-core           # NEW — own personal content
    source: https://github.com/sussdorff/library-core
    type: git
  - name: anthropic-skills         # NORMALIZE (was: anthropic-official org-wide)
    source: https://github.com/anthropics/skills
    type: git
  - name: disler                   # EXISTING
    source: https://github.com/disler
    type: git
  - name: pbakaus                  # EXISTING
    source: https://github.com/pbakaus
    type: git
  - name: skills-sh                # NEW (later phase, requires adapter)
    source: https://skills.sh
    type: skills-sh
    auth: bearer
  - name: cognovis-samurai         # EXISTING
    source: https://github.com/cognovis/samurai-skills
    type: git
  - name: thadenorigar             # EXISTING (private)
    source: https://github.com/ThadeNorigar
    type: git

skills:
  - name: agent-forge
    from_marketplace: cognovis-core      # uniform reference
    path: .claude/skills/agent-forge
    harness: both
    tags: [...]
  # ... 107 further entries, normalized to from_marketplace + path
```

After the schema refactor, **no skill entry uses a direct `source:`
URL**. The resolver has a single code path.

### Decision 3: Cache layout — namespaced + content-addressed

Cache path template:
`~/.local/share/library/skills/<marketplace>/<name>@<version>/`
(XDG `$XDG_DATA_HOME` if set, fallback `~/.local/share/`).

The **marketplace component is mandatory in the path** to avoid
collisions: if both `cognovis-core` and `disler` ship a skill named
`beads`, they get separate cache entries
(`.../cognovis-core/beads@<v>/` vs `.../disler/beads@<v>/`).
Without the namespace, the second install would clobber the first.

The `<version>` component is the git SHA for `type: git`
marketplaces (the common case) or a marketplace-provided version
string / content hash for non-git marketplaces (e.g. `skills.sh`).

Rationale for the `@<version>` suffix over in-place updates:

- **Rollback is trivial**: `library pin <name> <old-version>` swaps
  a symlink, no re-fetch needed.
- **Parallel pinned versions** are possible for experimentation
  (e.g. `library use beads --pin=<v> --project=foo` while global
  stays on a different version).
- **Atomic upgrade**: the new version exists in the cache before
  the symlink swap, so an interrupted upgrade leaves the previous
  symlink valid.

Equivalent precedent: nix-store, brew Cellar, pnpm content-addressed
store.

**GC policy**: a cache entry not referenced by any active symlink
(global lockfile + any registered project lockfile) is a candidate
for collection. `library gc` removes them; default policy is keep
the last N=3 unreferenced versions per (marketplace, name) for fast
rollback.

### Decision 4: Lockfile — extend existing `.library.lock` (YAML), add global counterpart

ADR-0003 **extends** the existing normative `.library.lock` spec
(`docs/lockfile-format.md`, `docs/schema/lockfile.schema.json`,
bead CL-t21) rather than introducing a parallel format. Rationale:

- A YAML spec already exists, is normative, and has cookbook flows
  (`cookbook/use.md`, `remove.md`, `sync.md`, `audit.md`) keyed to
  it. Replacing it with TOML would invalidate all of them.
- Consistency: `library.yaml` is also YAML. One serialization
  format across the library reduces tooling surface.
- The existing schema already supports `bridge_symlinks`, which
  the three-layer model needs (now extended to record the full
  symlink fan-out to all harnesses, not just the dual-install
  bridge).
- Migration is additive: two new fields (`marketplace`,
  `cache_path`) on `lockfile_entry`, plus an optional global
  lockfile instance at a different path.

**Two lockfile instances, same schema.**

| Scope | Path | Owner |
|-------|------|-------|
| Per-project | `<project>/.library.lock` | Project-local install set (existing CL-t21 placement; committed to git) |
| Global | `~/.config/library/global.lock` | Machine-local global install set (NEW; not git-tracked) |

**Schema extension (additive)**: two new fields on `lockfile_entry`.

**Path conventions**:
- `cache_path` is **always absolute** (Layer B is a single global
  cache, even when the skill is installed for a project). The
  `~/` shorthand may be used in human-edited examples; the
  resolver expands to an absolute path before writing.
- `install_target` is **relative for project-scoped installs**
  (existing convention from `docs/lockfile-format.md`) and
  **absolute for global installs** (e.g. `~/.claude/skills/<n>/`).
- `bridge_symlinks` entries describe a symlink as `<link-path> -> <target-path>`
  where both sides are written **as the resolver would `ln -sfn`
  them on this machine** — absolute target paths into the cache
  to avoid the relative-from-project trap (a `../../.local/...`
  target only resolves correctly from a global symlink, not from
  a project-local one).

**Global install example** (entry in `~/.config/library/global.lock`):

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core                                                              # NEW
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc...                                                     # full git commit SHA / object id (40-char SHA-1 for SHA-1 repos; 64-char hex for SHA-256 repos)
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/   # NEW — absolute, Layer B
    install_target: /Users/malte/.claude/skills/agent-forge/                                # absolute (global install)
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a094...                                                            # SHA-256 of SKILL.md content (distinct from source_commit)
    license: MIT
    bridge_symlinks:
      - /Users/malte/.agents/skills/agent-forge -> /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
      # plus any other harness path (~/.pi/skills/..., or ~/.codex/skills/ if Phase 0 keeps it) as they become applicable
```

**Project install example** (entry in `<project>/.library.lock`):

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc...
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/   # absolute — same cache for global and project
    install_target: .claude/skills/agent-forge/                                             # relative (project-scoped, existing convention)
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a094...
    license: MIT
    bridge_symlinks:
      - .agents/skills/agent-forge -> /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
      # link-path relative to project root; target absolute into the cache
```

The existing schema fields (`name`, `type`, `source`,
`source_commit`, `install_target`, `install_timestamp`,
`checksum_sha256`, `license`, `bridge_symlinks`) remain unchanged
in meaning. Note that `source_commit` is the **git commit hash**
of the source repo (SHA-1 by default, SHA-256 in repos using
`--object-format=sha256`), distinct from `checksum_sha256` which
is the SHA-256 digest of the artifact file content.

Two new fields are added:

- `marketplace`: the `name` of the source-provider marketplace
  entry in `library.yaml.marketplaces:`. Mandatory under ADR-0003;
  existing lockfiles without it migrate by setting it based on
  the `source:` URL (one-time migration, codified in the
  `/library` skill's `migrate` flow).
- `cache_path`: the Layer B path, always absolute. Recorded for
  debugging and for `library gc` reference-counting.

`/library sync` (per existing `cookbook/sync.md`) is extended to
materialize the Layer B cache entry first, then symlink. `library
audit` (per existing `cookbook/audit.md`) gains an additional
check: verify the symlink at `install_target` and each entry in
`bridge_symlinks` points to the recorded `cache_path`.

**Schema migration is a separate bead** (see Follow-up Beads
below) — ADR-0003 specifies the target schema; the bead executes
the JSON Schema + cookbook updates.

On a fresh machine: clone library-core repos (or rely on
marketplace-fetch for third-party), run `library sync` against
both lockfile instances, all skills materialize into cache and
become available across harnesses.

### Decision 5: Adapter pattern per marketplace `type:`

Each marketplace declares its `type:` and the library resolver
picks the appropriate adapter:

| `type:` | Fetch logic | Auth | Coverage in first phase |
|---------|-------------|------|-------------------------|
| `git` | `git fetch <source>`; checkout requested sha; copy `<path>` into cache | none / git credentials | All current + new own marketplaces, all known third-party (disler, anthropics/skills, pbakaus, samurai-skills, ThadeNorigar) |
| `skills-sh` | `GET /api/v1/skills/<name>` with Bearer header; download tarball; expand into cache | API key in `~/.config/library/credentials` | Deferred — first phase ships `git` only |
| `http-tarball` (future) | `curl <url>`; checksum-verify; expand | varies | Not in first phase |

`git` covers 100% of current `library.yaml` entries plus
`anthropics/skills` and similar. `skills-sh` is a follow-up bead.

### Decision 6: Harness path standardization

`library.yaml.default_dirs.skills` resolves to:

```yaml
default_dirs:
  skills:
    global_claude:  ~/.claude/skills/
    global_codex:   ~/.agents/skills/        # canonical per OpenAI Codex docs
    global_pi:      ~/.pi/skills/            # placeholder for future
    project_claude: .claude/skills/
    project_codex:  .agents/skills/          # canonical per OpenAI Codex docs
    project_pi:     .pi/skills/              # placeholder
```

**Codex skill path is `.agents/skills/`.** This matches the
published OpenAI Codex CLI documentation
(<https://developers.openai.com/codex/skills>) and the existing
normative spec in `docs/policy/name-collision.md`. The Open Agent
Skills Standard (agentskills.io) defines `SKILL.md` as the file
format; the `.agents/skills/<name>/SKILL.md` convention is the
Codex-side install location. Claude Code uses `.claude/skills/`.

**Empirical drift exists**: today, 71 skills live in
`~/.codex/skills/` rather than `~/.agents/skills/`, because the
existing `sync-codex-skills` deploys there. This is **not**
sufficient evidence that Codex CLI actually loads from
`~/.codex/skills/` — it may be loading from neither, from one,
or from both (the discovery surface is undocumented for
`codex-cli 0.130.0`). Before Phase 3 of this ADR proceeds,
a follow-up bead **must run a live smoke test**:

1. Place a uniquely identifiable test skill in `~/.agents/skills/`
   only (never `~/.codex/skills/`). Verify Codex CLI sees it.
2. Place a second test skill in `~/.codex/skills/` only. Verify
   Codex CLI sees it (or does not).
3. Document the result. The canonical path in `library.yaml`
   stays `.agents/skills/`; if `~/.codex/skills/` also loads,
   add it as a compatibility symlink target during Phase 2 so
   both paths point to the same cache entry.

The smoke test's outcome does not invalidate the design — it
only confirms how many symlinks per skill the
`/library use` implementation must create on the Codex side.
Worst case (both paths load): we symlink both. Best case
(only `.agents/skills/` loads): we symlink one and migrate
`~/.codex/skills/` content over.

The `sync-codex-skills` hook is removed in the same phase as the
`/library use` reimplementation — once every cache entry is
symlinked from both `~/.claude/skills/<name>` and the canonical
Codex path, the two harnesses observe the same bytes via the
same Inode; no reconciliation is necessary.

## Lifecycle example — the `beads` skill

To make the model concrete, here is what happens to a single skill
across develop → publish → upgrade → rollback.

### Initial install

```
$ library use beads
  resolve:    beads → marketplace=cognovis-core, path=.claude/skills/beads
  fetch:      git fetch cognovis-core; HEAD = a3f2d8e
  materialize: copy <repo>/.claude/skills/beads/ → ~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/
  symlink:    ~/.claude/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/
              ~/.agents/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/
  lockfile:   global.lock now records beads (marketplace=cognovis-core, source_commit=a3f2d8e)
```

### Agent usage (no library involvement)

Claude Code starts a session. Reads `~/.claude/skills/beads/SKILL.md`.
Symlink resolves to
`~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/SKILL.md`.
Codex starts a session. Reads `~/.agents/skills/beads/SKILL.md`.
Symlink resolves to the same Inode. Both harnesses see identical bytes.

### Source edit

```
$ cd ~/code/library/cognovis-core
$ $EDITOR .claude/skills/beads/SKILL.md
$ git diff   # shows pending change
```

Layer B and Layer C are unchanged. Any running agent session continues
to see `@a3f2d8e`. The change is git-local; it does not propagate.

### Commit and push

```
$ git commit -am "fix: beads error message wording"
$ git push   # remote HEAD now a different sha, say 9b1e72c
```

Layer B and Layer C are still unchanged. The new SHA exists in
`cognovis-core` but is not yet materialized.

### Explicit promote

```
$ library upgrade beads
  resolve:    beads → marketplace=cognovis-core
  fetch:      git fetch; HEAD = 9b1e72c
  materialize: copy → ~/.local/share/library/skills/cognovis-core/beads@9b1e72c/
  symlink swap: ~/.claude/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@9b1e72c/
                ~/.agents/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@9b1e72c/
  lockfile:   global.lock updated; source_commit=9b1e72c
  note:       cache@a3f2d8e remains for rollback
```

Only sessions started **after** this moment see the new version.
Existing in-flight sessions are not interrupted.

### Rollback

```
$ library pin beads a3f2d8e
  symlink swap back: ~/.claude/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/
                     ~/.agents/skills/beads → ~/.local/share/library/skills/cognovis-core/beads@a3f2d8e/
  lockfile: source_commit=a3f2d8e
```

No re-fetch necessary; the old cache entry was retained by the GC policy.

## Rationale

### Why a separate Cache layer at all

Two layers (`Source → Harness symlink directly`) is simpler. We
reject it because of Problem 2 above: edits in Source would
instantly affect running agents. The Cache is the explicit
"published version" boundary.

Two layers in the other direction (`Source → Harness with cp`,
no symlinks) is what we have today. We reject it because of
Problem 1: cross-harness drift + sync-hook bandage.

Three layers gives both properties: source is mutable in git
without affecting deployment; cache is immutable across harnesses;
symlinks deduplicate the deployment so all harnesses observe the
same bytes.

### Why marketplace symmetry

Treating own content (`cognovis-core`) and third-party content
(`anthropics/skills`, `skills.sh`) under the same primitive
removes a class of corner cases. The resolver does not need to
ask "is this our skill or someone else's?" — every skill is
`from_marketplace: <name>, path: <p>`. Adding a new marketplace
is purely additive; no changes to the rest of the schema.

The user-articulated principle: "Für unsere Library sind unsere
eigenen Marketplaces nichts anderes als irgendein Drittanbieter."

### Why content-addressed cache (`@<version>`)

Atomic upgrades (build new entry → swap symlink) require either a
version suffix or a temporary path with rename. The suffix is
cheaper and gives free rollback storage.

The `nix-store`, `brew Cellar`, `pnpm` content-addressed store, and
`Go module cache` all use this pattern. None of them use in-place
updates for the same reasons.

### Why lockfiles in two scopes

The fleet has both global needs (which skills are universally
available on this machine) and per-project needs (`mira` and
`polaris` and `cognovis-charly` pull in different subsets). A
single global lockfile cannot express both. Per-project lockfiles
also enable repo-level reproducibility: clone a project, run
`library sync`, get exactly the skills the project expects, at
the versions the project expects.

This mirrors `Gemfile.lock` / `package-lock.json` / `uv.lock` /
`Cargo.lock` patterns.

### Why we do not adopt skills.sh as the library

`skills.sh` is a hosted Marketplace + discovery index. It is not
a local coordinator. It does not handle:

- Multi-harness deployment to `.claude/` + `.codex/` + `.pi/`
- Private skills that should not leave a local network
- Cross-marketplace aggregation (our own cores + Anthropic + skills.sh
  + disler in one lockfile)
- Operation without network access

`skills.sh` becomes one valuable marketplace among several. The
library remains the local control plane.

### Why we do not adopt agentskills.io as the library

`agentskills.io` is a *specification* (the SKILL.md format), not a
distribution platform. It does not host content. It does not have
an install command. It is referenced as the format we conform to;
it is not registerable as a marketplace.

## Final-state architecture (after all phases)

```
                   ┌──── github.com/cognovis/library-core (Source)
                   │
   library.yaml ───┼──── github.com/sussdorff/library-core (Source)
   (marketplaces +─┼──── github.com/anthropics/skills (Source)
    skills        )│
                   ├──── github.com/disler (Source)
                   │
                   ├──── skills.sh (Source via API; later phase)
                   │
                   └──── ... (additional marketplaces, additive)
                              │
                              │ library use / library sync
                              │ (per `type:` adapter)
                              ▼
                   ~/.local/share/library/skills/<marketplace>/<name>@<version>/
                              │  (Cache, namespaced by marketplace)
                              │
                              │ ln -sfn
                              ▼
       ~/.claude/skills/<n>   ~/.agents/skills/<n>   ~/.pi/skills/<n>
       <project>/.claude/skills/<n>   ...            ...
              (Harness — what each coding agent observes)
```

Three lockfile sources state the world:

- `~/.config/library/global.lock` — global installed set (NEW, YAML, same schema as project lockfile)
- `<each-project>/.library.lock` — per-project installed set (existing per CL-t21, YAML)
- `library.yaml` — catalog of *available* skills + marketplaces

Three commands run the lifecycle:

- `library use <name>` — install (or move) a skill into Layer B + C
- `library upgrade <name>` — refresh from Layer A into Layer B + C
- `library pin <name> <version>` — swap symlink to a different cached version

Plus utilities: `library sync`, `library gc`, `library push` (for own
marketplaces).

## Migration Sequence

The migration runs in phases, each with its own bead. ADR-0003
acceptance is the gate to start Phase 1.

### Phase 0: Codex skill-loading smoke test

**Goal**: empirically determine which path(s) `codex-cli 0.130.0`
actually reads skills from.

**Actions**:
1. Create two uniquely identifiable test skills.
2. Place one in `~/.agents/skills/test-canon/SKILL.md` only.
3. Place the other in `~/.codex/skills/test-legacy/SKILL.md` only.
4. Start Codex, attempt to invoke each skill, observe which loads.
5. Document the result; update `default_dirs.skills.global_codex`
   and `project_codex` only if the smoke test contradicts the
   OpenAI documentation.

**Completion**: result recorded as a `bd update --append-notes`
on the smoke-test bead and referenced from Phase 2.

### Phase 1: library.yaml schema refactor

**Goal**: every skill entry uses `from_marketplace: <name>, path: <p>`;
no direct `source:` URLs remain; `cognovis-core` and `sussdorff-core`
appear in `marketplaces:`; `default_dirs.skills.global_codex` /
`project_codex` reflect the Phase 0 smoke-test outcome (default:
`.agents/skills/` per OpenAI docs).

**Prerequisite**: the library-catalog schema extension (see
Follow-up Bead 2) must land first, so that
`marketplace_entry.type` (and optional `auth`) is a valid field.
Without it, adding `type: git` to the new marketplace entries
fails validation.

**Actions**:
1. Verify the library-catalog schema extension is merged (Bead 2).
2. Add `cognovis-core` and `sussdorff-core` to `marketplaces:`
   with `type: git`.
3. Normalize the 108 direct-source entries (94 cognovis + 14 sussdorff)
   to `from_marketplace: ..., path: ...`.
4. Set `default_dirs.skills.global_codex = ~/.agents/skills/` and
   `project_codex = .agents/skills/` (per `docs/policy/name-collision.md`
   normative spec + Phase 0 outcome). If Phase 0 confirms
   `~/.codex/skills/` also loads, add it as an additional fan-out
   target in Decision 6's path list rather than replacing.
5. Run `library.yaml` validator (CL-wud). Fix lint errors.

**Completion**: validator passes; grep finds zero entries with
direct `source:` URLs in the `skills:` section.

### Phase 2: `/library use` reimplementation

**Goal**: `library use <name>` follows the three-layer model.
Cache + symlink replaces `cp`. Lockfile schema (`docs/lockfile-format.md`,
`docs/schema/lockfile.schema.json`) extended with `marketplace` and
`cache_path` fields.

**Actions**:
1. Implement git-type adapter (fetch + materialize into cache).
2. Implement cache layout
   `~/.local/share/library/skills/<marketplace>/<name>@<version>/`.
3. Implement symlink fan-out to all configured harness paths from
   `library.yaml.default_dirs.skills.*`.
4. Extend `.library.lock` schema (`marketplace`, `cache_path`) and
   add global lockfile (`~/.config/library/global.lock`, same schema).
5. Implement `library upgrade`, `library pin`, `library edit`,
   `library sync`, `library gc`, `library push` (First-Party only).
6. Update cookbooks (`cookbook/use.md`, `remove.md`, `sync.md`,
   `audit.md`) for the new model.
7. Smoke test on three diverse skills (one cognovis-core, one
   sussdorff-core, one third-party).

**Completion**: `library use beads` materializes a cache entry at
`.../cognovis-core/beads@<sha>/` and creates symlinks under
`~/.claude/skills/beads` and `~/.agents/skills/beads` pointing to
the same Inode. Both lockfile instances record the
`(marketplace, source_commit, cache_path, install_target,
bridge_symlinks)` tuple.

### Phase 3: clc-otu Go-Live (surgical wipe + reinstall)

**Goal**: every library-managed entry in `~/.claude/skills/` and
`~/.agents/skills/` is a symlink into the cache. Unmanaged
entries are preserved.

**Surgical-wipe principle**: `~/.claude/skills/` and
`~/.agents/skills/` may contain non-library content (manually-placed
skills, plugin-installed skills, `.system/` directories, in-flight
experiments). A blanket `rm -rf` would delete this. Phase 3 only
operates on entries the library can prove ownership of, via the
lockfile.

**Applies to both directories**: `~/.claude/skills/` is in scope
in addition to `~/.agents/skills/` (and `~/.codex/skills/` if
Phase 0 keeps it as a fan-out target).

**Actions** (per the existing clc-otu bead, updated):
1. Backup the entirety of `~/.claude/skills/` and
   `~/.agents/skills/` (plus `~/.codex/skills/` if applicable) to
   `~/.tmp/skills-pre-library-go-live-<date>/`. Same protocol as
   the existing clc-otu plan.
2. Inventory: list every entry. Classify each via a strict
   two-tier check.

   **Tier 1 — destructive replacement permitted** (entry is
   provably library-managed). At least ONE of:
   - Entry path is a symlink whose target is under
     `~/.local/share/library/skills/`.
   - Entry directory contains a Library-emitted marker file
     (e.g. `.library-managed` written at install time, recording
     `name`, `marketplace`, `cache_path`).
   - Entry's primary artifact (`SKILL.md`) `checksum_sha256`
     matches the `checksum_sha256` recorded in the global
     lockfile for an entry with the matching `name` AND the
     `install_target` resolves to this path.
   - Entry is referenced by an active record in the global
     lockfile via absolute `install_target` equality.

   **Tier 2 — candidate, do NOT destructively replace** (entry
   shares a name with a `library.yaml.skills` entry but does
   not meet any Tier 1 criterion). Treatment:
   - Leave in place.
   - Surface in the audit log as `CANDIDATE: <path> shares name
     with library.yaml entry <name>; manual review needed`.
   - User decides per-entry: either adopt (run
     `library use <name> --force` after backup) or rename
     locally to avoid the name clash.

   Everything else is **unmanaged**: leave in place; record in
   `unmanaged-skills-<date>.md`.

3. For Tier 1 entries: remove the existing directory or symlink.
   Run `library sync` from `~/.config/library/global.lock` to
   recreate them as symlinks into the cache.
4. For Tier 2 candidates and unmanaged entries: untouched. The
   audit log surfaces them for follow-up beads.
5. Remove `sync-codex-skills` hook only after both Claude and
   Codex harness paths verifiably resolve to the same Inode for
   every Tier 1 library-managed skill.

**Completion**:
- Every library-managed entry under `~/.claude/skills/` is a
  symlink whose target is under `~/.local/share/library/skills/`.
- Same for `~/.agents/skills/` (and `~/.codex/skills/` if kept).
- Inode equality verified for at least 5 diverse skills:
  `stat -f%i ~/.claude/skills/<n>/SKILL.md` equals
  `stat -f%i ~/.agents/skills/<n>/SKILL.md`.
- Unmanaged inventory file exists and lists every preserved entry.

### Phase 4 (optional, deferred): skills.sh adapter

**Goal**: `type: skills-sh` marketplace fetches via API.

**Actions**:
1. Implement Bearer-auth fetcher.
2. Document credential storage at `~/.config/library/credentials`.
3. Add `skills.sh` to `marketplaces:`.
4. Register one or two skills via `from_marketplace: skills-sh, path: <name>`
   as proof of concept.

**This phase is optional.** Phase 1-3 do not depend on it.

## Resolved questions

The five questions raised during the first draft are resolved as
follows (2026-05-12, after Codex adversarial review):

1. **GC retention policy** — keep last 3 unreferenced versions per
   `(marketplace, name)` tuple. Requires cache metadata to track
   marketplace provenance (covered by Decision 3's namespaced path).
2. **Project lockfile location** — keep `<project>/.library.lock`
   as specified in the existing normative spec (`docs/lockfile-format.md`,
   CL-t21). No new path introduced. The global counterpart is at
   `~/.config/library/global.lock` (same schema).
3. **`library push` semantics** — in Phase 2 ships only First-Party
   support: `library push` operates against `cognovis-core` and
   `sussdorff-core` only. Forks of third-party marketplaces are
   out of scope for this ADR; a `--upstream <fork>` flag may be
   added later via a separate ADR if the use case emerges.
4. **Cross-namespace collisions** — the lockfile schema mandates
   `marketplace:` for every entry (Decision 4). Two skills with the
   same `name` from different marketplaces get separate cache
   entries (Decision 3's namespace). On install, if the user runs
   `library use beads` and `beads` exists in multiple registered
   marketplaces, the resolver fails closed and prompts:
   `library use beads --marketplace=cognovis-core`. No last-write-wins.
5. **Codex skill description 1024-char limit** — **not treated as
   a Codex-blocking constraint**. Per the published OpenAI Codex
   skills docs (<https://developers.openai.com/codex/skills>), there
   is an initial skill-list token budget and Codex truncates skill
   descriptions to fit; there is no documented hard 1024-character
   rejection. `skill-auditor`'s existing 1024-char BLOCKING finding
   (CCP-wyi) should be reclassified to an ADVISORY warning, then
   re-tested against a live Codex with a known-long-description
   skill. The cache + symlink architecture is independent of this
   constraint; resolution lives in CCP-wyi, not ADR-0003.

## Rollback Plan

| Scenario | Recovery |
|----------|---------|
| Phase 1 validator rejects new schema | Revert `library.yaml`; investigate validator rules; fix before re-applying |
| Phase 2 `library use` cache write fails | Old cp-based implementation still callable via legacy code path; toggle config flag to revert |
| Phase 3 surgical-wipe misclassifies an unmanaged skill as managed | Restore the specific entry from backup in `~/.tmp/skills-pre-library-go-live-<date>/`; refine the classifier; re-run Phase 3 step 2 |
| Phase 3 leaves an unmanaged skill behind that should have been migrated | Audit log lists it; create a follow-up bead to register it in `library.yaml` and re-run `library use <name>` |
| Cache corruption | `rm -rf ~/.local/share/library/skills/<marketplace>/<name>@<version>/`; `library use <name>` rematerializes |
| Lockfile drift between machines | `library sync` is the authoritative reconciler; lockfile is source of truth for cache state |

## Alternatives Considered

### Alternative A: Status quo — `cp`-based deployment with sync-codex-skills hook

**Description**: keep the existing `cp` approach; rely on
`sync-codex-skills` to keep `~/.codex/skills/` in step with
`~/.claude/skills/`.

**Pros**: zero migration cost; already working for 71 skills.

**Cons**: Problem 1 (duplicate content, drift) is unresolved.
sync-codex-skills is a bandage, not a fix. Cross-harness drift
silently produces inconsistent agent behavior.

**Rejected because**: the duplication is architectural debt that
compounds as the fleet grows. The fix is not more sync hooks; it is
removing the duplication.

### Alternative B: Direct symlink into source repos (no cache layer)

**Description**: `~/.claude/skills/beads` → `~/code/library/cognovis-core/.claude/skills/beads/` directly.

**Pros**: simplest possible model; one symlink per skill; no cache layer.

**Cons**: every edit in `cognovis-core` is instantly live for every
running agent session. No publish step. No version pinning. No rollback.
User explicitly identified this as "tödlich".

**Rejected because**: source-equals-deployment defeats the iteration
workflow.

### Alternative C: Selected — Three-layer with content-addressed cache

See Decision section.

### Alternative D: Build/release artefacts in library-core (CI-published versions)

**Description**: `cognovis-core` has a CI pipeline that builds a
release tarball per skill, hosted as a GitHub release asset.
`/library use` downloads the tarball.

**Pros**: explicit release surface; signed/checksummed; works for
non-git marketplaces too.

**Cons**: heavyweight; CI overhead per skill push; less suitable for
the rapid iteration loop on personal skills.

**Rejected because**: overengineering for the current scale. Worth
revisiting if the fleet grows beyond ~5 contributors per marketplace.

### Alternative E: Adopt skills.sh as the entire library

**Description**: stop maintaining `library.yaml` locally; rely on
skills.sh discovery and install commands.

**Pros**: leverages an existing well-built service.

**Cons**: cannot host private skills; no multi-harness deployment;
no per-project lockfile; depends on network availability and
service uptime.

**Rejected because**: skills.sh is a marketplace, not a coordinator.
Multi-marketplace aggregation is not in its scope.

### Alternative F: Adopt Archon / Gas City Hall

**Description**: replace `library.yaml` with one of the agent
orchestration frameworks researched on 2026-05-12.

**Cons**: neither framework understands SKILL.md natively; both
operate at a different abstraction level (workflow orchestration
above skills, not skill distribution). Archon is Claude-first;
Gas City Hall lacks a detailed `skills/` schema.

**Rejected because**: orthogonal layer. Either framework could
sit on top of the library later if desired; neither replaces it.

## Success Criteria

After Phase 0-3 complete:

1. Phase 0 smoke-test result documented; `library.yaml.default_dirs.skills.global_codex`
   reflects the observed Codex loading behavior.
2. `library.yaml` `marketplaces:` lists `cognovis-core` and
   `sussdorff-core` alongside the existing third-party marketplaces.
3. Every entry in `library.yaml.skills` uses
   `from_marketplace: <name>, path: <p>`. Zero direct `source:` URLs
   in the `skills:` section.
4. `library use <name>` materializes
   `~/.local/share/library/skills/<marketplace>/<name>@<version>/`
   and creates symlinks under `~/.claude/skills/<name>` and
   `~/.agents/skills/<name>` (plus `~/.codex/skills/<name>` if
   Phase 0 keeps it as a fan-out target).
5. `find ~/.claude/skills -maxdepth 1 -type l | wc -l` equals
   `find ~/.agents/skills -maxdepth 1 -type l | wc -l` equals the
   library-managed entry count from the global lockfile.
6. `stat -f%i ~/.claude/skills/<any>/SKILL.md` equals
   `stat -f%i ~/.agents/skills/<same>/SKILL.md` (same Inode →
   parity by construction).
7. `.library.lock` schema includes `marketplace` and `cache_path`
   fields; existing lockfiles migrated; validator green.
8. `sync-codex-skills` hook is removed from `session-close`.
9. Source edit in `cognovis-core` does not affect Layer B or Layer C
   until `library upgrade` is run (manual test: edit + observe).
10. ARCHITECTURE.md references ADR-0003 in the ADR table.
11. ADR-0002 contains the marketplace-terminology clarification note.

## Communication

This ADR is decided in a single-developer context. Once accepted, the
`/library` skill's user-visible commands (`library use`, `library upgrade`,
`library pin`, `library sync`, `library gc`, `library push`) need to be
documented in the skill's SKILL.md and in `CHANGELOG.cognovis.md`.

External users of the library: 0. No external communication needed
beyond the changelog.

## Codex parallel

Decision 6 keeps `.agents/skills/` (project) and `~/.agents/skills/`
(global) as the canonical Codex paths per the published OpenAI
Codex skills documentation. The empirical observation that 71
skills currently live in `~/.codex/skills/` reflects the existing
`sync-codex-skills` deployment, not a verified Codex skill-loading
location. Phase 0 of this ADR resolves the ambiguity via a live
smoke test; Phase 1 commits the result to `library.yaml`.

The `sync-codex-skills` hook is removed as part of Phase 3 because
the symlink-into-cache model guarantees parity by Inode equality —
no reconciliation pass needed. If Phase 0 reveals that both
`~/.agents/skills/` and `~/.codex/skills/` load, both become
fan-out targets of the symlink step; the cache and source layers
are unaffected.

If Codex behavior on a future release changes, the response is
purely additive: append to `default_dirs.skills.*` and emit
additional symlinks. No change to source or cache layout.

## Follow-up Beads Required

The following beads should be created after this ADR moves to
`accepted`:

1. **CL-603** — Phase 0 execution: Codex skill-loading smoke test
   (place test skills, observe Codex behavior, document the actual
   load paths for `codex-cli 0.130.0`).
2. **CL-r92** — Library catalog schema extension (must precede
   Phase 1): extend `docs/schema/library.schema.json` so that
   `marketplace_entry` accepts `type` (enum: `git | skills-sh |
   http-tarball`) and an optional `auth` field; update validator
   tests (CL-wud); add representative `library.yaml` fixture
   covering all three marketplace types. Without this, Phase 1's
   addition of `cognovis-core`/`sussdorff-core` with `type: git`
   fails validation.
3. **Phase 1 execution** (bead TBD): library.yaml schema refactor
   (108 entries normalized; 2 new marketplaces added; default_dirs
   reflects Phase 0 outcome; validator green). Depends on CL-r92.
4. **CL-yx2** — Lockfile schema extension: extend
   `docs/lockfile-format.md` and `docs/schema/lockfile.schema.json`
   with `marketplace` and `cache_path` fields; update cookbooks
   (`use.md`, `remove.md`, `sync.md`, `audit.md`); provide a
   migration script for existing `.library.lock` instances.
4. **Phase 2 execution**: `/library use` reimplementation with cache +
   symlink + lockfile (per the extended schema) + adapter pattern;
   adds `library upgrade`, `library pin`, `library edit`,
   `library push` (First-Party only), `library gc`.
5. **Phase 3 execution**: clc-otu adapted to the new model
   (surgical wipe of library-managed entries + `library sync`
   from lockfile; covers both `~/.claude/skills/` and
   `~/.agents/skills/` plus `~/.codex/skills/` if applicable).
6. **Phase 4 execution (deferred, optional)**: skills.sh adapter +
   credential storage at `~/.config/library/credentials`.
7. **Documentation**: update `/library` SKILL.md to describe the
   new command surface and the three-layer model.
8. **GC test bead**: integration test for `library gc` retaining
   the configured number of versions per `(marketplace, name)`.
9. **CCP-wyi reclassification**: re-test Codex behavior with a
   skill exceeding 1024-char description; reclassify the
   `skill-auditor` finding from BLOCKING to ADVISORY per the
   resolved-questions answer.

The bead `clc-otu` is **blocked by ADR-0003 acceptance + Phase 0
+ Phase 1 + Phase 2**. The eight Phase-4 child beads under the
ADR-0002 Phase 4 epic (clc-8ya, clc-0h8, clc-7bi, clc-btt,
clc-kw2, clc-yqk, clc-dim, clc-a6m) remain valid — they migrate
content into the cores, which is orthogonal to the deployment
mechanism specified here.

The bead `cls-7vk` (sussdorff-plugins residual migration) is
similarly orthogonal: it consolidates content into sussdorff-core,
not affected by this ADR's deployment-mechanism change.
