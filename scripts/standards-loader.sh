#!/usr/bin/env bash
# standards-loader.sh — Standards file resolver
#
# Bead: CL-v56 | Epic: CL-36o (Multi-Harness Library)
#
# Usage:
#   standards-loader.sh --load <standard-name>
#     Load a single standard by name, resolve via project>global precedence,
#     write content to stdout. Warn on stderr if not found (warn-and-continue).
#
#   standards-loader.sh --list
#     List all available standards by scanning .agents/standards/ and
#     ~/.agents/standards/ directories.
#
# Path resolution (project-local ALWAYS overrides global):
#   1. ${PROJ_ROOT}/.agents/standards/<name>.md   (project-local)
#   2. ~/.agents/standards/<name>.md               (user-global)
#   3. ~/.agents/standards/**/<name>.md            (bundle subdir layout, recursive)
#
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

    # Priority 2: user-global (flat lookup)
    local global_path="${HOME}/.agents/standards/${name}.md"
    if [[ -f "${global_path}" ]]; then
        echo "${global_path}"
        return 0
    fi

    # Priority 3: user-global recursive lookup — bundle layout
    # Scan ~/.agents/standards/**/<name>.md so requires_standards: tool-standards
    # resolves to ~/.agents/standards/dev-tools/tool-standards.md, etc.
    local nested_path
    if nested_path="$(find "${HOME}/.agents/standards" -name "${name}.md" -maxdepth 3 2>/dev/null | head -1)"; then
        if [[ -n "${nested_path}" ]]; then
            echo "${nested_path}"
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
# resolve_model_standard <name>
#   Resolves a model-standard name to a file path using project>global precedence.
#   Model-standards live in .agents/model-standards/ (parallel to .agents/standards/).
#
#   Resolution order:
#   1. Exact filename match: .agents/model-standards/<name>.md
#   2. Alias scan: search all .md files in .agents/model-standards/ for a
#      model_aliases frontmatter field containing <name> as a value.
#      (Supports short names like 'sonnet' resolving to 'claude-sonnet-4-6.md')
#
#   For each priority tier (project-local, then user-global), try exact then alias.
#
#   Prints the resolved path to stdout.
#   Exits 0 on success, 1 if not found.
# ---------------------------------------------------------------------------
resolve_model_standard() {
    local name="$1"

    # Priority 1: project-local — exact filename
    local proj_path="${PROJ_ROOT}/.agents/model-standards/${name}.md"
    if [[ -f "${proj_path}" ]]; then
        echo "${proj_path}"
        return 0
    fi

    # Priority 2: project-local — alias scan
    if [[ -d "${PROJ_ROOT}/.agents/model-standards" ]]; then
        local alias_match
        alias_match="$(resolve_model_standard_by_alias "${name}" "${PROJ_ROOT}/.agents/model-standards")"
        if [[ -n "${alias_match}" ]]; then
            echo "${alias_match}"
            return 0
        fi
    fi

    # Priority 3: user-global — exact filename
    local global_path="${HOME}/.agents/model-standards/${name}.md"
    if [[ -f "${global_path}" ]]; then
        echo "${global_path}"
        return 0
    fi

    # Priority 4: user-global — alias scan
    if [[ -d "${HOME}/.agents/model-standards" ]]; then
        local alias_match
        alias_match="$(resolve_model_standard_by_alias "${name}" "${HOME}/.agents/model-standards")"
        if [[ -n "${alias_match}" ]]; then
            echo "${alias_match}"
            return 0
        fi
    fi

    # Not found — model-standards have no fallback path
    return 1
}

# ---------------------------------------------------------------------------
# resolve_model_standard_by_alias <alias> <search_dir>
#   Scans all .md files in <search_dir> for a model_aliases frontmatter field
#   containing <alias> as a value. Returns the first matching file path.
#   Used as a fallback when exact filename lookup fails.
#   Prints the matched path to stdout (empty if not found).
# ---------------------------------------------------------------------------
resolve_model_standard_by_alias() {
    local alias_name="$1"
    local search_dir="$2"

    # Use Python for YAML frontmatter parsing — portable across bash 3.2+.
    python3 - "${alias_name}" "${search_dir}" <<'PYEOF'
import sys, re
from pathlib import Path

alias = sys.argv[1]
search_dir = Path(sys.argv[2])

if not search_dir.is_dir():
    sys.exit(0)

for md_file in sorted(search_dir.glob('*.md')):
    try:
        content = md_file.read_text(encoding='utf-8')
    except OSError:
        continue

    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not m:
        continue

    frontmatter = m.group(1)

    # Check for model_aliases field.
    # Supports both inline: model_aliases: [a, b, c]
    # and block:
    #   model_aliases:
    #     - a
    #     - b
    lines = frontmatter.split('\n')
    in_aliases = False
    aliases = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('model_aliases:'):
            rest = stripped[len('model_aliases:'):].strip()
            if rest.startswith('['):
                inner = rest.strip('[]')
                aliases = [n.strip().strip('"\'') for n in inner.split(',') if n.strip()]
                break
            elif rest:
                aliases = [rest.strip().strip('"\'')]
                break
            else:
                in_aliases = True
        elif in_aliases:
            if stripped.startswith('- '):
                aliases.append(stripped[2:].strip().strip('"\''))
            elif stripped and not stripped.startswith('#'):
                break

    if alias in aliases:
        print(str(md_file))
        sys.exit(0)

sys.exit(0)
PYEOF
}

# ---------------------------------------------------------------------------
# cmd_load_model_standard <name>
#   Loads a model-standard by name, resolving via project>global precedence.
#   Same warn-and-continue policy as cmd_load.
#   Uses the same frontmatter validation as cmd_load.
# ---------------------------------------------------------------------------
cmd_load_model_standard() {
    local name="$1"
    local path

    if path="$(resolve_model_standard "${name}" 2>/dev/null)"; then
        # Validate frontmatter before emitting content (same check as cmd_load).
        python3 - "${path}" "${name}" >&2 <<'PYEOF'
import sys, re

standard_file = sys.argv[1]
standard_name = sys.argv[2]
required_fields = ['name', 'version', 'description']

with open(standard_file) as f:
    content = f.read()

m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not m:
    print(f"[standards-loader] WARNING: model-standard '{standard_name}' has no YAML frontmatter. "
          f"Required fields: {required_fields}. Proceeding anyway.")
    sys.exit(0)

frontmatter_text = m.group(1)
missing = []
for field in required_fields:
    if not re.search(rf'^{re.escape(field)}\s*:', frontmatter_text, re.MULTILINE):
        missing.append(field)

if missing:
    print(f"[standards-loader] WARNING: model-standard '{standard_name}' frontmatter missing required fields: "
          f"{missing}. Proceeding anyway.")
PYEOF
        cat "${path}"
    else
        warn "model-standard '${name}' not found. Checked:"
        warn "  - ${PROJ_ROOT}/.agents/model-standards/${name}.md"
        warn "  - ${HOME}/.agents/model-standards/${name}.md"
        warn "Proceeding without this model-standard."
        # Exit 0: warn-and-continue per loader contract
    fi
}

# ---------------------------------------------------------------------------
# cmd_list
#   Lists all available standards by scanning project-local and global directories.
# ---------------------------------------------------------------------------
cmd_list() {
    local proj_dir="${PROJ_ROOT}/.agents/standards"
    local global_dir="${HOME}/.agents/standards"
    local proj_ms_dir="${PROJ_ROOT}/.agents/model-standards"
    local global_ms_dir="${HOME}/.agents/model-standards"

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

    # Bundle subdirs under user-global (workflow/, python/, dev-tools/, …)
    if [[ -d "${global_dir}" ]]; then
        local has_nested=false
        local nested_label="User-global bundles (${global_dir}):"
        while IFS= read -r f; do
            if [[ "${has_nested}" != "true" ]]; then
                echo "${nested_label}"
                has_nested=true
            fi
            local rel
            rel="$(python3 -c "
import sys
from pathlib import Path
print(Path(sys.argv[1]).relative_to(sys.argv[2]))
" "${f}" "${global_dir}" 2>/dev/null || basename "${f}")"
            echo "  - ${rel}"
            found=true
        done < <(find "${global_dir}" -mindepth 2 -name "*.md" -maxdepth 3 2>/dev/null | sort)
        if [[ "${has_nested}" == "true" ]]; then
            echo ""
        fi
    fi

    if [[ "${found}" != "true" ]]; then
        echo "  (none found)"
        echo ""
        echo "To add a standard, create a markdown file at:"
        echo "  .agents/standards/<name>.md     (project-local)"
        echo "  ~/.agents/standards/<name>.md   (user-global)"
    fi

    echo ""
    echo "Available model-standards:"
    echo ""

    local ms_found=false

    if [[ -d "${proj_ms_dir}" ]]; then
        echo "Project-local (${proj_ms_dir}):"
        while IFS= read -r f; do
            local name
            name="$(basename "${f}" .md)"
            echo "  - ${name}"
            ms_found=true
        done < <(find "${proj_ms_dir}" -name "*.md" -maxdepth 1 2>/dev/null | sort)
        echo ""
    fi

    if [[ -d "${global_ms_dir}" ]]; then
        echo "User-global (${global_ms_dir}):"
        while IFS= read -r f; do
            local name
            name="$(basename "${f}" .md)"
            echo "  - ${name}"
            ms_found=true
        done < <(find "${global_ms_dir}" -name "*.md" -maxdepth 1 2>/dev/null | sort)
        echo ""
    fi

    if [[ "${ms_found}" != "true" ]]; then
        echo "  (none found)"
        echo ""
        echo "To add a model-standard, create a markdown file at:"
        echo "  .agents/model-standards/<model-name>.md     (project-local)"
        echo "  ~/.agents/model-standards/<model-name>.md   (user-global)"
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
        echo "  --load <name>                          Load a project-standard" >&2
        echo "  --load-model-standard <name>           Load a model-standard from .agents/model-standards/" >&2
        echo "  --list                                 List available standards and model-standards" >&2
        echo "" >&2
        echo "Path resolution for standards:       .agents/standards/<name>.md (project) > ~/.agents/standards/<name>.md (global)" >&2
        echo "Path resolution for model-standards: .agents/model-standards/<name>.md (project) > ~/.agents/model-standards/<name>.md (global)" >&2
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
        echo "No command given after --proj-root. Use --load, --load-model-standard, or --list." >&2
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
        --load-model-standard)
            if [[ $# -eq 0 ]]; then
                echo "Usage: standards-loader.sh --load-model-standard <model-standard-name>" >&2
                exit 1
            fi
            cmd_load_model_standard "$1"
            ;;
        --generate-adapter)
            echo "AGENTS.md adapter generation has been removed. Use requires_standards on the consuming skill or agent." >&2
            exit 1
            ;;
        --list)
            cmd_list
            ;;
        *)
            echo "Unknown command: ${cmd}" >&2
            echo "Use --load, --load-model-standard, or --list" >&2
            exit 1
            ;;
    esac
}

main "$@"
