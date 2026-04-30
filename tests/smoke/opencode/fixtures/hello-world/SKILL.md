---
name: hello-world
description: Smoke-test fixture skill for OpenCode harness (stub). OpenCode is not locally available — this fixture is a structural stub for MANUAL_VERIFICATION_REQUIRED paths.
argument-hint: [name]
---

# Hello World (Smoke Test Fixture — OpenCode Stub)

This is a stub fixture for the OpenCode harness. OpenCode is not locally available for automated testing.

## Status

MANUAL_VERIFICATION_REQUIRED — OpenCode runtime not available in CI or local development.

## Purpose

Document the expected install paths for OpenCode once runtime is available:
- Project-local (primary): `.opencode/skills/hello-world/SKILL.md`
- Project-local (fallback): `.claude/skills/hello-world/SKILL.md`
- Project-local (fallback): `.agents/skills/hello-world/SKILL.md`

## Verification Markers

- FIXTURE_HARNESS: opencode
- FIXTURE_VERSION: 1.0.0
- FIXTURE_SOURCE: tests/smoke/opencode/fixtures/hello-world/SKILL.md
- FIXTURE_STATUS: STUB
