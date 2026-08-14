#!/usr/bin/env zsh
# Resolve the Cognovis Core source files that own single-bead execution policy.

_bead_loop_authority_has_required_files() {
    local root="$1"
    local relative

    for relative in \
        "skills/bead-implementation-loop/SKILL.md" \
        "skills/bead-execution-loop/SKILL.md" \
        "agents/bead-loop-implementer.md"; do
        test -f "${root}/${relative}" || return 1
    done
}

_bead_loop_authority_is_clean() {
    local root="$1"
    local git_bin="$2"
    local -a paths=(
        "skills/bead-implementation-loop/SKILL.md"
        "skills/bead-execution-loop/SKILL.md"
        "agents/bead-loop-implementer.md"
    )

    "${git_bin}" -C "${root}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 1
    local relative
    for relative in "${paths[@]}"; do
        "${git_bin}" -C "${root}" cat-file -e "HEAD:${relative}" 2>/dev/null || return 1
    done
    "${git_bin}" -C "${root}" diff --quiet -- "${paths[@]}" || return 1
    "${git_bin}" -C "${root}" diff --cached --quiet -- "${paths[@]}" || return 1
}

_resolve_bead_loop_authority() {
    local git_bin="${BEAD_LOOP_AUTHORITY_GIT_BIN:-$(command -v git 2>/dev/null || true)}"
    local override="${COGNOVIS_CORE_AUTHORITY_ROOT:-}"
    local candidate=""
    local source=""

    test -n "${git_bin}" || {
        print -r -- "ERROR: git is required to verify the Cognovis Core bead-loop authority." >&2
        return 2
    }

    if test -n "${override}"; then
        candidate="${override:A}"
        source="explicit override"
        if ! _bead_loop_authority_has_required_files "${candidate}" || \
            ! _bead_loop_authority_is_clean "${candidate}" "${git_bin}"; then
            print -r -- "ERROR: COGNOVIS_CORE_AUTHORITY_ROOT is not a clean Cognovis Core source tree: ${candidate}" >&2
            return 2
        fi
    else
        local dev_checkout="${HOME}/code/library/cognovis-core"
        local catalog_clone="${HOME}/.local/share/library/cognovis-library-core"

        if _bead_loop_authority_has_required_files "${dev_checkout}" && \
            _bead_loop_authority_is_clean "${dev_checkout}" "${git_bin}"; then
            candidate="${dev_checkout:A}"
            source="canonical checkout"
        elif _bead_loop_authority_has_required_files "${catalog_clone}" && \
            _bead_loop_authority_is_clean "${catalog_clone}" "${git_bin}"; then
            candidate="${catalog_clone:A}"
            source="installed catalog clone"
        else
            print -r -- "ERROR: no clean Cognovis Core source authority is available for bead mode." >&2
            print -r -- "Set COGNOVIS_CORE_AUTHORITY_ROOT to a clean checkout or refresh the installed catalog clone." >&2
            return 2
        fi
    fi

    BEAD_LOOP_AUTHORITY_ROOT="${candidate}"
    BEAD_LOOP_AUTHORITY_REVISION="$("${git_bin}" -C "${candidate}" rev-parse HEAD 2>/dev/null)" || return 2
    BEAD_LOOP_AUTHORITY_SOURCE="${source}"
    export BEAD_LOOP_AUTHORITY_ROOT BEAD_LOOP_AUTHORITY_REVISION BEAD_LOOP_AUTHORITY_SOURCE
}

_bead_loop_authority_prompt() {
    cat <<EOF
Cognovis Core bead-loop authority: ${BEAD_LOOP_AUTHORITY_ROOT} (Git revision ${BEAD_LOOP_AUTHORITY_REVISION}, ${BEAD_LOOP_AUTHORITY_SOURCE}). Before acting, read these source files directly:
- ${BEAD_LOOP_AUTHORITY_ROOT}/skills/bead-implementation-loop/SKILL.md
- ${BEAD_LOOP_AUTHORITY_ROOT}/skills/bead-execution-loop/SKILL.md
- ${BEAD_LOOP_AUTHORITY_ROOT}/agents/bead-loop-implementer.md

These revision-bound source files supersede same-named home-scoped projections. Follow implementation and review policy only from these files; the launcher does not define reviewer ordering, models, rounds, receipts, or verdict format.
EOF
}
