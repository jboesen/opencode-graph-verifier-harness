"""Dependency-free, loopback-only visual board for Graph Verifier."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

GraphProvider = Callable[[str], dict | None]
GraphListProvider = Callable[[], list[dict]]
# (graph_id, node_id, annotation_text) -> result dict
AnnotateHandler = Callable[[str, str, str], dict]
# (graph_id, node_id) -> result dict (spawns work in the background)
RunHandler = Callable[[str, str], dict]

_servers: dict[int, ThreadingHTTPServer] = {}

HTML = r'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Graph Verifier Board</title>
<style>
:root{--ink:#1e1e1e;--muted:#6b7280;--paper:#ffffff;--line:#dfe3e6;--blue:#1971c2;--blue-bg:#e7f5ff;--green:#2f9e44;--green-bg:#ebfbee;--amber:#f08c00;--amber-bg:#fff9db;--red:#e03131;--red-bg:#fff5f5}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px 'Segoe Print','Bradley Hand','Comic Sans MS',cursive,system-ui,sans-serif;overflow:hidden}
header{height:60px;background:#fff;border-bottom:2px solid var(--ink);display:flex;align-items:center;gap:14px;padding:0 22px}
h1{margin:0;font-size:19px;font-weight:700}
h1 span,.summary{font-weight:400;color:var(--muted);font-size:13px}
select,button{border:2px solid var(--ink);border-radius:255px 15px 225px 15px/15px 225px 15px 255px;background:#fff;padding:7px 12px;font:inherit;cursor:pointer}
button:hover{background:#f5f5f5}
select{min-width:220px}
.summary{margin-left:auto}
.canvas{height:calc(100vh - 60px);overflow:hidden;position:relative;background-image:radial-gradient(#e2e2e2 1.4px,transparent 1.4px);background-size:22px 22px}
.world{position:absolute;inset:0;transform-origin:0 0}
.edges{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}
.edge{fill:none;stroke:#3f3f3f;stroke-width:2.2;marker-end:url(#arrow);filter:url(#sketch)}
.edge.blocked{stroke:#adb5bd;stroke-dasharray:6 6}
.node{width:308px;position:absolute;background:#fff;border-radius:9px 7px 8px 6px/6px 9px 7px 8px;padding:14px 16px;cursor:grab;user-select:none}
.node::before,.node::after{content:'';position:absolute;inset:-3px;border:2.2px solid var(--accent,var(--amber));border-radius:9px 7px 8px 6px/6px 9px 7px 8px;pointer-events:none}
.node::before{transform:rotate(-0.45deg)}
.node::after{transform:rotate(0.5deg);opacity:.55}
.node.active{--accent:var(--blue)}
.node.completed{--accent:var(--green)}
.node.failed,.node.terminated{--accent:var(--red)}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.title{font-weight:700;font-size:15.5px;line-height:1.25}
.tag{font:11px/1 ui-monospace,monospace;color:var(--muted);margin-top:3px;display:block}
.pill{font-size:11px;padding:3px 9px;border-radius:20px;background:var(--amber-bg);color:#a15c00;text-transform:capitalize;white-space:nowrap}
.node.active .pill{background:var(--blue-bg);color:#0c5aa6}
.node.completed .pill{background:var(--green-bg);color:#217a37}
.node.failed .pill,.node.terminated .pill{background:var(--red-bg);color:#b02525}
.desc{font-size:12.5px;line-height:1.4;margin-top:9px;color:#3d474e;font-family:system-ui,sans-serif;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.meta{margin-top:11px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between;font-family:system-ui,sans-serif}
.ann{margin-top:11px;border-top:1.5px dashed var(--line);padding-top:9px}
.ann textarea{width:100%;min-height:44px;resize:vertical;border:1.5px solid var(--line);border-radius:8px;padding:6px 8px;font:12px/1.35 system-ui,sans-serif;color:var(--ink)}
.ann-row{display:flex;align-items:center;gap:8px;margin-top:7px}
.run-btn{font-size:12px;padding:5px 11px;border-width:1.7px}
.run-btn:disabled{opacity:.55;cursor:default}
.run-status{font-size:11px;color:var(--muted);font-family:system-ui,sans-serif}
.run-output{margin:8px 0 0;max-height:130px;overflow:auto;background:#fbfbfa;border:1.5px solid var(--line);border-radius:8px;padding:8px;font:11px/1.4 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
.run-output.err{border-color:var(--red);color:#8a2020;background:var(--red-bg)}
.hint{position:absolute;left:22px;bottom:16px;background:#fff;border:2px solid var(--ink);border-radius:9px;padding:8px 12px;font-size:12px;color:var(--muted)}
.empty{padding:90px;text-align:center;color:var(--muted)}
</style>
<header><h1>Graph Verifier <span>· execution board</span></h1><select id="pick"></select><button id="fit">Fit graph</button><span class="summary" id="summary">Connecting…</span></header>
<main id="canvas" class="canvas"><div id="world" class="world">
<svg id="edges" class="edges">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#3f3f3f"/></marker>
    <filter id="sketch" x="-20%" y="-20%" width="140%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.014 0.05" numOctaves="2" seed="7" result="n"/>
      <feDisplacementMap in="SourceGraphic" in2="n" scale="3.4"/>
    </filter>
  </defs>
</svg>
<div id="nodes"></div>
</div><div class="hint">Drag cards to arrange · scroll to zoom · annotate a card + Run agent · refreshes every 2s</div></main>
<script>
const $ = s => document.querySelector(s);
const S = {
  id: new URLSearchParams(location.search).get('graph_id'),
  pos: {}, els: {}, scale: 1, x: 0, g: null, drag: null,
};
const W = $('#world'), N = $('#nodes'), E = $('#edges'), C = $('#canvas');

function esc(x) { const d = document.createElement('div'); d.textContent = x || ''; return d.innerHTML; }

function autoTitle(desc, nodeId) {
  if (!desc) return nodeId;
  const words = desc.trim().split(/\s+/).slice(0, 7).join(' ');
  return words.length < desc.trim().length ? words + '…' : words;
}

function move() { W.style.transform = `translate(${S.x}px,0) scale(${S.scale})`; }

function layout() {
  const byWave = {};
  S.g.tickets.forEach(t => (byWave[t.wave] ??= []).push(t));
  Object.keys(byWave).forEach(k =>
    byWave[k].forEach((t, i) => { S.pos[t.node_id] ??= { x: 75 + k * 380, y: 75 + i * 300 }; })
  );
}

function point(nodeId) { const p = S.pos[nodeId]; return { x: p.x + 308, y: p.y + 70 }; }

function mkNode(t) {
  const p = S.pos[t.node_id];
  const el = document.createElement('article');
  el.className = 'node';
  el.style.left = p.x + 'px';
  el.style.top = p.y + 'px';
  el.innerHTML = `
    <div class="head">
      <div><span class="title" data-f="title"></span><span class="tag">${esc(t.node_id)}</span></div>
      <span class="pill" data-f="pill"></span>
    </div>
    <div class="desc">${esc(t.description)}</div>
    <div class="meta"><span>${esc(t.specialist_type)}</span><span data-f="calls"></span></div>
    <div class="ann">
      <textarea data-f="ann-input" placeholder="Annotate this node — instructions for an agent…"></textarea>
      <div class="ann-row">
        <button class="run-btn" data-f="run-btn">▶ Run agent</button>
        <span class="run-status" data-f="run-status"></span>
      </div>
      <pre class="run-output" data-f="run-output" hidden></pre>
    </div>`;
  el.onpointerdown = e => {
    if (e.target.closest('textarea,button')) return;
    S.drag = { id: t.node_id, x: e.clientX, y: e.clientY, p: { ...S.pos[t.node_id] } };
    el.setPointerCapture(e.pointerId);
  };
  const runBtn = el.querySelector('[data-f="run-btn"]');
  const textarea = el.querySelector('[data-f="ann-input"]');
  runBtn.onclick = async () => {
    runBtn.disabled = true;
    el.querySelector('[data-f="run-status"]').textContent = 'starting…';
    try {
      const r = await fetch(`/api/graphs/${encodeURIComponent(S.id)}/nodes/${encodeURIComponent(t.node_id)}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ annotation: textarea.value }),
      });
      const body = await r.json();
      if (!r.ok || body.error) el.querySelector('[data-f="run-status"]').textContent = body.error || 'failed to start';
    } catch (e) {
      el.querySelector('[data-f="run-status"]').textContent = 'request failed';
      runBtn.disabled = false;
    }
  };
  N.append(el);
  return el;
}

function updateNode(el, t) {
  el.className = 'node ' + t.status;
  el.querySelector('[data-f="title"]').textContent = t.title || autoTitle(t.description, t.node_id);
  el.querySelector('[data-f="pill"]').textContent = t.status;
  el.querySelector('[data-f="calls"]').textContent = `${t.tool_calls_used || 0}/${t.expected_tool_calls} calls · wave ${t.wave}`;

  const runBtn = el.querySelector('[data-f="run-btn"]');
  const statusEl = el.querySelector('[data-f="run-status"]');
  const outEl = el.querySelector('[data-f="run-output"]');
  const running = t.agent_run_status === 'running';
  runBtn.disabled = running;
  statusEl.textContent = running ? 'running…' : (t.agent_run_status ? t.agent_run_status : '');
  if (t.agent_run_output) {
    outEl.hidden = false;
    outEl.textContent = t.agent_run_output;
    outEl.classList.toggle('err', t.agent_run_status === 'error');
  } else {
    outEl.hidden = true;
  }
}

function render() {
  if (!S.g) { N.innerHTML = '<div class="empty">No graph has been submitted yet.</div>'; S.els = {}; return; }
  layout();
  const seen = new Set();
  S.g.tickets.forEach(t => {
    seen.add(t.node_id);
    let el = S.els[t.node_id];
    if (!el) { el = mkNode(t); S.els[t.node_id] = el; }
    updateNode(el, t);
  });
  Object.keys(S.els).forEach(id => { if (!seen.has(id)) { S.els[id].remove(); delete S.els[id]; } });

  E.querySelectorAll('.edge').forEach(x => x.remove());
  S.g.tickets.forEach(t => t.depends_on.forEach(d => {
    if (!S.pos[d]) return;
    const a = point(d), b = S.pos[t.node_id], m = (a.x + b.x) / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M${a.x} ${a.y} C${m} ${a.y},${m} ${b.y + 70},${b.x} ${b.y + 70}`);
    path.setAttribute('class', 'edge ' + (t.status === 'pending' ? 'blocked' : ''));
    E.append(path);
  }));

  const c = S.g.status_counts || {};
  $('#summary').textContent = `${S.g.total_tickets} lanes · ${c.active || 0} active · ${c.completed || 0} complete`;
}

window.onpointermove = e => {
  if (!S.drag) return;
  const d = S.drag, p = S.pos[d.id];
  p.x = d.p.x + (e.clientX - d.x) / S.scale;
  p.y = d.p.y + (e.clientY - d.y) / S.scale;
  const el = S.els[d.id];
  if (el) { el.style.left = p.x + 'px'; el.style.top = p.y + 'px'; }
  const edges = E.querySelectorAll('.edge');
  if (edges.length) render();
};
window.onpointerup = () => { S.drag = null; };
C.onwheel = e => {
  e.preventDefault();
  S.scale = Math.max(.4, Math.min(1.7, S.scale * (e.deltaY < 0 ? 1.12 : .89)));
  move();
};
$('#fit').onclick = () => { S.scale = 1; S.x = 0; move(); };

async function json(u) { const r = await fetch(u); if (!r.ok) throw 0; return r.json(); }
async function refresh() {
  try {
    const l = await json('/api/graphs');
    if (!S.id && l.length) S.id = l[0].graph_id;
    $('#pick').innerHTML = l.map(g => `<option value="${g.graph_id}">${g.graph_id} · ${g.total_tickets} lanes</option>`).join('');
    $('#pick').value = S.id || '';
    if (S.id) { S.g = await json('/api/graphs/' + encodeURIComponent(S.id)); render(); }
  } catch (e) { $('#summary').textContent = 'Waiting for graph server…'; }
}
$('#pick').onchange = e => { S.id = e.target.value; S.pos = {}; S.els = {}; N.innerHTML = ''; history.replaceState(null, '', '?graph_id=' + S.id); refresh(); };
refresh();
setInterval(refresh, 2000);
</script>'''


def start_graph_view(
    get_graph: GraphProvider,
    get_graphs: GraphListProvider,
    on_annotate: AnnotateHandler | None = None,
    on_run: RunHandler | None = None,
    port: int = 8765,
) -> str:
    """Start one reusable local HTTP server and return its base URL."""
    if port in _servers:
        return f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self.send(200, "text/html; charset=utf-8", HTML.encode())
            elif path == "/api/graphs":
                self.send(200, "application/json", json.dumps(get_graphs()).encode())
            elif path.startswith("/api/graphs/"):
                graph = get_graph(path.rsplit("/", 1)[-1])
                self.send(200 if graph else 404, "application/json", json.dumps(graph or {"error": "graph not found"}).encode())
            else:
                self.send(404, "text/plain", b"Not found")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            # expected: api / graphs / <graph_id> / nodes / <node_id> / (annotate|run)
            if len(parts) != 6 or parts[0:2] != ["api", "graphs"] or parts[3] != "nodes":
                self.send(404, "application/json", b'{"error": "not found"}')
                return
            graph_id, node_id, action = parts[2], parts[4], parts[5]
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = json.loads(self.rfile.read(length).decode() or "{}") if length else {}
            except Exception:
                self.send(400, "application/json", b'{"error": "invalid JSON body"}')
                return

            if action == "annotate" and on_annotate:
                result = on_annotate(graph_id, node_id, body.get("annotation", ""))
            elif action == "run" and on_run:
                annotation = body.get("annotation")
                if annotation is not None and on_annotate:
                    on_annotate(graph_id, node_id, annotation)
                result = on_run(graph_id, node_id)
            else:
                self.send(404, "application/json", b'{"error": "unknown action"}')
                return

            status = 200 if not result.get("error") else 400
            self.send(status, "application/json", json.dumps(result).encode())

        def send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_: object) -> None: return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _servers[port] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"
