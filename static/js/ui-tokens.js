// ═══════════════════════════════════════════════════════════════════════════
// ui-tokens.js — Token display and cost estimation
// Extracted from ui.js (Phase 24)
// Purpose: Token count display, context limits, compact context management
// ═══════════════════════════════════════════════════════════════════════════

// Global state for compact context
let _cachedCompactSummary = '';  // LLM-generated summary, cached until refreshed
let _compactSummaryAtCall = 0;   // llmCallCount when summary was last generated
let _compactSummaryAtStep = 0;   // stepCount when summary was last generated (history cutoff)
let _lastCompactPrompt = '';     // last prompt sent to compact model

function getCompactSettings() {
  const enabledEl = document.getElementById('compactContext');
  if (!enabledEl) return { enabled: false, after: null, contextLimitUnit: 'tokens', contextLimitVal: 64000, compactOnLevel: false };
  const enabled = enabledEl.checked;
  const afterVal = document.getElementById('compactAfter')?.value;
  const after = afterVal ? parseInt(afterVal) : null;  // null = disabled
  const unit = document.getElementById('contextLimitUnit')?.value || 'tokens';
  const rawVal = parseInt(document.getElementById('compactContextPct')?.value) || 64000;
  const compactOnLevel = document.getElementById('compactOnLevel')?.checked ?? true;
  return { enabled, after, contextLimitUnit: unit, contextLimitVal: rawVal, compactOnLevel };
}

function onContextLimitUnitChange() {
  const unit = document.getElementById('contextLimitUnit').value;
  const input = document.getElementById('compactContextPct');
  if (unit === 'pct') {
    input.value = 60;
  } else {
    input.value = 32000;
  }
}

// Spin context limit: dir=1 up, dir=-1 down
function spinContextLimit(dir) {
  const unit = document.getElementById('contextLimitUnit').value;
  const input = document.getElementById('compactContextPct');
  const val = parseInt(input.value) || 0;
  if (unit === 'tokens') {
    input.value = dir > 0 ? Math.min(val * 2, 2000000) : Math.max(Math.floor(val / 2), 1000);
  } else {
    input.value = dir > 0 ? Math.min(val + 5, 99) : Math.max(val - 5, 1);
  }
}

function getContextTokenLimit(compact, contextWindow) {
  if (compact.contextLimitUnit === 'tokens') return compact.contextLimitVal;
  return Math.floor(contextWindow * compact.contextLimitVal / 100);
}

function getSelectedModelContextWindow() {
  const model = getSelectedModel();
  const info = modelsData.find(m => m.name === model);
  return (info && info.context_window) || 128000;
}

function estimateTokens(text) {
  // Rough estimate: ~4 chars per token for English/code
  return Math.ceil((text || '').length / 4);
}

function trimHistoryForTokens(history, maxTokens) {
  // If history fits within budget, return as-is.
  // Otherwise drop grid snapshots from older steps, keeping last 5 with grids.
  const KEEP_GRIDS = 5;
  if (!history || history.length <= KEEP_GRIDS) return history;

  // Estimate token cost of full history with grids
  let totalChars = 0;
  for (const h of history) {
    totalChars += 60; // step line overhead
    if (h.grid) totalChars += h.grid.length * 30; // rough RLE per row
  }
  const est = Math.ceil(totalChars / 4);
  if (est <= maxTokens) return history; // fits, keep all

  // Strip grids from older entries, keep last KEEP_GRIDS with grids
  return history.map((h, i) => {
    if (i >= history.length - KEEP_GRIDS) return h;
    const { grid, ...rest } = h;
    return rest;
  });
}

function collectObservation(resp, ss) {
  if (!resp || !resp.parsed) return;
  const p = resp.parsed;
  const obs = ss || { llmObservations, stepCount };
  obs.llmObservations.push({
    step: obs.stepCount,
    observation: p.observation || '',
    reasoning: p.reasoning || '',
    action: p.action,
    analysis: p.analysis || '',
  });
}

function _syncCompactToMemoryTab() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) el.value = _cachedCompactSummary;
}

function _syncCompactPromptToMemoryTab() {
  // No-op: compact prompt textarea is now user-editable template
}

function applyCompactEdit() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) {
    _cachedCompactSummary = el.value;
    _compactSummaryAtCall = llmCallCount;
    _compactSummaryAtStep = stepCount;
  }
}

function buildCompactContextFallback() {
  // Heuristic fallback when LLM summary is not available yet.
  if (!llmObservations.length) return '';
  const parts = ['## COMPACT CONTEXT (accumulated knowledge from prior steps)'];
  const actionEffects = {};
  for (const o of llmObservations) {
    if (o.action !== undefined) {
      const aname = ACTION_NAMES[o.action] || `ACTION${o.action}`;
      if (!actionEffects[aname]) actionEffects[aname] = [];
      const reason = (o.reasoning || '').substring(0, 100);
      if (reason && actionEffects[aname].length < 3) actionEffects[aname].push(reason);
    }
  }
  const effectLines = Object.entries(actionEffects)
    .map(([a, reasons]) => `  ${a}: ${reasons[reasons.length - 1]}`)
    .join('\n');
  if (effectLines) parts.push(`Action effects:\n${effectLines}`);
  const last3 = llmObservations.slice(-3);
  if (last3.length) {
    const lines = last3.map(o => `  Step ${o.step}: ${o.observation || ''}`).join('\n');
    parts.push(`Recent observations:\n${lines}`);
  }
  const lastReasoning = llmObservations[llmObservations.length - 1]?.reasoning;
  if (lastReasoning) parts.push(`Current plan: ${lastReasoning}`);
  return parts.join('\n');
}

async function checkInterrupt(expected, grid, changeMap) {
  // Ask a cheap model whether the plan went as expected after a step.
  // Returns true if plan should be interrupted, false otherwise.
  const gridCompact = grid ? grid.map(r => r.join(',')).join('\n') : '';
  const changesText = changeMap ? 'Recent changes: ' + JSON.stringify(changeMap) : '';
  const template = getPrompt('linear.interrupt_prompt');
  const prompt = template
    .replace('{expected}', expected)
    .replace('{grid}', gridCompact)
    .replace('{changes}', changesText);

  const interruptModelSel = document.getElementById('interruptModelSelect')?.value || 'auto';
  const agentModel = getSelectedModel();

  function parseInterruptResult(text) {
    if (!text) return false;
    // Strip markdown fences, JSON wrappers, whitespace
    const clean = text.replace(/```[\s\S]*?```/g, m => m.replace(/```\w*/g, '').trim())
      .replace(/[{}"]/g, '').trim().toUpperCase();
    // Prompt asks "should we interrupt?" — YES means interrupt
    if (clean.startsWith('YES')) return true;
    if (/\bYES\b/.test(clean) && !/\bNO\b/.test(clean)) return true;
    if (/TRUE/.test(clean) && !/FALSE/.test(clean)) return true;
    return false;
  }

  const _intStart = performance.now();
  try {
    let rawResult = '';
    let _intResult;
    {
      // BYOK / Puter.js path
      const model = interruptModelSel === 'same' ? agentModel
        : (interruptModelSel === 'auto' || interruptModelSel === 'auto-fastest') ? null
        : interruptModelSel;
      const info = model ? getModelInfo(model) : getModelInfo(agentModel);
      const useModel = model || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
      if (useModel) {
        const result = await callLLM([{role: 'user', content: prompt}], useModel);
        rawResult = `${result} (${useModel})`;
        _syncInterruptResult(rawResult);
        _intResult = parseInterruptResult(result);
      }
    }
    // Record interrupt timing in timeline
    const _intDur = Math.round(performance.now() - _intStart);
    const _intSs = getActiveSession();
    if (_intSs && _intSs.timelineEvents) {
      _intSs.timelineEvents.push({ type: 'interrupt', agent_type: 'interrupt', duration: _intDur, turn: _intSs.llmCallCount, response_preview: rawResult });
      emitObsEvent(_intSs, { event: 'interrupt', agent: 'interrupt', duration_ms: _intDur, summary: (rawResult || '').slice(0, 200) });
    }
    if (_intResult !== undefined) return _intResult;
  } catch (e) {
    console.warn('Interrupt check failed:', e);
    _syncInterruptResult('ERROR: ' + e.message);
  }
  return false; // default: don't interrupt
}

function _syncInterruptResult(text) {
  const el = document.getElementById('memoryInterruptResult');
  if (el) el.value = text;
}

async function buildCompactContext(ss) {
  // Use LLM to summarize the game history into key takeaways.
  // Falls back to heuristic if LLM call fails.
  // Re-summarize every 5 calls to stay current.
  // ss = SessionState (optional, falls back to globals)
  const _ss = ss || { _cachedCompactSummary, llmCallCount, _compactSummaryAtCall, _compactSummaryAtStep, llmObservations, moveHistory, currentState, _lastCompactPrompt, sessionId: sessionId, stepCount };
  const REFRESH_INTERVAL = 5;
  if (_ss._cachedCompactSummary && (_ss.llmCallCount - _ss._compactSummaryAtCall) < REFRESH_INTERVAL) {
    return _ss._cachedCompactSummary;
  }

  // Build a summary prompt from observations + history
  const obsText = _ss.llmObservations.map(o =>
    `Step ${o.step}: action=${ACTION_NAMES[o.action] || o.action}, obs="${o.observation || ''}", reasoning="${(o.reasoning || '').substring(0, 150)}"`
  ).join('\n');

  const histText = _ss.moveHistory.slice(-20).map(h =>
    `Step ${h.step}: ${ACTION_NAMES[h.action] || '?'} -> ${h.result_state || '?'}`
  ).join('\n');

  const promptTemplate = getPrompt('linear.compact_prompt');

  const summaryPrompt = `${promptTemplate}

OBSERVATIONS FROM GAMEPLAY:
${obsText}

RECENT MOVE HISTORY:
${histText}

Progress: Level ${_ss.currentState.levels_completed || 0}/${_ss.currentState.win_levels || 0}`;

  // Store the prompt for display in Memory tab
  _ss._lastCompactPrompt = summaryPrompt;
  if (!ss) _lastCompactPrompt = summaryPrompt;
  _syncCompactPromptToMemoryTab();

  // Determine compact model
  const compactModelSel = document.getElementById('compactModelSelectTop').value;
  const agentModel = getSelectedModel();
  // 'auto' = cheapest same provider (server decides), 'auto-fastest' = fastest same provider, 'same' = agent model, else specific model
  const compactModel = compactModelSel === 'same' ? agentModel
    : (compactModelSel === 'auto' || compactModelSel === 'auto-fastest') ? null
    : compactModelSel;

  try {
    let summary;
    const _compactStart = performance.now();
    const useCompactModel = compactModel || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
    if (useCompactModel) {
      summary = await callLLM([{role: 'user', content: summaryPrompt}], useCompactModel);
    }
    if (summary) {
      const _compactDur = Math.round(performance.now() - _compactStart);
      const _tlTarget = ss || getActiveSession();
      if (_tlTarget && _tlTarget.timelineEvents) {
        _tlTarget.timelineEvents.push({ type: 'compact', agent_type: 'compact', duration: _compactDur, turn: _ss.llmCallCount, response_preview: (summary || '').slice(0, 500) });
        emitObsEvent(_tlTarget, { event: 'compact', agent: 'compact', duration_ms: _compactDur, summary: (summary || '').slice(0, 200) });
      }
      _ss._cachedCompactSummary = `## COMPACT CONTEXT (LLM-summarized game knowledge)\n${summary}`;
      _ss._compactSummaryAtCall = _ss.llmCallCount;
      _ss._compactSummaryAtStep = _ss.stepCount;
      if (!ss) { _cachedCompactSummary = _ss._cachedCompactSummary; _compactSummaryAtCall = _ss._compactSummaryAtCall; _compactSummaryAtStep = _ss._compactSummaryAtStep; }
      _syncCompactToMemoryTab();
      return _ss._cachedCompactSummary;
    }
  } catch (e) {
    console.warn('Compact summary LLM call failed, using fallback:', e);
  }
  const fallback = buildCompactContextFallback();
  if (fallback) {
    _ss._cachedCompactSummary = fallback;
    if (!ss) _cachedCompactSummary = fallback;
    _syncCompactToMemoryTab();
  }
  return fallback;
}

async function manualCompact() {
  if (!sessionId || moveHistory.length === 0) return;
  saveSessionToState();  // sync globals → ss
  const ss = getActiveSession();
  const btn = document.getElementById('compactBtn');
  btn.disabled = true;
  btn.textContent = '\u23f3 Compacting...';
  try {
    _cachedCompactSummary = '';  // force refresh
    if (ss) ss._cachedCompactSummary = '';
    const summary = await buildCompactContext(ss);
    if (summary) {
      _cachedCompactSummary = summary;
      if (ss) ss._cachedCompactSummary = summary;
      _syncCompactToMemoryTab();
      _compactSummaryAtCall = llmCallCount;
      _compactSummaryAtStep = stepCount;
      if (ss) { ss._compactSummaryAtCall = llmCallCount; ss._compactSummaryAtStep = stepCount; }
      logSessionEvent('compact', stepCount, { call_count: llmCallCount, history_length: moveHistory.length, trigger: 'manual' });
      const content = document.getElementById('reasoningContent');
      if (content.querySelector('.empty-state')) content.innerHTML = '';
      const entry = document.createElement('div');
      entry.className = 'reasoning-entry';
      entry.innerHTML = `<div class="step-label" style="color:var(--purple);">Context compacted at step ${stepCount} (${llmCallCount} calls)</div>`;
      content.appendChild(entry);
      scrollReasoningToBottom();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '\ud83d\udcdc Compact';
  }
}

function getThinkingLevel() {
  return document.querySelector('input[name="thinkingLevel"]:checked')?.value || 'low';
}

function getToolsMode() {
  return document.querySelector('input[name="toolsMode"]:checked')?.value || 'off';
}

function getPlanningMode() {
  return document.querySelector('input[name="planMode"]:checked')?.value || 'off';
}

function getMaxTokens() {
  return parseInt(document.getElementById('maxTokensLimit')?.value) || 16384;
}

function spinMaxTokens(dir) {
  const el = document.getElementById('maxTokensLimit');
  el.value = Math.max(1024, Math.min(65536, (parseInt(el.value) || 16384) + dir * 1024));
}

function shouldAskAdaptive() {
  // In adaptive mode, ask the LLM if no level progress in last 5 steps
  if (moveHistory.length < 5) return false;
  const last5 = moveHistory.slice(-5);
  const levels = last5.map(h => h.levels ?? 0);
  return new Set(levels).size <= 1;
}
