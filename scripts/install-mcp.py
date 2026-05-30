#!/usr/bin/env python3
"""install-mcp.py — Install an MCP server per library.yaml library.mcp_servers entry.

Parallel to install-hook.py. Reads a `library.mcp_servers:` entry from library.yaml,
extracts the per-harness snippet from `install.mcp.<harness>`, and writes it
into the target harness config file under the correct top-level key. Tags
every entry with `_origin = "library:mcp:<name>"` for idempotent re-install
and clean `--remove`.

Supported harnesses (CL-l0c Deliverable D; antigravity + cursor added in CL-qdtc;
config paths corrected in CL-oo82):
  claude_code  -> ~/.claude.json                       ("mcpServers" map)
  codex        -> ~/.codex/config.toml                 ("mcp_servers" table)
  opencode     -> ~/.config/opencode/opencode.json     ("mcp" map)
  antigravity  -> ~/.gemini/config/mcp_config.json     ("mcpServers" map)
  cursor       -> ~/.cursor/mcp.json                   ("mcpServers" map)
  claude_ai    -> emits install URL (manual: no programmatic install)
  claude_ios   -> emits install URL (manual: no programmatic install)
  all          -> every harness that the entry declares (default)

NOTE: claude_code user-scoped MCP servers live in the top-level `mcpServers` map
of ~/.claude.json — NOT ~/.claude/settings.json (that file holds permissions,
hooks, and env; its `mcpServers` key is ignored by Claude Code). Antigravity
(Gemini/Codeium CLI, `agy`) reads MCP servers from ~/.gemini/config/mcp_config.json.

Usage:
    install-mcp.py <name>                          # install to all declared harnesses
    install-mcp.py <name> --harness codex          # one harness
    install-mcp.py <name> --dry-run                # preview only
    install-mcp.py <name> --remove                 # uninstall (drop by _origin tag)

Designed for ADR-0004 (cross-harness install) and CL-l0c Deliverable D.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from lib.catalog import get_entries


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LIBRARY_YAML = REPO_ROOT / "library.yaml"

# Default config paths (override via env vars for testing).
# Claude Code reads user-scoped MCP servers from the top-level `mcpServers` map of
# ~/.claude.json (NOT ~/.claude/settings.json — that file is for permissions/hooks/env).
CLAUDE_SETTINGS = Path(
    os.environ.get("CLAUDE_SETTINGS_FILE", str(Path.home() / ".claude.json"))
)
CODEX_CONFIG_TOML = Path(
    os.environ.get("CODEX_CONFIG_FILE", str(Path.home() / ".codex" / "config.toml"))
)
OPENCODE_CONFIG = Path(
    os.environ.get(
        "OPENCODE_CONFIG_FILE",
        str(Path.home() / ".config" / "opencode" / "opencode.json"),
    )
)
# Antigravity (Gemini/Codeium CLI, `agy`) reads MCP servers from
# ~/.gemini/config/mcp_config.json (NOT ~/.config/gemini/settings.json).
GEMINI_SETTINGS = Path(
    os.environ.get(
        "GEMINI_SETTINGS_FILE",
        str(Path.home() / ".gemini" / "config" / "mcp_config.json"),
    )
)
CURSOR_MCP_CONFIG = Path(
    os.environ.get("CURSOR_MCP_FILE", str(Path.home() / ".cursor" / "mcp.json"))
)

ORIGIN_PREFIX = "library:mcp:"


# ---------------------------------------------------------------------------
# YAML / catalog loading
# ---------------------------------------------------------------------------


def load_library() -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML required: pip install pyyaml")
    with LIBRARY_YAML.open() as f:
        return yaml.safe_load(f)


def find_mcp_entry(library: dict, name: str) -> dict:
    """Locate an MCP server entry by name in library.yaml."""
    for entry in get_entries(library, "mcp"):
        if entry.get("name") == name:
            return entry
    sys.exit(f"MCP server {name!r} not found in library.yaml library.mcp_servers")


def harness_block(entry: dict, harness: str) -> dict | None:
    """Return install.mcp.<harness> block or None if not declared."""
    return (entry.get("install", {}) or {}).get("mcp", {}).get(harness)


# ---------------------------------------------------------------------------
# JSON helpers (claude_code, opencode)
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open() as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if path.is_file():
        backup.write_text(path.read_text())
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _merge_json_map(
    config: dict, top_level_key: str, name: str, snippet: dict, origin: str
) -> tuple[dict, str]:
    """Merge snippet into config[top_level_key][name] with _origin tag.

    Returns (updated_config, action) where action is one of:
      "installed", "refreshed", "skipped_manual", "no_change"
    """
    config = json.loads(json.dumps(config))  # deep copy
    container = config.setdefault(top_level_key, {})
    existing = container.get(name)

    new_entry = dict(snippet)
    new_entry["_origin"] = origin

    if existing is None:
        container[name] = new_entry
        return config, "installed"

    if existing.get("_origin") == origin:
        # Library-managed: refresh in place.
        if existing == new_entry:
            return config, "no_change"
        container[name] = new_entry
        return config, "refreshed"

    # Manual / foreign entry — refuse to clobber.
    return config, "skipped_manual"


def _remove_json_map(
    config: dict, top_level_key: str, name: str, origin: str
) -> tuple[dict, bool]:
    """Remove config[top_level_key][name] if _origin matches. Returns (cfg, removed)."""
    config = json.loads(json.dumps(config))
    container = config.get(top_level_key, {})
    existing = container.get(name)
    if existing is None:
        return config, False
    if existing.get("_origin") != origin:
        print(
            f"  WARN: {top_level_key}.{name} not library-managed (origin={existing.get('_origin')!r}); leaving alone",
            file=sys.stderr,
        )
        return config, False
    del container[name]
    if not container:
        config.pop(top_level_key, None)
    return config, True


# ---------------------------------------------------------------------------
# TOML helpers (codex)
# ---------------------------------------------------------------------------


def _load_toml(path: Path):
    """Read TOML as a tomlkit document (preserves comments + formatting)."""
    try:
        import tomlkit
    except ImportError:
        sys.exit("tomlkit required for Codex TOML manipulation: pip install tomlkit")
    if not path.is_file():
        return tomlkit.document()
    with path.open() as f:
        return tomlkit.parse(f.read())


def _write_toml(path: Path, doc) -> None:
    try:
        import tomlkit
    except ImportError:
        sys.exit("tomlkit required for Codex TOML manipulation: pip install tomlkit")
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if path.is_file():
        backup.write_text(path.read_text())
    with path.open("w") as f:
        f.write(tomlkit.dumps(doc))


def _merge_toml_table(
    doc, table_name: str, name: str, snippet: dict, origin: str
) -> tuple[Any, str]:
    """Merge snippet into doc[table_name][name] as a TOML sub-table.

    Returns (updated_doc, action).
    """
    import tomlkit

    table = doc.get(table_name)
    if table is None:
        table = tomlkit.table()
        doc[table_name] = table

    existing = table.get(name)
    if existing is not None:
        existing_origin = (
            existing.get("_origin") if hasattr(existing, "get") else None
        )
        if existing_origin == origin:
            # refresh
            for key in list(existing.keys()):
                del existing[key]
            for key, value in snippet.items():
                existing[key] = value
            existing["_origin"] = origin
            return doc, "refreshed"
        return doc, "skipped_manual"

    new_table = tomlkit.table()
    for key, value in snippet.items():
        new_table[key] = value
    new_table["_origin"] = origin
    table[name] = new_table
    return doc, "installed"


def _remove_toml_table(
    doc, table_name: str, name: str, origin: str
) -> tuple[Any, bool]:
    """Remove doc[table_name][name] if _origin matches."""
    table = doc.get(table_name)
    if table is None or name not in table:
        return doc, False
    existing = table[name]
    existing_origin = existing.get("_origin") if hasattr(existing, "get") else None
    if existing_origin != origin:
        print(
            f"  WARN: {table_name}.{name} not library-managed (origin={existing_origin!r}); leaving alone",
            file=sys.stderr,
        )
        return doc, False
    del table[name]
    if not len(table):
        del doc[table_name]
    return doc, True


# ---------------------------------------------------------------------------
# Per-harness install handlers
# ---------------------------------------------------------------------------


def install_claude_code(
    name: str, block: dict, dry_run: bool, remove: bool
) -> int:
    """Install/remove in ~/.claude/settings.json under mcpServers."""
    settings = _load_json(CLAUDE_SETTINGS)
    origin = f"{ORIGIN_PREFIX}{name}"

    if remove:
        updated, removed = _remove_json_map(settings, "mcpServers", name, origin)
        if dry_run:
            print(f"[claude_code] (dry-run) would {'remove' if removed else 'no-op'} mcpServers.{name}")
            return 0
        if removed:
            _write_json(CLAUDE_SETTINGS, updated)
            print(f"[claude_code] removed mcpServers.{name} from {CLAUDE_SETTINGS}")
        else:
            print(f"[claude_code] no library-managed mcpServers.{name} to remove")
        return 0

    snippet = block.get("snippet")
    if not snippet:
        print(f"[claude_code] entry missing install.mcp.claude_code.snippet — skip", file=sys.stderr)
        return 0
    updated, action = _merge_json_map(settings, "mcpServers", name, snippet, origin)
    if dry_run:
        print(f"[claude_code] (dry-run) action={action}")
        print(json.dumps(updated.get("mcpServers", {}).get(name, {}), indent=2))
        return 0
    if action == "skipped_manual":
        print(
            f"[claude_code] mcpServers.{name} exists with non-library _origin; refusing to overwrite",
            file=sys.stderr,
        )
        return 1
    if action == "no_change":
        print(f"[claude_code] mcpServers.{name} already up-to-date (no change)")
        return 0
    _write_json(CLAUDE_SETTINGS, updated)
    print(f"[claude_code] {action} mcpServers.{name} in {CLAUDE_SETTINGS}")
    return 0


def install_codex(name: str, block: dict, dry_run: bool, remove: bool) -> int:
    """Install/remove in ~/.codex/config.toml under [mcp_servers]."""
    doc = _load_toml(CODEX_CONFIG_TOML)
    origin = f"{ORIGIN_PREFIX}{name}"

    if remove:
        updated, removed = _remove_toml_table(doc, "mcp_servers", name, origin)
        if dry_run:
            print(f"[codex] (dry-run) would {'remove' if removed else 'no-op'} mcp_servers.{name}")
            return 0
        if removed:
            _write_toml(CODEX_CONFIG_TOML, updated)
            print(f"[codex] removed mcp_servers.{name} from {CODEX_CONFIG_TOML}")
        else:
            print(f"[codex] no library-managed mcp_servers.{name} to remove")
        return 0

    snippet = block.get("snippet")
    if not snippet:
        print(f"[codex] entry missing install.mcp.codex.snippet — skip", file=sys.stderr)
        return 0
    updated, action = _merge_toml_table(doc, "mcp_servers", name, snippet, origin)
    if dry_run:
        import tomlkit
        print(f"[codex] (dry-run) action={action}")
        section = updated.get("mcp_servers", {}).get(name)
        if section is not None:
            print(tomlkit.dumps({"mcp_servers": {name: section}}))
        return 0
    if action == "skipped_manual":
        print(
            f"[codex] mcp_servers.{name} exists with non-library _origin; refusing to overwrite",
            file=sys.stderr,
        )
        return 1
    _write_toml(CODEX_CONFIG_TOML, updated)
    print(f"[codex] {action} mcp_servers.{name} in {CODEX_CONFIG_TOML}")
    return 0


def install_opencode(name: str, block: dict, dry_run: bool, remove: bool) -> int:
    """Install/remove in ~/.config/opencode/opencode.json under mcp."""
    config = _load_json(OPENCODE_CONFIG)
    origin = f"{ORIGIN_PREFIX}{name}"

    if remove:
        updated, removed = _remove_json_map(config, "mcp", name, origin)
        if dry_run:
            print(f"[opencode] (dry-run) would {'remove' if removed else 'no-op'} mcp.{name}")
            return 0
        if removed:
            _write_json(OPENCODE_CONFIG, updated)
            print(f"[opencode] removed mcp.{name} from {OPENCODE_CONFIG}")
        else:
            print(f"[opencode] no library-managed mcp.{name} to remove")
        return 0

    snippet = block.get("snippet")
    if not snippet:
        print(f"[opencode] entry missing install.mcp.opencode.snippet — skip", file=sys.stderr)
        return 0
    updated, action = _merge_json_map(config, "mcp", name, snippet, origin)
    if dry_run:
        print(f"[opencode] (dry-run) action={action}")
        print(json.dumps(updated.get("mcp", {}).get(name, {}), indent=2))
        return 0
    if action == "skipped_manual":
        print(
            f"[opencode] mcp.{name} exists with non-library _origin; refusing to overwrite",
            file=sys.stderr,
        )
        return 1
    if action == "no_change":
        print(f"[opencode] mcp.{name} already up-to-date (no change)")
        return 0
    _write_json(OPENCODE_CONFIG, updated)
    print(f"[opencode] {action} mcp.{name} in {OPENCODE_CONFIG}")
    return 0


def _install_json_mcp_servers(
    name: str,
    block: dict,
    dry_run: bool,
    remove: bool,
    *,
    harness: str,
    config_path: Path,
) -> int:
    """Install/remove in a JSON config under the standard ``mcpServers`` map.

    Shared by harnesses whose config files use the same ``{"mcpServers": {...}}``
    shape as Claude Code (Gemini CLI / Antigravity, Cursor). The only per-harness
    differences are the config path and the log label.
    """
    config = _load_json(config_path)
    origin = f"{ORIGIN_PREFIX}{name}"

    if remove:
        updated, removed = _remove_json_map(config, "mcpServers", name, origin)
        if dry_run:
            print(f"[{harness}] (dry-run) would {'remove' if removed else 'no-op'} mcpServers.{name}")
            return 0
        if removed:
            _write_json(config_path, updated)
            print(f"[{harness}] removed mcpServers.{name} from {config_path}")
        else:
            print(f"[{harness}] no library-managed mcpServers.{name} to remove")
        return 0

    snippet = block.get("snippet")
    if not snippet:
        print(f"[{harness}] entry missing install.mcp.{harness}.snippet — skip", file=sys.stderr)
        return 0
    updated, action = _merge_json_map(config, "mcpServers", name, snippet, origin)
    if dry_run:
        print(f"[{harness}] (dry-run) action={action}")
        print(json.dumps(updated.get("mcpServers", {}).get(name, {}), indent=2))
        return 0
    if action == "skipped_manual":
        print(
            f"[{harness}] mcpServers.{name} exists with non-library _origin; refusing to overwrite",
            file=sys.stderr,
        )
        return 1
    if action == "no_change":
        print(f"[{harness}] mcpServers.{name} already up-to-date (no change)")
        return 0
    _write_json(config_path, updated)
    print(f"[{harness}] {action} mcpServers.{name} in {config_path}")
    return 0


def install_antigravity(name: str, block: dict, dry_run: bool, remove: bool) -> int:
    """Install/remove in ~/.config/gemini/settings.json under mcpServers."""
    return _install_json_mcp_servers(
        name, block, dry_run, remove, harness="antigravity", config_path=GEMINI_SETTINGS
    )


def install_cursor(name: str, block: dict, dry_run: bool, remove: bool) -> int:
    """Install/remove in ~/.cursor/mcp.json under mcpServers."""
    return _install_json_mcp_servers(
        name, block, dry_run, remove, harness="cursor", config_path=CURSOR_MCP_CONFIG
    )


def install_url_only(name: str, block: dict, dry_run: bool, remove: bool, harness: str) -> int:
    """For claude_ai / claude_ios: emit the manual install URL."""
    url = block.get("install_url", "(no install_url declared)")
    if remove:
        print(
            f"[{harness}] cannot programmatically remove (install was manual via URL). "
            f"Remove from the app UI if needed."
        )
        return 0
    print(f"[{harness}] manual install required — open this URL in the app:")
    print(f"  {url}")
    return 0


# Dispatch table: harness -> handler function
HANDLERS: dict[str, Callable[..., int]] = {
    "claude_code": install_claude_code,
    "codex": install_codex,
    "opencode": install_opencode,
    "antigravity": install_antigravity,
    "cursor": install_cursor,
    "claude_ai": lambda n, b, d, r: install_url_only(n, b, d, r, "claude_ai"),
    "claude_ios": lambda n, b, d, r: install_url_only(n, b, d, r, "claude_ios"),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="library.mcp_servers entry name (e.g. open-brain)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument(
        "--harness",
        choices=list(HANDLERS.keys()) + ["all"],
        default="all",
        help="Target harness (default: all declared in entry).",
    )
    args = ap.parse_args()

    library = load_library()
    entry = find_mcp_entry(library, args.name)
    mcp_block = (entry.get("install", {}) or {}).get("mcp", {})
    if not mcp_block:
        sys.exit(
            f"MCP entry {args.name!r} has no install.mcp.* block; nothing to install"
        )

    declared = list(mcp_block.keys())
    if args.harness == "all":
        targets = declared
    else:
        if args.harness not in declared:
            print(
                f"WARN: harness {args.harness!r} not declared by {args.name!r}. "
                f"Declared: {declared}. Skipping.",
                file=sys.stderr,
            )
            return 0
        targets = [args.harness]

    if not targets:
        print(f"No harness blocks declared for {args.name!r}")
        return 0

    exit_code = 0
    for harness in targets:
        block = mcp_block.get(harness, {}) or {}
        handler = HANDLERS.get(harness)
        if handler is None:
            print(f"WARN: no handler for harness {harness!r}; skipping", file=sys.stderr)
            continue
        result = handler(args.name, block, args.dry_run, args.remove)
        exit_code |= result

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
