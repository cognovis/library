# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

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


## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Canonical Launchers (cld/cdx)

- **Canonical home:** `cognovis-library/bin/` (this repo)
  - `bin/cld` — Claude Code launcher (502 lines, full-featured zsh wrapper)
  - `bin/cdx` — Codex CLI launcher (zsh wrapper, parallel to `cld`)
- **Install command:** `bash scripts/install-bin.sh`
  - Creates symlinks from `~/.local/bin/cld` and `~/.local/bin/cdx` into `bin/`
  - Idempotent: safe to run multiple times
  - `~/.local/bin/` must be in `$PATH` (replaces the old `~/.claude/scripts/` PATH entry)
- **Per ADR-0002 Decision 2:** launchers live in `cognovis-library/bin/`, not in
  `~/.claude/scripts/`. The `~/.claude/scripts/` directory is no longer in `$PATH`.
- **Note:** `CMUX_BUNDLED_CLI_PATH` in `cld` still references `~/.claude/scripts/cmux-shim.sh`
  at runtime. Moving `cmux-shim.sh` to `cognovis-library/bin/` is a follow-up task (Phase 2 cleanup per ADR-0002 Decision 3).

## Conventions & Patterns

### library.yaml schema ownership

Schema extensions to `library.yaml` are **serialized**. Per top-level section
(`mcp_servers:`, `guardrails:`, `marketplaces:`, `hooks:`, …) at most one
extending bead may be active at a time. While that bead is open, other beads
must not modify the same section in parallel — file an explicit
`bd dep add <new-bead> <active-bead>` instead.

Validator tests (`CL-wud`) run on every schema change.
