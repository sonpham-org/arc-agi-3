// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: LLM call orchestration for ARC-AGI-3 web UI. Handles screenshot capture,
//   autoplay loop (single-agent, planning, RLM, three-system, agent-spawn scaffoldings),
//   plan execution with monitor/interrupt checks, tool use (Python REPL via Pyodide),
//   compact context generation, and reasoning panel rendering. Coordinates between
//   scaffolding-*.js modules, ui.js, state.js, and session.js. Modified in Phases 1 & 3
//   to extract formatting utils and token helpers to separate modules.
// SRP/DRY check: Pass — formatting in utils/formatting.js, tokens in utils/tokens.js,
//   scaffolding logic split into scaffolding-*.js in Phase 5
// ═══════════════════════════════════════════════════════════════════════════
// LLM
// ═══════════════════════════════════════════════════════════════════════════

// Configuration getters: extracted to llm-config.js
// getCanvasScreenshotB64(), getInputSettings(), getScaffoldingSettings()
// These are loaded from llm-config.js before this file

// estimateTokens, TOKEN_PRICES — defined in utils/tokens.js (loaded before llm.js)

let sessionTotalTokens = { input: 0, output: 0, cost: 0 };

// ── Timeline helpers ──────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════
// TIMELINE & REASONING: Extracted to separate modules (Phase 12)
// ═══════════════════════════════════════════════════════════════════════════
// Timeline functions extracted to llm-timeline.js:
//   _rebuildTimelineFromSteps(), renderTimelineTree(), renderTimeline(),
//   _tlEsc(), _tlFormatCost(), _tlCallTypeLabel(), _tlCssClass(),
//   _tlBuildDetail(), _tlToggleDetail(), _updateAsTransform(),
//   renderToolCallsHtml() and related SVG/pan/zoom helpers
// Reasoning/logging functions extracted to llm-reasoning.js:
//   scrollReasoningToBottom(), copyReasoningLog(), _flashCopyBtn(),
//   copyTimelineLogs(), getLastReasoningEntry()
// These modules are loaded BEFORE llm.js in index.html (dependency order)

// ═══════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════
// PART 1: ORCHESTRATION & REQUEST HANDLING
// ═══════════════════════════════════════════════════════════════════════════
// Core LLM request orchestration: model routing, prompt building, response parsing.
// Functions:
//   askLLM(ss) — main entry point for LLM calls
//     - Handles all scaffolding types: RLM, 3-system, 2-system, agent-spawn, linear
//     - Context compression, token estimation, history trimming
//     - Parse retries, fallback action generation
//     - Response validation and tool extraction
// Called by: stepOnce(), toggleAutoPlay(), truncAutoRetry()
// Dependencies:
//   - buildCompactContext() from ui.js
//   - askLLMRlm(), askLLMThreeSystem(), askLLMAgentSpawn() from scaffolding-*.js
//   - executeToolBlocks(), gameStep() from engine.js
//   - parseClientLLMResponse() from utils/json-parsing.js
// ═══════════════════════════════════════════════════════════════════════════

async function askLLM(ss) {
  // ss = SessionState to operate on (optional, falls back to globals for backward compat)
  const _ss = ss || null;
  const _cur = _ss || { currentState, llmCallCount, moveHistory, stepCount, currentChangeMap,
    sessionId: sessionId, sessionTotalTokens, _cachedCompactSummary, _compactSummaryAtCall,
    _compactSummaryAtStep, _lastCompactPrompt, autoPlaying, llmObservations };

  if (!_cur.currentState.grid) return;
  // Capture session at call time — used to discard stale responses
  const _callSessionId = _cur.sessionId;
  const _callSession = _ss || getActiveSession();
  const isActive = () => activeSessionId === _callSessionId;

  // Use snapshot settings for background (detached) sessions, live DOM for active
  const _snap = (!isActive() && _ss?._settings) ? _ss._settings : null;
  const model = _snap?.model || getSelectedModel();
  if (!model) { alert('Select or type a model name'); return; }

  // Create AbortController for this call (used to cancel on pause)
  const _abortCtrl = new AbortController();
  if (_ss) { _ss.abortController = _abortCtrl; _ss.waitStartTime = performance.now(); }
  else { window._globalAbortCtrl = _abortCtrl; }

  if (isActive()) {
    document.getElementById('llmSpinner').style.display = 'inline';
    document.getElementById('topSpinner').style.display = 'inline';
    updateScaffoldingNodeState('reasoning', 'waiting');
    updateScaffoldingNodeState('root_lm', 'waiting');
    updateScaffoldingNodeState('planner', 'waiting');
    updateScaffoldingNodeState('world_model', 'waiting');
  }
  if (_callSession) { _callSession.waitingForLLM = true; renderSessionTabs(); }

  // Show waiting indicator in reasoning tab (only if active)
  const _waitEl = document.createElement('div');
  _waitEl.className = 'reasoning-entry llm-waiting';
  _waitEl.innerHTML = `<div class="step-label" style="color:var(--dim);"><span class="spinner" style="margin-right:6px;"></span>Waiting for model response... <span class="wait-timer">0s</span></div><div class="stream-preview" style="font-size:12px;color:var(--fg);opacity:0.7;max-height:200px;overflow-y:auto;white-space:pre-wrap;margin-top:4px;padding:4px 8px;border-left:2px solid var(--accent);display:none;"></div>`;
  if (isActive()) {
    const _reasoningContent = document.getElementById('reasoningContent');
    if (_reasoningContent.querySelector('.empty-state')) _reasoningContent.innerHTML = '';
    _reasoningContent.appendChild(_waitEl);
    scrollReasoningToBottom();
    switchTopTab('agent');
    switchSubTab('reasoning');
  }
  const _waitStart = performance.now();
  if (_ss) _ss.waitStartTime = _waitStart;
  if (isActive() && _callSession) renderTimeline(_callSession);
  const _waitInterval = setInterval(() => {
    const el = _waitEl.querySelector('.wait-timer');
    if (el) el.textContent = ((performance.now() - _waitStart) / 1000).toFixed(1) + 's';
    // Update in-flight block in timeline
    const tlFlight = document.getElementById('tlInFlight');
    if (tlFlight) {
      const tlDur = tlFlight.querySelector('.tl-dur');
      if (tlDur) tlDur.textContent = ((performance.now() - _waitStart) / 1000).toFixed(1) + 's';
    }
  }, 100);

  try {
    let resp;
    const inputSettings = _snap?.input || getInputSettings();

    _cur.llmCallCount++;
    if (_ss) { /* already on _ss */ } else { llmCallCount = _cur.llmCallCount; }
    const compact = _snap?.compact || getCompactSettings();
    const contextWindow = _snap ? (getModelInfo(model)?.context_window || 128000) : getSelectedModelContextWindow();
    const maxHistTokens = getContextTokenLimit(compact, contextWindow);
    const callTrigger = compact.enabled && compact.after && _cur.llmCallCount >= compact.after;
    // Token-based trigger: compact when estimated history tokens exceed budget
    const histTokenEst = estimateTokens(JSON.stringify(_cur.moveHistory));
    const tokenTrigger = compact.enabled && histTokenEst > maxHistTokens;
    const needsCompact = tokenTrigger || callTrigger;
    const prevCompactCall = _cur._compactSummaryAtCall;
    if (needsCompact && isActive()) updateScaffoldingNodeState('compact', 'waiting');
    const compactBlock = needsCompact ? await buildCompactContext(_ss) : '';
    if (needsCompact && isActive()) updateScaffoldingNodeState('compact', 'done');

    // Guard: session changed during compact — discard
    if (!sessions.has(_callSessionId)) { console.log('[askLLM] session closed during compact, discarding'); return null; }

    // Only show reasoning entry when a NEW compact was generated (not cached)
    if (compactBlock && _cur._compactSummaryAtCall !== prevCompactCall && isActive()) {
      logSessionEvent('compact', _cur.stepCount, { trigger: callTrigger ? 'calls' : 'tokens', call_count: _cur.llmCallCount });
      const content = document.getElementById('reasoningContent');
      if (content.querySelector('.empty-state')) content.innerHTML = '';
      const cEntry = document.createElement('div');
      cEntry.className = 'reasoning-entry';
      const trigger = callTrigger ? `after ${_cur.llmCallCount} calls` : `tokens exceeded ${maxHistTokens}`;
      cEntry.innerHTML = `<div class="step-label" style="color:var(--purple);">&#128220; Auto-compacted at step ${_cur.stepCount} (${trigger})</div>`;
      content.appendChild(cEntry);
      scrollReasoningToBottom();
    }

    // When compact context exists, only send history AFTER the compaction point
    // (the compact summary already covers everything before it)
    const postCompactHistory = (compactBlock && _cur._compactSummaryAtStep > 0)
      ? _cur.moveHistory.filter(h => h.step > _cur._compactSummaryAtStep)
      : _cur.moveHistory;
    const historyForLLM = compact.enabled
      ? trimHistoryForTokens(postCompactHistory, maxHistTokens)
      : postCompactHistory;

    const modelInfo = getModelInfo(model);
    const isPuterModel = modelInfo?.provider === 'puter';
    const isByokModel = modelInfo && getByokKey(modelInfo.provider);

    const _callStart = performance.now();
    {
      // ── Client-side LLM (Puter.js or BYOK) ────────────────────────────
      const _scaffType = _snap?.scaffolding_type || activeScaffoldingType;
      if (_scaffType === 'rlm') {
        // RLM scaffolding: full iteration loop runs client-side
        try {
          resp = await askLLMRlm(_cur, model, modelInfo, _waitEl, isActive, historyForLLM, compactBlock, _snap);
        } catch (e) {
          console.error('[askLLM] RLM client-side error:', e);
          resp = { error: e.message, model };
        }
        if (resp) resp._clientSide = true;
      } else if (_scaffType === 'three_system' || _scaffType === 'two_system') {
        // Three-System / Two-System scaffolding: Planner REPL + WM + Monitor
        try {
          resp = await askLLMThreeSystem(_cur, model, modelInfo, _waitEl, isActive, historyForLLM, compactBlock, _snap);
        } catch (e) {
          console.error('[askLLM] Three-System client-side error:', e);
          resp = { error: e.message, model };
        }
        if (resp) resp._clientSide = true;
      } else if (_scaffType === 'agent_spawn') {
        // Agent Spawn scaffolding: orchestrator + subagent loops
        try {
          resp = await askLLMAgentSpawn(_cur, model, modelInfo, _waitEl, isActive, historyForLLM, compactBlock, _snap);
        } catch (e) {
          console.error('[askLLM] Agent Spawn client-side error:', e);
          resp = { error: e.message, model };
        }
        if (resp) resp._clientSide = true;
      } else {
      const prompt = buildClientPrompt(_cur.currentState, historyForLLM, _cur.currentChangeMap, inputSettings, _snap?.tools_mode || getToolsMode(), compactBlock, _snap?.planning_mode || getPlanningMode());
      window._lastLLMGrid = _cur.currentState.grid;
      window._lastLLMPrevGrid = _ss ? _ss.previousGrid : previousGrid;
      let rawContent;
      try {
        const _onChunk = modelInfo?.provider === 'gemini' ? (textSoFar) => {
          if (isActive()) {
            const previewEl = _waitEl.querySelector('.stream-preview');
            if (previewEl) {
              previewEl.style.display = 'block';
              previewEl.textContent = textSoFar.length > 500 ? textSoFar.slice(-500) : textSoFar;
              previewEl.scrollTop = previewEl.scrollHeight;
            }
            const label = _waitEl.querySelector('.step-label');
            if (label && !label.dataset.streaming) {
              label.dataset.streaming = '1';
              const spinnerEl = label.querySelector('.spinner');
              const timerEl = label.querySelector('.wait-timer');
              label.innerHTML = '';
              if (spinnerEl) label.appendChild(spinnerEl);
              label.appendChild(timerEl);
            }
          }
        } : null;
        rawContent = await callLLM(
          [{role: 'user', content: prompt}], model,
          { maxTokens: _snap?.max_tokens || getMaxTokens(), onChunk: _onChunk }
        );
        // Handle Gemini MALFORMED_FUNCTION_CALL recovery
        if (rawContent && typeof rawContent === 'object' && rawContent.malformed) {
          const finishMsg = rawContent.finishMessage || '';
          const codeMatch = finishMsg.match(/```python\s*\n([\s\S]*?)```/);
          if (codeMatch && _pyodideReady) {
            console.warn('Gemini MALFORMED_FUNCTION_CALL — extracting code, running via Pyodide');
            const code = codeMatch[1].trim();
            const output = await runPyodide(code, window._lastLLMGrid || [[]], window._lastLLMPrevGrid || null, _callSessionId);
            rawContent = await callLLM([
              {role: 'user', content: prompt},
              {role: 'assistant', content: '```python\n' + code + '\n```'},
              {role: 'user', content: '[Code output]:\n' + output + '\n\nBased on this analysis, provide your answer as JSON only. No code.'},
            ], model, { maxTokens: getMaxTokens() });
          } else {
            console.warn('Gemini MALFORMED_FUNCTION_CALL — retrying without tools');
            rawContent = await callLLM(
              [{role: 'user', content: prompt + '\n\nIMPORTANT: Do NOT use code or function calls. Respond with plain JSON only.'}],
              model, { maxTokens: getMaxTokens() }
            );
          }
        }
      } catch (e) {
        resp = { error: e.message, model: model };
        rawContent = null;
      }
      // Guard: session changed during client LLM call — discard response
      if (!sessions.has(_callSessionId)) { console.log('[askLLM] session closed during client LLM call, discarding'); return null; }
      // Handle truncated BYOK responses (returned as {text, truncated})
      let _clientTruncated = false;
      if (rawContent && typeof rawContent === 'object' && rawContent.truncated) {
        _clientTruncated = true;
        rawContent = rawContent.text;
      }
      // If LLM returned empty/no content but no error was set, treat as empty response error
      if (!rawContent && !resp) {
        resp = { error: 'Empty response from model', model: model };
      }
      if (rawContent) {
        resp = parseClientLLMResponse(rawContent, model);
        if (_clientTruncated) resp.truncated = true;
        resp.tools_active = getToolsMode() === 'on';

        // ── Parse-retry loop: if no valid JSON action found, retry with nudge ──
        const MAX_PARSE_RETRIES = 2;
        if (!resp.parsed && !resp.truncated && rawContent) {
          const actions = (_cur.currentState.available_actions || []).map(a => `${a}=${ACTION_NAMES[a] || 'ACTION'+a}`).join(', ');
          const nudge = `Your previous response could not be parsed as a valid action. You MUST respond with ONLY a JSON object. Available actions: ${actions}\nExample: {"observation":"...","reasoning":"...","action":1}\nDo NOT output code, commentary, or markdown. JSON ONLY.`;
          for (let _retry = 0; _retry < MAX_PARSE_RETRIES; _retry++) {
            console.warn(`[askLLM] Parse retry ${_retry + 1}/${MAX_PARSE_RETRIES} — no valid action in response`);
            // Update wait element to show retry
            if (isActive()) {
              const previewEl = _waitEl.querySelector('.stream-preview');
              if (previewEl) {
                previewEl.style.display = 'block';
                previewEl.textContent = `Parse failed — retrying (${_retry + 1}/${MAX_PARSE_RETRIES})...`;
              }
            }
            let retryRaw;
            try {
              retryRaw = await callLLM([{role: 'user', content: prompt + '\n\n' + nudge}], model, { maxTokens: _snap?.max_tokens || getMaxTokens() });
            } catch (e) { console.warn('[askLLM] Parse retry error:', e.message); continue; }
            if (!sessions.has(_callSessionId)) return null;
            if (retryRaw && typeof retryRaw === 'object' && retryRaw.truncated) retryRaw = retryRaw.text;
            if (retryRaw) {
              const retryResp = parseClientLLMResponse(retryRaw, model);
              if (retryResp.parsed) {
                resp = retryResp;
                resp.tools_active = getToolsMode() === 'on';
                resp.retries = _retry + 1;
                rawContent = retryRaw;
                console.log(`[askLLM] Parse retry ${_retry + 1} succeeded`);
                break;
              }
            }
          }
          // All retries failed — fall back to random valid action
          if (!resp.parsed) {
            const avail = _cur.currentState.available_actions || [];
            // Prefer movement actions (1-4) over reset (0) and special actions
            const preferred = avail.filter(a => a >= 1 && a <= 4);
            const pool = preferred.length ? preferred : avail.filter(a => a !== 0);
            const fallbackAction = pool.length ? pool[Math.floor(Math.random() * pool.length)] : (avail[0] ?? 1);
            console.warn(`[askLLM] All parse retries exhausted — falling back to random action ${fallbackAction} (${ACTION_NAMES[fallbackAction]})`);
            resp.parsed = { action: fallbackAction, observation: 'Parse failed', reasoning: 'Random fallback after failed parse retries' };
            resp.retries = MAX_PARSE_RETRIES;
            resp._fallbackAction = true;
          }
        }

        // Execute Python code blocks if tools are on (Pyodide)
        if (resp.tools_active && _pyodideReady && rawContent) {
          const toolCalls = await executeToolBlocks(rawContent, _cur.currentState.grid, _ss ? _ss.previousGrid : previousGrid, _callSessionId);
          if (toolCalls.length) {
            resp.tool_calls = toolCalls;
          }
        }
        // Merge usage data from Puter.js if available
        if (callLLM._lastUsage) {
          resp.usage = callLLM._lastUsage;
          callLLM._lastUsage = null;
        }
      }
      // Always set prompt_length for token estimation (even on error)
      if (resp) { resp.prompt_length = prompt.length; resp._clientSide = true; }
      } // end inner else (non-RLM client-side)
    }

    // Attach call duration
    if (resp) resp.call_duration_ms = Math.round(performance.now() - _callStart);

    // Push reasoning event to timeline (skip for Agent Spawn — it pushes granular as_* events)
    if (resp && resp.call_duration_ms && _callSession && _callSession.timelineEvents && !resp._alreadyExecuted) {
      const _tlPlan = resp.parsed?.plan && Array.isArray(resp.parsed.plan) ? resp.parsed.plan : (resp.parsed ? [{ action: resp.parsed.action }] : []);
      const _tlActions = _tlPlan.map(p => p.action);
      _callSession.timelineEvents.push({
        type: 'reasoning', agent_type: resp.agent_type || 'executor',
        duration: resp.call_duration_ms,
        turn: _cur.llmCallCount, model: resp.model || model,
        stepStart: _cur.stepCount + 1, actions: _tlActions,
        call_id: resp.call_id, input_tokens: resp.usage?.prompt_tokens || 0,
        output_tokens: resp.usage?.candidates_tokens || 0,
        cost: resp.cost || 0,
        response_preview: (resp.raw || '').slice(0, 1000),
        error: resp.error,
      });
      if (isActive()) renderTimeline(_callSession);
      // Emit obs event
      emitObsEvent(_callSession, {
        event: 'llm_call', agent: 'executor', model: resp.model || model,
        duration_ms: resp.call_duration_ms,
        input_tokens: resp.usage?.prompt_tokens || 0,
        output_tokens: resp.usage?.candidates_tokens || 0,
        cost: resp.cost || 0,
        summary: (resp.raw || '').slice(0, 200),
      });
    }

    // Collect observation for compact context
    collectObservation(resp, _ss);

    // ── Fallback: if response has no usable plan (truncated, empty, or error),
    //    pick a random valid action so the game keeps moving ──
    const _needsFallback = resp && !resp.parsed && (
      resp.truncated ||                                       // token limit hit
      resp.error === 'Empty response from model' ||           // model returned nothing
      (resp.error && /empty|no content|no response/i.test(resp.error))  // similar empty errors
    );
    if (_needsFallback) {
      const avail = _cur.currentState.available_actions || [];
      const preferred = avail.filter(a => a >= 1 && a <= 4);
      const pool = preferred.length ? preferred : avail.filter(a => a !== 0);
      const fallbackAction = pool.length ? pool[Math.floor(Math.random() * pool.length)] : (avail[0] ?? 1);
      const reason = resp.truncated ? 'token limit reached' : 'empty response from model';
      console.warn(`[askLLM] ${reason} — falling back to random action ${fallbackAction} (${ACTION_NAMES[fallbackAction]})`);
      resp.parsed = { action: fallbackAction, observation: reason, reasoning: `Random fallback — ${reason}` };
      resp._fallbackAction = true;
      resp.truncated = false;
      resp.error = null;
    }

    // Build reasoning entry (always create it, but only insert into DOM if active)
    const entry = document.createElement('div');
    entry.className = 'reasoning-entry';

    if (resp.truncated) {
      const tokensHtml = formatTokenInfo(resp, _cur.sessionTotalTokens);
      const durationHtml = resp.call_duration_ms
        ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(resp.call_duration_ms / 1000).toFixed(1)}s</span>` : '';
      entry.innerHTML = `<div class="step-label" style="color:var(--yellow);">Truncated — ${resp.model || model}${durationHtml}</div>
        ${tokensHtml}
        <div style="color:var(--yellow);font-size:11px;margin-top:4px;">Response hit the token limit and was cut off. The output was discarded.</div>
        <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn btn-primary" style="font-size:11px;padding:4px 12px;" onclick="this.closest('div').querySelectorAll('button').forEach(b=>b.disabled=true);stepOnce()">Retry</button>
          <button class="btn" style="font-size:11px;padding:4px 12px;" onclick="truncAutoRetry(this,20)">Keep going (up to 20)</button>
          <button class="btn" style="font-size:11px;padding:4px 12px;" onclick="truncIncreaseAndRetry(this)">Double limit &amp; retry</button>
        </div>`;
      // Pause autoplay so user can decide
      if (_cur.autoPlaying) {
        _cur.autoPlaying = false;
        if (_ss) { /* already on _ss */ } else { autoPlaying = false; }
        if (isActive()) { updateAutoBtn(); unlockSettings(); }
        renderSessionTabs();
      }
    } else if (resp.error) {
      entry.innerHTML = `<div class="step-label">Error (${resp.model || model})</div>
        <div style="color:var(--red);">${resp.error}</div>`;
    } else if (resp.scaffolding === 'rlm' && resp.rlm) {
      // ── RLM scaffolding: show iteration details ──
      const rlm = resp.rlm;
      const durationHtml = resp.call_duration_ms
        ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(resp.call_duration_ms / 1000).toFixed(1)}s</span>` : '';
      const rlmBadge = '<span class="tools-badge" style="background:#bc8cff33;color:var(--purple);">RLM</span>';
      const iterBadge = `<span class="tools-badge" style="background:#58a6ff22;color:var(--accent);">${rlm.iterations}/${rlm.max_iterations} iter</span>`;
      const subBadge = rlm.sub_calls > 0 ? `<span class="tools-badge" style="background:#e3b34133;color:var(--yellow);">${rlm.sub_calls} sub-calls</span>` : '';

      // Build iteration log
      let iterHtml = '';
      if (rlm.log && rlm.log.length) {
        const iterDetails = rlm.log.map((it, idx) => {
          let content = '';
          if (it.error) {
            content = `<div style="color:var(--red);font-size:11px;">Error: ${esc(it.error)}</div>`;
          } else {
            // Show response excerpt
            const respExcerpt = esc((it.response || '').substring(0, 500));
            content = `<div style="font-size:11px;white-space:pre-wrap;color:var(--text-dim);max-height:100px;overflow:auto;">${respExcerpt}${it.response?.length > 500 ? '...' : ''}</div>`;
            // Show REPL outputs
            if (it.repl_outputs?.length) {
              content += it.repl_outputs.map((o, j) =>
                `<div style="margin-top:4px;padding:4px 8px;background:var(--bg);border-left:2px solid var(--green);font-size:10px;font-family:monospace;white-space:pre-wrap;max-height:80px;overflow:auto;"><span style="color:var(--green);">REPL ${j+1}:</span> ${esc(o)}</div>`
              ).join('');
            }
          }
          return `<div style="margin-bottom:8px;padding:4px 0;border-bottom:1px solid var(--border);">
            <div style="font-size:10px;color:var(--accent);font-weight:600;">Iteration ${idx + 1} ${it.code_blocks ? `(${it.code_blocks} code blocks)` : ''}</div>
            ${content}
          </div>`;
        }).join('');
        iterHtml = `<details style="margin-top:6px;"><summary style="cursor:pointer;color:var(--text-dim);font-size:10px;">RLM Iterations (${rlm.iterations})</summary>
          <div style="margin-top:4px;max-height:300px;overflow:auto;">${iterDetails}</div></details>`;
      }

      // Standard parsed response display
      if (resp.parsed) {
        const p = resp.parsed;
        const steps = (p.plan && Array.isArray(p.plan)) ? p.plan : [{ action: p.action, data: p.data || {} }];
        const planHtml = steps.map((s, i) => {
          const aName = ACTION_NAMES[s.action] || `ACTION${s.action}`;
          const dataStr = s.data?.x !== undefined ? ` (${s.data.x},${s.data.y})` : '';
          return `<div class="plan-step" data-plan-idx="${i}">${i + 1}. <span class="action-btn">${aName}</span>${dataStr}</div>`;
        }).join('');
        const stepLabel = steps.length > 1
          ? `Steps ${_cur.stepCount + 1}-${_cur.stepCount + steps.length}`
          : `Step ${_cur.stepCount + 1}`;
        entry.dataset.branchStep = _cur.stepCount + steps.length;
        entry.innerHTML = `
          <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount + steps.length})" title="Branch from here">&#8627; branch</button>
          <div class="step-label">${stepLabel} — ${resp.model}${durationHtml}${rlmBadge}${iterBadge}${subBadge}</div>
          <div class="observation"><strong>Obs:</strong> ${p.observation || '—'}</div>
          <div style="margin-top:4px;"><strong>Reasoning:</strong> ${p.reasoning || '—'}</div>
          <div class="plan-progress">${planHtml}</div>
          ${iterHtml}`;
      } else {
        entry.dataset.branchStep = _cur.stepCount;
        entry.innerHTML = `
          <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount})" title="Branch from here">&#8627; branch</button>
          <div class="step-label">Step ${_cur.stepCount} — ${resp.model}${durationHtml}${rlmBadge}${iterBadge}${subBadge}</div>
          <div style="color:var(--yellow);font-size:11px;">RLM did not produce a parseable action after ${rlm.iterations} iterations.</div>
          ${iterHtml}`;
      }
    } else if ((resp.scaffolding === 'three_system' || resp.scaffolding === 'two_system') && resp.three_system) {
      // ── Three-system scaffolding: show planner REPL + WM details ──
      console.log('[DEBUG reasoning] rendering three_system entry:', {
        scaffolding: resp.scaffolding,
        parsed: resp.parsed,
        three_system: resp.three_system,
        raw_length: resp.raw?.length,
        thinking: resp.thinking,
      });
      const ts = resp.three_system;
      const durationHtml = resp.call_duration_ms
        ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(resp.call_duration_ms / 1000).toFixed(1)}s</span>` : '';
      const tsBadge = `<span class="tools-badge" style="background:#58a6ff33;color:var(--accent);">${resp.scaffolding === 'two_system' ? '2-SYS' : '3-SYS'}</span>`;
      const turnBadge = `<span class="tools-badge" style="background:#bc8cff22;color:var(--purple);">Turn ${ts.turn}</span>`;
      const plannerTurns = ts.planner_log ? ts.planner_log.length : 0;
      const plannerBadge = `<span class="tools-badge" style="background:#58a6ff22;color:var(--accent);">${plannerTurns} REPL</span>`;
      const wmBadge = ts.world_model?.ran_update
        ? `<span class="tools-badge" style="background:#bc8cff22;color:var(--purple);">WM v${ts.world_model.rules_version}</span>` : '';
      const goalHtml = ts.goal ? `<div style="font-size:10px;color:var(--accent);margin-top:2px;">Goal: ${esc(ts.goal)}</div>` : '';

      // Build detailed call-by-call view for the planner REPL
      let callsHtml = '';
      if (ts.planner_log && ts.planner_log.length) {
        callsHtml = '<div style="margin-top:8px;">';
        callsHtml += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px;">Planner REPL Calls:</div>';
        ts.planner_log.forEach((lg, i) => {
          const dur = lg.duration_ms ? ` (${(lg.duration_ms/1000).toFixed(1)}s)` : '';
          const typeColor = lg.type === 'commit' ? 'var(--green)'
                          : lg.type === 'error' ? 'var(--red)'
                          : lg.type === 'rejected' ? 'var(--yellow)'
                          : 'var(--accent)';

          callsHtml += `<div style="border-left:2px solid ${typeColor};padding-left:8px;margin:4px 0;">`;
          callsHtml += `<div style="font-size:10px;"><strong style="color:${typeColor};">Call ${i+1}: ${lg.type}</strong>${dur}</div>`;

          if (lg.type === 'simulate' && lg.parsed) {
            const acts = (lg.parsed.actions || []).map(a => {
              const aName = ACTION_NAMES[a.action !== undefined ? a.action : a] || `A${a.action !== undefined ? a.action : a}`;
              return aName;
            }).join(', ');
            callsHtml += `<div style="font-size:10px;color:var(--text-dim);">Actions: ${acts}</div>`;
            if (lg.parsed.question) callsHtml += `<div style="font-size:10px;color:var(--text-dim);">Q: ${esc(lg.parsed.question)}</div>`;
            if (lg.predictions) callsHtml += `<div style="font-size:10px;color:var(--text-dim);">Predictions: ${lg.predictions.map(p => esc(p)).join('; ')}</div>`;
          }
          if (lg.type === 'analyze' && lg.tool) {
            callsHtml += `<div style="font-size:10px;color:var(--text-dim);">Tool: ${lg.tool}</div>`;
          }
          if (lg.type === 'commit') {
            const rawLen = lg.raw_plan_length;
            const padNote = rawLen !== undefined && rawLen < (lg.plan_length || 0) ? ` (LLM: ${rawLen}, padded)` : '';
            callsHtml += `<div style="font-size:10px;color:var(--text-dim);">${lg.plan_length || '?'} steps committed${padNote}</div>`;
          }
          if (lg.type === 'rejected') {
            callsHtml += `<div style="font-size:10px;color:var(--yellow);">${lg.plan_length} steps &lt; min ${lg.min_required}</div>`;
          }
          if (lg.type === 'simulate_skipped') {
            callsHtml += `<div style="font-size:10px;color:var(--yellow);">WM disabled — simulate skipped</div>`;
          }

          if (lg.raw) {
            callsHtml += `<details style="margin-top:2px;"><summary style="cursor:pointer;color:var(--text-dim);font-size:10px;">Raw response (${lg.raw.length} chars)</summary>`;
            callsHtml += `<div style="color:var(--text-dim);font-size:10px;margin-top:4px;white-space:pre-wrap;max-height:400px;overflow:auto;">${esc(lg.raw)}</div></details>`;
          }

          callsHtml += '</div>';
        });
        callsHtml += '</div>';
      }

      // WM update calls
      let wmCallsHtml = '';
      if (ts.world_model?.ran_update && ts.world_model.wm_log?.length) {
        wmCallsHtml = '<details style="margin-top:6px;"><summary style="cursor:pointer;font-size:10px;color:var(--purple);">WM Update Calls (' + ts.world_model.wm_log.length + ')</summary><div style="margin-top:4px;">';
        ts.world_model.wm_log.forEach((lg, i) => {
          const dur = lg.duration_ms ? ` (${(lg.duration_ms/1000).toFixed(1)}s)` : '';
          const typeColor = lg.type === 'commit' ? 'var(--green)' : lg.type === 'error' ? 'var(--red)' : 'var(--purple)';
          wmCallsHtml += `<div style="border-left:2px solid ${typeColor};padding-left:8px;margin:4px 0;font-size:10px;">`;
          if (lg.type === 'query') wmCallsHtml += `<strong style="color:var(--purple);">WM ${i+1}: query ${lg.tool || '?'}</strong>${dur}`;
          else if (lg.type === 'commit') wmCallsHtml += `<strong style="color:var(--green);">WM ${i+1}: commit</strong> (confidence: ${(lg.confidence || 0).toFixed(1)})${dur}`;
          else if (lg.type === 'error') wmCallsHtml += `<strong style="color:var(--red);">WM ${i+1}: error</strong>${dur}`;
          else wmCallsHtml += `<strong>WM ${i+1}: ${lg.type}</strong>${dur}`;
          wmCallsHtml += '</div>';
        });
        wmCallsHtml += '</div></details>';
      }

      // WM rules preview (collapsible)
      let wmPreviewHtml = '';
      if (ts.world_model?.rules_preview) {
        wmPreviewHtml = `<details style="margin-top:4px;"><summary style="cursor:pointer;color:var(--purple);font-size:10px;">WM Rules v${ts.world_model.rules_version}</summary>
          <div style="color:var(--text-dim);font-size:10px;margin-top:4px;white-space:pre-wrap;max-height:100px;overflow:auto;">${esc(ts.world_model.rules_preview)}</div></details>`;
      }

      if (resp.parsed) {
        const p = resp.parsed;
        const steps = (p.plan && Array.isArray(p.plan)) ? p.plan : [{ action: p.action, data: p.data || {} }];
        const planHtml = steps.map((s, i) => {
          const aName = ACTION_NAMES[s.action] || `ACTION${s.action}`;
          const dataStr = s.data?.x !== undefined ? ` (${s.data.x},${s.data.y})` : '';
          return `<div class="plan-step" data-plan-idx="${i}">${i + 1}. <span class="action-btn">${aName}</span>${dataStr}</div>`;
        }).join('');

        // Final committed plan details (collapsible, with expected outcomes)
        let finalPlanHtml = '';
        if (p.plan && Array.isArray(p.plan) && p.plan.length) {
          finalPlanHtml = '<details style="margin-top:6px;"><summary style="cursor:pointer;font-size:10px;color:var(--accent);">Committed Plan Details</summary>';
          finalPlanHtml += '<div style="font-size:10px;margin-top:4px;">';
          p.plan.forEach((s, i) => {
            const aName = ACTION_NAMES[s.action] || `ACTION${s.action}`;
            const dataStr = s.data?.x !== undefined ? ` (${s.data.x},${s.data.y})` : '';
            const expected = s.expected ? ` → ${esc(s.expected)}` : '';
            finalPlanHtml += `<div style="color:var(--text);margin:1px 0;">${i+1}. ${aName}${dataStr}${expected}</div>`;
          });
          finalPlanHtml += '</div></details>';
        }

        const stepLabel = steps.length > 1
          ? `Steps ${_cur.stepCount + 1}-${_cur.stepCount + steps.length}`
          : `Step ${_cur.stepCount + 1}`;
        entry.dataset.branchStep = _cur.stepCount + steps.length;
        entry.innerHTML = `
          <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount + steps.length})" title="Branch from here">&#8627; branch</button>
          <div class="step-label">${stepLabel} — ${resp.model}${durationHtml}${tsBadge}${turnBadge}${plannerBadge}${wmBadge}</div>
          ${goalHtml}
          <div class="observation"><strong>Obs:</strong> ${p.observation || '—'}</div>
          <div style="margin-top:4px;"><strong>Reasoning:</strong> ${p.reasoning || '—'}</div>
          <div class="plan-progress">${planHtml}</div>
          ${finalPlanHtml}
          ${callsHtml}
          ${wmCallsHtml}
          ${wmPreviewHtml}`;
      } else {
        entry.dataset.branchStep = _cur.stepCount;
        entry.innerHTML = `
          <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount})" title="Branch from here">&#8627; branch</button>
          <div class="step-label">Step ${_cur.stepCount} — ${resp.model}${durationHtml}${tsBadge}${turnBadge}${plannerBadge}</div>
          <div style="color:var(--yellow);font-size:11px;">Planner fallback — could not commit a plan.</div>
          ${callsHtml}`;
      }
    } else if (resp.scaffolding === 'agent_spawn' && resp.agent_spawn) {
      // ── Agent Spawn scaffolding: show orchestrator + subagent details ──
      const as = resp.agent_spawn;
      const p = resp.parsed || {};
      const durationHtml = resp.call_duration_ms
        ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(resp.call_duration_ms / 1000).toFixed(1)}s</span>` : '';
      const asBadge = '<span class="tools-badge" style="background:#ff8b3d33;color:var(--orange);">SPAWN</span>';
      const totalSteps = as.total_steps || 0;
      const totalSubs = as.total_subagents || 0;
      const stepsBadge = `<span class="tools-badge" style="background:#3fb95033;color:var(--green);">${totalSteps} steps</span>`;
      const subsBadge = `<span class="tools-badge" style="background:#bc8cff22;color:var(--purple);">${totalSubs} agents</span>`;

      // Orchestrator log
      let orchHtml = '';
      if (as.orchestrator_log?.length) {
        orchHtml = '<details style="margin-top:4px;"><summary style="cursor:pointer;font-size:10px;color:var(--dim);">Orchestrator Log (' + as.orchestrator_log.length + ' turns)</summary><div style="font-size:10px;color:var(--fg);padding:4px 8px;margin-top:2px;">';
        for (const oEntry of as.orchestrator_log) {
          const oColor = oEntry.type === 'delegate' ? 'var(--accent)' : oEntry.type === 'think' ? 'var(--yellow)' : 'var(--dim)';
          orchHtml += `<div style="color:${oColor};">Turn ${oEntry.turn}: ${oEntry.type}`;
          if (oEntry.agent_type) orchHtml += ` (${oEntry.agent_type})`;
          if (oEntry.task) orchHtml += ` — ${esc(oEntry.task.substring(0, 80))}`;
          if (oEntry.duration_ms) orchHtml += ` <span style="color:var(--dim);">${(oEntry.duration_ms / 1000).toFixed(1)}s</span>`;
          orchHtml += '</div>';
        }
        orchHtml += '</div></details>';
      }

      // Subagent summaries
      let subHtml = '';
      if (as.subagent_summaries?.length) {
        subHtml = '<details style="margin-top:2px;"><summary style="cursor:pointer;font-size:10px;color:var(--dim);">Subagent Reports (' + as.subagent_summaries.length + ')</summary><div style="font-size:10px;color:var(--fg);padding:4px 8px;margin-top:2px;">';
        for (const sub of as.subagent_summaries) {
          const subColor = sub.type === 'explorer' ? 'var(--green)' : sub.type === 'theorist' ? 'var(--cyan)' : sub.type === 'tester' ? 'var(--yellow)' : 'var(--purple)';
          subHtml += `<div style="color:${subColor};">[${sub.type}] ${sub.steps || 0} steps — ${esc((sub.summary || '').substring(0, 150))}</div>`;
        }
        subHtml += '</div></details>';
      }

      entry.dataset.branchStep = _cur.stepCount;
      entry.innerHTML = `
        <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount})" title="Branch from here">&#8627; branch</button>
        <div class="step-label">Step ${_cur.stepCount} — ${resp.model}${durationHtml}${asBadge}${stepsBadge}${subsBadge}</div>
        <div class="observation">${esc(p.observation || '')}</div>
        ${orchHtml}${subHtml}`;
    } else if (resp.parsed) {
      const p = resp.parsed;
      const thinkHtml = resp.thinking
        ? `<details style="margin-top:4px;"><summary style="cursor:pointer;color:var(--text-dim);font-size:10px;">Thinking...</summary>
           <div style="color:var(--text-dim);font-size:11px;margin-top:4px;white-space:pre-wrap;">${resp.thinking}</div></details>` : '';
      const toolsBadge = resp.tools_active ? '<span class="tools-badge">TOOLS</span>' : '';
      const thinkLevel = resp.thinking_level || getThinkingLevel();
      const thinkBadge = thinkLevel && thinkLevel !== 'off'
        ? `<span class="tools-badge" style="background:#58a6ff22;color:var(--accent);">${thinkLevel.toUpperCase()}</span>` : '';
      const cacheBadge = resp.cache_active ? '<span class="tools-badge" style="background:#e3b34133;color:var(--yellow);">CACHED</span>' : '';
      const compactBadge = compactBlock ? '<span class="tools-badge" style="background:#bc8cff33;color:var(--purple);">COMPACT</span>' : '';
      const planBadge = p.plan ? '<span class="tools-badge" style="background:#58a6ff33;color:var(--accent);">PLAN</span>' : '';
      const retryBadge = resp.retries ? `<span class="tools-badge" style="background:#e3b34133;color:var(--yellow);">${resp.retries} RETRY</span>` : '';
      const fallbackBadge = resp._fallbackAction ? '<span class="tools-badge" style="background:#f8514933;color:var(--red);">FALLBACK</span>' : '';
      const analysisHtml = p.analysis
        ? `<details class="analysis-wrap"><summary>Analysis</summary><div class="analysis-content">${p.analysis}</div></details>` : '';
      const ci = _cur.currentChangeMap?.change_count > 0
        ? `<div style="font-size:11px;color:var(--yellow);">${_cur.currentChangeMap.change_count} cells changed</div>` : '';
      const tokensHtml = formatTokenInfo(resp, _cur.sessionTotalTokens);
      const durationHtml = resp.call_duration_ms
        ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(resp.call_duration_ms / 1000).toFixed(1)}s</span>` : '';

      // Tool calls display (collapsible)
      const toolCallsHtml = renderToolCallsHtml(resp.tool_calls || p.tool_calls || []);

      // Normalize to plan format: single actions become a 1-step plan
      const steps = (p.plan && Array.isArray(p.plan))
        ? p.plan
        : [{ action: p.action, data: p.data || {} }];
      const planHtml = steps.map((s, i) => {
        const aName = ACTION_NAMES[s.action] || `ACTION${s.action}`;
        const dataStr = s.data?.x !== undefined ? ` (${s.data.x},${s.data.y})` : '';
        return `<div class="plan-step" data-plan-idx="${i}">${i + 1}. <span class="action-btn">${aName}</span>${dataStr}</div>`;
      }).join('');
      const stepLabel = steps.length > 1
        ? `Steps ${_cur.stepCount + 1}-${_cur.stepCount + steps.length}`
        : `Step ${_cur.stepCount + 1}`;
      entry.dataset.branchStep = _cur.stepCount + steps.length;
      entry.innerHTML = `
        <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount + steps.length})" title="Branch from here">&#8627; branch</button>
        <div class="step-label">${stepLabel} — ${resp.model}${durationHtml}${thinkBadge}${toolsBadge}${cacheBadge}${compactBadge}${planBadge}${retryBadge}${fallbackBadge}</div>
        ${tokensHtml}${ci}
        <div class="observation"><strong>Obs:</strong> ${p.observation || '—'}</div>
        <div style="margin-top:4px;"><strong>Reasoning:</strong> ${p.reasoning || '—'}</div>
        ${analysisHtml}${toolCallsHtml}
        <div class="plan-progress">${planHtml}</div>
        ${thinkHtml}`;
    } else {
      entry.dataset.branchStep = _cur.stepCount;
      entry.innerHTML = `
        <button class="branch-btn" onclick="branchFromStep(${_cur.stepCount})" title="Branch from here">&#8627; branch</button>
        <div class="step-label">Step ${_cur.stepCount} — ${resp.model}</div>
        <div style="white-space:pre-wrap;font-size:11px;">${resp.raw || 'No response'}</div>`;
    }

    if (isActive()) {
      const content = document.getElementById('reasoningContent');
      if (content.querySelector('.empty-state')) content.innerHTML = '';
      content.appendChild(entry);
      annotateCoordRefs(entry);
      scrollReasoningToBottom();
      switchTopTab('agent');
      switchSubTab('reasoning');
    }

    // Sync session state back to globals if still active
    if (_ss) syncSessionToGlobals(_ss);
    return resp;
  } finally {
    clearInterval(_waitInterval);
    if (_waitEl.parentNode) _waitEl.remove();
    if (_ss) { _ss.abortController = null; _ss.waitStartTime = null; }
    if (isActive()) {
      document.getElementById('llmSpinner').style.display = 'none';
      document.getElementById('topSpinner').style.display = 'none';
      updateScaffoldingNodeState('reasoning', 'done');
      updateScaffoldingNodeState('root_lm', 'done');
      updateScaffoldingNodeState('planner', 'done');
      updateScaffoldingNodeState('world_model', 'done');
    }
    if (_callSession) { _callSession.waitingForLLM = false; renderSessionTabs(); }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════
// PART 2: PLAN EXECUTION & ACTION HANDLING (Extracted to llm-executor.js — Phase 22)
// ═══════════════════════════════════════════════════════════════════════════
// Functions extracted to llm-executor.js:
//   executePlan(plan, resp, entry, expected, ss) — execute a multi-step plan from LLM
//   executeOneAction(resp) — execute a single action (non-plan mode)
//   stepOnce() — single-step orchestration
// These are loaded from llm-executor.js before this file.
// Called by: stepOnce(), toggleAutoPlay(), truncAutoRetry() (all now in llm-executor.js)

// [executePlan, executeOneAction, stepOnce definitions removed — see llm-executor.js]

// ──────────────────────────────────────────────────────────────────────────
// SECTION: Truncation & Retry Handlers
// ──────────────────────────────────────────────────────────────────────────
async function truncAutoRetry(btn, maxRetries) {
  // Disable all sibling buttons
  btn.closest('div').querySelectorAll('button').forEach(b => b.disabled = true);
  saveSessionToState();  // sync globals → ss before async pipeline
  const ss = getActiveSession();
  autoPlaying = true;
  lockSettings();
  updateAutoBtn();
  if (ss) { ss.autoPlaying = true; renderSessionTabs(); }

  for (let i = 0; i < maxRetries; i++) {
    if (ss ? !ss.autoPlaying : !autoPlaying) break;
    const resp = await askLLM(ss);
    if (ss ? !ss.autoPlaying : !autoPlaying) break;
    if (!resp) break;
    if (resp.error) break;
    if (resp.truncated) {
      // Still truncated — continue loop
      continue;
    }
    // Success — not truncated
    if (resp.parsed && !resp._alreadyExecuted) {
      const p = resp.parsed;
      const plan = (p.plan && Array.isArray(p.plan) && p.plan.length > 0)
        ? p.plan
        : (p.action !== undefined && p.action !== null)
          ? [{ action: p.action, data: p.data || {} }]
          : null;
      if (plan) {
        const entry = getLastReasoningEntry();
        const expected = p.expected || null;
        await executePlan(plan, resp, entry, expected, ss);
      }
    }
    autoPlaying = false;
    updateAutoBtn();
    unlockSettings();
    if (ss) { ss.autoPlaying = false; renderSessionTabs(); }
    return;
  }
  // Exhausted retries or stopped
  autoPlaying = false;
  updateAutoBtn();
  unlockSettings();
  if (ss) { ss.autoPlaying = false; renderSessionTabs(); }
}

function truncIncreaseAndRetry(btn) {
  const el = document.getElementById('maxTokensLimit');
  const cur = parseInt(el.value) || 16384;
  el.value = Math.min(cur * 2, 65536);
  btn.closest('div').querySelectorAll('button').forEach(b => b.disabled = true);
  stepOnce();
}

async function toggleAutoPlay() {
  saveSessionToState();  // sync globals → ss before async pipeline
  const ss = getActiveSession();
  if (ss ? ss.autoPlaying : autoPlaying) {
    autoPlaying = false;
    if (ss) { ss.autoPlaying = false; ss.waitingForLLM = false; }
    // Abort any in-flight LLM request immediately
    if (ss?.abortController) { ss.abortController.abort(); ss.abortController = null; }
    if (window._globalAbortCtrl) { window._globalAbortCtrl.abort(); window._globalAbortCtrl = null; }
    updateAutoBtn();
    unlockSettings();
    // Clear spinners immediately so UI doesn't look like it's still working
    document.getElementById('llmSpinner').style.display = 'none';
    document.getElementById('topSpinner').style.display = 'none';
    updateScaffoldingNodeState('reasoning', 'idle');
    updateScaffoldingNodeState('compact', 'idle');
    updateScaffoldingNodeState('interrupt', 'idle');
    updateScaffoldingNodeState('root_lm', 'idle');
    renderSessionTabs();
    // Update obs pause button text
    const _obsPB = document.getElementById('obsPauseBtn');
    if (_obsPB) _obsPB.innerHTML = '\u00BB Resume';
    return;
  }
  if (!sessionId) { alert('Start a game first'); return; }
  if (currentState.state !== 'NOT_FINISHED') return;

  // ── Branch-on-settings-change: if resumed session has different settings, auto-branch ──
  if (ss && ss._originalSettings && ss.stepCount > 0) {
    const curModel = getSelectedModel();
    const curScaff = activeScaffoldingType;
    const orig = ss._originalSettings;
    if ((curModel && orig.model && curModel !== orig.model) || (curScaff !== orig.scaffolding_type)) {
      const changes = [];
      if (curModel !== orig.model) changes.push(`model: ${orig.model} → ${curModel}`);
      if (curScaff !== orig.scaffolding_type) changes.push(`scaffolding: ${orig.scaffolding_type} → ${curScaff}`);
      if (!confirm(`Settings changed (${changes.join(', ')}).\nThis will create a branch from step ${ss.stepCount}. Continue?`)) return;
      // Auto-branch at current step
      try {
        const branchData = await fetchJSON('/api/sessions/branch', {
          parent_session_id: sessionId,
          step_num: ss.stepCount,
        });
        if (branchData.error) { alert(branchData.error); return; }
        // Switch to the new branch session
        const oldSid = ss.sessionId;
        sessionId = branchData.session_id;
        ss.sessionId = branchData.session_id;
        ss._originalSettings = { model: curModel, scaffolding_type: curScaff };
        ss.undoStack = [];
        ss.syncStepCounter = 0;
        activeSessionId = branchData.session_id;
        // Re-register under new id
        sessions.delete(oldSid);
        sessions.set(branchData.session_id, ss);
        saveSessionIndex();
        renderSessionTabs();
        logSessionEvent('branched_settings', ss.stepCount, { from: orig, to: { model: curModel, scaffolding_type: curScaff } });
      } catch (e) { alert('Branch failed: ' + e.message); return; }
    }
  }

  // Stop the blink guide
  const autoBtn = document.getElementById('autoPlayBtn');
  if (autoBtn) autoBtn.classList.remove('btn-blink');

  const mySessionId = sessionId; // capture for guard
  autoPlaying = true;
  lockHumanControls();
  lockSettings();
  updateAutoBtn();
  if (ss) {
    ss.autoPlaying = true;
    ss._obsResumedAt = performance.now();
    // Start elapsed timer if not already running
    if (!_obsElapsedTimer) {
      _obsElapsedTimer = setInterval(() => updateObsElapsed(ss), 1000);
    }
    // Generate session tab name on first autoplay: game - model - random
    if (!ss.tabLabel) {
      const model = (getSelectedModel() || 'agent').split('/').pop().split('-').slice(0, 2).join('-');
      const game = (ss.currentState.game_id || currentState.game_id || 'game').split('-')[0];
      const rand = Math.random().toString(36).slice(2, 5);
      ss.tabLabel = `${game} · ${model} · ${rand}`;
      ss.model = getSelectedModel() || '';
    }
  }
  renderSessionTabs();
  // Enter observability mode
  enterObsMode(ss);

  try {
  while (ss ? ss.autoPlaying : autoPlaying) {
    // Check game state from ss if available
    const gameState = ss ? ss.currentState.state : currentState.state;
    if (gameState !== 'NOT_FINISHED') break;

    // Guard: stop if session was closed
    if (!sessions.has(mySessionId)) { break; }

    let resp;
    try {
      resp = await askLLM(ss);
    } catch (e) {
      console.error('[autoPlay] askLLM threw:', e);
      resp = { error: e.message || 'Unknown error', model: getSelectedModel() };
    }
    if (ss && resp && resp.call_duration_ms) {
      ss.callDurations.push(resp.call_duration_ms);
    }

    if (ss ? !ss.autoPlaying : !autoPlaying) {
      // Paused — discard the reasoning entry and undo the call count (only if active)
      if (activeSessionId === mySessionId) {
        const discarded = getLastReasoningEntry();
        if (discarded && resp && !resp.error) { discarded.remove(); }
      }
      if (ss) ss.llmCallCount--;
      else llmCallCount--;
      break;
    }
    if (!sessions.has(mySessionId)) break;
    if (!resp || resp.error || resp.truncated || !resp.parsed) { if (ss) ss.autoPlaying = false; else autoPlaying = false; break; }

    // Agent spawn already executed steps inline — skip executePlan
    if (resp._alreadyExecuted) {
      // Steps already done; just continue the autoplay loop
    } else {
      const p = resp.parsed;

      // Normalize: single action becomes a 1-step plan
      const plan = (p.plan && Array.isArray(p.plan) && p.plan.length > 0)
        ? p.plan
        : (p.action !== undefined && p.action !== null)
          ? [{ action: p.action, data: p.data || {} }]
          : null;
      if (!plan) { if (ss) ss.autoPlaying = false; else autoPlaying = false; break; }

      const entry = (activeSessionId === mySessionId) ? getLastReasoningEntry() : null;
      const expected = resp.parsed.expected || null;
      let result;
      try {
        result = await executePlan(plan, resp, entry, expected, ss);
      } catch (planErr) {
        console.error('[autoPlay] executePlan threw:', planErr);
        // Continue the loop — the plan failed but game may still be playable
        await new Promise(r => setTimeout(r, 200));
        continue;
      }
      if (!result || result.interrupted) {
        await new Promise(r => setTimeout(r, 200));
      }
    }

    // Update session tabs to reflect progress
    if (ss) { ss.status = ss.currentState.state; }
    renderSessionTabs();
    saveSessionIndex();

    // If game is still going, brief pause so user can see the grid update
    const stillGoing = ss ? ss.currentState.state === 'NOT_FINISHED' : currentState.state === 'NOT_FINISHED';
    const stillPlaying = ss ? ss.autoPlaying : autoPlaying;
    if (stillPlaying && stillGoing) {
      await new Promise(r => setTimeout(r, 200));
    }
  }
  } catch (loopErr) {
    console.error('[autoPlay] loop crashed:', loopErr);
  }
  autoPlaying = false;
  if (ss) { ss.autoPlaying = false; }
  unlockSettings();
  updateAutoBtn();
  renderSessionTabs();
}

// ═══════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════
// PART 4: SESSION MANAGEMENT (Reset & Undo)
// ═══════════════════════════════════════════════════════════════════════════
// Manages session state: resetting to initial game state, undoing turns.
// Functions:
//   resetSession() — reset current game to initial state, save as session
//   undoStep() — undo the last turn(s) and restore grid state
// ═══════════════════════════════════════════════════════════════════════════

async function resetSession() {
  if (!currentState.game_id) return;
  if (!confirm('Reset this game? Current progress will be saved as a session.')) return;
  if (autoPlaying) toggleAutoPlay();
  const gameId = currentState.game_id;

  // Reset current session state so startGame doesn't block
  const cur = getActiveSession();
  if (cur) {
    cur.stepCount = 0;
    cur.moveHistory = [];
    cur.undoStack = [];
    cur.llmCallCount = 0;
    cur.turnCounter = 0;
    cur.sessionStepsBuffer = [];
    cur._cachedCompactSummary = '';
    cur._compactSummaryAtCall = 0;
    cur._compactSummaryAtStep = 0;
  }
  // Also reset globals
  stepCount = 0;
  moveHistory = [];
  undoStack = [];
  llmCallCount = 0;
  turnCounter = 0;

  // Clear reasoning panel
  document.getElementById('reasoningContent').innerHTML = '';

  await startGame(gameId);
}

async function undoStep() {
  if (!sessionId || undoStack.length === 0) return;

  // Find the turnId of the top entry and count all entries with that turnId
  const targetTurnId = undoStack[undoStack.length - 1].turnId;
  let stepsToUndo = 0;
  if (targetTurnId !== undefined) {
    for (let i = undoStack.length - 1; i >= 0; i--) {
      if (undoStack[i].turnId === targetTurnId) stepsToUndo++;
      else break;
    }
  } else {
    stepsToUndo = 1; // fallback for entries without turnId
  }

  // Pop all entries for this turn, keeping the earliest snapshot for state restore
  let earliestSnapshot = null;
  for (let i = 0; i < stepsToUndo; i++) {
    earliestSnapshot = undoStack.pop();
    if (moveHistory.length > 0) moveHistory.pop();
    if (sessionStepsBuffer.length > 0) sessionStepsBuffer.pop();
  }

  // Undo via Pyodide or server
  let data;
  if (_pyodideGameActive) {
    try {
      data = await pyodideUndo(stepsToUndo);
      data.session_id = sessionId;
    } catch (err) {
      console.warn('[PyodideGame] Undo failed:', err.message);
      data = {error: err.message};
    }
  } else {
    data = await fetchJSON('/api/undo', { session_id: sessionId, count: stepsToUndo });
  }
  if (data.error) {
    console.warn('Undo failed:', data.error);
  }

  // Restore local state from earliest snapshot
  stepCount = earliestSnapshot.stepCount;

  const restoredGrid = (data && !data.error) ? data.grid : earliestSnapshot.grid;
  currentState.grid = restoredGrid;
  currentState.state = earliestSnapshot.state;
  currentState.levels_completed = earliestSnapshot.levels_completed;
  currentChangeMap = null;
  renderGrid(restoredGrid);

  // Remove reasoning entries for this turn
  if (targetTurnId !== undefined) {
    document.querySelectorAll(`.reasoning-entry[data-turn-id="${targetTurnId}"]`).forEach(el => el.remove());
  } else {
    // Fallback: remove the topmost reasoning entry
    const topEntry = getLastReasoningEntry();
    if (topEntry) topEntry.remove();
  }

  document.getElementById('stepCounter').textContent = `Step ${stepCount}`;
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = earliestSnapshot.state;
  statusEl.className = 'status status-' + earliestSnapshot.state;
  document.getElementById('levelInfo').textContent = `Level ${earliestSnapshot.levels_completed}/${currentState.win_levels}`;

  updateUndoBtn();
}

// testModel() extracted to llm-controls.js (loaded before this file)

