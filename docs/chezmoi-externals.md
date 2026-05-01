# chezmoi Externals vs XDG Paths: File Categorization Guide

## Overview

Two dotfile repositories are managed as chezmoi externals:

- **sussdorff/claude** — managed at `~/.claude`
- **sussdorff/codex** — managed at `~/.codex`

These repos contain configuration and skill definitions. Runtime state, caches, and machine-specific files must be gitignored or stored outside the chezmoi-managed tree.

## Category Definitions

| Category | Description | Action |
|----------|-------------|--------|
| **config** | User-defined settings shared across machines | Commit to repo |
| **template** | Skill definitions, prompt templates, agent specs | Commit to repo |
| **runtime** | Files written at runtime by the tool (session state, locks) | Gitignore |
| **cache** | Derived or downloaded data, safe to regenerate | Gitignore (prefer XDG cache dir) |
| **log** | Append-only operation logs | Gitignore |
| **machine-specific** | Credentials, machine IDs, local paths | Gitignore or keep in XDG secret store |
| **orphaned** | Files with no current purpose | Remove or gitignore with comment |

## ~/.claude Categorization

| Path pattern | Category | Action | Reason |
|---|---|---|---|
| `CLAUDE.md` | config | commit | Global instructions for all projects |
| `settings.json` | config | commit | Shared tool settings |
| `settings.local.json` | machine-specific | gitignore (`**/settings.local.json`) | Per-machine permission overrides |
| `settings.json.bak.*` | runtime | gitignore (`*.bak.*`) | Timestamp-suffixed auto-backups |
| `daily-brief.yml` | config | commit | Project list for daily briefing |
| `rules.d/` | config | commit | Modular behavioral rules |
| `skills/*/SKILL.md` | template | commit | Skill definitions |
| `skills/open-brain/people-query/SKILL.md` | template | commit | Open-brain people query skill |
| `skills/claude-docs/docs/` | cache | gitignore | Downloaded Claude docs, regenerable |
| `projects/` | runtime | gitignore | Session JSONL files, one per project |
| `projects/**/*.jsonl` | runtime | gitignore (via `projects/`) | Individual session transcripts |
| `compaction-state/` | runtime | gitignore | Compaction bookmarks |
| `sessions/`, `session-state/` | runtime | gitignore | Live session data |
| `cache/` | cache | gitignore | General tool cache |
| `logs/`, `*.log` | log | gitignore | Tool operation logs |
| `history.jsonl` | log | gitignore | Command history |
| `statsig/`, `stats-cache.json` | runtime | gitignore | Analytics state |
| `update-check/` | runtime | gitignore | Version check cache |
| `telemetry/` | runtime | gitignore | Telemetry data |
| `oauth_token` | machine-specific | gitignore | Auth token |
| `plugins/cache/`, `plugins/data/` | cache | gitignore | Plugin download cache |
| `plugins/installed_plugins.json` | runtime | gitignore | Dynamic install state |
| `.beads/events/` | runtime | gitignore | Live event log (causes merge conflicts) |
| `.beads/backup/` | runtime | gitignore (via `.beads/` internal .gitignore) | Dolt backup files |
| `anatomy.json`, `buglog.json` | cache | gitignore | Rebuilt each session |
| `__pycache__/`, `*.pyc` | cache | gitignore | Python bytecode |
| `*.sqlite`, `*.sqlite-shm`, `*.sqlite-wal` | runtime | gitignore | SQLite database and WAL/SHM companion files |
| `.DS_Store` | OS artifact | gitignore | macOS metadata |

## ~/.codex Categorization

| Path pattern | Category | Action | Reason |
|---|---|---|---|
| `config.toml` | machine-specific | gitignore | Chezmoi-rendered from a 1Password-backed template; gitignored to prevent committing secrets |
| `AGENTS.md` | config | commit | Agent definitions |
| `RTK.md` | config | commit | Runtime knowledge |
| `hooks.json` | config | commit | Hook definitions |
| `agents/*.toml` | template | commit | Agent spec files |
| `skills/*/SKILL.md` | template | commit | Skill definitions |
| `rules/` | config | commit | Behavioral rules |
| `scripts/` | config | commit | Helper scripts |
| `auth.json` | machine-specific | gitignore | API credentials |
| `installation_id` | machine-specific | gitignore | Per-machine Codex ID |
| `history.jsonl` | log | gitignore | Command history |
| `session_index.jsonl` | runtime | gitignore | Session registry |
| `sessions/` | runtime | gitignore | Session data |
| `shell_snapshots/` | runtime | gitignore | Shell environment snapshots |
| `cache/` | cache | gitignore | General cache |
| `log/`, `logs/` | log | gitignore | Tool logs |
| `tmp/`, `.tmp/` | runtime | gitignore | Temporary files |
| `*.sqlite`, `*.sqlite-shm`, `*.sqlite-wal` | runtime | gitignore | SQLite database files |
| `generated_images/` | cache | gitignore | AI-generated image outputs |
| `memories/` | runtime | gitignore | Memory store (managed by open-brain) |
| `models_cache.json` | cache | gitignore | Downloaded model metadata |
| `.codex-global-state.json` | runtime | gitignore | Machine runtime state |
| `.codex-global-state.json.bak` | runtime | gitignore | Backup of runtime state |
| `*.bak`, `*.bak.*` | runtime | gitignore | Timestamp-suffixed auto-backups |
| `.personality_migration` | runtime | gitignore | Migration marker file |
| `vendor_imports/` | cache | gitignore | Vendored dependency cache |
| `projects/` | runtime | gitignore (defensive) | Not currently used by Codex, but gitignored to mirror ~/.claude structure and prevent accidental future leaks |
| `compaction-state/` | runtime | gitignore (defensive) | Not currently used by Codex, but gitignored defensively |

## What Belongs Where

### Commit to chezmoi external (shared across machines)

- Skill definitions (`SKILL.md`, agent specs, templates)
- User configuration (project lists, behavior rules, hook configs)
- Helper scripts that are not machine-specific
- Agent prompt files and boundaries

### Gitignore within the chezmoi external repo

- Session transcripts and state (`projects/`, `sessions/`)
- Runtime locks and PIDs
- Per-machine credentials and IDs
- Caches that are regenerable
- Timestamp-suffixed backup files (`*.bak.*`)
- SQLite files and WAL/SHM companions
- OS artifacts (`.DS_Store`)

### Store in XDG paths (outside chezmoi)

- `~/.cache/` — tool caches that should never be committed
- `~/.local/share/` — application data (e.g., beads Dolt database)
- `~/.config/` — application config that is not chezmoi-managed

The beads Dolt database and server state live under `~/.claude/.beads/` which has its own `.gitignore` that excludes runtime files. The beads config (`config.yaml`) and templates are tracked.

## Gitignore Files

- `~/.claude/.gitignore` — covers Claude Code runtime artifacts
- `~/.codex/.gitignore` — covers Codex runtime artifacts
- `~/.claude/.beads/.gitignore` — covers beads internal runtime files

## Audit History (CL-wn8, 2026-05-01)

The following drift was found and resolved:

| Item | Was | Resolution |
|------|-----|------------|
| `projects/-Users-malte-code-mira-adapters/538bd18f-...jsonl` | tracked (committed before `projects/` gitignore was added) | `git rm --cached` — untracked, file kept on disk |
| `settings.json.bak.20260501072951` | untracked (`.bak` pattern missed mid-name timestamps) | gitignored via new `*.bak.*` pattern |
| `daily-brief.yml` | untracked (config file missing from repo) | committed |
| `skills/open-brain/people-query/SKILL.md` | untracked (skill definition not yet committed) | committed |
| `~/.codex` | clean | no action needed — .gitignore already comprehensive |
