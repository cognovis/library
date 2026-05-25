# Hook and Permission Preservation Audit

Bead: `CL-uqug`  
Run: `fdcdb7e9-583b-4762-9b3d-e19953f2ada7`  
Date: 2026-05-25

## Capability Matrix

| Adapter | Hook Type | Hook Preservation Status | Evidence/Blocker |
|---------|-----------|--------------------------|------------------|
| `claude-agent` (`claude -p`) | `PreToolUse`, `PostToolUse` | blocked | `~/.claude/settings.json` contains `PreToolUse` and `PostToolUse` hooks, but the live leaf smoke returned `Not logged in` before a tool invocation could prove hook participation. |
| `codex-impl` (`codex exec`) | `PreToolUse`, `PostToolUse` | separate-harness | Codex has an independent hook chain in `~/.codex/hooks.json`; this is not Claude Code hook preservation. |
| `codex-exec` (`codex exec`) | `PreToolUse`, `PostToolUse` | separate-harness | Codex has an independent hook chain in `~/.codex/hooks.json`; this is not Claude Code hook preservation. |
| `cursor-composer` | Cursor extension system | not-applicable | Cursor uses its own extension and permission mechanism, not the Claude Code or Codex hook chain. Cursor mutating workflow execution remains outside this runtime approval. |

## Claude Leaf Smoke

Command:

```bash
timeout 45 claude -p --output-format json "Return the string HOOK_TEST_COMPLETE with no other output"
```

Observed result:

```json
{"type":"result","subtype":"success","is_error":true,"api_error_status":null,"duration_ms":12,"duration_api_ms":0,"num_turns":1,"result":"Not logged in \u00b7 Please run /login","stop_reason":"stop_sequence","session_id":"8aaab055-95be-44db-99c7-765bc10eeb08","total_cost_usd":0,"usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0,"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0},"inference_geo":"","iterations":[],"speed":"standard"},"modelUsage":{},"permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off","uuid":"8531055b-d77a-49c0-8876-0bedac1c382a"}
```

Exit code: `1`.

Interpretation: the subprocess path exists and returns Claude JSON, but the local
Claude CLI is not authenticated in this execution environment. Because the prompt
did not reach a successful model turn and did not request a Bash tool call, this
run cannot prove `PreToolUse` or `PostToolUse` hook participation inside the
spawned leaf process.

Reproduction steps after authentication:

```bash
claude /login
timeout 45 claude -p --output-format json "Use Bash to run: printf HOOK_TEST_COMPLETE"
```

Expected verification signal: a successful result plus an independently observed
Claude hook log/audit entry for the leaf session showing the Bash `PreToolUse`
and matching `PostToolUse` participation.

## Config Review

Claude config reviewed:

```bash
sed -n '1,220p' ~/.claude/settings.json
```

Relevant findings:

- `PreToolUse` matcher `Bash` runs `/Users/malte/.local/bin/dcg`.
- `PostToolUse` matcher `Bash` runs `python3 /Users/malte/.claude/hooks/bd-cache-invalidator.py`.
- Additional session lifecycle hooks are configured, but they do not by
  themselves prove spawned leaf tool-use preservation.

Codex config reviewed:

```bash
sed -n '1,220p' ~/.codex/hooks.json
```

Relevant findings:

- Codex has a separate `PreToolUse` matcher `Bash` running `/Users/malte/.local/bin/dcg`.
- Codex has separate `SessionStart` and `Stop` hooks.
- This establishes a separate Codex harness hook chain, not preservation of
  Claude Code hooks in a Codex leaf.

## Mutating Execution Decision

Only adapters with preservation status `verified` may run mutating workflow
execution.

Current statuses:

- `claude-agent`: `blocked`
- `codex-impl`: `separate-harness`
- `codex-exec`: `separate-harness`
- `cursor-composer`: `not-applicable`
- any unlisted adapter: `unknown`

Therefore no listed adapter is approved for mutating workflow execution from the
workflow runtime at this time. Read-only workflow leaves remain allowed.

## Follow-Up Decision

Codex preservation is not fully verified as workflow leaf behavior; it is only
documented as a separate harness with its own hook chain. A follow-up bead is
required for Codex-specific hook preservation smoke evidence.

Cursor is explicitly waived for this bead because Cursor uses a separate system,
not the Claude Code or Codex hook mechanism. A future Cursor adapter bead should
define its own permission preservation criteria before mutating workflow use.
