---
name: english-only
description: All source code must be in English, including comments, identifiers, log messages, and string literals.
tags:
  - origin:original
  - tier:global
  - category:standard
---

# English-Only Source Code

> Scope: All skills, agents, hooks, scripts, standards, and technical
> documentation in this library. Loaded globally via `default_scope: global`.

## Rule

All source code must be in English, including:

| Category | Rule |
|----------|------|
| Comments | English only. |
| Identifiers | English variable, function, class, and method names. |
| Log messages | English. |
| String literals | English for technical strings, error messages, and keys. |
| File names | English, kebab-case. |

## Exceptions

- User-facing strings, such as UI labels and end-user error messages, may be
  localized when the project requires it.
- Data values, such as test fixtures in another language, are permitted if the
  data itself is the subject.

## Non-Exceptions

This rule applies even when:

- The user prompt is in German or another language.
- The project domain is German-language, such as healthcare or accounting.
- A team member requests a comment in their native language.
