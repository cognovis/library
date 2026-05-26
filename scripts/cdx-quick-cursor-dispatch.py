#!/usr/bin/env python3
"""Deterministic cdx-composer quick implementation dispatch.

This helper exists because `codex exec` has no stable CLI flag for selecting a
custom top-level agent role. The generic Codex prompt path can therefore try to
spawn the quick-fix agent as a child before quick.implementation slot dispatch
is reached. For the cdx-composer profile, the contract we need to prove is the
implementation leaf: quick.implementation must resolve to cursor-composer and
run cursor-impl.py.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PHASE0_PYTHON_DEPS = ("pyyaml",)


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _resolve_beads_runtime(repo_root: Path) -> Path:
    candidates = [
        os.environ.get("BEADS_RUNTIME_DIR", ""),
        str(repo_root / ".agents" / "skills" / "beads"),
        str(repo_root / ".claude" / "skills" / "beads"),
        str(repo_root / "skills" / "beads"),
        str(Path.home() / ".agents" / "skills" / "beads"),
        str(Path.home() / ".claude" / "skills" / "beads"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if (path / "scripts").is_dir():
            return path
    raise RuntimeError("skill:beads runtime not found; install via /library use beads")


def _run_capture(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _uv_python_with(deps: tuple[str, ...], script: Path, *args: str) -> list[str]:
    command = ["uv", "run"]
    for dep in deps:
        command.extend(["--with", dep])
    command.extend(["python", str(script), *args])
    return command


def _load_phase0_payload(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("phase0-claim.py returned no JSON payload")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"phase0-claim.py returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("phase0-claim.py returned a non-object JSON payload")
    return payload


def _parse_dispatch(stdout: str) -> dict[str, str]:
    dispatch: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        dispatch[key.strip()] = value.strip()
    return dispatch


def _build_prompt(bead_id: str, bead_context: str) -> str:
    return f"""Implement bead {bead_id} as the cdx-composer quick implementation leaf.

You are Cursor Composer running as an implementer leaf only. Do not orchestrate
review, fix loops, or session-close. Make the smallest change that satisfies
the bead acceptance criteria, run focused verification, and commit the result.

## Bead Context

{bead_context}
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bead_id")
    parser.add_argument("--route-profile", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bead_context = sys.stdin.read()
    repo_root = _repo_root()

    try:
        beads_runtime = _resolve_beads_runtime(repo_root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    scripts_dir = beads_runtime / "scripts"
    phase0_script = scripts_dir / "phase0-claim.py"
    resolve_script = scripts_dir / "resolve_slot_dispatch.py"
    cursor_impl = scripts_dir / "cursor-impl.py"
    for path in (phase0_script, resolve_script, cursor_impl):
        if not path.is_file():
            print(f"ERROR: required helper not found: {path}", file=sys.stderr)
            return 1

    phase0 = _run_capture(
        _uv_python_with(
            PHASE0_PYTHON_DEPS,
            phase0_script,
            args.bead_id,
            "--line=cdx",
            "--tier=quick",
            "--bq",
            f"--route-profile={args.route_profile}",
        )
    )
    if phase0.stderr:
        print(phase0.stderr, end="", file=sys.stderr)
    if phase0.returncode != 0:
        if phase0.stdout:
            print(phase0.stdout, end="")
        return phase0.returncode

    try:
        payload = _load_phase0_payload(phase0.stdout)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    route_decision = payload.get("route_decision") or {}
    impl_model = str(route_decision.get("impl_model") or "")
    execution_plan = payload.get("execution_plan")
    if not execution_plan:
        print(
            "ERROR: cdx-composer quick dispatch requires an execution_plan; "
            "refusing to fall back to model-prefix dispatch.",
            file=sys.stderr,
        )
        return 1

    dispatch_env = os.environ.copy()
    dispatch_env["EXECUTION_PLAN"] = json.dumps(execution_plan)
    dispatch = _run_capture(
        [
            "uv",
            "run",
            "python",
            str(resolve_script),
            "quick",
            "implementation",
            f"--impl-model={impl_model}",
        ],
        env=dispatch_env,
    )
    if dispatch.stderr:
        print(dispatch.stderr, end="", file=sys.stderr)
    if dispatch.returncode != 0:
        if dispatch.stdout:
            print(dispatch.stdout, end="")
        return dispatch.returncode

    slot = _parse_dispatch(dispatch.stdout)
    adapter = slot.get("ADAPTER", "")
    model = slot.get("MODEL", "")
    harness = slot.get("HARNESS", "")
    source = slot.get("SOURCE", "")
    if adapter != "cursor-composer":
        print(
            "ERROR: cdx-composer quick.implementation resolved to "
            f"{adapter or '<missing>'}, not cursor-composer; refusing Codex/GPT fallback.",
            file=sys.stderr,
        )
        return 1
    if not model:
        print("ERROR: cursor-composer slot did not provide a model", file=sys.stderr)
        return 1

    print(
        "## LEAF_DISPATCH workflow=quick slot=implementation "
        f"adapter={adapter} harness={harness or 'cursor'} model={model} "
        f"source={source or 'slot'}",
        file=sys.stderr,
    )

    cursor_env = os.environ.copy()
    cursor_env.update(
        {
            "RUN_ID": str(payload.get("run_id") or ""),
            "BEAD_ID": args.bead_id,
            "PHASE_LABEL": "implementation",
            "AGENT_LABEL": "impl-cursor-self-log",
            "WORKSPACE": str(repo_root),
            "PRE_IMPL_SHA": str(payload.get("pre_impl_sha") or ""),
            "IMPL_MODEL": model,
        }
    )
    prompt = _build_prompt(args.bead_id, bead_context)
    completed = subprocess.run(
        ["uv", "run", "python", str(cursor_impl), prompt],
        check=False,
        env=cursor_env,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
