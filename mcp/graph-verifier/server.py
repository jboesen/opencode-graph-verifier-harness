#!/usr/bin/env python3
"""Graph Verifier MCP Server — validates, tracks, and manages graph execution."""

import asyncio
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from fastmcp import FastMCP
from graph_view import start_graph_view

# ---------------------------------------------------------------------------
# Logging — all to stderr (stdout is JSON-RPC)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("graph-verifier")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

VALID_SPECIALISTS = {"explorer", "librarian", "oracle", "designer", "fixer"}
MAX_CONCURRENCY = 8


@dataclass
class Ticket:
    id: str
    node_id: str
    graph_id: str
    description: str
    specialist_type: str
    depends_on: list[str]
    expected_tool_calls: int
    acceptance_criteria: str
    context_hints: str
    wave: int
    status: str = "pending"  # pending | active | completed | failed | terminated
    active_since: float | None = None
    completed_at: float | None = None
    result: dict | None = None
    tool_calls_used: int = 0
    error: str | None = None


@dataclass
class GraphState:
    graph_id: str
    nodes: list[dict]
    tickets: dict[str, Ticket]  # ticket_id -> Ticket
    waves: dict[int, list[str]]  # wave_number -> [ticket_id, ...]
    proposed_waves: dict[int, list[str]]
    warnings: list[str]
    created_at: float
    max_concurrency: int = MAX_CONCURRENCY


# In-memory store
graphs: dict[str, GraphState] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_set(text: str) -> set[str]:
    """Split text into lowercase tokens."""
    return set(text.lower().split())


def jaccard_similarity(text_a: str, text_b: str) -> float:
    tokens_a = _token_set(text_a)
    tokens_b = _token_set(text_b)
    if not tokens_a and not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def find_roots(nodes: list[dict]) -> list[str]:
    return [n["id"] for n in nodes if not n.get("depends_on")]


def detect_cycle(nodes: list[dict]) -> tuple[bool, list[str]]:
    """DFS-based cycle detection. Returns (has_cycle, cycle_path)."""
    node_ids = {n["id"] for n in nodes}
    # Build adjacency
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep in node_ids:
                adj[dep].append(n["id"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n["id"]: WHITE for n in nodes}
    parent: dict[str, str | None] = {n["id"]: None for n in nodes}
    cycle_path: list[str] = []

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color[v] == GRAY:
                # Found cycle — reconstruct
                cur: str | None = u
                cycle_path.clear()
                while cur is not None and cur != v:
                    cycle_path.append(cur)
                    cur = parent.get(cur)
                cycle_path.append(v)
                if cur == v:
                    cycle_path.reverse()
                else:
                    # fallback: just report u->v
                    cycle_path.clear()
                    cycle_path.append(u)
                    cycle_path.append(v)
                return True
            if color[v] == WHITE:
                parent[v] = u
                if dfs(v):
                    return True
        color[u] = BLACK
        return False

    for n in nodes:
        if color[n["id"]] == WHITE:
            if dfs(n["id"]):
                return True, cycle_path
    return False, []


def compute_waves(nodes: list[dict]) -> dict[int, list[str]]:
    """Assign nodes to waves via topological sort (BFS / Kahn's)."""
    node_map = {n["id"]: n for n in nodes}
    in_degree: dict[str, int] = {}
    # depends_on lists explicitly
    for n in nodes:
        in_degree[n["id"]] = len(n.get("depends_on", []))

    roots = [n["id"] for n in nodes if in_degree[n["id"]] == 0]
    # Build adjacency: node -> list of dependents
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep in adj:
                adj[dep].append(n["id"])

    waves: dict[int, list[str]] = {}
    wave = 0
    queue = list(roots)
    visited: set[str] = set()

    while queue:
        current_wave_nodes = list(queue)
        queue.clear()
        wave_nodes = []
        for uid in current_wave_nodes:
            if uid in visited:
                continue
            visited.add(uid)
            wave_nodes.append(uid)
            for dep_id in adj.get(uid, []):
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)
        if wave_nodes:
            waves[wave] = wave_nodes
            wave += 1

    return waves


def _compute_earliest_wave(nodes: list[dict]) -> dict[str, int]:
    """Return dict mapping node_id -> earliest_valid_wave."""
    node_map = {n["id"]: n for n in nodes}
    wave_of: dict[str, int] = {}
    # Process nodes in topological order via Kahn
    in_degree = {n["id"]: len(n.get("depends_on", [])) for n in nodes}
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep in adj:
                adj[dep].append(n["id"])

    queue: list[str] = [n["id"] for n in nodes if in_degree[n["id"]] == 0]
    for r in queue:
        wave_of[r] = 0

    while queue:
        u = queue.pop(0)
        for v in adj.get(u, []):
            in_degree[v] -= 1
            w = wave_of.get(u, 0) + 1
            if v not in wave_of or w > wave_of[v]:
                wave_of[v] = w
            if in_degree[v] == 0:
                queue.append(v)

    return wave_of


def _build_node_map(nodes: list[dict]) -> dict[str, dict]:
    return {n["id"]: n for n in nodes}


def _serialize_state(state: GraphState) -> dict:
    """Return graph data in a stable form for the state tool and web view."""
    tickets = [asdict(ticket) for ticket in state.tickets.values()]
    status_counts: dict[str, int] = {}
    for ticket in state.tickets.values():
        status_counts[ticket.status] = status_counts.get(ticket.status, 0) + 1
    return {
        "graph_id": state.graph_id,
        "created_at": state.created_at,
        "warnings": state.warnings,
        "max_concurrency": state.max_concurrency,
        "waves": {str(key): value for key, value in state.waves.items()},
        "tickets": tickets,
        "status_counts": status_counts,
        "total_tickets": len(tickets),
    }


def _get_view_graph(graph_id: str) -> dict | None:
    state = graphs.get(graph_id)
    return _serialize_state(state) if state else None


def _list_view_graphs() -> list[dict]:
    return [
        {"graph_id": state.graph_id, "created_at": state.created_at,
         "total_tickets": len(state.tickets)}
        for state in sorted(graphs.values(), key=lambda item: item.created_at,
                            reverse=True)
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_graph(
    graph: dict,
    max_concurrency: int,
    valid_specialists: set[str] | None = None,
) -> dict:
    """
    Validate graph definition. Returns dict with keys:
      - valid: bool
      - issues: list[str]  (if invalid)
      - warnings: list[str]
      - computed_waves: dict (only if valid)
    """
    nodes = graph.get("nodes", [])
    proposed_waves = graph.get("proposed_waves", {})
    issues: list[str] = []
    warnings: list[str] = []
    node_map = _build_node_map(nodes)

    # -- 0. Basic structure --
    if not nodes:
        return {"valid": False, "issues": ["No nodes in graph"]}

    # -- 6. Specialist type validation --
    effective_specialists = valid_specialists or VALID_SPECIALISTS
    for n in nodes:
        sp = n.get("specialist_type", "")
        if sp not in effective_specialists:
            issues.append(
                f"Node '{n['id']}': invalid specialist_type '{sp}'. "
                f"Must be one of {sorted(effective_specialists)}"
            )

    # -- 1. Cycle detection --
    has_cycle, cycle_path = detect_cycle(nodes)
    if has_cycle:
        issues.append(f"cycle_detected: {' -> '.join(cycle_path)}")

    # -- 2. Dependency integrity --
    all_ids = {n["id"] for n in nodes}
    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep not in all_ids:
                issues.append(
                    f"invalid_dependency: node '{n['id']}' depends on "
                    f"'{dep}' which does not exist"
                )

    # -- 3. Wave correctness --
    if proposed_waves:
        earliest = _compute_earliest_wave(nodes)
        for wave_str, node_list in proposed_waves.items():
            try:
                wave_num = int(wave_str)
            except ValueError:
                issues.append(f"invalid wave key: '{wave_str}'")
                continue
            for nid in node_list:
                ew = earliest.get(nid, 0)
                if wave_num < ew:
                    issues.append(
                        f"wave_dependency_violation: node '{nid}' "
                        f"proposed in wave {wave_num} but earliest "
                        f"valid wave is {ew}"
                    )

    if issues:
        return {"valid": False, "issues": issues}

    # -- 4. Synthetic decomposition --
    roots = find_roots(nodes)
    root_count = len(roots)
    wave0 = proposed_waves.get("0", [])
    extra_nodes = [nid for nid in wave0 if nid not in roots]
    if extra_nodes and wave0:
        # Check similarity among extra nodes
        high_sim = False
        for i in range(len(extra_nodes)):
            for j in range(i + 1, len(extra_nodes)):
                nid_a = extra_nodes[i]
                nid_b = extra_nodes[j]
                desc_a = node_map.get(nid_a, {}).get("description", "")
                desc_b = node_map.get(nid_b, {}).get("description", "")
                sim = jaccard_similarity(desc_a, desc_b)
                if sim > 0.7:
                    high_sim = True
                    break
            if high_sim:
                break
        if high_sim:
            issues.append(
                f"synthetic_decomposition: wave 0 has {len(wave0)} nodes "
                f"but only {root_count} roots; extra nodes have high "
                f"description similarity (>0.7)"
            )
            return {"valid": False, "issues": issues}
        else:
            warnings.append(
                f"low_parallelism: wave 0 has {len(wave0)} nodes but "
                f"only {root_count} are true roots; consider consolidating"
            )

    # -- 5. Concurrency ceiling --
    for wave_str, node_list in proposed_waves.items():
        count = len(node_list)
        if count > max_concurrency:
            issues.append(
                f"exceeds_max_width: wave {wave_str} has {count} nodes "
                f"(max {max_concurrency})"
            )

    if issues:
        return {"valid": False, "issues": issues}

    # Compute waves
    computed_waves = compute_waves(nodes)

    return {
        "valid": True,
        "issues": [],
        "warnings": warnings,
        "computed_waves": computed_waves,
    }


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="GraphVerifier",
    instructions="""Graph Verifier MCP — Mandatory Pre-Dispatch Protocol for Orchestrators

You MUST call this server before dispatching any subagent work. No ticket = no dispatch.

USE PARALLEL SUBAGENTS. When get_next_wave returns multiple tickets, dispatch ALL returned tickets as parallel subagent tasks. Do NOT run sequentially. Do NOT do the work yourself — you orchestrate, you do not execute.

=== MANDATORY SEQUENCE (always follow this order) ===
1. submit_graph — Submit your dependency graph (nodes + proposed_waves). If rejected, fix issues and re-submit. Do NOT dispatch until approved.
2. get_next_wave — Get ready tickets. Dispatch ALL of them as parallel subagent tasks in a single response. Do not stagger them.
3. report_lane_result — As each lane completes, report the result back to this server.
4. review_lanes — Before dispatching the next wave, review active lanes. TERMINATE any lane recommended \"terminate\".
5. Repeat steps 2-4 until get_next_wave returns all_complete: true.
6. Synthesize results and report to the user.

=== DECOMPOSITION PRESSURE ===
Before building the graph, challenge EVERY node. Ask: \"Can this be split into 2+ independent parallel subtasks that don't conflict?\" For sequential chains (A→B→C→D), challenge EVERY link: \"Does B truly depend on ALL of A's output, or just a piece of it?\" Only keep the chain sequential if there is a true data-dependency or write-conflict between consecutive nodes. Default to parallel.

=== GRAPH INPUT FORMAT ===
- nodes: list of objects — each node requires:
    - id (string): unique identifier
    - description (string): what work this node does
    - specialist_type (string): one of explorer, librarian, oracle, designer, fixer
    - depends_on (list of strings): node IDs this depends on (empty list for roots)
    - expected_tool_calls (int): estimated tool-call budget
    - acceptance_criteria (string): what defines completion
    - context_hints (string, optional): hints for the subagent
- proposed_waves (object): maps wave-number strings to node-ID lists, e.g. {\"0\":[\"n1\"],\"1\":[\"n2\"]}
    - Wave 0 = independent roots (all deps satisfied)
    - Later waves = nodes whose dependencies complete in earlier waves

=== FULL EXAMPLE — multi-file feature \"add user auth\" (8 nodes, 4 waves) ===
Input JSON:
{\"nodes\":[
  {\"id\":\"n1\",\"description\":\"Explore existing auth patterns\",\"specialist_type\":\"explorer\",\"depends_on\":[],\"expected_tool_calls\":5,\"acceptance_criteria\":\"List of existing auth patterns found\"},
  {\"id\":\"n2\",\"description\":\"Explore user model schema\",\"specialist_type\":\"explorer\",\"depends_on\":[],\"expected_tool_calls\":4,\"acceptance_criteria\":\"DB schema for users documented\"},
  {\"id\":\"n3\",\"description\":\"Research auth library best practices\",\"specialist_type\":\"librarian\",\"depends_on\":[],\"expected_tool_calls\":6,\"acceptance_criteria\":\"Best practices doc with 3+ sources\"},
  {\"id\":\"n4\",\"description\":\"Design auth API surface\",\"specialist_type\":\"oracle\",\"depends_on\":[\"n1\",\"n2\",\"n3\"],\"expected_tool_calls\":4,\"acceptance_criteria\":\"API design doc approved\"},
  {\"id\":\"n5\",\"description\":\"Implement user model\",\"specialist_type\":\"fixer\",\"depends_on\":[\"n4\"],\"expected_tool_calls\":8,\"acceptance_criteria\":\"User model code committed\"},
  {\"id\":\"n6\",\"description\":\"Implement login endpoint\",\"specialist_type\":\"fixer\",\"depends_on\":[\"n4\"],\"expected_tool_calls\":8,\"acceptance_criteria\":\"Login endpoint working\"},
  {\"id\":\"n7\",\"description\":\"Write auth tests\",\"specialist_type\":\"fixer\",\"depends_on\":[\"n5\",\"n6\"],\"expected_tool_calls\":6,\"acceptance_criteria\":\"All tests pass\"},
  {\"id\":\"n8\",\"description\":\"Review for security\",\"specialist_type\":\"oracle\",\"depends_on\":[\"n5\",\"n6\"],\"expected_tool_calls\":3,\"acceptance_criteria\":\"Security review complete\"}
],\"proposed_waves\":{\"0\":[\"n1\",\"n2\",\"n3\"],\"1\":[\"n4\"],\"2\":[\"n5\",\"n6\"],\"3\":[\"n7\",\"n8\"]}}

Execution pattern:
- Wave 0: dispatch n1, n2, n3 as 3 parallel subagent tasks (explorers + librarian)
- Wave 1: after all 3 complete, dispatch n4 (designer/oracle)
- Wave 2: after design, dispatch n5 AND n6 as 2 parallel fixer tasks
- Wave 3: after both fixers, dispatch n7 AND n8 as parallel tasks (tests + security review)

=== ANTI-PATTERN WARNING ===
Do NOT submit trivial sequential chains A→B→C→D unless EVERY link has a true data/write-conflict dependency. If 3 research tasks are independent, put them ALL in wave 0 — NOT in a chain. Challenge every node: \"Could this run in parallel with something else?\" If yes, make it parallel.""",
)


@mcp.tool(
    name="submit_graph",
    description=(
        "Submit and validate a task graph before dispatching any work. "
        "This is the FIRST call you must make — no ticket = no dispatch.\n\n"
        "=== INPUT SCHEMA ===\n"
        "graph: object with:\n"
        "  - nodes (list, required): each node has:\n"
        "      - id (string): unique node identifier\n"
        "      - description (string): what work this node does\n"
        "  - specialist_type (string): one of the configured specialist types "
        "(default: \"explorer\", \"librarian\", \"oracle\", \"designer\", \"fixer\")\n"
        "      - depends_on (list of strings): node IDs this depends on; "
        "empty list for root/independent nodes\n"
        "      - expected_tool_calls (int): estimated tool-call budget\n"
        "      - acceptance_criteria (string): what constitutes completion\n"
        "      - context_hints (string, optional): guidance for the subagent\n"
        "  - proposed_waves (object, required): maps wave-number strings to "
        "node-ID lists, e.g. {\"0\":[\"n1\"],\"1\":[\"n2\"]}\n"
        "max_concurrency: optional int, default 8, max 8\n\n"
        "=== SPECIALIST TYPE ENUM (configurable) ===\n"
        "Default set:\n"
        "- \"explorer\": investigates codebase, finds files, maps structure\n"
        "- \"librarian\": researches docs, best practices, libraries\n"
        "- \"oracle\": makes design decisions, reviews, approves\n"
        "- \"designer\": creates specs, schemas, architecture\n"
        "- \"fixer\": implements code changes, writes tests\n"
        "Pass `valid_specialists` to override.\n\n"
        "=== EXAMPLE JSON ===\n"
        '{\"nodes\":[{\"id\":\"n1\",\"description\":\"Search codebase for X\",'
        '\"specialist_type\":\"explorer\",\"depends_on\":[],'
        '\"expected_tool_calls\":5,\"acceptance_criteria\":\"Files found\",'
        '\"context_hints\":\"look in src/\"}],'
        '\"proposed_waves\":{\"0\":[\"n1\"]}}\n\n'
        "=== VALIDATION RULES ===\n"
        "- Cycle detection: rejects graphs with dependency cycles\n"
        "- Dependency integrity: all depends_on IDs must reference existing "
        "nodes\n"
        "- Wave correctness: nodes cannot appear in a wave before their "
        "dependencies are satisfied\n"
        "- Synthetic decomposition: wave-0 nodes beyond true roots are "
        "checked for false parallelism (high description similarity => "
        "rejection)\n"
        "- Concurrency ceiling: no wave can exceed 8 nodes\n"
        "- Specialist type: must be one of the valid enum values above\n\n"
        "Returns approved tickets with a graph_id, or rejection reasons. "
        "If rejected, fix the issues and re-submit before proceeding."
    ),
)
async def submit_graph(
    graph: dict,
    max_concurrency: int = MAX_CONCURRENCY,
    valid_specialists: list[str] | None = None,
) -> dict:
    max_conc = min(max_concurrency, MAX_CONCURRENCY)
    specialists_set = set(valid_specialists) if valid_specialists else None

    result = validate_graph(graph, max_conc, specialists_set)
    if not result["valid"]:
        return {
            "status": "rejected",
            "issues": result["issues"],
            "next_step": (
                "Graph rejected. Fix the issues and re-submit. Do NOT "
                "dispatch any subagents until approved."
            ),
        }

    # Build tickets from nodes
    nodes = graph["nodes"]
    waves = result["computed_waves"]
    warnings = result["warnings"]
    proposed_waves = graph.get("proposed_waves", {})

    graph_id = f"g-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    tickets: dict[str, Ticket] = {}
    node_map = _build_node_map(nodes)

    for w_num_str, node_ids in proposed_waves.items():
        w_num = int(w_num_str)
        for nid in node_ids:
            node = node_map.get(nid)
            if node is None:
                continue
            tid = f"t-{uuid.uuid4().hex[:8]}"
            ticket = Ticket(
                id=tid,
                node_id=nid,
                graph_id=graph_id,
                description=node.get("description", ""),
                specialist_type=node.get("specialist_type", ""),
                depends_on=list(node.get("depends_on", [])),
                expected_tool_calls=node.get("expected_tool_calls", 1),
                acceptance_criteria=node.get("acceptance_criteria", ""),
                context_hints=node.get("context_hints", ""),
                wave=w_num,
            )
            tickets[tid] = ticket

    state = GraphState(
        graph_id=graph_id,
        nodes=nodes,
        tickets=tickets,
        waves=waves,
        proposed_waves=proposed_waves,
        warnings=warnings,
        created_at=time.time(),
        max_concurrency=max_conc,
    )
    graphs[graph_id] = state

    ticket_list = []
    for tid, ticket in tickets.items():
        ticket_list.append(
            {
                "id": ticket.id,
                "node_id": ticket.node_id,
                "description": ticket.description,
                "specialist_type": ticket.specialist_type,
                "depends_on": ticket.depends_on,
                "expected_tool_calls": ticket.expected_tool_calls,
                "acceptance_criteria": ticket.acceptance_criteria,
                "context_hints": ticket.context_hints,
                "wave": ticket.wave,
                "status": ticket.status,
            }
        )

    roots = find_roots(nodes)

    return {
        "status": "approved",
        "graph_id": graph_id,
        "tickets": ticket_list,
        "computed_waves": {str(k): v for k, v in waves.items()},
        "warnings": warnings,
        "parallelism_width": len(roots),
        "next_step": (
            "Graph approved. Call get_next_wave with this graph_id, then "
            "dispatch ALL returned tickets as parallel subagent tasks."
        ),
    }


@mcp.tool(
    name="get_next_wave",
    description=(
        "Get the next batch of ready-to-execute tickets (dependencies all "
        "completed). Transitions them to \"active\" status.\n\n"
        "=== INPUT ===\n"
        "- graph_id (string): from submit_graph response\n"
        "- max_tickets (int, optional): cap on how many tickets to activate\n\n"
        "=== OUTPUT ===\n"
        "- wave_number (int): the wave these tickets belong to\n"
        "- tickets (list): tickets to dispatch (each has id, node_id, "
        "description, specialist_type, expected_tool_calls, "
        "acceptance_criteria, context_hints, wave, depends_on)\n"
        "- active_count (int): currently active tickets\n"
        "- remaining_pending (int): tickets still pending\n"
        "- all_complete (bool): true if all tickets are done\n\n"
        "CRITICAL: When this returns multiple tickets, dispatch ALL of them "
        "as parallel subagent tasks in a single response. Do NOT run "
        "sequentially. Do NOT do the work yourself — you orchestrate, you "
        "do not execute."
    ),
)
async def get_next_wave(
    graph_id: str,
    max_tickets: int | None = None,
) -> dict:
    state = graphs.get(graph_id)
    if state is None:
        return {
            "error": f"graph_id '{graph_id}' not found",
            "next_step": "Check the graph_id. If lost, submit a new graph.",
        }

    pending_tickets = [
        t for t in state.tickets.values() if t.status == "pending"
    ]
    if not pending_tickets:
        # All tickets are complete or no pending work
        all_active = [t for t in state.tickets.values() if t.status == "active"]
        if not all_active:
            return {
                "all_complete": True,
                "tickets": [],
                "next_step": (
                    "All complete. Synthesize results and report to the user."
                ),
            }
        return {
            "all_complete": False,
            "tickets": [],
            "active_count": len(all_active),
            "remaining_pending": 0,
            "next_step": (
                f"{len(all_active)} lane(s) still active. Wait for them to "
                "complete, then call get_next_wave."
            ),
        }

    # Check which dependencies are completed
    completed_ids: set[str] = {
        t.node_id
        for t in state.tickets.values()
        if t.status in ("completed", "failed", "terminated")
    }

    # Build node_id -> ticket mapping
    node_to_ticket: dict[str, Ticket] = {}
    for t in state.tickets.values():
        node_to_ticket[t.node_id] = t

    ready_tickets: list[Ticket] = []
    unready_info: list[dict] = []

    for ticket in pending_tickets:
        deps = ticket.depends_on
        missing = [d for d in deps if d not in completed_ids]
        if not missing:
            ready_tickets.append(ticket)
        else:
            unready_info.append(
                {
                    "ticket_id": ticket.id,
                    "node_id": ticket.node_id,
                    "missing_dependencies": missing,
                }
            )

    if not ready_tickets:
        # Blocked — report unready tickets
        return {
            "error": "blocked",
            "unready_tickets": unready_info,
            "all_complete": False,
            "next_step": (
                "No tickets ready. Check active lanes with review_lanes."
            ),
        }

    # Count currently active
    active_count = len(
        [t for t in state.tickets.values() if t.status == "active"]
    )
    capacity = state.max_concurrency - active_count
    if capacity <= 0:
        return {
            "error": "at_max_concurrency",
            "active_count": active_count,
            "remaining_pending": len(pending_tickets),
            "next_step": (
                f"At max concurrency ({active_count} active). Wait for "
                "active lanes to complete, then call get_next_wave."
            ),
        }

    # Activate tickets up to capacity or max_tickets
    if max_tickets is not None:
        capacity = min(capacity, max_tickets)

    to_activate = ready_tickets[:capacity]
    now = time.time()
    activated = []
    for ticket in to_activate:
        ticket.status = "active"
        ticket.active_since = now
        activated.append(
            {
                "id": ticket.id,
                "node_id": ticket.node_id,
                "description": ticket.description,
                "specialist_type": ticket.specialist_type,
                "expected_tool_calls": ticket.expected_tool_calls,
                "acceptance_criteria": ticket.acceptance_criteria,
                "context_hints": ticket.context_hints,
                "wave": ticket.wave,
                "depends_on": ticket.depends_on,
            }
        )

    # Find the wave number from the activated tickets
    wave_numbers = sorted(set(t.wave for t in to_activate))
    wave_number = wave_numbers[0] if wave_numbers else 0

    remaining_pending = len(
        [t for t in state.tickets.values() if t.status == "pending"]
    )
    new_active_count = len(
        [t for t in state.tickets.values() if t.status == "active"]
    )
    all_complete = remaining_pending == 0 and new_active_count == 0

    return {
        "wave_number": wave_number,
        "tickets": activated,
        "active_count": new_active_count,
        "remaining_pending": remaining_pending,
        "all_complete": all_complete,
        "next_step": (
            f"Dispatch ALL {len(activated)} ticket(s) as parallel subagent "
            "tasks NOW. After each completes, call report_lane_result."
        ),
    }


@mcp.tool(
    name="report_lane_result",
    description=(
        "Report the outcome of a dispatched lane/ticket. Call this as each "
        "subagent completes its work.\n\n"
        "=== INPUT ===\n"
        "- graph_id (string): from submit_graph response\n"
        "- ticket_id (string): the ticket id returned by get_next_wave\n"
        "- status (string): \"completed\", \"failed\", or \"terminated\"\n"
        "- result (object, optional): must contain:\n"
        "    - summary (string): brief summary of what was done\n"
        "    - artifacts (list of strings): file paths or references "
        "produced\n"
        "    - key_findings (list of strings): important discoveries\n"
        "- tool_calls_used (int): how many tool calls the subagent made\n"
        "- error (string, optional): error message if status is \"failed\"\n\n"
        "=== OUTPUT ===\n"
        "- acknowledged (bool): always true on success\n"
        "- ticket_status (string): the status you reported\n"
        "- unblocked_tickets (list of strings): ticket IDs now ready\n"
        "- next_wave_ready (bool): true if new tickets are unblocked\n"
        "- active_count (int): currently active tickets\n"
        "- completed_count (int): tickets completed so far\n"
        "- all_complete (bool): true if every single ticket is done\n\n"
        "=== NEXT STEP ===\n"
        "After reporting:\n"
        "- If next_wave_ready is true -> call get_next_wave immediately\n"
        "- If all_complete is true -> synthesize results and report to user"
    ),
)
async def report_lane_result(
    graph_id: str,
    ticket_id: str,
    status: str,
    result: dict | None = None,
    tool_calls_used: int = 0,
    error: str | None = None,
) -> dict:
    state = graphs.get(graph_id)
    if state is None:
        return {
            "error": f"graph_id '{graph_id}' not found",
            "next_step": "Check the graph_id. If lost, submit a new graph.",
        }

    ticket = state.tickets.get(ticket_id)
    if ticket is None:
        return {
            "error": f"ticket_id '{ticket_id}' not found",
            "next_step": "Verify the ticket_id. Check get_state for valid tickets.",
        }

    if status not in ("completed", "failed", "terminated"):
        return {
            "error": f"invalid status '{status}'",
            "next_step": "Use one of: completed, failed, terminated.",
        }

    ticket.status = status
    ticket.completed_at = time.time()
    ticket.result = result
    ticket.tool_calls_used = tool_calls_used
    if error:
        ticket.error = error

    # Find newly-unblocked pending tickets
    completed_ids: set[str] = {
        t.node_id
        for t in state.tickets.values()
        if t.status in ("completed", "failed", "terminated")
    }

    unblocked: list[str] = []
    for t in state.tickets.values():
        if t.status == "pending":
            deps = t.depends_on
            if all(d in completed_ids for d in deps):
                unblocked.append(t.id)

    active_count = len(
        [t for t in state.tickets.values() if t.status == "active"]
    )
    completed_count = len(
        [t for t in state.tickets.values() if t.status == "completed"]
    )
    remaining = len(
        [t for t in state.tickets.values() if t.status == "pending"]
    )
    all_complete = remaining == 0 and active_count == 0

    result = {
        "acknowledged": True,
        "ticket_status": status,
        "unblocked_tickets": unblocked,
        "next_wave_ready": len(unblocked) > 0,
        "active_count": active_count,
        "completed_count": completed_count,
        "all_complete": all_complete,
    }
    if all_complete:
        result["next_step"] = (
            "All work complete. Synthesize and report to user."
        )
    elif len(unblocked) > 0:
        result["next_step"] = (
            "New tickets unblocked. Call get_next_wave and dispatch "
            "them as parallel subagent tasks."
        )
    return result


@mcp.tool(
    name="review_lanes",
    description=(
        "Review all currently-active lanes and get CONTINUE/TERMINATE "
        "recommendations. Call this BEFORE dispatching the next wave.\n\n"
        "=== INPUT ===\n"
        "- graph_id (string): from submit_graph response\n\n"
        "=== OUTPUT ===\n"
        "- active_lanes (list): each entry has ticket_id, node_id, "
        "recommendation (\"continue\"|\"terminate\"), "
        "recommendation_reason, tool_calls_used, expected_tool_calls, "
        "redundant_with\n"
        "- summary (object): total_active, recommend_continue, "
        "recommend_terminate, completed, failed\n\n"
        "=== CRITICAL ===\n"
        "If a lane is recommended \"terminate\", call report_lane_result "
        "with status=\"terminated\" for that ticket_id. Do NOT keep lanes "
        "running that the verifier flags. Do NOT dispatch the next wave "
        "until you have reviewed and terminated dead lanes."
    ),
)
async def review_lanes(graph_id: str) -> dict:
    state = graphs.get(graph_id)
    if state is None:
        return {
            "error": f"graph_id '{graph_id}' not found",
            "next_step": "Check the graph_id. If lost, submit a new graph.",
        }

    active_tickets = [
        t for t in state.tickets.values() if t.status == "active"
    ]
    completed_tickets = [
        t for t in state.tickets.values() if t.status == "completed"
    ]
    failed_tickets = [
        t for t in state.tickets.values() if t.status == "failed"
    ]

    if not active_tickets:
        return {
            "active_lanes": [],
            "summary": {
                "total_active": 0,
                "recommend_continue": 0,
                "recommend_terminate": 0,
                "completed": len(completed_tickets),
                "failed": len(failed_tickets),
            },
            "next_step": (
                "No active lanes. Call get_next_wave for the next batch."
            ),
        }

    lanes: list[dict] = []

    for ticket in active_tickets:
        reasons: list[str] = []
        terminated = False
        redundant_with: list[str] | None = None

        # Budget exceeded: tool_calls_used > expected_tool_calls * 2
        if ticket.tool_calls_used > ticket.expected_tool_calls * 2:
            reasons.append(
                f"budget exceeded: used {ticket.tool_calls_used} calls, "
                f"expected {ticket.expected_tool_calls}"
            )
            terminated = True

        # Duplicative: another active lane with jaccard > 0.7
        if not terminated:
            for other in active_tickets:
                if other.id == ticket.id:
                    continue
                sim = jaccard_similarity(
                    ticket.description, other.description
                )
                if sim > 0.7:
                    reasons.append(
                        f"duplicative of lane '{other.id}' "
                        f"(similarity={sim:.2f})"
                    )
                    redundant_with = [other.id]
                    terminated = True
                    break

        # Made redundant by a completed sibling
        if not terminated:
            for sibling in completed_tickets:
                sibling_summary = ""
                if sibling.result:
                    sibling_summary = sibling.result.get("summary", "")
                # Check if sibling result covers this ticket's criteria
                ticket_tokens = _token_set(ticket.description)
                sibling_tokens = _token_set(sibling_summary)
                covered_tokens = ticket_tokens & sibling_tokens
                if len(ticket_tokens) > 0 and (
                    len(covered_tokens) / len(ticket_tokens) > 0.5
                ):
                    reasons.append(
                        f"made redundant by completed lane "
                        f"'{sibling.id}'"
                    )
                    redundant_with = [sibling.id]
                    terminated = True
                    break

        # No progress signals and calls >= expected
        if not terminated:
            if (
                ticket.tool_calls_used >= ticket.expected_tool_calls
                and ticket.result is None
            ):
                reasons.append(
                    f"no progress signals: used "
                    f"{ticket.tool_calls_used} calls without result"
                )
                terminated = True

        if terminated:
            recommendation = "terminate"
            reason = "; ".join(reasons) if reasons else "unknown"
        else:
            recommendation = "continue"
            reason = "progressing within budget"

        lanes.append(
            {
                "ticket_id": ticket.id,
                "node_id": ticket.node_id,
                "recommendation": recommendation,
                "recommendation_reason": reason,
                "tool_calls_used": ticket.tool_calls_used,
                "expected_tool_calls": ticket.expected_tool_calls,
                "redundant_with": redundant_with,
            }
        )

    total_active = len(active_tickets)
    recommend_continue = sum(
        1 for l in lanes if l["recommendation"] == "continue"
    )
    recommend_terminate = total_active - recommend_continue

    return {
        "active_lanes": lanes,
        "summary": {
            "total_active": total_active,
            "recommend_continue": recommend_continue,
            "recommend_terminate": recommend_terminate,
            "completed": len(completed_tickets),
            "failed": len(failed_tickets),
        },
        "next_step": (
            "Terminate lanes recommended 'terminate' via report_lane_result. "
            "Then call get_next_wave for the next batch."
        ),
    }


@mcp.tool(
    name="get_state",
    description=(
        "Get the full state snapshot of a graph — all tickets, waves, "
        "statuses, counts. Use this when you need the complete picture "
        "of graph state.\n\n"
        "=== INPUT ===\n"
        "- graph_id (string): from submit_graph response\n\n"
        "=== OUTPUT ===\n"
        "- graph_id, created_at, warnings, max_concurrency\n"
        "- waves: computed wave assignments\n"
        "- tickets: every ticket with id, node_id, description, status, "
        "active_since, completed_at, tool_calls_used, error, result\n"
        "- status_counts: breakdown by status\n"
        "- total_tickets: total count"
    ),
)
async def get_state(graph_id: str) -> dict:
    state = graphs.get(graph_id)
    if state is None:
        return {"error": f"graph_id '{graph_id}' not found"}
    return _serialize_state(state)


@mcp.tool(
    name="open_graph_view",
    description=(
        "Start a local interactive graph board for a submitted graph and "
        "return its URL. It visualizes task cards, dependency arrows, waves, "
        "and live lane status."
    ),
)
async def open_graph_view(graph_id: str, port: int = 8765) -> dict:
    if graph_id not in graphs:
        return {"error": f"graph_id '{graph_id}' not found"}
    if not 1024 <= port <= 65535:
        return {"error": "port must be between 1024 and 65535"}
    url = start_graph_view(_get_view_graph, _list_view_graphs, port)
    return {
        "url": f"{url}/?graph_id={graph_id}",
        "graph_id": graph_id,
        "next_step": "Open the URL in a browser. The board refreshes every 2 seconds.",
    }


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def async_main() -> None:
    await mcp.run_async(transport="stdio")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
