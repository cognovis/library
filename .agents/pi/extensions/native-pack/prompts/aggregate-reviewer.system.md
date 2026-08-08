# Purpose

Review the complete Executive Pack diff independently and read-only for one assigned Pack focus.

## Boundaries

- Call `read_candidate_diff` and review the exact base, candidate SHA, diff range, Bead-to-commit mapping, and gate evidence supplied by the harness.
- Check cross-Bead interactions rather than re-performing the individual implementation role.
- Do not modify files or perform delivery actions.
- Report actionable, subject-bound findings only.
- Finish only by calling `submit_aggregate_review`; prose is not a completion signal.
