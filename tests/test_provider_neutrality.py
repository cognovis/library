"""Mechanical proof that core carries no provider knowledge (CL-coif AC4).

ADR-0011 `Source Provider Contract`: the resolver, cache, and Workspace layers
consume the capability contract only and must contain **no provider-specific
branch**. AC4 makes that a CI check rather than a review convention, because
"the first awkward provider tempts a branch in core" is the named pre-mortem
risk of this bead.

Both directions are tested. A check that only ever passes proves nothing, so
each violation class is also shown to fail the check with a non-zero exit code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from checks.provider_neutrality import (  # noqa: E402
    CORE_MODULES,
    Finding,
    scan_paths,
    scan_repository,
)

CHECK_SCRIPT = REPO_ROOT / "scripts" / "checks" / "provider_neutrality.py"


def test_no_provider_names_in_core() -> None:
    """The live core modules are free of provider names, kinds, and URLs."""
    findings = scan_repository(REPO_ROOT)
    assert findings == [], "\n".join(finding.render() for finding in findings)


def test_the_check_covers_the_resolver_cache_and_workspace_modules() -> None:
    """The scanned set is the one ADR-0011 names, and every file exists."""
    covered = {Path(path).name for path in CORE_MODULES}
    assert {"resolver.py", "cache.py", "workspace.py"} <= covered
    for relative in CORE_MODULES:
        assert (REPO_ROOT / relative).is_file(), relative


def _findings_for(tmp_path: Path, source: str) -> list[Finding]:
    module = tmp_path / "core_module.py"
    module.write_text(source)
    return scan_paths([module])


def test_check_fails_on_a_provider_name(tmp_path: Path) -> None:
    findings = _findings_for(
        tmp_path,
        'def resolve(url):\n    if "github.com" in url:\n        return "special"\n',
    )
    assert [finding.kind for finding in findings] == ["provider-name", "upstream-url"] or (
        "provider-name" in {finding.kind for finding in findings}
    )


def test_check_fails_on_a_provider_name_in_a_comment(tmp_path: Path) -> None:
    """A comment claiming provider knowledge is the drift signal, not noise."""
    findings = _findings_for(tmp_path, "# Layer A source: a GitHub URL or a local path\nX = 1\n")
    assert [finding.kind for finding in findings] == ["provider-name"]


def test_check_fails_on_a_provider_kind_conditional(tmp_path: Path) -> None:
    findings = _findings_for(
        tmp_path,
        'def plan(entry):\n'
        '    if entry["provider_kind"] == "git-org":\n'
        '        return "allowlist"\n'
        '    return "default"\n',
    )
    kinds = {finding.kind for finding in findings}
    assert "provider-kind-conditional" in kinds


def test_check_fails_on_a_provider_kind_conditional_through_a_variable(
    tmp_path: Path,
) -> None:
    """The identifier is enough; the literal does not have to be present."""
    findings = _findings_for(
        tmp_path,
        "def plan(entry, expected):\n"
        "    if entry.provider_kind == expected:\n"
        "        return True\n"
        "    return False\n",
    )
    assert [finding.kind for finding in findings] == ["provider-kind-conditional"]


def test_check_fails_on_an_upstream_url(tmp_path: Path) -> None:
    findings = _findings_for(
        tmp_path, 'BASE = "https://example.invalid/org/repo"\n'
    )
    assert [finding.kind for finding in findings] == ["upstream-url"]


def test_check_accepts_provider_neutral_core(tmp_path: Path) -> None:
    """Normalized-inventory vocabulary is not a false positive."""
    findings = _findings_for(
        tmp_path,
        "def plan(item):\n"
        "    identity = item.qualified_identity()\n"
        "    if item.cache_state == 'verified':\n"
        "        return identity\n"
        "    return None\n",
    )
    assert findings == []


def test_check_exits_non_zero_when_a_violation_is_introduced(tmp_path: Path) -> None:
    """The CI entry point fails the build, not just the library function."""
    clean = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr

    dirty_root = tmp_path / "repo"
    (dirty_root / "scripts" / "lib").mkdir(parents=True)
    for relative in CORE_MODULES:
        target = dirty_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / relative).read_text())
    injected = dirty_root / CORE_MODULES[0]
    injected.write_text(
        injected.read_text()
        + '\n\ndef _special_case(entry):\n'
        '    if entry.get("provider_kind") == "git-repo":\n'
        '        return "https://github.com/mattpocock/skills"\n'
        '    return None\n'
    )

    dirty = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--repo-root", str(dirty_root)],
        capture_output=True,
        text=True,
    )
    assert dirty.returncode == 1
    assert "provider-kind-conditional" in dirty.stdout
    assert "provider-name" in dirty.stdout
    assert "upstream-url" in dirty.stdout


def test_check_writes_a_typed_artifact(tmp_path: Path) -> None:
    import json

    output = tmp_path / "provider-neutrality.json"
    result = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text())
    assert payload["schema"] == "cognovis.provider-neutrality.v1"
    assert payload["bead_id"] == "CL-coif"
    assert payload["result"] == "pass"
    assert payload["findings"] == []
    assert sorted(payload["scanned"]) == sorted(CORE_MODULES)


def test_check_fails_loudly_when_a_scanned_module_is_missing(tmp_path: Path) -> None:
    """A deleted or renamed core module must not silently pass the gate."""
    with pytest.raises(FileNotFoundError):
        scan_repository(tmp_path)
