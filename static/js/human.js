// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Play as Human (Coordinator & Initialization)
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
// MODULAR COMPONENTS — Imported via separate scripts:
// ═══════════════════════════════════════════════════════════════════════════
// - human-social.js: Comments, contributors, feedback
// - human-render.js: Canvas rendering, UI updates, timer, confetti
// - human-input.js: Canvas click, keyboard input handlers
// - human-session.js: Session lifecycle, pause, live mode
// - human-game.js: Game actions, steps, undo, level tracking, persistence
