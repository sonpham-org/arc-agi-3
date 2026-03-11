// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Shared scrubber (step slider) UI logic for ARC-AGI-3 observatory views.
//   Provides initScrubber(), updateScrubber(), and scrubber event binding for both
//   standalone obs.html and in-app observatory mode. Manages slider range, step label,
//   live/paused dot indicator, and "viewing step N" banner. Extracted from obs-page.js
//   and observatory.js in Phase 4. Requires DOM elements: #obsScrubSlider,
//   #obsScrubLabel, #obsScrubDot, #obsScrubBanner, #obsScrubBannerText.
// SRP/DRY check: Pass — scrubber logic consolidated; shared between standalone and in-app views
/**
 * obs-scrubber.js — Shared scrubber UI logic for Observatory views.
 * Extracted from obs-page.js and observatory.js — Phase 4 modularization.
 *
 * Requires DOM elements:
 *   #obsScrubSlider      — <input type="range">
 *   #obsScrubLabel       — text label "Step N / T"
 *   #obsScrubDot         — live/paused indicator
 *   #obsScrubBanner      — "viewing step N" banner
 *   #obsScrubBannerText  — text inside banner
 *
 * Usage:
 *   obsScrubSetLive(totalSteps)
 *   obsScrubSetHistorical(stepIdx, totalSteps, stepLabel)
 *   obsScrubHideBanner()
 *
 * Note: observatory.js (index.html context) uses #obsScrubLbl (no 'e').
 * The index.html template must use #obsScrubLabel to match this shared module.
 */

function obsScrubSetLive(totalSteps) {
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  slider.max = Math.max(0, totalSteps - 1);
  slider.value = Math.max(0, totalSteps - 1);
  const labelEl = document.getElementById('obsScrubLabel');
  if (labelEl) labelEl.textContent = `Step ${totalSteps} / ${totalSteps}`;
  const dot = document.getElementById('obsScrubDot');
  if (dot) { dot.className = 'obs-scrubber-dot is-live'; dot.innerHTML = '&#9679; LIVE'; }
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'none';
}

function obsScrubSetHistorical(stepIdx, totalSteps, stepLabel) {
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  slider.max = Math.max(0, totalSteps - 1);
  slider.value = stepIdx;
  const labelEl = document.getElementById('obsScrubLabel');
  if (labelEl) labelEl.textContent = `Step ${stepIdx + 1} / ${totalSteps}`;
  const dot = document.getElementById('obsScrubDot');
  if (dot) { dot.className = 'obs-scrubber-dot is-historical'; dot.innerHTML = '&#9679; PAUSED'; }
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'flex';
  const bannerText = document.getElementById('obsScrubBannerText');
  if (bannerText) bannerText.textContent = stepLabel || `Viewing step ${stepIdx + 1}`;
}

function obsScrubHideBanner() {
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'none';
}
