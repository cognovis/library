# Sync All Installed Items

## Context
Refresh every locally installed skill, agent, and prompt by re-pulling from its source. Uses
`.library.lock` as the authoritative source of truth for what is installed and where — two
clones with the same `.library.lock` end up with identical installed content.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read .library.lock (Source of Truth)

Read `.library.lock` from the project root. This file lists every item that was installed
via `/library use`, with its source URL, source commit, and install target.

If `.library.lock` does not exist:
> "No .library.lock found. Nothing has been installed via /library use. Run /library use <name>
> to install items."
Then exit.

If `.library.lock` is empty (no entries):
> "No items recorded in .library.lock. Nothing to sync."
Then exit.

**Why the lockfile, not library.yaml?**

`library.yaml` is the catalog — it lists what is *available*. `.library.lock` lists what is
*installed in this project*, with the exact source URL and commit. Syncing from the lockfile
guarantees that two developers with the same `.library.lock` get bit-for-bit identical installs.

### 3. Determine Items to Sync

All entries in `.library.lock` are synced. `/library sync` is a full re-pull of the locked state.
To sync a single item, use `/library use <name>` instead.

### 4. Re-pull Each Installed Item

For each entry in `.library.lock`, fetch fresh content from `source`:

**Use the `install_target` from the lockfile** — do NOT re-derive the path from `default_dirs`.
This ensures the item is refreshed at the same location it was originally installed to.

**If source is a local path** (starts with `/` or `~`):
- Resolve `~` to the home directory
- Get the parent directory of the referenced file
- For skills: copy the entire parent directory to the target:
  ```bash
  cp -R <parent_directory>/ <install_target>
  ```
- For agents: copy just the agent file to the target:
  ```bash
  cp <agent_file> <install_target>/<name>.md
  ```
- For prompts: copy just the prompt file to the target:
  ```bash
  cp <prompt_file> <install_target>/<name>.md
  ```

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
- Copy the parent directory of the file to the `install_target`:
  ```bash
  cp -R "$tmp_dir/<parent_path>/" <install_target>
  ```
- Clean up:
  ```bash
  rm -rf "$tmp_dir"
  ```

**If clone fails (private repo)**, try SSH:
  ```bash
  git clone --depth 1 --branch <branch> git@github.com:<org>/<repo>.git "$tmp_dir"
  ```

### 5. Recreate Bridge Symlinks

For each entry that has non-empty `bridge_symlinks`:
- Parse each bridge string (format: `<link-path> -> <target-path>`)
- Recreate the symlink:
  ```bash
  mkdir -p "$(dirname "<link-path>")"
  if [ -d "<link-path>" ] && [ ! -L "<link-path>" ]; then
    rm -rf "<link-path>"
  fi
  ln -sfn "$(realpath "<install_target>")" "<link-path>"
  ```
- This ensures cross-harness bridges are restored after a fresh clone.

### 6. Update .library.lock After Sync

After re-pulling each item, update its lockfile entry:
- Recompute `checksum_sha256` from the primary artifact file
- Update `source_commit` to the new HEAD of the cloned repo (or keep `local`)
- Update `install_timestamp` to the current UTC time

```python
import yaml, os
from datetime import datetime, timezone

lock_path = '.library.lock'
with open(lock_path) as f:
    lock = yaml.safe_load(f) or {'installed': []}

for entry in lock.get('installed', []):
    # Update entry fields for this item after re-pull
    # (source_commit, install_timestamp, checksum_sha256)
    pass  # implementation fills in the updated values

with open(lock_path, 'w') as f:
    yaml.dump(lock, f, default_flow_style=False, allow_unicode=True)
```

### 7. Resolve Dependencies

For each entry that has a `requires` field in `library.yaml`:
- Check if each dependency is also in `.library.lock`
- If a dependency is not in the lockfile, run `/library use <dep>` to install it
- Process dependencies before the items that require them

### 8. Report Results

Display a summary table:

```
## Sync Complete

| Type | Name | Status |
|------|------|--------|
| skill | skill-name | refreshed |
| agent | agent-name | refreshed |
| skill | other-skill | failed: <reason> |

Synced: X items
Failed: Y items
.library.lock updated
```

If any items failed (e.g., network error, missing source), list them with the reason so the user can fix individually.
