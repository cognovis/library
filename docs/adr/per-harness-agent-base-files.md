# ADR: Keep Per-Harness Agent Base Files

**Date:** 2026-05-16

## Status

Accepted.

## Context

The Library split the original generic `cognovis-base.md` Layer 1 agent prompt
into harness-specific files:

- `claude-agent-base.md`
- `codex-agent-base.md`

The two files intentionally share most behavioral guidance, but they differ in
the enforcement model they describe. Claude Code has per-agent tool declarations
and hook-based command gating. Codex relies more heavily on sandboxing, approval
policy, MCP tool filters, and prompt-level honoring of declared tool grants.

An alternative design was a single master Layer 1 file plus a harness-specific
Layer 1.5 patch. That would reduce visible duplication, but it would hide the
actual runtime contract for each harness behind composition logic.

## Decision

Keep `claude-agent-base.md` and `codex-agent-base.md` as separate source files.
Do not introduce a Layer 1.5 patch system or generate both files from a shared
master at this time.

Agents should declare `agent_base: auto`. The composer maps `auto` to the
appropriate per-harness Layer 1 file during build/install. The old
`agent_base_extends:` field remains a compatibility alias.

## Consequences

- Duplication between the two base files is accepted.
- Reviewers can read each harness contract directly without mentally applying a
  patch layer.
- Harness-specific enforcement differences stay explicit in the source file that
  owns them.
- Any future single-source generation proposal must show that it preserves direct
  reviewability of the full per-harness prompt.
