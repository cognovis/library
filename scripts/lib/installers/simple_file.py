"""
installers/simple_file.py — Generic single-file installer for prompt, script,
model-standard, agent-base, and workflow primitives.

All four follow the same pattern:
  1. Fetch source file
  2. Cache it in Layer B (~/.local/share/library/<type>s/<marketplace>/<name>@<sha>/)
  3. Copy to the install target by default (or symlink with --symlink)
  4. Write lockfile entry

Remove reverses steps 3 and 4.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..cache import compute_cache_path
from ..catalog import lookup_entry
from ..errors import InstallError, SourceError
from ..lockfile import (
    compute_checksum,
    find_lockfile,
    load_lockfile,
    make_entry,
    remove_entry,
    save_lockfile,
    upsert_entry,
)
from ..output import dry_run_result, success
from ..paths import resolve_install_paths
from ..primitives import get_primitive
from ..source import get_local_commit_sha, parse_source, resolve_marketplace, ParsedSource


def install_simple_file(
    catalog: dict,
    primitive_name: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
    harness: str = "all",
    install_mode: str = "vendor",
) -> dict[str, Any]:
    """Generic install for prompt, script, model-standard, agent-base, workflow.

    Args:
        catalog: Parsed library.yaml dict.
        primitive_name: One of 'prompt', 'script', 'model-standard', 'agent-base', 'workflow'.
        name: Entry name.
        repo_root: Project root.
        scope: 'project' or 'global'.
        dry_run: If True, return planned ops without mutating.
        harness: Target harness (used for determining install sub-path for prompts).
        install_mode: 'vendor' (default) or 'symlink'.

    Returns:
        Operation result dict.
    """
    if install_mode not in ("vendor", "symlink"):
        raise InstallError(f"Unknown install mode for {primitive_name} '{name}': {install_mode}")

    prim = get_primitive(primitive_name)
    if prim is None:
        raise InstallError(f"Unknown primitive: {primitive_name}")
    primitive_name = prim.name

    # 1. Catalog lookup
    entry = lookup_entry(catalog, primitive_name, name)
    item_name = entry.get("name", name)
    source_str = entry.get("source") or ""
    if not source_str:
        # Try sources map
        sources_map = entry.get("sources") or {}
        source_str = sources_map.get("claude") or sources_map.get("codex") or ""
    if not source_str:
        raise InstallError(f"'{primitive_name} {item_name}' has no source field.")

    # 2. Parse source
    parsed = parse_source(source_str)
    marketplace = resolve_marketplace(catalog, entry)

    # 3. Determine install paths
    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(
            f"Cannot determine install path for {primitive_name} '{item_name}' (scope={scope}). "
            f"Check default_dirs.{prim.install_subdir} in library.yaml."
        )

    # Determine install filename
    if primitive_name == "prompt":
        install_filename = f"{item_name}.md"
    elif primitive_name == "script":
        language = entry.get("language", "python")
        if language != "python":
            raise InstallError(
                f"Script '{item_name}' uses unsupported language '{language}'. "
                "Scripts are Python-only."
            )
        install_filename = f"{item_name}.py"
    elif primitive_name == "model-standard":
        install_filename = f"{item_name}.md"
    elif primitive_name == "agent-base":
        install_filename = f"{item_name}.md"
    elif primitive_name == "workflow":
        install_filename = f"{item_name}.js"
    else:
        install_filename = f"{item_name}.md"

    install_target = canonical_base / install_filename

    # 4. Dry-run mode
    if dry_run:
        ops = [
            {
                "operation": "materialize_cache",
                "path": f"~/.local/share/library/{primitive_name}s/{marketplace}/{item_name}@<sha>/",
                "details": f"copy source -> Layer-B cache",
            },
            {
                "operation": "vendor_file" if install_mode == "vendor" else "create_symlink",
                "path": str(install_target),
                "details": f"install {primitive_name} '{item_name}' to {install_target}",
            },
        ]
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        ops.append({
            "operation": "write_lockfile",
            "path": str(lockfile_path),
            "details": f"upsert entry '{item_name}'",
        })
        return dry_run_result(
            ops,
            summary=f"Would install {primitive_name} '{item_name}' to {install_target}",
            target_paths=[str(install_target)],
            # Simple-file primitives (prompt, script, model-standard, agent-base, workflow)
            # share one install target across harnesses — resolve_install_paths
            # does not consult `harness`. Surface that by emitting None instead
            # of echoing the caller's --harness argument.
            harness_routing=None,
            conflict_policy="overwrite",
            lockfile_changes=[
                {
                    "path": str(lockfile_path),
                    "operation": "upsert",
                    "entry": item_name,
                }
            ],
            requires_user_confirmation=False,
        )

    # 5. Fetch source
    source_file, source_commit, temp_root = _fetch_file_source(parsed, item_name)

    try:
        # 5a. Native parse-gate for workflows — a workflow whose post-`meta` body
        # does not parse as an async function (e.g. wrapped in
        # `export async function run(args)`, a second illegal `export`) never
        # launches under the native Claude Workflow tool. Refuse to deploy it.
        if primitive_name == "workflow" and source_file.is_file():
            _assert_workflow_native_parse(source_file, item_name)

        cache_path = compute_cache_path(
            f"{primitive_name}",
            marketplace,
            item_name,
            source_commit,
        )

        # 5b. Materialize cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(str(cache_path))
        cache_path.mkdir(parents=True, exist_ok=True)

        cached_file_name = source_file.name if source_file.is_file() else install_filename
        cached_file = cache_path / cached_file_name
        if source_file.is_file():
            shutil.copy2(str(source_file), str(cached_file))
        else:
            shutil.copytree(str(source_file), str(cache_path / item_name))
            entrypoint = entry.get("entrypoint") or install_filename
            cached_file = cache_path / item_name / entrypoint

        # 6. Install to target
        canonical_base.mkdir(parents=True, exist_ok=True)
        if install_target.is_symlink():
            install_target.unlink()
        elif install_target.exists():
            install_target.unlink()

        if cached_file.exists():
            if install_mode == "vendor":
                shutil.copy2(str(cached_file), str(install_target))
            else:
                install_target.symlink_to(cached_file)
        else:
            if install_mode == "vendor":
                shutil.copytree(str(cache_path), str(install_target))
            else:
                install_target.parent.mkdir(parents=True, exist_ok=True)
                install_target.symlink_to(cache_path)

        # 7. Write lockfile
        primary = install_target if install_target.exists() else cached_file
        checksum = compute_checksum(primary) if primary.is_file() else "0" * 64

        lockfile_entry = make_entry(
            name=item_name,
            primitive_type=primitive_name,
            marketplace=marketplace,
            source=source_str,
            source_commit=source_commit,
            cache_path=str(cache_path) + "/",
            install_target=str(install_target),
            checksum_sha256=checksum,
            content_sha256=checksum,
            install_mode=install_mode,
            license_id=entry.get("license", "unknown"),
        )
        lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))
        lock_data = load_lockfile(lockfile_path)
        upsert_entry(lock_data, lockfile_entry)
        save_lockfile(lockfile_path, lock_data)

        return success(
            data={
                "name": item_name,
                "install_target": str(install_target),
                "cache": str(cache_path),
                "source_commit": source_commit,
                "install_mode": install_mode,
            },
            message=f"{primitive_name.title()} '{item_name}' installed at {install_target}",
        )

    finally:
        _cleanup_temp(temp_root)


def remove_simple_file(
    catalog: dict,
    primitive_name: str,
    name: str,
    repo_root: Path,
    scope: str = "project",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generic remove for prompt, script, model-standard, agent-base, workflow."""
    prim = get_primitive(primitive_name)
    if prim is None:
        raise InstallError(f"Unknown primitive: {primitive_name}")
    primitive_name = prim.name

    install_paths = resolve_install_paths(catalog, prim, scope=scope, repo_root=repo_root)
    canonical_base = install_paths["canonical"]
    if canonical_base is None:
        raise InstallError(f"Cannot determine install path for {primitive_name} '{name}'.")

    if primitive_name == "script":
        extension = ".py"
    elif primitive_name == "workflow":
        extension = ".js"
    else:
        extension = ".md"
    install_target = canonical_base / f"{name}{extension}"
    lockfile_path = find_lockfile(repo_root, global_scope=(scope == "global"))

    if dry_run:
        ops = []
        if install_target.exists() or install_target.is_symlink():
            ops.append({"operation": "delete", "path": str(install_target), "details": f"remove {install_target}"})
        ops.append({"operation": "remove_lockfile_entry", "path": str(lockfile_path), "details": f"remove '{name}'"})
        return dry_run_result(ops, summary=f"Would remove {primitive_name} '{name}'")

    removed_files = []
    for candidate in [install_target, canonical_base / name]:
        if candidate.is_symlink():
            candidate.unlink()
            removed_files.append(str(candidate))
        elif candidate.exists():
            if candidate.is_dir():
                shutil.rmtree(str(candidate))
            else:
                candidate.unlink()
            removed_files.append(str(candidate))

    lock_data = load_lockfile(lockfile_path)
    remove_entry(lock_data, name, primitive_type=primitive_name)
    save_lockfile(lockfile_path, lock_data)

    return success(
        data={"name": name, "removed_files": removed_files},
        message=f"{primitive_name.title()} '{name}' removed.",
    )


def _assert_workflow_native_parse(js_path: Path, name: str) -> None:
    """Deploy-gate: a Library workflow is authored once as native Claude Workflow JS.

    A native spec must (1) begin with `export const meta = {...}` as the first real
    statement — no executable code before it; (2) have a parseable meta object
    literal; and (3) have a post-`meta` body that parses as the injected async
    function the native tool wraps it in (`args`/`agent`/`parallel`/`pipeline`/
    `phase`/`log`/`budget`/`workflow` are globals; top-level `await`/`return` valid).
    The `export async function run(args)` wrapper copied from the library-runtime
    convention is a second `export` — a `SyntaxError` — so the workflow never
    launches (clc-j7mn).

    This checks meta-first textually, then runs ONE `node --check` over
    `const __meta = <meta literal>;` + the body wrapped as an async function — which
    catches a malformed meta object and a non-parseable body together. Raises
    InstallError on any failure. If `node` is unavailable the gate is skipped with a
    warning (do not block installs on a missing toolchain).
    """
    node = shutil.which("node")
    src = js_path.read_text(encoding="utf-8")

    # Locate the real `export const meta` DECLARATION (at statement position), not a
    # mention inside a header comment — good workflows routinely document the token.
    meta_match = re.search(r"(?m)^[ \t]*export[ \t]+const[ \t]+meta\b", src)
    if meta_match is None:
        raise InstallError(
            f"Workflow '{name}' has no `export const meta = {{...}}` declaration; "
            "a native Claude Workflow spec must begin with it."
        )
    marker = meta_match.start()

    # (1) meta must be the first real statement — nothing but whitespace/comments
    # may precede it (executable pre-meta code is not part of the native body and
    # would run at import time).
    preamble = src[:marker]
    preamble = re.sub(r"/\*.*?\*/", "", preamble, flags=re.S)  # block comments
    preamble = re.sub(r"(?m)//.*$", "", preamble)              # line comments
    if preamble.strip():
        raise InstallError(
            f"Workflow '{name}': `export const meta` must be the first statement, but "
            "executable code precedes it. A native spec begins with the meta block; "
            "move setup code into the body (after meta)."
        )

    # Locate the balanced meta object literal.
    brace_start = src.find("{", marker)
    depth = 0
    end = -1
    idx = brace_start
    while idx != -1 and idx < len(src):
        char = src[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
        idx += 1
    if brace_start == -1 or end == -1:
        raise InstallError(f"Workflow '{name}': unbalanced or missing `export const meta` object.")

    meta_literal = src[brace_start:end]
    body = src[end:].lstrip(" \t\r\n;")

    if node is None:
        print(
            f"[workflow] WARN: node not found — skipping native parse-gate for '{name}'. "
            "Install Node.js to enable workflow launch validation.",
            file=sys.stderr,
        )
        return

    # (2)+(3): validate the meta literal AND the body in one parse. The meta object
    # is assigned to a const (catches malformed literals, e.g. double commas); the
    # body is wrapped exactly as the native tool runs it (catches a second export,
    # top-level syntax errors, etc.).
    wrapped = (
        "const __meta = " + meta_literal + ";\n"
        "async function __wf(agent, parallel, pipeline, phase, log, workflow, args, budget) {\n"
        + body
        + "\n}\n"
    )
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as handle:
            handle.write(wrapped)
            tmp = handle.name
        result = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if result.returncode != 0:
        stderr_lines = [line for line in result.stderr.splitlines() if "Error" in line]
        detail = stderr_lines[0].strip() if stderr_lines else "parse failed"
        raise InstallError(
            f"Workflow '{name}' is not a launchable native Claude Workflow spec "
            f"({detail}). The meta object must be a valid literal and the body after "
            "`export const meta` must parse as an async function — do NOT wrap it in "
            "`export async function run(args)` (a second `export` is illegal). "
            "See the workflow-forge skill."
        )


def _fetch_file_source(
    parsed: ParsedSource, name: str
) -> tuple[Path, str, Optional[Path]]:
    """Fetch source file.

    Returns (path, commit_sha, temp_root). `temp_root` is the directory
    that must be cleaned up after use, or None when the source is local.
    """
    if parsed.is_local():
        local = parsed.local_path
        if local is None or not local.exists():
            raise InstallError(f"Local source path does not exist: {parsed.raw}")
        commit = get_local_commit_sha(local)
        return local, commit, None

    if parsed.is_github():
        tmp = Path(tempfile.mkdtemp())
        clone_url = parsed.clone_url or ""
        result = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", clone_url, str(tmp)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            ssh_url = clone_url.replace("https://github.com/", "git@github.com:")
            result = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", ssh_url, str(tmp)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                shutil.rmtree(str(tmp), ignore_errors=True)
                raise InstallError(f"Failed to clone {clone_url}: {result.stderr.strip()}")

        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp)
        )
        commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        if parsed.file_path:
            source_file = tmp / parsed.file_path
            if source_file.exists():
                return source_file, commit, tmp

        for candidate in [tmp / f"{name}.md", tmp / "SKILL.md", tmp / "agent.md"]:
            if candidate.exists():
                return candidate, commit, tmp

        return tmp, commit, tmp

    raise SourceError(f"Cannot fetch source: unsupported kind '{parsed.kind}'")


def _cleanup_temp(temp_root: Optional[Path]) -> None:
    """Remove the temp clone dir, if one was created."""
    if temp_root is None:
        return
    shutil.rmtree(str(temp_root), ignore_errors=True)
