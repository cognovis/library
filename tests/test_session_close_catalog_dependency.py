from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.resolver import resolve_requires  # noqa: E402


def test_session_close_resolves_worktree_cleanup_before_install() -> None:
    order = resolve_requires(
        load_catalog(REPO_ROOT),
        "skill",
        "session-close",
        REPO_ROOT,
    )

    assert ("skill", "cognovis-beads") in order
    assert ("skill", "worktree-cleanup") in order
    assert order.index(("skill", "worktree-cleanup")) < order.index(
        ("skill", "session-close")
    )
