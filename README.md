# The Library Platform

The Library is a private-first platform for cataloging and distributing agentic
capabilities across repositories, machines, teams, and coding harnesses.

This repository owns the platform: the deterministic resolver and installers,
schemas, launchers, primitive authoring tools, tests, and architecture documents.
It also acts as the aggregate catalog index. Reusable Skills, Agents, Standards,
and other catalog content normally live in separate marketplace repositories.

## North star

This repository publishes exactly three things:

1. **The `library` command** — install skills and other primitives into a
   repository from central catalog management, repository-locally, with
   receipts. This is the product.
2. **`cld` and `cdx`** — deliberately lightweight launchers. They resolve a
   worktree, compose an initial prompt, and start a harness session. Delivery
   logic, review policy, and orchestration live in catalog skills
   (cognovis-core), never in the launchers.
3. **The docs and tests** that keep 1 and 2 trustworthy.

Every piece of work here must answer one question: *does it make installing
capabilities from central management into a repository better, or keep the
launchers thin?* If the answer is no, it does not belong in this repository's
backlog. In particular, these are **not** this repository's job:

- orchestration features, review workflows, or delivery lifecycles (catalog
  skills own those);
- harness tuning and coordinator wiring beyond starting a session;
- catalog *content* (skills, agents, standards live in marketplace repos);
- global installation of primitives — the enumerated Bootstrap (the `library`
  executable, the launchers, the harness entrypoints, launcher runtime
  configuration, the OpenBrain MCP server) is the only global surface.

One request is one bead. Side observations go into the conversation, not the
tracker.

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
The committed `.library.lock` records repository desired state. Library-generated
project installs and the transient `.library.lock.lock` and
`.library.lock.workspace-lock` sidecars stay local through the CLI-managed
`.gitignore` block. Marketplace repositories keep authored source primitives at
top level and ignore their generated install targets.
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

On a fresh machine, download `install.sh` from the published platform and run:

```bash
bash install.sh --fresh
```

Fresh mode clones the platform and `cognovis-base` catalog sources into the
XDG Library data directory, registers those portable checkouts, installs the
deterministic CLI and launchers through `uv tool`, and applies the small,
separately receipted product bootstrap. To initialize a repository in the same
run, pass `--project /path/to/git-repository`. The installer never projects a
Skill globally.

From an existing platform checkout, `bash install.sh` upgrades only the control
plane; run `library bootstrap install` explicitly when the bootstrap also needs
reconciliation. Bootstrap refuses to overwrite operator-owned instruction or
runtime files. Optional forge Skills belong in a project Workspace. Ensure
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
library standard use english-only --scope project
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
baselines. Existing parallel mechanisms are transitional:

- the historical global capability list is replaced repository by repository;
  only the enumerated product bootstrap remains global;
- legacy consumer manifests and updater scripts have retired in favor of
  direct or Workspace roots; and
- `project_tooling` accepts no new capability-distribution responsibilities.

Legacy targets remain protected external ownership until their replacement has
been verified. Workspaces do not absorb arbitrary file-copy rules, JSON patches,
secrets, customer facts, routing profiles, or repository-specific policy.

## Launchers

Packaged harness launchers live in `scripts/bin/`:

| Launcher | Harness |
|----------|---------|
| `scripts/bin/cld` | Claude Code |
| `scripts/bin/cdx` | Codex CLI |

Install them with:

```bash
bash install.sh --fresh
```

`bash install.sh` upgrades the global control plane: the `library` CLI and the
`cld` and `cdx` launchers. It does not install global desired-state Skills and
must not overwrite `~/.agents/skills`. After that control-plane upgrade,
`library init` or Workspace sync installs project-local Skills. For an existing
project using the default Workspace, reconcile them with:

```bash
library workspace sync --all --scope project
```

The default `cognovis-base` Workspace supplies two repository-delivery modes:

```bash
cld -sb CL-123 -- "Focus on the API boundary."
cdx --solo-bead CL-123 -- "Focus on the API boundary."
cld -b CL-123
cdx -b CL-123
cld -ep CL-101,CL-102
cdx --executive-pack CL-101,CL-102
```

`-sb` and `--solo-bead` select canonical Solo Bead delivery. The legacy `-b`
form remains a compatibility alias. `-ep` and `--executive-pack` select one
ordered, same-repository Executive Pack. In either mode, `--` separates launcher
options from an optional command prompt appended for the delivery session.

The default roles preserve implementation and review family separation:

| Launcher | Implementation | Reviewer 1 | Reviewer 2 |
|----------|----------------|------------|------------|
| `cdx` | GPT-5.6-sol with medium reasoning | Opus reviewer | Kimi; a fresh GPT-5.6 reviewer with high reasoning is the fallback |
| `cld` | Opus implementation | GPT-5.6-sol reviewer with high reasoning | Kimi; a fresh Opus reviewer is the fallback |

Explicit caller role instructions may override these defaults while preserving
the launcher's required role separation. Topic coordination is optional and sits
above repository-scoped Executive Packs for human-approved cross-repository work;
it is not part of the default Workspace roots.

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
