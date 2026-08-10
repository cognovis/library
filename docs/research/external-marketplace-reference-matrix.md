# External Marketplace Reference Matrix

> Evidence document for [ADR-0011](../adr/heterogeneous-marketplace-workspaces.md)
> (bead `CL-2p73`, AC6). Observations dated **2026-08-08**.
>
> Purpose: prove that three structurally different providers map onto **one**
> adapter capability contract, and that the resolver, cache, and Workspace layers
> need no provider-specific branch. This document is the reviewable mapping; the
> mechanical "no provider names in core" check is owned by implementation slice 1.

## How to read this

Each provider is described three times, in the same order:

1. **Adapter capability mapping** — how it satisfies the contract in ADR-0011
   `Source Provider Contract`, capability by capability.
2. **Normalized inventory mapping** — what an item looks like after
   normalization, in the fields of `Normalized Inventory and Admission State`.
3. **Rights resolution** — the four independent grants, each with its evidence
   source.

If a provider needed a capability that is not in the contract, that would be a
finding against the contract. None does. The two places where a provider is
*weaker* than the contract (`executive-circle` has no `revision_of`, and no
provider publishes machine-readable `rights_evidence()`) are handled by declared
absence behavior, not by special-casing.

## Summary

| Provider | Kind | Enumeration without checkout | Revision | Auth | Redistribution | Exercises restricted path |
|---|---|---|---|---|---|---|
| `mattpocock` | `git-repo` | Yes — recursive tree API | Commit SHA | None | `granted` | No |
| `disler` | `git-org` + allowlist | Yes — per allowlisted repo | Commit SHA per repo | None | `granted` (per repo) | No |
| `executive-circle` | `mcp-content` | Yes — typed MCP call | **None** | Subscriber token | `unknown` | **Yes** |

At least one reference provider exercises the rights-restricted projection path,
so ADR-0011 requires no constructed `unknown` case. `executive-circle` is the
real one.

---

## 1. Matt Pocock — `mattpocock/skills`

**Canonical source identity:** `https://github.com/mattpocock/skills`
**Provider kind:** `git-repo`
**Observed default branch:** `main`
**Observed upstream state:** 151 blobs, last push `2026-08-07T15:50:46Z`

### Why this provider is interesting

Its layout breaks the current scanner. The Library's convention scan expects
`skills/<name>/SKILL.md`; this repository stores skills at
`skills/<category>/<name>/SKILL.md` — one level deeper, with the category
directory carrying real meaning (`engineering`, `productivity`, `in-progress`,
`deprecated`, `misc`).

Three consequences the contract must absorb without a branch:

- **Recursive inventory.** Depth is a provider-declared selector, not a constant.
- **Maturity and audience filtering.** `in-progress` and `deprecated` are upstream
  maturity signals, not names. They map to `collection_membership`, and a
  Workspace or policy may filter on them. They must not be silently included as
  if they were stable.
- **Upstream name preservation.** `implement` and `ask-matt` keep their upstream
  names. Nothing renames them to fit a Library convention, which is also why
  ADR-0011 does not reserve a `runbook-` prefix.

### 1.1 Adapter capability mapping

| Capability | Realization |
|---|---|
| `identity()` | `https://github.com/mattpocock/skills` |
| `capabilities()` | `enumerate`, `describe`, `fetch`, `revision_of`, `verify`, `availability` |
| `enumerate(selector)` | `GET /repos/mattpocock/skills/git/trees/<ref>?recursive=1`, filtered to blobs matching the selector `skills/**/SKILL.md`. No clone |
| `describe(upstream_id)` | Fetch the single `SKILL.md` blob and read its YAML frontmatter (`name`, `description`, `disable-model-invocation`) |
| `fetch(upstream_id, revision)` | Blob content at the pinned commit, plus every sibling file under the skill directory (`agents/openai.yaml`, `*.md`, `scripts/*`) |
| `revision_of(upstream_id)` | Commit SHA of `<ref>`; per-path commit when finer granularity is wanted |
| `verify(bytes, expected)` | Git blob SHA available as supplementary evidence; the Library normalized digest remains authoritative |
| `auth_requirements()` | None for public read. An optional token reference raises the rate limit and is never stored in cache |
| `availability()` | `available` when the tree API responds; `degraded` on rate limit; `unavailable` otherwise |
| `rights_evidence()` | GitHub repository API `license.spdx_id` |

### 1.2 Normalized inventory mapping

Worked example, `implement`:

```yaml
provider_identity: https://github.com/mattpocock/skills
upstream_id: skills/engineering/implement
upstream_name: implement
collection_membership: [skills, engineering]
upstream_revision: <commit-sha-of-main-at-pin>
library_type: skill
library_name: implement
classification:
  skill_class: procedure          # upstream `disable-model-invocation: true`
  maturity: stable                # from the `engineering` category
runtime_compatibility: [claude-code, codex]
admission_state: installable
block_reasons: []
executable_admission: pending           # CL-lt51: a foreign steward's Skill
                                        # instructs a model, so it needs a decision
trust_state: unreviewed
rights:
  fetch_authorization: {state: granted, evidence: upstream-license-mit}
  install_rights:      {state: granted, evidence: upstream-license-mit}
  redistribution_rights: {state: granted, evidence: upstream-license-mit}
  derivative_rights:   {state: granted, evidence: upstream-license-mit}
cache_state: absent
projection_eligibility:
  machine_local: allowed
  project_committed: allowed
provider_availability: {state: available, observed_at: 2026-08-08T00:00:00Z}
```

Second worked example, `ask-matt`, differs in exactly two fields:
`upstream_id: skills/engineering/ask-matt` and
`classification.skill_class: navigator`. Both upstream files carry
`disable-model-invocation: true`; the navigator/procedure split is Library
classification over that flag plus the artifact's role, and it is the concrete
demonstration that no new primitive is needed to carry the distinction.

Items under `skills/in-progress/**` normalize with
`classification.maturity: in-progress`. They remain `discoverable`; promoting one
to `installable` is a Workspace or policy decision, never an inventory default.

### 1.3 Installation mapping

| Stage | Result |
|---|---|
| Cache identity | `(https://github.com/mattpocock/skills, skills/engineering/implement, <commit>, <normalized-digest>, skill, <transformation-version>)` |
| Cache object | Complete skill directory: `SKILL.md`, `agents/openai.yaml`, any sibling references |
| Transformation | Harness bridge shape only; upstream bytes unmodified. Recorded as `transformation_version` |
| Projection | Standard Skill projection. `project_committed` permitted because redistribution is `granted` |

### 1.4 Rights resolution

| Grant | State | Evidence source |
|---|---|---|
| `fetch_authorization` | `granted` | Public repository; `https://raw.githubusercontent.com/mattpocock/skills/main/LICENSE` returned HTTP 200, 2026-08-08 |
| `install_rights` | `granted` | MIT |
| `redistribution_rights` | `granted` | MIT; GitHub repository API reported `license.spdx_id: MIT`, 2026-08-08 |
| `derivative_rights` | `granted` | MIT permits modification, subject to notice retention |

Notice retention is a condition, not a blocker: a first-party derivative must
carry upstream provenance, the pin, and the MIT notice. ADR-0011 already requires
the first two for every derivative.

---

## 2. Nate B. Jones — Executive Circle prompt kits

**Canonical source identity:** `mcp:executive-circle`

This exact string is the canonical provider identity everywhere — `identity()`,
`provider_identity` on every normalized item, qualified identities, cache keys,
receipts, conflict diagnostics, ownership, and prune decisions. The bare word
`executive-circle` is the **display alias** and the `library.yaml` `mcp_servers`
entry name; it is never stored as an identity. Using both forms as identities
would let one provider produce two distinct record sets, which is why the
distinction is stated here rather than left to convention.

**Provider kind:** `mcp-content`
**Transport observed:** HTTP MCP endpoint at `contentmasterpro.limited`, registered
in `~/.codex/config.toml` (`[mcp_servers.executive-circle]`) and in
`~/.claude.json` under a project-scoped `mcpServers` entry. The endpoint path
embeds a **subscriber token**.
**Catalog record:** `library.yaml` `mcp_servers` entry `executive-circle`,
`coding_strategy: cli`, `mobile_strategy: mcp`, `capabilities.auth: token`.

### Explicit non-source

`https://github.com/NateBJones-Projects/OB1` is **not** this provider. It is a
separate public repository and must never be conflated with `executive-circle`,
substituted for it when the MCP endpoint is unreachable, or used to infer the
rights state of prompt-kit content. This is recorded here because the conflation
is easy and the consequence — treating subscription content as public content —
is a rights violation, not a routing mistake.

### Why this provider is interesting

It is the reason `mcp-content` exists as a provider kind, and it exercises three
contract paths no Git provider does:

1. **No local checkout is possible.** There is nothing to clone. `enumerate` must
   work over a typed tool call or the provider is unusable.
2. **No upstream revision.** The provider supplies stable item IDs but no
   immutable revision identity, so it is **revisionless** and governed by
   trust-on-first-use and the pin-only rule.
3. **Fetch authorization is not redistribution permission.** A working
   subscription proves only the first.

### 2.1 Adapter capability mapping

| Capability | Realization |
|---|---|
| `identity()` | `mcp:executive-circle` — the provider identity, **not** the tokenized URL. The URL is transport configuration and changes without changing identity |
| `capabilities()` | `enumerate`, `describe`, `fetch`, `availability`. **Absent:** `revision_of`, `verify`, `rights_evidence` |
| `enumerate(selector)` | Typed MCP call (`search prompt-kits` / `list`) returning provider item IDs and prompt-kit membership |
| `describe(upstream_id)` | `get prompt-kit <id>` metadata |
| `fetch(upstream_id, revision)` | `get prompt-kit <id>` content. `revision` is always `null` |
| `revision_of` | **Absent.** Provider is revisionless; first normalized digest becomes the TOFU pin |
| `verify` | **Absent.** Library normalized digest is the only integrity proof |
| `auth_requirements()` | Returns the credential *reference* `executive-circle.subscriber_token` and its scope. Never the value |
| `availability()` | `available` on a successful typed call; `degraded` on partial or truncated results; `unavailable` on transport failure or `401`/`403` |
| `rights_evidence()` | **Absent.** No published licence or redistribution grant located, so rights resolve to `unknown` |

### 2.2 The MCP transport boundary, concretely

This provider is the load-bearing test of ADR-0011's transport rule.

| Question | Answer |
|---|---|
| What receipt does a fetched prompt kit produce? | A **Prompt** receipt, in the scope that requested it |
| Does it create an `mcp:` dependency? | **No** |
| Does it create a global ownership edge? | **No** |
| Does it register an MCP server in a harness? | **No** |
| If the artifact needs a live MCP server at use time? | That is a **separate global prerequisite assertion** under ADR-0010 Decision 4, declared by the artifact, resolved against the global lock, recorded as non-owning |
| Does the existing `executive-circle` MCP server registration install anything? | **No.** Registration is a capability provider; inventory is a separate axis |

`CL-cy6` may build an `ec` CLI as an alternative transport. That would change
which transport the adapter uses and change nothing else: not the provider
identity, not the normalized items, not the receipts, not the rights. That
invariance is the point of the transport rule.

### 2.3 Normalized inventory mapping

```yaml
provider_identity: mcp:executive-circle
upstream_id: <provider-stable-prompt-kit-item-id>
upstream_name: <upstream title, preserved>
collection_membership: [<prompt-kit-id>]
upstream_revision: null                 # revisionless
library_type: prompt
library_name: <normalized name>
classification: {}
runtime_compatibility: [claude-code, codex, claude-ai, pi]
admission_state: blocked
block_reasons: [license-unknown, redistribution-blocked]
executable_admission: pending           # CL-lt51: foreign prompt content is
                                        # model-instructing, not inert
trust_state: unreviewed
rights:
  fetch_authorization:   {state: granted, evidence: configured-subscriber-token}
  install_rights:        {state: unknown, evidence: no-published-grant}
  redistribution_rights: {state: unknown, evidence: no-published-grant}
  derivative_rights:     {state: unknown, evidence: no-published-grant}
cache_state: absent
projection_eligibility:
  machine_local: opt-in                 # explicit operator opt-in, rights shown first
  project_committed: blocked            # Invariant 13 default for `unknown`
provider_availability: {state: available, observed_at: 2026-08-08T00:00:00Z}
```

Note that `admission_state: blocked` coexists with a working subscription and a
reachable provider. Nothing is broken. The item is discoverable and describable,
and it is not installable because its rights are unresolved. This is the
orthogonality of the four states, in the one case where it actually bites.

### 2.4 Installation mapping and the restricted path

| Stage | Behavior |
|---|---|
| Enumerate / describe | Allowed. Discovery is not installation |
| Fetch | Allowed — `fetch_authorization` is `granted` |
| Cache | Allowed. Content-addressed, TOFU-pinned, machine-local. Cache contains **only** artifact bytes and non-secret provenance; the subscriber token is never written to cache, receipt, or projection |
| Freshness | **Pin-only.** No digest polling. A changed digest on re-fetch is fail-closed drift requiring an operator decision |
| Machine-local gitignored projection | **Explicit opt-in only**, after the rights state is displayed |
| Committed project projection | **Blocked** |
| First-party derivative | **Not created.** `derivative_rights: unknown` forbids creating an adapted artifact at all. Only the unmodified upstream artifact may follow the paths above, with the unresolved rights state retained in provenance |

### 2.5 Rights resolution

| Grant | State | Evidence source |
|---|---|---|
| `fetch_authorization` | `granted` | Working subscriber-token-scoped MCP endpoint configured in `~/.codex/config.toml` and `~/.claude.json`, observed 2026-08-08 |
| `install_rights` | `unknown` | No published licence or terms grant located for prompt-kit content |
| `redistribution_rights` | `unknown` | Same |
| `derivative_rights` | `unknown` | Same |

**Path to resolution.** These states are `unknown`, not `denied`, and the
difference matters: `denied` is a finding, `unknown` is unfinished work. Resolving
them requires reading the subscription terms of service and recording the outcome
with a citation. Until someone does that, the blocked default holds — which is the
correct behavior for content someone paid for and nobody has cleared for
redistribution.

---

## 3. IndyDevDan / disler — allowlisted repositories

**Canonical source identity:** `https://github.com/disler`
**Provider kind:** `git-org` with an explicit repository allowlist
**Existing registration:** `library.yaml` `sources.marketplaces` entry `disler`,
`type: git`, `local_path: null`, `writable: false`
**Evidence document:**
`/Users/malte/code/library/cognovis-pi/docs/research/indydevdan-pi-repos.md`

### Allowlist

| Repository | Pin recorded in the evidence document | Licence | Content |
|---|---|---|---|
| `pi-vs-claude-code` | `0ed11f44932fdef29bd98467700019762298f50d` (pushed 2026-07-10) | MIT | Pi harness assets, comparison material |
| `fusion-harness` | `5852f2ed4f5f064a368d83d2dabad84fe6bfa0b4` (pushed 2026-07-20) | MIT | Pi extension; **already adapted into Cognovis** as `extensions/fusion-harness/` with `NOTICE.md` |
| `planf3` | `f34b7ba5ff8167ef6283791763f4b578bfb3a2c0` (pushed 2026-06-21) | MIT | Planning workflow and skill assets |

The allowlist is **Library-owned configuration**, not a property of the
organization. Organization-level enumeration without one is refused by ADR-0011,
because it would make Library inventory a function of an external party's
repository creation.

`live-bench` is recorded in the evidence document with **no observed LICENSE
file**. It is deliberately not on the allowlist. If it were added, its rights
would resolve to `unknown` and its committed project projection would be blocked
by default — the same path `executive-circle` takes, reached from a different
cause.

### 3.1 Adapter capability mapping

| Capability | Realization |
|---|---|
| `identity()` | `https://github.com/disler` |
| `capabilities()` | `enumerate`, `describe`, `fetch`, `revision_of`, `verify`, `availability`, `rights_evidence` |
| `enumerate(selector)` | Repository listing **intersected with the Library-owned allowlist**, then `git-repo` enumeration inside each allowlisted repository |
| `describe(upstream_id)` | Per-item metadata; item type is inferred from repository layout and manifest files |
| `fetch(upstream_id, revision)` | Blob or subtree content at the pinned commit |
| `revision_of(upstream_id)` | Commit SHA **per repository** — the organization has no single revision |
| `verify(bytes, expected)` | Git object hash as supplementary evidence |
| `auth_requirements()` | None for public read |
| `availability()` | Per repository; one unavailable repository degrades that repository's items only, never the whole provider |
| `rights_evidence()` | Per-repository `LICENSE`, cross-checked against the recorded evidence document |

`git-org` is the only place the contract needs a two-level identity, and it gets
it without a new capability: `enumerate` composes, and `revision_of` is per item,
which already implies per repository.

### 3.2 Mixed-inventory classification

These repositories are the mixed-bundle case, and they are decomposed rather than
typed as a bundle:

| Upstream content | Library type |
|---|---|
| `SKILL.md` directories | `skill` |
| Pi extension bundles | `pi-extension` |
| Pi profile documents | `pi-profile` |
| Workflow JS specs | `workflow` |
| Reference documentation | `standard` or excluded |

No generic `harness` primitive is created. A bundle member that fits no existing
type is `discoverable` and **not** classified, which is a visible gap rather than
a silent miscategorization.

**Executable admission applies here and only here among the three providers.**
Pi extensions, Pi profiles that load code, and Workflow specs are executable
artifacts. Each requires explicit executable admission bound to its content
digest before it can become `installable`, regardless of the MIT grant. A licence
answers whether you *may* run it; admission answers whether you *have decided to*.

### 3.3 Normalized inventory mapping

```yaml
provider_identity: https://github.com/disler
upstream_id: fusion-harness#extensions/fusion-harness
upstream_name: fusion-harness
collection_membership: [fusion-harness]
upstream_revision: 5852f2ed4f5f064a368d83d2dabad84fe6bfa0b4
library_type: pi-extension
library_name: fusion-harness
classification: {}
runtime_compatibility: [pi]
admission_state: blocked
block_reasons: [executable-admission-pending]
executable_admission: pending
trust_state: reviewed
rights:
  fetch_authorization:   {state: granted, evidence: upstream-license-mit}
  install_rights:        {state: granted, evidence: upstream-license-mit}
  redistribution_rights: {state: granted, evidence: upstream-license-mit}
  derivative_rights:     {state: granted, evidence: upstream-license-mit}
cache_state: absent
projection_eligibility:
  machine_local: allowed
  project_committed: allowed
provider_availability: {state: available, observed_at: 2026-08-08T00:00:00Z}
```

This item is `blocked` with full MIT rights, which is the second orthogonality
case: rights and executable admission are independent, and both must clear.

### 3.4 Derivative provenance — a live case

`fusion-harness` is **already adapted** into Cognovis as
`extensions/fusion-harness/` with a `NOTICE.md`. Under ADR-0011 this is a
first-party derivative, and it is compliant:

- `derivative_rights: granted` (MIT) — the adaptation was a licensed act;
- `redistribution_rights: granted` (MIT) — committing it is permitted;
- upstream provenance and pin are recorded
  (`5852f2ed4f5f064a368d83d2dabad84fe6bfa0b4`);
- `NOTICE.md` carries the notice MIT requires.

What ADR-0011 adds is that this state becomes **recorded and checkable** rather
than a convention someone followed correctly. The same adaptation performed
against `live-bench` — no observed LICENSE, `derivative_rights: unknown` — would
be refused before the adapted artifact was created.

### 3.5 Rights resolution

| Repository | fetch | install | redistribution | derivative | Evidence source |
|---|---|---|---|---|---|
| `pi-vs-claude-code` | `granted` | `granted` | `granted` | `granted` | MIT `LICENSE`, recorded in `indydevdan-pi-repos.md` with rev pin |
| `fusion-harness` | `granted` | `granted` | `granted` | `granted` | MIT `LICENSE`, recorded with rev pin; `NOTICE.md` in the Cognovis derivative |
| `planf3` | `granted` | `granted` | `granted` | `granted` | MIT `LICENSE`, recorded with rev pin |
| `live-bench` (**not allowlisted**) | `unknown` | `unknown` | `unknown` | `unknown` | "no LICENSE file observed" in `indydevdan-pi-repos.md` |

Rights are resolved **per repository**. There is no organizational grant, and the
adapter must never infer one from a sibling repository.

---

## 4. What this matrix demonstrates about the contract

| Claim | Demonstrated by |
|---|---|
| Remote-only enumeration works without a local checkout | All three. `mattpocock` uses a tree API, `disler` a repository listing plus tree APIs, `executive-circle` a typed MCP call. None clones |
| Consumers need no knowledge of provider layout | The nested `skills/<category>/<name>/` layout, the two-level org/repo layout, and the flat prompt-kit ID space all produce the same normalized item shape |
| Revisionless providers are expressible | `executive-circle` declares `revision_of` absent; TOFU and pin-only follow from the declared absence, not from a provider check in core |
| MCP transport is not the MCP primitive | Executive Circle produces Prompt receipts, no `mcp:` edge, no harness registration |
| Rights are independent of fetch capability | `executive-circle`: fetch `granted`, redistribution `unknown` |
| Admission is independent of rights | `disler` Pi extensions: MIT `granted`, admission `pending` |
| Cached is independent of projectable | Executive Circle content may be `verified` in cache while its committed projection stays `blocked` |
| Allowlists are Library-owned | `disler` allowlists three of the recorded repositories and excludes `live-bench` on evidence |
| No provider-specific branch is required in core | Every difference above is expressed as a declared capability, a declared absence, or Library-owned configuration. **The mechanical check that no provider name appears in resolver, cache, or Workspace modules is owned by implementation slice 1** |

## 5. Open items for the implementation slices

| Item | Slice | Note |
|---|---|---|
| `library.yaml` `sources.marketplaces` gains `provider_kind`, `allowlist`, `auth_ref`, `rights` | 1 | Registering `mattpocock` and `executive-circle` installs nothing |
| Resolve Executive Circle terms of service and record the citation | 2 | Until then `unknown` holds and the blocked default applies |
| Mechanical no-provider-names check in CI | 1 | Guards the central claim of this document |
| Maturity filtering policy for `skills/in-progress/**` | 5 | Workspace or policy decision, never an inventory default |
| Adopt or leave the unreceipted `~/.claude/skills/` mattpocock projections | 7 | See ADR-0011 `Legacy Projection Disposition` |
