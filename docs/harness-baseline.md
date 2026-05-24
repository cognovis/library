# Project Harness Baseline for Collaboration

## What This Is

A harness is the project-local configuration surface that lets agentic coding tools
work consistently in a repository. Examples include Claude Code's `.claude/`,
Codex CLI's `.codex/`, Cursor's `.cursor/`, and the shared `.agents/` tree used
by the library platform.

Collaboration projects need a committed baseline so another developer can clone
the repository and get the same rules, agents, commands, standards, and safe
permissions. Personal credentials, machine-local overrides, and generated runtime
state stay outside git.

## Baseline Checklist

### .claude/ (Claude Code)

**MUST be committed:**

| File/Dir | Purpose | Notes |
|---|---|---|
| CLAUDE.md | Project-specific instructions | @-imports AGENTS.md for shared rules |
| AGENTS.md | Shared cross-harness rules (English-only, tool use, etc.) | At repo root |
| .claude/agents/ | Project-specific agent definitions | Committed |
| .claude/commands/ | Project-specific slash commands | Committed |
| .claude/standards/ | Domain-specific coding standards | Committed |
| .claude/settings.json | Project permissions with no secrets | Committed |
| .claude/hooks/ | Project-specific hooks | Committed |

**MUST NOT be committed:**

| File/Dir | Reason | .gitignore pattern |
|---|---|---|
| .claude/settings.local.json | May contain OAuth tokens, API keys, or machine-local overrides | `.claude/settings.local.json` |
| .claude/worktrees/ | Ephemeral worktree directories | `.claude/worktrees/` |
| .claude/anatomy.json | Generated runtime state | `.claude/anatomy.json` |
| .claude/buglog.json | Generated runtime log | `.claude/buglog.json` |

**OPTIONAL but useful:**

| File/Dir | Purpose |
|---|---|
| .claude/skills/ | Project-local skills installed via `/library` |
| .claude/doc-config.yml | Documentation routing config |
| .claude/uat-config.yml | UAT test configuration |
| .claude/scenario-config.yml | Scenario-based testing config |

### .agents/ (Cross-harness / Codex)

**MUST be committed:**

| File/Dir | Purpose |
|---|---|
| .agents/standards/ | Domain-specific standards shared across harnesses |
| .agents/skills/ | Installed skills committed at project level; see mira for reference implementation |
| .agents/orchestrator-config.yml | Orchestrator routing configuration |

**MUST NOT be committed:**

| File/Dir | Reason | .gitignore pattern |
|---|---|---|
| .agents/skills/*/cache/ | Generated cache directories | `.agents/skills/*/cache/` |

### .codex/ (Codex CLI)

**MUST be committed:**

| File/Dir | Purpose |
|---|---|
| .codex/agents/ | Project-specific Codex agent definitions |
| .codex/commands/ | Project-specific Codex slash commands |
| .codex/standards/ | Domain standards for Codex sessions |
| .codex/hooks/ | Project-specific Codex hooks |

### .cursor/ (Cursor, future)

Reserved. As Cursor becomes a first-class harness, apply the same pattern:
committed project rules and credentials-free settings, with personal or secret
configs gitignored.

## Project-Local vs User-Global Separation

**Project-local** (`.claude/`, `.agents/`, `.codex/`, `.cursor/`) is anything
the whole team needs to collaborate effectively.

- Rules, agents, commands, standards, and credentials-free permissions are committed.
- Ephemeral state and secret-bearing overrides are gitignored.

**User-global** (`~/.claude/`, `~/.agents/`, `~/.codex/`) is personal,
machine-specific, and never shared.

- OAuth tokens, API keys, and other credentials
- Personal MCP server configuration
- Personal preferences and overrides
- Personal open-brain memories

The test: could a new team member clone this repo and immediately have a working
harness? If yes, the project-local baseline is met.

## .gitignore Patterns

Add these harness-specific patterns to your project's `.gitignore`:

```gitignore
# Claude Code harness - runtime and secret-bearing files
.claude/settings.local.json
.claude/worktrees/
.claude/anatomy.json
.claude/buglog.json

# Beads workflow - generated runtime artifacts
.beads/runs/

# Cross-harness skills cache
.agents/skills/*/cache/
```

## Generalizing Beyond .claude/

The same principles apply to all harnesses:

| Harness | Config dir | Rules file | Secret-bearing local file |
|---|---|---|---|
| Claude Code | `.claude/` | `CLAUDE.md` + `settings.json` | `settings.local.json` |
| Codex CLI | `.codex/` | `AGENTS.md` (symlink to `~/.agents/AGENTS.md`) | no documented project-local secret file; credentials in `~/.codex/auth.json` |
| Cursor | `.cursor/` | `.cursorrules` / `CURSOR.md` | `.cursor/settings.local.json` |
| Cross-harness | `.agents/` | `AGENTS.md` (shared) | - |

As harnesses mature, the library distribution system (`/library use`) installs
into both project-local and user-global paths automatically. Keeping the
project-local directories committed and secrets-free ensures the install state is
reproducible for the whole team.

## Reference Project: mira

mira (cognovis/mira) serves as the reference implementation of
this baseline. It was available during implementation, so zahnrad was not used
as the fallback reference.

Audit result, verified on 2026-05-24:

| Requirement | Status | Notes |
|---|---|---|
| CLAUDE.md + AGENTS.md | PASS | Root-level and tracked |
| .claude/agents/ | PASS | Project agents tracked |
| .claude/commands/ | PASS | Project commands tracked |
| .claude/standards/ | PASS | Domain standards tracked |
| .claude/settings.json | PASS | Project permissions tracked; keyword scan found no obvious secret markers |
| .claude/settings.local.json gitignored | PASS | `.claude/settings.local.json` in `.gitignore` |
| .claude/worktrees/ gitignored | PASS | `.claude/worktrees/` in `.gitignore` |
| .agents/ | PASS | `orchestrator-config.yml`, scripts, standards, and skills tracked |
| .codex/agents/ | PASS | Codex agents tracked |
| anatomy.json gitignored | PASS | `.claude/anatomy.json` in `.gitignore` |
| buglog.json gitignored | PASS | `.claude/buglog.json` in `.gitignore` |

mira meets all baseline requirements. It also has additional project-specific
configs (`.claude/doc-config.yml`, `.claude/uat-config.yml`, and
`.claude/scenario-config.yml`) that are not required by the baseline but are
recommended for mature collaboration projects.
