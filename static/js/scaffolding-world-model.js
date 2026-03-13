// World Model harness for ARC-AGI-3
// Agent REPL loop (based on RLM) + separate World Model agent that reverse-engineers game code
// Depends on: callLLM, getPrompt (scaffolding.js), findFinalMarker, extractJsonFromText (json-parsing.js),
//   ensurePyodide, runPyodide (engine.js)
// ═══════════════════════════════════════════════════════════════════════════

// ── Prompt templates ──
const _WM_AGENT_SYSTEM = getPrompt('world_model.agent_system');
const _WM_AGENT_FIRST = getPrompt('world_model.agent_first');
const _WM_AGENT_CONTINUE = getPrompt('world_model.agent_continue');
const _WM_WM_SYSTEM = getPrompt('world_model.wm_system');

function _wmPlanInstruction(planHorizon) {
  return `Output a plan of 1-${planHorizon} actions.`;
}

function _wmBuildAgentSystem(planHorizon) {
  const planInstructions = `For multi-step plans (up to ${planHorizon} steps ahead):\n` +
    `  FINAL({"plan": [{"action": <int>, "observation": "..."}, ...], "reasoning": "..."})\n` +
    `Output a plan of 1-${planHorizon} actions. If the next moves are obvious, include them all. If unsure, output a plan of just 1 action.\n\n`;
  return _WM_AGENT_SYSTEM.replace('{plan_instructions}', planInstructions);
}

// ── World Model REPL loop: iteratively build + test simulator code ──
async function _wmUpdateWorldModel(wmModel, wmMaxTokens, wmThinking, wmMaxIter, observations, currentCode, sessionId, waitEl, isActiveFn) {
  await ensurePyodide();

  // Serialize observations into Pyodide
  const obsForPy = observations.map(o => ({
    step: o.step, action: o.action,
    grid_before: o.gridBefore, grid_after: o.gridAfter,
  })).filter(o => o.grid_before && o.grid_after);

  const obsB64 = btoa(unescape(encodeURIComponent(JSON.stringify(obsForPy))));
  const codeB64 = btoa(unescape(encodeURIComponent(currentCode || '')));

  // Set up REPL with observations, test_model helper, and current code
  const setupCode = `import json as _json, base64 as _base64, copy as _copy
observations = _json.loads(_base64.b64decode('${obsB64}').decode('utf-8'))
current_code = _base64.b64decode('${codeB64}').decode('utf-8')

def test_model(code_str):
    """Test simulator code against all observations. Returns accuracy report."""
    _ns = {}
    try:
        exec(code_str, _ns)
    except Exception as e:
        return f"CODE ERROR: {e}"
    if 'simulate' not in _ns:
        return "ERROR: code must define a simulate(grid, action) function"
    sim = _ns['simulate']
    correct = 0
    total = len(observations)
    failures = []
    for i, obs in enumerate(observations):
        try:
            predicted = sim(_copy.deepcopy(obs['grid_before']), obs['action'])
            if predicted == obs['grid_after']:
                correct += 1
            else:
                # Find first differing row
                diff_rows = []
                for r in range(min(len(predicted), len(obs['grid_after']))):
                    if r < len(predicted) and r < len(obs['grid_after']) and predicted[r] != obs['grid_after'][r]:
                        diff_rows.append(f"  Row {r}: predicted {predicted[r]}, actual {obs['grid_after'][r]}")
                        if len(diff_rows) >= 3:
                            break
                failures.append(f"Step {obs['step']} (action {obs['action']}): MISMATCH\\n" + "\\n".join(diff_rows))
        except Exception as e:
            failures.append(f"Step {obs['step']} (action {obs['action']}): RUNTIME ERROR: {e}")
    report = f"Accuracy: {correct}/{total} ({100*correct/total:.0f}%)\\n"
    if failures:
        report += f"\\nFailed steps ({len(failures)}):\\n" + "\\n".join(failures[:10])
        if len(failures) > 10:
            report += f"\\n... and {len(failures)-10} more failures"
    else:
        report += "All observations match!"
    return report

if 'SHOW_VARS' not in dir():
    def SHOW_VARS():
        _skip = {'observations', 'current_code', 'test_model', '_json', '_base64', '_copy', 'SHOW_VARS', 'FINAL_VAR', '_io', '_sys', '_stdout_buf', '_old_stdout', '_out'}
        _vars = {k: type(v).__name__ for k, v in globals().items() if not k.startswith('_') and k not in _skip}
        result = "User variables:\\n" + ("\\n".join(f"  {k}: {t}" for k, t in sorted(_vars.items())) if _vars else "  (none)")
        print(result)
        return result
    def FINAL_VAR(name):
        val = globals().get(name)
        if val is None: return f"[ERROR] Variable '{name}' not found."
        return str(val) if not isinstance(val, str) else val
print(f"World Model REPL ready. {len(observations)} observations loaded.")
if current_code:
    print("Previous code loaded. Testing...")
    print(test_model(current_code))`;

  await runPyodide(setupCode, null, null, sessionId);

  // Build conversation
  const availActions = observations.length > 0 ? (observations[observations.length - 1].availActions || '') : '';
  const systemPrompt = _WM_WM_SYSTEM + `\n\n## Available Actions\n${availActions}`;

  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: currentCode
      ? 'Your previous code and test results are loaded in the REPL. Run `test_model(current_code)` to see current accuracy, then examine failing observations and fix the code. Call FINAL(your_code_string) when done.'
      : `There are ${obsForPy.length} observations loaded. Start by examining them in the REPL, then build a simulate() function, test it with test_model(), and iterate. Call FINAL(your_code_string) when done.`
    },
  ];

  let bestCode = currentCode || '';
  const maxIter = wmMaxIter || 5;

  for (let iter = 0; iter < maxIter; iter++) {
    if (isActiveFn && !isActiveFn()) break;

    if (waitEl) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`World Model iteration ${iter + 1}/${maxIter}... `));
        if (timer) label.appendChild(timer);
      }
    }

    let responseText;
    try {
      responseText = await callLLM(messages, wmModel, { maxTokens: wmMaxTokens, thinkingLevel: wmThinking });
    } catch (e) {
      console.error(`[WorldModel] WM iteration ${iter} failed:`, e);
      break;
    }
    if (!responseText) break;

    // Extract and run ```repl code blocks
    const codeBlocks = [];
    const replPattern = /```repl\s*\n([\s\S]*?)\n```/g;
    let match;
    while ((match = replPattern.exec(responseText)) !== null) {
      codeBlocks.push(match[1]);
    }

    const replOutputs = [];
    for (const code of codeBlocks) {
      let output = await runPyodide(code, null, null, sessionId);
      if (output.length > 8000) {
        output = output.substring(0, 8000) + `\n... [truncated]`;
      }
      replOutputs.push(output);
    }

    // Check for FINAL() marker
    const finalAnswer = findFinalMarker(responseText);
    if (finalAnswer) {
      // finalAnswer might be a variable name or raw code string
      // Try to get it from Pyodide
      try {
        const evalCode = `_wm_final = ${finalAnswer}\nprint(_wm_final if isinstance(_wm_final, str) else str(_wm_final))`;
        const evalResult = await runPyodide(evalCode, null, null, sessionId);
        if (evalResult && evalResult.includes('def simulate')) {
          bestCode = evalResult.trim();
        } else if (finalAnswer.includes('def simulate')) {
          bestCode = finalAnswer;
        }
      } catch {
        if (finalAnswer.includes('def simulate')) bestCode = finalAnswer;
      }
      break;
    }

    // Also check for ```python code block as fallback final output
    const pyMatch = responseText.match(/```python\s*\n([\s\S]*?)\n```/);
    if (pyMatch && pyMatch[1].includes('def simulate')) {
      bestCode = pyMatch[1];
    }

    messages.push({ role: 'assistant', content: responseText });

    if (replOutputs.length) {
      const feedback = replOutputs.map((out, i) => `[REPL output ${i + 1}]:\n${out}`).join('\n\n');
      messages.push({ role: 'user', content: feedback + '\n\nContinue refining. Test with test_model() and call FINAL(code_string) when accuracy is satisfactory.' });
    } else {
      messages.push({ role: 'user', content: 'Use ```repl blocks to write and test code. Call FINAL(code_string) when done.' });
    }
  }

  return bestCode;
}

// ── Main entry point ──
async function askLLMWorldModel(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const maxIter = parseInt(settings.max_iterations) || 10;
  const maxTokens = parseInt(settings.max_tokens) || 16384;
  const outputTrunc = parseInt(settings.output_truncation) || 5000;
  const thinkingLevel = settings.thinking_level || 'low';
  const planningMode = settings.planning_mode || 'off';
  const planHorizon = planningMode === 'off' ? 1 : (planningMode === 'unlimited' ? 999 : parseInt(planningMode));

  const wmModel = settings.wm_model || model;
  const wmMaxTokens = parseInt(settings.wm_max_tokens) || 16384;
  const wmThinking = settings.wm_thinking_level || 'low';
  const wmUpdateEvery = parseInt(settings.wm_update_every) || 3;
  const wmMaxIter = parseInt(settings.wm_max_iterations) || 5;

  // Build context dict for REPL
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

  // Ensure Pyodide is ready
  await ensurePyodide();

  // Initialize or retrieve world model state on the session
  if (!_cur._wmObservations) _cur._wmObservations = [];
  if (!_cur._wmCode) _cur._wmCode = '';
  if (!_cur._wmStepsSinceUpdate) _cur._wmStepsSinceUpdate = 0;

  // Add observation from last step (if we have history)
  const hist = _cur.moveHistory || [];
  if (hist.length > 0) {
    const last = hist[hist.length - 1];
    const prevIdx = hist.length >= 2 ? hist.length - 2 : -1;
    const gridBefore = prevIdx >= 0 ? hist[prevIdx].grid : null;
    _cur._wmObservations.push({
      step: last.step,
      action: last.action,
      gridBefore: gridBefore,
      gridAfter: last.grid,
      changeMap: last.change_map?.change_map_text || '',
      availActions: (context.available_actions || []).map(a => `${a}=${ACTION_NAMES[a] || 'ACTION' + a}`).join(', '),
    });
  }

  // Run World Model update if enough steps have passed
  _cur._wmStepsSinceUpdate++;
  if (_cur._wmObservations.length > 0 && _cur._wmStepsSinceUpdate >= wmUpdateEvery) {
    try {
      _cur._wmCode = await _wmUpdateWorldModel(wmModel, wmMaxTokens, wmThinking, wmMaxIter, _cur._wmObservations, _cur._wmCode, _cur.sessionId, waitEl, isActiveFn);
      _cur._wmStepsSinceUpdate = 0;
    } catch (e) {
      console.error('[WorldModel] WM update failed:', e);
    }
  }

  // Set up REPL context with world model code
  const contextB64 = btoa(unescape(encodeURIComponent(JSON.stringify(context))));
  const wmCodeB64 = btoa(unescape(encodeURIComponent(_cur._wmCode || '')));
  const setupCode = `import json as _json, base64 as _base64
context = _json.loads(_base64.b64decode('${contextB64}').decode('utf-8'))
world_model_code = _base64.b64decode('${wmCodeB64}').decode('utf-8')
if 'SHOW_VARS' not in dir():
    def SHOW_VARS():
        _skip = {'context', '_json', '_base64', 'json', 'np', 'numpy', 'collections', 'itertools', 'Counter', 'defaultdict', 'math', 'grid', 'prev_grid', 'SHOW_VARS', 'FINAL_VAR', 'llm_query', 'llm_query_batched', '_io', '_sys', '_stdout_buf', '_old_stdout', '_out', 'world_model_code', 'simulate'}
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
  const systemPrompt = _wmBuildAgentSystem(planHorizon);
  const isFirstTurn = (_cur.stepCount || 0) === 0;
  const userFirst = isFirstTurn
    ? _WM_AGENT_FIRST.replace('{plan_instruction}', _wmPlanInstruction(planHorizon))
    : _WM_AGENT_CONTINUE.replace('{plan_instruction}', _wmPlanInstruction(planHorizon));
  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userFirst },
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
    if (isActiveFn()) {
      const label = waitEl?.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`Agent iteration ${iter + 1}/${maxIter}... `));
        if (timer) label.appendChild(timer);
      }
    }

    let responseText;
    try {
      responseText = await callLLM(messages, model, { maxTokens, thinkingLevel, onChunk: modelInfo?.provider === 'gemini' ? onChunk : null });
    } catch (e) {
      console.error(`[WorldModel] Agent iteration ${iter} failed:`, e);
      iterationsLog.push({ iteration: iter, error: e.message });
      break;
    }

    if (!responseText) {
      iterationsLog.push({ iteration: iter, error: 'Empty response' });
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

    iterationsLog.push({
      iteration: iter,
      response: responseText.substring(0, 2000),
      code_blocks: codeBlocks.length,
      repl_outputs: replOutputs.map(o => o.substring(0, 1000)),
    });

    // Emit obs events
    const _wmSs = sessions.get(_cur.sessionId);
    emitObsEvent(_wmSs, { event: 'llm_call', agent: 'executor', model, summary: responseText.slice(0, 200) });
    if (codeBlocks.length > 0) {
      emitObsEvent(_wmSs, { event: 'repl_exec', agent: 'repl', summary: `${codeBlocks.length} code block(s)` });
    }

    // Check for FINAL()
    finalAnswer = findFinalMarker(responseText);
    if (finalAnswer) break;

    messages.push({ role: 'assistant', content: responseText });

    if (replOutputs.length) {
      const feedback = replOutputs.map((out, i) => `[REPL output ${i + 1}]:\n${out}`).join('\n\n');
      messages.push({ role: 'user', content: feedback + '\n\n' + _WM_AGENT_CONTINUE.replace('{plan_instruction}', _wmPlanInstruction(planHorizon)) });
    } else {
      messages.push({ role: 'user', content: _WM_AGENT_CONTINUE.replace('{plan_instruction}', _wmPlanInstruction(planHorizon)) });
    }

    // Clear streaming preview
    if (isActiveFn()) {
      const previewEl = waitEl.querySelector('.stream-preview');
      if (previewEl) { previewEl.style.display = 'none'; previewEl.textContent = ''; }
    }
  }

  // Parse final answer (reuse RLM parser)
  let parsed = _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon);

  // Force-action fallback
  const available = _cur.currentState.available_actions || [];
  if (!parsed && available.length) {
    const rawReasoning = iterationsLog.length ? (iterationsLog[iterationsLog.length - 1].response || '').substring(0, 500) : '';
    const safeAction = available.find(a => a !== 0) ?? available[0];
    parsed = {
      action: safeAction, data: {},
      observation: '(World Model harness did not produce parseable output — forcing action)',
      reasoning: rawReasoning || '(no reasoning captured)',
    };
  }

  return {
    raw: finalAnswer || (iterationsLog.length ? iterationsLog[iterationsLog.length - 1].response || '' : ''),
    thinking: null,
    parsed,
    model,
    scaffolding: 'world_model',
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
