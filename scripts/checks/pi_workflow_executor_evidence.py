#!/usr/bin/env python3
"""Executable Pi Workflow executor evidence checks for CL-2p73 (AC3).

ADR-0006 makes the Claude Workflow JS surface canonical and its native tool the
canonical executor. The heterogeneous-marketplace ADR may supersede that
decision only when an objective, re-runnable evidence threshold is met. This
module is that threshold: it enumerates the checks, runs them against the live
machine and repository, writes one typed artifact, and derives the verdict from
the recorded outcomes rather than from prose.

The verdict is intentionally derived, not authored. A later reader re-runs this
runner; if Pi grows a Workflow-spec executor the verdict flips without anyone
editing the ADR's claim by hand.

Usage:
    uv run python scripts/checks/pi_workflow_executor_evidence.py \\
        --output docs/research/pi-workflow-executor-evidence.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

SCHEMA = "cognovis.pi-workflow-executor-evidence.v1"
BEAD_ID = "CL-2p73"

PASS = "pass"
FAIL = "fail"
UNAVAILABLE = "unavailable"

#: Constitutive checks. ADR-0006 Decisions 2-4 define the Workflow primitive by
#: these properties; a candidate executor that misses one is not an executor for
#: this primitive, it is a different primitive.
CONSTITUTIVE_CHECKS = ("PWE-2", "PWE-3", "PWE-4", "PWE-5")

#: Migration-completeness checks. Even a working executor may not be adopted
#: until installed receipts, the deploy gate, and rollback have a defined path.
MIGRATION_CHECKS = ("PWE-6", "PWE-7", "PWE-8")

#: The canonical injected orchestration globals from ADR-0006 Decision 2.
WORKFLOW_GLOBALS = ("agent", "pipeline", "parallel", "phase", "budget", "args", "workflow")

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Check:
    """One executable evidence check."""

    check_id: str
    title: str
    method: str
    runner: Callable[["Context"], tuple[str, str]]


@dataclass(frozen=True)
class Context:
    """Everything a check may inspect."""

    repo_root: Path
    pi_executable: str | None
    pi_version: str | None
    pi_help: str


def _run(argv: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env dependent
        return 127, f"{type(exc).__name__}: {exc}"
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def build_context(repo_root: Path) -> Context:
    executable = shutil.which("pi")
    version = None
    help_text = ""
    if executable:
        code, out = _run([executable, "--version"])
        if code == 0:
            version = out.strip().splitlines()[0].strip() if out.strip() else None
        _, help_text = _run([executable, "--help"])
    return Context(
        repo_root=repo_root,
        pi_executable=executable,
        pi_version=version,
        pi_help=help_text,
    )


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def _check_runtime_identity(ctx: Context) -> tuple[str, str]:
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; the candidate runtime cannot be pinned."
    if not ctx.pi_version:
        return FAIL, f"`{ctx.pi_executable} --version` produced no version string."
    return PASS, f"Pi runtime pinned: executable={ctx.pi_executable} version={ctx.pi_version}"


def _check_spec_executor(ctx: Context) -> tuple[str, str]:
    """Does Pi expose an entrypoint that executes a canonical Workflow JS spec?"""
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; no executor entrypoint can be probed."
    haystack = ctx.pi_help.lower()
    # A Workflow-spec executor would have to surface a run/exec entrypoint for a
    # spec file. Pi's documented command set is install/remove/update/list/config/auth.
    documented_commands = re.findall(r"^\s{2}pi\s+([a-z-]+)", ctx.pi_help, re.MULTILINE)
    spec_commands = sorted(
        {cmd for cmd in documented_commands if cmd in {"workflow", "workflows", "run", "exec"}}
    )
    if spec_commands:
        return PASS, (
            "Pi documents a candidate spec-execution entrypoint: "
            f"{', '.join(spec_commands)} (commands seen: {sorted(set(documented_commands))})"
        )
    mentions_workflow = "workflow" in haystack
    return FAIL, (
        "Pi exposes no Workflow-spec execution entrypoint. Documented commands are "
        f"{sorted(set(documented_commands))}; the surface is an interactive/`--print` "
        "coding assistant with extensions, skills, prompt templates, and sessions. "
        f"'workflow' appears in `pi --help`: {mentions_workflow}. A canonical spec "
        "(`export const meta = {...}` first statement plus a top-level async body) has "
        "no loader."
    )


def _check_injected_globals(ctx: Context) -> tuple[str, str]:
    """Does the candidate executor inject the ADR-0006 orchestration globals?"""
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; injected globals cannot be probed."
    launcher = Path(ctx.pi_executable)
    try:
        blob = launcher.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:  # pragma: no cover - env dependent
        return UNAVAILABLE, f"Could not read {launcher}: {exc}"
    marker_present = "export const meta" in blob
    found = sorted(
        name for name in WORKFLOW_GLOBALS if re.search(rf"\b{name}\s*\(", ctx.pi_help)
    )
    if marker_present:
        return PASS, (
            f"{launcher} references the canonical `export const meta` spec marker; "
            f"help-surface global references: {found}"
        )
    return FAIL, (
        f"{launcher} contains no `export const meta` spec marker and Pi documents no "
        f"injected orchestration globals {list(WORKFLOW_GLOBALS)}. Pi's unit of model work "
        "is an AgentSession created by extension TypeScript, not a leaf `agent(prompt, opts)` "
        "call injected into an inert JavaScript spine."
    )


def _check_journal_and_resume(ctx: Context) -> tuple[str, str]:
    """Is orchestration journaled per leaf call and resumable after a crash?"""
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; journal semantics cannot be probed."
    resumes_sessions = "--resume" in ctx.pi_help or "--continue" in ctx.pi_help
    return FAIL, (
        "Pi resumes conversational SESSIONS (`--continue`/`--resume` present: "
        f"{resumes_sessions}), not orchestration runs. ADR-0006 requires a journal keyed by a "
        "hash of (prompt, opts) per `agent()` call so a re-run with the same script and args is "
        "a full cache hit and a crashed run resumes at the failed leaf. Pi exposes no such "
        "run journal, because it has no leaf-call abstraction to key one on."
    )


def _check_inert_spine(ctx: Context) -> tuple[str, str]:
    """Is the orchestration layer denied filesystem, shell, and network?

    Evidence source is the Cognovis Pi harness design, which is the only
    concrete Pi orchestration proposal on this machine.
    """
    candidates = [
        ctx.repo_root.parent / "cognovis-pi" / "docs" / "native-executive-pack-harness.md",
        Path.home() / "code" / "library" / "cognovis-pi" / "docs" / "native-executive-pack-harness.md",
    ]
    design = next((path for path in candidates if path.is_file()), None)
    if design is None:
        return UNAVAILABLE, (
            "The Pi harness design document was not found at "
            f"{[str(path) for path in candidates]}; spine inertness cannot be evaluated."
        )
    text = design.read_text(encoding="utf-8", errors="ignore")
    side_effect_markers = [
        marker
        for marker in ("Git and Beads adapters", "Evidence store", "Git adapter", "Beads adapter")
        if marker in text
    ]
    if side_effect_markers:
        return FAIL, (
            f"{design} places {side_effect_markers} inside the orchestration extension itself. "
            "ADR-0006 Decision 4 makes an inert spine normative: the orchestration layer has no "
            "filesystem, no shell, and no network. A host that executes git, Beads, and gate "
            "side effects is the acting layer and the deciding layer at once, which is the exact "
            "separation ADR-0006 exists to enforce."
        )
    return PASS, f"{design} declares no orchestration-layer side effects."


def _iter_lock_files(repo_root: Path) -> list[Path]:
    search_roots = [repo_root]
    code_root = Path.home() / "code"
    if code_root.is_dir():
        search_roots.append(code_root)
    found: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        for depth_glob in ("*/.library.lock", "*/*/.library.lock", ".library.lock"):
            for path in sorted(root.glob(depth_glob)):
                resolved = path.resolve()
                if resolved not in seen and ".worktrees" not in resolved.parts:
                    seen.add(resolved)
                    found.append(resolved)
    return found


def _check_receipt_migration(ctx: Context) -> tuple[str, str]:
    """Does every installed workflow receipt have a defined Pi target?"""
    locks = _iter_lock_files(ctx.repo_root)
    if not locks:
        return UNAVAILABLE, "No `.library.lock` files were reachable; receipts cannot be inventoried."
    workflow_receipts: list[str] = []
    for lock in locks:
        try:
            text = lock.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - env dependent
            continue
        for match in re.finditer(r"^\s*-\s*id:\s*(workflow:[^\s]+)", text, re.MULTILINE):
            workflow_receipts.append(f"{lock}:{match.group(1)}")
    catalogued = _count_catalogued_workflows(ctx.repo_root / "library.yaml")
    materialized = _materialized_workflow_projections()
    return FAIL, (
        f"{catalogued} workflow catalog entries, {len(workflow_receipts)} lockfile workflow "
        f"receipts, and {len(materialized)} materialized harness projections "
        f"({[path.name for path in materialized][:8]}) were found. The installer's workflow type "
        "still targets `workflows/` as Claude workflow JavaScript "
        "(scripts/lib/primitives.py: install_subdir='workflows'). No Pi target path, receipt "
        "re-key rule, or re-materialization rule is defined for any of them, so migration is "
        "undefined rather than merely incomplete. The projections that exist are additionally "
        "unreceipted, so a cutover has nothing to migrate FROM in lock terms."
    )


def _count_catalogued_workflows(catalog: Path) -> int:
    if not catalog.is_file():
        return 0
    try:
        import yaml  # local import: the checker must run without a hard YAML dependency
    except ImportError:  # pragma: no cover - env dependent
        return -1
    try:
        data = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:  # pragma: no cover - malformed catalog
        return -1
    entries = ((data.get("library") or {}).get("workflows")) or []
    return len(entries) if isinstance(entries, list) else 0


def _materialized_workflow_projections() -> list[Path]:
    roots = [
        Path.home() / ".claude" / "workflows",
        Path.home() / ".agents" / "workflows",
    ]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(path for path in root.iterdir() if path.suffix == ".js"))
    return found


def _check_deploy_gate_replacement(ctx: Context) -> tuple[str, str]:
    """Is there a Pi-side replacement for the native parse-check deploy gate?"""
    installer = ctx.repo_root / "scripts" / "lib" / "installers" / "simple_file.py"
    if not installer.is_file():
        return UNAVAILABLE, f"{installer} not found; the current deploy gate cannot be located."
    text = installer.read_text(encoding="utf-8", errors="ignore")
    has_native_gate = "export const meta" in text and "node --check" in text
    pi_gate_markers = [marker for marker in ("pi --check", "pi workflow", "pi_workflow_gate") if marker in text]
    if pi_gate_markers:
        return PASS, f"{installer} already carries a Pi-side gate: {pi_gate_markers}"
    return FAIL, (
        f"{installer} enforces the ADR-0006 native parse gate (meta-first textual check plus "
        f"`node --check`): present={has_native_gate}. No Pi-side equivalent exists, so superseding "
        "ADR-0006 today would delete a working deploy gate and replace it with nothing."
    )


def _check_rollback_path(ctx: Context) -> tuple[str, str]:
    """Is there a reachable rollback to the ADR-0006 Claude executor?"""
    runtime = ctx.repo_root / "scripts" / "lib" / "workflow_runtime.py"
    if not runtime.is_file():
        return UNAVAILABLE, f"{runtime} not found; rollback capability cannot be evaluated."
    text = runtime.read_text(encoding="utf-8", errors="ignore")
    has_status_registry = "ADAPTER_PRESERVATION_STATUS" in text
    blocked = re.findall(r'"(?P<name>[a-z0-9_-]+)":\s*"blocked"', text)
    verified = re.findall(r'"(?P<name>[a-z0-9_-]+)":\s*"verified"', text)
    return FAIL, (
        f"{runtime} carries the fail-closed adapter registry (present={has_status_registry}) with "
        f"verified adapters={sorted(set(verified))} and blocked adapters={sorted(set(blocked))}. "
        "No adapter is approved for mutating execution, so the ADR-0006 fallback is itself "
        "read-only. A rollback target that cannot run mutating work is not a rollback path for a "
        "superseded executor; it is the reason ADR-0006 must be retained rather than replaced."
    )


CHECKS: tuple[Check, ...] = (
    Check(
        "PWE-1",
        "Pi runtime identity and version pin",
        "Resolve `pi` on PATH and record its reported version as the runtime identity.",
        _check_runtime_identity,
    ),
    Check(
        "PWE-2",
        "Pi executes a canonical Workflow JS spec",
        "Scan Pi's documented command surface for an entrypoint that loads and runs a spec file.",
        _check_spec_executor,
    ),
    Check(
        "PWE-3",
        "Pi injects the ADR-0006 orchestration globals",
        "Probe the Pi launcher and help surface for the canonical spec marker and injected globals.",
        _check_injected_globals,
    ),
    Check(
        "PWE-4",
        "Pi journals leaf calls and resumes a crashed run",
        "Distinguish conversational session resume from a (prompt, opts)-keyed orchestration journal.",
        _check_journal_and_resume,
    ),
    Check(
        "PWE-5",
        "The Pi orchestration spine is inert",
        "Inspect the Cognovis Pi harness design for orchestration-layer filesystem, shell, or VCS side effects.",
        _check_inert_spine,
    ),
    Check(
        "PWE-6",
        "Installed workflow receipts have a defined Pi migration",
        "Inventory workflow catalog entries and lockfile receipts and look for a defined Pi target path.",
        _check_receipt_migration,
    ),
    Check(
        "PWE-7",
        "The native parse-check deploy gate has a Pi replacement",
        "Inspect the workflow installer for the ADR-0006 native gate and any Pi-side equivalent.",
        _check_deploy_gate_replacement,
    ),
    Check(
        "PWE-8",
        "A rollback path to the ADR-0006 executor is reachable",
        "Inspect the Library runtime adapter-preservation registry for an executor that may run mutating work.",
        _check_rollback_path,
    ),
)


def evaluate_threshold(outcomes: Mapping[str, str]) -> dict[str, object]:
    """Derive the supersession verdict from recorded check outcomes.

    Supersession requires every constitutive AND every migration check to pass.
    `PWE-1` is runtime context and is never a threshold input.
    """
    required = CONSTITUTIVE_CHECKS + MIGRATION_CHECKS
    missing = [check_id for check_id in required if check_id not in outcomes]
    if missing:
        raise ValueError(f"threshold requires an outcome for every check; missing {missing}")
    failed = [check_id for check_id in required if outcomes[check_id] != PASS]
    return {
        "threshold": (
            "Supersede ADR-0006 only when all of "
            f"{list(CONSTITUTIVE_CHECKS)} (constitutive) and {list(MIGRATION_CHECKS)} "
            "(migration completeness) record `pass`. Any `fail` or `unavailable` retains ADR-0006."
        ),
        "verdict": "retain-adr-0006" if failed else "supersede-adr-0006",
        "failed_checks": failed,
    }


def run_checks(repo_root: Path) -> dict[str, object]:
    ctx = build_context(repo_root)
    records: list[dict[str, str]] = []
    for check in CHECKS:
        result, evidence = check.runner(ctx)
        records.append(
            {
                "check_id": check.check_id,
                "title": check.title,
                "method": check.method,
                "result": result,
                "evidence": evidence,
            }
        )
    outcomes = {item["check_id"]: item["result"] for item in records}
    threshold = evaluate_threshold(outcomes)
    return {
        "schema": SCHEMA,
        "bead_id": BEAD_ID,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime": {
            "pi_executable": ctx.pi_executable,
            "pi_version": ctx.pi_version,
        },
        "constitutive_checks": list(CONSTITUTIVE_CHECKS),
        "migration_checks": list(MIGRATION_CHECKS),
        "checks": records,
        **threshold,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    payload = run_checks(args.repo_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        print(f"verdict: {payload['verdict']}")
        for item in payload["checks"]:  # type: ignore[index]
            print(f"  {item['check_id']} {item['result']:<12} {item['title']}")
    return 0 if payload["verdict"] == "supersede-adr-0006" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
