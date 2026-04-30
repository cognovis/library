#!/usr/bin/env bash
# standards-loader.sh — Cross-harness standards loading prototype
#
# Bead: CL-v56 | Epic: CL-36o (Multi-Harness Library)
#
# Implements two mechanisms from the standards-loading design:
#   (a) Adapter generation — writes standards into AGENTS.md at install time
#   (b) Skill-script-side loader — reads .agents/standards/<name>.md at runtime
#
# Usage:
#   standards-loader.sh --load <standard-name>
#     Load a single standard by name, resolve via project>global precedence,
#     write content to stdout. Warn on stderr if not found (warn-and-continue).
#
#   standards-loader.sh --generate-adapter <skill-name> [--target <file>]
#     Read requires_standards from skill's SKILL.md frontmatter, load all
#     declared standards, write a delimited section into the target file.
#     Default target: AGENTS.md in the current project root.
#     Idempotent: replaces existing section if present.
#
#   standards-loader.sh --list
#     List all available standards by scanning .agents/standards/ and
#     ~/.agents/standards/ directories.
#
# Path resolution (project-local ALWAYS overrides global):
#   1. ${PROJ_ROOT}/.agents/standards/<name>.md   (project-local)
#   2. ~/.agents/standards/<name>.md               (user-global)
#   3. ~/.claude/standards/**/<name>.md            (legacy Claude Code fallback)
#
# See docs/research/standards-loading.md for the full loader contract.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# PROJ_ROOT: the invoking project root, not the script's parent directory.
# Using the script's parent would silently ignore project-local standards when
# the script is invoked from a different project (e.g., via an absolute path).
# Resolution order:
#   1. --proj-root <path> flag (explicit override)
#   2. $PWD (caller's working directory — the project being operated on)
# The script's parent is NOT a valid default here; it's only correct when the
# script is invoked from its own repository, which is not the general case.
PROJ_ROOT="${PWD}"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
warn() {
    echo "[standards-loader] WARNING: $*" >&2
}

info() {
    echo "[standards-loader] $*" >&2
}

# ---------------------------------------------------------------------------
# resolve_standard <name>
#   Resolves a standard name to a file path using project>global precedence.
#   Prints the resolved path to stdout.
#   Exits 0 on success, 1 if not found.
# ---------------------------------------------------------------------------
resolve_standard() {
    local name="$1"

    # Priority 1: project-local
    local proj_path="${PROJ_ROOT}/.agents/standards/${name}.md"
    if [[ -f "${proj_path}" ]]; then
        echo "${proj_path}"
        return 0
    fi

    # Priority 2: user-global
    local global_path="${HOME}/.agents/standards/${name}.md"
    if [[ -f "${global_path}" ]]; then
        echo "${global_path}"
        return 0
    fi

    # Priority 3: legacy Claude Code fallback (compatibility mode)
    # Scan ~/.claude/standards/**/<name>.md — the legacy path uses domain subdirs.
    local legacy_path
    if legacy_path="$(find "${HOME}/.claude/standards" -name "${name}.md" -maxdepth 3 2>/dev/null | head -1)"; then
        if [[ -n "${legacy_path}" ]]; then
            echo "${legacy_path}"
            return 0
        fi
    fi

    # Not found
    return 1
}

# ---------------------------------------------------------------------------
# cmd_load <name>
#   Mechanism (b): skill-script-side loader.
#   Resolves the standard, cats content to stdout.
#   Warns to stderr on missing standard (does NOT exit 1 — warn-and-continue).
# ---------------------------------------------------------------------------
cmd_load() {
    local name="$1"
    local path

    if path="$(resolve_standard "${name}" 2>/dev/null)"; then
        # Validate frontmatter before emitting content.
        # Required fields: name, version, description.
        # Invalid frontmatter produces a warning but the standard is still loaded
        # (warn-and-continue per loader contract — a malformed standard should not
        # block context delivery).
        python3 - "${path}" "${name}" >&2 <<'PYEOF'
import sys, re

standard_file = sys.argv[1]
standard_name = sys.argv[2]
required_fields = ['name', 'version', 'description']

with open(standard_file) as f:
    content = f.read()

m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not m:
    print(f"[standards-loader] WARNING: standard '{standard_name}' has no YAML frontmatter. "
          f"Required fields: {required_fields}. Proceeding anyway.")
    sys.exit(0)

frontmatter_text = m.group(1)
missing = []
for field in required_fields:
    if not re.search(rf'^{re.escape(field)}\s*:', frontmatter_text, re.MULTILINE):
        missing.append(field)

if missing:
    print(f"[standards-loader] WARNING: standard '{standard_name}' frontmatter missing required fields: "
          f"{missing}. Proceeding anyway.")
PYEOF
        cat "${path}"
    else
        warn "standard '${name}' not found. Checked:"
        warn "  - ${PROJ_ROOT}/.agents/standards/${name}.md"
        warn "  - ${HOME}/.agents/standards/${name}.md"
        warn "  - ${HOME}/.claude/standards/ (legacy)"
        warn "Proceeding without this standard."
        # Exit 0: warn-and-continue per loader contract
    fi
}

# ---------------------------------------------------------------------------
# read_requires_standards <skill_dir>
#   Reads the requires_standards YAML frontmatter field from a SKILL.md file.
#   Prints each required standard name on a separate line.
# ---------------------------------------------------------------------------
read_requires_standards() {
    local skill_dir="$1"
    local skill_file="${skill_dir}/SKILL.md"

    if [[ ! -f "${skill_file}" ]]; then
        warn "SKILL.md not found at ${skill_file}"
        return 1
    fi

    # Extract YAML frontmatter block (between first two --- markers)
    # Then parse requires_standards field.
    # Supports both inline array: [a, b] and block sequence:
    #   requires_standards:
    #     - a
    #     - b
    python3 - "${skill_file}" <<'PYEOF'
import sys, re

skill_file = sys.argv[1]
with open(skill_file) as f:
    content = f.read()

# Extract frontmatter between first --- ... ---
m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not m:
    sys.exit(0)

frontmatter = m.group(1)

# Find requires_standards line
# Handles: requires_standards: [a, b, c]
# and:     requires_standards:
#            - a
#            - b
lines = frontmatter.split('\n')
in_requires = False
names = []

for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('requires_standards:'):
        rest = stripped[len('requires_standards:'):].strip()
        if rest.startswith('['):
            # Inline array
            inner = rest.strip('[]')
            names = [n.strip().strip('"\'') for n in inner.split(',') if n.strip()]
            break
        elif rest:
            # Inline scalar (unlikely but handle it)
            names = [rest.strip().strip('"\'')]
            break
        else:
            in_requires = True
    elif in_requires:
        if stripped.startswith('- '):
            names.append(stripped[2:].strip().strip('"\''))
        elif stripped and not stripped.startswith('#'):
            # Another top-level key — end of requires_standards block
            break

for name in names:
    print(name)
PYEOF
}

# ---------------------------------------------------------------------------
# write_adapter_section <target_file> <skill_name> <combined_content>
#   Writes (or replaces) a delimited standards section in the target file.
#   Section markers:
#     <!-- BEGIN STANDARDS <skill_name> -->
#     <!-- END STANDARDS <skill_name> -->
#   Idempotent: replaces existing section if present, appends if absent.
# ---------------------------------------------------------------------------
write_adapter_section() {
    local target_file="$1"
    local skill_name="$2"
    local content_file="$3"

    local begin_marker="<!-- BEGIN STANDARDS ${skill_name} -->"
    local end_marker="<!-- END STANDARDS ${skill_name} -->"

    local new_section
    new_section="$(printf '%s\n%s\n%s\n' "${begin_marker}" "$(cat "${content_file}")" "${end_marker}")"

    if [[ ! -f "${target_file}" ]]; then
        # Create target file with section
        printf '%s\n' "${new_section}" > "${target_file}"
        info "Created ${target_file} with standards section for skill '${skill_name}'"
        return 0
    fi

    if grep -qF "${begin_marker}" "${target_file}" 2>/dev/null; then
        # Replace existing section using Python for reliability with multiline content
        python3 - "${target_file}" "${begin_marker}" "${end_marker}" "${content_file}" <<'PYEOF'
import sys, re

target = sys.argv[1]
begin = sys.argv[2]
end = sys.argv[3]
content_file = sys.argv[4]

with open(target) as f:
    original = f.read()

with open(content_file) as f:
    new_content = f.read()

# Build new section
new_section = f"{begin}\n{new_content}\n{end}"

# Replace between markers (inclusive)
pattern = re.escape(begin) + r'.*?' + re.escape(end)
updated = re.sub(pattern, new_section, original, flags=re.DOTALL)

with open(target, 'w') as f:
    f.write(updated)
PYEOF
        info "Replaced standards section for skill '${skill_name}' in ${target_file}"
    else
        # Append new section
        printf '\n%s\n' "${new_section}" >> "${target_file}"
        info "Appended standards section for skill '${skill_name}' to ${target_file}"
    fi
}

# ---------------------------------------------------------------------------
# cmd_generate_adapter <skill_name> [<target_file>]
#   Mechanism (a): adapter generation into AGENTS.md (or specified target).
#   Reads requires_standards from skill's SKILL.md, concatenates standards,
#   writes delimited section into target file.
# ---------------------------------------------------------------------------
cmd_generate_adapter() {
    local skill_name="$1"
    local target_file="${2:-${PROJ_ROOT}/AGENTS.md}"

    # Locate the skill directory
    local skill_dir=""
    for candidate in \
        "${PROJ_ROOT}/.claude/skills/${skill_name}" \
        "${PROJ_ROOT}/.agents/skills/${skill_name}" \
        "${HOME}/.claude/skills/${skill_name}" \
        "${HOME}/.agents/skills/${skill_name}"; do
        if [[ -d "${candidate}" ]]; then
            skill_dir="${candidate}"
            break
        fi
    done

    if [[ -z "${skill_dir}" ]]; then
        warn "skill '${skill_name}' not found. Checked .claude/skills/, .agents/skills/, global paths."
        return 1
    fi

    # Read requires_standards
    local requires_list
    requires_list="$(read_requires_standards "${skill_dir}")" || {
        warn "Failed to read requires_standards from ${skill_dir}/SKILL.md"
        return 1
    }

    if [[ -z "${requires_list}" ]]; then
        info "Skill '${skill_name}' has no requires_standards — nothing to generate."
        return 0
    fi

    # Build combined content in a temp file.
    # Deduplication: if the same standard name appears multiple times in requires_list
    # (e.g., declared by multiple nested skills), load it exactly once.
    # First declaration wins per the merge order contract in docs/research/standards-loading.md.
    local tmpfile
    tmpfile="$(mktemp)"
    trap 'rm -f "${tmpfile}"' EXIT

    local first=true
    declare -A seen_standards  # associative array for O(1) dedup lookup

    while IFS= read -r standard_name; do
        [[ -z "${standard_name}" ]] && continue

        # Skip duplicates — first declaration wins
        if [[ -n "${seen_standards[${standard_name}]+x}" ]]; then
            info "Deduplicating standard '${standard_name}' — already included once."
            continue
        fi
        seen_standards["${standard_name}"]=1

        local path
        if path="$(resolve_standard "${standard_name}" 2>/dev/null)"; then
            if [[ "${first}" != "true" ]]; then
                printf '\n---\n\n' >> "${tmpfile}"
            fi
            printf '# Standard: %s\n' "${standard_name}" >> "${tmpfile}"
            cat "${path}" >> "${tmpfile}"
            first=false
        else
            warn "standard '${standard_name}' not found. Checked:"
            warn "  - ${PROJ_ROOT}/.agents/standards/${standard_name}.md"
            warn "  - ${HOME}/.agents/standards/${standard_name}.md"
            warn "  - ${HOME}/.claude/standards/ (legacy)"
            warn "Proceeding without this standard."
        fi
    done <<< "${requires_list}"

    if [[ ! -s "${tmpfile}" ]]; then
        info "No standards content generated for skill '${skill_name}' — all were missing."
        return 0
    fi

    write_adapter_section "${target_file}" "${skill_name}" "${tmpfile}"
}

# ---------------------------------------------------------------------------
# cmd_list
#   Lists all available standards by scanning project-local and global directories.
# ---------------------------------------------------------------------------
cmd_list() {
    local proj_dir="${PROJ_ROOT}/.agents/standards"
    local global_dir="${HOME}/.agents/standards"
    local legacy_dir="${HOME}/.claude/standards"

    echo "Available standards:"
    echo ""

    local found=false

    if [[ -d "${proj_dir}" ]]; then
        echo "Project-local (${proj_dir}):"
        while IFS= read -r f; do
            local name
            name="$(basename "${f}" .md)"
            echo "  - ${name}"
            found=true
        done < <(find "${proj_dir}" -name "*.md" -maxdepth 1 2>/dev/null | sort)
        echo ""
    fi

    if [[ -d "${global_dir}" ]]; then
        echo "User-global (${global_dir}):"
        while IFS= read -r f; do
            local name
            name="$(basename "${f}" .md)"
            echo "  - ${name}"
            found=true
        done < <(find "${global_dir}" -name "*.md" -maxdepth 1 2>/dev/null | sort)
        echo ""
    fi

    if [[ -d "${legacy_dir}" ]]; then
        echo "Legacy Claude Code (${legacy_dir}):"
        while IFS= read -r f; do
            local name
            # Use Python for portable relative path computation.
            # GNU realpath --relative-to is not available on macOS (BSD realpath
            # does not support that flag), so we use Python's pathlib which is
            # cross-platform and available on all supported platforms.
            name="$(python3 -c "
import sys
from pathlib import Path
print(Path(sys.argv[1]).relative_to(sys.argv[2]))
" "${f}" "${legacy_dir}" 2>/dev/null || basename "${f}")"
            echo "  - ${name}"
            found=true
        done < <(find "${legacy_dir}" -name "*.md" -maxdepth 3 2>/dev/null | sort)
        echo ""
    fi

    if [[ "${found}" != "true" ]]; then
        echo "  (none found)"
        echo ""
        echo "To add a standard, create a markdown file at:"
        echo "  .agents/standards/<name>.md     (project-local)"
        echo "  ~/.agents/standards/<name>.md   (user-global)"
    fi
}

# ---------------------------------------------------------------------------
# Main: argument dispatch
# ---------------------------------------------------------------------------
main() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: standards-loader.sh [--proj-root <path>] <command> [args]" >&2
        echo "" >&2
        echo "Global options:" >&2
        echo "  --proj-root <path>   Override project root (default: \$PWD)" >&2
        echo "" >&2
        echo "Commands:" >&2
        echo "  --load <name>                         Load a standard (mechanism b)" >&2
        echo "  --generate-adapter <skill> [--target <file>]  Generate AGENTS.md adapter (mechanism a)" >&2
        echo "  --list                                List available standards" >&2
        exit 1
    fi

    # Parse optional global --proj-root flag before the subcommand.
    # This allows callers in other projects to specify their project root explicitly:
    #   bash /path/to/standards-loader.sh --proj-root /my/project --load dolt
    while [[ $# -gt 0 && "$1" == --proj-root ]]; do
        shift
        if [[ $# -eq 0 ]]; then
            echo "--proj-root requires a path argument" >&2
            exit 1
        fi
        PROJ_ROOT="$(cd "$1" && pwd)"
        shift
    done

    if [[ $# -eq 0 ]]; then
        echo "No command given after --proj-root. Use --load, --generate-adapter, or --list." >&2
        exit 1
    fi

    local cmd="$1"
    shift

    case "${cmd}" in
        --load)
            if [[ $# -eq 0 ]]; then
                echo "Usage: standards-loader.sh --load <standard-name>" >&2
                exit 1
            fi
            cmd_load "$1"
            ;;
        --generate-adapter)
            if [[ $# -eq 0 ]]; then
                echo "Usage: standards-loader.sh --generate-adapter <skill-name> [--target <file>]" >&2
                exit 1
            fi
            local skill_name="$1"
            shift
            local target_file="${PROJ_ROOT}/AGENTS.md"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --target)
                        shift
                        target_file="$1"
                        shift
                        ;;
                    *)
                        echo "Unknown option: $1" >&2
                        exit 1
                        ;;
                esac
            done
            cmd_generate_adapter "${skill_name}" "${target_file}"
            ;;
        --list)
            cmd_list
            ;;
        *)
            echo "Unknown command: ${cmd}" >&2
            echo "Use --load, --generate-adapter, or --list" >&2
            exit 1
            ;;
    esac
}

main "$@"
