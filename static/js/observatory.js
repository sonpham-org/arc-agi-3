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

const OBS_AGENT_COLORS = {
  executor: '#58a6ff', planner: '#58a6ff', monitor: '#d29922',
  world_model: '#bc8cff', repl: '#3fb950', compact: '#bc8cff',
  interrupt: '#d29922', orchestrator: '#3b82f6', explorer: '#22c55e',
  theorist: '#a855f7', tester: '#f97316', solver: '#ef4444',
};
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

function obsAgentColor(agent) {
  if (!agent) return OBS_DEFAULT_COLOR;
  return OBS_AGENT_COLORS[agent.toLowerCase()] || OBS_DEFAULT_COLOR;
}

function obsAgentBadge(agent) {
  if (!agent) return '<span style="color:var(--text-dim)">--</span>';
  const c = obsAgentColor(agent);
  return `<span class="obs-agent-badge" style="background:${c}">${agent}</span>`;
}

function obsFmtK(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toString();
}

function obsHexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function obsEscHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

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

// ── Enter / exit obs mode ──

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

  // Hide "Back to Observatory" button since we're in obs mode
  const obsBtn = document.getElementById('backToObsBtn');
  if (obsBtn) obsBtn.style.display = 'none';

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

  // Move canvas back
  const canvasEl = document.getElementById('gameCanvas');
  const _ml = document.getElementById('mainLayout');
  const canvasCenter = _ml.querySelector('.canvas-center');
  if (canvasEl && canvasCenter) {
    canvasCenter.appendChild(canvasEl);
  }
  unlockSettings();

  // Show "Back to Observatory" button in transport bar
  const obsBtn = document.getElementById('backToObsBtn');
  if (obsBtn) obsBtn.style.display = '';
}

// ── Full re-render ──

function syncObsReasoning() {
  const src = document.getElementById('reasoningContent');
  const dst = document.getElementById('obsReasoningContent');
  if (!src || !dst) return;
  // Check if source has meaningful content (not all human entries for an agent session)
  const hasLLMEntries = src.querySelector('.reasoning-entry:not(.human)');
  if (hasLLMEntries || !src.querySelector('.reasoning-entry')) {
    dst.innerHTML = src.innerHTML;
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
  // Auto-scroll to bottom
  const wrap = dst.closest('.obs-reasoning-wrap');
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

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
  document.getElementById('obsTokens').textContent = `${obsFmtK(tokIn)} / ${obsFmtK(tokOut)}`;
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
  const c = obsAgentColor(agent);
  tr.style.borderLeft = `3px solid ${c}`;

  const time = ev.t ? ev.t.split('T')[1]?.split('.')[0] || ev.t : '';
  const elapsed = ev.elapsed_s != null ? `+${ev.elapsed_s.toFixed(0)}` : '';
  const tokIn = ev.input_tokens || '';
  const tokOut = ev.output_tokens || '';
  const dur = ev.duration_ms ? `${ev.duration_ms}ms` : '';

  let details = obsEscHtml(obsBuildDetails(ev));
  let expandHtml = '';
  if (ev.summary || ev.error || ev.response_preview) {
    const parts = [];
    if (ev.response_preview) parts.push(obsEscHtml(ev.response_preview));
    if (ev.error) parts.push(`<span style="color:var(--red)">Error: ${obsEscHtml(ev.error)}</span>`);
    if (ev.summary) parts.push(obsEscHtml(ev.summary));
    expandHtml = `<div class="obs-response-detail">${parts.join('\n')}</div>`;
  }

  tr.innerHTML = `
    <td>${time}</td>
    <td class="obs-dur">${elapsed}</td>
    <td>${obsAgentBadge(agent)}</td>
    <td>${ev.event || ''}</td>
    <td class="obs-details" title="Click to expand">${details}${expandHtml}</td>
    <td class="obs-tok">${tokIn ? obsFmtK(tokIn) + '/' + obsFmtK(tokOut) : ''}</td>
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
  switch (ev.event) {
    case 'llm_call': return `model: ${ev.model || '?'}${ev.summary ? ' — ' + ev.summary : ''}`;
    case 'act': return ev.action || '';
    case 'compact': return 'context compacted';
    case 'interrupt': return ev.summary || 'interrupt check';
    case 'repl_exec': return ev.summary || 'REPL execution';
    case 'monitor_call': return ev.summary || 'monitor check';
    case 'wm_update': return ev.summary || 'world model update';
    case 'planner_call': return ev.summary || 'planner REPL';
    default:
      const skip = new Set(['t','elapsed_s','event','agent','grid','input_tokens','output_tokens','duration_ms','cost','step_num','turn','model','summary','error','response_preview','action']);
      const extra = Object.entries(ev).filter(([k]) => !skip.has(k) && ev[k] != null);
      return extra.map(([k,v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
  }
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
    document.getElementById('obsScrubLbl').textContent = `Step ${total} / ${total}`;
    const dot = document.getElementById('obsScrubDot');
    dot.className = 'obs-scrub-dot is-live';
    dot.innerHTML = '&#9679; LIVE';
    document.getElementById('obsScrubBanner').style.display = 'none';
  } else {
    document.getElementById('obsScrubLbl').textContent = `Step ${_obsScrubIdx + 1} / ${total}`;
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
  document.getElementById('obsScrubLbl').textContent = `Step ${idx + 1} / ${hist.length}`;
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
    const c = obsAgentColor(agent);
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
      const c = obsAgentColor(agent);
      let html = `<div class="tt-agent" style="color:${c}">${agent || 'system'}</div>`;
      html += `<div>${ev.event || ''}</div>`;
      if (ev.elapsed_s != null) html += `<div class="tt-dim">t = +${ev.elapsed_s.toFixed(1)}s</div>`;
      if (ev.duration_ms) html += `<div>Duration: ${ev.duration_ms}ms</div>`;
      if (ev.input_tokens) html += `<div>Tokens: ${obsFmtK(ev.input_tokens)} in / ${obsFmtK(ev.output_tokens || 0)} out</div>`;
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
