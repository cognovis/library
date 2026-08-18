---
name: mcp-forge
description: >-
  use when: creating a Python MCP server or migrating a Python MCP server to the
  stateless 2026-07-28 protocol with the official Python SDK v2. NOT for:
  non-Python servers. boundary: this skill owns generic Python MCP server
  architecture, implementation, migration, and conformance.
requires_standards: [python, judge-layer]
compatibility: {}
metadata: {}
action_boundary:
  risk_class: reversible-write
  effect_type: filesystem
  proposal_schema: standard://judge-layer/proposals/action-proposal.v1
  judge: agent://judge-default
  requires_mandate: false
---

# MCP Forge

Build and migrate Python MCP servers through the official Python SDK v2.

## Inputs

- Target repository, server purpose, and required tools, resources, or prompts.
- Greenfield or migration mode; for migrations, current SDK pin and server entrypoint.
- Transport, deployment shape, and supported modern and legacy clients.

## Outputs

- Python MCP server code or an evidence-backed migration diff.
- Focused tests, applicable conformance results, and explicit compatibility evidence.

## Exclusions

- Reject TypeScript and every other non-Python server implementation.
- Do not implement product auth, access-control, PII, or compliance changes without the required human review.
- Require explicit confirmation before running conformance against a non-local MCP endpoint.

## Workflow

1. Confirm Python scope and classify the request as greenfield or v1-to-v2 migration.
2. Inventory repository rules, Python and `uv` configuration, transport, deployment, state, auth, and client requirements.
3. Use `references/python-authoring.md` for greenfield work or `references/migration-v1-v2.md` for migration work.
4. Treat `references/source-hierarchy.md` as the authority order; never implement protocol wire changes by hand when SDK v2 owns them.
5. Preserve application state only through explicit dependencies, lifespan state, databases, or server-minted handles; never depend on protocol sessions.
6. Implement the smallest typed vertical slice and keep tool side effects explicit and testable.
7. Apply every applicable gate in `references/verification.md` and report modern, legacy, and conformance-or-N/A evidence separately.

## Do NOT

- Do not use `FastMCP` in new v2 code or copy release-candidate wire shapes.
- Do not interpret protocol statelessness as a ban on persistent application state.
- Do not claim compatibility from startup success or unit tests alone.

## Resources

| File | Purpose |
|------|---------|
| `references/source-hierarchy.md` | Normative source order and final-versus-RC traps |
| `references/python-authoring.md` | Python SDK v2 greenfield contract |
| `references/migration-v1-v2.md` | Ordered Python SDK v1-to-v2 migration contract |
| `references/verification.md` | Unit, conformance, and client compatibility gates |
| `scripts/audit_mcp_v1.py` | Deterministic migration-signal inventory |
| `tests/mcp-forge.test.md` | Routing and behavior fixtures |
