# Action Boundary Reference

`action_boundary` is frontmatter that tells an orchestrator or hook when a skill's
proposed action must pass through a judge before execution. It is declarative:
the skill still emits an Action Proposal, and the judge decides whether the
side effect may run.

## Current Shape

```yaml
action_boundary:
  risk_class: external-side-effect
  effect_type: messaging
  proposal_schema: standard://judge-layer/proposals/action-proposal.v1
  judge: agent://judge-default
  requires_mandate: true
```

Use `risk_class`, not the obsolete `class` key.

## Risk Classes

| `risk_class` | Use for | Mandate |
|--------------|---------|---------|
| `read-only` | Inspecting files, data, or web pages without mutation | Usually no |
| `reversible-write` | Local files, drafts, generated artifacts, reversible edits | Usually no |
| `external-side-effect` | Sending, publishing, API writes, network mutation, irreversible external state | Yes |
| `high-risk` | Financial, credential, regulated, legal, safety, privileged, or destructive actions | Yes |

## Effect Types

| `effect_type` | Examples |
|---------------|----------|
| `filesystem` | Write, edit, delete, move, chmod, generate artifact |
| `network` | POST/PATCH/DELETE APIs, deploys, syncs, webhook calls |
| `financial` | Purchase, refund, invoice, payout, contract commitment |
| `messaging` | Email, chat, SMS, comments, public posting |
| `credential` | Token creation, key rotation, permission grants |
| `other` | Side effect that does not fit the categories above |

## Gate Questions

Ask these before scaffolding:

1. Can the skill write or delete local files?
2. Can it contact an external service with a mutating request?
3. Can it send a message or publish content outside the workspace?
4. Can it spend money, change credentials, grant access, or affect regulated data?
5. Would a mistaken execution be hard to reverse?

Any yes means the skill needs `action_boundary`. Use `external-side-effect` or
`high-risk` when the side effect crosses the local workspace boundary or involves
privileged/regulated consequences.

## Judge Selection

Default `proposal_schema` to
`standard://judge-layer/proposals/action-proposal.v1`. Use a specialist
`standard://.../proposals/...vN` contract only when the specialist judge needs
additional required fields beyond the shared shape.

Default `judge` to `agent://judge-default`. Use a specialist judge only when the
domain adds factual policy beyond the shared judge-layer contract: financial
limits, credential policy, regulated messaging, product-specific scope, or
external API authorization rules.

## Examples

| Skill behavior | Boundary |
|----------------|----------|
| Summarizes a local transcript | Omit or `read-only` |
| Writes a draft changelog file | `reversible-write` + `filesystem` |
| Sends an email to a customer | `external-side-effect` + `messaging` + mandate |
| Rotates a production API key | `high-risk` + `credential` + mandate |
| Pays a vendor invoice | `high-risk` + `financial` + mandate |
