#!/usr/bin/env python3
"""install-hook.py -- Install a `hooks-manifest`-kind guardrail per ADR-0004 Phase 2.

Reads a guardrail entry from library.yaml whose `kind` is `hooks-manifest`,
fetches the referenced hooks.json from its remote `source:`, caches the
source repo at ~/.local/share/library/guardrails/<name>/checkout/,
resolves ${CLAUDE_PLUGIN_ROOT} to that cache, and merges every declared
hook into the target harness config (idempotent, deep-merge by command).

Supported harnesses:
  claude  -- merges into ~/.claude/settings.json (default)
  codex   -- merges into ~/.codex/hooks.json (Codex CLI)
  all     -- installs to all supported harnesses (default when --harness omitted)

Codex CLI supports only 3 hook events: SessionStart, SessionEnd, Stop.
For any other event (PreToolUse, SubagentStop, etc.), a mismatch_warning is
emitted per the guardrail's capability.codex_cli field and the event is skipped.

Usage:
    install-hook.py <guardrail-name>                        # install to all harnesses
    install-hook.py <guardrail-name> --harness codex        # install to Codex only
    install-hook.py <guardrail-name> --harness claude       # install to Claude only
    install-hook.py <guardrail-name> --dry-run              # preview only, no writes
    install-hook.py <guardrail-name> --remove               # uninstall (drop from configs)

Designed for ADR-0004 Decision 8 -- distribution via /library use.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LIBRARY_YAML = REPO_ROOT / "library.yaml"

LIBRARY_HOME = Path(
    os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
) / "library"
GUARDRAILS_HOME = LIBRARY_HOME / "guardrails"

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

# Codex CLI supports only these 3 hook events.
# All other Claude events must be skipped with a mismatch_warning.
CODEX_SUPPORTED_EVENTS = frozenset({"SessionStart", "SessionEnd", "Stop"})

# Allow override via environment variable for testing.
CODEX_HOOKS_FILE = Path(
    os.environ.get("CODEX_HOOKS_FILE", str(Path.home() / ".codex" / "hooks.json"))
)


def load_library() -> dict:
    """Load library.yaml. Uses PyYAML if available, else minimal fallback."""
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML required: pip install pyyaml")
    with LIBRARY_YAML.open() as f:
        return yaml.safe_load(f)


def find_guardrail(library: dict, name: str) -> dict:
    for entry in library.get("guardrails", []):
        if entry.get("name") == name:
            return entry
    sys.exit(f"Guardrail {name!r} not found in library.yaml")


def parse_github_source(url: str) -> tuple[str, str, str, str]:
    """Parse https://github.com/<org>/<repo>/blob/<ref>/<path> -> (org, repo, ref, path)."""
    p = urlparse(url)
    if p.netloc != "github.com":
        sys.exit(f"Unsupported source host {p.netloc!r} -- only github.com today")
    parts = p.path.lstrip("/").split("/", 4)
    if len(parts) < 5 or parts[2] != "blob":
        sys.exit(f"URL must be of form https://github.com/<org>/<repo>/blob/<ref>/<path>: {url}")
    return parts[0], parts[1], parts[3], parts[4]


def ensure_checkout(org: str, repo: str, ref: str, dest: Path) -> None:
    """Clone or update the source repo at dest."""
    remote = f"git@github.com:{org}/{repo}.git"
    if dest.exists():
        # Refresh
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth=1", "origin", ref],
            check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(dest), "checkout", ref, "--quiet"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", f"origin/{ref}", "--quiet"],
            check=True,
        )
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "--branch", ref, remote, str(dest)],
            check=True,
        )


def load_manifest(checkout: Path, path_in_repo: str) -> dict:
    f = checkout / path_in_repo
    if not f.is_file():
        sys.exit(f"Manifest not found in checkout: {f}")
    with f.open() as fp:
        return json.load(fp)


def resolve_plugin_root(checkout: Path) -> str:
    """${CLAUDE_PLUGIN_ROOT} resolves to the source repo checkout root."""
    return str(checkout.resolve())


def rewrite_commands(manifest: dict, plugin_root: str) -> dict:
    """Replace ${CLAUDE_PLUGIN_ROOT} with absolute path."""
    out = json.loads(json.dumps(manifest))  # deep copy
    pattern = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}")
    for event_entries in out.get("hooks", {}).values():
        for group in event_entries:
            for hook in group.get("hooks", []):
                if "command" in hook:
                    hook["command"] = pattern.sub(plugin_root, hook["command"])
    return out


# ---------------------------------------------------------------------------
# Claude harness (settings.json)
# ---------------------------------------------------------------------------


def load_settings() -> dict:
    if not CLAUDE_SETTINGS.is_file():
        return {}
    with CLAUDE_SETTINGS.open() as f:
        return json.load(f)


def write_settings(data: dict) -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    backup = CLAUDE_SETTINGS.with_suffix(".json.bak")
    if CLAUDE_SETTINGS.is_file():
        backup.write_text(CLAUDE_SETTINGS.read_text())
    with CLAUDE_SETTINGS.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _hook_signature(hook: dict) -> str:
    """Stable key for dedup -- by type+command."""
    return f"{hook.get('type','')}::{hook.get('command','')}"


def merge_hooks(settings: dict, manifest: dict, guardrail_name: str) -> dict:
    """Deep-merge manifest.hooks into settings.hooks with _origin tag."""
    settings = json.loads(json.dumps(settings))
    settings_hooks = settings.setdefault("hooks", {})

    for event, manifest_groups in manifest.get("hooks", {}).items():
        target_event = settings_hooks.setdefault(event, [])
        existing_sigs = {
            _hook_signature(h)
            for group in target_event
            for h in group.get("hooks", [])
        }
        for src_group in manifest_groups:
            new_hooks = []
            for h in src_group.get("hooks", []):
                sig = _hook_signature(h)
                if sig in existing_sigs:
                    continue
                tagged = dict(h)
                tagged["_origin"] = guardrail_name
                new_hooks.append(tagged)
                existing_sigs.add(sig)
            if new_hooks:
                merged_group = dict(src_group)
                merged_group["hooks"] = new_hooks
                target_event.append(merged_group)
    return settings


def remove_hooks(settings: dict, guardrail_name: str) -> dict:
    settings = json.loads(json.dumps(settings))
    hooks = settings.get("hooks", {})
    for event in list(hooks.keys()):
        new_groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if h.get("_origin") != guardrail_name]
            if kept:
                ng = dict(group)
                ng["hooks"] = kept
                new_groups.append(ng)
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    return settings


# ---------------------------------------------------------------------------
# Codex harness (hooks.json)
# ---------------------------------------------------------------------------


def load_codex_hooks() -> dict:
    """Load ~/.codex/hooks.json (or CODEX_HOOKS_FILE override)."""
    if not CODEX_HOOKS_FILE.is_file():
        return {}
    with CODEX_HOOKS_FILE.open() as f:
        return json.load(f)


def write_codex_hooks(data: dict) -> None:
    """Write to CODEX_HOOKS_FILE with backup."""
    CODEX_HOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    backup = CODEX_HOOKS_FILE.with_suffix(".json.bak")
    if CODEX_HOOKS_FILE.is_file():
        backup.write_text(CODEX_HOOKS_FILE.read_text())
    with CODEX_HOOKS_FILE.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _filter_manifest_for_codex(
    manifest: dict,
    guardrail_name: str,
    capability: dict | None,
) -> tuple[dict, list[str]]:
    """Filter manifest hooks to only Codex-supported events.

    Returns:
        codex_manifest: filtered manifest with only supported events.
        warnings: list of mismatch_warning strings for unsupported events.
    """
    warnings: list[str] = []
    codex_hooks: dict[str, list] = {}

    codex_capability = (capability or {}).get("codex_cli", {})

    for event, groups in manifest.get("hooks", {}).items():
        if event in CODEX_SUPPORTED_EVENTS:
            codex_hooks[event] = groups
        else:
            # Emit mismatch_warning -- event not supported by Codex CLI
            mismatch_msg = codex_capability.get(
                "mismatch_warning",
                f"mismatch_warning: event {event!r} is not supported by Codex CLI "
                f"(supports: {sorted(CODEX_SUPPORTED_EVENTS)}). "
                f"Skipped for harness=codex. "
                f"Source: guardrail {guardrail_name!r} capability.codex_cli.",
            )
            warnings.append(
                f"SubagentStop" if event == "SubagentStop" else event
            )
            warnings.append(mismatch_msg)

    codex_manifest = dict(manifest)
    codex_manifest["hooks"] = codex_hooks
    return codex_manifest, warnings


def merge_codex_hooks(
    codex_config: dict,
    manifest: dict,
    guardrail_name: str,
) -> dict:
    """Deep-merge manifest.hooks into codex hooks.json with _origin tag."""
    config = json.loads(json.dumps(codex_config))
    config_hooks = config.setdefault("hooks", {})

    for event, manifest_groups in manifest.get("hooks", {}).items():
        target_event = config_hooks.setdefault(event, [])
        existing_sigs = {
            _hook_signature(h)
            for group in target_event
            for h in group.get("hooks", [])
        }
        for src_group in manifest_groups:
            new_hooks = []
            for h in src_group.get("hooks", []):
                sig = _hook_signature(h)
                if sig in existing_sigs:
                    continue
                tagged = dict(h)
                tagged["_origin"] = f"library:hook:{guardrail_name}"
                new_hooks.append(tagged)
                existing_sigs.add(sig)
            if new_hooks:
                merged_group = dict(src_group)
                merged_group["hooks"] = new_hooks
                target_event.append(merged_group)
    return config


def remove_codex_hooks(codex_config: dict, guardrail_name: str) -> dict:
    """Remove hooks tagged with _origin: library:hook:<guardrail_name>."""
    config = json.loads(json.dumps(codex_config))
    origin_tag = f"library:hook:{guardrail_name}"
    hooks = config.get("hooks", {})
    for event in list(hooks.keys()):
        new_groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if h.get("_origin") != origin_tag]
            if kept:
                ng = dict(group)
                ng["hooks"] = kept
                new_groups.append(ng)
        if new_groups:
            hooks[event] = new_groups
        else:
            del hooks[event]
    return config


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def install_claude_harness(
    args: argparse.Namespace,
    entry: dict,
    checkout: Path,
    manifest: dict,
    resolved: dict,
) -> int:
    """Install/remove hooks for the Claude harness."""
    if args.remove:
        before = load_settings()
        after = remove_hooks(before, args.name)
        if args.dry_run:
            print(json.dumps(after.get("hooks", {}), indent=2))
            return 0
        write_settings(after)
        print(f"[claude] Removed hooks for {args.name!r} from {CLAUDE_SETTINGS}")
        return 0

    settings = load_settings()
    merged = merge_hooks(settings, resolved, args.name)

    if args.dry_run:
        print("[claude] --- preview merged hooks ---")
        print(json.dumps(merged.get("hooks", {}), indent=2))
        return 0

    write_settings(merged)
    n_events = len(resolved.get("hooks", {}))
    n_hooks = sum(
        len(g.get("hooks", []))
        for groups in resolved.get("hooks", {}).values()
        for g in groups
    )
    print(f"[claude] Installed {args.name!r}: {n_hooks} hook(s) across {n_events} event(s)")
    print(f"[claude] Backup: {CLAUDE_SETTINGS.with_suffix('.json.bak')}")
    return 0


def install_codex_harness(
    args: argparse.Namespace,
    entry: dict,
    checkout: Path,
    manifest: dict,
    resolved: dict,
) -> int:
    """Install/remove hooks for the Codex CLI harness."""
    capability = entry.get("capability")

    if args.remove:
        before = load_codex_hooks()
        after = remove_codex_hooks(before, args.name)
        if args.dry_run:
            print(json.dumps(after.get("hooks", {}), indent=2))
            return 0
        write_codex_hooks(after)
        print(f"[codex] Removed hooks for {args.name!r} from {CODEX_HOOKS_FILE}")
        return 0

    # Filter manifest to Codex-supported events; emit warnings for unsupported ones
    codex_manifest, warnings = _filter_manifest_for_codex(resolved, args.name, capability)

    if warnings:
        print(f"[codex] mismatch_warning: the following events in {args.name!r} are not supported by Codex CLI:", file=sys.stderr)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)
        print(f"[codex] Supported Codex events: {sorted(CODEX_SUPPORTED_EVENTS)}", file=sys.stderr)

    codex_config = load_codex_hooks()
    merged = merge_codex_hooks(codex_config, codex_manifest, args.name)

    if args.dry_run:
        print("[codex] --- preview merged hooks (Codex-supported events only) ---")
        installed_events = list(codex_manifest.get("hooks", {}).keys())
        print(f"[codex] Events to install: {installed_events}")
        print(json.dumps(merged.get("hooks", {}), indent=2))
        return 0

    write_codex_hooks(merged)
    n_events = len(codex_manifest.get("hooks", {}))
    n_hooks = sum(
        len(g.get("hooks", []))
        for groups in codex_manifest.get("hooks", {}).values()
        for g in groups
    )
    print(f"[codex] Installed {args.name!r}: {n_hooks} hook(s) across {n_events} event(s)")
    print(f"[codex] Target: {CODEX_HOOKS_FILE}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument(
        "--harness",
        choices=["claude", "codex", "all"],
        default="all",
        help="Target harness to install hooks for (default: all).",
    )
    args = ap.parse_args()

    library = load_library()
    entry = find_guardrail(library, args.name)
    if entry.get("kind") != "hooks-manifest":
        sys.exit(f"{args.name!r} kind={entry.get('kind','single-hook')!r}, expected hooks-manifest")

    source = entry.get("source")
    if not source:
        sys.exit("guardrail entry missing source: URL")

    org, repo, ref, path_in_repo = parse_github_source(source)
    checkout = GUARDRAILS_HOME / args.name / "checkout"

    print(f"Cache: {checkout}")
    if not args.dry_run:
        ensure_checkout(org, repo, ref, checkout)

    if not checkout.exists():
        print("(dry-run) would clone " + str(checkout))
        return 0

    manifest = load_manifest(checkout, path_in_repo)
    plugin_root = resolve_plugin_root(checkout)
    resolved = rewrite_commands(manifest, plugin_root)

    harness = args.harness
    exit_code = 0

    if harness in ("claude", "all"):
        exit_code |= install_claude_harness(args, entry, checkout, manifest, resolved)

    if harness in ("codex", "all"):
        exit_code |= install_codex_harness(args, entry, checkout, manifest, resolved)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
