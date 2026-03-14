// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: In-app observatory mode lifecycle management for ARC-AGI-3 (index.html only).
//   Provides enterObservatoryMode(), exitObservatoryMode(), and updateObservatoryStatus()
//   for toggling the observatory panel during live gameplay. Coordinates with session.js,
//   reasoning.js, and state.js globals. NOT used in standalone obs.html/obs-page.js context.
//   Extracted from observatory.js in Phase 4. Loaded after session.js.
// SRP/DRY check: Pass — lifecycle logic separated from rendering (obs-log-renderer.js,
//   obs-scrubber.js, obs-swimlane-renderer.js)
/**
 * obs-lifecycle.js — In-app observatory mode lifecycle management.
 *
 * Requires: state.js, reasoning.js, session.js (agentColor, getActiveSession, moveHistory,
 *           renderGrid, unlockSettings, ACTION_NAMES, COLORS)
 *
 * NOT for use in obs.html / obs-page.js context.
 * Loaded by templates/index.html only, after session.js.
 *
 * Extracted from observatory.js — Phase 4 modularization.
 */

function enterObsMode(ss) {
  if (!ss) ss = getActiveSession();
  if (!ss) return;
  ss._obsStartTime = ss._obsStartTime || performance.now();
  ss._obsEvents = ss._obsEvents || [];
  ss._obsSyncCursor = ss._obsSyncCursor || 0;

  // Toggle to observatory view via CSS class (hides sidebar + game-area + right-panel, shows obs-screen)
  document.getElementById('outerLayout')?.classList.add('view-observatory');

  // Move the game canvas into the obs right panel
  const canvasEl = document.getElementById('gameCanvas');
  const obsHost = document.getElementById('obsCanvasHost');
  if (canvasEl && obsHost) {
    obsHost.appendChild(canvasEl);
    canvasEl.style.display = '';
    canvasEl.style.maxWidth = '100%';
    canvasEl.style.maxHeight = '100%';
  }

  // Update pause button
  const pauseBtn = document.getElementById('obsPauseBtn');
  if (pauseBtn) pauseBtn.innerHTML = (ss.autoPlaying) ? '&#10074;&#10074; Pause' : '&#187; Resume';

  // Disable Observatory button while in obs mode (it's always visible now)
  const obsBtn = document.getElementById('backToObsBtn');
  if (obsBtn) { obsBtn.disabled = true; obsBtn.classList.remove('btn-obs-active'); }

  // Re-render from existing events
  renderObsScreen(ss);
  startObsSync(ss);

  // Mirror reasoning panel changes to obs reasoning (debounced)
  if (window._obsReasoningObserver) window._obsReasoningObserver.disconnect();
  const _rcSrc = document.getElementById('reasoningContent');
  if (_rcSrc) {
    let _syncTimer = null;
    window._obsReasoningObserver = new MutationObserver(() => {
      if (_syncTimer) return;
      _syncTimer = setTimeout(() => { _syncTimer = null; syncObsReasoning(); }, 300);
    });
    window._obsReasoningObserver.observe(_rcSrc, { childList: true, subtree: true });
  }

  // Initialize scrubber with current move history
  _obsScrubLive = true;
  obsScrubUpdate();

  // Initialize memory panel by replaying all existing steps
  if (typeof obsMemoryInit === 'function') obsMemoryInit();

  // Start elapsed timer only if autoplay is active
  if (ss.autoPlaying) {
    _obsElapsedTimer = setInterval(() => updateObsElapsed(ss), 1000);
  }
}

function exitObsMode() {
  stopObsSync();
  if (_obsElapsedTimer) { clearInterval(_obsElapsedTimer); _obsElapsedTimer = null; }
  if (window._obsReasoningObserver) { window._obsReasoningObserver.disconnect(); window._obsReasoningObserver = null; }

  // Toggle back to settings view via CSS class
  document.getElementById('outerLayout')?.classList.remove('view-observatory');

  // Move canvas back — insert before the transport bar so it doesn't end up below it
  const canvasEl = document.getElementById('gameCanvas');
  const _ml = document.getElementById('mainLayout');
  const canvasCenter = _ml.querySelector('.canvas-center');
  if (canvasEl && canvasCenter) {
    const transportBar = document.getElementById('transportBar');
    if (transportBar) {
      canvasCenter.insertBefore(canvasEl, transportBar);
    } else {
      canvasCenter.appendChild(canvasEl);
    }
  }
  unlockSettings();

  // Enable Observatory button with active pulse to show session is running
  const obsBtn = document.getElementById('backToObsBtn');
  if (obsBtn) {
    const ss = getActiveSession();
    obsBtn.disabled = false;
    if (ss && ss.autoPlaying) {
      obsBtn.classList.add('btn-obs-active');
    } else {
      obsBtn.classList.remove('btn-obs-active');
    }
  }
}

function syncObsReasoning() {
  const src = document.getElementById('reasoningContent');
  const dst = document.getElementById('obsReasoningContent');
  if (!src || !dst) return;
  // Preserve open state of <details> elements so user-expanded sections survive the sync
  const openDetails = new Set();
  dst.querySelectorAll('details').forEach((d, i) => { if (d.open) openDetails.add(i); });
  // Check if source has meaningful content (not all human entries for an agent session)
  const hasLLMEntries = src.querySelector('.reasoning-entry:not(.human)');
  if (hasLLMEntries || !src.querySelector('.reasoning-entry')) {
    dst.innerHTML = src.innerHTML;
    // Restore open state after innerHTML replacement
    dst.querySelectorAll('details').forEach((d, i) => { if (openDetails.has(i)) d.open = true; });
    // Add click-to-navigate on mirrored entries that have data-step-nums
    dst.querySelectorAll('.reasoning-entry[data-step-nums]').forEach(el => {
      el.style.cursor = 'pointer';
      el.onclick = function() {
        const nums = (this.dataset.stepNums || '').split(',').map(Number).filter(n => n > 0);
        if (nums.length) obsScrubShow(nums[0] - 1);
      };
    });
  } else {
    // All entries are "human" — likely a legacy agent session without stored LLM responses
    // Build a compact step list from moveHistory, enriched with obs events / timeline data
    const ss = getActiveSession();
    const hist = ss?.moveHistory || moveHistory || [];
    if (hist.length === 0) { dst.innerHTML = src.innerHTML; return; }
    // Build a map of step_num → obs event data for enrichment
    const obsMap = {};
    const obsEvents = ss?._obsEvents || [];
    for (const ev of obsEvents) {
      if (ev.step_num != null) {
        if (!obsMap[ev.step_num]) obsMap[ev.step_num] = [];
        obsMap[ev.step_num].push(ev);
      }
    }
    let html = '';
    for (const h of hist) {
      const aName = ACTION_NAMES[h.action] || ('ACTION' + h.action);
      let obs = h.observation || '';
      let reason = h.reasoning || '';
      // Enrich from obs events if step-level data is empty
      if (!obs && !reason && obsMap[h.step]) {
        for (const oev of obsMap[h.step]) {
          if (oev.reasoning && !reason) reason = oev.reasoning;
          if (oev.summary && !obs) obs = oev.summary;
          if (oev.action_name && !obs) obs = oev.action_name;
        }
      }
      const cc = h.change_map?.change_count || 0;
      const ccStr = cc > 0 ? ` | ${cc} cells` : '';
      const agentLabel = obsMap[h.step]?.[0]?.agent ? ` [${obsMap[h.step][0].agent}]` : '';
      const reasonStr = reason ? `<div style="font-size:10px;color:var(--text-dim);margin-top:1px;">${reason.substring(0, 120)}</div>` : '';
      html += `<div class="reasoning-entry" data-step-nums="${h.step}" style="cursor:pointer;" onclick="obsScrubShow(${h.step - 1})">`;
      html += `<div class="step-label">Step ${h.step} — ${aName}${agentLabel}${ccStr}</div>`;
      if (obs) html += `<div style="font-size:10px;color:var(--accent);">${obs.substring(0, 150)}</div>`;
      html += reasonStr;
      html += `</div>`;
    }
    dst.innerHTML = html;
  }
  // Auto-scroll to bottom (scroll the log sub-container, not the outer flex wrap)
  const logWrap = dst.closest('.obs-reasoning-log') || dst.closest('.obs-reasoning-wrap');
  if (logWrap) logWrap.scrollTop = logWrap.scrollHeight;
}

// ── Server sync (POST new events every 5s) ──

function startObsSync(ss) {
  stopObsSync();
  _obsSyncTimer = setInterval(() => syncObsEvents(ss), 5000);
}

function stopObsSync() {
  if (_obsSyncTimer) { clearInterval(_obsSyncTimer); _obsSyncTimer = null; }
}

async function syncObsEvents(ss) {
  if (!ss || !ss._obsEvents || !ss.sessionId) return;
  const cursor = ss._obsSyncCursor || 0;
  const events = ss._obsEvents.slice(cursor);
  if (events.length === 0) return;
  try {
    const resp = await fetch(`/api/sessions/${ss.sessionId}/obs-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events, cursor }),
    });
    if (resp.ok) {
      const data = await resp.json();
      ss._obsSyncCursor = data.cursor || (cursor + events.length);
    }
  } catch (e) {
    console.warn('[obsSync] Failed:', e);
  }
}
