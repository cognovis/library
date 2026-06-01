#!/usr/bin/env python3
"""Regression tests for the bin/clw workflow launcher.

clw statically parses a workflow's `meta` block (no JS execution) and builds the
`claude --agent workflow-launcher "Run workflow '<name>' with args: <json>"`
invocation. These tests stub CLAUDE_BIN with `echo` so the built invocation is
captured instead of launching a live Claude session.

Guards the clc-iu78 contract: `meta.parameters` is a LIST of {name,...} objects.
An earlier implementation assumed a name-keyed dict, so required-validation,
type coercion, and defaults all silently no-op'd on real workflows.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLW = REPO_ROOT / "bin" / "clw"

# A workflow whose meta.parameters is a JSON list (the clc-iu78 shape).
_WORKFLOW = """\
/* test workflow */
export const meta = {
  "name": "test-wf",
  "description": "Test workflow for clw arg parsing.",
  "parameters": [
    {
      "name": "beadIds",
      "type": "list",
      "required": true,
      "help": "Comma-separated bead IDs"
    },
    {
      "name": "strict",
      "type": "bool",
      "required": false,
      "default": false,
      "help": "Strict mode"
    }
  ]
};

return { ok: true };
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A project dir with .claude/workflows/test-wf.js (clw resolves this first)."""
    wf_dir = tmp_path / ".claude" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "test-wf.js").write_text(_WORKFLOW, encoding="utf-8")
    return tmp_path


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Inherit the real environment (uv must stay on PATH); stub CLAUDE_BIN so the
    # built invocation is echoed, and point HOME at the project so a global
    # ~/.claude/workflows does not shadow the project-local test workflow.
    env = dict(os.environ)
    env["CLAUDE_BIN"] = "echo"
    env["HOME"] = str(project)
    return subprocess.run(
        [str(CLW), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def test_list_param_coerced_to_json_array(project: Path) -> None:
    result = _run(project, "test-wf", "--beadIds", "a,b,c")
    assert result.returncode == 0, result.stderr
    payload = result.stdout.split("with args: ", 1)[1].strip()
    # strict defaults to false (optional param default is applied).
    assert json.loads(payload) == {"beadIds": ["a", "b", "c"], "strict": False}


def test_bool_flag_presence_true(project: Path) -> None:
    result = _run(project, "test-wf", "--beadIds", "a", "--strict")
    assert result.returncode == 0, result.stderr
    payload = result.stdout.split("with args: ", 1)[1].strip()
    assert json.loads(payload) == {"beadIds": ["a"], "strict": True}


def test_missing_required_param_errors_without_launching(project: Path) -> None:
    result = _run(project, "test-wf")
    assert result.returncode == 2
    assert "beadIds" in result.stderr
    # Must not have built/echoed a launch invocation.
    assert "Run workflow" not in result.stdout


def test_help_lists_declared_parameters(project: Path) -> None:
    result = _run(project, "test-wf", "--help")
    assert result.returncode == 0, result.stderr
    assert "--beadIds" in result.stdout
    assert "[required]" in result.stdout
    assert "--strict" in result.stdout


# A workflow whose list param is flagged expandEpics: true.
_EPIC_WORKFLOW = """\
export const meta = {
  "name": "epic-wf",
  "description": "expandEpics test.",
  "parameters": [
    { "name": "beadIds", "type": "list", "required": true, "expandEpics": true, "help": "ids" }
  ]
};
return { ok: true };
"""

# Stub `bd`: `bd show <id> --json` returns an epic (EP) with two children,
# or a plain task otherwise. Mirrors the real `[{...}]` list shape.
_STUB_BD = """\
#!/usr/bin/env bash
if [ "$1" = "show" ]; then
  id="$2"
  if [ "$id" = "EP" ]; then
    echo '[{"id":"EP","issue_type":"epic","dependents":[{"id":"EP.1","dependency_type":"parent-child"},{"id":"EP.2","dependency_type":"parent-child"}]}]'
  else
    echo "[{\\"id\\":\\"$id\\",\\"issue_type\\":\\"task\\",\\"dependents\\":[]}]"
  fi
fi
"""


def test_expand_epics_includes_children(tmp_path: Path) -> None:
    wf_dir = tmp_path / ".claude" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "epic-wf.js").write_text(_EPIC_WORKFLOW, encoding="utf-8")
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    bd = stub_bin / "bd"
    bd.write_text(_STUB_BD, encoding="utf-8")
    bd.chmod(0o755)

    env = dict(os.environ)
    env["CLAUDE_BIN"] = "echo"
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"  # stub bd shadows real bd
    result = subprocess.run(
        [str(CLW), "epic-wf", "--beadIds", "EP,solo"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("with args: ", 1)[1].strip())
    # Epic EP expands to EP + children, epic-first; solo stays as-is.
    assert payload["beadIds"] == ["EP", "EP.1", "EP.2", "solo"]
