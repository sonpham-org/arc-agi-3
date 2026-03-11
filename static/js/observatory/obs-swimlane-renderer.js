// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Shared swimlane timeline rendering for ARC-AGI-3 observatory views.
//   Provides renderSwimlane(config) — builds and injects HTML/CSS swimlane timeline
//   with labeled agent lanes, colored step blocks, and scroll-synced tracks. Used by
//   both standalone obs-page.js and in-app observatory.js. Extracted from obs-page.js
//   and observatory.js in Phase 4. Depends on reasoning.js (agentColor) and
//   utils/formatting.js (escapeHtml). Must load BEFORE obs-page.js and observatory.js.
// SRP/DRY check: Pass — swimlane rendering consolidated; shared between both observatory contexts
/**
 * obs-swimlane-renderer.js — Shared swimlane rendering helper.
 * Extracted from obs-page.js and observatory.js — Phase 4 modularization.
 *
 * renderSwimlane(config) — builds and injects the swimlane HTML
 *   config = {
 *     canvasId: string,          // element to inject HTML into
 *     scrollId: string,          // scrollable tracks element id
 *     scrollClass: string,       // CSS class for the scroll wrapper div
 *     lanes: [{                  // ordered lanes to render
 *       label: string,
 *       color: string,           // hex color
 *       blocks: [{
 *         startT: number,        // seconds from t0
 *         endT: number,
 *         opacity: number,
 *         color: string?,        // override lane color per block
 *         dataAttr: string?,     // e.g. 'data-obs-idx="3"'
 *       }]
 *     }],
 *     t0: number,                // timeline start (seconds)
 *     pxPerSec: number,          // pixels per second (post-zoom)
 *     totalW: number,            // total canvas width in px
 *     autoScroll: boolean,
 *     labelClass: string,        // CSS class for label divs
 *     rowClass: string,          // CSS class for row divs
 *     blockClass: string,        // CSS class for event blocks
 *     wrapClass: string,         // CSS class for outer wrap
 *   }
 *
 * The caller builds the `lanes` array and handles tooltip binding after render.
 */
function renderSwimlane(config) {
  const canvas = document.getElementById(config.canvasId);
  if (!canvas) return;
  let labelsHtml = '';
  let tracksHtml = '';

  for (const lane of config.lanes) {
    labelsHtml += `<div class="${config.labelClass}" style="color:${lane.color}">${lane.label}</div>`;
    tracksHtml += `<div class="${config.rowClass}">`;
    for (const blk of lane.blocks) {
      const left = (blk.startT - config.t0) * config.pxPerSec;
      const w = Math.max((blk.endT - blk.startT) * config.pxPerSec, 4);
      tracksHtml += `<div class="${config.blockClass}" style="left:${left}px;width:${w}px;background:${blk.color || lane.color};opacity:${blk.opacity}" ${blk.dataAttr || ''}></div>`;
    }
    tracksHtml += '</div>';
  }

  canvas.innerHTML =
    `<div class="${config.wrapClass}">` +
      `<div class="${config.labelClass}-column">${labelsHtml}</div>` +
      `<div class="${config.scrollClass}" id="${config.scrollId}">` +
        `<div style="width:${config.totalW + 10}px">${tracksHtml}</div>` +
      `</div>` +
    `</div>`;

  if (config.autoScroll) {
    const scrollEl = document.getElementById(config.scrollId);
    if (scrollEl) scrollEl.scrollLeft = scrollEl.scrollWidth;
  }
}
