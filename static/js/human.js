// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Play as Human
// ═══════════════════════════════════════════════════════════════════════════

let _humanInited = false;
let _humanGameId = null;       // currently selected game ID
let _humanSessionId = null;    // active game session ID
let _humanStarted = false;     // true once first move made
let _humanRecording = false;   // true when recording a session (Start Session clicked)
let _humanPaused = false;      // true when session is paused
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
let _humanProcessing = false;  // true while a game step is being processed
let _humanAvailableActions = [];
let _humanLevelCount = 0;      // total levels in game
let _humanCurrentLevel = 0;    // currently selected level
let _humanGames = [];          // cached game list
let _humanLevelStats = [];     // per-level stats: [{ level, startStep, endStep, startTime, endTime }]
let _humanLiveMode = false;    // true when playing in live mode
let _humanLiveInterval = null; // interval handle for live mode auto-tick
let _humanLiveFps = 10;        // tick rate for live mode (user-adjustable, default 10)
let _humanGameHasLive = false; // true if current game supports live mode
let _humanLiveHeldAction = 6;  // currently held action in live mode (6 = no-op tick)

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
  if (_humanRecording) return; // locked during recorded session

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
  _humanRecording = false;
  _humanStartTime = null;
  _humanDuration = 0;
  _humanAvailableActions = data.available_actions || [];
  _humanAction6Mode = _humanAvailableActions.includes(6);

  // Check if game supports live mode
  const gameMeta = _humanGames.find(g => g.game_id === gameId || g.game_id.split('-')[0] === gameId.split('-')[0]);
  _humanGameHasLive = (gameMeta?.tags || []).includes('live');
  _humanLiveFps = 10; // default 10 FPS
  const liveBtn = document.getElementById('humanStartLiveBtn');
  const liveFpsWrap = document.getElementById('humanLiveFpsWrap');
  if (liveBtn) liveBtn.style.display = _humanGameHasLive ? '' : 'none';
  if (liveFpsWrap) liveFpsWrap.style.display = _humanGameHasLive ? '' : 'none';
  _humanUpdateFpsLabel();

  // Enable right panel (was greyed out before game selection)
  const rightPanel = document.getElementById('humanRightPanel');
  if (rightPanel) { rightPanel.classList.remove('panel-disabled'); rightPanel.style.pointerEvents = ''; rightPanel.style.opacity = ''; }

  // Refresh comments if that tab is currently active
  if (document.getElementById('humanSubComments')?.style.display !== 'none') loadComments();

  // Show canvas + controls (locked until Start Session)
  _humanPaused = false;
  const c = _humanCanvas();
  c.style.display = 'block';
  document.getElementById('humanEmptyState').style.display = 'none';
  const ctrlEl = document.getElementById('humanControls');
  ctrlEl.style.display = 'flex';
  ctrlEl.classList.add('controls-locked');
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
  if (_humanRecording) return; // can't change level during recorded session

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

async function humanDoAction(actionId, isClick, direct = false) {
  if (!_humanSessionId) return;
  if (!_humanRecording || _humanPaused || _humanProcessing) return;
  if (_humanState.state === 'WIN' || _humanState.state === 'GAME_OVER') return;

  if (!direct && (isClick || actionId === 6)) {
    _humanAction6Mode = true;
    const c = _humanCanvas();
    if (c) c.style.cursor = 'crosshair';
    return;
  }

  _humanStarted = true;
  _humanSetProcessing(true);

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
  if (data.error) { _humanUndoStack.pop(); _humanStepCount--; _humanSetProcessing(false); alert(data.error); return; }

  _humanMoveHistory.push({ step: _humanStepCount, action: actionId, state: data.state, levels: data.levels_completed, grid: data.grid });
  if (_humanRecording) {
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
  }

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

  const prevLevels = _humanState.levels_completed || 0;
  _humanState = data;
  _humanGrid = data.grid;
  _humanTrackLevelTransition(prevLevels, data.levels_completed || 0);
  _humanRenderGrid(data.grid);
  _humanUpdateTopBar();
  if (_humanRecording) _humanUpdateRecorder(actionId, {});
  _humanUpdateUndoBtn();
  _humanSetProcessing(false);
  _humanCheckEnd();
}

async function _humanCanvasClick(e) {
  if (!_humanAction6Mode || !_humanSessionId) return;
  if (!_humanRecording || _humanPaused || _humanProcessing) return;
  if (_humanState.state === 'WIN' || _humanState.state === 'GAME_OVER') return;

  const c = _humanCanvas();
  const rect = c.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) * 64 / c.clientWidth);
  const y = Math.floor((e.clientY - rect.top) * 64 / c.clientHeight);

  _humanStarted = true;
  _humanSetProcessing(true);

  _humanUndoStack.push({
    grid: _humanGrid ? _humanGrid.map(r => [...r]) : [],
    state: _humanState.state,
    levels_completed: _humanState.levels_completed,
    stepCount: _humanStepCount,
  });

  _humanStepCount++;
  const data = await _humanGameStep(6, { x, y });
  if (data.error) { _humanUndoStack.pop(); _humanStepCount--; _humanSetProcessing(false); alert(data.error); return; }

  _humanMoveHistory.push({ step: _humanStepCount, action: 6, x, y, state: data.state, levels: data.levels_completed, grid: data.grid });
  if (_humanRecording) {
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
  }

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

  const prevLevels = _humanState.levels_completed || 0;
  _humanState = data;
  _humanGrid = data.grid;
  _humanAvailableActions = data.available_actions || [];
  _humanAction6Mode = _humanAvailableActions.includes(6);
  if (!_humanAction6Mode) c.style.cursor = 'default';
  _humanTrackLevelTransition(prevLevels, data.levels_completed || 0);
  _humanRenderGrid(data.grid);
  _humanUpdateTopBar();
  if (_humanRecording) _humanUpdateRecorder(6, { x, y });
  _humanUpdateUndoBtn();
  _humanSetProcessing(false);
  _humanCheckEnd();
}

function _setupHumanCanvasClick() {
  const c = _humanCanvas();
  if (c) c.addEventListener('click', _humanCanvasClick);
}

function _setupHumanKeyboard() {
  const keyMap = { 'w': 1, 'ArrowUp': 1, 's': 2, 'ArrowDown': 2, 'a': 3, 'ArrowLeft': 3, 'd': 4, 'ArrowRight': 4, 'r': 0, 'z': 5, 'x': 7, 'c': 7 };

  document.addEventListener('keydown', (e) => {
    // Only handle when human view is visible
    const hv = document.getElementById('humanView');
    if (!hv || hv.style.display === 'none') return;
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    // Enter = Start Session, Shift+Enter = Start Live Session (before recording starts)
    if (e.key === 'Enter' && _humanGameId && !_humanRecording) {
      e.preventDefault();
      if (e.shiftKey && _humanGameHasLive) {
        humanStartLiveSession();
      } else {
        humanStartSession();
      }
      return;
    }

    if (!_humanSessionId || !_humanRecording || _humanPaused) return;

    const action = keyMap[e.key];
    if (action !== undefined) {
      e.preventDefault();
      if (_humanLiveMode) {
        // Live mode: just track held key — the tick loop applies it at FPS rate
        _humanLiveHeldAction = action;
      } else {
        humanDoAction(action, false, true);
      }
    }
    // Ctrl+Z for undo
    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); humanUndo(); }
  });

  document.addEventListener('keyup', (e) => {
    if (!_humanLiveMode) return;
    const action = keyMap[e.key];
    if (action !== undefined && _humanLiveHeldAction === action) {
      _humanLiveHeldAction = 6; // release → back to no-op tick
    }
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
  _humanRecording = true;
  _humanPaused = false;
  _humanStarted = true;
  _humanStartTime = Date.now();
  _humanStepCount = 0;
  _humanMoveHistory = [];
  _humanUndoStack = [];
  _humanStepsBuffer = [];

  // Unlock controls (were locked before session start)
  document.getElementById('humanControls')?.classList.remove('controls-locked');

  // Grey out game sidebar
  const sidebar = document.getElementById('humanSidebar');
  sidebar.querySelector('#humanSidebarGames').style.display = 'none';
  sidebar.querySelector('#humanSidebarRecorder').style.display = '';

  // Grey out level cards
  document.querySelectorAll('.human-level-card').forEach(c => {
    c.style.pointerEvents = 'none';
    c.style.opacity = '0.5';
  });

  // Swap transport buttons: hide Start, show Pause + Finish
  const startBtn = document.getElementById('humanStartSessionBtn');
  const pauseBtn = document.getElementById('humanPauseBtn');
  const finishBtn = document.getElementById('humanFinishSessionBtn');
  if (startBtn) startBtn.style.display = 'none';
  const liveBtn = document.getElementById('humanStartLiveBtn');
  if (liveBtn) liveBtn.style.display = 'none';
  if (pauseBtn) { pauseBtn.style.display = ''; pauseBtn.textContent = 'Pause'; pauseBtn.classList.remove('btn-primary'); }
  if (finishBtn) finishBtn.style.display = '';

  // Initialize per-level stats
  _humanLevelStats = [{ level: 0, startStep: 0, endStep: null, startTime: Date.now(), endTime: null }];

  // Clear any previous end-game overlay
  const endOverlay = document.getElementById('humanEndOverlay');
  if (endOverlay) endOverlay.style.display = 'none';

  // Start timer
  _humanTimerInterval = setInterval(_humanUpdateTimer, 100);
  _humanUpdateRecorder(null, null); // initial render
}

function _humanUnlockPlay() {
  _humanRecording = false;
  _humanPaused = false;
  _humanStarted = false;
  _humanStartTime = null;
  if (_humanTimerInterval) { clearInterval(_humanTimerInterval); _humanTimerInterval = null; }

  // Lock controls again
  document.getElementById('humanControls')?.classList.add('controls-locked');

  // Show game sidebar
  const sidebar = document.getElementById('humanSidebar');
  sidebar.querySelector('#humanSidebarGames').style.display = '';
  sidebar.querySelector('#humanSidebarRecorder').style.display = 'none';

  // Unlock level cards
  document.querySelectorAll('.human-level-card').forEach(c => {
    c.style.pointerEvents = '';
    c.style.opacity = '';
  });

  // Swap transport buttons: show Start, hide Pause + Finish
  const startBtn = document.getElementById('humanStartSessionBtn');
  const pauseBtn = document.getElementById('humanPauseBtn');
  const finishBtn = document.getElementById('humanFinishSessionBtn');
  if (startBtn) startBtn.style.display = '';
  const liveBtn = document.getElementById('humanStartLiveBtn');
  if (liveBtn) liveBtn.style.display = _humanGameHasLive ? '' : 'none';
  if (pauseBtn) pauseBtn.style.display = 'none';
  if (finishBtn) finishBtn.style.display = 'none';
  _humanStopLive();
  _humanLiveMode = false;
}

// ── Processing Lock (blocks input while game step is running) ────────────

function _humanSetProcessing(on) {
  _humanProcessing = on;
  // In live mode, never gray out buttons — actions are registered at interval
  if (_humanLiveMode) return;
  const ctrl = document.getElementById('humanControls');
  const canvas = _humanCanvas();
  if (on) {
    if (ctrl) ctrl.classList.add('controls-locked');
    if (canvas) canvas.style.cursor = 'wait';
    document.body.style.cursor = 'wait';
  } else {
    // Only unlock if not paused
    if (ctrl && !_humanPaused) ctrl.classList.remove('controls-locked');
    if (canvas) canvas.style.cursor = _humanAction6Mode ? 'crosshair' : 'default';
    document.body.style.cursor = '';
  }
}

// ── Pause / Resume ───────────────────────────────────────────────────────

function humanTogglePause() {
  if (!_humanRecording) return;
  _humanPaused = !_humanPaused;
  const btn = document.getElementById('humanPauseBtn');
  const ctrl = document.getElementById('humanControls');
  const canvas = _humanCanvas();
  const levelGrid = document.getElementById('humanLevelGrid');
  const topBar = document.getElementById('humanTopBar');
  if (_humanPaused) {
    // Freeze timer, lock controls, black out canvas + hide info
    if (_humanTimerInterval) { clearInterval(_humanTimerInterval); _humanTimerInterval = null; }
    _humanDuration = (Date.now() - _humanStartTime) / 1000;
    if (btn) { btn.textContent = 'Resume'; btn.classList.add('btn-primary'); }
    if (ctrl) ctrl.classList.add('controls-locked');
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#555';
      ctx.font = '24px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('PAUSED', canvas.width / 2, canvas.height / 2);
    }
    // Hide level thumbnails and top bar info to prevent peeking
    if (levelGrid) levelGrid.classList.add('paused-hidden');
    if (topBar) topBar.classList.add('paused-hidden');
    // Pause live mode tick
    _humanStopLive();
  } else {
    // Resume timer from accumulated duration, unlock controls, restore canvas
    _humanStartTime = Date.now() - _humanDuration * 1000;
    _humanTimerInterval = setInterval(_humanUpdateTimer, 100);
    // Resume live mode tick
    if (_humanLiveMode && !_humanLiveInterval) {
      const tickMs = Math.max(33, Math.round(1000 / _humanLiveFps));
      _humanLiveInterval = setInterval(_humanLiveTick, tickMs);
    }
    if (btn) { btn.textContent = 'Pause'; btn.classList.remove('btn-primary'); }
    if (ctrl) ctrl.classList.remove('controls-locked');
    if (_humanGrid) _humanRenderGrid(_humanGrid);
    // Restore level thumbnails and top bar
    if (levelGrid) levelGrid.classList.remove('paused-hidden');
    if (topBar) topBar.classList.remove('paused-hidden');
  }
}

// ── Timer ───────────────────────────────────────────────────────────────
// _humanUpdateTimer() and _formatDuration() moved to human-render.js

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

// ── New Game / Start Session ─────────────────────────────────────────────

async function humanStartSession() {
  if (!_humanGameId || _humanRecording) return;
  // Reset level to clean state before recording
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
      _humanRenderGrid(state.grid);
      _humanUpdateTopBar();
    }
  } catch (e) {
    console.error('[HumanPlay] Start session reset failed:', e);
  }
  _humanLockPlay();
}

async function humanStartLiveSession() {
  if (!_humanGameId || _humanRecording || !_humanGameHasLive) return;
  // Reset level to clean state before recording
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
      _humanRenderGrid(state.grid);
      _humanUpdateTopBar();
    }
  } catch (e) {
    console.error('[HumanPlay] Start live session reset failed:', e);
  }
  // Show 3-2-1-GO countdown before starting live mode
  await _humanLiveCountdown();
  _humanLiveMode = true;
  _humanLockPlay();
  // Start auto-tick interval (ACTION6 fires as no-op tick when no user action is processing)
  const tickMs = Math.max(33, Math.round(1000 / _humanLiveFps));
  _humanLiveInterval = setInterval(_humanLiveTick, tickMs);
}

function _humanLiveCountdown() {
  return new Promise(resolve => {
    const el = document.getElementById('humanCountdown');
    if (!el) { resolve(); return; }
    const label = el.querySelector('span');
    el.style.display = 'flex';
    const seq = ['3', '2', '1', 'GO'];
    let i = 0;
    label.textContent = seq[0];
    const timer = setInterval(() => {
      i++;
      if (i < seq.length) {
        label.textContent = seq[i];
      } else {
        clearInterval(timer);
        el.style.display = 'none';
        resolve();
      }
    }, 700);
  });
}

function _humanLiveTick() {
  if (!_humanRecording || _humanPaused || _humanProcessing) return;
  if (_humanState.state === 'WIN' || _humanState.state === 'GAME_OVER') {
    _humanStopLive();
    return;
  }
  // Fire whatever action is currently held (or ACTION6 no-op if nothing held)
  humanDoAction(_humanLiveHeldAction, false, true);
}

function _humanStopLive() {
  if (_humanLiveInterval) {
    clearInterval(_humanLiveInterval);
    _humanLiveInterval = null;
  }
  _humanLiveHeldAction = 6;
}

function humanSetLiveFps(val) {
  _humanLiveFps = parseInt(val) || 10;
  _humanUpdateFpsLabel();
  // If already running live, restart interval at new rate
  if (_humanLiveMode && _humanLiveInterval) {
    clearInterval(_humanLiveInterval);
    const tickMs = Math.max(33, Math.round(1000 / _humanLiveFps));
    _humanLiveInterval = setInterval(_humanLiveTick, tickMs);
  }
}

function _humanUpdateFpsLabel() {
  const label = document.getElementById('humanFpsLabel');
  if (label) label.textContent = _humanLiveFps + ' FPS';
  const slider = document.getElementById('humanFpsSlider');
  if (slider) slider.value = _humanLiveFps;
}

function humanFinishSession() {
  if (_humanRecording) _humanSaveSession();
  humanNewGame();
}

function humanNewGame() {
  if (_humanRecording) {
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
  _humanLevelStats = [];
  _humanStopLive();
  _humanLiveMode = false;

  // Reset UI
  const endOverlay = document.getElementById('humanEndOverlay');
  if (endOverlay) endOverlay.style.display = 'none';
  const confetti = document.getElementById('humanConfettiHost');
  if (confetti) confetti.innerHTML = '';
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

  // Grey out right panel again
  const rightPanel = document.getElementById('humanRightPanel');
  if (rightPanel) { rightPanel.classList.add('panel-disabled'); rightPanel.style.pointerEvents = 'none'; rightPanel.style.opacity = '0.4'; }
}

// ── Rendering ───────────────────────────────────────────────────────────
// Moved to human-render.js
// - _humanRenderGrid()
// - _humanUpdateTopBar()
// - _humanUpdateLevelCards()
// - _humanUpdateRecorder()

// ── Level Stats Tracking ─────────────────────────────────────────────────

function _humanTrackLevelTransition(prevLevels, newLevels) {
  if (newLevels > prevLevels && _humanLevelStats.length > 0) {
    // Close out the current level
    const cur = _humanLevelStats[_humanLevelStats.length - 1];
    cur.endStep = _humanStepCount;
    cur.endTime = Date.now();
    // Start the next level
    _humanLevelStats.push({ level: newLevels, startStep: _humanStepCount, endStep: null, startTime: Date.now(), endTime: null });
  }
  // Update the live results view
  _humanRenderLevelResults();
}

// _humanRenderLevelResults() moved to human-render.js

// ── Session End ─────────────────────────────────────────────────────────

function _humanCheckEnd() {
  const st = _humanState.state;
  if (st === 'WIN' || st === 'GAME_OVER') {
    // Stop timer (only relevant when recording)
    if (_humanTimerInterval) { clearInterval(_humanTimerInterval); _humanTimerInterval = null; }
    _humanUpdateTimer(); // final update

    // Close out the final level stats
    if (_humanLevelStats.length > 0) {
      const cur = _humanLevelStats[_humanLevelStats.length - 1];
      if (cur.endStep === null) {
        cur.endStep = _humanStepCount;
        cur.endTime = Date.now();
      }
    }
    _humanRenderLevelResults();

    // Show result
    const statusEl = document.getElementById('humanGameStatus');
    statusEl.textContent = st === 'WIN' ? 'WIN' : 'GAME OVER';
    statusEl.className = 'status status-' + st;

    // Show end-game overlay below canvas
    const overlay = document.getElementById('humanEndOverlay');
    if (overlay) {
      if (st === 'WIN') {
        overlay.textContent = 'YOU WIN!';
        overlay.className = 'human-end-overlay human-end-win';
      } else {
        overlay.textContent = 'GAME OVER';
        overlay.className = 'human-end-overlay human-end-gameover';
      }
      overlay.style.display = 'block';
    }

    // Stop live mode on game end
    _humanStopLive();

    // Confetti on win
    if (st === 'WIN') _humanFireConfetti();

    // Save session only if recording
    if (_humanRecording) _humanSaveSession();

    // Refresh game results
    setTimeout(() => _loadHumanGameResults(), 500);
  }
}

// ── Confetti ─────────────────────────────────────────────────────────────
// _humanFireConfetti() moved to human-render.js

// ── Persistence ─────────────────────────────────────────────────────────

function _humanSaveSession() {
  const payload = _humanBuildPayload();
  if (!payload) return;

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
  _humanUploadPayload(payload);
}

function _humanUploadPayload(payload) {
  fetch('/api/sessions/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function _humanBuildPayload() {
  if (!_humanSessionId || !_humanGameId || _humanStepsBuffer.length < 1) return null;
  return {
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
      live_mode: _humanLiveMode,
      live_fps: _humanLiveMode ? _humanLiveFps : null,
    },
    steps: _humanStepsBuffer,
  };
}

// Auto-upload on page close / tab close
window.addEventListener('beforeunload', () => {
  if (_humanRecording && _humanStepsBuffer.length > 0) {
    const payload = _humanBuildPayload();
    if (payload) {
      navigator.sendBeacon('/api/sessions/import',
        new Blob([JSON.stringify(payload)], { type: 'application/json' }));
    }
  }
});

// ── Game Results ────────────────────────────────────────────────────────

async function _loadHumanGameResults() {
  const body = document.getElementById('humanResultsBody');
  if (!body) return;

  // During an active recording, show live per-level stats instead
  if (_humanRecording && _humanLevelStats.length > 0) {
    _humanRenderLevelResults();
    return;
  }

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
// SOCIAL FEATURES — Moved to human-social.js
// ═══════════════════════════════════════════════════════════════════════════
// Includes:
// - Comments system: loadComments(), _renderComment(), submitComment(), voteComment()
// - Contributors page: loadContributors()
// - Feedback page: loadFeedback(), submitFeedback()
