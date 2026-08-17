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


def _catalog() -> dict:
    return yaml.safe_load((REPO_ROOT / "library.yaml").read_text(encoding="utf-8"))


def _entry(catalog: dict, kind: str, name: str) -> dict:
    return next(entry for entry in catalog["library"][kind] if entry["name"] == name)


def _source_catalog(catalog: dict, name: str) -> dict:
    return next(
        entry
        for entry in catalog["sources"]["catalogs"]
        if entry["name"] == name
    )


def _ccore_root() -> Path:
    """Return the registered ccore checkout.

    The path comes from the catalog's own source registry rather than a sibling
    guess, because `ccore` is an independent distribution and never sits beside
    this repository.
    """
    override = os.environ.get("COGNOVIS_CCORE")
    if override:
        return Path(override).expanduser()
    return Path(
        str(_source_catalog(_catalog(), "cognovis-ccore")["local_path"])
    ).expanduser()


CCORE_ROOT = _ccore_root()
SKILL_PREFIX = "skills/acpx-dispatch"
ACPX_SOURCE = CCORE_ROOT / SKILL_PREFIX


def _ccore_tree_at(commit: str) -> dict[str, bytes]:
    """Return the dispatch skill tree at `commit`, read from the ccore object store.

    Reading the recorded commit rather than the working tree ties the assertion to
    the receipt the installer wrote, so a checkout that is dirty or ahead of the
    installed revision does not turn into a spurious content mismatch.
    """
    listing = subprocess.run(
        ["git", "-C", str(CCORE_ROOT), "ls-tree", "-r", "--name-only", commit, "--", SKILL_PREFIX],
        capture_output=True,
        text=True,
        check=True,
    )
    tree: dict[str, bytes] = {}
    for path in listing.stdout.split():
        blob = subprocess.run(
            ["git", "-C", str(CCORE_ROOT), "show", f"{commit}:{path}"],
            capture_output=True,
            check=True,
        )
        tree[path[len(SKILL_PREFIX) :].lstrip("/")] = blob.stdout
    return tree


def _installed_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _last_json(stdout: str) -> dict:
    """Return the final JSON object the CLI emitted.

    A dependency-bearing install reports one object per installed member, so the
    root result is the last one rather than the whole stream.
    """
    decoder = json.JSONDecoder()
    payload: dict = {}
    index = 0
    while index < len(stdout):
        if stdout[index].isspace():
            index += 1
            continue
        payload, offset = decoder.raw_decode(stdout, index)
        index = offset
    return payload


def _lockfile(project: Path) -> dict:
    return yaml.safe_load((project / ".library.lock").read_text(encoding="utf-8"))


def _requested_root(lock: dict, entry_id: str) -> dict:
    return next(item for item in lock["requested_roots"] if item.get("id") == entry_id)


def _receipt(lock: dict, name: str, primitive: str) -> dict:
    return next(
        item
        for item in lock["receipts"]
        if item.get("name") == name and item.get("type") == primitive
    )


# clc-i19u: `ccore` owns the dispatch skill together with the transport command it
# documents, so the catalog must both register that repository as a skills source
# and serve the entry from it. A second copy in cognovis-core would drift.
def test_catalog_registers_ccore_as_a_skills_source() -> None:
    ccore = _source_catalog(_catalog(), "cognovis-ccore")

    assert ccore["source"] == "https://github.com/cognovis/ccore"
    assert ccore["local_path"] == "/Users/malte/code/ccore"
    assert "skills" in ccore["content_types"]
    assert "acpx" in ccore["scope"]["topics"]
    assert "dispatch" in ccore["scope"]["topics"]


def test_catalog_resolves_repository_delivery_through_the_owned_transport(
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    dispatch = _entry(catalog, "skills", "acpx-dispatch")
    pack = _entry(catalog, "skills", "executive-pack")
    loop = _entry(catalog, "skills", "bead-execution-loop")

    assert dispatch["source"] == (
        "https://github.com/cognovis/ccore/blob/main/"
        "skills/acpx-dispatch/SKILL.md"
    )
    assert dispatch["metadata"]["library"]["source_catalog"] == "cognovis-ccore"
    assert "skill:bead-execution-loop" in pack["requires"]
    assert "agent:bead-implementer" in loop["requires"]
    # clc-i19u: the entry's dependency edges are the ccore skill's own declared
    # contract, which `library catalog sync --source=cognovis-ccore` derives from
    # its `requires_standards`. The judge-layer and routing edges the entry used to
    # carry were never declared by the skill; they inflated every consumer's
    # closure and made an install of the transport skill build a judge agent.
    assert dispatch["requires"] == ["standard:mcp-client-timeout"]
    install_order = resolve_requires(
        catalog,
        "skill",
        "executive-pack",
        tmp_path,
    )
    assert ("skill", "bead-execution-loop") in install_order
    assert ("skill", "acpx-dispatch") in install_order


@pytest.mark.skipif(
    not ACPX_SOURCE.is_dir(),
    reason="registered ccore checkout is not available",
)
def test_catalog_backed_cli_install_vendors_the_policy_only_skill(
    tmp_path: Path,
) -> None:
    """A fresh consumer installs the committed entry as published, with no fixups.

    The previous version of this test replaced the entry's source with a local
    path and cleared its `requires`, which is exactly the state that hid a broken
    published entry: the real install resolved a dependency closure the skill never
    declared and exited non-zero while building an unrelated judge agent. Copying
    `library.yaml` verbatim is the point of the test.
    """
    project = tmp_path / "consumer"
    project.mkdir()
    (project / "library.yaml").write_bytes((REPO_ROOT / "library.yaml").read_bytes())
    # A project-scope install is refused outside a Git worktree top-level.
    subprocess.run(
        ["git", "init", "--quiet", str(project)],
        capture_output=True,
        text=True,
        check=True,
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
    assert _last_json(install.stdout)["status"] == "ok"

    lock = _lockfile(project)
    root = _requested_root(lock, "skill:acpx-dispatch")
    receipt = _receipt(lock, "acpx-dispatch", "skill")
    definition_commit = root["definition_commit"]

    assert receipt["source"] == (
        "https://github.com/cognovis/ccore/blob/main/skills/acpx-dispatch/SKILL.md"
    )
    assert receipt["source_commit"] == definition_commit
    assert len(definition_commit) == 40
    # The receipt must name a revision that exists in ccore, not an opaque marker.
    subprocess.run(
        ["git", "-C", str(CCORE_ROOT), "cat-file", "-e", f"{definition_commit}^{{commit}}"],
        capture_output=True,
        check=True,
    )

    installed = project / ".agents" / "skills" / "acpx-dispatch"
    # clc-i19u: the transport is the installed `ccore acpx` command, so the skill
    # is prose end to end. An installed copy that carries an executable surface
    # is a second transport, which is exactly what the move to `ccore` removed.
    assert not (installed / "scripts").exists()
    assert _installed_tree(installed) == _ccore_tree_at(definition_commit)
