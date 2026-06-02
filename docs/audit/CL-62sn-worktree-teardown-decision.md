# CL-62sn: Worktree Teardown Decision for Quick-Fix Workflow

## Decision

**Auto-teardown**: The quick-fix workflow will automatically remove the per-bead worktree after a verified successful close.

## Rationale

1. **Isolation scope**: Quick-fix runs in an isolated worktree (`bead-${beadId}`) created for a single bead fix.
2. **One-way flow**: Unlike `cld -b` (general bead orchestrator), quick-fix is a deterministic one-way flow that doesn't return to the same worktree.
3. **Verified-only teardown**: Worktree removal only happens after Phase 5 (Close) verifies `bead_closed=true` with actual `closed_at` and `close_reason`. Errors/fallbacks skip teardown.
4. **Orphan prevention**: Auto-teardown prevents orphaned worktrees (e.g., `bead-CL-mzya` left behind in previous run).
5. **Non-blocking**: Teardown is a non-fatal leaf using `git worktree remove --force` with `2>/dev/null || true` fallback.

## Implementation

Added Phase 5.5 (Teardown) in `~/.claude/workflows/quick-fix.js`:

- After `close.bead_closed` verification succeeds, spawn a haiku agent leaf to remove the worktree.
- Use `git worktree list --porcelain | grep " ${worktreeName}$"` to find the exact worktree path.
- Use `git worktree remove --force` to handle dirty state gracefully.
- Non-fatal: always exits 0 (missing worktrees are silently skipped).
- Result stored in workflow return object as `teardown: teardownResult`.

## Evidence

- Workflow meta block valid (tests: test_workflow_install_gate, test_workflow_gate_parity).
- All workflow runtime tests pass (test_workflow_runtime_production: 12/12).
- Full workflow-related test suite passes (41/41).
- Quick-fix determinism invariant maintained (no Date.now, Math.random, etc.).
- Design pattern matches phase teardown in session-close (non-blocking agent leaf).

## Notes

- Error path (`close.fallback_required || !close.bead_closed`): worktree is NOT removed; leaves it for manual cleanup or next session.
- This decision is local to quick-fix. General `cld -b` orchestrator continues to leave worktrees (matching existing behavior).
- Periodic housekeeping via `git worktree prune` remains the cleanup path for orphaned worktrees from errors/crashes.
