const COLOR_MAP   = window.COLOR_MAP;
const COLOR_NAMES = window.COLOR_NAMES;

// ── Constants ────────────────────────────────────────────────────────────
const W = 30, H = 62;
const LEVEL_NAMES = ['Level 1 — House','Level 2 — Ocean','Level 3 — Space','Level 4 — Forest','Level 5 — City'];
const ZOOM_STEPS  = [4, 6, 8, 10, 12, 16, 20, 28];

// ── State ────────────────────────────────────────────────────────────────
let pixels       = [];        // [H][W] base scene
let diffs        = [];        // [{x,y,w,h,color,side}]
let history      = [];        // unified undo stack: {pixels, diffs}
let currentLevel = 0;
let selectedColor = 5;
let tool         = 'draw';
let PS           = 10;        // pixel size (zoom)
let isDrawing    = false;
let isCustomScene = false;
let isCustomDiffs = false;

// Marker tool state
let selectedMarker = null;    // index into diffs
let markerDrag     = null;    // {idx, mode, startX, startY, orig}
let hoveredMarker  = null;    // {side, idx, handle} or null

// ── Init ─────────────────────────────────────────────────────────────────
function init() {
  buildLevelTabs();
  buildPalette();
  setupCanvas('canvasL', 'L');
  setupCanvas('canvasR', 'R');
  resizeCanvases();
  loadLevel(0);
  document.addEventListener('keydown', onKey);
  document.addEventListener('mouseup', () => {
    isDrawing = false;
    if (markerDrag) { markerDrag = null; }
  });
}

// ── Level tabs ───────────────────────────────────────────────────────────
function buildLevelTabs() {
  const el = document.getElementById('levelTabs');
  LEVEL_NAMES.forEach((name, i) => {
    const div = document.createElement('div');
    div.className = 'level-tab' + (i === 0 ? ' active' : '');
    div.id = `tab${i}`;
    div.textContent = name;
    div.onclick = () => switchLevel(i);
    el.appendChild(div);
  });
}

function switchLevel(i) {
  document.querySelectorAll('.level-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`tab${i}`).classList.add('active');
  currentLevel = i;
  history = [];
  selectedMarker = null;
  loadLevel(i);
}

function loadLevel(level) {
  fetch(`/api/draw/scene/${level}`)
    .then(r => r.json())
    .then(data => {
      pixels = data.pixels;
      diffs  = data.diffs || [];
      isCustomScene = data.custom || false;
      isCustomDiffs = data.custom_diffs || false;
      updateCustomBadge();
      renderAll();
    });
}

// ── Palette ──────────────────────────────────────────────────────────────
function buildPalette() {
  const el = document.getElementById('palette');
  for (let c = 0; c < 16; c++) {
    const sw = document.createElement('div');
    sw.className = 'swatch' + (c === selectedColor ? ' selected' : '');
    sw.style.background = COLOR_MAP[c];
    sw.id = `swatch${c}`;
    sw.onclick = () => selectColor(c);
    const tip = document.createElement('span');
    tip.className = 'swatch-tooltip';
    tip.textContent = `${c}: ${COLOR_NAMES[c]}`;
    sw.appendChild(tip);
    el.appendChild(sw);
  }
  updateColorInfo();
}

function selectColor(c) {
  document.querySelector('.swatch.selected')?.classList.remove('selected');
  document.getElementById(`swatch${c}`).classList.add('selected');
  selectedColor = c;
  updateColorInfo();
  // If a marker is selected and in marker mode, update its color
  if (tool === 'marker' && selectedMarker !== null) {
    diffs[selectedMarker].color = c;
    updateMarkerPanel();
    renderAll();
  }
  if (tool === 'pick') setTool('draw');
}

function updateColorInfo() {
  document.getElementById('colorPreview').style.background = COLOR_MAP[selectedColor];
  document.getElementById('colorLabel').textContent = `${selectedColor}: ${COLOR_NAMES[selectedColor]}`;
}

// ── Tool selection ────────────────────────────────────────────────────────
function setTool(t) {
  tool = t;
  ['Draw','Fill','Pick','Marker'].forEach(n => {
    const el = document.getElementById(`tool${n}`);
    if (el) el.classList.toggle('active', n.toLowerCase() === t);
  });
  document.getElementById('markerSection').style.display = (t === 'marker') ? '' : 'none';
  updateCursors();
}

function updateCursors() {
  ['canvasL','canvasR'].forEach(id => {
    const c = document.getElementById(id);
    if (!c) return;
    if (tool === 'fill')   c.style.cursor = 'cell';
    else if (tool === 'marker') c.style.cursor = 'crosshair';
    else c.style.cursor = 'crosshair';
  });
}

// ── Canvas setup ──────────────────────────────────────────────────────────
function setupCanvas(id, side) {
  const canvas = document.getElementById(id);

  canvas.addEventListener('mousedown', e => {
    e.preventDefault();
    if (tool === 'marker') { markerDown(e, canvas, side); return; }
    const {x, y} = cellAt(e, canvas);
    if (oob(x, y)) return;
    if (tool === 'draw') {
      pushHistory();
      isDrawing = true;
      pixels[y][x] = selectedColor;
      renderAll();
    } else if (tool === 'fill') {
      pushHistory();
      floodFill(x, y, selectedColor);
      renderAll();
    } else if (tool === 'pick') {
      selectColor(pixels[y][x]);
    }
  });

  canvas.addEventListener('mousemove', e => {
    if (tool === 'marker') { markerMove(e, canvas, side); return; }
    const {x, y} = cellAt(e, canvas);
    if (isDrawing && !oob(x, y)) {
      pixels[y][x] = selectedColor;
      renderAll();
    }
    if (!oob(x, y)) setStatus(`x=${x}  y=${y}  →  ${pixels[y][x]}: ${COLOR_NAMES[pixels[y][x]]}`);
  });

  canvas.addEventListener('mouseleave', () => {
    isDrawing = false;
    if (tool === 'marker' && !markerDrag) {
      if (hoveredMarker && hoveredMarker.side === side) {
        hoveredMarker = null;
        canvas.style.cursor = 'crosshair';
        renderAll();
      }
    }
    setStatus('Hover over canvas');
  });

  canvas.addEventListener('contextmenu', e => {
    e.preventDefault();
    if (tool === 'marker') return;
    const {x, y} = cellAt(e, canvas);
    if (!oob(x, y)) selectColor(pixels[y][x]);
  });
}

// ── Marker interaction ────────────────────────────────────────────────────
function getCorners(d) {
  return [
    {id:'nw', px: d.x*PS,         py: d.y*PS        },
    {id:'ne', px:(d.x+d.w)*PS,    py: d.y*PS        },
    {id:'sw', px: d.x*PS,         py:(d.y+d.h)*PS   },
    {id:'se', px:(d.x+d.w)*PS,    py:(d.y+d.h)*PS   },
  ];
}

function cursorForHandle(id) {
  return {nw:'nw-resize',ne:'ne-resize',sw:'sw-resize',se:'se-resize'}[id] || 'move';
}

function hitCorner(d, mx, my) {
  for (const c of getCorners(d)) {
    if (Math.abs(mx - c.px) <= 8 && Math.abs(my - c.py) <= 8) return c;
  }
  return null;
}

function hitBody(d, mx, my) {
  return mx >= d.x*PS && mx < (d.x+d.w)*PS && my >= d.y*PS && my < (d.y+d.h)*PS;
}

function markerDown(e, canvas, side) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  // Corner handle of selected marker?
  if (selectedMarker !== null && diffs[selectedMarker].side === side) {
    const d = diffs[selectedMarker];
    const c = hitCorner(d, mx, my);
    if (c) {
      pushHistory();
      markerDrag = {idx: selectedMarker, mode: 'resize-'+c.id, startX: mx, startY: my, orig: {...d}};
      return;
    }
  }

  // Body of any marker on this side?
  for (let i = diffs.length - 1; i >= 0; i--) {
    const d = diffs[i];
    if (d.side !== side) continue;
    if (hitBody(d, mx, my)) {
      selectedMarker = i;
      pushHistory();
      markerDrag = {idx: i, mode: 'move', startX: mx, startY: my, orig: {...d}};
      updateMarkerPanel();
      renderAll();
      return;
    }
  }

  // Empty click → add new marker
  const cx = Math.max(0, Math.min(W - 4, Math.floor(mx / PS)));
  const cy = Math.max(0, Math.min(H - 4, Math.floor(my / PS)));
  pushHistory();
  diffs.push({x: cx, y: cy, w: 4, h: 4, color: selectedColor, side});
  selectedMarker = diffs.length - 1;
  updateMarkerPanel();
  renderAll();
}

function markerMove(e, canvas, side) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (markerDrag) {
    const d    = diffs[markerDrag.idx];
    const orig = markerDrag.orig;
    const ddx  = Math.round((mx - markerDrag.startX) / PS);
    const ddy  = Math.round((my - markerDrag.startY) / PS);
    const mode = markerDrag.mode;

    if (mode === 'move') {
      d.x = Math.max(0, Math.min(W - d.w, orig.x + ddx));
      d.y = Math.max(0, Math.min(H - d.h, orig.y + ddy));
    } else {
      const id = mode.split('-')[1];
      if (id === 'se') {
        d.w = Math.max(1, Math.min(W - orig.x, orig.w + ddx));
        d.h = Math.max(1, Math.min(H - orig.y, orig.h + ddy));
      } else if (id === 'nw') {
        const nx = Math.max(0, Math.min(orig.x + orig.w - 1, orig.x + ddx));
        const ny = Math.max(0, Math.min(orig.y + orig.h - 1, orig.y + ddy));
        d.w = orig.x + orig.w - nx; d.h = orig.y + orig.h - ny;
        d.x = nx; d.y = ny;
      } else if (id === 'ne') {
        const ny = Math.max(0, Math.min(orig.y + orig.h - 1, orig.y + ddy));
        d.w = Math.max(1, Math.min(W - orig.x, orig.w + ddx));
        d.h = orig.y + orig.h - ny; d.y = ny;
      } else if (id === 'sw') {
        const nx = Math.max(0, Math.min(orig.x + orig.w - 1, orig.x + ddx));
        d.w = orig.x + orig.w - nx; d.x = nx;
        d.h = Math.max(1, Math.min(H - orig.y, orig.h + ddy));
      }
    }
    updateMarkerPanel();
    renderAll();
    return;
  }

  // Hover detection
  let hov = null;
  if (selectedMarker !== null && diffs[selectedMarker] && diffs[selectedMarker].side === side) {
    const c = hitCorner(diffs[selectedMarker], mx, my);
    if (c) hov = {side, idx: selectedMarker, handle: c.id};
  }
  if (!hov) {
    for (let i = diffs.length - 1; i >= 0; i--) {
      if (diffs[i].side !== side) continue;
      if (hitBody(diffs[i], mx, my)) { hov = {side, idx: i, handle: null}; break; }
    }
  }

  const cur = hov ? (hov.handle ? cursorForHandle(hov.handle) : 'move') : 'crosshair';
  canvas.style.cursor = cur;

  const prevKey = hoveredMarker ? `${hoveredMarker.side}-${hoveredMarker.idx}-${hoveredMarker.handle}` : '';
  const newKey  = hov           ? `${hov.side}-${hov.idx}-${hov.handle}` : '';
  if (prevKey !== newKey) { hoveredMarker = hov; renderAll(); }

  const cx = Math.floor(mx / PS), cy = Math.floor(my / PS);
  if (!oob(cx, cy)) setStatus(`x=${cx}  y=${cy}  →  ${pixels[cy][cx]}: ${COLOR_NAMES[pixels[cy][cx]]}`);
}

// Marker panel UI
function updateMarkerPanel() {
  if (selectedMarker === null || !diffs[selectedMarker]) {
    document.getElementById('markerNone').style.display = '';
    document.getElementById('markerSelected').style.display = 'none';
    return;
  }
  const d = diffs[selectedMarker];
  document.getElementById('markerNone').style.display = 'none';
  document.getElementById('markerSelected').style.display = '';
  document.getElementById('markerColorPreview').style.background = COLOR_MAP[d.color];
  document.getElementById('markerColorName').textContent = `${d.color}: ${COLOR_NAMES[d.color]}`;
  document.getElementById('markerSize').textContent = `${d.w} × ${d.h} px`;
  document.getElementById('sideBtnL').classList.toggle('active-side', d.side === 'L');
  document.getElementById('sideBtnR').classList.toggle('active-side', d.side === 'R');
}

function setMarkerSide(s) {
  if (selectedMarker === null) return;
  pushHistory();
  diffs[selectedMarker].side = s;
  updateMarkerPanel();
  renderAll();
}

function deleteMarker() {
  if (selectedMarker === null) return;
  pushHistory();
  diffs.splice(selectedMarker, 1);
  selectedMarker = null;
  updateMarkerPanel();
  renderAll();
}

// ── Rendering ─────────────────────────────────────────────────────────────
function renderAll() {
  renderCanvas('canvasL', 'L');
  renderCanvas('canvasR', 'R');
}

function renderCanvas(id, side) {
  const canvas = document.getElementById(id);
  const ctx    = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Base pixels
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      ctx.fillStyle = COLOR_MAP[pixels[y][x]];
      ctx.fillRect(x*PS, y*PS, PS, PS);
    }

  const showDiffs = document.getElementById('showDiffs').checked;

  // Apply diffs for this side as colored patches
  if (showDiffs) {
    diffs.forEach(d => {
      if (d.side !== side) return;
      ctx.fillStyle = COLOR_MAP[d.color];
      ctx.fillRect(d.x*PS, d.y*PS, d.w*PS, d.h*PS);
    });
  }

  // Grid
  if (PS >= 6) {
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth   = 0.5;
    for (let x = 0; x <= W; x++) { ctx.beginPath(); ctx.moveTo(x*PS,0); ctx.lineTo(x*PS,H*PS); ctx.stroke(); }
    for (let y = 0; y <= H; y++) { ctx.beginPath(); ctx.moveTo(0,y*PS); ctx.lineTo(W*PS,y*PS); ctx.stroke(); }
  }

  // Marker outlines
  if (!showDiffs) return;
  diffs.forEach((d, idx) => {
    if (d.side !== side) return;
    const isSel  = selectedMarker === idx;
    const isHov  = hoveredMarker && hoveredMarker.side === side && hoveredMarker.idx === idx && !hoveredMarker.handle;

    ctx.strokeStyle = isSel ? '#58a6ff' : isHov ? '#d29922' : 'rgba(255,255,255,0.7)';
    ctx.lineWidth   = isSel ? 2.5 : 1.5;
    ctx.setLineDash(isSel ? [] : [4,3]);
    ctx.strokeRect(d.x*PS + 0.5, d.y*PS + 0.5, d.w*PS - 1, d.h*PS - 1);
    ctx.setLineDash([]);

    // Index label
    ctx.font      = `bold ${Math.max(8, PS-2)}px monospace`;
    ctx.fillStyle = '#000';
    ctx.fillText(`${idx+1}`, d.x*PS + 2 + 1, (d.y+1)*PS - 2 + 1);
    ctx.fillStyle = '#fff';
    ctx.fillText(`${idx+1}`, d.x*PS + 2, (d.y+1)*PS - 2);

    // Corner resize handles when selected + marker tool
    if (isSel && tool === 'marker') {
      getCorners(d).forEach(c => {
        const isHovH = hoveredMarker && hoveredMarker.side === side &&
                       hoveredMarker.idx === idx && hoveredMarker.handle === c.id;
        ctx.fillStyle   = isHovH ? '#d29922' : '#58a6ff';
        ctx.strokeStyle = '#fff';
        ctx.lineWidth   = 1;
        ctx.fillRect(c.px - 5, c.py - 5, 10, 10);
        ctx.strokeRect(c.px - 5, c.py - 5, 10, 10);
      });
    }
  });
}

// ── Pixel helpers ─────────────────────────────────────────────────────────
function cellAt(e, canvas) {
  const r = canvas.getBoundingClientRect();
  return { x: Math.floor((e.clientX - r.left) / PS), y: Math.floor((e.clientY - r.top) / PS) };
}
function oob(x, y) { return x < 0 || x >= W || y < 0 || y >= H; }

function floodFill(sx, sy, fill) {
  const target  = pixels[sy][sx];
  if (target === fill) return;
  const visited = new Uint8Array(W * H);
  const stack   = [[sx, sy]];
  while (stack.length) {
    const [x, y] = stack.pop();
    if (x < 0 || x >= W || y < 0 || y >= H) continue;
    if (visited[y*W+x] || pixels[y][x] !== target) continue;
    visited[y*W+x] = 1;
    pixels[y][x]   = fill;
    stack.push([x+1,y],[x-1,y],[x,y+1],[x,y-1]);
  }
}

// ── Zoom ──────────────────────────────────────────────────────────────────
function zoom(dir) {
  const idx = ZOOM_STEPS.indexOf(PS);
  PS = ZOOM_STEPS[Math.max(0, Math.min(ZOOM_STEPS.length-1, idx+dir))];
  document.getElementById('zoomLabel').textContent = `${PS}×`;
  resizeCanvases();
  renderAll();
}

function resizeCanvases() {
  ['canvasL','canvasR'].forEach(id => {
    const c = document.getElementById(id);
    c.width  = W * PS;
    c.height = H * PS;
  });
}

// ── History ───────────────────────────────────────────────────────────────
function pushHistory() {
  if (history.length >= 80) history.shift();
  history.push({
    pixels: pixels.map(r => [...r]),
    diffs:  diffs.map(d => ({...d})),
    selMk:  selectedMarker,
  });
}

function undo() {
  if (!history.length) return;
  const snap = history.pop();
  pixels = snap.pixels;
  diffs  = snap.diffs;
  selectedMarker = snap.selMk;
  updateMarkerPanel();
  renderAll();
}

// ── Keyboard ──────────────────────────────────────────────────────────────
function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); undo(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) return;
  if (e.key === 'd') setTool('draw');
  if (e.key === 'f') setTool('fill');
  if (e.key === 'e') setTool('pick');
  if (e.key === 'm') setTool('marker');
  if ((e.key === 'Delete' || e.key === 'Backspace') && tool === 'marker') deleteMarker();
}

// ── Status ────────────────────────────────────────────────────────────────
function setStatus(txt) { document.getElementById('statusBar').textContent = txt; }

// ── Save/Reset ────────────────────────────────────────────────────────────
function saveScene() {
  const btn = document.getElementById('saveBtn');
  btn.textContent = 'Saving…'; btn.disabled = true;
  fetch('/api/draw/save', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({level: currentLevel, pixels})
  }).then(r => r.json()).then(() => {
    isCustomScene = true; updateCustomBadge();
    btn.textContent = '✓ Saved!'; btn.style.background = '#3fb950';
    setTimeout(() => { btn.textContent = '💾 Save Scene'; btn.style.background = ''; btn.disabled = false; }, 1800);
  }).catch(() => { btn.textContent = '✗ Error'; btn.disabled = false; });
}

function saveDiffs() {
  const btn = document.getElementById('saveDiffsBtn');
  btn.textContent = 'Saving…'; btn.disabled = true;
  fetch('/api/draw/save_diffs', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({level: currentLevel, diffs})
  }).then(r => r.json()).then(() => {
    isCustomDiffs = true; updateCustomBadge();
    btn.textContent = '✓ Saved!'; btn.style.background = '#3fb950';
    setTimeout(() => { btn.textContent = '💾 Save Markers'; btn.style.background = ''; btn.disabled = false; }, 1800);
  }).catch(() => { btn.textContent = '✗ Error'; btn.disabled = false; });
}

function resetLevel() {
  if (!confirm(`Reset Level ${currentLevel+1} to defaults?\nThis erases custom scene AND markers.`)) return;
  fetch('/api/draw/reset', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({level: currentLevel})
  }).then(r => r.json()).then(() => {
    history = []; selectedMarker = null;
    isCustomScene = false; isCustomDiffs = false;
    updateCustomBadge(); loadLevel(currentLevel);
  });
}

function updateCustomBadge() {
  document.getElementById('customBadge').style.display =
    (isCustomScene || isCustomDiffs) ? 'inline-block' : 'none';
}

// ── Start ─────────────────────────────────────────────────────────────────
init();
