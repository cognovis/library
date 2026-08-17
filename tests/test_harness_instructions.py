"""`library harness sync` installs the harness instruction files (CL-xgpw).

The instruction files are the first thing every coding harness reads, and they
carry the base knowledge about the Library. Before this contract they had no
owner: ADR-0012 left Library one desired state (the current Git repository),
so the two runtime-config entries targeting `~/.agents/` and `~/.claude/`
became unreachable — `--scope` is rejected outright, and a normal sync reported
entries refreshed while silently skipping both home-directory targets.

This suite is the source contract for the replacement. Installing the
instruction files is its own named operation, not a scope of the desired state,
and its substance is that the installed files agree with one another: every one
of them must resolve to the shared base, or a harness that opens a repository
never finds the project-level material.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.errors import InstallError  # noqa: E402
from lib.harness_instructions import (  # noqa: E402
    FALLBACK_MARKER,
    audit_harness_instructions,
    resolve_harness_targets,
    sync_harness_instructions,
)


BASE_BODY = (
    "# Always-on Cross-Harness Agent Rules\n"
    "\n"
    "Read `~/.agents/AGENTS.md` when no harness-specific instruction file is\n"
    "present.\n"
    "\n"
    "## Core Behavioral Rules\n"
    "\n"
    "- Branch naming: `typ/ticketnummer/kurze-beschreibung`.\n"
)

CLAUDE_BODY = (
    "@~/.agents/AGENTS.md\n"
    "\n"
    "# Claude Code — Harness-Specific Rules\n"
    "\n"
    "Read `~/.agents/AGENTS.md` when no harness-specific instruction file is\n"
    "present.\n"
)


def _catalog(tmp_path: Path) -> dict:
    """A catalog whose two instruction entries declare harness targets."""
    base_src = tmp_path / "src" / "AGENTS.md"
    claude_src = tmp_path / "src" / "CLAUDE.md"
    base_src.parent.mkdir(parents=True, exist_ok=True)
    base_src.write_text(BASE_BODY, encoding="utf-8")
    claude_src.write_text(CLAUDE_BODY, encoding="utf-8")

    return {
        "library": {
            "runtime_configs": [
                {
                    "name": "agents-md",
                    "base": str(base_src),
                    "format": "markdown",
                    "deploy_filename": "AGENTS.md",
                    "harness_instruction": {
                        "targets": [
                            {"harness": "agents", "path": "~/.agents/AGENTS.md", "shape": "file"},
                            {
                                "harness": "codex",
                                "path": "~/.codex/AGENTS.md",
                                "shape": "symlink",
                                "link_to": "~/.agents/AGENTS.md",
                            },
                            {
                                "harness": "kimi",
                                "path": "~/.kimi-code/AGENTS.md",
                                "shape": "symlink",
                                "link_to": "~/.agents/AGENTS.md",
                            },
                            {
                                "harness": "gemini",
                                "path": "~/.gemini/GEMINI.md",
                                "shape": "projection",
                            },
                            {
                                "harness": "cursor",
                                "path": "~/.cursor/rules/agents-md.mdc",
                                "shape": "projection",
                                "frontmatter": {"alwaysApply": True},
                            },
                        ]
                    },
                },
                {
                    "name": "claude-md-global",
                    "base": str(claude_src),
                    "format": "markdown",
                    "deploy_filename": "CLAUDE.md",
                    "harness_instruction": {
                        "targets": [
                            {
                                "harness": "claude_code",
                                "path": "~/.claude/CLAUDE.md",
                                "shape": "file",
                            }
                        ]
                    },
                },
                {
                    "name": "orchestrator-config",
                    "base": str(base_src),
                    "format": "markdown",
                    "deploy_filename": "orchestrator-config.yml",
                },
            ]
        }
    }


# AC1: a normal operator command installs every declared instruction file.


def test_sync_writes_every_declared_target(tmp_path):
    """AC1: one run reaches all six declared paths under the given home."""
    home = tmp_path / "home"
    result = sync_harness_instructions(_catalog(tmp_path), home=home)

    assert result["status"] == "ok", result
    written = {item["path"] for item in result["targets"]}
    assert written == {
        str(home / ".agents" / "AGENTS.md"),
        str(home / ".codex" / "AGENTS.md"),
        str(home / ".kimi-code" / "AGENTS.md"),
        str(home / ".gemini" / "GEMINI.md"),
        str(home / ".cursor" / "rules" / "agents-md.mdc"),
        str(home / ".claude" / "CLAUDE.md"),
    }
    assert (home / ".agents" / "AGENTS.md").read_text(encoding="utf-8") == BASE_BODY


def test_sync_ignores_entries_without_harness_targets(tmp_path):
    """A runtime-config that declares no targets is not an instruction file."""
    targets = resolve_harness_targets(_catalog(tmp_path), home=tmp_path / "home")
    assert "orchestrator-config" not in {item["entry"] for item in targets}


def test_dry_run_writes_nothing(tmp_path):
    """AC1: --dry-run reports the plan and leaves the filesystem untouched."""
    home = tmp_path / "home"
    result = sync_harness_instructions(_catalog(tmp_path), home=home, dry_run=True)

    assert result["status"] == "dry_run"
    assert len(result["targets"]) == 6
    assert not (home / ".agents").exists()


def test_sync_is_idempotent(tmp_path):
    """A second run rewrites the same bytes and reports no change."""
    home = tmp_path / "home"
    catalog = _catalog(tmp_path)
    sync_harness_instructions(catalog, home=home)
    second = sync_harness_instructions(catalog, home=home)

    assert second["status"] == "ok"
    assert all(item["changed"] is False for item in second["targets"]), second


# AC2: an unwritable tracked target fails loudly instead of being counted.


def test_unwritable_target_raises_instead_of_reporting_success(tmp_path):
    """AC2: the silent no-op that hid months of undeployed edits cannot recur."""
    home = tmp_path / "home"
    blocked = home / ".gemini"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(_catalog(tmp_path), home=home)

    assert str(blocked / "GEMINI.md") in str(excinfo.value)


def test_preflight_refuses_before_writing_any_target(tmp_path):
    """A blocked target aborts the whole run — no half-installed fleet."""
    home = tmp_path / "home"
    blocked = home / ".gemini"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InstallError):
        sync_harness_instructions(_catalog(tmp_path), home=home)

    assert not (home / ".agents" / "AGENTS.md").exists()


def test_refuses_to_clobber_an_unrecognized_file(tmp_path):
    """Claiming a file the platform never owned needs the operator's consent."""
    home = tmp_path / "home"
    foreign = home / ".gemini" / "GEMINI.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("hand-written by the operator\n", encoding="utf-8")

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(_catalog(tmp_path), home=home)

    assert "adopt" in str(excinfo.value).lower()
    assert foreign.read_text(encoding="utf-8") == "hand-written by the operator\n"


def test_adopt_claims_the_unrecognized_file(tmp_path):
    """With adopt=True the operator has said the file may be taken over."""
    home = tmp_path / "home"
    foreign = home / ".gemini" / "GEMINI.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("hand-written by the operator\n", encoding="utf-8")

    result = sync_harness_instructions(_catalog(tmp_path), home=home, adopt=True)

    assert result["status"] == "ok"
    assert FALLBACK_MARKER in foreign.read_text(encoding="utf-8")


def test_empty_file_is_not_foreign(tmp_path):
    """An empty placeholder (as gemini ships) is free to claim."""
    home = tmp_path / "home"
    placeholder = home / ".gemini" / "GEMINI.md"
    placeholder.parent.mkdir(parents=True, exist_ok=True)
    placeholder.write_text("", encoding="utf-8")

    result = sync_harness_instructions(_catalog(tmp_path), home=home)
    assert result["status"] == "ok"


# AC3: every installed file resolves to the shared base.


def test_symlink_targets_point_at_the_base(tmp_path):
    """AC3: Codex and Kimi read the base file itself, not a stale copy."""
    home = tmp_path / "home"
    sync_harness_instructions(_catalog(tmp_path), home=home)

    base = home / ".agents" / "AGENTS.md"
    for path in (home / ".codex" / "AGENTS.md", home / ".kimi-code" / "AGENTS.md"):
        assert path.is_symlink(), path
        assert path.resolve() == base.resolve()


def test_cursor_projection_carries_always_apply_frontmatter(tmp_path):
    """AC3: cursor-agent treats a rule as global only on alwaysApply: true."""
    home = tmp_path / "home"
    sync_harness_instructions(_catalog(tmp_path), home=home)

    text = (home / ".cursor" / "rules" / "agents-md.mdc").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head, _, body = text.partition("\n---\n")
    assert "alwaysApply: true" in head
    assert "## Core Behavioral Rules" in body


def test_projection_without_frontmatter_has_no_envelope(tmp_path):
    """Gemini reads plain markdown; a frontmatter block would be noise."""
    home = tmp_path / "home"
    sync_harness_instructions(_catalog(tmp_path), home=home)

    text = (home / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")
    assert not text.startswith("---\n")
    assert "## Core Behavioral Rules" in text


def test_claude_entry_keeps_its_own_import(tmp_path):
    """AC3: Claude Code resolves the base through its @-import, not a copy."""
    home = tmp_path / "home"
    sync_harness_instructions(_catalog(tmp_path), home=home)

    text = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("@~/.agents/AGENTS.md")


# AC4: the fallback rule is stated inside every installed file.


def test_every_installed_file_states_the_fallback_rule(tmp_path):
    """AC4: distribution without this is the original defect in a new place."""
    home = tmp_path / "home"
    result = sync_harness_instructions(_catalog(tmp_path), home=home)

    for item in result["targets"]:
        path = Path(item["path"])
        text = path.read_text(encoding="utf-8")
        assert FALLBACK_MARKER in text, f"{path} does not state the fallback rule"


def test_source_without_the_fallback_rule_is_rejected(tmp_path):
    """A source that drops the sentence must fail the sync, not ship silently."""
    catalog = _catalog(tmp_path)
    src = Path(catalog["library"]["runtime_configs"][0]["base"])
    src.write_text("# Rules\n\nNo pointer here.\n", encoding="utf-8")

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(catalog, home=tmp_path / "home")

    assert "fallback" in str(excinfo.value).lower()


# AC5: drift is reported for every installed file, not only the base.


def test_audit_reports_a_clean_fleet(tmp_path):
    """A freshly synced fleet has no drift."""
    home = tmp_path / "home"
    catalog = _catalog(tmp_path)
    sync_harness_instructions(catalog, home=home)

    result = audit_harness_instructions(catalog, home=home)
    assert result["drift"] is False
    assert all(item["status"] == "clean" for item in result["targets"])


@pytest.mark.parametrize(
    "relative",
    [
        ".agents/AGENTS.md",
        ".gemini/GEMINI.md",
        ".cursor/rules/agents-md.mdc",
        ".claude/CLAUDE.md",
    ],
)
def test_audit_reports_an_edited_target(tmp_path, relative):
    """AC5: every harness is audited, not only ~/.agents/AGENTS.md."""
    home = tmp_path / "home"
    catalog = _catalog(tmp_path)
    sync_harness_instructions(catalog, home=home)
    (home / relative).write_text("edited by hand\n", encoding="utf-8")

    result = audit_harness_instructions(catalog, home=home)
    assert result["drift"] is True
    drifted = {item["path"] for item in result["targets"] if item["status"] == "drift"}
    assert str(home / relative) in drifted


@pytest.mark.parametrize("relative", [".codex/AGENTS.md", ".kimi-code/AGENTS.md"])
def test_audit_reports_a_broken_symlink(tmp_path, relative):
    """A symlink target that no longer points at the base is drift, not clean."""
    home = tmp_path / "home"
    catalog = _catalog(tmp_path)
    sync_harness_instructions(catalog, home=home)

    link = home / relative
    link.unlink()
    link.write_text("a copy, not a link\n", encoding="utf-8")

    result = audit_harness_instructions(catalog, home=home)
    assert result["drift"] is True


def test_audit_reports_a_deleted_target(tmp_path):
    """A removed instruction file is missing, not clean."""
    home = tmp_path / "home"
    catalog = _catalog(tmp_path)
    sync_harness_instructions(catalog, home=home)
    (home / ".gemini" / "GEMINI.md").unlink()

    result = audit_harness_instructions(catalog, home=home)
    assert result["drift"] is True
    missing = {item["path"] for item in result["targets"] if item["status"] == "missing"}
    assert str(home / ".gemini" / "GEMINI.md") in missing


def test_audit_before_any_sync_reports_missing_not_clean(tmp_path):
    """The pre-CL-xgpw state must read as missing, never as a clean fleet."""
    result = audit_harness_instructions(_catalog(tmp_path), home=tmp_path / "home")
    assert result["drift"] is True
    assert all(item["status"] == "missing" for item in result["targets"])


# Declaration errors are typed, not silent.


def test_unknown_shape_is_rejected(tmp_path):
    """An unsupported delivery shape must name itself in the error."""
    catalog = _catalog(tmp_path)
    catalog["library"]["runtime_configs"][0]["harness_instruction"]["targets"][0][
        "shape"
    ] = "hardlink"

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(catalog, home=tmp_path / "home")

    assert "hardlink" in str(excinfo.value)


def test_symlink_without_link_to_is_rejected(tmp_path):
    """A symlink shape with no destination is a declaration error."""
    catalog = _catalog(tmp_path)
    target = catalog["library"]["runtime_configs"][0]["harness_instruction"]["targets"][1]
    del target["link_to"]

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(catalog, home=tmp_path / "home")

    assert "link_to" in str(excinfo.value)


def test_the_bare_base_path_does_not_satisfy_the_fallback_guard(tmp_path):
    """The guard must not pass on a file that only names the path in passing.

    `AGENTS.md` mentions `~/.agents/AGENTS.md` in its own header line. A guard
    keyed on the bare path would report the fallback rule present in every
    source that merely says where it lives.
    """
    catalog = _catalog(tmp_path)
    src = Path(catalog["library"]["runtime_configs"][0]["base"])
    src.write_text(
        "# Rules\n\nCanonical at `~/.agents/AGENTS.md`.\n",
        encoding="utf-8",
    )

    with pytest.raises(InstallError) as excinfo:
        sync_harness_instructions(catalog, home=tmp_path / "home")

    assert "fallback" in str(excinfo.value).lower()
