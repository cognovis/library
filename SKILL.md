---
name: library
description: Private skill distribution system. Use when the user wants to install, use, add, push, remove, sync, list, or search for skills, agents, or prompts from their private library catalog. Triggers on /library commands or mentions of library, skill distribution, or agentic management.
argument-hint: "[command or prompt] [name or details]"
---

# The Library

A meta-skill for private-first distribution of agentics (skills, agents, and prompts) across agents, devices, and teams.

## Variables

> Update these after forking and cloning the library repo.

- **LIBRARY_REPO_URL**: `<your forked repo url>`
- **LIBRARY_YAML_PATH**: `~/.claude/skills/library/library.yaml`
- **LIBRARY_SKILL_DIR**: `~/.claude/skills/library/`

## How It Works

The Library is a catalog of references to your agentics. The `library.yaml` file points to where skills, agents, and prompts live (local filesystem or GitHub repos). Nothing is fetched until you ask for it.

**The `library.yaml` is a catalog, not a manifest.** Entries define what's *available* — not what gets installed. You pull specific items on demand with `/library <primitive> use <name>`.

## Command Grammar

Primitive-scoped commands use the primitive name before the verb:

```text
/library <primitive> <verb> [name-or-query]
```

Valid primitive names are singular: `skill`, `agent`, `prompt`, `standard`,
`guardrail`, `mcp`, `model-standard`, and `golden-prompt`.

The `/library` skill is the chat-facing wrapper. Deterministic catalog parsing,
filtering, dependency resolution, and install/update behavior live in
`scripts/library.py`. Keep this skill focused on dispatch rules, user-facing
decisions, and fallback behavior when the CLI is unavailable.

## CLI Delegation

**For deterministic operations, call `python3 scripts/library.py` directly:**

```bash
# List all skills in JSON (machine-readable):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py skill list --json

# Dry-run install of a skill (preview without mutation):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py skill use <name> --dry-run --json

# Install a standard to global scope:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py standard use <name> --scope global

# Search across all primitives:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py search <keyword>

# Check upstream status for all installed entries (no clone):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py status --json

# Detect local drift across all primitives (exit 2 if drift):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py audit --drift-only --json

# Sync all installed entries, skip current, dry-run first:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py sync --dry-run
python3 <LIBRARY_SKILL_DIR>/scripts/library.py sync
```

**The CLI handles all primitives and verbs** (use, remove, sync, audit, list, search) for
all primitive types (skill, agent, prompt, standard, guardrail, mcp, model-standard,
golden-prompt). Dependency resolution, lockfile writes, and harness selection are all
handled by the CLI — do NOT implement these manually.

**Interpreting JSON output**: The CLI returns a JSON object with:
- `status`: `"ok"`, `"dry-run"`, `"blocked"`, or `"error"`
- `data`: operation-specific results (name, canonical path, cache path, etc.)
- `operations`: (dry-run only) list of planned write operations
- `message`: human-readable summary

## Commands

| Command                                  | Purpose                                  |
| ---------------------------------------- | ---------------------------------------- |
| `/library install`                       | First-time setup: fork, clone, configure |
| `/library <primitive> list`              | Show catalog entries for one primitive   |
| `/library <primitive> use <name>`        | Pull from source (install or refresh)    |
| `/library <primitive> add <details>`     | Register a new catalog entry             |
| `/library <primitive> push <name>`       | Push local changes back to source        |
| `/library <primitive> remove <name>`     | Remove from catalog and optionally local |
| `/library <primitive> sync`              | Re-pull all installed entries of one primitive type |
| `/library <primitive> audit`             | Detect local drift for one primitive type |
| `/library <primitive> search <keyword>`  | Search within a primitive section        |
| `/library search <keyword>`              | Search across all primitives             |
| `/library audit [--drift-only]`          | Detect local drift across all primitives; exit 2 on drift |
| `/library status`                        | Check upstream SHA for all installed entries (no clone) |
| `/library sync [--dry-run] [--force]`    | Re-sync all installed entries across primitives; skip current by default |

## Cookbook

The cookbook files provide supplementary guidance for operations that require
human judgment (scope selection, name collision resolution, first-time setup).
They do NOT contain install/remove/sync mechanics — those are handled by
`scripts/library.py`.

| Command | Cookbook                                   | Use When                                                     |
| ------- | ------------------------------------------ | ------------------------------------------------------------ |
| install | [cookbook/install.md](cookbook/install.md) | First-time setup on a new device                             |
| add     | [cookbook/add.md](cookbook/add.md)         | User wants to register a new skill/agent/prompt in catalog   |
| push    | [cookbook/push.md](cookbook/push.md)       | User improved a skill locally and wants to update the source |

For `use`, `remove`, `sync`, `list`, `search`, and `audit` — call the CLI directly.
The cookbook does not document these operations since the CLI handles them deterministically.

## Source Format

The `source` field in `library.yaml` supports these formats (auto-detected):

- `/absolute/path/to/SKILL.md` — local filesystem
- `https://github.com/org/repo/blob/main/path/to/SKILL.md` — GitHub browser URL
- `https://raw.githubusercontent.com/org/repo/main/path/to/SKILL.md` — GitHub raw URL

Both GitHub URL formats are supported. Parse org, repo, branch, and file path from the URL structure. For private repos, use SSH or `GITHUB_TOKEN` for auth automatically.

**Important:** The source points to a specific file (SKILL.md, AGENT.md, or prompt file). We always pull the entire parent directory, not just the file.

## Source Parsing Rules

**Local paths** start with `/` or `~`:
- Use the path directly. Copy the parent directory of the referenced file.

**GitHub browser URLs** match `https://github.com/<org>/<repo>/blob/<branch>/<path>`:
- Parse: `org`, `repo`, `branch`, `file_path`
- Clone URL: `https://github.com/<org>/<repo>.git`
- File location within repo: `<path>`

**GitHub raw URLs** match `https://raw.githubusercontent.com/<org>/<repo>/<branch>/<path>`:
- Parse: `org`, `repo`, `branch`, `file_path`
- Clone URL: `https://github.com/<org>/<repo>.git`
- File location within repo: `<path>`

## GitHub Workflow

When working with GitHub sources, prefer `gh api` for accessing single files (e.g., reading a SKILL.md to check metadata). For pulling entire skill directories, clone into a temp dir per the steps below.

**Fetching (use):**
1. Clone the repo with `git clone --depth 1 <clone_url>` into a temporary directory
2. Navigate to the parent directory of the referenced file
3. Copy that entire directory to the target local directory
4. The temporary directory is cleaned up automatically

**Pushing (push):**
1. Clone the repo with `git clone --depth 1 <clone_url>` into a temporary directory
2. Overwrite the skill directory in the clone with the local version
3. Stage only the relevant changes: `git add <skill_directory_path>`
4. Commit with message: `library: updated <skill name> <what changed>`
5. Push to remote
6. The temporary directory is cleaned up automatically

## Typed Dependencies

The `requires` field uses typed references to avoid ambiguity:
- `skill:name` — references a skill in the library catalog
- `agent:name` — references an agent in the library catalog
- `prompt:name` — references a prompt in the library catalog
- `standard:name` — references a standard in the library catalog

When resolving dependencies: look up each reference in `library.yaml`, fetch all dependencies first (recursively), then fetch the requested item.

## Target Directories

By default, items are installed to the directory for their primitive and scope
from `library.yaml`:

```yaml
default_dirs:
    skills:
        - default: .agents/skills/                    # canonical, project-local
        - global: ~/.agents/skills/                   # canonical, user-global
        - claude_bridge: .claude/skills/              # Claude bridge, project-local
        - global_claude_bridge: ~/.claude/skills/     # Claude bridge, user-global
    agents:
        - default: .claude/agents/
        - global: ~/.claude/agents/
    prompts:
        - default: .claude/commands/
        - global: ~/.claude/commands/
    standards:
        - default: .agents/standards/
        - global: ~/.agents/standards/
```

- If the user says "global" or "globally", use the `global` directory for the primitive.
- If the user specifies a custom path, use that path.
- Otherwise, use the `default` directory for the primitive.

Skills are cross-harness by default: `.agents/skills/<name>` is canonical and
Claude Code reaches it through `.claude/skills/<name>`. Codex reads
`.agents/skills/` directly.

## Validating library.yaml

The `library.yaml` catalog is validated against a formal JSON Schema at `docs/schema/library.schema.json`.

### Running validation

```bash
# Via just (recommended)
just validate-library

# Via Python directly
python3 scripts/validate-library.py

# With custom paths
python3 scripts/validate-library.py --yaml /path/to/library.yaml --schema /path/to/schema.json
```

Exit code `0` means PASS; exit code `1` means FAIL (errors printed to stdout).

### Schema coverage

The schema (`docs/schema/library.schema.json`) covers:

| Section | Status | Description |
|---------|--------|-------------|
| `default_dirs` | Defined | Per-primitive directory mappings per harness |
| `library.skills` | Defined | Skill catalog entries with source, requires, install paths |
| `library.agents` | Defined | Agent catalog entries with format-translation hints |
| `library.prompts` | Defined | Command/prompt catalog entries |
| `guardrails` | Stub | Capability matrix per harness (CL-xcm) |
| `standards` | Stub | Storage convention + loader-mechanism reference (CL-v56) |
| `mcp_servers` | Stub | Canonical MCP server model (CL-mfz) |
| `marketplaces` | Stub | Third-party source references (CL-7ii) |
| `plugins` | Stub | Bundle declarations |

Stub sections use `additionalProperties: true` so they pass validation when new beads (CL-xcm, CL-v56, CL-mfz, CL-7ii) add their content.

### Pre-commit hook integration

Add this to `.git/hooks/pre-commit` (or `scripts/pre-commit`):

```bash
#!/bin/sh
python3 scripts/validate-library.py --quiet
if [ $? -ne 0 ]; then
  echo "library.yaml validation failed. Fix errors before committing."
  exit 1
fi
```

Or install automatically:

```bash
echo 'python3 scripts/validate-library.py --quiet || exit 1' >> .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Extending the schema

When a new bead adds a section to `library.yaml`:

1. Edit `docs/schema/library.schema.json`
2. Replace the stub `additionalProperties: true` with a proper `$defs` entry
3. Run `just validate-library` to confirm the new schema accepts the updated `library.yaml`
4. Commit schema + `library.yaml` changes together

## Library Repo Sync

The library skill itself lives in `<LIBRARY_SKILL_DIR>` as a cloned git repo. When running `add` (which modifies `library.yaml`), always:
1. `git pull` in the library directory first to get latest
2. Make the changes
3. `git add library.yaml && git commit && git push`

This keeps the catalog in sync across devices.

## Example Filled Library File

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
  standards:
    - default: .agents/standards/
    - global: ~/.agents/standards/

library:
  skills:
    - name: firecrawl
      description: Scrape, crawl, and search websites using Firecrawl CLI
      source: /Users/me/projects/tools/skills/firecrawl/SKILL.md

    - name: meta-skill
      description: Creates new Agent Skills following best practices
      source: /Users/me/projects/tools/skills/meta-skill/SKILL.md

    - name: diagram-kroki
      description: Generate diagrams via Kroki HTTP API supporting 28+ languages
      source: https://github.com/myorg/private-skills/blob/main/skills/diagram-kroki/SKILL.md
      requires: [skill:firecrawl]

    - name: green-screen-captions
      description: Generate and burn AI-powered captions onto green screen videos
      source: https://raw.githubusercontent.com/myorg/video-tools/main/skills/green-screen-captions/SKILL.md
      requires: [agent:video-processor, prompt:caption-style]

  agents:
    - name: video-processor
      description: Processes video files with ffmpeg and whisper transcription
      source: /Users/me/projects/tools/agents/video-processor/AGENT.md

    - name: code-reviewer
      description: Reviews code for quality, security, and performance
      source: https://github.com/myorg/agent-configs/blob/main/agents/code-reviewer/AGENT.md

  prompts:
    - name: caption-style
      description: Style guide for generating video captions
      source: /Users/me/projects/content/prompts/caption-style.md

    - name: commit-message
      description: Standardized commit message format for all projects
      source: https://github.com/myorg/team-prompts/blob/main/prompts/commit-message.md
```
