"""An agent that resolves a handler at runtime must ship it, and rot must be visible.

Guards CL-b6oy. The installer has always supported shipping handler assets via an
entry's `handlers:` list, but no catalog entry declared it. Consequences observed
on 2026-07-20:

- `ci-monitor` and `release` were installed and locked with no handler directory,
  while their markdown resolves `$HOME/.claude/agents/<name>-handlers`. Both were
  broken at runtime and nothing said so.
- Installing `acpx-runner` cleared the hand-placed handler directory without
  shipping a replacement, because the declared set was empty.
- Declaring the source directory `<name>-handlers` installed it to
  `<name>-handlers/<name>-handlers`, a path no agent resolves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib.installers.agent import _handler_install_target  # noqa: E402
from lib.sync_audit import _check_missing_agent_handlers  # noqa: E402


# -- the source layout this marketplace actually uses ------------------------


def test_handler_root_in_the_source_path_is_not_doubled():
    """cognovis-core keeps handler sources in agents/<name>-handlers/."""
    target = _handler_install_target(
        Path("/home/u/.claude/agents"), "acpx-runner", Path("acpx-runner-handlers")
    )
    assert target == Path("/home/u/.claude/agents/acpx-runner-handlers")


def test_nested_handler_file_keeps_its_relative_position():
    target = _handler_install_target(
        Path("/home/u/.claude/agents"),
        "acpx-runner",
        Path("acpx-runner-handlers/tests/test_x.py"),
    )
    assert target == Path("/home/u/.claude/agents/acpx-runner-handlers/tests/test_x.py")


def test_flat_source_layout_still_nests_under_the_handler_root():
    """A declaration that does not name the handler root keeps the old behaviour."""
    target = _handler_install_target(
        Path("/home/u/.claude/agents"), "release", Path("release.sh")
    )
    assert target == Path("/home/u/.claude/agents/release-handlers/release.sh")


def test_a_similarly_named_directory_is_not_stripped():
    target = _handler_install_target(
        Path("/home/u/.claude/agents"), "release", Path("release-handlers-extra/x.sh")
    )
    assert target == Path(
        "/home/u/.claude/agents/release-handlers/release-handlers-extra/x.sh"
    )


# -- audit: a declared handler that is not installed -------------------------


CATALOG = {
    "library": {
        "agents": [
            {"name": "needs-handler", "handlers": ["needs-handler-handlers"]},
            {"name": "no-handler"},
        ]
    }
}


def _entry(name: str, install_target: Path) -> dict:
    return {"name": name, "type": "agent", "install_target": str(install_target)}


def test_missing_handler_directory_is_reported(tmp_path: Path):
    agents = tmp_path / "agents"
    agents.mkdir()
    entry = _entry("needs-handler", agents / "needs-handler.md")

    issue = _check_missing_agent_handlers(entry, CATALOG, "global")

    assert issue is not None
    assert str(agents / "needs-handler-handlers") in issue["missing"][0]
    assert "resolves that path at runtime" in issue["repair_hint"]
    assert "library agent use needs-handler --scope global" in issue["repair_hint"]


def test_empty_handler_directory_counts_as_missing(tmp_path: Path):
    agents = tmp_path / "agents"
    (agents / "needs-handler-handlers").mkdir(parents=True)
    entry = _entry("needs-handler", agents / "needs-handler.md")

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is not None


def test_present_handler_directory_is_clean(tmp_path: Path):
    agents = tmp_path / "agents"
    handlers = agents / "needs-handler-handlers"
    handlers.mkdir(parents=True)
    (handlers / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    entry = _entry("needs-handler", agents / "needs-handler.md")

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


def test_agent_without_declared_handlers_is_not_flagged(tmp_path: Path):
    agents = tmp_path / "agents"
    agents.mkdir()
    entry = _entry("no-handler", agents / "no-handler.md")

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


def test_non_agent_entries_are_ignored(tmp_path: Path):
    entry = {"name": "needs-handler", "type": "skill", "install_target": str(tmp_path / "x")}
    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


# -- CL-8a7z: completeness, not merely non-emptiness -------------------------


def _rotted(tmp_path: Path, keep: tuple[str, ...]) -> tuple[dict, Path]:
    """Build an install whose handler dir kept only `keep` plus a leftover."""
    agents = tmp_path / "agents"
    handlers = agents / "needs-handler-handlers"
    handlers.mkdir(parents=True)
    cache = tmp_path / "cache" / "handler-assets" / "needs-handler-handlers"
    cache.mkdir(parents=True)
    for name in ("run.sh", "helper.sh", "lib/util.sh"):
        target = cache / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/sh\n", encoding="utf-8")
    (handlers / "unrelated.txt").write_text("leftover\n", encoding="utf-8")
    for name in keep:
        target = handlers / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/sh\n", encoding="utf-8")
    entry = {
        "name": "needs-handler",
        "type": "agent",
        "install_target": str(agents / "needs-handler.md"),
        "bridge_symlinks": [f"{handlers} -> {cache}"],
    }
    return entry, handlers


def test_a_directory_holding_only_a_leftover_is_reported(tmp_path: Path):
    """The false negative: non-empty is not the same as intact."""
    entry, handlers = _rotted(tmp_path, keep=())

    issue = _check_missing_agent_handlers(entry, CATALOG, "global")

    assert issue is not None
    missing = {Path(p).name for p in issue["missing"]}
    assert missing == {"run.sh", "helper.sh", "util.sh"}
    assert (handlers / "unrelated.txt").exists()


def test_one_missing_handler_file_is_reported(tmp_path: Path):
    entry, _ = _rotted(tmp_path, keep=("run.sh", "lib/util.sh"))

    issue = _check_missing_agent_handlers(entry, CATALOG, "global")

    assert issue is not None
    assert [Path(p).name for p in issue["missing"]] == ["helper.sh"]
    assert "helper.sh" in issue["repair_hint"]


def test_a_complete_handler_tree_is_clean(tmp_path: Path):
    entry, _ = _rotted(tmp_path, keep=("run.sh", "helper.sh", "lib/util.sh"))

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


def test_an_entry_without_recorded_targets_is_not_accused(tmp_path: Path):
    """A record predating handler tracking cannot be judged, so it is not judged."""
    entry, _ = _rotted(tmp_path, keep=())
    entry["bridge_symlinks"] = []

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


def test_a_vanished_cache_is_not_treated_as_rot(tmp_path: Path):
    entry, _ = _rotted(tmp_path, keep=())
    entry["bridge_symlinks"] = [
        f"{tmp_path / 'agents' / 'needs-handler-handlers'} -> {tmp_path / 'gone'}"
    ]

    assert _check_missing_agent_handlers(entry, CATALOG, "global") is None


# -- CL-8a7z: the default scope must match where agents look -----------------


@pytest.mark.parametrize("name", ["ci-monitor", "release", "learning-extractor"])
def test_handler_agents_default_to_global_scope(name: str):
    """Project scope installs into <project>/.claude/agents, which these agents
    do not probe; without a declared default they landed there.

    `acpx-runner` was dropped from this list when the agent was removed from the
    catalog (clc-ex88 in library-core): a relay subagent can fabricate the
    envelope it is supposed to relay, so cross-model dispatch now calls
    acpx-dispatch.py directly. Its handler directory outlived the agent and
    currently has no distribution vehicle, tracked as clc-j4pf.
    """
    import yaml

    catalog = yaml.safe_load((REPO_ROOT / "library.yaml").read_text(encoding="utf-8"))
    entry = next(
        item for item in catalog["library"]["agents"] if item.get("name") == name
    )
    assert entry.get("handlers"), f"{name} is expected to carry handlers"
    assert entry.get("default_scope") == "global"
