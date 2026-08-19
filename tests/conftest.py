"""Test-suite guards.

Guards CL-t71i: on 2026-07-19 the operator's real `~/.config/library/global.lock`
was found to contain an entry written by a pytest run on 2026-07-17, whose source
and install target both pointed into a long-deleted pytest tmpdir. The test had
isolated itself with `monkeypatch.setenv("HOME", tmp_path)`, but the global
lockfile path was a module-level constant frozen at import, so the isolation
never took effect.

The lazy resolution in `lib.lockfile` fixes the cause. This fixture is the
backstop: if any future test writes to the operator's real library state, the run
fails and names the file, instead of the damage surfacing months later as a vague
`skipped 1 entries with unknown upstream status` warning during `library sync`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

OPERATOR_HOME = Path.home()
REAL_GLOBAL_LOCKFILE = OPERATOR_HOME / ".config" / "library" / "global.lock"
REAL_MODEL_STANDARDS = OPERATOR_HOME / ".agents" / "model-standards"


def harness_cli_checkout() -> Path:
    """Return the operator harness-cli checkout, ignoring the isolated test HOME."""
    env = os.environ.get("HARNESS_CLI_SOURCE")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(OPERATOR_HOME / "code" / "library" / "harness-cli")
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(
        "harness-cli checkout required; set HARNESS_CLI_SOURCE or keep "
        f"{OPERATOR_HOME / 'code' / 'library' / 'harness-cli'}"
    )


@pytest.fixture
def harness_cli_source() -> Path:
    return harness_cli_checkout()


def _fingerprint(path: Path) -> str | None:
    """Return a content hash, or None when the file does not exist."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@pytest.fixture(autouse=True, scope="session")
def operator_library_state_is_read_only(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Isolate global state and fail if the operator lockfile changes."""
    before = _fingerprint(REAL_GLOBAL_LOCKFILE)
    isolated_home = tmp_path_factory.mktemp("library-test-home")
    original_environment = {
        name: os.environ.get(name)
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "MODEL_STANDARDS_DIR")
    }
    os.environ["HOME"] = str(isolated_home)
    os.environ["XDG_CONFIG_HOME"] = str(isolated_home / ".config")
    os.environ["XDG_DATA_HOME"] = str(isolated_home / ".local" / "share")
    os.environ["MODEL_STANDARDS_DIR"] = str(REAL_MODEL_STANDARDS)
    try:
        yield
    finally:
        for name, value in original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        after = _fingerprint(REAL_GLOBAL_LOCKFILE)
        if before != after:
            pytest.fail(
                f"The test suite modified {REAL_GLOBAL_LOCKFILE}. Tests must never "
                "write to the operator's real library state. A global-scope install "
                "in a test needs its HOME isolated *and* a lockfile path that is "
                "resolved at call time (see lib.lockfile._global_lockfile_path).",
                pytrace=False,
            )
