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

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from checks.provider_neutrality import (  # noqa: E402
    BASELINE_PATH,
    CORE_MODULES,
    Finding,
    fingerprint_counts,
    load_baseline,
    scan_legacy,
    scan_paths,
    scan_repository,
    scan_source,
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
    assert {finding.kind for finding in findings} == {
        "provider-name",
        "provider-host-literal",
    }
    assert {finding.token for finding in findings} == {"github", "github.com"}


def test_check_fails_on_a_provider_name_inside_an_identifier(tmp_path: Path) -> None:
    """`resolve_github_url` is provider knowledge with or without a literal."""
    findings = _findings_for(
        tmp_path, "def _resolve_github_repo_url(base):\n    return base\n"
    )
    assert [finding.kind for finding in findings] == ["provider-name"]
    assert "identifier" in findings[0].excerpt


def test_check_fails_on_a_legacy_distribution_type_branch(tmp_path: Path) -> None:
    """A branch on the legacy `type` value is a provider-kind branch renamed."""
    findings = _findings_for(
        tmp_path,
        'def plan(entry):\n'
        '    if entry["type"] != "git":\n'
        '        raise ValueError("unsupported")\n'
        '    return entry\n',
    )
    assert [finding.kind for finding in findings] == ["provider-kind-conditional"]
    assert findings[0].token == "git"


def test_check_does_not_flag_the_word_git_in_prose(tmp_path: Path) -> None:
    """Only a whole-literal match counts, or the check becomes background noise."""
    findings = _findings_for(
        tmp_path,
        '# run git rev-parse to resolve the head\n'
        'COMMAND = ["git", "rev-parse", "HEAD"]\n',
    )
    # The list element is still a whole literal and is reported; the comment is not.
    assert [finding.line for finding in findings] == [2]


def test_check_fails_on_an_unlisted_provider_host(tmp_path: Path) -> None:
    """No allowlist of provider names can be complete; hostnames are structural."""
    for literal in ("sources.example-forge.io", "forge.example.de", "git.example.eu"):
        findings = _findings_for(tmp_path, f'HOST = "{literal}"\n')
        assert [finding.kind for finding in findings] == ["provider-host-literal"], literal


def test_check_sees_inside_an_f_string(tmp_path: Path) -> None:
    """PEP 701 tokenizes f-strings apart, and a token-only scan would miss them.

    Building an upstream URL with an f-string is the most idiomatic way to write
    the exact leak this check exists to stop, so it must be caught on every
    supported Python version.
    """
    findings = _findings_for(
        tmp_path,
        "def url(owner, repo):\n"
        '    return f"https://github.com/{owner}/{repo}"\n',
    )
    kinds = {finding.kind for finding in findings}
    assert {"provider-name", "upstream-url", "provider-host-literal"} <= kinds


def test_check_sees_a_provider_kind_identifier_in_any_casing(tmp_path: Path) -> None:
    findings = _findings_for(
        tmp_path,
        "def plan(entry, PROVIDER_KIND):\n"
        "    return entry == PROVIDER_KIND\n",
    )
    assert findings
    assert {finding.kind for finding in findings} == {"provider-kind-conditional"}
    assert {finding.token for finding in findings} == {"PROVIDER_KIND"}


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
    (dirty_root / BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (dirty_root / BASELINE_PATH).write_text(
        json.dumps({"schema": "cognovis.provider-neutrality-baseline.v1", "modules": {}})
    )
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


def test_legacy_provider_modules_are_measured_against_a_ratchet() -> None:
    """The pre-ADR-0011 resolution path is measured and may not get worse.

    A gate that certifies only three modules, while the module that actually
    resolves a marketplace today is full of provider knowledge, would read as a
    stronger claim than it is. The legacy baseline makes that state visible and
    stops it growing.
    """
    baseline = load_baseline(REPO_ROOT)
    # Slice 6 (`CL-mvet`) drove `scripts/lib/source.py` to zero by moving its
    # hosting-service knowledge into `providers/git_url.py`, which is the remedy
    # this check's own report names. It is therefore absent from the baseline,
    # and that absence is asserted rather than merely tolerated: a module
    # dropping out because it was cleaned and a module dropping out because the
    # measurement stopped seeing it look identical from here otherwise.
    assert "scripts/lib/source.py" not in baseline
    assert not scan_source(
        "scripts/lib/source.py", (REPO_ROOT / "scripts/lib/source.py").read_text()
    )
    assert baseline, "the legacy set is drawn down, not declared empty"

    statuses = scan_legacy(REPO_ROOT)
    assert statuses, "the legacy set must not be silently empty"
    for status in statuses:
        assert not status.regressed, (
            f"{status.path} gained provider knowledge: {status.new_fingerprints}"
        )
        # The baseline is measured, not a ceiling parked above reality.
        assert not status.improved, (
            f"{status.path} improved ({status.removed_fingerprints}); "
            "rerun with --update-baseline"
        )


def test_provider_adapters_are_not_measured_as_legacy_debt() -> None:
    """Provider knowledge belongs in adapters; recording it as debt is wrong."""
    baseline = load_baseline(REPO_ROOT)
    assert not [path for path in baseline if path.startswith("scripts/lib/providers/")]


def test_the_ratchet_compares_finding_identities_not_counts(tmp_path: Path) -> None:
    """Removing an old leak must not buy room for a new one.

    A counted ratchet passes when a module drops one finding and gains a
    different one, which lets the active resolver acquire a brand-new provider
    branch while CI stays green.
    """
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    legacy = repo / "scripts" / "lib" / "legacy.py"

    legacy.write_text('BASE = "https://github.com/x"\n')
    baseline = {"scripts/lib/legacy.py": fingerprint_counts(scan_paths([legacy]))}
    held = scan_legacy(repo, baseline)
    assert [status.regressed for status in held] == [False]

    # One finding removed, a different one added: the total is unchanged.
    legacy.write_text('KIND = "git-org"\n')
    swapped = scan_legacy(repo, baseline)
    assert swapped[0].regressed is True
    assert "provider-kind-conditional:git-org" in swapped[0].new_fingerprints


def test_a_missing_baseline_fails_the_check(tmp_path: Path) -> None:
    """A gate whose baseline can vanish is a gate that can be deleted."""
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path)


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
    # The artifact states the limit of its own claim, both in prose and in data.
    assert "not a claim about every module" in payload["scope_note"]
    legacy = {entry["path"]: entry for entry in payload["legacy_provider_modules"]}
    assert legacy, "the artifact reports the legacy set, not just the clean core"
    assert all(entry["state"] == "held" for entry in legacy.values())
    assert all(entry["new_fingerprints"] == {} for entry in legacy.values())
    assert "scripts/lib/source.py" not in legacy
    assert "not a claim about every module" in result.stdout


def test_check_fails_loudly_when_a_scanned_module_is_missing(tmp_path: Path) -> None:
    """A deleted or renamed core module must not silently pass the gate."""
    with pytest.raises(FileNotFoundError):
        scan_repository(tmp_path)
