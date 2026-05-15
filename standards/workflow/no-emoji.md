---
name: no-emoji
description: Do not add emoji to source code files, configuration files, or technical documentation.
tags:
  - origin:original
  - tier:global
  - category:standard
---

# No Emoji in Source

> Scope: All skills, agents, hooks, scripts, standards, and technical
> documentation in this library. Loaded globally via `default_scope: global`.

## Rule

Do not add emoji to:

| Location | Forbidden pattern |
|----------|-------------------|
| Source code comments | A status symbol before "done". |
| Log messages | A launch symbol before "started". |
| Identifiers or string literals | A checkmark-like symbol as a status value. |
| Error messages | A failure symbol before "invalid input". |
| Configuration files | YAML, TOML, or JSON keys and values. |
| Technical documentation | ADRs, READMEs, changelogs, and standards. |

## Exception

User-facing UI strings may use emoji only when the design spec explicitly
requires them, such as a status badge whose visual label is defined in a design
file.

## Rationale

- Emoji render inconsistently across terminals, editors, and log viewers.
- Diffs become noisy and harder to read.
- Some CI/CD systems and log parsers strip or mishandle multi-byte emoji
  codepoints.
