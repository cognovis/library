"""Tests for the workflow deploy parse-gate in simple_file.py (clc-j7mn).

A Library workflow is authored once as native Claude Workflow JS. The installer
must refuse to deploy a spec whose post-`meta` body does not parse as an async
function — e.g. the `export async function run(args)` wrapper that never launches
under the native tool.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import InstallError  # noqa: E402
from lib.installers.simple_file import _assert_workflow_native_parse  # noqa: E402

NATIVE_OK = """\
export const meta = { name: "ok", description: "d" };

const items = args.items ?? [];
const results = await parallel(items.map((i) => () => agent(`Do ${i}`)));
return results.filter(Boolean);
"""

RUN_WRAPPER = """\
export const meta = { name: "broken", description: "d" };

export async function run(args) {
  const items = args.items ?? [];
  return items;
}
"""

NO_META = """\
const items = args.items ?? [];
return items;
"""

node_required = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


@node_required
def test_native_body_passes(tmp_path: Path) -> None:
    js = tmp_path / "ok.js"
    js.write_text(NATIVE_OK, encoding="utf-8")
    # Should not raise.
    _assert_workflow_native_parse(js, "ok")


@node_required
def test_run_wrapper_rejected(tmp_path: Path) -> None:
    js = tmp_path / "broken.js"
    js.write_text(RUN_WRAPPER, encoding="utf-8")
    with pytest.raises(InstallError) as exc:
        _assert_workflow_native_parse(js, "broken")
    msg = str(exc.value)
    assert "run(args)" in msg
    assert "broken" in msg


def test_missing_meta_rejected(tmp_path: Path) -> None:
    js = tmp_path / "nometa.js"
    js.write_text(NO_META, encoding="utf-8")
    with pytest.raises(InstallError) as exc:
        _assert_workflow_native_parse(js, "nometa")
    assert "export const meta" in str(exc.value)


def test_skips_gracefully_without_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    js = tmp_path / "broken.js"
    js.write_text(RUN_WRAPPER, encoding="utf-8")
    monkeypatch.setattr("lib.installers.simple_file.shutil.which", lambda _: None)
    # node absent -> skip the gate (warn), do not raise.
    _assert_workflow_native_parse(js, "broken")
