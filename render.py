#!/usr/bin/env python3
"""
render.py - Memory access trace visualizer

Reads a text trace file (one record per line: "R|W <size> <addr>")
and generates a self-contained HTML visualization with:
  - HSV encoding: hue=time, brightness=frequency, last-write-wins on hue
  - Replay scrubber to step through the trace over time
  - Gaps between non-contiguous cacheline regions
  - Hover tooltip showing read/write counts per cell
  - Toggle to filter reads / writes / all

Usage:
    ./your_program 2> trace.txt
    python3 render.py trace.txt -o viz.html
"""

import sys
import argparse
import colorsys
import json
from collections import defaultdict

CACHELINE_SIZE = 64

def parse_trace(path):
    records = []
    with open(path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 3:
                continue
            rw, size, addr = parts
            is_write = 1 if rw == "W" else 0
            records.append((0, int(addr), int(size), is_write))
    return records

def build_hitmap(records):
    """
    Per cell tracks:
      [reads, writes, last_hue_all, last_hue_read, last_hue_write]
    Returns hitmap, max_reads, max_writes, max_total
    """
    # [reads, writes, last_hue_all, last_hue_read, last_hue_write]
    hitmap = defaultdict(lambda: [[0, 0, 0.0, 0.0, 0.0] for _ in range(CACHELINE_SIZE)])
    total  = len(records)

    for i, (tsc, addr, size, is_write) in enumerate(records):
        cacheline = addr & ~(CACHELINE_SIZE - 1)
        offset    = addr &  (CACHELINE_SIZE - 1)
        hue       = (i / total) * 360.0

        for byte in range(size):
            o = offset + byte
            if o >= CACHELINE_SIZE:
                break
            cell = hitmap[cacheline][o]
            if is_write:
                cell[1] += 1
                cell[4]  = hue
            else:
                cell[0] += 1
                cell[3]  = hue
            cell[2] = hue  # last access hue regardless of rw

    max_reads  = max((cell[0] for row in hitmap.values() for cell in row), default=1) or 1
    max_writes = max((cell[1] for row in hitmap.values() for cell in row), default=1) or 1
    max_total  = max((cell[0]+cell[1] for row in hitmap.values() for cell in row), default=1) or 1

    return hitmap, max_reads, max_writes, max_total

def hsv_to_rgb_hex(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))

def build_row_data(hitmap, max_reads, max_writes, max_total):
    """
    For each cacheline, build per-cell data:
      { r, w, ha, hr, hw }  (counts + last hues)
    Also compute gaps between non-contiguous cachelines.
    Returns list of row dicts.
    """
    sorted_addrs = sorted(hitmap.keys())
    rows = []
    prev_addr = None

    for cacheline_addr in sorted_addrs:
        # insert gap marker if address jump > 1 cacheline
        if prev_addr is not None and cacheline_addr > prev_addr + CACHELINE_SIZE:
            rows.append({"gap": True, "addr": cacheline_addr})

        cells_raw = hitmap[cacheline_addr]
        cells = []
        for reads, writes, hue_all, hue_r, hue_w in cells_raw:
            cells.append({
                "r":  reads,
                "w":  writes,
                "ha": round(hue_all, 2),
                "hr": round(hue_r,   2),
                "hw": round(hue_w,   2),
            })
        rows.append({"gap": False, "addr": cacheline_addr, "cells": cells})
        prev_addr = cacheline_addr

    return rows, max_reads, max_writes, max_total

def build_replay_frames(records, num_frames=200):
    """
    Split records into num_frames buckets.
    Each frame is the index of the last record included.
    Returns list of record indices (one per frame).
    """
    total = len(records)
    if total == 0:
        return [0]
    step = max(1, total // num_frames)
    frames = list(range(step - 1, total, step))
    if frames[-1] != total - 1:
        frames.append(total - 1)
    return frames

def build_replay_data(records, num_frames=200):
    """
    For replay, we encode the full records list as a JS array.
    The JS side rebuilds the hitmap incrementally up to the scrubber position.
    To keep HTML size manageable, we encode each record compactly.
    Returns JS array string: [[addr, size, is_write], ...]
    """
    encoded = [[int(addr), int(size), int(is_write)] for (_, addr, size, is_write) in records]
    return json.dumps(encoded)

def render_html(rows, max_reads, max_writes, max_total, total_records, trace_path, replay_data):
    num_rows   = len(rows)
    cell_size  = 10
    grid_w     = CACHELINE_SIZE * cell_size
    gap_height = 6  # px for gap rows

    rows_json      = json.dumps(rows)
    replay_json    = replay_data

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>memtrace — {trace_path}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0d0d0d;
    color: #c9c9c9;
    font-family: 'JetBrains Mono', 'Fira Mono', monospace;
    font-size: 12px;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
    user-select: none;
  }}
  header {{
    padding: 8px 16px;
    border-bottom: 1px solid #1e1e1e;
    display: flex;
    align-items: center;
    gap: 20px;
    flex-shrink: 0;
  }}
  header h1 {{ font-size: 13px; font-weight: 700; color: #fff; letter-spacing: 0.08em; }}
  .meta {{ color: #444; font-size: 11px; }}
  .meta span {{ color: #777; }}
  .controls {{
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .toggle-group {{
    display: flex;
    gap: 4px;
  }}
  .toggle-btn {{
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    color: #666;
    font-family: inherit;
    font-size: 11px;
    padding: 3px 10px;
    cursor: pointer;
    transition: all 0.1s;
  }}
  .toggle-btn.active {{
    background: #222;
    border-color: #555;
    color: #ddd;
  }}
  .scrubber-bar {{
    padding: 6px 16px;
    border-bottom: 1px solid #1a1a1a;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
    background: #0a0a0a;
  }}
  .scrubber-bar label {{ color: #444; font-size: 11px; white-space: nowrap; }}
  #play-btn {{
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    color: #888;
    font-family: inherit;
    font-size: 11px;
    padding: 3px 12px;
    cursor: pointer;
    flex-shrink: 0;
    letter-spacing: 0.05em;
  }}
  #play-btn:hover {{ border-color: #444; color: #ccc; }}
  #scrubber {{
    flex: 1;
    accent-color: #555;
    cursor: pointer;
    height: 3px;
  }}
  #scrubber-val {{ color: #666; font-size: 11px; min-width: 80px; text-align: right; }}
  .layout {{
    display: flex;
    flex: 1;
    overflow: hidden;
  }}
  .sidebar {{
    width: 150px;
    flex-shrink: 0;
    border-right: 1px solid #161616;
    overflow: hidden;
    position: relative;
  }}
  .sidebar-inner {{
    position: absolute;
    top: 0; left: 0; right: 0;
  }}
  .sidebar-row {{
    font-size: 10px;
    color: #333;
    padding: 0 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .sidebar-gap {{
    border-top: 1px dashed #1e1e1e;
    border-bottom: 1px dashed #1e1e1e;
  }}
  .canvas-wrap {{
    flex: 1;
    overflow: auto;
    position: relative;
  }}
  canvas {{
    display: block;
    image-rendering: pixelated;
    cursor: crosshair;
  }}
  #tooltip {{
    position: fixed;
    background: #111;
    border: 1px solid #2a2a2a;
    padding: 7px 11px;
    pointer-events: none;
    display: none;
    z-index: 100;
    line-height: 1.8;
    color: #aaa;
    font-size: 11px;
  }}
  #tooltip .addr {{ color: #eee; font-weight: 600; }}
  #tooltip .reads  {{ color: #6af; }}
  #tooltip .writes {{ color: #fa6; }}
  .footer {{
    padding: 6px 16px;
    border-top: 1px solid #1a1a1a;
    display: flex;
    gap: 20px;
    align-items: center;
    flex-shrink: 0;
    color: #333;
    font-size: 11px;
  }}
  .legend-hue {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
</style>
</head>
<body>

<header>
  <h1>memtrace</h1>
  <div class="meta">trace: <span>{trace_path}</span></div>
  <div class="meta">records: <span>{total_records:,}</span></div>
  <div class="meta">cachelines: <span>{sum(1 for r in rows if not r.get('gap'))}</span></div>
  <div class="controls">
    <div class="toggle-group">
      <button class="toggle-btn active" id="btn-all"   onclick="setMode('all')">ALL</button>
      <button class="toggle-btn"        id="btn-reads" onclick="setMode('reads')">READS</button>
      <button class="toggle-btn"        id="btn-writes"onclick="setMode('writes')">WRITES</button>
    </div>
  </div>
</header>

<div class="scrubber-bar">
  <label>REPLAY</label>
  <button id="play-btn" onclick="togglePlay()">&#9654; PLAY</button>
  <input type="range" id="scrubber" min="0" max="{total_records - 1}" value="{total_records - 1}" step="1">
  <span id="scrubber-val">{total_records:,} / {total_records:,}</span>
</div>

<div id="tooltip"></div>

<div class="layout">
  <div class="sidebar" id="sidebar">
    <div class="sidebar-inner" id="sidebar-inner"></div>
  </div>
  <div class="canvas-wrap" id="wrap">
    <canvas id="c" width="{grid_w}"></canvas>
  </div>
</div>

<div class="footer">
  <div class="legend-hue">
    <span>time →</span>
    <canvas id="legend_hue" width="160" height="8"></canvas>
  </div>
  <span>hue = access time &nbsp;·&nbsp; brightness = frequency &nbsp;·&nbsp; last access wins</span>
</div>

<script>
const CELL        = {cell_size};
const COLS        = {CACHELINE_SIZE};
const GAP_H       = {gap_height};
const MAX_READS   = {max_reads};
const MAX_WRITES  = {max_writes};
const MAX_TOTAL   = {max_total};
const TOTAL       = {total_records};

// Full row layout from Python (includes gap markers)
const ROWS = {rows_json};

// All records for replay: [[addr, size, is_write], ...]
const RECORDS = {replay_json};

// ── Layout ────────────────────────────────────────────────────────────────────

// Pre-compute y position and height of each row
const rowMeta = [];  // {{ y, h, gap, addr, rowIdx }}
let canvasH = 0;
ROWS.forEach((row, i) => {{
  if (row.gap) {{
    rowMeta.push({{ y: canvasH, h: GAP_H, gap: true, addr: row.addr }});
    canvasH += GAP_H;
  }} else {{
    rowMeta.push({{ y: canvasH, h: CELL, gap: false, addr: row.addr, rowIdx: i }});
    canvasH += CELL;
  }}
}});

const canvas = document.getElementById("c");
canvas.height = canvasH;
const ctx = canvas.getContext("2d");

// ── Sidebar ───────────────────────────────────────────────────────────────────

const sidebarInner = document.getElementById("sidebar-inner");
sidebarInner.style.height = canvasH + "px";
rowMeta.forEach((m) => {{
  const div = document.createElement("div");
  div.style.position   = "absolute";
  div.style.top        = m.y + "px";
  div.style.height     = m.h + "px";
  div.style.lineHeight = m.h + "px";
  div.style.left       = "0";
  div.style.right      = "0";
  if (m.gap) {{
    div.className = "sidebar-row sidebar-gap";
    div.textContent = "···";
    div.style.color = "#1e1e1e";
    div.style.fontSize = "9px";
    div.style.textAlign = "center";
  }} else {{
    div.className = "sidebar-row";
    div.textContent = m.addr;
    div.title = "0x" + BigInt(m.addr).toString(16).toUpperCase();
  }}
  sidebarInner.appendChild(div);
}});

const wrap = document.getElementById("wrap");
wrap.addEventListener("scroll", () => {{
  document.getElementById("sidebar").scrollTop = wrap.scrollTop;
  document.getElementById("sidebar").scrollLeft = 0;
  // move sidebar-inner instead
  sidebarInner.style.top = (-wrap.scrollTop) + "px";
}});

// ── HSV helpers ───────────────────────────────────────────────────────────────

function hsvToRgb(h, s, v) {{
  // h in [0,360], s,v in [0,1]
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

// ── Hitmap state ──────────────────────────────────────────────────────────────

// hitmap: Map<cacheline_addr, Uint32Array(COLS*3)>
// per cell: [reads, writes, last_hue_packed]
// We'll store hue as integer 0-3600 (×10)
function makeHitmap() {{
  const m = new Map();
  ROWS.forEach(row => {{
    if (!row.gap) m.set(row.addr, new Uint32Array(COLS * 3));
  }});
  return m;
}}

let hitmap = makeHitmap();
let currentIdx = -1;  // last record index applied
let mode = "all";     // "all" | "reads" | "writes"

// Running maximums — grow as records are applied, reset on scrub back
let runMaxReads  = 1;
let runMaxWrites = 1;
let runMaxTotal  = 1;

function resetHitmap() {{
  hitmap.forEach((arr) => arr.fill(0));
  currentIdx   = -1;
  runMaxReads  = 1;
  runMaxWrites = 1;
  runMaxTotal  = 1;
}}

function applyRecordsUpTo(targetIdx) {{
  if (targetIdx < currentIdx) {{
    resetHitmap();
  }}
  const start = currentIdx + 1;
  const end   = Math.min(targetIdx, RECORDS.length - 1);
  const total = RECORDS.length;

  for (let i = start; i <= end; i++) {{
    const [addr, size, isWrite] = RECORDS[i];
    const cl  = addr - (addr % COLS);   // safe for large ints (no bitwise)
    const off = addr % COLS;
    const arr = hitmap.get(cl);
    if (!arr) continue;
    const hue = Math.round((i / total) * 3600);
    for (let b = 0; b < size; b++) {{
      const o = off + b;
      if (o >= COLS) break;
      const base = o * 3;
      if (isWrite) {{
        arr[base + 1]++;
        if (arr[base + 1] > runMaxWrites) runMaxWrites = arr[base + 1];
      }} else {{
        arr[base]++;
        if (arr[base] > runMaxReads) runMaxReads = arr[base];
      }}
      const t = arr[base] + arr[base + 1];
      if (t > runMaxTotal) runMaxTotal = t;
      arr[base + 2] = hue;  // last-write-wins
    }}
  }}
  currentIdx = end;
}}

// ── Draw ──────────────────────────────────────────────────────────────────────

function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Draw gap markers
  rowMeta.forEach((m) => {{
    if (m.gap) {{
      ctx.fillStyle = "#111";
      ctx.fillRect(0, m.y, canvas.width, m.h);
      ctx.strokeStyle = "#1e1e1e";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, m.y + m.h / 2);
      ctx.lineTo(canvas.width, m.y + m.h / 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }}
  }});

  const imageData = ctx.createImageData(canvas.width, canvasH);
  const pixels    = imageData.data;

  rowMeta.forEach((m) => {{
    if (m.gap) return;
    const row = ROWS[m.rowIdx];
    const arr = hitmap.get(row.addr);
    if (!arr) return;

    for (let col = 0; col < COLS; col++) {{
      const base   = col * 3;
      const reads  = arr[base];
      const writes = arr[base + 1];
      const hue10  = arr[base + 2];

      let count = 0, maxCount = 1;
      if (mode === "all")         {{ count = reads + writes; maxCount = runMaxTotal;  }}
      else if (mode === "reads")  {{ count = reads;          maxCount = runMaxReads;  }}
      else if (mode === "writes") {{ count = writes;         maxCount = runMaxWrites; }}

      if (count === 0) continue;

      const brightness = 0.15 + 0.85 * (count / maxCount);
      const hue = hue10 / 10;
      const [r, g, b] = hsvToRgb(hue, 0.85, brightness);

      const px = (m.y * canvas.width + col * CELL);
      for (let dy = 0; dy < CELL; dy++) {{
        for (let dx = 0; dx < CELL; dx++) {{
          const idx = ((m.y + dy) * canvas.width + col * CELL + dx) * 4;
          pixels[idx]     = r;
          pixels[idx + 1] = g;
          pixels[idx + 2] = b;
          pixels[idx + 3] = 255;
        }}
      }}
    }}
  }});

  ctx.putImageData(imageData, 0, 0);
}}

// ── Scrubber ──────────────────────────────────────────────────────────────────

const scrubber    = document.getElementById("scrubber");
const scrubberVal = document.getElementById("scrubber-val");

let rafPending = false;
scrubber.addEventListener("input", () => {{
  const idx = parseInt(scrubber.value);
  scrubberVal.textContent = (idx + 1).toLocaleString() + " / " + TOTAL.toLocaleString();
  if (!rafPending) {{
    rafPending = true;
    requestAnimationFrame(() => {{
      applyRecordsUpTo(idx);
      draw();
      rafPending = false;
    }});
  }}
}});

// ── Autoplay ──────────────────────────────────────────────────────────────────

let playing    = false;
let playRafId  = null;
const PLAY_STEP = Math.max(1, Math.floor(TOTAL / 300));  // ~300 frames to traverse full trace

function togglePlay() {{
  playing = !playing;
  const btn = document.getElementById("play-btn");
  if (playing) {{
    btn.innerHTML = "&#9646;&#9646; PAUSE";
    // if at end, restart
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
  if (playing) playRafId = requestAnimationFrame(stepPlay);
}}

// ── Mode toggle ───────────────────────────────────────────────────────────────

function setMode(m) {{
  mode = m;
  ["all","reads","writes"].forEach(id => {{
    document.getElementById("btn-" + id).classList.toggle("active", id === m);
  }});
  draw();
}}

// ── Tooltip ───────────────────────────────────────────────────────────────────

const tooltip = document.getElementById("tooltip");

canvas.addEventListener("mousemove", (e) => {{
  const rect = canvas.getBoundingClientRect();
  const mx   = e.clientX - rect.left;
  const my   = e.clientY - rect.top;
  const col  = Math.floor(mx / CELL);

  // Find which row
  let found = null;
  for (const m of rowMeta) {{
    if (my >= m.y && my < m.y + m.h) {{ found = m; break; }}
  }}
  if (!found || found.gap || col < 0 || col >= COLS) {{
    tooltip.style.display = "none";
    return;
  }}

  const row = ROWS[found.rowIdx];
  const arr = hitmap.get(row.addr);
  const base = col * 3;
  const reads  = arr ? arr[base]     : 0;
  const writes = arr ? arr[base + 1] : 0;
  const hex    = "0x" + (BigInt(row.addr) + BigInt(col)).toString(16).toUpperCase().padStart(12, "0");

  tooltip.style.display = "block";
  tooltip.style.left    = (e.clientX + 16) + "px";
  tooltip.style.top     = (e.clientY + 12) + "px";
  tooltip.innerHTML = `
    <div class="addr">${{hex}}</div>
    <div>cacheline &nbsp;${{row.addr}}</div>
    <div>offset &nbsp;&nbsp;&nbsp;+${{col}}</div>
    <div class="reads">reads &nbsp;&nbsp;&nbsp;${{reads.toLocaleString()}}</div>
    <div class="writes">writes &nbsp;&nbsp;${{writes.toLocaleString()}}</div>
  `;
}});
canvas.addEventListener("mouseleave", () => {{ tooltip.style.display = "none"; }});

// ── Legend ────────────────────────────────────────────────────────────────────

const lc = document.getElementById("legend_hue");
const lx = lc.getContext("2d");
for (let x = 0; x < 160; x++) {{
  const h = (x / 160) * 360;
  lx.fillStyle = `hsl(${{h}}, 85%, 55%)`;
  lx.fillRect(x, 0, 1, 8);
}}

// ── Init ──────────────────────────────────────────────────────────────────────

applyRecordsUpTo(TOTAL - 1);
draw();
</script>
</body>
</html>"""

def main():
    parser = argparse.ArgumentParser(description="Render memtrace text trace to HTML")
    parser.add_argument("trace", help="Text trace file (R|W <size> <addr> per line)")
    parser.add_argument("-o", "--output", help="Output HTML file (default: stdout)")
    args = parser.parse_args()

    print(f"Parsing {args.trace}...", file=sys.stderr)
    records = parse_trace(args.trace)
    print(f"  {len(records):,} records", file=sys.stderr)

    if not records:
        print("No records found. Check trace format: R|W <size> <addr>", file=sys.stderr)
        sys.exit(1)

    print("Building hitmap...", file=sys.stderr)
    hitmap, max_reads, max_writes, max_total = build_hitmap(records)
    print(f"  {len(hitmap):,} cachelines", file=sys.stderr)
    print(f"  max reads={max_reads}, max writes={max_writes}, max total={max_total}", file=sys.stderr)

    print("Building row layout...", file=sys.stderr)
    rows, max_reads, max_writes, max_total = build_row_data(hitmap, max_reads, max_writes, max_total)

    print("Building replay data...", file=sys.stderr)
    replay_data = build_replay_data(records)

    print("Rendering HTML...", file=sys.stderr)
    html = render_html(rows, max_reads, max_writes, max_total, len(records), args.trace, replay_data)

    if args.output:
        with open(args.output, "w") as f:
            f.write(html)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(html)

if __name__ == "__main__":
    main()
