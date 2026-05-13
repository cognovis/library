"""
installers/harness_materializer.py — Materialize always_apply/globs into harness-native formats.

When a library entry has `always_apply: true` or `globs: [...]`, this module
writes the corresponding harness artifacts:

  Claude Code:  Append `@<path>` to CLAUDE.md (always_apply only)
  Codex:        Append `@<path>` to AGENTS.md (always_apply only)
  Cursor:       Write .cursor/rules/<name>.mdc with YAML frontmatter
                (both always_apply and globs)

For globs-only (no always_apply): Cursor gets the .mdc; Claude Code and Codex
emit a warning to stderr and are NOT modified.

No-op rule: if neither always_apply nor globs is set, do nothing.
Idempotent: if the @-import is already present, it is not duplicated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_harness_fields(
    entry: dict,
    name: str,
    primitive_type: str,
    repo_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Materialize always_apply / globs into harness-native formats.

    Args:
        entry:          Catalog entry dict (may contain always_apply and/or globs).
        name:           Primitive name (e.g. "my-skill").
        primitive_type: "skill" or "standard".
        repo_root:      Project root directory.
        dry_run:        If True, return planned ops without writing files.

    Returns:
        dict with keys:
          "operations": list of op dicts (same format as dry_run_result ops)
          "warnings":   list of warning strings (caller must print to stderr)
    """
    always_apply: bool = bool(entry.get("always_apply", False))
    globs: list[str] = entry.get("globs") or []

    operations: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not always_apply and not globs:
        return {"operations": operations, "warnings": warnings}

    # Determine the reference path for the primary artifact
    if primitive_type == "skill":
        import_ref = f"@.agents/skills/{name}/SKILL.md"
    elif primitive_type == "standard":
        import_ref = f"@.agents/standards/{name}/"
    else:
        return {"operations": operations, "warnings": warnings}

    # ------------------------------------------------------------------
    # 1. Cursor: .cursor/rules/<name>.mdc
    # ------------------------------------------------------------------
    mdc_path = repo_root / ".cursor" / "rules" / f"{name}.mdc"
    if always_apply or globs:
        ops, mdc_content = _cursor_mdc_op(name, mdc_path, always_apply, globs, import_ref)
        operations.extend(ops)
        if not dry_run:
            _write_cursor_mdc(mdc_path, mdc_content)

    # ------------------------------------------------------------------
    # 2. Claude Code: CLAUDE.md
    # ------------------------------------------------------------------
    claude_md = repo_root / "CLAUDE.md"
    if always_apply:
        ops = _append_import_op(claude_md, import_ref, "append_claude_md")
        operations.extend(ops)
        if not dry_run:
            _append_import_idempotent(claude_md, import_ref)
    elif globs:
        warn_msg = (
            f"{primitive_type.capitalize()} '{name}' has globs but no always_apply — "
            "CLAUDE.md not modified (globs are not supported natively in Claude Code). "
            "Use Cursor for glob-based rules."
        )
        warnings.append(warn_msg)
        operations.append(
            {
                "operation": "harness_warning_claude_md",
                "path": str(claude_md),
                "details": warn_msg,
            }
        )

    # ------------------------------------------------------------------
    # 3. Codex: AGENTS.md
    # ------------------------------------------------------------------
    agents_md = repo_root / "AGENTS.md"
    if always_apply:
        ops = _append_import_op(agents_md, import_ref, "append_agents_md")
        operations.extend(ops)
        if not dry_run:
            _append_import_idempotent(agents_md, import_ref)
    elif globs:
        warn_msg = (
            f"{primitive_type.capitalize()} '{name}' has globs but no always_apply — "
            "AGENTS.md not modified (globs are not supported natively in Codex). "
            "Use Cursor for glob-based rules."
        )
        warnings.append(warn_msg)
        operations.append(
            {
                "operation": "harness_warning_agents_md",
                "path": str(agents_md),
                "details": warn_msg,
            }
        )

    return {"operations": operations, "warnings": warnings}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cursor_mdc_op(
    name: str,
    mdc_path: Path,
    always_apply: bool,
    globs: list[str],
    import_ref: str,
) -> tuple[list[dict[str, Any]], str]:
    """Build the Cursor .mdc op dict and file content."""
    frontmatter_lines = ["---"]
    if always_apply:
        frontmatter_lines.append("alwaysApply: true")
    if globs:
        globs_yaml = ", ".join(f'"{g}"' for g in globs)
        frontmatter_lines.append(f"globs: [{globs_yaml}]")
    frontmatter_lines.append("---")
    frontmatter_lines.append(import_ref)
    content = "\n".join(frontmatter_lines) + "\n"

    ops = [
        {
            "operation": "write_cursor_mdc",
            "path": str(mdc_path),
            "details": f"write Cursor rule .mdc for '{name}' at {mdc_path}",
        }
    ]
    return ops, content


def _write_cursor_mdc(mdc_path: Path, content: str) -> None:
    """Create parent directories and write the .mdc file."""
    mdc_path.parent.mkdir(parents=True, exist_ok=True)
    mdc_path.write_text(content, encoding="utf-8")


def _append_import_op(
    target: Path, import_ref: str, op_name: str
) -> list[dict[str, Any]]:
    """Return a planned op dict for appending an @-import to a harness file."""
    return [
        {
            "operation": op_name,
            "path": str(target),
            "details": f"append '{import_ref}' to {target.name} (idempotent)",
        }
    ]


def _append_import_idempotent(target: Path, import_ref: str) -> None:
    """Append import_ref to target file if not already present.

    Creates the file if it does not exist.
    """
    if target.exists():
        existing = target.read_text(encoding="utf-8")
    else:
        existing = ""

    if import_ref in existing:
        return  # idempotent — already present

    # Append on a new line (ensure a trailing newline before the import)
    if existing and not existing.endswith("\n"):
        existing += "\n"
    existing += import_ref + "\n"
    target.write_text(existing, encoding="utf-8")
