# Remove an Entry from the Library

## Context
The user wants to remove a skill, agent, or prompt from the library catalog and optionally delete the local copy.

## Input
The user provides a skill name or description.

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before modifying:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Find the Entry
- Read `library.yaml`
- Search across all sections for the matching entry
- Determine the type (skill, agent, or prompt)
- If no match, tell the user the item wasn't found in the catalog

### 3. Confirm with User
Show the entry details and ask:
- "Remove **<name>** from the library catalog?"
- If installed locally, also ask: "Also delete the local copy at `<path>`?"

### 4. Remove from library.yaml
- Remove the entry from the appropriate section (`library.skills`, `library.agents`, or `library.prompts`)
- If other entries depend on this one (via `requires`), warn the user before proceeding

### 5. Delete Local Copy and Update .library.lock (if deletion was requested)

If the user confirmed local deletion:

#### 5a. Resolve paths from the lockfile

Before deleting, read `.library.lock` to find the entry for `<name>`:
- `install_target` — the canonical install directory
- `bridge_symlinks` — any symlinks that must also be removed

If no lockfile entry exists, fall back to the default directory from `default_dirs`.

#### 5b. Remove bridge symlinks first (per CL-b4o policy)

For each path listed in `bridge_symlinks`:
```bash
link_path="<link-path from bridge_symlinks entry>"
if [ -L "$link_path" ]; then
  rm "$link_path"
elif [ -d "$link_path" ] && [ ! -L "$link_path" ]; then
  echo "Warning: Bridge at $link_path is a real directory — removing."
  rm -rf "$link_path"
fi
```

#### 5c. Remove the canonical install directory

```bash
rm -rf <install_target>
```

#### 5d. Remove the lockfile entry

```python
import yaml

lock_path = '.library.lock'
with open(lock_path) as f:
    lock = yaml.safe_load(f) or {'installed': []}
lock['installed'] = [e for e in lock.get('installed', []) if e.get('name') != '<name>']
with open(lock_path, 'w') as f:
    yaml.dump(lock, f, default_flow_style=False, allow_unicode=True)
```

If `.library.lock` does not exist, skip this step (no lockfile to update).

### 6. Commit and Push
```bash
cd <LIBRARY_SKILL_DIR>
git add library.yaml
git commit -m "library: removed <type> <name>"
git push
```

### 7. Confirm
Tell the user:
- The entry has been removed from the catalog
- Whether the local copy was also deleted
- If other entries depended on it, remind them to update those entries
