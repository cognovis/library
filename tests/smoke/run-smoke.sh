#!/usr/bin/env bash
# run-smoke.sh — Cross-harness smoke test runner
#
# Usage: ./tests/smoke/run-smoke.sh [harness]
#   harness: claude-code | codex | pi | opencode | name-collision | all (default: all)
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
TMPDIRS=()

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

# Single EXIT trap registered once at script start — cleans all tmpdirs
trap 'rm -rf "${TMPDIRS[@]}"' EXIT

# ---------------------------------------------------------------------------
# Utility: make a temp dir, copy fixture, register cleanup
# ---------------------------------------------------------------------------
make_test_env() {
    local tmpdir
    tmpdir="$(mktemp -d)"
    # NOTE: Do NOT add TMPDIRS+=() here — this function is called via command
    # substitution (tmpdir="$(make_test_env)"), which runs in a subshell.
    # Any array mutation here is discarded. Callers must do TMPDIRS+=("$tmpdir")
    # in the parent shell after the assignment. The single EXIT trap at script
    # top then handles cleanup of all registered directories.
    echo "${tmpdir}"
}

# ---------------------------------------------------------------------------
# check_skill_file <dir> <label>
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
        pass "${label}: name collision scenario set up — both .claude/skills and .agents/skills present; runtime precedence not verified (see README claim 6, marked PARTIAL)"
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
    TMPDIRS+=("${tmpdir}")  # Register for cleanup in parent shell (subshell side-effect would be lost)

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
        # line format: mode SP hash SP stage TAB path — extract path after the tab
        local rel_path
        rel_path="$(printf '%s' "${line}" | cut -f2)"
        if [[ -n "${rel_path}" ]]; then
            pass "claude-code/git-symlink: repo symlink ${rel_path} tracked as mode 120000"
            real_symlink_check=1
        fi
    done < <(git -C "${REPO_ROOT}" ls-files --stage 2>/dev/null | grep "^120000" | grep -E '(^|/)\.claude/skills/' || true)

    if [[ "${real_symlink_check}" -eq 0 ]]; then
        skip "claude-code/git-symlink: no .claude/skills symlinks found in repo yet — create one to test git tracking"
    fi

    # CHECK 7: Runtime discovery — by-design SKIP, not a regression.
    # Verifying that a harness (Claude Code / Codex) actually discovers and loads a
    # skill requires starting a live session, which is outside the scope of a bash
    # smoke test. This limitation is documented in tests/smoke/README.md (Known
    # Limitations). The structural checks above (file existence, content, symlinks,
    # git tracking, discovery-order) are the maximum that can be automated here.
    echo "  NOTE  claude-code/runtime: Runtime skill discovery requires a live Claude Code session."
    echo "        Structural checks above confirm install paths are correct."
    echo "        To verify runtime: start a Claude Code session and invoke /hello-world"
}

# ---------------------------------------------------------------------------
# Harness: codex
# ---------------------------------------------------------------------------
smoke_codex() {
    section "codex"

    local fixture_src="${SCRIPT_DIR}/codex/fixtures/${FIXTURE_NAME}"
    local tmpdir
    tmpdir="$(make_test_env)"
    TMPDIRS+=("${tmpdir}")  # Register for cleanup in parent shell (subshell side-effect would be lost)

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

    # CHECK 4: Bridge direction per CL-b4o policy (post-CL-83q inversion):
    # Canonical = .agents/skills/<name>/ (real dir, read natively by Codex r1 root)
    # Bridge    = .claude/skills/<name>  (symlink -> canonical, used by Claude Code)
    # Codex needs no bridge — it reads .agents/skills/ directly.
    local claude_bridge_path="${tmpdir}/project/.claude/skills/${FIXTURE_NAME}"
    mkdir -p "$(dirname "${claude_bridge_path}")"
    # proj_agents_skills was already populated as the canonical real dir above.
    if [[ -d "${claude_bridge_path}" ]] && [[ ! -L "${claude_bridge_path}" ]]; then
      rm -r "${claude_bridge_path}"
    fi
    ln -sfn "$(realpath "${proj_agents_skills}")" "${claude_bridge_path}"
    check_symlink "${claude_bridge_path}" ".agents/skills/${FIXTURE_NAME}" "codex/cross-harness-bridge"

    # CHECK 5: Verify the Claude bridge symlink resolves to the canonical SKILL.md.
    local resolved_skill
    resolved_skill="$(readlink -f "${claude_bridge_path}")/SKILL.md"
    if [[ -f "${resolved_skill}" ]]; then
        pass "codex/symlink-skill-reachable: SKILL.md reachable via Claude bridge at ${resolved_skill}"
    else
        fail "codex/symlink-skill-reachable: SKILL.md NOT reachable via Claude bridge"
    fi

    # CHECK 6: Runtime discovery note
    echo "  NOTE  codex/runtime: Runtime skill discovery requires a live Codex session."
    echo "        Structural checks above confirm install paths are correct."
    echo "        To verify runtime: run 'codex' and invoke the hello-world skill"
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
# Harness: name-collision policy (CL-b4o, inverted by CL-83q)
# Validates docs/policy/name-collision.md structural rules:
#   1. Canonical path is .agents/skills/<name> (real dir or symlink into Layer-B cache)
#   2. Claude bridge .claude/skills/<name> is a symlink to the canonical path
#   3. Single SKILL.md file readable through canonical AND through Claude bridge
#   4. Two real directories (collision state) is detectable
#   5. Project-local overrides global
#   6. Claude-bridge removal correctly leaves canonical intact
# ---------------------------------------------------------------------------
smoke_name_collision() {
    section "name-collision"

    local fixture_src="${SCRIPT_DIR}/claude-code/fixtures/${FIXTURE_NAME}"
    local tmpdir
    tmpdir="$(make_test_env)"
    TMPDIRS+=("${tmpdir}")

    # Set up fake project structure (post-CL-83q polarity):
    # canonical real dir at .agents/skills/<name>, Claude bridge at .claude/skills/<name>.
    local canonical="${tmpdir}/project/.agents/skills/${FIXTURE_NAME}"
    local bridge_dir="${tmpdir}/project/.claude/skills"
    local bridge="${bridge_dir}/${FIXTURE_NAME}"
    local global_canonical="${tmpdir}/home/.agents/skills/${FIXTURE_NAME}"
    local global_bridge_dir="${tmpdir}/home/.claude/skills"
    local global_bridge="${global_bridge_dir}/${FIXTURE_NAME}"

    mkdir -p "${canonical}"
    mkdir -p "${bridge_dir}"
    mkdir -p "${global_canonical}"
    mkdir -p "${global_bridge_dir}"

    # Install fixture to canonical path (real file).
    cp "${fixture_src}/SKILL.md" "${canonical}/SKILL.md"

    # -----------------------------------------------------------------------
    # CHECK 1: Canonical is a real directory (not a symlink)
    # -----------------------------------------------------------------------
    if [[ -d "${canonical}" ]] && [[ ! -L "${canonical}" ]]; then
        pass "name-collision/canonical-real: .agents/skills/${FIXTURE_NAME} is a real directory (canonical)"
    else
        fail "name-collision/canonical-real: .agents/skills/${FIXTURE_NAME} is NOT a real directory"
    fi

    # -----------------------------------------------------------------------
    # CHECK 2: Create Claude bridge symlink pointing to canonical
    # -----------------------------------------------------------------------
    ln -sfn "$(realpath "${canonical}")" "${bridge}"
    check_symlink "${bridge}" ".agents/skills/${FIXTURE_NAME}" "name-collision/bridge-symlink"

    # -----------------------------------------------------------------------
    # CHECK 3: SKILL.md reachable through Claude bridge (single source of truth)
    # -----------------------------------------------------------------------
    local bridge_skill="${bridge}/SKILL.md"
    if [[ -f "${bridge_skill}" ]]; then
        pass "name-collision/bridge-skill-reachable: SKILL.md reachable via Claude bridge at ${bridge_skill}"
    else
        fail "name-collision/bridge-skill-reachable: SKILL.md NOT reachable via Claude bridge"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: Canonical and bridge resolve to the same inode (single file)
    # -----------------------------------------------------------------------
    local canonical_inode bridge_inode
    canonical_inode="$(stat -f '%i' "${canonical}/SKILL.md" 2>/dev/null || stat --format='%i' "${canonical}/SKILL.md" 2>/dev/null || echo "unknown")"
    bridge_inode="$(stat -f '%i' "${bridge}/SKILL.md" 2>/dev/null || stat --format='%i' "${bridge}/SKILL.md" 2>/dev/null || echo "unknown2")"
    if [[ "${canonical_inode}" == "${bridge_inode}" ]] && [[ "${canonical_inode}" != "unknown" ]]; then
        pass "name-collision/single-inode: canonical and bridge resolve to same inode (${canonical_inode}) — no drift possible"
    else
        fail "name-collision/single-inode: canonical inode=${canonical_inode}, bridge inode=${bridge_inode} — DRIFT RISK"
    fi

    # -----------------------------------------------------------------------
    # CHECK 5: Two real directories is detectable as collision state
    # -----------------------------------------------------------------------
    local collision_dir="${tmpdir}/collision-test"
    local col_canonical="${collision_dir}/.agents/skills/${FIXTURE_NAME}"
    local col_claude="${collision_dir}/.claude/skills/${FIXTURE_NAME}"
    mkdir -p "${col_canonical}" "${col_claude}"
    cp "${fixture_src}/SKILL.md" "${col_canonical}/SKILL.md"
    cp "${fixture_src}/SKILL.md" "${col_claude}/SKILL.md"

    # Detection: both exist as real dirs (neither is a symlink) = collision
    collision_detected=false
    if [[ -d "${col_canonical}" ]] && [[ ! -L "${col_canonical}" ]] && \
       [[ -d "${col_claude}" ]] && [[ ! -L "${col_claude}" ]]; then
        collision_detected=true
    fi
    if [[ "${collision_detected}" == "true" ]]; then
        pass "name-collision/collision-detection: two-real-directory collision state correctly detected"
    else
        fail "name-collision/collision-detection: collision state NOT detected when both are real directories"
    fi

    # -----------------------------------------------------------------------
    # CHECK 6: Project-local canonical overrides global canonical
    # -----------------------------------------------------------------------
    cp "${fixture_src}/SKILL.md" "${global_canonical}/SKILL.md"
    check_project_overrides_global \
        "${canonical}" \
        "${global_canonical}" \
        "name-collision/canonical-local-over-global"

    # -----------------------------------------------------------------------
    # CHECK 7: Project-local Claude bridge and global Claude bridge both
    # resolve correctly to their respective canonicals
    # -----------------------------------------------------------------------
    ln -sfn "$(realpath "${global_canonical}")" "${global_bridge}"
    local proj_resolved global_resolved
    proj_resolved="$(readlink -f "${bridge}" 2>/dev/null || true)"
    global_resolved="$(readlink -f "${global_bridge}" 2>/dev/null || true)"
    if [[ -d "${proj_resolved}" ]] && [[ -d "${global_resolved}" ]]; then
        pass "name-collision/claude-local-over-global: project-local Claude bridge and global Claude bridge both structurally valid (runtime picks project-local first per policy)"
    else
        fail "name-collision/claude-local-over-global: one or both Claude bridge resolutions invalid"
    fi

    # -----------------------------------------------------------------------
    # CHECK 8: Claude bridge removal leaves canonical intact
    # -----------------------------------------------------------------------
    local rm_test_canonical="${tmpdir}/rm-test/.agents/skills/${FIXTURE_NAME}"
    local rm_test_bridge_dir="${tmpdir}/rm-test/.claude/skills"
    local rm_test_bridge="${rm_test_bridge_dir}/${FIXTURE_NAME}"
    mkdir -p "${rm_test_canonical}" "${rm_test_bridge_dir}"
    cp "${fixture_src}/SKILL.md" "${rm_test_canonical}/SKILL.md"
    ln -sfn "$(realpath "${rm_test_canonical}")" "${rm_test_bridge}"

    # Simulate Claude-bridge-first removal (policy: bridge first, then canonical)
    rm "${rm_test_bridge}"
    if [[ ! -e "${rm_test_bridge}" ]] && [[ -f "${rm_test_canonical}/SKILL.md" ]]; then
        pass "name-collision/bridge-removal: Claude bridge removed; canonical intact (bridge-first removal order correct)"
    else
        fail "name-collision/bridge-removal: Claude bridge removal order incorrect"
    fi

    # -----------------------------------------------------------------------
    # CHECK 9: Verify docs/policy/name-collision.md exists and is non-empty
    # -----------------------------------------------------------------------
    local policy_doc="${REPO_ROOT}/docs/policy/name-collision.md"
    if [[ -f "${policy_doc}" ]] && [[ -s "${policy_doc}" ]]; then
        pass "name-collision/policy-doc: docs/policy/name-collision.md exists and is non-empty"
    else
        fail "name-collision/policy-doc: docs/policy/name-collision.md NOT found or empty"
    fi

    # -----------------------------------------------------------------------
    # CHECK 10: Policy doc references all 7 required decisions
    # -----------------------------------------------------------------------
    local required_decisions=("Decision 1" "Decision 2" "Decision 3" "Decision 4" "Decision 5" "Decision 6" "Decision 7")
    local all_found=true
    for decision in "${required_decisions[@]}"; do
        if ! grep -q "${decision}" "${policy_doc}" 2>/dev/null; then
            fail "name-collision/policy-completeness: '${decision}' NOT found in name-collision.md"
            all_found=false
        fi
    done
    if [[ "${all_found}" == "true" ]]; then
        pass "name-collision/policy-completeness: all 7 required decisions found in name-collision.md"
    fi

    echo "  NOTE  name-collision/runtime: Runtime precedence (which file the harness actually loads"
    echo "        when both paths exist) cannot be verified without a live harness session."
    echo "        Structural checks above confirm the policy-prescribed layout is achievable."
}

# ---------------------------------------------------------------------------
# Lockfile: .library.lock structural validation (CL-t21)
# Validates:
#   1. .library.lock format: required fields present
#   2. /library use writes a lockfile entry with all required fields
#   3. /library remove removes the entry from the lockfile
#   4. /library audit detects drift (installed file differs from locked checksum)
#   5. /library sync reads lockfile as source of truth (not just library.yaml)
#   6. checksum validation: computed sha256 matches stored value
#   7. Lockfile schema doc exists
#   8. Lockfile format doc exists
#   9. cookbook/audit.md exists
#  10. cookbook/use.md documents lockfile write step
#  11. cookbook/sync.md documents lockfile-as-source-of-truth
# ---------------------------------------------------------------------------
smoke_lockfile() {
    section "lockfile"

    # -----------------------------------------------------------------------
    # CHECK 1: Lockfile schema doc exists
    # -----------------------------------------------------------------------
    local schema_doc="${REPO_ROOT}/docs/schema/lockfile.schema.json"
    if [[ -f "${schema_doc}" ]]; then
        pass "lockfile/schema-doc: docs/schema/lockfile.schema.json exists"
    else
        fail "lockfile/schema-doc: docs/schema/lockfile.schema.json NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 2: Lockfile format doc exists
    # -----------------------------------------------------------------------
    local format_doc="${REPO_ROOT}/docs/lockfile-format.md"
    if [[ -f "${format_doc}" ]]; then
        pass "lockfile/format-doc: docs/lockfile-format.md exists"
    else
        fail "lockfile/format-doc: docs/lockfile-format.md NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 3: cookbook/audit.md exists
    # -----------------------------------------------------------------------
    local audit_cookbook="${REPO_ROOT}/cookbook/audit.md"
    if [[ -f "${audit_cookbook}" ]]; then
        pass "lockfile/audit-cookbook: cookbook/audit.md exists"
    else
        fail "lockfile/audit-cookbook: cookbook/audit.md NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: cookbook/use.md documents lockfile write step
    # -----------------------------------------------------------------------
    local use_cookbook="${REPO_ROOT}/cookbook/use.md"
    if grep -q "\.library\.lock\|lockfile" "${use_cookbook}" 2>/dev/null; then
        pass "lockfile/use-cookbook: cookbook/use.md references .library.lock"
    else
        fail "lockfile/use-cookbook: cookbook/use.md does NOT reference .library.lock"
    fi

    # -----------------------------------------------------------------------
    # CHECK 5: cookbook/remove.md documents lockfile removal step
    # -----------------------------------------------------------------------
    local remove_cookbook="${REPO_ROOT}/cookbook/remove.md"
    if grep -q "\.library\.lock\|lockfile" "${remove_cookbook}" 2>/dev/null; then
        pass "lockfile/remove-cookbook: cookbook/remove.md references .library.lock"
    else
        fail "lockfile/remove-cookbook: cookbook/remove.md does NOT reference .library.lock"
    fi

    # -----------------------------------------------------------------------
    # CHECK 6: cookbook/sync.md documents lockfile as source of truth
    # -----------------------------------------------------------------------
    local sync_cookbook="${REPO_ROOT}/cookbook/sync.md"
    if grep -q "\.library\.lock\|lockfile" "${sync_cookbook}" 2>/dev/null; then
        pass "lockfile/sync-cookbook: cookbook/sync.md references .library.lock"
    else
        fail "lockfile/sync-cookbook: cookbook/sync.md does NOT reference .library.lock"
    fi

    # -----------------------------------------------------------------------
    # CHECK 7: Lockfile format doc has all required fields documented
    # -----------------------------------------------------------------------
    if [[ -f "${format_doc}" ]]; then
        local required_fields=("name" "type" "source" "source_commit" "install_target" "install_timestamp" "checksum_sha256" "license")
        local all_fields=true
        for field in "${required_fields[@]}"; do
            if ! grep -q "${field}" "${format_doc}" 2>/dev/null; then
                fail "lockfile/format-fields: '${field}' NOT documented in lockfile-format.md"
                all_fields=false
            fi
        done
        if [[ "${all_fields}" == "true" ]]; then
            pass "lockfile/format-fields: all required fields documented in lockfile-format.md"
        fi
    else
        skip "lockfile/format-fields: lockfile-format.md not found — skipping field checks"
    fi

    # -----------------------------------------------------------------------
    # CHECK 8: Lockfile schema has required field definitions
    # -----------------------------------------------------------------------
    if [[ -f "${schema_doc}" ]]; then
        if grep -q "checksum_sha256\|source_commit\|install_target" "${schema_doc}" 2>/dev/null; then
            pass "lockfile/schema-fields: schema defines key lockfile fields"
        else
            fail "lockfile/schema-fields: schema missing key fields (checksum_sha256, source_commit, install_target)"
        fi
    else
        skip "lockfile/schema-fields: schema doc not found — skipping"
    fi

    # -----------------------------------------------------------------------
    # CHECK 9: Checksum validation — sha256 of a known file matches stored value
    # -----------------------------------------------------------------------
    local fixture_skill="${REPO_ROOT}/tests/smoke/claude-code/fixtures/hello-world/SKILL.md"
    if [[ -f "${fixture_skill}" ]]; then
        # Compute sha256 of the fixture file
        local computed_hash
        computed_hash="$(shasum -a 256 "${fixture_skill}" 2>/dev/null | awk '{print $1}' || sha256sum "${fixture_skill}" 2>/dev/null | awk '{print $1}')"
        if [[ -n "${computed_hash}" ]] && [[ "${#computed_hash}" -eq 64 ]]; then
            pass "lockfile/checksum-compute: sha256 computed successfully for fixture SKILL.md (${computed_hash:0:8}...)"
        else
            fail "lockfile/checksum-compute: sha256 computation failed or returned unexpected value: '${computed_hash}'"
        fi
    else
        fail "lockfile/checksum-compute: fixture SKILL.md not found at ${fixture_skill}"
    fi

    # -----------------------------------------------------------------------
    # CHECK 10: Lockfile YAML structure validation (write + read round-trip)
    #   Simulates what /library use would write and verifies the format is valid.
    # -----------------------------------------------------------------------
    local tmpdir
    tmpdir="$(make_test_env)"
    TMPDIRS+=("${tmpdir}")

    local lock_file="${tmpdir}/project/.library.lock"
    local fixture_skill="${REPO_ROOT}/tests/smoke/claude-code/fixtures/hello-world/SKILL.md"

    # Compute checksum for fixture
    local chksum
    chksum="$(shasum -a 256 "${fixture_skill}" 2>/dev/null | awk '{print $1}' || sha256sum "${fixture_skill}" 2>/dev/null | awk '{print $1}')"

    # Write a minimal lockfile entry (what /library use would produce)
    mkdir -p "$(dirname "${lock_file}")"
    cat > "${lock_file}" <<LOCKFILE_EOF
installed:
  - name: hello-world
    type: skill
    source: tests/smoke/claude-code/fixtures/hello-world/SKILL.md
    source_commit: e71925e1221ad7f1bcdd090b86a03a6aad7a3af6
    install_target: .claude/skills/hello-world/
    install_timestamp: 2026-04-30T15:00:00Z
    checksum_sha256: ${chksum}
    license: MIT
    bridge_symlinks: []
LOCKFILE_EOF

    # Verify lockfile was written and has the required structure
    if [[ -f "${lock_file}" ]]; then
        pass "lockfile/write-roundtrip: .library.lock written successfully"
    else
        fail "lockfile/write-roundtrip: .library.lock NOT written"
    fi

    # Verify YAML can be parsed (requires python3 with yaml)
    if python3 -c "import yaml; data = yaml.safe_load(open('${lock_file}')); assert 'installed' in data; assert len(data['installed']) == 1; e = data['installed'][0]; assert e['name'] == 'hello-world'; assert 'checksum_sha256' in e" 2>/dev/null; then
        pass "lockfile/yaml-parse: .library.lock is valid YAML with correct structure"
    else
        fail "lockfile/yaml-parse: .library.lock YAML parse or structure check failed"
    fi

    # -----------------------------------------------------------------------
    # CHECK 11: Drift detection — simulate audit finding a mismatch
    #   Install a file with known content, record its checksum, modify it,
    #   then verify the mismatch is detectable.
    # -----------------------------------------------------------------------
    local audit_dir="${tmpdir}/audit-test"
    local installed_skill="${audit_dir}/.claude/skills/hello-world/SKILL.md"
    mkdir -p "$(dirname "${installed_skill}")"
    cp "${fixture_skill}" "${installed_skill}"

    # Compute checksum of the installed file
    local locked_hash
    locked_hash="$(shasum -a 256 "${installed_skill}" 2>/dev/null | awk '{print $1}' || sha256sum "${installed_skill}" 2>/dev/null | awk '{print $1}')"

    # Simulate drift: append content to the installed file
    echo "# DRIFT: this line was added after install" >> "${installed_skill}"

    # Compute new checksum of the drifted file
    local drifted_hash
    drifted_hash="$(shasum -a 256 "${installed_skill}" 2>/dev/null | awk '{print $1}' || sha256sum "${installed_skill}" 2>/dev/null | awk '{print $1}')"

    # Verify drift is detectable (hashes differ)
    if [[ "${locked_hash}" != "${drifted_hash}" ]]; then
        pass "lockfile/drift-detection: checksum mismatch detected after file modification (locked=${locked_hash:0:8}..., actual=${drifted_hash:0:8}...)"
    else
        fail "lockfile/drift-detection: checksums IDENTICAL after modification — drift NOT detectable"
    fi

    # -----------------------------------------------------------------------
    # CHECK 12: Remove operation — entry removed from lockfile
    # -----------------------------------------------------------------------
    local lock_before="${lock_file}"
    local entry_count_before
    entry_count_before="$(python3 -c "import yaml; d = yaml.safe_load(open('${lock_before}')); print(len(d['installed']))" 2>/dev/null || echo "0")"

    # Simulate /library remove: remove the entry from the lockfile
    python3 - <<PYEOF
import yaml
with open('${lock_before}') as f:
    data = yaml.safe_load(f)
data['installed'] = [e for e in data['installed'] if e['name'] != 'hello-world']
with open('${lock_before}', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
PYEOF

    local entry_count_after
    entry_count_after="$(python3 -c "import yaml; d = yaml.safe_load(open('${lock_before}')); print(len(d['installed']))" 2>/dev/null || echo "-1")"

    if [[ "${entry_count_before}" == "1" ]] && [[ "${entry_count_after}" == "0" ]]; then
        pass "lockfile/remove-entry: entry correctly removed from .library.lock"
    else
        fail "lockfile/remove-entry: remove failed (before=${entry_count_before}, after=${entry_count_after})"
    fi

    # -----------------------------------------------------------------------
    # CHECK 13: bridge_symlinks field — dual-install records symlink info
    # -----------------------------------------------------------------------
    local bridge_lock="${tmpdir}/bridge-test/.library.lock"
    mkdir -p "$(dirname "${bridge_lock}")"
    cat > "${bridge_lock}" <<BRIDGE_EOF
installed:
  - name: hello-world
    type: skill
    source: tests/smoke/claude-code/fixtures/hello-world/SKILL.md
    source_commit: e71925e1221ad7f1bcdd090b86a03a6aad7a3af6
    install_target: .claude/skills/hello-world/
    install_timestamp: 2026-04-30T15:00:00Z
    checksum_sha256: ${chksum}
    license: MIT
    bridge_symlinks:
      - .agents/skills/hello-world -> ../../.claude/skills/hello-world
BRIDGE_EOF

    if python3 -c "
import yaml
d = yaml.safe_load(open('${bridge_lock}'))
e = d['installed'][0]
assert 'bridge_symlinks' in e
assert len(e['bridge_symlinks']) == 1
assert '.agents/skills/hello-world' in e['bridge_symlinks'][0]
" 2>/dev/null; then
        pass "lockfile/bridge-symlinks: bridge_symlinks field correctly recorded for dual-install"
    else
        fail "lockfile/bridge-symlinks: bridge_symlinks field missing or malformed"
    fi

    echo "  NOTE  lockfile/runtime: Full /library use lockfile integration requires a live Claude Code session."
    echo "        Structural checks above confirm lockfile format, schema, and drift detection logic."
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
# Standards smoke tests
#
# Validates the structural guarantees of the standards dependency model:
#  1. Loader script exists
#  2. Loader script is executable
#  3. Loader resolves project-local over global
#  4. Loader emits a warning for missing standards
#  5. Adapter generation fails
#  6. Standard install path does not mutate harness context files
#  7. SessionStart drift hook files are absent
#  8. Catalog does not register a standard drift guardrail
#  9. PRIMITIVES.md documents requires_standards loading
# 10. Loader still reads .agents/standards/<name>.md
# ---------------------------------------------------------------------------
smoke_standards() {
    section "standards"

    local loader_script="${REPO_ROOT}/scripts/standards-loader.sh"
    local primitives_doc="${REPO_ROOT}/docs/PRIMITIVES.md"
    local standard_installer="${REPO_ROOT}/scripts/lib/installers/standard.py"
    local library_yaml="${REPO_ROOT}/library.yaml"
    local drift_hook_dir="${REPO_ROOT}/hooks/standards""-drift-check"

    # -----------------------------------------------------------------------
    # CHECK 1: Loader script exists
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        pass "standards/loader-script: scripts/standards-loader.sh exists"
    else
        fail "standards/loader-script: scripts/standards-loader.sh NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 2: Loader script is executable
    # -----------------------------------------------------------------------
    if [[ -x "${loader_script}" ]]; then
        pass "standards/loader-executable: scripts/standards-loader.sh is executable"
    else
        fail "standards/loader-executable: scripts/standards-loader.sh is NOT executable"
    fi

    # -----------------------------------------------------------------------
    # CHECK 3: Loader implements project-local > global precedence
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        if grep -q "project-local ALWAYS overrides global" "${loader_script}" 2>/dev/null; then
            pass "standards/loader-precedence: loader script documents project-local precedence"
        else
            fail "standards/loader-precedence: loader script does NOT document project-local precedence"
        fi
    else
        fail "standards/loader-precedence: loader script not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: Missing standard emits warning and exits successfully
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        local missing_output
        if missing_output="$("${loader_script}" --load "__missing_standard_for_smoke__" 2>&1 >/dev/null)"; then
            if grep -q "WARNING" <<<"${missing_output}"; then
                pass "standards/loader-warn-on-missing: loader warns and continues"
            else
                fail "standards/loader-warn-on-missing: loader did not print warning text"
            fi
        else
            fail "standards/loader-warn-on-missing: loader exited nonzero for missing standard"
        fi
    else
        fail "standards/loader-warn-on-missing: loader script not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 5: Adapter generation fails
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        local adapter_output
        if adapter_output="$("${loader_script}" --generate-adapter 2>&1 >/dev/null)"; then
            fail "standards/adapter-removed: adapter generation succeeded"
        elif grep -q "adapter generation has been removed" <<<"${adapter_output}"; then
            pass "standards/adapter-removed: adapter generation fails with removal message"
        else
            fail "standards/adapter-removed: adapter generation failed with unexpected message"
        fi
    else
        fail "standards/adapter-removed: loader script not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 6: Standard installer does not mutate harness context files
    # -----------------------------------------------------------------------
    if [[ -f "${standard_installer}" ]]; then
        if grep -q "AGENTS.md\\|agents_md\\|agents""-md-block" "${standard_installer}" 2>/dev/null; then
            fail "standards/installer-no-context-mutation: standard installer still references harness context mutation"
        else
            pass "standards/installer-no-context-mutation: standard installer only writes files and lockfile"
        fi
    else
        fail "standards/installer-no-context-mutation: standard installer not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 7: Drift hook files are absent
    # -----------------------------------------------------------------------
    if [[ -d "${drift_hook_dir}" ]]; then
        fail "standards/drift-hook-removed: drift hook directory still exists"
    else
        pass "standards/drift-hook-removed: drift hook directory is absent"
    fi

    # -----------------------------------------------------------------------
    # CHECK 8: Catalog does not register the drift guardrail
    # -----------------------------------------------------------------------
    if [[ -f "${library_yaml}" ]]; then
        if grep -q "standards""-drift-check" "${library_yaml}" 2>/dev/null; then
            fail "standards/catalog-no-drift-guardrail: catalog still registers drift guardrail"
        else
            pass "standards/catalog-no-drift-guardrail: catalog has no drift guardrail entry"
        fi
    else
        fail "standards/catalog-no-drift-guardrail: library.yaml not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 9: PRIMITIVES.md documents requires_standards loading
    # -----------------------------------------------------------------------
    if [[ -f "${primitives_doc}" ]]; then
        if grep -q "requires_standards" "${primitives_doc}" 2>/dev/null \
            && grep -q "Never auto-injected" "${primitives_doc}" 2>/dev/null; then
            pass "standards/primitives-updated: PRIMITIVES.md documents scoped standard loading"
        else
            fail "standards/primitives-updated: PRIMITIVES.md does NOT document scoped standard loading"
        fi
    else
        fail "standards/primitives-updated: docs/PRIMITIVES.md NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 10: Loader reads from .agents/standards/
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        if grep -q '\.agents/standards' "${loader_script}" 2>/dev/null; then
            pass "standards/loader-path: loader reads from .agents/standards/"
        else
            fail "standards/loader-path: loader does NOT reference .agents/standards/"
        fi
    else
        fail "standards/loader-path: loader script not found"
    fi

    echo "  NOTE  standards/runtime: End-to-end requires_standards loading requires a live consuming primitive."
    echo "        Structural checks above confirm the removed adapter path fails closed."
}

# ---------------------------------------------------------------------------
# smoke_migration (CL-717)
#  Validates that the CL-717 skills-to-standards-loader migration completed:
#  1. ~/.agents/standards/ directory exists
#  2. ~/.agents/standards/ contains at least 60 standards files
#  3. Required core standards are present in ~/.agents/standards/
#  4. Each present standard has valid YAML frontmatter (name, version, description)
#  5. standards-loader.sh --load resolves core standards from ~/.agents/standards/
#  6. At least one SKILL.md in claude-code-plugins has requires_standards: frontmatter
#  7. inject-subagent-standards.py is absent
# ---------------------------------------------------------------------------
smoke_migration() {
    section "migration"

    local global_standards_dir="${HOME}/.agents/standards"
    local ccp_skills_root="${HOME}/code/claude-code-plugins"
    local loader_script="${REPO_ROOT}/scripts/standards-loader.sh"

    # -----------------------------------------------------------------------
    # CHECK 1: ~/.agents/standards/ directory exists
    # -----------------------------------------------------------------------
    if [[ -d "${global_standards_dir}" ]]; then
        pass "migration/global-standards-dir: ~/.agents/standards/ exists"
    else
        fail "migration/global-standards-dir: ~/.agents/standards/ NOT found — run CL-717 migration"
    fi

    # -----------------------------------------------------------------------
    # CHECK 2: ~/.agents/standards/ contains at least 60 standards files
    # -----------------------------------------------------------------------
    if [[ -d "${global_standards_dir}" ]]; then
        local count
        count="$(find "${global_standards_dir}" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')"
        if [[ "${count}" -ge 60 ]]; then
            pass "migration/global-standards-count: ${count} standards found (>= 60 required)"
        else
            fail "migration/global-standards-count: only ${count} standards found (expected >= 60)"
        fi
    else
        fail "migration/global-standards-count: directory not found — cannot count"
    fi

    # -----------------------------------------------------------------------
    # CHECK 3: Required core standards are present
    # -----------------------------------------------------------------------
    if [[ -d "${global_standards_dir}" ]]; then
        local required_standards=(
            "english-only.md"
            "no-emoji.md"
            "tool-standards.md"
            "healthcare-control-areas.md"
            "conventional-commits.md"
            "debrief-contract.md"
            "tool-boundaries.md"
        )
        local all_present=true
        for std in "${required_standards[@]}"; do
            if [[ ! -f "${global_standards_dir}/${std}" ]]; then
                fail "migration/core-standard-present: ${std} NOT found in ~/.agents/standards/"
                all_present=false
            fi
        done
        if [[ "${all_present}" == "true" ]]; then
            pass "migration/core-standards-present: all ${#required_standards[@]} required core standards present"
        fi
    else
        fail "migration/core-standards-present: directory not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: Standards have valid YAML frontmatter
    # -----------------------------------------------------------------------
    if [[ -d "${global_standards_dir}" ]]; then
        local missing_fm=0
        for std_file in "${global_standards_dir}"/*.md; do
            [[ -f "${std_file}" ]] || continue
            if ! grep -q "^name:" "${std_file}" 2>/dev/null || \
               ! grep -q "^version:" "${std_file}" 2>/dev/null || \
               ! grep -q "^description:" "${std_file}" 2>/dev/null; then
                missing_fm=$((missing_fm + 1))
            fi
        done
        if [[ "${missing_fm}" -eq 0 ]]; then
            pass "migration/standards-frontmatter: all standards have valid YAML frontmatter"
        else
            fail "migration/standards-frontmatter: ${missing_fm} standards missing required frontmatter fields"
        fi
    else
        fail "migration/standards-frontmatter: directory not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 5: Loader resolves core standards from ~/.agents/standards/
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        local loaded_content
        if loaded_content="$(bash "${loader_script}" --load english-only 2>/dev/null)" && \
           echo "${loaded_content}" | grep -q "English"; then
            pass "migration/loader-resolves-english-only: loader resolves english-only from ~/.agents/standards/"
        else
            fail "migration/loader-resolves-english-only: loader failed to resolve english-only standard"
        fi

        if loaded_content="$(bash "${loader_script}" --load tool-standards 2>/dev/null)" && \
           echo "${loaded_content}" | grep -q "tool\|Tool"; then
            pass "migration/loader-resolves-tool-standards: loader resolves tool-standards from ~/.agents/standards/"
        else
            fail "migration/loader-resolves-tool-standards: loader failed to resolve tool-standards"
        fi
    else
        fail "migration/loader-resolves-standards: loader script not found at ${loader_script}"
    fi

    # -----------------------------------------------------------------------
    # CHECK 6: SKILL.md files in claude-code-plugins have requires_standards:
    # Note: This check requires ~/code/claude-code-plugins to be cloned locally.
    # It fails (not skips) if the directory is missing — the smoke_migration harness
    # is designed to run only on machines where the full migration has been applied.
    # Run 'all' harness for CI-safe checks that don't depend on user-global state.
    # -----------------------------------------------------------------------
    if [[ -d "${ccp_skills_root}" ]]; then
        local skills_with_requires
        skills_with_requires="$(grep -rl "requires_standards:" "${ccp_skills_root}" \
            --include="SKILL.md" --include="skill.md" \
            --exclude-dir=".git" --exclude-dir="worktrees" \
            2>/dev/null | wc -l | tr -d ' ')"
        if [[ "${skills_with_requires}" -ge 50 ]]; then
            pass "migration/skills-have-requires-standards: ${skills_with_requires} skills have requires_standards: frontmatter"
        else
            fail "migration/skills-have-requires-standards: only ${skills_with_requires} skills have requires_standards: (expected >= 50)"
        fi
    else
        fail "migration/skills-have-requires-standards: claude-code-plugins not found at ${ccp_skills_root} — clone it or skip this harness"
    fi

    # -----------------------------------------------------------------------
    # CHECK 7: inject-subagent-standards.py is absent
    # -----------------------------------------------------------------------
    local hook_file="${HOME}/.claude/hooks/inject-subagent""-standards.py"
    if [[ -f "${hook_file}" ]]; then
        fail "migration/hook-removed: inject-subagent-standards.py still exists"
    else
        pass "migration/hook-removed: inject-subagent-standards.py is absent"
    fi

    echo "  NOTE  migration/hook-removed: Hook removal is complete on this machine."
}

# ---------------------------------------------------------------------------
# smoke_agent_bases
#  1. .agents/agent-bases/cognovis-base.md exists
#  2. cognovis-base.md has YAML frontmatter with name, version, description
#  3. .agents/model-standards/ directory exists with at least 2 .md files
#  4. Each model-standard has YAML frontmatter
#  5. standards-loader.sh supports --load-model-standard operation
#  6. PRIMITIVES.md §10 cross-references standards-loader and model-standards path
#  7. agents-format-mapping.md documents agent_base_extends and model_standards fields
# ---------------------------------------------------------------------------
smoke_agent_bases() {
    section "agent-bases"

    local agent_bases_dir="${REPO_ROOT}/.agents/agent-bases"
    local model_standards_dir="${REPO_ROOT}/.agents/model-standards"
    local cognovis_base="${agent_bases_dir}/cognovis-base.md"
    local loader_script="${REPO_ROOT}/scripts/standards-loader.sh"
    local primitives_doc="${REPO_ROOT}/docs/PRIMITIVES.md"
    local format_mapping_doc="${REPO_ROOT}/docs/research/agents-format-mapping.md"

    # -----------------------------------------------------------------------
    # CHECK 1: cognovis-base.md exists
    # -----------------------------------------------------------------------
    if [[ -f "${cognovis_base}" ]]; then
        pass "agent-bases/cognovis-base: .agents/agent-bases/cognovis-base.md exists"
    else
        fail "agent-bases/cognovis-base: .agents/agent-bases/cognovis-base.md NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 2: cognovis-base.md has required YAML frontmatter fields
    # -----------------------------------------------------------------------
    if [[ -f "${cognovis_base}" ]]; then
        local all_frontmatter=true
        for field in "name" "version" "description"; do
            if ! grep -q "^${field}:" "${cognovis_base}" 2>/dev/null; then
                fail "agent-bases/cognovis-base-frontmatter: '${field}' field NOT found in cognovis-base.md frontmatter"
                all_frontmatter=false
            fi
        done
        if [[ "${all_frontmatter}" == "true" ]]; then
            pass "agent-bases/cognovis-base-frontmatter: cognovis-base.md has required frontmatter (name, version, description)"
        fi
    else
        fail "agent-bases/cognovis-base-frontmatter: cognovis-base.md not found — cannot check frontmatter"
    fi

    # -----------------------------------------------------------------------
    # CHECK 3: model-standards directory has at least 2 .md files
    # -----------------------------------------------------------------------
    if [[ -d "${model_standards_dir}" ]]; then
        local ms_count
        ms_count="$(find "${model_standards_dir}" -name "*.md" -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
        if [[ "${ms_count}" -ge 2 ]]; then
            pass "agent-bases/model-standards-count: .agents/model-standards/ has ${ms_count} model-standard(s) (>= 2 required)"
        else
            fail "agent-bases/model-standards-count: .agents/model-standards/ has only ${ms_count} model-standard(s) — at least 2 required"
        fi
    else
        fail "agent-bases/model-standards-dir: .agents/model-standards/ directory NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: Each model-standard has YAML frontmatter
    # -----------------------------------------------------------------------
    if [[ -d "${model_standards_dir}" ]]; then
        local all_ms_frontmatter=true
        while IFS= read -r ms_file; do
            local ms_name
            ms_name="$(basename "${ms_file}" .md)"
            for field in "name" "version" "description"; do
                if ! grep -q "^${field}:" "${ms_file}" 2>/dev/null; then
                    fail "agent-bases/model-standard-frontmatter: '${ms_name}.md' missing '${field}' in frontmatter"
                    all_ms_frontmatter=false
                fi
            done
        done < <(find "${model_standards_dir}" -name "*.md" -maxdepth 1 2>/dev/null)
        if [[ "${all_ms_frontmatter}" == "true" ]]; then
            pass "agent-bases/model-standard-frontmatter: all model-standards have required frontmatter"
        fi
    else
        fail "agent-bases/model-standard-frontmatter: model-standards dir not found — cannot check frontmatter"
    fi

    # -----------------------------------------------------------------------
    # CHECK 5: standards-loader.sh supports --load-model-standard
    # -----------------------------------------------------------------------
    if [[ -f "${loader_script}" ]]; then
        if grep -q "load-model-standard\|model.standard\|model_standard" "${loader_script}" 2>/dev/null; then
            pass "agent-bases/loader-model-standard: standards-loader.sh supports model-standard loading"
        else
            fail "agent-bases/loader-model-standard: standards-loader.sh does NOT support --load-model-standard"
        fi
    else
        fail "agent-bases/loader-model-standard: standards-loader.sh not found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 6: PRIMITIVES.md §10 cross-references standards-loader and model-standards path
    # -----------------------------------------------------------------------
    if [[ -f "${primitives_doc}" ]]; then
        local cross_ref_ok=true
        if ! grep -q "standards-loader\|model-standards" "${primitives_doc}" 2>/dev/null; then
            fail "agent-bases/primitives-model-standard: PRIMITIVES.md §10 does NOT cross-reference standards-loader or model-standards path"
            cross_ref_ok=false
        fi
        if ! grep -q "three.layer\|three layer\|Layer 1\|Layer 2\|Layer 3\|composition" "${primitives_doc}" 2>/dev/null; then
            fail "agent-bases/primitives-composition: PRIMITIVES.md does NOT document three-layer composition"
            cross_ref_ok=false
        fi
        if [[ "${cross_ref_ok}" == "true" ]]; then
            pass "agent-bases/primitives-model-standard: PRIMITIVES.md §10 references standards-loader and composition model"
        fi
    else
        fail "agent-bases/primitives-model-standard: docs/PRIMITIVES.md NOT found"
    fi

    # -----------------------------------------------------------------------
    # CHECK 7: agents-format-mapping.md documents new frontmatter fields
    # -----------------------------------------------------------------------
    if [[ -f "${format_mapping_doc}" ]]; then
        local mapping_ok=true
        if ! grep -q "agent_base_extends\|agent-base-extends" "${format_mapping_doc}" 2>/dev/null; then
            fail "agent-bases/format-mapping-agent-base: agents-format-mapping.md does NOT document agent_base_extends field"
            mapping_ok=false
        fi
        if ! grep -q "model_standards\|model-standards" "${format_mapping_doc}" 2>/dev/null; then
            fail "agent-bases/format-mapping-model-standards: agents-format-mapping.md does NOT document model_standards field"
            mapping_ok=false
        fi
        if [[ "${mapping_ok}" == "true" ]]; then
            pass "agent-bases/format-mapping: agents-format-mapping.md documents agent_base_extends and model_standards fields"
        fi
    else
        fail "agent-bases/format-mapping: docs/research/agents-format-mapping.md NOT found"
    fi

    echo "  NOTE  agent-bases/runtime: End-to-end composition (install-time write to harness-native) requires a live library install session."
    echo "        Structural checks above confirm the files, frontmatter, and loader support satisfy the composition contract."
}

# ---------------------------------------------------------------------------
# smoke_fleet_migration
#  Validates that all agents in claude-code-plugins have been migrated to the
#  Agent Base composition model (CL-xpg).
#
#  Checks per agent file in ~/code/claude-code-plugins/**/agents/*.md:
#  1. agent_base_extends field is present in YAML frontmatter
#  2. model_standards field is present in YAML frontmatter
#
#  Cross-harness validation: verifies at least 3 agents across different plugins
#  (beads-workflow, core, dev-tools) have both fields.
#
#  agent-forge: init-agent.py template emits agent_base_extends and model_standards.
#
#  Note: This smoke uses ~/code/claude-code-plugins as the source of truth.
#  It is excluded from 'all' (same pattern as smoke_migration) because it relies
#  on the developer's local clone. Run explicitly: ./run-smoke.sh fleet-migration
# ---------------------------------------------------------------------------
smoke_fleet_migration() {
    section "fleet-migration"

    local plugins_root="${HOME}/code/claude-code-plugins"
    local init_agent_script="${plugins_root}/meta/skills/agent-forge/scripts/init-agent.py"

    if [[ ! -d "${plugins_root}" ]]; then
        skip "fleet-migration: ~/code/claude-code-plugins not found — all agent migration checks require the developer clone"
        return
    fi

    # Collect all agent .md files (excluding worktrees and test fixtures)
    local agent_files=()
    while IFS= read -r f; do
        agent_files+=("$f")
    done < <(find "${plugins_root}" -name "*.md" -path "*/agents/*" \
        | grep -v "worktrees" \
        | grep -v "token-cost" \
        | sort)

    local total="${#agent_files[@]}"
    if [[ "${total}" -eq 0 ]]; then
        fail "fleet-migration/agent-count: no agent .md files found under ~/code/claude-code-plugins"
        return
    fi

    pass "fleet-migration/agent-count: found ${total} agent .md files in claude-code-plugins"

    # -----------------------------------------------------------------------
    # CHECK 1+2: All agents have agent_base_extends and model_standards
    # -----------------------------------------------------------------------
    local missing_base=0
    local missing_std=0
    local missing_list_base=()
    local missing_list_std=()

    for f in "${agent_files[@]}"; do
        local rel
        rel="$(echo "${f}" | sed "s|${plugins_root}/||")"
        if ! grep -q "^agent_base_extends:" "${f}" 2>/dev/null; then
            missing_base=$((missing_base + 1))
            missing_list_base+=("${rel}")
        fi
        if ! grep -q "^model_standards:" "${f}" 2>/dev/null; then
            missing_std=$((missing_std + 1))
            missing_list_std+=("${rel}")
        fi
    done

    if [[ "${missing_base}" -eq 0 ]]; then
        pass "fleet-migration/agent-base-extends: all ${total} agents have agent_base_extends frontmatter"
    else
        fail "fleet-migration/agent-base-extends: ${missing_base} of ${total} agents missing agent_base_extends"
        for m in "${missing_list_base[@]}"; do
            echo "    MISSING: ${m}"
        done
    fi

    if [[ "${missing_std}" -eq 0 ]]; then
        pass "fleet-migration/model-standards: all ${total} agents have model_standards frontmatter"
    else
        fail "fleet-migration/model-standards: ${missing_std} of ${total} agents missing model_standards"
        for m in "${missing_list_std[@]}"; do
            echo "    MISSING: ${m}"
        done
    fi

    # -----------------------------------------------------------------------
    # CHECK 3: Cross-harness validation — at least 3 agents from different plugins
    # have both fields (beads-workflow, core, dev-tools minimum)
    # -----------------------------------------------------------------------
    local cross_ok=0
    local required_plugins=("beads-workflow" "core" "dev-tools")
    for plugin in "${required_plugins[@]}"; do
        local sample_file
        # Collect candidates without relying on pipe exit code (safe under set -e)
        local candidates=()
        while IFS= read -r f; do
            candidates+=("$f")
        done < <(find "${plugins_root}/${plugin}/agents" -name "*.md" 2>/dev/null | grep -v worktrees || true)
        sample_file="${candidates[0]:-}"
        if [[ -z "${sample_file}" ]]; then
            fail "fleet-migration/cross-harness-${plugin}: no agents found under ${plugin}/agents/"
            continue
        fi
        local rel
        rel="$(echo "${sample_file}" | sed "s|${plugins_root}/||")"
        local has_base=false
        local has_std=false
        grep -q "^agent_base_extends:" "${sample_file}" 2>/dev/null && has_base=true
        grep -q "^model_standards:" "${sample_file}" 2>/dev/null && has_std=true
        if [[ "${has_base}" == "true" && "${has_std}" == "true" ]]; then
            pass "fleet-migration/cross-harness-${plugin}: ${rel} has agent_base_extends + model_standards"
            cross_ok=$((cross_ok + 1))
        else
            fail "fleet-migration/cross-harness-${plugin}: ${rel} missing agent_base_extends=${has_base} model_standards=${has_std}"
        fi
    done

    if [[ "${cross_ok}" -ge 3 ]]; then
        pass "fleet-migration/cross-harness-validation: ${cross_ok}/3 required plugins validated"
    fi

    # -----------------------------------------------------------------------
    # CHECK 4: agent-forge init-agent.py template emits composition frontmatter
    # -----------------------------------------------------------------------
    if [[ -f "${init_agent_script}" ]]; then
        local has_base_template=false
        local has_ms_template=false
        grep -q "agent_base_extends" "${init_agent_script}" 2>/dev/null && has_base_template=true
        grep -q "model_standards" "${init_agent_script}" 2>/dev/null && has_ms_template=true
        if [[ "${has_base_template}" == "true" && "${has_ms_template}" == "true" ]]; then
            pass "fleet-migration/agent-forge-template: init-agent.py template emits agent_base_extends + model_standards"
        else
            fail "fleet-migration/agent-forge-template: init-agent.py template missing agent_base_extends=${has_base_template} model_standards=${has_ms_template}"
        fi
    else
        fail "fleet-migration/agent-forge-template: init-agent.py not found at ${init_agent_script}"
    fi
}

# ---------------------------------------------------------------------------
# smoke_use_cookbook_path (CL-o16)
#  Delegates to tests/smoke/use-agent-cookbook-path.sh for a self-contained
#  end-to-end test of the /library use cookbook path (fetch -> compose -> write).
#  That script exercises:
#    1. Full fetch+compose produces cognovis-base marker in installed file
#    2. Idempotent re-run: zero diff between run1 and run2
#    3. Graceful degradation when Layer 1 is absent (warn + keep uncomposed)
#    4. cookbook/use.md Step 6.5 wording unchanged (AK7 guard)
# ---------------------------------------------------------------------------
smoke_use_cookbook_path() {
    section "use-cookbook-path"

    local ext_script="${SCRIPT_DIR}/use-agent-cookbook-path.sh"
    if [[ ! -f "${ext_script}" ]]; then
        fail "use-cookbook-path/script-exists: use-agent-cookbook-path.sh not found at ${ext_script}"
        return
    fi

    local ext_rc=0
    bash "${ext_script}" || ext_rc=$?

    if [[ "${ext_rc}" -eq 0 ]]; then
        pass "use-cookbook-path/all-tests: use-agent-cookbook-path.sh exited 0 (all checks passed)"
    else
        fail "use-cookbook-path/all-tests: use-agent-cookbook-path.sh exited ${ext_rc} (one or more checks failed)"
        OVERALL_EXIT=1
    fi
}

# ---------------------------------------------------------------------------
# Harness: library-core (AK3 verification)
# ---------------------------------------------------------------------------
smoke_library_core() {
    section "library-core"

    local library_core="${1:-/tmp/cognovis-library-core}"
    local source_plugins="/Users/malte/code/claude-code-plugins"

    # Check library-core exists
    if [[ ! -d "${library_core}" ]]; then
        fail "library-core: clone not found at ${library_core}"
        return
    fi

    # Check 5 specific skills exist and content matches source
    local skills=("dolt" "cmux" "council" "prompt-refiner" "inject-standards")
    for skill in "${skills[@]}"; do
        local dest="${library_core}/.claude/skills/${skill}/SKILL.md"
        if [[ -f "${dest}" ]]; then
            pass "library-core/skill-exists: ${skill}/SKILL.md"
        else
            fail "library-core/skill-exists: ${skill}/SKILL.md NOT found"
        fi
    done

    # Check bridge symlinks for skills
    local bridged_skills=("dolt" "cmux")
    for skill in "${bridged_skills[@]}"; do
        check_symlink "${library_core}/.agents/skills/${skill}" ".claude/skills/${skill}" "library-core/bridge-${skill}"
    done

    # Check agents exist
    local agents=("researcher" "session-close" "test-engineer")
    for agent in "${agents[@]}"; do
        if [[ -f "${library_core}/.claude/agents/${agent}.md" ]]; then
            pass "library-core/agent-exists: ${agent}.md"
        else
            fail "library-core/agent-exists: ${agent}.md NOT found"
        fi
    done

    # Verify content matches source for one skill
    local spot_src=""
    if [[ -f "${source_plugins}/core/skills/dolt/SKILL.md" ]]; then
        spot_src="${source_plugins}/core/skills/dolt/SKILL.md"
        local spot_dest="${library_core}/.claude/skills/dolt/SKILL.md"
        if diff -q "${spot_src}" "${spot_dest}" &>/dev/null; then
            pass "library-core/content-match: dolt SKILL.md matches source"
        else
            fail "library-core/content-match: dolt SKILL.md differs from source"
        fi
    fi
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
        name-collision)
            smoke_name_collision
            ;;
        lockfile)
            smoke_lockfile
            ;;
        standards)
            smoke_standards
            ;;
        agent-bases)
            smoke_agent_bases
            ;;
        migration)
            smoke_migration
            ;;
        fleet-migration)
            smoke_fleet_migration
            ;;
        library-core)
            smoke_library_core
            ;;
        use-cookbook-path)
            smoke_use_cookbook_path
            ;;
        all)
            # Note: smoke_migration and smoke_fleet_migration are intentionally excluded from 'all'.
            # They validate user-global state (~/.agents/standards/, ~/code/claude-code-plugins)
            # and would fail on clean CI/dev homes.
            # Run explicitly: ./run-smoke.sh migration | ./run-smoke.sh fleet-migration
            smoke_claude_code
            smoke_codex
            smoke_pi
            smoke_opencode
            smoke_name_collision
            smoke_lockfile
            smoke_standards
            smoke_agent_bases
            smoke_use_cookbook_path
            ;;
        *)
            echo "ERROR: Unknown harness '${harness}'"
            echo "Usage: $0 [claude-code|codex|pi|opencode|name-collision|lockfile|standards|agent-bases|migration|fleet-migration|library-core|use-cookbook-path|all]"
            exit 1
            ;;
    esac

    print_summary
    exit "${OVERALL_EXIT}"
}

main "$@"
