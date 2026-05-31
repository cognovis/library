"""Parity: the installer deploy-gate and the workflow-forge parse-check must agree.

Two implementations of the native-workflow parse gate exist by necessity — the
deploy-time gate in Python (`installers/simple_file.py`) and the authoring-time
gate in JS (`workflow-forge/scripts/check-workflow-parse.mjs`, in the cognovis-core
catalog). They are advertised as "the same gate", so this test runs BOTH over a
shared fixture set and asserts identical accept/reject verdicts. Skips when the
sibling forge script or `node` is unavailable.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.errors import InstallError  # noqa: E402
from lib.installers.simple_file import _assert_workflow_native_parse  # noqa: E402

FORGE_CHECK = (
    REPO_ROOT.parent
    / "cognovis-core"
    / "skills"
    / "workflow-forge"
    / "scripts"
    / "check-workflow-parse.mjs"
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not FORGE_CHECK.is_file(),
    reason="node or sibling workflow-forge check script unavailable",
)

# (label, source, expected_accept)
CASES = [
    ("native_ok", 'export const meta = { name: "a", description: "d" };\nreturn { ok: true };\n', True),
    ("run_wrapper", 'export const meta = { name: "a", description: "d" };\nexport async function run(args) { return args; }\n', False),
    ("malformed_meta", 'export const meta = { name: "a",, description: "d" };\nreturn 1;\n', False),
    ("pre_meta_code", 'const x = 1;\nexport const meta = { name: "a", description: "d" };\nreturn x;\n', False),
    ("no_meta", "const x = 1;\nreturn x;\n", False),
    ("comment_mentions_meta", '/* after `export const meta` use top-level body; ex: { a: 1 } */\nexport const meta = { name: "a", description: "d" };\nreturn 1;\n', True),
    ("brace_in_string", 'export const meta = { name: "a", description: "has } and { brace" };\nreturn 1;\n', True),
    ("leading_comments", '// c\n/* b */\nexport const meta = { name: "a", description: "d" };\nreturn 1;\n', True),
]


def _installer_accepts(js: Path) -> bool:
    try:
        _assert_workflow_native_parse(js, js.stem)
        return True
    except InstallError:
        return False


def _forge_accepts(js: Path) -> bool:
    result = subprocess.run(
        ["node", str(FORGE_CHECK), str(js)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize("label,source,expected", CASES, ids=[c[0] for c in CASES])
def test_gates_agree(tmp_path: Path, label: str, source: str, expected: bool) -> None:
    js = tmp_path / f"{label}.js"
    js.write_text(source, encoding="utf-8")
    installer = _installer_accepts(js)
    forge = _forge_accepts(js)
    assert installer == forge, (
        f"gate disagreement on {label!r}: installer={installer}, forge={forge}"
    )
    assert installer == expected, (
        f"{label!r}: expected accept={expected}, got installer={installer}"
    )
