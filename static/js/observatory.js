// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: In-app observatory mode for ARC-AGI-3 (index.html context). Provides
//   staging banner, timeline rendering (renderTimeline), live scrubber, observatory
//   event emission (emitObsEvent), and inline observatory UI for viewing session
//   metrics during gameplay. Modified in Phases 1 & 4 to extract shared rendering
//   into observatory/obs-lifecycle.js, obs-log-renderer.js, obs-scrubber.js, and
//   obs-swimlane-renderer.js. Depends on reasoning.js, state.js, session.js.
// SRP/DRY check: Pass — shared rendering in observatory/ modules; this file is the
//   in-app orchestrator only
if (window.location.hostname === 'staging.arc3.sonpham.net') {
  const b = document.createElement('div');
  b.textContent = 'STAGING';
  Object.assign(b.style, {
    position:'fixed', top:'8px', right:'8px', zIndex:'99999',
    background:'#d29922', color:'#000', padding:'2px 10px',
    borderRadius:'4px', fontSize:'11px', fontWeight:'700',
    letterSpacing:'1px', opacity:'0.85', pointerEvents:'none'
  });
  document.body.appendChild(b);
}

/* ── Theme toggle ──────────────────────────────────────────────── */
(function(){
  const saved = localStorage.getItem('arc-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeBtn();
})();
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'light' ? 'dark' : 'light';
  if (next === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('arc-theme', next);
  updateThemeBtn();
}
function updateThemeBtn() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  btn.textContent = isLight ? '\u263C' : '\u263E';
}

// ═══════════════════════════════════════════════════════════════════════════
// OBSERVABILITY SCREEN
// ═══════════════════════════════════════════════════════════════════════════

// Agent colors now provided by reasoning.js agentColor()
const OBS_DEFAULT_COLOR = '#6b7280';

/** Check if observatory view is currently active */
function isObsModeActive() {
  return document.getElementById('outerLayout')?.classList.contains('view-observatory') || false;
}

let obsAutoScroll = true;
let obsTimelineZoom = 1.0;
let obsTimelineAutoScroll = true;
let _obsSyncTimer = null;
let _obsElapsedTimer = null;

function obsAgentBadge(agent) {
  if (!agent) return '<span style="color:var(--text-dim)">--</span>';
  const c = agentColor(agent) || OBS_DEFAULT_COLOR;
  return `<span class="obs-agent-badge" style="background:${c}">${agent}</span>`;
}

// obsFmtK and obsHexToRgba moved to observatory/obs-log-renderer.js as obsSharedFmtK / obsSharedHexToRgba

// ── Event model ──

function emitObsEvent(ss, partial) {
  if (!ss || !ss._obsEvents) return;
  const t0 = ss._obsStartTime || performance.now();
  const ev = {
    t: new Date().toISOString(),
    elapsed_s: (performance.now() - t0) / 1000,
    step_num: ss.stepCount || 0,
    turn: ss.turnCounter || 0,
    ...partial,
  };
  ss._obsEvents.push(ev);
  // Update UI if obs screen is visible
  if (isObsModeActive()) {
    appendObsLogRow(ev, ss._obsEvents.length - 1);
    renderObsSwimlane(ss);
    updateObsStatus(ss);
  }
}

// ── Enter / exit obs mode and reasoning sync ──
// enterObsMode(), exitObsMode(), syncObsReasoning() moved to observatory/obs-lifecycle.js

function renderObsScreen(ss) {
  if (!ss) return;
  // Clear log body
  document.getElementById('obsLogBody').innerHTML = '';
  // Re-render all existing events
  const events = ss._obsEvents || [];
  for (let i = 0; i < events.length; i++) {
    appendObsLogRow(events[i], i);
  }
  syncObsReasoning();
  renderObsSwimlane(ss);
  updateObsStatus(ss);
}

// ── Status bar update ──

function updateObsStatus(ss) {
  if (!ss) ss = getActiveSession();
  if (!ss) return;
  const events = ss._obsEvents || [];
  const gameId = ss.gameId || ss.currentState?.game_id || currentState?.game_id || '--';
  document.getElementById('obsGame').textContent = gameId;
  document.getElementById('obsStep').textContent = ss.stepCount || 0;
  document.getElementById('obsTurn').textContent = ss.turnCounter || 0;
  document.getElementById('obsCalls').textContent = ss.llmCallCount || 0;

  // Token totals from obs events
  let tokIn = 0, tokOut = 0, cost = 0;
  for (const ev of events) {
    tokIn += ev.input_tokens || 0;
    tokOut += ev.output_tokens || 0;
    cost += ev.cost || 0;
  }
  document.getElementById('obsTokens').textContent = `${obsSharedFmtK(tokIn)} / ${obsSharedFmtK(tokOut)}`;
  const costEl = document.getElementById('obsCost');
  if (cost < 0.01) costEl.textContent = cost > 0 ? '<$0.01' : '$0.00';
  else costEl.textContent = '$' + cost.toFixed(2);
  costEl.style.color = cost > 1 ? '#ef4444' : cost > 0.10 ? '#f59e0b' : '#22c55e';

  updateObsElapsed(ss);

  // Grid info
  const gridInfo = document.getElementById('obsGridInfo');
  gridInfo.textContent = `Step ${ss.stepCount || 0}`;
}

function updateObsElapsed(ss) {
  if (!ss) return;
  const el = document.getElementById('obsElapsed');
  if (!el) return;
  let elapsedSec = 0;
  // For resumed sessions, compute elapsed from timeline timestamps
  if (ss._obsElapsedFixed != null) {
    // Fixed elapsed from historical timeline — only update if autoplay is running
    if (ss.autoPlaying && ss._obsResumedAt) {
      elapsedSec = ss._obsElapsedFixed + (performance.now() - ss._obsResumedAt) / 1000;
    } else {
      elapsedSec = ss._obsElapsedFixed;
    }
  } else if (ss._obsStartTime) {
    elapsedSec = (performance.now() - ss._obsStartTime) / 1000;
  }
  if (elapsedSec < 60) el.textContent = `${Math.round(elapsedSec)}s`;
  else if (elapsedSec < 3600) el.textContent = `${(elapsedSec / 60).toFixed(1)}m`;
  else el.textContent = `${(elapsedSec / 3600).toFixed(1)}h`;
}

// ── Log table ──

function appendObsLogRow(ev, evIdx) {
  const tbody = document.getElementById('obsLogBody');
  if (!tbody) return;
  const tr = document.createElement('tr');
  if (ev.step_num != null) tr.dataset.step = ev.step_num;
  const agent = ev.agent || '';
  const c = agentColor(agent) || OBS_DEFAULT_COLOR;
  tr.style.borderLeft = `3px solid ${c}`;

  const time = ev.t ? ev.t.split('T')[1]?.split('.')[0] || ev.t : '';
  const elapsed = ev.elapsed_s != null ? `+${ev.elapsed_s.toFixed(0)}` : '';
  const tokIn = ev.input_tokens || '';
  const tokOut = ev.output_tokens || '';
  const dur = ev.duration_ms ? `${ev.duration_ms}ms` : '';

  let details = escapeHtml(obsBuildDetails(ev));
  let expandHtml = '';
  if (ev.summary || ev.error || ev.response_preview) {
    const parts = [];
    if (ev.response_preview) parts.push(escapeHtml(ev.response_preview));
    if (ev.error) parts.push(`<span style="color:var(--red)">Error: ${escapeHtml(ev.error)}</span>`);
    if (ev.summary) parts.push(escapeHtml(ev.summary));
    expandHtml = `<div class="obs-response-detail">${parts.join('\n')}</div>`;
  }

  tr.innerHTML = `
    <td>${time}</td>
    <td class="obs-dur">${elapsed}</td>
    <td>${obsAgentBadge(agent)}</td>
    <td>${ev.event || ''}</td>
    <td class="obs-details" title="Click to expand">${details}${expandHtml}</td>
    <td class="obs-tok">${tokIn ? obsSharedFmtK(tokIn) + '/' + obsSharedFmtK(tokOut) : ''}</td>
    <td class="obs-dur">${dur}</td>
  `;
  const detailsCell = tr.querySelector('.obs-details');
  if (detailsCell) {
    detailsCell.addEventListener('click', (e) => {
      e.stopPropagation();
      detailsCell.classList.toggle('expanded');
    });
  }
  tbody.appendChild(tr);

  if (obsAutoScroll) {
    const wrap = document.getElementById('obsLogWrap');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  }
}

function obsBuildDetails(ev) {
  // Universal: use agent_type + event to build detail string
  if (ev.event === 'llm_call') return `model: ${ev.model || '?'}${ev.summary ? ' — ' + ev.summary : ''}`;
  if (ev.event === 'act') return ev.action || '';
  if (ev.summary) return ev.summary;
  // Fallback: show agent_type or extra fields
  const agentStr = ev.agent ? agentLabel(ev.agent) : '';
  if (agentStr) return agentStr;
  const skip = new Set(['t','elapsed_s','event','agent','agent_type','grid','input_tokens','output_tokens','duration_ms','cost','step_num','turn','model','summary','error','response_preview','action']);
  const extra = Object.entries(ev).filter(([k]) => !skip.has(k) && ev[k] != null);
  return extra.map(([k,v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
}

// ── Obs scrubber (in-app observatory) ──

let _obsScrubLive = true;
let _obsScrubIdx = -1;  // index into moveHistory

function obsScrubUpdate() {
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  let hist = moveHistory;
  if ((!hist || !hist.length) && getActiveSession()) hist = getActiveSession().moveHistory || [];
  const total = hist.length;
  slider.max = Math.max(0, total - 1);
  if (_obsScrubLive) {
    slider.value = Math.max(0, total - 1);
    document.getElementById('obsScrubLabel').textContent = `Step ${total} / ${total}`;
    const dot = document.getElementById('obsScrubDot');
    dot.className = 'obs-scrub-dot is-live';
    dot.innerHTML = '&#9679; LIVE';
    document.getElementById('obsScrubBanner').style.display = 'none';
  } else {
    document.getElementById('obsScrubLabel').textContent = `Step ${_obsScrubIdx + 1} / ${total}`;
  }
}

function obsScrubShow(idx) {
  // Resolve moveHistory from active session if global is empty
  let hist = moveHistory;
  if ((!hist || !hist.length) && getActiveSession()) hist = getActiveSession().moveHistory || [];
  if (idx < 0 || idx >= hist.length) return;
  _obsScrubIdx = idx;
  _obsScrubLive = false;
  const entry = hist[idx];
  if (entry && entry.grid) {
    // Render directly to the game canvas (which is inside obsCanvasHost)
    const c = document.getElementById('gameCanvas');
    if (c) {
      const cCtx = c.getContext('2d');
      const grid = entry.grid;
      const h = grid.length, w = grid[0].length;
      const scale = Math.floor(512 / Math.max(h, w));
      c.width = w * scale;
      c.height = h * scale;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          cCtx.fillStyle = COLORS[grid[y][x]] || '#000';
          cCtx.fillRect(x * scale, y * scale, scale, scale);
        }
      }
    }
  }
  const slider = document.getElementById('obsScrubSlider');
  slider.value = idx;
  document.getElementById('obsScrubLabel').textContent = `Step ${idx + 1} / ${hist.length}`;
  const banner = document.getElementById('obsScrubBanner');
  banner.style.display = 'flex';
  document.getElementById('obsScrubBannerText').textContent = `Viewing step ${idx + 1}`;
  const dot = document.getElementById('obsScrubDot');
  dot.className = 'obs-scrub-dot is-hist';
  dot.innerHTML = '&#9679; PAUSED';

  // Scroll event log to the matching step row
  _obsScrubScrollToStep(idx + 1);
  // Highlight matching reasoning entry
  _obsScrubHighlightReasoning(idx + 1);
}

function _obsScrubScrollToStep(stepNum) {
  const tbody = document.getElementById('obsLogBody');
  const wrap = document.getElementById('obsLogWrap');
  if (!tbody || !wrap) return;
  // Find the last row matching this step number
  const rows = tbody.querySelectorAll(`tr[data-step="${stepNum}"]`);
  const target = rows.length ? rows[rows.length - 1] : null;
  if (target) {
    // Remove previous highlights
    tbody.querySelectorAll('tr.obs-highlight').forEach(r => r.classList.remove('obs-highlight'));
    target.classList.add('obs-highlight');
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

function _obsScrubHighlightReasoning(stepNum) {
  const container = document.getElementById('obsReasoningContent');
  if (!container) return;
  // Find reasoning entry whose data-step-nums contains this step
  container.querySelectorAll('.reasoning-entry').forEach(el => {
    el.style.outline = '';
    const nums = (el.dataset.stepNums || '').split(',').map(Number);
    if (nums.includes(stepNum)) {
      el.style.outline = '1px solid var(--accent)';
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  });
}

function obsScrubReturnToLive() {
  _obsScrubLive = true;
  _obsScrubIdx = -1;
  document.getElementById('obsScrubBanner').style.display = 'none';
  if (currentGrid) renderGrid(currentGrid);
  obsScrubUpdate();
}

// Bind slider
document.getElementById('obsScrubSlider').oninput = function() {
  const idx = parseInt(this.value);
  let hist = moveHistory;
  if ((!hist || !hist.length) && getActiveSession()) hist = getActiveSession().moveHistory || [];
  if (idx >= hist.length - 1) {
    obsScrubReturnToLive();
  } else {
    obsScrubShow(idx);
  }
};

// ── Swimlane renderer (simplified universal version) ──

function renderObsSwimlane(ss) {
  if (!ss) ss = getActiveSession();
  const events = ss?._obsEvents || [];
  if (events.length === 0) {
    document.getElementById('obsSwimlaneCanvas').innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:8px;">Waiting for events...</div>';
    return;
  }

  const canvas = document.getElementById('obsSwimlaneCanvas');
  const container = document.getElementById('obsSwimlaneContainer');

  const t0 = events[0].elapsed_s || 0;
  const tMax = events[events.length - 1].elapsed_s || 1;
  const duration = Math.max(tMax - t0, 1);

  const containerW = container.clientWidth - 90;
  const basePxPerSec = Math.max(containerW / duration, 2);
  const pxPerSec = basePxPerSec * obsTimelineZoom;
  const totalW = Math.max(Math.ceil(duration * pxPerSec), containerW);

  // Build lanes dynamically from unique agent values
  const laneMap = new Map(); // agent -> { events: [{ev, idx}] }
  for (let i = 0; i < events.length; i++) {
    const agent = events[i].agent || 'system';
    if (!laneMap.has(agent)) laneMap.set(agent, []);
    laneMap.get(agent).push({ ev: events[i], idx: i });
  }

  let labelsHtml = '';
  let tracksHtml = '';

  for (const [agent, entries] of laneMap) {
    const c = agentColor(agent) || OBS_DEFAULT_COLOR;
    labelsHtml += `<div class="obs-swimlane-label" style="color:${c}">${agent}</div>`;
    tracksHtml += '<div class="obs-swimlane-row">';

    for (const { ev, idx } of entries) {
      const evT = ev.elapsed_s || 0;
      const evDur = ev.duration_ms ? ev.duration_ms / 1000 : 0;
      const left = (evT - t0) * pxPerSec;
      const w = Math.max((evDur || 0.1) * pxPerSec, 4);
      let opacity = '0.6';
      if (ev.event === 'act') opacity = '0.8';
      if (ev.event === 'compact' || ev.event === 'interrupt') opacity = '0.4';
      tracksHtml += `<div class="obs-event-block" style="left:${left}px;width:${w}px;background:${c};opacity:${opacity}" data-obs-idx="${idx}"></div>`;
    }

    tracksHtml += '</div>';
  }

  const tracksCanvasW = totalW + 10;
  canvas.innerHTML =
    `<div class="obs-swimlane-wrap">` +
      `<div class="obs-swimlane-labels">${labelsHtml}</div>` +
      `<div class="obs-swimlane-tracks-scroll" id="obsSwimlaneScroll">` +
        `<div class="obs-swimlane-tracks-canvas" style="width:${tracksCanvasW}px">${tracksHtml}</div>` +
      `</div>` +
    `</div>`;

  // Auto-scroll
  if (obsTimelineAutoScroll) {
    const scrollEl = document.getElementById('obsSwimlaneScroll');
    if (scrollEl) scrollEl.scrollLeft = scrollEl.scrollWidth;
  }

  // Tooltips
  canvas.querySelectorAll('.obs-event-block[data-obs-idx]').forEach(el => {
    el.addEventListener('mouseenter', (e) => {
      const idx = parseInt(e.target.dataset.obsIdx);
      const ev = events[idx];
      if (!ev) return;
      const agent = ev.agent || '';
      const c = agentColor(agent) || OBS_DEFAULT_COLOR;
      let html = `<div class="tt-agent" style="color:${c}">${agent || 'system'}</div>`;
      html += `<div>${ev.event || ''}</div>`;
      if (ev.elapsed_s != null) html += `<div class="tt-dim">t = +${ev.elapsed_s.toFixed(1)}s</div>`;
      if (ev.duration_ms) html += `<div>Duration: ${ev.duration_ms}ms</div>`;
      if (ev.input_tokens) html += `<div>Tokens: ${obsSharedFmtK(ev.input_tokens)} in / ${obsSharedFmtK(ev.output_tokens || 0)} out</div>`;
      if (ev.action) html += `<div>Action: ${ev.action}</div>`;
      if (ev.model) html += `<div>Model: ${ev.model}</div>`;
      const tt = document.getElementById('obsTooltip');
      tt.innerHTML = html;
      tt.classList.add('visible');
      const pad = 12;
      tt.style.left = Math.max(0, e.clientX + pad) + 'px';
      tt.style.top = Math.max(0, e.clientY + pad) + 'px';
    });
    el.addEventListener('mouseleave', () => {
      document.getElementById('obsTooltip').classList.remove('visible');
    });
  });
}

// Ctrl+Scroll zoom on swimlane
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('obsSwimlaneContainer');
  if (container) {
    container.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.25 : 0.8;
      obsTimelineZoom = Math.max(0.1, Math.min(100, obsTimelineZoom * factor));
      obsTimelineAutoScroll = false;
      document.getElementById('obsZoomLabel').textContent = obsTimelineZoom.toFixed(1) + 'x';
      const ss = getActiveSession();
      renderObsSwimlane(ss);
    }, { passive: false });
  }
});

// ── Server sync ──
// startObsSync(), stopObsSync(), syncObsEvents() moved to observatory/obs-lifecycle.js
