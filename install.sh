#!/usr/bin/env bash
# Bootstrap the Library control plane and its portable catalog source checkouts.

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
fresh=false
project=""
platform_source="https://github.com/cognovis/library.git"
core_source="https://github.com/cognovis/library-core.git"
source_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/library/sources"

while test "$#" -gt 0; do
  case "$1" in
    --fresh)
      fresh=true
      shift
      ;;
    --project)
      test "$#" -ge 2 || { echo "Error: --project requires a path" >&2; exit 2; }
      project="$2"
      shift 2
      ;;
    --platform-source)
      test "$#" -ge 2 || { echo "Error: --platform-source requires a Git source" >&2; exit 2; }
      platform_source="$2"
      shift 2
      ;;
    --core-source)
      test "$#" -ge 2 || { echo "Error: --core-source requires a Git source" >&2; exit 2; }
      core_source="$2"
      shift 2
      ;;
    --source-dir)
      test "$#" -ge 2 || { echo "Error: --source-dir requires a path" >&2; exit 2; }
      source_dir="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: install.sh [--fresh] [--project PATH] [--source-dir PATH]"
      echo "                  [--platform-source GIT_URL] [--core-source GIT_URL]"
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

command -v uv >/dev/null 2>&1 || {
  echo "Error: uv is required. Install uv from https://docs.astral.sh/uv/ first." >&2
  exit 1
}

clone_or_update() {
  source="$1"
  checkout="$2"
  if test -d "$checkout/.git"; then
    if ! git -C "$checkout" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "Error: managed checkout is incomplete: $checkout" >&2
      echo "Move it aside after preserving any needed files, then re-run install.sh --fresh." >&2
      return 1
    fi
    current_origin="$(git -C "$checkout" remote get-url origin)"
    if test "$current_origin" != "$source"; then
      echo "Error: managed checkout has a different origin: $checkout" >&2
      return 1
    fi
    git -C "$checkout" pull --quiet --ff-only
    return
  fi
  if test -e "$checkout"; then
    echo "Error: managed checkout is incomplete: $checkout" >&2
    echo "Move it aside after preserving any needed files, then re-run install.sh --fresh." >&2
    return 1
  fi
  mkdir -p "$(dirname "$checkout")"
  git clone --quiet "$source" "$checkout"
}

install_source="$script_dir"
if test "$fresh" = true; then
  platform_checkout="$source_dir/library-platform"
  core_checkout="$source_dir/cognovis-library-core"
  clone_or_update "$platform_source" "$platform_checkout"
  clone_or_update "$core_source" "$core_checkout"
  install_source="$platform_checkout"

  config_home="${XDG_CONFIG_HOME:-${HOME}/.config}/library"
  registry="$config_home/catalog-sources.json"
  mkdir -p "$config_home"
  temporary_registry="$registry.tmp-$$"
  uv run python - "$temporary_registry" "$platform_checkout" "$core_checkout" <<'PY'
import json
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "catalogs": [
        {
            "identity": "https://github.com/cognovis/library",
            "checkout": str(Path(sys.argv[2]).resolve()),
        },
        {
            "identity": "https://github.com/cognovis/library-core",
            "checkout": str(Path(sys.argv[3]).resolve()),
        },
    ],
}
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(target, 0o600)
PY
  mv -f "$temporary_registry" "$registry"
fi

echo "Installing the Library control plane with uv"
uv tool install --upgrade "$install_source"

library_bin="${UV_TOOL_BIN_DIR:-${HOME}/.local/bin}/library"
if ! test -x "$library_bin"; then
  library_bin="$(command -v library || true)"
fi
if ! test -x "$library_bin"; then
  echo "Error: uv installed Library but its executable is not available" >&2
  exit 1
fi

if test "$fresh" = true; then
  "$library_bin" bootstrap install
fi

if test -n "$project"; then
  git -C "$project" rev-parse --show-toplevel >/dev/null
  (cd "$project" && "$library_bin" init)
fi

echo ""
echo "The global bootstrap contains only the Library executable and its product"
echo "launchers/instruction/runtime prerequisites. It does not install a Library"
echo "skill or any other Library primitive globally."
echo ""
echo "Next steps:"
echo "  library --help"
echo "  library bootstrap install"
echo "  cd <git-repository> && library init"
