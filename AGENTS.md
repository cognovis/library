# Repository Navigation for Agents

> **For both Claude Code and Codex CLI.** This is the entry point — read this first,
> then jump to the linked detail document for the question you have.
> `CLAUDE.md` in this repo @-imports this file; do not duplicate content there.

## Where to look first

| Your question | Read | Section / anchor |
|---|---|---|
| What is a Skill / Agent / Hook / Standard / Plugin / Marketplace exactly? | `docs/PRIMITIVES.md` | matching `### N. <name>` section |
| Is primitive X portable between Claude Code, Codex, Pi, OpenCode? | `docs/PRIMITIVES.md` | **Portability Matrix (TL;DR)** — top of file, after Decision Tree |
| Which primitive should I create for this new capability? | `docs/PRIMITIVES.md` | **Quick Decision Tree** — very top |
| How is this repo structured (4-layer stack, install paths)? | `docs/ARCHITECTURE.md` | The 4-layer Agentic Stack |
| Which design decisions were made and why? | `docs/adr/` | matching ADR filename |
| Name collisions, project-local vs. global precedence | `docs/policy/name-collision.md` | — |
| How does `library.yaml` / lockfile work? | `docs/lockfile-format.md` | — |
| Tooling (chezmoi, install scripts, etc.) | `docs/project-tooling.md`, `docs/chezmoi-externals.md` | — |
| How standards are loaded into context (hook vs. `requires_standards:` vs. adapter) | `docs/research/standards-loading.md` | — |
| Beads workflow (issue tracking, session-close protocol) | `bd prime` | run the command — single source of truth |

**Rule of thumb:** if a question is about a *primitive's behavior or portability*,
the answer is in `docs/PRIMITIVES.md`. If it is about *how this repo is wired*,
the answer is in `docs/ARCHITECTURE.md` or an ADR. If it is about *workflow*,
it is in `bd prime`.

## Repository-specific Conventions

### Canonical Launchers (`cld` / `cdx`)

- **Canonical home:** `bin/` (this repo)
  - `bin/cld` — Claude Code launcher (full-featured zsh wrapper)
  - `bin/cdx` — Codex CLI launcher (parallel to `cld`)
- **Install:** `bash scripts/install-bin.sh` — symlinks into `~/.local/bin/` (must be on `$PATH`). Idempotent.
- **Per ADR `canonical-library-architecture` Decision 2:** launchers live in `bin/`, not in `~/.claude/scripts/`. The `~/.claude/scripts/` directory is no longer on `$PATH`.
- **Follow-up:** `CMUX_BUNDLED_CLI_PATH` in `cld` still references `~/.claude/scripts/cmux-shim.sh`. Move target is Phase 2 cleanup per the same ADR.

### `library.yaml` Schema Ownership (serialized)

Schema extensions to `library.yaml` are **serialized** per top-level section
(`mcp_servers:`, `guardrails:`, `marketplaces:`, `hooks:`, …). At most one extending
bead may be active at a time per section. While that bead is open, other beads must
not modify the same section in parallel — file an explicit `bd dep add <new-bead> <active-bead>` instead.

Validator tests (`CL-wud`) run on every schema change.

## Non-Interactive Shell Commands

Shell commands like `cp`, `mv`, `rm` may be aliased to `-i` mode on some systems, causing the agent to hang. Always use non-interactive flags:

```bash
cp -f source dest          # NOT: cp source dest
mv -f source dest          # NOT: mv source dest
rm -f file                 # NOT: rm file
rm -rf directory           # NOT: rm -r directory

# Others that may prompt:
# scp / ssh: -o BatchMode=yes
# apt-get:   -y
# brew:      HOMEBREW_NO_AUTO_UPDATE=1 (env var)
```

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

<!-- BEGIN STANDARD:python-cli-patterns v:1 hash:ab6e04218fc3 -->
---
domain: python-cli-patterns
description: Python CLI tool conventions — project structure, versioning, PyPI distribution, config resolution, update hints, packaging.
---

# Python CLI Patterns

> **Scope**: Loaded by Python development and testing skills that build or
> maintain command-line tools published to PyPI. Covers project layout, release
> flow, runtime config resolution, distribution, and update UX.

## What This Standard Covers

| File | Topic |
|------|-------|
| [project-scaffold.md](project-scaffold.md) | Directory layout and `pyproject.toml` template |
| [versioning-release.md](versioning-release.md) | CalVer, tag-driven GitHub Actions release, Trusted Publishing |
| [config-resolution.md](config-resolution.md) | Platform config paths, `key_command`, lazy click context |
| [distribution-packaging.md](distribution-packaging.md) | Hatchling `force-include`, package vs import names, `install-skill` |
| [update-and-ux.md](update-and-ux.md) | PyPI version self-check, first-run wizard, output file conventions |

## When These Patterns Apply

A Python tool is a CLI under this standard when:

- It is invoked by users from a shell (entry point in `[project.scripts]`)
- It is distributed via PyPI and installed with `uv tool install <name>`
- It may require runtime configuration (API keys, server URLs)

For internal libraries without a CLI entry point, only `project-scaffold.md`
applies; the other sub-topics are optional.

## Core Rules

- Use the `src/` layout — prevents accidental local imports during development.
- Version is single-sourced from a git tag, stamped by CI, never hand-edited.
- Config resolution order: env var → `key_command` → explicit setup hint.
- Never self-update; show an upgrade hint and let the user run `uv tool upgrade`.
- Bundle non-Python files explicitly via Hatchling `force-include`.
<!-- END STANDARD:python-cli-patterns -->

<!-- BEGIN STANDARD:english-only v:1 hash:1d10ea481194 -->
---
name: english-only
description: All source code must be in English — comments, identifiers, log messages, and string literals. Applies even when the user prompt is in another language.
---

# English-Only Source Code

> **Scope**: All skills, agents, hooks, and scripts in this library. Loaded globally via `default_scope: global`.

## Rule

All source code MUST be in English — including:

| Category | Rule |
|----------|------|
| Comments | English only |
| Identifiers | English variable, function, class, and method names |
| Log messages | English |
| String literals | English (technical strings, error messages, keys) |
| File names | English, kebab-case |

## Exceptions

- **User-facing strings** (UI labels, end-user error messages) may be localized when the project requires it
- **Data values** (e.g. test fixtures in another language) are permitted if the data itself is the subject

## Non-Exceptions

This rule applies even when:
- The user prompt is in German (or any other language)
- The project domain is German-language (e.g. healthcare, accounting)
- A team member requests a comment in their native language
<!-- END STANDARD:english-only -->

<!-- BEGIN STANDARD:no-emoji v:1 hash:c2492196344f -->
---
name: no-emoji
description: Do not add emojis to source code files, configuration files, or technical documentation. Emojis degrade diff readability and cause encoding issues in some terminals.
---

# No Emoji in Code

> **Scope**: All skills, agents, hooks, scripts, and technical documentation in this library. Loaded globally via `default_scope: global`.

## Rule

Do not add emojis to:

| Location | Examples |
|----------|---------|
| Source code comments | `# ✅ done` — forbidden |
| Log messages | `logger.info("🚀 started")` — forbidden |
| Identifiers or string literals | `const STATUS_OK = "✓"` — forbidden |
| Error messages | `raise ValueError("❌ invalid input")` — forbidden |
| Configuration files | YAML, TOML, JSON keys/values — forbidden |
| Technical documentation | ADRs, READMEs, changelogs — forbidden |

## Exception

User-facing UI strings where the **design spec explicitly requires** emoji (e.g. a status badge that is defined in a Figma design as "✅ Done").

## Rationale

- Emoji render inconsistently across terminals, editors, and log viewers
- Diffs become noisy and harder to read
- Some CI/CD systems and log parsers strip or mishandle multi-byte emoji codepoints
<!-- END STANDARD:no-emoji -->
