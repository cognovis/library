# cognovis-claude-code-plugins Retirement Audit

**Date**: 2026-05-12
**Bead**: CL-ns6
**ADR**: docs/adr/canonical-library-architecture.md (ADR-0002 Phase 2b)

## Summary

1 bundle (`cognovis-workflow`) with 5 primitive artefacts audited.
All 5 artefacts have canonical equivalents in `cognovis-core` or `beads-workflow`.
The marketplace was **never formally registered** in `known_marketplaces.json` or
`installed_plugins.json` — no plugin uninstall step is required.
`library.yaml` `marketplaces:` section has no cognovis-marketplace entry — no YAML update needed.
ADR-0002 Phase 2b is complete: the cognovis-claude-code-plugins distribution path is retired.

---

## Registry State (Pre-Retirement)

| Registry File | cognovis-claude-code-plugins present? |
|---|---|
| `~/.claude/plugins/known_marketplaces.json` | NO — never registered |
| `~/.claude/plugins/installed_plugins.json` | NO — cognovis-workflow never formally installed |
| `library.yaml` `marketplaces:` | NO — never added |

**Conclusion**: The marketplace existed only as a local checkout at
`~/code/cognovis-marketplace/` used via direct path reference (not via plugin install).
No plugin uninstall, no JSON edits, and no YAML changes are required.

---

## Bundle: cognovis-workflow (v1.4.0)

### Artefact 1 — Skill: `beads`

| Field | Value |
|---|---|
| Marketplace path | `cognovis-workflow/skills/beads/SKILL.md` |
| Canonical location | `cognovis-core/.claude/skills/beads/SKILL.md` |
| Status | **SUPERSEDED** — canonical is newer (updated dispatch table, auto-routing, --full/--quick flags) |
| Action | None required — canonical version is authoritative and deployed |

Drift summary: marketplace version describes Phase 0–5 orchestration, spawning
`bead-orchestrator` directly. Canonical version adds auto-routing (quick-fix vs full
orchestrator), `--full`, `--quick` flags, and updated dispatch table.

### Artefact 2 — Skill: `epic-init`

| Field | Value |
|---|---|
| Marketplace path | `cognovis-workflow/skills/epic-init/SKILL.md` |
| Canonical location | `cognovis-core/plugins/beads-workflow/skills/epic-init/SKILL.md` |
| Status | **SUPERSEDED** — canonical is newer (adds `requires_standards: [english-only]`, user profile step, richer duplicate check) |
| Action | None required — canonical version is authoritative |

Drift summary: canonical adds a user-profile-read step before CLAUDE.md, extended
duplicate/overlap detection examples, and a `requires_standards` frontmatter field.

### Artefact 3 — Skill: `session-close`

| Field | Value |
|---|---|
| Marketplace path | `cognovis-workflow/skills/session-close/SKILL.md` + `handlers/` (4 files) |
| Canonical location | `cognovis-core/.claude/agents/session-close.md` (agent, not skill) |
| Status | **SUPERSEDED** — marketplace version is a skill stub; canonical is a full agent |
| Handlers | All 4 handler scripts (`beads-close.sh`, `changelog.sh`, `docs-check.sh`, `version.sh`) are byte-identical to `beads-workflow/skills/session-close/handlers/` |
| Action | None required — canonical agent is deployed to `~/.claude/agents/` |

Drift summary: the marketplace `SKILL.md` (142 lines at origin, 35 lines after CL-l22e
trimming) is a pure-trigger wrapper. The agent (`~/.claude/agents/session-close.md`)
contains all logic. Handlers are identical. No content is lost in retirement.

### Artefact 4 — Agent: `bead-orchestrator`

| Field | Value |
|---|---|
| Marketplace path | `cognovis-workflow/agents/bead-orchestrator.md` (268 lines) |
| Canonical location | `cognovis-core/.claude/agents/bead-orchestrator.md` (1235 lines) |
| Deployed to | `~/.claude/agents/beads-workflow/bead-orchestrator.md` (1235 lines) |
| Status | **SUPERSEDED** — marketplace version is the old Phase 0–5 orchestrator; canonical is the current Phase 0–16 full orchestrator |
| Action | None required — canonical is deployed and active |

Drift summary: the marketplace version is an early iteration covering only Phase 0–5
with basic claiming and implementation spawning. The canonical version adds Phase 6–16
(review, Codex adversarial, verification, MoC/E2E, UAT, constraints, changelog,
session-close), standards injection, metrics, and adversarial Axis B logic. The
marketplace version is fully superseded.

### Artefact 5 — Command: `workplan`

| Field | Value |
|---|---|
| Marketplace path | `cognovis-workflow/commands/workplan.md` |
| Canonical location | `cognovis-core/plugins/beads-workflow/skills/workplan/SKILL.md` |
| Status | **SUPERSEDED** — canonical adds `requires_standards: [english-only]`, `gather-data.sh` script, MoC/NLSpec scoring, richer prioritization table |
| Action | None required — canonical version is authoritative |

Drift summary: the marketplace version is a minimal `/workplan` command. The canonical
version promotes it to a skill with frontmatter, a `gather-data.sh` helper script,
MoC-table scoring (+1 for MoC, +1 for NLSpec), and updated scoring thresholds.

### Scripts: `cld.zsh` and `cld.ps1`

Already addressed in Phase 1 (CL-w4g). Canonical home is `cognovis-library/bin/cld`
(deployed to `~/.local/bin/` via `install-bin.sh`).

Drift between marketplace `cld.zsh` and `cognovis-library/bin/cld`:
- Marketplace version lacks: `--help` / `-h` flag, `--caveman` / `-c` mode,
  `-bq` / `--bead-quick`, `-bw` / `--bead-wave`, `-bl` / `--bead-label`,
  `-bi` / `--bead-ids` flags.
- Canonical version is a superset. No content is lost.

**Status**: SUPERSEDED — canonical is deployed and active.

---

## Follow-up Beads

All 5 artefacts are equivalent or superseded in the canonical location. No content
migration is required. No follow-up beads are needed for this marketplace.

(Contrast with CL-ast / sussdorff-plugins, which filed 7 follow-up beads for missing
artefacts. cognovis-marketplace had a smaller footprint of 5 artefacts already covered
by beads-workflow and cognovis-core.)

---

## Smoke Test

Verified post-retirement state:

| Check | Result |
|---|---|
| `~/.claude/plugins/installed_plugins.json` — no cognovis-workflow entry | PASS |
| `~/.claude/plugins/known_marketplaces.json` — no cognovis-claude-code-plugins entry | PASS |
| `library.yaml` `marketplaces:` — no cognovis-marketplace entry | PASS |
| `~/.claude/agents/beads-workflow/bead-orchestrator.md` present (1235 lines) | PASS |
| `~/.claude/agents/core/session-close.md` present | PASS |
| hooks fire at session start (bd-cache-invalidator.py, session-context.py) | PASS — verified by hook presence in `~/.claude/hooks/` |
| cognovis-workflow bundle not installed = no breakage risk | PASS |

**Overall smoke test result: PASS**

The cognovis-claude-code-plugins distribution path is fully retired. All canonical
artefacts are deployed from `cognovis-core` and `beads-workflow`. No breakage introduced.
