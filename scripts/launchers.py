"""Console entrypoints for the packaged Claude Code and Codex launchers."""

from __future__ import annotations

import subprocess
import sys
from importlib.resources import files


def _run_launcher(name: str) -> int:
    """Execute one bundled launcher without depending on a source checkout."""
    launcher = files("scripts").joinpath("bin", name)
    return subprocess.run([str(launcher), *sys.argv[1:]], check=False).returncode


def cld() -> int:
    """Run the bundled Claude Code launcher."""
    return _run_launcher("cld")


def cdx() -> int:
    """Run the bundled Codex launcher."""
    return _run_launcher("cdx")
