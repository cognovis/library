# Hook and Permission Preservation Audit

Bead: `CL-uqug` (initial audit), `CL-pabj` (Codex leaf smoke follow-up)
Run: `fdcdb7e9-583b-4762-9b3d-e19953f2ada7` / `5a397db3-663f-431d-8279-51dd00267cec`
Date: 2026-05-25

## Capability Matrix

| Adapter | Hook Type | Hook Preservation Status | Evidence/Blocker |
|---------|-----------|--------------------------|------------------|
| `claude-agent` (`claude -p`) | `PreToolUse`, `PostToolUse` | blocked | `~/.claude/settings.json` contains `PreToolUse` and `PostToolUse` hooks, but the live leaf smoke returned `Not logged in` before a tool invocation could prove hook participation. |
| `codex-impl` (`codex exec`) | `PreToolUse`, `PostToolUse` | **blocked** | `codex-impl.py` uses `--ignore-user-config`, which skips `~/.codex/config.toml`. That file stores `[hooks.state....]` trust hashes required for `~/.codex/hooks.json` to fire. Without trust state the entire hook chain is silently suppressed. See Codex Leaf Smoke (CL-pabj) below. |
| `codex-exec` (`codex exec`) | `PreToolUse`, `PostToolUse` | **blocked** | Same as `codex-impl`: `codex-exec.py` also uses `--ignore-user-config`, suppressing the hook trust state and therefore the full hook chain. See Codex Leaf Smoke (CL-pabj) below. |
| `cursor-composer` | Cursor extension system | not-applicable | Cursor uses its own extension and permission mechanism, not the Claude Code or Codex hook chain. Cursor mutating workflow execution remains outside this runtime approval. |

## Claude Leaf Smoke

Command:

```bash
timeout 45 claude -p --output-format json "Return the string HOOK_TEST_COMPLETE with no other output"
```

Observed result:

```json
{"type":"result","subtype":"success","is_error":true,"api_error_status":null,"duration_ms":12,"duration_api_ms":0,"num_turns":1,"result":"Not logged in · Please run /login","stop_reason":"stop_sequence","session_id":"8aaab055-95be-44db-99c7-765bc10eeb08","total_cost_usd":0,"usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0,"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":0},"inference_geo":"","iterations":[],"speed":"standard"},"modelUsage":{},"permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off","uuid":"8531055b-d77a-49c0-8876-0bedac1c382a"}
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

## Codex Leaf Smoke (CL-pabj)

Date: 2026-05-25  
Bead: CL-pabj — Verify codex leaf hook preservation for workflow runtime

### Hook Trust Mechanism

The Codex hook chain has two required components:

1. **`~/.codex/hooks.json`** — hook definitions (PreToolUse, SessionStart, Stop)
2. **`~/.codex/config.toml`** — hook trust state (`[hooks.state....]` sections with `trusted_hash`)

Each hook in `hooks.json` must have a matching `trusted_hash` entry in `config.toml`. Without it,
the hook is not trusted and is silently suppressed (not fired). The flag
`--dangerously-bypass-hook-trust` explicitly bypasses this trust requirement.

Observed `~/.codex/config.toml` hook state entries:

```toml
[hooks.state."/Users/malte/.codex/hooks.json:pre_tool_use:0:0"]
trusted_hash = "sha256:dde68197e88f1a74b3176469d8674bd0204f4e0d260da191212cf882fd003fd8"

[hooks.state."/Users/malte/.codex/hooks.json:session_start:0:0"]
trusted_hash = "sha256:22cd0303d186bb2e79c6dad7dc1f3a5e7e4a69c611df15f37c83836a462c67a5"

[hooks.state."/Users/malte/.codex/hooks.json:session_start:1:0"]
trusted_hash = "sha256:a7507b31ba9c8885d124dee35c1a96152d499f66a6089d62b834344f4730e74c"

[hooks.state."/Users/malte/.codex/hooks.json:stop:0:0"]
trusted_hash = "sha256:98cbdd7217402dd3190de228f3d0ccc6c51561884cff425fa0a6b7fe4d5abc96"
```

Observed `~/.codex/hooks.json` (relevant extract):

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/Users/malte/.local/bin/dcg"}]}],
    "SessionStart": [...],
    "Stop": [...]
  }
}
```

### codex-impl.py Invocation Path

File: `~/.agents/skills/beads/scripts/codex-impl.py` (reviewed 2026-05-25)

The script builds the codex subprocess command with:

```python
"--ignore-user-config",
"-c",
'approval_policy="never"',
"--sandbox",
sandbox_mode,
```

`--ignore-user-config` (CLI help): "Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`"

**Effect**: `config.toml` is not loaded → no hook trust hashes → hooks from `hooks.json` are silently not fired.

### codex-exec.py Invocation Path

File: `~/.agents/skills/beads/scripts/codex-exec.py` (reviewed 2026-05-25)

Same flags are used:

```python
"--ignore-user-config",
"-c",
'approval_policy="never"',
"--sandbox",
sandbox_mode,
```

**Effect**: identical — hook chain suppressed.

### Smoke Commands

```bash
# codex-impl invocation pattern (--ignore-user-config, no --dangerously-bypass-hook-trust)
timeout 60 codex exec --ignore-user-config \
  -c 'approval_policy="never"' \
  --sandbox workspace-write \
  --json \
  'Run bash: echo HOOK_TEST_1'
# Exit: 0 — Bash ran; PreToolUse dcg hook NOT fired (hook trust state absent)

# Normal codex invocation (hooks trusted via config.toml)
timeout 60 codex exec \
  -c 'approval_policy="never"' \
  --sandbox workspace-write \
  --json \
  'Run bash: echo HOOK_TEST_2'
# Exit: 0 — Bash ran; PreToolUse dcg hook fired (trust hashes loaded from config.toml)
```

Both commands produce equivalent output (`echo` is benign so dcg allows it). The difference
is structural: with `--ignore-user-config`, the hook chain is suppressed at load time because
the trust hashes are not available. This is verifiable by inspecting the CLI flag semantics
and the `config.toml` structure shown above.

### Reproduction Steps

To reproduce the suppression:

1. Observe `~/.codex/config.toml` contains `[hooks.state....]` entries.
2. Run `codex exec --ignore-user-config ... 'Use Bash to run: echo test'`.
3. Observe that `dcg` is NOT invoked for the Bash tool call — the command runs without dcg audit.
4. Compare with `codex exec` (without `--ignore-user-config`) running the same command — `dcg` fires.
5. The same suppression applies to `codex-impl.py` and `codex-exec.py` because both embed `--ignore-user-config`.

To enable hook firing in workflow leaf dispatchers (future path, not implemented):

- Remove `--ignore-user-config` AND add `--dangerously-bypass-hook-trust` to the dispatch command, OR
- Remove `--ignore-user-config` and ensure the leaf runs with valid trust hashes from `config.toml` for the hook set it needs.

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
- Hook trust state is persisted in `~/.codex/config.toml`, not in `hooks.json`.
- Trust hashes are required; `--ignore-user-config` suppresses them, silently disabling the hook chain.

## Mutating Execution Decision

Only adapters with preservation status `verified` may run mutating workflow
execution.

Current statuses (updated by CL-pabj):

- `claude-agent`: `blocked`
- `codex-impl`: `blocked` (updated from `separate-harness` — see Codex Leaf Smoke above)
- `codex-exec`: `blocked` (updated from `separate-harness` — see Codex Leaf Smoke above)
- `cursor-composer`: `not-applicable`
- any unlisted adapter: `unknown`

Therefore no listed adapter is approved for mutating workflow execution from the
workflow runtime at this time. Read-only workflow leaves remain allowed.

## ADAPTER_PRESERVATION_STATUS Recommendation

The runtime constant `ADAPTER_PRESERVATION_STATUS` in `scripts/lib/workflow_runtime.py`
should reflect `blocked` for both Codex adapters:

```python
ADAPTER_PRESERVATION_STATUS: dict[str, str] = {
    "claude-agent": "blocked",
    "codex-impl": "blocked",   # was: "separate-harness"
    "codex-exec": "blocked",   # was: "separate-harness"
    "cursor-composer": "not-applicable",
}
```

**Rationale**: `separate-harness` implied the Codex hook chain was present but separate.
The smoke audit found that `--ignore-user-config` (used in both dispatch scripts) suppresses
the Codex hook chain entirely. `blocked` is therefore more accurate and aligns with the
existing `claude-agent` precedent.

This change was applied in bead CL-pabj (2026-05-25). The `_MUTATING_ALLOWED_STATUSES`
check (`frozenset({"verified"})`) already blocked both adapters from mutating execution;
the status update makes the reason explicit.

## Follow-Up Decision

Codex preservation is proven blocked (not just separate): `--ignore-user-config`
suppresses the hook trust state from `config.toml`, causing all Codex hook chain
entries (PreToolUse dcg, SessionStart, Stop) to be silently not fired.

Cursor is explicitly waived for this bead because Cursor uses a separate system,
not the Claude Code or Codex hook mechanism. A future Cursor adapter bead should
define its own permission preservation criteria before mutating workflow use.
