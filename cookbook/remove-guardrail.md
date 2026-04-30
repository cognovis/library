# Remove a Guardrail from the Library

## Context
Uninstall a guardrail from the current project (or globally) and clean up the associated
config entries (hooks, permission rules, approval policies). The catalog entry in
`library.yaml` is NOT removed — only the local installation is undone.

## Input
The user provides: guardrail name, optional target harness(es), optional scope (local/global).

## Steps

### 1. Find the Lockfile Entry
Check `.library.lock` for the installed guardrail:
```bash
# Look for entries where name matches and type is 'guardrail'
```
```python
import yaml
with open('.library.lock') as f:
    lock = yaml.safe_load(f) or {}
entries = [e for e in lock.get('installed', []) if e['name'] == '<name>' and e['type'] == 'guardrail']
```

If no entry found in lockfile: warn the user that this guardrail may not be installed
(or was installed manually). Ask if they want to proceed anyway.

### 2. Detect Target Harness(es)
Same logic as `use-guardrail.md` Step 3. If multiple harness lockfile entries exist
for the same guardrail (one per harness), ask the user which to remove or offer to
remove all.

### 3. Undo Installation Per Harness

#### Claude Code removal
```bash
INSTALL_TARGET="<entry.install_target>"   # from lockfile, e.g. .claude/hooks/my-guardrail/
```

1. Unregister from settings.json:
   - Read `~/.claude/settings.json` (global) or `.claude/settings.json` (local)
   - Find hook entries whose `command` path matches the installed file
   - Remove those hook entries from the relevant event array
   - If the event array becomes empty, remove the key
   - Write settings.json back

2. Delete the hook file:
   ```bash
   # Confirm the file is inside the expected install target before deleting
   if [[ "$TARGET_FILE" == "$INSTALL_TARGET"* ]]; then
       rm "$TARGET_FILE"
       # Remove the directory if now empty
       rmdir "$INSTALL_TARGET" 2>/dev/null || true
   fi
   ```

#### Codex CLI removal
1. Unregister from hooks.json:
   - Read `hooks.json`
   - Find SessionStart (or relevant event) entries pointing to this guardrail's script
   - Remove those entries
   - Write hooks.json back

2. Delete the hook file:
   ```bash
   HOOK_FILE="<install_target>/<name>.mjs"
   [ -f "$HOOK_FILE" ] && rm "$HOOK_FILE"
   ```

#### Codex Cloud removal
1. Edit `~/.codex/config.toml`:
   - Find and remove (or comment out) the `approval_policy` line that was added
   - Do NOT remove other unrelated settings
   - Warn the user: "Removing approval_policy setting. If another guardrail set this,
     you may want to keep it."

#### OpenCode removal
1. Read `opencode.json`
2. Find rules that were added by this guardrail (match by `pattern` from the source fragment)
3. Remove those rules
4. Write `opencode.json` back

### 4. Update .library.lock
Remove the lockfile entries for the uninstalled harnesses:

```python
import yaml

lock_path = '.library.lock'
with open(lock_path) as f:
    lock = yaml.safe_load(f) or {}
lock.setdefault('installed', [])

# Remove entries for this guardrail
lock['installed'] = [
    e for e in lock['installed']
    if not (e.get('name') == '<name>' and e.get('type') == 'guardrail')
]

with open(lock_path, 'w') as f:
    yaml.dump(lock, f, default_flow_style=False, allow_unicode=True)
```

### 5. Verify Removal
For each harness removed:
- Confirm the hook file no longer exists
- Confirm settings.json / hooks.json / config.toml / opencode.json no longer references
  this guardrail
- Confirm the lockfile entry is gone

### 6. Confirm
Tell the user:
- Which harnesses were uninstalled
- Which config files were modified
- The guardrail catalog entry in `library.yaml` remains — they can reinstall with
  `/library use-guardrail <name>` at any time
