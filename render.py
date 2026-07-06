#!/usr/bin/env python3
"""
render.py - Memory access trace visualizer

Trace format (one record per line, function name may contain spaces):
    R|W <size> <addr> <file>::<line>::<col> <function name>

Features:
  - HSV encoding: hue = time, brightness = frequency, last-access-wins on hue
  - Replay scrubber + autoplay
  - Function multiselect filter; memory region, running max, and log all follow the filter
  - Per-cell function attribution in the hover tooltip
  - Cacheline row highlighting on hover
  - Viewport-aware tooltip
  - Live trace log panel synced with the replay position
  - Embedded source code panel (user code only, std/system headers excluded)

Usage:
    ./your_program 2> trace.txt
    python3 render.py trace.txt -o viz.html
"""

import sys
import os
import argparse
import json

CACHELINE_SIZE   = 64
MAX_SOURCE_LINES = 8000   # per-file safety cap

def is_system_path(path):
    return path.startswith("/usr/") or "/include/c++/" in path or path.startswith("/opt/")

def parse_trace(path):
    """
    Returns:
      records: list of (addr, size, is_write, func_id, loc_id)
      funcs:   list of function names
      locs:    list of [file, line, col]
    """
    records = []
    funcs, func_idx = [], {}
    locs,  loc_idx  = [], {}

    with open(path, "r") as f:
        for raw in f:
            parts = raw.rstrip("\n").split(maxsplit=4)
            if len(parts) < 4:
                continue
            rw, size, addr, loc = parts[0], parts[1], parts[2], parts[3]
            func = parts[4] if len(parts) == 5 else "<unknown>"

            if rw not in ("R", "W"):
                continue
            try:
                size, addr = int(size), int(addr)
            except ValueError:
                continue

            lp = loc.rsplit("::", 2)
            if len(lp) == 3:
                try:
                    loc_key = (lp[0], int(lp[1]), int(lp[2]))
                except ValueError:
                    loc_key = (loc, 0, 0)
            else:
                loc_key = (loc, 0, 0)

            if func not in func_idx:
                func_idx[func] = len(funcs)
                funcs.append(func)
            if loc_key not in loc_idx:
                loc_idx[loc_key] = len(locs)
                locs.append(list(loc_key))

            records.append((addr, size, 1 if rw == "W" else 0,
                            func_idx[func], loc_idx[loc_key]))

    return records, funcs, locs

def load_sources(locs, trace_dir):
    """
    Read user source files referenced by the trace. System headers excluded.
    Files are resolved relative to the trace file's directory, then cwd.
    Returns {filename: [line1, line2, ...]}
    """
    sources = {}
    seen = set()
    for file, _line, _col in locs:
        if file in seen:
            continue
        seen.add(file)
        if is_system_path(file):
            continue
        candidates = [file]
        if not os.path.isabs(file):
            candidates = [os.path.join(trace_dir, file), file]
        for cand in candidates:
            if os.path.isfile(cand):
                try:
                    with open(cand, "r", errors="replace") as f:
                        lines = f.read().splitlines()[:MAX_SOURCE_LINES]
                    sources[file] = lines
                except OSError:
                    pass
                break
    return sources

def render_html(records, funcs, locs, sources, trace_path):
    total  = len(records)
    cell   = 10
    grid_w = CACHELINE_SIZE * cell
    gap_h  = 6

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>memtrace — {trace_path}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0d0d0d; color: #c9c9c9;
    font-family: 'JetBrains Mono', 'Fira Mono', monospace;
    font-size: 12px;
    display: flex; flex-direction: column;
    height: 100vh; overflow: hidden; user-select: none;
  }}

  header {{
    padding: 8px 16px; border-bottom: 1px solid #1e1e1e;
    display: flex; align-items: center; gap: 20px; flex-shrink: 0;
  }}
  header h1 {{ font-size: 13px; font-weight: 700; color: #fff; letter-spacing: 0.08em; }}
  .meta {{ color: #444; font-size: 11px; }}
  .meta span {{ color: #777; }}
  .controls {{ margin-left: auto; display: flex; align-items: center; gap: 12px; }}

  .toggle-group {{ display: flex; gap: 4px; }}
  .toggle-btn {{
    background: #1a1a1a; border: 1px solid #2a2a2a; color: #666;
    font-family: inherit; font-size: 11px; padding: 3px 10px; cursor: pointer;
  }}
  .toggle-btn.active {{ background: #222; border-color: #555; color: #ddd; }}

  .fn-filter {{ position: relative; }}
  #fn-filter-btn {{
    background: #1a1a1a; border: 1px solid #2a2a2a; color: #888;
    font-family: inherit; font-size: 11px; padding: 3px 12px; cursor: pointer;
  }}
  #fn-filter-btn:hover {{ border-color: #444; color: #ccc; }}
  #fn-dropdown {{
    display: none; position: absolute; right: 0; top: calc(100% + 4px);
    background: #111; border: 1px solid #2a2a2a; min-width: 380px; max-width: 560px;
    max-height: 320px; overflow-y: auto; z-index: 200; padding: 6px 0;
  }}
  #fn-dropdown.open {{ display: block; }}
  .fn-row {{
    display: flex; align-items: center; gap: 8px; padding: 4px 12px;
    cursor: pointer; color: #999; font-size: 11px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }}
  .fn-row:hover {{ background: #1a1a1a; color: #ddd; }}
  .fn-row input {{ accent-color: #666; flex-shrink: 0; }}
  .fn-row .fn-name {{ overflow: hidden; text-overflow: ellipsis; }}
  .fn-actions {{
    display: flex; gap: 8px; padding: 4px 12px 8px;
    border-bottom: 1px solid #1e1e1e; margin-bottom: 4px;
  }}
  .fn-actions button {{
    background: none; border: none; color: #567; font-family: inherit;
    font-size: 10px; cursor: pointer; padding: 0;
  }}
  .fn-actions button:hover {{ color: #9ab; }}

  .scrubber-bar {{
    padding: 6px 16px; border-bottom: 1px solid #1a1a1a;
    display: flex; align-items: center; gap: 12px; flex-shrink: 0; background: #0a0a0a;
  }}
  .scrubber-bar label {{ color: #444; font-size: 11px; white-space: nowrap; }}
  #play-btn {{
    background: #1a1a1a; border: 1px solid #2a2a2a; color: #888;
    font-family: inherit; font-size: 11px; padding: 3px 12px; cursor: pointer;
    flex-shrink: 0; letter-spacing: 0.05em;
  }}
  #play-btn:hover {{ border-color: #444; color: #ccc; }}
  #scrubber {{ flex: 1; accent-color: #555; cursor: pointer; height: 3px; }}
  #scrubber-val {{ color: #666; font-size: 11px; min-width: 110px; text-align: right; }}

  .layout {{ display: flex; flex: 1; overflow: hidden; }}

  .sidebar {{
    width: 150px; flex-shrink: 0; border-right: 1px solid #161616;
    overflow: hidden; position: relative;
  }}
  .sidebar-inner {{ position: absolute; top: 0; left: 0; right: 0; }}
  .sidebar-row {{
    font-size: 10px; color: #333; padding: 0 8px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }}
  .sidebar-row.hl {{ color: #ddd; background: #1c1c1c; }}
  .sidebar-gap {{ border-top: 1px dashed #1e1e1e; border-bottom: 1px dashed #1e1e1e; }}

  .canvas-wrap {{ flex: 1; overflow: auto; position: relative; }}
  canvas#c {{ display: block; image-rendering: pixelated; cursor: crosshair; }}
  #row-highlight {{
    position: absolute; left: 0; width: 100%;
    background: rgba(255,255,255,0.07);
    outline: 1px solid rgba(255,255,255,0.25);
    pointer-events: none; display: none; z-index: 5;
  }}

  .right-panel {{
    width: 420px; flex-shrink: 0; border-left: 1px solid #161616;
    display: flex; flex-direction: column; background: #0a0a0a;
  }}
  .panel-header {{
    padding: 6px 12px; border-bottom: 1px solid #1a1a1a;
    color: #444; font-size: 10px; letter-spacing: 0.1em; flex-shrink: 0;
    display: flex; justify-content: space-between;
  }}
  .panel-header .file {{ color: #567; text-transform: none; letter-spacing: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px; }}

  #log-lines {{ flex: 1; overflow: hidden; padding: 4px 0; min-height: 0; }}
  .log-line {{
    padding: 1px 12px; font-size: 10px; color: #444;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    cursor: pointer; line-height: 1.5;
  }}
  .log-line:hover {{ background: #141414; color: #888; }}
  .log-line.current {{ background: #1e1e1e; color: #eee; }}
  .log-line.filtered-out {{ opacity: 0.25; }}
  .log-line .rw-r {{ color: #6af; }}
  .log-line .rw-w {{ color: #fa6; }}
  .log-line .fn {{ color: #567; }}
  .log-line.current .fn {{ color: #9ab; }}

  #code-view {{
    flex: 1; overflow-y: auto; min-height: 0;
    border-top: 1px solid #161616; padding: 4px 0;
  }}
  .code-line {{
    display: flex; font-size: 10px; line-height: 1.5;
    color: #556; white-space: pre;
  }}
  .code-line .ln {{
    width: 46px; flex-shrink: 0; text-align: right; padding-right: 10px;
    color: #2a2a2a;
  }}
  .code-line.current {{ background: #23281e; color: #cd9; }}
  .code-line.current .ln {{ color: #8a5; }}
  #code-view .no-source {{
    color: #333; padding: 12px; font-size: 10px; font-style: italic;
  }}

  #tooltip {{
    position: fixed; background: #111; border: 1px solid #2a2a2a;
    padding: 8px 12px; pointer-events: none; display: none; z-index: 100;
    line-height: 1.7; color: #aaa; font-size: 11px; max-width: 480px;
  }}
  #tooltip .addr {{ color: #eee; font-weight: 600; }}
  #tooltip .reads  {{ color: #6af; }}
  #tooltip .writes {{ color: #fa6; }}
  #tooltip .fn-list {{ margin-top: 5px; border-top: 1px solid #222; padding-top: 5px; }}
  #tooltip .fn-item {{ color: #789; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  #tooltip .fn-item b {{ color: #aaa; font-weight: 400; }}

  .footer {{
    padding: 6px 16px; border-top: 1px solid #1a1a1a;
    display: flex; gap: 20px; align-items: center; flex-shrink: 0;
    color: #333; font-size: 11px;
  }}
  .legend-hue {{ display: flex; align-items: center; gap: 8px; }}
</style>
</head>
<body>

<header>
  <h1>memtrace</h1>
  <div class="meta">trace: <span>{trace_path}</span></div>
  <div class="meta">records: <span>{total:,}</span></div>
  <div class="meta">functions: <span>{len(funcs)}</span></div>
  <div class="controls">
    <div class="fn-filter">
      <button id="fn-filter-btn" onclick="toggleFnDropdown()">FUNCTIONS ▾</button>
      <div id="fn-dropdown">
        <div class="fn-actions">
          <button onclick="setAllFns(true)">select all</button>
          <button onclick="setAllFns(false)">clear</button>
        </div>
        <div id="fn-list"></div>
      </div>
    </div>
    <div class="toggle-group">
      <button class="toggle-btn active" id="btn-all"    onclick="setMode('all')">ALL</button>
      <button class="toggle-btn"        id="btn-reads"  onclick="setMode('reads')">READS</button>
      <button class="toggle-btn"        id="btn-writes" onclick="setMode('writes')">WRITES</button>
    </div>
  </div>
</header>

<div class="scrubber-bar">
  <label>REPLAY</label>
  <button id="play-btn" onclick="togglePlay()">&#9654; PLAY</button>
  <input type="range" id="scrubber" min="0" max="{total - 1}" value="{total - 1}" step="1">
  <span id="scrubber-val">{total:,} / {total:,}</span>
</div>

<div id="tooltip"></div>

<div class="layout">
  <div class="sidebar" id="sidebar"><div class="sidebar-inner" id="sidebar-inner"></div></div>
  <div class="canvas-wrap" id="wrap">
    <canvas id="c" width="{grid_w}"></canvas>
    <div id="row-highlight"></div>
  </div>
  <div class="right-panel">
    <div class="panel-header"><span>TRACE LOG</span></div>
    <div id="log-lines"></div>
    <div class="panel-header"><span>SOURCE</span><span class="file" id="code-file"></span></div>
    <div id="code-view"><div class="no-source">no record selected</div></div>
  </div>
</div>

<div class="footer">
  <div class="legend-hue">
    <span>time →</span>
    <canvas id="legend_hue" width="160" height="8"></canvas>
  </div>
  <span>hue = access time &nbsp;·&nbsp; brightness = frequency (within filter) &nbsp;·&nbsp; last access wins</span>
</div>

<script>
const CELL   = {cell};
const COLS   = {CACHELINE_SIZE};
const GAP_H  = {gap_h};
const TOTAL  = {total};

const RECORDS = {json.dumps(records)};   // [addr, size, isWrite, funcId, locId]
const FUNCS   = {json.dumps(funcs)};
const LOCS    = {json.dumps(locs)};      // [file, line, col]
const SOURCES = {json.dumps(sources)};   // {{file: [lines...]}}

// ── HSV ──────────────────────────────────────────────────────────────────────
function hsvToRgb(h, s, v) {{
  const c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c;
  let r=0,g=0,b=0;
  if      (h < 60)  {{ r=c; g=x; }}
  else if (h < 120) {{ r=x; g=c; }}
  else if (h < 180) {{ g=c; b=x; }}
  else if (h < 240) {{ g=x; b=c; }}
  else if (h < 300) {{ r=x; b=c; }}
  else              {{ r=c; b=x; }}
  return [Math.round((r+m)*255), Math.round((g+m)*255), Math.round((b+m)*255)];
}}

// ── State ────────────────────────────────────────────────────────────────────
const canvas       = document.getElementById("c");
const ctx          = canvas.getContext("2d");
const wrap         = document.getElementById("wrap");
const sidebarInner = document.getElementById("sidebar-inner");
const rowHl        = document.getElementById("row-highlight");
const scrubber     = document.getElementById("scrubber");
const scrubberVal  = document.getElementById("scrubber-val");

let activeFns  = new Set(FUNCS.map((_, i) => i));
let mode       = "all";
let rowMeta    = [];      // built per filter
let hitmap     = new Map();
let currentIdx = -1;
let runMaxReads = 1, runMaxWrites = 1, runMaxTotal = 1;
let hlSidebarEl = null;

// ── Layout (rebuilt whenever the function filter changes) ────────────────────
function rebuildLayout() {{
  // 1. collect cachelines visible under the current filter (across full trace)
  const clSet = new Set();
  for (const [addr, size, _w, funcId] of RECORDS) {{
    if (!activeFns.has(funcId)) continue;
    clSet.add(addr - (addr % COLS));
  }}
  const lines = [...clSet].sort((a, b) => a - b);

  // 2. build rowMeta with gap markers
  rowMeta = [];
  let y = 0, prev = null;
  for (const cl of lines) {{
    if (prev !== null && cl > prev + COLS) {{
      rowMeta.push({{ y, h: GAP_H, gap: true }});
      y += GAP_H;
    }}
    rowMeta.push({{ y, h: CELL, gap: false, addr: cl }});
    y += CELL;
    prev = cl;
  }}
  canvas.height = Math.max(y, 1);

  // 3. rebuild sidebar
  sidebarInner.innerHTML = "";
  sidebarInner.style.height = y + "px";
  rowMeta.forEach((m) => {{
    const div = document.createElement("div");
    div.style.cssText = `position:absolute;top:${{m.y}}px;height:${{m.h}}px;line-height:${{m.h}}px;left:0;right:0`;
    if (m.gap) {{
      div.className = "sidebar-row sidebar-gap";
      div.textContent = "···";
      div.style.cssText += ";color:#1e1e1e;font-size:9px;text-align:center";
    }} else {{
      div.className = "sidebar-row";
      div.textContent = m.addr;
      div.title = "0x" + BigInt(m.addr).toString(16).toUpperCase();
    }}
    sidebarInner.appendChild(div);
    m.sidebarEl = div;
  }});

  // 4. fresh hitmap for visible cachelines
  hitmap = new Map();
  rowMeta.forEach(m => {{
    if (!m.gap) hitmap.set(m.addr, Array.from({{length: COLS}}, () => ({{ r:0, w:0, hue:0, fns:{{}} }})));
  }});
  currentIdx = -1;
  runMaxReads = runMaxWrites = runMaxTotal = 1;
}}

wrap.addEventListener("scroll", () => {{
  sidebarInner.style.top = (-wrap.scrollTop) + "px";
}});

// ── Replay core ──────────────────────────────────────────────────────────────
function resetHitmap() {{
  hitmap.forEach(cells => cells.forEach(c => {{ c.r=0; c.w=0; c.hue=0; c.fns={{}}; }}));
  currentIdx = -1;
  runMaxReads = runMaxWrites = runMaxTotal = 1;
}}

function applyRecordsUpTo(targetIdx) {{
  if (targetIdx < currentIdx) resetHitmap();
  const start = currentIdx + 1;
  const end   = Math.min(targetIdx, RECORDS.length - 1);

  for (let i = start; i <= end; i++) {{
    const [addr, size, isWrite, funcId] = RECORDS[i];
    if (!activeFns.has(funcId)) continue;

    const cl  = addr - (addr % COLS);
    const off = addr % COLS;
    const cells = hitmap.get(cl);
    if (!cells) continue;
    const hue = (i / TOTAL) * 360;

    for (let b = 0; b < size; b++) {{
      const o = off + b;
      if (o >= COLS) break;
      const cell = cells[o];
      if (isWrite) {{ cell.w++; if (cell.w > runMaxWrites) runMaxWrites = cell.w; }}
      else         {{ cell.r++; if (cell.r > runMaxReads)  runMaxReads  = cell.r; }}
      const t = cell.r + cell.w;
      if (t > runMaxTotal) runMaxTotal = t;
      cell.hue = hue;
      cell.fns[funcId] = (cell.fns[funcId] || 0) + 1;
    }}
  }}
  currentIdx = end;
}}

// ── Draw ─────────────────────────────────────────────────────────────────────
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  rowMeta.forEach((m) => {{
    if (!m.gap) return;
    ctx.fillStyle = "#111";
    ctx.fillRect(0, m.y, canvas.width, m.h);
    ctx.strokeStyle = "#1e1e1e";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, m.y + m.h / 2);
    ctx.lineTo(canvas.width, m.y + m.h / 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }});

  rowMeta.forEach((m) => {{
    if (m.gap) return;
    const cells = hitmap.get(m.addr);
    for (let col = 0; col < COLS; col++) {{
      const cell = cells[col];
      let count = 0, maxCount = 1;
      if (mode === "all")         {{ count = cell.r + cell.w; maxCount = runMaxTotal;  }}
      else if (mode === "reads")  {{ count = cell.r;          maxCount = runMaxReads;  }}
      else if (mode === "writes") {{ count = cell.w;          maxCount = runMaxWrites; }}
      if (count === 0) continue;

      const brightness = 0.15 + 0.85 * (count / maxCount);
      const [r, g, b] = hsvToRgb(cell.hue, 0.85, brightness);
      ctx.fillStyle = `rgb(${{r}},${{g}},${{b}})`;
      ctx.fillRect(col * CELL, m.y, CELL, CELL);
    }}
  }});
}}

// ── Function filter ──────────────────────────────────────────────────────────
const fnList = document.getElementById("fn-list");
FUNCS.forEach((name, i) => {{
  const row = document.createElement("label");
  row.className = "fn-row";
  row.innerHTML = `<input type="checkbox" checked data-fid="${{i}}"><span class="fn-name" title="${{name.replace(/"/g,'&quot;')}}">${{name}}</span>`;
  row.querySelector("input").addEventListener("change", (e) => {{
    const fid = parseInt(e.target.dataset.fid);
    if (e.target.checked) activeFns.add(fid); else activeFns.delete(fid);
    refilter();
  }});
  fnList.appendChild(row);
}});

function toggleFnDropdown() {{
  document.getElementById("fn-dropdown").classList.toggle("open");
}}
document.addEventListener("click", (e) => {{
  if (!e.target.closest(".fn-filter"))
    document.getElementById("fn-dropdown").classList.remove("open");
}});

function setAllFns(on) {{
  activeFns = on ? new Set(FUNCS.map((_, i) => i)) : new Set();
  fnList.querySelectorAll("input").forEach(cb => cb.checked = on);
  refilter();
}}

function refilter() {{
  const idx = parseInt(scrubber.value);
  rebuildLayout();               // memory region follows the filter
  applyRecordsUpTo(idx);
  draw();
  renderLog(idx);
  renderCode(idx);
  const btn = document.getElementById("fn-filter-btn");
  btn.textContent = activeFns.size === FUNCS.length
    ? "FUNCTIONS ▾"
    : `FUNCTIONS (${{activeFns.size}}/${{FUNCS.length}}) ▾`;
}}

// ── Scrubber + autoplay ──────────────────────────────────────────────────────
let rafPending = false;
scrubber.addEventListener("input", () => {{
  const idx = parseInt(scrubber.value);
  scrubberVal.textContent = (idx + 1).toLocaleString() + " / " + TOTAL.toLocaleString();
  if (!rafPending) {{
    rafPending = true;
    requestAnimationFrame(() => {{
      applyRecordsUpTo(idx);
      draw();
      renderLog(idx);
      renderCode(idx);
      rafPending = false;
    }});
  }}
}});

let playing = false, playRafId = null;
const PLAY_STEP = Math.max(1, Math.floor(TOTAL / 300));

function togglePlay() {{
  playing = !playing;
  const btn = document.getElementById("play-btn");
  if (playing) {{
    btn.innerHTML = "&#9646;&#9646; PAUSE";
    if (parseInt(scrubber.value) >= TOTAL - 1) {{
      scrubber.value = 0;
      resetHitmap();
    }}
    stepPlay();
  }} else {{
    btn.innerHTML = "&#9654; PLAY";
    if (playRafId) cancelAnimationFrame(playRafId);
  }}
}}

function stepPlay() {{
  if (!playing) return;
  let idx = parseInt(scrubber.value) + PLAY_STEP;
  if (idx >= TOTAL - 1) {{
    idx = TOTAL - 1;
    playing = false;
    document.getElementById("play-btn").innerHTML = "&#9654; PLAY";
  }}
  scrubber.value = idx;
  scrubberVal.textContent = (idx + 1).toLocaleString() + " / " + TOTAL.toLocaleString();
  applyRecordsUpTo(idx);
  draw();
  renderLog(idx);
  renderCode(idx);
  if (playing) playRafId = requestAnimationFrame(stepPlay);
}}

// ── Mode toggle ──────────────────────────────────────────────────────────────
function setMode(m) {{
  mode = m;
  ["all","reads","writes"].forEach(id =>
    document.getElementById("btn-" + id).classList.toggle("active", id === m));
  draw();
}}

// ── Live trace log ───────────────────────────────────────────────────────────
const logLines = document.getElementById("log-lines");
const LOG_WINDOW = 24;

function shortAddr(a) {{ return "…" + String(a).slice(-6); }}
function shortFn(f)   {{ return f.length > 30 ? f.slice(0, 27) + "…" : f; }}

function renderLog(idx) {{
  const half  = Math.floor(LOG_WINDOW / 2);
  let start   = Math.max(0, idx - half);
  const end   = Math.min(TOTAL - 1, start + LOG_WINDOW - 1);
  start       = Math.max(0, end - LOG_WINDOW + 1);

  let html = "";
  for (let i = start; i <= end; i++) {{
    const [addr, size, isWrite, funcId] = RECORDS[i];
    const cls = ["log-line", i === idx ? "current" : "",
                 activeFns.has(funcId) ? "" : "filtered-out"].join(" ");
    const rw = isWrite ? '<span class="rw-w">W</span>' : '<span class="rw-r">R</span>';
    html += `<div class="${{cls}}" data-idx="${{i}}">` +
            `${{String(i).padStart(6, "\\u00a0")}} ${{rw}} ${{size}}B ${{shortAddr(addr)}} ` +
            `<span class="fn">${{shortFn(FUNCS[funcId])}}</span></div>`;
  }}
  logLines.innerHTML = html;
}}

logLines.addEventListener("click", (e) => {{
  const line = e.target.closest(".log-line");
  if (!line) return;
  const idx = parseInt(line.dataset.idx);
  scrubber.value = idx;
  scrubberVal.textContent = (idx + 1).toLocaleString() + " / " + TOTAL.toLocaleString();
  applyRecordsUpTo(idx);
  draw();
  renderLog(idx);
  renderCode(idx);
}});

// ── Source code panel ────────────────────────────────────────────────────────
const codeView = document.getElementById("code-view");
const codeFile = document.getElementById("code-file");
let renderedFile = null;

function renderCode(idx) {{
  if (idx < 0 || idx >= TOTAL) return;
  const [, , , , locId] = RECORDS[idx];
  const [file, line]    = LOCS[locId];

  if (!(file in SOURCES)) {{
    renderedFile = null;
    codeFile.textContent = file;
    codeView.innerHTML = `<div class="no-source">source not embedded (${{file}})</div>`;
    return;
  }}

  if (renderedFile !== file) {{
    renderedFile = file;
    codeFile.textContent = file;
    const lines = SOURCES[file];
    let html = "";
    for (let i = 0; i < lines.length; i++) {{
      const text = lines[i].replace(/&/g, "&amp;").replace(/</g, "&lt;") || "\\u00a0";
      html += `<div class="code-line" id="src-${{i + 1}}"><span class="ln">${{i + 1}}</span><span>${{text}}</span></div>`;
    }}
    codeView.innerHTML = html;
  }}

  codeView.querySelectorAll(".code-line.current").forEach(el => el.classList.remove("current"));
  const el = document.getElementById("src-" + line);
  if (el) {{
    el.classList.add("current");
    // keep the highlighted line vertically centered
    codeView.scrollTop = el.offsetTop - codeView.clientHeight / 2;
  }}
}}

// ── Hover: tooltip + row highlight ───────────────────────────────────────────
const tooltip = document.getElementById("tooltip");

canvas.addEventListener("mousemove", (e) => {{
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const col = Math.floor(mx / CELL);

  let found = null;
  for (const m of rowMeta) {{
    if (my >= m.y && my < m.y + m.h) {{ found = m; break; }}
  }}

  if (hlSidebarEl) hlSidebarEl.classList.remove("hl");
  if (!found || found.gap || col < 0 || col >= COLS) {{
    tooltip.style.display = "none";
    rowHl.style.display = "none";
    return;
  }}

  rowHl.style.display = "block";
  rowHl.style.top = found.y + "px";
  rowHl.style.height = found.h + "px";
  hlSidebarEl = found.sidebarEl;
  hlSidebarEl.classList.add("hl");

  const cell = hitmap.get(found.addr)[col];
  const hex  = "0x" + (BigInt(found.addr) + BigInt(col)).toString(16).toUpperCase().padStart(12, "0");

  const fnEntries = Object.entries(cell.fns)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([fid, cnt]) => `<div class="fn-item"><b>${{cnt}}×</b> ${{FUNCS[fid]}}</div>`)
    .join("");

  tooltip.innerHTML = `
    <div class="addr">${{hex}}</div>
    <div>cacheline &nbsp;${{found.addr}} &nbsp;·&nbsp; offset +${{col}}</div>
    <div><span class="reads">reads ${{cell.r.toLocaleString()}}</span> &nbsp;
         <span class="writes">writes ${{cell.w.toLocaleString()}}</span></div>
    ${{fnEntries ? '<div class="fn-list">' + fnEntries + '</div>' : ''}}
  `;

  tooltip.style.display = "block";
  tooltip.style.left = "0px"; tooltip.style.top = "0px";
  const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
  let tx = e.clientX + 16, ty = e.clientY + 12;
  if (tx + tw > window.innerWidth  - 8) tx = e.clientX - tw - 16;
  if (ty + th > window.innerHeight - 8) ty = e.clientY - th - 12;
  tooltip.style.left = Math.max(8, tx) + "px";
  tooltip.style.top  = Math.max(8, ty) + "px";
}});

canvas.addEventListener("mouseleave", () => {{
  tooltip.style.display = "none";
  rowHl.style.display = "none";
  if (hlSidebarEl) hlSidebarEl.classList.remove("hl");
}});

// ── Legend ───────────────────────────────────────────────────────────────────
const lc = document.getElementById("legend_hue");
const lx = lc.getContext("2d");
for (let x = 0; x < 160; x++) {{
  lx.fillStyle = `hsl(${{(x / 160) * 360}}, 85%, 55%)`;
  lx.fillRect(x, 0, 1, 8);
}}

// ── Init ─────────────────────────────────────────────────────────────────────
rebuildLayout();
applyRecordsUpTo(TOTAL - 1);
draw();
renderLog(TOTAL - 1);
renderCode(TOTAL - 1);
</script>
</body>
</html>"""

def main():
    parser = argparse.ArgumentParser(description="Render memtrace text trace to HTML")
    parser.add_argument("trace", help="Trace file: R|W <size> <addr> <file>::<line>::<col> <function>")
    parser.add_argument("-o", "--output", help="Output HTML file (default: stdout)")
    args = parser.parse_args()

    print(f"Parsing {args.trace}...", file=sys.stderr)
    records, funcs, locs = parse_trace(args.trace)
    print(f"  {len(records):,} records, {len(funcs)} functions, {len(locs)} source locations", file=sys.stderr)

    if not records:
        print("No records parsed. Expected: R|W <size> <addr> <file>::<line>::<col> <function>", file=sys.stderr)
        sys.exit(1)

    trace_dir = os.path.dirname(os.path.abspath(args.trace))
    sources = load_sources(locs, trace_dir)
    if sources:
        for f, lines in sources.items():
            print(f"  embedded source: {f} ({len(lines)} lines)", file=sys.stderr)
    else:
        print("  no user sources found to embed", file=sys.stderr)

    html = render_html(records, funcs, locs, sources, args.trace)

    if args.output:
        with open(args.output, "w") as f:
            f.write(html)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(html)

if __name__ == "__main__":
    main()
