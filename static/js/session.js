// ═══════════════════════════════════════════════════════════════════════════
// SESSION HISTORY + REPLAY
// ═══════════════════════════════════════════════════════════════════════════

let replayData = null; // { session, steps }

// ═══════════════════════════════════════════════════════════════════════════
// LOCAL SESSION STORAGE (localStorage-based, per-user)
// ═══════════════════════════════════════════════════════════════════════════

const LOCAL_SESSIONS_KEY = 'arc_sessions_index';
const LOCAL_SESSION_PREFIX = 'arc_session_data:';
const MAX_LOCAL_SESSIONS = 50;

function getLocalSessions() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_SESSIONS_KEY) || '[]');
  } catch { return []; }
}

function saveLocalSessionIndex(sessions) {
  // Keep only the most recent MAX_LOCAL_SESSIONS
  const trimmed = sessions.slice(0, MAX_LOCAL_SESSIONS);
  localStorage.setItem(LOCAL_SESSIONS_KEY, JSON.stringify(trimmed));
  // Clean up data for sessions that fell off
  if (sessions.length > MAX_LOCAL_SESSIONS) {
    for (const s of sessions.slice(MAX_LOCAL_SESSIONS)) {
      localStorage.removeItem(LOCAL_SESSION_PREFIX + s.id);
    }
  }
}

function saveLocalSession(sessionMeta, steps) {
  // Update index (newest first)
  const sessions = getLocalSessions().filter(s => s.id !== sessionMeta.id);
  sessions.unshift(sessionMeta);
  saveLocalSessionIndex(sessions);
  // Save full session data (steps with grids)
  try {
    localStorage.setItem(LOCAL_SESSION_PREFIX + sessionMeta.id,
      JSON.stringify({ session: sessionMeta, steps }));
  } catch (e) {
    // localStorage full — remove oldest sessions to make space
    const idx = getLocalSessions();
    if (idx.length > 5) {
      const removed = idx.pop();
      localStorage.removeItem(LOCAL_SESSION_PREFIX + removed.id);
      saveLocalSessionIndex(idx);
      try {
        localStorage.setItem(LOCAL_SESSION_PREFIX + sessionMeta.id,
          JSON.stringify({ session: sessionMeta, steps }));
      } catch {}
    }
  }
}

function getLocalSessionData(sid) {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_SESSION_PREFIX + sid));
  } catch { return null; }
}

function deleteLocalSession(sid) {
  const sessions = getLocalSessions().filter(s => s.id !== sid);
  saveLocalSessionIndex(sessions);
  localStorage.removeItem(LOCAL_SESSION_PREFIX + sid);
}

function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m > 60) return `${Math.floor(m / 60)}h${m % 60}m`;
  if (m > 0) return `${m}m${s}s`;
  return `${s}s`;
}

async function loadSessionHistory() {
  const list = document.getElementById('historyList');
  try {
    let sessions = [];
    // Always fetch from server DB
    try {
      const data = await fetchJSON('/api/sessions');
      const serverSessions = data.sessions || [];
      // Merge with localStorage sessions (online mode), dedup by id
      const byId = {};
      for (const s of serverSessions) byId[s.id] = s;
      if (MODE === 'prod') {
        for (const s of getLocalSessions()) {
          if (!byId[s.id]) byId[s.id] = s;
        }
      }
      sessions = Object.values(byId);
      sessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    } catch (e) {
      // Fallback to localStorage only
      sessions = MODE === 'prod' ? getLocalSessions() : [];
    }
    if (!sessions.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No sessions yet. Play a game!</div>';
      return;
    }
    list.innerHTML = '';
    sessions = sessions.filter(s => (s.steps || 0) >= 5);
    if (!sessions.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No sessions yet. Play a game!</div>';
      return;
    }
    for (const s of sessions) {
      const div = document.createElement('div');
      const isBranch = !!s.parent_session_id;
      div.className = 'history-item' + (isBranch ? ' branched' : '');
      const date = new Date((s.created_at || 0) * 1000).toLocaleString();
      const resultClass = `h-result-${s.result || 'NOT_FINISHED'}`;
      const branchLabel = isBranch
        ? `<span class="branch-indicator">&#8627; from step ${s.branch_at_step}</span>`
        : '';
      div.innerHTML = `
        ${branchLabel}
        <span class="h-game">${gameShortName(s.game_id)}</span>
        <span class="h-result ${resultClass}">${s.result || '?'}</span>
        <span class="h-meta">${s.steps || 0} steps | ${s.model || '?'} | $${(s.total_cost || 0).toFixed(4)}${s.duration ? ` | ${formatDuration(s.duration)}` : ''}</span>
        <span class="h-meta">${date}</span>
`;
      div.style.cursor = 'pointer';
      div.onclick = () => window.open(`/share/${s.id}`, '_blank');
      // Replay button (in-app)
      const replayBtn = document.createElement('button');
      replayBtn.className = 'btn';
      replayBtn.style.cssText = 'padding:2px 8px;font-size:10px;margin-left:6px;background:var(--surface2);border:1px solid var(--border);color:var(--text);';
      replayBtn.textContent = '\u25b6 Replay';
      replayBtn.onclick = (e) => { e.stopPropagation(); loadReplay(s.id); };
      div.appendChild(replayBtn);
      if (s.result === 'NOT_FINISHED') {
        const resumeBtn = document.createElement('button');
        resumeBtn.className = 'btn btn-primary';
        resumeBtn.style.cssText = 'padding:2px 8px;font-size:10px;margin-left:6px;';
        resumeBtn.textContent = '\u25b6 Resume';
        resumeBtn.onclick = (e) => { e.stopPropagation(); resumeSession(s.id); };
        div.appendChild(resumeBtn);
      }
      list.appendChild(div);
    }
  } catch (e) {
    list.innerHTML =
      `<div class="empty-state" style="height:auto;font-size:12px;">Error loading sessions: ${e.message}</div>`;
  }
}

async function loadReplay(sid) {
  try {
    let data;
    if (MODE === 'prod') {
      data = getLocalSessionData(sid);
      if (!data) {
        data = await fetchJSON(`/api/sessions/${sid}`);
        if (data.error) { alert('Session not found locally or on server.'); return; }
      }
    } else {
      data = await fetchJSON(`/api/sessions/${sid}`);
      if (data.error) { alert(data.error); return; }
    }
    replayData = data;

    // Show the replay bar in the canvas area
    const bar = document.getElementById('replayBar');
    bar.style.display = 'block';
    document.getElementById('controls').style.display = 'none';
    document.getElementById('transportBar').style.display = 'none';
    hideLiveScrubber();

    const scrubber = document.getElementById('replayScrubber');
    const totalSteps = data.steps?.length || 0;
    scrubber.max = Math.max(totalSteps - 1, 0);
    scrubber.value = 0;
    document.getElementById('replayInfo').textContent =
      `Replay: ${gameShortName(data.session.game_id)} — Step 0 / ${totalSteps}`;

    // Render full reasoning in the Reasoning tab (same format as live/resumed sessions)
    const sess = data.session || {};
    const resultLabel = sess.result || 'REPLAY';
    renderRestoredReasoning(data.steps || [],
      `Replay: ${gameShortName(sess.game_id) || '?'} — ${totalSteps} steps — ${resultLabel}`, 'var(--accent)', { replay: true });
    // Switch to Agent tab so user sees the reasoning
    switchTopTab('agent');
    switchSubTab('reasoning');

    // Hide the old History-tab reasoning panel (we use the main Reasoning tab now)
    document.getElementById('replayReasoningPanel').style.display = 'none';

    scrubber.oninput = () => showReplayStep(parseInt(scrubber.value));
    if (totalSteps > 0) showReplayStep(0);
  } catch (e) { alert('Error loading replay: ' + e.message); }
}

function showReplayStep(stepIdx) {
  if (!replayData || !replayData.steps) return;
  const total = replayData.steps.length;
  const info = document.getElementById('replayInfo');
  info.textContent = `Replay: ${gameShortName(replayData.session.game_id)} — Step ${stepIdx + 1} / ${total}`;

  document.getElementById('replayScrubber').value = stepIdx;

  if (stepIdx >= 0 && stepIdx < total) {
    const step = replayData.steps[stepIdx];
    if (step.grid) {
      renderGrid(step.grid);
      document.getElementById('emptyState').style.display = 'none';
      canvas.style.display = 'block';
    }

    // Highlight the matching reasoning entry and plan step in Reasoning tab
    const content = document.getElementById('reasoningContent');
    // Reset all highlights
    content.querySelectorAll('.reasoning-entry').forEach(e => {
      e.style.outline = '';
      e.style.outlineOffset = '';
    });
    content.querySelectorAll('.plan-step .action-btn').forEach(btn => {
      btn.style.background = '';
      btn.style.color = '';
      btn.style.borderColor = '';
    });
    // Find and highlight the active entry + plan step
    const entries = content.querySelectorAll('.reasoning-entry[data-step-nums]');
    entries.forEach(e => {
      const stepNums = (e.dataset.stepNums || '').split(',').map(Number);
      const idx = stepNums.indexOf(step.step_num);
      if (idx !== -1) {
        e.style.outline = '2px solid var(--accent)';
        e.style.outlineOffset = '-2px';
        e.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        // Light up this and all previous plan steps (progressive fill)
        const planBtns = e.querySelectorAll('.plan-step .action-btn');
        for (let pi = 0; pi <= idx && pi < planBtns.length; pi++) {
          planBtns[pi].style.background = 'var(--green)';
          planBtns[pi].style.color = '#000';
          planBtns[pi].style.borderColor = 'var(--green)';
        }
      }
    });
  }
}

function replayPrev() {
  if (!replayData) return;
  const scrubber = document.getElementById('replayScrubber');
  const v = Math.max(0, parseInt(scrubber.value) - 1);
  showReplayStep(v);
}

function replayNext() {
  if (!replayData) return;
  const scrubber = document.getElementById('replayScrubber');
  const v = Math.min(replayData.steps.length - 1, parseInt(scrubber.value) + 1);
  showReplayStep(v);
}

function closeReplay() {
  replayData = null;
  document.getElementById('replayBar').style.display = 'none';
  document.getElementById('replayReasoningPanel').style.display = 'none';
  // Restore game controls if a session is active
  if (sessionId) {
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    if (currentGrid) renderGrid(currentGrid);
    initLiveScrubber();
    liveScrubUpdate();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// LIVE SCRUBBER
// ═══════════════════════════════════════════════════════════════════════════

function initLiveScrubber() {
  const bar = document.getElementById('liveScrubberBar');
  if (!bar) return;
  // Live scrubber is only used for internal state tracking, not shown in settings view
  bar.style.display = 'none';
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  _liveScrubLiveGrid = null;
  const slider = document.getElementById('liveScrubSlider');
  slider.value = 0; slider.max = 0;
  document.getElementById('liveScrubLabel').textContent = 'Step 0 / 0';
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-live';
  dot.innerHTML = '&#9679; LIVE';
  document.getElementById('liveScrubBanner').style.display = 'none';

  // Bind slider events
  slider.oninput = function() {
    const idx = parseInt(this.value);
    if (idx >= moveHistory.length) {
      liveScrubReturnToLive();
    } else {
      liveScrubShow(idx);
    }
  };
}

function liveScrubUpdate() {
  const bar = document.getElementById('liveScrubberBar');
  if (!bar || bar.style.display === 'none') return;
  const slider = document.getElementById('liveScrubSlider');
  const total = moveHistory.length;
  slider.max = Math.max(0, total - 1);
  if (_liveScrubMode) {
    slider.value = Math.max(0, total - 1);
    document.getElementById('liveScrubLabel').textContent = `Step ${total} / ${total}`;
  } else {
    const viewStep = _liveScrubViewIdx + 1;
    document.getElementById('liveScrubLabel').textContent = `Step ${viewStep} / ${total}`;
  }
}

function liveScrubShow(idx) {
  if (idx < 0 || idx >= moveHistory.length) return;
  _liveScrubViewIdx = idx;
  // Stash the live grid on first historical view
  if (_liveScrubMode) {
    _liveScrubLiveGrid = currentGrid;
  }
  _liveScrubMode = false;
  const entry = moveHistory[idx];
  if (entry && entry.grid) {
    _renderGridPreview(entry.grid);
  }
  // Update slider position
  const slider = document.getElementById('liveScrubSlider');
  slider.value = idx;
  // Update label
  document.getElementById('liveScrubLabel').textContent = `Step ${idx + 1} / ${moveHistory.length}`;
  // Show banner
  const banner = document.getElementById('liveScrubBanner');
  banner.style.display = 'flex';
  document.getElementById('liveScrubBannerText').textContent = `Viewing step ${idx + 1}`;
  // Update dot
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-historical';
  dot.innerHTML = '&#9679; PAUSED';
}

function liveScrubReturnToLive() {
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  // Restore the live grid
  if (_liveScrubLiveGrid) {
    renderGrid(_liveScrubLiveGrid);
    _liveScrubLiveGrid = null;
  } else if (currentGrid) {
    renderGrid(currentGrid);
  }
  // Hide banner
  document.getElementById('liveScrubBanner').style.display = 'none';
  // Update dot
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-live';
  dot.innerHTML = '&#9679; LIVE';
  // Snap slider to end
  liveScrubUpdate();
}

function liveScrubToStep(stepNum) {
  // Map step number to moveHistory index
  const idx = moveHistory.findIndex(m => m.step === stepNum);
  if (idx >= 0) {
    liveScrubShow(idx);
  }
}

function hideLiveScrubber() {
  const bar = document.getElementById('liveScrubberBar');
  if (bar) bar.style.display = 'none';
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  _liveScrubLiveGrid = null;
}

function _renderGridPreview(grid) {
  if (!grid || !grid.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  canvas.width = w * scale;
  canvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
  // Note: does NOT set currentGrid — that stays at the live value
}

// ═══════════════════════════════════════════════════════════════════════════
// TURNSTILE VERIFICATION
// ═══════════════════════════════════════════════════════════════════════════

let turnstileVerified = !document.getElementById('turnstileGate');

async function onTurnstileSuccess(token) {
  try {
    const resp = await fetch('/api/turnstile/verify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token}),
    });
    const data = await resp.json();
    if (data.status === 'ok') {
      turnstileVerified = true;
      document.getElementById('turnstileGate').style.display = 'none';
      initApp();
    } else {
      document.getElementById('turnstileError').style.display = 'block';
      if (typeof turnstile !== 'undefined') turnstile.reset();
    }
  } catch {
    document.getElementById('turnstileError').style.display = 'block';
    if (typeof turnstile !== 'undefined') turnstile.reset();
  }
}

// Wrap fetchJSON to handle turnstile expiry (403 with need_turnstile)
const _origFetchJSON = fetchJSON;
fetchJSON = async function(url, body) {
  const r = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 403) {
    const data = await r.json();
    if (data.need_turnstile) {
      // Re-show the gate
      turnstileVerified = false;
      const gate = document.getElementById('turnstileGate');
      if (gate) {
        gate.style.display = 'flex';
        if (typeof turnstile !== 'undefined') turnstile.reset();
      }
      throw new Error('Human verification required');
    }
    return data;
  }
  return r.json();
};

// ═══════════════════════════════════════════════════════════════════════════
// PUTER.KV PERSISTENCE + AUTO-UPLOAD (online mode only)
// ═══════════════════════════════════════════════════════════════════════════

let sessionStepsBuffer = []; // accumulates steps during play for puter.kv
let sessionStartTime = null;
let syncStepCounter = 0; // counts steps since last periodic sync

function puterKvKey(sid) { return `arc_session:${sid}`; }

function _collectPrompts() {
  return {
    system_prompt: getPrompt('shared.arc_description'),
    hard_memory: getPrompt('shared.agent_priors'),
    compact_prompt: getPrompt('linear.compact_prompt'),
    interrupt_prompt: getPrompt('linear.interrupt_prompt'),
  };
}

function buildSessionPayload(ss) {
  const _s = ss || null;
  const _sid = _s ? _s.sessionId : sessionId;
  const _cs = _s ? _s.currentState : currentState;
  const _sc = _s ? _s.stepCount : stepCount;
  const _buf = _s ? _s.sessionStepsBuffer : sessionStepsBuffer;
  const _st = _s ? _s.sessionStartTime : sessionStartTime;
  if (!_sid || !_cs.game_id) return null;
  const _tlEvents = _s ? _s.timelineEvents : (getActiveSession()?.timelineEvents || []);
  return {
    session: {
      id: _sid,
      game_id: _cs.game_id,
      model: (_s ? _s.model : null) || getSelectedModel() || '',
      mode: MODE,
      created_at: _st || (Date.now() / 1000),
      result: _cs.state || 'NOT_FINISHED',
      steps: _sc,
      levels: _cs.levels_completed || 0,
      prompts: _collectPrompts(),
      timeline: _tlEvents,
      user_id: currentUser?.id || null,
    },
    steps: _buf,
  };
}

function recordStepForPersistence(actionId, actionData, grid, changeMap, llmResponse, ss, extras) {
  const _ss = ss || { stepCount, sessionStepsBuffer, syncStepCounter, sessionId: sessionId };
  const stepEntry = {
    step_num: _ss.stepCount,
    action: actionId,
    data: actionData || {},
    grid: grid,
    change_map: changeMap || null,
    llm_response: llmResponse || null,
    timestamp: Date.now() / 1000,
    levels_completed: extras?.levels_completed ?? 0,
    result_state: extras?.result_state || 'NOT_FINISHED',
  };
  _ss.sessionStepsBuffer.push(stepEntry);
  _ss.syncStepCounter++;
  if (!ss) { syncStepCounter = _ss.syncStepCounter; }
  updateShareBtnVisibility();
  updateUploadBadge();

  // Save to localStorage periodically (online mode or Pyodide — per-user local history)
  if ((MODE === 'prod' || _pyodideGameActive) && (_ss.syncStepCounter % 5 === 0 || _ss.stepCount <= 1)) {
    const payload = buildSessionPayload(ss);
    if (payload) saveLocalSession(payload.session, payload.steps);
  }

  // Fire-and-forget puter.kv write (online mode only)
  if (MODE === 'prod' && FEATURES.puter_js && typeof puter !== 'undefined' && puter.kv) {
    const payload = buildSessionPayload(ss);
    if (payload) {
      puter.kv.set(puterKvKey(_ss.sessionId), JSON.stringify(payload)).catch(() => {});
    }
  }

  // Periodic sync every 30 steps
  if (_ss.syncStepCounter >= 30) {
    _ss.syncStepCounter = 0;
    if (!ss) syncStepCounter = 0;
    autoUploadSession(ss || getActiveSession());
  }
}

const MIN_STEPS_FOR_UPLOAD = 5;

async function autoUploadSession(ss) {
  const payload = buildSessionPayload(ss || getActiveSession());
  if (!payload) return;
  // Always save to localStorage as backup (even below server threshold)
  if (payload.session && payload.steps?.length > 0) {
    saveLocalSession(payload.session, payload.steps);
  }
  if ((payload.steps || []).length < MIN_STEPS_FOR_UPLOAD) return;
  try {
    const resp = await fetch('/api/sessions/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (resp.ok) {
      const uploadedStep = payload.session.steps || payload.steps.length;
      const _ss = ss || getActiveSession();
      if (_ss) _ss._lastUploadedStep = uploadedStep;
      updateUploadBadge();
    }
  } catch {} // fire-and-forget
}

function uploadClosedSession(s) {
  // Build payload from SessionState object (not globals)
  if (!s.sessionId || s.sessionId.startsWith('pending_')) return;
  const steps = s.sessionStepsBuffer || [];
  if (steps.length < MIN_STEPS_FOR_UPLOAD) return;
  const gameId = s.currentState?.game_id || s.gameId || '';
  if (!gameId) return;
  const payload = {
    session: {
      id: s.sessionId,
      game_id: gameId,
      model: s.model || '',
      mode: MODE,
      created_at: s.sessionStartTime || s.createdAt || (Date.now() / 1000),
      result: s.currentState?.state || s.status || 'NOT_FINISHED',
      steps: s.stepCount || steps.length,
      levels: s.currentState?.levels_completed || 0,
      prompts: _collectPrompts(),
      timeline: s.timelineEvents || [],
    },
    steps: steps,
  };
  // Upload to local server
  fetch('/api/sessions/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(resp => {
    if (resp.ok) {
      s._lastUploadedStep = s.stepCount || steps.length;
      updateUploadBadge();
    }
  }).catch(() => {});
  // Also upload to Railway if running locally
  if (MODE === 'staging') {
    fetch('https://arc3.sonpham.net/api/sessions/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(() => {});
  }
}

function checkSessionEndAndUpload() {
  if (!sessionId) return;
  const st = currentState.state;
  // Update multi-session state
  const ms = getActiveSession();
  if (ms) { ms.status = st; ms.stepCount = stepCount; }
  saveSessionIndex();
  renderSessionTabs();
  if (st === 'WIN' || st === 'GAME_OVER') {
    // Final save to localStorage (online mode or Pyodide)
    if (MODE === 'prod' || _pyodideGameActive) {
      const payload = buildSessionPayload();
      if (payload) saveLocalSession(payload.session, payload.steps);
    }
    // Auto-upload completed session to server
    autoUploadSession().then(() => {
      // Clean up puter.kv entry on success (online mode only)
      if (MODE === 'prod' && FEATURES.puter_js && typeof puter !== 'undefined' && puter.kv) {
        puter.kv.del(puterKvKey(sessionId)).catch(() => {});
      }
    });
    // Upload to Railway for sharing (local mode only — online already uploads to itself)
    if (MODE === 'staging') {
      const payload = buildSessionPayload();
      if (payload && (payload.steps || []).length >= MIN_STEPS_FOR_UPLOAD) {
        fetch('https://arc3.sonpham.net/api/sessions/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }).then(r => r.json()).then(data => {
          if (data.status === 'ok') showShareLink(sessionId);
        }).catch(() => {});
      }
    } else {
      // Online mode — session is already on this server
      if (sessionStepsBuffer.length >= MIN_STEPS_FOR_UPLOAD) showShareLink(sessionId);
    }
  }
}

function showShareLink(sid) {
  const base = (MODE === 'staging') ? 'https://arc3.sonpham.net' : '';
  const url = `${base}/share/${sid}`;
  // Remove existing share banner if any
  const old = document.getElementById('shareBanner');
  if (old) old.remove();
  const banner = document.createElement('div');
  banner.id = 'shareBanner';
  banner.style.cssText = 'background:#1a3a1a;border:1px solid var(--green,#4FCC30);padding:8px 14px;margin:8px 0;border-radius:6px;font-size:13px;display:flex;align-items:center;gap:8px;';
  banner.innerHTML = `<span style="color:var(--green,#4FCC30);">&#9734; Share replay:</span>
    <a href="${url}" target="_blank" style="color:var(--blue,#1E93FF);word-break:break-all;">${url}</a>
    <button onclick="navigator.clipboard.writeText('${url}');this.textContent='Copied!'" style="background:var(--green,#4FCC30);color:#000;border:none;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;">Copy</button>`;
  // Insert after the canvas container
  const container = document.getElementById('gameCanvas').parentElement;
  container.parentElement.insertBefore(banner, container.nextSibling);
}

function updateShareBtnVisibility() {
  const btn = document.getElementById('shareBtn');
  if (!btn) return;
  btn.style.display = (sessionId && stepCount >= MIN_STEPS_FOR_UPLOAD) ? '' : 'none';
}

function updateUploadBadge() {
  const badge = document.getElementById('uploadBadge');
  if (!badge) return;
  const ss = getActiveSession();
  const sc = ss?.stepCount || stepCount || 0;
  if (!sessionId || sc === 0) { badge.style.display = 'none'; return; }
  badge.style.display = '';
  const uploaded = ss?._lastUploadedStep || 0;
  if (uploaded <= 0) {
    badge.className = 'upload-badge is-local';
    badge.textContent = 'Local';
    badge.title = 'Session saved locally only';
  } else if (uploaded >= sc) {
    badge.className = 'upload-badge is-synced';
    badge.textContent = '↑ Synced';
    badge.title = `All ${sc} steps uploaded to server`;
  } else {
    badge.className = 'upload-badge is-partial';
    badge.textContent = `↑ ${uploaded}`;
    badge.title = `Uploaded up to step ${uploaded} of ${sc}`;
  }
}

async function shareCurrentSession() {
  const btn = document.getElementById('shareBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Sharing...'; }
  try {
    const payload = buildSessionPayload();
    if (!payload || (payload.steps || []).length < MIN_STEPS_FOR_UPLOAD) {
      if (btn) { btn.disabled = false; btn.textContent = 'Share'; }
      return;
    }
    // Upload to local server
    await fetch('/api/sessions/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    // Also upload to Railway if running locally
    if (MODE === 'staging') {
      const resp = await fetch('https://arc3.sonpham.net/api/sessions/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (data.status === 'ok') showShareLink(sessionId);
    } else {
      showShareLink(sessionId);
    }
  } catch (e) {
    console.error('Share failed:', e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Share'; }
  }
}

async function puterKvCheckResume() {
  if (MODE !== 'online' || !FEATURES.puter_js || typeof puter === 'undefined' || !puter.kv) return;
  try {
    // Scan for in-progress sessions
    const keys = await puter.kv.list();
    const arcKeys = (keys || []).filter(k => k.startsWith('arc_session:'));
    if (!arcKeys.length) return;

    // Check the most recent one
    const raw = await puter.kv.get(arcKeys[arcKeys.length - 1]);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (!data.session || data.session.result !== 'NOT_FINISHED') {
      // Already finished, clean it up
      await puter.kv.del(arcKeys[arcKeys.length - 1]).catch(() => {});
      return;
    }

    // Show resume banner
    const banner = document.createElement('div');
    banner.className = 'resume-banner';
    banner.id = 'resumeBanner';
    banner.innerHTML = `
      <span>Resume session <strong>${gameShortName(data.session.game_id)}</strong> (${data.steps?.length || 0} steps)?</span>
      <button class="btn btn-primary" onclick="resumeFromPuterKv('${arcKeys[arcKeys.length - 1]}')">Resume</button>
      <button class="btn" onclick="dismissResumeBanner('${arcKeys[arcKeys.length - 1]}')">Dismiss</button>`;
    document.body.appendChild(banner);
  } catch (e) {
    console.warn('puter.kv resume check failed:', e);
  }
}

async function resumeFromPuterKv(kvKey) {
  document.getElementById('resumeBanner')?.remove();
  try {
    const raw = await puter.kv.get(kvKey);
    if (!raw) return;
    const data = JSON.parse(raw);
    // Upload to server and get a live session back
    await fetch('/api/sessions/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    // Start the game fresh and replay via the server recovery mechanism
    const gameId = data.session.game_id;
    sessionId = data.session.id;
    sessionStepsBuffer = data.steps || [];
    stepCount = sessionStepsBuffer.length;
    sessionStartTime = data.session.created_at;
    syncStepCounter = 0;

    // Fetch last state by triggering recovery
    const lastStep = sessionStepsBuffer[sessionStepsBuffer.length - 1];
    if (lastStep && lastStep.grid) {
      currentState = {
        grid: lastStep.grid,
        state: data.session.result || 'NOT_FINISHED',
        game_id: gameId,
        levels_completed: data.session.levels || 0,
        win_levels: currentState.win_levels || 0,
        available_actions: currentState.available_actions || [0,1,2,3,4,5,6,7],
      };
      renderGrid(lastStep.grid);
      document.getElementById('emptyState').style.display = 'none';
      canvas.style.display = 'block';
      document.getElementById('controls').style.display = 'flex';
      document.getElementById('transportBar').style.display = 'block';
      updateUI(currentState);
    }
  } catch (e) {
    console.warn('Resume failed:', e);
  }
}

function dismissResumeBanner(kvKey) {
  document.getElementById('resumeBanner')?.remove();
  if (MODE === 'prod' && FEATURES.puter_js && typeof puter !== 'undefined' && puter.kv) {
    puter.kv.del(kvKey).catch(() => {});
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// RESTORED REASONING PANEL (shared by resume + branch)
// ═══════════════════════════════════════════════════════════════════════════

function renderRestoredReasoning(steps, bannerText, bannerColor, opts = {}) {
  const isReplay = opts.replay || false;
  const content = document.getElementById('reasoningContent');
  content.innerHTML = '';

  // Banner (only for resume/branch, not tab-switch reconstruction)
  if (bannerText) {
    const bannerEntry = document.createElement('div');
    bannerEntry.className = 'reasoning-entry';
    bannerEntry.innerHTML = `<div class="step-label" style="color:${bannerColor};">${bannerText}</div>`;
    content.appendChild(bannerEntry);
  }

  // Group steps into LLM calls (plan groups) and human actions
  const groups = [];
  let currentGroup = null;
  let planCapacity = 0;
  for (const s of steps) {
    const hasLLM = s.llm_response && typeof s.llm_response === 'object' && s.llm_response.parsed;
    if (hasLLM) {
      const plan = s.llm_response.parsed.plan;
      const planSize = (plan && Array.isArray(plan)) ? plan.length : 1;
      currentGroup = { type: 'llm', steps: [s], llm: s.llm_response };
      planCapacity = planSize - 1;
      groups.push(currentGroup);
    } else if (currentGroup && currentGroup.type === 'llm' && planCapacity > 0) {
      currentGroup.steps.push(s);
      planCapacity--;
    } else {
      groups.push({ type: 'human', steps: [s], llm: null });
      currentGroup = null;
      planCapacity = 0;
    }
  }

  // Compute per-group level info
  let prevGroupLevel = 0;
  for (const g of groups) {
    const lastS = g.steps[g.steps.length - 1];
    g.levelsAfter = lastS.levels_completed || 0;
    g.levelsBefore = prevGroupLevel;
    prevGroupLevel = g.levelsAfter;
  }

  // Render groups chronologically (oldest first)
  for (let gi = 0; gi < groups.length; gi++) {
    const g = groups[gi];

    // Level-up marker before this group if previous group caused a level change
    if (gi > 0 && groups[gi - 1].levelsAfter > groups[gi - 1].levelsBefore) {
      const pg = groups[gi - 1];
      const lvlEntry = document.createElement('div');
      lvlEntry.className = 'reasoning-entry';
      lvlEntry.style.opacity = '0.7';
      lvlEntry.innerHTML = `<div class="step-label" style="color:var(--green);">\u2b50 Level ${pg.levelsBefore} completed! (${pg.levelsBefore} \u2192 ${pg.levelsAfter})</div>`;
      content.appendChild(lvlEntry);
    }

    const html = buildReasoningGroupHTML(g, gi, {
      showBranchBtn: true,
      isRestored: true,
      isParent: false,
      levelBefore: g.levelsBefore,
      levelAfter: g.levelsAfter,
      defaultModel: '?',
      isReplay: isReplay,
    });
    if (!html) continue;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    const entry = wrapper.firstElementChild;
    if (!entry) continue;
    content.appendChild(entry);
    annotateCoordRefs(entry);
  }

  // Final level-up marker if last group caused a level change
  if (groups.length > 0) {
    const last = groups[groups.length - 1];
    if (last.levelsAfter > last.levelsBefore) {
      const lvlEntry = document.createElement('div');
      lvlEntry.className = 'reasoning-entry';
      lvlEntry.style.opacity = '0.7';
      lvlEntry.innerHTML = `<div class="step-label" style="color:var(--green);">\u2b50 Level ${last.levelsBefore} completed! (${last.levelsBefore} \u2192 ${last.levelsAfter})</div>`;
      content.appendChild(lvlEntry);
    }
  }

  scrollReasoningToBottom();
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION RESUME (resume NOT_FINISHED sessions from history)
// ═══════════════════════════════════════════════════════════════════════════

async function resumeSession(sid) {
  // Guard: don't overwrite an active session that already has a loaded grid
  if (sessionId === sid && currentGrid && stepCount > 0) return;

  // Track whether session was already registered — used to detect close-during-resume
  const _wasRegistered = sessions.has(sid);

  try {
    let data = await fetchJSON('/api/sessions/resume', { session_id: sid });
    if (data.error) {
      // Server doesn't have this session — try localStorage fallback
      const localData = getLocalSessionData(sid);
      if (localData && localData.steps && localData.steps.length > 0) {
        console.log(`[resumeSession] Server 404, restoring ${sid} from localStorage (${localData.steps.length} steps)`);
        // Re-upload to server so future resumes work
        const reimportPayload = { session: localData.session, steps: localData.steps };
        fetch('/api/sessions/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reimportPayload),
        }).catch(() => {});
        // Retry resume after re-import
        await new Promise(r => setTimeout(r, 500));
        data = await fetchJSON('/api/sessions/resume', { session_id: sid });
        if (data.error) {
          // Still failed — start fresh with the game from localStorage
          console.warn(`[resumeSession] Re-import failed for ${sid}, starting fresh`);
          const gameId = localData.session?.game_id;
          if (gameId) {
            // Remove the dead session and let the user start fresh
            sessions.delete(sid);
            saveSessionIndex();
            renderSessionTabs();
          }
          return;
        }
      } else {
        // No local data either — session is truly gone
        console.warn(`[resumeSession] Session ${sid} not found in server or localStorage`);
        sessions.delete(sid);
        saveSessionIndex();
        renderSessionTabs();
        updateEmptyAppState();
        return;
      }
    }

    // Guard: if session was registered before the await but got closed while server was replaying, abort
    if (_wasRegistered && !sessions.has(sid)) {
      console.log('[resumeSession] Session was closed during server replay, aborting.');
      return;
    }

    // Set up client state for live play
    sessionId = sid;
    stepCount = data.resumed_step_count || 0;
    autoPlaying = false;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    undoStack = [];
    syncStepCounter = 0;

    // Rebuild moveHistory, sessionStepsBuffer, llmObservations, and token totals from step history
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      // Rebuild turnIds: LLM leader starts new turn, followers inherit, human gets own turn
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++; // human action
      }
      const _turnId = turnCounter;
      // Rebuild moveHistory (with per-step game stats from server replay)
      moveHistory.push({
        step: s.step_num,
        action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null,
        change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      // Rebuild sessionStepsBuffer
      sessionStepsBuffer.push({
        step_num: s.step_num,
        action: s.action,
        data: s.data || {},
        grid: s.grid || null,
        change_map: s.change_map || null,
        llm_response: s.llm_response || null,
        timestamp: s.timestamp || 0,
      });
      // Rebuild llmObservations from LLM responses
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num,
          observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '',
          action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      // Rebuild sessionTotalTokens from LLM usage
      if (llm && llm.usage) {
        const inputTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outputTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inputTok;
        sessionTotalTokens.output += outputTok;
        const model = llm.model || data.model || '';
        const prices = TOKEN_PRICES[model] || null;
        if (prices) {
          sessionTotalTokens.cost += (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
        }
      }
    }

    // If no token data from llm_response (e.g. Agent Spawn), rebuild from timeline events
    if (sessionTotalTokens.input === 0 && sessionTotalTokens.output === 0 && data.timeline) {
      for (const ev of data.timeline) {
        if (ev.input_tokens) sessionTotalTokens.input += ev.input_tokens;
        if (ev.output_tokens) sessionTotalTokens.output += ev.output_tokens;
        if (ev.cost) sessionTotalTokens.cost += ev.cost;
      }
      // Count LLM calls from timeline: each sub_act and orch_think/delegate is a call
      if (llmCallCount === 0) {
        for (const ev of data.timeline) {
          if (['as_sub_act', 'as_sub_tool', 'as_sub_report', 'as_orch_think', 'as_orch_delegate'].includes(ev.type)) {
            llmCallCount++;
          }
        }
      }
    }
    sessionStartTime = Date.now() / 1000;

    // Close replay if open
    closeReplay();

    updateUI(data);
    updateUndoBtn();

    // Show controls
    document.getElementById('emptyState').style.display = 'none';
    canvas.style.display = 'block';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    initLiveScrubber();
    liveScrubUpdate();

    // Highlight the matching game card in the sidebar
    if (data.game_id) {
      document.querySelectorAll('.game-card').forEach(c => {
        c.classList.toggle('active', c.dataset.gameId === data.game_id);
      });
    }

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    // Switch to Agent tab
    switchTopTab('agent');

    // Log the resume event
    logSessionEvent('resumed', stepCount, {});

    // ── Restore settings from session history ──
    // Find model + scaffolding from LLM responses or timeline events
    let _resumeModel = data.model || '';
    let _resumeScaffolding = 'linear';
    for (let i = steps.length - 1; i >= 0; i--) {
      const llm = steps[i].llm_response;
      if (llm) {
        if (llm.model) _resumeModel = llm.model;
        if (llm.scaffolding) _resumeScaffolding = llm.scaffolding;
        break;
      }
    }
    // Fallback: detect scaffolding from timeline event types
    if (_resumeScaffolding === 'linear' && data.timeline) {
      const tlTypes = new Set(data.timeline.map(e => e.type));
      if (tlTypes.has('as_orch_start')) _resumeScaffolding = 'agent_spawn';
      else if (tlTypes.has('planner_call') || tlTypes.has('monitor_call')) _resumeScaffolding = 'three_system';
      else if (tlTypes.has('rlm_iter')) _resumeScaffolding = 'rlm';
    }
    // Switch scaffolding UI to match session's scaffolding
    if (SCAFFOLDING_SCHEMAS[_resumeScaffolding] && _resumeScaffolding !== activeScaffoldingType) {
      switchScaffolding(_resumeScaffolding);
    }
    // Set model select to match session's model (after scaffolding switch ensures correct selects exist)
    if (_resumeModel) {
      await loadModels();
      const _modelSelId = _resumeScaffolding === 'rlm' ? 'sf_rlm_modelSelect'
        : _resumeScaffolding === 'three_system' ? 'sf_ts_plannerModelSelect'
        : _resumeScaffolding === 'two_system' ? 'sf_2s_plannerModelSelect'
        : _resumeScaffolding === 'agent_spawn' ? 'sf_as_orchestratorModelSelect'
        : 'modelSelect';
      const _msel = document.getElementById(_modelSelId);
      if (_msel && [..._msel.options].some(o => o.value === _resumeModel)) {
        _msel.value = _resumeModel;
      }
    }

    // ── Multi-session: register resumed session ──
    if (!sessions.has(sid)) {
      const s = new SessionState(sid);
      registerSession(sid, s);
    }
    activeSessionId = sid;

    // Rebuild timelineEvents from step history (or use saved timeline)
    const _tlSs = sessions.get(sid);
    if (_tlSs) {
      _tlSs.timelineEvents = data.timeline || _rebuildTimelineFromSteps(steps);
      // Rebuild obs events from timeline for observatory display
      _tlSs._obsEvents = [];
      const _tl = _tlSs.timelineEvents;
      const _tlStart = _tl.length ? (_tl[0].timestamp || 0) : 0;
      for (const ev of _tl) {
        const agentType = ev.agent_type || ev.current_agent || 'orchestrator';
        const obsEvent = ev.type?.startsWith('as_') ? ev.type.replace('as_', '') : (ev.type || '');
        const obsData = { event: obsEvent, agent: agentType.toLowerCase() };
        if (ev.timestamp) {
          const d = new Date(ev.timestamp);
          obsData.t = d.toISOString();
          obsData.elapsed_s = (ev.timestamp - _tlStart) / 1000;
        }
        if (ev.model) obsData.model = ev.model;
        if (ev.duration_ms) obsData.duration_ms = ev.duration_ms;
        if (ev.input_tokens) obsData.input_tokens = ev.input_tokens;
        if (ev.output_tokens) obsData.output_tokens = ev.output_tokens;
        if (ev.cost) obsData.cost = ev.cost;
        if (ev.task || ev.summary) obsData.summary = ev.task || ev.summary;
        if (ev.reasoning) obsData.reasoning = ev.reasoning;
        if (ev.response) obsData.response = ev.response;
        if (ev.findings != null) obsData.findings = ev.findings;
        if (ev.hypotheses != null) obsData.hypotheses = ev.hypotheses;
        if (ev.action_name) obsData.action_name = ev.action_name;
        if (ev.tool_name) obsData.tool_name = ev.tool_name;
        if (ev.step_num != null) obsData.step_num = ev.step_num;
        _tlSs._obsEvents.push(obsData);
      }
      // Enrich moveHistory from timeline events (for legacy sessions where llm_response was NULL)
      if (moveHistory.length && _tl.length) {
        const tlByStep = {};
        for (const ev of _tl) {
          if (ev.step_num != null && (ev.reasoning || ev.action_name || ev.agent_type)) {
            tlByStep[ev.step_num] = ev;
          }
        }
        for (const h of moveHistory) {
          if (!h.observation && !h.reasoning && tlByStep[h.step]) {
            const ev = tlByStep[h.step];
            h.observation = ev.action_name ? `[${ev.agent_type || 'agent'}] ${ev.action_name}` : '';
            h.reasoning = ev.reasoning || '';
          }
        }
        // Also backfill sessionStepsBuffer so renderRestoredReasoning sees LLM groups (not "Human")
        for (const sb of sessionStepsBuffer) {
          if (!sb.llm_response && tlByStep[sb.step_num]) {
            const ev = tlByStep[sb.step_num];
            sb.llm_response = {
              parsed: {
                observation: ev.action_name ? `[${ev.agent_type || 'agent'}] ${ev.action_name}` : '',
                reasoning: ev.reasoning || '',
                action: sb.action,
                data: sb.data || {},
              },
              model: ev.model || _resumeModel || '',
              scaffolding: 'agent_spawn',
              usage: (ev.input_tokens || ev.output_tokens) ? { input_tokens: ev.input_tokens || 0, output_tokens: ev.output_tokens || 0 } : null,
              call_duration_ms: ev.duration_ms || null,
            };
          }
        }
      }
      // Store original settings for branch-on-change detection
      _tlSs._originalSettings = { model: _resumeModel, scaffolding_type: _resumeScaffolding };
      // Compute elapsed time from timeline timestamps (don't tick from now)
      if (_tl.length >= 2) {
        const t0 = _tl[0].timestamp || 0;
        const tN = _tl[_tl.length - 1].timestamp || 0;
        _tlSs._obsElapsedFixed = (tN - t0) / 1000;
      } else {
        _tlSs._obsElapsedFixed = 0;
      }
      // Session was loaded from server, so all steps are already uploaded
      _tlSs._lastUploadedStep = stepCount;
    }

    // Rebuild reasoning panel (after timeline enrichment so Agent Spawn steps show as LLM groups)
    renderRestoredReasoning(sessionStepsBuffer, `Session resumed at step ${stepCount} (${llmCallCount} prior LLM calls, ${sessionTotalTokens.input + sessionTotalTokens.output} tokens restored)`, 'var(--green)');

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();

    // Persist enriched steps back to DB so future resumes don't need re-enrichment
    if (sessionStepsBuffer.some(s => s.llm_response && !steps.find(orig => orig.step_num === s.step_num && orig.llm_response))) {
      autoUploadSession();
    }

    // Enter observability view so user sees the grid + scrubber
    enterObsMode(_tlSs || getActiveSession());
  } catch (e) {
    alert('Resume failed: ' + e.message);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION BRANCHING (client-side)
// ═══════════════════════════════════════════════════════════════════════════

async function branchFromStep(stepNum) {
  // Branch the current live session at a given step number
  if (!sessionId) return;
  if (!confirm(`Branch from step ${stepNum}? This creates a new session from that point.`)) return;
  try {
    const data = await fetchJSON('/api/sessions/branch', {
      parent_session_id: sessionId,
      step_num: stepNum,
    });
    if (data.error) { alert(data.error); return; }

    const parentId = sessionId;
    sessionId = data.session_id;
    stepCount = stepNum;
    undoStack = [];
    syncStepCounter = 0;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    autoPlaying = false;

    // Rebuild state from returned steps (same as resume)
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++;
      }
      const _turnId = turnCounter;
      moveHistory.push({
        step: s.step_num,
        action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null,
        change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      sessionStepsBuffer.push({
        step_num: s.step_num,
        action: s.action,
        data: s.data || {},
        grid: s.grid || null,
        change_map: s.change_map || null,
        llm_response: s.llm_response || null,
        timestamp: s.timestamp || 0,
      });
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num,
          observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '',
          action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      if (llm && llm.usage) {
        const inputTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outputTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inputTok;
        sessionTotalTokens.output += outputTok;
        const model = llm.model || '';
        const prices = TOKEN_PRICES[model] || null;
        if (prices) {
          sessionTotalTokens.cost += (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
        }
      }
    }
    sessionStartTime = Date.now() / 1000;

    updateUI(data);
    updateUndoBtn();

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    logSessionEvent('branch_created', stepNum, { parent_session_id: parentId });
    switchTopTab('agent');

    // Render reasoning trace from parent steps
    renderRestoredReasoning(steps,
      `Branched from step ${stepNum} (${llmCallCount} prior LLM calls, $${sessionTotalTokens.cost.toFixed(3)} cost)`,
      'var(--purple)');

    // ── Multi-session: register branch session ──
    const bs = new SessionState(data.session_id);
    bs.gameId = data.game_id || currentState.game_id || '';
    bs.status = data.state || 'NOT_FINISHED';
    registerSession(data.session_id, bs);

    // Rebuild timelineEvents from step history
    bs.timelineEvents = _rebuildTimelineFromSteps(steps);

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();
  } catch (e) {
    alert('Branch failed: ' + e.message);
  }
}

async function branchHere() {
  if (!replayData || !replayData.session) return;
  const scrubber = document.getElementById('replayScrubber');
  const stepNum = parseInt(scrubber.value);
  const parentId = replayData.session.id;

  try {
    const data = await fetchJSON('/api/sessions/branch', {
      parent_session_id: parentId,
      step_num: stepNum,
    });
    if (data.error) { alert(data.error); return; }

    // Transition from replay to live play
    sessionId = data.session_id;
    stepCount = stepNum;
    undoStack = [];
    syncStepCounter = 0;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    autoPlaying = false;
    replayData = null;

    // Rebuild state from returned steps
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++;
      }
      const _turnId = turnCounter;
      moveHistory.push({
        step: s.step_num, action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null, change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      sessionStepsBuffer.push({
        step_num: s.step_num, action: s.action, data: s.data || {},
        grid: s.grid || null, change_map: s.change_map || null,
        llm_response: s.llm_response || null, timestamp: s.timestamp || 0,
      });
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num, observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '', action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      if (llm && llm.usage) {
        const inTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inTok;
        sessionTotalTokens.output += outTok;
        const prices = TOKEN_PRICES[llm.model || ''] || null;
        if (prices) sessionTotalTokens.cost += (inTok * prices[0] + outTok * prices[1]) / 1_000_000;
      }
    }
    sessionStartTime = Date.now() / 1000;

    // Hide replay bar, show controls
    document.getElementById('replayBar').style.display = 'none';
    document.getElementById('replayReasoningPanel').style.display = 'none';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    initLiveScrubber();

    updateUI(data);
    updateUndoBtn();

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    // Log the branch event on the new session
    logSessionEvent('branch_created', stepNum, { parent_session_id: parentId });

    // Switch to Agent tab and render reasoning trace
    switchTopTab('agent');
    renderRestoredReasoning(steps,
      `Branched from replay at step ${stepNum} (${llmCallCount} prior LLM calls)`,
      'var(--purple)');

    // ── Multi-session: register branch session ──
    const bs = new SessionState(data.session_id);
    bs.gameId = data.game_id || '';
    bs.status = data.state || 'NOT_FINISHED';
    registerSession(data.session_id, bs);

    // Rebuild timelineEvents from step history
    bs.timelineEvents = _rebuildTimelineFromSteps(steps);

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();
  } catch (e) {
    alert('Branch failed: ' + e.message);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MEMORY TAB (system prompt + hard memory editing)
// ═══════════════════════════════════════════════════════════════════════════

// ── Prompt section helpers (scaffolding-specific prompts from window.PROMPTS) ──

const _PROMPT_SECTION_MAP = {
  linear: ['shared', 'linear'],
  linear_interrupt: ['shared', 'linear'],
  rlm: ['shared', 'rlm'],
  three_system: ['shared', 'three_system'],
};

function _humanizePromptName(name) {
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _getPromptSections(schemaId) {
  const sections = _PROMPT_SECTION_MAP[schemaId] || ['shared'];
  const result = [];
  for (const section of sections) {
    const prompts = window.PROMPTS[section];
    if (!prompts) continue;
    for (const name of Object.keys(prompts).sort()) {
      result.push({ section, name, label: _humanizePromptName(name) });
    }
  }
  return result;
}

function _savePromptField(textarea) {
  const key = textarea.dataset.promptKey; // format: section.name
  if (!key) return;
  const [section, name] = key.split('.');
  const defaultVal = (window.PROMPTS[section] && window.PROMPTS[section][name]) || '';
  const lsKey = 'arc_prompt.' + key;
  if (textarea.value === defaultVal) {
    localStorage.removeItem(lsKey);
  } else {
    localStorage.setItem(lsKey, textarea.value);
  }
}

function _populatePromptFields() {
  document.querySelectorAll('textarea[data-prompt-key]').forEach(ta => {
    ta.value = getPrompt(ta.dataset.promptKey);
  });
}

// Which runtime fields each scaffold gets in the Prompts tab
const _PROMPTS_TAB_FEATURES = {
  linear:           { compact: true,  interrupt: false },
  linear_interrupt: { compact: true,  interrupt: true  },
  rlm:              { compact: false, interrupt: false },
  three_system:     { compact: false, interrupt: true  },
  two_system:       { compact: false, interrupt: true  },
};

function renderPromptsTab() {
  const container = document.getElementById('promptsTabBody');
  if (!container) return;
  const schemaId = localStorage.getItem('arc_scaffolding_type') || 'linear';
  const features = _PROMPTS_TAB_FEATURES[schemaId] || { compact: false, interrupt: false };
  const promptSections = _getPromptSections(schemaId);
  let html = '';
  for (const { section, name, label } of promptSections) {
    const key = `${section}.${name}`;
    html += `<div class="mem-section"><label>${label}</label>`;
    html += `<textarea data-prompt-key="${key}" rows="6" placeholder="${key}..."`;
    html += ` onblur="_savePromptField(this)"></textarea></div>`;
  }
  // Runtime fields (read-only, auto-generated) — only shown for relevant scaffolds
  if (features.compact) {
    html += '<div class="mem-section"><label>Compact Summary <span style="font-size:10px;color:var(--text-dim);text-transform:none;">(auto-generated)</span></label>';
    html += '<textarea id="memoryCompactSummary" rows="3" readonly placeholder="No compact summary yet." style="opacity:0.8;"></textarea></div>';
  }
  if (features.interrupt) {
    html += '<div class="mem-section"><label>Interrupt Result <span style="font-size:10px;color:var(--text-dim);text-transform:none;">(auto-generated)</span></label>';
    html += '<textarea id="memoryInterruptResult" rows="2" readonly placeholder="—" style="opacity:0.8;"></textarea></div>';
  }
  html += '<div style="font-size:9px;color:var(--dim);margin-top:4px;font-style:italic;">Edits to prompt templates auto-save to your browser on blur.</div>';
  container.innerHTML = html;
  _populatePromptFields();
  // Restore runtime fields
  const compactEl = document.getElementById('memoryCompactSummary');
  if (compactEl && _cachedCompactSummary) compactEl.value = _cachedCompactSummary;
}

// ═══════════════════════════════════════════════════════════════════════════
// BROWSE SESSIONS VIEW
// ═══════════════════════════════════════════════════════════════════════════

let _browseActive = false;
let _menuActive = false;
let _currentView = 'human';  // tracks which top-level view is active (default: human)
let _browseGlobalCache = null;  // cache server sessions
let _browseGameFilter = null;   // currently selected game in By Game tab

// Hash-to-view mapping
const _VIEW_HASHES = { agent: 'play', human: 'human', sessions: 'browse', leaderboards: 'leaderboard', contributors: 'contributors', feedback: 'feedback' };
const _VIEW_TO_HASH = { play: 'agent', human: 'human', browse: 'sessions', leaderboard: 'leaderboards', contributors: 'contributors', feedback: 'feedback' };

function showAppView(view, skipHash) {
  // Update URL hash (unless called from hashchange handler)
  if (!skipHash) {
    const hash = _VIEW_TO_HASH[view] || 'human';
    if (location.hash !== '#' + hash) history.replaceState(null, '', '#' + hash);
  }

  _currentView = view;
  document.querySelectorAll('.top-nav .nav-link').forEach(l => l.classList.remove('active'));
  const links = document.querySelectorAll('.top-nav .nav-link');
  const browseView = document.getElementById('browseView');
  const sessionHost = document.getElementById('sessionViewHost');
  const tabBar = document.getElementById('sessionTabBar');
  const emptyApp = document.getElementById('emptyAppState');
  const menuView = document.getElementById('menuView');
  const humanView = document.getElementById('humanView');
  const leaderboardView = document.getElementById('leaderboardView');
  const contributorsView = document.getElementById('contributorsView');
  const feedbackView = document.getElementById('feedbackView');

  const sidebar = document.getElementById('gameSidebar');
  const outerLayout = document.getElementById('outerLayout');

  // Hide everything first
  outerLayout.style.display = 'none';
  browseView.style.display = 'none';
  if (humanView) humanView.style.display = 'none';
  if (leaderboardView) leaderboardView.style.display = 'none';
  if (contributorsView) contributorsView.style.display = 'none';
  if (feedbackView) feedbackView.style.display = 'none';
  tabBar.style.display = 'none';
  emptyApp.style.display = 'none';
  menuView.classList.remove('visible');

  // Highlight nav link by href (no brittle index assumptions)
  const _navHighlight = hash => document.querySelector(`.top-nav a[href="#${hash}"]`)?.classList.add('active');
  if (view === 'browse') {
    _navHighlight('sessions');
    _browseActive = true;
    _menuActive = false;
    browseView.style.display = 'flex';
    loadBrowseView();
  } else if (view === 'human') {
    _navHighlight('human');
    _browseActive = false;
    _menuActive = false;
    if (humanView) {
      humanView.style.display = 'flex';
      if (typeof initHumanView === 'function') initHumanView();
    }
  } else if (view === 'leaderboard') {
    _navHighlight('leaderboards');
    _browseActive = false;
    _menuActive = false;
    if (leaderboardView) {
      leaderboardView.style.display = 'flex';
      if (typeof initLeaderboard === 'function') initLeaderboard();
    }
  } else if (view === 'contributors') {
    _navHighlight('contributors');
    _browseActive = false;
    _menuActive = false;
    if (contributorsView) {
      contributorsView.style.display = 'flex';
      if (typeof loadContributors === 'function') loadContributors();
    }
  } else if (view === 'feedback') {
    _navHighlight('feedback');
    _browseActive = false;
    _menuActive = false;
    if (feedbackView) {
      feedbackView.style.display = 'flex';
      if (typeof loadFeedback === 'function') loadFeedback();
    }
  } else {
    // Default: agent / play
    _navHighlight('agent');
    _browseActive = false;
    outerLayout.style.display = '';
    tabBar.style.display = 'flex';
    if (_menuActive) {
      menuView.classList.add('visible');
      sessionHost.style.display = 'none';
      sidebar.style.display = 'none';
    } else {
      menuView.classList.remove('visible');
      sidebar.style.display = '';
      updateEmptyAppState();
      if (sessions.size > 0) sessionHost.style.display = '';
      // Lazy-resume: if active session hasn't been loaded from server yet, resume now
      if (activeSessionId && !activeSessionId.startsWith('pending_')) {
        const _s = sessions.get(activeSessionId);
        if (_s && !_s.currentGrid) resumeSession(activeSessionId);
      }
    }
  }
}

// Route from URL hash on page load and back/forward navigation
function _routeFromHash() {
  const hash = location.hash.replace('#', '');
  const view = _VIEW_HASHES[hash];
  if (view) showAppView(view, true);
}
window.addEventListener('hashchange', _routeFromHash);

// ── Menu view ─────────────────────────────────────────────────────────────

function showMenuView() {
  _menuActive = true;
  _browseActive = false;
  // Save current session state
  if (activeSessionId && sessions.has(activeSessionId)) saveSessionToState();
  // Hide game layout, show menu (do NOT detach — just hide the host)
  const menuView = document.getElementById('menuView');
  const sessionHost = document.getElementById('sessionViewHost');
  const emptyApp = document.getElementById('emptyAppState');
  const browseView = document.getElementById('browseView');
  menuView.classList.add('visible');
  sessionHost.style.display = 'none';
  emptyApp.style.display = 'none';
  browseView.style.display = 'none';
  // Hide game sidebar — menu has its own layout
  document.getElementById('gameSidebar').style.display = 'none';
  // Highlight Play nav link
  document.querySelectorAll('.top-nav .nav-link').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.top-nav .nav-link')[0]?.classList.add('active');
  renderMenuSessions();
  renderSessionTabs();
}

function renderMenuSessions() {
  const container = document.getElementById('menuSessionList');
  if (!container) return;
  const saved = getLocalSessions();
  if (!saved.length) {
    container.innerHTML = '<div class="menu-empty">No saved sessions yet. Start a new session to play!</div>';
    return;
  }
  container.innerHTML = '';
  for (const s of saved) {
    const row = document.createElement('div');
    row.className = 'menu-session-row';
    const gameName = s.game_id || s.id?.slice(0, 8) || '?';
    const steps = s.steps || 0;
    const result = s.result || 'NOT_FINISHED';
    const badgeClass = 'ms-badge-' + result.replace(/\s/g, '_');
    const date = s.created_at ? new Date(s.created_at * 1000).toLocaleDateString() : '';
    row.innerHTML = `
      <span class="ms-game">${gameName}</span>
      <span class="ms-steps">${steps} steps</span>
      <span class="ms-badge ${badgeClass}">${result.replace(/_/g, ' ')}</span>
      <span class="ms-date">${date}</span>
      <button class="ms-resume" onclick="event.stopPropagation(); menuResume('${s.id}');">Resume</button>`;
    container.appendChild(row);
  }
}

function menuResume(sid) {
  _menuActive = false;
  document.getElementById('menuView').classList.remove('visible');
  showAppView('play');
  browseResume(sid);
}

function switchBrowseTab(tab) {
  document.querySelectorAll('.browse-tabs button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.browse-pane').forEach(p => p.classList.remove('active'));
  const idx = { byGame: 0, global: 1, local: 2 }[tab] || 0;
  const btns = document.querySelectorAll('.browse-tabs button');
  if (btns[idx]) btns[idx].classList.add('active');
  const paneMap = { byGame: 'browseByGame', global: 'browseGlobal', local: 'browseLocal' };
  const pane = document.getElementById(paneMap[tab]);
  if (pane) pane.classList.add('active');
  if (tab === 'global') loadBrowseGlobal();
  if (tab === 'local') loadBrowseLocal();
  if (tab === 'byGame') loadBrowseByGame();
}

function loadBrowseView() {
  // Load whichever tab is active
  const activeBtn = document.querySelector('.browse-tabs button.active');
  const tab = activeBtn?.textContent?.trim();
  if (tab === 'Public Sessions') loadBrowseGlobal();
  else if (tab === 'My Sessions') loadBrowseLocal();
  else loadBrowseByGame();
}

// ── By Game tab ──────────────────────────────────────────────────────────

async function loadBrowseByGame() {
  const listEl = document.getElementById('browseGameList');
  // Populate game list
  try {
    let games = await fetchJSON('/api/games');
    if (MODE === 'prod') games = games.filter(g => g.game_id !== 'fd01-00000001');
    listEl.innerHTML = '';
    const foundation = games.filter(g => _ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
    const observatory = games.filter(g => !_ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
    _renderGameGroup(listEl, 'ARC Prize Foundation', foundation, g => loadGameSessions(g.game_id));
    _renderGameGroup(listEl, 'ARC Observatory', observatory, g => loadGameSessions(g.game_id));
  } catch { listEl.innerHTML = '<div class="browse-empty">Failed to load games.</div>'; }
}

async function loadGameSessions(gameId) {
  _browseGameFilter = gameId;
  // Highlight active game
  document.querySelectorAll('#browseGameList .game-card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('#browseGameList .game-card').forEach(c => {
    if (c.querySelector('.title')?.textContent === gameShortName(gameId)) c.classList.add('active');
  });
  const el = document.getElementById('browseGameSessions');
  el.innerHTML = '<div class="browse-empty">Loading sessions...</div>';
  try {
    // Fetch all sessions then filter by game
    const allSessions = await fetchAllSessions();
    const gameSessions = allSessions.filter(s => s.game_id === gameId);
    if (!gameSessions.length) {
      el.innerHTML = `<div class="browse-empty">No sessions for ${gameShortName(gameId)} yet.</div>`;
      return;
    }
    el.innerHTML = '';
    for (const s of gameSessions) el.appendChild(buildSessionRow(s));
  } catch (e) {
    el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
  }
}

// ── Public Sessions tab ──────────────────────────────────────────────────

async function loadBrowseGlobal() {
  const el = document.getElementById('browseGlobalList');
  el.innerHTML = '<div class="browse-empty">Loading...</div>';
  try {
    const allSessions = await fetchAllSessions(true);
    let filtered = allSessions.filter(s => (s.steps || 0) >= 20);
    if (MODE === 'prod') filtered = filtered.filter(s => s.game_id !== 'fd01-00000001');
    const header = document.getElementById('browseGlobalHeader');
    header.textContent = `All sessions from server (${filtered.length} with 20+ steps)`;
    if (!filtered.length) {
      el.innerHTML = '<div class="browse-empty">No sessions with 20+ steps found.</div>';
      return;
    }
    el.innerHTML = '';
    for (const s of filtered) el.appendChild(buildSessionRow(s));
  } catch (e) {
    el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
  }
}

// ── My Sessions tab ──────────────────────────────────────────────────────

async function loadBrowseLocal() {
  const el = document.getElementById('browseLocalList');
  const header = document.getElementById('browseLocalHeader');

  // If logged in, fetch user's sessions from server
  if (currentUser) {
    el.innerHTML = '<div class="browse-empty">Loading...</div>';
    try {
      const data = await fetchJSON('/api/sessions?mine=1');
      const serverSessions = data.sessions || [];
      // Merge with local sessions (dedup by id)
      const localSessions = getLocalSessions();
      const byId = {};
      for (const s of serverSessions) byId[s.id] = s;
      for (const s of localSessions) { if (!byId[s.id]) byId[s.id] = s; }
      const merged = Object.values(byId).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      header.textContent = `My sessions (${merged.length})`;
      if (!merged.length) {
        el.innerHTML = '<div class="browse-empty">No sessions yet. Play a game to see sessions here.</div>';
        return;
      }
      el.innerHTML = '';
      for (const s of merged) el.appendChild(buildSessionRow(s));
    } catch (e) {
      el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
    }
    return;
  }

  // Not logged in — show local-only sessions
  const localSessions = getLocalSessions();
  header.textContent = `My sessions (${localSessions.length})`;
  if (!localSessions.length) {
    el.innerHTML = '<div class="browse-empty">Log in to see your sessions across devices, or play a game to save sessions locally.</div>';
    return;
  }
  el.innerHTML = '';
  for (const s of localSessions) {
    el.appendChild(buildSessionRow(s, true));
  }
}

// ── Shared helpers ───────────────────────────────────────────────────────

async function fetchAllSessions(forceRefresh) {
  if (_browseGlobalCache && !forceRefresh) return _browseGlobalCache;
  const data = await fetchJSON('/api/sessions');
  let serverSessions = data.sessions || [];
  // Merge localStorage sessions (dedup)
  if (MODE === 'prod') {
    const byId = {};
    for (const s of serverSessions) byId[s.id] = s;
    for (const s of getLocalSessions()) { if (!byId[s.id]) byId[s.id] = s; }
    serverSessions = Object.values(byId);
  }
  serverSessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  _browseGlobalCache = serverSessions;
  return serverSessions;
}

function buildSessionRow(s, isLocal) {
  const div = document.createElement('div');
  div.className = 'session-row';
  const date = new Date((s.created_at || 0) * 1000);
  const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const result = s.result || 'NOT_FINISHED';
  const resultClass = `s-result-${result}`;
  const branchHtml = s.parent_session_id
    ? `<span class="s-branch">&#8627; branch@${s.branch_at_step || '?'}</span>` : '';
  const costStr = (s.total_cost || s.cost || 0) > 0
    ? `$${(s.total_cost || s.cost || 0).toFixed(4)}` : '';
  const durationStr = s.duration ? formatDuration(s.duration) : '';
  const metaParts = [
    `${s.steps || 0} steps`,
    s.model || '',
    costStr,
    durationStr,
    dateStr,
  ].filter(Boolean).join(' · ');

  div.innerHTML = `
    ${branchHtml}
    <span class="s-game">${gameShortName(s.game_id) || '?'}</span>
    <span class="s-result ${resultClass}">${result}</span>
    <span class="s-model">${s.model || '—'}</span>
    <span class="s-meta">${metaParts}</span>
    <span class="s-actions">
      <button class="btn" onclick="event.stopPropagation(); window.open('/share/${s.id}','_blank');">Shareable Replay</button>
      ${result === 'NOT_FINISHED' ? `<button class="btn btn-primary" onclick="event.stopPropagation(); browseResume('${s.id}');">&#9654; Resume playing</button>` : ''}
      ${isLocal ? `<button class="btn btn-danger" onclick="event.stopPropagation(); browseDeleteLocal('${s.id}', this);">Delete</button>` : ''}
    </span>`;
  return div;
}

function browseReplay(sid) {
  showAppView('play');
  loadReplay(sid);
}

function browseResume(sid) {
  showAppView('play');
  // Create a new session tab for this resume
  if (!sessions.has(sid)) {
    // Detach current session if any
    if (activeSessionId && sessions.has(activeSessionId)) {
      saveSessionToState();
      detachSessionView(activeSessionId);
    }
    const s = new SessionState(sid);
    sessions.set(sid, s);
    activeSessionId = sid;
    attachSessionView(sid);
    renderSessionTabs();
  } else {
    switchSession(sid);
  }
  resumeSession(sid);
}

function browseDeleteLocal(sid, btn) {
  if (!confirm('Delete this local session?')) return;
  deleteLocalSession(sid);
  const row = btn.closest('.session-row');
  if (row) row.remove();
  // Update header count
  const header = document.getElementById('browseLocalHeader');
  const count = getLocalSessions().length;
  header.textContent = `Sessions stored in this browser (${count})`;
}

// ═══════════════════════════════════════════════════════════════════════════
// MULTI-SESSION: Tab rendering, switching, creation, closing
// ═══════════════════════════════════════════════════════════════════════════

function getTabDotClass(s) {
  if (s.status === 'WIN') return 'tab-dot-win';
  if (s.status === 'GAME_OVER') return 'tab-dot-gameover';
  if ((s.autoPlaying || s.waitingForLLM) && s.status === 'NOT_FINISHED') return 'tab-dot-running';
  return 'tab-dot-idle';
}

function renderSessionTabs() {
  const bar = document.getElementById('sessionTabBar');
  if (!bar) return;
  bar.innerHTML = '';

  // Menu tab (always first)
  const menuTab = document.createElement('div');
  menuTab.className = 'session-tab-menu' + (_menuActive ? ' active' : '');
  menuTab.innerHTML = '<span class="menu-icon">&#9776;</span> Menu';
  menuTab.onclick = () => showMenuView();
  bar.appendChild(menuTab);

  // Session tabs
  for (const [id, s] of sessions) {
    const tab = document.createElement('div');
    tab.className = 'session-tab' + (id === activeSessionId && !_menuActive ? ' active' : '');
    const label = s.tabLabel || s.gameId || (id.startsWith('pending_') ? 'New Session' : id.slice(0, 8));
    const dotClass = getTabDotClass(s);
    const stepBadge = s.stepCount > 0 ? `<span class="tab-steps">${s.stepCount}</span>` : '';
    tab.innerHTML = `
      <span class="tab-dot ${dotClass}"></span>${stepBadge}
      <span class="tab-label">${label}</span>
      <span class="tab-countdown" id="tabCountdown_${id}"></span>
      <button class="tab-close" onclick="event.stopPropagation(); closeSession('${id}');">&times;</button>`;
    tab.title = `${s.gameId || 'No game'} | ${s.stepCount} steps | $${(s.sessionTotalTokens?.cost || 0).toFixed(3)}`;
    tab.onclick = () => switchSession(id);
    bar.appendChild(tab);
  }

  // Quick + button for new session
  const newBtn = document.createElement('button');
  newBtn.className = 'session-tab-new';
  newBtn.textContent = '+';
  newBtn.title = 'New Session';
  newBtn.onclick = createNewSession;
  bar.appendChild(newBtn);

  updateEmptyAppState();
}

function resetGlobalsToBlank() {
  sessionId = null;
  currentGrid = null;
  previousGrid = null;
  currentChangeMap = null;
  currentState = {};
  stepCount = 0;
  llmCallCount = 0;
  turnCounter = 0;
  moveHistory = [];
  undoStack = [];
  llmObservations = [];
  autoPlaying = false;
  action6Mode = false;
  sessionTotalTokens = { input: 0, output: 0, cost: 0 };
  sessionStepsBuffer = [];
  sessionStartTime = null;
  syncStepCounter = 0;
  _cachedCompactSummary = '';
  _compactSummaryAtCall = 0;
  _compactSummaryAtStep = 0;
  _lastCompactPrompt = '';
  hideLiveScrubber();
}

function createNewSession() {
  // Hide menu view if active
  if (_menuActive) {
    _menuActive = false;
    document.getElementById('menuView').classList.remove('visible');
    document.getElementById('sessionViewHost').style.display = '';
    document.getElementById('gameSidebar').style.display = '';
  }
  // Save + detach current session if one exists
  if (activeSessionId && sessions.has(activeSessionId)) {
    saveSessionToState();
    detachSessionView(activeSessionId);
  }
  // Create a pending session with fresh DOM
  const pendingId = 'pending_' + Math.random().toString(36).slice(2, 10);
  const s = new SessionState(pendingId);
  sessions.set(pendingId, s);
  activeSessionId = pendingId;
  resetGlobalsToBlank();
  // Attach fresh DOM from template
  attachSessionView(pendingId);
  // Reset UI on the fresh DOM
  canvas.style.display = 'none';
  document.getElementById('emptyState').style.display = '';
  document.getElementById('controls').style.display = 'none';
  document.getElementById('transportBar').style.display = 'none';
  document.getElementById('gameTitle').textContent = 'No game selected';
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = '—';
  statusEl.className = 'status status-NOT_PLAYED';
  document.getElementById('levelInfo').textContent = '';
  document.getElementById('stepCounter').textContent = '';
  document.getElementById('reasoningContent').innerHTML =
    '<div class="empty-state" style="height:auto;font-size:12px;">Select a game from the sidebar to start.</div>';
  // Unlock sidebar for game selection
  updatePanelBlur();
  updateGameListLock();
  renderSessionTabs();
  saveSessionIndex();
}

function switchSession(targetId) {
  if (targetId === activeSessionId && !_menuActive) return;
  const target = sessions.get(targetId);
  if (!target) return;

  const wasMenu = _menuActive;
  // Hide menu view if active
  if (_menuActive) {
    _menuActive = false;
    document.getElementById('menuView').classList.remove('visible');
    document.getElementById('sessionViewHost').style.display = '';
    document.getElementById('gameSidebar').style.display = '';
  }

  // If returning from menu to the same session, just re-show — don't re-attach
  if (wasMenu && targetId === activeSessionId) {
    renderSessionTabs();
    return;
  }

  // Close replay if open
  closeReplay();
  // Save + detach current session (do NOT stop autoplay — let it run in background)
  if (activeSessionId && sessions.has(activeSessionId) && activeSessionId !== targetId) {
    saveSessionToState();
    detachSessionView(activeSessionId);
  }
  // Switch
  activeSessionId = targetId;
  attachSessionView(targetId);
  restoreSessionFromState(target);
  renderSessionTabs();

  // If this is a restored stub (no grid data), resume from server
  if (!target.currentGrid && target.sessionId && !target.sessionId.startsWith('pending_')) {
    resumeSession(target.sessionId);
  }

  // If target session is in obs/autoplay mode, re-enter observatory view
  if (target.autoPlaying || document.getElementById('obsScreen')?.style.display === 'flex') {
    enterObsMode(target);
  }
}

function closeSession(id) {
  const s = sessions.get(id);
  if (!s) return;

  try {
    // Stop autoplay if running
    if (s.autoPlaying) { s.autoPlaying = false; }
    if (id === activeSessionId && autoPlaying) { autoPlaying = false; updateAutoBtn(); }
    // Abort in-flight LLM fetch
    if (s.abortController) { s.abortController.abort(); s.abortController = null; }
    // Clear REPL namespace for this session
    if (_pyodideWorker && _pyodideReady) {
      const clearId = ++_pyodideCallId;
      _pyodideWorker.postMessage({type: 'clear_session', id: clearId, session_id: s.sessionId || id});
    }
    // Upload session to main DB before deleting (if enough steps)
    if (id === activeSessionId) saveSessionToState();
    uploadClosedSession(s);
    // Persist session data to localStorage
    try {
      const steps = s.sessionStepsBuffer || [];
      if (steps.length > 0 && s.gameId) {
        saveLocalSession({
          id: s.sessionId || id,
          game_id: s.currentState?.game_id || s.gameId,
          model: s.model || '',
          result: s.currentState?.state || s.status || 'NOT_FINISHED',
          steps: s.stepCount || steps.length,
          levels: s.currentState?.levels_completed || 0,
          created_at: s.createdAt || (Date.now() / 1000),
        }, steps);
      }
    } catch (e) { console.warn('[closeSession] saveLocalSession failed:', e); }
  } catch (e) { console.warn('[closeSession] pre-delete step failed:', e); }

  // Detach + free DOM if this is the active session
  if (id === activeSessionId) {
    detachSessionView(id);
  }
  // Free detached DOM memory
  s._viewEl = null;

  // Always delete and update UI regardless of any errors above
  sessions.delete(id);

  try {
    if (id === activeSessionId) {
      const remaining = [...sessions.keys()];
      if (remaining.length > 0) {
        switchSession(remaining[remaining.length - 1]);
      } else {
        activeSessionId = null;
        resetGlobalsToBlank();
      }
    }
  } catch (e) { console.warn('[closeSession] post-delete UI update failed:', e); }

  renderSessionTabs();
  saveSessionIndex();
  updateGameListLock();
  updateEmptyAppState();
}

function updatePanelBlur() {
  // Don't blur the right panel — only blur after a game has started and ended,
  // not before. Keep it always visible so users can configure settings first.
}

function updateGameListLock() {
  const sidebar = document.getElementById('gameSidebar');
  if (sidebar) {
    // Lock the sidebar once a session has any steps — can't switch games mid-session
    const cur = getActiveSession();
    const hasSteps = (cur && cur.stepCount > 0) || stepCount > 0;
    const shouldLock = sessionId && hasSteps;
    sidebar.classList.toggle('locked', shouldLock);
  }
}

function updateEmptyAppState() {
  const empty = document.getElementById('emptyAppState');
  const sessionHost = document.getElementById('sessionViewHost');
  const menuView = document.getElementById('menuView');
  if (!empty || !sessionHost) return;
  if (_currentView !== 'play') return; // only applies to agent view
  if (_browseActive) return; // browse view handles its own display
  if (_menuActive) return; // menu view handles its own display
  if (sessions.size === 0) {
    // Show menu view instead of hero when no sessions
    empty.style.display = 'none';
    sessionHost.style.display = 'none';
    _menuActive = true;
    menuView.classList.add('visible');
    document.getElementById('gameSidebar').style.display = 'none';
    renderMenuSessions();
    renderSessionTabs();
  } else {
    empty.style.display = 'none';
    menuView.classList.remove('visible');
    sessionHost.style.display = '';
  }
}

// ── Countdown timer functions ────────────────────────────────────────────

function startCountdown(s) { /* removed — countdown disabled */ }
function stopCountdown(s) { /* removed — countdown disabled */ }

// ── localStorage session index ───────────────────────────────────────────

const MULTI_SESSION_KEY = 'arc_multi_sessions';

function saveSessionIndex() {
  try {
    const index = [];
    for (const [id, s] of sessions) {
      if (id.startsWith('pending_') && !s.gameId) continue; // skip truly empty pending
      index.push({
        id: s.sessionId || id,
        gameId: s.gameId || '',
        tabLabel: s.tabLabel || '',
        model: s.model || '',
        status: s.status || 'NOT_PLAYED',
        steps: s.stepCount || 0,
        cost: s.sessionTotalTokens?.cost || 0,
        createdAt: s.createdAt || 0,
      });
    }
    localStorage.setItem(MULTI_SESSION_KEY, JSON.stringify(index));
  } catch {}
}

function loadSessionIndex() {
  try {
    return JSON.parse(localStorage.getItem(MULTI_SESSION_KEY)) || [];
  } catch { return []; }
}

function restoreSessionsFromLocalStorage() {
  const index = loadSessionIndex();
  if (!index.length) return;
  for (const meta of index) {
    if (sessions.has(meta.id)) continue;
    const s = new SessionState(meta.id);
    s.gameId = meta.gameId || '';
    s.tabLabel = meta.tabLabel || '';
    s.model = meta.model || '';
    s.status = meta.status || 'NOT_PLAYED';
    s.stepCount = meta.steps || 0;
    s.sessionTotalTokens = { input: 0, output: 0, cost: meta.cost || 0 };
    s.createdAt = meta.createdAt || 0;
    sessions.set(meta.id, s);
  }
  if (sessions.size > 0 && !activeSessionId) {
    activeSessionId = [...sessions.keys()][0];
  }
  renderSessionTabs();

  // Auto-resume only if we're about to show the agent/play view
  // (avoids async resume overwriting human view on default load)
  if (_currentView === 'play' && activeSessionId && !activeSessionId.startsWith('pending_')) {
    resumeSession(activeSessionId);
  } else {
    updateGameListLock();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

async function initApp() {
  // Render scaffolding settings (must happen before loadModels populates selects)
  migrateOldSettingsToScaffolding();
  const savedScaffolding = localStorage.getItem('arc_scaffolding_type') || 'linear';
  renderScaffoldingSettings(savedScaffolding);
  loadScaffoldingFromStorage(savedScaffolding);

  loadGames();
  await loadModels();  // await so selects are populated before template capture
  // Capture populated DOM as clonable template for new sessions
  captureSessionTemplate();

  if (FEATURES.copilot) checkCopilotStatus();
  if (FEATURES.puter_js) puterKvCheckResume();

  // Establish view FIRST so _currentView is set before session restore
  // Default to human view for empty hash, #human, or #agent (old default)
  if (location.hash && location.hash !== '#' && location.hash !== '#human' && location.hash !== '#agent') {
    _routeFromHash();
  } else {
    showAppView('human');
  }

  // Restore sessions AFTER view is set (auto-resume only fires in agent/play view)
  restoreSessionsFromLocalStorage();

  // Auth: check login status (async, doesn't block init)
  checkAuthStatus();
}

// ═══════════════════════════════════════════════════════════════════════════
// AUTH — Magic link login
// ═══════════════════════════════════════════════════════════════════════════

function updateAuthUI() {
  const loginBtn = document.getElementById('loginBtn');
  const userBadge = document.getElementById('userBadge');
  if (currentUser) {
    loginBtn.style.display = 'none';
    userBadge.style.display = '';
    const label = currentUser.display_name || currentUser.email.split('@')[0];
    document.getElementById('userBadgeLabel').textContent = label;
    document.getElementById('userMenuEmail').textContent = currentUser.email;
  } else {
    loginBtn.style.display = '';
    userBadge.style.display = 'none';
  }
}

function toggleUserMenu() {
  const menu = document.getElementById('userMenu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

// Close user menu on outside click
document.addEventListener('click', (e) => {
  const badge = document.getElementById('userBadge');
  const menu = document.getElementById('userMenu');
  if (badge && menu && !badge.contains(e.target)) {
    menu.style.display = 'none';
  }
});

function showLoginModal() {
  const modal = document.getElementById('loginModal');
  modal.style.display = 'flex';
  document.getElementById('loginStep1').style.display = '';
  document.getElementById('loginStep2').style.display = 'none';
  document.getElementById('loginError').style.display = 'none';
  const emailEl = document.getElementById('loginEmail');
  if (emailEl) { emailEl.value = ''; emailEl.focus(); }
  // Render Google button if GSI is loaded
  if (typeof GOOGLE_CLIENT_ID !== 'undefined' && GOOGLE_CLIENT_ID && window.google?.accounts?.id) {
    _initGoogleSignIn();
  }
}

function hideLoginModal() {
  document.getElementById('loginModal').style.display = 'none';
}

// ── Google Sign-In (GSI) ────────────────────────────────────────────────

let _gsiInitialized = false;

function _initGoogleSignIn() {
  if (_gsiInitialized) return;
  const container = document.getElementById('googleSignInBtn');
  if (!container || !window.google?.accounts?.id) return;
  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: _handleGoogleCredential,
  });
  google.accounts.id.renderButton(container, {
    theme: 'outline',
    size: 'large',
    width: 312,
    text: 'signin_with',
  });
  _gsiInitialized = true;
}

async function _handleGoogleCredential(response) {
  const errEl = document.getElementById('loginError');
  try {
    const resp = await fetch('/api/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential: response.credential }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (errEl) { errEl.textContent = data.error || 'Google login failed'; errEl.style.display = ''; }
      return;
    }
    currentUser = data.user;
    updateAuthUI();
    hideLoginModal();
    claimLocalSessions();
  } catch (e) {
    if (errEl) { errEl.textContent = 'Network error. Please try again.'; errEl.style.display = ''; }
  }
}

// Initialize GSI when the script loads (if available)
if (typeof GOOGLE_CLIENT_ID !== 'undefined' && GOOGLE_CLIENT_ID) {
  // GSI script may load after this file — wait for it
  const _waitGSI = setInterval(() => {
    if (window.google?.accounts?.id) {
      clearInterval(_waitGSI);
      _initGoogleSignIn();
    }
  }, 200);
  // Stop waiting after 10 seconds
  setTimeout(() => clearInterval(_waitGSI), 10000);
}

// Close modal on backdrop click
document.getElementById('loginModal')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) hideLoginModal();
});

// Submit on Enter in email field
document.getElementById('loginEmail')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMagicLink();
});

async function sendMagicLink() {
  const email = document.getElementById('loginEmail').value.trim();
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginSendBtn');
  if (!email || !email.includes('@')) {
    errEl.textContent = 'Please enter a valid email address.';
    errEl.style.display = '';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Sending...';
  errEl.style.display = 'none';
  try {
    const resp = await fetch('/api/auth/magic-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errEl.textContent = data.error || 'Failed to send link';
      errEl.style.display = '';
      btn.disabled = false;
      btn.textContent = 'Send login link';
      return;
    }
    // Dev mode: if code returned, auto-verify
    if (data.dev_code) {
      window.location.href = '/api/auth/verify?code=' + data.dev_code;
      return;
    }
    document.getElementById('loginStep1').style.display = 'none';
    document.getElementById('loginStep2').style.display = '';
    document.getElementById('loginSentEmail').textContent = email;
  } catch (e) {
    errEl.textContent = 'Network error. Please try again.';
    errEl.style.display = '';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send login link';
  }
}

async function doLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (e) { /* ignore */ }
  currentUser = null;
  updateAuthUI();
  document.getElementById('userMenu').style.display = 'none';
}

async function checkAuthStatus() {
  try {
    const resp = await fetch('/api/auth/status');
    const data = await resp.json();
    if (data.authenticated && data.user) {
      currentUser = data.user;
      updateAuthUI();
      // Claim local sessions
      claimLocalSessions();
    } else {
      currentUser = null;
      updateAuthUI();
    }
  } catch (e) {
    console.warn('Auth status check failed:', e);
    currentUser = null;
    updateAuthUI();
  }
  // Clean ?logged_in param from URL
  if (new URLSearchParams(window.location.search).has('logged_in')) {
    const url = new URL(window.location);
    url.searchParams.delete('logged_in');
    window.history.replaceState({}, '', url.pathname + url.search);
  }
}

async function claimLocalSessions() {
  if (!currentUser) return;
  // Collect session IDs from localStorage
  const ids = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('arc_session_')) {
      ids.push(key.replace('arc_session_', ''));
    }
  }
  if (ids.length === 0) return;
  try {
    await fetch('/api/auth/claim-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_ids: ids }),
    });
  } catch (e) {
    console.warn('Claim sessions failed:', e);
  }
}

// If no Turnstile gate (not configured), init immediately
if (turnstileVerified) initApp();
