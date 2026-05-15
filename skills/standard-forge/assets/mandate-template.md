---
domain: mandate
description: Defines an authorization-as-evidence Mandate schema for judge decisions.
maturity: draft
---

# Mandate Schema

> **Scope**: Use for standards that define bounded authority records consumed by
> Action Proposals and judges. A Mandate proves allowed scope; it does not grant
> authority outside that scope.

Contract URI: `standard://<namespace>/mandates/<mandate-name>.v1`

Related contracts: [Action Proposal](action-proposal.md), [Judge Outcomes](judge-outcomes.md),
[Provenance Labels](provenance-labels.md).

## Required Fields

| Field | Type | Meaning |
|-------|------|---------|
| `mandate_id` | string | Stable identifier for proposals, logs, and audits. |
| `scope` | object | Actions, targets, systems, accounts, and time range covered. |
| `limits` | object | Amount caps, recipient constraints, allowed verbs, approval ceilings, or other boundaries. |
| `evidence_refs` | array | Sources proving the mandate, each with a provenance label. |
| `granted_at` | timestamp | When the mandate was granted. |
| `granted_by` | object | Person, role, system, or policy authority that granted it. |
| `expires_at` | timestamp or null | Expiration time. `null` means no explicit expiry, not permanent authority. |
| `supersedes` | array | Mandate IDs this record replaces. |

## Optional Fields

| Field | Meaning |
|-------|---------|
| `subject_ref` | Actor, user, service account, or organization receiving the authority. |
| `delegation_chain` | Chain of grants when authority is delegated. |
| `revoked_at` | Time the mandate was revoked. |
| `notes` | Non-authoritative explanation for auditors. |

## Proposal Link

Action Proposals reference a mandate with `authorization.mandate_ref`. Judges use
the mandate's `scope`, `limits`, expiry, supersession, and provenance to decide
whether the proposed action is authorized.

## JSON Schema Fragment

```json
{
  "type": "object",
  "required": [
    "mandate_id",
    "scope",
    "limits",
    "evidence_refs",
    "granted_at",
    "granted_by",
    "expires_at",
    "supersedes"
  ],
  "properties": {
    "mandate_id": {"type": "string"},
    "scope": {"type": "object"},
    "limits": {"type": "object"},
    "evidence_refs": {"type": "array"},
    "granted_at": {"type": "string", "format": "date-time"},
    "granted_by": {"type": "object"},
    "expires_at": {"type": ["string", "null"], "format": "date-time"},
    "supersedes": {"type": "array"},
    "subject_ref": {"type": "string"},
    "delegation_chain": {"type": "array"},
    "revoked_at": {"type": ["string", "null"], "format": "date-time"},
    "notes": {"type": "string"}
  }
}
```
