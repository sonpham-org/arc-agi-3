// ═══════════════════════════════════════════════════════════════════════════
// SESSION REPLAY + LIVE SCRUBBER — Replay and scrubbing logic
// ═══════════════════════════════════════════════════════════════════════════
//
// This module handles session replay and live scrubber UI:
// - loadSessionHistory() — fetch and render server sessions
// - loadReplay(), showReplayStep(), replayPrev(), replayNext(), closeReplay()
// - initLiveScrubber(), liveScrubUpdate(), liveScrubShow(), etc.
// - _renderGridPreview() — grid preview utility
//
// Dependencies:
// - renderGrid(), currentGrid, currentChangeMap, canvas, ctx, COLORS (from ui.js)
// - fetchJSON() (from ui.js)
// - gameShortName(), moveHistory (from state/ui.js)
// - switchTopTab(), switchSubTab() (from llm.js)
// - renderRestoredReasoning() (from session-persistence.js)
// - getLocalSessions(), getLocalSessionData(), formatDuration() (from session-storage.js)
// - replayData (from session-storage.js)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// LIVE SCRUBBER STATE
// ═══════════════════════════════════════════════════════════════════════════

// _liveScrubMode, _liveScrubViewIdx, _liveScrubLiveGrid declared in state.js

async function loadSessionHistory() {
  const list = document.getElementById('historyList');
  try {
    let sessions = [];
    // Always fetch from server DB
    try {
      const data = await fetchJSON('/api/sessions');
      const serverSessions = data.sessions || [];
      // Merge with localStorage sessions (online mode), dedup by id
      const byId = {};
      for (const s of serverSessions) byId[s.id] = s;
      if (MODE === 'prod') {
        for (const s of getLocalSessions()) {
          if (!byId[s.id]) byId[s.id] = s;
        }
      }
      sessions = Object.values(byId);
      sessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    } catch (e) {
      // Fallback to localStorage only
      sessions = MODE === 'prod' ? getLocalSessions() : [];
    }
    if (!sessions.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No sessions yet. Play a game!</div>';
      return;
    }
    list.innerHTML = '';
    sessions = sessions.filter(s => (s.steps || 0) >= 5);
    if (!sessions.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No sessions yet. Play a game!</div>';
      return;
    }
    for (const s of sessions) {
      const div = document.createElement('div');
      const isBranch = !!s.parent_session_id;
      div.className = 'history-item' + (isBranch ? ' branched' : '');
      const date = new Date((s.created_at || 0) * 1000).toLocaleString();
      const resultClass = `h-result-${s.result || 'NOT_FINISHED'}`;
      const branchLabel = isBranch
        ? `<span class="branch-indicator">&#8627; from step ${s.branch_at_step}</span>`
        : '';
      div.innerHTML = `
        ${branchLabel}
        <span class="h-game">${gameShortName(s.game_id)}</span>
        <span class="h-result ${resultClass}">${s.result || '?'}</span>
        <span class="h-meta">${s.steps || 0} steps | ${s.model || '?'} | $${(s.total_cost || 0).toFixed(4)}${s.duration ? ` | ${formatDuration(s.duration)}` : ''}</span>
        <span class="h-meta">${date}</span>
`;
      div.style.cursor = 'pointer';
      div.onclick = () => window.open(`/share?id=${s.id}`, '_blank');
      // Replay button (in-app)
      const replayBtn = document.createElement('button');
      replayBtn.className = 'btn';
      replayBtn.style.cssText = 'padding:2px 8px;font-size:10px;margin-left:6px;background:var(--surface2);border:1px solid var(--border);color:var(--text);';
      replayBtn.textContent = '\u25b6 Replay';
      replayBtn.onclick = (e) => { e.stopPropagation(); loadReplay(s.id); };
      div.appendChild(replayBtn);
      if (s.result === 'NOT_FINISHED') {
        const resumeBtn = document.createElement('button');
        resumeBtn.className = 'btn btn-primary';
        resumeBtn.style.cssText = 'padding:2px 8px;font-size:10px;margin-left:6px;';
        resumeBtn.textContent = '\u25b6 Resume';
        resumeBtn.onclick = (e) => { e.stopPropagation(); resumeSession(s.id); };
        div.appendChild(resumeBtn);
      }
      list.appendChild(div);
    }
  } catch (e) {
    list.innerHTML =
      `<div class="empty-state" style="height:auto;font-size:12px;">Error loading sessions: ${e.message}</div>`;
  }
}

async function loadReplay(sid) {
  try {
    let data;
    if (MODE === 'prod') {
      data = getLocalSessionData(sid);
      if (!data) {
        data = await fetchJSON(`/api/sessions/${sid}`);
        if (data.error) { alert('Session not found locally or on server.'); return; }
      }
    } else {
      data = await fetchJSON(`/api/sessions/${sid}`);
      if (data.error) { alert(data.error); return; }
    }
    replayData = data;

    // Show the replay bar in the canvas area
    const bar = document.getElementById('replayBar');
    bar.style.display = 'block';
    document.getElementById('transportBar').style.display = 'none';
    hideLiveScrubber();

    const scrubber = document.getElementById('replayScrubber');
    const totalSteps = data.steps?.length || 0;
    scrubber.max = Math.max(totalSteps - 1, 0);
    scrubber.value = 0;
    document.getElementById('replayInfo').textContent =
      `Replay: ${gameShortName(data.session.game_id)} — Step 0 / ${totalSteps}`;

    // Render full reasoning in the Reasoning tab (same format as live/resumed sessions)
    const sess = data.session || {};
    const resultLabel = sess.result || 'REPLAY';
    renderRestoredReasoning(data.steps || [],
      `Replay: ${gameShortName(sess.game_id) || '?'} — ${totalSteps} steps — ${resultLabel}`, 'var(--accent)', { replay: true });
    // Switch to Agent tab so user sees the reasoning
    switchTopTab('agent');
    switchSubTab('reasoning');

    // Hide the old History-tab reasoning panel (we use the main Reasoning tab now)
    document.getElementById('replayReasoningPanel').style.display = 'none';

    scrubber.oninput = () => showReplayStep(parseInt(scrubber.value));
    if (totalSteps > 0) showReplayStep(0);
  } catch (e) { alert('Error loading replay: ' + e.message); }
}

function showReplayStep(stepIdx) {
  if (!replayData || !replayData.steps) return;
  const total = replayData.steps.length;
  const info = document.getElementById('replayInfo');
  info.textContent = `Replay: ${gameShortName(replayData.session.game_id)} — Step ${stepIdx + 1} / ${total}`;

  document.getElementById('replayScrubber').value = stepIdx;

  if (stepIdx >= 0 && stepIdx < total) {
    const step = replayData.steps[stepIdx];
    if (step.grid) {
      renderGrid(step.grid);
      document.getElementById('emptyState').style.display = 'none';
      canvas.style.display = 'block';
    }

    // Highlight the matching reasoning entry and plan step in Reasoning tab
    const content = document.getElementById('reasoningContent');
    // Reset all highlights
    content.querySelectorAll('.reasoning-entry').forEach(e => {
      e.style.outline = '';
      e.style.outlineOffset = '';
    });
    content.querySelectorAll('.plan-step .action-btn').forEach(btn => {
      btn.style.background = '';
      btn.style.color = '';
      btn.style.borderColor = '';
    });
    // Find and highlight the active entry + plan step
    const entries = content.querySelectorAll('.reasoning-entry[data-step-nums]');
    entries.forEach(e => {
      const stepNums = (e.dataset.stepNums || '').split(',').map(Number);
      const idx = stepNums.indexOf(step.step_num);
      if (idx !== -1) {
        e.style.outline = '2px solid var(--accent)';
        e.style.outlineOffset = '-2px';
        e.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        // Light up this and all previous plan steps (progressive fill)
        const planBtns = e.querySelectorAll('.plan-step .action-btn');
        for (let pi = 0; pi <= idx && pi < planBtns.length; pi++) {
          planBtns[pi].style.background = 'var(--green)';
          planBtns[pi].style.color = '#000';
          planBtns[pi].style.borderColor = 'var(--green)';
        }
      }
    });
  }
}

function replayPrev() {
  if (!replayData) return;
  const scrubber = document.getElementById('replayScrubber');
  const v = Math.max(0, parseInt(scrubber.value) - 1);
  showReplayStep(v);
}

function replayNext() {
  if (!replayData) return;
  const scrubber = document.getElementById('replayScrubber');
  const v = Math.min(replayData.steps.length - 1, parseInt(scrubber.value) + 1);
  showReplayStep(v);
}

function closeReplay() {
  replayData = null;
  document.getElementById('replayBar').style.display = 'none';
  document.getElementById('replayReasoningPanel').style.display = 'none';
  // Restore game controls if a session is active
  if (sessionId) {
    document.getElementById('transportBar').style.display = 'block';
    if (currentGrid) renderGrid(currentGrid);
    initLiveScrubber();
    liveScrubUpdate();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// LIVE SCRUBBER
// ═══════════════════════════════════════════════════════════════════════════

function initLiveScrubber() {
  const bar = document.getElementById('liveScrubberBar');
  if (!bar) return;
  // Live scrubber is only used for internal state tracking, not shown in settings view
  bar.style.display = 'none';
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  _liveScrubLiveGrid = null;
  const slider = document.getElementById('liveScrubSlider');
  slider.value = 0; slider.max = 0;
  document.getElementById('liveScrubLabel').textContent = 'Step 0 / 0';
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-live';
  dot.innerHTML = '&#9679; LIVE';
  document.getElementById('liveScrubBanner').style.display = 'none';

  // Bind slider events
  slider.oninput = function() {
    const idx = parseInt(this.value);
    if (idx >= moveHistory.length) {
      liveScrubReturnToLive();
    } else {
      liveScrubShow(idx);
    }
  };
}

function liveScrubUpdate() {
  const bar = document.getElementById('liveScrubberBar');
  if (!bar || bar.style.display === 'none') return;
  const slider = document.getElementById('liveScrubSlider');
  const total = moveHistory.length;
  slider.max = Math.max(0, total - 1);
  if (_liveScrubMode) {
    slider.value = Math.max(0, total - 1);
    document.getElementById('liveScrubLabel').textContent = `Step ${total} / ${total}`;
  } else {
    const viewStep = _liveScrubViewIdx + 1;
    document.getElementById('liveScrubLabel').textContent = `Step ${viewStep} / ${total}`;
  }
}

function liveScrubShow(idx) {
  if (idx < 0 || idx >= moveHistory.length) return;
  _liveScrubViewIdx = idx;
  // Stash the live grid on first historical view
  if (_liveScrubMode) {
    _liveScrubLiveGrid = currentGrid;
  }
  _liveScrubMode = false;
  const entry = moveHistory[idx];
  if (entry && entry.grid) {
    _renderGridPreview(entry.grid);
  }
  // Update slider position
  const slider = document.getElementById('liveScrubSlider');
  slider.value = idx;
  // Update label
  document.getElementById('liveScrubLabel').textContent = `Step ${idx + 1} / ${moveHistory.length}`;
  // Show banner
  const banner = document.getElementById('liveScrubBanner');
  banner.style.display = 'flex';
  document.getElementById('liveScrubBannerText').textContent = `Viewing step ${idx + 1}`;
  // Update dot
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-historical';
  dot.innerHTML = '&#9679; PAUSED';
}

function liveScrubReturnToLive() {
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  // Restore the live grid
  if (_liveScrubLiveGrid) {
    renderGrid(_liveScrubLiveGrid);
    _liveScrubLiveGrid = null;
  } else if (currentGrid) {
    renderGrid(currentGrid);
  }
  // Hide banner
  document.getElementById('liveScrubBanner').style.display = 'none';
  // Update dot
  const dot = document.getElementById('liveScrubDot');
  dot.className = 'live-scrubber-dot is-live';
  dot.innerHTML = '&#9679; LIVE';
  // Snap slider to end
  liveScrubUpdate();
}

function liveScrubToStep(stepNum) {
  // Map step number to moveHistory index
  const idx = moveHistory.findIndex(m => m.step === stepNum);
  if (idx >= 0) {
    liveScrubShow(idx);
  }
}

function hideLiveScrubber() {
  const bar = document.getElementById('liveScrubberBar');
  if (bar) bar.style.display = 'none';
  _liveScrubMode = true;
  _liveScrubViewIdx = -1;
  _liveScrubLiveGrid = null;
}

function _renderGridPreview(grid) {
  if (!grid || !grid.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  canvas.width = w * scale;
  canvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
  // Note: does NOT set currentGrid — that stays at the live value
}

// turnstileVerified declared in session-persistence.js
