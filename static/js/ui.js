// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47 (Phase 24 refactor: extracted model mgmt, token display, grid UI)
// PURPOSE: UI interaction handlers for ARC-AGI-3 web UI. Provides collapsible section
//   toggling, compact settings, grid rendering wrappers (renderGrid, renderGridWithChanges
//   delegating to grid-renderer.js), keyboard/mouse input handling, canvas click-to-act,
//   cell info tooltips, navigation buttons, and DOM manipulation helpers. Modified in
//   Phase 3 to extract pure grid rendering to rendering/grid-renderer.js.
//   Phase 24: extracted model management (ui-models.js), token UI (ui-tokens.js),
//   grid canvas helpers (ui-grid.js).
// SRP/DRY check: Pass — pure rendering in grid-renderer.js; model mgmt in ui-models.js;
//   token UI in ui-tokens.js; grid UI helpers in ui-grid.js; this file owns control flow
// ═══════════════════════════════════════════════════════════════════════════
// COLLAPSIBLE SECTIONS
// ═══════════════════════════════════════════════════════════════════════════

function toggleSection(id) {
  document.getElementById(id).classList.toggle('open');
}

function toggleCompactSettings() {
  const on = document.getElementById('compactContext')?.checked;
  const body = document.getElementById('compactSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function toggleInterruptSettings() {
  const on = document.getElementById('interruptPlan')?.checked;
  const body = document.getElementById('interruptSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function switchTopTab(tab) {
  // History tab removed — this is now a no-op kept for compat with resume/branch code
  if (tab === 'agent') switchSubTab('settings');
}

function switchSubTab(tab) {
  // Reasoning/timeline tabs removed — redirect to settings
  if (tab === 'reasoning' || tab === 'timeline') tab = 'settings';
  document.querySelectorAll('.subtab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.subtab-pane').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  const tabMap = { settings: 'subtabSettings', prompts: 'subtabPrompts', graphics: 'subtabGraphics' };
  const buttons = document.querySelectorAll('.subtab-bar button');
  const idx = { settings: 0, prompts: 1, graphics: 2 }[tab] || 0;
  if (buttons[idx]) buttons[idx].classList.add('active');
  const pane = document.getElementById(tabMap[tab]);
  if (pane) { pane.classList.add('active'); pane.style.display = 'flex'; }
  if (tab === 'prompts') renderPromptsTab();
}

function toggleAdBanner() {} // legacy no-op


// ═══════════════════════════════════════════════════════════════════════════
// GRAPHICS LISTENERS
// ═══════════════════════════════════════════════════════════════════════════

document.getElementById('changeOpacity').addEventListener('input', (e) => {
  document.getElementById('changeOpacityVal').textContent = e.target.value + '%';
  redrawGrid();
});
document.getElementById('showChanges').addEventListener('change', redrawGrid);
document.getElementById('changeColor').addEventListener('input', redrawGrid);

function showTransportDesc(text) {
  document.getElementById('transportDesc').textContent = text;
}
function clearTransportDesc() {
  document.getElementById('transportDesc').textContent = '';
}

function redrawGrid() {
  if (!currentGrid) return;
  if (currentChangeMap && currentChangeMap.change_count > 0 && document.getElementById('showChanges').checked) {
    renderGridWithChanges(currentGrid, currentChangeMap);
  } else {
    renderGrid(currentGrid);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// RENDERING
// ═══════════════════════════════════════════════════════════════════════════

function renderGrid(grid) {
  if (!grid || !grid.length) return;
  currentGrid = grid;  // ui.js-specific side effect
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
}

function renderGridWithChanges(grid, changeMap) {
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
  const enabled = document.getElementById('showChanges') ? document.getElementById('showChanges').checked : true;
  const opacityEl = document.getElementById('changeOpacity');
  const colorEl = document.getElementById('changeColor');
  const opacity = opacityEl ? parseInt(opacityEl.value) / 100 : 0.4;
  const color = colorEl ? colorEl.value : '#ff0000';
  renderGridWithChangesOnCanvas(grid, changeMap, canvas, ctx, COLORS, { opacity, color, stroke: true, enabled });
}

// ═══════════════════════════════════════════════════════════════════════════
// API
// ═══════════════════════════════════════════════════════════════════════════

async function fetchJSON(url, body, signal) {
  const r = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: signal || undefined,
  });
  return r.json();
}

const _ARC_FOUNDATION_GAMES = ['ls20', 'vc33', 'ft09', 'lp85'];
function gameSource(gameId) {
  const short = (gameId || '').split('-')[0].toLowerCase();
  return _ARC_FOUNDATION_GAMES.includes(short) ? 'ARC Prize Foundation' : 'ARC Observatory';
}
function gameDevTag(gameId) {
  const short = (gameId || '').split('-')[0].toLowerCase();
  if (_ARC_FOUNDATION_GAMES.includes(short)) return '';
  return '<span class="dev-tag" title="The game is currently iterating through feedback before released and open-sourced">staging</span>';
}

async function loadGames() {
  let games = await fetchJSON('/api/games');
  // Hide "Find the Difference" on the online/global server for now
  // prod filtering handled server-side via HIDDEN_GAMES
  const el = document.getElementById('gameList');
  el.innerHTML = '';
  const foundation = games.filter(g => _ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
  const observatory = games.filter(g => !_ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
  const sortByTitle = (a, b) => ((a.title || a.game_id).localeCompare(b.title || b.game_id));
  foundation.sort(sortByTitle);
  observatory.sort(sortByTitle);
  _renderGameGroup(el, 'ARC Prize Foundation', foundation, g => startGame(g.game_id));
  _renderGameGroup(el, 'ARC Observatory', observatory, g => startGame(g.game_id));
}

function _renderGameGroup(el, label, games, onClick) {
  if (!games.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'game-group';
  const header = document.createElement('div');
  header.className = 'game-group-header';
  header.innerHTML = `<span class="game-group-arrow">&#9662;</span> ${_esc(label)} <span class="game-group-count">${games.length}</span>`;
  header.onclick = () => {
    wrap.classList.toggle('collapsed');
    header.querySelector('.game-group-arrow').innerHTML = wrap.classList.contains('collapsed') ? '&#9656;' : '&#9662;';
  };
  wrap.appendChild(header);
  const list = document.createElement('div');
  list.className = 'game-group-list';
  games.forEach(g => {
    const div = document.createElement('div');
    div.className = 'game-card';
    const shortName = g.title || g.game_id.split('-')[0].toUpperCase();
    const tag = gameDevTag(g.game_id);
    const liveTag = (g.tags || []).includes('live') ? ' <span class="live-tag">LIVE</span>' : '';
    const gameLabel = g.game_id.split('-')[0].toUpperCase();
    div.innerHTML = `<div class="title">${shortName}${tag ? ' ' + tag : ''}${liveTag}</div><div class="game-id-label">${gameLabel}</div>`;
    div.dataset.gameId = g.game_id;
    div.onclick = () => onClick(g);
    list.appendChild(div);
  });
  wrap.appendChild(list);
  el.appendChild(wrap);
}

function gameShortName(gameId) {
  return (gameId || '').split('-')[0].toUpperCase();
}

async function startGame(gameId) {
  // Block game change if current session already has moves
  const cur = getActiveSession();
  if (cur && cur.stepCount > 0) return;

  document.querySelectorAll('.game-card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.game-card').forEach(c => {
    if (c.dataset.gameId === gameId) c.classList.add('active');
  });

  // Pyodide mode: run game entirely client-side. Server mode: run entirely server-side.
  let data;
  if (FEATURES.pyodide_game) {
    _pyodideGameActive = true;
    _pyodideGameSessionId = activeSessionId;
    try {
      data = await pyodideStartGame(gameId);
      console.log('[PyodideGame] Game started client-side:', gameId);
    } catch (err) {
      _pyodideGameActive = false;
      alert('Game engine failed to load: ' + err.message);
      return;
    }
  } else {
    _pyodideGameActive = false;
    data = await fetchJSON('/api/start', { game_id: gameId });
  }
  if (data.error) { alert(data.error); return; }

  sessionId = data.session_id;
  stepCount = 0;
  llmCallCount = 0;
  turnCounter = 0;
  _cachedCompactSummary = '';
  _compactSummaryAtCall = 0;
  _compactSummaryAtStep = 0;
  moveHistory = [];
  undoStack = [];
  sessionStepsBuffer = [];
  sessionStartTime = Date.now() / 1000;
  syncStepCounter = 0;
  llmObservations = [];
  sessionTotalTokens = { input: 0, output: 0, cost: 0 };
  autoPlaying = false;
  updateUI(data);
  updateUndoBtn();

  if ((data.available_actions || []).includes(6)) { action6Mode = true; canvas.style.cursor = 'crosshair'; }
  document.getElementById('emptyState').style.display = 'none';
  canvas.style.display = 'block';
  document.getElementById('controls').style.display = 'flex';
  document.getElementById('transportBar').style.display = 'block';
  document.getElementById('reasoningContent').innerHTML =
    '<div class="empty-state" style="height:auto;font-size:12px;">Game started. Press Agent Autoplay to let the agent play, or use the controls to play yourself.</div>';

  // ── Multi-session: reuse current tab when switching games (no moves yet) ──
  const curSession = getActiveSession();
  if (curSession && curSession.stepCount === 0) {
    // Reuse the current tab — just swap the session ID
    const oldId = activeSessionId;
    sessions.delete(oldId);
    curSession.sessionId = data.session_id;
    curSession.gameId = gameShortName(gameId);
    curSession.status = data.state || 'NOT_FINISHED';
    curSession.createdAt = Date.now() / 1000;
    curSession.callDurations = [];
    curSession.tabLabel = '';
    sessions.set(data.session_id, curSession);
    activeSessionId = data.session_id;
    // Update Pyodide ownership to match the new session ID
    if (_pyodideGameSessionId === oldId) _pyodideGameSessionId = data.session_id;
  } else if (!curSession) {
    // No active session at all (first load)
    const s = new SessionState(data.session_id);
    s.gameId = gameShortName(gameId);
    s.status = data.state || 'NOT_FINISHED';
    s.createdAt = Date.now() / 1000;
    registerSession(data.session_id, s);
  } else {
    // Active session has moves — create a new tab
    saveSessionToState();
    detachSessionView(activeSessionId);
    const s = new SessionState(data.session_id);
    s.gameId = gameShortName(gameId);
    s.status = data.state || 'NOT_FINISHED';
    s.createdAt = Date.now() / 1000;
    sessions.set(data.session_id, s);
    activeSessionId = data.session_id;
    attachSessionView(data.session_id);
    // Re-apply DOM writes on the fresh view
    document.getElementById('emptyState').style.display = 'none';
    canvas.style.display = 'block';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    document.getElementById('reasoningContent').innerHTML =
      '<div class="empty-state" style="height:auto;font-size:12px;">Game started. Press Agent Autoplay to let the agent play, or use the controls to play yourself.</div>';
    renderSessionTabs();
    saveSessionIndex();
  }
  renderSessionTabs();
  saveSessionIndex();
  updatePanelBlur();
  updateGameListLock();

  // Blink the Agent Autoplay button to guide the user
  const autoBtn = document.getElementById('autoPlayBtn');
  if (autoBtn) autoBtn.classList.add('btn-blink');

  // Initialize live scrubber
  initLiveScrubber();
}

function updateUI(data) {
  previousGrid = currentGrid;
  currentState = data;
  currentGrid = data.grid;
  currentChangeMap = data.change_map || null;
  // If viewing historical step via either scrubber, don't render live grid
  const _inObsMode = isObsModeActive();
  const _scrubPaused = _inObsMode ? !_obsScrubLive : !_liveScrubMode;
  if (_scrubPaused) {
    if (!_inObsMode) _liveScrubLiveGrid = data.grid;
  } else if (currentChangeMap && currentChangeMap.change_count > 0 && document.getElementById('showChanges').checked) {
    renderGridWithChanges(data.grid, currentChangeMap);
  } else {
    renderGrid(data.grid);
  }
  if (_inObsMode) obsScrubUpdate();
  else liveScrubUpdate();
  const titleEl = document.getElementById('gameTitle');
  titleEl.textContent = gameShortName(data.game_id) || 'Game';
  // Show "Local" badge when running via Pyodide
  const existingBadge = titleEl.parentElement.querySelector('.pyodide-badge');
  if (existingBadge) existingBadge.remove();
  if (_pyodideGameActive) {
    const badge = document.createElement('span');
    badge.className = 'pyodide-badge';
    badge.style.cssText = 'display:inline-block;background:#4FCC30;color:#000;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:6px;vertical-align:middle;';
    badge.textContent = 'Local';
    titleEl.parentElement.insertBefore(badge, titleEl.nextSibling);
  }
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = data.state; statusEl.className = 'status status-' + data.state;
  document.getElementById('levelInfo').textContent = `Level ${data.levels_completed}/${data.win_levels}`;
  const ci = currentChangeMap?.change_count > 0 ? ` | ${currentChangeMap.change_count} cells` : '';
  document.getElementById('stepCounter').textContent = `Step ${stepCount}${ci}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// ACTIONS
// ═══════════════════════════════════════════════════════════════════════════

function showNoChangeIfSame(prevGrid, newGrid) {
  const el = document.getElementById('noChangeMsg');
  if (prevGrid && JSON.stringify(newGrid) === prevGrid) {
    el.textContent = 'no state change';
    el.className = 'no-change-flash';
    el.style.display = '';
    setTimeout(() => { el.style.display = 'none'; }, 2000);
  } else {
    el.style.display = 'none';
  }
}

function toggleHumanLock() {
  humanLocked = !humanLocked;
  const ctrl = document.getElementById('controls');
  const btn = document.getElementById('interveneBtn');
  if (humanLocked) {
    ctrl.classList.add('locked');
    btn.classList.remove('active');
    btn.innerHTML = '&#128274; Intervene as Human';
  } else {
    ctrl.classList.remove('locked');
    btn.classList.add('active');
    btn.innerHTML = '&#128275; Controls Unlocked';
  }
}

function lockHumanControls() {
  humanLocked = true;
  const ctrl = document.getElementById('controls');
  const btn = document.getElementById('interveneBtn');
  if (ctrl) ctrl.classList.add('locked');
  if (btn) { btn.classList.remove('active'); btn.innerHTML = '&#128274; Intervene as Human'; }
}

function lockSettings() {
  // Grey out settings controls but keep the scaffold diagram visible (it shows live call status)
  const body = document.getElementById('settingsBody');
  if (body) { body.style.opacity = '0.5'; body.style.pointerEvents = 'none'; }
  const scaffSelect = document.getElementById('scaffoldingSelect');
  if (scaffSelect) scaffSelect.disabled = true;
  const sidebar = document.getElementById('gameSidebar');
  if (sidebar) sidebar.classList.add('locked');
}

function unlockSettings() {
  const body = document.getElementById('settingsBody');
  if (body) { body.style.opacity = ''; body.style.pointerEvents = ''; }
  const scaffSelect = document.getElementById('scaffoldingSelect');
  if (scaffSelect) scaffSelect.disabled = false;
  updateGameListLock();  // re-evaluate — may stay locked if session in progress
}

function logHumanAction(actionId, actionData, changeMap, turnId) {
  const content = document.getElementById('reasoningContent');
  if (content.querySelector('.empty-state')) content.innerHTML = '';
  const entry = document.createElement('div');
  entry.className = 'reasoning-entry';
  if (turnId) entry.setAttribute('data-turn-id', turnId);
  const ci = changeMap?.change_count > 0 ? ` | ${changeMap.change_count} cells changed` : '';
  const coordStr = actionData?.x !== undefined ? ` at (${actionData.x}, ${actionData.y})` : '';
  entry.innerHTML = `
    <button class="branch-btn" onclick="branchFromStep(${stepCount})" title="Branch from step ${stepCount}">&#8627; branch</button>
    <div class="step-label" style="color:var(--yellow);">Step ${stepCount} — Human</div>
    <div class="action-rec" style="color:var(--yellow);">\u2192 Action ${actionId} (${ACTION_NAMES[actionId] || '?'})${coordStr}${ci}</div>`;
  content.appendChild(entry);
  annotateCoordRefs(entry);
  scrollReasoningToBottom();
}

async function doAction(actionId, isClick) {
  if (humanLocked) return;
  if (!sessionId) return;
  if (isClick || actionId === 6) {
    action6Mode = true; canvas.style.cursor = 'crosshair'; canvas.title = 'Click grid for ACTION6';
    return;
  }
  // Save undo snapshot
  turnCounter++;
  const currentTurnId = turnCounter;
  undoStack.push({
    grid: currentState.grid ? currentState.grid.map(r => [...r]) : [],
    state: currentState.state,
    levels_completed: currentState.levels_completed,
    stepCount: stepCount,
    turnId: currentTurnId,
  });
  stepCount++;
  const prevGrid = currentState.grid ? JSON.stringify(currentState.grid) : null;
  const data = await gameStep(sessionId, actionId, {}, {session_cost: sessionTotalTokens.cost});
  if (data.error) { undoStack.pop(); alert(data.error); return; }
  moveHistory.push({ step: stepCount, action: actionId, result_state: data.state, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId });
  recordStepForPersistence(actionId, {}, data.grid, data.change_map, null, null, { levels_completed: data.levels_completed, result_state: data.state });
  logHumanAction(actionId, {}, data.change_map, currentTurnId);
  updateUI(data);
  showNoChangeIfSame(prevGrid, data.grid);
  updateUndoBtn();
  checkSessionEndAndUpload();
}

canvas.addEventListener('click', async (e) => {
  if (humanLocked) return;
  if (!action6Mode || !sessionId) return;
  const rect = canvas.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) * 64 / canvas.clientWidth);
  const y = Math.floor((e.clientY - rect.top) * 64 / canvas.clientHeight);
  // Save undo snapshot
  turnCounter++;
  const currentTurnId = turnCounter;
  undoStack.push({
    grid: currentState.grid ? currentState.grid.map(r => [...r]) : [],
    state: currentState.state,
    levels_completed: currentState.levels_completed,
    stepCount: stepCount,
    turnId: currentTurnId,
  });
  stepCount++;
  const prevGrid = currentState.grid ? JSON.stringify(currentState.grid) : null;
  const data = await gameStep(sessionId, 6, { x, y }, {session_cost: sessionTotalTokens.cost});
  if (data.error) { undoStack.pop(); alert(data.error); return; }
  moveHistory.push({ step: stepCount, action: 6, result_state: data.state, x, y, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId });
  recordStepForPersistence(6, { x, y }, data.grid, data.change_map, null, null, { levels_completed: data.levels_completed, result_state: data.state });
  logHumanAction(6, { x, y }, data.change_map, currentTurnId);
  updateUI(data);
  showNoChangeIfSame(prevGrid, data.grid);
  updateUndoBtn();
  checkSessionEndAndUpload();
  action6Mode = (data.available_actions || []).includes(6);
  if (!action6Mode) canvas.style.cursor = 'default';
});

document.addEventListener('keydown', (e) => {
  if (!sessionId) return;
  if (humanLocked) return;
  // Don't capture keyboard when user is interacting with inputs/settings
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  const map = {'ArrowUp':1,'ArrowDown':2,'ArrowLeft':3,'ArrowRight':4,'w':1,'s':2,'a':3,'d':4,'z':5,'x':7,'r':0};
  if (map[e.key] !== undefined) { e.preventDefault(); doAction(map[e.key]); }
});

// ═══════════════════════════════════════════════════════════════════════════
// WARN BEFORE LEAVING (active session protection)
// ═══════════════════════════════════════════════════════════════════════════

window.addEventListener('beforeunload', (e) => {
  // Warn if any session has steps in progress
  const hasActiveSession = sessionId && stepCount > 0 && currentState.state === 'NOT_FINISHED';
  const hasAutoplay = autoPlaying;
  if (hasActiveSession || hasAutoplay) {
    e.preventDefault();
    // Modern browsers ignore custom text but require returnValue to be set
    e.returnValue = '';
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// REASONING MODE HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function collectObservation(resp, ss) {
  if (!resp || !resp.parsed) return;
  const p = resp.parsed;
  const obs = ss || { llmObservations, stepCount };
  obs.llmObservations.push({
    step: obs.stepCount,
    observation: p.observation || '',
    reasoning: p.reasoning || '',
    action: p.action,
    analysis: p.analysis || '',
  });
}

let _cachedCompactSummary = '';  // LLM-generated summary, cached until refreshed
let _compactSummaryAtCall = 0;   // llmCallCount when summary was last generated
let _compactSummaryAtStep = 0;   // stepCount when summary was last generated (history cutoff)
let _lastCompactPrompt = '';     // last prompt sent to compact model

function _syncCompactToMemoryTab() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) el.value = _cachedCompactSummary;
}
function _syncCompactPromptToMemoryTab() {
  // No-op: compact prompt textarea is now user-editable template
}

function applyCompactEdit() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) {
    _cachedCompactSummary = el.value;
    _compactSummaryAtCall = llmCallCount;
    _compactSummaryAtStep = stepCount;
  }
}

function buildCompactContextFallback() {
  // Heuristic fallback when LLM summary is not available yet.
  if (!llmObservations.length) return '';
  const parts = ['## COMPACT CONTEXT (accumulated knowledge from prior steps)'];
  const actionEffects = {};
  for (const o of llmObservations) {
    if (o.action !== undefined) {
      const aname = ACTION_NAMES[o.action] || `ACTION${o.action}`;
      if (!actionEffects[aname]) actionEffects[aname] = [];
      const reason = (o.reasoning || '').substring(0, 100);
      if (reason && actionEffects[aname].length < 3) actionEffects[aname].push(reason);
    }
  }
  const effectLines = Object.entries(actionEffects)
    .map(([a, reasons]) => `  ${a}: ${reasons[reasons.length - 1]}`)
    .join('\n');
  if (effectLines) parts.push(`Action effects:\n${effectLines}`);
  const last3 = llmObservations.slice(-3);
  if (last3.length) {
    const lines = last3.map(o => `  Step ${o.step}: ${o.observation || ''}`).join('\n');
    parts.push(`Recent observations:\n${lines}`);
  }
  const lastReasoning = llmObservations[llmObservations.length - 1]?.reasoning;
  if (lastReasoning) parts.push(`Current plan: ${lastReasoning}`);
  return parts.join('\n');
}

async function checkInterrupt(expected, grid, changeMap) {
  // Ask a cheap model whether the plan went as expected after a step.
  // Returns true if plan should be interrupted, false otherwise.
  const gridCompact = grid ? grid.map(r => r.join(',')).join('\n') : '';
  const changesText = changeMap ? 'Recent changes: ' + JSON.stringify(changeMap) : '';
  const template = getPrompt('linear.interrupt_prompt');
  const prompt = template
    .replace('{expected}', expected)
    .replace('{grid}', gridCompact)
    .replace('{changes}', changesText);

  const interruptModelSel = document.getElementById('interruptModelSelect')?.value || 'auto';
  const agentModel = getSelectedModel();

  function parseInterruptResult(text) {
    if (!text) return false;
    // Strip markdown fences, JSON wrappers, whitespace
    const clean = text.replace(/```[\s\S]*?```/g, m => m.replace(/```\w*/g, '').trim())
      .replace(/[{}"]/g, '').trim().toUpperCase();
    // Prompt asks "should we interrupt?" — YES means interrupt
    if (clean.startsWith('YES')) return true;
    if (/\bYES\b/.test(clean) && !/\bNO\b/.test(clean)) return true;
    if (/TRUE/.test(clean) && !/FALSE/.test(clean)) return true;
    return false;
  }

  const _intStart = performance.now();
  try {
    let rawResult = '';
    let _intResult;
    {
      // BYOK / Puter.js path
      const model = interruptModelSel === 'same' ? agentModel
        : (interruptModelSel === 'auto' || interruptModelSel === 'auto-fastest') ? null
        : interruptModelSel;
      const info = model ? getModelInfo(model) : getModelInfo(agentModel);
      const useModel = model || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
      if (useModel) {
        const result = await callLLM([{role: 'user', content: prompt}], useModel);
        rawResult = `${result} (${useModel})`;
        _syncInterruptResult(rawResult);
        _intResult = parseInterruptResult(result);
      }
    }
    // Record interrupt timing in timeline
    const _intDur = Math.round(performance.now() - _intStart);
    const _intSs = getActiveSession();
    if (_intSs && _intSs.timelineEvents) {
      _intSs.timelineEvents.push({ type: 'interrupt', agent_type: 'interrupt', duration: _intDur, turn: _intSs.llmCallCount, response_preview: rawResult });
      emitObsEvent(_intSs, { event: 'interrupt', agent: 'interrupt', duration_ms: _intDur, summary: (rawResult || '').slice(0, 200) });
    }
    if (_intResult !== undefined) return _intResult;
  } catch (e) {
    console.warn('Interrupt check failed:', e);
    _syncInterruptResult('ERROR: ' + e.message);
  }
  return false; // default: don't interrupt
}

function _syncInterruptResult(text) {
  const el = document.getElementById('memoryInterruptResult');
  if (el) el.value = text;
}

async function buildCompactContext(ss) {
  // Use LLM to summarize the game history into key takeaways.
  // Falls back to heuristic if LLM call fails.
  // Re-summarize every 5 calls to stay current.
  // ss = SessionState (optional, falls back to globals)
  const _ss = ss || { _cachedCompactSummary, llmCallCount, _compactSummaryAtCall, _compactSummaryAtStep, llmObservations, moveHistory, currentState, _lastCompactPrompt, sessionId: sessionId, stepCount };
  const REFRESH_INTERVAL = 5;
  if (_ss._cachedCompactSummary && (_ss.llmCallCount - _ss._compactSummaryAtCall) < REFRESH_INTERVAL) {
    return _ss._cachedCompactSummary;
  }

  // Build a summary prompt from observations + history
  const obsText = _ss.llmObservations.map(o =>
    `Step ${o.step}: action=${ACTION_NAMES[o.action] || o.action}, obs="${o.observation || ''}", reasoning="${(o.reasoning || '').substring(0, 150)}"`
  ).join('\n');

  const histText = _ss.moveHistory.slice(-20).map(h =>
    `Step ${h.step}: ${ACTION_NAMES[h.action] || '?'} -> ${h.result_state || '?'}`
  ).join('\n');

  const promptTemplate = getPrompt('linear.compact_prompt');

  const summaryPrompt = `${promptTemplate}

OBSERVATIONS FROM GAMEPLAY:
${obsText}

RECENT MOVE HISTORY:
${histText}

Progress: Level ${_ss.currentState.levels_completed || 0}/${_ss.currentState.win_levels || 0}`;

  // Store the prompt for display in Memory tab
  _ss._lastCompactPrompt = summaryPrompt;
  if (!ss) _lastCompactPrompt = summaryPrompt;
  _syncCompactPromptToMemoryTab();

  // Determine compact model
  const compactModelSel = document.getElementById('compactModelSelectTop').value;
  const agentModel = getSelectedModel();
  // 'auto' = cheapest same provider (server decides), 'auto-fastest' = fastest same provider, 'same' = agent model, else specific model
  const compactModel = compactModelSel === 'same' ? agentModel
    : (compactModelSel === 'auto' || compactModelSel === 'auto-fastest') ? null
    : compactModelSel;

  try {
    let summary;
    const _compactStart = performance.now();
    const useCompactModel = compactModel || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
    if (useCompactModel) {
      summary = await callLLM([{role: 'user', content: summaryPrompt}], useCompactModel);
    }
    if (summary) {
      const _compactDur = Math.round(performance.now() - _compactStart);
      const _tlTarget = ss || getActiveSession();
      if (_tlTarget && _tlTarget.timelineEvents) {
        _tlTarget.timelineEvents.push({ type: 'compact', agent_type: 'compact', duration: _compactDur, turn: _ss.llmCallCount, response_preview: (summary || '').slice(0, 500) });
        emitObsEvent(_tlTarget, { event: 'compact', agent: 'compact', duration_ms: _compactDur, summary: (summary || '').slice(0, 200) });
      }
      _ss._cachedCompactSummary = `## COMPACT CONTEXT (LLM-summarized game knowledge)\n${summary}`;
      _ss._compactSummaryAtCall = _ss.llmCallCount;
      _ss._compactSummaryAtStep = _ss.stepCount;
      if (!ss) { _cachedCompactSummary = _ss._cachedCompactSummary; _compactSummaryAtCall = _ss._compactSummaryAtCall; _compactSummaryAtStep = _ss._compactSummaryAtStep; }
      _syncCompactToMemoryTab();
      return _ss._cachedCompactSummary;
    }
  } catch (e) {
    console.warn('Compact summary LLM call failed, using fallback:', e);
  }
  const fallback = buildCompactContextFallback();
  if (fallback) {
    _ss._cachedCompactSummary = fallback;
    if (!ss) _cachedCompactSummary = fallback;
    _syncCompactToMemoryTab();
  }
  return fallback;
}

// ── Session event logging ──────────────────────────────────────────────
function logSessionEvent(eventType, stepNum, data = {}) {
  if (!sessionId) return;
  fetchJSON(`/api/sessions/${sessionId}/event`, {
    event_type: eventType,
    step_num: stepNum,
    data: data,
  }).catch(() => {});  // fire and forget
}

async function manualCompact() {
  if (!sessionId || moveHistory.length === 0) return;
  saveSessionToState();  // sync globals → ss
  const ss = getActiveSession();
  const btn = document.getElementById('compactBtn');
  btn.disabled = true;
  btn.textContent = '\u23f3 Compacting...';
  try {
    _cachedCompactSummary = '';  // force refresh
    if (ss) ss._cachedCompactSummary = '';
    const summary = await buildCompactContext(ss);
    if (summary) {
      _cachedCompactSummary = summary;
      if (ss) ss._cachedCompactSummary = summary;
      _syncCompactToMemoryTab();
      _compactSummaryAtCall = llmCallCount;
      _compactSummaryAtStep = stepCount;
      if (ss) { ss._compactSummaryAtCall = llmCallCount; ss._compactSummaryAtStep = stepCount; }
      logSessionEvent('compact', stepCount, { call_count: llmCallCount, history_length: moveHistory.length, trigger: 'manual' });
      const content = document.getElementById('reasoningContent');
      if (content.querySelector('.empty-state')) content.innerHTML = '';
      const entry = document.createElement('div');
      entry.className = 'reasoning-entry';
      entry.innerHTML = `<div class="step-label" style="color:var(--purple);">Context compacted at step ${stepCount} (${llmCallCount} calls)</div>`;
      content.appendChild(entry);
      scrollReasoningToBottom();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '\ud83d\udcdc Compact';
  }
}

function getThinkingLevel() {
  return document.querySelector('input[name="thinkingLevel"]:checked')?.value || 'low';
}
function getToolsMode() {
  return document.querySelector('input[name="toolsMode"]:checked')?.value || 'off';

}

function getPlanningMode() {
  return document.querySelector('input[name="planMode"]:checked')?.value || 'off';
}

function getMaxTokens() {
  return parseInt(document.getElementById('maxTokensLimit')?.value) || 16384;
}
function spinMaxTokens(dir) {
  const el = document.getElementById('maxTokensLimit');
  el.value = Math.max(1024, Math.min(65536, (parseInt(el.value) || 16384) + dir * 1024));
}

function shouldAskAdaptive() {
  // In adaptive mode, ask the LLM if no level progress in last 5 steps
  if (moveHistory.length < 5) return false;
  const last5 = moveHistory.slice(-5);
  const levels = last5.map(h => h.levels ?? 0);
  return new Set(levels).size <= 1;
}
