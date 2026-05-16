#!/usr/bin/env bash
set -euo pipefail

marketplace_root="${1:-.}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
validator="${VALIDATE_AGENT_PY:-${repo_root}/skills/agent-forge/scripts/validate-agent.py}"

if [[ ! -d "${marketplace_root}/agents" ]]; then
  echo "No agents directory at ${marketplace_root}; skipping agent validation."
  exit 0
fi

agent_files=()
while IFS= read -r agent_file; do
  agent_files+=("${agent_file}")
done < <(find "${marketplace_root}/agents" -maxdepth 1 -type f -name "*.md" | sort)

if [[ "${#agent_files[@]}" -eq 0 ]]; then
  echo "No marketplace agents found in ${marketplace_root}/agents; skipping."
  exit 0
fi

for agent_file in "${agent_files[@]}"; do
  python3 "${validator}" "${agent_file}" --strict --frontmatter-only
done

echo "Validated ${#agent_files[@]} marketplace agent(s)."
