# The Library

A meta-skill for private-first distribution of agentics (skills, agents, and prompts) across agents, devices, and teams.

![The Library](images/10_meta_skill.svg)

## Who This Is For

If you're an engineer working on 10+ codebases with agents and you're building specialized private skills, agents, and prompts — this was made for you.

If you work in one or two repos, you don't need this. If you install skills from the public internet without reviewing them, this isn't for you either.

The Library solves a specific problem: you've built powerful agentics scattered across repos, devices, and teams. They're duplicated, out of sync, and hard to coordinate. This gives you a single reference catalog to distribute them privately.

## What It Is

The Library is a single skill whose only job is to manage other skills. It's a catalog of references — local file paths and GitHub repo URLs — that point to where your agentics live. Nothing is copied or installed until you ask for it.

Think of it as a `package.json` for agent capabilities — but instead of packages, you're managing skills, agents, and prompts. Instead of a registry, you're pointing at your own private GitHub repos and local paths.

**This is a pure agent application.** There are no scripts, no CLIs, no dependencies, no build tools. The entire application is encoded in `SKILL.md` and a set of cookbook instructions that teach the agent exactly what to do. The agent IS the runtime. This matters because:

- Any agent harness that reads skill files can run it (Claude Code, Pi, etc.)
- You can modify behavior by editing markdown, not code
- The skill can be extended, forked, and adapted instantly
- An orchestrator agent can chain library commands without any tooling overhead

## Why It Exists

![The Problem: Skill Sprawl](images/26_problem_skill_sprawl.svg)

As you build with AI agents, you accumulate skills, custom agents, and prompts — potentially hundreds of them. You need to:

- **Reuse** them across projects without copy-pasting
- **Distribute** them to your agents running on other devices (Mac mini, remote servers, cloud sandboxes)
- **Share** them with your team without making everything public
- **Keep them private** — these are specialized capabilities built for competitive edge
- **Stay in sync** — one source of truth, not 10 stale copies

![The Problem: Siloed Teams](images/32_problem_team_sharing.svg)

Existing solutions don't fit:
- **Global `~/.claude/*`** — exposes everything to every agent. Global is the opposite of specialized.
- **Claude Code plugins** — requires marketplace infrastructure, manifests, and locks you into one platform.
- **Single monorepo** — doesn't reflect reality. You build agentics in specific codebases for specific use cases.

## How It Works

![The Solution: The Library](images/27_solution_library_workflow.svg)

### The Catalog (`library.yaml`)

```yaml
default_dirs:
  skills:
    - default: .agents/skills/
    - global: ~/.agents/skills/
    - claude_bridge: .claude/skills/
    - global_claude_bridge: ~/.claude/skills/
  agents:
    - default: .claude/agents/
    - global: ~/.claude/agents/
  prompts:
    - default: .claude/commands/
    - global: ~/.claude/commands/

library:
  skills:
    - name: my-skill
      description: What this skill does
      source: /Users/me/projects/tools/skills/my-skill/SKILL.md
      requires: [agent:helper-agent]
    - name: remote-skill
      description: A skill from a private repo
      source: https://github.com/myorg/private-skills/blob/main/skills/remote-skill/SKILL.md
  agents: []
  prompts: []
```

The catalog stores pointers, not copies. Skills live in their source repos. You pull on demand.

### Source Formats

| Format             | Example                                                            |
| ------------------ | ------------------------------------------------------------------ |
| Local filesystem   | `/absolute/path/to/SKILL.md`                                       |
| GitHub browser URL | `https://github.com/org/repo/blob/main/path/to/SKILL.md`           |
| GitHub raw URL     | `https://raw.githubusercontent.com/org/repo/main/path/to/SKILL.md` |

The source points to a specific file. The system pulls the entire parent directory (skills include scripts, references, assets — not just the markdown file).

For private repos, authentication uses SSH keys or `GITHUB_TOKEN` automatically.

### Consumer vs Marketplace Repos

`/library use` vendors real files into `.agents/` by default. Consumer projects should
commit those files; marketplace/library-core repos keep `.agents/` ignored because their
source content lives in top-level primitive directories.

| Repo type | Project tooling profile | `.agents/` policy |
|-----------|-------------------------|-------------------|
| Consumer app repo | `consumer` | Commit `.agents/skills/`, `.agents/standards/`, `.agents/agents/`, `.agents/prompts/` |
| Marketplace/library-core repo | `marketplace` | Ignore `.agents/` install targets |

Apply the profile from a project root with:

```bash
python3 <LIBRARY_SKILL_DIR>/scripts/sync_project_tooling.py --profile consumer --verbose
```

### Platform-Owned Primitive Forges

Primitive forge skills live in this repository because they define the Library
platform's own primitive contracts, templates, validators, and authoring rules.
The platform-owned forges are `skill-forge`, `agent-forge`, `standard-forge`,
`script-forge`, and `hook-forge` under `skills/`. `install.sh` installs these
forges into each detected harness alongside the `library` skill so they are
available on a fresh platform bootstrap.

### Typed Dependencies

Dependencies use typed references to avoid name collisions:

```yaml
requires: [skill:base-utils, agent:reviewer, prompt:task-router]
```

Dependencies are resolved and pulled first, recursively.

## Prerequisites

- **Claude Code** (or a compatible agent harness that reads `.claude/skills/` — e.g., Pi)
- **git** — for cloning sources and syncing the catalog
- **gh** (optional) — GitHub CLI for forking, cloning, and private repo access. Install: `brew install gh` or see [gh docs](https://cli.github.com)
- **GitHub SSH key or `GITHUB_TOKEN`** — for accessing private repos (not needed if using `gh auth login`)
- **just** (optional) — for justfile shortcuts. Install: `brew install just` or see [just docs](https://github.com/casey/just)

## Installation

This is a template repo. You fork it, clone it into your global skills directory, and it becomes a `/library` slash command available in every Claude Code session.

### 1. Fork This Repo

Fork to your own GitHub account (private repo recommended). This fork is your personal library catalog — you'll push catalog updates to it.

```bash
# Using GitHub CLI
gh repo fork disler/the-library --private --clone=false
```

Or fork manually via the GitHub UI.

### 2. Clone to Global Skills Directory

Clone your fork into `~/.claude/skills/library`. This path is what makes `/library` available as a global slash command in Claude Code.

```bash
# Using git
mkdir -p ~/.claude/skills/library
git clone <your-fork-url> ~/.claude/skills/library

# Or using GitHub CLI
gh repo clone <yourname>/the-library ~/.claude/skills/library
```

### 3. Configure

Open `~/.claude/skills/library/SKILL.md` and update the `## Variables` section with your fork URL. The agent reads these variables at runtime to know where to sync the catalog.

```markdown
# Before (template defaults)
- **LIBRARY_REPO_URL**: `<your forked repo url>`

# After (your values)
- **LIBRARY_REPO_URL**: `https://github.com/yourname/the-library.git`
```

The other two variables (`LIBRARY_YAML_PATH` and `LIBRARY_SKILL_DIR`) are correct by default if you cloned to `~/.claude/skills/library/`.

### 4. Verify

Start a new Claude Code session anywhere. `/library skill list` should work and
show an empty catalog.

## Quick Start

![Full Workflow](images/45_solution_full_workflow.svg)

Here's the typical workflow: **build → catalog → distribute → use**.

### Add a skill to the catalog

You built a deploy skill in one of your repos. Register it:

```
/library skill add deploy from https://github.com/yourorg/infra-tools/blob/main/skills/deploy/SKILL.md
```

This adds a reference to `library.yaml` and pushes the update to your fork.

### Use it in another project

On another device, repo, or agent:

```
/library skill use deploy
```

This pulls the skill from the source repo into the canonical `.agents/skills/deploy`
path and creates the Claude bridge at `.claude/skills/deploy`.

Want it globally available on this machine?

```
/library skill use deploy install globally
```

### Push changes back

You improved the skill locally. Push the update to the source repo:

```
/library skill push deploy
```

Now every device that runs `/library sync` gets the latest version.

### Sync everything

Pull the latest version of all installed items:

```
/library sync
```

## Commands

| Command                              | What It Does                                               |
| ------------------------------------ | ---------------------------------------------------------- |
| `/library install`                   | First-time setup — fork, clone, configure                  |
| `/library <primitive> add <details>` | Register a new entry in the catalog                        |
| `/library <primitive> use <name>`    | Pull from source into local directory (install or refresh) |
| `/library <primitive> push <name>`   | Push local changes back to the source                      |
| `/library <primitive> remove <name>` | Remove from catalog and optionally delete local copy       |
| `/library <primitive> list`          | Show catalog entries with install status                   |
| `/library sync`                      | Re-pull all installed items from source                    |
| `/library search <keyword>`          | Find entries by name or description                        |

### Justfile Shortcuts

The included `justfile` lets you run library commands from your terminal without an interactive Claude session.

```bash
just list                  # List catalog
just use my-skill          # Pull a skill
just push my-skill         # Push changes back
just add "name: foo, description: bar, source: /path/to/SKILL.md"
just sync                  # Re-pull all installed items
just search "keyword"
```

> **Note:** Justfile recipes use `--dangerously-skip-permissions` because the agent needs filesystem and git access to clone, copy, and push. Review the `justfile` if you want to modify this behavior.

## cdx — Codex Launcher with Beads Workflow

`cdx` is the Codex parallel to `cld`. It wraps the `codex` CLI with beads workflow integration,
using prompt injection to pass bead context (since Codex has no `--bead` flag equivalent).

### Install cdx

```bash
# From this repo
just install-cdx

# Or manually
cp scripts/cdx ~/.local/bin/cdx && chmod +x ~/.local/bin/cdx
```

Ensure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"  # Add to ~/.zshrc or ~/.bashrc
```

### Usage

```bash
# Plain Codex launch (full-auto by default)
cdx

# Bead orchestrator mode — equivalent to cld -b <id>
cdx -b <bead-id>
just cdx <bead-id>

# Quick-fix mode — equivalent to cld -bq <id>
cdx -bq <bead-id>
just cdx-quick <bead-id>

# Fresh-context bead-spec/readiness review (Opus by default)
cdx -br <bead-id>
just cdx-review <bead-id>

# Coordinator callback — signal a cmux pane on blocking questions and session-close
cdx -b <bead-id> --coordinator-workspace workspace:3 --coordinator-surface surface:5
cld -b <bead-id> --coordinator-workspace workspace:3 --coordinator-surface surface:5

# Full bypass for bead modes (opt-in only; prints stderr warning)
cdx -b <bead-id> --bead-dangerous-full-auto
```

> **Permission defaults for bead modes:** `cdx -b`, `cdx -bq`, and `cdx -br` use
> `--sandbox workspace-write -c approval_policy="never"` by default. Pass
> `--bead-dangerous-full-auto` only when you need Codex's full
> `--dangerously-bypass-approvals-and-sandbox` behavior; this prints a visible
> warning to stderr. The plain `cdx` launch path is unaffected.

### How It Works

Codex has no `--bead` flag. `cdx` synthesizes bead context by:

1. Calling `bd show <bead-id>` to fetch the full bead description and acceptance criteria
2. Serializing the bead fields (title, description, AC, notes, labels, dependency titles) as a
   validated, provenance-tagged JSON envelope wrapped in explicit untrusted-data delimiters, then
   injecting it as an initial prompt to `codex exec`
3. The bead-orchestrator skill is invoked by natural-language reference in the prompt

The envelope approach prevents bead-authored text from being interpreted as launcher instructions
(prompt-injection isolation). `bin/cdx` fails closed with a non-zero exit on any malformed or
oversized envelope rather than passing raw text through.

```bash
# Under the hood, cdx -b <id> is equivalent to:
codex exec "Work on bead <id>. Use the bead-orchestrator skill. [validated JSON envelope injected here]"
```

See `docs/research/codex-prompts.md` for the full rationale and prompt-injection vs flag-dispatch
analysis.

### Justfile Targets

| Target | Equivalent | Description |
|--------|-----------|-------------|
| `just install-cdx` | — | Install cdx to ~/.local/bin |
| `just cdx <id>` | `cld -b <id>` | Bead orchestrator mode |
| `just cdx-quick <id>` | `cld -bq <id>` | Quick-fix mode |
| `just cdx-review <id>` | `cld -br <id>` | Fresh-context bead-spec review (Opus) |

---

## Architecture

```
~/.claude/skills/library/     # The Library skill (globally installed)
    SKILL.md                  # Agent instructions — the brain
    library.yaml              # Your catalog of references
    cookbook/                  # Step-by-step guides for each command
        install.md
        add.md
        use.md
        push.md
        remove.md
        list.md
        sync.md
        search.md
    justfile                  # CLI shorthand for all commands
    README.md                 # This file
```

## Design Principles

- **Private-first**: Built for your specialized, competitive-edge agentics. Not a public marketplace.
- **Reference-based**: The catalog stores pointers, not copies. Skills live in their source repos.
- **Pure agent**: No scripts, no build tools. The SKILL.md teaches the agent everything it needs to know.
- **Agent-agnostic**: Default target is `.claude/skills/` but supports any directory for any agent harness.
- **Catalog, not manifest**: Entries define what's available, not what's installed. Pull on demand.

## The Agentic Stack

![The Agentic Stack](images/03_agentic_stack.svg)

| Layer           | Purpose                                        |
| --------------- | ---------------------------------------------- |
| **Skills**      | Raw capabilities — what an agent can do        |
| **Agents**      | Scale + parallelism + specialization           |
| **Prompts**     | Orchestration — coordinate skills and agents   |
| **Justfile**    | Terminal access without an interactive session |
| **The Library** | Distribution across devices, teams, and agents |

## Master Agentic Coding
> Prepare for the future of software engineering

Agentic Engineering is a NEW SKILL for software engineers. And soon it will be a required skill for software engineers. Master it before the masses with [Tactical Agentic Coding](https://agenticengineer.com/tactical-agentic-coding?y=tlibms)

Follow the [IndyDevDan YouTube channel](https://www.youtube.com/@indydevdan) to improve your agentic coding advantage.
