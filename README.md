# Graph Verifier MCP for AI Coding Tools

## What This Is

A **graph-verifier MCP server** that forces any MCP-compatible coding assistant to build a validated dependency graph before dispatching work, and to review lanes for continue/terminate decisions. Includes prompt files that teach the orchestrator how to use it.

Supported hosts:
- **OpenCode** (via `opencode.json` + orchestrator system prompt)
- **Claude Code** (via `claude.jsonc`/`claude_desktop_config.json` + `CLAUDE.md` instructions)

## Prerequisites

- **OpenCode** with oh-my-opencode-slim plugin (or any OpenCode setup where you can append a prompt and add an MCP server).
- **Claude Code** (any recent version that supports MCP servers in `claude.jsonc` or `claude_desktop_config.json`).
- **Python 3.12+** with `fastmcp` installed.

To keep the MCP isolated, a project virtual environment is a convenient setup:

```bash
python3 -m venv .venv
.venv/bin/pip install fastmcp
```

When using that environment, set `GRAPH_VERIFIER_PYTHON` to its interpreter in
your MCP host configuration (for example, `"GRAPH_VERIFIER_PYTHON": "/absolute/path/to/.venv/bin/python"`).

## Setup

### General MCP Server Setup

1. Copy the complete `mcp/graph-verifier/` directory to a location on your machine (e.g. `~/.local/graph-verifier-mcp/`). It includes the optional visual board alongside the MCP server.

2. Make `run.sh` executable:
   ```bash
   chmod +x ~/.local/graph-verifier-mcp/run.sh
   ```

### OpenCode Setup

1. Add the MCP server to your `opencode.json` or `opencode.jsonc`:
   ```json
   "mcp": {
     "graph-verifier": {
       "type": "local",
       "command": ["/path/to/graph-verifier-mcp/run.sh"],
       "enabled": true
     }
   }
   ```

2. Append the contents of `prompts/orchestrator-graph-verifier.md` to your orchestrator system prompt. If using oh-my-opencode-slim, place it at `~/.config/opencode/oh-my-opencode-slim/orchestrator_append.md`.

### Claude Code Setup

1. Add the MCP server to your `claude.jsonc` (project-level) or `claude_desktop_config.json` (global):
   ```json
   {
     "mcpServers": {
       "graph-verifier": {
         "type": "local",
         "command": ["/path/to/graph-verifier-mcp/run.sh"],
         "enabled": true
       }
     }
   }
   ```

2. Add the contents of `prompts/claude-code-graph-verifier.md` to your `CLAUDE.md` file in the project root (or append it to an existing `CLAUDE.md`).

## How It Works

The graph-verifier server exposes five tools that form a **mandatory pre-dispatch protocol**:

| Tool | Purpose |
|------|---------|
| `submit_graph` | Submit and validate a dependency graph (cycle detection, dependency integrity, wave correctness, decomposition checks, concurrency ceiling). |
| `get_next_wave` | Get the next batch of ready-to-execute tickets whose dependencies are all satisfied. |
| `report_lane_result` | Report outcome of a completed/failed/terminated lane. |
| `review_lanes` | Review active lanes for CONTINUE/TERMINATE recommendations based on budget, duplication, and progress signals. |
| `get_state` | Full state snapshot of a graph — all tickets, waves, statuses, counts. |
| `open_graph_view` | Starts a local interactive execution board and returns a browser URL. |

**Mandatory sequence:**

1. `submit_graph` → if rejected, fix and re-submit
2. `get_next_wave` → dispatch ALL returned tickets as parallel background subagents
3. `report_lane_result` as each lane completes
4. `review_lanes` before next wave → terminate any TERMINATE-recommended lane
5. Repeat steps 2–4 until `all_complete`
6. Synthesize results and report

## Interactive graph board

After `submit_graph` approves a graph, call `open_graph_view` with its `graph_id`.
It returns a localhost URL (default: `http://127.0.0.1:8765`) that shows the graph as draggable cards connected by dependency arrows. Cards are laid out by wave, status colors update as lanes are reported, and the board refreshes automatically. The viewer binds only to `127.0.0.1`.

## Files

- `mcp/graph-verifier/server.py` — The MCP server implementation (tool-neutral, works with any MCP host).
- `mcp/graph-verifier/run.sh` — Startup script that launches the server.
- `prompts/orchestrator-graph-verifier.md` — Prompt for **OpenCode** (append to orchestrator system prompt).
- `prompts/claude-code-graph-verifier.md` — Prompt for **Claude Code** (add to `CLAUDE.md`).

## Model Choice

The prompts work with any orchestrator model, but stronger models (Claude Opus/Sonnet, Kimi K2.7, GPT-4.5/5) handle the graph reasoning better than weak models.

## License

MIT
