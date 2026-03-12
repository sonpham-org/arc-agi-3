// ═══════════════════════════════════════════════════════════════════════════
// ui-grid.js — Grid rendering and canvas interaction
// Extracted from ui.js (Phase 24)
// Purpose: Grid cell rendering, canvas hover/highlight, coordinate annotation
// ═══════════════════════════════════════════════════════════════════════════

function redrawGrid() {
  if (!currentGrid) return;
  if (currentChangeMap && currentChangeMap.change_count > 0 && document.getElementById('showChanges').checked) {
    renderGridWithChanges(currentGrid, currentChangeMap);
  } else {
    renderGrid(currentGrid);
  }
}

function renderGrid(grid) {
  if (!grid || !grid.length) return;
  currentGrid = grid;  // ui.js-specific side effect
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
}

function renderGridWithChanges(grid, changeMap) {
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
  const enabled = document.getElementById('showChanges') ? document.getElementById('showChanges').checked : true;
  const opacityEl = document.getElementById('changeOpacity');
  const colorEl = document.getElementById('changeColor');
  const opacity = opacityEl ? parseInt(opacityEl.value) / 100 : 0.4;
  const color = colorEl ? colorEl.value : '#ff0000';
  renderGridWithChangesOnCanvas(grid, changeMap, canvas, ctx, COLORS, { opacity, color, stroke: true, enabled });
}

// ═══════════════════════════════════════════════════════════════════════════
// COORDINATE TOOLTIP & HIGHLIGHT
// ═══════════════════════════════════════════════════════════════════════════

let _canvasHoverCell = null;  // {row, col} of cell under cursor

function drawCanvasHover(row, col) {
  if (!currentGrid) return;
  const h = currentGrid.length, w = currentGrid[0].length;
  if (row < 0 || row >= h || col < 0 || col >= w) return;
  const scale = Math.floor(512 / Math.max(h, w));
  ctx.save();
  ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
  ctx.fillRect(col * scale, row * scale, scale, scale);
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
  ctx.lineWidth = 1;
  ctx.strokeRect(col * scale + 0.5, row * scale + 0.5, scale - 1, scale - 1);
  ctx.restore();
}

canvas.addEventListener('mousemove', (e) => {
  const tip = document.getElementById('coordTooltip');
  if (!currentGrid) { tip.style.display = 'none'; _canvasHoverCell = null; return; }
  const rect = canvas.getBoundingClientRect();
  const h = currentGrid.length, w = currentGrid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  const gx = Math.floor((e.clientX - rect.left) * (canvas.width / rect.width) / scale);
  const gy = Math.floor((e.clientY - rect.top) * (canvas.height / rect.height) / scale);
  if (gx < 0 || gx >= w || gy < 0 || gy >= h) {
    tip.style.display = 'none';
    if (_canvasHoverCell) { _canvasHoverCell = null; renderGrid(currentGrid); }
    return;
  }
  // Tooltip
  if (document.getElementById('coordToggle').checked) {
    tip.textContent = `(${gy}, ${gx})`;
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY - 8) + 'px';
  } else {
    tip.style.display = 'none';
  }
  // Cell hover highlight
  if (!_canvasHoverCell || _canvasHoverCell.row !== gy || _canvasHoverCell.col !== gx) {
    _canvasHoverCell = {row: gy, col: gx};
    renderGrid(currentGrid);
    if (_highlightCells.length) drawCellHighlights(_highlightCells);
    drawCanvasHover(gy, gx);
  }
});

canvas.addEventListener('mouseleave', () => {
  document.getElementById('coordTooltip').style.display = 'none';
  if (_canvasHoverCell) {
    _canvasHoverCell = null;
    renderGrid(currentGrid);
    if (_highlightCells.length) drawCellHighlights(_highlightCells);
  }
});

let _highlightCells = [];

function drawCellHighlights(cells) {
  if (!cells.length || !currentGrid) return;
  const h = currentGrid.length, w = currentGrid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  ctx.save();
  for (const {row, col} of cells) {
    if (row < 0 || row >= h || col < 0 || col >= w) continue;
    ctx.fillStyle = 'rgba(255, 255, 100, 0.4)';
    ctx.fillRect(col * scale, row * scale, scale, scale);
    ctx.strokeStyle = 'rgba(255, 255, 100, 0.8)';
    ctx.lineWidth = 2;
    ctx.strokeRect(col * scale + 1, row * scale + 1, scale - 2, scale - 2);
  }
  ctx.restore();
}

function highlightCellsOnCanvas(cells) {
  _highlightCells = cells;
  if (currentGrid) {
    renderGrid(currentGrid);
    drawCellHighlights(cells);
  }
}

function clearCellHighlights() {
  _highlightCells = [];
  if (currentGrid) renderGrid(currentGrid);
}

function annotateCoordRefs(element) {
  // Combined regex — order matters (longest first):
  // 1. Region: "rows N-M, cols N-M" (combined into one highlight)
  // 2. Point: (row, col)
  // 3. rows? N[-N]
  // 4. cols? N[-N]
  const COORD_RE = /(?:rows?)\s+(\d+)(?:\s*[-–]\s*(\d+))?\s*,\s*(?:cols?)\s+(\d+)(?:\s*[-–]\s*(\d+))?|\((\d+),\s*(\d+)\)|(?:rows?)\s+(\d+)(?:\s*[-–]\s*(\d+))?|(?:cols?)\s+(\d+)(?:\s*[-–]\s*(\d+))?/gi;

  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  for (const node of textNodes) {
    const text = node.textContent;
    COORD_RE.lastIndex = 0;
    if (!COORD_RE.test(text)) continue;
    COORD_RE.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let match;
    while ((match = COORD_RE.exec(text)) !== null) {
      if (match.index > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      }
      const span = document.createElement('span');
      span.className = 'coord-ref';
      if (match[1] !== undefined) {
        // Region: rows N-M, cols N-M
        span.dataset.rows = match[2] !== undefined ? `${match[1]}-${match[2]}` : match[1];
        span.dataset.cols = match[4] !== undefined ? `${match[3]}-${match[4]}` : match[3];
      } else if (match[5] !== undefined) {
        // (row, col) point
        span.dataset.row = match[5];
        span.dataset.col = match[6];
      } else if (match[7] !== undefined) {
        // rows N or rows N-M
        span.dataset.rows = match[8] !== undefined ? `${match[7]}-${match[8]}` : match[7];
      } else if (match[9] !== undefined) {
        // cols N or cols N-M
        span.dataset.cols = match[10] !== undefined ? `${match[9]}-${match[10]}` : match[9];
      }
      span.textContent = match[0];
      frag.appendChild(span);
      lastIdx = COORD_RE.lastIndex;
    }
    if (lastIdx < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    }
    if (lastIdx > 0) node.parentNode.replaceChild(frag, node);
  }
}

function cellsFromCoordRef(ref) {
  const cells = [];
  if (!currentGrid) return cells;
  const h = currentGrid.length, w = currentGrid[0].length;
  if (ref.dataset.row !== undefined && ref.dataset.col !== undefined) {
    // Single point
    cells.push({row: parseInt(ref.dataset.row), col: parseInt(ref.dataset.col)});
  } else if (ref.dataset.rows !== undefined && ref.dataset.cols !== undefined) {
    // Region: rows + cols combined
    const rp = ref.dataset.rows.split('-').map(Number);
    const cp = ref.dataset.cols.split('-').map(Number);
    const r0 = rp[0], r1 = rp.length > 1 ? rp[1] : r0;
    const c0 = cp[0], c1 = cp.length > 1 ? cp[1] : c0;
    for (let r = r0; r <= r1; r++)
      for (let c = c0; c <= c1; c++) cells.push({row: r, col: c});
  } else if (ref.dataset.rows !== undefined) {
    // Rows only — highlight full rows
    const parts = ref.dataset.rows.split('-').map(Number);
    const r0 = parts[0], r1 = parts.length > 1 ? parts[1] : r0;
    for (let r = r0; r <= r1; r++)
      for (let c = 0; c < w; c++) cells.push({row: r, col: c});
  } else if (ref.dataset.cols !== undefined) {
    // Cols only — highlight full columns
    const parts = ref.dataset.cols.split('-').map(Number);
    const c0 = parts[0], c1 = parts.length > 1 ? parts[1] : c0;
    for (let r = 0; r < h; r++)
      for (let c = c0; c <= c1; c++) cells.push({row: r, col: c});
  }
  return cells;
}

// Event delegation for coord-ref hover on reasoning content
document.addEventListener('mouseover', (e) => {
  const ref = e.target.closest('.coord-ref');
  if (!ref) return;
  highlightCellsOnCanvas(cellsFromCoordRef(ref));
});
document.addEventListener('mouseout', (e) => {
  const ref = e.target.closest('.coord-ref');
  if (!ref) return;
  clearCellHighlights();
});
