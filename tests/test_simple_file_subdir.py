"""Regression: vendor-install of a slash-named item must create its subdir.

A script catalogued with a slash in its name (e.g. "bead-review/review-prep")
installs to "<base>/bead-review/review-prep.py". The vendor copy path must
create the intermediate "bead-review/" directory first, or shutil.copy2 raises
FileNotFoundError. (simple_file.py previously only created canonical_base.)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib.installers.simple_file import install_simple_file  # noqa: E402


def test_vendor_install_creates_slash_named_subdir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    src = tmp_path / "src" / "review-prep.py"
    src.parent.mkdir(parents=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    catalog = {
        "default_dirs": {
            "scripts": [
                {"default": ".agents/scripts/"},
                {"global": "~/.agents/scripts/"},
            ]
        },
        "library": {
            "scripts": [
                {"name": "grp/review-prep", "source": str(src), "language": "python"}
            ]
        },
    }

    result = install_simple_file(
        catalog, "script", "grp/review-prep", repo_root=tmp_path, scope="global"
    )

    target = tmp_path / ".agents" / "scripts" / "grp" / "review-prep.py"
    assert target.exists(), f"slash-named script not installed: {result}"
