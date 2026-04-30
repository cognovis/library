# Add a New Guardrail to the Library

## Context
Register a new guardrail in the library catalog. A guardrail is a deterministic
enforcement primitive that runs outside the LLM loop — the model cannot bypass it.
Each guardrail compiles to a per-harness native format (hooks, permission rules,
approval policies) and declares which harnesses it supports.

See `docs/PRIMITIVES.md` section 4 (Guardrail) and `docs/research/guardrails-mapping.md`
for the full capability matrix.

## Input
The user provides:
- Name (kebab-case, e.g. `block-destructive-bash`)
- Description (what it enforces)
- Purpose: `pre-tool-veto | post-tool-reaction | session-init | cleanup | audit-log`
- Source files per harness (at least one harness required)
- Supported harnesses and their capabilities

## Steps

### 1. Sync the Library Repo
Pull the latest catalog before modifying:
```bash
cd <LIBRARY_SKILL_DIR>
git pull
```

### 2. Validate Purpose and Harness Compatibility
Look up the guardrail's purpose in `docs/research/guardrails-mapping.md` to confirm
which harnesses natively support it:

| Purpose | Claude Code | Codex CLI | Codex Cloud | Pi | OpenCode |
|---------|-------------|-----------|-------------|-----|----------|
| `pre-tool-veto` | NATIVE (PreToolUse) | WORKAROUND (SessionStart) | BLUNT (approval_policy) | NATIVE | NATIVE |
| `post-tool-reaction` | NATIVE (PostToolUse) | NOT SUPPORTED | NOT SUPPORTED | NATIVE | NOT SUPPORTED |
| `session-init` | NATIVE (SessionStart) | NATIVE (SessionStart) | NOT SUPPORTED | PARTIAL | NOT SUPPORTED |
| `cleanup` | NATIVE (Stop/PreCompact) | PARTIAL (Stop only) | NOT SUPPORTED | NOT SUPPORTED | NOT SUPPORTED |
| `audit-log` | NATIVE (PostToolUse) | NOT SUPPORTED | NOT SUPPORTED | NATIVE | NOT SUPPORTED |

If a harness is listed as NOT SUPPORTED: omit it from the `capability` section.
If a harness is WORKAROUND or BLUNT: document the limitation in the `capability.note` field.

### 3. Prepare Source Files

Create the source directory:
```bash
mkdir -p guardrails/<name>/
```

For each supported harness, create the handler file:

| Harness | File | Format |
|---------|------|--------|
| `claude_code` | `guardrails/<name>/claude-code.sh` | bash or python script |
| `codex_cli` | `guardrails/<name>/codex-cli.mjs` | Node ESM module |
| `codex_cloud` | `guardrails/<name>/codex-cloud-config-fragment.toml` | TOML config fragment |
| `pi` | `guardrails/<name>/pi-extension.ts` | TypeScript extension |
| `opencode` | `guardrails/<name>/opencode-fragment.json` | JSON rules fragment |

**Claude Code hook contract** (the primary implementation):
- Read `$CLAUDE_TOOL_INPUT` JSON for tool input
- Exit 0 → allow; Exit 2 → block (print JSON to stdout: `{"decision": "block", "reason": "..."}`)
- For Bash tool: check `data["command"]` string for destructive patterns
- For pre-tool-veto: use `matcher` field in settings.json to scope to specific tools

Example minimal claude-code.sh:
```bash
#!/usr/bin/env bash
set -euo pipefail
COMMAND=$(echo "${CLAUDE_TOOL_INPUT:-}" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('command',''))
except: print('')
")
if echo "$COMMAND" | grep -qE '<pattern>'; then
    python3 -c "import json; print(json.dumps({'decision':'block','reason':'<reason>'}))"
    exit 2
fi
exit 0
```

Make the script executable:
```bash
chmod +x guardrails/<name>/claude-code.sh
```

### 4. Build the library.yaml Entry

Add the guardrail entry under `guardrails:` in `library.yaml`. Follow the existing
`block-destructive-bash` entry as a pattern:

```yaml
guardrails:
  - name: <name>
    description: <one-line description of what is enforced>
    purpose: <purpose>
    capability:
      claude_code:
        events: [PreToolUse]           # adjust to actual events used
        handler: bash-script
        matcher: Bash                  # tool name to match, or omit for all tools
      codex_cli:                       # omit if NOT SUPPORTED for this purpose
        events: [SessionStart]
        handler: node-mjs
        note: "Capability limitation note here"
        mismatch_warning: "Warning text shown to user during use-guardrail"
      codex_cloud:                     # omit if NOT SUPPORTED
        mechanism: approval_policy
        config_key: approval_policy
        recommended_value: all
        note: "..."
        mismatch_warning: "..."
      opencode:                        # omit if NOT SUPPORTED
        mechanism: permission-rule
        config_key: rules
    sources:
      claude_code: guardrails/<name>/claude-code.sh
      codex_cli: guardrails/<name>/codex-cli.mjs     # omit if not created
      codex_cloud: guardrails/<name>/codex-cloud-config-fragment.toml
      opencode: guardrails/<name>/opencode-fragment.json
    tags:
      - <relevant-tags>
```

**YAML formatting rules:**
- 2-space indentation
- Omit harness keys where support is NOT available (not just unsupported but omit entirely)
- Keep entries alphabetically sorted by name within the `guardrails:` list
- `mismatch_warning` text is shown verbatim to the user by `use-guardrail`

### 5. Validate the Entry
Run the schema validator to confirm the entry is well-formed:
```bash
python3 tests/test_guardrails_schema.py
# or
python3 -m pytest tests/test_guardrails_schema.py -v
```

All tests must pass before committing.

### 6. Commit and Push
```bash
cd <LIBRARY_SKILL_DIR>
git add library.yaml guardrails/<name>/
git commit -m "library: add guardrail <name>"
git push
```

### 7. Confirm
Tell the user:
- The guardrail has been added to the catalog
- Which harnesses it supports natively vs. with workarounds
- Any capability limitations (WORKAROUND or BLUNT harnesses)
- How to install it with: `/library use-guardrail <name>`
