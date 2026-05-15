"""Network-gated liveness checks for source URLs in library.yaml."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PATH = REPO_ROOT / "library.yaml"


pytestmark = pytest.mark.skipif(
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
        result = subprocess.run(
            ["gh", "api", target.endpoint],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            failures.append(
                f"{target.source} at {', '.join(target.locations)}\n"
                f"  gh api {target.endpoint}\n"
                f"  {result.stderr.strip() or result.stdout.strip()}"
            )

    assert not failures, "Dead library.yaml GitHub source URL(s):\n" + "\n".join(failures)
