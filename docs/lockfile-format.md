# .library.lock Format

> **Status**: NORMATIVE — this document is the authoritative format specification for the
> `.library.lock` file used by the cognovis-library tooling.
>
> **Bead**: CL-t21 | **Epic**: CL-36o | **Last updated**: 2026-04-30
>
> **Applies to**: `/library use`, `/library remove`, `/library sync`, `/library audit`, and
> any tooling that installs or manages library items.

---

## Overview

`.library.lock` is a project-local YAML file that records every item installed by
`/library use`. It provides:

- **Reproducibility**: any clone of the project can restore the exact set of installed
  items by running `/library sync` (which reads the lockfile, not the catalog).
- **Drift detection**: `/library audit` compares the `checksum_sha256` stored at install
  time against the current on-disk file to identify modifications made outside the Library.
- **Audit trail**: every entry records the source URL, commit SHA, license, and install
  timestamp for security and compliance review.

---

## File Location

`.library.lock` is a **project-local** file placed at the repository root:

```
<project-root>/
├── .library.lock       ← this file
├── library.yaml
├── .claude/
│   └── skills/
└── ...
```

`.library.lock` must be **committed to git** so all collaborators share the same install
manifest. It should NOT be gitignored.

---

## Format

The file is YAML. The top-level key is `installed`, containing an ordered list of entries.

### Minimal example

```yaml
installed:
  - name: dolt
    type: skill
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456abc123
    install_target: .claude/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    license: MIT
    bridge_symlinks: []
```

### Dual-install example (skill installed for both Claude Code and Codex)

```yaml
installed:
  - name: dolt
    type: skill
    source: https://github.com/cognovis/library-core/blob/main/skills/dolt/SKILL.md
    source_commit: abc123def456abc123def456abc123def456abc123def456abc123def456abc123
    install_target: .claude/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: 9483a0941234567890abcdef1234567890abcdef1234567890abcdef12345678
    license: MIT
    bridge_symlinks:
      - .agents/skills/dolt -> ../../.claude/skills/dolt
```

The `bridge_symlinks` list records every symlink created during a dual-install. See
`docs/policy/name-collision.md` (Decision 2) for the canonical/bridge model.

---

## Field Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | YES | string | Unique item name. Must match the catalog entry in `library.yaml`. |
| `type` | YES | string | `skill`, `agent`, or `prompt`. |
| `source` | YES | string | GitHub browser URL or local path used for the install. |
| `source_commit` | YES | string | Git commit SHA of the source repo at install time. Use `local` for non-git sources. |
| `install_target` | YES | string | Relative path of the install directory (trailing slash required). |
| `install_timestamp` | YES | string | ISO 8601 UTC datetime of the install or last refresh. |
| `checksum_sha256` | YES | string | SHA-256 hex digest (64 chars) of the primary artifact file. |
| `license` | NO | string | SPDX license identifier (e.g. `MIT`, `Apache-2.0`). Default: `unknown`. |
| `bridge_symlinks` | NO | array | List of symlink strings created for dual-install. Default: `[]`. |

The JSON Schema for this format lives at `docs/schema/lockfile.schema.json`.

---

## Checksum Computation

The `checksum_sha256` field is computed over the **primary artifact file**:

| Item type | Primary artifact |
|-----------|-----------------|
| `skill` | `<install_target>/SKILL.md` |
| `agent` | `<install_target>/<name>.md` |
| `prompt` | `<install_target>/<name>.md` |

Compute with:

```bash
# macOS
shasum -a 256 <primary_artifact_path> | awk '{print $1}'

# Linux
sha256sum <primary_artifact_path> | awk '{print $1}'
```

`/library audit` recomputes this checksum and compares it to the stored value to
detect drift. A mismatch means the installed file was modified after the lock record
was written.

---

## Lockfile Lifecycle

### `/library use` writes/updates an entry

After a successful install, write or update the entry:

1. If an entry for `name` already exists (refresh): update all fields in place.
2. If no entry exists: append a new entry.
3. Write the updated `installed` list back to `.library.lock`.
4. Checksum the primary artifact file immediately after copying it.

See `cookbook/use.md` Step 9 for the full procedure.

### `/library remove` removes an entry

After deleting the installed files:

1. Remove the entry matching `name` from the `installed` list.
2. Write the updated list back to `.library.lock`.
3. If `bridge_symlinks` is non-empty, verify all listed symlinks were also removed.

See `cookbook/remove.md` Step 5 for the full procedure.

### `/library sync` uses the lockfile as source of truth

Instead of reading `library.yaml` to discover what to sync, `/library sync` reads
`.library.lock` directly:

1. For each entry in `installed`, re-fetch from `source` at `source_commit`.
2. Re-checksum after fetching and update `checksum_sha256`.
3. Update `install_timestamp` and `source_commit` to the new HEAD.

This guarantees that two clones with the same `.library.lock` end up with identical
installed content. See `cookbook/sync.md` for the full procedure.

### `/library audit` detects drift

For each entry in `installed`:

1. Locate the primary artifact file at `install_target`.
2. Recompute `sha256` of the file.
3. Compare against `checksum_sha256`.
4. Report MATCH or DRIFT.

See `cookbook/audit.md` for the full procedure.

---

## Example: Full Lockfile

```yaml
installed:
  - name: researcher
    type: skill
    source: https://github.com/disler/claude-code-hooks-mastery/blob/main/.claude/skills/researcher/SKILL.md
    source_commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
    install_target: .claude/skills/researcher/
    install_timestamp: 2026-04-30T09:00:00Z
    checksum_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    license: MIT
    bridge_symlinks:
      - .agents/skills/researcher -> ../../.claude/skills/researcher

  - name: dolt
    type: skill
    source: /Users/malte/code/cognovis-library-core/skills/dolt/SKILL.md
    source_commit: local
    install_target: .claude/skills/dolt/
    install_timestamp: 2026-04-30T10:23:00Z
    checksum_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    license: proprietary
    bridge_symlinks: []
```

---

## Cross-References

- `docs/schema/lockfile.schema.json` — JSON Schema for machine validation.
- `docs/policy/name-collision.md` — Canonical/bridge model for `bridge_symlinks`.
- `cookbook/use.md` Step 9 — How `/library use` writes lockfile entries.
- `cookbook/remove.md` Step 5 — How `/library remove` removes lockfile entries.
- `cookbook/sync.md` — How `/library sync` uses the lockfile as source of truth.
- `cookbook/audit.md` — How `/library audit` detects drift.
