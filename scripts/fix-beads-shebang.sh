#!/usr/bin/env bash
set -e

BEADS_MCP="$HOME/.local/beads-venv/bin/beads-mcp"

if [ ! -f "$BEADS_MCP" ]; then
  echo "  [fix-beads-shebang] $BEADS_MCP not found — skipping"
  exit 0
fi

SHEBANG=$(head -1 "$BEADS_MCP")
BROKEN_PATH="#!/tmp/beads-venv/bin/python3"
CORRECT_PATH="#!/root/.local/beads-venv/bin/python3"

if [ "$SHEBANG" = "$BROKEN_PATH" ]; then
  echo "  [fix-beads-shebang] Fixing broken shebang in $BEADS_MCP"
  echo "  [fix-beads-shebang]   Old: $BROKEN_PATH"
  echo "  [fix-beads-shebang]   New: $CORRECT_PATH"
  # Use sed to rewrite the shebang
  sed -i "1s|$BROKEN_PATH|$CORRECT_PATH|" "$BEADS_MCP"
  echo "  [fix-beads-shebang] Done"
elif [ "$SHEBANG" = "$CORRECT_PATH" ]; then
  echo "  [fix-beads-shebang] Shebang already correct ($CORRECT_PATH)"
else
  echo "  [fix-beads-shebang] Shebang is unexpected: $SHEBANG"
  echo "  [fix-beads-shebang] No changes made"
fi
