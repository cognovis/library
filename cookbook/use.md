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
- Search across `library.skills`, `library.agents`, `library.prompts`, and top-level `guardrails:`
- Match by name (exact) or description (fuzzy/keyword match)
- If multiple matches, show them and ask the user to pick one
- If no match, tell the user and suggest `/library search`

### 2b. Branch on Entry Kind

Some entries are not skills/agents/prompts but installed via dedicated
scripts. The Step 3–8 catalog workflow does not apply to them.

**(i) hook-manifest guardrails** (e.g. `open-brain-hooks`, per ADR-0004 Decision 8):

If the entry comes from `guardrails:` AND has `kind: hooks-manifest`:
1. **Skip Steps 3–8 entirely.** They do not apply (no SKILL.md to copy, no
   skills-dir target, no symlinks).
2. Shell out to the installer:
   ```bash
   python3 <LIBRARY_SKILL_DIR>/scripts/install-hook.py <entry-name>
   ```
   The installer handles fetch + cache + settings.json merge atomically
   and is idempotent.
3. Confirm the user: "<n> hook(s) across <m> event(s) installed to
   `~/.claude/settings.json`. Use `python3 .../scripts/install-hook.py
   <entry-name> --remove` to uninstall."
4. Skip directly to Step 9 (Confirm).

**(ii) MCP servers** (`mcp_servers:` section, per CL-l0c Deliverable D):

If the entry comes from the top-level `mcp_servers:` list:
1. **Skip Steps 3–8 entirely.** MCP servers have no SKILL.md and no
   skills-dir; the per-harness snippet under `install.mcp.<harness>` is
   what gets merged into each harness's MCP config file.
2. Shell out to the installer:
   ```bash
   python3 <LIBRARY_SKILL_DIR>/scripts/install-mcp.py <entry-name>
   #   --harness claude_code|codex|opencode|claude_ai|claude_ios|all   (default: all)
   #   --dry-run     (preview only, no writes)
   #   --remove      (uninstall library-managed entries by _origin tag)
   ```
   The installer writes the snippet into the harness's config file:
   - `claude_code` → `~/.claude/settings.json` under `mcpServers.<name>`
   - `codex` → `~/.codex/config.toml` under `[mcp_servers.<name>]`
   - `opencode` → `~/.config/opencode/opencode.json` under `mcp.<name>`
   - `claude_ai` / `claude_ios` → emit the manual install URL (no
     programmatic install; user must open the URL in the app)

   Every library-managed entry is tagged with `_origin = "library:mcp:<name>"`
   so re-runs are idempotent (refresh in place, no duplicates) and
   `--remove` drops only what the library installed (leaves manual entries
   alone).
3. Confirm the user: "MCP server `<entry-name>` registered with
   `<n>` harness(es). Use `python3 .../scripts/install-mcp.py <entry-name> --remove`
   to uninstall."
4. Skip directly to Step 9 (Confirm).

For all other entries (skills, agents, prompts, single-hook guardrails),
continue with Step 3.

### 3. Resolve Marketplace Reference

#### 3a. Handle `sources:` map (per-harness file paths)

If the entry has a `sources:` map instead of (or in addition to) a singular `source:`,
resolve files per harness:

```yaml
# Example: agent with both Claude and Codex files
sources:
  claude: https://github.com/cognovis/library-core/blob/main/agents/bead-orchestrator.md
  codex: https://github.com/cognovis/library-core/blob/main/.codex/agents/bead-orchestrator.toml
```

- **`sources.claude`**: Install the `.md` file to the Claude agents directory
  (e.g. `~/.claude/agents/<name>.md` for global install).
- **`sources.codex`**: Install the `.toml` file to the Codex agents directory
  (e.g. `~/.codex/agents/<name>.toml` for global install).
- **Codex coverage gap**: If the entry has `sources.claude` but no `sources.codex`
  (or a singular `source:` pointing to a `.md` file only), emit:
  > "Codex coverage gap: agent `<name>` has no Codex `.toml` sibling.
  > Claude install complete. To add Codex coverage: author a `.toml` file
  > and add it to `library.yaml` under `sources.codex:`."
  Do NOT auto-convert `.md` to `.toml` — they have different runtime semantics.
- Fetch each file in `sources:` separately using the normal GitHub clone flow.

If the entry has a singular `source:` field, skip step 3a and continue.

#### 3b. (Original Step 3) Marketplace Reference

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
- For each typed reference (`skill:name`, `agent:name`, `prompt:name`, `standard:name`):
  - Look it up in `library.yaml`
  - If found, recursively run the `use` workflow for that dependency first
  - If not found, warn the user: "Dependency <ref> not found in library catalog"
- Process all dependencies before the requested item

### 5. Determine Target Directory

#### 5a. Determine harness coverage (NOT a user choice for cross-platform primitives)

**Foundational principle**: The library is **cross-platform by construction**.
Which harnesses a primitive installs to is determined by **what file format the
primitive ships in**, not by user preference.

| Primitive's source file | Reaches which harnesses |
|-------------------------|--------------------------|
| `SKILL.md` (agentskills.io standard) | **Claude Code AND Codex CLI** (and any future harness that loads SKILL.md). This is the dominant case. Never harness-restricted. |
| Agent file `.md` (YAML frontmatter) | Claude Code (native). Codex needs `.toml`. If both ship as siblings → both harnesses. |
| Agent file `.toml` | Codex (native). Claude needs `.md`. If both ship → both. |
| Slash-command `.md` (no SKILL.md format) | Claude Code today. Codex equivalents TBD. |
| Hook script + per-harness adapter | Whichever harnesses the entry's `capability:` map declares. |
| MCP server | All harnesses listed under `mcp_servers.<name>.install.mcp.*` in library.yaml. |

**For SKILL.md specifically: it is a violation to mark it `harness: claude`
or `harness: codex`.** The format is harness-neutral by agentskills.io
specification (see ADR-0003 Decision 1). Any registry entry pointing at
a SKILL.md must use `harness: both` (or omit the field — `both` is the
default for skills).

**Decision sequence:**

**1 — Derive coverage from `source:` URL** (primary, authoritative):

| URL pattern | Coverage |
|-------------|----------|
| `.../SKILL.md` | `{claude, codex}` — agentskills.io universal |
| `.../agents/<X>.md` | `{claude}` natively. **Convert to `.toml` and also install to Codex** via `scripts/convert-agent.py` (if available); otherwise emit Codex-coverage gap warning |
| `.../agents/<X>.toml` | `{codex}` natively. **Convert to `.md` and also install to Claude** via converter |
| `.../prompts/<X>.md` or `.../commands/<X>.md` | `{claude}` today; `{codex}` once Codex slash-command adapter lands |
| Hook manifest (`kind: hooks-manifest`, handled separately in Step 2b) | per `capability:` map |
| MCP entry (`mcp_servers:` section) | per `install.mcp.*` map |

**2 — Legacy `harness:` field (transitional, deprecated for skills):**
If an entry still carries `harness:` (legacy from pre-ADR-0004 era), respect it
as a hard override only when it NARROWS the URL-derived set (you can't widen).
The field is being phased out — new entries should not set it; resolver should
prefer URL derivation.

**2 — Detect deployment scope (global vs. project-local).** This IS a user
question, but framed by scope not harness:
- Default: **global** install. Most library primitives are useful cross-project.
- Switch to **project-local** if: the user says "in this project" / "local",
  OR the entry's `tags:` include `tier:project` (e.g. FHIR-only tools).

**3 — Install to ALL harnesses in the coverage set.** No partial installs by
default. For `SKILL.md` skills this means: write the real files to the
canonical `.agents/skills/<name>/` location AND create the Claude harness
bridge symlink at `.claude/skills/<name>`. Codex reads `.agents/skills/`
natively (CL-603 r1 root) — no separate Codex install path is needed.

**The only legitimate user prompt** is global-vs-local scope when the request
is ambiguous. Example:

> "Install ob-search globally (cross-project, recommended) or only in this
> project's `.claude/skills/`?"

**Never** generate prompts that look like:
- ❌ "Install for Claude Code only or both tools?" (for a SKILL.md)
- ❌ "Which harness do you want?" (when the primitive declares `both`)

Those are architectural violations of cross-platform-by-default.

#### 5b. Select the Target Path

Read `default_dirs` from `library.yaml`. For **skills**, the layout is
canonical+bridge: real files at the canonical `.agents/skills/` path, with
a Claude harness bridge symlink at `.claude/skills/`. Codex reads `.agents/`
natively — no separate Codex install path.

| Role | Scope | Key in `default_dirs.skills` |
|------|-------|------------------------------|
| Canonical (real files / Layer-B symlink) | project-local | `default` (resolves to `.agents/skills/`) |
| Canonical | user-global | `global` (resolves to `~/.agents/skills/`) |
| Claude harness bridge (symlink) | project-local | `claude_bridge` (resolves to `.claude/skills/`) |
| Claude harness bridge | user-global | `global_claude_bridge` (resolves to `~/.claude/skills/`) |

> **Note (agents/prompts):** `default_dirs.agents` and `default_dirs.prompts`
> have only `default` / `global` keys. Agents and prompts ship as
> harness-specific file formats (`.md` for Claude, `.toml` for Codex), so
> they install to the Claude path natively. Codex equivalents are handled
> by `scripts/convert-agent.py` separately, not via the bridge symlink
> mechanism.

> **YAML structure note:** `default_dirs.<type>` is a **list of single-key
> maps**, not a flat map. To look up a key, iterate the list and find the
> entry whose key matches the desired name. For example, to resolve `default`
> under `skills`: iterate `default_dirs.skills`, find the map
> `{ default: .agents/skills/ }`, and use its value.

Scope rules:
- If user said "global" or "globally" → use the global keys
- If user specified a custom path → use that path directly
- Otherwise → use the project-local (default) keys

**Resolved paths for a skill install** (using Step 5b lookup):
- `<canonical_path>`: from `default` (or `global`) — e.g. `.agents/skills/`
- `<claude_bridge_path>`: from `claude_bridge` (or `global_claude_bridge`) — e.g. `.claude/skills/`

#### 5c. Canonical install + Claude bridge symlink

> **Note:** This dual-link strategy applies to **skills only**. Agents and
> prompts ship as harness-specific file formats; see Step 5b.

Skills are installed in two steps: first the canonical files (which are
themselves a symlink into the Layer-B cache per ADR-0003 and Step 8c), then
a Claude harness bridge symlink pointing to the canonical path. Codex reads
`.agents/skills/` natively, so no Codex-side symlink is needed.

```bash
# <canonical_path> and <claude_bridge_path> are the base dirs resolved in 5b.
canonical_target="<canonical_path><name>"          # e.g. .agents/skills/dolt
claude_bridge_target="<claude_bridge_path><name>"  # e.g. .claude/skills/dolt

# Step A: canonical install (per Step 6 + Step 8c — writes the Layer-B cache
# and points <canonical_target> at it via a symlink).
mkdir -p "$(dirname "$canonical_target")"
# ... (Step 6 / Step 8c materializes <canonical_target> -> cache_path)

# Step B: Claude harness bridge. Points at the canonical path so Claude Code
# resolves through it transparently.
mkdir -p "$(dirname "$claude_bridge_target")"
# Replace a stale real directory if one exists (e.g. legacy install). The
# `block-destructive-bash` guardrail refuses recursive forced deletes, so we
# use `rm -r` without `-f`; this is safe because the agent owns the path.
if [ -d "$claude_bridge_target" ] && [ ! -L "$claude_bridge_target" ]; then
  rm -r "$claude_bridge_target"
fi
ln -sfn "$(realpath "$canonical_target")" "$claude_bridge_target"
```

The resolution chain is `.claude/skills/<name>` → `.agents/skills/<name>` →
Layer-B cache (`~/.local/share/library/skills/<m>/<n>@<tree-sha>/`). Claude
Code follows the chain; Codex reads `.agents/skills/<name>` directly. One
real copy, three resolution paths, zero drift.

#### 5d. Name Collision Check (MANDATORY for skill installs)

> **Policy reference**: `docs/policy/name-collision.md` (CL-b4o). Run this
> check whenever installing a skill. Use the **resolved paths from Step 5b** —
> do NOT hard-code `.agents/skills/` or `.claude/skills/`; the user may have
> specified global or custom paths.

Detect the current state of canonical and Claude-bridge paths before writing:

```bash
# Paths resolved in Step 5b.
canonical_path="<canonical_path><name>"          # e.g. .agents/skills/dolt
claude_bridge_path="<claude_bridge_path><name>"  # e.g. .claude/skills/dolt
codex_legacy_path="<codex_legacy_root>/<name>"   # e.g. ~/.codex/skills/dolt
                                                 # only for legacy detection;
                                                 # never an install target

canonical_real=false        # canonical exists as a real directory
canonical_is_link=false     # canonical exists as a symlink (e.g. into cache)
claude_bridge_real=false    # claude path exists as a real directory (BAD)
claude_is_bridge=false      # claude path exists as a symlink (GOOD)
codex_legacy_exists=false   # legacy .codex/skills/<name> present (must be removed)

[ -d "$canonical_path" ] && [ ! -L "$canonical_path" ] && canonical_real=true
[ -L "$canonical_path" ] && canonical_is_link=true
[ -d "$claude_bridge_path" ] && [ ! -L "$claude_bridge_path" ] && claude_bridge_real=true
[ -L "$claude_bridge_path" ] && claude_is_bridge=true
[ -e "$codex_legacy_path" ] && codex_legacy_exists=true
```

**Collision decision table** (rows are mutually exclusive):

| canonical | claude_bridge | legacy `.codex/` | Action |
|-----------|---------------|------------------|--------|
| neither real nor link | neither real nor link | absent | Fresh install — proceed to Step 6 |
| link (into cache) | is_bridge → canonical | absent | Already installed correctly — refresh canonical; bridge auto-updates |
| real (legacy real dir at canonical) | absent | absent | Promote: materialize into Layer-B cache, replace canonical with symlink |
| absent | real (legacy `.claude/` only) | absent | Legacy claude-canonical install — migrate content to canonical, replace `.claude/` with bridge |
| real | real | (any) | **COLLISION** — two independent real copies; emit warning, prompt user |
| any | any | present | Legacy Codex bridge exists — warn and offer to remove (Codex reads `.agents/` natively) |

**Collision warning** (for the dual-real-directory case):

```
Warning: Name collision detected for skill '<name>':
  .agents/skills/<name>/ exists (real directory)
  .claude/skills/<name>/  exists (real directory, NOT a symlink)

These are two independent copies that may have diverged.
Policy: .agents/skills/<name>/ is canonical (real or symlink into Layer-B cache).
        .claude/skills/<name>  is the Claude harness bridge symlink.

Options:
  1. Use .agents/ copy as canonical, replace .claude/ with bridge symlink
     (recommended if .agents/ is newer or content matches)
  2. Use .claude/ copy as canonical, move into .agents/ and bridge from .claude/
     (use if .claude/ is the newer/correct copy)
  3. Keep both as separate files (not recommended — manual maintenance)
  4. Cancel and inspect manually

Default: option 1.
```

If user selects option 1 or 2: after Step 6 materializes the canonical
location, replace the other side with a bridge symlink (Step 5c).

If user selects option 3: install proceeds, both real directories remain;
warn that drift is the user's responsibility.

**Legacy `.codex/skills/<name>` handling**: If detected, prompt the user:

```
Notice: ~/.codex/skills/<name> exists from a legacy install.
Codex 0.130.0+ reads ~/.agents/skills/ natively (CL-603 r1), so this path is
no longer needed.

Remove ~/.codex/skills/<name>? [Y/n]
```

Default yes. Removing eliminates a stale entry that could shadow the new
canonical install if Codex's r0 root (`~/.codex/skills/`) is searched first.

#### 5e. Translation Warnings

> Skills install canonically to `.agents/skills/`, which Codex reads
> natively. Run these checks for every skill install — they surface skill
> features that may behave differently under Codex even though both harnesses
> see the same SKILL.md file.

After determining the target, inspect the skill's frontmatter for fields that
do not translate cleanly to Codex. Emit the relevant warnings **before**
proceeding with installation:

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
# File: <canonical_path><name>/agents/openai.yaml
# (Codex reads .agents/skills/ natively; the sibling config lives in the
# canonical install location, NOT in a separate .codex/ path.)
model: "<model-value>"
```

If the user confirms, create the file at `<canonical_path><name>/agents/openai.yaml`
with the `model:` value from the frontmatter. (Use the `<canonical_path>` resolved in Step 5b.)

**Advisory 3 — `$ARGUMENTS` substitution:**
If the skill's SKILL.md body contains `$ARGUMENTS`:
> "Advisory: This skill uses `$ARGUMENTS` substitution (Claude Code invocation style). Codex skills receive input via prompt context rather than `$ARGUMENTS` substitution. The skill should still work, but `$ARGUMENTS` will not be replaced — the literal string will appear in the prompt. Consider adapting the skill for Codex if precise argument handling is needed."

### 5f. Standards: ALWAYS ask whether global or project-local

`library.standards:` entries (single files and bundles) can install at two tiers:

| Tier | Path | When to choose |
|------|------|----------------|
| **Global** | `~/.agents/standards/<name>/` | Standard applies broadly; triggers will filter dynamically. Default suggestion. |
| **Project-local** | `<cwd>/.agents/standards/<name>/` | Standard is project-specific, or you want to override a global version for this project only. |

**When `/library use <name>` for a standard runs, ASK the user before installing.**
Do not silently default. Phrase the question so the user can pick at a glance:

> "Install `python` standard globally (`~/.agents/standards/`, available in every
> project) or project-local (`<cwd>/.agents/standards/`)? Global is the usual
> answer — triggers filter dynamically."

Skip the question only when the invocation explicitly states scope:
- `/library use python globally` → global, no prompt
- `/library use python locally` / `... for this project` / `... in this project` → project-local, no prompt

The loader resolution order is the same in both directions (standards-loader and
inject-subagent-standards): project-local wins over user-global. So a
project-local install always overrides a global one when both exist.

```yaml
default_dirs:
  standards:
    - default: .agents/standards/         # project-local
    - global: ~/.agents/standards/        # user-global
```

### 6. Fetch from Source

> For skills: this step fetches the source content into a temp directory.
> The actual placement happens in Step 8c (Layer-B cache materialization),
> and the canonical `<canonical_path><name>` symlink plus Claude bridge are
> created from there. Do NOT cp directly to `<canonical_path>` — that
> bypasses the Layer-B cache and breaks `/library sync` tree-SHA short-circuit.

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
- Clean up (use `rm -r` without `-f` — `mktemp -d` directories are owned by the
  agent, no force needed; this also satisfies the `block-destructive-bash`
  guardrail which refuses any recursive forced delete):
  ```bash
  rm -r "$tmp_dir"
  ```

**If clone fails (private repo)**, try SSH:
  ```bash
  git clone --depth 1 --branch <branch> git@github.com:<org>/<repo>.git "$tmp_dir"
  ```

### 6.5: Compose Agent Body (compose-on-install)

> **Applies to agent entries only.** Skills, prompts, and guardrails are not composed.

If the installed entry is an `agent` AND the fetched file's YAML frontmatter contains
`golden_prompt_extends:` AND the value is NOT `from-scratch`:

1. Locate `scripts/compose-agent.py` in the library root (same directory as `library.yaml`).

2. Run the composer for the target harness:
   ```bash
   # For Claude Code (default):
   python3 <LIBRARY_ROOT>/scripts/compose-agent.py <fetched-agent-file>

   # For Codex:
   python3 <LIBRARY_ROOT>/scripts/compose-agent.py <fetched-agent-file> --harness=codex
   ```

3. **On success** (exit code 0): replace the body of the fetched agent file (everything
   after the closing `---` of the frontmatter) with the composed output.

4. **On failure** (non-zero exit — missing Layer 1 or Layer 3):
   - Warn the user: "Compose failed: <error>. Installing uncomposed agent body.
     Run `/library sync` after installing the required base/model-standard."
   - Continue with the original fetched body (graceful degradation). Do NOT abort
     the install — an uncomposed agent still works with the harness system prompt.

5. **For Codex agents** (`.toml` format): write the composed body into the
   `developer_instructions` field in the TOML file.

6. Continue with Step 7 (Verify Installation).

> **Idempotency**: The composer is deterministic given the same input files.
> Re-running install produces the same composed body. If a Layer 1 (`cognovis-base`)
> or Layer 3 (model-standard) source file changes, the tree-SHA in the lockfile
> changes and `/library sync` re-composes automatically.

> **Layer resolution search order** for `compose-agent.py`:
> 1. `<proj_root>/.agents/golden-prompts/<name>.md` (project-local)
> 2. `~/.agents/golden-prompts/<name>.md` (user-global)
>
> Install the required layers first: `/library use cognovis-base` and
> `/library use claude-haiku-4-5` (or whichever model-standard the agent declares).

### 7. Verify Installation
- Confirm the target directory exists
- Confirm the main file (SKILL.md, AGENT.md, or prompt file) exists in it
- Report success with the installed path

### 8. Update .library.lock

After a successful install (Step 7 confirms the primary artifact exists), write or update the
lockfile entry in `.library.lock` at the project root.

#### 8a. Compute the checksum of the primary artifact

Determine the primary artifact path based on type:

| `type` | Primary artifact |
|--------|-----------------|
| `skill` | `<install_target>/SKILL.md` |
| `agent` | `<install_target>/<name>.md` |
| `prompt` | `<install_target>/<name>.md` |

```bash
# macOS
checksum=$(shasum -a 256 "<primary_artifact_path>" | awk '{print $1}')

# Linux
checksum=$(sha256sum "<primary_artifact_path>" | awk '{print $1}')
```

#### 8b. Resolve the source commit (content-addressable tree hash)

> **NORMATIVE**: `source_commit` is the **git tree-object SHA** of the skill's
> sub-path within the marketplace repo — NOT the marketplace repo's HEAD commit.
> Tree-SHAs are content-addressable: if the skill's files don't change, the SHA
> doesn't change, even across hundreds of unrelated marketplace commits. This
> keeps the Layer-B cache stable and lets `/library sync` short-circuit when
> there's nothing new.
>
> **Rationale**: An earlier draft of this spec used `git rev-parse HEAD`, which
> tied the cache key to the marketplace's HEAD. Result: every unrelated commit
> to `library.yaml` or to a sibling skill produced a new cache directory for
> every skill — cache bloat with zero content change. Tree-hash fixes this.

> **IMPORTANT — timing**: For GitHub sources, both SHAs must be resolved from
> `$tmp_dir` BEFORE the `rm -r "$tmp_dir"` cleanup in Step 6. Capture them
> immediately after the copy, before cleanup.

For a **GitHub source** (resolve while `$tmp_dir` still exists, before cleanup):
```bash
# <skill_subpath> is the path inside the marketplace repo, e.g. "skills/dolt"
# or "skills/agent-forge" — derived from the URL parsing in Step 6.
#
# Tree-SHA: content-addressable identifier of the sub-tree (PRIMARY — cache key).
source_commit=$(git -C "$tmp_dir" rev-parse "HEAD:${skill_subpath}")

# Repo HEAD: provenance ("which marketplace commit did this install observe?").
# Stored alongside source_commit but NOT used as the cache key.
source_repo_commit=$(git -C "$tmp_dir" rev-parse HEAD)

rm -r "$tmp_dir"   # cleanup happens AFTER both captures
```

For a **local path source** (copied via `cp`, source is inside a git repo):
```bash
# Same approach when the source has a git ancestor — tree-hash the sub-path.
source_commit=$(git -C "${source_root}" rev-parse "HEAD:${skill_subpath}" 2>/dev/null || echo "")
source_repo_commit=$(git -C "${source_root}" rev-parse HEAD 2>/dev/null || echo "")
```

For a **local path source with NO git ancestor** (loose files on disk):
```bash
# Content-hash fallback: deterministic SHA over the file tree.
# Hashes file names + contents in sorted order so reordering can't perturb it.
source_commit="local-$(
  cd "${source_root}/${skill_subpath}" && \
  find . -type f \! -name '.DS_Store' -print0 | \
  sort -z | \
  xargs -0 shasum -a 256 | \
  shasum -a 256 | \
  awk '{print substr($1, 1, 14)}'
)"
source_repo_commit=""   # no provenance available
```

**Stability properties (NORMATIVE — implementations MUST preserve these):**

| Change | Does `source_commit` change? |
|--------|------------------------------|
| Marketplace HEAD advances, skill files unchanged | **No** — tree-SHA is stable |
| Skill file edited (any byte) | Yes — tree-SHA changes |
| Skill file renamed | Yes — tree-SHA changes |
| Sibling skill in same marketplace edited | **No** — only that sibling's tree-SHA changes |
| `library.yaml` edited | **No** — top-level repo change, this skill's sub-tree unchanged |

**Sync short-circuit (used by `/library sync`):**

```bash
# Re-fetch latest source, recompute tree-SHA, compare against lockfile.
new_tree=$(git -C "$tmp_dir" rev-parse "HEAD:${skill_subpath}")
locked_tree=$(yq '.installed[] | select(.name=="<name>") | .source_commit' .library.lock)
if [[ "$new_tree" == "$locked_tree" ]]; then
  # No content change — update install_timestamp + source_repo_commit only.
  # Do NOT re-materialize the cache; do NOT touch symlinks.
  exit 0
fi
# Otherwise: materialize new cache at <name>@${new_tree:0:14}/ and re-point symlinks.
```

**Migration of existing lockfile entries**: Entries written before this spec
revision used `git rev-parse HEAD` (marketplace HEAD) as `source_commit`. They
look like valid 40-char hex but are NOT tree-SHAs. On next `/library sync`:
recompute the tree-SHA, compare; if they differ (they almost always will, since
HEAD ≠ tree-SHA in general), rewrite the lockfile entry with the new tree-SHA
and materialize the canonical cache location. No content change is implied —
this is a one-time key correction.

#### 8c. Materialize the cache entry (Layer B) and create symlinks (Layer C)

Per ADR-0003, the fetched content lives in the Layer-B cache. The canonical
harness path (Layer C) is a symlink into that cache, and the Claude bridge
is a symlink to the canonical path.

Determine the `cache_path` using the tree-SHA from Step 8b:

```
~/.local/share/library/skills/<marketplace>/<name>@<source_commit_short>/
```

Where `<source_commit_short>` is the first 14 hex characters of `source_commit`
(tree-SHA from Step 8b) or `local-<14hex>` for local-path sources with no git
ancestor. Derive `<marketplace>` from the URL using `library.yaml.marketplaces`.

**Step 8c.1 — materialize cache (idempotent: skip if path already exists):**

```bash
cache_base="${HOME}/.local/share/library/skills"
cache_path="${cache_base}/<marketplace>/<name>@${source_commit:0:14}/"

if [ ! -d "$cache_path" ]; then
  mkdir -p "$(dirname "$cache_path")"
  cp -R "<fetched_source_dir>/" "$cache_path"
fi
# If $cache_path already exists, tree-SHA guarantees content is identical —
# no re-copy needed (this is the /library sync short-circuit from Step 8b).
```

**Step 8c.2 — point canonical (Layer C) at cache (Layer B):**

```bash
canonical_target="<canonical_path><name>"   # e.g. ~/.agents/skills/dolt
mkdir -p "$(dirname "$canonical_target")"

# Replace stale canonical (legacy real dir or wrong-version symlink).
if [ -d "$canonical_target" ] && [ ! -L "$canonical_target" ]; then
  rm -r "$canonical_target"
fi
ln -sfn "$cache_path" "$canonical_target"
```

**Step 8c.3 — Claude harness bridge → canonical (Step 5c):**

After 8c.1 + 8c.2, run the bridge command from Step 5c so Claude Code can
resolve `<claude_bridge_path><name>` through the canonical path into the
cache.

> **Note**: If `cache_path` materialization is not yet implemented by the
> tool (legacy lockfile entries from before this spec revision), set
> `cache_path: ""` in the lockfile entry. The next `/library sync` will
> recompute the tree-SHA, populate `cache_path`, and re-point the symlinks.

#### 8d. Build the lockfile entry

```yaml
- name: <name>
  type: <type>          # skill | agent | prompt | guardrail
  marketplace: <marketplace>  # from library.yaml.marketplaces[].name, or "local" / "unknown"
  source: <source>      # the URL or path from Step 2 / 3
  source_commit: <sha>  # from 8b, or "local"
  cache_path: <cache_path>  # from 8c; empty string if not yet materialized
  install_target: <install_target>/  # trailing slash required; from Step 5b
  install_timestamp: <ISO 8601 UTC>  # e.g. 2026-04-30T10:23:00Z
  checksum_sha256: <checksum>
  license: <license>    # from SKILL.md/agent frontmatter, or "unknown"
  bridge_symlinks:      # from Step 5c; empty list if no bridge was created
    - "<link-path> -> <target-path>"
```

#### 8e. Write/update the lockfile

Read `.library.lock` (create with `installed: []` if it does not exist). Find the existing
entry by `name` and replace it in place; or append if not found. Write back to `.library.lock`.

```python
import yaml, os
from datetime import datetime, timezone

lock_path = '.library.lock'
if os.path.exists(lock_path):
    with open(lock_path) as f:
        lock = yaml.safe_load(f) or {}
else:
    lock = {}
lock.setdefault('installed', [])

entry = {
    'name': '<name>',
    'type': '<type>',
    'marketplace': '<marketplace>',   # from library.yaml.marketplaces[].name
    'source': '<source>',
    'source_commit': '<source_commit>',
    'cache_path': '<cache_path>',     # from 8c; empty string if not materialized
    'install_target': '<install_target>/',
    'install_timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'checksum_sha256': '<checksum>',
    'license': '<license>',
    'bridge_symlinks': ['<link> -> <target>'],  # or [] if no bridge
}

# Replace existing or append
lock['installed'] = [e for e in lock['installed'] if e.get('name') != entry['name']]
lock['installed'].append(entry)

with open(lock_path, 'w') as f:
    yaml.dump(lock, f, default_flow_style=False, allow_unicode=True)
```

See `docs/lockfile-format.md` for the full field reference and `docs/schema/lockfile.schema.json`
for machine-readable validation.

### 9. Confirm
Tell the user:
- What was installed and where
- Any dependencies that were also installed
- If this was a refresh (overwrite), mention that
- Confirm that `.library.lock` was updated


---

## Codex Slash-Commands: Coverage Gap Documentation

> **Spike date:** 2026-05-12 | **Codex CLI version:** 0.130.0 | **Bead:** CL-l0c (Deliverable C)

### Is slash-command install to Codex supported?

**Short answer: Not via the same mechanism as Claude Code.**

| Feature | Claude Code | Codex CLI 0.130.0 |
|---------|-------------|-------------------|
| User-defined slash commands | `~/.claude/commands/<name>.md` (YAML frontmatter) | Not directly supported via `.md` files |
| User-defined "commands" equivalent | -- | **Skills** (`~/.codex/skills/<name>/SKILL.md`) |
| Built-in slash commands | `/beads`, `/library`, `/dispatch`, ... | `/model`, `/review`, `/plan`, `/skills`, ... |
| Custom prompt format | Single `.md` file, YAML frontmatter, `$ARGUMENTS` | Deprecated: `~/.codex/prompts/<name>.md` |

### Resolution path

- **For SKILL.md-based primitives:** The library already handles cross-harness install via
  the dual-install symlink mechanism (Step 5c). Skills work in both harnesses today.
- **For slash-commands (.md in commands/):** These are Claude-Code-only today. Library
  entries pointing to `commands/*.md` files should have `harness: claude` until Codex
  adds native slash-command support.
- **For agents with Codex `.toml` siblings:** Use the `sources:` map pattern
  (see Step 3a). This is the ship-both-files pattern implemented in CL-l0c.

### Follow-up recommendation

If Codex CLI adds a dedicated slash-command mechanism in a future version, a follow-up
bead should:
1. Research the format (likely `~/.codex/commands/` or inline in `config.toml`).
2. Add `sources.codex_command:` key to the `prompt_entry` schema.
3. Update the resolver (Step 3a) to handle prompt entries with Codex sources.

Until then, prompt entries in `library.yaml` are **Claude-only** and should not claim
Codex coverage.
