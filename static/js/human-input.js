// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Input Handling
// ═══════════════════════════════════════════════════════════════════════════
// Extracted from human.js — handles canvas clicks and keyboard events

// ── Canvas Click Handler ────────────────────────────────────────────────

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
      _humanLiveHeldAction = 6; // release → back to no-op tick
    }
  });
}
