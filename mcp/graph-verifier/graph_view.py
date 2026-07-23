"""Dependency-free, loopback-only visual board for Graph Verifier."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

GraphProvider = Callable[[str], dict | None]
GraphListProvider = Callable[[], list[dict]]
_servers: dict[int, ThreadingHTTPServer] = {}

HTML = r'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Graph Verifier Board</title>
<style>
:root{--ink:#20252d;--muted:#6e7780;--paper:#f4f7f7;--line:#d9e0e1;--blue:#4f98db;--green:#65ad74;--amber:#d9a340;--red:#d86f6f}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px ui-rounded,system-ui,sans-serif;overflow:hidden}header{height:62px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:15px;padding:0 24px}h1{margin:0;font-size:17px}h1 span,.summary{font-weight:400;color:var(--muted)}select,button{border:1px solid var(--line);border-radius:8px;background:white;padding:8px 10px;font:inherit}select{min-width:230px}.summary{margin-left:auto;font-size:12px}.canvas{height:calc(100vh - 62px);overflow:hidden;position:relative;background-image:radial-gradient(#dbe3e4 1px,transparent 1px);background-size:20px 20px}.world{position:absolute;inset:0;transform-origin:0 0}.edges{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}.edge{fill:none;stroke:#707a80;stroke-width:2;marker-end:url(#arrow)}.edge.blocked{stroke:#abb4b7;stroke-dasharray:5 5}.node{width:276px;min-height:142px;position:absolute;background:#fff;border:2px solid var(--amber);border-radius:8px;padding:14px 16px;box-shadow:0 2px 7px #28394116;cursor:grab;user-select:none}.node.active{border-color:var(--blue)}.node.completed{border-color:var(--green)}.node.failed,.node.terminated{border-color:var(--red)}.head,.meta{display:flex;justify-content:space-between;gap:8px}.id{font-weight:750;font-size:15px}.pill{font-size:11px;padding:3px 8px;border-radius:20px;background:#fbf0dc;text-transform:capitalize}.active .pill{background:#e6f1fb;color:#2876bd}.completed .pill{background:#e8f5eb;color:#397a45}.failed .pill,.terminated .pill{background:#f9e8e8;color:#ae4646}.desc{font-size:12px;line-height:1.4;margin-top:9px;color:#3d474e;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.meta{margin-top:13px;color:var(--muted);font-size:11px}.hint{position:absolute;left:22px;bottom:18px;background:#fff;border:1px solid var(--line);border-radius:9px;padding:8px 11px;font-size:11px;color:var(--muted)}.empty{padding:90px;text-align:center;color:var(--muted)}
</style><header><h1>Graph Verifier <span>· execution board</span></h1><select id="pick"></select><button id="fit">Fit graph</button><span class="summary" id="summary">Connecting…</span></header><main id="canvas" class="canvas"><div id="world" class="world"><svg id="edges" class="edges"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#707a80"/></marker></defs></svg><div id="nodes"></div></div><div class="hint">Drag cards to arrange · scroll to zoom · refreshes every 2 seconds</div></main><script>
const $=s=>document.querySelector(s),S={id:new URLSearchParams(location.search).get('graph_id'),pos:{},scale:1,x:0,g:null,drag:null};const W=$('#world'),N=$('#nodes'),E=$('#edges'),C=$('#canvas');function esc(x){let d=document.createElement('div');d.textContent=x||'';return d.innerHTML}function move(){W.style.transform=`translate(${S.x}px,0) scale(${S.scale})`}function layout(){let w={};S.g.tickets.forEach(t=>(w[t.wave]??=[]).push(t));Object.keys(w).forEach(k=>w[k].forEach((t,i)=>S.pos[t.node_id]??={x:75+k*355,y:75+i*200}))}function point(id){let p=S.pos[id];return{x:p.x+276,y:p.y+70}}function render(){if(!S.g){N.innerHTML='<div class="empty">No graph has been submitted yet.</div>';return}layout();N.innerHTML='';E.querySelectorAll('.edge').forEach(x=>x.remove());S.g.tickets.forEach(t=>{let p=S.pos[t.node_id],n=document.createElement('article');n.className='node '+t.status;n.style.cssText=`left:${p.x}px;top:${p.y}px`;n.innerHTML=`<div class="head"><span class="id">${esc(t.node_id)}</span><span class="pill">${esc(t.status)}</span></div><div class="desc">${esc(t.description)}</div><div class="meta"><span>${esc(t.specialist_type)}</span><span>${t.tool_calls_used||0}/${t.expected_tool_calls} calls · wave ${t.wave}</span></div>`;n.onpointerdown=e=>{S.drag={id:t.node_id,x:e.clientX,y:e.clientY,p:{...p}};n.setPointerCapture(e.pointerId)};N.append(n)});S.g.tickets.forEach(t=>t.depends_on.forEach(d=>{if(!S.pos[d])return;let a=point(d),b=S.pos[t.node_id],m=(a.x+b.x)/2,p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',`M${a.x} ${a.y} C${m} ${a.y},${m} ${b.y+70},${b.x} ${b.y+70}`);p.setAttribute('class','edge '+(t.status==='pending'?'blocked':''));E.append(p)}));let c=S.g.status_counts||{};$('#summary').textContent=`${S.g.total_tickets} lanes · ${c.active||0} active · ${c.completed||0} complete`}window.onpointermove=e=>{if(!S.drag)return;let d=S.drag,p=S.pos[d.id];p.x=d.p.x+(e.clientX-d.x)/S.scale;p.y=d.p.y+(e.clientY-d.y)/S.scale;render()};window.onpointerup=()=>S.drag=null;C.onwheel=e=>{e.preventDefault();S.scale=Math.max(.4,Math.min(1.7,S.scale*(e.deltaY<0?1.12:.89)));move()};$('#fit').onclick=()=>{S.scale=1;S.x=0;move()};async function json(u){let r=await fetch(u);if(!r.ok)throw 0;return r.json()}async function refresh(){try{let l=await json('/api/graphs');if(!S.id&&l.length)S.id=l[0].graph_id;$('#pick').innerHTML=l.map(g=>`<option value="${g.graph_id}">${g.graph_id} · ${g.total_tickets} lanes</option>`).join('');$('#pick').value=S.id||'';if(S.id){S.g=await json('/api/graphs/'+encodeURIComponent(S.id));render()}}catch(e){$('#summary').textContent='Waiting for graph server…'}}$('#pick').onchange=e=>{S.id=e.target.value;S.pos={};history.replaceState(null,'','?graph_id='+S.id);refresh()};refresh();setInterval(refresh,2000);
</script>'''


def start_graph_view(get_graph: GraphProvider, get_graphs: GraphListProvider, port: int = 8765) -> str:
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

        def send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_: object) -> None: return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _servers[port] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"
