"""Tests for the shared coordinator callback executor.

Covers CL-t32e acceptance criteria:
  AC1: callback identity accepted only via explicit CLI parameters / validated
       structured state derived from those parameters (never environment
       variables).
  AC2: exactly-once delivery per (run, event); distinct events/runs remain
       distinguishable; concurrent duplicate delivery invokes cmux at most once.
  AC3: malformed refs, missing cmux, stale/mismatched run state, and
       unwritable state paths all fail visibly (non-zero, clear stderr) without
       ever constructing a shell string from unvalidated input.
  AC4: this file — focused unit/integration coverage for the above.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coordinator_callback.py"


def _import_module():
    """Dynamically import coordinator_callback.py (matches repo convention,
    e.g. _import_sync_script() in test_project_tooling.py).

    Registers the module in sys.modules before exec_module(): the module uses
    ``from __future__ import annotations`` with ``@dataclasses.dataclass``,
    and dataclasses resolves annotations via ``sys.modules[cls.__module__]``
    -- without this registration that lookup returns None and dataclass
    construction crashes.
    """
    spec = importlib.util.spec_from_file_location("coordinator_callback", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# AC1: explicit-parameter identity, no environment variable interface
# ---------------------------------------------------------------------------


def test_module_has_no_callback_environment_variable_interface() -> None:
    """Identity (run/event/workspace/surface) must come only from CLI params."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "getenv" not in source


def test_main_requires_run_argument() -> None:
    cc = _import_module()
    with pytest.raises(SystemExit) as exc_info:
        cc.main(["--event", "terminal", "--surface", "surface:1"])
    assert exc_info.value.code == 2


def test_main_requires_event_argument() -> None:
    cc = _import_module()
    with pytest.raises(SystemExit) as exc_info:
        cc.main(["--run", "run-1", "--surface", "surface:1"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("bad_workspace", ["workspace:", "workspace:abc", "1", "workspace: 1", "workspace:-1"])
def test_rejects_malformed_workspace_ref(tmp_path: Path, bad_workspace: str) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    with pytest.raises(cc.ValidationError):
        cc.deliver_callback(
            run_id="run-1",
            event="terminal",
            workspace=bad_workspace,
            surface=None,
            state_root=tmp_path / "state",
            runner=runner,
        )
    assert runner.calls == []


@pytest.mark.parametrize("bad_surface", ["surface:", "surface:abc", "3", "surface: 3", "surface:-3"])
def test_rejects_malformed_surface_ref(tmp_path: Path, bad_surface: str) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    with pytest.raises(cc.ValidationError):
        cc.deliver_callback(
            run_id="run-1",
            event="terminal",
            workspace=None,
            surface=bad_surface,
            state_root=tmp_path / "state",
            runner=runner,
        )
    assert runner.calls == []


def test_rejects_invalid_run_id(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    with pytest.raises(cc.ValidationError):
        cc.deliver_callback(
            run_id="../etc/passwd",
            event="terminal",
            workspace=None,
            surface="surface:1",
            state_root=tmp_path / "state",
            runner=runner,
        )
    assert runner.calls == []


def test_rejects_invalid_event_name(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    with pytest.raises(cc.ValidationError):
        cc.deliver_callback(
            run_id="run-1",
            event="../terminal",
            workspace=None,
            surface="surface:1",
            state_root=tmp_path / "state",
            runner=runner,
        )
    assert runner.calls == []


@pytest.mark.parametrize(
    "ref_kind,bad_ref",
    [
        ("workspace", "workspace:1\n"),
        ("surface", "surface:1\n"),
    ],
)
def test_ref_with_trailing_newline_is_rejected(ref_kind: str, bad_ref: str) -> None:
    """re's `$` treats a trailing "\\n" as end-of-string, which would
    otherwise let "workspace:1\\n" slip past this supposedly-strict pattern.
    """
    cc = _import_module()
    with pytest.raises(cc.ValidationError):
        cc.validate_ref(bad_ref, ref_kind)


@pytest.mark.parametrize("bad_run_id", ["run-1\n", "run-1\r\n"], ids=["trailing-lf", "trailing-crlf"])
def test_run_id_with_trailing_newline_or_crlf_is_rejected(bad_run_id: str) -> None:
    cc = _import_module()
    with pytest.raises(cc.ValidationError):
        cc.validate_run_id(bad_run_id)


def test_event_with_trailing_newline_is_rejected() -> None:
    cc = _import_module()
    with pytest.raises(cc.ValidationError):
        cc.validate_event("terminal\n")


def test_command_injection_style_ref_is_rejected_before_any_command_runs(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    with pytest.raises(cc.ValidationError):
        cc.deliver_callback(
            run_id="run-1",
            event="terminal",
            workspace=None,
            surface="surface:1; rm -rf /tmp/whatever",
            state_root=tmp_path / "state",
            runner=runner,
        )
    assert runner.calls == []


# ---------------------------------------------------------------------------
# AC2 / AC4: exactly-once delivery, distinguishable events, no-callback
# ---------------------------------------------------------------------------


def test_no_callback_when_neither_workspace_nor_surface_supplied(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1",
        event="terminal",
        workspace=None,
        surface=None,
        state_root=tmp_path / "state",
        runner=runner,
    )
    assert result.status == "skipped_no_callback"
    assert runner.calls == []


def test_first_delivery_invokes_cmux_trigger_flash_with_surface_ref(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1",
        event="terminal",
        workspace="workspace:15",
        surface="surface:33",
        state_root=tmp_path / "state",
        runner=runner,
    )
    assert result.status == "delivered"
    assert runner.calls == [["cmux", "trigger-flash", "--surface", "surface:33"]]


def test_uses_workspace_ref_when_only_workspace_given(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1",
        event="terminal",
        workspace="workspace:15",
        surface=None,
        state_root=tmp_path / "state",
        runner=runner,
    )
    assert result.status == "delivered"
    assert runner.calls == [["cmux", "trigger-flash", "--workspace", "workspace:15"]]


def test_repeated_delivery_same_run_event_is_noop(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    state_root = tmp_path / "state"
    first = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    second = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    assert first.status == "delivered"
    assert second.status == "already_delivered"
    assert len(runner.calls) == 1


def test_distinct_event_types_same_run_both_deliver(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    state_root = tmp_path / "state"
    intervention = cc.deliver_callback(
        run_id="run-1", event="intervention", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    terminal = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    assert intervention.status == "delivered"
    assert terminal.status == "delivered"
    assert len(runner.calls) == 2


def test_distinct_run_ids_same_event_both_deliver(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    state_root = tmp_path / "state"
    run_a = cc.deliver_callback(
        run_id="run-a", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    run_b = cc.deliver_callback(
        run_id="run-b", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    assert run_a.status == "delivered"
    assert run_b.status == "delivered"
    assert len(runner.calls) == 2


def test_concurrent_repeated_delivery_invokes_cmux_at_most_once(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    state_root = tmp_path / "state"

    def _attempt(_: int):
        return cc.deliver_callback(
            run_id="run-concurrent",
            event="terminal",
            workspace=None,
            surface="surface:33",
            state_root=state_root,
            runner=runner,
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_attempt, range(32)))

    assert len(runner.calls) == 1
    statuses = {r.status for r in results}
    assert statuses <= {"delivered", "already_delivered"}
    assert sum(1 for r in results if r.status == "delivered") == 1


# ---------------------------------------------------------------------------
# AC3: fail visibly — missing cmux, stale/mismatched state, unwritable state
# ---------------------------------------------------------------------------


def test_missing_cmux_binary_fails_visibly_and_allows_retry(tmp_path: Path) -> None:
    cc = _import_module()
    unavailable_runner = cc.MockCommandRunner(which_results={"cmux": None})
    state_root = tmp_path / "state"

    with pytest.raises(cc.CmuxUnavailableError):
        cc.deliver_callback(
            run_id="run-1", event="terminal", workspace=None, surface="surface:33",
            state_root=state_root, runner=unavailable_runner,
        )
    assert unavailable_runner.calls == []

    # Lock must be rolled back so a later attempt (once cmux is available)
    # can still deliver — a transient/missing binary must not permanently
    # silence the callback for this run+event.
    available_runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=available_runner,
    )
    assert result.status == "delivered"
    assert len(available_runner.calls) == 1


def test_cmux_invocation_failure_fails_visibly_and_allows_retry(tmp_path: Path) -> None:
    cc = _import_module()
    failing_runner = cc.MockCommandRunner(
        default_run_result=cc.CommandResult(returncode=1, stdout="", stderr="surface not found")
    )
    state_root = tmp_path / "state"

    with pytest.raises(cc.CmuxInvocationError):
        cc.deliver_callback(
            run_id="run-1", event="terminal", workspace=None, surface="surface:33",
            state_root=state_root, runner=failing_runner,
        )
    assert len(failing_runner.calls) == 1

    succeeding_runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=succeeding_runner,
    )
    assert result.status == "delivered"


def test_stale_mismatched_run_state_fails_visibly_without_invoking_cmux(tmp_path: Path) -> None:
    cc = _import_module()
    state_root = tmp_path / "state"
    run_state_dir = state_root / "run-1"
    run_state_dir.mkdir(parents=True)
    (run_state_dir / "terminal.lock").write_text("99999\n", encoding="utf-8")
    (run_state_dir / "terminal.json").write_text(
        json.dumps({"run_id": "some-other-run", "event": "terminal", "ref": "surface:1"}),
        encoding="utf-8",
    )

    runner = cc.MockCommandRunner()
    with pytest.raises(cc.StateError):
        cc.deliver_callback(
            run_id="run-1", event="terminal", workspace=None, surface="surface:33",
            state_root=state_root, runner=runner,
        )
    assert runner.calls == []


def test_stale_lock_without_state_is_reclaimed_and_delivers(tmp_path: Path) -> None:
    """Simulates the crash window between acquiring the lock and writing the
    state file: a lock file exists but its {event}.json state never got
    written, and the lock is older than STALE_LOCK_SECONDS. This must not be
    silently reported as already_delivered without ever invoking cmux --
    instead the orphaned lock is reclaimed and delivery proceeds normally."""
    cc = _import_module()
    state_root = tmp_path / "state"
    run_state_dir = state_root / "run-1"
    run_state_dir.mkdir(parents=True)
    lock_path = run_state_dir / "terminal.lock"
    lock_path.write_text("12345\n", encoding="utf-8")
    # Backdate the lock past STALE_LOCK_SECONDS so it is treated as an
    # orphan left behind by a crashed process, not an in-flight delivery.
    stale_time = time.time() - (cc.STALE_LOCK_SECONDS + 10)
    os.utime(lock_path, (stale_time, stale_time))

    runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    assert result.status == "delivered"
    assert runner.calls == [["cmux", "trigger-flash", "--surface", "surface:33"]]
    state_path = run_state_dir / "terminal.json"
    assert state_path.exists()
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["run_id"] == "run-1"
    assert written["event"] == "terminal"


def test_fresh_lock_without_state_is_not_reclaimed(tmp_path: Path) -> None:
    """A brand-new lock with no state file yet (well within
    STALE_LOCK_SECONDS) looks identical to a genuine in-flight concurrent
    delivery -- it must NOT be reclaimed, to avoid a second concurrent cmux
    invocation for the same run+event."""
    cc = _import_module()
    state_root = tmp_path / "state"
    run_state_dir = state_root / "run-1"
    run_state_dir.mkdir(parents=True)
    (run_state_dir / "terminal.lock").write_text("12345\n", encoding="utf-8")

    runner = cc.MockCommandRunner()
    result = cc.deliver_callback(
        run_id="run-1", event="terminal", workspace=None, surface="surface:33",
        state_root=state_root, runner=runner,
    )
    assert result.status == "already_delivered"
    assert runner.calls == []


def test_unwritable_state_path_fails_visibly(tmp_path: Path) -> None:
    cc = _import_module()
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("occupied", encoding="utf-8")
    # state_root itself is a plain file, so mkdir(parents=True) beneath it fails.
    state_root = blocking_file / "state"

    runner = cc.MockCommandRunner()
    with pytest.raises(cc.StateError):
        cc.deliver_callback(
            run_id="run-1", event="terminal", workspace=None, surface="surface:33",
            state_root=state_root, runner=runner,
        )
    assert runner.calls == []


def test_write_time_mkstemp_failure_fails_visibly(tmp_path: Path, monkeypatch) -> None:
    """Regression (Phase 7): an OSError from ``tempfile.mkstemp()`` DURING the
    atomic state write -- distinct from the earlier ``state_dir.mkdir(...)``
    failure exercised by test_unwritable_state_path_fails_visibly -- must
    surface as a visible StateError, never an uncaught traceback.

    This is the exact-once hazard the fix guards: the state write runs only
    AFTER a successful cmux invocation, so cmux IS expected to have fired once
    here (the callback was genuinely delivered) before mkstemp() fails. Without
    the fix, mkstemp() sat outside the try/except and leaked a raw traceback,
    leaving an orphaned lock with no state file -- the precondition a later
    stale-lock reclaim would misread as "crashed, safe to re-flash". We assert
    the failure is a clean StateError so main() maps it to EXIT_STATE_ERROR."""
    cc = _import_module()
    state_root = tmp_path / "state"
    runner = cc.MockCommandRunner()

    def _boom(*args, **kwargs):
        raise OSError("simulated: state directory unwritable at write time")

    monkeypatch.setattr(cc.tempfile, "mkstemp", _boom)

    with pytest.raises(cc.StateError):
        cc.deliver_callback(
            run_id="run-1", event="terminal", workspace=None, surface="surface:33",
            state_root=state_root, runner=runner,
        )
    # cmux was invoked exactly once before the write-time failure -- this is the
    # already-delivered-but-no-state window the fix makes fail visibly.
    assert runner.calls == [["cmux", "trigger-flash", "--surface", "surface:33"]]
    # No state file was persisted (the write failed), and no traceback escaped.
    assert not (state_root / "run-1" / "terminal.json").exists()


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() == 0,
    reason="root ignores directory write permission bits",
)
def test_unwritable_state_directory_at_write_time_fails_visibly(tmp_path: Path) -> None:
    """Regression (Phase 7): the state directory is created and the lock is
    acquired successfully, but the directory becomes read-only right before the
    atomic state write (a real filesystem reproduction, distinct from the
    mkdir-failure path). ``tempfile.mkstemp(dir=state_dir)`` then raises
    PermissionError, which must be re-raised as a visible StateError.

    A custom runner chmods the state directory read-only as a side effect of
    the cmux call, precisely modelling a directory whose permissions changed
    after mkdir -- so cmux IS invoked once (delivery happened) before the write
    fails. Permissions are restored in a finally so tmp_path cleanup works."""
    cc = _import_module()
    state_root = tmp_path / "state"
    state_dir = state_root / "run-1"

    class _ChmodOnRunRunner:
        """CommandRunner double that turns state_dir read-only when cmux runs,
        simulating a permissions change between lock acquisition and write."""

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def which(self, name: str) -> str | None:
            return f"/usr/bin/{name}"

        def run(self, argv):
            self.calls.append(list(argv))
            os.chmod(state_dir, 0o555)
            return cc.CommandResult(0, "", "")

    runner = _ChmodOnRunRunner()
    try:
        with pytest.raises(cc.StateError):
            cc.deliver_callback(
                run_id="run-1", event="terminal", workspace=None, surface="surface:33",
                state_root=state_root, runner=runner,
            )
        assert runner.calls == [["cmux", "trigger-flash", "--surface", "surface:33"]]
    finally:
        # Restore write permission so tmp_path teardown can remove the dir.
        if state_dir.exists():
            os.chmod(state_dir, 0o755)


def test_main_reports_errors_on_stderr_and_returns_nonzero_without_traceback(tmp_path: Path, capsys) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner(which_results={"cmux": None})
    exit_code = cc.main(
        [
            "--run", "run-1",
            "--event", "terminal",
            "--surface", "surface:33",
            "--state-root", str(tmp_path / "state"),
        ],
        runner=runner,
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "ERROR" in captured.err
    assert "Traceback" not in captured.err


def test_main_delivers_successfully_end_to_end(tmp_path: Path, capsys) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    exit_code = cc.main(
        [
            "--run", "run-1",
            "--event", "terminal",
            "--surface", "surface:33",
            "--state-root", str(tmp_path / "state"),
        ],
        runner=runner,
    )
    assert exit_code == 0
    assert runner.calls == [["cmux", "trigger-flash", "--surface", "surface:33"]]


def test_main_no_callback_exits_zero_without_invoking_cmux(tmp_path: Path) -> None:
    cc = _import_module()
    runner = cc.MockCommandRunner()
    exit_code = cc.main(
        [
            "--run", "run-1",
            "--event", "terminal",
            "--state-root", str(tmp_path / "state"),
        ],
        runner=runner,
    )
    assert exit_code == 0
    assert runner.calls == []
