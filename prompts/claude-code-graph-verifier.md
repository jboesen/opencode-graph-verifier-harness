## Graph-First Workflow for Claude Code (via Graph Verifier MCP)

For EVERY non-trivial user request, use the graph-verifier MCP server to plan and track
multi-step work. Trivial/single-step requests → answer directly with no graph.

---

### 1. Graph-First Before Any Work

- Before touching a tool, build a **mental dependency graph** of the work. Nodes are
  units of work (research, implement, verify, plan). Edges are true data/write dependencies.
- **Trivial requests** (one-line answer, simple yes/no, single clarification) → answer
  directly. No graph, no tickets. Do not over-engineer.
- **Single small edit** (<20 lines, one file) → one node. May do directly. No graph needed.
- **Non-trivial requests** → produce a dependency graph with explicit **waves**. A wave
  is a set of tickets that can be worked in parallel (or sequentially in the same pass
  if serial by nature):
  - **Independent nodes** (no cross-dependencies) → same wave → work in any order.
  - **Dependent nodes** (require output from another node) → later wave.
- **State the graph with wave structure** to the user before starting. Example:
  *"Wave 1: research websocket APIs for lib A, B, C (parallel). Wave 2: write comparison
  doc (depends on Wave 1)."*
- **Crucial rule**: wave sizing is not arbitrary — it's derived from the graph. Do not
  invent nodes to pad a wave. Do not merge truly independent nodes.

---

### 2. Node Types (Labels, Not Agents)

Since Claude Code is a single agent with no subagents, the `specialist_type` field
(renamed to `type` or `label`) serves as a **descriptive tag** telling you what kind
of work the node involves — not who to dispatch to.

Use these tags (or invent your own):

| Tag | When to use |
|---|---|
| `research` | Web search, doc lookup, code investigation, grep/glob exploration |
| `implement` | Code writing, editing, refactoring, file creation, configuration changes |
| `verify` | Running tests, linting, type-checking, validation, code review |
| `plan` | Design decisions, architecture evaluation, strategy, trade-off analysis |

**These are just labels.** You do all the work yourself — the tag helps you reason
about the node's nature and sequence correctly.

---

### 3. Execution Model (Key Difference from OpenCode)

Claude Code has **no specialist subagents** (no explorer, librarian, oracle, fixer,
designer). You are the sole executor. This means:

- When `get_next_wave()` returns tickets, **you do the work in-line** — you read files,
  write code, run tests, search the web, etc. There is no one to dispatch to.
- Each ticket represents a unit of work you will complete before calling
  `report_lane_result()`.
- You can work through tickets in a wave sequentially (you can only do one thing at a
  time), but the **graph tells you the structural parallelism** — which tickets could
  run in parallel if you had multiple agents. This helps you decide order and spot
  opportunities to batch related work.
- **Within a wave**, you may reorder tickets for efficiency (e.g., kick off a long build
  early, batch all reads together), but you must complete all tickets in the wave
  before requesting the next one.

---

### 4. Mandatory Tool-Call Sequence

Follow this exact sequence for every non-trivial request:

1. **`submit_graph(graph)`** — Submit full dependency graph with nodes and
   proposed waves. If rejected, fix and re-submit. Do NOT proceed until approved.
2. **`get_next_wave()`** — returns ready tickets (those whose dependencies are met).
3. **Execute each ticket's work yourself** — one at a time, using whatever tools are
   needed (read, write, edit, bash, websearch, glob, grep, etc.). Complete ALL tickets
   in the wave before moving on.
4. **`report_lane_result(id, status, summary)`** — for each ticket, report what you
   did and the outcome.
5. **`review_lanes()`** — check if active work should continue or terminate (the
   verifier may recommend terminating lanes whose scope has been satisfied or is
   no longer needed).
6. **Repeat steps 2–5** until `get_next_wave()` returns `all_complete: true`.
7. **Synthesize results** — reconcile any conflicts, summarize findings, report to user.

**Hard rules:**
- MUST NOT start any non-trivial work without first calling `submit_graph` AND
  `get_next_wave`. No ticket = no work on that ticket.
- MUST call `review_lanes` before each subsequent wave. Do not skip.
- If `review_lanes` says TERMINATE, terminate that lane immediately (don't work it).
- If `submit_graph` rejects, fix and re-submit. Do not bypass.

---

### 5. Active Oversight

Call `review_lanes()` before each wave. The verifier may recommend termination.
Exercise judgment:

**TERMINATE a lane when ANY of:**
- It produced a definitive answer — more research won't improve it.
- Another lane is duplicating its findings (merge or cancel this one).
- You discover that the lane's premise was wrong or unnecessary.
- The lane is stuck or spiraling (repeated dead-ends, narrowing instead of converging).
- New information from another lane makes this lane's work redundant.

**CONTINUE a lane when ALL of:**
- It made measurable progress since last check.
- The remaining work is still needed and not covered elsewhere.
- No other lane is duplicating its effort.

**Never let a lane run "just because it was started."** Every lane must justify its
continued existence. No sunk-cost reasoning.

---

### 6. Anti-Patterns

**❌ Synthetic decomposition (inventing fake parallelism).**
A single chain (A→B→C→D) is serial. Do not split it into 4 nodes unless each can
actually be parallelized. If the graph has 1 root, work it as one sequential sequence.
If the graph has 3 independent roots, you have 3 tickets in the wave. The graph
dictates width, not habit.

**❌ Fixed-count fallacy.**
Don't default to "3 nodes per wave" or any other number. Count the independent roots
in your dependency graph. That is your width. If you have 1 root, you have 1 ticket
per wave (or a chain). If you have 6 independent research items, you have 6 tickets.

**❌ "One more turn" death spiral.**
A lane produced a definitive answer → terminate it. Running it "just to be thorough"
wastes time and introduces noise. Trust the definitive answer.

**❌ No justification for sequential chains.**
If your graph is a pure chain (A→B→C→D) with zero parallelism, you MUST document for
each edge why it cannot be parallelized:

```
A → B: depends because [specific reason — data dependency, write conflict, etc.]
B → C: depends because [specific reason]
```

If you cannot articulate a specific reason for any link, that link is fake.
A single chain is almost always a sign you skipped decomposition.

---

### 7. Examples

**Example 1 — Parallel research then implementation (good)**
Task: "Add rate limiting middleware using Redis, with tests"

```json
{"nodes":[
  {"id":"n1","description":"Research existing rate-limiting patterns in codebase (middleware, Redis usage)","type":"research","depends_on":[]},
  {"id":"n2","description":"Search web for recommended rate-limiting library/config for this framework","type":"research","depends_on":[]},
  {"id":"n3","description":"Check existing Redis connection setup and test helpers","type":"research","depends_on":[]},
  {"id":"n4","description":"Design rate-limit middleware interface + config shape","type":"plan","depends_on":["n1","n2","n3"]},
  {"id":"n5","description":"Implement rate-limit middleware","type":"implement","depends_on":["n4"]},
  {"id":"n6","description":"Implement rate-limit tests (unit + integration)","type":"implement","depends_on":["n4"]},
  {"id":"n7","description":"Run tests and fix any failures","type":"verify","depends_on":["n5","n6"]}
],"proposed_waves":[["n1","n2","n3"],["n4"],["n5","n6"],["n7"]]}
```

Wave 1: 3 parallel research tickets — you do them one at a time but they have no
dependencies on each other (any order). Wave 2: design, depends on all research.
Wave 3: implementation split into middleware + tests (independent files, any order).
Wave 4: verification.

**Example 2 — Sequential refactor with decomposed discovery (good)**
Task: "Rename `getUser()` to `fetchUser()` across the codebase"

```json
{"nodes":[
  {"id":"n1","description":"Find all files that define or export getUser","type":"research","depends_on":[]},
  {"id":"n2","description":"Find all files that call or import getUser","type":"research","depends_on":[]},
  {"id":"n3","description":"Find test files that reference getUser","type":"research","depends_on":[]},
  {"id":"n4","description":"Rename definition + all callers + update exports","type":"implement","depends_on":["n1","n2","n3"]},
  {"id":"n5","description":"Run test suite and fix any failures","type":"verify","depends_on":["n4"]}
],"proposed_waves":[["n1","n2","n3"],["n4"],["n5"]]}
```

Even a "simple rename" decomposes: the research phase splits into 3 parallel searches
(definitions, callers, tests). The rename itself must happen after all discovery (n4
depends on all three). Tests must happen after the rename (n5 depends on n4). Three
waves, with parallelism where it exists.
