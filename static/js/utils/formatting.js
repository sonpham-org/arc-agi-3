// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Canonical HTML escaping and formatting utilities for ARC-AGI-3 web UI.
//   Provides escapeHtml (XSS-safe text insertion), _esc (alias), formatDuration
//   (ms → human-readable), and formatCost (USD formatting). Extracted from inline
//   code in Phase 1 to eliminate duplication across llm.js, observatory.js, obs-page.js,
//   share-page.js. Defines globals — no module system. Must load BEFORE all other scripts.
// SRP/DRY check: Pass — single source of truth for HTML escaping and number formatting
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
