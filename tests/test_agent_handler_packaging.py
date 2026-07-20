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
