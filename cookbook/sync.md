# Sync All Installed Items

## Context
Refresh every locally installed skill, agent, prompt, and standard by re-pulling from its source. Uses
`.library.lock` as the authoritative source of truth for what is installed and where — two
clones with the same `.library.lock` end up with identical installed content.

## CLI Shortcut (when available)

```bash
# Preview sync plan:
python3 <LIBRARY_SKILL_DIR>/scripts/library.py sync --dry-run --json

# Real sync (re-pulls all entries recorded in .library.lock):
python3 <LIBRARY_SKILL_DIR>/scripts/library.py sync --json
```

The CLI's
`skill use <name>` command already handles single-item refresh with correct
lockfile update, vendor-copy materialization, and bridge recreation.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before reading:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Read .library.lock (Source of Truth)

Read `.library.lock` from the project root. This file lists every item that was installed
via `/library <primitive> use <name>`, with its source URL, source commit, and install target.

If `.library.lock` does not exist:
> "No .library.lock found. Nothing has been installed via the Library. Run /library <primitive> use <name>
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
To sync a single item, use `/library <primitive> use <name>` instead.

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
- Clone into a temporary directory, then **pin to `source_commit`** from the lockfile entry
  to guarantee reproducibility (the branch HEAD may have moved since the original install):
  ```bash
  tmp_dir=$(mktemp -d)
  git clone https://github.com/<org>/<repo>.git "$tmp_dir"
  git -C "$tmp_dir" checkout <entry.source_commit>
  ```
  > **Why pin?** A shallow `--depth 1` clone always fetches the current branch tip.
  > Pinning to `source_commit` ensures two clones of the same `.library.lock` produce
  > bit-for-bit identical content, regardless of upstream changes since the original install.
  > Use a full clone (no `--depth 1`) so that `git checkout <sha>` succeeds.
- Copy the parent directory of the file to the `install_target`:
  ```bash
  cp -R "$tmp_dir/<parent_path>/" <install_target>
  ```
- Capture the new commit SHA and clean up (use `rm -r` without `-f` to satisfy
  the `block-destructive-bash` guardrail):
  ```bash
  new_commit=$(git -C "$tmp_dir" rev-parse HEAD)   # should equal entry.source_commit
  rm -r "$tmp_dir"
  ```

**If clone fails (private repo)**, try SSH:
  ```bash
  git clone git@github.com:<org>/<repo>.git "$tmp_dir"
  git -C "$tmp_dir" checkout <entry.source_commit>
  ```

**Upgrade behavior** — if the user explicitly requests an upgrade (e.g. `/library upgrade <name>`),
omit the `git checkout <source_commit>` pin and use the current branch HEAD instead. Then update
`source_commit` in the lockfile to the new HEAD SHA.

### 4.5. Compose Agent Body on Resync

> **Applies to agent entries only.** Skills, prompts, and guardrails are not composed.

After re-pulling a fresh agent body in Step 4, check whether the agent requires composition
before restoring bridge symlinks or updating the lockfile.

For each entry in `.library.lock` where `type` is `agent`:

1. **Read the freshly re-pulled agent file** at `install_target/<name>.md` (or the `.toml`
   sibling for Codex).

2. **Check the YAML frontmatter**: if `agent_base_extends:` is present AND the value is
   NOT `from-scratch`, the agent requires composition.

3. **Locate the composer script** in the library root (the same directory that contains
   `library.yaml`):
   ```bash
   LIBRARY_ROOT="<path to the library checkout>"
   COMPOSE_SCRIPT="${LIBRARY_ROOT}/scripts/compose-agent.py"
   ```

4. **Run the composer for the target harness**:
   ```bash
   # For Claude Code (default):
   python3 "${COMPOSE_SCRIPT}" "<install_target>/<name>.md"

   # For Codex (when a .toml sibling exists):
   python3 "${COMPOSE_SCRIPT}" "<install_target>/<name>.md" --harness=codex
   ```

5. **On success** (exit code 0): replace the body of the fetched agent file (everything
   after the closing `---` of the frontmatter) with the composed output:
   ```bash
   # Read the frontmatter (everything up to and including the second ---)
   frontmatter=$(awk '/^---$/{n++; print; if(n==2) exit; next} {print}' "<install_target>/<name>.md")
   composed_body=$(python3 "${COMPOSE_SCRIPT}" "<install_target>/<name>.md")
   printf '%s\n\n%s\n' "${frontmatter}" "${composed_body}" > "<install_target>/<name>.md"
   ```

6. **On failure** (non-zero exit — missing Layer 1 or Layer 3):
   - Warn the user:
     ```
     Warning: Compose failed for <name>: <error>.
     Keeping uncomposed agent body. Run /library agent use <name> after installing the required
     base/model-standard (cognovis-base, model-standard).
     ```
   - Continue with the original fetched body (graceful degradation). Do NOT abort
     the sync — an uncomposed agent still works; it just runs with its persona
     body alone as the agent system prompt, with no Cognovis base layer
     prepended. (Agents do not inherit the orchestrator / harness system prompt,
     so the persona body IS the agent system prompt.)

7. **Update the lockfile `composed_sha` and `composed_layers` fields** for the entry
   (these will be written out in Step 7):
   ```python
   import hashlib

   # After successful composition:
   with open("<install_target>/<name>.md") as f:
       body_after_frontmatter = f.read().split("---", 2)[-1].lstrip("\n")

   entry["composed_sha"] = hashlib.sha256(body_after_frontmatter.encode()).hexdigest()
   entry["composed_layers"] = {
       "layer1": "<agent_base_extends value>",   # e.g. "cognovis-base"
       "layer3": "<model_standards list or []>",    # e.g. ["claude-haiku-4-5"]
   }

   # On failure: leave composed_sha and composed_layers unchanged (keep prior values
   # or omit if never composed).
   ```

> **Idempotency**: The composer is deterministic given the same layer files. Re-running
> `/library sync` on an already-composed agent produces the same body byte-for-byte.
> If a Layer 1 (`cognovis-base`) or Layer 3 (model-standard) source file changes, the
> `composed_sha` in the lockfile will differ from the recomputed SHA after the next sync,
> which triggers re-composition automatically.

> **Layer resolution search order** for `compose-agent.py`:
> 1. `<proj_root>/.agents/agent-bases/<name>.md` (project-local)
> 2. `~/.agents/agent-bases/<name>.md` (user-global)

### 5. Recreate Bridge Symlinks

For each entry that has non-empty `bridge_symlinks`:
- Parse each bridge string (format: `<link-path> -> <target-path>`)
- Recreate the symlink:
  ```bash
  mkdir -p "$(dirname "<link-path>")"
  if [ -d "<link-path>" ] && [ ! -L "<link-path>" ]; then
    rm -r "<link-path>"
  fi
  ln -sfn "$(realpath "<install_target>")" "<link-path>"
  ```
- This ensures cross-harness bridges are restored after a fresh clone.

### 6. Reconcile Cache And Install Target

Before updating the lockfile, reconcile the Layer-B cache and Layer-C install target with
each entry's `cache_path` and `install_mode`:

For each entry in `.library.lock`:

1. **If `cache_path` is empty**: derive and materialize the cache path:
   ```bash
   cache_path="${HOME}/.local/share/library/skills/<marketplace>/<name>@${source_commit:0:14}/"
   mkdir -p "$cache_path"
   cp -R <install_target>/ "$cache_path"
   ```
   Update the entry's `cache_path` to the materialized path.

2. **If `cache_path` is set**: verify the cache directory exists. If the cache is missing
   after a clean install on a new machine, fetch from `source` and repopulate the cache:
   ```bash
   mkdir -p "<cache_path>"
   cp -R <fetched_source_directory>/ "<cache_path>"
   ```

3. **Materialize `install_target` from the cache**:
   - `install_mode: vendor` or missing: remove the existing install target and copy real
     files from `cache_path` into `install_target`.
   - `install_mode: symlink`: recreate `install_target` as a symlink to `cache_path`.

4. **Recompute the installed content hash** from `install_target`. For directory entries,
   hash all files in the vendored directory. For file entries, hash the installed file.

### 7. Update .library.lock After Sync

After re-pulling each item, update its lockfile entry:
- Recompute `checksum_sha256` and `content_sha256` from the installed content
- Update `source_commit` to the new HEAD of the cloned repo (or keep `local`)
- Update `cache_path` if it was empty
- Update `install_mode` to `vendor` unless the entry was explicitly installed with `--symlink`
- Update `install_timestamp` to the current UTC time

```python
import yaml, os
from datetime import datetime, timezone

lock_path = '.library.lock'
with open(lock_path) as f:
    lock = yaml.safe_load(f) or {'installed': []}

for entry in lock.get('installed', []):
    # Update entry fields for this item after re-pull
    # (source_commit, install_timestamp, checksum_sha256, content_sha256, install_mode)
    pass  # implementation fills in the updated values

with open(lock_path, 'w') as f:
    yaml.dump(lock, f, default_flow_style=False, allow_unicode=True)
```

### 8. Resolve Dependencies

For each entry that has a `requires` field in `library.yaml`:
- Check if each dependency is also in `.library.lock`
- If a dependency is not in the lockfile, run `/library <dependency-type> use <dependency-name>` to install it
- Process dependencies before the items that require them

### 8.5. Commit Consumer Vendored Files

Consumer projects commit the vendored `.agents/` tree and `.library.lock` so a fresh clone
has real primitive files available immediately. After `/library sync`, apply the consumer
project-tooling profile and review the diff:

```bash
python3 <LIBRARY_SKILL_DIR>/scripts/sync_project_tooling.py --profile consumer --verbose
git status --short
git add .library.lock .agents/ .gitignore
git commit -m "Sync library-installed agent files"
```

Marketplace/library-core repos use the marketplace profile because their `.agents/` tree is
a local install target, not source content:

```bash
python3 <LIBRARY_SKILL_DIR>/scripts/sync_project_tooling.py --profile marketplace --verbose
```

### 9. Report Results

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
