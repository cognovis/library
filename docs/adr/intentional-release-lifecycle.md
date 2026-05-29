---
adr: "0008"
title: "Intentional release lifecycle: beads are release truth, pipelines are evidence"
status: proposed
date: 2026-05-29
bead: "CL-khyy.1"
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0006", "0007"]
---

# ADR-0008: Intentional release lifecycle

## Status

Proposed. This ADR locks the repo-agnostic release vocabulary, invariants, and
the `cliff.toml` role. It implements nothing. The factual contract (metadata
schema, lifecycle states, gate-declaration shape) lives in the companion
standard `standards/release/release-lifecycle.md`; the typed-tool surface that
operates on it is built under `CL-ugwe.11` (`release.*` in cognovis-tools)
against this contract.

## Context

Several Cognovis repositories already carry `cliff.toml`, but a commit-derived
changelog cannot answer the questions that matter for an intentional release:
*did this bead make it into a published image? which deploy ran? what e2e
evidence exists?* Commits and tags carry neither inclusion nor deployment
evidence.

Beads already carry the unit of work and its closure. Release pipelines carry
artifact and deployment evidence. The lifecycle must combine the two rather
than silently elect one as truth. The durable rule must be repo-agnostic:
ordinary pushes *verify*; an explicit release trigger *publishes*; beads are
marked *released* only after the artifact exists and any repo-specific
deployment / e2e gate passes.

This ADR also feeds ADR-0007: release truth stored as bead metadata is only
trustworthy if it is mutated through a closed, server-validated surface. The
`release.*` family of the `cognovis-tools` `library-tool-surface` server is
that surface; its safety property (closed catalog, write-once) is what makes
"metadata is the source of truth" hold.

## Decision

### Decision 1: Three separate lifecycle concepts

`closed`, `release candidate`, and `released` are distinct and ordered:

- **closed** — implementation is done (the existing bead status). Says nothing
  about shipping.
- **release candidate** — a closed bead eligible for the next release: it has
  `release_note.include = true` and no `release.version` yet.
- **released** — included in a published artifact that passed the repo's
  release gates; recorded by `release.*` metadata on the bead.

`closed` does NOT imply `released`.

### Decision 2: Bead metadata is release truth; tags and changelog are views

The source of truth for release inclusion and release evidence is **bead
metadata** (`release_note` + `release`, see the standard). Git tags and the
generated `CHANGELOG.md` are **outputs/views** rendered at release time, never
inputs. No new bead status is introduced — released-state lives in metadata;
labels are optional, for filtering only.

### Decision 3: Release candidate set is derived, not hand-listed

The candidate set for a release is exactly: **closed beads with
`release_note.include = true` and no `release.version`.** It is a deterministic
query over bead state, not a manually maintained list.

### Decision 4: Versioning is an explicit trigger; push/PR only verifies

Push and PR runs **verify** (build, test, lint). They do **not** bump a
version or publish an artifact. Versioning and publication happen only on an
**explicit release trigger**. The repository **declares its scheme**
(CalVer or SemVer); the release trigger takes the explicit version, and the
helper MAY suggest or validate it against the scheme — it does not invent it
from commits.

### Decision 5: `cliff.toml` is hybrid, not replaced and not primary

`cliff.toml` remains the repository-local renderer/config for commit-derived
changelog material. Bead metadata is the source of release inclusion and
release evidence. A repo rollout MUST either integrate git-cliff into the
release generator or explicitly document why the bead-sourced section is
generated separately. git-cliff is never the release source of truth — it sees
only commits and cannot know image, deploy, or e2e facts.

### Decision 6: Release gates are repo-specific and declared

Each repo declares its required release gates. Marking beads `released`
requires evidence for every declared gate. **MIRA's** required gates are:
image publish + deploy to `demo.mira-pvs.de` + e2e smoke. The repo-agnostic
lifecycle/vocabulary (Decisions 1-5, 7-8) is universal; the gate set is the
repo-specific configuration the `release.*` tools read.

### Decision 7: Failure leaves beads unreleased; release runs are idempotent

If publish, deploy, or e2e fails, the candidate beads **remain unreleased** (no
partial-release state). A release run can be re-invoked and is **idempotent**:
re-stamping the same version with the same evidence is a no-op.

### Decision 8: Historical backlog is baselined, not retro-released

Old closed beads are not swept into release notes. A one-time **baseline
backfill** marks pre-existing closed beads as `released` under a chosen
cutoff/version, so the candidate query starts clean.

### Decision 9: The contract is consumed by `cognovis-tools` `release.*`

This is the ADR-0007 bridge. The lifecycle is operated through the
`library-tool-surface` server, and the contract carries three tool-level
invariants:

1. **Schema location.** The `release_note` / `release` metadata schema lives in
   `standards/release/release-lifecycle.md` and is referenced by both `bd`
   metadata usage and the `release.*` MCP tool schemas. It is **not** duplicated
   into `library.schema.json`. Single source.
2. **Named surface.** The decisions imply a minimal closed surface:
   `release.candidates` (the Decision 3 query), `release.stamp(version,
   evidence)` (writes `release.*` onto candidate beads), `release.show(version)`
   (the view). `CL-ugwe.11` implements these; tool naming is fixed here so it is
   not re-derived.
3. **Write-once + gate-guarded.** `release.version` on a bead is **write-once,
   set only via `release.*`** — this is the integrity guarantee behind
   Decision 2 and the closed-catalog safety property of ADR-0007. `release.stamp`
   refuses unless every declared gate (Decision 6) has evidence; on failure beads
   stay unreleased (Decision 7); re-runs are no-ops.

## Metadata contract (summary)

Canonical definition in the standard. Shape:

```json
{
  "release_note": {
    "include": true,
    "section": "changed",
    "summary": "Short release-facing note",
    "audience": "developer"
  },
  "release": {
    "version": "2026.06.1",
    "image_digest": "sha256:...",
    "released_at": "2026-06-01T12:00:00Z",
    "deployment_target": "demo.mira-pvs.de",
    "e2e_evidence": "artifact-or-url"
  }
}
```

`release_note` is author-supplied at/after closure (inclusion intent).
`release` is written only by `release.stamp` (evidence), and `release.version`
is write-once.

## Alternatives Considered

1. **Repository-specific release rules only.** Rejected — agents re-derive
   version/changelog behavior differently per repo.
2. **Replace git-cliff everywhere.** Rejected — existing `cliff.toml`
   rendering/grouping is useful; only its claim to release truth is removed.
3. **Git tags alone as release truth.** Rejected — tags carry neither bead
   inclusion nor deployment/e2e evidence.
4. **A new `released` bead status.** Rejected — duplicates metadata that must
   carry evidence anyway; status cannot hold `image_digest`/`e2e_evidence`.

## Consequences

- Release notes become a function of bead metadata; the changelog is generated
  output. Authors set `release_note.include` deliberately.
- `release.*` tools (`CL-ugwe.11`) gain a locked contract to implement against;
  `CL-ugwe.11` depends on this ADR.
- Each adopting repo must declare its scheme (Decision 4) and gate set
  (Decision 6), and run a baseline backfill (Decision 8) once.
- `cliff.toml` stays; its role narrows to commit-derived rendering.

## Rollback Plan

| Scenario | Recovery |
|---|---|
| Bead-sourced changelog proves worse than git-cliff for a repo | That repo documents the bypass (Decision 5) and renders from git-cliff only; the metadata contract still records released-state. |
| `release.stamp` write-once blocks a legitimate re-version | Correction is an explicit, audited metadata edit; the write-once rule is enforced by `release.*`, not the DB, so an operator override path exists. |
| Gate evidence schema too strict for an early repo | `release.e2e_evidence` accepts an artifact-or-URL string; gates are per-repo declared, so a repo can declare a minimal gate set initially. |

## Success Criteria

1. `closed` / `release candidate` / `released` defined as separate concepts.
2. Required `release_note` + `release` metadata fields defined (in the standard).
3. Push/PR verification defined as non-versioning, non-publishing.
4. Failure behavior leaves beads unreleased; release runs idempotent.
5. `cliff.toml` integration-or-bypass rule defined.
6. MIRA and Polaris named as first rollout targets; others later.
7. The three cognovis-tools locks (schema location, named surface, write-once +
   gate-guarded) are stated so `CL-ugwe.11` implements against a fixed contract.

## Cross-References

- `standards/release/release-lifecycle.md` — the factual contract (states,
  metadata schema, gate-declaration shape, invariants).
- [ADR-0007](library-tool-surface-mcp.md) — `library-tool-surface` species;
  `release.*` is one of its tool families. Write-once is the closed-catalog
  safety property.
- [ADR-0006](workflow-primitive.md) — release generation can be a workflow.
- Epic `CL-khyy` (cross-repo release standard); `CL-khyy.1` (this decision);
  `CL-ugwe.11` (`release.*` implementation, depends on this ADR).
- Rollout targets: MIRA, Polaris first.
