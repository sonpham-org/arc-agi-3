// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Canvas grid rendering for ARC-AGI-3 web UI. Provides renderGridOnCanvas()
//   and renderGridWithChangesOnCanvas() — low-level canvas drawing of game grids with
//   optional change map overlay (opacity, color, stroke). Does NOT manage currentGrid
//   state — ui.js wrapper handles that. Extracted from ui.js in Phase 3.
//   Must load BEFORE ui.js. No external dependencies beyond canvas API.
// SRP/DRY check: Pass — pure rendering logic separated from UI state management in ui.js
// ═══════════════════════════════════════════════════════════════════════════
// GRID RENDERER
// Extracted from ui.js — Phase 3 modularization
// Load order: must be loaded before ui.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Render a grid onto a canvas element.
 * NOTE: Does NOT set currentGrid — ui.js wrapper does that.
 */
function renderGridOnCanvas(grid, targetCanvas, targetCtx, colors) {
  if (!grid || !grid.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  targetCanvas.width = w * scale;
  targetCanvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      targetCtx.fillStyle = colors[grid[y][x]] || '#000';
      targetCtx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
}

/**
 * Render a grid with change highlights.
 * @param {object} opts - {opacity, color, stroke, enabled}
 */
function renderGridWithChangesOnCanvas(grid, changeMap, targetCanvas, targetCtx, colors, opts = {}) {
  renderGridOnCanvas(grid, targetCanvas, targetCtx, colors);
  if (!changeMap?.changes?.length) return;
  if (opts.enabled === false) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  const opacity = opts.opacity ?? 0.4;
  const color = opts.color ?? '#ff0000';
  const r = parseInt(color.slice(1,3), 16);
  const g = parseInt(color.slice(3,5), 16);
  const b = parseInt(color.slice(5,7), 16);
  targetCtx.fillStyle = `rgba(${r},${g},${b},${opacity})`;
  for (const c of changeMap.changes) targetCtx.fillRect(c.x * scale, c.y * scale, scale, scale);
  if (opts.stroke) {
    targetCtx.strokeStyle = `rgba(${r},${g},${b},${Math.min(opacity + 0.3, 1)})`;
    targetCtx.lineWidth = 1;
    for (const c of changeMap.changes) targetCtx.strokeRect(c.x * scale + 0.5, c.y * scale + 0.5, scale - 1, scale - 1);
  }
}
