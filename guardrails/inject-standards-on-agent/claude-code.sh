#!/usr/bin/env bash
# PreToolUse hook: inject project standards paths into Agent tool prompts
#
# When an Agent is spawned, this hook reads .claude/standards/index.yml,
# extracts all standard file paths, and outputs them as DECISION feedback.
# The agent sees this as context and can load the relevant standards.
#
# Does NOT block the tool call - only provides additional context.

set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only run for Agent tool calls
if [[ "$TOOL_NAME" != "Agent" ]]; then
  exit 0
fi

# Find the project root (git root, not worktree)
PROJECT_ROOT=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/.git$||')
STANDARDS_INDEX="$PROJECT_ROOT/.claude/standards/index.yml"

# Skip if no standards index exists
if [[ ! -f "$STANDARDS_INDEX" ]]; then
  exit 0
fi

# Check if the agent prompt already mentions standards
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
if echo "$PROMPT" | grep -qi "standards/"; then
  # Standards already referenced in prompt - no injection needed
  exit 0
fi

# Extract all standard paths from index.yml
PATHS=$(grep -E '^\s+- path:' "$STANDARDS_INDEX" | sed 's/.*path:[[:space:]]*//' | sed 's/[[:space:]]*$//')

if [[ -z "$PATHS" ]]; then
  exit 0
fi

# Build the feedback message
echo "IMPORTANT: This project has coding standards that subagents must follow."
echo "Before writing code, read the relevant standards from .claude/standards/:"
echo ""
while IFS= read -r path; do
  echo "  - .claude/standards/$path"
done <<< "$PATHS"
echo ""
echo "Match standards to the task domain (billing -> billing/, frontend -> frontend/, etc.)."
echo "Load at least the standards matching the code area being modified."
