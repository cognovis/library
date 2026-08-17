---
adr: "0012"
title: "Repository-local Library environments and an explicit bootstrap"
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

# ADR-0012: Repository-local Library environments and an explicit bootstrap

## Status

Accepted and in force. Library installs artifacts into the current Git
repository. This ADR amends ADR-0002, ADR-0003, ADR-0010, and ADR-0011 wherever
they authorized a machine-wide primitive lock, direct machine-wide roots, a
machine-wide Workspace lobby, or Library-managed Cursor, OpenCode, or
Antigravity projections. Their source, cache, ownership, provider, and
reconciliation decisions otherwise remain in force.

The decision was implemented under CL-rm8o; the fleet moved to `cognovis-base`
under CL-l022 and CL-9yok, and CL-ldnu removed the last scope selection from the
CLI, the catalog, and the documentation. The normative consumer baseline is
`docs/harness-baseline.md`; Library-generated receipt targets are ignored while
repository-authored primitives remain tracked.

## Context

The machine-wide Library scope had stopped being small enough to act as a
deliberate baseline. Its lock carried more than one hundred materialized
receipts spanning Skills, Agents, Standards, Scripts, MCP servers, runtime
configuration, prompts, and model standards. A primitive installed there became
ambient in every repository even when one project needed it. That weakened
reproducibility, inflated harness discovery and context surfaces, and made
removal a machine-wide decision instead of a repository decision.

Workspace desired state already provided the right ownership and reconciliation
model. The missing constraint was that desired state belongs to a Git
repository. A developer opts a repository into a small shared baseline and then
deliberately adds domain- or tool-specific capabilities there. Historical
machine-wide installation was useful migration evidence, but it was never
evidence that every receipt belongs in every repository.

The supported harness set also narrowed. The Library platform targets Claude
Code, Codex, and Pi through the sibling `cognovis-pi` project. Cursor, OpenCode,
Antigravity, and other experimental projections added implementation and
documentation surface without an active consumer.

The Library control plane itself must be available before a repository has a
Library skill. That bootstrapping concern is distinct from Library artifact
desired state and does not recreate a generic machine-wide scope under another
name.

## Decision

### Decision 1: Artifact desired state is the current Git repository

Every directly requestable Library artifact primitive and every Library
Workspace is installed and owned through `<git-root>/.library.lock`. Lifecycle
commands resolve one Git top-level and write only project-local targets
belonging to that root.

There is no second desired state to select, so there is no selector. No
subcommand declares a `--scope` option, and a literally passed `--scope` is
answered by one typed rejection at a shared pre-mutation boundary, deterministic
in human and JSON modes, before catalog, repository, lockfile, and installer
resolution. The engine still threads an internal scope parameter through
lockfile and receipt bookkeeping; it has exactly one value and is not a caller
choice.

There is no authoritative `~/.config/library/global.lock`. Any surviving copy is
read-only migration inventory. It grants neither desired-state authority nor
permission to copy its contents into a repository.

### Decision 2: Bootstrap is an enumerated product contract

Machine-wide state exists only where the product cannot make the repository
usable without it. The bootstrap allowlist is:

- the Python `library` executable;
- the `cld` and `cdx` launchers;
- the `AGENTS.md` instruction entrypoint in `$HOME` and Claude's importing
  `CLAUDE.md` entrypoint;
- launcher runtime configuration required before a repository projection can be
  loaded; and
- the OpenBrain MCP server, as one explicitly accepted machine-wide singleton.

This allowlist is the deliberate exception to Decision 1 and the only one.
Bootstrap is not a Library primitive scope: no `library <primitive> use` path
installs these targets, and no primitive lock owns them. Bootstrap installation
has its own exact receipts or equivalent product-owned manifest, so status and
uninstall can distinguish its allowlisted targets from historical Library
projections.

The Library Skill is not bootstrap state. `library init` installs it through the
project `cognovis-base` Workspace. OpenBrain Skills are likewise project
members; only the MCP server is machine-wide.

Because the MCP registration lifecycle is retired, `library mcp remove <name>`
does one thing: it clears a legacy project lock record left behind by that
lifecycle, and reports the retirement when there is none. The check runs before
the shared receipted-removal path, so a v2 receipts-form MCP record — which the
retired lifecycle never wrote — would also be answered with the retirement
rather than reconciled. That is accepted: no such record exists, and inventing
a reconciliation path for one would re-open the registration surface this
decision closes.

### Decision 3: The Library CLI is a uv-installed Python tool

The Library platform is packaged with a console entrypoint and installed or
upgraded through `uv tool install`. The package carries the executable resources
needed by the CLI and installs or exposes `cld` and `cdx` as its launcher
entrypoints. The source checkout is not the deployed executable location.

For a fresh machine, `install.sh --fresh` is the normative bootstrap wrapper. It
materializes the platform and the source catalogs required by `cognovis-base`
below the XDG Library data directory, records their identities and portable
checkout paths in a machine-local source registry, delegates executable
installation to `uv tool install`, and applies the enumerated bootstrap. These
checkouts are provider inputs, not primitive projections: the installer creates
no Skill target and no Workspace desired state outside a repository. Plain
`install.sh` from an existing checkout is a control-plane-only upgrade route.

This supersedes ADR-0002 Decision 4's deferral of `uv tool install`. It does not
require `cld` and `cdx` to remain zsh files or to become Python modules;
packaging may expose bundled launcher resources through appropriate console
scripts. The observable requirement is that installation and upgrade are owned
by the uv tool package rather than symlinks into a mutable or disposable
checkout.

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

The command is idempotent. It does not choose a project profile, inspect any
historical machine-wide lock for candidates, or infer additional primitives.
General Workspace selection is available through the ordinary Workspace command.

### Decision 5: Repository recommendations are conversational and confirmed

After initialization, the project-local Library Skill may inspect the current
repository and recommend additional Workspaces or direct primitives based on
observable language, tooling, domain, configuration, and workflow evidence. It
distinguishes findings from recommendations and shows why each candidate fits.

Recommendations do not mutate state. The user confirms the desired additions,
then the deterministic CLI resolves and installs them. There is no
`--from-global` installation mode: a historical machine-wide receipt does not
identify which repository should own it.

### Decision 6: Status is the repository health boundary

Top-level `library status` is a read-only health check over the current Git
repository rather than only an upstream-SHA query. Its stable human and JSON
results cover:

- desired state: requested roots, Workspace closure, upstream freshness, and
  pending reconciliation;
- projections: missing, drifted, conflicting, and ownerless Library receipts;
- Git hygiene: the committed `.library.lock`, CL-1les managed-Gitignore block,
  stale managed entries, and tracked generated targets;
- bootstrap prerequisites: presence and compatibility of the enumerated
  bootstrap targets, including OpenBrain MCP; and
- unmanaged primitives: supported-harness content present in project target
  paths without a Library receipt, classified without automatic adoption or
  deletion.

Exit 0 means healthy and converged. Exit 2 means deterministic repository repair
is available. Exit 3 means a protected collision, unmanaged ambiguity, or other
decision is required. Exit 1 means the check itself failed. JSON status and exit
code describe the same state.

### Decision 7: Supported projections are Claude Code, Codex, and Pi

The active Library contract contains projection adapters and operator
documentation only for Claude Code, Codex, and Pi. Pi-native extensions and
profiles are project-only and continue to be owned with `cognovis-pi`.

Cursor, OpenCode, Antigravity, and other harness targets are absent from CLI
choices, default directories, bridge generation, tests, and current operator
documentation. Historical ADR evidence remains historical and is not rewritten
merely to remove a name.

### Decision 8: Migration was project-by-project, not distributive

Repositories containing `.beads/config.yaml` formed the discovery set for the
manual fleet migration. Discovery never read `.beads/issues.jsonl`. Each
approved repository ran the fixed `library init`, checked status, and then used
the Library Skill to consider repository-specific additions.

The old machine-wide lock was dispositioned receipt by receipt as bootstrap,
replaced-project-locally, archived, or unmanaged. A machine-wide projection was
removed only after exact ownership and replacement evidence, or an explicit
decision that it was no longer needed. Unknown or drifted content was preserved
until resolved. What remains is the enumerated bootstrap; the historical lock is
archived. Physical removal of leftover `~/.agents/skills` and `~/.claude/skills`
projections is an operator act tracked by CL-31po.

## Consequences

Repository clones carry a reviewable desired-state declaration and do not
inherit an unrelated ambient skill collection. The shared `cognovis-base`
Workspace evolves through normal Workspace ownership and pruning semantics,
while project-specific roots remain independently visible.

Bootstrap is smaller but more explicit. Adding another machine-wide item
requires amending the enumerated bootstrap contract rather than setting catalog
metadata. Intrinsically machine-wide product integrations therefore face a
higher architecture bar, by design.

The migration was slower than copying one lock into every repository. That cost
was accepted because the repository-by-repository pass produced the missing
evidence about which capabilities are actually useful and prevented existing
bloat from becoming the new baseline.

## Rejected Alternatives

### Preserve a small machine-wide Workspace

Rejected. It remains an ambient artifact scope and inevitably reopens the
question of which generally useful Skill should be added next. The bootstrap
allowlist is deliberately a product contract, not desired-state composition.

### Make `library init` select a Workspace

Rejected. Selection turns initialization into another guided installer and
weakens the one-command fleet convention. `init` means `cognovis-base`; other
Workspaces use the normal Workspace lifecycle.

### Migrate with `--from-global`

Rejected. Machine-wide presence proves machine use, not repository relevance.
The Library Skill's evidence-backed recommendation flow preserves the necessary
human judgment without making installation itself non-deterministic.

### Keep `--scope project` as a compatibility spelling

Rejected. A flag with one accepted value is a claim that a second value could
exist. Agents and operators read that claim as live capability and keep writing
scope-aware call sites. The flag is gone, and a literally passed `--scope` says
so in one typed error.

### Ignore whole harness directories in Git

Rejected. Repository-owned primitives may coexist with Library projections.
CL-1les's receipt-derived marker block ignores only authoritative generated
targets and preserves project-authored content.
