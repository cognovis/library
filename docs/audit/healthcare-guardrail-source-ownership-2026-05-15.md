# Healthcare Guardrail Source Ownership Audit

Date: 2026-05-15
Bead: CL-eca

## Scope

Checked the four healthcare guardrails cataloged in `library.yaml`:

- `gitleaks-guard`
- `beads-version-gate`
- `inject-standards-on-agent`
- `session-catchup`

## Result

The canonical source for these installer-coupled guardrails is now
`meta/guardrails/<name>/`, per ADR-0006.

The local `cognovis-core` checkout does not contain duplicate source files for
these four guardrails under `hooks/`. The following search found no matching
guardrail source files beyond unrelated existing marketplace hooks:

```bash
find /Users/malte/code/library/cognovis-core -maxdepth 3 -type f \
  | rg '/hooks/|gitleaks|beads-version|inject-standards|session-catchup'
```

## Policy

If duplicate editable copies are later found in a marketplace repo, remove them
or replace them with a short pointer to `meta/guardrails/<name>/`. Do not keep a
second editable copy without a CI drift check.
