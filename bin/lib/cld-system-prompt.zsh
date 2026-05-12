#!/usr/bin/env zsh
# lib/cld-system-prompt.zsh — System prompt resolution for cld
#
# Provides _cld_resolve_system_prompt() which reads a registry.yml and
# returns the system prompt file + mode for the current working directory.

# _cld_resolve_system_prompt
#
# Args:
#   $1  registry_path  — absolute path to registry.yml
#   $2  working_dir    — directory to match against registry entries
#
# Output (stdout):
#   "file:<relative-path> mode:<replace|append>"  on match
#   empty string on no match
#
# Returns:
#   0  match found (entry or default)
#   1  no match and no default, or registry file missing
_cld_resolve_system_prompt() {
    local registry="$1"
    local workdir="$2"

    [[ -f "$registry" ]] || return 1

    local section=""        # "entries" or "default"
    local entry_match=""
    local entry_file=""
    local entry_mode=""
    local default_file=""
    local default_mode=""

    while IFS= read -r line; do
        case "$line" in
            "entries:")
                section="entries"
                ;;
            "default:")
                section="default"
                if [[ -n "$entry_match" ]] && [[ -z "$entry_file" || -z "$entry_mode" ]]; then
                    echo "[cld-system-prompt] WARN: incomplete registry entry for match='$entry_match' (missing file or mode)" >&2
                fi
                entry_match="" entry_file="" entry_mode=""
                ;;
            "  - match: "*)
                # Start of a new entries block item
                # Warn if the previous entry was incomplete (match set but file/mode missing)
                if [[ -n "$entry_match" ]] && [[ -z "$entry_file" || -z "$entry_mode" ]]; then
                    echo "[cld-system-prompt] WARN: incomplete registry entry for match='$entry_match' (missing file or mode)" >&2
                fi
                entry_match="${line#  - match: }"
                entry_match="${entry_match//\"/}"
                entry_match="${entry_match//\'/}"
                entry_match="${entry_match## }"; entry_match="${entry_match%% }"
                entry_file=""
                entry_mode=""
                ;;
            "    file: "*)
                if [[ "$section" == "entries" ]]; then
                    entry_file="${line#    file: }"
                    entry_file="${entry_file//\"/}"
                    entry_file="${entry_file//\'/}"
                    entry_file="${entry_file## }"; entry_file="${entry_file%% }"
                    # Entry may be complete if mode: came before file: — check now
                    if [[ -n "$entry_match" && -n "$entry_file" && -n "$entry_mode" ]]; then
                        if [[ "$workdir" == "$entry_match" ]] || [[ "$workdir" == "${entry_match}/"* ]]; then
                            echo "file:${entry_file} mode:${entry_mode}"
                            return 0
                        fi
                        entry_match="" entry_file="" entry_mode=""
                    fi
                fi
                ;;
            "    mode: "*)
                if [[ "$section" == "entries" ]]; then
                    entry_mode="${line#    mode: }"
                    entry_mode="${entry_mode//\"/}"
                    entry_mode="${entry_mode//\'/}"
                    entry_mode="${entry_mode## }"; entry_mode="${entry_mode%% }"
                    # Entry may be complete if file: came before mode: — check now
                    if [[ -n "$entry_match" && -n "$entry_file" && -n "$entry_mode" ]]; then
                        if [[ "$workdir" == "$entry_match" ]] || [[ "$workdir" == "${entry_match}/"* ]]; then
                            echo "file:${entry_file} mode:${entry_mode}"
                            return 0
                        fi
                        entry_match="" entry_file="" entry_mode=""
                    fi
                fi
                ;;
            "  file: "*)
                if [[ "$section" == "default" ]]; then
                    default_file="${line#  file: }"
                    default_file="${default_file//\"/}"
                    default_file="${default_file//\'/}"
                    default_file="${default_file## }"; default_file="${default_file%% }"
                fi
                ;;
            "  mode: "*)
                if [[ "$section" == "default" ]]; then
                    default_mode="${line#  mode: }"
                    default_mode="${default_mode//\"/}"
                    default_mode="${default_mode//\'/}"
                    default_mode="${default_mode## }"; default_mode="${default_mode%% }"
                fi
                ;;
            "#"*|"") ;;  # skip comments and blank lines
            *)
                # Unrecognized line — warn in debug mode
                [[ "${CLD_DEBUG:-}" == "1" ]] && echo "[cld-system-prompt] WARN: unrecognized line: $line" >&2
                ;;
        esac
    done < "$registry"

    # Warn if the final entry before EOF was incomplete
    if [[ -n "$entry_match" ]] && [[ -z "$entry_file" || -z "$entry_mode" ]]; then
        echo "[cld-system-prompt] WARN: incomplete registry entry for match='$entry_match' (missing file or mode)" >&2
    fi

    # No entry matched — try default
    if [[ -n "$default_file" && -n "$default_mode" ]]; then
        echo "file:${default_file} mode:${default_mode}"
        return 0
    fi

    return 1
}
