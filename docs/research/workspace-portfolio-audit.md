# Workspace Portfolio Audit

**Date:** 2026-08-05

**Bead:** CL-r7n6

**Implementation status:** platform contract implemented by `CL-r7n6`. Only the
`python-cli` pilot is admitted for initial marketplace publication under
`clc-tzn5`; the remaining portfolio entries stay evidence-gated candidates.

## Question

Which reusable Library Workspaces are justified by the repositories and operating
flows in regular use, where should they be applied, and which existing grouping or
distribution concepts should be retired instead of carried forward?

## Evidence base

This audit used primary repository state and selected Open Brain observations:

- Project `.library.lock` files in `mira`, `polaris`, `mvz-reetfurt`,
  `cognovis-platform`, `open-brain`, the FHIR repositories, `library/meta`, and
  `cli-tools/ccu-cli`.
- Committed `.agents/`, `.claude/`, `.codex/`, and `.agents/pi/` trees in those
  repositories.
- The Python CLI repositories below `~/code/cli-tools/`.
- The Library catalog and primitive sources in `library/meta`,
  `library/cognovis-core`, `library/sussdorff-core`, and `library/cognovis-pi`.
- Open Brain observation 23576 for the regularly used healthcare and factory
  portfolio; observations 29957 and 29950 for the current multi-repository product
  and customer-operator flows; observation 29904 for the Reetfurt operating-practice
  model; observation 21384 for customer invoicing across `collmex-cli` and
  `sussdorff-core`; observations 10044, 10046, and 10047 for shared brand, proposal,
  and mail concerns; observation 13878 for the FHIR IG build/release boundary; and
  observation 29062 for Open Brain's current platform shape.

The inventory is a snapshot, not a promise that every checked-out repository should
receive a Workspace.

## Findings

### One repository can need several Workspaces

Workspace selection is many-to-many. A repository is not a Workspace and a Workspace
is not a repository template. The effective desired state is the union of all direct
primitive roots and all registered Workspace closures in one lock scope.

`fhir-management` is the clearest current example: its lock contains the same FHIR IG
closure as the other IG repositories plus the exact `python-dev`, `python-test`, and
`python-cli-patterns` baseline seen in `ccu-cli`. It should compose `fhir-ig-authoring`
and `python-cli`, not require a third combined Workspace.

`library/meta` has the same Python CLI roots plus four Library forge skills and the
primitive-placement standards. It should compose `python-cli` and
`library-authoring`.

### Workspaces should follow reusable work, not directory names

The observed repositories fall into overlapping capability families:

| Evidence cluster | Repeated state | Architectural reading |
|------------------|----------------|-----------------------|
| 16 repositories under `cli-tools/` | All use `pyproject.toml` and `uv.lock`; only `ccu-cli` has the complete five-entry Python baseline | A `python-cli` Workspace is justified and exposes present drift in the other CLI repositories. |
| Five FHIR repositories | Four locks contain the same seven-member IG closure; `fhir-management` adds Python CLI roots | Run a `requires:` audit first. If one IG entrypoint already owns that closure, use it directly; publish a Workspace only if at least two independent roots remain. |
| `mira`, `polaris`, `mvz-reetfurt` | Large overlapping Bead/Fusion harness closures with different assurance levels | First create one atomic entrypoint dependency graph for the Bead harness; then expose standard and high-assurance Workspace baselines. Do not copy the current 29-56 lock entries into manifests by hand. |
| `mira`, `polaris`, `cognovis-platform`, PVS adapters | Aidbox/FHIR capabilities recur, while product-specific agents and topology differ | A healthcare-application baseline is plausible. Product topology, customer credentials, and repository-specific agents stay project-owned. |
| Proposal, invoice, mail, archive flows | Capabilities span `cognovis-core`, `sussdorff-core`, and `collmex-cli`, but no dedicated operations consumer exists | Defer a customer-document Workspace until an operations repository and at least one additional consumer provide lock evidence and every entrypoint owns its strict dependencies. |
| Public sites and infrastructure repos | Repeated work exists, but current locks contain little or no canonical Library state | Do not publish Workspaces yet. First extract stable primitives from the repeated work. |

### The current global lobby is not a useful baseline

The inspected machine has 85 entries under `~/.agents/skills`, 31 standards, and
roughly 34 agents per major harness. The global v1 lock covers only part of that
surface; other entries come from external managers, system bundles, or historical
installs. A first global Workspace must therefore be an additive registration plus
an ownership audit, not a declaration that every existing global file belongs to the
Library.

The recommended global baseline is deliberately small: only cross-repository entry
points that are genuinely useful in nearly every engineering session. Customer,
healthcare, FHIR, website, and infrastructure capabilities should not be folded into
that lobby merely because they are sometimes used globally today.

### Several existing concepts are parallel desired-state systems

The following mechanisms overlap the Workspace reconciler and should not remain
independent long-term:

- ADR-0002's hand-maintained bootstrap capability list is replaced by a global
  Workspace root. The Library engine and conversational entrypoint remain an
  irreducible pre-Workspace bootstrap; the five forge Skills historically
  installed by `install.sh` move to `library-authoring` instead of remaining ambient.
- `consumer-projects.yml` plus `scripts/update-consumers.py` is replaced by each
  consumer's registered Workspaces and ordinary primitive roots. A file that cannot
  be represented as a primitive remains project-owned; it is not copied through a
  second manifest.
- `project_tooling` is a transitional fleet mutator. Distributable hooks and files
  move to normal primitive dependency graphs and Workspace ownership. Tool-owned
  state such as Beads database configuration belongs to that tool's migration path,
  while repository `.gitignore` policy remains project-owned.
- `Package` is not implemented by the current Library CLI or catalog schema. Strict
  co-installation is already expressed by an entrypoint primitive's `requires:`
  closure; selectable desired-state composition belongs to Workspace. Retaining a
  third composite abstraction would add vocabulary without a distinct interface.

## Recommended Workspace portfolio

### First implementation wave

| Workspace | Catalog steward | Default scope | Apply to | Root shape |
|-----------|-----------------|---------------|----------|------------|
| `python-cli` | `cognovis-core` | project | Active Python CLI repositories, `library/meta`, and `fhir-management` | Exactly `skill:python-dev` plus `skill:python-test`; `python-cli-patterns` and other mandatory Standards remain transitive `requires:` dependencies. Keep the name only while the baseline is genuinely CLI-specific; otherwise rename it once to `python-repo` before publication. |
| `library-authoring` | `cognovis-core` | project | `library/meta`; catalog repositories only while authoring Library content | Forge Skills plus primitive-placement Standards. It does not nest `python-cli`; `library/meta` registers both directly. The platform repository is a consumer, not the manifest steward. |

`python-cli` is the platform pilot because it has a small two-root boundary and a
large potential consumer set. `library-authoring` follows after the current global
forge links have an explicit ownership disposition. Publishing either Workspace
still requires two committed consumer locks; the catalog may stage the manifest
before that gate, but must label it experimental rather than generally available.

### Conditional candidate

| Workspace | Publish only when | Otherwise |
|-----------|-------------------|-----------|
| `fhir-ig-authoring` | A standalone-install audit leaves at least two independently meaningful roots beyond one provider-neutral IG entrypoint's `requires:` closure | Register the IG entrypoint Skill directly in each repository. An identical dependency closure is evidence for a strong entrypoint, not automatically for a Workspace. |

### Deferred portfolio

| Candidate | Preconditions to reconsider |
|-----------|-----------------------------|
| `engineering-lobby` | Enumerate at most five router or entrypoint roots and 15 receipts; prove the one-percent standing-context budget; write bootstrap receipts; ship collision preview, bulk adoption/replacement, and the chezmoi manager-inventory adapter; verify the routing Standard still enters the Beads flow during ordinary task work. |
| `customer-documents` | Create the dedicated Cognovis operations repository; make `customer-invoice` declare its strict runtime and primitive dependencies; observe the same independent root selection in at least two committed locks; and prove cross-catalog composition through several direct Workspace registrations rather than v1 manifest roots. |
| `engineering-standard` / `engineering-high-assurance` | Consolidate one atomic Bead-harness entrypoint graph. Assurance is a separately versioned policy Standard, not a second near-duplicate Workspace axis. Reconsider one `bead-harness` Workspace only after that graph exists. |
| `healthcare-application` | Sharpen the authoring, emitting, querying, and runtime seam. If one entrypoint's `requires:` closure owns the result, keep it a direct root. |

`practice-simulation` is not a deferred Workspace. Its current content is
repository-owned product research; reopen the question only after independently
reusable primitives exist. Website, infrastructure, Open Brain, and per-customer
Workspaces remain rejected because repository names and current global usage do
not establish a reusable desired-state boundary.

### Lobby and bootstrap boundary

The Library cannot bootstrap itself through a Workspace. The pre-Workspace layer
therefore contains only the engine and conversational Library entrypoint. The
previous installer also linked `skill-forge`, `agent-forge`, `standard-forge`,
`script-forge`, and `hook-forge` globally. The bootstrap now adopts exact
historical links into receipts without recreating them; those authoring
capabilities belong in `library-authoring` for repositories that maintain
Library content.

The lobby carries only cross-repository routing information and entrypoints. For
Beads, the always-on contract should say when to enter the tracker flow and where
the upstream truth lives (`bd prime`); detailed intake, implementation, review,
and close behavior stays in invoked Skills and their dependencies. The lobby must
not enumerate every transitive Bead Agent or Standard. Before publishing the
lobby, audit those entrypoint closures so selecting one root cannot pull the full
high-assurance fleet unintentionally.

## Admission, size, and composition rules

1. A lock scope may register zero or more Workspaces directly. Schema v1 does not
   allow a Workspace manifest to root another Workspace.
2. A Workspace contains 2-10 independently meaningful, standalone-installable
   roots from its own catalog and is evidenced in at least two committed consumer
   locks. One-member aliases remain direct roots.
3. Composition is set union plus dependency resolution. It has no order,
   exclusions, overrides, or last-writer-wins behavior. Exclusion pressure forces
   a split.
4. Cross-catalog v1 composition uses several qualified direct registrations at
   the scope boundary. Locks record canonical catalog identity; ambiguous bare
   operator names fail with candidates.
5. Project Workspaces may resolve at most 30 receipts. The lobby permits at most
   five direct roots and 15 receipts and must remain within the configured
   one-percent standing-context budget.
6. A lobby root must be a router or entrypoint. Removing it should make the agent
   unable to find where a capability lives, not remove the capability's complete
   implementation from every repository.
7. `requires:` expresses what one primitive needs to function. Workspace
   membership expresses which independent capabilities a user wants to select
   and retire together. Marketplace CI installs every direct root alone to enforce
   that boundary.
8. A repo-specific file, secret, customer fact, runtime route, or deployment
   topology is not made portable by listing it in a Workspace.
9. Every Workspace has one marketplace steward and an annual portfolio review.
   Fewer than two registered consumers at two consecutive reviews retires it to
   direct roots.

These rules are incorporated into ADR-0010 and the Workspace primitive contract.
