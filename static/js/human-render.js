// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Rendering & Visual Updates
// ═══════════════════════════════════════════════════════════════════════════
// Extracted from human.js (Phase 16 refactor)
// Provides: grid rendering, UI updates, visual feedback

// ── Thumbnail & Grid Rendering ─────────────────────────────────────────────

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

// ── Top Bar & Info Updates ─────────────────────────────────────────────────

function _humanUpdateTopBar() {
  const status = _humanState.state || 'NOT_FINISHED';
  const statusEl = document.getElementById('humanGameStatus');
  statusEl.textContent = status === 'NOT_FINISHED' ? 'IN PROGRESS' : status.replace(/_/g, ' ');
  statusEl.className = 'status status-' + status;

  const levels = _humanState.levels_completed || 0;
  const total = _humanState.win_levels || _humanLevelCount || '?';
  document.getElementById('humanLevelInfo').textContent = `Level ${levels}/${total}`;
  document.getElementById('humanStepCounter').textContent = `Step ${_humanStepCount}`;

  // Update level card highlighting to reflect current progress
  _humanUpdateLevelCards();
}

function _humanUpdateLevelCards() {
  const levelsCompleted = _humanState.levels_completed || 0;
  document.querySelectorAll('.human-level-card').forEach((card, i) => {
    card.classList.remove('active', 'completed');
    if (i < levelsCompleted) {
      card.classList.add('completed');
    } else if (i === levelsCompleted) {
      card.classList.add('active');
    }
  });
}

// ── Session Recorder Display ───────────────────────────────────────────────

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

// ── Results Display ────────────────────────────────────────────────────────

function _humanRenderLevelResults() {
  const body = document.getElementById('humanResultsBody');
  if (!body || !_humanRecording) return;

  if (_humanLevelStats.length === 0) {
    body.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Start playing to see per-level stats.</div>';
    return;
  }

  let html = '<table class="human-results-table"><thead><tr><th>Level</th><th>Steps</th><th>Time</th><th>Status</th></tr></thead><tbody>';
  for (const ls of _humanLevelStats) {
    const steps = (ls.endStep !== null ? ls.endStep : _humanStepCount) - ls.startStep;
    const elapsed = ((ls.endTime !== null ? ls.endTime : Date.now()) - ls.startTime) / 1000;
    const done = ls.endStep !== null;
    const statusClass = done ? 'result-win' : '';
    const statusText = done ? 'Cleared' : 'In Progress';
    html += `<tr>
      <td>Level ${ls.level + 1}</td>
      <td>${steps}</td>
      <td>${_formatDuration(elapsed)}</td>
      <td class="${statusClass}">${statusText}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  body.innerHTML = html;
}

// ── Timer & Duration Formatting ────────────────────────────────────────────

function _humanUpdateTimer() {
  if (!_humanRecording || !_humanStartTime) return;
  if (_humanPaused) {
    _humanDuration = (Date.now() - _humanStartTime) / 1000;
  } else {
    const elapsed = (Date.now() - _humanStartTime) / 1000;
    _humanDuration = elapsed;
  }
  const timer = document.getElementById('humanTimer');
  if (timer) timer.textContent = _formatDuration(_humanDuration);
}

function _formatDuration(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── Confetti Animation ─────────────────────────────────────────────────────

function _humanFireConfetti() {
  const container = document.getElementById('humanConfettiHost');
  if (!container) return;
  container.innerHTML = '';
  const colors = ['#ff6b6b', '#ffd93d', '#6bcb77', '#4d96ff', '#ff6fff', '#ff9f43', '#54a0ff', '#f368e0'];
  const count = 80;
  for (let i = 0; i < count; i++) {
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    piece.style.left = Math.random() * 100 + '%';
    piece.style.background = colors[Math.floor(Math.random() * colors.length)];
    piece.style.animationDelay = (Math.random() * 0.8) + 's';
    piece.style.animationDuration = (1.5 + Math.random() * 1.5) + 's';
    // Randomize horizontal drift
    piece.style.setProperty('--drift', (Math.random() * 200 - 100) + 'px');
    container.appendChild(piece);
  }
  // Clean up after animation
  setTimeout(() => { container.innerHTML = ''; }, 4000);
}
