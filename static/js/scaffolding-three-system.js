// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:54
// PURPOSE: Three-System and Two-System scaffolding for ARC-AGI-3. Implements
//   multi-agent cognitive architecture: Planner (strategic), Actor (tactical), and
//   Monitor (evaluation) LLM agents with working memory management. Provides
//   runThreeSystemStep(), runTwoSystemStep(), and prompt template loading from
//   window.PROMPTS.three_system.*. Depends on callLLM, getPrompt (scaffolding.js).
//   Extracted from scaffolding.js in Phase 5.
// SRP/DRY check: Pass — three/two-system logic fully separated from other scaffolding types
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING-THREE-SYSTEM — Three-System / Two-System scaffolding
// Extracted from scaffolding.js — Phase 5 modularization
// Depends on: callLLM, getPrompt (scaffolding.js)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE THREE-SYSTEM / TWO-SYSTEM SCAFFOLDING
// ═══════════════════════════════════════════════════════════════════════════

// -- Prompt templates (loaded from prompts/three_system/*.txt via window.PROMPTS) --

const TS_PLANNER_SYSTEM_BODY = getPrompt('three_system.planner_system');
const TS_PLANNER_SYSTEM_BODY_NO_WM = getPrompt('three_system.planner_system_no_wm');
const TS_PLANNER_CONTEXT = window.PROMPTS.three_system.planner_context;
const TS_PLANNER_CONTEXT_NO_WM = window.PROMPTS.three_system.planner_context_no_wm;
const TS_WM_SYSTEM_PROMPT = getPrompt('three_system.wm_system');
const TS_WM_CONTEXT = window.PROMPTS.three_system.wm_context;
const TS_MONITOR_PROMPT = window.PROMPTS.three_system.monitor;

/**
 * Template fill for Three-System (TS) prompts.
 * Supports {{/}} escaping for literal brace output.
 * NOTE: Do NOT replace with _asFill — _asFill lacks {{ }} escape support.
 */
function _tsTemplateFill(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, key) => vars[key] !== undefined ? vars[key] : '')
                 .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}

// -- Color histogram & region map helpers --
function _computeColorHistogram(grid) {
  const counts = {};
  for (const row of grid) for (const c of row) counts[c] = (counts[c] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([c, n]) => `Color ${c}: ${n} cells`).join('\n');
}

function _computeRegionMap(grid) {
  if (!grid || !grid.length) return '(empty grid)';
  const rows = grid.length, cols = grid[0].length;
  const visited = Array.from({length: rows}, () => new Uint8Array(cols));
  const regions = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (visited[r][c]) continue;
      const color = grid[r][c];
      const stack = [[r, c]];
      let minR = r, maxR = r, minC = c, maxC = c, count = 0;
      while (stack.length) {
        const [cr, cc] = stack.pop();
        if (cr < 0 || cr >= rows || cc < 0 || cc >= cols) continue;
        if (visited[cr][cc] || grid[cr][cc] !== color) continue;
        visited[cr][cc] = 1;
        count++;
        if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
        if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
        stack.push([cr-1,cc],[cr+1,cc],[cr,cc-1],[cr,cc+1]);
      }
      if (count >= 2) regions.push({color, count, minR, maxR, minC, maxC});
    }
  }
  regions.sort((a, b) => b.count - a.count);
  return regions.slice(0, 30).map(r =>
    `Color ${r.color}: ${r.count} cells, rows ${r.minR}-${r.maxR}, cols ${r.minC}-${r.maxC}`
  ).join('\n') || '(no regions)';
}

// -- WM query handler (pure data, no LLM) --
function _tsHandleWmQuery(tsState, tool, step, stepRange) {
  const snapshots = tsState.snapshots;
  if (step !== undefined && step !== null) {
    const snap = snapshots.find(s => s.step === step);
    if (!snap) return `(no data for step ${step})`;
    if (tool === 'change_map') return snap.change_map_text || '(no changes)';
    if (tool === 'histogram') return _computeColorHistogram(snap.grid || []);
    if (tool === 'grid') return (snap.grid || []).map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n');
  } else if (stepRange && stepRange.length >= 2) {
    const [start, end] = [stepRange[0], stepRange[stepRange.length - 1]];
    const snaps = snapshots.filter(s => s.step >= start && s.step <= end);
    if (!snaps.length) return `(no data for steps ${start}-${end})`;
    return snaps.map(snap => {
      const aname = ACTION_NAMES[snap.action] || '?';
      let detail = '';
      if (tool === 'change_map') detail = snap.change_map_text || '  (no changes)';
      else if (tool === 'histogram') detail = _computeColorHistogram(snap.grid || []);
      else if (tool === 'grid') detail = (snap.grid || []).map((r, i) => `  Row ${i}: ${compressRowJS(r)}`).join('\n');
      return `Step ${snap.step} (${aname}):\n${detail}`;
    }).join('\n');
  }
  return '(invalid query — specify step or step_range)';
}

// -- Simulate actions using WM rules --
async function _tsSimulateActions(actions, tsState, context, settings) {
  const rulesDoc = tsState.rules_doc;
  if (!rulesDoc) return actions.map(() => 'unknown — no rules discovered yet, try it and observe');
  const wmModel = settings.wm_model || settings.model || 'gemini-2.5-flash';
  const wmThinking = settings.wm_thinking_level || 'low';
  const wmMaxTokens = Math.min(parseInt(settings.wm_max_tokens) || 8192, 65536);
  const actionDescs = actions.map(act => {
    const a = act.action || 0;
    const aname = ACTION_NAMES[a] || `ACTION${a}`;
    const data = act.data || {};
    return a === 6 && data.x !== undefined ? `${aname}@(${data.x},${data.y})` : aname;
  });
  const prompt = `You are a World Model predicting game outcomes.

## RULES (v${tsState.rules_version})
${rulesDoc}

## CURRENT STATE
Game: ${context.game_id || '?'} | Step: ${context.step_num || 0} | Levels: ${context.levels_completed || 0}/${context.win_levels || 0}

## ACTIONS TO PREDICT
${actionDescs.map((d, i) => `${i + 1}. ${d}`).join('\n')}

For each action, predict what would happen based on your rules.
Respond with EXACTLY this JSON:
{"predictions": ["<prediction for action 1>", "<prediction for action 2>", ...]}

If uncertain, say "uncertain — <best guess>". Keep each prediction under 100 chars.`;
  try {
    const raw = await callLLM(
      [{role: 'system', content: prompt}],
      wmModel, { maxTokens: wmMaxTokens, thinkingLevel: wmThinking }
    );
    const parsed = extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();
    if (parsed && parsed.predictions) {
      const preds = parsed.predictions;
      while (preds.length < actions.length) preds.push('no prediction');
      return preds.slice(0, actions.length);
    }
  } catch (e) { console.warn('[ts_simulate] error:', e); }
  return actions.map(() => 'prediction unavailable');
}

// -- Recover truncated rules_document from raw WM response --
function _tsRecoverTruncatedRules(raw) {
  if (!raw) return null;
  const m = raw.match(/"rules_document"\s*:\s*"/);
  if (!m) return null;
  const start = m.index + m[0].length;
  let result = '', i = start;
  while (i < raw.length) {
    const c = raw[i];
    if (c === '\\' && i + 1 < raw.length) {
      const nc = raw[i + 1];
      if (nc === 'n') result += '\n';
      else if (nc === 't') result += '\t';
      else if (nc === '"') result += '"';
      else if (nc === '\\') result += '\\';
      else result += nc;
      i += 2;
    } else if (c === '"') break;
    else { result += c; i++; }
  }
  return result.trim().length > 20 ? result.trim() : null;
}

// -- WM update REPL loop --
async function _tsRunWmUpdate(tsState, context, settings, waitEl, isActive) {
  const wmModel = settings.wm_model || settings.model || 'gemini-2.5-flash';
  const wmThinking = settings.wm_thinking_level || 'low';
  const wmMaxTokens = Math.min(parseInt(settings.wm_max_tokens) || 16384, 65536);
  const maxTurns = parseInt(settings.wm_max_turns) || 5;

  const rulesDoc = tsState.rules_doc || '(No rules yet — this is your first analysis!)';
  const obs = tsState.observations;
  const obsLines = obs.map(o => {
    const aname = ACTION_NAMES[o.action] || '?';
    let line = `Step ${o.step}: ${aname} -> levels=${o.levels || '?'}, state=${o.state || '?'}`;
    const cm = typeof o.change_map_text === 'object' ? (o.change_map_text?.change_map_text || '') : (o.change_map_text || '');
    if (cm) line += '\n  ' + cm.trim().split('\n').slice(0, 4).join('\n  ');
    return line;
  });
  const obsText = obsLines.length ? obsLines.join('\n') : '(no new observations)';
  const obsStart = obs.length ? obs[0].step : 0;
  const obsEnd = obs.length ? obs[obs.length - 1].step : 0;

  const conversation = [];
  const wmLog = [];

  for (let turn = 1; turn <= maxTurns; turn++) {
    let ctxText = _tsTemplateFill(TS_WM_CONTEXT, {
      game_id: context.game_id || '?', step_num: context.step_num || 0,
      levels_done: context.levels_completed || 0, win_levels: context.win_levels || 0,
      rules_version: tsState.rules_version, rules_doc: rulesDoc,
      observations_text: obsText, obs_start: obsStart, obs_end: obsEnd,
      turn_num: turn, max_turns: maxTurns,
    });
    if (conversation.length) ctxText += '\n\n## WORLD MODEL CONVERSATION\n' + conversation.join('\n\n');
    if (turn === maxTurns) ctxText += '\n\n!! THIS IS YOUR LAST TURN — you MUST commit your rules document now. !!';

    const prompt = TS_WM_SYSTEM_PROMPT + '\n\n' + ctxText;
    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], wmModel, { maxTokens: wmMaxTokens, thinkingLevel: wmThinking });
    } catch (e) {
      console.error(`[ts_wm] turn ${turn} failed:`, e);
      wmLog.push({turn, type: 'error', error: e.message, duration_ms: 0});
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    // Emit obs event for WM call
    emitObsEvent(getActiveSession(), { event: 'wm_update', agent: 'world_model', model: wmModel, duration_ms: durMs, summary: (raw || '').slice(0, 200) });

    const parsed = extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.type) {
      const recovered = _tsRecoverTruncatedRules(raw);
      if (recovered) {
        tsState.rules_doc = recovered;
        tsState.rules_version++;
        tsState.observations = [];
        wmLog.push({turn, type: 'commit', confidence: 0.5, duration_ms: durMs, recovered: true});
        break;
      }
      wmLog.push({turn, type: 'error', error: 'unparseable', duration_ms: durMs});
      break;
    }

    if (parsed.type === 'query') {
      const tool = parsed.tool || 'change_map';
      const resultText = _tsHandleWmQuery(tsState, tool, parsed.step, parsed.step_range);
      const truncResult = resultText.length > 2000 ? resultText.substring(0, 2000) + '\n... (truncated)' : resultText;
      conversation.push(`[Turn ${turn}] Queried '${tool}':\n${truncResult}`);
      wmLog.push({turn, type: 'query', tool, duration_ms: durMs});
    } else if (parsed.type === 'commit') {
      const newRules = parsed.rules_document || '';
      if (newRules) {
        tsState.rules_doc = newRules;
        tsState.rules_version++;
        tsState.observations = [];
        wmLog.push({turn, type: 'commit', confidence: parsed.confidence || 0.5, duration_ms: durMs});
        break;
      }
      wmLog.push({turn, type: 'commit_empty', duration_ms: durMs});
    }
  }

  return {
    ran_update: true, wm_log: wmLog,
    rules_version: tsState.rules_version,
    rules_preview: (tsState.rules_doc || '').substring(0, 200),
  };
}

// -- Monitor check --
async function _tsMonitorCheck(step, expected, changeData, gameState, settings, tsState) {
  const monitorModel = settings.monitor_model || settings.model || 'gemini-2.5-flash';
  const monitorThinking = settings.monitor_thinking_level || 'off';
  const monitorMaxTokens = Math.min(parseInt(settings.monitor_max_tokens) || 4096, 16384);

  const actionName = ACTION_NAMES[step.action] || `ACTION${step.action}`;
  const changeSummary = changeData?.change_map_text || (changeData?.change_count > 0 ? `${changeData.change_count} cells changed` : 'no changes');
  const levelChange = (gameState.levels_completed || 0) > (gameState.prev_levels || 0) ? 'LEVEL UP!' : 'same level';
  const replanCooldown = parseInt(settings.replan_cooldown) || 3;
  const plansSince = tsState.plans_since_replan || 99;
  const onCooldown = plansSince < replanCooldown;
  const cooldownLine = onCooldown
    ? `Replan cooldown: ON COOLDOWN (${plansSince}/${replanCooldown} plans) — you MUST return CONTINUE`
    : `Replan cooldown: available (${plansSince}/${replanCooldown} plans since last replan)`;

  const prompt = _tsTemplateFill(TS_MONITOR_PROMPT, {
    game_id: gameState.game_id || '?', step_num: gameState.step_num || 0,
    levels_done: gameState.levels_completed || 0, win_levels: gameState.win_levels || 0,
    action_name: actionName, expected: expected,
    change_summary: changeSummary, level_change: levelChange,
    state: gameState.state || 'NOT_FINISHED',
    replan_cooldown: replanCooldown, cooldown_line: cooldownLine,
  });

  const t0 = performance.now();
  try {
    const raw = await callLLM([{role: 'system', content: prompt}], monitorModel, { maxTokens: monitorMaxTokens, thinkingLevel: monitorThinking });
    const durMs = Math.round(performance.now() - t0);
    const parsed = extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();
    if (!parsed) return {verdict: 'CONTINUE', reason: 'monitor parse error', discovery: null, duration_ms: durMs};

    let verdict = (parsed.verdict || 'CONTINUE').toUpperCase();
    if (verdict !== 'CONTINUE' && verdict !== 'REPLAN') verdict = 'CONTINUE';

    let suppressed = false;
    if (verdict === 'REPLAN' && onCooldown) {
      verdict = 'CONTINUE';
      suppressed = true;
    } else if (verdict === 'REPLAN') {
      tsState.plans_since_replan = 0;
    }

    // Store discovery in observations
    if (parsed.discovery) {
      tsState.observations.push({
        step: gameState.step_num || 0, action: step.action,
        levels: gameState.levels_completed || 0, state: gameState.state || 'NOT_FINISHED',
        change_map_text: changeSummary, discovery: parsed.discovery,
      });
    }

    // Emit obs event for monitor
    emitObsEvent(getActiveSession(), { event: 'monitor_call', agent: 'monitor', model: monitorModel, duration_ms: durMs, summary: `${verdict}${parsed.reason ? ': ' + parsed.reason : ''}` });
    return {verdict, reason: parsed.reason || '', discovery: parsed.discovery || null, duration_ms: durMs, replan_suppressed: suppressed};
  } catch (e) {
    console.error('[ts_monitor] failed:', e);
    return {verdict: 'CONTINUE', reason: 'monitor error', discovery: null, duration_ms: 0};
  }
}

// -- Main Three-System planner --
async function askLLMThreeSystem(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const t0Total = performance.now();
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const plannerModel = settings.planner_model || settings.model || model;
  const plannerThinking = settings.planner_thinking_level || settings.thinking_level || 'low';
  const plannerMaxTokens = Math.min(parseInt(settings.planner_max_tokens || settings.max_tokens) || 16384, 65536);
  const maxTurns = parseInt(settings.planner_max_turns) || 10;
  const maxPlan = parseInt(settings.max_plan_length) || 15;
  const minPlan = parseInt(settings.min_plan_length) || 3;
  const wmUpdateEvery = parseInt(settings.wm_update_every) || 5;
  const wmModel = settings.wm_model; // empty = WM disabled (two_system mode)
  const wmEnabled = !!wmModel;
  const scaffoldingType = settings.scaffolding || 'three_system';

  // Get/init tsState from session
  if (!_cur._tsState) {
    _cur._tsState = {
      rules_doc: '', rules_version: 0,
      observations: [], snapshots: [],
      turn_count: 0, plans_since_replan: 99,
    };
  }
  const ss = _cur._tsState;
  ss.turn_count++;

  const context = {
    grid: _cur.currentState.grid || [],
    available_actions: _cur.currentState.available_actions || [],
    history: historyForLLM || [],
    change_map: _cur.currentChangeMap || {},
    levels_completed: _cur.currentState.levels_completed || 0,
    win_levels: _cur.currentState.win_levels || 0,
    game_id: _cur.currentState.game_id || 'unknown',
    state: _cur.currentState.state || '',
    step_num: _cur.stepCount || 0,
    compact_context: compactBlock || '',
  };

  // 1. World Model update if enough observations
  let wmInfo = {ran_update: false, wm_log: [], rules_version: ss.rules_version, rules_preview: (ss.rules_doc || '').substring(0, 200)};
  if (wmEnabled && ss.observations.length >= wmUpdateEvery) {
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode('WM updating rules... '));
        if (timer) label.appendChild(timer);
      }
    }
    wmInfo = await _tsRunWmUpdate(ss, context, settings, waitEl, isActiveFn);
  }

  // 2. Planner REPL
  const desc = getPrompt('shared.arc_description');
  const planLenVars = {min_plan_length: minPlan, max_plan_length: maxPlan};
  const plannerSystemPrompt = wmEnabled
    ? desc + '\n\n' + _tsTemplateFill(TS_PLANNER_SYSTEM_BODY, planLenVars)
    : desc + '\n\n' + _tsTemplateFill(TS_PLANNER_SYSTEM_BODY_NO_WM, planLenVars);

  const actionDesc = context.available_actions.map(a => `${a}=${ACTION_NAMES[a] || 'ACTION' + a}`).join(', ');

  // History block
  let historyBlock = '';
  const hist = context.history;
  if (hist.length) {
    const lines = hist.map(h => {
      const aname = ACTION_NAMES[h.action] || '?';
      const obs = (h.observation || '').substring(0, 500);
      let line = `  Step ${h.step || '?'}: ${aname} -> levels=${h.levels || '?'} | ${obs}`;
      if (h.reasoning) line += `\n    Reasoning: ${h.reasoning.substring(0, 500)}`;
      return line;
    });
    historyBlock = `## HISTORY (all ${hist.length})\n` + lines.join('\n');
  }

  // Change map block
  const cm = context.change_map;
  let changeMapBlock = '';
  if (typeof cm === 'object' && cm?.change_map_text) changeMapBlock = cm.change_map_text;
  else if (typeof cm === 'string' && cm) changeMapBlock = cm;

  // Grid block
  const gridText = context.grid.length ? context.grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n') : '(no grid)';
  const gridBlock = `## GRID (RLE)\n${gridText}`;

  const rulesDoc = ss.rules_doc || '(No rules discovered yet — explore to learn!)';
  const conversation = [];
  const plannerLog = [];

  for (let turn = 1; turn <= maxTurns; turn++) {
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`Planner turn ${turn}/${maxTurns}... `));
        if (timer) label.appendChild(timer);
      }
    }

    const ctxVars = {
      game_id: context.game_id, state: context.state,
      levels_done: context.levels_completed, win_levels: context.win_levels,
      step_num: context.step_num, action_desc: actionDesc,
      memory_block: '', history_block: historyBlock,
      change_map_block: changeMapBlock, grid_block: gridBlock,
      rules_version: ss.rules_version, rules_doc: rulesDoc,
      turn_num: turn, max_turns: maxTurns,
    };
    let ctxText = wmEnabled
      ? _tsTemplateFill(TS_PLANNER_CONTEXT, ctxVars)
      : _tsTemplateFill(TS_PLANNER_CONTEXT_NO_WM, ctxVars);
    if (conversation.length) ctxText += '\n\n## PLANNER CONVERSATION\n' + conversation.join('\n\n');

    const prompt = plannerSystemPrompt + '\n\n' + ctxText;
    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], plannerModel, { maxTokens: plannerMaxTokens, thinkingLevel: plannerThinking });
    } catch (e) {
      console.error(`[ts_planner] turn ${turn} failed:`, e);
      plannerLog.push({turn, type: 'error', error: e.message, duration_ms: 0});
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    // Emit obs event for planner call
    emitObsEvent(getActiveSession(), { event: 'planner_call', agent: 'planner', model: plannerModel, duration_ms: durMs, summary: (raw || '').slice(0, 200) });

    const parsed = extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.type) {
      plannerLog.push({turn, type: 'error', error: 'unparseable', duration_ms: durMs, raw});
      if (turn === maxTurns) break;
      conversation.push(`[Turn ${turn}] (unparseable response, trying again)`);
      continue;
    }

    if (parsed.type === 'simulate') {
      if (!wmEnabled) {
        conversation.push(`[Turn ${turn}] No World Model available — cannot simulate. Use 'analyze' or 'commit' instead.`);
        plannerLog.push({turn, type: 'simulate_skipped', duration_ms: durMs});
        continue;
      }
      const actions = parsed.actions || [];
      const question = parsed.question || '';
      const predictions = await _tsSimulateActions(actions, ss, context, settings);
      const resultText = `Simulation of ${actions.length} action(s):\n` +
        actions.map((act, i) => `  ${i + 1}. ${ACTION_NAMES[act.action || 0] || '?'}: ${predictions[i]}`).join('\n');
      conversation.push(`[Turn ${turn}] You simulated: ${question}\nResult: ${resultText}`);
      plannerLog.push({turn, type: 'simulate', actions: actions.map(a => a.action || 0), predictions: predictions.slice(0, 5), duration_ms: durMs});

    } else if (parsed.type === 'analyze') {
      const tool = parsed.tool || 'region_map';
      let resultText;
      if (tool === 'region_map') resultText = _computeRegionMap(context.grid);
      else if (tool === 'histogram') resultText = _computeColorHistogram(context.grid);
      else if (tool === 'change_map' && changeMapBlock) resultText = changeMapBlock;
      else resultText = '(no data available)';
      conversation.push(`[Turn ${turn}] Analyzed '${tool}':\n${resultText}`);
      plannerLog.push({turn, type: 'analyze', tool, duration_ms: durMs});

    } else if (parsed.type === 'commit') {
      const plan = parsed.plan || [];
      const goal = parsed.goal || '';
      const observation = parsed.observation || '';
      const reasoning = parsed.reasoning || '';
      const avail = new Set(context.available_actions);
      const validPlan = [];
      for (const step of plan.slice(0, maxPlan)) {
        if (step.action !== undefined && avail.has(step.action)) {
          validPlan.push({action: parseInt(step.action), data: step.data || {}, expected: step.expected || ''});
        }
      }

      // Reject short plans (unless last turn)
      if (validPlan.length < minPlan && turn < maxTurns) {
        conversation.push(`[Turn ${turn}] REJECTED: Your plan has only ${validPlan.length} action(s). The minimum is ${minPlan}. Think further ahead — plan a sequence of at least ${minPlan} actions to reach your goal. Try again.`);
        plannerLog.push({turn, type: 'rejected', plan_length: validPlan.length, min_required: minPlan, duration_ms: durMs});
        continue;
      }

      // Last turn: pad if needed
      if (validPlan.length < minPlan) {
        const exploratory = context.available_actions.filter(a => a !== 0);
        let idx = 0;
        while (validPlan.length < minPlan && exploratory.length) {
          validPlan.push({action: exploratory[idx % exploratory.length], data: {}, expected: 'explore'});
          idx++;
        }
      }

      plannerLog.push({turn, type: 'commit', plan_length: validPlan.length, raw_plan_length: plan.length, duration_ms: durMs});
      ss.plans_since_replan = (ss.plans_since_replan || 0) + 1;
      const totalDur = Math.round(performance.now() - t0Total);

      return {
        raw, thinking: null,
        parsed: {
          observation, reasoning,
          action: validPlan.length ? validPlan[0].action : 0,
          data: validPlan.length ? validPlan[0].data || {} : {},
          plan: validPlan,
        },
        model: plannerModel, scaffolding: scaffoldingType,
        _clientSide: true,
        three_system: {
          turn: ss.turn_count, goal,
          planner_log: plannerLog, world_model: wmInfo,
        },
        call_duration_ms: totalDur,
      };
    }
  }

  // Fallback: exploratory plan
  const exploratory = context.available_actions.filter(a => a !== 0);
  const fallbackPlan = [];
  let idx = 0;
  const target = Math.max(minPlan, 6);
  while (fallbackPlan.length < target && exploratory.length) {
    fallbackPlan.push({action: exploratory[idx % exploratory.length], data: {}, expected: 'explore'});
    idx++;
  }
  const totalDur = Math.round(performance.now() - t0Total);

  return {
    raw: '', thinking: null,
    parsed: {
      observation: 'Planner could not commit a plan',
      reasoning: 'Max REPL turns reached or errors occurred, falling back to exploration',
      action: fallbackPlan.length ? fallbackPlan[0].action : 0,
      data: {},
      plan: fallbackPlan,
    },
    model: plannerModel, scaffolding: scaffoldingType,
    _clientSide: true, _fallbackAction: true,
    three_system: {
      turn: ss.turn_count, goal: 'explore — planner fallback',
      planner_log: plannerLog, world_model: wmInfo,
    },
    call_duration_ms: totalDur,
  };
}
