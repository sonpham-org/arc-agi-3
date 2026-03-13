// ═══════════════════════════════════════════════════════════════════════════
// SESSION VIEWS — HISTORY (Session resumption & branching)
// ═══════════════════════════════════════════════════════════════════════════
//
// This module handles session history tracking and resumption:
// - resumeSession(sid): Load a saved session from server (with localStorage fallback)
// - branchFromStep(stepNum): Create a new branch from the current live session
// - branchHere(): Create a new branch from a replayed session at current scrubber position
//
// Dependencies:
// - fetchJSON(), updateUI(), updateUndoBtn(), switchTopTab(), logSessionEvent() (from ui.js)
// - currentUser, currentState, currentGrid, sessionId, moveHistory, stepCount, sessionStepsBuffer, etc. (from state.js)
// - sessions, activeSessionId, getActiveSession(), registerSession(), saveSessionToState(), renderSessionTabs(), saveSessionIndex(), updateEmptyAppState(), updatePanelBlur(), updateGameListLock() (from ui.js)
// - SessionState (from state.js)
// - getLocalSessionData() (from session-storage.js)
// - renderRestoredReasoning() (from session-persistence.js)
// - closeReplay(), replayData, document.getElementById('replayScrubber') (from session-replay.js)
// - closeReplay(), enterObsMode() (from observatory.js)
// - _getModelPricing(), switchScaffolding(), loadModels(), SCAFFOLDING_SCHEMAS, activeScaffoldingType (from tokens.js / scaffolding.js)
// - initLiveScrubber(), liveScrubUpdate() (from ui.js)
// - _rebuildTimelineFromSteps() (from session.js)
// - autoUploadSession() (from session-sync.js)
// ═══════════════════════════════════════════════════════════════════════════

async function resumeSession(sid) {
  // Guard: don't overwrite an active session that already has a loaded grid
  if (sessionId === sid && currentGrid && stepCount > 0) return;

  // Track whether session was already registered — used to detect close-during-resume
  const _wasRegistered = sessions.has(sid);

  try {
    let data = await fetchJSON('/api/sessions/resume', { session_id: sid });
    if (data.error) {
      // Server doesn't have this session — try localStorage fallback
      const localData = getLocalSessionData(sid);
      if (localData && localData.steps && localData.steps.length > 0) {
        console.log(`[resumeSession] Server 404, restoring ${sid} from localStorage (${localData.steps.length} steps)`);
        // Re-upload to server so future resumes work
        const reimportPayload = { session: localData.session, steps: localData.steps };
        fetch('/api/sessions/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reimportPayload),
        }).catch(() => {});
        // Retry resume after re-import
        await new Promise(r => setTimeout(r, 500));
        data = await fetchJSON('/api/sessions/resume', { session_id: sid });
        if (data.error) {
          // Still failed — start fresh with the game from localStorage
          console.warn(`[resumeSession] Re-import failed for ${sid}, starting fresh`);
          const gameId = localData.session?.game_id;
          if (gameId) {
            // Remove the dead session and let the user start fresh
            sessions.delete(sid);
            saveSessionIndex();
            renderSessionTabs();
          }
          return;
        }
      } else {
        // No local data either — session is truly gone
        console.warn(`[resumeSession] Session ${sid} not found in server or localStorage`);
        sessions.delete(sid);
        saveSessionIndex();
        renderSessionTabs();
        updateEmptyAppState();
        return;
      }
    }

    // Guard: if session was registered before the await but got closed while server was replaying, abort
    if (_wasRegistered && !sessions.has(sid)) {
      console.log('[resumeSession] Session was closed during server replay, aborting.');
      return;
    }

    // Set up client state for live play
    sessionId = sid;
    stepCount = data.resumed_step_count || 0;
    autoPlaying = false;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    undoStack = [];
    syncStepCounter = 0;

    // Rebuild moveHistory, sessionStepsBuffer, llmObservations, and token totals from step history
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      // Rebuild turnIds: LLM leader starts new turn, followers inherit, human gets own turn
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++; // human action
      }
      const _turnId = turnCounter;
      // Rebuild moveHistory (with per-step game stats from server replay)
      moveHistory.push({
        step: s.step_num,
        action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null,
        change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      // Rebuild sessionStepsBuffer
      sessionStepsBuffer.push({
        step_num: s.step_num,
        action: s.action,
        data: s.data || {},
        grid: s.grid || null,
        change_map: s.change_map || null,
        llm_response: s.llm_response || null,
        timestamp: s.timestamp || 0,
      });
      // Rebuild llmObservations from LLM responses
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num,
          observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '',
          action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      // Rebuild sessionTotalTokens from LLM usage
      if (llm && llm.usage) {
        const inputTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outputTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inputTok;
        sessionTotalTokens.output += outputTok;
        const model = llm.model || data.model || '';
        const prices = _getModelPricing(model);
        if (prices) {
          sessionTotalTokens.cost += (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
        }
      }
    }

    // If no token data from llm_response (e.g. Agent Spawn), rebuild from timeline events
    if (sessionTotalTokens.input === 0 && sessionTotalTokens.output === 0 && data.timeline) {
      for (const ev of data.timeline) {
        if (ev.input_tokens) sessionTotalTokens.input += ev.input_tokens;
        if (ev.output_tokens) sessionTotalTokens.output += ev.output_tokens;
        if (ev.cost) sessionTotalTokens.cost += ev.cost;
      }
      // Count LLM calls from timeline: each sub_act and orch_think/delegate is a call
      if (llmCallCount === 0) {
        for (const ev of data.timeline) {
          if (['as_sub_act', 'as_sub_tool', 'as_sub_report', 'as_orch_think', 'as_orch_delegate'].includes(ev.type)) {
            llmCallCount++;
          }
        }
      }
    }
    sessionStartTime = Date.now() / 1000;

    // Close replay if open
    closeReplay();

    updateUI(data);
    updateUndoBtn();

    // Show controls
    document.getElementById('emptyState').style.display = 'none';
    canvas.style.display = 'block';
    document.getElementById('transportBar').style.display = 'block';
    initLiveScrubber();
    liveScrubUpdate();

    // Highlight the matching game card in the sidebar
    if (data.game_id) {
      document.querySelectorAll('.game-card').forEach(c => {
        c.classList.toggle('active', c.dataset.gameId === data.game_id);
      });
    }

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    // Switch to Agent tab
    switchTopTab('agent');

    // Log the resume event
    logSessionEvent('resumed', stepCount, {});

    // ── Restore settings from session history ──
    // Find model + scaffolding from LLM responses or timeline events
    let _resumeModel = data.model || '';
    let _resumeScaffolding = 'linear';
    for (let i = steps.length - 1; i >= 0; i--) {
      const llm = steps[i].llm_response;
      if (llm) {
        if (llm.model) _resumeModel = llm.model;
        if (llm.scaffolding) _resumeScaffolding = llm.scaffolding;
        break;
      }
    }
    // Switch scaffolding UI to match session's scaffolding (if it's a known type)
    if (SCAFFOLDING_SCHEMAS[_resumeScaffolding] && _resumeScaffolding !== activeScaffoldingType) {
      switchScaffolding(_resumeScaffolding);
    }
    // Set model select to match session's model
    if (_resumeModel) {
      await loadModels();
      const _msel = document.getElementById('modelSelect');
      if (_msel && [..._msel.options].some(o => o.value === _resumeModel)) {
        _msel.value = _resumeModel;
      }
    }

    // ── Multi-session: register resumed session ──
    if (!sessions.has(sid)) {
      const s = new SessionState(sid);
      registerSession(sid, s);
    }
    activeSessionId = sid;

    // Rebuild timelineEvents from step history (or use saved timeline)
    const _tlSs = sessions.get(sid);
    if (_tlSs) {
      _tlSs.timelineEvents = data.timeline || _rebuildTimelineFromSteps(steps);
      // Rebuild obs events from timeline for observatory display
      _tlSs._obsEvents = [];
      const _tl = _tlSs.timelineEvents;
      const _tlStart = _tl.length ? (_tl[0].timestamp || 0) : 0;
      for (const ev of _tl) {
        const agentType = ev.agent_type || ev.current_agent || 'orchestrator';
        const obsEvent = ev.type?.startsWith('as_') ? ev.type.replace('as_', '') : (ev.type || '');
        const obsData = { event: obsEvent, agent: agentType.toLowerCase() };
        if (ev.timestamp) {
          const d = new Date(ev.timestamp);
          obsData.t = d.toISOString();
          obsData.elapsed_s = (ev.timestamp - _tlStart) / 1000;
        }
        if (ev.model) obsData.model = ev.model;
        if (ev.duration_ms) obsData.duration_ms = ev.duration_ms;
        if (ev.input_tokens) obsData.input_tokens = ev.input_tokens;
        if (ev.output_tokens) obsData.output_tokens = ev.output_tokens;
        if (ev.cost) obsData.cost = ev.cost;
        if (ev.task || ev.summary) obsData.summary = ev.task || ev.summary;
        if (ev.reasoning) obsData.reasoning = ev.reasoning;
        if (ev.response) obsData.response = ev.response;
        if (ev.findings != null) obsData.findings = ev.findings;
        if (ev.hypotheses != null) obsData.hypotheses = ev.hypotheses;
        if (ev.action_name) obsData.action_name = ev.action_name;
        if (ev.tool_name) obsData.tool_name = ev.tool_name;
        if (ev.step_num != null) obsData.step_num = ev.step_num;
        _tlSs._obsEvents.push(obsData);
      }
      // Enrich moveHistory from timeline events (for legacy sessions where llm_response was NULL)
      if (moveHistory.length && _tl.length) {
        const tlByStep = {};
        for (const ev of _tl) {
          if (ev.step_num != null && (ev.reasoning || ev.action_name || ev.agent_type)) {
            tlByStep[ev.step_num] = ev;
          }
        }
        for (const h of moveHistory) {
          if (!h.observation && !h.reasoning && tlByStep[h.step]) {
            const ev = tlByStep[h.step];
            h.observation = ev.action_name ? `[${ev.agent_type || 'agent'}] ${ev.action_name}` : '';
            h.reasoning = ev.reasoning || '';
          }
        }
        // Also backfill sessionStepsBuffer so renderRestoredReasoning sees LLM groups (not "Human")
        for (const sb of sessionStepsBuffer) {
          if (!sb.llm_response && tlByStep[sb.step_num]) {
            const ev = tlByStep[sb.step_num];
            sb.llm_response = {
              parsed: {
                observation: ev.action_name ? `[${ev.agent_type || 'agent'}] ${ev.action_name}` : '',
                reasoning: ev.reasoning || '',
                action: sb.action,
                data: sb.data || {},
              },
              model: ev.model || _resumeModel || '',
              scaffolding: 'agent_spawn',
              usage: (ev.input_tokens || ev.output_tokens) ? { input_tokens: ev.input_tokens || 0, output_tokens: ev.output_tokens || 0 } : null,
              call_duration_ms: ev.duration_ms || null,
            };
          }
        }
      }
      // Store original settings for branch-on-change detection
      _tlSs._originalSettings = { model: _resumeModel, scaffolding_type: _resumeScaffolding };
      // Compute elapsed time from timeline timestamps (don't tick from now)
      if (_tl.length >= 2) {
        const t0 = _tl[0].timestamp || 0;
        const tN = _tl[_tl.length - 1].timestamp || 0;
        _tlSs._obsElapsedFixed = (tN - t0) / 1000;
      } else {
        _tlSs._obsElapsedFixed = 0;
      }
      // Session was loaded from server, so all steps are already uploaded
      _tlSs._lastUploadedStep = stepCount;
    }

    // Rebuild reasoning panel (after timeline enrichment so Agent Spawn steps show as LLM groups)
    renderRestoredReasoning(sessionStepsBuffer, `Session resumed at step ${stepCount} (${llmCallCount} prior LLM calls, ${sessionTotalTokens.input + sessionTotalTokens.output} tokens restored)`, 'var(--green)');

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();

    // Persist enriched steps back to DB so future resumes don't need re-enrichment
    if (sessionStepsBuffer.some(s => s.llm_response && !steps.find(orig => orig.step_num === s.step_num && orig.llm_response))) {
      autoUploadSession();
    }

    // Enter observability view so user sees the grid + scrubber
    enterObsMode(_tlSs || getActiveSession());
  } catch (e) {
    alert('Resume failed: ' + e.message);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION BRANCHING (client-side)
// ═══════════════════════════════════════════════════════════════════════════

async function branchFromStep(stepNum) {
  // Branch the current live session at a given step number
  if (!sessionId) return;
  if (!confirm(`Branch from step ${stepNum}? This creates a new session from that point.`)) return;
  try {
    const data = await fetchJSON('/api/sessions/branch', {
      parent_session_id: sessionId,
      step_num: stepNum,
    });
    if (data.error) { alert(data.error); return; }

    const parentId = sessionId;
    sessionId = data.session_id;
    stepCount = stepNum;
    undoStack = [];
    syncStepCounter = 0;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    autoPlaying = false;

    // Rebuild state from returned steps (same as resume)
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++;
      }
      const _turnId = turnCounter;
      moveHistory.push({
        step: s.step_num,
        action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null,
        change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      sessionStepsBuffer.push({
        step_num: s.step_num,
        action: s.action,
        data: s.data || {},
        grid: s.grid || null,
        change_map: s.change_map || null,
        llm_response: s.llm_response || null,
        timestamp: s.timestamp || 0,
      });
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num,
          observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '',
          action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      if (llm && llm.usage) {
        const inputTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outputTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inputTok;
        sessionTotalTokens.output += outputTok;
        const model = llm.model || '';
        const prices = _getModelPricing(model);
        if (prices) {
          sessionTotalTokens.cost += (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
        }
      }
    }
    sessionStartTime = Date.now() / 1000;

    updateUI(data);
    updateUndoBtn();

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    logSessionEvent('branch_created', stepNum, { parent_session_id: parentId });
    switchTopTab('agent');

    // Render reasoning trace from parent steps
    renderRestoredReasoning(steps,
      `Branched from step ${stepNum} (${llmCallCount} prior LLM calls, $${sessionTotalTokens.cost.toFixed(3)} cost)`,
      'var(--purple)');

    // ── Multi-session: register branch session ──
    const bs = new SessionState(data.session_id);
    bs.gameId = data.game_id || currentState.game_id || '';
    bs.status = data.state || 'NOT_FINISHED';
    registerSession(data.session_id, bs);

    // Rebuild timelineEvents from step history
    bs.timelineEvents = _rebuildTimelineFromSteps(steps);

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();
  } catch (e) {
    alert('Branch failed: ' + e.message);
  }
}

async function branchHere() {
  if (!replayData || !replayData.session) return;
  const scrubber = document.getElementById('replayScrubber');
  const stepNum = parseInt(scrubber.value);
  const parentId = replayData.session.id;

  try {
    const data = await fetchJSON('/api/sessions/branch', {
      parent_session_id: parentId,
      step_num: stepNum,
    });
    if (data.error) { alert(data.error); return; }

    // Transition from replay to live play
    sessionId = data.session_id;
    stepCount = stepNum;
    undoStack = [];
    syncStepCounter = 0;
    _cachedCompactSummary = '';
    _compactSummaryAtCall = 0;
    _compactSummaryAtStep = 0;
    autoPlaying = false;
    replayData = null;

    // Rebuild state from returned steps
    moveHistory = [];
    sessionStepsBuffer = [];
    llmObservations = [];
    llmCallCount = 0;
    turnCounter = 0;
    sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    const steps = data.steps || [];
    let _rebuildPlanRemaining = 0;
    for (const s of steps) {
      const llm = s.llm_response;
      if (llm && llm.parsed) {
        turnCounter++;
        _rebuildPlanRemaining = ((llm.parsed.plan && Array.isArray(llm.parsed.plan)) ? llm.parsed.plan.length : 1) - 1;
      } else if (_rebuildPlanRemaining > 0) {
        _rebuildPlanRemaining--;
      } else {
        turnCounter++;
      }
      const _turnId = turnCounter;
      moveHistory.push({
        step: s.step_num, action: s.action,
        result_state: s.result_state || 'NOT_FINISHED',
        levels: s.levels_completed || 0,
        grid: s.grid || null, change_map: s.change_map || null,
        turnId: _turnId,
        observation: llm?.parsed?.observation || '',
        reasoning: llm?.parsed?.reasoning || '',
      });
      sessionStepsBuffer.push({
        step_num: s.step_num, action: s.action, data: s.data || {},
        grid: s.grid || null, change_map: s.change_map || null,
        llm_response: s.llm_response || null, timestamp: s.timestamp || 0,
      });
      if (llm && llm.parsed) {
        llmCallCount++;
        llmObservations.push({
          step: s.step_num, observation: llm.parsed.observation || '',
          reasoning: llm.parsed.reasoning || '', action: llm.parsed.action,
          analysis: llm.parsed.analysis || '',
        });
      }
      if (llm && llm.usage) {
        const inTok = llm.usage.input_tokens || llm.usage.prompt_tokens || 0;
        const outTok = llm.usage.output_tokens || llm.usage.completion_tokens || 0;
        sessionTotalTokens.input += inTok;
        sessionTotalTokens.output += outTok;
        const prices = _getModelPricing(llm.model || '');
        if (prices) sessionTotalTokens.cost += (inTok * prices[0] + outTok * prices[1]) / 1_000_000;
      }
    }
    sessionStartTime = Date.now() / 1000;

    // Hide replay bar, show controls
    document.getElementById('replayBar').style.display = 'none';
    document.getElementById('replayReasoningPanel').style.display = 'none';
    document.getElementById('transportBar').style.display = 'block';
    initLiveScrubber();

    updateUI(data);
    updateUndoBtn();

    if ((data.available_actions || []).includes(6)) {
      action6Mode = true;
      canvas.style.cursor = 'crosshair';
    }

    // Log the branch event on the new session
    logSessionEvent('branch_created', stepNum, { parent_session_id: parentId });

    // Switch to Agent tab and render reasoning trace
    switchTopTab('agent');
    renderRestoredReasoning(steps,
      `Branched from replay at step ${stepNum} (${llmCallCount} prior LLM calls)`,
      'var(--purple)');

    // ── Multi-session: register branch session ──
    const bs = new SessionState(data.session_id);
    bs.gameId = data.game_id || '';
    bs.status = data.state || 'NOT_FINISHED';
    registerSession(data.session_id, bs);

    // Rebuild timelineEvents from step history
    bs.timelineEvents = _rebuildTimelineFromSteps(steps);

    saveSessionToState();
    renderSessionTabs();
    saveSessionIndex();
    updatePanelBlur();
    updateGameListLock();
  } catch (e) {
    alert('Branch failed: ' + e.message);
  }
}
