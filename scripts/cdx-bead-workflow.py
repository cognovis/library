#!/usr/bin/env python3
"""Deterministic cdx full-bead workflow entrypoint.

This runner is the first production slice of the bead-orchestrator workflow for
the Codex launcher. It keeps the Codex outer harness out of the large
bead-orchestrator prompt and drives the implementation leaf directly from the
Phase 0 execution_plan.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SUPPORTED_SCRIPT_ADAPTERS = {
    "codex-impl": "codex-impl.py",
    "cursor-composer": "cursor-impl.py",
}


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


def _build_prompt(bead_id: str, bead_context: str, adapter: str) -> str:
    return f"""Implement bead {bead_id} as the deterministic cdx full-workflow implementation leaf.

You are the implementation leaf selected by the bead-orchestrator workflow
slot full.implementation. Do not orchestrate review, verification, or
session-close. Make the smallest change that satisfies the bead acceptance
criteria, run focused verification, and commit the result.

Adapter: {adapter}

## Bead Context

{bead_context}
"""


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"required helper not found: {path}")


def _run_phase0(
    scripts_dir: Path,
    bead_id: str,
    route_profile: str,
) -> tuple[dict[str, Any], int]:
    phase0_args = [
        "uv",
        "run",
        "python",
        str(scripts_dir / "phase0-claim.py"),
        bead_id,
        "--line=cdx",
        "--tier=auto",
    ]
    if route_profile:
        phase0_args.append(f"--route-profile={route_profile}")

    phase0 = _run_capture(phase0_args)
    if phase0.stderr:
        print(phase0.stderr, end="", file=sys.stderr)
    if phase0.returncode != 0:
        if phase0.stdout:
            print(phase0.stdout, end="")
        return {}, phase0.returncode

    try:
        return _load_phase0_payload(phase0.stdout), 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {}, 1


def _resolve_full_implementation(
    scripts_dir: Path,
    payload: dict[str, Any],
) -> tuple[dict[str, str], int]:
    route_decision = payload.get("route_decision") or {}
    impl_model = str(route_decision.get("impl_model") or "")
    execution_plan = payload.get("execution_plan")

    dispatch_env = os.environ.copy()
    if execution_plan:
        dispatch_env["EXECUTION_PLAN"] = json.dumps(execution_plan)
    else:
        dispatch_env["EXECUTION_PLAN"] = ""

    dispatch = _run_capture(
        [
            "uv",
            "run",
            "python",
            str(scripts_dir / "resolve_slot_dispatch.py"),
            "full",
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
        return {}, dispatch.returncode
    return _parse_dispatch(dispatch.stdout), 0


def _run_script_adapter(
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
) -> int:
    adapter = dispatch.get("ADAPTER", "")
    script_name = SUPPORTED_SCRIPT_ADAPTERS.get(adapter)
    if script_name is None:
        print(
            "ERROR: deterministic cdx bead workflow cannot execute adapter "
            f"{adapter or '<missing>'!r}. Supported adapters: "
            f"{', '.join(sorted(SUPPORTED_SCRIPT_ADAPTERS))}.",
            file=sys.stderr,
        )
        return 1

    script_path = scripts_dir / script_name
    if not script_path.is_file():
        print(f"ERROR: required adapter helper not found: {script_path}", file=sys.stderr)
        return 1

    model = dispatch.get("MODEL", "")
    harness = dispatch.get("HARNESS", "")
    source = dispatch.get("SOURCE", "")
    print(
        "## LEAF_DISPATCH workflow=full slot=implementation "
        f"adapter={adapter} harness={harness or 'unknown'} model={model} "
        f"source={source or 'slot'}",
        file=sys.stderr,
    )

    adapter_env = os.environ.copy()
    adapter_env.update(
        {
            "RUN_ID": str(payload.get("run_id") or ""),
            "BEAD_ID": bead_id,
            "PHASE_LABEL": "implementation",
            "AGENT_LABEL": f"{adapter}-full-implementation",
            "WORKSPACE": str(repo_root),
            "PRE_IMPL_SHA": str(payload.get("pre_impl_sha") or ""),
            "IMPL_MODEL": model,
        }
    )
    prompt = _build_prompt(bead_id, bead_context, adapter)
    completed = subprocess.run(
        ["uv", "run", "python", str(script_path), prompt],
        check=False,
        env=adapter_env,
    )
    return completed.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bead_id")
    parser.add_argument(
        "--route-profile",
        default="",
        help="Named route profile to resolve through phase0-claim.py.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bead_context = sys.stdin.read()
    repo_root = _repo_root()

    try:
        beads_runtime = _resolve_beads_runtime(repo_root)
        scripts_dir = beads_runtime / "scripts"
        _require_file(scripts_dir / "phase0-claim.py")
        _require_file(scripts_dir / "resolve_slot_dispatch.py")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload, phase0_rc = _run_phase0(scripts_dir, args.bead_id, args.route_profile)
    if phase0_rc != 0:
        return phase0_rc

    route_decision = payload.get("route_decision") or {}
    execution_plan = payload.get("execution_plan") or {}
    print(
        "### Phase Progress\n"
        f"phase: 0 | name: route_decision | status: complete | "
        f"route: {str(route_decision.get('tier') or '').upper()}",
        file=sys.stderr,
    )
    if execution_plan:
        print(
            "## WORKFLOW_PLAN "
            f"profile={execution_plan.get('profile', args.route_profile) or args.route_profile} "
            f"workflow={execution_plan.get('workflow', 'full')}",
            file=sys.stderr,
        )

    dispatch, dispatch_rc = _resolve_full_implementation(scripts_dir, payload)
    if dispatch_rc != 0:
        return dispatch_rc

    print(
        "### Phase Progress\n"
        "phase: 5 | name: p5_impl | status: in_progress | iteration: 1",
        file=sys.stderr,
    )
    return _run_script_adapter(
        scripts_dir,
        repo_root,
        args.bead_id,
        bead_context,
        payload,
        dispatch,
    )


if __name__ == "__main__":
    raise SystemExit(main())
