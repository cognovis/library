---
domain: judge-layer
description: Deterministic MCP tool policy manifest for cognovis-tools call_tool authorization.
maturity: draft
---

# MCP Tool Policy Manifest

Contract URI: `standard://judge-layer/mcp-tool-policy-manifest.v1`

Maturity: draft.

This contract defines the deterministic policy metadata used by a future
`WorkspaceFastMCP.call_tool` authorization gate. It is a transport-layer gate,
not a judge-layer Action Proposal evaluation.

## Source of Truth

The source of truth is `mcp-servers/cognovis-tools/concurrency.py`:

- `TOOL_POLICY_VERSION`
- `ToolRiskClass`
- `ToolEffectType`
- `ToolPolicy`
- `tool_policy_manifest()`
- `tool_policy_manifest_digest()`
- `assert_policy_manifest_covers_tools()`

The existing `tool_concurrency_registry()` derives from this manifest. It is not
a second classification list. A new entry in `server.TOOL_FUNCTIONS` must fail
the completeness check until the tool is classified once in the policy manifest.

## Manifest Row

Each registered tool has one row:

| Field | Meaning |
|---|---|
| `concurrency_class` | Existing repository-locking class: `concurrent_read` or `repository_mutation`. |
| `risk_class` | ADR-0003 action-boundary risk class: `read-only`, `reversible-write`, `external-side-effect`, or `high-risk`. |
| `effect_type` | ADR-0003 action-boundary effect type: `filesystem`, `network`, `financial`, `messaging`, `credential`, or `other`. |
| `requires_authorization_grant` | Whether a trusted MCP Authorization Mandate is required before dispatch. |
| `annotations` | Stable strings for policy-specific handling and MCP/client annotations. |
| `parameterized_by` | Argument names that affect the effective policy of a registered tool. |

## Mapping Rules

The effect axis maps onto the concurrency axis, but it is not an alias:

- A concurrent tool may still write session state. `workspace_bind` is
  `concurrent_read` for repository locking but `reversible-write` for
  authorization because it changes the MCP session binding.
- A repository mutation may be higher risk than a filesystem write. Release and
  externally coordinated operations may have `effect_type=network`.
- A tool may be parameterized. Authorization must include effective arguments,
  not only one coarse static label.

## Default Deny

In `enforce=deny`, the server must deny before handler dispatch when:

- A tool is not present in `tool_policy_manifest()`.
- A mutation or grant-required read has no valid MCP Authorization Mandate.
- The grant issuer is not trusted.
- The grant is expired, revoked, replayed, superseded, or outside its scope.
- The grant session, workspace, run, bead, phase, or policy digest does not
  match the call.
- A caller attempts to authorize itself through caller-supplied `role`,
  `capability`, `provider`, `allowed_tools`, prompt text, or client-side tool
  visibility.

## Migration Modes

Rollout must use three explicit modes:

| Mode | Behavior |
|---|---|
| `enforce=off` | No production authorization decision. Prototype checks may run in tests. |
| `enforce=audit` | Compute the authorization decision and emit audit records for every would-be denial, then dispatch. This is a logged compatibility inventory, not a silent bypass. |
| `enforce=deny` | Enforce default-deny behavior before handler dispatch. |

There is no permanent compatibility bypass mode.

## Policy Version and Digest

`TOOL_POLICY_VERSION` is currently `mcp-tool-policy.v1`.

`tool_policy_manifest_digest()` hashes canonical JSON containing the policy
version and every manifest row with sorted keys. This mirrors the
`AgentPolicy.digest()` precedent and gives audit events a stable reference when
policy changes.

## Audit Event

A `call_tool` authorization decision emits one audit event with this minimum
shape:

| Field | Meaning |
|---|---|
| `event_type` | `mcp_call_tool_authorization`. |
| `mode` | `audit` or `deny`. |
| `decision` | `allow` or `deny`. |
| `reason_code` | Stable machine-readable reason. |
| `tool` | Tool name. |
| `risk_class` | Manifest risk class at decision time. |
| `effect_type` | Manifest effect type at decision time. |
| `policy_version` | Manifest version. |
| `policy_digest` | Manifest digest. |
| `issuer` | Grant issuer if present. |
| `subject_ref` | Grant subject if present. |
| `run_id` | Bound run if present. |
| `bead_id` | Bound bead if present. |
| `phase` | Bound phase if present. |
| `expires_at` | Grant expiry if present. |
| `redactions` | Names of fields redacted or hashed. |

The audit event must not log bearer secrets, raw session IDs, raw nonces, or
raw workspace paths. Hashes or stable digests are acceptable.

## MCP Annotations

Generated MCP tool metadata may expose non-secret annotations from the manifest,
including `risk_class`, `effect_type`, `requires_authorization_grant`,
`parameterized_by`, and `policy_version`. These annotations are hints for
clients and reviews. They do not authorize calls.

## Completeness Evidence

Minimum deterministic checks:

```text
assert_policy_manifest_covers_tools(server.registered_tool_names())
assert_registry_covers_tools(server.registered_tool_names())
```

The first check proves authorization/effect coverage. The second proves the
derived concurrency registry still covers every registered tool.
