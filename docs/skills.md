# Skills Reference

The oh-my-opencode-slim plugin automatically provides these skills. They are fetched from npm when the plugin loads, so you do **not** need to copy them manually:

- `reflect` — Review recent work and suggest reusable skills/agents/commands.
- `simplify` — Simplify code for clarity without changing behavior.
- `worktrees` — Manage Git worktrees as isolated coding lanes.
- `deepwork` — Heavy coding sessions, multi-phase implementation, risky refactors.
- `clonedeps` — Clone dependency source code locally for inspection.
- `codemap` — Generate hierarchical codemaps for unfamiliar repositories.

These are **not** custom prompts — they are part of the oh-my-opencode-slim plugin distribution.

The only custom prompt in this harness is `opencode/oh-my-opencode-slim/orchestrator_append.md`, which adds the graph-verifier gate and parallel-dispatch discipline on top of the base oh-my-opencode-slim orchestrator.
