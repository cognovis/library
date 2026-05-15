# .library.lock Format

> **Status**: NORMATIVE — this document is the authoritative format specification for the
> `.library.lock` file used by the cognovis-library tooling.
>
> **Bead**: CL-t21 / CL-yx2 | **Epic**: CL-36o | **Last updated**: 2026-05-12
>
> **Applies to**: `/library <primitive> use`, `/library <primitive> remove`,
> `/library sync`, `/library audit`, and any tooling that installs or manages library items.

---

## Overview

`.library.lock` is a project-local YAML file that records every item installed by
`/library <primitive> use`. It provides:

- **Reproducibility**: any clone of the project can restore the exact set of installed
  items by running `/library sync` (which reads the lockfile, not the catalog).
- **Drift detection**: `/library audit` compares the `content_sha256`/`checksum_sha256` stored at install
  time against the current on-disk file to identify modifications made outside the Library.
- **Audit trail**: every entry records the source URL, commit SHA, license, and install
  timestamp for security and compliance review.

---

## File Location

Two lockfile instances exist, sharing the same schema:

### Per-project lockfile (existing)

`.library.lock` is placed at the repository root:

```
<project-root>/
├── .library.lock       ← per-project lockfile (committed to git)
├── library.yaml
├── .agents/
│   └── skills/
└── ...
```

`.library.lock` must be **committed to git** so all collaborators share the same install
manifest. It should NOT be gitignored.

### Global lockfile (new — ADR-0003)

`~/.config/library/global.lock` records globally installed items (installed with
`/library <primitive> use <name> --global`):

```
~/.config/library/
└── global.lock         ← global lockfile (NOT git-tracked; user-local only)
```

The global lockfile uses the same schema as the per-project lockfile. It is NOT committed
to version control — it is a user-local file managed by `library` tooling. The path
`~/.config/library/` follows the XDG Base Directory specification for user configuration.

---

## Format

The file is YAML. The top-level key is `installed`, containing an ordered list of entries.

### Minimal example

```yaml
installed:
  - name: dolt
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456ab12
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
    install_target: .agents/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    content_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - .claude/skills/dolt -> .agents/skills/dolt
```

### Symlink opt-in example (developer mode)

```yaml
installed:
  - name: dolt
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456ab12
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
    install_target: .agents/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    content_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    install_mode: symlink
    license: MIT
    bridge_symlinks:
      - .claude/skills/dolt -> /Users/malte/.local/share/library/skills/cognovis-core/dolt@abc123def456ab/
```

The `bridge_symlinks` list records every symlink created during a dual-install. See
`docs/policy/name-collision.md` (Decision 2) for the canonical/bridge model.

### Three-Layer model (Source → Cache → Harness)

Per ADR-0003, skill deployment passes through three layers:

```
Layer A — Source:  https://github.com/cognovis/library-core/...  (canonical git repo)
Layer B — Cache:   ~/.local/share/library/skills/<marketplace>/<name>@<commit>/
Layer C — Harness: ~/.agents/skills/<name>/  or  .agents/skills/<name>/
```

The lockfile records Layer A (`source`, `source_commit`) and Layer B (`cache_path`).
Layer C is recorded as `install_target`. The harness directory at Layer C is a
**vendored copy** by default so consumer projects can commit real files. The
Layer-B cache is a per-machine resolver source, not a runtime path. `--symlink`
keeps Layer C as a symlink into the Layer-B cache for local development.

**Global install example (ADR-0003):**

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc00000000000000000000000000000000000000000000000
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
    install_target: /Users/malte/.agents/skills/agent-forge/
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    content_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - /Users/malte/.claude/skills/agent-forge -> /Users/malte/.agents/skills/agent-forge/
```

**Project-scoped install example (ADR-0003):**

```yaml
installed:
  - name: agent-forge
    type: skill
    marketplace: cognovis-core
    source: https://github.com/cognovis/library-core/blob/9b1e72c98f3e21/.claude/skills/agent-forge/SKILL.md
    source_commit: 9b1e72c98f3e21abc00000000000000000000000000000000000000000000000
    cache_path: /Users/malte/.local/share/library/skills/cognovis-core/agent-forge@9b1e72c98f3e21/
    install_target: .agents/skills/agent-forge/
    install_timestamp: 2026-05-12T07:30:00Z
    checksum_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    content_sha256: 9483a09400000000000000000000000000000000000000000000000000000000
    install_mode: vendor
    license: MIT
    bridge_symlinks:
      - .claude/skills/agent-forge -> .agents/skills/agent-forge/
```

---

## Field Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | YES | string | Unique item name. Must match the catalog entry in `library.yaml`. |
| `type` | YES | string | `skill`, `agent`, `prompt`, `guardrail`, `standard`, `model-standard`, `agent-base`, or `mcp`. |
| `marketplace` | YES | string | Name of the source marketplace from `library.yaml` `sources.marketplaces`. Use `local` for local-path sources, `unknown` for unrecognized sources. |
| `source` | YES | string | GitHub browser URL or local path used for the install. |
| `source_commit` | YES | string | Git commit SHA of the source repo at install time. Use `local` for non-git sources. |
| `cache_path` | YES | string | Absolute Layer-B cache path (`~/.local/share/library/skills/<marketplace>/<name>@<first-14-hex-chars-of-source_commit>/`). Empty string `""` for migrated entries pending next sync. |
| `install_target` | YES | string | Relative (project) or absolute (global) path of the install directory (trailing slash required). |
| `install_timestamp` | YES | string | ISO 8601 UTC datetime of the install or last refresh. |
| `checksum_sha256` | YES | string | Backward-compatible SHA-256 hex digest (64 chars). New entries compute it from the local installed content. |
| `checksum_type` | NO | string | `file` (default) or `directory`. Skills and standards use `directory`; agents and prompts use `file`. Entries without this field are treated as unknown by `library audit`. |
| `content_sha256` | NO | string | Explicit SHA-256 of the local installed content at `install_target`. New vendor-mode entries set this and `checksum_sha256` to the same value. |
| `install_mode` | NO | string | `vendor` (default, real copied files) or `symlink` (explicit opt-in pointing Layer C at Layer B). If omitted, `/library sync` writes `vendor` on the next refresh. |
| `license` | NO | string | SPDX license identifier (e.g. `MIT`, `Apache-2.0`). Default: `unknown`. |
| `bridge_symlinks` | NO | array | List of symlink strings created for dual-install. Format: `<link-path> -> <target-path>`. Default: `[]`. |

The JSON Schema for this format lives at `docs/schema/lockfile.schema.json`.

---

## Checksum Computation

The `checksum_sha256` field and `checksum_type` field together specify how the digest is computed.

### Directory hash (`checksum_type: directory`)

Skills and standards use a Merkle-style directory hash over **all files** in the local installed directory:

| Item type | Checksum scope |
|-----------|----------------|
| `skill` | All files in `<install_target>/` (sorted, recursive) |
| `standard` | All files in `<install_target>/` (sorted, recursive) |

The hash is computed by `scripts/lib/lockfile.py:compute_directory_hash()`:

1. Walk all files under the directory, sorted by relative path.
2. For each file, feed the relative path string + NUL separator + SHA-256 of the file contents + NUL separator into an outer SHA-256 digest.
3. Return the final 64-character hex digest.

This means any file edit, addition, or deletion inside the vendored project copy is detected as drift.

### File hash (`checksum_type: file`)

Agents and prompts use a single-file hash over the primary artifact:

| Item type | Primary artifact |
|-----------|-----------------|
| `agent` | `<install_target>/<name>.md` |
| `prompt` | `<install_target>/<name>.md` |

Compute with:

```bash
# macOS
shasum -a 256 <primary_artifact_path> | awk '{print $1}'

# Linux
sha256sum <primary_artifact_path> | awk '{print $1}'
```

### Entries without `checksum_type`

Entries without this field are not auditable with a known strategy. `/library audit`
reports them as `unknown` — it does not report them as drifted. Run `/library <primitive> use <name>`
to refresh the entry and write `checksum_type`.

`/library audit` recomputes the checksum (using the strategy from `checksum_type`) and compares
it to the stored value to detect drift. A mismatch means the installed files were modified after
the lock record was written.

---

## Lockfile Lifecycle

### `/library <primitive> use` writes/updates an entry

After a successful install, write or update the entry:

1. If an entry for `name` already exists (refresh): update all fields in place.
2. If no entry exists: append a new entry.
3. Write the updated `installed` list back to `.library.lock`.
4. Compute checksum immediately after copying to `install_target`: use `directory` hash for skills/standards, `file` hash for agents/prompts. Write `checksum_type`, `content_sha256`, and `install_mode` accordingly.

See `cookbook/use.md` Step 9 for the full procedure.

### `/library <primitive> remove` removes an entry

After deleting the installed files:

1. Remove the entry matching `name` from the `installed` list.
2. Write the updated list back to `.library.lock`.
3. If `bridge_symlinks` is non-empty, verify all listed symlinks were also removed.

See `cookbook/remove.md` Step 5 for the full procedure.

### `/library sync` uses the lockfile as source of truth

Instead of reading `library.yaml` to discover what to sync, `/library sync` reads
`.library.lock` directly. The top-level `sync` command (no primitive prefix) iterates
all entries across all primitives:

1. For each entry in `installed`, compare `source_commit` against the remote HEAD via `git ls-remote`.
2. Skip entries that are already current (unless `--force` is passed).
3. Re-fetch and re-install only entries that are behind or cannot be verified.
4. Re-checksum after fetching using the appropriate `checksum_type` strategy.
5. Update `install_timestamp` and `source_commit` to the new HEAD.

Use `--dry-run` to print the planned skip vs. refresh decisions without performing any writes.

This guarantees that two clones with the same `.library.lock` end up with identical
installed content. See `cookbook/sync.md` for the full procedure.

### `/library audit` detects drift

For each entry in `installed`:

1. Inspect `checksum_type` to determine the audit strategy.
2. For `directory` entries: recompute the Merkle-style directory hash over `cache_path`.
3. For `file` entries: recompute the SHA-256 of the primary artifact.
4. For entries without `checksum_type`: report `unknown` — do not report as drift.
5. Compare against `checksum_sha256`. Report `clean`, `drift`, or `unknown` per entry.

Use `--drift-only` to filter output to only drifted entries and exit with code 2.
The top-level `audit` command (no primitive prefix) checks all primitives in one pass.

See `cookbook/audit.md` for the full procedure.

### `/library status` checks upstream without cloning

For each entry in `installed`:

1. Extract the `source` URL and `source_commit` from the lockfile.
2. Call `git ls-remote <clone_url> HEAD` (or the pinned branch) — no clone.
3. Compare the returned SHA against `source_commit`.
4. Report `current`, `behind`, or `unknown` (for local sources or network failures).

The `overall` field in the JSON result is `behind` if any entry is behind, otherwise
`current` or `unknown`. Exit code is 0 in all cases (status is informational only).

---

## Example: Full Lockfile

```yaml
installed:
  - name: researcher
    type: skill
    marketplace: disler
    source: https://github.com/disler/claude-code-hooks-mastery/blob/main/.claude/skills/researcher/SKILL.md
    source_commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
    cache_path: /Users/malte/.local/share/library/skills/disler/researcher@deadbeef/
    install_target: .claude/skills/researcher/
    install_timestamp: 2026-04-30T09:00:00Z
    checksum_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    checksum_type: directory
    license: MIT
    bridge_symlinks:
      - .agents/skills/researcher -> /Users/malte/.local/share/library/skills/disler/researcher@deadbeef/

  - name: dolt
    type: skill
    marketplace: local
    source: /Users/malte/code/cognovis-library-core/skills/dolt/SKILL.md
    source_commit: local
    cache_path: ""
    install_target: .claude/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    license: proprietary
    bridge_symlinks: []
```

---

## Cross-References

- `docs/schema/lockfile.schema.json` — JSON Schema for machine validation (`checksum_type` field, expanded `type` enum).
- `docs/adr/three-layer-cache-architecture.md` (ADR-0003) — Three-layer deployment model that introduced `marketplace` and `cache_path`.
- `docs/policy/name-collision.md` — Canonical/bridge model for `bridge_symlinks`.
- `scripts/lib/lockfile.py` — `compute_directory_hash()` for Merkle-style directory checksums; `make_entry()` for lockfile entry construction.
- `scripts/lib/status.py` — `cmd_status_impl()` upstream SHA check via `git ls-remote`.
- `scripts/lib/sync_audit.py` — `cmd_audit_impl()` drift detection logic; `reinstall_entry()` for sync.
- `cookbook/use.md` — How `/library <primitive> use` writes lockfile entries (including cache materialization).
- `cookbook/remove.md` — How `/library <primitive> remove` removes lockfile entries (including GC hints).
- `cookbook/sync.md` — How `/library sync` uses the lockfile as source of truth (including cache reconciliation).
- `cookbook/audit.md` — How `/library audit` detects drift (including symlink target verification).
- `scripts/migrate-lockfile.py` — Migration script to add `marketplace` and `cache_path` to existing lockfiles.
