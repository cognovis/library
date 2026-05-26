#!/usr/bin/env python3
"""Deterministic cdx full-bead workflow entrypoint.

This runner keeps the Codex outer harness out of the large bead-orchestrator
prompt and drives full-workflow leaves directly from the Phase 0 execution_plan.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SUPPORTED_SCRIPT_ADAPTERS = {
    "codex-impl": "codex-impl.py",
    "cursor-composer": "cursor-impl.py",
}

PHASE0_PYTHON_DEPS = ("pyyaml",)

PREP_GAP_PHASES: tuple[dict[str, str], ...] = (
    {
        "phase": "2",
        "phase_name": "scope_check",
        "reason": "deterministic_cdx_phase_not_implemented",
    },
    {
        "phase": "3",
        "phase_name": "architecture_review",
        "reason": "deterministic_cdx_phase_not_implemented",
    },
)

FULL_WORKFLOW_SLOTS: tuple[dict[str, str], ...] = (
    {
        "slot": "implementation",
        "phase": "5",
        "phase_name": "p5_impl",
        "phase_label": "implementation",
    },
    {
        "slot": "adversarial_review",
        "phase": "7",
        "phase_name": "codex_adversarial",
        "phase_label": "codex-adversarial",
    },
    {
        "slot": "verification",
        "phase": "9",
        "phase_name": "verification",
        "phase_label": "verification",
    },
    {
        "slot": "session_close",
        "phase": "16",
        "phase_name": "session_close",
        "phase_label": "session-close",
    },
)

CLAUDE_AGENT_FOR_SLOT = {
    "implementation": "",
    "adversarial_review": "review-agent",
    "verification": "verification-agent",
    "session_close": "session-close",
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _event_value(value: object) -> str:
    text = str(value)
    return "_".join(text.split()) if text else ""


def _workflow_event(
    workflow_started_at: float,
    *,
    phase: str,
    name: str,
    status: str,
    **fields: object,
) -> None:
    elapsed_ms = int((time.monotonic() - workflow_started_at) * 1000)
    parts = [
        f"ts={_utc_timestamp()}",
        f"elapsed_ms={elapsed_ms}",
        f"phase={_event_value(phase)}",
        f"name={_event_value(name)}",
        f"status={_event_value(status)}",
    ]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_event_value(value)}")
    print("## WORKFLOW_EVENT " + " ".join(parts), file=sys.stderr)


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


def _run_capture(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
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


def _diff_range(payload: dict[str, Any]) -> str:
    pre_impl_sha = str(payload.get("pre_impl_sha") or "").strip()
    return f"{pre_impl_sha}...HEAD" if pre_impl_sha else "HEAD"


def _build_prompt(bead_id: str, bead_context: str, adapter: str, slot_name: str, payload: dict[str, Any]) -> str:
    diff_range = _diff_range(payload)
    if slot_name == "implementation":
        return f"""Implement bead {bead_id} as the deterministic cdx full-workflow implementation leaf.

You are the implementation leaf selected by the bead-orchestrator workflow
slot full.implementation. Do not orchestrate review, verification, or
session-close. Make the smallest change that satisfies the bead acceptance
criteria, run focused verification, and commit the result.

Adapter: {adapter}

## Bead Context

{bead_context}
"""

    if slot_name == "adversarial_review":
        return f"""Review bead {bead_id} implementation diff for regressions and bugs.

You are the adversarial review leaf selected by full.adversarial_review.
Use the diff range {diff_range} as the primary source of truth. Report only
actual bugs and regressions. If there are no findings, report exactly LGTM.

Format findings as:
REGRESSION: <file>:<line> - <description>

Adapter: {adapter}

## Bead Context

{bead_context}
"""

    if slot_name == "verification":
        return f"""Verify bead {bead_id} against its acceptance criteria.

You are the verification leaf selected by full.verification. Inspect the
implementation diff ({diff_range}), run focused verification where needed, and
return a concise result:
- VERIFIED when acceptance criteria are satisfied.
- DISPUTED with concrete file/test evidence when they are not.
- UNVERIFIABLE when the stated Means of Compliance cannot be run.

Adapter: {adapter}

## Bead Context

{bead_context}
"""

    if slot_name == "session_close":
        return f"""Close session for bead {bead_id}.

You are the session-close leaf selected by full.session_close. Run the complete
session-close pipeline: changelog/version handling where applicable, final
quality checks, merge/push, Dolt sync, and bead close. Do not stop after a
partial handoff.

Run metadata:
- run_id: {payload.get("run_id") or ""}
- pre_impl_sha: {payload.get("pre_impl_sha") or ""}
- diff_range: {diff_range}

Adapter: {adapter}

## Bead Context

{bead_context}
"""

    return f"""Run bead {bead_id} workflow slot full.{slot_name}.

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
    phase0_args = _uv_python_with(
        PHASE0_PYTHON_DEPS,
        scripts_dir / "phase0-claim.py",
        bead_id,
        "--line=cdx",
        "--tier=auto",
    )
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


def _resolve_inject_standards_runner(beads_runtime: Path, repo_root: Path) -> Path:
    candidates = [
        os.environ.get("INJECT_STANDARDS_RUNNER", ""),
        str(beads_runtime.parent / "inject-standards" / "runner.py"),
        str(repo_root / "skills" / "inject-standards" / "runner.py"),
        str(Path.home() / ".agents" / "skills" / "inject-standards" / "runner.py"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    raise RuntimeError("inject-standards runner not found")


def _phase1_context_keywords(bead_id: str, bead_context: str) -> str:
    compact = "\n".join(line.strip() for line in bead_context.splitlines() if line.strip())
    if len(compact) > 8000:
        compact = compact[:8000]
    return f"{bead_id}\n{compact}".strip()


def _run_phase1_context(
    *,
    beads_runtime: Path,
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
) -> tuple[dict[str, Any], int]:
    context_provider = Path(os.environ.get("CONTEXT_PROVIDER_SCRIPT", "") or scripts_dir / "context_provider.py")
    if not context_provider.is_file():
        print(f"ERROR: context provider runner not found at {context_provider}", file=sys.stderr)
        return {}, 1

    try:
        inject_runner = _resolve_inject_standards_runner(beads_runtime, repo_root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {}, 1

    with tempfile.TemporaryDirectory(prefix="cdx-phase1-") as tmp_dir_text:
        tmp_dir = Path(tmp_dir_text)
        standards_full_path = tmp_dir / "standards_full"
        standard_paths_path = tmp_dir / "standard_paths"

        inject = _run_capture(
            [
                "uv",
                "run",
                "python",
                str(inject_runner),
                f"--full-out={standards_full_path}",
                f"--paths-out={standard_paths_path}",
                f"--context={_phase1_context_keywords(bead_id, bead_context)}",
            ],
            cwd=repo_root,
        )
        if inject.stderr:
            print(inject.stderr, end="", file=sys.stderr)
        if inject.returncode != 0:
            print(f"ERROR: inject-standards exited {inject.returncode}", file=sys.stderr)
            if inject.stdout:
                print(inject.stdout, end="")
            return {}, inject.returncode

        provider_env = os.environ.copy()
        provider_env.setdefault("BEAD_CONTEXT_PROVIDER", "auto")
        provider = _run_capture(
            [
                "uv",
                "run",
                "python",
                str(context_provider),
                bead_id,
                "--repo-root",
                str(repo_root),
                "--provider",
                provider_env["BEAD_CONTEXT_PROVIDER"],
            ],
            cwd=repo_root,
            env=provider_env,
        )
        if provider.stderr:
            print(provider.stderr, end="", file=sys.stderr)
        if provider.returncode != 0:
            print(f"ERROR: context provider exited {provider.returncode}", file=sys.stderr)
            if provider.stdout:
                print(provider.stdout, end="")
            return {}, provider.returncode

        context_bundle_text = provider.stdout.strip()
        try:
            context_bundle = json.loads(context_bundle_text) if context_bundle_text else {}
        except json.JSONDecodeError:
            context_bundle = {"provider_status": "invalid-json", "raw": context_bundle_text}

        standards_full = standards_full_path.read_text(encoding="utf-8") if standards_full_path.exists() else ""
        standard_paths = standard_paths_path.read_text(encoding="utf-8") if standard_paths_path.exists() else ""
        primary_files = context_bundle.get("primary_files", []) if isinstance(context_bundle, dict) else []
        test_files = context_bundle.get("test_files", []) if isinstance(context_bundle, dict) else []

        return {
            "context_bundle_text": context_bundle_text,
            "context_bundle": context_bundle,
            "standards_full": standards_full,
            "standard_paths": standard_paths,
            "primary_files": primary_files if isinstance(primary_files, list) else [],
            "test_files": test_files if isinstance(test_files, list) else [],
        }, 0


def _enrich_bead_context(bead_context: str, phase1: dict[str, Any]) -> str:
    context_bundle_text = str(phase1.get("context_bundle_text") or "{}")
    standard_paths = str(phase1.get("standard_paths") or "").strip()
    standards_full = str(phase1.get("standards_full") or "").strip()
    standards_preamble = (
        "The following standards were injected by deterministic Phase 1 and must be followed.\n\n"
        + standards_full
        if standards_full
        else "No project-specific standards loaded. Follow general code quality conventions."
    )
    return f"""{bead_context.rstrip()}

## Deterministic Phase 1 Context

### Context Provider Bundle

```json
{context_bundle_text}
```

### Standard Paths

{standard_paths or "none"}

### Standards Enforcement Preamble

{standards_preamble}
"""


def _resolve_full_slot(
    scripts_dir: Path,
    payload: dict[str, Any],
    slot_name: str,
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
            slot_name,
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


def _adapter_env(
    repo_root: Path,
    bead_id: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
    slot_name: str,
    phase_label: str,
) -> dict[str, str]:
    env = os.environ.copy()
    timeout_sec = dispatch.get("TIMEOUT_SEC", "")
    env.update(
        {
            "RUN_ID": str(payload.get("run_id") or ""),
            "BEAD_ID": bead_id,
            "PHASE_LABEL": phase_label,
            "AGENT_LABEL": f"{dispatch.get('ADAPTER', 'unknown')}-full-{slot_name}",
            "WORKSPACE": str(repo_root),
            "PRE_IMPL_SHA": str(payload.get("pre_impl_sha") or ""),
            "IMPL_MODEL": dispatch.get("MODEL", ""),
            "ITERATION": env.get("ITERATION", "1"),
        }
    )
    if timeout_sec:
        env.setdefault("CODEX_EXEC_TIMEOUT", timeout_sec)
        env.setdefault("CLAUDE_IMPL_TIMEOUT", timeout_sec)
    return env


def _metrics_dir_for(beads_runtime_scripts: Path) -> Path:
    override = os.environ.get("METRICS_DIR_OVERRIDE", "")
    if override:
        return Path(override).expanduser().resolve()
    return beads_runtime_scripts.parent / "lib" / "orchestrator"


def _record_runner_agent_call(
    *,
    scripts_dir: Path,
    env: dict[str, str],
    bead_id: str,
    phase_label: str,
    agent_label: str,
    model: str,
    duration_ms: int,
    exit_code: int,
) -> None:
    run_id = env.get("RUN_ID", "")
    if not run_id:
        return

    metrics_dir = _metrics_dir_for(scripts_dir)
    sys.path.insert(0, str(metrics_dir))
    try:
        from metrics import DB_PATH, insert_agent_call  # type: ignore[import]
    except ImportError as exc:
        print(
            "cdx-bead-workflow.py: WARNING: Cannot import metrics module from "
            f"{metrics_dir} - runner metrics skipped ({exc})",
            file=sys.stderr,
        )
        return

    db_path = Path(env["METRICS_DB_PATH"]) if env.get("METRICS_DB_PATH") else DB_PATH
    try:
        insert_agent_call(
            run_id=run_id,
            bead_id=bead_id,
            phase_label=phase_label,
            agent_label=agent_label,
            model=model,
            iteration=int(env.get("ITERATION", "1") or "1"),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
            total_tokens=0,
            duration_ms=duration_ms,
            exit_code=exit_code,
            wave_id=env.get("WAVE_ID", ""),
            db_path=db_path,
        )
    except Exception as exc:
        print(f"cdx-bead-workflow.py: WARNING: runner metrics skipped: {exc}", file=sys.stderr)


def _emit_leaf_dispatch(slot_name: str, dispatch: dict[str, str]) -> None:
    adapter = dispatch.get("ADAPTER", "")
    model = dispatch.get("MODEL", "")
    harness = dispatch.get("HARNESS", "")
    source = dispatch.get("SOURCE", "")
    print(
        f"## LEAF_DISPATCH workflow=full slot={slot_name} "
        f"adapter={adapter} harness={harness or 'unknown'} model={model} "
        f"source={source or 'slot'}",
        file=sys.stderr,
    )


def _run_script_adapter(
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
    slot_name: str,
    phase_label: str,
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

    _emit_leaf_dispatch(slot_name, dispatch)
    adapter_env = _adapter_env(repo_root, bead_id, payload, dispatch, slot_name, phase_label)
    prompt = _build_prompt(bead_id, bead_context, adapter, slot_name, payload)
    completed = subprocess.run(
        ["uv", "run", "python", str(script_path), prompt],
        check=False,
        env=adapter_env,
    )
    return completed.returncode


def _run_codex_exec_adapter(
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
    slot_name: str,
    phase_label: str,
) -> int:
    script_path = scripts_dir / "codex-exec.py"
    if not script_path.is_file():
        print(f"ERROR: required adapter helper not found: {script_path}", file=sys.stderr)
        return 1

    _emit_leaf_dispatch(slot_name, dispatch)
    adapter_env = _adapter_env(repo_root, bead_id, payload, dispatch, slot_name, phase_label)
    prompt = _build_prompt(bead_id, bead_context, "codex-exec", slot_name, payload)
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script_path),
            "--diff-range",
            _diff_range(payload),
            prompt,
        ],
        check=False,
        env=adapter_env,
    )
    return completed.returncode


def _run_claude_agent_adapter(
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
    slot_name: str,
    phase_label: str,
) -> int:
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    agent_name = CLAUDE_AGENT_FOR_SLOT.get(slot_name, "")
    model = dispatch.get("MODEL", "")
    cmd = [
        claude_bin,
        "--print",
        "--dangerously-skip-permissions",
        "--setting-sources",
        os.environ.get("CLAUDE_SETTING_SOURCES", "user,project,local"),
    ]
    if agent_name:
        cmd.extend(["--agent", agent_name])
    if model:
        cmd.extend(["--model", model])

    _emit_leaf_dispatch(slot_name, dispatch)
    adapter_env = _adapter_env(repo_root, bead_id, payload, dispatch, slot_name, phase_label)
    prompt = _build_prompt(bead_id, bead_context, "claude-agent", slot_name, payload)
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            check=False,
            cwd=str(repo_root),
            env=adapter_env,
            timeout=int(dispatch.get("TIMEOUT_SEC") or 1800),
        )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        _record_runner_agent_call(
            scripts_dir=scripts_dir,
            env=adapter_env,
            bead_id=bead_id,
            phase_label=phase_label,
            agent_label=f"claude-agent-full-{slot_name}",
            model=model or "claude",
            duration_ms=duration_ms,
            exit_code=completed.returncode,
        )
        return completed.returncode
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(
            f"ERROR: claude-agent slot full.{slot_name} timed out after "
            f"{dispatch.get('TIMEOUT_SEC') or 1800}s",
            file=sys.stderr,
        )
        _record_runner_agent_call(
            scripts_dir=scripts_dir,
            env=adapter_env,
            bead_id=bead_id,
            phase_label=phase_label,
            agent_label=f"claude-agent-full-{slot_name}",
            model=model or "claude",
            duration_ms=duration_ms,
            exit_code=124,
        )
        return 124


def _run_slot_adapter(
    scripts_dir: Path,
    repo_root: Path,
    bead_id: str,
    bead_context: str,
    payload: dict[str, Any],
    dispatch: dict[str, str],
    slot_name: str,
    phase_label: str,
) -> int:
    adapter = dispatch.get("ADAPTER", "")
    if adapter in SUPPORTED_SCRIPT_ADAPTERS:
        return _run_script_adapter(
            scripts_dir,
            repo_root,
            bead_id,
            bead_context,
            payload,
            dispatch,
            slot_name,
            phase_label,
        )
    if adapter == "codex-exec":
        return _run_codex_exec_adapter(
            scripts_dir,
            repo_root,
            bead_id,
            bead_context,
            payload,
            dispatch,
            slot_name,
            phase_label,
        )
    if adapter == "claude-agent":
        return _run_claude_agent_adapter(
            scripts_dir,
            repo_root,
            bead_id,
            bead_context,
            payload,
            dispatch,
            slot_name,
            phase_label,
        )

    supported = sorted([*SUPPORTED_SCRIPT_ADAPTERS, "claude-agent", "codex-exec"])
    print(
        "ERROR: deterministic cdx bead workflow cannot execute adapter "
        f"{adapter or '<missing>'!r}. Supported adapters: {', '.join(supported)}.",
        file=sys.stderr,
    )
    return 1


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
    workflow_started_at = time.monotonic()
    repo_root = _repo_root()

    try:
        beads_runtime = _resolve_beads_runtime(repo_root)
        scripts_dir = beads_runtime / "scripts"
        _require_file(scripts_dir / "phase0-claim.py")
        _require_file(scripts_dir / "resolve_slot_dispatch.py")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    phase0_started_at = time.monotonic()
    _workflow_event(workflow_started_at, phase="0", name="phase0_claim", status="in_progress")
    payload, phase0_rc = _run_phase0(scripts_dir, args.bead_id, args.route_profile)
    phase0_duration_ms = int((time.monotonic() - phase0_started_at) * 1000)
    _workflow_event(
        workflow_started_at,
        phase="0",
        name="phase0_claim",
        status="complete" if phase0_rc == 0 else "failed",
        duration_ms=phase0_duration_ms,
        exit_code=phase0_rc,
    )
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
    _workflow_event(
        workflow_started_at,
        phase="0",
        name="route_decision",
        status="complete",
        route=str(route_decision.get("tier") or "").upper(),
    )
    if execution_plan:
        print(
            "## WORKFLOW_PLAN "
            f"profile={execution_plan.get('profile', args.route_profile) or args.route_profile} "
            f"workflow={execution_plan.get('workflow', 'full')}",
            file=sys.stderr,
        )
        _workflow_event(
            workflow_started_at,
            phase="0",
            name="workflow_plan",
            status="complete",
            profile=execution_plan.get("profile", args.route_profile) or args.route_profile,
            workflow=execution_plan.get("workflow", "full"),
            run_id=payload.get("run_id") or "",
        )

    print(
        "### Phase Progress\n"
        "phase: 1 | name: context | status: in_progress",
        file=sys.stderr,
    )
    phase1_started_at = time.monotonic()
    _workflow_event(workflow_started_at, phase="1", name="context", status="in_progress")
    phase1, phase1_rc = _run_phase1_context(
        beads_runtime=beads_runtime,
        scripts_dir=scripts_dir,
        repo_root=repo_root,
        bead_id=args.bead_id,
        bead_context=bead_context,
    )
    phase1_duration_ms = int((time.monotonic() - phase1_started_at) * 1000)
    if phase1_rc != 0:
        _workflow_event(
            workflow_started_at,
            phase="1",
            name="context",
            status="failed",
            duration_ms=phase1_duration_ms,
            exit_code=phase1_rc,
        )
        return phase1_rc
    print(
        "### Phase Progress\n"
        "phase: 1 | name: context | status: complete",
        file=sys.stderr,
    )
    _workflow_event(
        workflow_started_at,
        phase="1",
        name="context",
        status="complete",
        duration_ms=phase1_duration_ms,
        primary_files=len(phase1.get("primary_files") or []),
        test_files=len(phase1.get("test_files") or []),
    )

    bead_context = _enrich_bead_context(bead_context, phase1)

    missing_phases = ",".join(item["phase"] for item in PREP_GAP_PHASES)
    print(
        "## WORKFLOW_DEGRADED "
        f"missing_phases={missing_phases} "
        "reason=deterministic_cdx_phase_not_implemented",
        file=sys.stderr,
    )
    for gap in PREP_GAP_PHASES:
        _workflow_event(
            workflow_started_at,
            phase=gap["phase"],
            name=gap["phase_name"],
            status="skipped",
            reason=gap["reason"],
        )

    print(
        "### Phase Progress\n"
        "phase: 4 | name: standards_preamble | status: complete",
        file=sys.stderr,
    )
    _workflow_event(
        workflow_started_at,
        phase="4",
        name="standards_preamble",
        status="complete",
        standards_paths=len(str(phase1.get("standard_paths") or "").splitlines()),
    )

    for slot in FULL_WORKFLOW_SLOTS:
        slot_name = slot["slot"]
        dispatch, dispatch_rc = _resolve_full_slot(scripts_dir, payload, slot_name)
        if dispatch_rc != 0:
            return dispatch_rc

        iteration = " | iteration: 1" if slot_name == "implementation" else ""
        print(
            "### Phase Progress\n"
            f"phase: {slot['phase']} | name: {slot['phase_name']} | "
            f"status: in_progress{iteration}",
            file=sys.stderr,
        )
        _workflow_event(
            workflow_started_at,
            phase=slot["phase"],
            name=slot["phase_name"],
            status="in_progress",
            slot=slot_name,
        )
        slot_started_at = time.monotonic()
        slot_rc = _run_slot_adapter(
            scripts_dir,
            repo_root,
            args.bead_id,
            bead_context,
            payload,
            dispatch,
            slot_name,
            slot["phase_label"],
        )
        slot_duration_ms = int((time.monotonic() - slot_started_at) * 1000)
        _workflow_event(
            workflow_started_at,
            phase=slot["phase"],
            name=slot["phase_name"],
            status="complete" if slot_rc == 0 else "failed",
            slot=slot_name,
            duration_ms=slot_duration_ms,
            exit_code=slot_rc,
        )
        if slot_rc != 0:
            return slot_rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
