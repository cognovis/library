---
adr: "0006"
title: "Meta may host installer-coupled guardrail sources"
status: accepted
date: 2026-05-15
bead: CL-eca
deciders:
  - Malte Sussdorff
supersedes: []
superseded_by: []
related_adrs: ["0002", "0005"]
---

# ADR-0006: Meta may host installer-coupled guardrail sources

## Context

ADR-0002 separates Library platform code from marketplace content: `meta`
owns catalog, schema, installers, launchers, and docs; `cognovis-core` and
`sussdorff-core` own reusable primitive source files.

Healthcare guardrails introduce a narrow exception. `scripts/install-hook.py`
binds directly to local `guardrails/<name>/<harness>` paths and registers those
files into harness configuration. For these installer-coupled hooks, keeping
the source beside the installer reduces drift between catalog metadata,
installer behavior, schema tests, and runtime source contracts.

## Decision

`meta` may host guardrail source files under `guardrails/<name>/` when all of
the following are true:

- the guardrail is installed by platform code in this repo;
- the catalog entry points to the local `guardrails/<name>/` source path;
- the source is part of the installer contract or test fixture surface;
- any Codex/Claude support gaps are explicit in catalog fields such as
  `codex_status`, `sources`, and `runtime_requirements`.

This exception does not make `meta` a general marketplace. Skills, agents,
prompts, standards, model standards, and golden prompts still belong in source
marketplaces unless a separate ADR grants a platform-source exception.

## Duplicate Source Policy

An installer-coupled guardrail has one canonical source. If an older marketplace
copy exists, replace it with documentation pointing to the `meta/guardrails/`
path or remove it in the owning marketplace. Do not keep two editable copies
without a CI drift check.

## Consequences

- `library.yaml` may use `https://github.com/cognovis/library/blob/main/guardrails/...`
  for guardrail source URLs.
- `docs/ARCHITECTURE.md` and `docs/PRIMITIVES.md` must describe guardrails as a
  platform-source exception.
- Reviewers should treat new non-guardrail source files in `meta` as suspect
  unless they are covered by another ADR.
