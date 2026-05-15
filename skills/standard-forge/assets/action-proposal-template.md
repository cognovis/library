---
domain: action-proposal
description: Defines an Action Proposal schema for pre-action judge decisions.
maturity: draft
---

# Action Proposal

> **Scope**: Use for standards that define a structured proposal submitted
> before a side-effecting actor executes an action. Judges evaluate this shape
> before the side effect happens.

Contract URI: `standard://<namespace>/proposals/<proposal-name>.v1`

Related contracts: [Mandate Schema](mandate-schema.md), [Judge Outcomes](judge-outcomes.md),
[Provenance Labels](provenance-labels.md).

## Required Fields

| Field | Type | Meaning |
|-------|------|---------|
| `proposal_id` | string | Stable identifier for logs, eval cases, and mandates. |
| `actor_ref` | string | Skill, agent, or script proposing the action. |
| `risk_class` | enum | `read-only`, `reversible-write`, `external-side-effect`, or `high-risk`. |
| `effect_type` | enum | `filesystem`, `network`, `financial`, `messaging`, `credential`, or `other`. |
| `intended_action` | object | Verb, target, arguments, and external system affected. |
| `reason` | string | Why the actor believes the action is needed. |
| `evidence_refs` | array | Source references supporting the proposal, each with a provenance label. |
| `authorization` | object or null | Mandate reference or inline authorization evidence. |
| `expected_consequence` | string | Expected external/user-visible result if allowed. |
| `rollback_path` | string or null | How the action can be undone; `null` only when impossible. |

## Mandate Link

For `external-side-effect` and `high-risk`, `authorization` should include a
`mandate_ref` unless local policy explicitly allows mandate-free execution.

## JSON Schema Fragment

```json
{
  "type": "object",
  "required": [
    "proposal_id",
    "actor_ref",
    "risk_class",
    "effect_type",
    "intended_action",
    "reason",
    "evidence_refs",
    "authorization",
    "expected_consequence",
    "rollback_path"
  ],
  "properties": {
    "proposal_id": {"type": "string"},
    "actor_ref": {"type": "string"},
    "risk_class": {
      "enum": ["read-only", "reversible-write", "external-side-effect", "high-risk"]
    },
    "effect_type": {
      "enum": ["filesystem", "network", "financial", "messaging", "credential", "other"]
    },
    "intended_action": {"type": "object"},
    "reason": {"type": "string"},
    "evidence_refs": {"type": "array"},
    "authorization": {"type": ["object", "null"]},
    "expected_consequence": {"type": "string"},
    "rollback_path": {"type": ["string", "null"]}
  }
}
```
