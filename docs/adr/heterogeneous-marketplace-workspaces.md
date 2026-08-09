---
adr: "0011"
title: "Library workspaces compose durable environments across heterogeneous marketplaces"
status: accepted
date: 2026-08-08
bead: "CL-2p73"
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
amends: ["0003", "0010"]
retains: ["0006"]
related_adrs: ["0003", "0004", "0005", "0006", "0010"]
---

# ADR-0011: Library workspaces compose durable environments across heterogeneous marketplaces

## Status

Accepted as the normative architecture for source providers, normalized
inventory, admission, distribution rights, durable foreign-resource caching, and
cross-catalog Workspace composition.

Two sub-decisions carry a qualified status and say so in their own sections:

- The **Workspace v2 composition contract** (`Cross-Catalog Resolution`) is
  normative as a contract, and its ADR-0010 consumer-evidence gate amendment is
  **final** (finalized 2026-08-09 on slice-1 evidence). See `Approval Finalization`.
- The **Workflow executor authority** branch (`Workflow Executor Evidence and
  Authority`) records a **failed** supersession attempt. ADR-0006 remains
  authoritative.

Implementation of providers, cache, admission, and Workspace v2 is deliberately
out of scope here and is carried by the slices in `Implementation Slices`.

## Context

The Library Platform already separates `sources.catalogs` from
`sources.marketplaces`, normalizes primitives under `library.*`, records
provenance and digests in `.library.lock`, and performs ownership-aware Workspace
reconciliation (ADR-0010). Every one of those contracts was written for content
the platform effectively owns, and each defers the heterogeneous case at exactly
the same boundary:

| Contract | Current shape | Verified today |
|---|---|---|
| Marketplace install | Git only; a non-`git` marketplace type raises before install | `scripts/lib/source.py` `resolve_marketplace_source`, the `marketplace_type != "git"` guard |
| Cache identity | `<type>/<marketplace>/<name>@<commit14>`; a revisionless provider degrades to the literal tag `local` | `scripts/lib/cache.py` `compute_cache_path` |
| Workspace manifest | Closed allowed-key set; no per-root `catalog` qualifier, no nested Workspace | `scripts/lib/workspace.py` `validate_workspace_manifest` |
| Cross-catalog lifecycle | Deferred behind a "two real consumers" gate | ADR-0010, *Ship nested Workspaces and cross-catalog manifest roots in v1* |
| Inventory scan | Convention scan of local writable sources; fixed shallow `skills/<name>/SKILL.md` layout | `docs/primitives/marketplace.md`, *Inventory refresh* |

The forcing function is that real third-party content is already on this machine
and is already outside every one of those contracts. Under `~/.claude/skills/`,
**23** directories carry the names of upstream `mattpocock/skills` items —
`implement`, `ask-matt`, `tdd`, `research`, `triage`, `wayfinder` and 17 more —
and **not one of them has a lockfile receipt, a pin, or a recorded rights state**.
Twelve are real directories and 11 are Library-shaped symlinks into
`~/.agents/skills/`, which makes the point sharper: the shape of a Library install
is present and the ownership is not. `~/.claude/workflows/` holds four
materialized workflow projections with **zero** lockfile receipts. The complete
inventory and its method are in `Legacy Projection Disposition`.

Upstream, `mattpocock/skills` stores
its skills at `skills/<category>/<name>/SKILL.md` — one level deeper than the
scanner's fixed layout — and `executive-circle` is reachable only through a
subscriber-token-scoped MCP endpoint that no Git adapter can clone.

Two further pressures meet at the same boundary and are therefore decided here
rather than deferred to separate ADRs:

1. Whether **Runbook** earns a first-class primitive contract, because a Runbook
   would need its own catalog identity, projection prefix, and Workspace
   selection semantics — the same resolution and collision surface.
2. Whether the **Workflow executor** moves to Pi, because Workflow receipts,
   runtime compatibility, migration, and rollback share one authoritative state
   transition with everything else in this ADR.

## Independent Authority Axes

Six axes are canonical. They are independent: a value on one axis never implies a
value on another, and no code may collapse two of them into one field. Every
contract in this ADR is expressed in these terms.

| # | Axis | Answers | Owned by | Never implies |
|---|---|---|---|---|
| A1 | Source provider and location | Where may these bytes be found, and over what transport? | Provider adapter | That the bytes may be fetched, kept, or used |
| A2 | Source stewardship | Who maintains the upstream artifact and under what grant? | Upstream steward; recorded, never inferred | That the Library may adapt or redistribute it |
| A3 | Normalized inventory identity | What is this item, stably, across refreshes? | Library normalization | That it is installable |
| A4 | Primitive classification | Which Library primitive contract governs it? | Library classification | That the runtime can execute it |
| A5 | Runtime compatibility | Which harnesses and runtimes can consume it? | Declared compatibility | That it is admitted to run |
| A6 | Desired-state authority | What must be installed in this scope, and who owns the receipt? | Workspace and direct roots | That it is discoverable or cached |

Restating the invariant that the axes exist to protect:

> Marketplace registration answers **where content may be found**. Normalized
> inventory answers **what is available**. Workspace roots and their resolved
> closure answer **what is installed**.

**Discovery never implies installation, trust, license permission, redistribution
permission, compatibility, or availability of credentials.** Each of those is a
separate recorded state with its own evidence, defined in
`Normalized Inventory and Admission State` and `Distribution Rights`.

### Numbered invariants used by this ADR

`CL-2p73` states fourteen architecture invariants that this ADR must preserve.
Two of them are cited by number in the sections below. They are reproduced here
in full so that a reader with only this repository — and no access to the bead
tracker — can check the citation. They are stated as this ADR's own normative
rules; the bead is their origin, not a second authority a reader must go find.

> **Invariant 4 (Runbook admission).** If justified as a distinct primitive, a
> Runbook guides an acting agent; it neither executes orchestration nor owns
> installation. A Workspace may select its projection and required capabilities.
> **If no Library-enforced behavior distinguishes it from a Skill plus metadata,
> the ADR must reject the new primitive honestly.**

> **Invariant 13 (blocked project projection).** A project projection without
> confirmed redistribution rights must not materialize third-party bytes into a
> committed vendored tree. The default for `unknown` or `denied` redistribution
> state is a blocked project projection. A machine-local cached projection into a
> gitignored target requires explicit policy or operator opt-in after the rights
> state is shown, and the chosen behavior is visible before mutation.

The remaining twelve invariants are preserved but are not cited by number
anywhere in this document; each is carried by the section that owns its subject.

## Source Provider Contract

There is no universal scanner. A provider adapter implements a capability
contract; the resolver, cache, and Workspace layers consume only that contract
and must contain **no provider-specific branch**. The mechanical absence check
for provider names in core modules is owned by the implementation slices
(`Implementation Slices`, slice 1), not asserted here.

### Adapter capabilities

Every capability is explicitly declared. A consumer asks `capabilities()` and
degrades deterministically; it never probes by catching exceptions.

| Capability | Signature intent | Required | Absence behavior |
|---|---|---|---|
| `identity()` | Canonical, stable provider identity (URL or URN). Display aliases resolve to it. | YES | — |
| `capabilities()` | The declared capability set, including which of the below are present. | YES | — |
| `enumerate(selector)` | Remote-only listing of items with no local checkout. Returns upstream IDs, names, and collection membership. | YES | — |
| `describe(upstream_id)` | Item metadata sufficient for classification without fetching content. | NO | Falls back to `fetch` plus classification; recorded as a costlier path, never as a failure |
| `fetch(upstream_id, revision)` | Complete immutable content bytes for one item. | YES | — |
| `revision_of(upstream_id)` | Immutable upstream revision identity. | NO | Provider is **revisionless**; see `Trust on first use` |
| `verify(bytes, expected)` | Provider-native integrity proof (for example a Git object hash). | NO | Library normalized digest is the only integrity proof |
| `auth_requirements()` | Named credential *references* and scopes. Never values. | YES | — |
| `availability()` | `available`, `degraded`, or `unavailable`, with a reason. | YES | — |
| `rights_evidence()` | Machine-readable pointer to the licensing evidence source, if the provider publishes one. | NO | Rights state is `unknown` until a human records evidence |
| `item_rights_evidence(upstream_id)` | Licensing evidence for **one item**, for a provider whose units are not uniform. | NO | The provider is uniform; one rights answer covers every item it lists |
| `member_manifest(upstream_id, revision)` | The item-relative paths one item consists of, listed from the source. | NO | Completeness rests on the adapter's own declaration, which an install records explicitly as its weakest evidence |

`enumerate` is deliberately the required floor. A provider that cannot list
without a local checkout is not a provider under this contract; it is a local
catalog, which the platform already supports.

**Amendment (slice 1, `CL-coif`, 2026-08-08).** `describe` was originally marked
`Required: YES` while this same table also defined behavior for its absence. Both
readings — "mandatory method with a default implementation" and "optional
declared capability" — were supported by the text, and the ambiguity was routed
to this slice as a round-2 review advisory on `CL-2p73`. It is resolved in favor
of **optional and declared**: the absence behavior is required to be driven by
`capabilities()`, and a capability that is always present cannot be. A provider
that cannot cheaply describe an item is a costlier provider, never an excluded
one. The implemented contract is `scripts/lib/providers/contract.py`; the
fetch-then-classify path is recorded as a typed `NormalizationCost`, and
`tests/test_source_provider_contract.py::test_optional_capability_absence_is_declared`
holds it.

Two clarifications from the same slice, both raised in its adversarial review:

- **`fetch` returns a complete item, not a marker file.** An item is frequently
  a directory — the reference provider's `implement` skill ships `SKILL.md` and
  `agents/openai.yaml` — so "complete immutable content bytes" is carried by a
  typed `FetchedItem` holding every member file, its item-relative path, its
  upstream content identity, and the pinned revision. A fetch that returned only
  the marker would hand the slice-3 cache an incomplete item while reporting
  success.
- **`describe` answers the type axis, not `classification.skill_class`.**
  `skill_class` is curated catalog metadata (see the correction under
  `Runbook: rejected as a primitive`), not something any provider capability can
  answer. The normalized item carries it **only** when the catalog supplies it,
  and otherwise records `classification.skill_class_source: not-curated`. No
  third `skill_class` state is introduced: the vocabulary remains
  `navigator | procedure`. Content inspection remains available as an explicit,
  costed normalization option and records the factual
  `classification.upstream_model_invocation`.

### Provider kinds

| Kind | Enumeration | Revision | Auth | Reference provider |
|---|---|---|---|---|
| `git-repo` | Tree listing at a ref, recursive, no clone required | Commit SHA | Optional | `mattpocock/skills` |
| `git-org` | Repository listing filtered by an explicit **allowlist**; then per-repo `git-repo` behavior | Commit SHA per repo | Optional | `disler` |
| `mcp-content` | Typed MCP tool call returning item IDs and collection membership | Provider-supplied ID or none | Required, token-scoped | `mcp:executive-circle` |
| `hosted-index` | HTTP index document | Index-declared | Optional | none yet; contract only |

`git-org` is not "a Git repo with a wildcard". Organization-level enumeration
without an allowlist is refused: it makes the inventory a function of someone
else's repository creation, which would let an upstream party inject items into a
Library catalog. The allowlist is Library-owned configuration.

### MCP as transport is not the MCP primitive

`mcp-content` is a **transport for fetching a primitive's bytes**. It produces a
receipt for the fetched primitive's own type and scope — a Prompt receipt for a
prompt kit, not an MCP receipt.

It never creates an `mcp:` dependency edge, a global ownership edge, or a harness
MCP registration. If the fetched artifact genuinely requires a running MCP server
at use time, that server is a **separate global prerequisite assertion** under
ADR-0010 Decision 4, declared by the artifact, resolved against the global lock,
and never implied by the fact that its bytes arrived over MCP.

This is the single most confusable point in the architecture, so it is stated as
an invariant: **the transport that delivered an artifact contributes nothing to
that artifact's type, scope, dependencies, or ownership.**

### Consumers of provider identity

A qualified item identity is:

```text
<provider-identity>#<upstream-id>
```

for example `https://github.com/mattpocock/skills#skills/engineering/implement`.
The provider identity is canonical, not the operator's display alias. Locks,
conflict diagnostics, ownership, audit, and prune decisions all use the canonical
form; display aliases appear only in human output.

A non-URL provider uses a URN-shaped identity: the MCP reference provider's
canonical identity is `mcp:executive-circle`, and the bare `executive-circle` —
its `library.yaml` `mcp_servers` entry name — is a display alias only. Prose in
this ADR uses the alias for readability; **stored** identity is always the
canonical form. Storing both would let one provider produce two distinct record
sets under two identities.

## Normalized Inventory and Admission State

Normalization preserves upstream identity and adds Library-owned classification.
It never rewrites upstream identity to make it fit.

### Normalized item schema decision table

| Field | Axis | Required | Decision |
|---|---|---|---|
| `provider_identity` | A1 | YES | Canonical provider identity |
| `upstream_id` | A1/A3 | YES | Provider-native item identity, opaque to the Library |
| `upstream_name` | A2/A3 | YES | Preserved verbatim; never renamed to resolve a collision |
| `collection_membership` | A2/A3 | YES, may be empty | Ordered upstream grouping (repo category directory, prompt-kit ID) |
| `upstream_revision` | A1 | Nullable | `null` marks a revisionless provider |
| `library_type` | A4 | YES | An existing primitive type. Introducing a type requires its own ADR |
| `library_name` | A4 | YES | Library-scoped name; may differ from `upstream_name` only via a recorded projection rule |
| `classification` | A4 | YES | Library-owned metadata, including `skill_class: navigator \| procedure` |
| `runtime_compatibility` | A5 | YES | Declared harness/runtime set; `unknown` is a legal value and blocks nothing by itself |
| `admission_state` | A6 | YES | `discoverable` \| `installable` \| `blocked` |
| `block_reasons` | A6 | YES when not `installable` | Ordered, typed; see below |
| `executable_admission` | A6 | YES | `inert` \| `admitted` \| `pending` \| `refused` |
| `trust_state` | A2/A6 | YES | `first-party` \| `reviewed` \| `unreviewed` |
| `rights` | A2 | YES | Four independent grants; see `Distribution Rights` |
| `cache_state` | — | YES | `absent` \| `materialized` \| `verified` |
| `projection_eligibility` | A6 | YES | Per target class; see `Distribution Rights` |
| `provider_availability` | A1 | YES | Mirrors `availability()` at last refresh, with its timestamp |

### The four states are orthogonal

`admission_state`, `executable_admission`, `cache_state`, and
`projection_eligibility` are separate fields precisely because their real
combinations are not nested. The load-bearing case:

> An item may be `cache_state: verified` while its
> `projection_eligibility.project_committed` is `blocked`.

That is the normal state for rights-restricted content: the bytes are lawfully
fetched, verified, and durable on this machine, and materializing them into a
committed vendored tree is still forbidden. Any model that treats "cached"
as "installable" cannot express it.

### Typed block reasons

`block_reasons` is a closed, ordered vocabulary. Each carries the evidence that
produced it.

| Reason | Meaning | Cleared by |
|---|---|---|
| `license-unknown` | No recorded upstream grant | Recording a rights evidence source |
| `license-denied` | Recorded grant forbids this use | A changed upstream grant |
| `redistribution-blocked` | Fetch allowed, redistribution not | Rights change, or choosing a machine-local target |
| `authentication-required` | Provider needs a credential this scope does not have | Configuring the named credential reference |
| `incompatible-runtime` | Declared compatibility excludes every target runtime | A compatible runtime, or a recorded override |
| `executable-admission-pending` | Executable artifact not yet admitted | The `Executable Admission` gate |
| `untrusted-source` | Source below the required trust state for this scope | Explicit review |
| `content-unavailable` | Provider cannot supply complete content now | Provider recovery |

`blocked` is a first-class, queryable state, not an error. An operator must be
able to ask "what did I not get, and exactly why" without re-running discovery.

**Implementation record (slice 2, `CL-n7ex`).** Two readings of this table were
open, and both are resolved in the implemented gate rather than left to each
call site:

- The vocabulary has no entry for a *refused* executable admission. A refusal
  records `untrusted-source`, not `executable-admission-pending`: the pending
  entry is cleared by "the Executable Admission gate", which a refusal has
  already been through, and what a refusal needs is the explicit review that
  clears `untrusted-source`. Recording a decided refusal as "pending" would also
  make a deliberate decision read as unfinished work.
- `admission_state` is derived by one rule: `installable` when there is no block
  reason and at least one projection target is `allowed`; `blocked` when there
  is any block reason; `discoverable` otherwise. `blocked` is therefore reached
  by an item that still has a machine-local opt-in path — which is the intended
  reading of orthogonal axes, not a contradiction: the item was not installed,
  the reason is recorded, and `projection_eligibility` separately names the path
  that remains open.

`block_reasons` entries are stored as typed records carrying `reason`, an
`evidence` observation, its named `source`, and an optional `detail`, per this
section's requirement that each reason "carries the evidence that produced it".
Evidence held only in a transient decision object would not survive to answer
the question this state exists to answer.

Evidence is **two fields rather than one**, recorded after review twice found
text that passed every shape check while naming nothing. The observation and its
source are separate sentences, so a caller cannot silently omit the half they do
not have. The honest limit is stated rather than glossed: the record enforces
shape, not truth. Whether the observation is accurate remains a review question,
and no validator in this system decides it.

### Freshness and provider availability

A normalized inventory entry records `provider_availability` **with the timestamp
of the observation**. It never presents a cached inventory as a current one. When
a provider is `unavailable`, its previously normalized entries remain readable and
are marked stale; they do not vanish, and they do not claim currency.

## Primitive and Projection Boundaries

### Runbook: rejected as a primitive, retained as Skill classification

The candidate was tested against the normative Quick Decision Tree in
`docs/PRIMITIVES.md` **as that tree stood before this change**. The
`runbook -> SKILL` terminator this delivery adds to the tree is a *record of this
result* for future readers; it is not evidence for it, and the derivation below
does not use it. The rows are grouped by topic rather than replayed in the tree's
literal order — the STANDARD question sits ninth in the tree, not third — because
the terminating question is the same either way:

| Tree question | Answer for a Runbook | Consequence |
|---|---|---|
| Purely deterministic logic (>50 lines) running NO model? | No — it guides a model | Not SCRIPT |
| Fixed-shape orchestration of multiple subagents, deterministic control flow spawning fresh contexts? | No — Invariant 4 (`Numbered invariants used by this ADR`) says a Runbook guides one **acting** agent and executes no orchestration | Not WORKFLOW |
| Is it project-specific or cross-cutting context supplementing skills — passive, injected, not invokable? | No. A Runbook's defining shape is *invoked routing and handoff*: `ask-matt` answers "which flow fits my situation", which requires being asked. A Standard is loaded into context and never asked anything, and a Standard containing "Step 1, then Step 2" is exactly what `standards/agentic-primitives` names as the counter-example that must become a Skill | Not STANDARD |
| Should the model auto-pick it up from context? | Sometimes; the "navigator" shape is explicitly user-invoked | **SKILL**, with the auto-pickup flag varying |
| Does the user invoke it explicitly by slash command? | For the navigator shape, yes | See the Skill/Command note below |

**The Skill/Command boundary, stated rather than glossed.** The tree reaches
SKILL at the auto-pickup question, and a user-invoked navigator would ordinarily
continue to COMMAND. That tension is real and is resolved on the *source format*
axis, not by overriding the tree: the Open Skills format carries
`disable-model-invocation`, and both `ask-matt` and `implement` ship it upstream.
A user-invoked Skill is therefore an existing, portable shape, not a contradiction
— the flag is what a harness projects into a slash command where it has one. What
the Library must not do is re-type an upstream `SKILL.md` as a Command because of
one frontmatter flag; that would break upstream identity (axis A3) for a
projection concern (axis A5). Recorded as a real seam rather than a settled one:
if the Command primitive later grows Library-enforced behavior that a flagged
Skill cannot carry, this classification is the thing to revisit.

The tree terminates at SKILL. Invariant 4 then permits admission anyway, but only
on proof of **at least one Library-enforced behavior that Skill plus catalog
metadata cannot carry**. Each candidate behavior was tested and each failed:

| Claimed constitutive behavior | Why Skill plus metadata already carries it |
|---|---|
| Navigator versus Procedure distinction | Carried by Skill plus catalog metadata: the Library adds a validated `classification.skill_class` field for querying. It is **curated, not derived** — see the slice-1 correction below |
| Versioned, non-self-executing decision graph | Every Library primitive is versioned, and the Library executes **no** primitive. Non-self-execution is not a distinguishing property; it is the default |
| Required versus optional capabilities | `requires:` already carries hard dependencies (ADR-0004); Workspace membership already carries optional composition (ADR-0010) |
| Conditional routes and handoff artifacts | Content inside the artifact. The Library enforces nothing about them and would enforce nothing about them under a new type either |
| Human gates | Enforced by the consuming harness or skill body, never by the Library |
| Reserved `runbook-` projection prefix | A name-collision policy concern (`docs/policy/name-collision.md`), not a primitive concern. It can be applied to a classification just as well as to a type |

**Decision: no Runbook primitive.** Runbook-shaped content is a Skill carrying
validated `classification.skill_class` of `navigator` or `procedure`. The
`runbook-` prefix is **not reserved**, and no `runbook-` harness projection
exists.

**Correction (slice 1, `CL-coif`, 2026-08-08).** This section originally cited
`disable-model-invocation: true` on both `ask-matt` and `implement` as evidence
that the distinction is already expressed in upstream frontmatter. It is not.
The Placement Records below classify `implement` as `procedure` and `ask-matt`
as `navigator` while both carry that identical flag, so the flag cannot be the
discriminator — it means "do not auto-invoke me", which navigators and
procedures alike declare. Slice 1 briefly implemented that derivation, and the
adversarial review caught the resulting misclassification against this ADR's own
table.

`classification.skill_class` is therefore **Library-curated catalog metadata**,
supplied by the catalog and validated against `navigator | procedure`. An item
with no curated value records `classification.skill_class_source: not-curated`
and no `skill_class` at all; content inspection instead records the factual
`classification.upstream_model_invocation`. This strengthens rather than weakens
the Runbook rejection: the distinction is carried by catalog metadata, which is
exactly what the rejection claimed.

This decision also avoids a collision the prefix would have caused immediately:
the two reference navigator/procedure artifacts are upstream-named `ask-matt` and
`implement`. A reserved prefix would have had to either rename them — violating
upstream name preservation (A3) — or fail closed on first contact.

Recording the honest cost: a `navigator` Skill and a `procedure` Skill remain
indistinguishable to a harness that ignores classification metadata. That is
accepted. It is a discovery-quality cost, not a correctness cost, and it is
strictly smaller than the cost of a fourteenth primitive whose entire enforced
behavior is a naming convention.

### Executable admission

Discovery is non-executing. Selection into a Workspace is not permission to run.

An externally sourced **executable** artifact — Workflow, Pi extension, Pi
profile that loads code, hook, or script — requires an explicit
executable-admission decision beyond ordinary Workspace selection.

| Element | Decision |
|---|---|
| Authority | The scope operator. Never a provider, never an upstream manifest, never a Workspace author who is not the operator of that scope |
| Trigger | First transition of an item with `library_type` in the executable set from `discoverable` toward `installable` |
| Required evidence | Recorded reviewer identity, the exact reviewed content digest, and the declared permission surface the artifact requests |
| Recorded state | `executable_admission` on the normalized item and on the receipt, bound to the **content digest**, not to the name or version |
| Composition with Workspace selection | Admission is a precondition of installability. A Workspace root that reaches a `pending` or `refused` executable item **fails the whole resolution before mutation**; it does not silently skip it |
| Invalidation | Any change to the content digest returns the item to `pending`. Re-admission is a new decision with new evidence |
| Authority (slice 2, `CL-n7ex`) | The operator's admission ledger, keyed by identity **and** content digest. A normalized item's own `executable_admission` field is never consulted as authority: any producer of an item can write `admitted` into it, and review demonstrated such an item evaluating to `installable` with no reviewer, no digest, and no permission surface behind it. The gate digests the content it will materialize, so the reviewed bytes and the written bytes are the same bytes |

Inert Prompt, Standard, and documentation content is `executable_admission:
inert` and never silently inherits executable trust by sharing a bundle,
collection, or provider with an executable artifact.

### Mixed external bundles

An external bundle is **decomposed** into its typed members — Skills, Workflows,
Pi extensions, Pi profiles, Standards, Prompts — each classified individually. A
generic `harness` primitive is rejected by default; introducing one requires
separate evidence that the existing type system cannot preserve an enforced
behavior, and its own ADR.

### Placement Records

| Field | `implement` | `ask-matt` | `ask-malte` |
|---|---|---|---|
| Steward marketplace | `mattpocock` (`https://github.com/mattpocock/skills`), provider kind `git-repo` | `mattpocock`, same provider | `cognovis-library-core` (`https://github.com/cognovis/library-core`), first-party catalog |
| Upstream identity | `skills/engineering/implement/SKILL.md` | `skills/engineering/ask-matt/SKILL.md` | first-party; no upstream |
| Plane | dev | dev | dev |
| Primitive | Skill | Skill | Skill |
| Classification | `skill_class: procedure` | `skill_class: navigator` | `skill_class: navigator` |
| Runtime compatibility | Claude Code, Codex (Open Skills portable source) | Claude Code, Codex | Claude Code, Codex, Pi |
| Executable admission | `inert` | `inert` | `inert` |
| Rights | `granted` (MIT) | `granted` (MIT) | first-party |
| Product counterpart | none | none | none |

`ask-malte` is the platform-owned counterpart of `ask-matt`, and its routing is
constrained rather than merely recommended:

- It MUST resolve candidate skills, agents, and workspaces through **catalog
  data** — the `lib catalog match` surface over `sources.catalogs` and
  `library.*` — and through **canonical context pointers** such as
  `~/.agents/AGENTS.md`, `docs/PRIMITIVES.md`, and the installed workspace set.
- It MUST NOT hard-code provider names, sibling-repository paths, or a routing
  table of repositories. A routing answer that names `cognovis-core` or
  `sussdorff-core` must have read that name out of the catalog in that session.
- Consequence: `ask-malte` returns a correct, narrower answer on a machine with
  fewer catalogs registered, instead of a confidently wrong answer naming a
  repository that is not there.

### Workflow Executor Evidence and Authority

The Pi-only Workflow target was tested, not assumed. This subsection records a
**failed supersession branch**.

**Runtime identity and version pin.** `pi` at `/Users/malte/.local/bin/pi`,
version `0.84.1`, observed 2026-08-08.

**Evidence checks.** Enumerated and executed by
`scripts/checks/pi_workflow_executor_evidence.py`, tested by
`tests/test_pi_workflow_executor_evidence.py`.

**Result artifact.** `docs/research/pi-workflow-executor-evidence.json`
(`cognovis.pi-workflow-executor-evidence.v1`). The test suite verifies the
committed artifact's schema, its check identities and titles, its outcome
vocabulary, its constitutive/migration partition, and its verdict and threshold
recomputed from the recorded outcomes. A hand-edited verdict, a renamed check, or
an invented outcome value all fail CI. The per-check `evidence` prose is asserted
non-empty but is not otherwise pinned; regenerate the artifact by re-running the
checker rather than editing it.

**Every threshold check has a reachable `pass` path.** This is a property of the
checker, enforced by paired pass/fail tests over synthetic contexts for all seven
threshold checks, plus one end-to-end test proving a fully capable world reaches
`supersede-adr-0006`. A check that could never pass would silently weld the
re-entry condition below shut and make the "the verdict flips automatically"
claim false. The first draft of this checker had exactly that defect in three
checks; adversarial review caught it, and the tests exist so it cannot return.

**What each check can and cannot prove — stated because the ADR leans on it.**

| Check | Strength of its pass condition |
|---|---|
| PWE-2, PWE-3 | **Behavioral.** A canonical probe spec is executed and reports its own injected globals. These cannot pass without a working executor |
| PWE-6 | **Identity-matched.** Every materialized projection must match a workflow receipt *by name*; a count comparison is explicitly rejected and tested against |
| PWE-7 | **Reachability-checked.** The Pi gate must be *called*, not merely defined, with comments and docstrings stripped first |
| PWE-4, PWE-5, PWE-8 | **Declaration-level.** PWE-4 reads a documented surface, PWE-5 reads a design document, PWE-8 reads an environment gate or an adapter-status registry. Each is the strongest evidence available without a running executor, and none is a behavioral proof |

The three declaration-level checks are an accepted limitation, not an oversight:
there is no executor to behaviorally probe, and a checker cannot smoke-test a
rollback path that does not exist. Their consequence is bounded and one-directional
— they can be *too generous* on a future pass, never too strict on today's fail —
so they cannot manufacture the current `retain` verdict. **Whoever writes the
eventual supersession ADR must not treat a PWE-4/5/8 pass as proof of the
capability; the supersession slice owns upgrading them to behavioral probes once
an executor exists to probe.** This is recorded here so a future reader inherits
the caveat rather than the number.

**Objective threshold.** Supersede ADR-0006 only when **all** constitutive checks
`PWE-2, PWE-3, PWE-4, PWE-5` and **all** migration-completeness checks
`PWE-6, PWE-7, PWE-8` record `pass`. Any `fail` or `unavailable` retains ADR-0006.
`PWE-1` is runtime context and is never a threshold input.

| Check | Question | Result |
|---|---|---|
| PWE-1 | Pi runtime identity and version pin | `pass` — Pi 0.84.1 |
| PWE-2 | Does Pi execute a canonical Workflow JS spec? Discover a documented entrypoint, then run a canonical probe spec through it | `fail` |
| PWE-3 | Does the discovered entrypoint inject the ADR-0006 orchestration globals, as reported by the probe spec itself? | `fail` |
| PWE-4 | Does the discovered entrypoint document a run journal and run resume, as distinct from conversational session resume? | `fail` |
| PWE-5 | Does the only concrete Pi orchestration **design** keep its spine inert? (Scope note: this probes a design document, not Pi's runtime) | `fail` |
| PWE-6 | Is a Pi target declared for the workflow primitive, and does every materialized projection carry a lockfile receipt? | `fail` |
| PWE-7 | Does the workflow installer contain a Pi-side validation **code path** (comments and docstrings stripped)? | `fail` |
| PWE-8 | Is an ADR-0006 executor reachable for mutating work — native tool gate enabled, or ≥1 `verified` adapter? | `fail` |

**Verdict: `retain-adr-0006`.** Seven of seven required checks fail. The
substantive findings:

- Pi's documented command surface is `install`, `remove`, `uninstall`, `update`,
  `list`, `config`, `auth` plus an interactive/`--print` assistant. There is no
  entrypoint that loads a spec file, and the string `workflow` does not appear in
  `pi --help`. Pi's unit of model work is an `AgentSession` created by extension
  TypeScript, not a leaf `agent(prompt, opts)` call injected into an inert spine.
- Pi resumes conversational **sessions**, not orchestration **runs**. ADR-0006
  requires a journal keyed by a hash of `(prompt, opts)` per leaf so a re-run is a
  full cache hit; Pi has no leaf-call abstraction to key such a journal on.
- The only concrete Pi orchestration design on this machine,
  `/Users/malte/code/library/cognovis-pi/docs/native-executive-pack-harness.md`,
  places `Git and Beads adapters`, an `Evidence store`, and gate execution
  **inside the orchestration extension itself**. That directly violates ADR-0006
  Decision 4, which makes an inert spine normative. It is also pack-specific: it
  is a native Executive Pack harness, not a general executor for the Workflow
  primitive.
- No Pi target is declared for the workflow primitive — `scripts/lib/primitives.py`
  still describes it as "Claude workflow JavaScript" with
  `install_subdir="workflows"` — so there is nowhere to migrate *to*. And five
  workflow catalog entries with four materialized projections in
  `~/.claude/workflows/` carry **zero** lockfile receipts, so there is nothing to
  migrate *from* in lock terms either. The unreceipted projections are a defect in
  their own right and are dispositioned in `Legacy Projection Disposition`.
- Neither ADR-0006 executor path can run mutating work. The **canonical** executor
  is the native Claude Workflow tool, whose `CLAUDE_CODE_WORKFLOWS` gate is unset;
  the explicitly non-canonical `scripts/lib/workflow_runtime.py` reports zero
  `verified` adapters and three `blocked` ones (`claude-agent`, `codex-exec`,
  `codex-impl`). A rollback target that cannot run mutating work is not a rollback
  path for a superseded executor.

**Authority statement.** ADR-0006 Decision 2 and the clc-j7mn amendment remain
**authoritative and unamended**. The canonical Workflow spec format stays the
Anthropic Workflow JS surface; the native tool stays the canonical executor; the
native parse-check deploy gate in `scripts/lib/installers/simple_file.py` stays in
force. No receipt migration is performed and no rollback is required, because no
cutover occurs.

**Re-entry condition.** Re-run the checker. If it reports
`supersede-adr-0006`, a supersession ADR may be written; until then the branch is
closed. Pi remains fully supported as a **runtime target** for Pi extensions and
Pi profiles — which is a different axis (A5) from executor authority — and
Workflow source ownership may still be first-party or external.

This closure does not block anything else in this ADR. Marketplace, cache, rights,
admission, and Workspace decisions stand on their own.

## Cross-Catalog Resolution

Workspace schema v2 lets one Workspace name roots across catalogs and
marketplaces. Everything ADR-0010 made non-replaceable stays non-replaceable.

### Qualified roots

A v2 root may carry an optional `catalog` qualifier resolving to a canonical
catalog or provider identity:

```yaml
schema_version: 2
name: matt-engineering
version: 1.0.0
description: Engineering navigator and procedure skills across first-party and upstream sources
catalogs:
  - alias: mattpocock
    identity: https://github.com/mattpocock/skills
    pin:
      kind: commit
      value: 4f2c1e9a8b7d6c5e4f3a2b1c0d9e8f7a6b5c4d3e
  - alias: core
    identity: https://github.com/cognovis/library-core
    pin:
      kind: commit
      value: dee0415f47d8ae4ccfa7e166bdd682c29f94c33b
roots:
  - type: skill
    name: implement
    catalog: mattpocock
  - type: skill
    name: python-test
    catalog: core
    constraint: ">=1.0.0,<2.0.0"
```

Rules:

1. **The `catalogs:` block is the only place a Workspace may name a source.** A
   root's `catalog` value must be an alias declared in that same manifest. A root
   may not carry a URL. This is what prevents an external provider from silently
   redirecting a trusted root: the redirection surface is one reviewable,
   pinned block in the manifest the operator installed.
2. **Every declared catalog carries a `pin`.** Resolution uses the pin, not a
   moving branch. An unpinned catalog entry is a schema error.

   A pin is **typed**, and the type is written out — the mapping above, never a
   bare string. A bare string would have to be interpreted as one kind by
   default, and defaulting a revisionless source's snapshot digest to `commit`
   is exactly the silent mis-typing the table below exists to prevent:

   | `pin.kind` | Value | Used by |
   |---|---|---|
   | `commit` | Immutable upstream revision | `git-repo`, `git-org` |
   | `inventory-snapshot` | Digest over the provider's normalized inventory listing — the set of `(upstream_id, upstream_name, collection_membership, per-item content digest)` tuples returned by `enumerate` plus `describe`, canonically serialized | revisionless providers such as `mcp:executive-circle` |

   An `inventory-snapshot` pin is a trust-on-first-use pin over the **catalog**,
   exactly as a per-item digest is a TOFU pin over one item, and it carries the
   same honesty requirement: it proves the inventory has not changed since it was
   recorded, and proves nothing about upstream authenticity. Re-resolution
   computing a different snapshot digest is **fail-closed drift** naming both
   digests; it is never silently re-pinned. This is what makes a revisionless
   provider usable as a Workspace catalog at all — without it, the `pin`
   requirement would be unsatisfiable for one of the three reference providers and
   the cross-catalog contract would be incomplete for it.
3. **An unqualified root resolves from the Workspace's own steward catalog**, as
   in v1. v1 manifests remain valid v1 manifests; v2 is additive.
4. **Alias-to-identity mapping is manifest-local.** Two Workspaces may use the
   same alias for different identities without interfering, because locks and
   diagnostics use canonical identity throughout.

### Direct manifest roots, not a separate environment manifest

Cross-marketplace roots appear **directly in the Workspace manifest**, qualified
as above. The alternative — a separate resolved environment manifest — was
rejected: it would create a second desired-state document, and ADR-0010 Decision
12 exists specifically to retire parallel Library desired-state manifests.

The lock already is the resolved artifact. Adding a third document between
manifest and lock would put the reviewable pin in a file nobody reviews.

### What is restated unchanged from ADR-0010

These are **non-replaceable** and are restated, not re-derived:

- **Fail before mutation.** Complete resolution of the entire selected root set
  precedes any target mutation. Incompatible constraints, ambiguous catalog
  matches, target collisions, cycles, and scope mismatches fail with every root,
  constraint, canonical identity, and steward named in the diagnostic.
- **Deterministic pins.** Every resolved node records canonical catalog identity
  and definition pin regardless of display alias.
- **Scope isolation.** One operation reconciles exactly one lock scope. A
  cross-catalog Workspace does not gain the ability to mix project and global
  targets. Intrinsically global dependencies remain non-owning prerequisite
  assertions.
- **Shared ownership.** A receipt reachable from two roots survives the removal of
  one. The authoritative owner set is recomputed from a fresh complete resolution;
  `owners_cache` is never resolver input.
- **Provenance-bound, fail-closed prune.** All seven ADR-0010 Decision 8
  conditions hold unchanged.
- **The foreign-catalog prune guard.** Restated with the distinction this ADR
  requires: a catalog is **registered in the resolved Workspace closure** when its
  canonical identity appears in the `catalogs:` block of a Workspace in the
  selected scope's freshly resolved root set. A receipt whose `catalog_identity`
  is registered in that closure is prunable subject to every other condition. A
  receipt whose `catalog_identity` is **not** in that closure is a foreign owner
  and is never pruned by this scope. The fail-closed default is authoritative:
  when closure registration cannot be determined — unresolvable catalog, degraded
  provider, missing identity, or the legacy value `catalog_identity: unknown`
  observed in `mira/.library.lock` — the receipt is treated as foreign.

### No-overlay semantics: restated, not replaced

The no-overlay rule is **restated unchanged**. Composition remains an unordered
set union. There is no overlay layer, exclusion layer, precedence order, or
last-writer-wins behavior. Version conflicts, target collisions, and scope
mismatches fail before mutation.

Cross-catalog composition makes overlays *more* tempting, which is exactly why the
answer is no: an overlay across a trust boundary would let a lower-precedence
external catalog's item be silently replaced by another source under the same
name. That is the redirection attack the `catalogs:` block was designed to
prevent, reintroduced through the composition layer. A consumer wanting "all
except one member" splits the Workspace.

### Offline ownership-derived deletion refusal

Ownership-derived prune and `--prune --apply` **fail closed** whenever any
provider in the resolved scope closure is unavailable, returns an inventory that
is incomplete, truncated, or reduced by changed authorization, or no longer lists
a previously installed item. See `Offline Semantics` for the full behavior and for
the `upstream-vanished` receipt state.

### Implementation record (slice 5, `CL-dbam`)

Delivered: schema v2 validation in both `docs/schema/workspace.schema.json` and
`scripts/lib/workspace.py`, cross-catalog closure resolution with per-node
canonical identity and pin, the mutation gate, and the restated foreign-catalog
prune guard. v1 manifests validate unchanged.

Three points where the implementation is more specific than the text above, each
because the text alone admitted a reading that would have broken something:

1. **Registration has two sources, not one.** Read literally, "registered in the
   resolved Workspace closure" would mean *only* a v2 `catalogs:` block, and a
   v1-only scope would register nothing and could never prune. The implemented
   rule is the union of ADR-0010's shipped provenance comparison — the audited
   catalog and its configured first-party source catalogs — with this ADR's
   addition: every identity a resolved Workspace registers, meaning its steward
   and its declared catalogs. A marketplace or provider is deliberately excluded
   from the first source: configuring one is not registration, and reaching one
   requires the pinned declaration this section is about.
2. **"Unresolvable catalog" is not "unresolvable member."** A registered
   Workspace whose manifest can no longer be read makes registration
   undeterminable and suspends the scope's prune. A stale direct root whose
   member left the catalog does not: it is reported as a blocker, and the
   catalog it records still counts. Collapsing the two would let one stale entry
   suspend an operator's ability to remove anything, which contradicts shipped,
   tested behavior.
3. **Every resolved catalog must be declared, in v2.** The ADR requires a pin on
   every resolved node; a dependency resolving into a catalog the manifest does
   not declare therefore has no pin available, and the resolution fails naming
   the member and the undeclared identity rather than recording an unpinned
   node. This also closes a redirection path the qualifier alone leaves open: a
   published item's `requires:` cannot pull the closure into an unreviewed
   source.

`gate_workspace_mutation` is the single door from a completed resolution to a
mutation. It refuses an item the resolution did not select, an item carrying a
selected member's name under a different provider identity, a duplicate item, an
item with no content, and a selection that does not cover every resolved
artifact, before applying `executable_admission.gate_resolution`. The writer is
called by that gate with the frozen content the gate digested.

**Materialization is staged behind the adapters, deliberately.** A v2 Workspace
resolves, validates, and previews in this slice; `library workspace use` refuses
to materialize a closure with declared catalogs. The reason is not incompleteness
but honesty: the existing installer path fetches each member from the live
catalog and would ignore the declared pin entirely, so installing now would ship
a `catalogs:` block that looks pinned and is not. Verifying the pin against the
source, normalizing members into inventory items, and putting the gate in the
write path is `CL-mvet`'s work.

**Adversarial review of this slice produced five accepted blocking findings**, all
repaired before delivery, and each is a place the first implementation looked
correct while a probe walked through it:

| Finding | Repair |
|---|---|
| Pins were recorded on every node and never verified against anything, and the mutation gate had no production caller | Declared pins are recorded on the requested root at registration and a changed pin is fail-closed drift naming both values; materialization of a cross-catalog closure is refused outright until the adapters land |
| The gate accepted a strict subset of the closure, so calling it with an empty selection returned success and invoked the writer | The gate now requires every resolved artifact to be supplied exactly once with content |
| An observation with `complete: true` and an empty listing authorized deletion of a receipt whose upstream had vanished | An empty listing is not a complete inventory; a receipt absent from a complete listing is `upstream-vanished` and is never deletion authority |
| No production path supplies catalog observations, so a healthy cross-catalog prune was unreachable | Resolved by the staging boundary above: a scope cannot hold v2 receipts until materialization lands with the observations that authorize pruning them |
| ADR-0010 Decision 8 condition 2 (catalog identity, resolved version, **and** source pin known) was not enforced anywhere | Enforced in the plan and re-derived in the preflight immediately before deletion; a plan with no recorded catalog closure is refused outright |

Two further hardenings were made without a reviewer asking, because the cache
slice had already paid for both lessons: catalog observations carry an explicit
evidence window with no default, so a stale observation cannot authorize today's
deletion; and an observation attributed to a different source is refused.

**A second adversarial round found four more, all accepted and repaired**, and
three of them were the first round's repairs relocating the unsafe assumption
rather than removing it:

| Finding | Repair |
|---|---|
| Declared pins still did not constrain resolution: they were copied onto every node and compared with nothing, so an edit to the local catalog changed the closure while every node reported its pin | A cross-catalog closure is not produced at all without a caller-supplied verifier that answers what each declared source currently serves; a differing, empty, or failed answer is fail-closed drift naming both values |
| A nonempty but irrelevant listing, or a receipt with no recorded upstream identity, still authorized pruning | Under a cross-catalog closure a receipt must appear in its source's complete listing; absence is `upstream-vanished`, and a receipt with no upstream identity is undeterminable and therefore not deletable |
| Observation freshness was measured against a caller-supplied run clock, so 2020 evidence beside a 2020 run time passed in 2026 | Freshness is measured against the real clock; the caller-supplied run time is gone, and future-dated evidence is refused as well |
| Cycle and ambiguity diagnostics carried display catalog names only, so AC3's "canonical identities and stewards named" held for constraint and collision failures and not for these | Every resolver failure is re-raised naming the root, its constraint, its canonical identity, and its steward |

**The residual, stated rather than implied.** A verified pin proves the source
has not moved. It does not prove that a consuming repository's catalog document
describes that revision, because members are still read locally until an adapter
fetches at the pin. Slice 5 therefore ships resolution, validation, and preview
with verified pins, and refuses materialization; `CL-mvet` closes the second half
by fetching at the pin. A test asserts this limitation directly so a later reader
finds it in the suite instead of inferring a guarantee that is not there.

Kimi was unavailable for both rounds of this slice (`provider.auth_error: 403
You've reached your usage limit for this billing cycle`), so the user-mandated
second reviewer produced no verdict. Compensating evidence: every proof of
concept from both rounds is a regression test in the delivered suite, including
an end-to-end CLI test that a v2 manifest validates and refuses to install while
writing no lock and no files.

### Nested Workspace disposition

**Nested Workspaces remain deferred.** This ADR admits cross-catalog roots and
nothing else.

The two features were bundled in ADR-0010's deferral, and separating them is
deliberate. Cross-catalog roots add a resolution and trust dimension to a graph
whose shape is unchanged. Nested Workspaces change the graph shape itself and
would require cycle detection, hidden-removal semantics, and nested ownership
visibility. No evidence for the second exists, so it stays deferred with its
original conditions: independent justification plus cycle handling, ownership
visibility, and removal semantics.

### Consumer Lock Evidence

ADR-0010 gates cross-catalog manifest roots on "at least two real consumers
requiring the same nested or cross-catalog lifecycle."

**Observed evidence.** Three committed `.library.lock` files compose across
catalogs today. Each path is repository-relative to its own repository:

| Repository | Lock path | Distinct `catalog_identity` values |
|---|---|---|
| `library/meta` | `.library.lock` | `https://github.com/cognovis/library`, `https://github.com/cognovis/library-core` |
| `library/cognovis-pi` | `.library.lock` | `https://github.com/cognovis/library`, `https://github.com/cognovis/library-core` |
| `mira` | `.library.lock` | `https://github.com/cognovis/cognovis-pi`, `https://github.com/cognovis/library`, `unknown` |

**What this evidence does and does not prove.** It proves that cross-catalog
composition is real and routine. It does **not** satisfy the gate as written,
because every one of these locks composes at the **scope boundary** — several
directly registered Workspaces, one per catalog — which is precisely the ADR-0010
v1 escape hatch. None of them demonstrates a consumer that *requires* a
cross-catalog root inside a single manifest. Presenting scope-boundary
composition as manifest-root evidence would be reading the gate to pass itself.

**Therefore the gate is amended, not satisfied.**

**Amendment (Human Decision, Malte Sussdorff, 2026-08-08, FINAL since 2026-08-09).** The
ADR-0010 two-consumer evidence gate is waived for cross-catalog manifest roots
only. Rationale on record: the gate was written to prevent speculative lifecycle
complexity, and the complexity here is no longer speculative — three committed
locks compose across catalogs, the scope-boundary workaround forces a consumer to
publish one Workspace per catalog for what is one baseline, and the heterogeneous
providers this ADR admits (`mattpocock`, `mcp:executive-circle`, `disler`) cannot be
reached by a first-party Workspace at all without qualified roots. Nested
Workspaces, the other half of the original deferral, keep the gate unchanged.

The amendment is **final** as of 2026-08-09. The finalizing slice-1 evidence is
recorded in `Approval Finalization`.

### Approval Finalization

The Workspace v2 contract above is complete as a contract and provisionally
approved. It becomes **final** only on concrete evidence from implementation
slice 1.

| Element | Value |
|---|---|
| Current state | `final` — finalized by Malte Sussdorff, 2026-08-09, on delivered slice-1 evidence (`CL-coif`, merged as `2b16f5d`) |
| Finalizing slice | Slice 1, provider core and normalized inventory (`Implementation Slices`) |
| Final state on success | `final` — the amendment stands and later slices unblock |
| Final state on failure | `withdrawn` — the amendment lapses, ADR-0010's gate is restored unamended, and Workspace v2 returns to deferred |

**Evidence that finalizes the approval.** All four must hold, and all four are
deliverable **within slice 1's own scope** — this was checked against `CL-coif`'s
acceptance criteria rather than assumed. Workspace-v2 schema validation and
cache/receipt round-tripping are deliberately *not* required here, because slice 1
scopes both out; requiring them would make the gate unsatisfiable by the only
slice authorized to satisfy it.

| # | Evidence | Slice-1 AC that delivers it |
|---|---|---|
| 1 | **A working normalized-inventory contract over at least one real provider.** `enumerate` plus `describe` produce normalized items with populated `provider_identity`, `upstream_id`, `upstream_name`, `collection_membership`, `library_type`, and `rights` for a live reference provider, with no local checkout | `CL-coif` AC1 and AC3 |
| 2 | **No provider-specific branches in core.** A mechanical check proves the resolver, cache, and Workspace modules contain no provider name, provider-kind conditional, or upstream URL, and it fails CI when one is introduced | `CL-coif` AC4 |
| 3 | **Passing catalog validator tests.** `library.yaml` accepts `provider_kind`, `allowlist`, `auth_ref`, and `rights`, rejects an unknown `provider_kind`, and rejects a `git-org` entry with no `allowlist` | `CL-coif` AC5 |
| 4 | **A round-trip qualified identity.** One normalized item round-trips from provider through the canonical `<provider-identity>#<upstream-id>` and back without loss | `CL-coif` AC6 |

The Workspace-v2 schema negative cases — unpinned `catalogs:` entry, URL in a
root, undeclared alias, `catalog:` qualifier in a v1 manifest — and the
cache-identity-to-receipt round trip remain required, but they are **acceptance
criteria of the slices that own them** (`CL-dbam` AC2 and `CL-y5z4` AC3), not
inputs to this gate. They are gated *by* this approval; they cannot also gate it.

All four held on the delivered slice-1 candidate (`CL-coif`, delivered `2ebf699`,
merged `2b16f5d`, closed 2026-08-09 after a CLEAN two-reviewer adversarial gate):

1. 35 normalized items enumerated live from `https://github.com/mattpocock/skills`
   with no local checkout, enforced in-test by blocking `subprocess` and
   `tempfile` (`tests/test_source_provider_contract.py`).
2. `scripts/checks/provider_neutrality.py` PASS, wired into CI
   (`.github/workflows/provider-contract.yml`) and failing on every injected
   violation class (`tests/test_provider_neutrality.py`).
3. The catalog validator accepts `provider_kind`, `allowlist`, `auth_ref`, and
   `rights` and rejects the negative cases
   (`tests/test_library_yaml_provider_fields.py`, `scripts/validate-library.py`).
4. Lossless qualified-identity round trip
   (`tests/test_normalized_inventory.py::test_qualified_identity_round_trip`).

Known bounded caveat, accepted at finalization: the neutrality proof covers the
three ADR-named core modules; 15 legacy modules (foremost `scripts/lib/source.py`)
remain provider-aware under a ratcheted baseline and are driven to zero by
`CL-mvet`. This section's status field remains the authoritative answer to "is
cross-catalog Workspace composition approved?" and the answer is "yes, final".

## Cache Transaction

Content-addressed caching extends beyond Skills and beyond Git.

### Cache identity

The cache key is a tuple, not a path convention:

```text
(provider_identity, upstream_id, upstream_revision | null,
 normalized_content_digest, library_type, transformation_version)
```

This replaces the current `<type>/<marketplace>/<name>@<commit14>` key
(`scripts/lib/cache.py` `compute_cache_path`).

**The precise defect, corrected after review.** The current key does *not* collide
two revisionless items across different providers: `marketplace` and `name` are
both path segments, so `provider-a/kit-x@local` and `provider-b/kit-x@local` are
distinct. That earlier claim was wrong. The real collisions are within a provider:

| Collision | Current key | Why |
|---|---|---|
| Same provider, same name, **different content** | `provider-a/kit-x@local` for both | A revisionless item's every version pins to the literal tag `local`, so changed upstream bytes overwrite the cache object in place, destroying the only copy of the previous bytes and erasing the drift signal |
| Two **different upstream IDs** that normalize to the same Library name | one path for both | The key carries `name`, not `upstream_id`, so upstream identity is lost |
| Same content reached under **different transformation rules** | one path | The key has no transformation dimension, so changing a projection rule silently rewrites an existing object |

The tuple key fixes all three: `normalized_content_digest` separates content,
`upstream_id` separates upstream identity, and `transformation_version` separates
projection rules.

`normalized_content_digest` is a Library-computed digest over normalized content
bytes, and it is the **only** integrity proof the Library relies on. A
provider-native proof from `verify()` is recorded as supplementary evidence when
available.

### Trust on first use

For a revisionless provider (`revision_of` absent), the first observed
`normalized_content_digest` is a **trust-on-first-use pin**. It is recorded as
such, explicitly: it proves that the bytes have not changed since first
observation, and it proves nothing about upstream authenticity.

A re-fetch whose digest differs is **fail-closed drift**. It is never silently
accepted, never auto-upgraded, and never overwrites the pinned object. It becomes
a visible drift status naming both digests and requiring an explicit operator
decision.

**Decision on freshness polling.** Revisionless providers are **pin-only**. They
do not support digest-polling freshness. A poll can only report "the current bytes
differ from your pin", which is drift — a state the operator must resolve — and
dressing that up as a freshness signal invites automatic re-pinning, which is
exactly the silent-substitution failure this ADR forbids. `executive-circle` is
governed by this rule.

### Install and adoption transaction

Ordered, and the order is the contract:

1. **Retrieve** complete content. A partial or truncated retrieval aborts here.
2. **Verify** the normalized digest against the pin, or record the first-use pin.
3. **Materialize atomically** into the cache: write to a temporary object, then
   atomically swap into the final cache path. A crash never leaves a partial
   cache object visible.
4. **Write the receipt**, including rights state, admission state, transformation
   identity, and cache digest.
5. **Only then activate target projections.**

**No harness projection becomes active before its cache object and receipt are
complete.** The historic failure this prevents is a live projection whose bytes
cannot be reproduced once the provider disappears — which is the current state of
`~/.claude/workflows/`.

### Transformation Identity

When installed bytes are not byte-identical to upstream bytes, the receipt
records a `transformation_version` naming the exact projection rule applied
(frontmatter normalization, path rewriting, harness bridge shape). It is part of
the cache key, so changing a projection rule produces a new cache object rather
than silently rewriting an existing one.

A transformation is **not** an adaptation. A transformation is a mechanical,
reproducible projection the Library applies to unmodified upstream content. A
material adaptation produces a first-party derivative, which is governed by
`Distribution Rights`.

### Implementation record (slice 3, `CL-y5z4`)

Six readings of the sections above were open. They are resolved in the
implemented cache (`scripts/lib/providers/foreign_cache.py`,
`cache_transaction.py`, `offline.py`, `receipts.py`) rather than left to each
call site.

1. **`normalized_content_digest` covers upstream bytes, not transformed ones.**
   It is the subject of the trust-on-first-use pin, and a pin has to be
   comparable against what a later re-fetch returns; a pin over transformed
   bytes would change meaning whenever a transformation rule changed. The cache
   object *stores* the transformed bytes, because those are what an outage must
   reproduce, and carries its own `projected_content_digest` as the integrity
   proof of the stored object. Under the identity transformation the two are
   equal, which is why the distinction is easy to lose.
2. **The digest function is adopted from executable admission, not forked.**
   Slice 2 left this open and required only that admission stay bound to
   content. Two independent digests over the same bytes would reopen exactly the
   gap that binding closes: a decision recorded against one identity while the
   cache stores another.
3. **A cache object is self-describing.** It stores the whole key tuple beside
   its content, so an object can be identified without the receipt that
   references it — which is what the operator-explicit purge of `Retention,
   Garbage Collection, and Explicit Purge` needs to prove anything by digest.
   Every tuple member is length-framed and a null revision is framed as its own
   marker, so a revisionless identity can never collide with a pinned one.
4. **A refused projection keeps its cache object and its receipt.** `Caching is
   not installing`: the bytes were lawfully fetched and verified, so they stay
   durable and recorded, and the receipt records zero targets and
   `verified: false`. Likewise, a **failed receipt write does not roll back the
   materialized object** — a failure is not deletion authority over retrieved
   and verified bytes.
5. **`degraded` is treated as unavailable for every refused row of the offline
   table.** A truncated or partial answer is not a complete resolution, and both
   deletion authority and remote comparison require one.
6. **Explicit named removal archives the retired receipt.** ADR-0011 requires
   the removal to record the degraded state and the operator's intent in receipt
   history; discarding the record with the receipt would destroy the one entry
   nobody can reconstruct afterwards.

Adversarial review then demonstrated, by execution, six further gaps that the
ADR text implies but does not say, and the implemented contract now states them:

7. **A removal deactivates the projection it retires.** Retiring the receipt
   alone left the installed files in place with nothing describing them —
   recreating the exact unreceipted projection this section exists to end.
   Deactivation happens *before* the receipt is retired, which is the reverse of
   the install order and for the same reason: the recoverable failure is a
   receipt without its targets, never a target without its receipt.
8. **Projection is two-phase.** The receipt declares its intended target paths
   before anything is written and records the install-time proofs afterwards.
   Recording the inventory only after activation leaves a window in which a live
   projection is described by a zero-target receipt.
9. **Executable admission binds the projected bytes.** A transformation that
   rewrites content produces bytes no reviewer saw, so admitting the upstream
   digest and installing the transformed one repeats precisely the divergence
   `Executable admission` forbids. The upstream digest remains the
   trust-on-first-use identity.
10. **Completeness is proven or named.** A first retrieval's completeness is not
    decidable from its own bytes: a truncated item is a valid item of a
    different shape. It is established against a member manifest, against an
    existing pin, or on the adapter's contract alone — and the receipt records
    which, so `adapter-declaration` is a queryable fact rather than a silence.
11. **Reachability is not a complete resolution.** Every destructive verdict
    requires a source-scoped observation that is complete and not narrowed by
    changed authorization. An observation also may only change receipts of the
    source it describes; one source's complete listing marked another source's
    receipts as vanished before this was explicit.
12. **A verified read and an installed read are one read.** A repair takes one
    immutable snapshot, digests that snapshot, and installs that snapshot.
    Reading twice is a check-to-use window, and it was walked through. For the
    same reason a corrupt object is never reused or silently replaced: repair is
    an explicit act that must reproduce the recorded digest.

## Offline Semantics

Offline operation is **additive and repair-only**.

| Operation | Provider unavailable | Rationale |
|---|---|---|
| Reinstall from verified cache | **Allowed** | The bytes are present and verified; no remote claim is made |
| Integrity verification | **Allowed** | Purely local |
| Status | **Allowed**, with freshness reported as `unknown` | Never `current` |
| Upgrade | **Refused** | An upgrade requires a remote comparison |
| Re-pin | **Refused** | Would silently substitute |
| Ownership-derived prune | **Refused, fail closed** | Deletion authority derives from a complete resolution |
| `--prune --apply` | **Refused, fail closed** | Same |
| Explicit named removal of a named receipt | **Allowed** | See below |
| Automatic garbage collection | **Refused, fail closed** | See `Retention, Garbage Collection, and Explicit Purge` |

`verified local integrity` and `unknown remote freshness` are separate reported
facts and are never merged into one "ok".

### Degraded inventory and `upstream-vanished`

Prune fails closed when any provider in the resolved scope closure is
unavailable, **or** returns an inventory that is incomplete, truncated, or reduced
by changed authorization, **or** no longer lists a previously installed item.

The last case is distinct and durable. When a provider is reachable and complete
but a previously installed item is absent from its inventory, the receipt enters
the durable, queryable state **`upstream-vanished`**. It remains there until the
upstream identity reappears or the receipt is explicitly removed. It is never
converted into deletion authority — a vanished upstream is exactly when the local
cache is most valuable.

### Explicit named removal under degraded conditions

**Explicit named removal of a named receipt remains available under every
degraded-inventory condition.** It:

- records the degraded provider state and the operator's intent in receipt
  history;
- is **never** triggered by ownership-derived prune;
- **never** implicitly deletes the underlying cache object.

This is deliberate: an operator must always be able to remove something they can
name, even during a total provider outage, and doing so must never destroy bytes
that may not be re-fetchable.

## Distribution Rights

Four grants are recorded **independently**, each with a named evidence source and
each resolving to `granted`, `denied`, or `unknown`:

| Grant | Question |
|---|---|
| `fetch_authorization` | May these bytes be retrieved with the configured credentials? |
| `install_rights` | May they be materialized for local use? |
| `redistribution_rights` | May they be copied into a tree that others receive? |
| `derivative_rights` | May a materially adapted first-party derivative be created? |

Authorization to fetch is **not** permission to redistribute. A subscriber token
proves the first and says nothing about the second.

**Implementation record (slice 2, `CL-n7ex`).** "Each with a named evidence
source" is implemented as evidence **per grant**, with the item-level
`evidence_source` retained as the fallback for grants that have none of their
own. One shared string cannot state that a fetch grant rests on a reachable
subscriber endpoint while a redistribution grant rests on nothing located at
all, and that is precisely the pair this ADR ships as its worked case.

The phrase is read as a **requirement, not a description**: resolving a grant to
`granted` or `denied` without a named evidence source is refused at
construction and at provider registration. `unknown` is the state for "nobody
has looked", and it is the only one reachable without evidence. Adversarial
review made the cost of the weaker reading concrete — an all-`granted` rights
value invented at a call site authorized a committed projection, durable
retention, and a derivative, with nothing behind any of them.

The operator opt-in is issued, not asserted. An opt-in-required act is
authorized only through a presenter: the gate renders the statement, issues a
single-use presentation, hands it to the presenter, and accepts only an
acknowledgement carrying that presentation's token and digest. An
acknowledgement therefore cannot exist unless the statement was rendered first,
and it authorizes exactly one act. Two weaker designs were tried and both were
broken by review: a boolean flag can be passed without rendering anything, and a
value bound only to a publicly computable digest can be self-minted with nothing
ever shown.

The statement names the **subject** — the qualified identity of the item —
alongside the target and every grant. The subject is load-bearing, not
decoration: rights are recorded per provider, so without it two items from one
provider render byte-identical statements and one acknowledgement silently
covers content the operator never saw.

A composed decision is a **report, not a capability**. The mutation boundary
re-derives it from the recorded rights and refuses any decision that does not
match, so a hand-built decision claiming `allowed` over a recorded denial writes
nothing. Proving *who* the operator is remains out of scope: authenticating an
operator is credential handling, and this ADR's gate binds an acknowledgement to
content rather than to an identity.

### Caching is not installing

Three capabilities are separated, and the separation is what makes the table
below sound:

| Capability | Governed by | Meaning |
|---|---|---|
| **Retrieve (transient)** | `fetch_authorization` | Bytes are requested from the provider and held only for the duration of the operation |
| **Retain durably in cache** | `install_rights` | Authorized bytes are kept in the content-addressed cache across sessions and are available for offline repair. No projection exists; nothing is on a harness path |
| **Install (project a machine-local copy)** | `install_rights` | Bytes are materialized into a usable machine-local target |
| **Redistribute (project into a committed tree)** | `redistribution_rights` | Bytes enter a tree that others receive |

**Retrieval authorization is not retention authorization.** A credential proving
endpoint access proves that the provider will serve the bytes now; it says nothing
about a right to keep an indefinite offline copy. Durable cache retention of
third-party content is therefore governed by `install_rights`, not by
`fetch_authorization`. This was corrected after review, which observed that
treating a subscriber token as a retention grant is exactly the conflation the
rest of the rights model exists to prevent.

`install_rights: unknown` does not forbid durable retention outright — it makes it
an **operator-acknowledged** act, under the same explicit opt-in as a machine-local
projection, and the rights state is shown first. `install_rights: denied` forbids
durable retention; only transient retrieval remains.

A lawfully fetched and lawfully retained artifact may therefore sit `verified` in
the cache while its committed projection stays blocked. Cache retention is not a
projection — but it is also not free of rights.

### Invariant 13 binding

**A project projection without confirmed redistribution rights must not
materialize third-party bytes into a committed vendored tree.**

Projection eligibility composes the grants in order. `install_rights` is checked
**first** and governs both targets; `redistribution_rights` then adds the separate
committed-tree restriction. A recorded denial of local installation is not
something an operator opt-in may override — the opt-in exists to accept a
*redistribution* risk the operator is entitled to accept, not to grant a
permission the upstream party withheld.

| `install_rights` | `redistribution_rights` | Machine-local gitignored projection | Committed project projection |
|---|---|---|---|
| `granted` | `granted` | Allowed | Allowed |
| `granted` | `unknown` | Explicit policy or operator opt-in, after the rights state is displayed | **Blocked (default)** |
| `granted` | `denied` | Explicit policy or operator opt-in, after the rights state is displayed | **Blocked** |
| `unknown` | any | Explicit policy or operator opt-in, after the rights state is displayed | **Blocked** |
| `denied` | any | **Blocked. No opt-in overrides a recorded denial** | **Blocked** |

`unknown` binds to the blocked default on both axes. It is not a permissive middle
state; it is the conservative one, and the distinction from `denied` is that
`unknown` is unfinished work an operator may knowingly accept for a machine-local
target, whereas `denied` is a decision someone else already made. The chosen
behavior is displayed **before** mutation, never discovered afterwards.

Worked case, because it is the one this ADR actually ships: `executive-circle`
resolves `fetch_authorization: granted` and `install_rights: unknown`. Its bytes
may be fetched and cached. Its committed projection is blocked. Its machine-local
projection requires an explicit operator opt-in shown first, and that opt-in
accepts an *unresolved* rights state rather than overriding a refusal.

### Derivative works

Third-party source stays upstream. A materially adapted artifact becomes a
first-party derivative with explicit upstream provenance and pin.

**Adaptation is itself a licensed act.** A first-party derivative may be created
only where `derivative_rights` is `granted`, and may be committed or redistributed
only where `redistribution_rights` also permits that use. Without a
derivative-works grant, **no adapted artifact is created at all**; only the
unmodified upstream artifact may follow the blocked-by-default or explicit
machine-local path above, and the unresolved rights state is retained in
provenance.

### Revoked access

Revoked provider access does **not** automatically erase already-authorized cached
bytes. It does change forward policy: a receipt whose provider access is revoked
records that state, and future projection or sharing follows the recorded
`redistribution_rights` — which revocation does not improve.

### Credential isolation

Credentials live in provider configuration and are referenced by name. Cache
objects contain only authorized artifact bytes and non-secret provenance. No
token, cookie, header, or private transport configuration is ever written into a
cache object, a receipt, or a projection. `auth_requirements()` returns credential
*references and scopes*, never values.

### Resolved rights for the reference providers

Full evidence in `docs/research/external-marketplace-reference-matrix.md`.

| Provider | fetch | install | redistribution | derivative | Evidence source |
|---|---|---|---|---|---|
| `mattpocock/skills` | `granted` | `granted` | `granted` | `granted` | Upstream `LICENSE` (MIT) confirmed via `raw.githubusercontent.com` HTTP 200 and the GitHub repository API reporting `spdx_id: MIT`, 2026-08-08 |
| `disler` (allowlist: `pi-vs-claude-code`, `fusion-harness`, `planf3`) | `granted` | `granted` | `granted` | `granted` | Per-repository MIT `LICENSE` recorded in `/Users/malte/code/library/cognovis-pi/docs/research/indydevdan-pi-repos.md`, with commit pins |
| `mcp:executive-circle` | `granted` | `unknown` | `unknown` | `unknown` | Subscriber-token-scoped MCP endpoint in `~/.codex/config.toml` and `~/.claude.json`; no published licence or redistribution grant located |

At least one provider exercises the rights-restricted path, so no constructed
`unknown` case is required: **`executive-circle` resolves to `unknown` for
install, redistribution, and derivative rights.** Its committed project projection
is therefore **blocked by default**, and a machine-local gitignored projection
requires an explicit operator opt-in shown before mutation. Its prompt-kit content
is additionally revisionless, so it is pin-only under `Trust on first use`.

Two related traps, recorded because both are live:

- Nate B. Jones's `https://github.com/NateBJones-Projects/OB1` is **not** the
  Executive Circle source. It must never be conflated with the
  `mcp:executive-circle` provider identity or used as a substitute when the MCP
  provider is unreachable.
- The `disler` grant is per repository, not organizational.
  `indydevdan-pi-repos.md` records `live-bench` with **no observed LICENSE file**.
  It is not on the allowlist, and if it were added its rights would resolve to
  `unknown`.

## Migration

### Schema and version identity

| Artifact | From | To | Rule |
|---|---|---|---|
| Workspace manifest | `schema_version: 1` | `schema_version: 2` | Additive. v1 manifests stay valid and are not rewritten. A `catalog` qualifier in a v1 manifest is a validation error |
| Cache object | `<type>/<marketplace>/<name>@<commit14>` | Tuple key incl. digest and `transformation_version` | Re-key by **re-materialization**, never by renaming a directory |
| Lock receipt | v2 receipt fields | v2 plus rights, admission, transformation, and cache-digest fields | Additive fields; absent fields read as `unknown` |

### Re-key versus re-materialization

Existing cache objects are **not renamed into the new key space**. A legacy object
lacks a recorded normalized digest and a transformation identity, so a rename
would fabricate identity it never had. Legacy objects are re-materialized on next
install or repair, which recomputes the digest honestly.

An unresolvable legacy receipt — one whose source, digest, or catalog identity
cannot be reconstructed — is marked `unresolvable`, retained, and prune-blocked.

**Migration grants no deletion authority.** This is restated from ADR-0010
Decision 6 and holds for cache objects, receipts, and projections alike.

### Legacy Projection Disposition

Already-materialized third-party projections are inventoried and classified by
redistribution state.

**Inventory method, stated because it determines what the inventory can and
cannot say.** Taken 2026-08-08 by intersecting the names under `~/.claude/skills/`
with the upstream `mattpocock/skills` tree at `skills/<category>/<name>/SKILL.md`,
and by listing `~/.claude/workflows/`, then checking each against
`~/.config/library/global.lock`. Name matching is the only method available
**because none of these projections has a receipt** — and that is the finding, not
a limitation of the survey. With zero receipts there is no recorded provenance,
so it is not possible to state from local evidence whether a given directory came
from `mattpocock`, from a first-party catalog, or from a hand copy. Slice 7
(`CL-m6cc`) must re-derive provenance by content digest, not by name.

| Projection group | Count | Location | Receipt | Rights | Disposition |
|---|---|---|---|---|---|
| Directories whose names match upstream `mattpocock/skills` items — including `implement`, `ask-matt`, `tdd`, `code-review`, `research`, `resolving-merge-conflicts`, `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `grilling`, `prototype`, `triage`, `wayfinder`, `to-spec`, `to-tickets`, `teach`, `handoff`, `improve-codebase-architecture`, `grill-me`, `grill-with-docs`, `setup-matt-pocock-skills`, `claude-handoff`, `loop-me` | **23** | `~/.claude/skills/<name>` — 12 real directories and 11 symlinks into `~/.agents/skills/<name>` (themselves real directories) | **none** — 0 of 23 | `granted` **if** upstream is `mattpocock` (MIT); **unverified** per item until provenance is re-derived | Machine-local global scope, not a committed tree, so nothing is currently non-compliant. Re-derive provenance by content digest, then either adopt under the ADR-0010 exact-digest adoption path once the provider is registered, or leave as untracked operator-owned content |
| Workflow specs `bead-context-pack.js`, `bead-review.js`, `quick-fix.js`, `stream-review.js` | **4** | `~/.claude/workflows/` | **none** — 0 of 4 | first-party | Re-materialize from catalog on next install so a receipt exists. First-party, so no rights issue — but an unreceipted projection is unreproducible regardless of who wrote it |

A Library-**shaped** bridge without a Library receipt is not Library-owned; the
shape does not confer ownership. Eleven of the 23 have exactly that shape, which
is why shape is not accepted as evidence anywhere in this ADR.

Rules that follow:

1. A legacy projection resolving to `unknown` or `denied` redistribution is marked
   **non-compliant**. It **cannot be re-materialized** by future sync or repair.
2. A non-compliant projection receives an explicit remediation path: operator-
   confirmed removal, or relocation to an allowed machine-local projection.
3. **Migration never silently deletes committed bytes.** Non-compliant committed
   content is reported and remediated by an operator decision, never by the
   reconciler.
4. No projection above is currently non-compliant: all are either MIT or
   first-party. This is a fortunate accident of what was installed, not evidence
   that the rule is unnecessary — every one of them was materialized with no
   rights check at all.

## Retention, Garbage Collection, and Explicit Purge

### Retention inputs

1. **Active receipts protect their cache objects.** An object referenced by any
   active receipt in any scope is ineligible for garbage collection.
2. **Re-fetchability is also a retention input, and it must be *proven*, not
   inferred from provider health.** Automatic garbage collection **fails closed**
   for an unreferenced foreign object whenever exact re-fetchability is not
   proven. It is not proven when:
   - the provider is unavailable; or
   - access is revoked; or
   - the upstream item no longer exists (`upstream-vanished`); or
   - **the object came from a revisionless provider** and a digest-verified
     re-fetch has not confirmed that the pinned digest is still what the provider
     serves.

The second input is what makes an outage survivable. A cache that discards
unreferenced objects during an outage discards exactly the bytes that cannot be
re-fetched, at exactly the moment they became irreplaceable.

**The revisionless clause is not an edge case, and omitting it was an internal
contradiction.** A revisionless provider has no immutable revision to request by;
`Trust on first use` decides that such providers are pin-only, and that a changed
digest on re-fetch is fail-closed drift. A provider can therefore be `available`,
authorized, and still listing an item while serving **different bytes** than the
pin. "Provider healthy" says nothing about whether *these* bytes can be retrieved
again. Deleting the object under that assumption would destroy the last copy of
the pinned content, and a later reinstall would record a fresh first-use pin —
converting detectable drift into undetectable silent substitution, which is the
outcome this ADR forbids everywhere else.

Therefore, for a revisionless-provider object, automatic garbage collection may
delete only after a **digest-verified re-fetch** proves the provider currently
serves the pinned digest. Without that proof, the object is retained and its
deletion is available only through the operator-explicit purge below.

### Operator-explicit purge

A separate operator-explicit purge is the only path that deletes an unreferenced
cache object under degraded conditions. It:

- **requires an object digest** — not a name, not a glob, not a provider;
- **proves no active receipt references that digest**, across every scope, before
  deleting;
- **records an explicit acknowledgement** that the loss is permanent and the bytes
  may not be re-fetchable;
- is **never** invoked by automatic reconciliation or garbage collection.

Degraded provider state never triggers a purge automatically. Purge is a human
act with a digest in their hand.

### Implementation record (slice 4, `CL-uliw`)

Implemented in `scripts/lib/providers/retention.py`, on the slice-3 primitives
rather than beside them: `ReceiptStore.referencing_digest` answers the reference
question for one store, `ForeignReceipt.upstream_state` and
`completeness_evidence` supply the recorded evidence, and
`offline.evaluate_operation("automatic-garbage-collection", …)` remains the one
table that decides whether collection may run against an observation at all.
Five readings were open, and the implemented contract states them:

1. **"Any scope" is a required set, not a supported one.** The reference check
   is constructed over named scopes and refuses unless every required scope —
   `project` and `global` — is present. A caller holding one store gets a typed
   refusal instead of a confident wrong answer, because a project-scoped
   maintenance run that cannot see the global lock reports "unreferenced" for
   objects that lock is holding.
2. **An unreadable scope is never an empty one.** A corrupt receipt file, or a
   scope whose declared location does not exist, raises rather than contributing
   zero references. The two states are the same silence and opposite facts.
3. **The two preconditions the offline table declines to evaluate are evaluated
   here, per object.** The table returns them as `additional_preconditions`; this
   module holds the object, so it answers them: no active receipt references it,
   and exact re-fetchability is proven. Every unmet condition is named, and a
   decision carries all of them rather than only the first.
4. **The revisionless clause extends to `adapter-declaration` completeness.** A
   pin-only source needs a digest-verified re-fetch before its unreferenced
   object may be deleted. An install whose completeness rests only on the
   adapter's word never had independent proof of what it stored, so it is in the
   same position and is treated identically. A re-fetch observing a *different*
   digest is fail-closed drift, not a licence to collect: deleting there destroys
   the last copy of the pinned content, and a later reinstall records a fresh
   first-use pin — turning detectable drift into undetectable substitution.
5. **Quarantined objects are retained evidence for collection and named-only for
   purge.** Automatic collection never sees a tree a repair set aside. An
   operator holding the digest may destroy it, but only by naming it explicitly,
   so reclaiming space can never silently remove the evidence of a corruption.

Two structural decisions support the guarantee that collection never escalates:

- **Deletion lives in retention, not in `ObjectStore`.** Slice 3 shipped a store
  with no delete path, and that stays true. Deleting bytes is a retention
  decision, and keeping the only deletion behind these gates is what makes the
  guarantee checkable. A deletion renames the tree into the store's staging area
  before removing it, so a reader sees the whole object or nothing, and an
  interrupted removal leaves a sweepable staging entry rather than a half-deleted
  object a later run would read as cached.
- **The digest and the acknowledgement are one value.** `PurgeAcknowledgement`
  carries the object digest, the operator, the reason, and the fixed
  acknowledgement token together, and no purge entry point takes a digest
  without it. Removing the requirement would have to delete the type's only
  constructor rather than add a default argument. The acknowledgement is written
  to a durable purge ledger *before* the deletion and completed afterwards, so an
  interrupted purge leaves the intent on record rather than an unexplained
  absence.

Both deleting paths re-prove their preconditions under
`TofuPinStore.identity_lock`, the same lock an install holds across retrieval,
materialization, the receipt, and activation. An object can acquire its first
reference between a plan and a deletion; taking that lock and evaluating again
is what makes "an active receipt protects its object" true for receipts that did
not exist when the plan was made.

Adversarial review then demonstrated, by execution, six further gaps, and the
implemented contract now states them:

6. **A scope is its location, not its label.** Two required labels over one
   store satisfied the scope set while hiding the other scope's receipts
   entirely, and an object a live global receipt referenced was collected.
   Required scopes must resolve to distinct locations.
7. **A quarantined tree is a bucket-level sibling, and nothing else is.**
   Searching the whole object root for a quarantine-shaped name let a purge of
   one digest reach a legitimate member directory nested inside another object's
   content, remove it, and leave that referenced object failing verification.
8. **A proof set is evaluated whole, and it must be current.** Keeping one proof
   per identity made the outcome depend on argument order: a stale proof that
   matched the pin overrode a current one that showed drift. Any disagreement
   inside the set is drift, and a proof older than the source observation it
   accompanies — or one whose time cannot be ordered against it — is stale.
9. **Every deletion runs under the identity lock an install takes.** When only
   quarantined bytes remain there is no canonical object to derive that identity
   from, and a synthetic lock name serialized against nothing. The identity is
   recovered from the quarantined tree's own descriptor, and a subject whose
   identity cannot be recovered is retained rather than deleted under a lock that
   protects nothing.
10. **A removal that does not complete is not a deletion.** Ignoring the removal
    error made the staging rename look like success: the caller reported the
    members as deleted and the ledger recorded `purged` while every byte was
    still on disk. Both a raising and a silently ineffective removal now fail
    loudly, and the ledger entry stays at its recorded intent.
11. **Degraded facts are independent and are all named.** An observation that is
    unavailable *and* truncated *and* narrowed by changed authorization reported
    one of the three, so an operator repairing it would fix one third of the
    problem. Precedence orders the primary reason; it does not hide the others.

A second adversarial round demonstrated five more, and they are stated too:

12. **A deletion follows no link, and a name is not evidence.** A
    quarantine-shaped symbolic link beside one object pointed at another
    object's canonical directory; validating the *resolved* path accepted it,
    because a canonical object sits at the same depth. Paths are now validated
    as written, every component from the object root down must be a real
    directory, and a quarantined tree must additionally prove through its own
    descriptor that it belongs to the digest that named it.
13. **The proof-to-deletion window is serialized against every receipt writer.**
    The install identity lock excludes the install transaction and nothing else;
    a bare receipt write is guarded only by the receipt file's own lock. A
    receipt committed after the final reference read and before the rename lost
    its object. Both deleting paths now hold every scope's receipt lock across
    the proof and the deletion, taken in a fixed path order.
14. **A malformed receipt store is never an empty one.** `receipts: null` parsed
    as "this scope holds nothing", and absence of receipts is deletion authority
    everywhere that consumes the store. Receipt and retired records must be
    strictly typed lists, so a damaged scope refuses instead of authorizing.
15. **Evidence has to describe the present, and how recent is operator policy.**
    A source observation and a re-fetch proof that agree with each other prove
    nothing if both were taken long before the run; review supplied a matching
    pair twenty-six years old and the last copy of a revisionless object's
    pinned bytes was deleted. Collection now takes a required
    `evidence_max_age`, with no default, and evidence outside that window — or
    dated after the run — is typed and fails closed.
16. **The dry run reports the whole object, not only its payload.** A deletion
    removes the object directory including its self-describing descriptor, while
    the plan measured `content/` alone and reported 45 bytes where 665 were
    removed. AC7 says *exactly* what would be deleted.

**Scope boundary.** This slice ships the retention core and its contracts. No
production CLI, installer, or sync path calls them yet; CLI wiring is `CL-mvet`.

### Implementation record (slice 6, `CL-mvet`)

The three reference adapters, the production wiring, and the legacy neutrality
drawdown. Slices 1 to 5 each ended with a working core and no caller; this slice
is where every one of those boundaries closes.

**The adapters.**

| Adapter | Module | Declared capabilities beyond the required floor |
|---|---|---|
| `git-repo` | `scripts/lib/providers/git_repo.py` | `describe`, `revision_of`, `verify`, `rights_evidence`, `member_manifest` |
| `git-org` | `scripts/lib/providers/git_org.py` | the same, plus `item_rights_evidence` |
| `mcp-content` | `scripts/lib/providers/mcp_content.py` | `describe`, `rights_evidence` only |

Two capabilities are added to the contract table, both because a reference
provider needs a question answered that no existing capability asks:

- **`item_rights_evidence(upstream_id)`** exists because this ADR records the
  organization provider's grant as *per repository* and names a repository in the
  same organization with no observed `LICENSE`. A provider-wide answer would let
  one repository's grant stand in for a sibling that has none. Declaring the
  capability is what makes a consumer ask per item; an adapter that does not
  declare it is stating that its provider is uniform.
- **`member_manifest(upstream_id, revision)`** exists because
  `CompletenessEvidence.from_manifest` requires a member list read *from the
  source*, which is a different claim from the adapter's own word that its
  `FetchedItem` is complete. An adapter that cannot list members is not a lesser
  adapter; its installs record `adapter-declaration`, the weakest evidence in the
  vocabulary, explicitly rather than by default.

**The `mcp-content` credential boundary, stated rather than implied.** This
adapter implements **no credential handling**: no acquisition, no storage, no
token exchange, no transmission. It holds a credential *reference* and its scope,
returns them through `auth_requirements()`, and takes a caller-owned transport.
That separation is what makes `Credential isolation` structural instead of a
promise — a module that never receives a secret cannot write one into a cache
object, a receipt, or a projection. Resolving a reference into a token is
credential handling and requires a human security review before any such code is
written; it is deliberately out of this slice. The visible consequence is that an
operator with no configured transport gets a typed `unavailable` availability
naming the credential reference. That is a refusal, and in particular it is never
a reason to read the distinct public repository this ADR records as *not* this
provider.

**Maturity is classification, not a filter.** Items under an `in-progress` or
`deprecated` collection carry `classification.maturity` with the collection that
produced it named, stay in the inventory, and resolve to `discoverable`.
Promotion is an explicit scope decision (`AdmissionContext.admitted_maturities`)
or a Workspace naming the item. Filtering them out of the inventory would delete
upstream's own statement about its confidence and make the inventory disagree
with the source it claims to describe.

**Unclassified is the recorded absence of a type, not a type.** A bundle member
fitting no existing primitive is recorded as `unclassified`, stays
`discoverable`, and is never `installable`. The two alternatives are both silent
falsehoods: a new catch-all primitive is the `harness` type this ADR refuses, and
filing the member under the nearest existing type records a classification nobody
made. It is deliberately not `blocked` either — a block reason asserts that
something was observed about the content, and nothing was.

**Production wiring.** `scripts/lib/providers/wiring.py` holds the one legitimate
`provider_kind` branch in the platform, and supplies the four obligations the
cores refuse to work without: stated `CompletenessEvidence`, a two-phase
`ProjectionActivation`, a `ReferenceIndex` over **both** receipt scopes, and one
source-scoped `ResolutionEvidence` per provider beside an explicit
`evidence_max_age` and a durable purge ledger. `library marketplace
list|inventory|install|status|gc` is the caller. Foreign receipts are addressed
from their lock scope — `<lock path>.foreign-receipts.json` — so "which receipts
belong to this scope" is answerable from the lock path with no scan and no second
configuration entry.

**Workspace v2 materialization is unblocked.** `assert_materializable` refused a
cross-catalog closure pending three things, and all three now hold: the CLI
resolves every closure with a provider-backed pin verifier that reads what each
declared source currently serves, normalizes the resolved members into inventory
items bound to their exact bytes, and routes every v2 mutation through
`gate_workspace_mutation` and the executable-admission gate. The refusal is a
retained no-op rather than a deletion or a weaker residual check, because a
second version of the same refusal is what gets relaxed later while everyone
assumes the real gate is still there.

**Two residuals, recorded rather than closed.**

1. A verified pin proves the *source* has not moved. It does not prove that this
   repository's catalog document describes that revision, because members are
   still read from the local checkout rather than fetched at the pin. A catalog
   document edited between the pin check and the read can still describe a member
   the pinned revision does not.
2. A v2 closure containing an executable member fails the whole resolution until
   a scope operator admits that member's exact bytes, and this slice ships no CLI
   for recording that decision. Inert closures install now; an executable one is
   refused, which is the correct ADR behavior and an incomplete operator surface.
3. **The v2 mutation gate detects source drift; it does not prevent its effects.**
   The gate digests an immutable snapshot and admits a decision about it, and the
   legacy installers resolve their own source rather than consuming that
   snapshot. The gap is bridged by comparison — the admitted content is
   re-derived and compared before the first write, before every member's own
   installer, and after the last one, and any difference fails the operation with
   exit 3.

   What that buys and what it does not, stated exactly, because two successively
   weaker claims were written here first and adversarial review broke both:

   - A source that differs *before* a member's installer runs stops the run
     before that member is written.
   - A source that changes *after* its member's pre-check is detected by the
     final comparison, and the run fails — **but the installer has already
     published the unadmitted bytes, and nothing rolls them back.** The Workspace
     journal records the operation; it does not undo a member's projection.
     Review demonstrated this end to end: exit 3 was returned and
     `.agents/skills/helper/SKILL.md` still contained content the gate never
     admitted.
   - A source changed and changed back inside a single installer's read is
     invisible to every comparison.

   So the honest claim is: the v2 write path *reports* whether what was installed
   is what was admitted, and refuses to complete when it is not. It does not
   guarantee that only admitted bytes reach disk. Closing that requires the
   installers to consume the gate's frozen content and publish it atomically, or
   a rollback that restores the pre-operation state — a change to the installer
   contract, routed forward rather than attempted here. An operator who sees this
   failure must treat the projection as untrusted and re-run, and
   `tests/test_provider_review_regressions.py` asserts the post-failure
   filesystem state so the residual is proven rather than described.

**Legacy neutrality drawdown.** `scripts/lib/source.py` carried 50 findings, more
than every other legacy module combined. Its URL shapes, clone forms, SSH
fallback, and owner-or-repository resolution moved to
`scripts/lib/providers/git_url.py` — the remedy the check's own report names —
and the module now measures zero and has dropped out of the baseline. The legacy
set falls from 15 modules and 126 findings to 11 and 55; the certified core grows
from 12 modules to 17, adding the normalization layer, the inventory schema, the
Library-owned classification and decomposition rules, and catalog-derived
routing. What remains legacy is the catalog and installer surface, which still
resolves by cloning; that is the path the provider contract exists to replace,
and it is not extended here.

**What the drawdown does not claim**, stated because review found the stronger
reading available and wrong: `source.py` is now free of provider *knowledge*, not
provider *dependence*. It still imports a Git marketplace-type constant, Git URL
kind sets, and Git parsing and cloning functions from `providers/git_url.py`, and
it still branches on that imported constant — so it resolves a repository URL on
one hosting service and returns `unknown` for an equivalent URL on another, with
the neutrality scan reporting nothing. That is the correct outcome for a legacy
path: the knowledge now lives at the sanctioned boundary where a second host
could be added, and the module that consumes it no longer encodes which host it
is. It is not the same thing as `source.py` having become provider-independent,
and reading the zero as that claim would overstate it.

## Migration and Existing Bead Disposition

### Named contract dispositions

| Item | Disposition |
|---|---|
| ADR-0003 (three-layer cache) | **Extended, not superseded.** The Source/Cache/Harness layering and marketplace symmetry stand. The skill-focused Git cache key and the deferred hosted adapter are replaced by the tuple key and the provider contract here. Decision 5's adapter-per-marketplace-type intent is fulfilled by `Source Provider Contract` |
| ADR-0004 (frontmatter dependency resolution) | **Unchanged.** `requires:` remains the hard-dependency mechanism, including for foreign items |
| ADR-0005 (plane vocabulary) | **Unchanged.** Placement Records use its plane vocabulary |
| ADR-0006 (Workflow primitive) | **Retained, unamended.** Supersession attempted and failed on evidence; see `Workflow Executor Evidence and Authority`. A `Status` note pointing at that evidence is added to ADR-0006 |
| ADR-0010 (Workspace desired state) | **Amended in one place only** (amendment finalized 2026-08-09): the two-consumer evidence gate is waived for cross-catalog manifest roots. Nested Workspaces stay deferred with the gate intact. Every other decision, including fail-before-mutation, the prune conditions, and no-overlay, is restated unchanged |
| `docs/PRIMITIVES.md` | **Amended.** No new primitive is added. The Skill entry gains the `skill_class` classification; the Quick Decision Tree gains an explicit Runbook terminator so the question is not re-litigated |
| `docs/policy/name-collision.md` | **Amended.** No `runbook-` prefix is reserved. A rule is added for upstream name preservation and qualified identity under cross-catalog composition |
| `standards/agentic-primitives/agentic-primitives.md` | **Amended.** Runbook is added to the counter-examples table with its rejection rationale |
| `docs/primitives/marketplace.md` | **Amended.** Provider kinds, remote-only enumeration, and the rights fields are described; the convention scan is scoped to local writable sources |
| `docs/primitives/workspace.md` | **Amended.** Schema v2 qualified roots, the approval state (final since 2026-08-09), and the nested-Workspace deferral |
| `docs/primitives/workflow.md` | **Amended.** Records the failed Pi supersession and the retained ADR-0006 authority |
| `docs/lockfile-format.md` | **Amended.** Rights, admission, transformation, cache-digest, and `upstream-vanished` receipt fields |
| Source metadata (`library.yaml` `sources.marketplaces`) | **Amended by slice 1**, not here. Entries gain `provider_kind`, `allowlist`, `auth_ref`, and `rights` fields. No content is installed by a registration |

### CL-yism subtree disposition

On 2026-08-07 Malte replaced the Library-retirement direction with **Library
Platform as the durable discovery, cache, projection, and desired-state layer**.
Open Skills remains the portable source format for ordinary Skills; it is not
replaced, and the Library does not compete with it. The two are orthogonal: Open
Skills says what a Skill file *is*, the Library Platform says where it came from,
whether it may be used, and what is installed.

A note is insufficient to carry that reversal. Every open bead below is rewritten
or closed.

| Bead | Disposition | Action |
|---|---|---|
| `CL-yism` (epic) | **Rewrite.** Migration to Open Skills, Beads/Open Engine, Pi, and Hermes stands; Library retirement is removed from the goal | Body rewritten |
| `CL-yism.1` | **Rewrite.** "Make Open Skills canonical" is retained as the portable **source format** decision; "stage the Library retirement" is removed and replaced by the durable-platform boundary | Body rewritten, title changed |
| `CL-yism.2` | **Keep as-is.** Beads/Open Engine compatibility is independent of Library authority | No change |
| `CL-yism.3` | **Keep as-is.** A global Beads home is independent of Library authority | No change |
| `CL-yism.4` | **Closed; retained as reusable foundation.** The generic project-local Pi asset bridge is not duplicate scope | No change (already closed) |
| `CL-yism.5` | **Rewrite.** Hermes connects to canonical Open Skills, Open Brain, and Beads; the assumption that the Library stops being the resolver is removed | Body rewritten |
| `CL-yism.6` (epic) | **Rewrite.** Staged harness cutover is retained; "Library authority retirement" is removed from the epic goal and title | Body rewritten, title changed |
| `CL-yism.6.1` | **Rewrite.** The shared Pi/Hermes task-loop proof stands on its own; retirement framing removed | Body rewritten |
| `CL-yism.6.2` | **Rewrite.** Harness rollback and forward recovery stand on their own; retirement framing removed | Body rewritten |
| `CL-yism.6.3` | **Rewrite.** Soak evidence stands on its own; the decision it feeds is harness cutover, not Library retirement | Body rewritten |
| `CL-yism.6.4` | **Close as superseded.** Its entire purpose was retiring Library runtime authority, which this ADR reverses. Nothing survives to rewrite | Closed |
| `CL-yism.7` | **Rewrite.** The Pi interactive-engineering cutover stands; Library-retirement assumptions removed | Body rewritten |
| `CL-cy6` | **Keep as-is, with a boundary note.** It may provide a CLI transport for Executive Circle. Transport is not the normalized marketplace inventory or the cache contract, and building `ec` does not make Executive Circle a registered provider | Note appended |

**No implementation slice from this ADR may be dispatched while a governing body
still carries the retirement instruction.** The rewrites landed in the same
delivery as this ADR, before slice dispatch. Applied on 2026-08-08: `CL-yism`,
`CL-yism.1`, `CL-yism.5`, `CL-yism.6`, `CL-yism.6.1`, `CL-yism.6.2`,
`CL-yism.6.3`, and `CL-yism.7` were rewritten (bodies replaced, four retitled) and
each passed `bead-author-check` as `FACTORY_READY`; `CL-yism.6.4` was closed as
superseded after its three now-meaningless blocking edges were removed; `CL-cy6`
received the transport-boundary note. `CL-yism.2`, `CL-yism.3`, and the closed
`CL-yism.4` were deliberately left unchanged.

## Implementation Slices

Slices are independently verifiable capabilities, not phases. Each has its own
acceptance surface and could ship alone.

| Slice | Bead | Capability | Independently verifiable by | Depends on |
|---|---|---|---|---|
| 1 | `CL-coif` | Provider adapter contract and normalized inventory core | Normalized items from a live `git-repo` provider with no local checkout; mechanical no-provider-names check over core; validator tests | `CL-2p73` |
| 2 | `CL-n7ex` | Rights, admission, and executable-admission state machine | Rights states drive blocked/allowed projection decisions; blocked-by-default for `unknown`; admission bound to content digest | `CL-coif` |
| 3 | `CL-y5z4` | Durable foreign-resource cache: tuple key, atomic materialization, TOFU, offline repair | Offline reinstall from a verified cache with the provider unreachable; drift is fail-closed | `CL-coif` |
| 4 | `CL-uliw` | Retention, fail-closed GC, and operator-explicit purge | GC refuses an unreferenced object during simulated outage; purge requires a digest and an acknowledgement | `CL-y5z4` |
| 5 | `CL-dbam` | Workspace schema v2 qualified roots and cross-catalog resolution | v2 manifest resolves across two catalogs; unpinned catalog, URL-in-root, and undeclared-alias cases fail | `CL-coif`, `CL-n7ex` |
| 6 | `CL-mvet` | Reference provider adapters: `git-repo`, `git-org` allowlist, `mcp-content` | Each reference provider enumerates and installs through the generic contract only | `CL-coif`, `CL-n7ex`, `CL-y5z4` |
| 7 | `CL-m6cc` | Cache and lock migration, legacy projection disposition | Legacy receipts re-materialize; unresolvable receipts are retained and prune-blocked; no deletion authority is granted | `CL-y5z4`, `CL-uliw`, `CL-n7ex` |

The dependency edges above are live in the Beads graph, not narrative ordering.
`bd dep tree CL-2p73` shows this ADR's own dependencies, not its dependents, so
verify the slice edges from the slice side:

```bash
bd dep list CL-coif --json   # -> CL-2p73
bd dep list CL-dbam --json   # -> CL-coif, CL-n7ex
bd dep list CL-mvet --json   # -> CL-coif, CL-n7ex, CL-y5z4
bd dep list CL-m6cc --json   # -> CL-y5z4, CL-uliw, CL-n7ex
bd dep cycles                # -> no dependency cycles detected
```

Each slice is independently verifiable rather than a phase fragment: every one has
its own acceptance surface, its own tests, and its own reviewable outcome. That is
weaker than "could ship in any order" and is the honest claim — slices 2 through 7
have real prerequisites, listed above. What it rules out is a phase fragment whose
only acceptance criterion is "the next phase can now start". Slices 3 and 5 in
particular do not depend on each other, and slice 4 exists separately from slice 3
because "cache the bytes" and "decide when bytes may be destroyed" have different
failure modes and different reviewers.

**Slice 1 (`CL-coif`) is pre-approved to execute** without further approval
(Human Decision HD-3, Malte Sussdorff, 2026-08-08). Slices 2 through 7 were gated
on `Approval Finalization` reaching `final`, which it did on 2026-08-09.

## Human Decisions

Recorded because they are decisions, not derivations. They are not to be
re-litigated by a later reader; they are to be *found* by one.

| # | Decision | Maker, date | Status | Rationale |
|---|---|---|---|---|
| HD-1 | The Library Platform is the durable discovery, cache, projection, and desired-state authority. The retirement direction is reversed | Malte Sussdorff, 2026-08-07 | Final | Open Skills is the portable source format; it does not answer provenance, rights, caching, or desired state. Something must, and nothing else does |
| HD-2 | The ADR-0010 consumer-evidence gate is amended for cross-catalog manifest roots | Malte Sussdorff, 2026-08-08 | **Final** — finalized 2026-08-09 on slice-1 evidence, see `Approval Finalization` | Strategic. Observed lock evidence is real but proves scope-boundary composition, not manifest-root need. The amendment is recorded honestly as a waiver rather than dressed up as a satisfied gate |
| HD-3 | Implementation slice 1 is pre-approved to execute without further approval | Malte Sussdorff, 2026-08-08 | Final | Slice 1 is exactly the work that produces the evidence finalizing HD-2, so gating it on HD-2 would deadlock |
| HD-4 | The CL-yism subtree is rewritten or closed in the same delivery as this ADR | Malte Sussdorff, 2026-08-08 | Final | A body that contradicts its own note hands out the superseded instruction silently |

Two outcomes in this ADR are **not** Human Decisions and were derived from
evidence: the Runbook rejection (primitive decision tree plus Invariant 4) and the
retention of ADR-0006 (seven of seven failed executable checks). Both happened to
match the expected outcome. Had the evidence contradicted the expectation, the
evidence would have governed.

## Alternatives Considered

### One integrated decision versus five separate ADRs

**Selected: one integrated decision.** All five concerns meet at the same
authority, resolution, lock, receipt, and materialization boundary. Splitting
would duplicate the six axes across five documents and risk incompatible partial
decisions. The executor question is included because Workflow receipts, runtime
compatibility, migration, and rollback share one state transition with everything
else — and it explicitly does not block the rest, which is why its failure closed
one branch instead of the ADR.

### Runbook as a first-class primitive

**Rejected**, on the decision-tree test above. Its entire enforced behavior would
have been a naming convention, and that convention would have collided with the
upstream names of the two artifacts it was designed for.

### Pi-only Workflow execution

**Rejected on evidence**, seven of seven required checks failing. Recorded as a
failed supersession branch with a re-entry condition, not as a rejected idea.

### A separate resolved environment manifest for cross-catalog roots

**Rejected.** It would reintroduce the parallel desired-state manifest that
ADR-0010 Decision 12 retired, and it would move the reviewable pin into a file
nobody reviews. The lock is already the resolved artifact.

### Overlay or precedence semantics for cross-catalog composition

**Rejected.** Across a trust boundary, an overlay is a redirection mechanism. It
would reintroduce, at the composition layer, exactly the attack the pinned
`catalogs:` block prevents at the manifest layer.

### Live remote reads instead of durable local materialization

**Rejected.** An installed environment that depends on a reachable provider is not
reproducible. Verified content-addressed objects plus pinned receipts, constrained
by rights, are the only shape that survives an outage.

### Organization-level enumeration without an allowlist

**Rejected.** It would make Library inventory a function of an external party's
repository creation.

### Digest-polling freshness for revisionless providers

**Rejected.** A poll can only report drift, and treating drift as a freshness
signal invites automatic re-pinning — the silent substitution this ADR forbids.

### A generic Harness primitive for mixed external bundles

**Rejected by default.** Bundles decompose into existing typed primitives. A new
type needs separate evidence and its own ADR.

## Consequences

### Positive

- Remote-only providers become first-class. `mattpocock/skills` is installable
  without a local checkout and without flattening its nested layout.
- Rights become a recorded, queryable state rather than an implicit assumption.
  The blocked-by-default rule for `unknown` closes the current gap in which
  third-party bytes were materialized with no rights check at all.
- A verified cache survives provider loss. The `upstream-vanished` state makes the
  worst case visible instead of destructive.
- The primitive count does not grow. Runbook is answered without a fourteenth
  type, and the answer is recorded so the question stops recurring.
- The Workflow executor question is settled with a re-runnable check rather than a
  standing opinion. The verdict flips automatically when the world changes.

### Negative

- A `navigator` and a `procedure` Skill are indistinguishable to a harness that
  ignores classification metadata. Accepted.
- The rights model adds four fields and a decision table to every foreign item.
  This is real friction and is the point.
- Re-materialization rather than re-keying means the first operation after
  migration is slower and requires provider availability. Legacy objects remain
  usable meanwhile.
- Cross-catalog manifest roots shipped on a **tentative** amendment with a
  defined off-ramp (revert to deferred). Slice 1's evidence held and the
  amendment was finalized on 2026-08-09; the off-ramp was not needed.
- `executive-circle` content will be blocked from committed project projection by
  default, which will look like a bug to someone who has a working subscription.
  The rights state, not the ability to fetch, is the reason, and the message must
  say so.

### Pre-mortem: the three most likely ways this goes wrong

1. **Provider-specific logic leaks into core resolution.** The generic contract is
   easy to state and hard to hold, and the first awkward provider will tempt a
   branch. Mitigation: slice 1's mechanical no-provider-names check runs in CI,
   not as a review convention.
2. **The tentative amendment is quietly treated as final.** Someone cites the
   Workspace v2 section without reading `Approval Finalization`. Mitigation: the
   status is stated in the ADR `Status` block, in the section itself, and in
   `docs/primitives/workspace.md`. (Moot since 2026-08-09: the amendment is
   final.)
3. **`unknown` rights get treated as permissive under delivery pressure.** The
   blocked default is inconvenient exactly when someone wants content. Mitigation:
   the default is fail-closed in the contract, the opt-in is explicit and
   operator-scoped, and the rights state is displayed before mutation.

## References

- `docs/research/external-marketplace-reference-matrix.md` — reference provider
  inventory, installation mappings, and rights evidence
- `docs/research/pi-workflow-executor-evidence.json` — executed Pi executor
  evidence artifact
- `scripts/checks/pi_workflow_executor_evidence.py` — the re-runnable checks
- `tests/test_pi_workflow_executor_evidence.py` — threshold and artifact tests
- `/Users/malte/code/library/cognovis-pi/docs/research/indydevdan-pi-repos.md` —
  per-repository `disler` licence evidence
- `/Users/malte/code/library/cognovis-pi/docs/native-executive-pack-harness.md` —
  the Pi harness design evaluated by PWE-5
