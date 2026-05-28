# Repository Navigation for Agents

> **For both Claude Code and Codex CLI.** This is the entry point — read this first,
> then jump to the linked detail document for the question you have.
> `CLAUDE.md` in this repo @-imports this file; do not duplicate content there.

## Repository Identity

This repository is the **library platform**. Its current checkout path is
`/Users/malte/code/library/meta`, but the intended name is
`library-platform/`.

Use this repo for the tooling, scripts, schemas, launchers, installers, tests,
and documentation that power the library system. It is not itself a catalog of
shareable skills or agents.

Sibling catalog repositories:

- `../cognovis-core/` is the Cognovis developer marketplace, intended name
  `cognovis-marketplace/`.
- `../sussdorff-core/` is the private personal catalog, intended name
  `sussdorff-private-catalog/`.

When install/remove/sync code touches a catalog, keep the platform repository
separate from the target catalog or project where content is installed.

## Where to look first

| Your question | Read | Section / anchor |
|---|---|---|
| What is a Skill / Agent / Hook / Standard / Plugin / Marketplace exactly? | `docs/PRIMITIVES.md` | matching `### N. <name>` section |
| Orchestrator system prompt vs. agent system prompt (which one am I editing?) | `docs/primitives/system-prompt.md` (orchestrator) + `docs/primitives/agent-base.md` (agent Layer 1) | — |
| Is primitive X portable between Claude Code, Codex, Pi, OpenCode? | `docs/PRIMITIVES.md` | **Portability Matrix (TL;DR)** — top of file, after Decision Tree |
| Which primitive should I create for this new capability? | `docs/PRIMITIVES.md` | **Quick Decision Tree** — very top |
| How is this repo structured (4-layer stack, install paths)? | `docs/ARCHITECTURE.md` | The 4-layer Agentic Stack |
| Which design decisions were made and why? | `docs/adr/` | matching ADR filename |
| Name collisions, project-local vs. global precedence | `docs/policy/name-collision.md` | — |
| How does `library.yaml` / lockfile work? | `docs/lockfile-format.md` | — |
| Tooling (chezmoi, install scripts, etc.) | `docs/project-tooling.md`, `docs/chezmoi-externals.md` | — |
| How standards dependencies work | `docs/PRIMITIVES.md` | `### 7. Standard` |
| What to commit in `.claude/` / `.agents/` / `.codex/` for a collaboration project | `docs/harness-baseline.md` | Baseline Checklist |
| Beads workflow (issue tracking, session-close protocol) | `bd prime` | run the command — single source of truth |

**Rule of thumb:** if a question is about a *primitive's behavior or portability*,
the answer is in `docs/PRIMITIVES.md`. If it is about *how this repo is wired*,
the answer is in `docs/ARCHITECTURE.md` or an ADR. If it is about *workflow*,
it is in `bd prime`.

## Repository-specific Conventions

### Canonical Launchers (`cld` / `cdx` / `agr` / `cra`)

- **Canonical home:** `bin/` (this repo)
  - `bin/cld` — Claude Code launcher (full-featured zsh wrapper)
  - `bin/cdx` — Codex CLI launcher (parallel to `cld`)
  - `bin/agr` — Antigravity (Gemini CLI) launcher with automatic approvals
  - `bin/cra` — Cursor Agent launcher with automatic approvals
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
