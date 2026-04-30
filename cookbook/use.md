# Use a Skill from the Library

## Context
Pull a skill, agent, or prompt from the catalog into the local environment. If already installed locally, overwrite with the latest from the source (refresh).

## Input
The user provides a skill name or description.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Find the Entry
- Read `library.yaml`
- Search across `library.skills`, `library.agents`, and `library.prompts`
- Match by name (exact) or description (fuzzy/keyword match)
- If multiple matches, show them and ask the user to pick one
- If no match, tell the user and suggest `/library search`

### 3. Resolve Marketplace Reference
If the matched catalog entry has a `source` field, skip this step — use the explicit `source` directly in Step 6.

If the entry has a `from_marketplace` field (and no `source`):
- Look up the marketplace by name in `library.yaml` → `marketplaces`
- If not found, warn the user: "Marketplace '<name>' is not registered in library.yaml" and stop
- Construct the full browser-form GitHub URL:
  - `<marketplace.source>/<repo>/blob/main/<path>/SKILL.md`
  - Example: `https://github.com/disler/claude-code-hooks-mastery/blob/main/.claude/skills/ruff/SKILL.md`
  - If the entry's `path` already includes the filename, use it directly
- Use this resolved URL as the effective `source` for the remaining steps

### 4. Resolve Dependencies
If the entry has a `requires` field:
- For each typed reference (`skill:name`, `agent:name`, `prompt:name`):
  - Look it up in `library.yaml`
  - If found, recursively run the `use` workflow for that dependency first
  - If not found, warn the user: "Dependency <ref> not found in library catalog"
- Process all dependencies before the requested item

### 5. Determine Target Directory

#### 5a. Detect the Target Tool

Determine which tool(s) to install into using the following priority order:

**Priority 1 — Explicit user instruction (highest priority):**
| User says | Target |
|-----------|--------|
| "for claude" / "claude only" / "in claude" | Claude Code only |
| "for codex" / "codex only" / "in codex" | Codex only |
| "for both" / "both tools" | Both tools |

**Priority 2 — Marker-file detection (check in cwd):**
```bash
# Check which tool directories are present
[ -d ".claude" ] && echo "found: .claude/"
[ -d ".agents" ] && echo "found: .agents/"
[ -d ".codex" ] && echo "found: .codex/"
[ -f "$HOME/.codex/config.toml" ] && echo "found: ~/.codex/config.toml"
```

Detection rules (in order):
1. Both `.claude/` AND (`.agents/` or `.codex/`) present → **dual-install** (both tools); warn on skill name collisions
2. Only `.claude/` present → **Claude Code** target
3. Only `.agents/` or `.codex/` present → **Codex** target
4. Neither present → **prompt user**: "This doesn't appear to be a Claude Code or Codex project. Install for Claude Code (creates `.claude/skills/`), Codex (creates `.agents/skills/`), or both?" Default suggestion: **Claude Code only**.

**Priority 3 — Fall back:**
- If detection is ambiguous, ask the user. Default answer is "Claude Code only".

#### 5b. Select the Target Path

Read `default_dirs` from `library.yaml`. Select the correct section based on type (skills/agents/prompts), then pick the path key based on target tool and scope:

| Target tool | Scope | Key to use |
|-------------|-------|------------|
| Claude Code | local (default) | `default` |
| Claude Code | global | `global` |
| Codex | local (default) | `default_codex` |
| Codex | global | `global_codex` |

> **Note:** `default_codex` and `global_codex` keys currently exist only under `default_dirs.skills` in `library.yaml`. For `agents` and `prompts`, no Codex path keys are defined — install to the Claude Code path only for those types (treat them as Claude-only until `library.yaml` is extended with Codex paths).

> **YAML structure note:** `default_dirs.<type>` is a **list of single-key maps**, not a flat map. To look up a key, iterate the list and find the entry whose key matches the desired name. For example, to resolve `default` under `skills`: iterate `default_dirs.skills`, find the map `{ default: .claude/skills/ }`, and use its value.

Scope rules:
- If user said "global" or "globally" → use global paths for the selected target
- If user specified a custom path → use that path directly
- Otherwise → use the local (default) paths

**Example for skills with dual-install** (resolve paths as described above):
- `<claude_path>`: value resolved by finding the `default` entry under `default_dirs.skills` (e.g. `.claude/skills/`)
- `<codex_path>`: value resolved by finding the `default_codex` entry under `default_dirs.skills` (e.g. `.agents/skills/`)

#### 5c. Dual-Install Symlink Strategy

> **Note:** Dual-install via symlink applies to **skills only**. For agents and prompts, `default_codex`/`global_codex` path keys are not yet defined in `library.yaml` — install to the Claude Code path only for those types.

When installing skills to **both** tools simultaneously:
1. Install to the Claude Code path first using Step 6, then create the symlink below (Step 6 must complete before the symlink can be created)
2. Create a symlink from the Codex path pointing to the Claude Code installation (using paths resolved in 5b):
   ```bash
   # After installing to Claude Code path:
   # <claude_path> and <codex_path> are the base dirs resolved in 5b
   claude_target="<claude_path><name>"
   codex_target="<codex_path><name>"
   mkdir -p "$(dirname "$codex_target")"
   # Remove existing target if it's a real directory (not already a symlink);
   # ln -sfn would nest inside a real dir rather than replacing it.
   if [ -d "$codex_target" ] && [ ! -L "$codex_target" ]; then
     rm -rf "$codex_target"
   fi
   ln -sfn "$(realpath "$claude_target")" "$codex_target"
   ```
   Codex officially follows symlinked skill directories, so this avoids maintaining two separate copies. The `ln -sfn` flag force-replaces any existing symlink at `$codex_target`. The explicit `rm -rf` guard above handles the case where a previous install left a real (non-symlink) directory there — without it, `ln -sfn` would create a nested symlink inside that directory instead of replacing it.

#### 5d. Translation Warnings

> **Only perform this check if `target_tool` includes Codex** (i.e. `target_tool = codex` or `target_tool = both`). Skip this section entirely for Claude-only installs.

After determining the target, inspect the skill's frontmatter for fields that do not translate cleanly to Codex. Emit the relevant warnings **before** proceeding with installation:

**Warning 1 — `tools:` frontmatter (Claude Code tool scoping):**
If the skill's SKILL.md contains a `tools:` key in its frontmatter:
> "Note: This skill uses `tools:` frontmatter to scope which Claude Code tools it can call. There is no direct Codex equivalent — Codex applies `sandbox_mode` and `mcp_servers` globally, not per-skill. The `tools:` restriction will be lost when installing to Codex."

**Warning 2 — `model:` frontmatter:**
If the skill's SKILL.md contains a `model:` key in its frontmatter, emit this warning:

> "Note: This skill specifies a model (`<model-value>`). To preserve this in Codex, a sibling config file is needed."

Offer to create the config file (ask the user):

> "Should I create the Codex model config file for this skill?"

What will be created:
```yaml
# File: <codex_path><name>/agents/openai.yaml
model: "<model-value>"
```

If the user confirms, create the file at `<resolved-codex-path>/<name>/agents/openai.yaml` with the `model:` value from the frontmatter. (Use the `<codex_path>` resolved in Step 5b.)

**Advisory 3 — `$ARGUMENTS` substitution:**
If the skill's SKILL.md body contains `$ARGUMENTS`:
> "Advisory: This skill uses `$ARGUMENTS` substitution (Claude Code invocation style). Codex skills receive input via prompt context rather than `$ARGUMENTS` substitution. The skill should still work, but `$ARGUMENTS` will not be replaced — the literal string will appear in the prompt. Consider adapting the skill for Codex if precise argument handling is needed."

### 6. Fetch from Source

> If `target_tool = both` (dual-install), run this step once targeting the Claude Code path (`<claude_path>`). After this step completes, create the symlink as described in Step 5c to complete the Codex-side installation.

**If source is a local path** (starts with `/` or `~`):
- Resolve `~` to the home directory
- Get the parent directory of the referenced file
- For skills: copy the entire parent directory to the target:
  ```bash
  cp -R <parent_directory>/ <target_directory>/<name>/
  ```
- For agents: copy just the agent file to the target:
  ```bash
  cp <agent_file> <target_directory>/<agent_name>.md
  ```
- For prompts: copy just the prompt file to the target:
  ```bash
  cp <prompt_file> <target_directory>/<prompt_name>.md
  ```
- If the agent or prompt is nested in a subdirectory under the `agents/` or `commands/` directories, copy the subdirectory to the target as well, creating the subdir if it doesn't exist. This is useful because it keeps the agents or commands grouped together.

**If source is a GitHub URL**:
- Parse the URL to extract: `org`, `repo`, `branch`, `file_path`
  - Browser URL pattern: `https://github.com/<org>/<repo>/blob/<branch>/<path>`
  - Raw URL pattern: `https://raw.githubusercontent.com/<org>/<repo>/<branch>/<path>`
- Determine the clone URL: `https://github.com/<org>/<repo>.git`
- Determine the parent directory path within the repo (everything before the filename)
- Clone into a temporary directory:
  ```bash
  tmp_dir=$(mktemp -d)
  git clone --depth 1 --branch <branch> https://github.com/<org>/<repo>.git "$tmp_dir"
  ```
- Copy the parent directory of the file to the target:
  ```bash
  cp -R "$tmp_dir/<parent_path>/" <target_directory>/<name>/
  ```
- Clean up:
  ```bash
  rm -rf "$tmp_dir"
  ```

**If clone fails (private repo)**, try SSH:
  ```bash
  git clone --depth 1 --branch <branch> git@github.com:<org>/<repo>.git "$tmp_dir"
  ```

### 7. Verify Installation
- Confirm the target directory exists
- Confirm the main file (SKILL.md, AGENT.md, or prompt file) exists in it
- Report success with the installed path

### 8. Confirm
Tell the user:
- What was installed and where
- Any dependencies that were also installed
- If this was a refresh (overwrite), mention that
