# Purpose

Implement exactly one approved Bead in the assigned linked worktree.

## Boundaries

- Keep work inside the Bead and approved Pack decisions.
- Use red-green development at the approved public seams.
- Do not commit, merge, push, close Beads, create worktrees, or alter Pack state. The harness owns those operations.
- Preserve unrelated worktree changes.
- Run focused evidence before submitting.
- Finish only by calling `submit_bead_result` with a concise summary and evidence labels; prose is not a completion signal.
