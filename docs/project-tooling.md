# project_tooling — Fleet-wide per-project file/hook distribution

**Bead:** CL-3fh

## What it is and why it exists

`project_tooling` is a top-level section in `library.yaml` that declares files, git hooks,
and JSON field patches to be automatically distributed into every matching project at
SessionStart. It replaces the old hardcoded PRIME.md distribution block that lived in
the beads SessionStart hook.

**Problem it solves:** Without this, each new "fleet-wide" file (hook script, policy doc,
config enforcement) required a new hardcoded block in `beads-session-start.zsh` — coupled,
hard to audit, and not schema-validated.

**With `project_tooling`:** Each target is a structured entry in `library.yaml`,
schema-validated on every change, applied by a single runtime script, and easy to add
without touching the hook script.

## Schema reference

```yaml
project_tooling:
  - name: string            # required, unique identifier (kebab-case)
    description: string     # required, human-readable purpose
    target_kind: string     # required, one of: file | file_section | git_hook | gitignore_patch | json_field_enforce
    target_path: string     # required, path relative to project root

    # Optional fields
    source: string          # source path relative to library root (required for file/git_hook/file_section/gitignore_patch)
    conditions: []          # list of conditions — all must be true; see Conditions below
    sync_strategy: string   # one of: overwrite_if_source_newer | overwrite_always | append_if_missing | replace_section | repair_fields
    conflict_policy: string # one of: canonical_wins | user_wins | warn_only (default: canonical_wins)
    consumed_by:            # optional hint about which tool reads this target
      tool: string
      command: string
    fields:                 # for json_field_enforce only
      ensure: {}            # key/value pairs to enforce
      remove: []            # field names to delete
    hook_name: string       # for git_hook: git hook name (post-commit, pre-commit, etc.)
    section_markers:        # for file_section/gitignore_patch: delimiter comments
      begin: string
      end: string
    tags: []                # optional tags for filtering
```

### target_kind

| Value | What it does |
|-------|-------------|
| `file` | Copies a file from library source to project target. Content-based comparison. |
| `file_section` | Replaces a delimited section within an existing file. Uses `section_markers`. |
| `git_hook` | Copies a shell script to `.git/hooks/<hook_name>` and sets executable bit. |
| `gitignore_patch` | Appends or replaces a section in `.gitignore`. Uses `section_markers`. |
| `json_field_enforce` | Reads a JSON file, sets `fields.ensure` keys, removes `fields.remove` keys. |

### Conditions language

Each entry in `conditions` is a single-key object. All conditions must be true for the entry to be applied.

| Key | Value | Meaning |
|-----|-------|---------|
| `dir_exists` | relative path | `Path(value).is_dir()` relative to project root |
| `file_exists` | relative path | `Path(value).is_file()` relative to project root |
| `command_available` | command name | `shutil.which(value) is not None` |
| `env_set` | env var name | `os.environ.get(value)` is non-empty |

Example:
```yaml
conditions:
  - dir_exists: .beads
  - command_available: bd
  - env_set: COGNOVIS_LIBRARY
```

### sync_strategy

| Value | Behaviour |
|-------|-----------|
| `overwrite_if_source_newer` | Copy only if target content differs from source (byte comparison). |
| `overwrite_always` | Always overwrite, regardless of existing content. |
| `append_if_missing` | Append source content to target only if not already present (line match). |
| `replace_section` | Replace content between `section_markers.begin` / `.end` in target. |
| `repair_fields` | For `json_field_enforce`: apply `ensure`/`remove` operations, skip if no change. |

## How the runtime works

`scripts/sync_project_tooling.py` is the runtime. It is called by the SessionStart hook
in beads-enabled projects:

```zsh
# In ~/.claude/scripts/beads-session-start.zsh
if [[ -d ".beads" ]] && command -v bd &>/dev/null; then
    local sync_script="$HOME/code/cognovis-library/scripts/sync_project_tooling.py"
    if [[ -f "$sync_script" ]]; then
        python3 "$sync_script" 2>/dev/null || true
    fi
    bd prime
fi
```

**Discovery order for library root:**
1. `COGNOVIS_LIBRARY` environment variable
2. `~/code/cognovis-library/`
3. `~/cognovis-library/`

If the library is not found, the script exits 0 (non-fatal — not every machine has it checked out).

**Idempotency:** Every sync strategy is designed to be a no-op when the target already matches
the desired state. Running the script twice produces the same result.

### Running manually

```bash
# From the project directory where you want to apply tooling:
python3 ~/code/cognovis-library/scripts/sync_project_tooling.py --verbose

# With explicit roots:
python3 /path/to/library/scripts/sync_project_tooling.py \
    --library-root /path/to/library \
    --project-root /path/to/project \
    --verbose
```

## Registered use cases

### 1. beads-prime — PRIME.md fleet primer

```yaml
- name: beads-prime
  target_kind: file
  target_path: .beads/PRIME.md
  source: prime/PRIME.md
  conditions:
    - dir_exists: .beads
  sync_strategy: overwrite_if_source_newer
  conflict_policy: canonical_wins
  consumed_by: {tool: bd, command: bd prime}
```

Syncs the bd workflow primer from `cognovis-library/prime/PRIME.md` into every beads-enabled
project. `bd prime` emits this content. Previously this was a hardcoded block in the
SessionStart hook; now it is schema-driven and version-controlled alongside related content.

### 2. beads-server-mode — Enforce dolt_mode=server

```yaml
- name: beads-server-mode
  target_kind: json_field_enforce
  target_path: .beads/metadata.json
  conditions:
    - file_exists: .beads/metadata.json
  sync_strategy: repair_fields
  fields:
    ensure: {dolt_mode: server}
    remove: [database, backend, dolt_server_port, dolt_server_user]
```

Ensures `.beads/metadata.json` is in server mode and removes stale embedded-mode fields
that can trigger journal corruption. This replaces the `enforce_server_mode()` function
in the SessionStart hook (which is kept for now as a safety net during migration).

### 3. beads-post-commit-hook — bd export on commit

```yaml
- name: beads-post-commit-hook
  target_kind: git_hook
  target_path: .git/hooks/post-commit
  hook_name: post-commit
  source: prime/hooks/post-commit.sh
  conditions:
    - dir_exists: .beads
    - command_available: bd
  sync_strategy: overwrite_if_source_newer
```

Installs a `post-commit` hook that runs `bd export` after every commit, keeping the
beads database in sync with git history automatically.

## Adding a new target

1. Create the source file in the library (if `target_kind` requires one — `file`, `git_hook`, etc.).
2. Add an entry to `library.yaml` under `project_tooling:` following the schema.
3. Run `python3 scripts/validate-library.py` to confirm the schema is satisfied.
4. Run `python3 -m pytest tests/test_project_tooling.py -v` to verify existing tests still pass.
5. Add a test case in `tests/test_project_tooling.py` for your new entry if it has non-trivial
   behavior (new conditions, new sync strategy, new target_kind).
6. Commit with the `feat(CL-xxx):` prefix for the relevant bead.

The next SessionStart in any matching project will pick up the change automatically.

## Schema and test locations

| File | Purpose |
|------|---------|
| `docs/schema/library.schema.json` | JSON Schema — `$defs/project_tooling_entry` and `$defs/tooling_condition` |
| `library.yaml` | Registered entries (`project_tooling:` section) |
| `tests/test_project_tooling.py` | Validator and runtime integration tests |
| `scripts/sync_project_tooling.py` | Runtime — reads library.yaml, applies entries |
| `~/.claude/scripts/beads-session-start.zsh` | Hook that calls the runtime at SessionStart |
