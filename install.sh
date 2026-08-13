#!/usr/bin/env bash
# Transitional bootstrap entrypoint for the Library control-plane package.

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

echo "Installing the Library control plane with uv"
uv tool install --upgrade "$script_dir"

echo ""
echo "The global bootstrap contains only the Library executable and its product"
echo "launchers/instruction/runtime prerequisites. It does not install a Library"
echo "skill or any other Library primitive globally."
echo ""
echo "Next steps:"
echo "  library --help"
echo "  library bootstrap install"
echo "  cd <git-repository> && library init"
