// ═══════════════════════════════════════════════════════════════════════════
// SESSION PERSISTENCE — Session recording, upload, sharing, and restoration
// ═══════════════════════════════════════════════════════════════════════════
//
// This module handles session persistence across network boundaries:
// - Turnstile human verification + fetchJSON wrapper
// - Session step recording and periodic syncing
// - Session payload building and validation
// - Auto-upload to server and Puter.kv storage
// - Session sharing (share links, banners)
// - Puter.kv resume detection and recovery
// - renderRestoredReasoning() for displaying persisted/resumed session history
//
// Dependencies:
// - getPrompt(), getSelectedModel(), getActiveSession() (from llm.js)
// - fetchJSON(), gameShortName(), updateUI(), MODE, FEATURES, currentUser, currentState, sessionId, stepCount, currentGrid (from ui/state)
// - saveLocalSession(), getLocalSessionData(), formatDuration() (from session-storage.js)
// - buildReasoningGroupHTML(), annotateCoordRefs(), scrollReasoningToBottom() (from llm.js)
// - saveSessionIndex(), renderSessionTabs(), updateEmptyAppState() (from session.js)
// ═══════════════════════════════════════════════════════════════════════════

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
  const url = `${base}/share?id=${sid}`;
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

