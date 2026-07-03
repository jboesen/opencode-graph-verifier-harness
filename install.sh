#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== opencode-graph-verifier-harness Installer ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Ensure ~/.config/opencode/ exists
# ---------------------------------------------------------------------------
OPENCODE_DIR="$HOME/.config/opencode"
OPENCODE_SLIM_DIR="$OPENCODE_DIR/oh-my-opencode-slim"

echo "[1/7] Ensuring $OPENCODE_DIR exists..."
mkdir -p "$OPENCODE_DIR"
mkdir -p "$OPENCODE_SLIM_DIR"

# ---------------------------------------------------------------------------
# 2. Backup existing files
# ---------------------------------------------------------------------------
BACKUP_DIR="$OPENCODE_DIR/backup-$(date +%Y%m%d-%H%M%S)"
EXISTING_FILES=(
  "$OPENCODE_DIR/opencode.jsonc"
  "$OPENCODE_DIR/oh-my-opencode-slim.json"
  "$OPENCODE_SLIM_DIR/orchestrator_append.md"
)

NEEDS_BACKUP=false
for f in "${EXISTING_FILES[@]}"; do
  if [ -f "$f" ]; then
    NEEDS_BACKUP=true
    break
  fi
done

if [ "$NEEDS_BACKUP" = true ]; then
  echo "[2/7] Backing up existing config files to $BACKUP_DIR..."
  mkdir -p "$BACKUP_DIR"
  for f in "${EXISTING_FILES[@]}"; do
    if [ -f "$f" ]; then
      cp "$f" "$BACKUP_DIR/"
      echo "  -> backed up $(basename "$f")"
    fi
  done
else
  echo "[2/7] No existing config files to back up."
fi

# ---------------------------------------------------------------------------
# 3. Copy opencode config files
# ---------------------------------------------------------------------------
echo "[3/7] Copying opencode config files..."
cp "$SCRIPT_DIR/opencode/opencode.jsonc" "$OPENCODE_DIR/"
cp "$SCRIPT_DIR/opencode/oh-my-opencode-slim.json" "$OPENCODE_DIR/"
cp "$SCRIPT_DIR/opencode/oh-my-opencode-slim/orchestrator_append.md" "$OPENCODE_SLIM_DIR/"
echo "  -> copied opencode.jsonc, oh-my-opencode-slim.json, orchestrator_append.md"

# ---------------------------------------------------------------------------
# 4. Create graph-verifier MCP directory and copy files
# ---------------------------------------------------------------------------
GRAPH_VERIFIER_DIR="$HOME/.local/graph-verifier-mcp"
echo "[4/7] Setting up graph-verifier MCP in $GRAPH_VERIFIER_DIR..."
mkdir -p "$GRAPH_VERIFIER_DIR"
cp "$SCRIPT_DIR/mcp/graph-verifier/server.py" "$GRAPH_VERIFIER_DIR/"
cp "$SCRIPT_DIR/mcp/graph-verifier/run.sh" "$GRAPH_VERIFIER_DIR/"
echo "  -> copied server.py, run.sh"

# ---------------------------------------------------------------------------
# 5. Make run.sh executable
# ---------------------------------------------------------------------------
echo "[5/7] Making run.sh executable..."
chmod +x "$GRAPH_VERIFIER_DIR/run.sh"
echo "  -> $GRAPH_VERIFIER_DIR/run.sh is now executable"

# ---------------------------------------------------------------------------
# 6. Create Python venv and install packages
# ---------------------------------------------------------------------------
VENV_DIR="$HOME/.local/beads-venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "[6/7] Creating Python 3.12 venv at $VENV_DIR..."
  python3.12 -m venv "$VENV_DIR"
  echo "  -> venv created"
else
  echo "[6/7] Python venv already exists at $VENV_DIR (skipping creation)"
fi

echo "  -> Installing/updating fastmcp and beads-mcp..."
"$VENV_DIR/bin/pip" install -q fastmcp beads-mcp
echo "  -> packages installed"

# ---------------------------------------------------------------------------
# 7. Fix beads-mcp shebang
# ---------------------------------------------------------------------------
echo "[7/7] Running fix-beads-shebang.sh..."
bash "$SCRIPT_DIR/scripts/fix-beads-shebang.sh"

echo ""
echo "=== Install complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. Set your API keys (add these to ~/.bashrc or ~/.zshrc):"
echo ""
echo "      export OPENROUTER_API_KEY=\"sk-or-v1-...\""
echo "      export BIG_PICKLE_API_KEY=\"bp-...\""
echo ""
echo "  2. Start opencode:"
echo ""
echo "      opencode"
echo ""
echo "  3. Verify MCP servers respond:"
echo ""
echo "      opencode mcp list"
echo ""
echo "     You should see both 'beads' and 'graph-verifier' in the list."
echo ""
echo "  4. If your home directory is not /root, edit these files to fix paths:"
echo ""
echo "      ~/.config/opencode/opencode.jsonc"
echo "      ~/.local/graph-verifier-mcp/run.sh"
echo ""
echo "Happy hacking!"
