#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/uv-cache}"

uv run --no-project python "$SCRIPT_DIR/audit-mcp-migration-debt.py" --check-class A "$@"
