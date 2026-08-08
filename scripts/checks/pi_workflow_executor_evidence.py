#!/usr/bin/env python3
"""Executable Pi Workflow executor evidence checks for CL-2p73 (AC3).

ADR-0006 makes the Claude Workflow JS surface canonical and its native tool the
canonical executor. ADR-0011 may supersede that decision only when an objective,
re-runnable evidence threshold is met. This module is that threshold: it
enumerates the checks, runs them against the live machine and repository, writes
one typed artifact, and derives the verdict from the recorded outcomes rather
than from prose.

The verdict is intentionally derived, not authored. **Every threshold check has a
reachable `pass` path**, and `tests/test_pi_workflow_executor_evidence.py`
exercises both the pass and the fail path of each one against synthetic contexts.
A checker whose checks cannot pass would weld the re-entry gate shut and make the
"the verdict flips automatically" claim false; that defect was found in review and
is what this structure exists to prevent.

Checks compose. `PWE-2` discovers a spec-execution entrypoint and publishes it in
a shared probe map; `PWE-3` and `PWE-4` then probe **that entrypoint**. A check
that has no subject to probe records `fail` with "no executor to probe", which is
an honest observation about the world, not a hard-coded outcome.

Usage:
    uv run python scripts/checks/pi_workflow_executor_evidence.py \\
        --output docs/research/pi-workflow-executor-evidence.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "cognovis.pi-workflow-executor-evidence.v1"
BEAD_ID = "CL-2p73"

PASS = "pass"
FAIL = "fail"
UNAVAILABLE = "unavailable"
RESULTS = (PASS, FAIL, UNAVAILABLE)

#: Constitutive checks. ADR-0006 Decisions 2-4 define the Workflow primitive by
#: these properties; a candidate executor that misses one is not an executor for
#: this primitive, it is a different primitive.
CONSTITUTIVE_CHECKS = ("PWE-2", "PWE-3", "PWE-4", "PWE-5")

#: Migration-completeness checks. Even a working executor may not be adopted
#: until installed receipts, the deploy gate, and rollback have a defined path.
MIGRATION_CHECKS = ("PWE-6", "PWE-7", "PWE-8")

#: The canonical injected orchestration globals from ADR-0006 Decision 2.
WORKFLOW_GLOBALS = ("agent", "pipeline", "parallel", "phase", "budget", "args", "workflow")

#: Command names that could plausibly load and run a spec file.
SPEC_ENTRYPOINT_CANDIDATES = frozenset({"workflow", "workflows", "run", "exec"})

#: A canonical-shaped probe spec. `export const meta` must be the first statement
#: (ADR-0006 Decision 2); the body reports which orchestration globals the
#: executor injected.
PROBE_SPEC = """export const meta = {
  name: 'pwe-probe',
  description: 'ADR-0011 executor probe: reports injected orchestration globals',
};

const names = %s;
const present = names.filter((n) => typeof globalThis[n] !== 'undefined');
console.log('PWE_GLOBALS=' + present.join(','));
""" % json.dumps(list(WORKFLOW_GLOBALS))

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Check:
    """One executable evidence check."""

    check_id: str
    title: str
    method: str
    runner: Callable[["Context", dict[str, Any]], tuple[str, str]]


@dataclass(frozen=True)
class Context:
    """Everything a check may inspect.

    `spec_runner` is the single injection point that makes behavioral probing
    testable: it executes a canonical spec through a discovered entrypoint and
    returns `(exit_code, output)`.
    """

    repo_root: Path
    pi_executable: str | None
    pi_version: str | None
    pi_help: str
    subcommand_help: Mapping[str, str] = field(default_factory=dict)
    spec_runner: Callable[[str, Path], tuple[int, str]] | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    #: Where materialized harness projections live. Explicit so PWE-6 probes a
    #: bounded, testable surface instead of reaching into the ambient home directory.
    projection_roots: tuple[Path, ...] = ()
    #: Extra roots searched for `.library.lock` files, beyond the repository itself.
    lock_search_roots: tuple[Path, ...] = ()


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


def documented_commands(help_text: str) -> list[str]:
    """Command names Pi documents in its own help output."""
    return sorted(set(re.findall(r"^\s{2}pi\s+([a-z-]+)", help_text, re.MULTILINE)))


def build_context(repo_root: Path) -> Context:
    import os

    executable = shutil.which("pi")
    version = None
    help_text = ""
    sub_help: dict[str, str] = {}
    if executable:
        code, out = _run([executable, "--version"])
        if code == 0 and out.strip():
            version = out.strip().splitlines()[0].strip()
        _, help_text = _run([executable, "--help"])
        for command in sorted(SPEC_ENTRYPOINT_CANDIDATES & set(documented_commands(help_text))):
            _, sub_help[command] = _run([executable, command, "--help"])

    def real_spec_runner(entrypoint: str, spec_path: Path) -> tuple[int, str]:
        assert executable is not None
        return _run([executable, entrypoint, str(spec_path)])

    return Context(
        repo_root=repo_root,
        pi_executable=executable,
        pi_version=version,
        pi_help=help_text,
        subcommand_help=sub_help,
        spec_runner=real_spec_runner if executable else None,
        env=dict(os.environ),
        projection_roots=(
            Path.home() / ".claude" / "workflows",
            Path.home() / ".agents" / "workflows",
        ),
        lock_search_roots=(Path.home() / "code",),
    )


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def _check_runtime_identity(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; the candidate runtime cannot be pinned."
    if not ctx.pi_version:
        return FAIL, f"`{ctx.pi_executable} --version` produced no version string."
    return PASS, f"Pi runtime pinned: executable={ctx.pi_executable} version={ctx.pi_version}"


def _check_spec_executor(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Does Pi execute a canonical Workflow JS spec?

    Discovery, then behavior. A documented entrypoint is necessary but not
    sufficient: the check passes only when a canonical-shaped spec actually runs
    through it. The discovered entrypoint is published for PWE-3 and PWE-4.
    """
    if not ctx.pi_executable:
        return UNAVAILABLE, "No `pi` executable on PATH; no executor entrypoint can be probed."
    commands = documented_commands(ctx.pi_help)
    candidates = sorted(SPEC_ENTRYPOINT_CANDIDATES & set(commands))
    if not candidates:
        return FAIL, (
            "Pi documents no candidate spec-execution entrypoint. Documented commands are "
            f"{commands}; the surface is an interactive/`--print` coding assistant with "
            "extensions, skills, prompt templates, and sessions. A canonical spec "
            "(`export const meta = {...}` first statement plus a top-level async body) has no "
            f"loader. ('workflow' appears in `pi --help`: {'workflow' in ctx.pi_help.lower()})"
        )
    if ctx.spec_runner is None:  # pragma: no cover - guarded by the executable check
        return UNAVAILABLE, "No spec runner is available to execute the probe spec."

    attempts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = Path(tmp) / "pwe-probe.js"
        spec_path.write_text(PROBE_SPEC, encoding="utf-8")
        for entrypoint in candidates:
            code, output = ctx.spec_runner(entrypoint, spec_path)
            attempts.append(f"`pi {entrypoint} <spec>` exit={code}")
            if code == 0:
                shared["executor_entrypoint"] = entrypoint
                shared["executor_output"] = output
                return PASS, (
                    f"Pi executed a canonical probe spec through `pi {entrypoint}` (exit 0). "
                    f"Discovered entrypoint published for PWE-3 and PWE-4. Attempts: {attempts}"
                )
    return FAIL, (
        f"Pi documents candidate entrypoints {candidates} but none executed a canonical probe "
        f"spec. Attempts: {attempts}"
    )


def _check_injected_globals(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Does the executor inject the ADR-0006 orchestration globals?

    Probes the entrypoint PWE-2 discovered by reading the probe spec's own report
    of which globals were defined during its run.
    """
    entrypoint = shared.get("executor_entrypoint")
    if not entrypoint:
        return FAIL, (
            "No spec-execution entrypoint was discovered by PWE-2, so there is no executor whose "
            f"injected globals can be probed. ADR-0006 requires {list(WORKFLOW_GLOBALS)}. Pi's "
            "unit of model work is an AgentSession created by extension TypeScript, not a leaf "
            "`agent(prompt, opts)` call injected into an inert JavaScript spine."
        )
    output = str(shared.get("executor_output") or "")
    match = re.search(r"PWE_GLOBALS=([a-zA-Z0-9_,]*)", output)
    if not match:
        return FAIL, (
            f"`pi {entrypoint}` ran the probe spec but emitted no `PWE_GLOBALS=` report, so no "
            "orchestration global could be observed."
        )
    present = [name for name in match.group(1).split(",") if name]
    missing = [name for name in WORKFLOW_GLOBALS if name not in present]
    if missing:
        return FAIL, (
            f"`pi {entrypoint}` injected {present} but is missing {missing} of the ADR-0006 "
            "orchestration globals."
        )
    return PASS, f"`pi {entrypoint}` injected every ADR-0006 orchestration global: {present}"


def _check_journal_and_resume(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Is orchestration journaled per leaf call and resumable after a crash?

    Conversational session resume does not qualify. The check looks for run-level
    journal/resume on the discovered spec entrypoint's own surface.
    """
    entrypoint = shared.get("executor_entrypoint")
    if not entrypoint:
        session_resume = "--resume" in ctx.pi_help or "--continue" in ctx.pi_help
        return FAIL, (
            "No spec-execution entrypoint was discovered by PWE-2, so there is no orchestration "
            "run to journal. Pi resumes conversational SESSIONS (`--continue`/`--resume` present: "
            f"{session_resume}), not runs. ADR-0006 requires a journal keyed by a hash of "
            "(prompt, opts) per `agent()` call so a re-run with the same script and args is a "
            "full cache hit and a crashed run resumes at the failed leaf."
        )
    surface = ctx.subcommand_help.get(entrypoint, "")
    has_journal = bool(re.search(r"\bjournal\b", surface, re.IGNORECASE))
    has_run_resume = bool(re.search(r"--resume\b|\bresume (a |the )?run\b", surface, re.IGNORECASE))
    if has_journal and has_run_resume:
        return PASS, (
            f"`pi {entrypoint} --help` documents both a run journal and run resume: "
            f"journal={has_journal}, resume={has_run_resume}."
        )
    return FAIL, (
        f"`pi {entrypoint} --help` does not document a leaf-call journal and run resume "
        f"(journal={has_journal}, resume={has_run_resume}). Conversational session resume does "
        "not satisfy ADR-0006's (prompt, opts)-keyed run journal."
    )


#: Markers that indicate an orchestration layer performing its own side effects.
_SPINE_SIDE_EFFECT_MARKERS = (
    "Git and Beads adapters",
    "Git adapter",
    "Beads adapter",
    "Evidence store",
    "Git and Beads",
)


def _design_document(ctx: Context) -> Path | None:
    candidates = [
        ctx.repo_root.parent / "cognovis-pi" / "docs" / "native-executive-pack-harness.md",
        Path.home() / "code" / "library" / "cognovis-pi" / "docs" / "native-executive-pack-harness.md",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _check_design_spine_inertness(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Does the only concrete Pi orchestration design keep its spine inert?

    Scope note, because the title used to overclaim: this probes a **design
    document**, not Pi's runtime. It is the strongest available evidence because
    that document is the only concrete Pi orchestration proposal on this machine.
    """
    design = _design_document(ctx)
    if design is None:
        return UNAVAILABLE, (
            "The Pi harness design document was not found next to this repository or under "
            "~/code/library/cognovis-pi/docs/; spine inertness cannot be evaluated."
        )
    text = design.read_text(encoding="utf-8", errors="ignore")
    markers = [marker for marker in _SPINE_SIDE_EFFECT_MARKERS if marker in text]
    if markers:
        return FAIL, (
            f"{design} places {sorted(set(markers))} inside the orchestration extension itself. "
            "ADR-0006 Decision 4 makes an inert spine normative: the orchestration layer has no "
            "filesystem, no shell, and no network. A host that executes git, Beads, and gate side "
            "effects is the acting layer and the deciding layer at once, which is the exact "
            "separation ADR-0006 exists to enforce. The document is also pack-specific: it is a "
            "native Executive Pack harness, not a general executor for the Workflow primitive."
        )
    return PASS, f"{design} declares no orchestration-layer side effects."


def _iter_lock_files(repo_root: Path, extra_roots: tuple[Path, ...] = ()) -> list[Path]:
    search_roots = [repo_root, *(root for root in extra_roots if root.is_dir())]
    found: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        for depth_glob in (".library.lock", "*/.library.lock", "*/*/.library.lock"):
            for path in sorted(root.glob(depth_glob)):
                resolved = path.resolve()
                if resolved not in seen and ".worktrees" not in resolved.parts:
                    seen.add(resolved)
                    found.append(resolved)
    return found


def _count_catalogued_workflows(catalog: Path) -> int:
    if not catalog.is_file():
        return 0
    try:
        import yaml
    except ImportError:  # pragma: no cover - env dependent
        return -1
    try:
        data = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:  # pragma: no cover - malformed catalog
        return -1
    entries = ((data.get("library") or {}).get("workflows")) or []
    return len(entries) if isinstance(entries, list) else 0


def _materialized_workflow_projections(roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(path for path in root.iterdir() if path.suffix == ".js"))
    return found


def _receipted_workflow_names(locks: list[Path]) -> set[str]:
    """Workflow receipt names, parsed per receipt entry rather than by line count.

    A receipt is recognized from either serialization the lockfile uses: a
    `- id: workflow:<name>` list item, or a `- name: <name>` entry whose block
    also declares `type: workflow`.
    """
    names: set[str] = set()
    for lock in locks:
        try:
            text = lock.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - env dependent
            continue
        for match in re.finditer(r"^\s*-\s*id:\s*workflow:([^\s@]+)", text, re.MULTILINE):
            names.add(match.group(1))
        # Block form: split on list-item boundaries and keep blocks typed workflow.
        for block in re.split(r"^\s*-\s+(?=\w)", text, flags=re.MULTILINE):
            if re.search(r"^\s*type:\s*workflow\s*$", block, re.MULTILINE):
                found = re.search(r"^\s*name:\s*(\S+)", block, re.MULTILINE)
                if found:
                    names.add(found.group(1))
    return names


def _check_receipt_migration(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Do installed workflow receipts have a defined Pi migration?

    Passes when the workflow primitive declares a Pi install target (somewhere to
    migrate TO) and **every materialized projection is individually matched to a
    receipt by name** (something to migrate FROM).

    The identity match is the point. An earlier version compared the *count* of
    projections against the *count* of receipts found in unrelated lock files,
    which could certify coverage that no projection actually had.
    """
    primitives = ctx.repo_root / "scripts" / "lib" / "primitives.py"
    if not primitives.is_file():
        return UNAVAILABLE, f"{primitives} not found; the workflow install target cannot be read."
    text = primitives.read_text(encoding="utf-8", errors="ignore")
    workflow_block = ""
    match = re.search(r'name="workflow",(.*?)\)\s*,\s*PrimitiveInfo', text, re.S)
    if match:
        workflow_block = match.group(1)
    pi_target = bool(re.search(r"pi[_-]?(install_subdir|target|projection)", workflow_block, re.I))

    locks = _iter_lock_files(ctx.repo_root, ctx.lock_search_roots)
    receipted = _receipted_workflow_names(locks)
    materialized = _materialized_workflow_projections(ctx.projection_roots)
    uncovered = sorted(path.stem for path in materialized if path.stem not in receipted)
    catalogued = _count_catalogued_workflows(ctx.repo_root / "library.yaml")

    if pi_target and not uncovered:
        return PASS, (
            f"The workflow primitive declares a Pi target, and each of the {len(materialized)} "
            f"materialized projections is matched by name to a workflow receipt "
            f"(receipted names: {sorted(receipted)}). Every installed receipt therefore has a "
            "defined migration source and destination."
        )
    return FAIL, (
        f"{catalogued} workflow catalog entries and {len(materialized)} materialized harness "
        f"projections ({[path.name for path in materialized][:8]}) were found. A Pi target path "
        f"is declared for the workflow primitive: {pi_target} (the entry still uses "
        "`install_subdir='workflows'` as Claude workflow JavaScript). Projections with **no "
        f"matching workflow receipt by name**: {uncovered[:8]} ({len(uncovered)} of "
        f"{len(materialized)}); receipted workflow names found across {len(locks)} lock files: "
        f"{sorted(receipted)[:8]}. Migration is therefore undefined in both directions: no Pi "
        "destination is declared, and the projections that exist have nothing to migrate FROM in "
        "lock terms."
    )


def _check_deploy_gate_replacement(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Does the native parse-check deploy gate have a Pi replacement?

    Requires a real Pi-side validation code path, not a marker string that a
    comment could satisfy.
    """
    installer = ctx.repo_root / "scripts" / "lib" / "installers" / "simple_file.py"
    if not installer.is_file():
        return UNAVAILABLE, f"{installer} not found; the current deploy gate cannot be located."
    text = installer.read_text(encoding="utf-8", errors="ignore")
    code_only = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    code_only = re.sub(r'"""(?:.|\n)*?"""', "", code_only)
    has_native_gate = "export const meta" in text and "node --check" in text
    pi_gate_defs = set(
        re.findall(r"^\s*def\s+(\w*pi\w*(?:gate|check|validate)\w*)", code_only, re.I | re.M)
    )
    # Remove definition sites so `def foo(` is not mistaken for a call to `foo`.
    call_surface = re.sub(r"^\s*def\s+\w+\s*\(", "", code_only, flags=re.M)
    called = set(
        re.findall(r"\b(\w*pi\w*(?:gate|parse|check|validate)\w*)\s*\(", call_surface, re.I)
    )
    # A defined-but-never-called gate is dead code, not a deploy gate.
    reachable = called
    if reachable:
        return PASS, (
            f"{installer} carries a Pi-side gate code path that is actually invoked: "
            f"definitions={sorted(pi_gate_defs)}, call sites={sorted(called)}."
        )
    if pi_gate_defs:
        return FAIL, (
            f"{installer} defines {sorted(pi_gate_defs)} but never calls it. A defined-but-unreached "
            "gate is dead code, not a deploy gate."
        )
    return FAIL, (
        f"{installer} enforces the ADR-0006 native parse gate (meta-first textual check plus "
        f"`node --check`): present={has_native_gate}. No Pi-side validation code path exists "
        "(searched executable code with comments and docstrings stripped), so superseding ADR-0006 "
        "today would delete a working deploy gate and replace it with nothing."
    )


def _check_rollback_path(ctx: Context, shared: dict[str, Any]) -> tuple[str, str]:
    """Is a rollback path to the ADR-0006 executor reachable?

    ADR-0006's canonical executor is the **native Claude Workflow tool**; the
    Library runtime is an explicitly non-canonical subset. Rollback is therefore
    reachable when either the native tool is enabled, or the non-canonical runtime
    has at least one adapter verified for mutating execution.
    """
    native_gate = str(ctx.env.get("CLAUDE_CODE_WORKFLOWS") or "").strip()
    native_enabled = native_gate not in ("", "0", "false", "False")

    runtime = ctx.repo_root / "scripts" / "lib" / "workflow_runtime.py"
    verified: list[str] = []
    blocked: list[str] = []
    runtime_present = runtime.is_file()
    if runtime_present:
        text = runtime.read_text(encoding="utf-8", errors="ignore")
        verified = sorted(set(re.findall(r'"([a-z0-9_-]+)":\s*"verified"', text)))
        blocked = sorted(set(re.findall(r'"([a-z0-9_-]+)":\s*"blocked"', text)))

    if native_enabled:
        return PASS, (
            "The ADR-0006 canonical executor is reachable: the native Workflow tool gate "
            f"CLAUDE_CODE_WORKFLOWS is set to {native_gate!r}."
        )
    if verified:
        return PASS, (
            "The non-canonical Library runtime has adapters verified for mutating execution: "
            f"{verified}. A rollback target that can run mutating work exists."
        )
    return FAIL, (
        "Neither ADR-0006 executor path can run mutating work. The canonical native Workflow tool "
        f"is gated off (CLAUDE_CODE_WORKFLOWS={native_gate!r}), and the explicitly non-canonical "
        f"Library runtime ({runtime}, present={runtime_present}) reports verified adapters="
        f"{verified} and blocked adapters={blocked}. A rollback target that cannot run mutating "
        "work is not a rollback path for a superseded executor; it is the reason ADR-0006 must be "
        "retained rather than replaced."
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
        "Discover a documented spec-execution entrypoint, then execute a canonical probe spec through it.",
        _check_spec_executor,
    ),
    Check(
        "PWE-3",
        "Pi injects the ADR-0006 orchestration globals",
        "Read the probe spec's own report of which orchestration globals the discovered entrypoint injected.",
        _check_injected_globals,
    ),
    Check(
        "PWE-4",
        "Pi journals leaf calls and resumes a crashed run",
        "Probe the discovered entrypoint's surface for a run journal and run resume, not conversational session resume.",
        _check_journal_and_resume,
    ),
    Check(
        "PWE-5",
        "The only concrete Pi orchestration design keeps its spine inert",
        "Inspect the Cognovis Pi harness design document for orchestration-layer filesystem, shell, or VCS side effects.",
        _check_design_spine_inertness,
    ),
    Check(
        "PWE-6",
        "Installed workflow receipts have a defined Pi migration",
        "Require a declared Pi target on the workflow primitive and a lockfile receipt for every materialized projection.",
        _check_receipt_migration,
    ),
    Check(
        "PWE-7",
        "The native parse-check deploy gate has a Pi replacement",
        "Search the workflow installer's executable code, comments stripped, for a Pi-side validation code path.",
        _check_deploy_gate_replacement,
    ),
    Check(
        "PWE-8",
        "A rollback path to the ADR-0006 executor is reachable",
        "Require either the native Workflow tool gate enabled or at least one adapter verified for mutating execution.",
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


def run_checks(repo_root: Path, ctx: Context | None = None) -> dict[str, object]:
    context = ctx if ctx is not None else build_context(repo_root)
    shared: dict[str, Any] = {}
    records: list[dict[str, str]] = []
    for check in CHECKS:
        result, evidence = check.runner(context, shared)
        if result not in RESULTS:  # pragma: no cover - guards a programming error
            raise ValueError(f"{check.check_id} returned an invalid result {result!r}")
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
            "pi_executable": context.pi_executable,
            "pi_version": context.pi_version,
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
