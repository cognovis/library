---
name: release-lifecycle
description: Repo-agnostic release lifecycle contract — bead metadata is release truth, pipelines supply evidence, release.version is write-once.
tags:
  - origin:original
  - tier:global
  - category:standard
---

# Release Lifecycle Contract

> Factual contract for [ADR-0008](../../docs/adr/intentional-release-lifecycle.md).
> Referenced by `bd` metadata usage and by the `cognovis-tools` `release.*`
> typed-tool schemas (`CL-ugwe.11`). This is the single source for the release
> metadata shape — it is NOT duplicated into `docs/schema/library.schema.json`.

## Lifecycle states

| State | Meaning | Source |
|---|---|---|
| `closed` | Implementation done. | bead status |
| release candidate | Closed AND `release_note.include = true` AND no `release.version`. | derived query |
| `released` | Included in a published artifact that passed all declared gates. | `release` metadata |

`closed` does not imply `released`. There is no separate `released` bead
status; released-state is the presence of `release.version` in metadata.

## Metadata schema

Two namespaces under bead metadata.

### `release_note` (author-supplied, inclusion intent)

| Field | Type | Required | Notes |
|---|---|---|---|
| `include` | bool | yes | `true` makes a closed bead a release candidate. |
| `section` | enum | yes | Changelog section: `added` / `changed` / `fixed` / `deprecated` / `removed` / `security`. |
| `summary` | string | yes | Short release-facing note (one line). |
| `audience` | enum | no | `developer` (default) / `operator` / `end-user`. |

### `release` (evidence; written only by `release.stamp`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | string | yes | Repo's declared scheme (CalVer/SemVer). **Write-once.** |
| `image_digest` | string | gate-dependent | e.g. `sha256:...`. |
| `released_at` | RFC3339 | yes | UTC timestamp the stamp ran. |
| `deployment_target` | string | gate-dependent | e.g. `demo.mira-pvs.de`. |
| `e2e_evidence` | string | gate-dependent | Artifact path or URL. |

Example:

```json
{
  "release_note": { "include": true, "section": "changed",
                    "summary": "Typed git.* tools", "audience": "developer" },
  "release": { "version": "2026.06.1", "image_digest": "sha256:...",
               "released_at": "2026-06-01T12:00:00Z",
               "deployment_target": "demo.mira-pvs.de",
               "e2e_evidence": "https://ci/.../e2e-123" }
}
```

## Per-repo declaration

Each repo declares two things (location: repo release config):

- **`version_scheme`**: `calver` | `semver`.
- **`required_gates`**: ordered list of gates that must have evidence before a
  bead is `released`. Each gate names the `release` field(s) it satisfies.

MIRA: `required_gates = [image_publish (image_digest), deploy
(deployment_target=demo.mira-pvs.de), e2e_smoke (e2e_evidence)]`.

## Invariants (enforced by `release.*`, not by the DB)

1. **`release.version` is write-once.** Once set, `release.stamp` treats a
   re-stamp of the same version + evidence as a no-op and refuses to overwrite
   with a different version. Corrections are explicit, audited metadata edits.
2. **Gate-guarded.** `release.stamp` refuses unless every entry in the repo's
   `required_gates` has its evidence field populated.
3. **Idempotent failure.** If publish/deploy/e2e fails, no `release.version` is
   written; candidate beads stay candidates; the run can be retried.
4. **Candidate set is derived**, never hand-maintained: closed ∧
   `release_note.include` ∧ ¬`release.version`.

## Typed-tool surface (`CL-ugwe.11`)

| Tool | Contract |
|---|---|
| `release.candidates` | Returns the derived candidate set. Read-only, `bd`-backed. |
| `release.stamp(version, evidence)` | Writes `release` metadata onto candidates after gate check. Enforces invariants 1-3. |
| `release.show(version)` | Returns beads + evidence for a version. Read-only. |

## Changelog generation

`release_note` across the released set is the source for generated release
notes. `cliff.toml` renders commit-derived material only; a rollout integrates
git-cliff into the release generator or documents why the bead-sourced section
is generated separately (ADR-0008 Decision 5). git-cliff is never release truth.

## Baseline backfill

On adoption, run a one-time backfill marking pre-existing closed beads as
`released` under a chosen cutoff/version so the candidate query starts clean.
