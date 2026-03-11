// ═══════════════════════════════════════════════════════════════════════════
// formatting.js — Canonical HTML escaping and formatting utilities
//
// Load this file BEFORE any script that needs escapeHtml, formatDuration,
// or formatCost. It defines globals; no module system required.
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Escape a string for safe HTML text content insertion.
 * Handles null/undefined → empty string. Coerces non-strings via String().
 * Escapes: & < >
 */
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Escape a string for safe insertion into an HTML attribute value.
 * Same as escapeHtml but also escapes double-quotes.
 * Use when building: <tag attr="${escapeHtmlAttr(value)}">
 */
function escapeHtmlAttr(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Format a duration in seconds to a human-readable string.
 * Examples: 3661 → "1h1m", 125 → "2m5s", 45 → "45s"
 * @param {number} seconds
 * @returns {string}
 */
function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m > 60) return `${Math.floor(m / 60)}h${m % 60}m`;
  if (m > 0) return `${m}m${s}s`;
  return `${s}s`;
}

/**
 * Format a USD cost value for display.
 * Examples: 0.00123 → "$0.0012", 1.5 → "$1.5000"
 * @param {number} cost - Cost in USD
 * @param {number} [decimals=4] - Decimal places
 * @returns {string}
 */
function formatCost(cost, decimals = 4) {
  if (cost == null || isNaN(cost)) return '';
  return `$${cost.toFixed(decimals)}`;
}
