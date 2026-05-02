---
adr: "0001"
title: "Replace sussdorff-plugins marketplace with per-project /library use"
status: accepted
date: 2026-05-01
bead: CL-0va
epic: CL-36o
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
---

# ADR-0001: Replace sussdorff-plugins marketplace with per-project /library use

## Status

Accepted

## Context

After completing Wave 1 of the Library migration (CL-sxt, CL-4mt, CL-2x4), the completion
bead CL-8vb, and the catalog registration bead CL-yko, two artifact distribution mechanisms
now coexist:

1. **`sussdorff-plugins` marketplace** — a directory-backed marketplace pointing at
   `~/code/claude-code-plugins/`. It installs 8 category bundles globally (scope: user)
   into `~/.claude/plugins/cache/sussdorff-plugins/<bundle>/`. All 8 bundles are currently
   installed: `core`, `beads-workflow`, `infra`, `business`, `content`, `meta`, `medical`,
   `dev-tools`.

2. **`/library use <name>`** — per-project, on-demand artifact installation that pulls
   individual skills/agents/prompts into `.claude/skills/<name>/`, `.claude/agents/<name>.md`,
   or `.claude/commands/<name>.md`. The Library catalog (`library.yaml`) now contains 107
   registered entries: 57 skills, 38 agents, 12 prompts (as of CL-yko).

The name-collision policy (CL-b4o, `docs/policy/name-collision.md`) ensures that
project-local artifacts always win over user-global ones, so the two mechanisms can coexist
without runtime breakage. However, long-term architectural clarity requires a decision on
which mechanism is authoritative.

### Empirical data

| Fact | Value | Source |
|------|-------|--------|
| sussdorff-plugins bundles installed | 8 | `~/.claude/plugins/installed_plugins.json` |
| sussdorff-plugins source type | `directory:/Users/malte/code/claude-code-plugins` | `~/.claude/plugins/known_marketplaces.json` |
| Library catalog entries | 107 (57 skills + 38 agents + 12 prompts) | `library.yaml` post CL-yko |
| Artifacts classified `keep_in_plugin` | 30 | `docs/audit/skills-origin.json` |
| Artifacts classified `move_to_cognovis_library_core` | 77 | `docs/audit/skills-origin.json` |
| Artifacts classified `move_to_sussdorff_library_core` | 13 | `docs/audit/skills-origin.json` |
| Total classified artifacts | 169 | `docs/audit/skills-origin.json` |
| Known external users of sussdorff-plugins | 0 (Malte only) | Marketplace source is a local directory path |

The marketplace source being `directory:/Users/malte/code/claude-code-plugins` (a local path)
proves that `sussdorff-plugins` is not published to any external registry. Only the machine
that owns that path can install from it. No other users can or do depend on it.

## Decision

**Option 3 (Hybrid)**: The marketplace stays for fleet-wide always-on bundles; `/library use`
becomes the exclusive install path for project-specific artifacts.

Specifically:

| Bundle | Fate | Rationale |
|--------|------|-----------|
| `core` | **Keep in marketplace** | Cross-cutting standards, dev-tools hooks, and core utilities needed in every session. Installing per-project would create 15+ redundant copies with no benefit. |
| `beads-workflow` | **Keep in marketplace** | The orchestrator runtime (`codex-exec.py`, `metrics-*.py`, `claim-bead.py`, etc.) must be available globally for the `cld -b <id>` workflow to function. It is not a per-project concern. |
| `infra` | **Keep in marketplace** | Infrastructure tooling (chezmoi, dolt, server management) applies across all machines, not per project. |
| `business` | **Retire from marketplace → /library use** | Business skills (CRM, offers, project management) are project-specific. The medical project must not receive LinkedIn or Angebotserstellung by default. |
| `content` | **Retire from marketplace → /library use** | Content creation skills are domain-specific. Projects opt in via `/library use`. |
| `meta` | **Retire from marketplace → /library use** | Meta-skills (agent creators, skill creators) are used in specific contexts, not always-on. |
| `medical` | **Retire from marketplace → /library use** | Medical domain skills must not install globally for non-medical projects. Explicit project opt-in is a safety requirement. |
| `dev-tools` | **Conditional keep** | The base dev-tools bundle (playwright, browser tools) stays in the marketplace. Codex-specific overlays move to `/library use`. Review after Phase 1 migration completes. |

This is the "Hybrid" option from the Alternatives Considered section, refined by empirical data.

## Rationale

### Why not Option 1 (full retirement)?

The `~/.claude/plugins` surface is the only mechanism Claude Code's UI exposes for
one-time global installs. Retiring the marketplace entirely would:
- Remove the onboarding affordance for `core` and `beads-workflow` (every new machine
  would need a multi-step manual setup)
- Require per-project boilerplate for utilities that are genuinely fleet-wide

The audit data confirms 30 artifacts are correctly classified `keep_in_plugin` — these
are the exact artifacts backing `core`, `beads-workflow`, and `infra` bundles.

### Why not Option 2 (keep marketplace, drop /library use)?

The Library's per-project model was built specifically to solve the heterogeneous-project
problem: a medical project must not get the LinkedIn skill. The marketplace cannot express
this constraint — bundles are all-or-nothing at install time. Dropping `/library use`
defeats the entire CL-36o epic.

### Why not Option 4 (meta-plugin indirection)?

Indirection adds cognitive overhead without benefit. Users who open the Claude Code
plugin manager and see "sussdorff-plugins" installing zero artifacts would file confusion
reports. The meta-plugin pattern is useful for onboarding strangers to a new ecosystem,
not for a single-user local directory marketplace.

### Why Hybrid works here

The key insight from the audit data:
- 30 artifacts are `keep_in_plugin` → these are the fleet-wide always-on category
- 77+13 = 90 artifacts are `move_to_*_library_core` → these are project-specific content
- The 30:90 ratio maps cleanly to marketplace:per-project

The name-collision policy (project-local wins) ensures the transition is safe: as projects
adopt `/library use` for business/content/meta/medical skills, those project-local installs
automatically shadow any residual marketplace versions. No hard cutover is needed.

## Migration Sequence

Migration proceeds in three phases. No concrete dates — phases gate on completion
criteria, not calendar time.

### Phase 1: Per-project opt-in (no marketplace changes)

**Goal**: Projects start using `/library use` for project-specific skills. Marketplace
bundles remain installed and provide the safety net.

**Trigger for starting**: CL-yko complete (done — 107 catalog entries registered).

**Actions**:
1. For each active project, audit which business/content/meta/medical skills are in use.
2. Run `/library use <name>` for each needed skill in that project's repo.
3. Verify project-local install shadows marketplace version (no behavioral change expected
   per name-collision policy).
4. Document in each project's CLAUDE.md which Library skills are installed.

**Name-collision handling during this phase**:
- Both marketplace bundle and project-local install may coexist.
- Project-local wins per `docs/policy/name-collision.md` Decision 1.
- No explicit uninstall of marketplace versions yet.
- Run `bd show CL-b4o` smoke tests to verify no regressions.

**Completion criterion**: All active projects have a `/library use` manifest for their
domain-specific skills.

### Phase 2: Marketplace bundle cleanup

**Goal**: Remove business, content, meta, medical bundles from the marketplace.

**Trigger for starting**: Phase 1 completion criterion met AND all projects verified.

**Actions**:
1. For each of the four bundles to retire: verify no project depends on the marketplace
   version (i.e., every project that uses any skill from the bundle has a project-local
   install).
2. Run `plugin uninstall business@sussdorff-plugins` (and content, meta, medical).
3. Verify no session-start errors. If any: re-install the affected bundle and create a
   follow-up bead.
4. Update `library.yaml` `marketplaces:` section to remove sussdorff-plugins entries for
   retired bundles (follow-up bead — requires schema serialization per CLAUDE.md
   conventions).

**dev-tools review**: Assess whether the base dev-tools bundle can also be retired.
If Codex-specific overlays have been moved to `/library use`, retire the bundle. If
still needed fleet-wide, keep.

**Completion criterion**: `installed_plugins.json` shows no `business`, `content`, `meta`,
or `medical` bundles from `sussdorff-plugins`.

### Phase 3: Marketplace source migration (long-term)

**Goal**: `sussdorff-plugins` marketplace source migrates from local directory to a proper
Git repository, or is deregistered.

**Trigger**: When `core`, `beads-workflow`, and `infra` bundles are stable and rarely
change, OR when the machine layout changes (e.g., new development machine).

**Actions**:
1. Publish `core`, `beads-workflow`, and `infra` bundle contents to a public/private Git
   repository.
2. Update `known_marketplaces.json` source from `directory:` to `github:`.
3. Optionally: convert to a meta-plugin (Option 4 for the remaining fleet-wide bundles)
   for cleaner onboarding.

**This phase is optional** — the local directory source works correctly as-is for a
single-developer setup.

## Name-Collision Handling During Transition

The transition is safe because of `docs/policy/name-collision.md`:

| Scenario | Behavior | Required action |
|----------|----------|-----------------|
| Skill exists only in marketplace bundle | Marketplace version loads | None — will be shadowed when project installs via `/library use` |
| Skill installed via `/library use` AND in marketplace bundle | Project-local wins (Decision 1) | None — this is the intended coexistence state |
| Skill removed from marketplace but project-local exists | Project-local continues to work | No action needed — removal is safe |
| Skill removed from marketplace, no project-local | Skill becomes unavailable | Must ensure project-local install before retiring the bundle (Phase 1 gate) |
| Cross-harness (Claude Code + Codex) | Bridge symlink handles this | `/library use` with `harness: both` creates symlink automatically |

**Recommendation during Phase 1**: Do not uninstall any marketplace bundles. Let the
project-local installs accumulate. The Phase 1 completion criterion (every active project
has a `/library use` manifest) is the gate. Only after that gate: Phase 2 uninstalls.

## Rollback Plan

| Scenario | Recovery action |
|----------|----------------|
| Phase 1 in progress, project-local install breaks a skill | `plugin install <bundle>@sussdorff-plugins` restores the marketplace version; project-local is still there but uninstall it if needed |
| Phase 2 bundle removal breaks something | `plugin install <bundle>@sussdorff-plugins` — reinstall the retired bundle. The marketplace source (`directory:/Users/malte/code/claude-code-plugins`) is preserved and available at all times |
| Phase 2 and `claude-code-plugins` directory has moved | Update `known_marketplaces.json` source path. No git history is lost — this is a local directory reference, not a registry entry |
| Phase 3 migration fails | Revert `known_marketplaces.json` to `directory:` source. The content was never deleted, only the pointer changed |

**Key safety property**: `sussdorff-plugins` will NOT be deregistered as a marketplace
source until Phase 3 is explicitly started. Even after Phase 2 bundle retirement, the
marketplace registration remains so reinstallation is a single command.

## Communication

**Who uses `sussdorff-plugins` outside of Malte**: Nobody.

Evidence: The marketplace source is `directory:/Users/malte/code/claude-code-plugins` — a
local filesystem path that does not resolve on any other machine. Any external user who
added this marketplace would get a "path not found" error on install. The marketplace was
never published to a public registry. No follow-up communication required.

## Codex Parallel

The same logic applies to Codex's plugin equivalent with one difference: Codex uses
`.codex/agents/<name>.toml` (per-repo) or `~/.codex/agents/<name>.toml` (global/personal)
rather than a marketplace bundle model.

| Library mechanism | Claude Code equivalent | Codex equivalent |
|-------------------|----------------------|------------------|
| `marketplace bundle` | `~/.claude/plugins/cache/<marketplace>/<bundle>/` | `~/.codex/agents/<name>.toml` (global) |
| `/library use <name>` | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` (via bridge symlink) |

**Decision**: The Codex parallel is structurally different enough that no additional ADR is
needed at this time. The `/library use` dual-install (`harness: both`) already handles Codex
via bridge symlinks (see `docs/policy/name-collision.md` Decision 2). As Codex plugin support
matures, a separate ADR may be warranted (see bead `CL-tap` for the `cdx` wrapper work).

## Success Criteria

The decision is successfully implemented when all of the following are true:

1. `installed_plugins.json` shows `business`, `content`, `meta`, `medical` bundles
   absent from `sussdorff-plugins` entries.
2. All active projects that used those bundles have a documented `/library use` manifest
   in their CLAUDE.md or `.claude/settings.json`.
3. No session-start errors related to missing skills in any active project.
4. `core`, `beads-workflow`, and `infra` bundles remain installed and functional.
5. `library.yaml` `marketplaces:` section updated to reflect retired bundles (or a
   new bead tracks this).
6. This ADR is linked from `docs/ARCHITECTURE.md`.

## Deprecation Timeline

Migration proceeds in phases gated on completion criteria (not calendar dates, per
project convention). The phases are:

| Phase | Name | Gate to start | Gate to complete |
|-------|------|---------------|-----------------|
| 1 | Per-project opt-in | CL-yko done (complete) | All active projects have /library use manifests |
| 2 | Bundle retirement | Phase 1 gate met + all projects verified | business/content/meta/medical uninstalled from marketplace |
| 3 | Source migration (optional) | `core`/`beads-workflow`/`infra` stable + machine layout change | Local directory source replaced or deregistered |

Phase 1 can start immediately. Phases 2 and 3 are follow-up beads.

## Follow-up Beads Required

This ADR does not execute any implementation. The following beads should be created to
execute the decision:

1. **Phase 1 execution bead**: For each active project, run `/library use` for
   business/content/meta/medical skills. Document manifests.
2. **Phase 2 execution bead**: Uninstall retired bundles after Phase 1 gate met.
3. **library.yaml marketplaces: update bead** (schema-serialized — depends on Phase 2 bead,
   no parallel edits to `marketplaces:` section per CLAUDE.md conventions).

## Alternatives Considered

### Option 1: Retire sussdorff-plugins entirely

**Description**: Stop using the marketplace bundle mechanism entirely. Install everything
via `/library use`.

**Pros**: Single distribution mechanism; no precedence ambiguity; clean mental model.

**Cons**: `~/.claude/plugins` is the only surface Claude Code's UI exposes for global
installs. `core` and `beads-workflow` are genuinely fleet-wide — per-project installation
of these would create 15+ redundant copies and require per-project boilerplate for
fundamentals like `bd` commands and the beads orchestrator runtime.

**Rejected because**: 30 artifacts are correctly classified `keep_in_plugin` in the audit.
Those 30 back the fleet-wide bundles. Full retirement would break the development workflow
on new machines.

### Option 2: Keep marketplace, drop /library use

**Description**: Abandon the Library migration. Revert to marketplace-only distribution.

**Pros**: Zero migration cost. No per-project manifests to maintain.

**Cons**: Defeats the entire CL-36o epic. Cannot express per-project constraints (medical
project must not get LinkedIn skill). Bundle-level granularity is too coarse for a
heterogeneous project portfolio.

**Rejected because**: The heterogeneous project problem (business vs medical vs infra) is
real and the marketplace has no solution for it.

### Option 3: Hybrid (selected)

See Decision section above.

### Option 4: Meta-plugin

**Description**: `sussdorff-plugins` becomes a thin marketplace that only installs the
`/library` skill itself. All subsequent artifact installs go through `/library use`.

**Pros**: Keeps the Claude Code plugin manager UI affordance for first-time setup on a
new machine.

**Cons**: Indirection — users see "sussdorff-plugins" in the marketplace but it brings
no skills. Creates confusion. Adds an install step (first install meta-plugin, then use
library) where today there is one step (install marketplace bundle).

**Rejected because**: The single-developer context makes the onboarding UX argument
weak. Option 3 retains the useful bundles directly without the indirection layer.
