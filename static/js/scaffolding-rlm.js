// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:54
// PURPOSE: RLM (Reflective Language Model) scaffolding for ARC-AGI-3. Implements
//   multi-turn reflective reasoning loop: system prompt construction with plan horizon,
//   iterative LLM calls with observation feedback, FINAL(...) marker detection for
//   convergence, and RLM response parsing into action/plan structures. Provides
//   buildRlmSystemPrompt() and runRlmLoop(). Depends on callLLM, getPrompt (scaffolding.js),
//   findFinalMarker, extractJsonFromText (json-parsing.js). Extracted from scaffolding.js
//   in Phase 5.
// SRP/DRY check: Pass — RLM logic fully separated from other scaffolding types
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING-RLM — RLM (Reflective Language Model) scaffolding
// Extracted from scaffolding.js — Phase 5 modularization
// Depends on: callLLM, getPrompt (scaffolding.js), findFinalMarker, extractJsonFromText (json-parsing.js)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE RLM SCAFFOLDING
// ═══════════════════════════════════════════════════════════════════════════

const _RLM_SYSTEM_PROMPT_TEMPLATE = getPrompt('rlm.system_prompt');

function buildRlmSystemPrompt(planHorizon) {
  const planInstructions = `For multi-step plans (up to ${planHorizon} steps ahead):\n` +
    `  FINAL({"plan": [{"action": <int>, "observation": "..."}, ...], "reasoning": "..."})\n` +
    `Output a plan of 1-${planHorizon} actions. If the next moves are obvious, include them all. If unsure, output a plan of just 1 action.\n\n`;
  return _RLM_SYSTEM_PROMPT_TEMPLATE
    .replace('{plan_instructions}', planInstructions)
    .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}

const _RLM_USER_FIRST_TEMPLATE = getPrompt('rlm.user_first');
const _RLM_USER_CONTINUE_TEMPLATE = getPrompt('rlm.user_continue');

function _rlmPlanInstruction(planHorizon) {
  return `Output a plan of 1-${planHorizon} actions.`;
}
function buildRlmUserFirst(planHorizon) {
  return _RLM_USER_FIRST_TEMPLATE.replace('{plan_instruction}', _rlmPlanInstruction(planHorizon));
}
function buildRlmUserContinue(planHorizon) {
  return _RLM_USER_CONTINUE_TEMPLATE.replace('{plan_instruction}', _rlmPlanInstruction(planHorizon));
}

// _rlmFindFinal → findFinalMarker, _extractJsonFromText → extractJsonFromText
// Both defined in utils/json-parsing.js (loaded before scaffolding.js)

function _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon) {
  let parsed = null;
  if (finalAnswer) {
    parsed = extractJsonFromText(finalAnswer);
    if (!parsed) {
      try { parsed = JSON.parse(finalAnswer); } catch {}
    }
  }
  // Fallback: try to extract from last response
  if (!parsed && iterationsLog.length) {
    const lastResp = iterationsLog[iterationsLog.length - 1].response || '';
    parsed = extractJsonFromText(lastResp);
  }
  if (!parsed) return null;
  // Normalize: "actions" array → "plan"
  if (parsed.actions && Array.isArray(parsed.actions) && !parsed.plan) {
    parsed.plan = parsed.actions;
    delete parsed.actions;
  }
  // Always wrap single action as 1-element plan
  if (parsed.action !== undefined && !parsed.plan) {
    parsed.plan = [{ action: parsed.action, data: parsed.data || {} }];
  }
  // Validate plan entries
  if (parsed.plan && Array.isArray(parsed.plan)) {
    const cleanPlan = [];
    for (const step of parsed.plan.slice(0, planHorizon)) {
      if (typeof step === 'object' && step !== null && step.action !== undefined) {
        cleanPlan.push({ action: parseInt(step.action), data: step.data || {}, observation: step.observation || '' });
      } else if (typeof step === 'number') {
        cleanPlan.push({ action: parseInt(step), data: {} });
      }
    }
    if (cleanPlan.length) parsed.plan = cleanPlan;
  }
  return parsed;
}

async function askLLMRlm(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const maxIter = parseInt(settings.max_iterations) || 10;
  const maxTokens = parseInt(settings.max_tokens) || 16384;
  const outputTrunc = parseInt(settings.output_truncation) || 5000;
  const thinkingLevel = settings.thinking_level || 'low';
  const planningMode = settings.planning_mode || 'off';
  const planHorizon = planningMode === 'off' ? 1 : (planningMode === 'unlimited' ? 999 : parseInt(planningMode));

  // Build context dict for REPL (mirrors server-side handler)
  const context = {
    grid: _cur.currentState.grid || [],
    available_actions: _cur.currentState.available_actions || [],
    history: (historyForLLM || []).slice(-20).map(h => ({
      step: h.step, action: h.action, result_state: h.result_state,
      change_count: h.change_map?.change_count
    })),
    change_map: _cur.currentChangeMap || {},
    levels_completed: _cur.currentState.levels_completed || 0,
    win_levels: _cur.currentState.win_levels || 0,
    game_id: _cur.currentState.game_id || 'unknown',
    state: _cur.currentState.state || '',
    compact_context: compactBlock || '',
  };

  // Ensure Pyodide is ready for REPL code execution
  await ensurePyodide();

  // Set up REPL context for this turn: update context variable, define helpers if first time
  const contextB64 = btoa(unescape(encodeURIComponent(JSON.stringify(context))));
  const setupCode = `import json as _json, base64 as _base64
context = _json.loads(_base64.b64decode('${contextB64}').decode('utf-8'))
if 'SHOW_VARS' not in dir():
    def SHOW_VARS():
        _skip = {'context', '_json', '_base64', 'json', 'np', 'numpy', 'collections', 'itertools', 'Counter', 'defaultdict', 'math', 'grid', 'prev_grid', 'SHOW_VARS', 'FINAL_VAR', 'llm_query', 'llm_query_batched', '_io', '_sys', '_stdout_buf', '_old_stdout', '_out'}
        _vars = {k: type(v).__name__ for k, v in globals().items() if not k.startswith('_') and k not in _skip}
        _lines = [f"  {k}: {t}" for k, t in sorted(_vars.items())]
        result = "User variables:\\n" + ("\\n".join(_lines) if _lines else "  (none)")
        print(result)
        return result
    def FINAL_VAR(name):
        val = globals().get(name)
        if val is None: return f"[ERROR] Variable '{name}' not found."
        return str(val) if not isinstance(val, str) else val
    def llm_query(prompt):
        return "[llm_query not available in browser mode - use REPL iterations to reason step-by-step]"
    def llm_query_batched(prompts):
        return ["[llm_query not available in browser mode]"] * len(prompts)`;
  await runPyodide(setupCode, context.grid, null, _cur.sessionId);

  // Build conversation messages
  const systemPrompt = buildRlmSystemPrompt(planHorizon);
  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: buildRlmUserFirst(planHorizon) },
  ];

  const iterationsLog = [];
  let finalAnswer = null;

  // Streaming preview callback
  const onChunk = (textSoFar) => {
    if (isActiveFn()) {
      const previewEl = waitEl.querySelector('.stream-preview');
      if (previewEl) {
        previewEl.style.display = 'block';
        previewEl.textContent = textSoFar.length > 500 ? textSoFar.slice(-500) : textSoFar;
        previewEl.scrollTop = previewEl.scrollHeight;
      }
    }
  };

  for (let iter = 0; iter < maxIter; iter++) {
    // Update waiting label with iteration count
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`RLM iteration ${iter + 1}/${maxIter}... `));
        if (timer) label.appendChild(timer);
      }
    }

    // Call LLM with multi-turn conversation
    let responseText;
    try {
      responseText = await callLLM(messages, model, { maxTokens, thinkingLevel, onChunk: modelInfo?.provider === 'gemini' ? onChunk : null });
    } catch (e) {
      console.error(`[RLM] Iteration ${iter} LLM call failed:`, e);
      iterationsLog.push({ iteration: iter, error: e.message });
      break;
    }

    if (!responseText) {
      iterationsLog.push({ iteration: iter, error: 'Empty response from model' });
      break;
    }

    // Extract ```repl code blocks
    const codeBlocks = [];
    const replPattern = /```repl\s*\n([\s\S]*?)\n```/g;
    let match;
    while ((match = replPattern.exec(responseText)) !== null) {
      codeBlocks.push(match[1]);
    }

    // Execute each code block via Pyodide
    const replOutputs = [];
    for (const code of codeBlocks) {
      let output = await runPyodide(code, context.grid, null, _cur.sessionId);
      if (output.length > outputTrunc) {
        output = output.substring(0, outputTrunc) + `\n... [${output.length - outputTrunc} chars truncated]`;
      }
      replOutputs.push(output);
    }

    // Log iteration
    iterationsLog.push({
      iteration: iter,
      response: responseText.substring(0, 2000),
      code_blocks: codeBlocks.length,
      repl_outputs: replOutputs.map(o => o.substring(0, 1000)),
      sub_calls: 0,
    });
    // Emit obs events for RLM
    const _rlmSs = sessions.get(_cur.sessionId);
    emitObsEvent(_rlmSs, { event: 'llm_call', agent: 'executor', model, summary: responseText.slice(0, 200) });
    if (codeBlocks.length > 0) {
      emitObsEvent(_rlmSs, { event: 'repl_exec', agent: 'repl', summary: `${codeBlocks.length} code block(s)` });
    }

    // Check for FINAL() in response text (outside code blocks)
    finalAnswer = findFinalMarker(responseText);
    if (finalAnswer) break;

    // Append to conversation
    messages.push({ role: 'assistant', content: responseText });

    // Build REPL output feedback
    if (replOutputs.length) {
      const feedback = replOutputs.map((out, i) => `[REPL output ${i + 1}]:\n${out}`).join('\n\n');
      messages.push({ role: 'user', content: feedback + '\n\n' + buildRlmUserContinue(planHorizon) });
    } else {
      messages.push({ role: 'user', content: buildRlmUserContinue(planHorizon) });
    }

    // Clear streaming preview for next iteration
    if (isActiveFn()) {
      const previewEl = waitEl.querySelector('.stream-preview');
      if (previewEl) { previewEl.style.display = 'none'; previewEl.textContent = ''; }
    }
  }

  // Parse final answer
  let parsed = _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon);

  // Force-action fallback
  const available = _cur.currentState.available_actions || [];
  if (!parsed && available.length) {
    const rawReasoning = iterationsLog.length ? (iterationsLog[iterationsLog.length - 1].response || '').substring(0, 500) : '';
    const safeAction = available.find(a => a !== 0) ?? available[0];
    parsed = {
      action: safeAction, data: {},
      observation: '(RLM did not produce parseable output \u2014 forcing action)',
      reasoning: rawReasoning || '(no reasoning captured)',
    };
    console.warn(`[RLM client] No parseable output after ${iterationsLog.length} iterations, forcing action=${safeAction}`);
  }

  return {
    raw: finalAnswer || (iterationsLog.length ? iterationsLog[iterationsLog.length - 1].response || '' : ''),
    thinking: null,
    parsed,
    model,
    scaffolding: 'rlm',
    _clientSide: true,
    rlm: {
      iterations: iterationsLog.length,
      sub_calls: 0,
      max_iterations: maxIter,
      final_answer: finalAnswer,
      log: iterationsLog,
    },
  };
}
