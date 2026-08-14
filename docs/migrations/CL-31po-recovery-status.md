# CL-31po Repository-Local Cutover Recovery Status

## Evidence boundary

This report replaces worktree-local CL-l022 receipts as the current fleet and
global-disposition evidence. It records read-only probes run from the CL-31po
platform candidate on 2026-08-14. Canonical repositories were not modified.
The real Bootstrap migration, fleet materialization, backup, and global Skill
cutover have not been performed.

The candidate exposes one narrow operation:

```text
library bootstrap cutover-skills \
  --fleet-manifest <approved-fleet.json> \
  --repository <canonical-git-root> [--repository <canonical-git-root> ...] \
  --backup <new-backup-directory> \
  [--apply] \
  --json
```

The repository list is exact and explicit; the operation performs no repository
discovery. The required fleet manifest is the operator approval record. It names
`CL-31po`, the approver and approval time, and every approved repository's
absolute path, canonical branch, published commit, and remote. The command
requires exact set equality between the manifest and repeated `--repository`
arguments. Each checkout must serve the approved commit on its canonical branch,
track the approved remote branch, and match `git ls-remote` before cutover can
continue.

Without `--apply` the command is audit-only. With `--apply`, it checks the same
preconditions while holding the global lock, creates and verifies a checksummed
backup, then checks repository health, the unchanged fleet approval digest, and
Skill ownership again immediately before removing exact Skill receipt targets.
A transaction failure restores the original targets and global lock bytes.

The manifest contract is:

```json
{
  "schema_version": 1,
  "bead_id": "CL-31po",
  "approval": {
    "approved_by": "operator identity",
    "approved_at": "RFC 3339 timestamp"
  },
  "repositories": [
    {
      "path": "/absolute/canonical/repository",
      "branch": "main",
      "published_commit": "40-character commit SHA",
      "remote": "origin"
    }
  ]
}
```

## Mutable machine state

The platform catalog contains exactly 110 distinct Skill names. The current
global lock contains 103 receipts:

| Type | Count | Cutover disposition |
| --- | ---: | --- |
| Skill | 27 | Conditional removal after every gate passes. |
| Agent | 27 | Retain. |
| Standard | 31 | Retain. |
| Script | 6 | Retain. |
| Model standard | 5 | Retain. |
| Prompt | 1 | Retain. |
| Runtime config | 3 | Retain. |
| MCP | 3 | Retain; OpenBrain remains the enumerated Bootstrap singleton. |

The installer-managed catalog-source registry and Bootstrap manifest are both
absent at `~/.config/library/catalog-sources.json` and
`~/.config/library/bootstrap.json`. This alone blocks cutover. The 27 current
Skill receipt IDs are:

```text
skill:worktree-cleanup
skill:cognovis-beads
skill:cmux-workspace
skill:intake
skill:inject-standards
skill:workplan
skill:session-close
skill:bead-implementation-loop
skill:compound
skill:acpx-dispatch
skill:bead-execution-loop
skill:cmux
skill:cmux-bead-dispatch
skill:parallelize
skill:council
skill:bug-triage
skill:bead-reviewer
skill:skill-forge
skill:agent-forge
skill:standard-forge
skill:script-forge
skill:hook-forge
skill:context-handoff
skill:executive-pack
skill:fhir-ig-development
skill:fhir-emission
skill:aidbox-ig-development
```

This list is evidence, not standing deletion authority. The operation reloads
the lock and proves every target again immediately before backup.

The candidate's read-only ownership audit currently classifies 16 of the 27
Skill receipts as exact and blocks 11. Three recorded Skill directories
(`cognovis-beads`, `acpx-dispatch`, and `bead-execution-loop`) contain nested
content absent from their receipts. Eight Skills have an unrecorded projection
under `~/.codex/skills/`: `cmux-workspace`, `bead-implementation-loop`, `cmux`,
`skill-forge`, `agent-forge`, `standard-forge`, `script-forge`, and
`hook-forge`. The cutover retains all 11 until their ownership is reconciled;
it does not infer deletion authority from their names or other harness targets.

## Canonical fleet snapshot

| Canonical Git root | Main SHA | Git status entries | Candidate Workspace result | Current disposition |
| --- | --- | ---: | --- | --- |
| `/Users/malte/code/library/meta` | `27ae17a0bd2a` | 0 | blocked | Eleven platform Skill/Standard targets are drifted. |
| `/Users/malte/code/library/cognovis-core` | `daf10eb59fc0` | 0 | converged | Projection state converges and the canonical checkout is clean; machine Bootstrap and complete catalog observation remain unavailable. |
| `/Users/malte/code/library/sussdorff-core` | `e7bef872ac72` | 0 | blocked | The four baseline Skill targets are drifted or absent. |
| `/Users/malte/code/library/cognovis-pi` | `71a5360a3010` | 4 | blocked | Four baseline Skills are drifted or absent and retired Cursor receipts lie outside current managed roots; preserve the user changes. |
| `/Users/malte/code/open-brain` | `facf2f03e8fe` | 0 | blocked | The four baseline Skill targets are drifted or absent. |
| `/Users/malte/code/polaris` | `4d3cb02b1fa9` | 0 | blocked | The four baseline Skill targets are drifted or absent. |

The current committed locks remain desired-state evidence. They are not proof
that ignored projections exist in canonical checkouts. Only a clean canonical
checkout with `cognovis-base` registered, converged Workspace status, healthy
repository status, verified catalog pins, clean managed Git state, and no
unmanaged target can pass the cutover gate.

## Candidate verification

The final repair candidate verification on 2026-08-14 produced:

- 18 passing transactional cutover tests, including repository-health refusal,
  drift and unmanaged-content refusal, exact Skill/bridge identity checks,
  linked-worktree refusal, canonical branch and published-remote verification,
  fleet-manifest equality and post-backup digest revalidation, backup-path
  overlap refusal, rollback restoration, and repository and Skill-ownership
  revalidation immediately before deletion;
- 222 passed and 1 skipped across the expanded Bootstrap, packaging, init,
  status, Workspace, Gitignore, source-pin, launcher, and cutover suite;
- 1951 passed, 72 skipped, and 29 failed in the raw full candidate suite. One
  failure was the known order-dependent provider-publication test and passed
  immediately in isolation;
- the remaining 28 stable candidate failures match the detached `origin/main`
  comparison subset exactly: 28 failed, 163 passed, and 28 skipped on both
  candidate and base;
- the first cold change review blocked on four safety gaps. The bound repair
  review confirmed all four were substantively repaired and identified stale
  evidence plus missing direct probes. The final-round repair added the four
  probes above and refreshed this report; the two-round high-assurance contract
  delivers that final repair without a third review;
- clean `git diff --check` output and clean Ruff checks for the new cutover and
  local-Git modules and their regression tests. The legacy `scripts/library.py`
  entrypoint also passes Ruff with its pre-existing `E402` and compatibility
  import exceptions;
- a real audit-only invocation with all six canonical repository paths stopped
  at the missing Bootstrap manifest with exit 2, returned `repositories: []`,
  and created no backup path. It used an explicitly non-authoritative
  verification manifest and omitted `--apply`.

No result above authorizes operational rollout. The platform candidate remains
unpublished, and no real Bootstrap installation, fleet materialization, backup,
or global Skill cutover has occurred.

## Guard order

The final operational order remains:

1. publish the reviewed platform candidate;
2. install the repaired control plane, Bootstrap manifest, and catalog-source
   registry;
3. materialize `cognovis-base` in every approved canonical repository without
   overwriting user changes;
4. verify exact repository and Workspace health for the explicit fleet list;
5. verify all 110 catalog Skill names and every global Skill receipt target,
   including bridges, drift, and unrecorded nested content;
6. create and validate the backup of the global lock and every removal root;
7. remove only Skill projections and Skill records from the global lock;
8. prove zero global Skill receipts, 110 catalog Skills, ready OpenBrain
   Bootstrap, and unchanged non-Skill receipts.

Any failure through step 6 occurs before global deletion. Any transactional
failure in steps 7-8 restores the original target trees, bridges, and global
lock from the verified backup.
