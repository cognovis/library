---
adr: "0005"
title: "Library catalog plane vocabulary and Gas City PackV2 projection boundaries"
status: accepted
date: 2026-05-14
bead: CL-8q4
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0003", "0004"]
---

# ADR-0005: Library catalog plane vocabulary and Gas City PackV2 projection boundaries

## Status

Accepted.

## Context

The Library platform now needs to describe the same primitive in several
contexts:

- source-provider marketplaces such as `cognovis-core` and `sussdorff-core`;
- repo-local primitives installed into a project as vendored or local overlays;
- Library catalog metadata in `library.yaml`;
- runtime projections into Gas City PackV2;
- product-plane runtime agents and packs owned by product repositories such as
  Mira or Polaris.

Without fixed vocabulary, the same words drift. "Marketplace" can mean a source
of primitives, a Claude plugin bundle, or a product packaging mechanism. "Pack"
can mean a Library install bundle or a runtime target. "Agent" can mean a
Library primitive or a product feature.

This ADR fixes the vocabulary for the Library groundwork before schema and
primitive refactors continue.

## Decision

### Decision 1: Library/meta is the dev-plane installer, catalog, and compiler engine

`library/meta` is the platform that indexes primitive sources, validates
catalog metadata, resolves dependencies, materializes installs, and compiles or
exports primitives into target surfaces.

It is not itself a primitive catalog. Source primitives live in marketplaces or
repo-local overlays; runtime product features live in product repositories.

### Decision 2: Marketplaces are stewarded primitive sources

A Library marketplace is a source-provider entry such as `cognovis-core` or
`sussdorff-core`. It answers "where does this primitive come from?" and points
to source files owned by that marketplace.

This is the ADR-0003 meaning of marketplace, not the removed Claude Code plugin
marketplace mechanism from ADR-0002.

Examples:

| Marketplace | Role |
|-------------|------|
| `cognovis-core` | Stewarded Cognovis developer primitives |
| `sussdorff-core` | Private personal primitives |
| `anthropic-skills` | Third-party skill source |

### Decision 3: Repo-local primitives are vendored or local overlays

A project repository may contain `.agents/`, `.claude/`, `skills/`, `agents/`,
or other primitive source files for local use. Those entries are repo-local
primitives.

Repo-local primitives can shadow or extend marketplace-provided primitives per
the name-collision policy. They are still dev-plane Library primitives when they
are authored for developer harnesses, not product-plane features.

### Decision 4: Product-plane runtime agents are not Library catalog primitives

Product-plane runtime agents are product features. They belong in product
repositories and product deployment systems, not in the Library catalog as
installable developer primitives.

Examples:

| Entry | Classification |
|-------|----------------|
| A Codex/Claude helper agent installed for developers | Library primitive |
| A Mira or Polaris runtime agent that acts for end users inside the product | Product-plane feature |
| A product-specific orchestrator compiled from Library primitives into runtime code | Product-plane projection |

The Library catalog may reference a paired product-plane artifact through
metadata such as `metadata.library.product_counterpart`, but that reference does
not make the product artifact a Library primitive.

### Decision 5: Gas City PackV2 is a runtime projection target

Gas City PackV2 is a target shape that Library primitives can project into. It
is not a Library install bundle and does not replace marketplace, plugin, skill,
agent, hook, standard, or script primitives.

Library metadata describes whether and how a primitive can be exported into Gas
City. The exported PackV2 artifact is runtime output.

Examples:

| Library source | Gas City projection |
|----------------|---------------------|
| Python script primitive | PackV2 command or doctor entrypoint |
| Skill with deterministic helper script | PackV2 docs plus script asset |
| Developer-only guidance skill | No projection unless explicitly marked exportable |

### Decision 6: Catalog metadata is separate from primitive source files

Primitive source files contain the content the harness or runtime consumes:
`SKILL.md`, agent definitions, standards, scripts, hooks, and prompts.

Catalog metadata describes indexing, placement, dependency resolution, install
targets, and projection targets. It belongs in `library.yaml` or derived
lockfiles. Library-owned metadata lives under `metadata.library.*` so external
metadata can coexist.

Catalog metadata may mirror source frontmatter for indexing, but the distinction
remains:

| Source file concern | Catalog metadata concern |
|---------------------|--------------------------|
| Skill instructions and trigger description | Marketplace, path, harness, tags |
| Python script code and output contract | Exportability, plane, projection target |
| Agent prompt and tool guidance | Product counterpart reference |

### Decision 7: Script is a first-class Python-only primitive

`script` is a first-class Library primitive for deterministic logic. Reusable
Library scripts are Python-only and are cataloged under `library.scripts`.

Scripts can be called by skills, agents, hooks, standards, tests, CI, and Gas
City exports. A script is not a model-selected context primitive; it runs only
when another primitive or runtime surface invokes it explicitly.

## Rationale

The Library needs one vocabulary across catalog validation, installation,
documentation, and Gas City export work. The most important boundary is the
dev-plane versus product-plane split: Library should be able to compile or
reference product-plane counterparts without becoming their source of truth.

Treating Gas City PackV2 as a projection target keeps the Library primitive
model stable. It avoids introducing a second bundle concept while still allowing
runtime packaging to evolve.

Separating catalog metadata from primitive source files keeps source artifacts
portable across harnesses and prevents runtime-specific projection metadata from
polluting core skill, agent, standard, hook, prompt, or script formats.

## Alternatives Considered

### Alternative A: Treat Gas City packs as Library install bundles

Rejected. Library already has plugin and dependency-graph semantics for
installing groups of developer primitives. Reusing "pack" for install bundles
would conflict with Gas City's runtime packaging model and with ADR-0004's
decision not to add a separate bundle primitive.

### Alternative B: Catalog product-plane runtime agents as Library agents

Rejected. Product runtime agents have product-specific lifecycles, permissions,
deployment targets, tests, and safety requirements. Library may track a paired
counterpart, but the product artifact remains outside the Library primitive
catalog.

### Alternative C: Put all projection metadata in primitive source frontmatter

Rejected. Some projection fields are catalog concerns, can vary per installation
or target, and may be irrelevant to the source primitive's native harness. Keeping
projection metadata in `metadata.library.*` lets the source file remain portable.

## Consequences

- Schema work can add `metadata.library.plane` with Library catalog entries
  limited to the dev plane.
- Library catalog validation rejects `metadata.library.plane: product`;
  product-plane artifacts must be referenced through
  `metadata.library.product_counterpart`.
- Schema work can add `metadata.library.product_counterpart` as a reference to
  paired product-plane work without cataloging the product artifact itself.
- Gas City metadata can evolve toward projection entries without redefining
  PackV2 as a Library install bundle.
- Primitive authors can continue using `docs/PRIMITIVES.md` for type decisions
  and use this ADR for placement and plane boundaries.
