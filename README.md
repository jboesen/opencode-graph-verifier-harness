# Graph Verifier MCP for OpenCode

## What This Is

A **graph-verifier MCP server** that forces an OpenCode orchestrator to build a validated dependency graph before dispatching work, and to review lanes for continue/terminate decisions. Includes a prompt file that teaches the orchestrator how to use it.

## Prerequisites

- **OpenCode** with oh-my-opencode-slim plugin (or any OpenCode setup where you can append a prompt and add an MCP server).
- **Python 3.12+** with `fastmcp` installed.

## Setup

1. Copy `mcp/graph-verifier/server.py` and `mcp/graph-verifier/run.sh` to a location on your machine (e.g. `~/.local/graph-verifier-mcp/`).

2. Make `run.sh` executable:
   ```bash
   chmod +x ~/.local/graph-verifier-mcp/run.sh
   ```

3. Add the MCP server to your `opencode.json` or `opencode.jsonc`:
   ```json
   "mcp": {
     "graph-verifier": {
       "type": "local",
       "command": ["/path/to/graph-verifier-mcp/run.sh"],
       "enabled": true
     }
   }
   ```

4. Append the contents of `prompts/orchestrator-graph-verifier.md` to your orchestrator system prompt. If using oh-my-opencode-slim, place it at `~/.config/opencode/oh-my-opencode-slim/orchestrator_append.md`.

## How It Works

The graph-verifier server exposes five tools that form a **mandatory pre-dispatch protocol**:

| Tool | Purpose |
|------|---------|
| `submit_graph` | Submit and validate a dependency graph (cycle detection, dependency integrity, wave correctness, decomposition checks, concurrency ceiling). |
| `get_next_wave` | Get the next batch of ready-to-execute tickets whose dependencies are all satisfied. |
| `report_lane_result` | Report outcome of a completed/failed/terminated lane. |
| `review_lanes` | Review active lanes for CONTINUE/TERMINATE recommendations based on budget, duplication, and progress signals. |
| `get_state` | Full state snapshot of a graph — all tickets, waves, statuses, counts. |

**Mandatory sequence:**

1. `submit_graph` → if rejected, fix and re-submit
2. `get_next_wave` → dispatch ALL returned tickets as parallel background subagents
3. `report_lane_result` as each lane completes
4. `review_lanes` before next wave → terminate any TERMINATE-recommended lane
5. Repeat steps 2–4 until `all_complete`
6. Synthesize results and report

## Model Choice

The prompt works with any orchestrator model, but stronger models (Claude Opus/Sonnet, Kimi K2.7, GPT-4.5/5) handle the graph reasoning better than weak models.

## License

MIT
