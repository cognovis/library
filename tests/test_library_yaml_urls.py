"""Network-gated liveness checks for source URLs in library.yaml."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PATH = REPO_ROOT / "library.yaml"


network_test = pytest.mark.skipif(
    os.environ.get("NETWORK_TESTS") != "1",
    reason="Set NETWORK_TESTS=1 to verify library.yaml source URLs against GitHub.",
)


@dataclass(frozen=True)
class GithubTarget:
    source: str
    endpoint: str
    locations: tuple[str, ...]


def _source_values(node: object) -> dict[str, list[str]]:
    """Return source-like URL values from library.yaml with their YAML locations."""
    values: dict[str, list[str]] = {}
    _collect_source_values(node, (), values)
    return values


def _collect_source_values(
    node: object,
    path: tuple[str, ...],
    values: dict[str, list[str]],
) -> None:
    """Populate source URL locations while walking nested YAML data."""
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = path + (str(key),)
            if key == "source" and isinstance(value, str):
                values.setdefault(value, []).append(".".join(child_path))
            elif key == "sources" and isinstance(value, dict):
                for source_key, source_value in value.items():
                    if isinstance(source_value, str):
                        source_path = child_path + (str(source_key),)
                        values.setdefault(source_value, []).append(".".join(source_path))
            _collect_source_values(value, child_path, values)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _collect_source_values(value, path + (str(index),), values)


def _github_endpoint(source: str) -> str | None:
    """Convert a GitHub URL into the GitHub API endpoint that proves it exists."""
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "github.com":
        return None

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) == 1:
        return f"users/{parts[0]}"
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1].removesuffix(".git")
    if len(parts) == 2:
        return f"repos/{owner}/{repo}"

    if len(parts) >= 5 and parts[2] in {"blob", "tree"}:
        ref = quote(parts[3], safe="")
        path = quote("/".join(parts[4:]), safe="/")
        return f"repos/{owner}/{repo}/contents/{path}?ref={ref}"

    return None


def _github_targets() -> tuple[list[GithubTarget], list[tuple[str, list[str]]]]:
    """Return verifiable GitHub targets and unsupported GitHub URL shapes."""
    data = yaml.safe_load(LIBRARY_PATH.read_text())
    targets: list[GithubTarget] = []
    unsupported: list[tuple[str, list[str]]] = []
    for source, locations in sorted(_source_values(data).items()):
        if not source.startswith("https://github.com/"):
            continue
        endpoint = _github_endpoint(source)
        if endpoint is None:
            unsupported.append((source, locations))
        else:
            targets.append(
                GithubTarget(
                    source=source,
                    endpoint=endpoint,
                    locations=tuple(locations),
                )
            )
    return targets, unsupported


def _run_gh_api(
    endpoint: str,
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], object] = time.sleep,
) -> subprocess.CompletedProcess[str]:
    """Run a GitHub API probe, retrying only transient server failures."""
    for attempt in range(max_attempts):
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
        )
        detail = result.stderr.strip() or result.stdout.strip()
        is_server_error = re.search(r"\bHTTP 5\d{2}\b", detail) is not None
        if result.returncode == 0 or not is_server_error or attempt == max_attempts - 1:
            return result
        sleep(float(2**attempt))

    raise AssertionError("max_attempts must be positive")


@network_test
def test_github_source_urls_are_live() -> None:
    """Every GitHub source URL in library.yaml resolves through the GitHub API."""
    if shutil.which("gh") is None:
        pytest.fail("NETWORK_TESTS=1 requires the GitHub CLI (`gh`) on PATH.")

    targets, unsupported = _github_targets()
    assert not unsupported, "Unsupported GitHub source URL shape(s):\n" + "\n".join(
        f"{source} at {', '.join(locations)}" for source, locations in unsupported
    )

    failures: list[str] = []
    for target in targets:
        result = _run_gh_api(target.endpoint)
        if result.returncode != 0:
            failures.append(
                f"{target.source} at {', '.join(target.locations)}\n"
                f"  gh api {target.endpoint}\n"
                f"  {result.stderr.strip() or result.stdout.strip()}"
            )

    assert not failures, "Dead library.yaml GitHub source URL(s):\n" + "\n".join(failures)


# Regression guard for CL-fxeb: transient GitHub server errors must not make the
# scheduled source-liveness workflow fail on the first attempt.
def test_regression_transient_github_5xx_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            subprocess.CompletedProcess(
                ["gh", "api", "repos/example/catalog"],
                1,
                stderr="gh: HTTP 502",
            ),
            subprocess.CompletedProcess(
                ["gh", "api", "repos/example/catalog"],
                0,
                stdout="{}",
                stderr="",
            ),
        ]
    )
    calls: list[list[str]] = []
    delays: list[float] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return next(results)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_gh_api(
        "repos/example/catalog",
        sleep=delays.append,
    )

    assert result.returncode == 0
    assert calls == [
        ["gh", "api", "repos/example/catalog"],
        ["gh", "api", "repos/example/catalog"],
    ]
    assert delays == [1.0]


# Regression guard for CL-fxeb: permanent missing sources must still fail fast.
def test_regression_permanent_github_4xx_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="gh: Not Found (HTTP 404)",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_gh_api("repos/example/missing", sleep=lambda _: None)

    assert result.returncode == 1
    assert calls == [["gh", "api", "repos/example/missing"]]


def test_github_5xx_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    delays: list[float] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="gh: Service Unavailable (HTTP 503)",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _run_gh_api("repos/example/unavailable", sleep=delays.append)

    assert result.returncode == 1
    assert len(calls) == 3
    assert delays == [1.0, 2.0]
