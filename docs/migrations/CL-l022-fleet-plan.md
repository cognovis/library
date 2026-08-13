# CL-l022 Fleet Migration Plan

## Purpose and boundary

This is a read-only migration plan for the repository-local Library environment
transition. It records the observed fleet and historical user-global Library
inventory as of 2026-08-13. It does not authorize an installation, deletion,
global-state change, or a change in another repository.

`cognovis-base` is published by `library-platform` as the fixed `library init`
baseline. Its direct roots are deliberately limited to:

- `cognovis-library-core:cognovis-beads` for the team Beads overlay;
- `cognovis-library-core:inject-standards` for explicit standards delivery; and
- `cognovis-library-core:ob-cli` for repository-scoped OpenBrain access; and
- `library-platform:library` for the project-installable Library recommendation
  skill.

The declared catalogs are pinned to `cognovis/library` commit
`00c43f828ca3cce7d29e949f44bced59c7e5e121` and `cognovis/library-core` commit
`5aa05ca2f5a45d09c15fddb73c69201a477579ee`. The resolved project closure is
exactly those four Skills. The core pin governs the source catalog content; a
later project-lock migration in that catalog does not change this Workspace pin.
OpenBrain MCP is intentionally not a Workspace root:
ADR-0012 names it an enumerated global bootstrap singleton. The baseline also
does not include a Python toolchain, FHIR capabilities, execution agents,
reviewers, launchers, or runtime configuration; each has repository-specific
scope or needs an explicit recommendation and confirmation.

## Catalog preservation receipt

The platform catalog retains every one of the 109 pre-existing skill names and
adds the project-installable `library` skill, for 110 names. Publication does
not remove or relocate a Skill source primitive.

## Repository inventory and disposition

| Git root | Beads | `.library.lock` | Disposition | Required owning-pack action |
| --- | --- | --- | --- | --- |
| `/Users/malte/code/library/meta` | yes | present | Baseline publisher; existing authoring and Python Workspaces remain deliberate additions. | Commit this catalog slice; decide whether to add `cognovis-base` in a later platform-only lock update. |
| `/Users/malte/code/library/cognovis-core` | yes | present | Active Cognovis catalog; baseline consumer candidate. | Run `library init`, inspect `library status --offline --json`, then review any additional catalog-owner roots before commit. |
| `/Users/malte/code/library/sussdorff-core` | yes | absent | Approved active fleet member. | Run the baseline `library init` in its own repository pack; preserve existing untracked Beads state. |
| `/Users/malte/code/library/cognovis-pi` | yes | present | Active Pi consumer; a committed lock already demonstrates Library consumption. | Run `library init` only after confirming coexistence with Pi-local extensions and uncommitted prototype changes. |
| `/Users/malte/code/open-brain` | yes | present | Active service/catalog and source of the bootstrap MCP singleton. | Run `library init` in its own worktree; retain the MCP bootstrap separately from project skills. |
| `/Users/malte/code/polaris` | yes | present | Active product repository. | Run `library init`, inspect status, then obtain confirmation for product/FHIR-specific recommendations. |

Repository discovery was limited to known active roots containing
`.beads/config.yaml`; it never reads derived Beads JSONL exports. The plan must
be extended before touching any additional repository.

## Historical global inventory disposition plan

The historical `~/.config/library/global.lock` is read-only migration input. At
inspection it held 11 requested roots and 106 receipts, including 28 Skill
receipts. It must not be copied into any repository. Its retained global state
is only ADR-0012's bootstrap contract:

| Global projection class | Disposition before removal |
| --- | --- |
| `library`, `cld`, `cdx` executables | Bootstrap; verify `uv tool install` ownership, not a Library primitive receipt. |
| Global `AGENTS.md`, Claude `CLAUDE.md`, launcher runtime configuration | Bootstrap; move to the explicit bootstrap manifest/receipt owned by CL-rm8o. |
| `mcp:open-brain` server registration | Bootstrap singleton; verify its supported Claude, Codex, and Pi boundary separately. |
| `mcp:markitdown` and `mcp:lsp` receipts | Ordinary non-bootstrap MCP projections; preserve until exact project replacement, archive, or unmanaged evidence exists. |
| 28 ordinary Skill receipts | Replace only after a repository-specific committed project lock proves ownership, or classify archive/unmanaged; do not remove a catalog entry. |
| 27 Agent, 31 Standard, 8 Script, 5 Model-standard, 1 Prompt, and 3 Runtime-config receipts | Same replacement/archive/unmanaged decision, keyed to exact receipt target and owner. No bulk deletion. |

The 11 historical requested roots (`claude-md-global`, `worktree-subagent-discipline`,
`review-governance`, `english-only`, `no-emoji`, `context-handoff`, `ccore`,
`executive-pack`, `fhir-publication-reviewer`, `fhir-ig-development`, and
`mcp-client-timeout`) are not a baseline selection. Each remains subject to the
exact projection disposition above.

## Per-repository execution receipt

Each owning repository pack must capture, after human confirmation where
additional recommendations are proposed:

```text
library init
library status --offline --json
git status --short
git diff -- .library.lock .gitignore
```

Commit only that repository's authored `.library.lock` and managed Gitignore
state through its own delivery boundary. Retain the command output with the
repository commit SHA. A healthy result covers supported Claude Code, Codex,
and applicable Pi projections; unsupported harness targets are not migration
evidence.

## Executed fleet receipts

The first migration pass produced the following repository-local commits. Each
lock retains its pre-existing requested roots and adds `cognovis-base`; a clean
baseline closure contains `library`, `cognovis-beads`, `inject-standards`, and
`ob-cli`. These commits are consumer evidence only after their repository-owned
delivery boundary has published them.

| Git root | Commit | Baseline receipt |
| --- | --- | --- |
| `/Users/malte/code/library/meta` | `4fd9a30f` | Existing `library-authoring` and `python-cli` roots retained; `cognovis-base` added and projections reconciled. |
| `/Users/malte/code/library/cognovis-core` | `5e9845ee` | Four baseline Skills; project projections clean. |
| `/Users/malte/code/library/sussdorff-core` | `48f22c8` | Four baseline Skills; first committed project lock and clean projections. |
| `/Users/malte/code/library/cognovis-pi` | `f72094c` | Existing `library-authoring` root retained; four baseline Skills added. |
| `/Users/malte/code/open-brain` | `d982ba6` | Four baseline Skills; 2,183 non-integration tests passed during commit. |
| `/Users/malte/code/polaris` | `fc685b62e` | Four baseline Skills; project projections clean and push checks passed. |

The rollout exposed and repaired two platform defects before fleet-wide use:
the root-level Library Skill is now explicitly installed as a single-file
bundle instead of copying the full platform repository, and fixed `library
init` resolves `cognovis-base` from the packaged tool catalog when the target
repository owns a different `library.yaml`.

Global Skill projections remain in place until all six commits are published
and their Workspace catalog pins resolve from those published sources. Removal
then targets only the 28 global Skill receipts and their recorded harness
bridges; it never deletes a Skill entry or source from a catalog.

## Residual decisions

1. Review repository-specific additions after each initialization; historical
   global receipts are not recommendations.
2. Create the explicit CL-rm8o bootstrap receipt/manifest before removing any
   matching global projection.
3. Apply the receipt-level decision in
   `docs/migrations/CL-l022-global-disposition.md`: only the 28 Library-owned
   global Skill projections are conditional removal candidates; the remaining
   78 receipts are retained as Bootstrap or deferred state.
