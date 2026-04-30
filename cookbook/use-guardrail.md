# Install a Guardrail from the Library

## Context
Install a guardrail from the catalog into the current project (or globally). A guardrail
runs outside the LLM loop — once installed, the model cannot bypass it.

Guardrails are per-harness: the same logical guardrail compiles to different native
mechanisms per harness (Claude Code hooks, Codex CLI SessionStart hooks, OpenCode
permission rules, etc.). This cookbook handles the capability check and per-harness
installation.

## Input
The user provides: guardrail name, optional target harness(es), optional scope (local/global).

## Steps

### 1. Sync the Library Repo
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Find the Guardrail Entry
- Read `library.yaml` → `guardrails` list
- Match by `name` (exact) or `description` (fuzzy)
- If multiple matches, show them and ask the user to pick one
- If no match, tell the user and suggest `/library list` to see available guardrails

### 3. Detect Target Harness(es)

**Priority 1 — Explicit user instruction (highest priority):**
| User says | Target |
|-----------|--------|
| "for claude" / "claude only" | Claude Code only |
| "for codex" / "codex cli" | Codex CLI only |
| "for codex cloud" | Codex Cloud only |
| "for opencode" | OpenCode only |
| "for pi" | Pi only |
| "for all" / "everywhere" | All supported harnesses |

**Priority 2 — Marker-file detection (check in cwd):**
```bash
[ -d ".claude" ] && echo "found: .claude/ → claude_code"
[ -f "hooks.json" ] && echo "found: hooks.json → codex_cli"
[ -f "opencode.json" ] || [ -f ".config/opencode/opencode.json" ] && echo "found: opencode.json → opencode"
[ -d ".pi" ] && echo "found: .pi/ → pi"
```

**Priority 3 — Fall back:**
Ask the user. Default suggestion: Claude Code only.

### 4. Capability Check (MANDATORY — emit mismatch warnings)

For EACH target harness, check the guardrail's `capability` section:

```python
# Pseudocode for capability check
guardrail = library_yaml['guardrails'][matched_entry]
for harness in target_harnesses:
    if harness not in guardrail.get('capability', {}):
        # Harness completely unsupported
        print(f"""
Warning: Capability mismatch for guardrail '{guardrail['name']}' on harness '{harness}':
  Harness '{harness}' is not in this guardrail's capability map.
  This guardrail has NO implementation for {harness}.

  Options:
    1. Skip this harness (recommended)
    2. Cancel installation

  Default: option 1 (skip).
""")
        # Prompt user for choice; default to skip
        continue

    harness_cap = guardrail['capability'][harness]
    mismatch_warning = harness_cap.get('mismatch_warning', '')

    if mismatch_warning:
        # Harness supported but with reduced effectiveness
        print(f"""
Warning: Capability mismatch for guardrail '{guardrail['name']}' on harness '{harness}':
  {mismatch_warning}

  Options:
    1. Install anyway with reduced effectiveness
    2. Skip this harness
    3. Cancel

  Default: option 2 (skip).
""")
        # Prompt user for choice; default to skip
```

**Purpose-specific mismatch warnings** (emit these verbatim):

For `purpose: pre-tool-veto` on `codex_cli`:
```
Warning: Capability mismatch for guardrail '<name>' on harness 'codex_cli':
  Requested purpose: pre-tool-veto
  codex_cli does not support PreToolUse events (only: SessionStart, SessionEnd, Stop)
  
  This guardrail will install a SessionStart advisory hook instead.
  Effectiveness: advisory only — the model is warned but not hard-blocked.
  
  Options:
    1. Install anyway with SessionStart workaround (reduced effectiveness)
    2. Skip this harness
    3. Cancel

  Default: option 2 (skip).
```

For `purpose: pre-tool-veto` on `codex_cloud`:
```
Warning: Capability mismatch for guardrail '<name>' on harness 'codex_cloud':
  Requested purpose: pre-tool-veto
  codex_cloud has no per-tool-call hook mechanism.
  
  This guardrail will set approval_policy=all in config.toml instead.
  This requires human approval for ALL tool calls, not just the blocked patterns.
  
  Options:
    1. Install anyway (sets approval_policy=all — affects all tool calls)
    2. Skip this harness
    3. Cancel

  Default: option 2 (skip).
```

For `purpose: post-tool-reaction` on `codex_cli`, `codex_cloud`, `opencode`:
```
Warning: Capability mismatch for guardrail '<name>' on harness '<harness>':
  Requested purpose: post-tool-reaction
  <harness> does not support PostToolUse events.
  
  This guardrail CANNOT be installed on <harness>. Skipping.
```

### 5. Resolve Target Directory

Read `default_dirs.guardrails` from `library.yaml`. Pick the path key:

| Target harness | Scope | Key to use |
|----------------|-------|------------|
| `claude_code` | local | `default` |
| `claude_code` | global | `global` |
| `codex_cli` | local | `default_codex` |
| `codex_cli` | global | `global_codex` |
| `opencode` | local | `default_opencode` |

> **YAML list note:** `default_dirs.guardrails` is a list of single-key maps. Iterate the
> list to find the entry whose key matches the desired name. For example, to find `default`:
> iterate `default_dirs.guardrails`, find the map `{ default: .claude/hooks/ }`.

### 6. Install Per Harness

For each harness the user confirmed (after capability check):

#### Claude Code installation
```bash
# Source file from guardrail entry: guardrail['sources']['claude_code']
SOURCE_FILE="<repo_root>/<sources.claude_code>"
TARGET_DIR="<resolved_default_or_global_path>"
TARGET_FILE="$TARGET_DIR/<name>/<filename>"

mkdir -p "$(dirname "$TARGET_FILE")"
cp "$SOURCE_FILE" "$TARGET_FILE"
chmod +x "$TARGET_FILE"
```

Then register in Claude Code settings.json. Read the existing settings.json and add/merge
the hook entry under `hooks.PreToolUse` (or the relevant event for the guardrail's purpose):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "<guardrail capability.claude_code.matcher, or empty string for all>",
        "hooks": [
          {
            "type": "command",
            "command": "<TARGET_FILE>"
          }
        ]
      }
    ]
  }
}
```

If the event already has entries in settings.json, append — do NOT overwrite existing hooks.

#### Codex CLI installation (if user confirmed despite mismatch warning)
```bash
SOURCE_FILE="<repo_root>/<sources.codex_cli>"
TARGET_DIR="<resolved_default_codex_path>"
mkdir -p "$TARGET_DIR"
cp "$SOURCE_FILE" "$TARGET_DIR/<name>.mjs"
```

Register in hooks.json:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "script": "<TARGET_DIR>/<name>.mjs"
      }
    ]
  }
}
```

#### Codex Cloud installation (if user confirmed despite mismatch warning)
```bash
# Read config.toml, add/update approval_policy line
TOML_FRAGMENT="<repo_root>/<sources.codex_cloud>"
```
- Open `~/.codex/config.toml`
- If `approval_policy` already set: warn user and ask before overwriting
- Add: `approval_policy = "all"` (or the value from the fragment)
- Do NOT modify other config settings

#### OpenCode installation
```bash
SOURCE_FRAGMENT="<repo_root>/<sources.opencode>"
# Read JSON fragment, merge rules array into opencode.json
```
- Read `opencode.json` (create if not exists with `{"rules": []}`)
- Parse the fragment's `rules` array
- Append rules to `opencode.json` `rules` array (check for duplicates by `pattern`)
- Write back to `opencode.json`

### 7. Verify Installation
For each harness installed:
- Confirm the target file exists (Claude Code, Codex CLI)
- Confirm settings.json / hooks.json / config.toml / opencode.json was updated
- Print a summary of what was installed and where

### 8. Update .library.lock
Add a lockfile entry for each harness installed. See `docs/lockfile-format.md`.

```yaml
- name: <guardrail-name>
  type: guardrail
  source: <source_file_path>      # relative path from library repo root
  source_commit: <sha_or_local>
  install_target: <target_dir>/   # trailing slash required
  install_timestamp: <ISO 8601>
  checksum_sha256: <sha256 of installed file>
  license: <license or "unknown">
  bridge_symlinks: []
```

For multi-harness installs, add one lockfile entry per harness.

### 9. Confirm
Tell the user:
- Which harnesses were installed successfully
- Which were skipped (with reason)
- Any capability mismatches and what was installed instead
- Settings files that were modified
- How to verify the guardrail is active (e.g. test command for Claude Code hook)
