"""FastAPI server for the Loom link review UI.

Serves a single-page HTML app at ``GET /`` that lets users approve or reject
semantic link suggestions.  On approval a ``[[wikilink]]`` is appended to the
source note via VaultClient and the pair is added to ``graph_cache`` so the
hybrid retrieval engine can traverse it immediately.

Start with::

    loom review-links            # default port 7842
    loom review-links --port N   # custom port
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from loom.config import LoomConfig, load_config
from loom.db import get_connection
from loom.retrieval.semantic_links import (
    approve_link,
    discover_links,
    get_pending_links,
    reject_link,
)
from loom.vault import VaultClient

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(config: LoomConfig | None = None) -> FastAPI:
    """Create and return the FastAPI application.

    Args:
        config: Loom configuration to use.  Loaded from disk when None.
    """
    _config: LoomConfig = config or load_config()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        yield

    app = FastAPI(title="Loom Link Review", lifespan=lifespan)

    # ------------------------------------------------------------------
    # HTML UI
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _HTML_PAGE

    # ------------------------------------------------------------------
    # API — pending suggestions
    # ------------------------------------------------------------------

    @app.get("/api/pending")
    async def api_pending(limit: int = 50) -> JSONResponse:
        """Return pending link suggestions."""
        db = get_connection()
        try:
            rows = get_pending_links(db, limit=limit)
        finally:
            db.close()
        return JSONResponse({"suggestions": rows})

    # ------------------------------------------------------------------
    # API — approve
    # ------------------------------------------------------------------

    @app.post("/api/approve/{link_id}")
    async def api_approve(link_id: int) -> JSONResponse:
        """Approve a suggestion: write wikilink and update graph_cache."""
        db = get_connection()
        try:
            pair = approve_link(db, link_id)
        finally:
            db.close()

        if pair is None:
            raise HTTPException(status_code=404, detail="Link not found or already processed")

        source_path, target_path = pair

        # Derive a short wikilink target — use the stem of the target path.
        link_target = Path(target_path).stem
        wikilink_line = f"\n\n## Related\n\n[[{link_target}]]"

        try:
            async with VaultClient(_config) as client:
                try:
                    existing = await client.read_note(source_path)
                    # Avoid duplicate wikilinks.
                    if f"[[{link_target}]]" not in existing:
                        await client.append_to_note(source_path, wikilink_line)
                except FileNotFoundError:
                    pass
        except Exception as exc:
            # Wikilink write is best-effort; the DB approval already happened.
            return JSONResponse(
                {"ok": True, "source": source_path, "target": target_path,
                 "warning": f"Wikilink write failed: {exc}"},
                status_code=200,
            )

        return JSONResponse({"ok": True, "source": source_path, "target": target_path})

    # ------------------------------------------------------------------
    # API — reject
    # ------------------------------------------------------------------

    @app.post("/api/reject/{link_id}")
    async def api_reject(link_id: int) -> JSONResponse:
        """Reject a suggestion."""
        db = get_connection()
        try:
            ok = reject_link(db, link_id)
        finally:
            db.close()

        if not ok:
            raise HTTPException(status_code=404, detail="Link not found or already processed")

        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------
    # API — trigger discovery
    # ------------------------------------------------------------------

    @app.post("/api/discover")
    async def api_discover() -> JSONResponse:
        """Run the background link discovery job and return the new count."""
        db = get_connection()
        try:
            count = await asyncio.to_thread(
                discover_links,
                db,
                _config.semantic_links_threshold,
                _config.semantic_links_max_per_note,
            )
        finally:
            db.close()
        return JSONResponse({"new_candidates": count})

    return app


# ---------------------------------------------------------------------------
# HTML + JS (single-file, no build step)
# ---------------------------------------------------------------------------

_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Loom — Link Review</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;500;700&display=swap');

  :root {
    --bg:       #0d0f12;
    --surface:  #141720;
    --border:   #252a35;
    --text:     #c9d1e0;
    --muted:    #5a6378;
    --accent:   #4f8ef7;
    --green:    #2ecc71;
    --yellow:   #f0c060;
    --red:      #e05252;
    --radius:   6px;
    --mono:     'IBM Plex Mono', monospace;
    --sans:     'IBM Plex Sans', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-weight: 300;
    min-height: 100vh;
  }

  header {
    border-bottom: 1px solid var(--border);
    padding: 18px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 10;
  }

  .brand {
    font-family: var(--mono);
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.06em;
    color: var(--accent);
  }

  .brand span { color: var(--muted); }

  #discover-btn {
    font-family: var(--mono);
    font-size: 12px;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 6px 14px;
    border-radius: var(--radius);
    cursor: pointer;
    transition: border-color .15s, color .15s;
  }
  #discover-btn:hover { border-color: var(--accent); color: var(--accent); }

  #counter {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
  }

  main { padding: 32px; max-width: 1200px; margin: 0 auto; }

  #empty {
    display: none;
    text-align: center;
    padding: 80px 0;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 14px;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 16px;
    overflow: hidden;
    animation: slide-in .2s ease;
  }

  @keyframes slide-in {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    gap: 12px;
  }

  .paths {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--mono);
    font-size: 12px;
    overflow: hidden;
    flex: 1;
  }

  .path-label {
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 320px;
  }

  .arrow { color: var(--muted); flex-shrink: 0; }

  .badge {
    font-family: var(--mono);
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 20px;
    flex-shrink: 0;
    font-weight: 600;
  }
  .badge-green  { background: #1a3a2a; color: var(--green); }
  .badge-yellow { background: #332a14; color: var(--yellow); }
  .badge-grey   { background: #1e2230; color: var(--muted); }

  .card-body {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
  }

  .excerpt {
    padding: 14px 20px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    line-height: 1.6;
    border-right: 1px solid var(--border);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 120px;
    overflow: hidden;
  }
  .excerpt:last-child { border-right: none; }

  .card-footer {
    display: flex;
    gap: 10px;
    padding: 12px 20px;
    border-top: 1px solid var(--border);
    justify-content: flex-end;
  }

  button.action {
    font-family: var(--mono);
    font-size: 12px;
    padding: 6px 18px;
    border-radius: var(--radius);
    border: none;
    cursor: pointer;
    transition: opacity .15s;
  }
  button.action:hover { opacity: 0.85; }
  button.approve { background: #1d3d2a; color: var(--green); border: 1px solid #2a5038; }
  button.reject  { background: #3a1e1e; color: var(--red);   border: 1px solid #5a2a2a; }
  button.action:disabled { opacity: 0.3; cursor: default; }

  #toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 10px 18px;
    border-radius: var(--radius);
    opacity: 0;
    transition: opacity .2s;
    pointer-events: none;
    z-index: 100;
  }
  #toast.show { opacity: 1; }
</style>
</head>
<body>

<header>
  <span class="brand">loom<span>/</span>review-links</span>
  <span id="counter">loading…</span>
  <button id="discover-btn" onclick="runDiscover()">⟳ find new links</button>
</header>

<main>
  <div id="empty">No pending suggestions — run "loom find-links" or click "find new links" above.</div>
  <div id="cards"></div>
</main>

<div id="toast"></div>

<script>
const cardsEl = document.getElementById('cards');
const emptyEl = document.getElementById('empty');
const counterEl = document.getElementById('counter');

function badgeClass(sim) {
  if (sim >= 0.9) return 'badge-green';
  if (sim >= 0.75) return 'badge-yellow';
  return 'badge-grey';
}

function shortPath(p) {
  const parts = p.split('/');
  return parts.length > 2 ? '…/' + parts.slice(-2).join('/') : p;
}

function renderCards(suggestions) {
  cardsEl.innerHTML = '';
  if (!suggestions.length) {
    emptyEl.style.display = 'block';
    counterEl.textContent = '0 pending';
    return;
  }
  emptyEl.style.display = 'none';
  counterEl.textContent = suggestions.length + ' pending';

  suggestions.forEach(s => {
    const sim = (s.similarity * 100).toFixed(1);
    const bClass = badgeClass(s.similarity);
    const card = document.createElement('div');
    card.className = 'card';
    card.id = 'card-' + s.id;
    card.innerHTML = `
      <div class="card-header">
        <div class="paths">
          <span class="path-label" title="${s.source_path}">${shortPath(s.source_path)}</span>
          <span class="arrow">→</span>
          <span class="path-label" title="${s.target_path}">${shortPath(s.target_path)}</span>
        </div>
        <span class="badge ${bClass}">${sim}%</span>
      </div>
      <div class="card-body">
        <div class="excerpt">${escHtml(s.source_excerpt || s.source_path)}</div>
        <div class="excerpt">${escHtml(s.target_excerpt || s.target_path)}</div>
      </div>
      <div class="card-footer">
        <button class="action reject" onclick="act(${s.id},'reject')">Reject</button>
        <button class="action approve" onclick="act(${s.id},'approve')">Approve &amp; link</button>
      </div>`;
    cardsEl.appendChild(card);
  });
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function load() {
  try {
    const res = await fetch('/api/pending?limit=100');
    const data = await res.json();
    renderCards(data.suggestions);
  } catch (e) {
    counterEl.textContent = 'error loading';
  }
}

async function act(id, action) {
  const card = document.getElementById('card-' + id);
  const btns = card.querySelectorAll('button');
  btns.forEach(b => b.disabled = true);

  try {
    const res = await fetch('/api/' + action + '/' + id, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      card.style.transition = 'opacity .2s';
      card.style.opacity = '0';
      setTimeout(() => { card.remove(); updateCounter(); }, 200);
      toast(action === 'approve' ? '✓ Link approved & written' : '✗ Suggestion rejected');
    } else {
      btns.forEach(b => b.disabled = false);
      toast('Error: ' + (data.detail || 'unknown'));
    }
  } catch (e) {
    btns.forEach(b => b.disabled = false);
    toast('Request failed');
  }
}

function updateCounter() {
  const remaining = cardsEl.querySelectorAll('.card').length;
  counterEl.textContent = remaining + ' pending';
  if (remaining === 0) emptyEl.style.display = 'block';
}

async function runDiscover() {
  const btn = document.getElementById('discover-btn');
  btn.disabled = true;
  btn.textContent = '⟳ scanning…';
  try {
    const res = await fetch('/api/discover', { method: 'POST' });
    const data = await res.json();
    toast('Found ' + data.new_candidates + ' new candidate(s)');
    await load();
  } catch (e) {
    toast('Discovery failed');
  } finally {
    btn.disabled = false;
    btn.textContent = '⟳ find new links';
  }
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

load();
</script>
</body>
</html>"""
