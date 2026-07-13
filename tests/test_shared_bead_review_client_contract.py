"""Contract tests for the provider-neutral bead review entry point."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "bin" / "lib" / "bead-review-client.py"
CLD = ROOT / "bin" / "cld"
CDX = ROOT / "bin" / "cdx"


def _review_branch(source: str) -> str:
    start = source.rindex('if [[ -n "$bead_review_id" ]]')
    end = source.index("\nfi", start) + len("\nfi")
    return source[start:end]


def test_shared_review_client_exists_and_both_launchers_delegate_to_it() -> None:
    assert CLIENT.is_file()

    cld = CLD.read_text(encoding="utf-8")
    cdx = CDX.read_text(encoding="utf-8")
    assert "CLD_BEAD_REVIEW_CLIENT" in cld
    assert "CDX_BEAD_REVIEW_CLIENT" in cdx
    assert "bead-review-client.py" in cld
    assert "bead-review-client.py" in cdx
    assert '"${BEAD_REVIEW_CLIENT}"' in cld
    assert '"${BEAD_REVIEW_CLIENT}"' in cdx


def test_launcher_review_branches_do_not_construct_provider_review_processes() -> None:
    cld_branch = _review_branch(CLD.read_text(encoding="utf-8"))
    cdx_branch = _review_branch(CDX.read_text(encoding="utf-8"))

    assert '"${CLAUDE_BIN}"' not in cld_branch
    assert '"${CODEX_BIN}"' not in cdx_branch
    assert "--allowedTools" not in cld_branch
    assert "--sandbox" not in cdx_branch
    assert "Use the bead-reviewer skill" not in cld_branch
    assert "Use the bead-reviewer skill" not in cdx_branch
