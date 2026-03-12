// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Game Logic (Actions, Steps, Undo, Level Tracking)
// ═══════════════════════════════════════════════════════════════════════════

// ── Game Actions ────────────────────────────────────────────────────────────

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

// ── Undo ────────────────────────────────────────────────────────────────────

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

// ── Level Tracking ──────────────────────────────────────────────────────────

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

// ── Session End Detection ───────────────────────────────────────────────────

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
    if (_humanLiveMode) _humanStopLive();
  }
}

