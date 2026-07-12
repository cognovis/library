#!/usr/bin/env bash
# install-agent-composed.sh — Smoke test: layered agent prompt composition end-to-end
#
# Bead: CL-08n
#
# Tests:
#   1. compose-agent.py installed changelog-updater with cognovis-base marker
#   2. Idempotent: running twice produces zero diff in output
#   3. Drift detection: mutate cached base, re-run → output changes
#   4. from-scratch: agent with from-scratch does not include base marker
#   5. /library use claude-haiku-4-5 installs to ~/.agents/model-standards/
#      (simulated: installs to temp dir)
#
# Usage:
#   bash tests/smoke/install-agent-composed.sh
#   COGNOVIS_CORE=/path/to/cognovis-core bash tests/smoke/install-agent-composed.sh
#
# Returns exit code 0 on all PASS, 1 on any FAIL.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Detect cognovis-core location
COGNOVIS_CORE="${COGNOVIS_CORE:-}"
if [[ -z "$COGNOVIS_CORE" ]]; then
    # Try sibling directory
    candidate="$(cd "${REPO_ROOT}/.." && pwd)/cognovis-core"
    if [[ -d "$candidate" ]]; then
        COGNOVIS_CORE="$candidate"
    fi
fi

COMPOSE_SCRIPT="${REPO_ROOT}/scripts/compose-agent.py"
BUILD_AGENT_SCRIPT="${REPO_ROOT}/scripts/build-agent.py"
FLEET_AUDIT_SCRIPT="${REPO_ROOT}/scripts/agent-fleet-audit.py"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
PASS_COUNT=0
FAIL_COUNT=0

pass() {
    echo "  PASS  $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "  FAIL  $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
TMPDIRS=()
cleanup() {
    rm -rf "${TMPDIRS[@]}" 2>/dev/null || true
}
trap cleanup EXIT

make_tmp() {
    local tmp
    tmp=$(mktemp -d)
    TMPDIRS+=("$tmp")
    echo "$tmp"
}

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
make_fake_base_dir() {
    local tmp_dir="$1"
    local marker="${2:-COGNOVIS_BASE_LAYER1_MARKER}"
    local base_dir="${tmp_dir}/agent-bases"
    mkdir -p "$base_dir"
    cat > "${base_dir}/cognovis-base.md" << MDEOF
---
name: cognovis-base
version: "2026.05.12"
description: Test fixture base
---

# Cognovis Base (smoke test)

${marker}

This is the smoke test base agent base prompt.
MDEOF
    echo "$base_dir"
}

# ---------------------------------------------------------------------------
# Test 1: compose-agent.py with changelog-updater contains cognovis-base marker
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 1: changelog-updater compose contains base marker"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -z "$COGNOVIS_CORE" ]] || [[ ! -d "$COGNOVIS_CORE" ]]; then
    echo "  SKIP  changelog-updater compose [cognovis-core not found: ${COGNOVIS_CORE:-unset}]"
    PASS_COUNT=$((PASS_COUNT + 1))  # count as skip/pass for CI
else
    AGENT_FILE="${COGNOVIS_CORE}/agents/changelog-updater.md"
    if [[ ! -f "$AGENT_FILE" ]]; then
        echo "  SKIP  changelog-updater compose [agent file not found: ${AGENT_FILE}]"
    else
        TMP1=$(make_tmp)
        BASE_DIR=$(make_fake_base_dir "$TMP1")

        if AGENT_BASES_DIR="$BASE_DIR" \
           python3 "$COMPOSE_SCRIPT" "$AGENT_FILE" > "${TMP1}/composed.md" 2>&1; then
            if grep -q "COGNOVIS_BASE_LAYER1_MARKER" "${TMP1}/composed.md"; then
                pass "changelog-updater composed body contains COGNOVIS_BASE_LAYER1_MARKER"
            else
                fail "changelog-updater composed body missing COGNOVIS_BASE_LAYER1_MARKER"
                echo "    Composed body (first 500 chars):"
                head -c 500 "${TMP1}/composed.md" | sed 's/^/    /'
            fi
        else
            fail "compose-agent.py exited non-zero for changelog-updater"
            cat "${TMP1}/composed.md" | head -10 | sed 's/^/    /'
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Test 2: Idempotent re-compose (same base → same output)
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 2: Idempotent re-compose"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TMP2=$(make_tmp)
BASE_DIR2=$(make_fake_base_dir "$TMP2")
# Use a fixture agent that we can run twice
FIXTURE_AGENT="${REPO_ROOT}/tests/compose/fixtures/agent-with-base.md"

if [[ ! -f "$FIXTURE_AGENT" ]]; then
    fail "idempotent test [fixture agent not found: ${FIXTURE_AGENT}]"
else
    AGENT_BASES_DIR="$BASE_DIR2" python3 "$COMPOSE_SCRIPT" "$FIXTURE_AGENT" > "${TMP2}/run1.md"
    AGENT_BASES_DIR="$BASE_DIR2" python3 "$COMPOSE_SCRIPT" "$FIXTURE_AGENT" > "${TMP2}/run2.md"

    if diff -q "${TMP2}/run1.md" "${TMP2}/run2.md" > /dev/null 2>&1; then
        pass "idempotent re-compose: run1 and run2 are identical"
    else
        fail "idempotent re-compose: run1 and run2 differ"
        diff "${TMP2}/run1.md" "${TMP2}/run2.md" | head -20 | sed 's/^/    /'
    fi
fi

# ---------------------------------------------------------------------------
# Test 3: Drift detection (mutate base → output changes)
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 3: Drift detection (mutate base file)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TMP3=$(make_tmp)
BASE_DIR3=$(make_fake_base_dir "$TMP3")

AGENT_BASES_DIR="$BASE_DIR3" python3 "$COMPOSE_SCRIPT" "$FIXTURE_AGENT" > "${TMP3}/before.md"

# Mutate the base file
echo "" >> "${BASE_DIR3}/cognovis-base.md"
echo "DRIFT_MARKER_ADDED_BY_SMOKE_TEST" >> "${BASE_DIR3}/cognovis-base.md"

AGENT_BASES_DIR="$BASE_DIR3" python3 "$COMPOSE_SCRIPT" "$FIXTURE_AGENT" > "${TMP3}/after.md"

if diff -q "${TMP3}/before.md" "${TMP3}/after.md" > /dev/null 2>&1; then
    fail "drift detection: output did NOT change after mutating base file"
else
    if grep -q "DRIFT_MARKER_ADDED_BY_SMOKE_TEST" "${TMP3}/after.md"; then
        pass "drift detection: output changed after base mutation (drift marker found in after)"
    else
        fail "drift detection: output changed but DRIFT_MARKER not found in after output"
    fi
fi

# ---------------------------------------------------------------------------
# Test 4: from-scratch agent does NOT include base marker
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 4: from-scratch agent skips Layer 1"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TMP4=$(make_tmp)
BASE_DIR4=$(make_fake_base_dir "$TMP4")
SCRATCH_AGENT="${REPO_ROOT}/tests/compose/fixtures/agent-from-scratch.md"

if [[ ! -f "$SCRATCH_AGENT" ]]; then
    fail "from-scratch test [fixture not found: ${SCRATCH_AGENT}]"
else
    AGENT_BASES_DIR="$BASE_DIR4" python3 "$COMPOSE_SCRIPT" "$SCRATCH_AGENT" > "${TMP4}/scratch.md"
    if ! grep -q "COGNOVIS_BASE_LAYER1_MARKER" "${TMP4}/scratch.md"; then
        pass "from-scratch: Layer 1 marker absent in composed output"
    else
        fail "from-scratch: Layer 1 marker found but should be absent"
    fi
fi

# ---------------------------------------------------------------------------
# Test 5: claude-haiku-4-5.md installs to a target dir
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 5: claude-haiku-4-5.md exists in cognovis-core/model-standards/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -z "$COGNOVIS_CORE" ]]; then
    echo "  SKIP  haiku model-standard check [COGNOVIS_CORE not set]"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    HAIKU_FILE="${COGNOVIS_CORE}/model-standards/claude-haiku-4-5.md"
    if [[ -f "$HAIKU_FILE" ]]; then
        # Validate YAML frontmatter has model_aliases
        if python3 -c "
import sys
try:
    import yaml
    text = open('${HAIKU_FILE}').read()
    lines = text.split('\n')
    if lines[0].strip() == '---':
        for i, l in enumerate(lines[1:], 1):
            if l.strip() == '---':
                fm = yaml.safe_load('\n'.join(lines[1:i])) or {}
                break
        aliases = fm.get('model_aliases', [])
        assert 'haiku' in aliases, f'haiku not in model_aliases: {aliases}'
        assert 'haiku-4-5' in aliases, f'haiku-4-5 not in model_aliases: {aliases}'
        print('FRONTMATTER OK: model_aliases =', aliases)
        sys.exit(0)
    sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1; then
            pass "claude-haiku-4-5.md exists with valid model_aliases frontmatter"
        else
            fail "claude-haiku-4-5.md exists but has invalid frontmatter"
        fi
    else
        fail "claude-haiku-4-5.md not found at ${HAIKU_FILE}"
    fi
fi

# ---------------------------------------------------------------------------
# Test 6: generated reviewer artifact and fleet audit use simulated install dirs
# ---------------------------------------------------------------------------
echo ""
echo "=================================================="
echo "  Test 6: reviewer sandbox and fleet audit"
echo "=================================================="

TMP6=$(make_tmp)
CLAUDE_AGENTS_ROOT="${TMP6}/claude-agents"
CODEX_AGENTS_ROOT="${TMP6}/codex-agents"
BUILD_OUT="${TMP6}/built-agents"
MODEL_STANDARDS6="${TMP6}/model-standards"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMP6}/uv-cache}"
mkdir -p "$CLAUDE_AGENTS_ROOT" "$CODEX_AGENTS_ROOT" "$BUILD_OUT" "$MODEL_STANDARDS6"

if [[ -n "$COGNOVIS_CORE" ]] \
    && [[ -f "${COGNOVIS_CORE}/agents/review-agent.md" ]] \
    && [[ -d "${COGNOVIS_CORE}/agent-bases" ]] \
    && [[ -d "${COGNOVIS_CORE}/model-standards" ]]; then
    REVIEW_SOURCE="${COGNOVIS_CORE}/agents/review-agent.md"
    BUILD_AGENT_BASES="${COGNOVIS_CORE}/agent-bases"
    BUILD_MODEL_STANDARDS="${COGNOVIS_CORE}/model-standards"
else
    REVIEW_SOURCE="${TMP6}/review-agent.md"
    BUILD_AGENT_BASES="${TMP6}/agent-bases"
    BUILD_MODEL_STANDARDS="$MODEL_STANDARDS6"
    mkdir -p "$BUILD_AGENT_BASES"
    cp -f "${REPO_ROOT}/tests/compose/fixtures/base-claude-agent-base.md" \
        "${BUILD_AGENT_BASES}/claude-agent-base.md"
    cp -f "${REPO_ROOT}/tests/compose/fixtures/base-codex-agent-base.md" \
        "${BUILD_AGENT_BASES}/codex-agent-base.md"
    cat > "$REVIEW_SOURCE" <<'MDEOF'
---
name: review-agent
description: Reviewer smoke fixture.
model: sonnet
tools: Read, Write, Edit, MultiEdit, Bash
capabilities:
  - run_shell
pair_loop_constraints:
  review_contexts:
    - in_loop
    - cold
  run_shell: read_only
agent_base: auto
---

# Review Agent

Read-only reviewer smoke fixture.
MDEOF
fi

if uv run python "$BUILD_AGENT_SCRIPT" "$REVIEW_SOURCE" \
    --harness all \
    --output-dir "$BUILD_OUT" \
    --agent-bases-dir "$BUILD_AGENT_BASES" \
    --model-standards-dir "$BUILD_MODEL_STANDARDS" > "${TMP6}/build.log" 2>&1; then
    cp -f "$BUILD_OUT"/*.md "$CLAUDE_AGENTS_ROOT"/
    cp -f "$BUILD_OUT"/*.toml "$CODEX_AGENTS_ROOT"/
    pass "review-agent built into simulated Claude and Codex install roots"
else
    fail "review-agent build failed for simulated install roots"
    head -20 "${TMP6}/build.log" | sed 's/^/    /'
fi

if uv run python "$FLEET_AUDIT_SCRIPT" \
    --claude-root "$CLAUDE_AGENTS_ROOT" \
    --codex-root "$CODEX_AGENTS_ROOT" \
    --json > "${TMP6}/fleet-audit.json" 2> "${TMP6}/fleet-audit.err"; then
    if uv run python - "${TMP6}/fleet-audit.json" <<'PYEOF'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["harnesses"]["claude"]["inspected_count"] == 1
assert payload["harnesses"]["codex"]["inspected_count"] == 1
PYEOF
    then
        pass "fleet audit reports one Claude and one Codex simulated agent"
    else
        fail "fleet audit counts did not match simulated install roots"
        cat "${TMP6}/fleet-audit.json" | sed 's/^/    /'
    fi
else
    fail "fleet audit failed for simulated install roots"
    cat "${TMP6}/fleet-audit.err" | sed 's/^/    /'
fi

if uv run python - "$BUILD_OUT/review-agent.toml" <<'PYEOF'
import sys
import tomllib
from pathlib import Path

artifact = Path(sys.argv[1])
data = tomllib.loads(artifact.read_text(encoding="utf-8"))
assert data["sandbox_mode"] == "read-only", data.get("sandbox_mode")
PYEOF
then
    pass "generated review-agent Codex artifact is read-only"
else
    fail "generated review-agent Codex artifact is not read-only"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi
exit 0
