# Workspace Portfolio Audit

**Date:** 2026-08-05

**Bead:** CL-r7n6

**Status:** Architecture input, not an installation manifest

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
| Five FHIR repositories | Four locks contain the same seven-member IG closure; `fhir-management` adds Python CLI roots | A reusable FHIR authoring baseline is justified, but it composes with language/tooling Workspaces rather than absorbing them. |
| `mira`, `polaris`, `mvz-reetfurt` | Large overlapping Bead/Fusion harness closures with different assurance levels | First create one atomic entrypoint dependency graph for the Bead harness; then expose standard and high-assurance Workspace baselines. Do not copy the current 29-56 lock entries into manifests by hand. |
| `mira`, `polaris`, `cognovis-platform`, PVS adapters | Aidbox/FHIR capabilities recur, while product-specific agents and topology differ | A healthcare-application baseline is plausible. Product topology, customer credentials, and repository-specific agents stay project-owned. |
| Proposal, invoice, mail, archive flows | Capabilities span `cognovis-core`, `sussdorff-core`, and `collmex-cli` | A customer-document Workspace is justified, preferably in a dedicated Cognovis operations repository rather than the global engineering lobby. |
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
  irreducible pre-Workspace bootstrap; the five forge Skills currently installed
  by `install.sh` move to `library-authoring` instead of remaining ambient.
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

### Adopt first

| Workspace | Catalog steward | Default scope | Apply to | Root shape |
|-----------|-----------------|---------------|----------|------------|
| `engineering-lobby` | `cognovis-core` | global | Developer machine | A minimal routing Standard plus genuinely universal engineering entrypoint Skills after their dependency closures are audited. No forges, domain, or customer capabilities. |
| `python-cli` | `cognovis-core` | project | Active Python CLI repositories, `library/meta`, and `fhir-management` | `skill:python-dev` plus `skill:python-test`; their standards remain transitive dependencies. |
| `library-authoring` | Library platform catalog | project | `library/meta`; optionally catalog repositories when they need the forge tools | Forge Skills plus primitive-placement Standards; composes `python-cli` where the repository also develops the Python engine. |
| `fhir-ig-authoring` | `cognovis-core` | project | `fhir-praxis-de`, `fhir-dental-de`, `fhir-deidentification-de`, `fhir-terminology-de`, and `fhir-management` | Provider-neutral IG entrypoint plus only genuinely independent release/registry roots. Avoid duplicating its existing `requires:` closure. |
| `customer-documents` | `sussdorff-core`, with qualified Cognovis roots | project | A dedicated private Cognovis operations repository | Proposal, brand, outgoing invoice, document lookup, mail archive, and reviewed mail-draft capabilities. Customer data and credentials are not members. |

The customer Workspace should not contain a Workspace per customer. Its reusable
process applies across customers; customer-specific facts live in the operations
repository, the document system, or Open Brain. A customer product repository may add
a separate product or deployment Workspace when it genuinely shares implementation
capabilities with other customer repositories.

Before `customer-documents` is publishable, `customer-invoice` must declare its strict
runtime and primitive dependencies itself. A Workspace must not be used to make an
otherwise incomplete Skill happen to work.

### Lobby and bootstrap boundary

The Library cannot bootstrap itself through a Workspace. The pre-Workspace layer
therefore contains only the engine and conversational Library entrypoint. The
current installer also links `skill-forge`, `agent-forge`, `standard-forge`,
`script-forge`, and `hook-forge` globally; those are authoring capabilities and
belong in `library-authoring` for the repositories that maintain Library content.

The lobby carries only cross-repository routing information and entrypoints. For
Beads, the always-on contract should say when to enter the tracker flow and where
the upstream truth lives (`bd prime`); detailed intake, implementation, review,
and close behavior stays in invoked Skills and their dependencies. The lobby must
not enumerate every transitive Bead Agent or Standard. Before publishing the
lobby, audit those entrypoint closures so selecting one root cannot pull the full
high-assurance fleet unintentionally.

### Extract a stable entrypoint first

| Candidate Workspace | Why not yet |
|---------------------|-------------|
| `engineering-standard` / `engineering-high-assurance` | Polaris and Reetfurt prove the repeated closure, but the current state mixes entrypoint dependencies, Pi runtime profiles, scripts, and individually installed agents. Consolidate that graph before publishing the Workspace pair. |
| `healthcare-application` | MIRA and Polaris share Aidbox/FHIR roots, but authoring, emitting, querying, and product-specific runtime concerns are still mixed. The seam must be sharpened first. |
| `practice-simulation` | Reetfurt's role knowledge is valuable, but most of it is currently repository-owned product research rather than reusable Library primitives. |

### Do not create yet

Do not create `website`, `infrastructure`, `open-brain`, or per-customer Workspaces
from repository names alone. Their present Library-owned closures are absent, too
small, or dominated by project-specific state. A one-member alias is normally a
direct root, not a Workspace.

## Composition rules derived from the audit

1. A lock scope may register zero or more Workspaces.
2. A Workspace may reference another Workspace in the same scope. The nested
   Workspace is a transitive node, not an additional direct request.
3. Composition is set union plus dependency resolution. It has no order and no
   override semantics.
4. Cross-catalog roots are qualified. Same-catalog shorthand is allowed only when
   resolution is unambiguous, and the resolved catalog identity is always locked.
5. Cycles, incompatible version constraints, target collisions, and cross-scope
   ownership fail before mutation.
6. `requires:` expresses what one primitive needs to function. Workspace membership
   expresses which independently meaningful capabilities a user wants together.
7. A repo-specific file, secret, customer fact, runtime route, or deployment topology
   is not made portable by listing it in a Workspace.

These rules are incorporated into ADR-0010 and the Workspace primitive contract.
