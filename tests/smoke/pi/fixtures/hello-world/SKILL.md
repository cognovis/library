---
name: hello-world
description: Smoke-test fixture skill for Pi harness (stub). Pi is not locally available — this fixture is a structural stub for MANUAL_VERIFICATION_REQUIRED paths.
argument-hint: [name]
---

# Hello World (Smoke Test Fixture — Pi Stub)

This is a stub fixture for the Pi harness. Pi is not locally available for automated testing.

## Status

MANUAL_VERIFICATION_REQUIRED — Pi runtime not available in CI or local development.

## Purpose

Document the expected install paths for Pi once runtime is available:
- Project-local (primary): `.pi/skills/hello-world/SKILL.md`
- Project-local (fallback): `.agents/skills/hello-world/SKILL.md`
- User-global (primary):   `~/.pi/agent/skills/hello-world/SKILL.md`
- User-global (fallback):  `~/.agents/skills/hello-world/SKILL.md`

## Verification Markers

- FIXTURE_HARNESS: pi
- FIXTURE_VERSION: 1.0.0
- FIXTURE_SOURCE: tests/smoke/pi/fixtures/hello-world/SKILL.md
- FIXTURE_STATUS: STUB
