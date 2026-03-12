// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Session Lifecycle
// ═══════════════════════════════════════════════════════════════════════════
// Extracted from human.js — handles session start/finish, live mode, pause, persistence

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

// ── Session Start ────────────────────────────────────────────────────────

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

// ── Live Mode ────────────────────────────────────────────────────────────

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

// ── Session End ──────────────────────────────────────────────────────────

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

// ── Persistence ──────────────────────────────────────────────────────────

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
