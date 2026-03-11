// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Shared observatory log/tooltip rendering utilities for ARC-AGI-3. Provides
//   obsSharedFmtK() (K/M number formatting), positionTooltip(), hideTooltip(), and
//   step log entry rendering helpers shared by both obs-page.js (standalone) and
//   observatory.js (in-app). No DOM dependencies except tooltip positioning.
//   Extracted from obs-page.js and observatory.js in Phase 4. Uses utils/formatting.js
//   for HTML escaping. Must load BEFORE obs-page.js and observatory.js.
// SRP/DRY check: Pass — shared rendering helpers consolidated; eliminates duplication
//   between standalone and in-app observatory views
/**
 * obs-log-renderer.js — Shared utility functions for observatory log/tooltip rendering.
 * No DOM dependencies except positionTooltip and hideTooltip.
 * Extracted from obs-page.js and observatory.js — Phase 4 modularization.
 *
 * Note: escapeHtml / escapeHtmlAttr are already provided by utils/formatting.js.
 * This module provides the obs-specific numeric formatting and tooltip helpers.
 */

function obsSharedFmtK(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toString();
}

function obsSharedHexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Position a tooltip element near the mouse event, keeping within viewport.
 * @param {HTMLElement} tt - the tooltip element (must already have .visible class and content)
 * @param {MouseEvent} e
 */
function obsSharedPositionTooltip(tt, e) {
  const pad = 12;
  let left = e.clientX + pad;
  let top = e.clientY + pad;
  const ttRect = tt.getBoundingClientRect();
  if (left + ttRect.width > window.innerWidth - 10) left = e.clientX - ttRect.width - pad;
  if (top + ttRect.height > window.innerHeight - 10) top = e.clientY - ttRect.height - pad;
  tt.style.left = Math.max(0, left) + 'px';
  tt.style.top = Math.max(0, top) + 'px';
}

/**
 * Hide a tooltip by id.
 * @param {string} tooltipId - defaults to 'tooltip'
 */
function obsSharedHideTooltip(tooltipId = 'tooltip') {
  document.getElementById(tooltipId)?.classList.remove('visible');
}
