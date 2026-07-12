#!/usr/bin/env python3
"""Shared callback executor for coordinator cmux trigger-flash signaling.

Delivers a `cmux trigger-flash` callback for a given (run_id, event) pair
exactly once, driven only by explicit CLI parameters -- never environment
variables -- for callback identity (workspace ref, surface ref, run id,
event name). See docs/ARCHITECTURE.md "Coordinator callbacks" for the
best-effort signaling contract this executor implements deterministically.

This module is greenfield and standalone: it does not wire into bin/cld or
bin/cdx (that lifecycle wiring is out of scope here; see sibling beads
CL-gzvu / CL-eqiq). It exists so those launchers can eventually delegate to a
single, tested, exactly-once delivery implementation instead of duplicating
the current best-effort prose contract.

Exit codes:
  0 - success: delivered now, already delivered (idempotent no-op), or no
      callback identity supplied (well-defined no-op, AC "no-callback
      behavior").
  2 - validation error: malformed workspace/surface ref, malformed run id or
      event name, or a missing required argument.
  3 - cmux binary not found on PATH.
  4 - run state error: stale/mismatched state file, or an unwritable state
      path.
  5 - cmux trigger-flash invocation itself returned a non-zero exit code.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Protocol, Sequence


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# \Z (not $) anchors strictly at end-of-string: re's `$` treats a trailing
# "\n" as equivalent to end-of-string, which would let e.g. "run-1\n" match
# these otherwise-strict identity patterns and leak a stray newline into a
# state/lock directory or filename.
WORKSPACE_REF_RE = re.compile(r"^workspace:[0-9]+\Z")
SURFACE_REF_RE = re.compile(r"^surface:[0-9]+\Z")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\Z")

DEFAULT_STATE_ROOT = Path(".beads") / "callback-state"

EXIT_OK = 0
EXIT_VALIDATION_ERROR = 2
EXIT_CMUX_UNAVAILABLE = 3
EXIT_STATE_ERROR = 4
EXIT_CMUX_FAILED = 5


class CallbackError(Exception):
    """Base class for user-facing callback executor failures.

    Every subclass carries a distinct exit_code so main() can fail visibly
    without leaking a traceback into control flow.
    """

    exit_code = EXIT_VALIDATION_ERROR


class ValidationError(CallbackError):
    """Malformed workspace/surface ref, run id, or event name."""

    exit_code = EXIT_VALIDATION_ERROR


class CmuxUnavailableError(CallbackError):
    """The cmux binary is not present on PATH."""

    exit_code = EXIT_CMUX_UNAVAILABLE


class StateError(CallbackError):
    """Stale/mismatched run state, or an unwritable state path."""

    exit_code = EXIT_STATE_ERROR


class CmuxInvocationError(CallbackError):
    """cmux trigger-flash was invoked but returned a non-zero exit code."""

    exit_code = EXIT_CMUX_FAILED


def _validate_path_component(value: str, label: str, pattern: re.Pattern[str]) -> None:
    if not value or not pattern.match(value) or ".." in value or "/" in value:
        raise ValidationError(f"invalid {label} {value!r} (expected pattern {pattern.pattern})")


def validate_run_id(run_id: str) -> None:
    _validate_path_component(run_id, "run id", RUN_ID_RE)


def validate_event(event: str) -> None:
    _validate_path_component(event, "event name", EVENT_NAME_RE)


def validate_ref(value: str | None, kind: str) -> None:
    """Validate an already-present workspace/surface ref. None is always fine
    (absence is handled separately as the no-callback path)."""
    if value is None:
        return
    pattern = WORKSPACE_REF_RE if kind == "workspace" else SURFACE_REF_RE
    if not pattern.match(value):
        raise ValidationError(f"invalid coordinator {kind} {value!r} (expected {kind}:<n>)")


# ---------------------------------------------------------------------------
# CommandRunner (dependency injection for subprocess.run per
# python/dependency-injection.md — never call subprocess.run directly from
# delivery logic, always through an injected CommandRunner).
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CommandResult:
    """Result of running a single external command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Executes external commands. Injectable so tests never shell out."""

    def which(self, name: str) -> str | None:
        ...

    def run(self, argv: Sequence[str]) -> CommandResult:
        ...


class SubprocessCommandRunner:
    """Default CommandRunner backed by the real shutil/subprocess."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(self, argv: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def get_default_runner() -> CommandRunner:
    return SubprocessCommandRunner()


class MockCommandRunner:
    """Test double for CommandRunner. Never shells out to a real binary.

    ``which_results`` overrides presence checks per binary name (defaults to
    "present" for any name not listed). ``default_run_result`` is returned for
    every ``run()`` call unless ``run_results`` has an exact argv-tuple match.
    """

    def __init__(
        self,
        *,
        which_results: dict[str, str | None] | None = None,
        run_results: dict[tuple[str, ...], CommandResult] | None = None,
        default_run_result: CommandResult | None = None,
    ) -> None:
        self._which_results = which_results or {}
        self._run_results = run_results or {}
        self._default_run_result = default_run_result or CommandResult(0, "", "")
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        if name in self._which_results:
            return self._which_results[name]
        return f"/usr/bin/{name}"

    def run(self, argv: Sequence[str]) -> CommandResult:
        argv_list = list(argv)
        self.calls.append(argv_list)
        return self._run_results.get(tuple(argv_list), self._default_run_result)


# ---------------------------------------------------------------------------
# Exactly-once delivery
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CallbackResult:
    """Outcome of a single deliver_callback() invocation."""

    status: str  # "delivered" | "already_delivered" | "skipped_no_callback"
    detail: str


def _state_dir(state_root: Path, run_id: str) -> Path:
    return state_root / run_id


def _lock_path(state_dir: Path, event: str) -> Path:
    return state_dir / f"{event}.lock"


def _state_path(state_dir: Path, event: str) -> Path:
    return state_dir / f"{event}.json"


# A lock older than this with no corresponding state file is treated as an
# orphan left behind by a process that crashed between acquiring the lock
# and writing its state, rather than a legitimate delivery still in flight
# (cmux invocation + the atomic state write normally complete in well under
# a second). Conservative on purpose: a value too small risks reclaiming a
# lock out from under a merely-slow-but-alive delivery and invoking cmux
# twice for the same run+event.
STALE_LOCK_SECONDS = 30.0


def _lock_is_stale(lock_path: Path) -> bool:
    """True if ``lock_path`` exists and is older than STALE_LOCK_SECONDS."""
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        # Lock vanished between the caller's exists()-adjacent check and
        # here (e.g. cleaned up concurrently by another caller). Treat as
        # not stale -- the caller re-attempts acquisition through the normal
        # path rather than racing an unlink against nothing.
        return False
    return age > STALE_LOCK_SECONDS


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON to ``path`` atomically: temp file in the same directory,
    then os.replace() (per python-default-bash-exception / DI standards'
    atomic-write guidance for concurrency-safe state files).

    ``tempfile.mkstemp()`` is inside the try/except so that an OSError raised
    by mkstemp() itself -- e.g. the state directory became unwritable, full,
    or was removed concurrently after the earlier mkdir -- surfaces as a
    visible StateError rather than an uncaught traceback, matching every other
    failure mode in this module (AC3 "unwritable state fail visibly"). This
    also matters for exactly-once safety: this write runs AFTER a successful
    cmux invocation, so an uncaught crash here would leave an orphaned lock
    with no state file -- exactly the precondition _lock_is_stale treats as
    reclaimable, which could trigger a second cmux flash for an already
    delivered event. ``tmp_name`` is guarded because if mkstemp() is what
    failed there is no temp file to clean up yet."""
    directory = path.parent
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(directory))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    except OSError as exc:
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
        raise StateError(f"failed to write state file {path}: {exc}") from exc


def deliver_callback(
    *,
    run_id: str,
    event: str,
    workspace: str | None,
    surface: str | None,
    state_root: Path,
    runner: CommandRunner,
) -> CallbackResult:
    """Deliver (or dedup) a single cmux trigger-flash callback.

    Exactly-once semantics: the first caller for a given (run_id, event) pair
    invokes cmux and persists delivery state; every subsequent call for the
    same pair is a no-op. A failed delivery attempt (missing cmux binary, or
    cmux itself returning non-zero) rolls back its claim so a later retry can
    still succeed -- a transient failure must not permanently silence the
    callback for that run+event. A lock left behind with no state file after
    STALE_LOCK_SECONDS (a crashed prior attempt) is reclaimed and retried
    rather than silently reported as already delivered -- see
    ``_lock_is_stale``.
    """
    validate_run_id(run_id)
    validate_event(event)
    validate_ref(workspace, "workspace")
    validate_ref(surface, "surface")

    if not workspace and not surface:
        return CallbackResult("skipped_no_callback", "no workspace or surface ref supplied; cmux not invoked")

    ref_kind = "surface" if surface else "workspace"
    ref = surface if surface else workspace
    assert ref is not None  # narrowed by the branch above

    state_dir = _state_dir(state_root, run_id)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StateError(f"cannot create state directory {state_dir}: {exc}") from exc

    lock_path = _lock_path(state_dir, event)
    state_path = _state_path(state_dir, event)

    acquired = False
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        acquired = True
    except FileExistsError:
        acquired = False
    except OSError as exc:
        raise StateError(f"cannot create lock file {lock_path}: {exc}") from exc

    if not acquired and not state_path.exists() and _lock_is_stale(lock_path):
        # A lock this old with no corresponding state file means a prior
        # process almost certainly crashed between acquiring the
        # O_CREAT|O_EXCL lock (above) and the later _atomic_write_json()
        # call, leaving an orphaned lock behind -- a legitimate concurrent
        # delivery normally completes the cmux call and writes its state
        # within a small fraction of STALE_LOCK_SECONDS. Reclaim: remove the
        # orphaned lock and retry acquisition once. If a genuine concurrent
        # delivery grabs the lock in that same instant, this retry's
        # FileExistsError simply falls through to the normal
        # already_delivered/mismatch handling below -- exactly-once
        # semantics are preserved either way, and we never call cmux twice
        # for the same run+event without holding the lock ourselves.
        with contextlib.suppress(OSError):
            lock_path.unlink()
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
            finally:
                os.close(fd)
            acquired = True
        except FileExistsError:
            acquired = False
        except OSError as exc:
            raise StateError(f"cannot create lock file {lock_path}: {exc}") from exc

    if not acquired:
        # Another invocation already claimed delivery for this run+event.
        # Exactly-once means we skip -- but verify the recorded state (if any
        # has been written yet) actually matches this run+event before
        # treating it as a legitimate prior delivery, to catch stale/corrupt
        # state left behind by an unrelated run.
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StateError(f"cannot read existing state file {state_path}: {exc}") from exc
            if existing.get("run_id") != run_id or existing.get("event") != event:
                raise StateError(
                    f"state file {state_path} is stale/mismatched: expected "
                    f"run_id={run_id!r} event={event!r}, found "
                    f"run_id={existing.get('run_id')!r} event={existing.get('event')!r}"
                )
        return CallbackResult(
            "already_delivered",
            f"cmux trigger-flash already delivered for run={run_id} event={event}",
        )

    # We hold the lock: attempt delivery. Any failure here rolls back the
    # lock so a future call can retry.
    try:
        if runner.which("cmux") is None:
            raise CmuxUnavailableError("cmux binary not found on PATH; cannot deliver callback")

        argv = ["cmux", "trigger-flash", f"--{ref_kind}", ref]
        result = runner.run(argv)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "no output"
            raise CmuxInvocationError(
                f"cmux trigger-flash failed (exit {result.returncode}): {message}"
            )
    except CallbackError:
        with contextlib.suppress(OSError):
            lock_path.unlink()
        raise

    _atomic_write_json(
        state_path,
        {
            "run_id": run_id,
            "event": event,
            "ref_kind": ref_kind,
            "ref": ref,
            "delivered_at": time.time(),
        },
    )
    return CallbackResult(
        "delivered",
        f"cmux trigger-flash delivered for run={run_id} event={event} ref={ref}",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="Run identifier (identity parameter; never read from env)")
    parser.add_argument("--event", required=True, help="Event name for this callback, e.g. intervention or terminal")
    parser.add_argument("--workspace", default=None, help="Coordinator workspace ref, workspace:<n>")
    parser.add_argument("--surface", default=None, help="Coordinator surface ref, surface:<n>")
    parser.add_argument(
        "--state-root",
        default=None,
        help="Root directory for per-run callback state (default: .beads/callback-state under CWD)",
    )
    return parser


def main(argv: list[str] | None = None, *, runner: CommandRunner | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    active_runner = runner or get_default_runner()
    state_root = Path(args.state_root) if args.state_root else Path.cwd() / DEFAULT_STATE_ROOT

    try:
        result = deliver_callback(
            run_id=args.run,
            event=args.event,
            workspace=args.workspace,
            surface=args.surface,
            state_root=state_root,
            runner=active_runner,
        )
    except CallbackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"{result.status.upper()}: {result.detail}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
