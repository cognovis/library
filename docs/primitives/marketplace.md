# Marketplace

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).

**Definition.** A source that publishes a discoverable collection of primitives.
The library catalog can reference a marketplace so users can browse and pull from
it. It is not necessarily a GitHub org or repository — see *Provider kinds*.

**Key constitutive feature.** Discovery surface: a marketplace is defined by its role
as a catalog entry point — it publishes primitives for others to find and install, but
does not itself contain installed primitives.

**Registration installs nothing.** Marketplace registration answers *where content
may be found*. Normalized inventory answers *what is available*. Workspace roots
and their resolved closure answer *what is installed*. Discovery never implies
installation, trust, license permission, redistribution permission, compatibility,
or availability of credentials.

**Provider kinds** ([ADR-0011](../adr/heterogeneous-marketplace-workspaces.md),
`CL-2p73`). A marketplace declares a provider kind, and adapters implement one
capability contract so that resolver, cache, and Workspace layers contain no
provider-specific branch:

| Kind | Enumeration | Revision | Auth |
|---|---|---|---|
| `git-repo` | Recursive tree listing at a ref, no clone required | Commit SHA | Optional |
| `git-org` | Repository listing filtered by an explicit **Library-owned allowlist**, then per-repo `git-repo` behavior | Commit SHA per repo | Optional |
| `mcp-content` | Typed MCP tool call returning item IDs and collection membership | Often none — **revisionless** | Usually required |
| `hosted-index` | HTTP index document | Index-declared | Optional |

Organization-level enumeration **without** an allowlist is refused: it would make
Library inventory a function of an external party's repository creation.

**MCP as transport is not the MCP primitive.** A `mcp-content` provider fetching a
prompt kit produces a **Prompt** receipt for that item's own type and scope. It
never creates an `mcp:` dependency, a global ownership edge, or a harness MCP
registration. A genuinely required MCP server remains a separate global
prerequisite assertion. The transport that delivered an artifact contributes
nothing to that artifact's type, scope, dependencies, or ownership.

**Foreign content is admission-required, and that now includes Skills and
Prompts** ([ADR-0011](../adr/heterogeneous-marketplace-workspaces.md)
`Model-instructing foreign content`, `CL-lt51`, Human Decision HD-5 of
2026-08-10). A Skill, Agent, Prompt, or Standard from a non-first-party steward
runs no process and is still not inert: an agent harness loads it into a model's
context so the model will follow it. Installing one therefore needs a
digest-bound decision recorded with `library admission grant`, exactly as a
Workflow does, and the install-time refusal names the exact command. First-party
catalog content is unaffected.

**Updating foreign content is a decision, not a refresh** (`CL-lt51`):

| Command | Effect |
|---|---|
| `library marketplace update <name>` | Fetches the current upstream state into the update quarantine under the cache root, computes the change set against the pinned **and admitted** state, runs the deterministic risk scanner and one agent-shell reviewer over it, and writes a decision packet. Raises no pin, records no decision, and writes no projected byte |
| `library marketplace update-show <packet-id>` | Prints the packet: per-item size, scanner markers, reviewer verdict, recommendation, and the exact approve and decline commands. `--content` prints the whole post-update content |
| `library marketplace update-list` | Lists packets and any decision recorded about them |
| `library marketplace update-approve <packet-id>` | The human transition. Records the admission decision with the packet, scan, and verdict digests as evidence, raises the pin, and projects through the atomic publication path. `--item` adopts named items only |
| `library marketplace update-reject <packet-id>` | Writes one decision row. Pins, ledger admissions, and projected bytes stay byte-identical |

No verdict value adopts anything, a clean scan never skips the review or the
human gate, and a reviewer that could not be reached is recorded as unavailable
and forces a `reject` recommendation. The scanner is risk *reduction* rather than
detection: an injection can be written in plain prose with no shell, no URL, and
no unusual byte.

**Agents prepare, humans decide.** `.dcg/packs/library-pin-raise-guard.yaml`
blocks `update-approve`, any adoption flag, and `library admission grant` in an
agent shell, and leaves the preparation and read-only verbs — and
`library admission deny`, which fails closed — available. The packet renders the
exact approval command for the agent to hand over.

**Rights metadata.** A marketplace entry records four independent grants —
`fetch_authorization`, `install_rights`, `redistribution_rights`,
`derivative_rights` — each `granted`, `denied`, or `unknown` with a named evidence
source. `unknown` is conservative, not permissive: it blocks committed project
projection by default and permits a machine-local gitignored projection only on
explicit operator opt-in after the rights state is displayed. Rights are resolved
**per repository** for a `git-org` provider; there is no organizational grant.

**Registration fields** (`CL-coif`). A `sources.marketplaces` entry carries four
schema-validated provider fields beyond its legacy `name`, `source`, and `type`:

| Field | Meaning |
|---|---|
| `provider_kind` | One of the four kinds above. An unknown kind is rejected by `docs/schema/library.schema.json` |
| `allowlist` | Library-owned list of upstream units a provider may contribute. **Required and non-empty for `git-org`** |
| `auth_ref` | The *name* of a credential reference and nothing else. Credential values never enter the catalog, a cache object, or a receipt |
| `rights` | The four independent grants plus a named `evidence_source` |

The API counterpart is `lib.providers.registration.register_provider`, which
enforces the same rules before it mutates anything and reports explicitly that it
produced no cache object, no receipt, and no projection.

Provider knowledge stays inside adapters. `scripts/checks/provider_neutrality.py`
fails CI when a provider name, provider-kind conditional, legacy
distribution-type branch, upstream URL, or provider host literal appears in
`scripts/lib/resolver.py`, `scripts/lib/cache.py`, or `scripts/lib/workspace.py`
— in identifiers and f-strings as well as plain literals and comments. The
pre-ADR-0011 resolution path (`scripts/lib/source.py` and its neighbours) is
held to a committed baseline compared **per finding identity**, so its provider
knowledge may shrink as slice 6 (`CL-mvet`) routes it through adapters and may
not grow, and removing one leak never buys room for another. Adapters under
`scripts/lib/providers/` are excluded from that ledger because provider
knowledge belongs there. The check reports every one of these facts, so a clean
core is never read as a clean repository.

**Trigger semantics.** Marketplaces are not invoked. They are registered via
`library add-marketplace <github-url>`. Users browse or search them and then pull
specific items into their repos.

**Promotion routing metadata.** Registered source providers in `library.yaml`
can declare routing fields used by `lib catalog match`:

- `local_path`: local checkout path, or `null` for remote-only sources.
- `writable`: whether tools may create or update primitives in that source.
- `content_types`: primitive families the source accepts, such as `skills`,
  `agents`, `standards`, or `hooks`.
- `scope.topics`: positive topic tags used for ranking promotion targets.
- `scope.excludes`: optional anti-tags that disqualify a source for a request.

Promotion tools should query the catalog instead of hard-coding repository
knowledge. Example:

```bash
lib catalog match --primitive-type=standard --topics=python,uv --writable-only --json
```

The command returns ranked candidates plus the selected top candidate or tie
set. Writable first-party catalogs such as Cognovis Core, Sussdorff Core, and
Open-Brain can therefore become promotion targets without client-specific
repository routing tables.

**Inventory refresh.** This convention scan applies to **local writable sources
only**. It reads `local_path` and regenerates catalog entries from a fixed shallow
layout. Remote-only providers do not use it: they enumerate through their adapter's
`enumerate()` capability, which supports recursive and provider-native layouts.
`mattpocock/skills` is the worked counter-example — it stores skills at
`skills/<category>/<name>/SKILL.md`, one level deeper than this scan expects.

Local writable sources can be scanned by convention with:

```bash
lib catalog sync --source=cognovis-library-core --primitive-type=standard --write --json
```

The sync path reads `local_path` and regenerates catalog entries from standard
repository locations such as `skills/**/SKILL.md`, `agents/**/*.md`, and
`standards/**/*.md`, avoiding hand-edited entry blocks for refreshed inventory.

**Cost.** No runtime cost. Marketplaces are a distribution mechanism only.

**When to choose it.** Register a marketplace when:
- An external GitHub org or repo publishes reusable primitives you want to make
  discoverable to the team.
- You want to centralize discovery without mirroring content.

**Counter-examples.**
- Do NOT mirror third-party content into your own content repos — reference via
  marketplace instead.
- A marketplace is not a primitive you configure in a project — it is a catalog-level
  registration.

**Worked examples.**

| Marketplace | Why it is a marketplace |
|-------------|------------------------|
| `cognovis/samurai-skills` | A GitHub repo that publishes multiple skills for others to pull. Registered in the library catalog; content stays at source. |
| `disler` (GitHub org) | Many public skill repos. Referenced in the library catalog; we do not mirror his content. |
| `anthropics/claude-plugins-official` | Anthropic's curated plugin directory. Third-party; referenced, not mirrored. |

---
