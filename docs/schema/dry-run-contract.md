# Installer Dry-Run JSON Contract

contract_version: "1"

This document defines the JSON envelope emitted by `scripts/library.py <primitive> use --dry-run --json`.
The contract applies to skill, standard, agent, prompt, script, model-standard, agent-base, MCP, and
guardrail installers.

## Schema

```json
{
  "type": "object",
  "required": [
    "status",
    "operations",
    "summary",
    "target_paths",
    "harness_routing",
    "conflict_policy",
    "lockfile_changes",
    "requires_user_confirmation"
  ],
  "properties": {
    "status": { "const": "dry-run" },
    "operations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["operation", "path", "details"],
        "properties": {
          "operation": { "type": "string" },
          "path": { "type": "string" },
          "target": { "type": "string" },
          "details": { "type": "string" },
          "existing_target": { "type": "boolean" }
        },
        "additionalProperties": true
      }
    },
    "summary": { "type": "string" },
    "target_paths": {
      "type": "array",
      "items": { "type": "string" }
    },
    "harness_routing": {
      "type": ["string", "null"],
      "enum": ["claude_code", "codex", "all", null]
    },
    "conflict_policy": {
      "type": "string",
      "enum": ["overwrite", "merge", "skip", "fail"]
    },
    "lockfile_changes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "operation", "entry"],
        "properties": {
          "path": { "type": "string" },
          "operation": { "enum": ["upsert", "remove"] },
          "entry": { "type": "string" }
        },
        "additionalProperties": true
      }
    },
    "requires_user_confirmation": { "type": "boolean" }
  },
  "additionalProperties": true
}
```

## Fields

- `status`: Always `dry-run`.
- `operations`: Ordered planned writes or related actions. If a path in `target_paths` already exists,
  the matching operation includes `existing_target: true`.
- `summary`: Human-readable one-line preview.
- `target_paths`: Files or directories the installer would write for the primitive itself, excluding
  cache and lockfile paths.
- `harness_routing`: Requested harness route. Installers without harness-specific routing emit `null`.
- `conflict_policy`: Installer policy for existing targets. Current primitive installers overwrite existing
  primitive targets and report that detection on the matching operation.
- `lockfile_changes`: Planned `.library.lock` mutation records.
- `requires_user_confirmation`: Whether the dry-run found a change that needs interactive approval before
  execution. Current installers emit `false`.

## Examples

Skill:

```json
{
  "status": "dry-run",
  "operations": [
    { "operation": "materialize_cache", "path": "/Users/me/.local/share/library/skills/local/example@<commit-sha>/", "details": "copy source -> Layer-B cache" },
    { "operation": "vendor_copy", "path": "/repo/.agents/skills/example", "details": "Layer-C vendored copy /repo/.agents/skills/example <- cache" }
  ],
  "summary": "Would install skill 'example' to /repo/.agents/skills/example",
  "target_paths": ["/repo/.agents/skills/example", "/repo/.claude/skills/example"],
  "harness_routing": null,
  "conflict_policy": "overwrite",
  "lockfile_changes": [{ "path": "/repo/.library.lock", "operation": "upsert", "entry": "example" }],
  "requires_user_confirmation": false
}
```

Agent with Codex routing:

```json
{
  "status": "dry-run",
  "operations": [
    { "operation": "vendor_copy", "path": "/repo/.codex/agents/example.toml", "details": "Layer-C vendored copy /repo/.codex/agents/example.toml <- cache" }
  ],
  "summary": "Would install agent 'example' to /repo/.codex/agents/example.toml",
  "target_paths": ["/repo/.codex/agents/example.toml"],
  "harness_routing": "codex",
  "conflict_policy": "overwrite",
  "lockfile_changes": [{ "path": "/repo/.library.lock", "operation": "upsert", "entry": "example" }],
  "requires_user_confirmation": false
}
```

Simple-file primitives (`prompt`, `script`, `model-standard`, `agent-base`) use the same envelope with
their resolved single target file in `target_paths`.

MCP and guardrail installers use harness config files as targets. For project scope they report project-local
config paths such as `/repo/.claude/settings.json`, `/repo/.codex/config.toml`, or `/repo/.codex/hooks.json`.
