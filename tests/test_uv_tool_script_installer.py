from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import lockfile  # noqa: E402
from lib.installers import uv_tool  # noqa: E402


def _catalog(source: Path) -> dict:
    return {
        "catalog": {
            "name": "test-catalog",
            "source": "https://github.com/example/catalog",
        },
        "library": {
            "scripts": [
                {
                    "name": "ccore",
                    "description": "Cognovis developer workflow CLI.",
                    "source": str(source),
                    "language": "python",
                    "output_contract": "json-envelope",
                    "default_scope": "global",
                    "distribution": {
                        "kind": "uv-tool",
                        "package_name": "cognovis-core-tools",
                        "executables": ["ccore"],
                    },
                }
            ]
        },
    }


def _package(root: Path) -> Path:
    package = root / "ccore"
    package.mkdir()
    (package / "pyproject.toml").write_text(
        """
[project]
name = "cognovis-core-tools"
version = "1.0.0"
requires-python = ">=3.12"

[project.scripts]
ccore = "ccore.cli:main"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return package


def test_uv_tool_script_dry_run_plans_install_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(uv_tool, "_uv_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(
        uv_tool, "compute_cache_path", lambda *_: tmp_path / "cache" / "ccore"
    )

    result = uv_tool.install_uv_tool(
        catalog=_catalog(package),
        name="ccore",
        repo_root=tmp_path,
        scope="global",
        dry_run=True,
    )

    assert result["status"] == "dry-run"
    assert [operation["operation"] for operation in result["operations"]] == [
        "materialize_cache",
        "uv_tool_install",
        "write_lockfile",
    ]
    assert not bin_dir.exists()


def test_uv_tool_script_installs_all_declared_executables_and_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    bin_dir = tmp_path / "bin"
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setattr(
        lockfile, "GLOBAL_LOCKFILE", config_home / "library" / "global.lock"
    )
    monkeypatch.setattr(uv_tool, "_uv_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(
        uv_tool, "compute_cache_path", lambda *_: tmp_path / "cache" / "ccore"
    )

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 1, "", "not a repository")
        calls.append(argv)
        if argv[:3] == ["uv", "tool", "install"]:
            bin_dir.mkdir(parents=True)
            for executable in ("ccore",):
                target = bin_dir / executable
                target.write_text("#!/bin/sh\n", encoding="utf-8")
                target.chmod(0o755)
            return subprocess.CompletedProcess(argv, 0, "installed\n", "")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(uv_tool.subprocess, "run", fake_run)

    result = uv_tool.install_uv_tool(
        catalog=_catalog(package),
        name="ccore",
        repo_root=tmp_path,
        scope="global",
    )

    assert result["status"] == "ok"
    assert calls == [["uv", "tool", "install", "--force", result["data"]["cache"]]]
    assert result["data"]["executables"] == [str(bin_dir / "ccore")]
    lock = lockfile.load_lockfile(config_home / "library" / "global.lock")
    receipt = next(item for item in lock["receipts"] if item["name"] == "ccore")
    assert receipt["type"] == "script"
    assert receipt["install_target"] == str(bin_dir / "ccore")
    assert receipt["checksum_type"] == "directory"
    assert receipt["scope"] == "global"


def test_uv_tool_script_rejects_project_scope_before_install(tmp_path: Path) -> None:
    package = _package(tmp_path)

    with pytest.raises(Exception, match="global scope"):
        uv_tool.install_uv_tool(
            catalog=_catalog(package),
            name="ccore",
            repo_root=tmp_path,
            scope="project",
        )


def test_uv_tool_script_remove_uninstalls_distribution_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    config_home = tmp_path / "config"
    lock_path = config_home / "library" / "global.lock"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setattr(lockfile, "GLOBAL_LOCKFILE", lock_path)
    receipt = lockfile.make_entry(
        name="ccore",
        primitive_type="script",
        catalog_identity="test-catalog",
        marketplace="test",
        source=str(package),
        source_commit="abc123",
        cache_path=str(tmp_path / "cache"),
        install_target=str(tmp_path / "bin" / "ccore"),
        checksum_sha256="abc123",
        scope="global",
    )
    state = lockfile.load_lockfile(lock_path)
    lockfile.upsert_entry(state, receipt)
    lockfile.save_lockfile(lock_path, state)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "uninstalled\n", "")

    monkeypatch.setattr(uv_tool.subprocess, "run", fake_run)

    result = uv_tool.remove_uv_tool(
        catalog=_catalog(package), name="ccore", repo_root=tmp_path, scope="global"
    )

    assert result["status"] == "ok"
    assert calls == [["uv", "tool", "uninstall", "cognovis-core-tools"]]
    state = lockfile.load_lockfile(lock_path)
    assert all(item.get("id") != "script:ccore" for item in state["receipts"])


def test_uv_tool_install_timeout_is_reported_as_install_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(uv_tool, "_uv_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(
        uv_tool, "compute_cache_path", lambda *_: tmp_path / "cache" / "ccore"
    )

    def timeout(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(argv, 1, "", "not a repository")
        raise subprocess.TimeoutExpired(argv, uv_tool.UV_TIMEOUT_SECONDS)

    monkeypatch.setattr(uv_tool.subprocess, "run", timeout)

    with pytest.raises(Exception, match="uv command timed out"):
        uv_tool.install_uv_tool(
            catalog=_catalog(package), name="ccore", repo_root=tmp_path, scope="global"
        )
