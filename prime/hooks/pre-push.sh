#!/usr/bin/env bash
# pre-push hook — managed by cognovis-library project_tooling (CL-rkww)
# managed-by: cognovis-library chain_existing (CL-rkww)
# Scans bounded outgoing commit ranges with gitleaks before allowing a push.
# Do not edit manually — canonical version is in prime/hooks/pre-push.sh.
#
# Threat model: this is a cooperative client-side defense-in-depth control.
# It cannot prevent `git push --no-verify`, direct edits to git hooks, or other
# local bypasses by an agent/user with write access to the checkout. The
# independent cognovis-core session-close secret scan (clc-i5ld) remains a
# separate, non-bypassable defense.

ZERO_SHA="0000000000000000000000000000000000000000"
TIMEOUT_SECONDS="${GITLEAKS_PRE_PUSH_TIMEOUT_SECONDS:-120}"

fail() {
  printf 'pre-push: %s\n' "$*" >&2
  exit 2
}

if [[ -z "$TIMEOUT_SECONDS" || "$TIMEOUT_SECONDS" == *[!0-9]* ]]; then
  fail "invalid GITLEAKS_PRE_PUSH_TIMEOUT_SECONDS value"
fi

stdin_file="$(mktemp "${TMPDIR:-/tmp}/cognovis-pre-push.XXXXXX")" \
  || fail "cannot create temporary stdin capture"

trap 'rm -f "$stdin_file"' EXIT

cat > "$stdin_file" || fail "cannot capture pre-push stdin"

is_object_id() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
}

is_zero_sha() {
  [[ "$1" == "$ZERO_SHA" ]]
}

ranges=()
line_number=0

while IFS= read -r line || [[ -n "$line" ]]; do
  line_number=$((line_number + 1))

  local_ref=""
  local_sha=""
  remote_ref=""
  remote_sha=""
  extra=""
  read -r local_ref local_sha remote_ref remote_sha extra <<< "$line"

  if [[ -z "$local_ref" || -z "$local_sha" || -z "$remote_ref" || -z "$remote_sha" || -n "$extra" ]]; then
    fail "malformed pre-push input on line ${line_number}"
  fi

  if ! is_object_id "$local_sha" || ! is_object_id "$remote_sha"; then
    fail "malformed pre-push input on line ${line_number}: invalid object id"
  fi

  if is_zero_sha "$local_sha"; then
    continue
  fi

  if is_zero_sha "$remote_sha"; then
    ranges+=("${local_sha} --not --remotes")
  else
    ranges+=("${remote_sha}..${local_sha}")
  fi
done < "$stdin_file"

if ((${#ranges[@]} > 0)); then
  if command -v timeout >/dev/null 2>&1; then
    timeout_bin="timeout"
  elif command -v gtimeout >/dev/null 2>&1; then
    timeout_bin="gtimeout"
  else
    fail "cannot bound gitleaks runtime: install timeout or gtimeout"
  fi

  command -v gitleaks >/dev/null 2>&1 || fail "gitleaks not found on PATH"

  for range in "${ranges[@]}"; do
    "$timeout_bin" "$TIMEOUT_SECONDS" gitleaks git --no-banner --redact "--log-opts=${range}"
    scan_status=$?
    if [[ "$scan_status" -ne 0 ]]; then
      printf 'pre-push: gitleaks blocked outgoing range: %s\n' "$range" >&2
      exit 2
    fi
  done
fi

hook_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" \
  || fail "cannot resolve hook directory"
chain_hook="${hook_dir}/pre-push.local"

if [[ -e "$chain_hook" || -L "$chain_hook" ]]; then
  "$chain_hook" "$@" < "$stdin_file"
  exit $?
fi

exit 0
