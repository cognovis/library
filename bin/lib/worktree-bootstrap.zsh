#!/usr/bin/env zsh
# lib/worktree-bootstrap.zsh — prepare ignored agent overlays in bead worktrees.
#
# Project-local agent and skill installs are intentionally gitignored in some
# repos. A fresh git worktree therefore starts without the runtime overlay that
# the main checkout has already installed. This helper reads:
#
#   worktree_bootstrap:
#     symlink_from_main:
#       - .agents
#       - .claude/skills
#
# from the project-local .agents/orchestrator-config.yml, falling back to the
# user-global ~/.agents/orchestrator-config.yml, and symlinks each existing path
# from the main checkout into the bead worktree. The two recurring runtime
# overlay paths are safe built-in defaults; config can add more paths.

_worktree_bootstrap_default_entries() {
    printf '%s\n' ".agents" ".claude/skills"
}

_worktree_bootstrap_config_path() {
    local repo_root="$1"
    local project_config="${repo_root}/.agents/orchestrator-config.yml"
    local global_config="${HOME}/.agents/orchestrator-config.yml"

    if [[ -f "$project_config" ]]; then
        printf '%s\n' "$project_config"
    elif [[ -f "$global_config" ]]; then
        printf '%s\n' "$global_config"
    fi
}

_worktree_bootstrap_symlink_entries() {
    local config_path="$1"

    [[ -f "$config_path" ]] || return 0

    awk '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
        {
            line = $0
            sub(/[[:space:]]+#.*/, "", line)

            if (line ~ /^[^[:space:]][^:]*:[[:space:]]*$/) {
                top = line
                sub(/:.*/, "", top)
                in_bootstrap = (top == "worktree_bootstrap")
                in_list = 0
                next
            }

            if (in_bootstrap && line ~ /^  symlink_from_main:[[:space:]]*$/) {
                in_list = 1
                next
            }

            if (in_bootstrap && in_list && line ~ /^    -[[:space:]]+/) {
                value = line
                sub(/^    -[[:space:]]*/, "", value)
                gsub(/^[" ]+|[" ]+$/, "", value)
                gsub(/\/+$/, "", value)
                if (value != "") {
                    print value
                }
                next
            }

            if (in_bootstrap && in_list && (line ~ /^  [^[:space:]-][^:]*:/ || line ~ /^[^[:space:]]/)) {
                in_list = 0
            }
        }
    ' "$config_path"
}

_worktree_bootstrap_is_safe_relative_path() {
    local rel="$1"

    case "$rel" in
        ""|/*|..|../*|*/../*|*/..)
            return 1
            ;;
    esac
    return 0
}

_worktree_bootstrap_exclude_path() {
    local repo_root="$1"
    local rel="$2"
    local git_bin="${GIT_BIN:-git}"
    local exclude_file

    exclude_file="$("$git_bin" -C "$repo_root" rev-parse --git-path info/exclude 2>/dev/null)" || return 0
    [[ -n "$exclude_file" ]] || return 0
    if [[ "$exclude_file" != /* ]]; then
        exclude_file="${repo_root}/${exclude_file}"
    fi

    mkdir -p "${exclude_file:h}" 2>/dev/null || return 0
    if [[ ! -f "$exclude_file" ]] || ! grep -qxF "$rel" "$exclude_file" 2>/dev/null; then
        {
            printf '\n# bead worktree runtime overlay symlinks\n'
            printf '%s\n' "$rel"
        } >> "$exclude_file" 2>/dev/null || return 0
    fi
}

_bootstrap_worktree_from_main() {
    local repo_root="${1:A}"
    local worktree_dir="${2:A}"
    local config_path
    local rel src dst current_target

    config_path="$(_worktree_bootstrap_config_path "$repo_root")"

    {
        _worktree_bootstrap_default_entries
        if [[ -n "$config_path" ]]; then
            _worktree_bootstrap_symlink_entries "$config_path"
        fi
    } | while IFS= read -r rel; do
        _worktree_bootstrap_is_safe_relative_path "$rel" || continue

        src="${repo_root}/${rel}"
        dst="${worktree_dir}/${rel}"

        [[ -e "$src" || -L "$src" ]] || continue

        mkdir -p "${dst:h}" 2>/dev/null || continue

        if [[ -L "$dst" ]]; then
            current_target="$(readlink "$dst" 2>/dev/null || true)"
            if [[ "$current_target" == "$src" ]]; then
                continue
            fi
            rm "$dst" 2>/dev/null || {
                print -r -- "[worktree-bootstrap] cannot replace symlink: ${dst}" >&2
                continue
            }
        elif [[ -e "$dst" ]]; then
            print -r -- "[worktree-bootstrap] skip existing non-symlink: ${dst}" >&2
            continue
        fi

        if ln -s "$src" "$dst" 2>/dev/null; then
            _worktree_bootstrap_exclude_path "$repo_root" "$rel"
            print -r -- "[worktree-bootstrap] linked ${dst/#$HOME/~} -> ${src/#$HOME/~}" >&2
        fi
    done

    return 0
}
