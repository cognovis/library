"""A network failure must not be reported as a missing artefact.

Guards CL-rnus. `tests/test_personal_migration.py` asserts the published state of
`sussdorff/library-core` through `gh api`, and treated every non-zero exit as
"file missing". On 2026-07-20 a full-suite run failed on
`skills/ai-readiness/SKILL.md`; an immediate re-run of the same class passed 13/13
with nothing changed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "migration_under_test", REPO_ROOT / "tests" / "test_personal_migration.py"
)
migration = importlib.util.module_from_spec(_spec)
sys.modules["migration_under_test"] = migration
_spec.loader.exec_module(migration)


# -- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Not Found (HTTP 404)",
        "HTTP 404: Not Found (https://api.github.com/repos/x/y/contents/z)",
        "not found",
    ],
)
def test_missing_artefact_is_classified_absent(stderr: str):
    assert migration.classify_gh_failure(stderr) == "absent"


@pytest.mark.parametrize(
    "stderr",
    [
        "API rate limit exceeded for user ID 1234",
        "gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable",
        "dial tcp: lookup api.github.com: no such host",
        "HTTP 401: Bad credentials",
        "HTTP 503: Service Unavailable",
        "",
    ],
)
def test_transient_or_setup_failures_are_classified_unavailable(stderr: str):
    assert migration.classify_gh_failure(stderr) == "unavailable"


# -- gh_api behaviour --------------------------------------------------------


def _stub_run(monkeypatch, *, returncode: int, stderr: str = "", stdout: str = ""):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(migration.subprocess, "run", fake_run)


def test_absent_artefact_still_fails_and_names_the_path(monkeypatch):
    """A genuine 404 must stay a failure, or the test stops being a check."""
    _stub_run(monkeypatch, returncode=1, stderr="gh: Not Found (HTTP 404)")

    with pytest.raises(FileNotFoundError) as exc:
        migration.gh_api("skills/gone/SKILL.md")

    assert "skills/gone/SKILL.md" in str(exc.value)
    assert "absent" in str(exc.value)


def test_rate_limit_skips_with_the_reason(monkeypatch):
    _stub_run(monkeypatch, returncode=1, stderr="API rate limit exceeded for user ID 1234")

    with pytest.raises(pytest.skip.Exception) as exc:
        migration.gh_api("skills/x/SKILL.md")

    assert "rate limit" in str(exc.value).lower()
    assert "skills/x/SKILL.md" in str(exc.value)


def test_missing_credentials_skips(monkeypatch):
    _stub_run(monkeypatch, returncode=1, stderr="HTTP 401: Bad credentials")

    with pytest.raises(pytest.skip.Exception) as exc:
        migration.gh_api("skills/x/SKILL.md")

    assert "Bad credentials" in str(exc.value)


def test_missing_gh_binary_skips(monkeypatch):
    def raise_oserror(argv, **kwargs):
        raise OSError("No such file or directory: 'gh'")

    monkeypatch.setattr(migration.subprocess, "run", raise_oserror)

    with pytest.raises(pytest.skip.Exception) as exc:
        migration.gh_api("skills/x/SKILL.md")

    assert "gh is unavailable" in str(exc.value)


def test_unparsable_output_skips_rather_than_crashing(monkeypatch):
    _stub_run(monkeypatch, returncode=0, stdout="not json")

    with pytest.raises(pytest.skip.Exception) as exc:
        migration.gh_api("skills/x/SKILL.md")

    assert "unparsable" in str(exc.value)


def test_success_returns_the_payload(monkeypatch):
    _stub_run(monkeypatch, returncode=0, stdout='{"type": "file", "size": 42}')

    assert migration.gh_api("skills/x/SKILL.md") == {"type": "file", "size": 42}
