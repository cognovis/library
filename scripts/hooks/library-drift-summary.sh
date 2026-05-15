#!/usr/bin/env bash
# library-drift-summary.sh — Session-start hook for library drift detection.
# Opt-in: add to ~/.claude/hooks/ as a SessionStart hook.
# Does NOT auto-install; user must link manually.

set -uo pipefail

HOOK_REAL_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" || echo "${BASH_SOURCE[0]}")")" && pwd)"
LIBRARY_PY="$(cd "$HOOK_REAL_DIR/../.." && pwd)/scripts/library.py"

# Fallback: if library.py not found via resolved path, search from working directory
# (hooks run in the project root during session start)
if [[ ! -f "$LIBRARY_PY" ]]; then
    CANDIDATE="$PWD/scripts/library.py"
    [[ -f "$CANDIDATE" ]] && LIBRARY_PY="$CANDIDATE"
fi

# Fail silently if library.py not found (repo not yet set up)
[[ -f "$LIBRARY_PY" ]] || exit 0

# Local drift — exit code 2 means drift, 0 means clean; capture separately
DRIFT_JSON=$(python3 "$LIBRARY_PY" audit --scope project --project "$PWD" --drift-only --json 2>/dev/null; true)
DRIFT_STATUS=$(echo "$DRIFT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")

# Upstream status — exit code 2 means behind, 0 means current
STATUS_JSON=$(python3 "$LIBRARY_PY" status --scope project --project "$PWD" --json 2>/dev/null; true)
OVERALL=$(echo "$STATUS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('overall','unknown'))" 2>/dev/null || echo "unknown")

# Print summary only if issues found
if [[ "$DRIFT_STATUS" == "drift" || "$OVERALL" == "behind" ]]; then
    echo "## Library Drift Summary"
    if [[ "$DRIFT_STATUS" == "drift" ]]; then
        echo "### Local drift (files edited since install):"
        echo "$DRIFT_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for e in d.get('entries',[]):
    print(f\"  DRIFT: {e['primitive']}:{e['name']}\")
" 2>/dev/null || true
    fi
    if [[ "$OVERALL" == "behind" ]]; then
        echo "### Upstream drift (source repo has new commits):"
        echo "$STATUS_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for e in d.get('entries',[]):
    if e.get('behind'):
        print(f\"  BEHIND: {e['primitive']}:{e['name']} ({e['installed_sha'][:8]} -> {str(e.get('remote_sha','?'))[:8]})\")
" 2>/dev/null || true
    fi
fi
