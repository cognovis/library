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

MALFORMED_META = """\
export const meta = { name: "bad",, description: "x" };

return { ok: true };
"""

PRE_META_CODE = """\
const before = Date.now();
export const meta = { name: "premeta", description: "x" };

return { ok: true };
"""

PRE_META_COMMENT_OK = """\
// a leading comment is fine
/* and a block comment */
export const meta = { name: "okc", description: "x" };

return { ok: true };
"""

# A header comment that MENTIONS `export const meta` and contains braces must not
# fool the marker search into matching inside the comment (regression for the
# bead-orchestrator dogfood failure).
COMMENT_MENTIONS_META = """\
/**
 * doc — everything after `export const meta` is the body.
 * Do NOT use `export async function run(args)`.
 * Example: args = { slots: { implementation: { agentType: "x" } } }
 */

export const meta = { name: "mentioned", description: "x" };

const t = args.slots?.implementation;
return { ok: true, t };
"""

# A brace inside a meta string must not throw off the object-literal scan.
BRACE_IN_META_STRING = """\
export const meta = {
  name: "braces",
  description: "args shape: { beadId: string } with a } brace and a { brace",
  parameters: [
    { name: "beadId", type: "string", required: true, help: "id like { x }" }
  ]
};

return { ok: true };
"""

# meta must be a pure static literal (standards/workflow/parameters.md).
META_TEMPLATE_LITERAL = """\
export const meta = { name: `bad-${1 + 1}`, description: "x" };

return { ok: true };
"""

META_ARROW_FN = """\
export const meta = { name: "x", description: "y", make: () => 1 };

return { ok: true };
"""

META_PARENS_IN_STRING_OK = """\
export const meta = { name: "x", description: "maps (a) and ... ellipsis in text" };

return { ok: true };
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


@node_required
def test_malformed_meta_rejected(tmp_path: Path) -> None:
    js = tmp_path / "bad.js"
    js.write_text(MALFORMED_META, encoding="utf-8")
    with pytest.raises(InstallError):
        _assert_workflow_native_parse(js, "bad")


def test_pre_meta_executable_code_rejected(tmp_path: Path) -> None:
    js = tmp_path / "premeta.js"
    js.write_text(PRE_META_CODE, encoding="utf-8")
    with pytest.raises(InstallError) as exc:
        _assert_workflow_native_parse(js, "premeta")
    assert "first statement" in str(exc.value)


@node_required
def test_pre_meta_comments_allowed(tmp_path: Path) -> None:
    js = tmp_path / "okc.js"
    js.write_text(PRE_META_COMMENT_OK, encoding="utf-8")
    # Comments before meta are fine — should not raise.
    _assert_workflow_native_parse(js, "okc")


@node_required
def test_comment_mentioning_meta_not_matched(tmp_path: Path) -> None:
    js = tmp_path / "mentioned.js"
    js.write_text(COMMENT_MENTIONS_META, encoding="utf-8")
    # The marker search must anchor on the real declaration, not the comment text.
    _assert_workflow_native_parse(js, "mentioned")


@node_required
def test_brace_inside_meta_string_allowed(tmp_path: Path) -> None:
    js = tmp_path / "braces.js"
    js.write_text(BRACE_IN_META_STRING, encoding="utf-8")
    # A `}`/`{` inside a meta string must not break the object-literal scan.
    _assert_workflow_native_parse(js, "braces")


def test_meta_template_literal_rejected(tmp_path: Path) -> None:
    js = tmp_path / "tmpl.js"
    js.write_text(META_TEMPLATE_LITERAL, encoding="utf-8")
    with pytest.raises(InstallError) as exc:
        _assert_workflow_native_parse(js, "tmpl")
    assert "static literal" in str(exc.value)


def test_meta_function_value_rejected(tmp_path: Path) -> None:
    js = tmp_path / "fn.js"
    js.write_text(META_ARROW_FN, encoding="utf-8")
    with pytest.raises(InstallError) as exc:
        _assert_workflow_native_parse(js, "fn")
    assert "static literal" in str(exc.value)


def test_meta_parens_in_string_allowed(tmp_path: Path) -> None:
    js = tmp_path / "strok.js"
    js.write_text(META_PARENS_IN_STRING_OK, encoding="utf-8")
    # Parens/ellipsis inside a meta string are content, not dynamic expressions.
    _assert_workflow_native_parse(js, "strok")


def test_skips_gracefully_without_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    js = tmp_path / "broken.js"
    js.write_text(RUN_WRAPPER, encoding="utf-8")
    monkeypatch.setattr("lib.installers.simple_file.shutil.which", lambda _: None)
    # node absent -> skip the gate (warn), do not raise.
    _assert_workflow_native_parse(js, "broken")
