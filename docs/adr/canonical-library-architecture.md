---
adr: "0002"
title: "Library-core repos as canonical source; harness dirs as deployment targets; full marketplace retirement"
status: accepted
date: 2026-05-02
bead: CL-7na
deciders:
  - Malte Sussdorff
supersedes: ["0001"]
superseded_by: []
related_adrs: ["0001"]
---

# ADR-0002: Library-core repos as canonical source; harness dirs as deployment targets; full marketplace retirement

## Status

Accepted. **Supersedes ADR-0001.**

## Context

ADR-0001 chose a Hybrid retirement model for `sussdorff-plugins`:
retire `business`/`content`/`meta`/`medical` bundles, keep
`core`/`beads-workflow`/`infra` (and conditionally `dev-tools`) as
fleet-wide marketplace bundles. ADR-0001 did not address the second
marketplace `cognovis-claude-code-plugins`.

Three things have happened since ADR-0001 was accepted:

1. **CL-8vb migrated all `keep_in_plugin` artefacts to
   `cognovis/library-core` anyway.** All 14 `beads-workflow/skills/`,
   all 10 `beads-workflow/agents/`, the 3 codex bridges, 9 standards,
   and 4 misc skills are now canonical in `cognovis/library-core`.
   The "keep in marketplace" half of ADR-0001's Hybrid is no longer
   backed by unique content — every bundle artefact is duplicated in
   library-core.

2. **The `cognovis-claude-code-plugins` marketplace was identified as
   a third unaddressed distribution path.** It contains 5 primitive
   artefacts (all already canonical in `cognovis/library-core`) plus
   `cld.zsh` and `cld.ps1` launchers. Three divergent copies of `cld`
   exist across the fleet (`~/.claude/scripts/`,
   `~/code/claude-code-plugins/`, `~/code/cognovis-marketplace/`).

3. **The principle "develop in source-of-truth, deploy to harness
   dirs" has crystallized.** `~/.claude/` and `~/.codex/` should hold
   only deployment artefacts (settings, runtime state, deployed
   skills), never development source. Skills, agents, prompts,
   hooks, and standards develop in `cognovis/library-core` (team) or
   `sussdorff/library-core` (personal) and deploy via `/library use`
   or equivalent install scripts.

ADR-0001's Hybrid was a defensible intermediate stance. The data and
principle changes above make full retirement the correct end state.

### Empirical data

| Fact | Value | Source |
|------|-------|--------|
| `sussdorff-plugins` bundles installed | 8 | `~/.claude/plugins/installed_plugins.json` |
| `keep_in_plugin` artefacts already migrated to `cognovis/library-core` | 100% (per CL-8vb) | CL-8vb close reason |
| `cognovis-claude-code-plugins` bundle | 1 (`cognovis-workflow`) | `~/code/cognovis-marketplace/.claude-plugin/` |
| `cognovis-claude-code-plugins` primitive artefacts | 5 | `cognovis-marketplace/cognovis-workflow/` |
| Of those, present in `cognovis/library-core` | 5 / 5 | CL-sxt + CL-8vb |
| Divergent `cld` implementations across fleet | 3 | `~/.claude/scripts/`, `claude-code-plugins/`, `cognovis-marketplace/` |
| Most recent `cld` edit | 2026-05-01 (cognovis-marketplace) | `git log` per repo |
| External users of either marketplace | 0 known | Both are local-directory or single-developer sources |

The "all keep_in_plugin already migrated" finding eliminates ADR-0001's
core argument for Hybrid retention. The "0 external users" finding
makes full retirement low-risk.

## Decision

### Decision 1: Full retirement of both marketplace repos

Both `sussdorff/claude-code-plugins` and `cognovis/claude-code-plugins`
are fully retired as distribution mechanisms. ADR-0001's Hybrid
decision is reversed — there are no "keep in marketplace" bundles.

| Repo | Local checkout | Fate |
|------|----------------|------|
| `sussdorff/claude-code-plugins` | `~/code/claude-code-plugins/` | Retired. All bundles uninstalled. Marketplace deregistered. Repo archived/deleted. |
| `cognovis/claude-code-plugins` | `~/code/cognovis-marketplace/` | Retired. Bundle uninstalled. Marketplace deregistered. Repo archived/deleted. |

Distribution moves entirely to `/library use` against
`cognovis/library-core` (team artefacts) and `sussdorff/library-core`
(personal artefacts). Fleet-wide essentials (`core`-equivalent,
`beads-workflow`-equivalent, `infra`-equivalent) install via a
single bootstrap script that calls `/library use` for the required
artefact set on a new machine.

### Decision 2: cld/cdx canonical home is `cognovis-library/bin/`

`cld` and `cdx` move to `~/code/cognovis-library/bin/` as the single
source of truth. Distribution to `~/.local/bin/` is via a project-local
install script (`scripts/install-bin.sh`) that creates idempotent
symlinks.

| Concern | Source of truth | Deployed location |
|---------|-----------------|-------------------|
| `cld` (zsh) | `cognovis-library/bin/cld` | `~/.local/bin/cld` (symlink) |
| `cdx` (zsh) | `cognovis-library/bin/cdx` | `~/.local/bin/cdx` (symlink) |
| `cld.ps1` (Windows, when ported) | `cognovis-library/bin/cld.ps1` | Windows install — deferred |

cld/cdx are not skills/agents/prompts; they are the harness launchers
that consume the library. Hosting them in `cognovis-library` co-locates
them with the catalog they invoke.

### Decision 3: `~/.claude/` and `~/.codex/` are deployment targets only

No development happens in `~/.claude/` or `~/.codex/`. These directories
hold:

| Permitted in `~/.claude/` and `~/.codex/` | Source |
|------------------------------------------|--------|
| `settings.json` | Personal deployment-time config |
| `permissions.yml` | Personal deployment-time config |
| Plugin cache, backups, runtime state | Generated/managed by the harness |
| Deployed `skills/`, `agents/`, `commands/`, `hooks/`, `standards/` | Installed via `/library use` from library-core repos |

What does **not** belong in `~/.claude/` or `~/.codex/`:

- Hand-edited skill/agent/prompt source — must develop in
  `cognovis/library-core` or `sussdorff/library-core`, then deploy.
- Hand-edited hooks — same. Hooks are content; canonical source is
  in a library-core repo.
- Behavioral rule files (`rules.d/`) — content; canonical source is
  in a library-core repo.
- `cld`, `cdx`, or other shell launchers — canonical source is
  `cognovis-library/bin/`.

This corollary applies equally to Codex's `~/.codex/`. Same principle,
same enforcement.

The boundary is enforced architecturally rather than by hooks: there
is no source-of-truth git history in `~/.claude/` or `~/.codex/` for
content artefacts (only for personal config), so any drift is
detectable as "canonical version differs from deployed version" and
resolved by re-deploying from the canonical source.

### Decision 4: Defer `uv tool install` packaging

`uv tool install` is the right answer **if** cld/cdx become Python
tools. For zsh scripts it doesn't apply. A Python rewrite is a
separate, larger decision driven by cross-platform need (Windows
team members, CI runners) — not by this ADR. Plain zsh + symlink
install is correct for now.

## Final-state architecture

After all phases of this ADR complete, the fleet has exactly three
first-party canonical repos for agentic content:

| Repo | Role | Audience |
|------|------|----------|
| `cognovis-library` | Catalog + distribution mechanism + cld/cdx + ADRs + `library.yaml` | Single-machine source for `/library use` |
| `cognovis/library-core` | Team agentic content (skills/agents/prompts/hooks/standards) | Cognovis team |
| `sussdorff/library-core` | Personal agentic content | Malte personal |

Plus two deployment targets:

| Target | Role |
|--------|------|
| `~/.claude/` | Deployment target for Claude Code; personal config + deployed library content |
| `~/.codex/` | Deployment target for Codex; personal config + deployed library content |

No marketplaces. No `claude-code-plugins`. No `cognovis-marketplace`.
Single distribution mechanism (`/library use`) backed by
`cognovis-library`'s catalog.

## Rationale

### Why full retirement now (Option 1) instead of ADR-0001's Hybrid

ADR-0001's Hybrid argument: 30 artefacts were `keep_in_plugin` in the
audit, backing the fleet-wide bundles. CL-8vb migrated those 30 to
`cognovis/library-core` anyway, eliminating the "marketplace has
unique content" argument. With no unique content, Hybrid's only
remaining benefit is the marketplace-UI install affordance — which is
a one-time cost on new machines, easily replaced by a bootstrap
script that runs `/library use` for the essentials.

### Why deployment-only stance for `~/.claude/` and `~/.codex/`

Three concrete benefits:

1. **No three-way divergence.** Editing a skill in `~/.claude/skills/`
   today doesn't propagate to `claude-code-plugins/` or
   `cognovis/library-core`. Today's fleet has many such divergences
   (cld is the most visible). Establishing source-only-in-library-core
   eliminates the class of bug.

2. **Reproducibility.** A fresh machine becomes:
   `git clone library-core && /library use <bootstrap-list>`.
   No "copy from your other machine" step.

3. **Review-ability.** Skills/agents in a library-core repo get
   normal git review, PRs, and changelog discipline. Skills in
   `~/.claude/` are personal config — no review surface, no team
   visibility.

### Why `cognovis-library/bin/` for cld/cdx (not a library-core repo)

cld/cdx invoke the harness CLIs that consume the library. They are
distribution infrastructure, not distributed content. Co-locating
with `library.yaml` and the install scripts in `cognovis-library`
puts them in the right architectural layer.

### Why not extend `/library use` to install cld/cdx

Possible future direction: add a `tools:` primitive type to
`library.yaml`, register cld/cdx there, install via
`/library use cld --target=~/.local/bin/`. This would unify the
install model. Defer to a later ADR — for now, a simple
`scripts/install-bin.sh` is sufficient and doesn't require
extending the library schema.

## Migration Sequence

Three phases, gated on completion criteria, plus a parallel Phase 4
epic for the deployment-only enforcement.

### Phase 1: Canonicalize cld/cdx in cognovis-library

**Goal**: Single source of truth for cld/cdx exists at
`cognovis-library/bin/`, deployed to `~/.local/bin/`, used in normal
work.

**Trigger**: This ADR accepted.

**Actions**:
1. Identify the canonical-quality version of `cld` and `cdx` (likely
   the cognovis-marketplace copy for `cld` due to the recent
   version.sh fix; cdx canonical version TBD).
2. Move files to `cognovis-library/bin/cld` and
   `cognovis-library/bin/cdx`.
3. Add `cognovis-library/scripts/install-bin.sh`:
   - Idempotently `ln -sfn cognovis-library/bin/<name>
     ~/.local/bin/<name>` for each entry in `bin/`.
   - Safe to re-run.
4. Run install-bin.sh. Verify `which cld` and `which cdx` resolve to
   `~/.local/bin/<name>` symlinking into `cognovis-library/bin/`.
5. Update CLAUDE.md and ARCHITECTURE.md to document the new location.
6. Remove `~/.claude/scripts/` from `$PATH`.

**Completion criterion**: `which cld` / `which cdx` → `~/.local/bin/`
symlinks; `cld -b <id>` smoke test passes.

### Phase 2: Retire both marketplaces

**Goal**: No marketplace bundles installed; both marketplaces
deregistered; library.yaml `marketplaces:` cleaned.

**Trigger**: Phase 1 complete + verified.

**Actions**:
1. Verify content equivalence: every artefact in either marketplace
   has an equivalent in `cognovis/library-core` or
   `sussdorff/library-core`. Resolve any drift in the canonical repo
   first.
2. For each `sussdorff-plugins` bundle: `plugin uninstall <bundle>`.
3. `plugin uninstall cognovis-workflow@cognovis-claude-code-plugins`.
4. Remove both marketplace registrations from
   `~/.claude/plugins/known_marketplaces.json`.
5. Update `library.yaml` `marketplaces:` to remove both entries
   (schema-serialized — see CLAUDE.md conventions).
6. Add a bootstrap script in `cognovis-library/scripts/` that
   installs the fleet-wide essential set via `/library use` (replaces
   the marketplace-bundle install affordance for new machines).

**Completion criterion**: `installed_plugins.json` contains no
artefacts from either marketplace. `library.yaml` `marketplaces:`
contains neither. New-machine bootstrap script exists and runs
cleanly.

### Phase 3: Archive or delete the two marketplace repos

**Goal**: Repo state matches the retirement decision.

**Trigger**: Phase 2 complete + 30 days of clean operation.

**Actions**:
1. For each of `sussdorff/claude-code-plugins` and
   `cognovis/claude-code-plugins`: add a final commit to README
   pointing users at `cognovis-library` and `/library use`.
2. Archive on GitHub (read-only, indicates retirement) OR delete
   if no historical value.
3. Decision on archive vs delete deferred until trigger.

**This phase is optional.** Phase 2 is sufficient for functional
retirement. Local checkouts remain available as backup until Phase 3.

### Phase 4 (separate epic): Migrate residual `~/.claude/` and `~/.codex/` content

**Goal**: `~/.claude/` and `~/.codex/` hold only deployment artefacts
and personal config — no source.

**Trigger**: Phase 1 complete. Can run in parallel with Phase 2 / 3.

**Actions** (high-level — own follow-up bead/epic):
1. Audit `~/.claude/{hooks,rules.d,agents,skills,standards,scripts}`
   for content that should canonicalize in a library-core repo.
2. For each: move to canonical repo, update `library.yaml`
   registration, deploy back via `/library use`.
3. Same for `~/.codex/`.

**This is large in scope** and warrants its own epic. Phase 4 is
listed here to record the architectural commitment, not to scope the
work.

**Completion criterion**: `~/.claude/` and `~/.codex/` contain only
files matching the "permitted" list in Decision 3.

## Rollback Plan

| Scenario | Recovery action |
|----------|----------------|
| Phase 1 install-bin.sh produces broken symlinks | Remove `~/.local/bin/cld` symlink. Original `~/.claude/scripts/cld` still exists until Phase 2 cleanup. |
| Phase 1 cld behaviour regression | Diff against `cognovis-marketplace/cognovis-workflow/scripts/cld.zsh` (preserved through Phase 3). Cherry-pick missing fixes. |
| Phase 2 uninstall breaks something | Reinstall the affected bundle from the still-existing local marketplace clone. |
| Phase 2 bootstrap script missing an essential | Add to `/library use` manifest, re-run; affected user is unblocked. |
| Phase 3 needs reversal | If archived: GitHub un-archive is reversible. If deleted: restore from local clone (preserved on this machine). |
| Phase 4 deployed artefact regresses | Re-deploy via `/library use` from the canonical version; investigate drift cause. |

**Key safety property**: Phase 3 is a 30-day-delayed optional phase
specifically so reversal stays trivial through Phase 2. Local clones
of both marketplace repos remain on disk through all phases as
backup.

## Communication

**External users of either marketplace**: 0 known.

`sussdorff/claude-code-plugins` source is
`directory:/Users/malte/code/claude-code-plugins` — local-only,
unreachable from any other machine. `cognovis/claude-code-plugins`
has had no published advertising. No follow-up communication
required.

## Codex parallel

Decision 3 explicitly extends to `~/.codex/`. Codex uses
`~/.codex/agents/<name>.toml` (global) or per-repo `.codex/agents/`
rather than a marketplace bundle model — the equivalent retirement
work in Codex's case is the migration of any global-personal toml
files into `sussdorff/library-core` with the cross-harness bridge
(per `docs/policy/name-collision.md` Decision 2).

The cdx wrapper (CL-tap, closed) already lives in this repo's
tooling ecosystem; this ADR canonicalizes that placement under
`cognovis-library/bin/cdx`.

## Success Criteria

1. `cognovis-library/bin/cld` and `cognovis-library/bin/cdx` are the
   single source of truth — verified via `git log` showing recent
   edits land here.
2. `~/.local/bin/cld` and `~/.local/bin/cdx` exist as symlinks
   pointing into `cognovis-library`.
3. `~/.claude/scripts/`, `~/code/claude-code-plugins/`, and
   `~/code/cognovis-marketplace/` no longer contain a maintained
   `cld`/`cdx`.
4. `installed_plugins.json` contains no bundles from either retired
   marketplace.
5. `library.yaml` `marketplaces:` contains neither retired
   marketplace.
6. A bootstrap script exists in `cognovis-library/scripts/` that
   installs fleet-wide essentials via `/library use`.
7. CLAUDE.md and ARCHITECTURE.md reference `cognovis-library/bin/`
   as the canonical home and document the deployment-only stance.
8. This ADR is linked from `docs/ARCHITECTURE.md`.
9. ADR-0001's frontmatter records `superseded_by: ["0002"]`.

Phase 4 (full deployment-only enforcement in `~/.claude/` and
`~/.codex/`) has its own success criteria in its own epic and is
not gated by this ADR's success.

## Deprecation Timeline

Phases gated on completion criteria, not calendar time.

| Phase | Name | Gate to start | Gate to complete |
|-------|------|---------------|------------------|
| 1 | Canonicalize cld/cdx | This ADR accepted | which cld/cdx → symlinks; smoke test passes |
| 2 | Retire both marketplaces | Phase 1 verified | installed_plugins.json clean; library.yaml clean; bootstrap script works |
| 3 | Archive or delete repos (optional) | Phase 2 + 30 days clean | GitHub repos archived or deleted |
| 4 | Migrate ~/.claude / ~/.codex content (own epic) | Phase 1 done | ~/.claude/ and ~/.codex/ contain only permitted files |

## Follow-up Beads Required

This ADR does not execute any implementation. The following beads
should be created to execute the decision:

1. **Phase 1 execution**: Move cld/cdx to `cognovis-library/bin/`,
   add `install-bin.sh`, run on this machine, update CLAUDE.md and
   ARCHITECTURE.md.
2. **Phase 2 execution (a)**: Verify content equivalence;
   uninstall `sussdorff-plugins` bundles; deregister marketplace.
3. **Phase 2 execution (b)**: Same for `cognovis-claude-code-plugins`.
4. **Phase 2 execution (c)**: Add `cognovis-library/scripts/bootstrap.sh`
   for new-machine fleet-wide essential install.
5. **Phase 3 execution** (optional, deferred): Archive / delete the
   two marketplace repos.
6. **Phase 4 epic**: Migrate residual `~/.claude/` and `~/.codex/`
   content to library-core repos (own epic with its own children).

The bead `claude-8u7c` (in the `~/.claude/` bd project) titled
"Migrate cld/cdx launchers to ~/.local/bin/" is **superseded** by
this ADR's Phase 1. claude-8u7c should be closed with a "superseded
by ADR-0002, see CL-7na + Phase 1 follow-up" note when the Phase 1
bead is filed.

The bead `claude-bpln` (XDG migration epic) remains valid for the
`~/.claude/` deployment target's XDG layout question (settings,
plugin cache, runtime state). It does **not** cover content
migration — that is Phase 4 of this ADR. claude-bpln should be
revised to reflect: spike claude-zkk5 confirmed `CLAUDE_CONFIG_DIR`
is NO-GO; the symlink-based approach is the sole viable path.

## Alternatives Considered

### Option A: Maintain ADR-0001's Hybrid

**Description**: Keep `core`, `beads-workflow`, `infra` bundles in
`sussdorff-plugins`. Retire `cognovis-marketplace`.

**Pros**: Less migration work. Preserves new-machine marketplace-UI
install affordance for fleet-wide essentials.

**Cons**: Two distribution mechanisms persist. The "keep in
marketplace" content is no longer unique (CL-8vb migrated it to
`cognovis/library-core`). New-machine install affordance is replaced
trivially by a bootstrap script.

**Rejected because**: The Hybrid's content-uniqueness premise no
longer holds; preserving two distribution paths for entirely
duplicated content is overhead without benefit.

### Option B: Selected — Full retirement + deployment-only harness dirs

See Decision section above.

### Option C: Move cld/cdx to a library-core repo

**Description**: Treat cld/cdx as content artefacts and host them in
`cognovis/library-core` (or `sussdorff/library-core`).

**Pros**: All Cognovis or personal content under one repo per
audience.

**Cons**: cld/cdx are not per-project artefacts. They invoke the
library, they are not consumed by it. Placing them in library-core
crosses the layer boundary.

**Rejected because**: Layering integrity. cld/cdx belong with the
distribution mechanism, not with the content.

### Option D: cld/cdx in `~/.claude/bin/` (original `claude-8u7c`)

**Description**: Per the existing XDG migration epic `claude-bpln`,
move cld/cdx into the personal config repo.

**Pros**: Already in flight.

**Cons**: `~/.claude/` is now formally a deployment target only
(Decision 3). cld/cdx need git review, team visibility, and
changelog discipline — characteristics of a tooling repo, not a
deployment target.

**Rejected because**: Conflicts with Decision 3.

### Option E: New `tools:` primitive type in library.yaml

**Description**: Extend `library.yaml` schema with a `tools:`
primitive. Register cld/cdx there. Install via
`/library use cld --target=~/.local/bin/`.

**Pros**: Unifies install model. cld/cdx become a normal library
artefact.

**Cons**: Schema extension; library-yaml validator changes; CL-wud
test updates. More work than `scripts/install-bin.sh`.

**Status**: **Deferred, not rejected.** Worth doing in a future
ADR once Phase 1 ships and we have data on whether cld/cdx benefit
from per-project vs fleet-wide install variants.

### Option F: `uv tool install` packaging

**Description**: Rewrite cld/cdx as Python tools, distribute via
`uv tool install`.

**Pros**: Modern packaging story; cross-platform; clean update path.

**Cons**: cld is non-trivial zsh integrating dolt, git, cmux,
worktree creation. Python rewrite is substantial work driven by
needs (cross-platform, complexity) not yet urgent.

**Rejected because**: Out of scope for retirement decision. Decision 4
codifies the deferral.
