#!/usr/bin/env bash
# install-agent-with-handlers.sh - Smoke test: agent-owned handler assets install end-to-end.
#
# Bead: CL-ii7a
#
# Tests:
#   1. library.py installs a fixture agent prompt for Claude, Codex, and OpenCode.
#   2. Declared private handler assets are copied beside each harness prompt.
#   3. A clean project needs no separate skill install to receive the handler.
#
# Usage:
#   bash tests/smoke/install-agent-with-handlers.sh
#
# Returns exit code 0 on all PASS, 1 on any FAIL.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LIBRARY_PY="${REPO_ROOT}/scripts/library.py"
FIXTURE_DIR="${REPO_ROOT}/tests/installers/fixtures/agent-with-handlers"

PASS_COUNT=0
FAIL_COUNT=0
TMPDIRS=()

pass() {
    echo "  PASS  $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "  FAIL  $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

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

TMP_ROOT=$(make_tmp)
PROJECT_DIR="${TMP_ROOT}/project"
XDG_DIR="${TMP_ROOT}/xdg-data"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMP_ROOT}/uv-cache}"
mkdir -p "$PROJECT_DIR"

cat > "${PROJECT_DIR}/library.yaml" << YAML
default_dirs:
  agents:
    - default: .claude/agents/
    - default_codex: .codex/agents/
    - default_opencode: .opencode/agents/

library:
  agents:
    - name: handler-agent
      description: Agent with private handler assets
      sources:
        claude: ${FIXTURE_DIR}/handler-agent.md
        codex: ${FIXTURE_DIR}/handler-agent.toml
        opencode: ${FIXTURE_DIR}/handler-agent.md
      handlers:
        - handlers/fixture-handler.sh
  skills: []
  standards: []
  prompts: []

marketplaces: []
guardrails: []
mcp_servers: []
model_standards: []
YAML

echo ""
echo "--------------------------------------------------"
echo "  Test 1: clean install with private handlers"
echo "--------------------------------------------------"

if (
    cd "$PROJECT_DIR"
    XDG_DATA_HOME="$XDG_DIR" uv run --project "$REPO_ROOT" python "$LIBRARY_PY" agent use handler-agent --harness all --json > "${TMP_ROOT}/install.json"
); then
    pass "library.py agent use handler-agent --harness all exited 0"
else
    fail "library.py agent use handler-agent --harness all failed"
    sed 's/^/    /' "${TMP_ROOT}/install.json" 2>/dev/null || true
fi

echo ""
echo "--------------------------------------------------"
echo "  Test 2: harness prompt files are present"
echo "--------------------------------------------------"

for target in \
    ".claude/agents/handler-agent.md" \
    ".codex/agents/handler-agent.toml" \
    ".opencode/agents/handler-agent.md"; do
    if [[ -f "${PROJECT_DIR}/${target}" ]]; then
        pass "installed ${target}"
    else
        fail "missing ${target}"
    fi
done

echo ""
echo "--------------------------------------------------"
echo "  Test 3: private handler files are present"
echo "--------------------------------------------------"

for target in \
    ".claude/agents/handler-agent-handlers/handlers/fixture-handler.sh" \
    ".codex/agents/handler-agent-handlers/handlers/fixture-handler.sh" \
    ".opencode/agents/handler-agent-handlers/handlers/fixture-handler.sh"; do
    if [[ -f "${PROJECT_DIR}/${target}" ]] && grep -q "HANDLER_AGENT_PRIVATE_HANDLER" "${PROJECT_DIR}/${target}"; then
        pass "installed ${target}"
    else
        fail "missing or invalid ${target}"
    fi
done

echo ""
echo "--------------------------------------------------"
echo "  Test 4: no handler-providing skill was installed"
echo "--------------------------------------------------"

if [[ ! -d "${PROJECT_DIR}/.agents/skills" ]]; then
    pass "no .agents/skills directory created"
else
    fail ".agents/skills directory should not be created"
fi

echo ""
echo "--------------------------------------------------"
echo "  Summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"
echo "--------------------------------------------------"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi
exit 0
