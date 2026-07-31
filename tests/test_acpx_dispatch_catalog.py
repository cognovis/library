"""Catalog and installer contract for the owned ACPX dispatcher skill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.resolver import resolve_requires  # noqa: E402

COGNOVIS_CORE = (
    Path(os.environ["COGNOVIS_CORE"]).expanduser()
    if os.environ.get("COGNOVIS_CORE")
    else REPO_ROOT.parent / "cognovis-core"
)
ACPX_SOURCE = COGNOVIS_CORE / "skills" / "acpx-dispatch"


def _catalog() -> dict:
    return yaml.safe_load((REPO_ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def test_catalog_resolves_loop_to_owned_dispatcher_bundle(tmp_path: Path) -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "acpx-dispatch")
    loop = _entry(catalog, "skills", "bead-implementation-loop")

    assert dispatch["source"] == (
        "https://github.com/cognovis/library-core/blob/main/"
        "skills/acpx-dispatch/SKILL.md"
    )
    assert loop["requires"][0] == "skill:acpx-dispatch"
    assert dispatch["requires"] == [
        "agent:judge-default",
        "standard:english-only",
        "standard:judge-layer",
        "standard:model-routing",
        "standard:no-emoji",
    ]
    assert [script["path"] for script in dispatch["scripts"]] == [
        "skills/acpx-dispatch/scripts/acpx-dispatch.py",
        "skills/acpx-dispatch/scripts/dispatch_state.py",
        "skills/acpx-dispatch/scripts/review_contract.py",
    ]
    install_order = resolve_requires(
        catalog,
        "skill",
        "bead-implementation-loop",
        tmp_path,
    )
    assert ("skill", "acpx-dispatch") in install_order


@pytest.mark.skipif(
    not ACPX_SOURCE.is_dir(),
    reason="cognovis-core sibling checkout is not available",
)
def test_catalog_backed_cli_install_vendors_runnable_dispatcher(
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "acpx-dispatch")
    dispatch["source"] = str(ACPX_SOURCE / "SKILL.md")
    dispatch["requires"] = []

    project = tmp_path / "consumer"
    project.mkdir()
    (project / "library.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False),
        encoding="utf-8",
    )
    isolated_home = tmp_path / "home"
    environment = {
        **os.environ,
        "HOME": str(isolated_home),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    install = subprocess.run(
        [
            sys.executable,
            str(LIBRARY_PY),
            "skill",
            "use",
            "acpx-dispatch",
            "--json",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr or install.stdout
    assert json.loads(install.stdout)["status"] == "ok"
    installed = project / ".agents" / "skills" / "acpx-dispatch"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "scripts" / "dispatch_state.py").is_file()
    assert (installed / "scripts" / "review_contract.py").is_file()

    capabilities = subprocess.run(
        [
            sys.executable,
            str(installed / "scripts" / "acpx-dispatch.py"),
            "--print-capabilities",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert capabilities.returncode == 0, capabilities.stderr
    payload = json.loads(capabilities.stdout)
    assert payload["interface_version"] == 2
    assert "review-subject-v1" in payload["capabilities"]
