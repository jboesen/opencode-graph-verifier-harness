#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${GRAPH_VERIFIER_PYTHON:-python3}" "$SCRIPT_DIR/server.py" "$@"
