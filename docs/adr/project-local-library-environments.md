---
adr: "0012"
title: "Repository-local Library environments and an explicit global bootstrap"
status: accepted
date: 2026-08-13
bead: CL-rm8o
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
amends: ["0002", "0003", "0010", "0011"]
related_adrs: ["0002", "0003", "0010", "0011"]
---

# ADR-0012: Repository-local Library environments and an explicit global bootstrap

## Status

Accepted as the replacement for user-global Library artifact installation. This
ADR amends ADR-0002, ADR-0003, ADR-0010, and ADR-0011 wherever they authorize a
global primitive lock, direct global roots, a global Workspace lobby, or
Library-managed Cursor, OpenCode, or Antigravity projections. Their source,
cache, ownership, provider, and reconciliation decisions otherwise remain in
force.

Implementation is tracked by CL-rm8o. Fleet migration and publication of
`cognovis-base` are tracked separately by CL-l022. CL-1les is a prerequisite for
the managed-Gitignore part of `library init` and `library status`.

## Context

The user-global Library scope is no longer small enough to act as a deliberate
baseline. Its lock contains more than one hundred materialized receipts spanning
Skills, Agents, Standards, Scripts, MCP servers, runtime configuration, prompts,
and model standards. A primitive installed there becomes ambient in every
repository even when only one project needs it. That weakens reproducibility,
inflates harness discovery and context surfaces, and makes removal a machine-wide
decision instead of a repository decision.

Workspace desired state already provides the right ownership and reconciliation
model. The missing constraint is that normal desired state belongs to a Git
repository. A developer should opt a repository into a small shared baseline and
then deliberately add domain- or tool-specific capabilities there. Historical
global installation is useful migration evidence, but it is not evidence that
every receipt belongs in every repository.

The supported harness set has also narrowed. The Library platform now targets
Claude Code, Codex, and Pi through the sibling `cognovis-pi` project. Cursor,
OpenCode, Antigravity, and other experimental projections add implementation and
documentation surface without an active consumer.

The Library control plane itself must remain available before a repository has a
Library skill. That bootstrapping concern is distinct from Library artifact
desired state and must not recreate a generic global scope under another name.

## Decision

### Decision 1: Artifact desired state is repository-local

All directly requestable Library artifact primitives and all Library Workspaces
are installed and owned through `<git-root>/.library.lock`. Lifecycle commands
resolve one Git top-level and may only write project-local targets belonging to
that root. There is no user-global primitive installation scope and no global
Workspace lobby.

An explicit `--scope global` on a primitive, Workspace, sync, audit, status, or
related lifecycle command is rejected at a shared pre-mutation boundary. The
failure is deterministic in human and JSON modes. `--scope project` may remain
as a compatibility spelling, but it conveys no additional capability and may be
removed after callers migrate.

The final architecture has no authoritative
`~/.config/library/global.lock`. During migration that file is read-only
inventory. It grants neither desired-state authority nor permission to copy its
contents into a repository.

### Decision 2: Bootstrap is an enumerated product contract

Global state exists only where the product cannot make the repository usable
without it. The bootstrap allowlist is:

- the Python `library` executable;
- the `cld` and `cdx` launchers;
- the global `AGENTS.md` instruction entrypoint and Claude's importing
  `CLAUDE.md` entrypoint;
- launcher runtime configuration required before a repository projection can be
  loaded; and
- the OpenBrain MCP server, as one explicitly accepted user-global singleton.

Bootstrap is not a Library primitive scope. No normal
`library <primitive> use --scope global` path installs these targets, and no
global primitive lock owns them. Bootstrap installation has its own exact
receipts or equivalent product-owned manifest so status and uninstall can
distinguish its allowlisted targets from historical Library projections.

The Library Skill is not bootstrap state. `library init` installs it through
the project `cognovis-base` Workspace. OpenBrain Skills are likewise project
members; only the MCP server remains global.

### Decision 3: The Library CLI is a uv-installed Python tool

The Library platform is packaged with a console entrypoint and installed or
upgraded through `uv tool install`. The package carries the executable resources
needed by the CLI and installs or exposes `cld` and `cdx` as its launcher
entrypoints. The source checkout is no longer the deployed executable location,
and `install.sh` becomes transitional migration machinery rather than the
normative installer.

This supersedes ADR-0002 Decision 4's deferral of `uv tool install`. It does not
require `cld` and `cdx` to remain zsh files or to become Python modules; packaging
may expose bundled launcher resources through appropriate console scripts. The
observable requirement is that installation and upgrade are owned by the uv
tool package rather than symlinks into a mutable or disposable checkout.

### Decision 4: `library init` has one fixed meaning

`library init` is an intentional top-level grammar extension. It takes no
Workspace selector. In the current Git repository it is shorthand for the
complete first-use transaction:

1. validate that the target is exactly one eligible Git top-level;
2. register the canonical `cognovis-base` Workspace as project desired state;
3. materialize its complete closure for Claude Code, Codex, and applicable Pi
   targets;
4. write or reconcile `.library.lock`; and
5. invoke CL-1les's authoritative v2-receipt reconciler for the one
   marker-delimited `.gitignore` block.

The command is idempotent. It does not choose a project profile, inspect the
historical global lock for candidates, or infer additional primitives. General
Workspace selection remains available through the ordinary Workspace command.

### Decision 5: Repository recommendations are conversational and confirmed

After initialization, the project-local Library Skill may inspect the current
repository and recommend additional Workspaces or direct primitives based on
observable language, tooling, domain, configuration, and workflow evidence. It
must distinguish findings from recommendations and show why each candidate fits.

Recommendations do not mutate state. The user confirms the desired additions,
then the deterministic CLI resolves and installs them. There is no
`--from-global` installation mode: a historical machine-wide receipt does not
identify which repository should own it.

### Decision 6: Status is the repository health boundary

Top-level `library status` becomes a read-only health check over the current Git
repository rather than only an upstream-SHA query. Its stable human and JSON
results cover:

- desired state: requested roots, Workspace closure, upstream freshness, and
  pending reconciliation;
- projections: missing, drifted, conflicting, and ownerless Library receipts;
- Git hygiene: the committed `.library.lock`, CL-1les managed-Gitignore block,
  stale managed entries, and tracked generated targets;
- bootstrap prerequisites: presence and compatibility of the enumerated global
  bootstrap targets, including OpenBrain MCP; and
- unmanaged primitives: supported-harness content present in project target
  paths without a Library receipt, classified without automatic adoption or
  deletion.

Exit 0 means healthy and converged. Exit 2 means deterministic repository repair
is available. Exit 3 means a protected collision, unmanaged ambiguity, or other
decision is required. Exit 1 means the check itself failed. JSON status and exit
code must describe the same state.

### Decision 7: Supported projections are Claude Code, Codex, and Pi

The active Library contract contains projection adapters and operator
documentation only for Claude Code, Codex, and Pi. Pi-native extensions and
profiles remain project-only and continue to be owned with `cognovis-pi`.

Cursor, OpenCode, Antigravity, and other harness targets are removed from active
CLI choices, default directories, bridge generation, tests, and current operator
documentation. Historical ADR evidence remains historical and need not be
rewritten merely to remove a name.

### Decision 8: Migration is project-by-project, not distributive

Repositories containing `.beads/config.yaml` form the initial discovery set for
manual fleet migration. Discovery never reads `.beads/issues.jsonl`. Each
approved repository runs the fixed `library init`, checks status, and then uses
the Library Skill to consider repository-specific additions.

The old global lock is dispositioned receipt by receipt as bootstrap,
replaced-project-locally, archived, or unmanaged. A global projection is removed
only after exact ownership and replacement evidence, or an explicit decision
that it is no longer needed. Unknown or drifted content is preserved until
resolved. The final state retains only the enumerated bootstrap and removes or
archives the historical global lock.

## Consequences

Repository clones regain a reviewable desired-state declaration and no longer
inherit an unrelated ambient skill collection. The shared `cognovis-base`
Workspace can evolve through normal Workspace ownership and pruning semantics,
while project-specific roots remain independently visible.

Bootstrap becomes smaller but more explicit. Adding another global item requires
amending the enumerated bootstrap contract rather than setting
`default_scope: global` in catalog metadata. Intrinsically global product
integrations therefore face a higher architecture bar, by design.

The migration is slower than copying the global lock into every repository. That
cost is accepted because the repository-by-repository pass produces the missing
evidence about which capabilities are actually useful and prevents existing
bloat from becoming the new baseline.

## Rejected Alternatives

### Preserve a small global Workspace

Rejected. A global Workspace remains an ambient artifact scope and inevitably
reopens the question of which generally useful Skill should be added next. The
bootstrap allowlist is deliberately a product contract, not desired-state
composition.

### Make `library init` select a Workspace

Rejected. Selection turns initialization into another guided installer and
weakens the one-command fleet convention. `init` means `cognovis-base`; other
Workspaces use the normal Workspace lifecycle.

### Migrate with `--from-global`

Rejected. Global presence proves machine use, not repository relevance. The
Library Skill's evidence-backed recommendation flow preserves the necessary
human judgment without making installation itself non-deterministic.

### Ignore whole harness directories in Git

Rejected. Repository-owned primitives may coexist with Library projections.
CL-1les's receipt-derived marker block ignores only authoritative generated
targets and preserves project-authored content.
