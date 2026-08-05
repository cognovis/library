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

Workspace support and lockfile schema v2 are tracked by bead `CL-r7n6`; the
Workspace commands documented in ADR-0010 are therefore a target interface until
that bead lands. The current CLI remains additive and non-pruning.

The evidence-backed initial Workspace cuts and repository mapping live in the
[Workspace Portfolio Audit](docs/research/workspace-portfolio-audit.md).

## Repository roles

| Repository | Responsibility |
|------------|----------------|
| `library/meta` (this repository) | Platform engine, schemas, launchers, forges, aggregate catalog index, and architecture |
| `library/cognovis-core` | Shared Cognovis marketplace content |
| `library/sussdorff-core` | Private personal and operations marketplace content |
| `library/cognovis-pi` | Pi extensions, profiles, and project-native bridge modules |

A consumer repository registers only the primitives and Workspaces it needs. It
commits project-local `.agents/` content and `.library.lock`. Marketplace
repositories keep authored source primitives at top level and normally ignore
their `.agents/` install targets.

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
detected harness directories and records exact bootstrap receipts. Optional
forge Skills belong in a project Workspace. The installer is idempotent. The deterministic engine can also be run
directly from this repository:

```bash
uv run --script scripts/library.py --help
```

The repository currently has no standalone `bin/library` executable. Until one is
published, use `/library` inside a supported harness or invoke the engine through
`uv run --script`.

## Current command surface

Primitive commands use singular primitive names:

```bash
uv run --script scripts/library.py skill list
uv run --script scripts/library.py skill use python-dev --dry-run --json
uv run --script scripts/library.py skill use python-dev
uv run --script scripts/library.py standard use english-only --scope global
uv run --script scripts/library.py installed --diff-catalog
uv run --script scripts/library.py status --offline --json
uv run --script scripts/library.py audit --drift-only --json
uv run --script scripts/library.py sync --dry-run
```

Run `uv run --script scripts/library.py --help` for the authoritative primitive and
verb inventory. Guided catalog-authoring and source-publication flows remain in the
`/library` Skill because they require user decisions; they are not deterministic CLI
verbs.

## Desired-state migration

Workspace reconciliation becomes the sole Library mechanism for reusable project
or global baselines. Existing parallel mechanisms are transitional:

- the ADR-0002 hand-maintained capability list becomes a deliberately small
  global `engineering-lobby` Workspace; only the Library engine and its chat
  entrypoint remain in the irreducible pre-Workspace bootstrap;
- `consumer-projects.yml` and `scripts/update-consumers.py` retire after each
  consumer owns equivalent direct or Workspace roots; and
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
| `bin/agr` | Antigravity |
| `bin/cra` | Cursor Agent |

Install them with:

```bash
bash scripts/install-bin.sh
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
- [Workspace Portfolio Audit](docs/research/workspace-portfolio-audit.md) — observed
  repository families and recommended Workspace cuts.

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
