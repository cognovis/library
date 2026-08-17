"""
harness_instructions.py — Install the per-harness instruction files (CL-xgpw).

The instruction files are what a coding harness reads before anything else:
`~/.agents/AGENTS.md` for the provider-neutral base, `~/.claude/CLAUDE.md`,
`~/.codex/AGENTS.md`, `~/.kimi-code/AGENTS.md`, `~/.gemini/GEMINI.md`, and a
Cursor rule under `~/.cursor/rules/`. They carry the base knowledge about the
Library, so a harness that opens a repository knows how to find the rest.

Installing them is its own operation, not a scope of the desired state.
ADR-0012 leaves Library exactly one desired state — the current Git repository
— and `--scope` is rejected outright. That decision stands here: this module is
reached only through `library harness sync`, whose name states its blast radius,
and it never touches a lockfile or a project tree.

Two properties matter more than the copying:

  * Consistency. Every installed file must resolve to the shared base, and must
    say so in its own text (FALLBACK_MARKER). Five files generated from one
    source that do not reference each other reproduce the defect this replaced.
  * Loudness. A tracked instruction file that cannot be written raises. The
    predecessor reported "refreshed" while skipping both home targets, which
    hid undeployed edits for as long as nobody diffed the target by hand.

Delivery shapes, chosen per harness from what that harness actually reads:

  file        Write the composed source verbatim (the base, and CLAUDE.md).
  symlink     Point at an already-declared file (Codex, Kimi — both read
              AGENTS.md natively, so a link cannot go stale).
  projection  Write an envelope plus the base body (Gemini reads only
              GEMINI.md; Cursor needs `alwaysApply: true` frontmatter before it
              treats a rule as always-on).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from .errors import InstallError
from .runtime_config import compose_for_entry

#: Every installed instruction file must state the fallback rule, or a harness
#: that finds no harness-specific file never learns where the shared base lives.
#: This is a phrase from that sentence rather than the bare path, because the
#: path alone occurs incidentally in the base file's own header — a guard that
#: matched it would pass for the wrong reason.
FALLBACK_MARKER = "no harness-specific instruction file"

VALID_SHAPES = ("file", "symlink", "projection")

#: Catalog key that marks a runtime-config as a harness instruction file.
DECLARATION_KEY = "harness_instruction"


def _entries(catalog: dict) -> list[dict[str, Any]]:
    section = (catalog.get("library") or {}).get("runtime_configs") or []
    return [item for item in section if isinstance(item, dict)]


def _expand(raw: str, home: Path) -> Path:
    """Expand a declared target path against the given home.

    Declared paths come from the trusted, versioned catalog, so (like
    ``default_dirs``) they are not sandboxed against traversal.
    """
    text = str(raw)
    if text.startswith("~/"):
        return home / text[2:]
    if text == "~":
        return home
    return Path(text)


def resolve_harness_targets(catalog: dict, home: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return every declared instruction target, in declaration order.

    A runtime-config without a ``harness_instruction`` block is an ordinary
    entry and is not an instruction file.
    """
    home = home or Path.home()
    targets: list[dict[str, Any]] = []

    for entry in _entries(catalog):
        declaration = entry.get(DECLARATION_KEY)
        if not declaration:
            continue
        name = entry.get("name", "<unnamed>")
        declared = declaration.get("targets") if isinstance(declaration, dict) else None
        if not declared:
            raise InstallError(
                f"runtime-config '{name}' declares '{DECLARATION_KEY}' with no targets."
            )

        for item in declared:
            shape = item.get("shape", "file")
            if shape not in VALID_SHAPES:
                raise InstallError(
                    f"runtime-config '{name}' declares unknown harness target shape "
                    f"'{shape}' (expected one of {', '.join(VALID_SHAPES)})."
                )
            if shape == "symlink" and not item.get("link_to"):
                raise InstallError(
                    f"runtime-config '{name}' declares a 'symlink' target for harness "
                    f"'{item.get('harness')}' without 'link_to'."
                )
            targets.append(
                {
                    "entry": name,
                    "harness": item.get("harness", "<unnamed>"),
                    "shape": shape,
                    "path": _expand(item.get("path", ""), home),
                    "link_to": _expand(item["link_to"], home) if item.get("link_to") else None,
                    "frontmatter": item.get("frontmatter") or {},
                    "_entry": entry,
                }
            )

    return targets


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_frontmatter(frontmatter: dict[str, Any]) -> str:
    lines = []
    for key, value in frontmatter.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "---\n" + "\n".join(lines) + "\n---\n"


def _render(target: dict[str, Any], composed: str) -> str:
    """Return the exact bytes a non-symlink target must hold."""
    if target["shape"] == "projection" and target["frontmatter"]:
        return _render_frontmatter(target["frontmatter"]) + composed
    return composed


def _composed_for(target: dict[str, Any], catalog: dict, cache: dict[str, str]) -> str:
    """Compose an entry once per run, and refuse a source without the pointer."""
    name = target["entry"]
    if name not in cache:
        composed, _base_commit, _overlay_commit = compose_for_entry(catalog, target["_entry"])
        if FALLBACK_MARKER not in composed:
            raise InstallError(
                f"runtime-config '{name}' does not state the fallback rule "
                f"({FALLBACK_MARKER}). A harness that finds no harness-specific "
                "instruction file would never learn where the shared base lives; "
                "add the pointer to the source before syncing."
            )
        cache[name] = composed
    return cache[name]


def _preflight(target: dict[str, Any], expected: Optional[str], adopt: bool) -> None:
    """Refuse a target before any target is written."""
    path = target["path"]

    parent = path.parent
    for candidate in [parent, *parent.parents]:
        if candidate.exists():
            if not candidate.is_dir():
                raise InstallError(
                    f"Cannot install harness instruction file {path}: "
                    f"{candidate} exists and is not a directory."
                )
            break

    if path.is_symlink() or not path.exists():
        return

    if not path.is_file():
        raise InstallError(
            f"Cannot install harness instruction file {path}: it exists and is not a file."
        )

    if adopt:
        return

    current = path.read_text(encoding="utf-8", errors="replace")
    if not current.strip():
        return
    if expected is not None and current == expected:
        return
    if FALLBACK_MARKER in current:
        # Previously installed by this operation (or an equivalent hand repair).
        return

    raise InstallError(
        f"Refusing to overwrite {path}: it holds content this operation did not "
        "write and does not state the fallback rule. Re-run with --adopt to let "
        "`library harness sync` take ownership of the file."
    )


def _write(target: dict[str, Any], expected: Optional[str]) -> bool:
    """Write one target. Returns True when the bytes on disk changed."""
    path = target["path"]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(
            f"Cannot install harness instruction file {path}: {exc}"
        ) from exc

    if target["shape"] == "symlink":
        destination = target["link_to"]
        if path.is_symlink() and path.readlink() == destination:
            return False
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
            path.symlink_to(destination)
        except OSError as exc:
            raise InstallError(
                f"Cannot install harness instruction file {path}: {exc}"
            ) from exc
        return True

    assert expected is not None
    if path.is_file() and not path.is_symlink():
        if path.read_text(encoding="utf-8", errors="replace") == expected:
            return False
    try:
        if path.is_symlink():
            path.unlink()
        path.write_text(expected, encoding="utf-8")
    except OSError as exc:
        raise InstallError(
            f"Cannot install harness instruction file {path}: {exc}"
        ) from exc
    return True


def sync_harness_instructions(
    catalog: dict,
    home: Optional[Path] = None,
    dry_run: bool = False,
    adopt: bool = False,
) -> dict[str, Any]:
    """Install every declared harness instruction file under ``home``.

    Preflights every target before writing any of them, so a blocked target
    never leaves a half-installed fleet behind.
    """
    home = home or Path.home()
    targets = resolve_harness_targets(catalog, home=home)
    cache: dict[str, str] = {}

    planned: list[tuple[dict[str, Any], Optional[str]]] = []
    for target in targets:
        composed = _composed_for(target, catalog, cache)
        expected = None if target["shape"] == "symlink" else _render(target, composed)
        planned.append((target, expected))

    for target, expected in planned:
        _preflight(target, expected, adopt)

    if dry_run:
        return {
            "status": "dry_run",
            "home": str(home),
            "targets": [
                {
                    "entry": target["entry"],
                    "harness": target["harness"],
                    "shape": target["shape"],
                    "path": str(target["path"]),
                }
                for target, _ in planned
            ],
        }

    written: list[dict[str, Any]] = []
    for target, expected in planned:
        changed = _write(target, expected)
        written.append(
            {
                "entry": target["entry"],
                "harness": target["harness"],
                "shape": target["shape"],
                "path": str(target["path"]),
                "changed": changed,
                "content_sha256": _sha256_text(expected) if expected is not None else "",
            }
        )

    return {"status": "ok", "home": str(home), "targets": written}


def audit_harness_instructions(
    catalog: dict,
    home: Optional[Path] = None,
) -> dict[str, Any]:
    """Report drift for every declared instruction file.

    A file is ``clean`` only when it holds exactly what a sync would write; a
    symlink is clean only while it still points at its declared destination.
    """
    home = home or Path.home()
    targets = resolve_harness_targets(catalog, home=home)
    cache: dict[str, str] = {}

    results: list[dict[str, Any]] = []
    for target in targets:
        composed = _composed_for(target, catalog, cache)
        expected = None if target["shape"] == "symlink" else _render(target, composed)
        path = target["path"]

        record: dict[str, Any] = {
            "entry": target["entry"],
            "harness": target["harness"],
            "shape": target["shape"],
            "path": str(path),
        }

        if target["shape"] == "symlink":
            if not path.is_symlink():
                record["status"] = "missing" if not path.exists() else "drift"
            elif path.readlink() != target["link_to"]:
                record["status"] = "drift"
            else:
                record["status"] = "clean"
            results.append(record)
            continue

        if not path.exists():
            record["status"] = "missing"
        elif path.read_text(encoding="utf-8", errors="replace") == expected:
            record["status"] = "clean"
        else:
            record["status"] = "drift"
        results.append(record)

    return {
        "status": "ok",
        "home": str(home),
        "drift": any(item["status"] != "clean" for item in results),
        "targets": results,
    }
