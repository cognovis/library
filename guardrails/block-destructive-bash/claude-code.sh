#!/usr/bin/env bash
# block-destructive-bash — Claude Code PreToolUse guardrail
#
# Blocks destructive bash commands that cannot be undone:
#   - Recursive forced deletes
#   - Force-pushes to git remotes
#   - SQL destructive DDL (DROP TABLE, TRUNCATE TABLE)
#   - Low-level disk writes (dd if=)
#   - Windows drive format (format c:)
#
# Installation: Add to .claude/hooks/ or ~/.claude/hooks/
# Register in settings.json under hooks.PreToolUse with matcher "Bash"
#
# Claude Code hook contract:
#   Input:  JSON object on STDIN — { "tool_name": "Bash", "tool_input": { "command": "..." } }
#   Output: Exit 0 → allow; Exit 2 → block (print JSON message to stdout)
#
# References:
#   - https://docs.anthropic.com/claude-code/hooks
#   - library.yaml guardrails[block-destructive-bash]

set -euo pipefail

# Read tool input from STDIN (Claude Code hook contract)
TOOL_INPUT=$(cat)

if [[ -z "$TOOL_INPUT" ]]; then
    # No input — not a Bash tool call or called directly; allow
    exit 0
fi

# Extract the command string from the JSON input
# Claude Code passes: { "tool_name": "Bash", "tool_input": { "command": "..." } }
COMMAND=$(echo "$TOOL_INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    # Support both direct input and nested tool_input wrapper
    if 'tool_input' in data:
        print(data['tool_input'].get('command', ''))
    else:
        print(data.get('command', ''))
except Exception:
    print('')
")

if [[ -z "$COMMAND" ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Destructive pattern detection
# -----------------------------------------------------------------------

BLOCKED_REASON=""

# Pattern 1: rm with recursive + force flags (any order, with optional paths)
# Matches: rm -rf, rm -fr, rm -rf /, rm --recursive --force, rm -rf path, etc.
# Also matches end of command and common separators (;, &&, |)
if echo "$COMMAND" | grep -qiE '(^|[[:space:]];|&&|\|)rm[[:space:]]+(-[a-z]*r[a-z]*f[a-z]*|--recursive[[:space:]]+--force|--force[[:space:]]+--recursive)([[:space:]]|$)'; then
    BLOCKED_REASON="Recursive forced delete (rm -rf) detected. This irreversibly deletes files."
fi

# Pattern 2: git push with force flags
# Matches:
#   git push --force
#   git push -f
#   git push --force origin main
#   git push origin main --force
#   git push origin --force
#   git push -f origin
# Requires "git push" followed anywhere by --force or -f (as a standalone flag)
if echo "$COMMAND" | grep -qiE 'git[[:space:]]+push([[:space:]]+[^[:space:]]+)*[[:space:]]+(--force|-f)([[:space:]]|$)'; then
    BLOCKED_REASON="Force push to git remote detected. This can overwrite remote history irreversibly."
fi
# Also catch --force appearing before the remote/branch
if echo "$COMMAND" | grep -qiE 'git[[:space:]]+push[[:space:]]+(--force|-f)([[:space:]]|$)'; then
    BLOCKED_REASON="Force push to git remote detected. This can overwrite remote history irreversibly."
fi

# Pattern 3: SQL DROP TABLE / DROP DATABASE
if echo "$COMMAND" | grep -qiE '(DROP[[:space:]]+(TABLE|DATABASE|SCHEMA)[[:space:]])'; then
    BLOCKED_REASON="SQL DROP TABLE/DATABASE/SCHEMA detected. This irreversibly destroys data."
fi

# Pattern 4: SQL TRUNCATE TABLE
if echo "$COMMAND" | grep -qiE '(TRUNCATE[[:space:]]+(TABLE[[:space:]])?[a-zA-Z])'; then
    BLOCKED_REASON="SQL TRUNCATE TABLE detected. This irreversibly removes all rows from a table."
fi

# Pattern 5: dd writing to block devices or disk images
# Matches: dd if=... of=/dev/sda, dd if=... of=/dev/disk, etc.
if echo "$COMMAND" | grep -qiE '(^|[[:space:]]|;|&&|\|)dd[[:space:]]+.*of=/dev/'; then
    BLOCKED_REASON="dd writing to a block device detected. This can irreversibly overwrite disk data."
fi

# Pattern 6: Windows drive format (format c: or similar)
if echo "$COMMAND" | grep -qiE '(^|[[:space:]]|;|&&|\|)format[[:space:]]+[a-zA-Z]:'; then
    BLOCKED_REASON="Windows drive format command detected. This irreversibly destroys all data on the drive."
fi

# -----------------------------------------------------------------------
# Output result
# -----------------------------------------------------------------------

if [[ -n "$BLOCKED_REASON" ]]; then
    # Exit 2 = block the tool call, show message to user
    REASON_ESCAPED=$(echo "$BLOCKED_REASON" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip()))")
    python3 -c "
import json
message = {
    'decision': 'block',
    'reason': $REASON_ESCAPED + '\n\nIf this operation is truly needed, ask the user for explicit permission and have them run the command manually.'
}
print(json.dumps(message))
"
    exit 2
fi

# Command is safe — allow
exit 0
