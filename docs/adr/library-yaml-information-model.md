---
title: "Normalize library.yaml section ownership"
status: accepted
date: 2026-05-14
---

# ADR: Normalize library.yaml section ownership

## Context

`library.yaml` had accumulated three different kinds of information at the
root level:

- installer defaults: `default_dirs`
- catalog vocabulary: `tag_vocabulary`
- primitive catalog entries: `library.skills`, `library.agents`,
  `library.prompts`, `library.scripts`, `library.standards`
- later primitive catalog entries: `guardrails`, `mcp_servers`,
  `model_standards`, `agent_bases`
- source registries: `catalog`, `marketplaces`
- fleet policy: `project_tooling`

The asymmetry made it hard to answer a basic ownership question: "Is this root
key a primitive catalog, a source provider, or fleet policy?" It also forced
loader code and cookbook instructions to remember which primitives were nested
and which were root-level exceptions.

## Section Ownership Audit

| Section | Previous Location | Canonical Location | Owner | Main Consumers |
|---|---|---|---|---|
| `default_dirs` | root | root | installer path policy | `scripts/lib/paths.py`, installers |
| `tag_vocabulary` | root | root | catalog metadata | search and taxonomy tests |
| `skills` | `library.skills` | `library.skills` | primitive catalog | `scripts/lib/catalog.py`, installers, search, resolver |
| `agents` | `library.agents` | `library.agents` | primitive catalog | `scripts/lib/catalog.py`, agent installer, resolver |
| `prompts` | `library.prompts` | `library.prompts` | primitive catalog | `scripts/lib/catalog.py`, simple-file installer |
| `scripts` | `library.scripts` | `library.scripts` | primitive catalog | `scripts/lib/catalog.py`, simple-file installer, Gas City validator |
| `standards` | `library.standards` | `library.standards` | primitive catalog | `scripts/lib/catalog.py`, standard installer, dependency resolver |
| `guardrails` | root | `library.guardrails` | primitive catalog | guardrail installer, list/search, Gas City validator |
| `mcp_servers` | root | `library.mcp_servers` | primitive catalog | MCP installer, list/search, resolver |
| `model_standards` | root | `library.model_standards` | primitive catalog | simple-file installer, agent composer inputs |
| `agent_bases` | n/a | `library.agent_bases` | primitive catalog | simple-file installer, agent composer inputs |
| `catalog` | root | `sources.catalogs` | source registry | source provenance, docs, future source management |
| `marketplaces` | root | `sources.marketplaces` | source registry | marketplace resolution, lockfile migration |
| `project_tooling` | root | root | fleet policy | `scripts/sync_project_tooling.py` |

## Decision

The canonical information model is:

```yaml
default_dirs:
tag_vocabulary:

sources:
  catalogs:
  marketplaces:

library:
  skills:
  agents:
  prompts:
  scripts:
  standards:
  guardrails:
  mcp_servers:
  model_standards:
  agent_bases:

project_tooling:
```

All primitive catalog entries live under `library.*`. All source-provider
registries live under `sources.*`. Root-level keys are reserved for document-wide
policy or metadata that is not itself a primitive catalog.

## Compatibility

The checked-in `library.yaml` has been migrated to the canonical shape. Runtime
loaders keep read compatibility for older catalogs:

- `guardrails` falls back to root `guardrails`
- `mcp_servers` falls back to root `mcp_servers`
- `model_standards` falls back to root `model_standards`
- `agent_bases` has no root-level compatibility alias
- `sources.catalogs` falls back to root `catalog`
- `sources.marketplaces` falls back to root `marketplaces`

Canonical keys win when both canonical and legacy keys exist. This avoids
silently merging duplicate entries from two ownership models.

The JSON Schema accepts the legacy root aliases listed above during the
compatibility period. `agent_bases` is intentionally not aliased; the
`golden_prompts` catalog key was removed during the agent-base rename.
New catalog edits should use only the canonical locations.

## Consequences

- Primitive lookup becomes uniform: `scripts/lib/primitives.py` maps every
  primitive to `library/<section>`.
- Source registry lookup becomes explicit through `sources.catalogs` and
  `sources.marketplaces`.
- `project_tooling` remains root-level because it is fleet policy, not a
  primitive catalog.
- Future schema work should extend `library.*` for primitive types and
  `sources.*` for provider registries instead of adding unrelated root keys.
