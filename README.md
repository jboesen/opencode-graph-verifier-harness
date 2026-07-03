# opencode-graph-verifier-harness

A self-contained **opencode orchestrator harness** that enforces **graph-first planning** via a **graph-verifier MCP server**, uses **Kimi K2.7 (OpenRouter)** as the orchestrator model and **Big Pickle** as the worker model, and dispatches **parallel background subagents**.

## What This Is

This harness packages the configuration, prompts, and tooling needed to run an opencode session that:

- **Forces graph-first orchestration** — every non-trivial request must pass through the graph-verifier MCP before any subagent acts. You submit a dependency graph, get approved tickets, dispatch parallel background subagents, and report results back. No ticket = no dispatch.
- **Uses Kimi K2.7 for orchestration** — the orchestrator model (`openrouter/moonshotai/kimi-k2.7-code`) handles planning, oversight, and reconciliation.
- **Uses Big Pickle for execution** — all worker specialists (explorer, librarian, oracle, designer, fixer) use `opencode/big-pickle`.
- **Manages work with beads** — a local MCP-based issue tracker (`beads-mcp`) for cross-session persistence.

## Prerequisites

- **opencode** ≥ 1.17.13
- **Python 3.12** (for the venv that hosts `fastmcp` and `beads-mcp`)
- **pip** (for installing Python packages)
- **API keys** set in your shell environment:
  - `OPENROUTER_API_KEY` — for the orchestrator model (Kimi K2.7 via OpenRouter)
  - `BIG_PICKLE_API_KEY` — for the worker model (Big Pickle)
- **git** and **GitHub CLI (`gh`)** if you want the full workflow

## Quick Install

```bash
git clone https://github.com/jboesen/opencode-graph-verifier-harness.git
cd opencode-graph-verifier-harness
./install.sh
```

Then set your API keys and start opencode.

## Manual Install

If you prefer to install step by step:

### 1. Copy opencode config files

```bash
mkdir -p ~/.config/opencode/oh-my-opencode-slim
cp opencode/opencode.jsonc ~/.config/opencode/
cp opencode/oh-my-opencode-slim.json ~/.config/opencode/
cp opencode/oh-my-opencode-slim/orchestrator_append.md ~/.config/opencode/oh-my-opencode-slim/
```

### 2. Set up the graph-verifier MCP

```bash
mkdir -p ~/.local/graph-verifier-mcp
cp mcp/graph-verifier/server.py ~/.local/graph-verifier-mcp/
cp mcp/graph-verifier/run.sh ~/.local/graph-verifier-mcp/
chmod +x ~/.local/graph-verifier-mcp/run.sh
```

### 3. Set up the Python venv

```bash
python3.12 -m venv ~/.local/beads-venv
~/.local/beads-venv/bin/pip install fastmcp beads-mcp
```

### 4. Fix the beads-mcp shebang (if needed)

```bash
bash scripts/fix-beads-shebang.sh
```

This checks whether `~/.local/beads-venv/bin/beads-mcp` has a broken shebang (pointing to `/tmp/beads-venv/bin/python3`) and rewrites it to the correct path.

### 5. Set API keys

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
export BIG_PICKLE_API_KEY="bp-..."
```

Add these to your `~/.bashrc`, `~/.zshrc`, or equivalent.

### 6. Start opencode

```bash
opencode
```

## How to Verify Everything Works

### Verify MCP servers

In an opencode session (or with `opencode mcp`), check that both MCP servers respond to `tools/list`:

- **beads** — run via `/root/.local/beads-venv/bin/beads-mcp`
- **graph-verifier** — run via `/root/.local/graph-verifier-mcp/run.sh`

```bash
opencode mcp list
```

You should see entries for `beads` and `graph-verifier`.

### Submit a sample graph

Use the `submit_graph` tool with a minimal graph:

```json
{
  "nodes": [
    {
      "id": "n1",
      "description": "Verify the codebase structure",
      "specialist_type": "explorer",
      "depends_on": [],
      "expected_tool_calls": 3,
      "acceptance_criteria": "Report directory layout"
    }
  ],
  "proposed_waves": {"0": ["n1"]}
}
```

Expected response: `status: "approved"` with a `graph_id`.

## Architecture

### Graph-Verifier MCP Protocol

The graph-verifier server implements a **mandatory pre-dispatch protocol** that every orchestrator must follow:

```
┌────────────────────────────────────────────────────┐
│               Mandatory Sequence                    │
├────────────────────────────────────────────────────┤
│ 1. submit_graph(graph)         → approved/rejected │
│ 2. get_next_wave()             → tickets to dispatch│
│ 3. report_lane_result(id, ...) → per completed lane │
│ 4. review_lanes()              → terminate stale    │
│ 5. Repeat 2-4 until all_complete                    │
└────────────────────────────────────────────────────┘
```

**Tools provided:**

| Tool | Description |
|------|-------------|
| `submit_graph` | Submit and validate a dependency graph. Validates cycles, dependency integrity, wave correctness, synthetic decomposition, and concurrency ceiling. |
| `get_next_wave` | Get the next batch of ready-to-execute tickets (dependencies all satisfied). Returns tickets to dispatch as parallel background subagents. |
| `report_lane_result` | Report the outcome of a completed/failed/terminated lane. |
| `review_lanes` | Review active lanes and get CONTINUE/TERMINATE recommendations based on budget, duplication, and progress signals. |
| `get_state` | Full state snapshot of a graph — all tickets, waves, statuses, counts. |

### Model Architecture

| Role | Model | Provider |
|------|-------|----------|
| Orchestrator | `moonshotai/kimi-k2.7-code` | OpenRouter |
| Oracle | `opencode/big-pickle` | Big Pickle |
| Librarian | `opencode/big-pickle` | Big Pickle |
| Explorer | `opencode/big-pickle` | Big Pickle |
| Designer | `opencode/big-pickle` | Big Pickle |
| Fixer | `opencode/big-pickle` | Big Pickle |

### File Layout

```
~/.config/opencode/
├── opencode.jsonc                        # Main config with MCP entries
├── oh-my-opencode-slim.json              # Model presets
└── oh-my-opencode-slim/
    └── orchestrator_append.md            # Orchestrator prompt (graph-first)

~/.local/graph-verifier-mcp/
├── server.py                             # Graph-verifier MCP server
└── run.sh                                # Launcher script

~/.local/beads-venv/                      # Python venv (fastmcp + beads-mcp)
```

## Tmux Launcher

For a persistent session, use tmux:

```bash
tmux new-session -s opencode -d 'opencode'
tmux attach -t opencode
```

Or create a session that also tails logs:

```bash
tmux new-session -s opencode -d
tmux send-keys -t opencode 'opencode 2> ~/opencode.log' Enter
tmux attach -t opencode
```

## Path Notes

The config files use absolute paths (`/root/.local/...`) because opencode's MCP configuration does not expand `~` in command arrays. The install script copies files to these same absolute paths. If your home directory is not `/root` (e.g., `/home/yourname`), edit `~/.config/opencode/opencode.jsonc` and `~/.local/graph-verifier-mcp/run.sh` to use your actual home path.

## Skills

This harness relies on the **oh-my-opencode-slim** plugin, which provides several built-in skills. See [docs/skills.md](docs/skills.md) for the full reference.

The skills (`reflect`, `simplify`, `worktrees`, `deepwork`, `clonedeps`, `codemap`) are fetched automatically from npm when the plugin loads — you do not need to copy them manually. The only custom prompt in this harness is `opencode/oh-my-opencode-slim/orchestrator_append.md`.

## License

MIT
