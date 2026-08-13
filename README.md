# The Library Platform

The Library is a private-first platform for cataloging and distributing agentic
capabilities across repositories, machines, teams, and coding harnesses.

This repository owns the platform: the deterministic resolver and installers,
schemas, launchers, primitive authoring tools, tests, and architecture documents.
It also acts as the aggregate catalog index. Reusable Skills, Agents, Standards,
and other catalog content normally live in separate marketplace repositories.

## What it solves

Agentic capabilities tend to become duplicated, globally over-installed, and tied
to one harness. The Library separates four concerns:

1. **Catalog** — which reviewed primitives and Workspace definitions are available.
2. **Selection** — which direct primitives and Workspaces a project or the global
   lobby intentionally requests.
3. **Materialization** — which files and harness bridges the Library installs.
4. **Loading** — when a Skill, Standard, Agent, Hook, or other primitive actually
   enters a model or runtime context.

The catalog stores published Git source pointers rather than copied catalog
content. Project-local installs are vendored into canonical `.agents/` paths and
recorded in `.library.lock`; harness-specific bridges are generated separately.

## Current platform and target architecture

The current deterministic engine supports additive install, remove, sync, search,
status, installed-state inspection, and audit operations for the implemented
primitive types. The `/library` Skill is the conversational interface over that
engine; it is not the runtime itself.

[ADR-0010](docs/adr/workspace-desired-state-reconciliation.md) defines the accepted
next state: a **Workspace** is a metadata-only desired-state root that selects a
reviewed closure of ordinary Library primitives. A scope can register zero or more
Workspaces, and Workspaces can compose other Workspaces in the same scope. Strict
functional coupling remains in primitive `requires:` metadata.

```text
direct primitive roots + Workspace roots
                    |
                    | complete dependency resolution
                    v
            materialized receipts
                    |
                    | explicit, provenance-bound prune
                    v
       verified + clean + ownerless targets only
```

Workspace support and lockfile schema v2 are available through the `library`
CLI. Ordinary lifecycle operations remain additive and non-pruning; physical
deletion requires the explicit, provenance-bound Workspace prune flow.

The current Workspace architecture and repository mapping are defined by
ADR-0010 and ADR-0011.

## Repository roles

| Repository | Responsibility |
|------------|----------------|
| `library/meta` (this repository) | Platform engine, schemas, launchers, forges, aggregate catalog index, and architecture |
| `library/cognovis-core` | Shared Cognovis marketplace content |
| `library/sussdorff-core` | Private personal and operations marketplace content |
| `library/cognovis-pi` | Pi extensions, profiles, and project-native bridge modules |

A consumer repository registers only the primitives and Workspaces it needs.
Library-generated project installs and lock artifacts stay local through the
CLI-managed `.gitignore` block. Marketplace repositories keep authored source
primitives at top level and ignore their generated install targets.
For this lifecycle, the Git top-level, project root, `.library.lock` root, and
`.gitignore` root are one directory. An explicit `--project` must name that Git
top-level exactly; linked worktrees are valid independent top-levels.

One repository may use several orthogonal Workspaces. For example, the accepted
portfolio maps `fhir-management` to both `fhir-ig-authoring` and `python-cli`, and
maps `library/meta` to both `library-authoring` and `python-cli`. A Workspace is
therefore neither a repository template nor a filesystem directory.

## Primitive model

Use the [primitive decision tree](docs/PRIMITIVES.md) before adding a new concept.
The important composition distinction is:

- `requires:` means one primitive cannot function correctly without another.
- Workspace roots select independently meaningful capabilities that should share
  a desired-state lifecycle.

The previously documented Library `Package` concept is retired. External npm,
PyPI, Pi, and harness packages remain valid distribution formats, but Package is
not a Library primitive or requested-root type.

## Installation

From a platform checkout:

```bash
bash install.sh
```

The installer links only the irreducible Library conversational entrypoint into
detected harness directories, installs the deterministic CLI as
`~/.local/bin/library`, and records exact bootstrap receipts. Optional forge
Skills belong in a project Workspace. The installer is idempotent. Ensure
`~/.local/bin` is on `PATH`, then verify the command from any directory:

```bash
library --help
```

`library` is the deterministic shell interface and belongs to the irreducible global
bootstrap; it is not copied into project Workspaces. `/library` remains the
dialog-oriented interface inside supported coding harnesses for operations that
benefit from advice or user decisions.

## Current command surface

Primitive commands use singular primitive names:

```bash
library workspace status --all --scope project
library workspace sync --all --scope project
library skill list
library skill use python-dev --dry-run --json
library standard use english-only --scope global
library installed --diff-catalog
library status --offline --json
library audit
library sync --dry-run
```

Run `library --help` for the authoritative primitive and verb inventory. Guided
catalog-authoring and source-publication flows remain in the `/library` Skill
because they require user decisions; they are not deterministic CLI verbs.

## Desired-state migration

Workspace reconciliation becomes the sole Library mechanism for reusable project
or global baselines. Existing parallel mechanisms are transitional:

- the ADR-0002 hand-maintained capability list becomes a deliberately small
  global `engineering-lobby` Workspace; only the Library engine and its chat
  entrypoint remain in the irreducible pre-Workspace bootstrap;
- legacy consumer manifests and updater scripts have retired in favor of
  direct or Workspace roots; and
- `project_tooling` accepts no new capability-distribution responsibilities.

Legacy targets remain protected external ownership until their replacement has
been verified. Workspaces do not absorb arbitrary file-copy rules, JSON patches,
secrets, customer facts, routing profiles, or repository-specific policy.

## Launchers

Canonical harness launchers live in `bin/`:

| Launcher | Harness |
|----------|---------|
| `bin/cld` | Claude Code |
| `bin/cdx` | Codex CLI |

Install them with:

```bash
bash install.sh
```

Launcher architecture and Beads routing are documented in
[Architecture](docs/ARCHITECTURE.md).

## Documentation map

- [Architecture](docs/ARCHITECTURE.md) — platform layers, repository boundaries,
  install paths, and operational flow.
- [Primitive glossary](docs/PRIMITIVES.md) — primitive contracts, portability, and
  the selection decision tree.
- [Workspace contract](docs/primitives/workspace.md) — Workspace semantics and
  composition rules.
- [Workspace reconciliation ADR](docs/adr/workspace-desired-state-reconciliation.md)
  — accepted ownership, lockfile, prune, and transition decisions.
- [Lockfile format](docs/lockfile-format.md) — current v1 format and planned v2
  transition.
- [Harness baseline](docs/harness-baseline.md) — what collaboration repositories
  commit locally.

## Design principles

- **Private-first** — catalogs may point to private reviewed sources.
- **Pull-based** — consumers select only what they need.
- **Harness-aware** — canonical content is shared where possible; adapters own real
  harness differences.
- **Provenance-bound** — deletion authority comes only from exact Library receipts.
- **Composable without overlays** — Workspace composition is set union and dependency
  resolution, never order or last-writer-wins behavior.
- **Repository-safe** — project data and policy remain project-owned unless they are
  modeled as a real reusable Library primitive.
