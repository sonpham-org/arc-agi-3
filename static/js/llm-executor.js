// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12 17:30 EDT
// PURPOSE: Plan execution orchestration (Phase 22 extraction)
// Extracted from llm.js: executePlan(), executeOneAction(), stepOnce()
// These functions coordinate multi-step and single-step game action execution.
// Dependencies: askLLM() (defined in llm.js, loaded after this module)
// SRP/DRY: Plan execution logic separated from LLM orchestration (askLLM)

// ═══════════════════════════════════════════════════════════════════════════
// PART 2: PLAN EXECUTION & ACTION HANDLING
// ═══════════════════════════════════════════════════════════════════════════
// Coordinates multi-step plan execution, single action execution, and state management.
// Functions:
//   executePlan(plan, resp, entry, expected, ss) — execute a multi-step plan from LLM
//   executeOneAction(resp) — execute a single action (non-plan mode)
//   stepOnce() — single-step orchestration: call askLLM, then executePlan
// Called by: stepOnce(), toggleAutoPlay(), truncAutoRetry()
// ═══════════════════════════════════════════════════════════════════════════

async function executePlan(plan, resp, entry, expected, ss) {
  // Execute a multi-step plan, updating UI live
  // ss = SessionState (optional, falls back to globals)
  const _ss = ss || null;
  const _cur = _ss || { sessionId: sessionId, currentState, undoStack, stepCount, turnCounter,
    moveHistory, currentGrid: currentGrid, previousGrid: previousGrid, currentChangeMap,
    autoPlaying, sessionTotalTokens, sessionStepsBuffer, syncStepCounter,
    llmCallCount, _cachedCompactSummary, _compactSummaryAtCall, _compactSummaryAtStep };
  const _planSessionId = _cur.sessionId;
  const isActive = () => activeSessionId === _planSessionId;
  const planSteps = entry ? entry.querySelectorAll('.plan-step') : [];
  let consecutiveNoChange = 0;
  const levelsBefore = _cur.currentState.levels_completed || 0;
  let completed = 0;
  const wasAutoPlaying = _ss ? _ss.autoPlaying : autoPlaying; // snapshot at plan start

  // Assign a turn ID for the entire plan
  _cur.turnCounter++;
  if (!_ss) turnCounter = _cur.turnCounter;
  const currentTurnId = _cur.turnCounter;
  if (entry) entry.setAttribute('data-turn-id', currentTurnId);

  for (let i = 0; i < plan.length; i++) {
    const step = plan[i];
    // Pause check: if user paused mid-plan during autoplay, stop remaining steps immediately
    if (wasAutoPlaying && completed > 0) {
      const nowPaused = _ss ? !_ss.autoPlaying : !autoPlaying;
      if (nowPaused) {
        if (isActive()) { for (let j = i; j < planSteps.length; j++) planSteps[j].className = 'plan-step skipped'; }
        break;
      }
    }
    // For linear/default in step-once mode (not autoplay), only execute 1 step
    const isScaffoldPlan = resp?.scaffolding === 'three_system' || resp?.scaffolding === 'two_system' || resp?.scaffolding === 'rlm' || resp?.scaffolding === 'agent_spawn' || resp?.scaffolding === 'world_model';
    if (!isScaffoldPlan && !_cur.autoPlaying && completed > 0) break;

    // Mark step as executing
    if (isActive() && planSteps[i]) {
      planSteps[i].className = 'plan-step executing';
    }

    // Save undo snapshot
    const prevGrid = _cur.currentState.grid ? JSON.stringify(_cur.currentState.grid) : '';
    _cur.undoStack.push({
      grid: _cur.currentState.grid ? _cur.currentState.grid.map(r => [...r]) : [],
      state: _cur.currentState.state,
      levels_completed: _cur.currentState.levels_completed,
      stepCount: _cur.stepCount,
      turnId: currentTurnId,
    });

    _cur.stepCount++;
    if (!_ss) stepCount = _cur.stepCount;
    const extras = { session_cost: _cur.sessionTotalTokens.cost };
    if (resp?._clientSide) extras.llm_response = (i === 0) ? resp : null;
    const data = await gameStep(_planSessionId, step.action, step.data || {}, extras,
      { grid: _cur.currentState.grid, _ownerSessionId: _ss?.sessionId || activeSessionId });

    // Guard: session closed mid-plan — stop executing further steps
    if (!sessions.has(_planSessionId)) {
      console.log('[executePlan] session closed mid-plan, aborting remaining steps');
      break;
    }

    if (data.error) {
      _cur.undoStack.pop();
      _cur.stepCount--;
      if (!_ss) stepCount = _cur.stepCount;
      if (isActive() && planSteps[i]) planSteps[i].className = 'plan-step failed';
      // Mark remaining as skipped
      if (isActive()) { for (let j = i + 1; j < planSteps.length; j++) planSteps[j].className = 'plan-step skipped'; }
      break;
    }

    // Update session state with new data
    _cur.currentState = data;
    if (_ss) { _ss.currentGrid = data.grid; _ss.currentChangeMap = data.change_map; }
    else { currentState = data; currentGrid = data.grid; currentChangeMap = data.change_map; }

    const _histObs = i === 0 ? (resp?.parsed?.observation || '') : '';
    const _histReason = i === 0 ? (resp?.parsed?.reasoning || '') : '';
    _cur.moveHistory.push({ step: _cur.stepCount, action: step.action, result_state: data.state, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId, observation: _histObs, reasoning: _histReason });
    recordStepForPersistence(step.action, step.data || {}, data.grid, data.change_map, i === 0 ? resp : null, _ss, { levels_completed: data.levels_completed, result_state: data.state });
    if (isActive()) { updateUI(data); updateUndoBtn(); }
    completed++;

    // Mark step as done
    if (isActive() && planSteps[i]) {
      planSteps[i].className = 'plan-step done';
      const btn = planSteps[i].querySelector('.action-btn');
      if (btn) { btn.style.background = 'var(--green)'; btn.style.color = '#000'; btn.style.borderColor = 'var(--green)'; }
    }
    // Emit obs act event
    const _obsAgent = resp?.scaffolding === 'three_system' || resp?.scaffolding === 'two_system' ? 'planner' : 'executor';
    emitObsEvent(_ss || getActiveSession(), {
      event: 'act', agent: _obsAgent, action: ACTION_NAMES[step.action] || `A${step.action}`,
      grid: data.grid || null,
    });

    // ── Three-system: record observation and run monitor client-side ──
    if (resp?.scaffolding === 'three_system' || resp?.scaffolding === 'two_system') {
      // Record observation directly into session tsState
      const tsState = _cur._tsState;
      if (tsState) {
        const prevGridArr = prevGrid ? JSON.parse(prevGrid) : [];
        // Compute change_map_text client-side (reuse data from step response)
        const cmText = data.change_map?.change_map_text || '';
        const obs = {
          step: _cur.stepCount, action: step.action,
          grid: data.grid, levels: data.levels_completed || 0,
          state: data.state, change_map_text: cmText,
        };
        tsState.observations.push(obs);
        tsState.snapshots.push(obs);
      }

      // Run monitor check client-side if we have expected outcome and more steps remain
      const stepExpected = step.expected || '';
      if (stepExpected && i < plan.length - 1 && tsState) {
        try {
          const tsSettings = getScaffoldingSettings();
          const monData = await _tsMonitorCheck(
            step, stepExpected, data.change_map,
            { game_id: _cur.currentState.game_id || '', step_num: _cur.stepCount,
              levels_completed: data.levels_completed || 0, prev_levels: levelsBefore,
              win_levels: data.win_levels || 0, state: data.state },
            tsSettings, tsState
          );
          // Show monitor verdict inline on plan step
          if (isActive() && planSteps[i]) {
            const monDur = monData.duration_ms ? `${(monData.duration_ms/1000).toFixed(1)}s` : '';
            const monColor = monData.verdict === 'REPLAN' ? 'var(--yellow)' : 'var(--dim)';
            const monLabel = document.createElement('div');
            monLabel.style.cssText = `font-size:9px;color:${monColor};margin-top:1px;`;
            monLabel.textContent = `${monData.verdict}${monData.reason ? ': ' + monData.reason : ''} ${monDur}`;
            planSteps[i].appendChild(monLabel);
          }
          if (monData.verdict === 'REPLAN') {
            if (isActive()) {
              for (let j = i + 1; j < plan.length; j++)
                if (planSteps[j]) planSteps[j].className = 'plan-step interrupted';
              const content = document.getElementById('reasoningContent');
              const intEntry = document.createElement('div');
              intEntry.className = 'reasoning-entry';
              intEntry.innerHTML = `<div class="step-label" style="color:var(--yellow);">Monitor: REPLAN at step ${i + 1}/${plan.length} — ${esc(monData.reason || '')}</div>`;
              content.appendChild(intEntry);
            }
            break;
          }
        } catch (e) { console.warn('[3sys] monitor check failed:', e); }
      }
    }

    // Surprise detection: game ended
    if (data.state !== 'NOT_FINISHED') {
      if (isActive()) { for (let j = i + 1; j < planSteps.length; j++) planSteps[j].className = 'plan-step skipped'; }
      checkSessionEndAndUpload();
      break;
    }

    // Surprise detection: grid not changing
    const newGrid = JSON.stringify(data.grid || []);
    if (newGrid === prevGrid) {
      consecutiveNoChange++;
      if (consecutiveNoChange >= 3) {
        if (isActive()) { for (let j = i + 1; j < planSteps.length; j++) planSteps[j].className = 'plan-step skipped'; }
        break;
      }
    } else {
      consecutiveNoChange = 0;
    }

    // Interrupt model check: ask cheap model if plan is going as expected
    const interruptEnabled = document.getElementById('interruptPlan')?.checked;
    if (interruptEnabled && expected && i < plan.length - 1) {
      if (isActive()) updateScaffoldingNodeState('interrupt', 'waiting');
      const shouldInterrupt = await checkInterrupt(expected, data.grid, data.change_map);
      if (isActive()) updateScaffoldingNodeState('interrupt', 'done');
      if (shouldInterrupt) {
        if (isActive()) {
          for (let j = i + 1; j < planSteps.length; j++)
            planSteps[j].className = 'plan-step interrupted';
          // Add visual indicator in reasoning
          const content = document.getElementById('reasoningContent');
          const intEntry = document.createElement('div');
          intEntry.className = 'reasoning-entry';
          intEntry.innerHTML = `<div class="step-label" style="color:var(--yellow);">⚡ Plan interrupted at step ${i + 1}/${plan.length}: expected "${expected}" not met</div>`;
          content.appendChild(intEntry);
        }
        break;
      }
    }

    // Brief pause for visual feedback
    await new Promise(r => setTimeout(r, 100));
  }

  // Guard: if session closed mid-plan, don't touch UI or globals
  if (!sessions.has(_planSessionId)) {
    return { completed, total: plan.length, interrupted: true };
  }

  // Detect level change and show indicator + auto-compact
  const levelsAfter = _cur.currentState.levels_completed || 0;
  if (levelsAfter > levelsBefore && isActive()) {
    const lvlEntry = document.createElement('div');
    lvlEntry.className = 'reasoning-entry';
    lvlEntry.innerHTML = `<div class="step-label" style="color:var(--green);">\u2b50 Level ${levelsBefore} completed! (${levelsBefore}/${_cur.currentState.win_levels} \u2192 ${levelsAfter}/${_cur.currentState.win_levels})</div>`;
    const content = document.getElementById('reasoningContent');
    content.appendChild(lvlEntry);
    if (document.getElementById('compactOnLevel')?.checked) {
      _cur._cachedCompactSummary = '';
      if (!_ss) _cachedCompactSummary = '';
      const summary = await buildCompactContext(_ss);
      if (summary) {
        _cur._cachedCompactSummary = summary;
        if (!_ss) _cachedCompactSummary = summary;
        _syncCompactToMemoryTab();
        _cur._compactSummaryAtCall = _cur.llmCallCount;
        _cur._compactSummaryAtStep = _cur.stepCount;
        if (!_ss) { _compactSummaryAtCall = _cur._compactSummaryAtCall; _compactSummaryAtStep = _cur._compactSummaryAtStep; }
        logSessionEvent('compact', _cur.stepCount, { trigger: 'level_up', level: levelsAfter });
        const cEntry = document.createElement('div');
        cEntry.className = 'reasoning-entry';
        cEntry.innerHTML = `<div class="step-label" style="color:var(--purple);">Context auto-compacted on level ${levelsAfter}</div>`;
        content.appendChild(cEntry);
      }
    }
  }
  // Update the entry with level info
  if (isActive() && entry) {
    const levelBadge = document.createElement('span');
    levelBadge.className = 'tools-badge';
    levelBadge.style.cssText = levelsAfter > levelsBefore
      ? 'background:#3fb95033;color:var(--green);' : 'background:var(--bg);color:var(--text-dim);';
    levelBadge.textContent = `L${levelsAfter}/${_cur.currentState.win_levels || '?'}`;
    const stepLabel = entry.querySelector('.step-label');
    if (stepLabel) stepLabel.appendChild(levelBadge);
  }

  // Sync session state back to globals if still active
  if (_ss) syncSessionToGlobals(_ss);

  checkSessionEndAndUpload();
  return { completed, total: plan.length, interrupted: completed < plan.length };
}

// ──────────────────────────────────────────────────────────────────────────
// SECTION: Single Action Execution (non-plan mode)
// ──────────────────────────────────────────────────────────────────────────
async function executeOneAction(resp) {
  // Execute a single action from LLM response
  const _actionSessionId = sessionId;
  const p = resp.parsed;
  const levelsBefore = currentState.levels_completed || 0;
  turnCounter++;
  const currentTurnId = turnCounter;
  undoStack.push({
    grid: currentState.grid ? currentState.grid.map(r => [...r]) : [],
    state: currentState.state,
    levels_completed: currentState.levels_completed,
    stepCount: stepCount,
    turnId: currentTurnId,
  });

  stepCount++;
  const singleExtras = { session_cost: sessionTotalTokens.cost };
  if (resp?._clientSide) singleExtras.llm_response = resp;
  const data = await gameStep(_actionSessionId, p.action, p.data || {}, singleExtras);
  // Guard: session changed during step execution
  if (!sessions.has(_actionSessionId)) { console.log('[executeOneAction] session closed, discarding'); return null; }
  if (data.error) { undoStack.pop(); stepCount--; alert(data.error); return null; }
  moveHistory.push({ step: stepCount, action: p.action, result_state: data.state, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId, observation: p.observation || '', reasoning: p.reasoning || '' });
  recordStepForPersistence(p.action, p.data || {}, data.grid, data.change_map, resp, null, { levels_completed: data.levels_completed, result_state: data.state });
  updateUI(data);
  updateUndoBtn();

  // Detect level change
  const levelsAfter = data.levels_completed || 0;
  if (levelsAfter > levelsBefore) {
    const content = document.getElementById('reasoningContent');
    const lvlEntry = document.createElement('div');
    lvlEntry.className = 'reasoning-entry';
    lvlEntry.innerHTML = `<div class="step-label" style="color:var(--green);">\u2b50 Level ${levelsBefore} completed! (${levelsBefore}/${data.win_levels} \u2192 ${levelsAfter}/${data.win_levels})</div>`;
    content.appendChild(lvlEntry);
    if (document.getElementById('compactOnLevel')?.checked) {
      _cachedCompactSummary = '';
      const summary = await buildCompactContext();
      if (summary) {
        _cachedCompactSummary = summary;
        _syncCompactToMemoryTab();
        _compactSummaryAtCall = llmCallCount;
        _compactSummaryAtStep = stepCount;
        logSessionEvent('compact', stepCount, { trigger: 'level_up', level: levelsAfter });
        const cEntry = document.createElement('div');
        cEntry.className = 'reasoning-entry';
        cEntry.innerHTML = `<div class="step-label" style="color:var(--purple);">Context auto-compacted on level ${levelsAfter}</div>`;
        content.appendChild(cEntry);
      }
    }
  }

  checkSessionEndAndUpload();
  return data;
}

// ═══════════════════════════════════════════════════════════════════════════
// PART 3a: SINGLE-STEP EXECUTION
// ═══════════════════════════════════════════════════════════════════════════
// Single-step orchestration: call askLLM, then executePlan for the result.
// Called by: manual step button (stepOnce), retry flow, etc.
// ═══════════════════════════════════════════════════════════════════════════

async function stepOnce() {
  if (!sessionId) { alert('Start a game first'); return; }
  if (currentState.state !== 'NOT_FINISHED') return;
  // Stop blink guide
  const _ab = document.getElementById('autoPlayBtn');
  if (_ab) _ab.classList.remove('btn-blink');

  saveSessionToState();  // sync globals → ss before async pipeline
  const ss = getActiveSession();
  const resp = await askLLM(ss);
  if (!resp || resp.error || resp.truncated || !resp.parsed) return;
  const p = resp.parsed;

  // Agent spawn executes steps inline — skip executePlan
  if (resp._alreadyExecuted) return;

  // Normalize: single action becomes a 1-step plan
  const plan = (p.plan && Array.isArray(p.plan) && p.plan.length > 0)
    ? p.plan
    : (p.action !== undefined && p.action !== null)
      ? [{ action: p.action, data: p.data || {} }]
      : null;
  if (!plan) return;

  const entry = getLastReasoningEntry();
  const expected = resp.parsed.expected || null;
  return await executePlan(plan, resp, entry, expected, ss);
}
