"""Setuptools hook that carries the root catalog inside the CLI package."""

from __future__ import annotations

from pathlib import Path
from shutil import copy2

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    """Copy the catalog beside the installed scripts package."""

    def run(self) -> None:
        super().run()
        source = Path(__file__).parent / "library.yaml"
        target = Path(self.build_lib) / "scripts" / "library.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)


setup(cmdclass={"build_py": build_py})
