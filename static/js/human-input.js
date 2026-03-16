// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Input Handling
// ═══════════════════════════════════════════════════════════════════════════
// Extracted from human.js — handles canvas clicks and keyboard events

// ── Canvas Click Handler ────────────────────────────────────────────────

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

// ── Keyboard Handler ────────────────────────────────────────────────────

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
      _humanLiveHeldAction = _humanLiveIdleAction; // release → back to idle tick
    }
  });
}
