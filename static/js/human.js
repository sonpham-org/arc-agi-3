// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Play as Human
// ═══════════════════════════════════════════════════════════════════════════

let _humanInited = false;
let _humanGameId = null;       // currently selected game ID
let _humanSessionId = null;    // active game session ID
let _humanStarted = false;     // true once first move made
let _humanGrid = null;         // current grid state
let _humanState = {};          // current game state from engine
let _humanStepCount = 0;
let _humanMoveHistory = [];
let _humanUndoStack = [];
let _humanStepsBuffer = [];    // for persistence
let _humanStartTime = null;    // when timer started (ms)
let _humanTimerInterval = null;
let _humanDuration = 0;        // accumulated seconds
let _humanAction6Mode = false;
let _humanAvailableActions = [];
let _humanLevelCount = 0;      // total levels in game
let _humanCurrentLevel = 0;    // currently selected level
let _humanGames = [];          // cached game list

const _humanCanvas = () => document.getElementById('humanCanvas');
const _humanCtx = () => _humanCanvas()?.getContext('2d');

// ── Initialization ──────────────────────────────────────────────────────

function initHumanView() {
  if (!_humanInited) {
    _humanInited = true;
    _loadHumanGames();
    _setupHumanCanvasClick();
    _setupHumanKeyboard();
  }
  _loadHumanGameResults();
}

async function _loadHumanGames() {
  try {
    let games = await fetchJSON('/api/games');
    _humanGames = games;
    const el = document.getElementById('humanGameList');
    el.innerHTML = '';
    const foundation = games.filter(g => _ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
    const observatory = games.filter(g => !_ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
    const sortByTitle = (a, b) => ((a.title || a.game_id).localeCompare(b.title || b.game_id));
    foundation.sort(sortByTitle);
    observatory.sort(sortByTitle);
    _renderGameGroup(el, 'ARC Prize Foundation', foundation, g => _humanSelectGame(g.game_id));
    _renderGameGroup(el, 'ARC Observatory', observatory, g => _humanSelectGame(g.game_id));
  } catch (e) {
    document.getElementById('humanGameList').innerHTML = '<div class="empty-state" style="height:auto;">Failed to load games.</div>';
  }
}

// ── Game Selection ──────────────────────────────────────────────────────

async function _humanSelectGame(gameId) {
  if (_humanStarted) return; // locked once play begins

  // Highlight selected game
  document.querySelectorAll('#humanGameList .game-card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('#humanGameList .game-card').forEach(c => {
    if (c.dataset.gameId === gameId) c.classList.add('active');
  });

  _humanGameId = gameId;
  const shortName = gameId.split('-')[0].toUpperCase();
  document.getElementById('humanGameTitle').textContent = shortName;
  document.getElementById('humanGameStatus').textContent = '—';
  document.getElementById('humanGameStatus').className = 'status status-NOT_PLAYED';

  // Start game to get level info
  let data;
  if (FEATURES.pyodide_game) {
    try {
      await ensurePyodideGame();
      data = await pyodideStartGame(gameId);
      _pyodideGameActive = true;
      _pyodideGameSessionId = data.session_id;
    } catch (err) {
      alert('Game engine failed: ' + err.message);
      return;
    }
  } else {
    _pyodideGameActive = false;
    data = await fetchJSON('/api/start', { game_id: gameId });
  }
  if (data.error) { alert(data.error); return; }

  _humanSessionId = data.session_id;
  _humanState = data;
  _humanGrid = data.grid;
  _humanLevelCount = data.win_levels || 10;
  _humanCurrentLevel = 0;
  _humanStepCount = 0;
  _humanMoveHistory = [];
  _humanUndoStack = [];
  _humanStepsBuffer = [];
  _humanStarted = false;
  _humanStartTime = null;
  _humanDuration = 0;
  _humanAvailableActions = data.available_actions || [];
  _humanAction6Mode = _humanAvailableActions.includes(6);

  // Show canvas + controls
  const c = _humanCanvas();
  c.style.display = 'block';
  document.getElementById('humanEmptyState').style.display = 'none';
  document.getElementById('humanControls').style.display = 'flex';
  document.getElementById('humanTransport').style.display = 'block';

  // Render initial state
  _humanRenderGrid(data.grid);
  _humanUpdateTopBar();

  // Build level selector thumbnails
  await _humanBuildLevelSelector();

  // Load game results
  _loadHumanGameResults();
}

// ── Level Selector ──────────────────────────────────────────────────────

async function _humanBuildLevelSelector() {
  const grid = document.getElementById('humanLevelGrid');
  grid.innerHTML = '';

  for (let i = 0; i < _humanLevelCount; i++) {
    const card = document.createElement('div');
    card.className = 'human-level-card' + (i === _humanCurrentLevel ? ' active' : '');
    card.innerHTML = `
      <canvas class="level-thumb" width="128" height="128"></canvas>
      <div class="level-label">Level ${i + 1}</div>`;
    card.onclick = () => _humanJumpToLevel(i);
    grid.appendChild(card);

    // Generate thumbnail by jumping to level, rendering, then jumping back
    try {
      let levelState;
      if (FEATURES.pyodide_game && _pyodideGameActive) {
        levelState = await _sendGameWorkerMsg({ type: 'jump_level', level: i });
      } else {
        // Server mode: use dev jump (won't work without secret, fallback to blank)
        levelState = null;
      }
      if (levelState && levelState.grid) {
        _renderThumbnail(card.querySelector('.level-thumb'), levelState.grid);
      }
    } catch (e) {
      // Thumbnail failed, leave blank
    }
  }

  // Jump back to current level
  if (_humanCurrentLevel !== _humanLevelCount - 1) {
    try {
      if (FEATURES.pyodide_game && _pyodideGameActive) {
        const restored = await _sendGameWorkerMsg({ type: 'jump_level', level: _humanCurrentLevel });
        _humanState = restored;
        _humanGrid = restored.grid;
        _humanRenderGrid(restored.grid);
      }
    } catch {}
  }
}

function _renderThumbnail(thumbCanvas, grid) {
  if (!grid || !grid.length) return;
  const ctx = thumbCanvas.getContext('2d');
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(128 / Math.max(h, w));
  thumbCanvas.width = w * scale;
  thumbCanvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
}

async function _humanJumpToLevel(levelIndex) {
  if (_humanStarted) return; // can't change level once started

  _humanCurrentLevel = levelIndex;

  // Highlight active level
  document.querySelectorAll('.human-level-card').forEach((c, i) => {
    c.classList.toggle('active', i === levelIndex);
  });

  try {
    let state;
    if (FEATURES.pyodide_game && _pyodideGameActive) {
      state = await _sendGameWorkerMsg({ type: 'jump_level', level: levelIndex });
    } else {
      // Server mode fallback — restart and set level
      state = await fetchJSON('/api/start', { game_id: _humanGameId });
      _humanSessionId = state.session_id;
    }
    if (state && !state.error) {
      _humanState = state;
      _humanGrid = state.grid;
      _humanAvailableActions = state.available_actions || [];
      _humanAction6Mode = _humanAvailableActions.includes(6);
      _humanStepCount = 0;
      _humanMoveHistory = [];
      _humanUndoStack = [];
      _humanStepsBuffer = [];
      _humanRenderGrid(state.grid);
      _humanUpdateTopBar();
    }
  } catch (e) {
    console.error('[HumanPlay] Jump level failed:', e);
  }
}

// ── Action Execution ────────────────────────────────────────────────────

async function humanDoAction(actionId, isClick) {
  if (!_humanSessionId) return;
  if (_humanState.state === 'WIN' || _humanState.state === 'GAME_OVER') return;

  if (isClick || actionId === 6) {
    _humanAction6Mode = true;
    const c = _humanCanvas();
    if (c) c.style.cursor = 'crosshair';
    return;
  }

  // First move locks game/level selection
  if (!_humanStarted) _humanLockPlay();

  // Save undo snapshot
  _humanUndoStack.push({
    grid: _humanGrid ? _humanGrid.map(r => [...r]) : [],
    state: _humanState.state,
    levels_completed: _humanState.levels_completed,
    stepCount: _humanStepCount,
  });

  _humanStepCount++;
  const prevGrid = _humanGrid ? JSON.stringify(_humanGrid) : null;
  const data = await _humanGameStep(actionId, {});
  if (data.error) { _humanUndoStack.pop(); _humanStepCount--; alert(data.error); return; }

  _humanMoveHistory.push({ step: _humanStepCount, action: actionId, state: data.state, levels: data.levels_completed, grid: data.grid });
  _humanStepsBuffer.push({
    step_num: _humanStepCount,
    action: actionId,
    data: {},
    grid: data.grid,
    change_map: data.change_map || null,
    llm_response: null,
    timestamp: Date.now() / 1000,
    levels_completed: data.levels_completed ?? 0,
    result_state: data.state || 'NOT_FINISHED',
  });

  // Animate intermediate frames (e.g. level transitions) on human canvas
  if (data.frames && data.frames.length > 1) {
    const fps = (currentState && currentState.default_fps) || 5;
    const delay = Math.max(50, Math.round(1000 / fps));
    for (let i = 0; i < data.frames.length - 1; i++) {
      _humanRenderGrid(data.frames[i]);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  delete data.frames;

  _humanState = data;
  _humanGrid = data.grid;
  _humanRenderGrid(data.grid);
  _humanUpdateTopBar();
  _humanUpdateRecorder(actionId, {});
  _humanUpdateUndoBtn();
  _humanCheckEnd();
}

async function _humanCanvasClick(e) {
  if (!_humanAction6Mode || !_humanSessionId) return;
  if (_humanState.state === 'WIN' || _humanState.state === 'GAME_OVER') return;

  const c = _humanCanvas();
  const rect = c.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) * 64 / c.clientWidth);
  const y = Math.floor((e.clientY - rect.top) * 64 / c.clientHeight);

  if (!_humanStarted) _humanLockPlay();

  _humanUndoStack.push({
    grid: _humanGrid ? _humanGrid.map(r => [...r]) : [],
    state: _humanState.state,
    levels_completed: _humanState.levels_completed,
    stepCount: _humanStepCount,
  });

  _humanStepCount++;
  const data = await _humanGameStep(6, { x, y });
  if (data.error) { _humanUndoStack.pop(); _humanStepCount--; alert(data.error); return; }

  _humanMoveHistory.push({ step: _humanStepCount, action: 6, x, y, state: data.state, levels: data.levels_completed, grid: data.grid });
  _humanStepsBuffer.push({
    step_num: _humanStepCount,
    action: 6,
    data: { x, y },
    grid: data.grid,
    change_map: data.change_map || null,
    llm_response: null,
    timestamp: Date.now() / 1000,
    levels_completed: data.levels_completed ?? 0,
    result_state: data.state || 'NOT_FINISHED',
  });

  // Animate intermediate frames on human canvas
  if (data.frames && data.frames.length > 1) {
    const fps = (currentState && currentState.default_fps) || 5;
    const delay = Math.max(50, Math.round(1000 / fps));
    for (let i = 0; i < data.frames.length - 1; i++) {
      _humanRenderGrid(data.frames[i]);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  delete data.frames;

  _humanState = data;
  _humanGrid = data.grid;
  _humanAvailableActions = data.available_actions || [];
  _humanAction6Mode = _humanAvailableActions.includes(6);
  if (!_humanAction6Mode) c.style.cursor = 'default';
  _humanRenderGrid(data.grid);
  _humanUpdateTopBar();
  _humanUpdateRecorder(6, { x, y });
  _humanUpdateUndoBtn();
  _humanCheckEnd();
}

function _setupHumanCanvasClick() {
  const c = _humanCanvas();
  if (c) c.addEventListener('click', _humanCanvasClick);
}

function _setupHumanKeyboard() {
  document.addEventListener('keydown', (e) => {
    // Only handle when human view is visible
    const hv = document.getElementById('humanView');
    if (!hv || hv.style.display === 'none') return;
    if (!_humanSessionId) return;
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    const keyMap = { 'w': 1, 'ArrowUp': 1, 's': 2, 'ArrowDown': 2, 'a': 3, 'ArrowLeft': 3, 'd': 4, 'ArrowRight': 4, 'r': 0, 'z': 5, 'x': 7 };
    const action = keyMap[e.key];
    if (action !== undefined) { e.preventDefault(); humanDoAction(action); }
    // Ctrl+Z for undo
    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); humanUndo(); }
  });
}

async function _humanGameStep(actionId, actionData) {
  if (FEATURES.pyodide_game && _pyodideGameActive) {
    try {
      const prevGrid = _humanGrid;
      const state = await pyodideStep(actionId, actionData);
      state.change_map = computeChangeMapJS(prevGrid, state.grid);
      state.session_id = _humanSessionId;
      return state;
    } catch (err) {
      return { error: err.message };
    }
  }
  return fetchJSON('/api/step', { session_id: _humanSessionId, action: actionId, data: actionData || {} });
}

// ── Lock / Unlock ───────────────────────────────────────────────────────

function _humanLockPlay() {
  _humanStarted = true;
  _humanStartTime = Date.now();

  // Grey out game sidebar
  const sidebar = document.getElementById('humanSidebar');
  sidebar.querySelector('#humanSidebarGames').style.display = 'none';
  sidebar.querySelector('#humanSidebarRecorder').style.display = '';

  // Grey out level cards
  document.querySelectorAll('.human-level-card').forEach(c => {
    c.style.pointerEvents = 'none';
    c.style.opacity = '0.5';
  });

  // Start timer
  _humanTimerInterval = setInterval(_humanUpdateTimer, 100);
  _humanUpdateRecorder(null, null); // initial render
}

function _humanUnlockPlay() {
  _humanStarted = false;
  _humanStartTime = null;
  if (_humanTimerInterval) { clearInterval(_humanTimerInterval); _humanTimerInterval = null; }

  // Show game sidebar
  const sidebar = document.getElementById('humanSidebar');
  sidebar.querySelector('#humanSidebarGames').style.display = '';
  sidebar.querySelector('#humanSidebarRecorder').style.display = 'none';

  // Unlock level cards
  document.querySelectorAll('.human-level-card').forEach(c => {
    c.style.pointerEvents = '';
    c.style.opacity = '';
  });
}

// ── Timer ───────────────────────────────────────────────────────────────

function _humanUpdateTimer() {
  if (!_humanStartTime) return;
  _humanDuration = (Date.now() - _humanStartTime) / 1000;
  const el = document.getElementById('humanTimer');
  if (el) el.textContent = _formatDuration(_humanDuration);
}

function _formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ── Undo ────────────────────────────────────────────────────────────────

async function humanUndo() {
  if (!_humanUndoStack.length) return;
  const snap = _humanUndoStack.pop();

  // Restore game state via Pyodide reset + replay, or just use the grid snapshot
  try {
    if (FEATURES.pyodide_game && _pyodideGameActive) {
      // Jump to the level and replay up to the snapshot step count
      const state = await _sendGameWorkerMsg({ type: 'undo' });
      if (state && !state.error) {
        _humanState = state;
        _humanGrid = state.grid;
      } else {
        _humanGrid = snap.grid;
        _humanState = { ...(_humanState || {}), state: snap.state, levels_completed: snap.levels_completed, grid: snap.grid };
      }
    } else {
      _humanGrid = snap.grid;
      _humanState = { ...(_humanState || {}), state: snap.state, levels_completed: snap.levels_completed, grid: snap.grid };
    }
  } catch {
    _humanGrid = snap.grid;
    _humanState = { ...(_humanState || {}), state: snap.state, levels_completed: snap.levels_completed, grid: snap.grid };
  }

  _humanStepCount = snap.stepCount;
  _humanMoveHistory.pop();
  _humanStepsBuffer.pop();
  _humanRenderGrid(_humanGrid);
  _humanUpdateTopBar();
  _humanUpdateUndoBtn();
}

function _humanUpdateUndoBtn() {
  const btn = document.getElementById('humanUndoBtn');
  if (btn) btn.disabled = _humanUndoStack.length === 0;
}

// ── Restart / New Game ──────────────────────────────────────────────────

async function humanRestart() {
  if (!_humanGameId) return;
  _humanUnlockPlay();
  await _humanJumpToLevel(_humanCurrentLevel);
}

async function humanRestartLevel() {
  if (!_humanGameId || !_humanStarted) return;
  if (_humanState.state === 'WIN') return; // already won, no point restarting
  try {
    let state;
    if (FEATURES.pyodide_game && _pyodideGameActive) {
      state = await _sendGameWorkerMsg({ type: 'jump_level', level: _humanCurrentLevel });
    } else {
      state = await fetchJSON('/api/start', { game_id: _humanGameId });
      _humanSessionId = state.session_id;
    }
    if (state && !state.error) {
      _humanState = state;
      _humanGrid = state.grid;
      _humanAvailableActions = state.available_actions || [];
      _humanAction6Mode = _humanAvailableActions.includes(6);
      _humanUndoStack = [];
      _humanRenderGrid(state.grid);
      _humanUpdateTopBar();
    }
  } catch (e) {
    console.error('[HumanPlay] Restart level failed:', e);
  }
}

function humanFinishSession() {
  if (_humanStarted) _humanSaveSession();
  humanNewGame();
}

function humanNewGame() {
  if (_humanStarted) {
    // Save the session first
    _humanSaveSession();
  }
  _humanUnlockPlay();
  _humanSessionId = null;
  _humanGameId = null;
  _humanGrid = null;
  _humanState = {};
  _humanStepCount = 0;
  _humanMoveHistory = [];
  _humanUndoStack = [];
  _humanStepsBuffer = [];
  _humanDuration = 0;
  _humanAction6Mode = false;

  // Reset UI
  const c = _humanCanvas();
  if (c) { c.style.display = 'none'; c.style.cursor = 'default'; }
  document.getElementById('humanEmptyState').style.display = '';
  document.getElementById('humanControls').style.display = 'none';
  document.getElementById('humanTransport').style.display = 'none';
  document.getElementById('humanGameTitle').textContent = 'No game selected';
  document.getElementById('humanGameStatus').textContent = '—';
  document.getElementById('humanGameStatus').className = 'status status-NOT_PLAYED';
  document.getElementById('humanLevelInfo').textContent = '';
  document.getElementById('humanStepCounter').textContent = '';
  document.getElementById('humanLevelGrid').innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Select a game first.</div>';

  // Deselect game in sidebar
  document.querySelectorAll('#humanGameList .game-card').forEach(c => c.classList.remove('active'));
}

// ── Rendering ───────────────────────────────────────────────────────────

function _humanRenderGrid(grid) {
  if (!grid || !grid.length) return;
  _humanGrid = grid;
  const c = _humanCanvas();
  if (!c) return;
  const ctx = c.getContext('2d');
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  c.width = w * scale;
  c.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
}

function _humanUpdateTopBar() {
  const status = _humanState.state || 'NOT_FINISHED';
  const statusEl = document.getElementById('humanGameStatus');
  statusEl.textContent = status === 'NOT_FINISHED' ? 'IN PROGRESS' : status.replace(/_/g, ' ');
  statusEl.className = 'status status-' + status;

  const levels = _humanState.levels_completed || 0;
  const total = _humanState.win_levels || _humanLevelCount || '?';
  document.getElementById('humanLevelInfo').textContent = `Level ${levels}/${total}`;
  document.getElementById('humanStepCounter').textContent = `Step ${_humanStepCount}`;
}

// ── Session Recorder ────────────────────────────────────────────────────

function _humanUpdateRecorder(actionId, actionData) {
  document.getElementById('humanRecSteps').textContent = `${_humanStepCount} steps`;
  document.getElementById('humanRecLevel').textContent = `Level ${(_humanState.levels_completed || 0) + 1}`;

  if (actionId !== null && actionId !== undefined) {
    const log = document.getElementById('humanMoveLog');
    const entry = document.createElement('div');
    entry.className = 'recorder-move-entry';
    const coordStr = actionData?.x !== undefined ? ` (${actionData.x},${actionData.y})` : '';
    entry.textContent = `#${_humanStepCount} ${ACTION_NAMES[actionId] || '?'}${coordStr}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
  }
}

// ── Session End ─────────────────────────────────────────────────────────

function _humanCheckEnd() {
  const st = _humanState.state;
  if (st === 'WIN' || st === 'GAME_OVER') {
    // Stop timer
    if (_humanTimerInterval) { clearInterval(_humanTimerInterval); _humanTimerInterval = null; }
    _humanUpdateTimer(); // final update

    // Show result
    const statusEl = document.getElementById('humanGameStatus');
    statusEl.textContent = st === 'WIN' ? 'WIN' : 'GAME OVER';
    statusEl.className = 'status status-' + st;

    // Save session
    _humanSaveSession();

    // Refresh game results
    setTimeout(() => _loadHumanGameResults(), 500);
  }
}

// ── Persistence ─────────────────────────────────────────────────────────

function _humanSaveSession() {
  if (!_humanSessionId || !_humanGameId) return;
  if (_humanStepsBuffer.length < 1) return;

  const payload = {
    session: {
      id: _humanSessionId,
      game_id: _humanState.game_id || _humanGameId,
      model: '',
      mode: MODE,
      created_at: (_humanStartTime || Date.now()) / 1000,
      result: _humanState.state || 'NOT_FINISHED',
      steps: _humanStepCount,
      levels: _humanState.levels_completed || 0,
      player_type: 'human',
      duration_seconds: _humanDuration,
      user_id: (typeof currentUser !== 'undefined' && currentUser?.id) || null,
    },
    steps: _humanStepsBuffer,
  };

  // Save to localStorage
  try {
    const key = 'arc_human_sessions';
    const idx = JSON.parse(localStorage.getItem(key) || '[]').filter(s => s.id !== _humanSessionId);
    idx.unshift(payload.session);
    if (idx.length > 50) idx.length = 50;
    localStorage.setItem(key, JSON.stringify(idx));
    localStorage.setItem('arc_human_session_data:' + _humanSessionId, JSON.stringify(payload));
  } catch {}

  // Upload to server (fire-and-forget)
  if (_humanStepsBuffer.length >= 5) {
    fetch('/api/sessions/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(() => {});
  }
}

// ── Game Results ────────────────────────────────────────────────────────

async function _loadHumanGameResults() {
  const body = document.getElementById('humanResultsBody');
  if (!body) return;

  // Collect from localStorage
  let localResults = [];
  try {
    const idx = JSON.parse(localStorage.getItem('arc_human_sessions') || '[]');
    localResults = idx.filter(s => s.result === 'WIN' || s.result === 'GAME_OVER');
  } catch {}

  // Fetch from server
  let serverResults = [];
  try {
    const url = _humanGameId ? `/api/game-results?game_id=${encodeURIComponent(_humanGameId)}` : '/api/game-results';
    const resp = await fetchJSON(url);
    serverResults = resp.results || [];
  } catch {}

  // Merge (dedup by id)
  const byId = {};
  for (const r of localResults) byId[r.id] = r;
  for (const r of serverResults) byId[r.id] = r;
  let results = Object.values(byId);

  // Filter by current game if selected
  if (_humanGameId) {
    const gid = _humanGameId;
    results = results.filter(r => r.game_id === gid || r.game_id?.startsWith(gid.split('-')[0]));
  }

  // Sort: most levels first, then fastest time
  results.sort((a, b) => {
    if ((b.levels || 0) !== (a.levels || 0)) return (b.levels || 0) - (a.levels || 0);
    return (a.duration_seconds || 999999) - (b.duration_seconds || 999999);
  });

  if (!results.length) {
    body.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No results yet. Play a game to completion!</div>';
    return;
  }

  let html = `<table class="human-results-table">
    <thead><tr>
      <th>#</th><th>Game</th><th>Result</th><th>Levels</th><th>Steps</th><th>Time</th><th>Date</th>
    </tr></thead><tbody>`;
  results.slice(0, 50).forEach((r, i) => {
    const gameName = (r.game_id || '').split('-')[0].toUpperCase();
    const resultClass = r.result === 'WIN' ? 'result-win' : 'result-lose';
    const dur = r.duration_seconds ? _formatDuration(r.duration_seconds) : '—';
    const date = r.created_at ? new Date(r.created_at * 1000).toLocaleDateString() : '';
    html += `<tr>
      <td>${i + 1}</td>
      <td>${gameName}</td>
      <td class="${resultClass}">${r.result === 'WIN' ? 'WIN' : 'LOSE'}</td>
      <td>${r.levels || 0}</td>
      <td>${r.steps || 0}</td>
      <td>${dur}</td>
      <td>${date}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  body.innerHTML = html;
}

// ── Sub-tab switching ───────────────────────────────────────────────────

function switchHumanSubTab(tab) {
  const bar = document.querySelector('#humanRightPanel .subtab-bar');
  if (!bar) return;
  bar.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  document.getElementById('humanSubLevels').style.display = tab === 'levels' ? '' : 'none';
  document.getElementById('humanSubComments').style.display = tab === 'comments' ? 'flex' : 'none';
  document.getElementById('humanSubResults').style.display = tab === 'results' ? '' : 'none';
  if (tab === 'levels') bar.children[0]?.classList.add('active');
  else if (tab === 'results') bar.children[1]?.classList.add('active');
  else bar.children[2]?.classList.add('active');

  if (tab === 'results') _loadHumanGameResults();
  if (tab === 'comments') loadComments();
}

// ═══════════════════════════════════════════════════════════════════════════
// COMMENTS SYSTEM
// ═══════════════════════════════════════════════════════════════════════════

function _getCommenterId() {
  // Use logged-in user ID, or generate a persistent anonymous ID
  if (typeof currentUser !== 'undefined' && currentUser?.id) return currentUser.id;
  let id = localStorage.getItem('arc_commenter_id');
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('arc_commenter_id', id); }
  return id;
}

function _getCommenterName() {
  if (typeof currentUser !== 'undefined' && currentUser) {
    return currentUser.display_name || currentUser.email?.split('@')[0] || 'User';
  }
  return 'anon-' + _getCommenterId().slice(0, 6);
}

function _timeAgo(ts) {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

async function loadComments() {
  const gameId = _humanGameId;
  const list = document.getElementById('commentsList');
  const compose = document.getElementById('commentCompose');
  if (!gameId) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Select a game to see comments.</div>';
    compose.style.display = 'none';
    return;
  }
  compose.style.display = '';
  list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Loading...</div>';
  try {
    const comments = await fetchJSON('/api/comments/' + encodeURIComponent(gameId.split('-')[0]) + '?voter_id=' + encodeURIComponent(_getCommenterId()));
    if (!comments.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No comments yet. Be the first!</div>';
      return;
    }
    list.innerHTML = comments.map(c => _renderComment(c, 'game')).join('');
  } catch (e) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Failed to load comments.</div>';
  }
}

function _renderComment(c, context) {
  const upClass = c.my_vote === 1 ? ' active-up' : '';
  const downClass = c.my_vote === -1 ? ' active-down' : '';
  const ctx = context ? `,'${context}'` : '';
  return `<div class="comment-card" id="comment-${c.id}">
    <div class="comment-header">
      <span class="comment-author">${_esc(c.author_name)}</span>
      <span class="comment-time">${_timeAgo(c.created_at)}</span>
    </div>
    <div class="comment-body">${_esc(c.body)}</div>
    <div class="comment-actions">
      <button class="vote-btn${upClass}" onclick="voteComment(${c.id}, ${c.my_vote === 1 ? 0 : 1}${ctx})">&#9650; ${c.upvotes || 0}</button>
      <button class="vote-btn${downClass}" onclick="voteComment(${c.id}, ${c.my_vote === -1 ? 0 : -1}${ctx})">&#9660; ${c.downvotes || 0}</button>
    </div>
  </div>`;
}

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function submitComment() {
  const input = document.getElementById('commentInput');
  const body = input.value.trim();
  if (!body || !_humanGameId) return;
  const gameId = _humanGameId.split('-')[0];
  try {
    const resp = await fetch('/api/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: gameId,
        body,
        author_id: _getCommenterId(),
        author_name: _getCommenterName(),
      }),
    });
    if (resp.ok) {
      input.value = '';
      document.getElementById('commentCharCount').textContent = '0 / 2000';
      loadComments();
    }
  } catch (e) { /* ignore */ }
}

async function voteComment(commentId, vote, context) {
  const card = document.getElementById('comment-' + commentId);
  const btns = card?.querySelectorAll('.vote-btn');
  // Optimistic UI: update buttons immediately
  if (btns && btns.length >= 2) {
    const upBtn = btns[0], downBtn = btns[1];
    const wasUp = upBtn.classList.contains('active-up');
    const wasDown = downBtn.classList.contains('active-down');
    upBtn.classList.remove('active-up');
    downBtn.classList.remove('active-down');
    let upCount = parseInt(upBtn.textContent.replace(/[^\d]/g, '')) || 0;
    let downCount = parseInt(downBtn.textContent.replace(/[^\d]/g, '')) || 0;
    if (wasUp) upCount--;
    if (wasDown) downCount--;
    if (vote === 1) { upCount++; upBtn.classList.add('active-up'); }
    if (vote === -1) { downCount++; downBtn.classList.add('active-down'); }
    upBtn.innerHTML = '&#9650; ' + upCount;
    downBtn.innerHTML = '&#9660; ' + downCount;
    // Update onclick to toggle correctly
    upBtn.setAttribute('onclick', `voteComment(${commentId}, ${vote === 1 ? 0 : 1}, '${context || ''}')`);
    downBtn.setAttribute('onclick', `voteComment(${commentId}, ${vote === -1 ? 0 : -1}, '${context || ''}')`);
  }
  try {
    await fetch('/api/comments/' + commentId + '/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voter_id: _getCommenterId(), vote }),
    });
  } catch (e) { /* ignore */ }
}

// Wire up char counter
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('commentInput');
  if (input) input.addEventListener('input', () => {
    document.getElementById('commentCharCount').textContent = input.value.length + ' / 2000';
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// CONTRIBUTORS PAGE
// ═══════════════════════════════════════════════════════════════════════════

let _contribLoaded = false;

function _fmtTime(secs) {
  if (!secs) return '-';
  if (secs < 60) return Math.round(secs) + 's';
  if (secs < 3600) return Math.round(secs / 60) + 'm';
  return (secs / 3600).toFixed(1) + 'h';
}

async function loadContributors() {
  if (_contribLoaded) return;
  try {
    const data = await fetchJSON('/api/contributors');
    // Human players
    const hBody = document.getElementById('contribHumans');
    if (data.human_players?.length) {
      hBody.innerHTML = data.human_players.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.uid === 'anon' ? 'Anonymous' : r.uid.slice(0, 8))}</td>
        <td>${r.session_count}</td><td>${r.games_played}</td>
        <td>${r.total_steps}</td><td>${_fmtTime(r.total_time)}</td>
      </tr>`).join('');
    } else {
      hBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    // Commenters
    const cBody = document.getElementById('contribCommenters');
    if (data.commenters?.length) {
      cBody.innerHTML = data.commenters.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.author_name)}</td>
        <td>${r.comment_count}</td><td>${r.total_upvotes || 0}</td>
      </tr>`).join('');
    } else {
      cBody.innerHTML = '<tr><td colspan="4" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    // AI contributors
    const aBody = document.getElementById('contribAI');
    if (data.ai_contributors?.length) {
      aBody.innerHTML = data.ai_contributors.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.uid === 'anon' ? 'Anonymous' : r.uid.slice(0, 8))}</td>
        <td>${r.session_count}</td><td>${r.games_played}</td>
        <td>${r.total_steps}</td><td>${_esc(r.model || '-')}</td>
      </tr>`).join('');
    } else {
      aBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    _contribLoaded = true;
  } catch (e) {
    console.error('Failed to load contributors', e);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// FEEDBACK PAGE (reuses comments API with game_id = '_feedback')
// ═══════════════════════════════════════════════════════════════════════════

let _feedbackLoaded = false;

async function loadFeedback() {
  const list = document.getElementById('feedbackList');
  list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Loading...</div>';
  try {
    const comments = await fetchJSON('/api/comments/_feedback?voter_id=' + encodeURIComponent(_getCommenterId()));
    if (!comments.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No feedback yet. Be the first!</div>';
    } else {
      list.innerHTML = comments.map(c => _renderComment(c, 'feedback')).join('');
    }
  } catch (e) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Failed to load feedback.</div>';
  }
}

async function submitFeedback() {
  const input = document.getElementById('feedbackInput');
  const body = input.value.trim();
  if (!body) return;
  try {
    const resp = await fetch('/api/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: '_feedback',
        body,
        author_id: _getCommenterId(),
        author_name: _getCommenterName(),
      }),
    });
    if (resp.ok) {
      input.value = '';
      document.getElementById('feedbackCharCount').textContent = '0 / 2000';
      loadFeedback();
    }
  } catch (e) { /* ignore */ }
}

// Wire up feedback char counter
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('feedbackInput');
  if (input) input.addEventListener('input', () => {
    document.getElementById('feedbackCharCount').textContent = input.value.length + ' / 2000';
  });
});
