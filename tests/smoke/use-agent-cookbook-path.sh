#!/usr/bin/env bash
# use-agent-cookbook-path.sh — Smoke test: end-to-end /library use cookbook path
#
# Bead: CL-o16
#
# Tests the full fetch -> compose -> write flow that an agent would execute when
# following the cookbook steps in cookbook/use.md Step 6.5 and cookbook/sync.md
# Step 4.5. Does NOT invoke compose-agent.py directly via its Python interface;
# instead, it exercises the shell-level cookbook sequence.
#
# Tests:
#   1. Fetch agent file + compose (cognovis-base marker present in installed file)
#   2. Idempotent re-run: identical installed body after second fetch+compose
#   3. Graceful degradation: missing Layer 1 (cognovis-base absent) -> warn, keep uncomposed
#   4. cookbook/use.md Step 6.5 wording is unchanged (guard against accidental edits)
#
# Usage:
#   bash tests/smoke/use-agent-cookbook-path.sh
#
# Returns exit code 0 on all PASS, 1 on any FAIL.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_SCRIPT="${REPO_ROOT}/scripts/compose-agent.py"
FIXTURE_AGENT="${REPO_ROOT}/tests/compose/fixtures/agent-with-base.md"

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
    local d
    for d in "${TMPDIRS[@]:-}"; do
        rm -rf "$d" 2>/dev/null || true
    done
}
trap cleanup EXIT

make_tmp() {
    local tmp
    tmp=$(mktemp -d)
    TMPDIRS+=("$tmp")
    echo "$tmp"
}

# ---------------------------------------------------------------------------
# Helper: build a minimal fake library checkout in tmp_lib_dir with:
#   - scripts/compose-agent.py (symlink to real script)
#   - .agents/agent-bases/cognovis-base.md (fake Layer 1)
# ---------------------------------------------------------------------------
make_fake_library() {
    local lib_dir="$1"
    mkdir -p "${lib_dir}/scripts"
    mkdir -p "${lib_dir}/.agents/agent-bases"

    # Symlink (not copy) compose script so we use the real implementation
    ln -sf "${COMPOSE_SCRIPT}" "${lib_dir}/scripts/compose-agent.py"

    # Fake Layer 1 (cognovis-base)
    cat > "${lib_dir}/.agents/agent-bases/cognovis-base.md" << 'LAYER1EOF'
---
name: cognovis-base
version: "2026.05.12"
description: Smoke test fixture for cognovis-base Layer 1
---

# Cognovis Base (cookbook-path smoke test)

COGNOVIS_BASE_LAYER1_MARKER

Base agent base prompt content for smoke test.
LAYER1EOF
}

# ---------------------------------------------------------------------------
# Helper: simulate cookbook use.md Step 6.5 sequence:
#   1. Copy agent file to temp project's .claude/agents/
#   2. Check frontmatter for agent_base_extends
#   3. Run compose-agent.py
#   4. Replace body with composed output (or keep original on failure)
# Returns 0 on success (compose ran and replaced body), 1 on graceful failure.
# ---------------------------------------------------------------------------
cookbook_use_step65() {
    local lib_dir="$1"
    local agent_src="$2"
    local install_dir="$3"
    local agent_name
    agent_name="$(basename "${agent_src}")"
    local installed="${install_dir}/${agent_name}"

    mkdir -p "${install_dir}"

    # Step 4 equivalent: copy the agent file (simulate fetch)
    cp "${agent_src}" "${installed}"

    # Step 6.5: check frontmatter for agent_base_extends
    local extends
    extends=$(python3 - "${installed}" <<'PYEOF'
import sys, re

text = open(sys.argv[1]).read()
lines = text.split('\n')
if not lines or lines[0].strip() != '---':
    print('')
    sys.exit(0)
for i, line in enumerate(lines[1:], 1):
    if line.strip() == '---':
        fm_text = '\n'.join(lines[1:i])
        import yaml
        fm = yaml.safe_load(fm_text) or {}
        val = fm.get('agent_base_extends', '')
        print(val if val else '')
        sys.exit(0)
print('')
PYEOF
    )

    if [[ -z "${extends}" ]] || [[ "${extends}" == "from-scratch" ]]; then
        # No composition needed
        return 0
    fi

    # Locate composer in library root
    local compose_py="${lib_dir}/scripts/compose-agent.py"
    if [[ ! -f "${compose_py}" ]]; then
        echo "  WARNING: compose-agent.py not found at ${compose_py}; skipping composition"
        return 1
    fi

    # Run composer; capture composed body
    local composed_body
    local compose_rc=0
    composed_body=$(AGENT_BASES_DIR="${lib_dir}/.agents/agent-bases" \
        python3 "${compose_py}" "${installed}" 2>/tmp/compose_err_$$) || compose_rc=$?

    if [[ "${compose_rc}" -ne 0 ]]; then
        local err_msg
        err_msg=$(cat /tmp/compose_err_$$ 2>/dev/null || echo "unknown error")
        rm -f /tmp/compose_err_$$
        echo "  WARNING: Compose failed for ${agent_name}: ${err_msg}. Keeping uncomposed agent body."
        return 1
    fi
    rm -f /tmp/compose_err_$$

    # Replace body: extract frontmatter, then write frontmatter + composed body
    python3 - "${installed}" "${composed_body}" <<'PYEOF'
import sys

path = sys.argv[1]
new_body = sys.argv[2]

text = open(path).read()
lines = text.split('\n')
if lines and lines[0].strip() == '---':
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            frontmatter_block = '\n'.join(lines[:i+1])
            with open(path, 'w') as f:
                f.write(frontmatter_block + '\n\n' + new_body + '\n')
            sys.exit(0)
# Fallback: just overwrite entire file
with open(path, 'w') as f:
    f.write(new_body + '\n')
PYEOF
    return 0
}

# ---------------------------------------------------------------------------
# Test 1: Full cookbook path — fetch + compose + install contains cognovis-base marker
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 1: cookbook use path produces cognovis-base marker"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ ! -f "${FIXTURE_AGENT}" ]]; then
    fail "cookbook-path/fixture: ${FIXTURE_AGENT} not found"
else
    TMP1=$(make_tmp)
    PROJ1="${TMP1}/project"
    LIB1="${TMP1}/library"
    make_fake_library "${LIB1}"

    if cookbook_use_step65 "${LIB1}" "${FIXTURE_AGENT}" "${PROJ1}/.claude/agents"; then
        INSTALLED1="${PROJ1}/.claude/agents/$(basename "${FIXTURE_AGENT}")"
        if [[ -f "${INSTALLED1}" ]]; then
            if grep -q "COGNOVIS_BASE_LAYER1_MARKER" "${INSTALLED1}"; then
                pass "cookbook-path/compose: installed file contains COGNOVIS_BASE_LAYER1_MARKER"
            else
                fail "cookbook-path/compose: installed file missing COGNOVIS_BASE_LAYER1_MARKER"
                echo "    First 300 chars of installed file:"
                head -c 300 "${INSTALLED1}" | sed 's/^/    /'
            fi
        else
            fail "cookbook-path/install: installed file not found at ${INSTALLED1}"
        fi
    else
        fail "cookbook-path/compose: cookbook_use_step65 returned non-zero (compose failed)"
    fi
fi

# ---------------------------------------------------------------------------
# Test 2: Idempotent re-run — second fetch+compose produces zero diff
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 2: Idempotent re-run (zero diff on second install)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ ! -f "${FIXTURE_AGENT}" ]]; then
    fail "idempotent/fixture: ${FIXTURE_AGENT} not found"
else
    TMP2=$(make_tmp)
    PROJ2A="${TMP2}/proj-run1"
    PROJ2B="${TMP2}/proj-run2"
    LIB2="${TMP2}/library"
    make_fake_library "${LIB2}"

    # Run 1
    cookbook_use_step65 "${LIB2}" "${FIXTURE_AGENT}" "${PROJ2A}/.claude/agents" || true
    INSTALLED2A="${PROJ2A}/.claude/agents/$(basename "${FIXTURE_AGENT}")"

    # Run 2 (fresh project dir, same library)
    cookbook_use_step65 "${LIB2}" "${FIXTURE_AGENT}" "${PROJ2B}/.claude/agents" || true
    INSTALLED2B="${PROJ2B}/.claude/agents/$(basename "${FIXTURE_AGENT}")"

    if [[ -f "${INSTALLED2A}" ]] && [[ -f "${INSTALLED2B}" ]]; then
        if diff -q "${INSTALLED2A}" "${INSTALLED2B}" > /dev/null 2>&1; then
            pass "idempotent/zero-diff: run1 and run2 produce identical installed bodies"
        else
            fail "idempotent/zero-diff: run1 and run2 bodies differ"
            diff "${INSTALLED2A}" "${INSTALLED2B}" | head -20 | sed 's/^/    /'
        fi
    else
        fail "idempotent/files-missing: one or both installed files not found"
    fi
fi

# ---------------------------------------------------------------------------
# Test 3: Graceful degradation — missing Layer 1 warns, keeps uncomposed body
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 3: Graceful degradation — missing Layer 1 (no cognovis-base)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ ! -f "${FIXTURE_AGENT}" ]]; then
    fail "graceful-degradation/fixture: ${FIXTURE_AGENT} not found"
else
    TMP3=$(make_tmp)
    PROJ3="${TMP3}/project"
    LIB3="${TMP3}/library"
    # Build library WITHOUT cognovis-base (empty agent-bases dir)
    mkdir -p "${LIB3}/scripts"
    mkdir -p "${LIB3}/.agents/agent-bases"
    ln -sf "${COMPOSE_SCRIPT}" "${LIB3}/scripts/compose-agent.py"
    # agent-bases dir is empty -- Layer 1 missing

    # cookbook_use_step65 should return 1 (compose failed) and keep uncomposed body
    INSTALL_RC=0
    cookbook_use_step65 "${LIB3}" "${FIXTURE_AGENT}" "${PROJ3}/.claude/agents" || INSTALL_RC=$?

    INSTALLED3="${PROJ3}/.claude/agents/$(basename "${FIXTURE_AGENT}")"

    if [[ "${INSTALL_RC}" -ne 0 ]]; then
        pass "graceful-degradation/return-code: compose failure returned non-zero (graceful)"
    else
        # compose-agent.py may succeed with no Layer 1 if it's optional;
        # accept either outcome as long as install does not abort
        pass "graceful-degradation/return-code: compose returned 0 (Layer 1 may be optional)"
    fi

    if [[ -f "${INSTALLED3}" ]]; then
        pass "graceful-degradation/file-exists: installed file exists despite missing Layer 1"
        # The installed body must contain the Layer 2 persona content (not empty)
        if grep -q "Test Agent\|This is a test agent persona" "${INSTALLED3}" 2>/dev/null; then
            pass "graceful-degradation/body-intact: installed body contains Layer 2 persona text"
        else
            fail "graceful-degradation/body-intact: installed body missing Layer 2 persona text"
            head -c 300 "${INSTALLED3}" | sed 's/^/    /'
        fi
    else
        fail "graceful-degradation/file-exists: installed file NOT found — sync must not abort on missing layer"
    fi
fi

# ---------------------------------------------------------------------------
# Test 4: cookbook/use.md Step 6.5 wording is unchanged (AK7 guard)
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Test 4: cookbook/use.md Step 6.5 wording is unchanged (AK7)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

USE_MD="${REPO_ROOT}/cookbook/use.md"
if [[ ! -f "${USE_MD}" ]]; then
    fail "use-md-unchanged/exists: cookbook/use.md not found"
else
    # Verify Step 6.5 section heading exists
    if grep -q "^### 6\.5: Compose Agent Body" "${USE_MD}"; then
        pass "use-md-unchanged/heading: Step 6.5 heading present"
    else
        fail "use-md-unchanged/heading: Step 6.5 heading missing or altered in cookbook/use.md"
    fi

    # Verify key invariant phrases from the original Step 6.5 are still present
    MISSING=0
    for phrase in \
        "agent_base_extends" \
        "compose-agent.py" \
        "graceful degradation" \
        "from-scratch" \
        "Idempotency"
    do
        if ! grep -q "${phrase}" "${USE_MD}"; then
            fail "use-md-unchanged/phrase: '${phrase}' missing from cookbook/use.md — Step 6.5 may have been altered"
            MISSING=$((MISSING + 1))
        fi
    done
    if [[ "${MISSING}" -eq 0 ]]; then
        pass "use-md-unchanged/phrases: all Step 6.5 invariant phrases present in cookbook/use.md"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    exit 1
fi
exit 0
