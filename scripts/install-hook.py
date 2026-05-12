#!/usr/bin/env python3
"""install-hook.py — Install a `hooks-manifest`-kind guardrail per ADR-0004 Phase 2.

Reads a guardrail entry from library.yaml whose `kind` is `hooks-manifest`,
fetches the referenced hooks.json from its remote `source:`, caches the
source repo at ~/.local/share/library/guardrails/<name>/checkout/,
resolves ${CLAUDE_PLUGIN_ROOT} to that cache, and merges every declared
hook into ~/.claude/settings.json (idempotent, deep-merge by command).

Usage:
    install-hook.py <guardrail-name>          # install (or refresh)
    install-hook.py <guardrail-name> --dry-run  # preview only, no writes
    install-hook.py <guardrail-name> --remove   # uninstall (drop from settings.json)

Designed for ADR-0004 Decision 8 — distribution via /library use.
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
    """Parse https://github.com/<org>/<repo>/blob/<ref>/<path> → (org, repo, ref, path)."""
    p = urlparse(url)
    if p.netloc != "github.com":
        sys.exit(f"Unsupported source host {p.netloc!r} — only github.com today")
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
    """${CLAUDE_PLUGIN_ROOT} in Claude Code's plugin model refers to the plugin's root
    directory (the dir containing hooks/, skills/, etc. as siblings). After ADR-0004's
    harness-neutral restructure, that's the source repo root — i.e. our git checkout."""
    return str(checkout.resolve())


def rewrite_commands(manifest: dict, plugin_root: str) -> dict:
    """Replace ${CLAUDE_PLUGIN_ROOT} with absolute path. Leaves manifest structure intact."""
    out = json.loads(json.dumps(manifest))  # deep copy
    pattern = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}")
    for event_entries in out.get("hooks", {}).values():
        for group in event_entries:
            for hook in group.get("hooks", []):
                if "command" in hook:
                    hook["command"] = pattern.sub(plugin_root, hook["command"])
    return out


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
    """Stable key for dedup — by type+command."""
    return f"{hook.get('type','')}::{hook.get('command','')}"


def merge_hooks(settings: dict, manifest: dict, guardrail_name: str) -> dict:
    """Deep-merge manifest.hooks into settings.hooks. Tag each merged hook
    with `_origin: <guardrail_name>` so we can remove later."""
    settings = json.loads(json.dumps(settings))  # don't mutate caller
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


CODEX_HOOKS = Path.home() / ".codex" / "hooks.json"

HARNESS_SETTINGS = {
    "claude_code": CLAUDE_SETTINGS,
    "codex_cli": CODEX_HOOKS,
}


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


def install_single_hook(entry: dict, dry_run: bool = False) -> int:
    """Install a kind=single-hook guardrail per-harness.

    For each harness key in entry.sources, register the source path as a hook
    command in the harness's settings file under every event listed in
    entry.capability.<harness>.events. Tagged with _origin=entry.name.
    """
    name = entry["name"]
    sources = entry.get("sources", {})
    capability = entry.get("capability", {})
    if not sources:
        sys.exit(f"{name!r}: kind=single-hook but no sources: map")

    total = 0
    for harness, rel_path in sources.items():
        if harness not in HARNESS_SETTINGS:
            print(f"  skip: unknown harness {harness!r}")
            continue
        events = capability.get(harness, {}).get("events", [])
        if not events:
            print(f"  skip: {harness} declared no events")
            continue

        abs_path = REPO_ROOT / rel_path
        if not abs_path.is_file():
            sys.exit(f"  ERROR: {abs_path} missing on disk")

        command = f"python3 {abs_path}"

        settings_path = HARNESS_SETTINGS[harness]
        settings = _load_json(settings_path)
        hooks_root = settings.setdefault("hooks", {})

        for event in events:
            group_list = hooks_root.setdefault(event, [])
            # Idempotent: drop any prior entry with same _origin
            group_list[:] = [g for g in group_list if not any(
                h.get("_origin") == name
                for h in (g.get("hooks", []) if isinstance(g, dict) else [])
            )]
            timeout_key = "timeoutSec" if harness == "codex_cli" else "timeout"
            group_list.append({
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        timeout_key: 15,
                        "_origin": name,
                    }
                ]
            })
            total += 1

        if dry_run:
            print(f"  (dry-run) {harness}: would update {settings_path}")
        else:
            _write_json(settings_path, settings)
            print(f"  {harness}: registered {len(events)} event(s) in {settings_path}")

    print(f"Installed {name!r} as single-hook: {total} event registration(s)")
    return 0


def remove_single_hook(entry: dict, dry_run: bool = False) -> int:
    name = entry["name"]
    sources = entry.get("sources", {})
    removed_total = 0
    for harness in sources:
        settings_path = HARNESS_SETTINGS.get(harness)
        if not settings_path or not settings_path.is_file():
            continue
        settings = _load_json(settings_path)
        hooks_root = settings.get("hooks", {})
        for event in list(hooks_root.keys()):
            before = len(hooks_root[event])
            hooks_root[event] = [g for g in hooks_root[event] if not any(
                h.get("_origin") == name
                for h in (g.get("hooks", []) if isinstance(g, dict) else [])
            )]
            removed_total += before - len(hooks_root[event])
            if not hooks_root[event]:
                del hooks_root[event]
        if dry_run:
            print(f"  (dry-run) {harness}: would remove {name!r} entries from {settings_path}")
        else:
            _write_json(settings_path, settings)
            print(f"  {harness}: pruned in {settings_path}")
    print(f"Removed {name!r}: {removed_total} hook entr{'y' if removed_total==1 else 'ies'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    library = load_library()
    entry = find_guardrail(library, args.name)
    kind = entry.get("kind", "single-hook")

    if kind == "single-hook":
        if args.remove:
            return remove_single_hook(entry, dry_run=args.dry_run)
        return install_single_hook(entry, dry_run=args.dry_run)

    if kind != "hooks-manifest":
        sys.exit(f"{args.name!r} has unsupported kind={kind!r}")

    if args.remove:
        before = load_settings()
        after = remove_hooks(before, args.name)
        if args.dry_run:
            print(json.dumps(after.get("hooks", {}), indent=2))
            return 0
        write_settings(after)
        print(f"Removed hooks for {args.name!r} from {CLAUDE_SETTINGS}")
        return 0

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

    settings = load_settings()
    merged = merge_hooks(settings, resolved, args.name)

    if args.dry_run:
        print("--- preview merged hooks ---")
        print(json.dumps(merged.get("hooks", {}), indent=2))
        return 0

    write_settings(merged)
    n_events = len(resolved.get("hooks", {}))
    n_hooks = sum(
        len(g.get("hooks", []))
        for groups in resolved.get("hooks", {}).values()
        for g in groups
    )
    print(f"Installed {args.name!r}: {n_hooks} hook(s) across {n_events} event(s)")
    print(f"Backup: {CLAUDE_SETTINGS.with_suffix('.json.bak')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
