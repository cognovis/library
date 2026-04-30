---
name: hello-world
description: Smoke-test fixture skill for Codex harness. Prints a greeting. Used by tests/smoke to verify skill discovery and install path resolution.
argument-hint: [name]
---

# Hello World (Smoke Test Fixture)

This is a minimal skill fixture used by the cross-harness smoke tests.

## Purpose

Verify that Codex can discover and load a skill installed at:
- Project-local: `.agents/skills/hello-world/SKILL.md`
- User-global:   `~/.agents/skills/hello-world/SKILL.md`

## Usage

When invoked, greet the user:

> Hello from the hello-world smoke-test fixture! Harness: Codex.

If an argument (name) is provided, greet by name:

> Hello, <name>! Smoke test fixture running on Codex.

## Verification Markers

- FIXTURE_HARNESS: codex
- FIXTURE_VERSION: 1.0.0
- FIXTURE_SOURCE: tests/smoke/codex/fixtures/hello-world/SKILL.md
