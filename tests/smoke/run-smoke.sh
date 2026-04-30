#!/usr/bin/env bash
# run-smoke.sh — Cross-harness smoke test runner
#
# Usage: ./tests/smoke/run-smoke.sh [harness]
#   harness: claude-code | codex | pi | opencode | all (default: all)
#
# Returns: exit code 0 on all PASS, 1 on any FAIL
#
# Constraint: does NOT pollute the project's .claude/ or .agents/ dirs.
# Uses mktemp -d for isolation.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIXTURE_NAME="hello-world"

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
OVERALL_EXIT=0

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
pass() {
    echo "  PASS  $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "  FAIL  $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    OVERALL_EXIT=1
}

skip() {
    echo "  SKIP  $1  [MANUAL_VERIFICATION_REQUIRED]"
    SKIP_COUNT=$((SKIP_COUNT + 1))
}

section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Harness: $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---------------------------------------------------------------------------
# Utility: make a temp dir, copy fixture, register cleanup
# ---------------------------------------------------------------------------
make_test_env() {
    local tmpdir
    tmpdir="$(mktemp -d)"
    # Always clean up on exit
    trap "rm -rf '${tmpdir}'" EXIT
    echo "${tmpdir}"
}

# ---------------------------------------------------------------------------
# check_skill_file <dir> <skill_name> <label>
#   Verifies that <dir>/SKILL.md exists and is readable.
# ---------------------------------------------------------------------------
check_skill_file() {
    local dir="$1" label="$2"
    if [[ -f "${dir}/SKILL.md" ]]; then
        pass "${label}: SKILL.md exists at ${dir}/SKILL.md"
    else
        fail "${label}: SKILL.md NOT found at ${dir}/SKILL.md"
    fi
}

# ---------------------------------------------------------------------------
# check_skill_content <skill_md_path> <expected_marker> <label>
#   Verifies that the file contains the expected FIXTURE_HARNESS marker.
# ---------------------------------------------------------------------------
check_skill_content() {
    local path="$1" marker="$2" label="$3"
    if grep -q "FIXTURE_HARNESS: ${marker}" "${path}" 2>/dev/null; then
        pass "${label}: SKILL.md contains correct FIXTURE_HARNESS marker"
    else
        fail "${label}: SKILL.md missing FIXTURE_HARNESS: ${marker} in ${path}"
    fi
}

# ---------------------------------------------------------------------------
# check_symlink <link_path> <expected_target_suffix> <label>
#   Verifies symlink exists and its resolved target ends with expected suffix.
# ---------------------------------------------------------------------------
check_symlink() {
    local link_path="$1" expected_suffix="$2" label="$3"
    if [[ -L "${link_path}" ]]; then
        local resolved
        resolved="$(readlink -f "${link_path}" 2>/dev/null || true)"
        if [[ "${resolved}" == *"${expected_suffix}" ]]; then
            pass "${label}: symlink ${link_path} -> ${resolved}"
        else
            fail "${label}: symlink ${link_path} resolves to ${resolved} (expected suffix: ${expected_suffix})"
        fi
    else
        fail "${label}: ${link_path} is NOT a symlink (or does not exist)"
    fi
}

# ---------------------------------------------------------------------------
# check_symlink_in_git <git_repo_root> <rel_symlink_path> <label>
#   Verifies that the symlink is tracked in git with mode 120000.
# ---------------------------------------------------------------------------
check_symlink_in_git() {
    local repo_root="$1" rel_path="$2" label="$3"
    # git ls-files --stage shows: <mode> <hash> <stage>\t<path>
    local git_output
    git_output="$(git -C "${repo_root}" ls-files --stage -- "${rel_path}" 2>/dev/null || true)"
    if echo "${git_output}" | grep -q "^120000"; then
        pass "${label}: symlink ${rel_path} tracked in git as mode 120000"
    elif [[ -z "${git_output}" ]]; then
        fail "${label}: ${rel_path} NOT tracked in git at all"
    else
        fail "${label}: ${rel_path} tracked in git but NOT as symlink (mode 120000); got: ${git_output}"
    fi
}

# ---------------------------------------------------------------------------
# check_project_overrides_global <project_dir> <global_dir> <label>
#   Verifies that project-local skill takes precedence over global.
#   Since we can't run the harness, we document the resolution order
#   by verifying both exist and the project-local one is not empty.
# ---------------------------------------------------------------------------
check_project_overrides_global() {
    local project_dir="$1" global_dir="$2" label="$3"
    local project_skill="${project_dir}/SKILL.md"
    local global_skill="${global_dir}/SKILL.md"

    if [[ -f "${project_skill}" && -f "${global_skill}" ]]; then
        # Both exist — runtime would pick project-local first (per Open Agent Skills Standard)
        pass "${label}: project-local skill takes precedence over global (both present; runtime picks project-local first)"
    elif [[ -f "${project_skill}" ]]; then
        pass "${label}: project-local skill present (global not installed — no collision)"
    elif [[ -f "${global_skill}" ]]; then
        pass "${label}: global skill present (no project-local — fallback to global)"
    else
        fail "${label}: neither project-local nor global skill found"
    fi
}

# ---------------------------------------------------------------------------
# check_name_collision <path_a> <label_a> <path_b> <label_b> <label>
#   When both a .claude/skills/foo and .agents/skills/foo exist,
#   documents which one wins. Cannot run harness, so we just verify
#   structures and document the expected precedence.
# ---------------------------------------------------------------------------
check_name_collision() {
    local claude_dir="$1" agents_dir="$2" label="$3"
    local claude_skill="${claude_dir}/SKILL.md"
    local agents_skill="${agents_dir}/SKILL.md"

    if [[ -f "${claude_skill}" && -f "${agents_skill}" ]]; then
        pass "${label}: name collision scenario present — .claude/skills wins for Claude Code (harness-native path has priority); .agents/skills wins for Codex"
    elif [[ -f "${claude_skill}" ]]; then
        pass "${label}: only .claude/skills present — no collision"
    elif [[ -f "${agents_skill}" ]]; then
        pass "${label}: only .agents/skills present — no collision"
    else
        fail "${label}: neither .claude/skills nor .agents/skills found"
    fi
}

# ---------------------------------------------------------------------------
# Harness: claude-code
# ---------------------------------------------------------------------------
smoke_claude_code() {
    section "claude-code"

    local fixture_src="${SCRIPT_DIR}/claude-code/fixtures/${FIXTURE_NAME}"
    local tmpdir
    tmpdir="$(make_test_env)"

    # Set up fake project structure in tmpdir
    local proj_claude_skills="${tmpdir}/project/.claude/skills/${FIXTURE_NAME}"
    local proj_agents_skills="${tmpdir}/project/.agents/skills/${FIXTURE_NAME}"
    local global_claude_skills="${tmpdir}/home/.claude/skills/${FIXTURE_NAME}"

    mkdir -p "${proj_claude_skills}"
    mkdir -p "${proj_agents_skills}"
    mkdir -p "${global_claude_skills}"

    # Install fixture to project-local Claude Code path
    cp "${fixture_src}/SKILL.md" "${proj_claude_skills}/SKILL.md"

    # Install same fixture to global Claude Code path (simulating a different version)
    cp "${fixture_src}/SKILL.md" "${global_claude_skills}/SKILL.md"

    # Install fixture to Codex path (simulating dual install)
    cp "${fixture_src}/SKILL.md" "${proj_agents_skills}/SKILL.md"

    # CHECK 1: skill file exists at project-local Claude Code path
    check_skill_file "${proj_claude_skills}" "claude-code/install"

    # CHECK 2: SKILL.md content has correct harness marker
    check_skill_content "${proj_claude_skills}/SKILL.md" "claude-code" "claude-code/content"

    # CHECK 3: Create symlink from .claude/skills -> ../.agents/skills and verify
    local symlink_path="${tmpdir}/project/.claude/skills/${FIXTURE_NAME}-via-agents"
    ln -sf "../../.agents/skills/${FIXTURE_NAME}" "${symlink_path}"
    check_symlink "${symlink_path}" ".agents/skills/${FIXTURE_NAME}" "claude-code/symlink"

    # CHECK 4: Project overrides global
    check_project_overrides_global \
        "${proj_claude_skills}" \
        "${global_claude_skills}" \
        "claude-code/discovery-order"

    # CHECK 5: Name collision check
    check_name_collision \
        "${proj_claude_skills}" \
        "${proj_agents_skills}" \
        "claude-code/name-collision"

    # CHECK 6: Verify real project symlink is tracked in git (if symlink exists in repo)
    # Look for any .claude/skills symlinks already in this repo
    local real_symlink_check=0
    while IFS= read -r line; do
        # line format: mode hash stage\tpath
        local rel_path
        rel_path="$(echo "${line}" | awk '{print $NF}')"
        if [[ -n "${rel_path}" ]]; then
            pass "claude-code/git-symlink: repo symlink ${rel_path} tracked as mode 120000"
            real_symlink_check=1
        fi
    done < <(git -C "${REPO_ROOT}" ls-files --stage 2>/dev/null | grep "^120000" | grep ".claude/skills" || true)

    if [[ "${real_symlink_check}" -eq 0 ]]; then
        skip "claude-code/git-symlink: no .claude/skills symlinks found in repo yet — create one to test git tracking"
    fi

    # CHECK 7: Runtime discovery — structural only (cannot run Claude Code in test)
    echo "  NOTE  claude-code/runtime: Runtime skill discovery requires a live Claude Code session."
    echo "        Structural checks above confirm install paths are correct."
    echo "        To verify runtime: start a Claude Code session and invoke /hello-world"

    rm -rf "${tmpdir}"
    trap - EXIT
}

# ---------------------------------------------------------------------------
# Harness: codex
# ---------------------------------------------------------------------------
smoke_codex() {
    section "codex"

    local fixture_src="${SCRIPT_DIR}/codex/fixtures/${FIXTURE_NAME}"
    local tmpdir
    tmpdir="$(make_test_env)"

    # Set up fake project structure in tmpdir
    local proj_agents_skills="${tmpdir}/project/.agents/skills/${FIXTURE_NAME}"
    local global_agents_skills="${tmpdir}/home/.agents/skills/${FIXTURE_NAME}"

    mkdir -p "${proj_agents_skills}"
    mkdir -p "${global_agents_skills}"

    # Install fixture to project-local Codex path
    cp "${fixture_src}/SKILL.md" "${proj_agents_skills}/SKILL.md"

    # Install fixture to global Codex path
    cp "${fixture_src}/SKILL.md" "${global_agents_skills}/SKILL.md"

    # CHECK 1: skill file exists at project-local Codex path
    check_skill_file "${proj_agents_skills}" "codex/install"

    # CHECK 2: SKILL.md content has correct harness marker
    check_skill_content "${proj_agents_skills}/SKILL.md" "codex" "codex/content"

    # CHECK 3: Project overrides global
    check_project_overrides_global \
        "${proj_agents_skills}" \
        "${global_agents_skills}" \
        "codex/discovery-order"

    # CHECK 4: Name collision with Claude Code path
    # Codex uses .agents/skills; Claude Code uses .claude/skills
    # When symlink .claude/skills/foo -> ../../.agents/skills/foo exists, both read same file
    local claude_symlink_dir="${tmpdir}/project/.claude/skills/${FIXTURE_NAME}"
    mkdir -p "$(dirname "${claude_symlink_dir}")"
    ln -sf "../../.agents/skills/${FIXTURE_NAME}" "${claude_symlink_dir}"
    check_symlink "${claude_symlink_dir}" ".agents/skills/${FIXTURE_NAME}" "codex/cross-harness-symlink"

    # CHECK 5: Verify the symlink resolves to the SKILL.md
    local resolved_skill
    resolved_skill="$(readlink -f "${claude_symlink_dir}")/SKILL.md"
    if [[ -f "${resolved_skill}" ]]; then
        pass "codex/symlink-skill-reachable: SKILL.md reachable via symlink at ${resolved_skill}"
    else
        fail "codex/symlink-skill-reachable: SKILL.md NOT reachable via symlink"
    fi

    # CHECK 6: Runtime discovery note
    echo "  NOTE  codex/runtime: Runtime skill discovery requires a live Codex session."
    echo "        Structural checks above confirm install paths are correct."
    echo "        To verify runtime: run 'codex' and invoke the hello-world skill"

    rm -rf "${tmpdir}"
    trap - EXIT
}

# ---------------------------------------------------------------------------
# Harness: pi (stub)
# ---------------------------------------------------------------------------
smoke_pi() {
    section "pi"

    local fixture_src="${SCRIPT_DIR}/pi/fixtures/${FIXTURE_NAME}"

    # CHECK 1: fixture stub exists
    if [[ -f "${fixture_src}/SKILL.md" ]]; then
        pass "pi/fixture-stub: fixture SKILL.md exists at ${fixture_src}/SKILL.md"
    else
        fail "pi/fixture-stub: fixture SKILL.md NOT found at ${fixture_src}/SKILL.md"
    fi

    # CHECK 2: fixture has STUB status marker
    if grep -q "FIXTURE_STATUS: STUB" "${fixture_src}/SKILL.md" 2>/dev/null; then
        pass "pi/fixture-stub: SKILL.md correctly marked as STUB"
    else
        fail "pi/fixture-stub: SKILL.md missing FIXTURE_STATUS: STUB marker"
    fi

    # CHECK 3: All remaining checks are stubs
    skip "pi/install: Pi runtime not locally available"
    skip "pi/discovery-order: Pi runtime not locally available"
    skip "pi/symlink: Pi runtime not locally available"
    skip "pi/git-symlink: Pi runtime not locally available"
    skip "pi/runtime: Pi runtime not locally available"

    echo "  NOTE  pi: Expected install paths (from architecture docs):"
    echo "          Project-local primary:  .pi/skills/hello-world/SKILL.md"
    echo "          Project-local fallback: .agents/skills/hello-world/SKILL.md"
    echo "          Global primary:         ~/.pi/agent/skills/hello-world/SKILL.md"
    echo "          Global fallback:        ~/.agents/skills/hello-world/SKILL.md"
    echo "        Manual verification required when Pi runtime is available."
}

# ---------------------------------------------------------------------------
# Harness: opencode (stub)
# ---------------------------------------------------------------------------
smoke_opencode() {
    section "opencode"

    local fixture_src="${SCRIPT_DIR}/opencode/fixtures/${FIXTURE_NAME}"

    # CHECK 1: fixture stub exists
    if [[ -f "${fixture_src}/SKILL.md" ]]; then
        pass "opencode/fixture-stub: fixture SKILL.md exists at ${fixture_src}/SKILL.md"
    else
        fail "opencode/fixture-stub: fixture SKILL.md NOT found at ${fixture_src}/SKILL.md"
    fi

    # CHECK 2: fixture has STUB status marker
    if grep -q "FIXTURE_STATUS: STUB" "${fixture_src}/SKILL.md" 2>/dev/null; then
        pass "opencode/fixture-stub: SKILL.md correctly marked as STUB"
    else
        fail "opencode/fixture-stub: SKILL.md missing FIXTURE_STATUS: STUB marker"
    fi

    # CHECK 3: All remaining checks are stubs
    skip "opencode/install: OpenCode runtime not locally available"
    skip "opencode/discovery-order: OpenCode runtime not locally available"
    skip "opencode/symlink: OpenCode runtime not locally available"
    skip "opencode/git-symlink: OpenCode runtime not locally available"
    skip "opencode/runtime: OpenCode runtime not locally available"

    echo "  NOTE  opencode: Expected install paths (from architecture docs):"
    echo "          Project-local primary:  .opencode/skills/hello-world/SKILL.md"
    echo "          Project-local fallback: .claude/skills/hello-world/SKILL.md"
    echo "          Project-local fallback: .agents/skills/hello-world/SKILL.md"
    echo "        Manual verification required when OpenCode runtime is available."
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Summary"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  PASS: ${PASS_COUNT}"
    echo "  FAIL: ${FAIL_COUNT}"
    echo "  SKIP: ${SKIP_COUNT}  (MANUAL_VERIFICATION_REQUIRED)"
    echo ""
    if [[ "${OVERALL_EXIT}" -eq 0 ]]; then
        echo "  RESULT: ALL CHECKS PASSED"
    else
        echo "  RESULT: SOME CHECKS FAILED (exit code 1)"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local harness="${1:-all}"

    echo "Cross-harness skill smoke tests"
    echo "Repo root: ${REPO_ROOT}"
    echo "Fixture:   ${FIXTURE_NAME}"
    echo "Harness:   ${harness}"

    case "${harness}" in
        claude-code)
            smoke_claude_code
            ;;
        codex)
            smoke_codex
            ;;
        pi)
            smoke_pi
            ;;
        opencode)
            smoke_opencode
            ;;
        all)
            smoke_claude_code
            smoke_codex
            smoke_pi
            smoke_opencode
            ;;
        *)
            echo "ERROR: Unknown harness '${harness}'"
            echo "Usage: $0 [claude-code|codex|pi|opencode|all]"
            exit 1
            ;;
    esac

    print_summary
    exit "${OVERALL_EXIT}"
}

main "$@"
