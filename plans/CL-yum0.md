# Task: Global MCP ownership keeps harness registrations and locks consistent

## Current State

The public Library CLI can resolve MCP operations to project scope even though every writable MCP target is a user-global harness configuration. The lower-level MCP installer also defaults to project lock ownership. Existing provenance-less registrations with the canonical name are rejected even when their descriptor exactly matches the catalog, which prevents safe adoption of older installs. On the live machine, `open-brain` and `cognovis-tools` are recorded in the project lock, Codex registrations lack provenance, and Codex contains both `openbrain` and `open-brain` aliases for the same remote endpoint.

## Desired State

MCP use/remove defaults to global ownership, public `--scope project` requests fail before mutation, and exact provenance-less canonical registrations can be safely adopted. The live `open-brain` and `cognovis-tools` state is migrated to the global lock with canonical provenance and no duplicate alias, while their source ownership and MCP species remain unchanged.

## Approaches Considered

### Approach A: Catalog `default_scope: global` on two entries

- Description: Extend the MCP schema and set the field only on `open-brain` and `cognovis-tools`.
- Pros: Small catalog-local change; follows the closed CL-brl mechanism.
- Cons: Leaves other MCP entries inconsistent, allows explicit project scope to recreate the defect, and conflicts with CL-t13's planned catalog cleanup.
- Effort: Low.

### Approach B: Primitive-level global invariant with exact-match adoption

- Description: Make MCP the global fallback in CLI resolution and installer defaults, reject public project scope, and adopt provenance-less canonical registrations only on exact normalized descriptor equality.
- Pros: Matches actual write targets, is independent of catalog/frontmatter scope hints, protects genuinely foreign configurations, and generalizes beyond two entries.
- Cons: Intentionally rejects a previously accepted but incoherent CLI combination; requires focused migration and tests.
- Effort: Medium.

### Approach C: Support true project-local MCP configuration

- Description: Add per-project harness MCP config targets and retain project lock ownership.
- Pros: Makes project scope semantically real.
- Cons: Not supported uniformly by the target harnesses, substantially expands scope, and does not solve the requested global machine migration.
- Effort: High.

### Recommendation: Approach B — Ready to implement

The primitive-level invariant directly matches the harness filesystem contract and remains valid if CL-t13 replaces generic scope recommendations later.

## Break Analysis

**Risk Level:** YELLOW

| Dimension | Level | Evidence | Mitigation |
|-----------|-------|----------|------------|
| Technical complexity | YELLOW | CLI resolution, low-level merge logic, and live state interact. | Separate tests for scope rejection, exact adoption, and live verification. |
| Blast radius | YELLOW | MCP is a cross-harness primitive. | Preserve explicit lower-level test hooks; run focused and full installer suites. |
| Reversibility | GREEN | Harness configs are snapshotted by the installer and lock migration is additive before cleanup. | Verify global records before removing project records. |
| Data integrity | YELLOW | Global and project lockfiles must not diverge during migration. | Install globally first, verify, then remove only the two project entries. |
| Security impact | GREEN | No endpoint, OAuth, credential, or authorization changes. | Compare sanitized descriptors only; do not inspect or move auth state. |

### Assumptions

- Verified: all writable MCP config paths returned by `_mcp_config_path()` are user-global.
- Verified: current `openbrain` and `open-brain` Codex aliases point to the same HTTPS endpoint.
- Verified: CL-t13 concerns content frontmatter recommendations, while MCP scope is a primitive filesystem invariant.
- Assumed until live migration: catalog-supported harness registrations either match canonically or can be safely adopted by the exact-match rule; unsupported registrations remain foreign.

### Fragile Points

- Descriptor comparison must exclude only the Library `_origin` marker; it must not normalize away behavioral differences.
- Scope rejection must happen before dependency resolution, config writes, daemon operations, or lock mutation.
- `cognovis-tools` service health must remain successful when the global lock is created.

## Relevant Files

- `scripts/library.py`
- `scripts/lib/installers/mcp_installer.py`
- `scripts/install-mcp.py`
- `tests/test_library_py_new_features.py`
- `tests/test_library_py_installers.py`
- `tests/test_install_mcp.py`
- `docs/lockfile-format.md`
- `docs/schema/dry-run-contract.md`
- `CHANGELOG.md`

## Step by Step Tasks

### Task 1: Lock the public MCP scope invariant

**Files:** `tests/test_library_py_new_features.py`, `scripts/library.py`
**Change:** Default MCP use/remove to global scope and return a typed error for explicit project scope before dispatch or mutation. Leave other primitive default-scope behavior unchanged.
**Red test:** Add CLI tests showing default MCP dry-run targets the global lock and explicit project scope for use/remove fails with no project lock/config mutation.
**Green code:** Add a shared public-scope resolver/guard used by both `cmd_use()` and `cmd_remove()`.
**Verify:** `uv run pytest tests/test_library_py_new_features.py -k 'Mcp and scope' -v` returns PASS.

### Task 2: Align lower-level MCP installer defaults

**Files:** `tests/test_library_py_installers.py`, `scripts/lib/installers/mcp_installer.py`
**Change:** Make `install_mcp()` and `remove_mcp()` default to global lock scope while preserving explicit lower-level scope parameters for isolated compatibility tests.
**Red test:** Add direct-installer dry-run assertions that omitted scope reports `~/.config/library/global.lock` for install and removal.
**Green code:** Change installer function defaults and related documentation/comments to `global`.
**Verify:** `uv run pytest tests/test_library_py_installers.py -k mcp -v` returns PASS.

### Task 3: Safely adopt exact provenance-less registrations

**Files:** `tests/test_install_mcp.py`, `scripts/install-mcp.py`
**Change:** Treat a canonical-name entry with no `_origin` as adoptable only when every descriptor field exactly matches the catalog snippet after excluding only `_origin`. Replace the current command/args-only legacy comparison with the same complete normalized dictionary equality. Keep extra, missing, changed-type, and foreign-origin descriptors protected.
**Red test:** Add JSON and TOML cases for exact canonical and declared-legacy adoption plus extra, missing, changed-type, and explicit foreign-origin fields.
**Green code:** Add one complete normalized descriptor equality predicate used by JSON and TOML merge paths for both canonical and declared-legacy adoption before manual-entry refusal.
**Verify:** `uv run pytest tests/test_install_mcp.py -v` returns PASS.

### Task 4: Document and validate the behavior

**Files:** `docs/lockfile-format.md`, `docs/schema/dry-run-contract.md`, `CHANGELOG.md`
**Change:** Document that MCP public lifecycle operations are globally owned, project scope is rejected, and exact descriptor adoption is conservative. Record the user-visible CLI behavior change.
**Red test:** Not applicable; documentation/config-only task.
**Green code:** Update the relevant lifecycle and dry-run sections without changing MCP species or endpoints.
**Verify:** `uv run scripts/validate-library.py --quiet` and targeted documentation grep return PASS.

### Task 5: Migrate and verify live MCP state

**Files:** user-global harness configuration files, `~/.config/library/global.lock`, project `.library.lock`
**Change:** Run dry-runs, install/adopt `open-brain` and `cognovis-tools` globally, verify service/config/lock state, then back up `/Users/malte/code/library/meta/.library.lock` and perform a lock-only `load_lockfile` → `remove_entry` → `save_lockfile` migration for exactly those two records. Remove the duplicate Codex `openbrain` alias only after normalized endpoint equality is confirmed. Leave the unsupported Open Brain Cursor registration foreign and untouched.
**Red test:** Not applicable; operational migration with pre/post evidence.
**Green code:** Use the updated Library CLI, the existing lockfile library for lock-only cleanup, and a surgical patch only where alias cleanup is not represented by a catalog entry. Never call MCP remove for the project-lock migration.
**Verify:** `uv run scripts/library.py installed --scope global --primitive mcp --offline --json`, project-scope installed view, sanitized Claude/Codex/Cursor/OpenCode config inspection, and cognovis-tools health all return the canonical state.

## Developer Decisions

### Q: Should explicit MCP project scope remain supported?
**Decision:** No. Public MCP use/remove rejects it before mutation because supported config targets are user-global.
**Rationale:** A project lock cannot honestly own an exclusively global side effect.

### Q: How may an existing provenance-less registration be adopted?
**Decision:** Only the canonical name or a declared legacy descriptor with complete normalized dictionary equality may be adopted; normalization excludes only `_origin`. Extra, missing, changed, and foreign-origin descriptors remain protected.
**Rationale:** This repairs legacy ownership without weakening the no-clobber boundary.

### Q: Does cognovis-tools move out of the Library?
**Decision:** No. It remains a Library-owned `library-tool-surface`; open-brain remains an external capability.
**Rationale:** Source ownership and install-scope bookkeeping are separate concerns.

### Q: How does this coordinate with CL-t13?
**Decision:** MCP global ownership is a primitive-level invariant that CL-t13 must preserve; the beads remain separate because CL-yum0 has independent value and verification.
**Rationale:** CL-t13's frontmatter recommendations cannot make project ownership coherent for global MCP files.

### Q: What happens to the existing Open Brain Cursor registration?
**Decision:** It remains foreign and untouched.
**Rationale:** The Open Brain catalog entry does not declare Cursor support; adding that support is outside the approved migration and requires its own compatibility decision.

### Q: How are obsolete project lock records removed without unregistering MCPs?
**Decision:** After global verification, create a backup and use the lockfile library to remove exactly the two records from `/Users/malte/code/library/meta/.library.lock` without invoking MCP removal.
**Rationale:** `remove_mcp()` owns runtime and harness teardown and is unsafe for a bookkeeping-only migration.

## Test Plan

### Test Framework

- Unit tests: pytest through `uv run pytest`
- Validation: `uv run scripts/validate-library.py --quiet`
- Linter: `uv run ruff check` for changed Python files if ruff is configured/available

### Unit Tests

| Test File | Command |
|-----------|---------|
| `tests/test_library_py_new_features.py` | `uv run pytest tests/test_library_py_new_features.py -k 'Mcp or DefaultScope' -v` |
| `tests/test_library_py_installers.py` | `uv run pytest tests/test_library_py_installers.py -k mcp -v` |
| `tests/test_install_mcp.py` | `uv run pytest tests/test_install_mcp.py -v` |

### Integration Tests

| Scenario | Command |
|----------|---------|
| Catalog remains valid | `uv run scripts/validate-library.py --quiet` |
| Global MCP inventory | `uv run scripts/library.py installed --scope global --primitive mcp --offline --json` |
| Project MCP inventory empty after migration | `uv run scripts/library.py installed --scope project --primitive mcp --offline --json` |
| Full focused regression | `uv run pytest tests/test_install_mcp.py tests/test_mcp_installer_sha.py tests/test_library_py_new_features.py tests/test_library_py_installers.py -v` |

### Expected Results

- Before: default MCP use can report/write a project lock; exact legacy registrations are refused; live state is project-locked and Codex is duplicated.
- After: default MCP use/remove is globally locked, project scope is rejected, exact legacy descriptors are adopted, and live state has one canonical globally managed registration per catalog-supported server/harness.

## Means of Compliance

| # | Acceptance Criterion | MoC | Planned Evidence |
|---|---------------------|-----|------------------|
| 1 | Default MCP install uses and reports the global lock. | unit | `tests/test_library_py_new_features.py`, `tests/test_library_py_installers.py` |
| 2 | Default removal is global and public project scope fails before mutation. | unit | `tests/test_library_py_new_features.py`, `tests/test_library_py_installers.py` |
| 3 | Catalog and non-MCP scope behavior remain valid. | unit | `tests/test_validate_library.py`, existing CL-brl tests |
| 4 | MCP species remain unchanged. | review | `library.yaml` diff/review |
| 5 | Exact descriptor adoption preserves the no-clobber boundary. | unit | `tests/test_install_mcp.py` |
| 6 | Live state is globally locked, canonical, and healthy. | integ | installed views, sanitized config inspection, daemon status |

## Validation Commands

```text
uv run pytest tests/test_install_mcp.py tests/test_mcp_installer_sha.py tests/test_library_py_new_features.py tests/test_library_py_installers.py -v
uv run scripts/validate-library.py --quiet
uv run ruff check scripts/library.py scripts/install-mcp.py scripts/lib/installers/mcp_installer.py tests/test_install_mcp.py tests/test_library_py_new_features.py tests/test_library_py_installers.py
```

## Recommendation

Ready to implement.
