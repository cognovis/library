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

A Library Workspace selects reusable Library-owned parts of that baseline. It
does not replace repository-owned `AGENTS.md`, permissions, product instructions,
customer facts, or runtime configuration. A repository may register several
orthogonal Workspaces; their union is recorded through one project lockfile.

## Baseline Checklist

### Library desired state

The table describes the lockfile v2 target accepted in ADR-0010. Until
`CL-r7n6` lands, `.library.lock` remains the released v1 additive installed list
and no Workspace command is available.

**MUST be committed when the project uses Library-managed primitives:**

| File | Purpose |
|------|---------|
| `.library.lock` | Universal direct and Workspace requested roots plus exact materialized receipts |

Workspace manifests themselves remain versioned catalog content and are not
copied into the consumer repository. A clone restores the selected roots through
`library workspace sync --all --scope project` or conservative `library sync`.
The project may add direct primitive roots that intentionally survive Workspace
changes.

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
| .agents/orchestrator-config.yml | Orchestrator routing configuration (project-local). The **global** fallback `~/.agents/orchestrator-config.yml` is self-healed on every `cld`/`cdx` launch from the canonical catalog source (`bin/lib/orchestrator-config-sync.zsh`), so it never silently drifts. |

**MUST NOT be committed:**

| File/Dir | Reason | .gitignore pattern |
|---|---|---|
| .agents/skills/*/cache/ | Generated cache directories | `.agents/skills/*/cache/` |

### .codex/ (Codex CLI)

**MUST be committed:**

| File/Dir | Purpose | Notes |
|---|---|---|
| .codex/agents/ | Project-specific Codex agent definitions | Required for project-level agent access |

**OPTIONAL but useful:**

| File/Dir | Purpose |
|---|---|
| .codex/commands/ | Project-specific Codex slash commands |
| .codex/standards/ | Codex-specific domain standards (if different from .agents/standards/) |
| .codex/hooks/ | Project-specific Codex hooks |

**MUST NOT be committed:**

Codex stores credentials user-global in `~/.codex/auth.json`. There is no documented
project-local secret file for Codex today — no gitignore entries required for credentials.


### .cursor/ (Cursor)

**MUST be committed when used:**

| File/Dir | Purpose | Notes |
|---|---|---|
| .cursor/skills/ | Cursor skill bridge symlinks | `/library skill use --harness cursor` creates `.cursor/skills/<name>/` pointing at `.agents/skills/<name>/` |
| .cursor/rules/ | Cursor rules generated from skill `always_apply` or `globs` | Materialized as `.cursor/rules/<name>.mdc` |

**MUST NOT be committed:**

| File/Dir | Reason | .gitignore pattern |
|---|---|---|
| .cursor/settings.local.json | May contain credentials or machine-local overrides | `.cursor/settings.local.json` |

Cursor **MCP servers** are managed by the library installer: `/library mcp use
<name> --harness cursor` (or the default `--harness all`) writes the server into
the global `~/.cursor/mcp.json` under the standard `mcpServers` map, tagged with
`_origin` for idempotent re-install and clean `--remove`. The generic MCP
installer also supports Antigravity-compatible registrations in
`~/.gemini/config/mcp_config.json`; individual products may intentionally omit
that harness. Cursor **agent and guardrail** projection remain unmanaged today;
requests for those primitives with `--harness cursor` fail with a compatibility
message before target writes.

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

## Worktree Overlays

A linked Git worktree checks out tracked content only. The harness directories
that make a session behave like the main checkout are deliberately gitignored —
installed skills under `.agents/` and `.claude/skills/`, plus the local `.env` —
so a fresh bead worktree starts without them. Hygiene review, standards
resolution, and session-close gates then behave differently from the main
checkout for no reason the operator can see.

Both launchers bootstrap the same overlay set through one resolver,
`scripts/worktree-overlays.py`, which never overwrites anything the worktree
already owns and never links a source that is missing from the main checkout:

| Launcher | Mechanism |
|---|---|
| `cdx` | Creates its worktree with `git worktree add`, then calls the resolver's `link` command. Codex has no worktree bootstrap of its own, so the launcher creates the relative symlinks itself. |
| `cld` | Claude Code creates the worktree itself via native `--worktree`, so the wrapper cannot symlink into it afterwards. It resolves the overlay set up front and passes it as `worktree.symlinkDirectories` in `--settings`; Claude Code creates the symlinks during worktree creation. |

The resolver applies one rule through two presence probes. `cdx` probes the
worktree it just created; `cld` probes the main checkout's Git index, because a
fresh worktree carries exactly the tracked paths and its own worktree does not
exist yet.

- A source missing from the main checkout is skipped, so no dangling symlink is
  created.
- An overlay path that will be absent from the worktree is linked whole.
- An overlay path the worktree already owns is never replaced. When it is a
  directory, resolution descends and links only the children that are missing.
  This matters in marketplace repositories, where `.agents/` holds tracked
  content while `.agents/skills/` is gitignored: linking only the root would
  silently do nothing.

Set `CDX_WORKTREE_OVERLAYS` or `CLD_WORKTREE_OVERLAYS` to a space-separated list
to override the overlay set for a repository, or to an empty string to disable
the bootstrap. The default set is `.agents .claude/skills .env`. Claude Code's
`symlinkDirectories` accepts directories only, so `cld` omits `.env`; a project
that wants `.env` in a Claude Code worktree copies it through `.worktreeinclude`
instead, accepting that a copy duplicates the secret.

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

# Cursor harness - secret-bearing local settings
.cursor/settings.local.json
```

## Generalizing Beyond .claude/

The same principles apply to all harnesses:

| Harness | Config dir | Rules file | Secret-bearing local file |
|---|---|---|---|
| Claude Code | `.claude/` | `CLAUDE.md` + `settings.json` | `settings.local.json` |
| Codex CLI | `.codex/` | `AGENTS.md` (symlink to `~/.agents/AGENTS.md`) | no documented project-local secret file; credentials in `~/.codex/auth.json` |
| Cursor | `.cursor/` | `.cursorrules` / `CURSOR.md` | `.cursor/settings.local.json` |
| Cross-harness | `.agents/` | `AGENTS.md` (shared) | - |

As harnesses mature, the library distribution system (`library <primitive> use`) installs
into both project-local and user-global paths automatically. Keeping the
project-local directories committed and secrets-free ensures the install state is
reproducible for the whole team.

In the target CLI contract, primitive operations use
`library <primitive> use <name>`. Workspace operations add composition and
ownership-aware lifecycle without changing the harness paths above. Installation
scope is not context-load scope: each installed member retains its own trigger
semantics.

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
| .codex/commands/, .codex/standards/, .codex/hooks/ | N/A | Optional directories; mira does not require them — project cross-harness standards live in `.agents/standards/` |
| anatomy.json gitignored | PASS | `.claude/anatomy.json` in `.gitignore` |
| buglog.json gitignored | PASS | `.claude/buglog.json` in `.gitignore` |

mira meets all baseline requirements. It also has additional project-specific
configs (`.claude/doc-config.yml`, `.claude/uat-config.yml`, and
`.claude/scenario-config.yml`) that are not required by the baseline but are
recommended for mature collaboration projects.
