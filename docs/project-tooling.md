# project_tooling — Fleet-wide per-project file/hook distribution

**Bead:** CL-3fh

> **Status: transitional.** ADR-0010 makes Workspace plus normal primitive
> dependencies the sole Library desired-state mechanism. No new distributable
> capability should be added to `project_tooling`. Existing entries remain
> protected from Workspace adoption and pruning until their ownership has been
> migrated and verified. The transition exports a read-only target inventory,
> and each repository disables its legacy writer in the same change that
> registers replacement roots.

## Workspace transition

`project_tooling` solved a real pre-Workspace problem, but its conditional
SessionStart scan is a second desired-state engine without lockfile receipts.
Its entry kinds now route as follows:

| Existing concern | Target owner |
|------------------|--------------|
| Reusable Library file or Git hook | A normal primitive dependency selected directly or by a Workspace |
| Beads primer and database-mode migration | The installed `bd` tool and its own migration contract |
| Repository `.gitignore` policy | The repository or an explicit bootstrap operation, never ambient fleet mutation |
| Foreign hook composition during migration | Protected legacy-manager state until a receipt-backed primitive takes ownership |

Workspace manifests do not gain `conditions`, arbitrary file-copy, JSON-patch,
or gitignore-patch fields. A file that cannot be represented by a real Library
primitive remains project- or tool-owned.

Before cutover, every existing target receives one recorded disposition:
becomes a primitive, becomes project-owned and frozen with provenance, or is
explicitly retired. Until then it remains a protected external-manager path and
cannot be adopted, replaced, or pruned by Workspace reconciliation.

The governing desired-state and legacy-writer dispositions are recorded in
[ADR-0010](adr/workspace-desired-state-reconciliation.md) and
[ADR-0011](adr/heterogeneous-marketplace-workspaces.md).

## What it is and why it exists

In the released legacy implementation, `project_tooling` is a top-level section in `library.yaml` that declares files, git hooks,
and JSON field patches to be automatically distributed into every matching project at
SessionStart. It replaces the old hardcoded PRIME.md distribution block that lived in
the beads SessionStart hook.

**Problem it solves:** Without this, each new "fleet-wide" file (hook script, policy doc,
config enforcement) required a new hardcoded block in `beads-session-start.zsh` — coupled,
hard to audit, and not schema-validated.

**Historically with `project_tooling`:** Each target became a structured entry in
`library.yaml`, schema-validated on every change and applied by one runtime script.
That advantage no longer justifies adding targets to a second desired-state engine.

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
    chain_existing: bool    # for git_hook: move a foreign hook to <hook_name>.local and chain it
    section_markers:        # for file_section/gitignore_patch: delimiter comments
      begin: string
      end: string
    tags: []                # optional tags for filtering
```

### target_kind

| Value | What it does |
|-------|-------------|
| `file` | Copies a file from library source to project target. Content-based comparison. |
| `file_section` | Replaces a delimited section within an existing file. Uses `section_markers`. (not yet implemented in runtime) |
| `git_hook` | Copies a shell script to the effective Git hooks directory and sets executable bit. The runtime honors `core.hooksPath` via `git rev-parse --git-path hooks`. |
| `gitignore_patch` | Appends or replaces a section in `.gitignore`. Uses `section_markers`. (not yet implemented in runtime) |
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

### git_hook chaining

`chain_existing: true` is an opt-in contract for managed hook wrappers that know how
to invoke a preserved local hook. When enabled, the sync runtime treats the canonical
source hook's marker line as proof that a target hook is already managed. A foreign
hook at the same target is moved aside once to `<hook_name>.local`; later syncs update
or skip the managed wrapper without nesting, re-moving, or duplicating the sidecar.

The wrapper owns composition. The sync runtime only preserves the foreign hook and
installs the canonical wrapper. The wrapper must replay Git hook stdin and positional
arguments to the sidecar if its own checks pass.

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

**Git hooks path:** For `git_hook` entries, the runtime asks Git for the effective
hooks directory. If `core.hooksPath` redirects hooks to a custom directory, the hook is
installed there. If Git cannot resolve or write that hooks directory, sync reports an
error instead of silently installing into an unused `.git/hooks` path.

## Security threat model for client-side hooks

Managed Git hooks are cooperative client-side defense-in-depth controls. They cannot
prevent `git push --no-verify`, direct edits to the hooks directory, or bypasses by an
agent/user with write access to the checkout. The gitleaks pre-push hook is still useful
because it catches accidental secret pushes early, but it is not the sole enforcement
layer. The independent cognovis-core session-close scan tracked as clc-i5ld is a
separate defense that does not rely on the local pre-push hook being honored.

### Running manually

```bash
# From the project directory where you want to apply tooling:
uv run python ~/code/cognovis-library/scripts/sync_project_tooling.py --verbose

# With explicit roots:
uv run python /path/to/library/scripts/sync_project_tooling.py \
    --library-root /path/to/library \
    --project-root /path/to/project \
    --verbose
```

## Registered use cases

The Library deliberately does not project `.beads/PRIME.md`; the upstream
Beads CLI owns `bd prime` and its workflow context.

### 1. beads-server-mode — Enforce dolt_mode=server

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

### 2. beads-post-commit-hook — bd export on commit

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

### 4. gitleaks-pre-push-hook — outgoing secret scan

```yaml
- name: gitleaks-pre-push-hook
  target_kind: git_hook
  target_path: .git/hooks/pre-push
  hook_name: pre-push
  source: prime/hooks/pre-push.sh
  chain_existing: true
  conditions:
    - dir_exists: .beads
    - command_available: git
  sync_strategy: overwrite_if_source_newer
```

Installs a managed `pre-push` wrapper that scans bounded outgoing commit ranges with
`gitleaks git --log-opts=<range>` before allowing the push. If a foreign `pre-push`
hook already exists, the sync runtime preserves it once as `pre-push.local`; the
managed wrapper runs gitleaks first and invokes the sidecar exactly once only after the
scan succeeds.

## Maintaining a legacy target

Do not add a new capability here. The steps below are retained only for a
required repair to an existing transitional entry before its migration:

1. Confirm that the target already exists in `library.yaml` and that the repair
   cannot wait for its ownership migration. Do not add a target.
2. Repair only that existing source or entry; do not add a condition, strategy,
   target kind, or second destination that broadens its responsibility.
3. Run `uv run python scripts/validate-library.py` to confirm the schema is satisfied.
4. Run `uv run python -m pytest tests/test_project_tooling.py -v` to verify existing tests still pass.
5. Add or adjust a focused test only for the repaired existing behavior.
6. Record the repair and its remaining migration owner in the relevant bead.

This authoring flow applies only while the transitional manager exists. New
capabilities must instead define a primitive dependency and, when the selection
has an independent lifecycle, include it in a Workspace.

## Schema and test locations

| File | Purpose |
|------|---------|
| `docs/schema/library.schema.json` | JSON Schema — `$defs/project_tooling_entry` and `$defs/tooling_condition` |
| `library.yaml` | Registered entries (`project_tooling:` section) |
| `tests/test_project_tooling.py` | Validator and runtime integration tests |
| `scripts/sync_project_tooling.py` | Runtime — reads library.yaml, applies entries |
| `~/.claude/scripts/beads-session-start.zsh` | Hook that calls the runtime at SessionStart |
