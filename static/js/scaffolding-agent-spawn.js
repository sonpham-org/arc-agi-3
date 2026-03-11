// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Agent Spawn orchestrator scaffolding for ARC-AGI-3. Implements Agentica-style
//   multi-agent orchestration: a coordinator LLM spawns reactive subagents, each running
//   independent observation-action loops. Provides runAgentSpawn() entry point, subagent
//   lifecycle management, inter-agent message passing, and result aggregation. Depends on
//   callLLM and getPrompt from scaffolding.js, extractJsonFromText from json-parsing.js.
//   Extracted from scaffolding.js in Phase 5.
// SRP/DRY check: Pass — agent-spawn logic fully separated from other scaffolding types
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING-AGENT-SPAWN — Agent Spawn orchestrator scaffolding
// Extracted from scaffolding.js — Phase 5 modularization
// Depends on: callLLM, getPrompt (scaffolding.js)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// AGENT SPAWN — Agentica-style orchestrator + reactive subagent loops
// ═══════════════════════════════════════════════════════════════════════════

// ── Step 1: Per-step execution helper ────────────────────────────────────

async function _asExecuteOneStep(actionId, actionData, reasoning, agentType, _cur, isActiveFn, llmMeta) {
  // Push undo snapshot
  const currentTurnId = _cur.turnCounter;
  _cur.undoStack.push({
    grid: _cur.currentState.grid ? _cur.currentState.grid.map(r => [...r]) : [],
    state: _cur.currentState.state,
    levels_completed: _cur.currentState.levels_completed,
    stepCount: _cur.stepCount,
    turnId: currentTurnId,
  });

  const prevGrid = _cur.currentState.grid ? _cur.currentState.grid.map(r => [...r]) : [];
  _cur.stepCount++;

  const extras = { session_cost: _cur.sessionTotalTokens?.cost || 0 };
  const data = await gameStep(_cur.sessionId, actionId, actionData || {}, extras,
    { grid: _cur.currentState.grid, _ownerSessionId: _cur.sessionId });

  if (data.error) {
    // Rollback
    _cur.undoStack.pop();
    _cur.stepCount--;
    return { data, terminal: null, prevGrid, newGrid: prevGrid, error: true };
  }

  // Update session state
  _cur.currentState = data;
  _cur.currentGrid = data.grid;
  _cur.currentChangeMap = data.change_map;

  // Compute change map
  const newGrid = data.grid || [];
  const changeMap = computeChangeMapJS(prevGrid, newGrid);
  _cur.currentChangeMap = changeMap;

  // Push to move history
  _cur.moveHistory.push({
    step: _cur.stepCount, action: actionId,
    result_state: data.state, levels: data.levels_completed,
    grid: data.grid, change_map: changeMap,
    turnId: currentTurnId,
    observation: `[${agentType}] ${reasoning || ''}`,
    reasoning: reasoning || '',
  });

  // Record for persistence — include subagent LLM metadata so reasoning is available on resume
  const _stepLlm = {
    parsed: { observation: `[${agentType}] ${reasoning || ''}`, reasoning: reasoning || '', action: actionId, data: actionData || {} },
    model: llmMeta?.model || '', scaffolding: 'agent_spawn',
    usage: llmMeta?.usage || null,
    call_duration_ms: llmMeta?.call_duration_ms || null,
  };
  recordStepForPersistence(actionId, actionData || {}, data.grid, changeMap, _stepLlm, _cur,
    { levels_completed: data.levels_completed, result_state: data.state });

  // Update UI if active
  if (isActiveFn()) { updateUI(data); updateUndoBtn(); }

  // Determine terminal
  let terminal = null;
  if (data.state === 'WIN') terminal = 'WIN';
  else if (data.state === 'GAME_OVER') terminal = 'GAME_OVER';

  return { data, terminal, prevGrid, newGrid, error: false };
}

// ── Step 2: Bounded budget + frame helpers ───────────────────────────────

function _makeBoundedBudget(limit) {
  return {
    remaining: limit, total: limit,
    use(actionId) {
      if (actionId === 0) return true; // RESET doesn't cost budget
      if (this.remaining <= 0) return false;
      this.remaining--;
      return true;
    },
    exhausted() { return this.remaining <= 0; },
  };
}

function _asRenderGrid(grid) {
  if (!grid || !grid.length) return '(empty grid)';
  return grid.map((r, i) => `Row ${String(i).padStart(2)}: ${compressRowJS(r)}`).join('\n');
}

function _asDiffFrames(oldGrid, newGrid) {
  if (!oldGrid || !newGrid) return '(no diff available)';
  const cm = computeChangeMapJS(oldGrid, newGrid);
  if (!cm.changes.length) return '(no changes)';
  // Group changes by region
  const byRow = {};
  for (const c of cm.changes) {
    if (!byRow[c.y]) byRow[c.y] = [];
    byRow[c.y].push(c);
  }
  const lines = [];
  for (const [row, changes] of Object.entries(byRow).sort((a, b) => a[0] - b[0])) {
    const details = changes.map(c => `col ${c.x}: ${c.from}->${c.to}`).join(', ');
    lines.push(`Row ${row}: ${details}`);
  }
  return lines.join('\n');
}

function _asChangeSummary(oldGrid, newGrid) {
  if (!oldGrid || !newGrid) return 'No previous grid';
  const cm = computeChangeMapJS(oldGrid, newGrid);
  return `${cm.change_count} cell(s) changed`;
}

function _asFind(grid, ...colors) {
  if (!grid || !grid.length) return '(empty grid)';
  const colorSet = new Set(colors.map(Number));
  const results = [];
  for (let r = 0; r < grid.length; r++) {
    for (let c = 0; c < grid[r].length; c++) {
      if (colorSet.has(grid[r][c])) results.push(`(${r},${c})=${grid[r][c]}`);
    }
  }
  return results.length ? results.join(', ') : '(none found)';
}

function _asBoundingBox(grid, ...colors) {
  if (!grid || !grid.length) return '(empty grid)';
  const colorSet = new Set(colors.map(Number));
  let minR = Infinity, maxR = -1, minC = Infinity, maxC = -1;
  for (let r = 0; r < grid.length; r++) {
    for (let c = 0; c < grid[r].length; c++) {
      if (colorSet.has(grid[r][c])) {
        if (r < minR) minR = r; if (r > maxR) maxR = r;
        if (c < minC) minC = c; if (c > maxC) maxC = c;
      }
    }
  }
  if (maxR === -1) return '(no cells with those colors)';
  return `rows ${minR}-${maxR}, cols ${minC}-${maxC} (${maxR-minR+1}x${maxC-minC+1})`;
}

function _asColorCounts(grid) {
  return _computeColorHistogram(grid);
}

function _asDispatchFrameTool(tool, grid, prevGrid, args) {
  switch (tool) {
    case 'render_grid': return _asRenderGrid(grid);
    case 'diff_frames': return _asDiffFrames(prevGrid, grid);
    case 'change_summary': return _asChangeSummary(prevGrid, grid);
    case 'find_colors': return _asFind(grid, ...(args?.colors || []));
    case 'bounding_box': return _asBoundingBox(grid, ...(args?.colors || []));
    case 'color_counts': return _asColorCounts(grid);
    default: return `Unknown frame tool: ${tool}`;
  }
}

// ── Step 3: Stack-based shared memory ────────────────────────────────────

function _asCreateMemories() {
  return {
    facts: [],
    hypotheses: [],
    stack: [], // [{summary, details, agentType, timestamp}]

    addFact(fact) { if (!this.facts.includes(fact)) this.facts.push(fact); },
    addHypothesis(h) { if (!this.hypotheses.includes(h)) this.hypotheses.push(h); },

    add(summary, details, agentType) {
      this.stack.push({ summary, details: details || '', agentType: agentType || 'system', timestamp: Date.now() });
    },

    summaries() {
      return this.stack.map((m, i) => `[${i}] (${m.agentType}) ${m.summary}`);
    },

    formatForPrompt() {
      const parts = [];
      if (this.facts.length) {
        const recent = this.facts.slice(-5);
        parts.push('## Facts\n' + recent.map((f, i) => `${i + 1}. ${f}`).join('\n'));
      }
      if (this.hypotheses.length) {
        const recent = this.hypotheses.slice(-5);
        parts.push('## Hypotheses\n' + recent.map((h, i) => `${i + 1}. ${h}`).join('\n'));
      }
      if (this.stack.length) {
        const recent = this.stack.slice(-8);
        parts.push('## Agent Reports\n' + recent.map((m, i) =>
          `[${i}] (${m.agentType}) ${m.summary}${m.details ? '\n   ' + m.details : ''}`
        ).join('\n'));
      }
      return parts.length ? parts.join('\n\n') : '(none yet)';
    },
  };
}

// ── Step 4: Agentica-style prompts ───────────────────────────────────────

const AS_GAME_REFERENCE = `# ARC-AGI-3 Game Reference

## Grid
The game is played on a grid (up to 64x64). Each cell has a color value 0-15.
Colors: 0=White, 1=LightGray, 2=Gray, 3=DarkGray, 4=VeryDarkGray, 5=Black, 6=Magenta, 7=LightMagenta, 8=Red, 9=Blue, 10=LightBlue, 11=Yellow, 12=Orange, 13=Maroon, 14=Green, 15=Purple.

## Actions
Actions are integers. Common mapping:
  0=RESET (restart current level), 1=UP, 2=DOWN, 3=LEFT, 4=RIGHT, 5=ACT5, 6=CLICK, 7=ACT7
Not all actions are available in every game — check available_actions.

## RESET Discipline
Action 0 (RESET) restarts the current level to its initial state. Use it when stuck or to test hypotheses from a clean state. RESET does NOT cost budget.

## Level Progression
- levels_completed increments mid-action when you complete a level's objective.
- state='WIN' ONLY when ALL levels are done (levels_completed == win_levels).
- A single action can complete a level (levels_completed goes up) while state stays 'NOT_FINISHED' if more levels remain.

## Frame Tools
You can use frame tools to analyze the grid without taking an action:
- render_grid: Full text rendering of the current grid with row numbers
- diff_frames: Region-grouped diff between previous and current grid
- change_summary: One-line summary of how many cells changed
- find_colors(colors): Find pixel coordinates matching given color values
- bounding_box(colors): Tight bounding box around cells of given colors
- color_counts: Color histogram of the grid

Usage: {"command": "frame_tool", "tool": "<name>", "args": {"colors": [1, 2]}}

## Memory
Findings are stored in shared memory. Reference by index: "See report [2]".
Add findings as you discover them — other agents can see your reports.

## Methodology
1. Hypothesize what an action might do
2. Test by executing the action
3. Verify by analyzing the grid changes (use diff_frames / change_summary)
4. Record confirmed findings as facts
5. Always analyze changes AFTER each action — never assume the result`;

const AS_ORCHESTRATOR_PREMISE = `You are the ORCHESTRATOR for an ARC-AGI-3 game-playing system.

## Your Role
You are a MANAGER, not a player. You coordinate subagents to explore, theorize, test, and solve.
You do NOT have submit_action. You CANNOT play the game directly.
Your only tools are THINKING and DELEGATING to subagents.

## Subagent Types
- **explorer**: Systematic action sampling. Tries available actions, uses frame tools, reports what each action does. Best for early-game discovery.
- **theorist**: Analysis only — receives data, outputs hypotheses, challenges assumptions. Has NO game actions. Can only use frame_tool and report.
- **tester**: Receives a hypothesis. Designs a minimal experiment (1-3 actions), executes, reports whether hypothesis is confirmed or refuted.
- **solver**: Receives a strategy. Executes a sequence of actions efficiently. Reports progress and obstacles.

## Orchestration Phases
1. **Explore** — Spawn explorer(s) to try all available actions and map mechanics
2. **Hypothesize** — Spawn theorist to analyze findings and propose level-solving strategy
3. **Test** — Spawn tester to verify critical hypotheses before committing
4. **Iterate** — If tests fail, update hypotheses and re-test
5. **Solve** — Spawn solver with a clear strategy to complete the level
6. **Next Level** — After level completion, re-explore (mechanics may change)

## Briefing Subagents
Always tell subagents:
- What is known so far (summarize key facts)
- What they should focus on (specific task)
- Reference memory indices: "See reports [0]-[2] for explored actions"

## Commands
You MUST respond with exactly one JSON object:

Option A — Delegate to a subagent:
{"command": "delegate", "reasoning": "why this delegation is the right next step", "agent_type": "explorer|theorist|tester|solver", "task": "specific instructions", "budget": <1-10>}

Option B — Think and record to memory:
{"command": "think", "reasoning": "analysis of current situation", "facts": ["confirmed fact", ...], "hypotheses": ["working theory", ...], "next": "what to do next"}`;

const AS_AGENT_SYSTEM = {
  explorer: `You are an EXPLORER subagent for ARC-AGI-3.

Your mission: systematically try ALL available actions to discover what they do.
- Try each available action at least once
- Use frame tools (diff_frames, change_summary) AFTER each action to see what changed
- Try actions from different grid states (use RESET to get a clean slate)
- Report: what each action does, which actions seem to advance the level, any patterns

You have a limited action budget. Prioritize coverage over depth — try different actions rather than repeating the same one.
Respond in JSON only.`,

  theorist: `You are a THEORIST subagent for ARC-AGI-3.

Your mission: analyze data from other agents and formulate hypotheses.
- You have NO game actions — you CANNOT use the "act" command
- You CAN use frame_tool to examine the current grid state
- Study the facts and agent reports in shared memory
- Propose testable hypotheses about game mechanics and level solutions
- Challenge existing assumptions — look for what might be wrong
- Be specific: "Action 4 moves the player right by 1 cell" not "actions move things"

Respond in JSON only.`,

  tester: `You are a TESTER subagent for ARC-AGI-3.

Your mission: test a specific hypothesis with minimal actions.
- Design the smallest possible experiment to confirm or refute the hypothesis
- RESET first if you need a clean state
- Execute actions and analyze results with frame tools
- Report conclusively: CONFIRMED or REFUTED, with evidence
- Keep experiments small (1-3 actions) — don't waste budget on exploration

Respond in JSON only.`,

  solver: `You are a SOLVER subagent for ARC-AGI-3.

Your mission: execute a strategy to complete the current level.
- Follow the orchestrator's plan but adapt if results are unexpected
- Use frame tools to verify progress after each action
- If stuck, report the obstacle rather than thrashing
- Report progress: what worked, what didn't, current state

Respond in JSON only.`,
};

const AS_AGENT_TURN = `# Task from Orchestrator
{task}

# Current State
- Step: {step_num} | Budget remaining: {budget_remaining}/{budget_total}
- Level: {levels_done} / {win_levels}
- State: {state_str}
- Available actions: {action_desc}

# Grid
{grid_block}

# Changes from last action
{change_map_block}

# Shared Memories
{memories}

# My Actions This Session
{session_history}
{tool_results}
# Commands
Respond with exactly one JSON object:

Option A — Take a game action (NOT available for theorist):
{"command": "act", "action": <action_id>, "data": {}, "reasoning": "why this action"}

Option B — Use a frame tool to analyze the grid:
{"command": "frame_tool", "tool": "render_grid|diff_frames|change_summary|find_colors|bounding_box|color_counts", "args": {"colors": [1, 2]}}

Option C — Report findings and yield to orchestrator:
{"command": "report", "findings": ["finding1", ...], "hypotheses": ["hypothesis1", ...], "summary": "what I learned"}`;

/**
 * Template fill for Agent-Spawn (AS) prompts.
 * Uses replaceAll with explicit String() coercion.
 * NOTE: Does not support {{/}} escaping. Do NOT replace with _tsTemplateFill
 * without verifying no AS templates need literal { } output.
 */
function _asFill(template, vars) {
  let s = template;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll('{' + k + '}', String(v));
  return s;
}

// ── Step 5: Main function — reactive subagent loops ──────────────────────

async function askLLMAgentSpawn(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const t0Total = performance.now();
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const orchModel = settings.orchestrator_model || settings.model || model;
  const orchThinking = settings.orchestrator_thinking_level || 'high';
  const orchMaxTokens = Math.min(parseInt(settings.orchestrator_max_tokens) || 16384, 65536);
  const subModel = settings.subagent_model || orchModel;
  const subThinking = settings.subagent_thinking_level || 'med';
  const subMaxTokens = Math.min(parseInt(settings.subagent_max_tokens) || 16384, 65536);
  const maxSubBudget = parseInt(settings.max_subagent_budget) || 5;
  const orchMaxTurns = parseInt(settings.orchestrator_max_turns) || 5;

  // Token/cost tracking — uses trackTokenUsage() from utils/tokens.js
  const _asTokens = _cur.sessionTotalTokens || sessionTotalTokens;

  // Init shared memory on session (stack-based)
  if (!_cur._asMemories) {
    _cur._asMemories = _asCreateMemories();
  }
  const mem = _cur._asMemories;

  // Assign a turn ID for all steps in this call
  _cur.turnCounter++;
  const currentTurnId = _cur.turnCounter;

  const orchestratorLog = [];
  const subagentSummaries = [];
  let totalStepsExecuted = 0;
  let totalSubagents = 0;

  // Timeline event helper — push granular as_* events for tree view
  const _asSess = sessions.get(_cur.sessionId);
  const _asTlEvents = _asSess ? _asSess.timelineEvents : null;
  function _asPushTl(ev) {
    if (!_asTlEvents) return;
    ev.timestamp = Date.now();
    _asTlEvents.push(ev);
    if (isActiveFn() && _asSess) renderTimeline(_asSess);
    // Map agent spawn events to obs events
    const _asTypeMap = { as_orch_start: 'orchestrator', as_orch_decide: 'orchestrator',
      as_subagent_start: null, as_subagent_report: null, as_step: null };
    const agentType = ev.agent_type || ev.current_agent || 'orchestrator';
    const obsEvent = ev.type?.startsWith('as_') ? ev.type.replace('as_', '') : ev.type;
    const obsData = {
      event: obsEvent || ev.type, agent: agentType.toLowerCase(),
    };
    // Only include non-empty fields
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
    if (ev.steps_used != null) obsData.steps_used = ev.steps_used;
    if (ev.tool_name) obsData.tool_name = ev.tool_name;
    if (ev.action_name) obsData.action_name = ev.action_name;
    emitObsEvent(_asSess, obsData);
  }

  _asPushTl({ type: 'as_orch_start', turn: 0 });

  // Helper: build current context from _cur (re-read each time for fresh state)
  function _buildContext() {
    const grid = _cur.currentState.grid || [];
    const avail = _cur.currentState.available_actions || [];
    const cm = _cur.currentChangeMap || {};
    let changeMapBlock = '';
    if (typeof cm === 'object' && cm?.change_map_text) changeMapBlock = cm.change_map_text;
    else if (typeof cm === 'string' && cm) changeMapBlock = cm;
    else changeMapBlock = '(no changes)';

    return {
      game_id: _cur.currentState.game_id || 'unknown',
      state: _cur.currentState.state || '',
      step_num: _cur.stepCount || 0,
      levels_completed: _cur.currentState.levels_completed || 0,
      win_levels: _cur.currentState.win_levels || 0,
      grid, avail,
      actionDesc: avail.map(a => `${a}=${ACTION_NAMES[a] || 'ACTION' + a}`).join(', '),
      gridText: grid.length ? grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n') : '(no grid)',
      changeMapBlock,
    };
  }

  // Helper: format history with grid + change map per step
  const orchHistoryLength = parseInt(settings.orchestrator_history_length) || 10;
  function _buildHistoryBlock() {
    const hist = _cur.moveHistory || [];
    if (!hist.length) return '(none)';
    return hist.slice(-orchHistoryLength).map(h => {
      const aname = ACTION_NAMES[h.action] || '?';
      const lines = [`--- Step ${h.step || '?'}: ${aname} | levels=${h.levels || '?'} | state=${h.result_state || '?'} ---`];
      if (h.observation) lines.push(`  Observation: ${h.observation}`);
      // Include change map (full, no truncation)
      const cmText = h.change_map?.change_map_text || '';
      if (cmText && cmText !== '(no changes)' && cmText !== '(initial)') {
        lines.push(`  Changes:\n${cmText}`);
      }
      // Include full grid snapshot (RLE compressed, all rows)
      if (h.grid && h.grid.length) {
        const gridLines = h.grid.map((r, i) => `    Row ${i}: ${compressRowJS(r)}`);
        lines.push(`  Grid:\n${gridLines.join('\n')}`);
      }
      return lines.join('\n');
    }).join('\n\n');
  }

  // ── Orchestrator REPL loop ──
  for (let turn = 1; turn <= orchMaxTurns; turn++) {
    if (!isActiveFn()) break;
    // Check terminal
    if (_cur.currentState.state === 'WIN' || _cur.currentState.state === 'GAME_OVER') break;

    // Update wait label
    const label = waitEl?.querySelector('.step-label');
    if (label) {
      const timer = label.querySelector('.wait-timer');
      const spinner = label.querySelector('.spinner');
      label.innerHTML = '';
      if (spinner) label.appendChild(spinner);
      label.appendChild(document.createTextNode(`Orchestrator turn ${turn}/${orchMaxTurns}... `));
      if (timer) label.appendChild(timer);
    }

    const ctx = _buildContext();
    const turnVars = {
      game_id: ctx.game_id, step_num: ctx.step_num, levels_done: ctx.levels_completed,
      win_levels: ctx.win_levels, state_str: ctx.state, action_desc: ctx.actionDesc,
      grid_block: ctx.gridText, change_map_block: ctx.changeMapBlock,
      memories: mem.formatForPrompt(),
      history_block: _buildHistoryBlock(),
      history_length: orchHistoryLength,
    };

    const prompt = AS_ORCHESTRATOR_PREMISE + '\n\n' + AS_GAME_REFERENCE + '\n\n' + _asFill(
      `# Current State
- Game: {game_id}
- Step: {step_num}
- Level: {levels_done} / {win_levels}
- State: {state_str}
- Available actions: {action_desc}

# Grid
{grid_block}

# Change from last step
{change_map_block}

# Shared Memories
{memories}

# Recent History (last {history_length} steps with grid snapshots)
{history_block}

Decide your next move. Respond with a JSON object (delegate or think).`, turnVars);

    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], orchModel, { maxTokens: orchMaxTokens, thinkingLevel: orchThinking });
    } catch (e) {
      console.error(`[agent_spawn] orchestrator turn ${turn} failed:`, e);
      orchestratorLog.push({ turn, type: 'error', error: e.message });
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    const orchUsage = trackTokenUsage(orchModel, raw || '', _asTokens);
    const parsed = extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.command) {
      console.warn(`[agent_spawn] orchestrator turn ${turn}: unparseable response (${(raw||'').length} chars):`, raw?.substring(0, 500));
      orchestratorLog.push({ turn, type: 'error', error: 'unparseable', raw_preview: (raw||'').substring(0, 300), duration_ms: durMs });
      _asPushTl({ type: 'as_orch_think', turn, facts: 0, hypotheses: 0, duration_ms: durMs, error: 'unparseable response',
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      continue;
    }

    const command = parsed.command;

    // ── THINK ──
    if (command === 'think') {
      const facts = parsed.facts || [];
      const hypotheses = parsed.hypotheses || [];
      for (const f of facts) mem.addFact(f);
      for (const h of hypotheses) mem.addHypothesis(h);
      if (parsed.reasoning) mem.add(parsed.reasoning, '', 'orchestrator');
      orchestratorLog.push({ turn, type: 'think', facts: facts.length, hypotheses: hypotheses.length, duration_ms: durMs, raw_preview: (raw||'').substring(0, 500) });
      _asPushTl({ type: 'as_orch_think', turn, facts: facts.length, hypotheses: hypotheses.length, duration_ms: durMs, reasoning: parsed.next || parsed.reasoning || '', response: (raw||'').substring(0, 1000),
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      continue;
    }

    // ── DELEGATE ──
    if (command === 'delegate' || command === 'spawn') {
      const agentType = (['explorer', 'theorist', 'tester', 'solver'].includes(parsed.agent_type))
        ? parsed.agent_type : 'explorer';
      const task = parsed.task || 'explore the game';
      const isTheorist = agentType === 'theorist';
      const budgetLimit = isTheorist ? 0 : Math.min(parseInt(parsed.budget) || 3, maxSubBudget);
      const budget = _makeBoundedBudget(budgetLimit);

      orchestratorLog.push({ turn, type: 'delegate', agent_type: agentType, task: task.substring(0, 100), budget: budgetLimit, duration_ms: durMs, raw_preview: (raw||'').substring(0, 500) });
      _asPushTl({ type: 'as_orch_delegate', turn, agent_type: agentType, task: task.substring(0, 80), budget: budgetLimit, duration_ms: durMs, reasoning: parsed.reasoning || '', response: (raw||'').substring(0, 1000),
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      totalSubagents++;
      const subStartCtx = _buildContext();
      _asPushTl({ type: 'as_sub_start', turn, agent_type: agentType, task: task.substring(0, 200), budget: budgetLimit, parentTurn: turn,
        step_num: subStartCtx.step_num, level: `${subStartCtx.levels_completed}/${subStartCtx.win_levels}`,
        available_actions: subStartCtx.actionDesc, memory_summary: mem.formatForPrompt().substring(0, 500),
      });

      // Update wait label
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`[${agentType}] ${task.substring(0, 40)}... `));
        if (timer) label.appendChild(timer);
      }

      // ── SUBAGENT REACTIVE LOOP (multi-turn conversation) ──
      const subActions = [];
      let toolResults = '';
      const maxIter = isTheorist ? 3 : (budgetLimit + 3); // theorist gets 3 iterations for frame_tool + report
      let subTerminal = null;

      // Build initial system prompt + first user turn
      const systemPrompt = AS_AGENT_SYSTEM[agentType] || AS_AGENT_SYSTEM.explorer;
      const subMessages = [{ role: 'system', content: systemPrompt + '\n\n' + AS_GAME_REFERENCE }];

      for (let si = 0; si < maxIter; si++) {
        if (!isActiveFn()) break;
        if (subTerminal) break;

        // Re-read current state from _cur (fresh after each _asExecuteOneStep)
        const subCtx = _buildContext();

        const subVars = {
          task,
          step_num: subCtx.step_num,
          budget_remaining: budget.remaining,
          budget_total: budget.total,
          levels_done: subCtx.levels_completed,
          win_levels: subCtx.win_levels,
          state_str: subCtx.state,
          action_desc: subCtx.actionDesc,
          grid_block: subCtx.gridText,
          change_map_block: subCtx.changeMapBlock,
          memories: mem.formatForPrompt(),
          session_history: subActions.length
            ? subActions.map((a, i) => `  ${i + 1}. ${ACTION_NAMES[a.action] || '?'}: ${a.reasoning || ''} → ${a.result || ''}`).join('\n')
            : '(none yet)',
          tool_results: toolResults ? `\n# Frame Tool Results\n${toolResults}\n` : '',
        };

        // First iteration: full context as user message. Subsequent: feedback as user message.
        if (si === 0) {
          subMessages.push({ role: 'user', content: _asFill(AS_AGENT_TURN, subVars) });
        }
        // (feedback appended at end of loop for subsequent iterations)

        let subRaw;
        try {
          subRaw = await callLLM(subMessages, subModel, { maxTokens: subMaxTokens, thinkingLevel: subThinking });
        } catch (e) {
          console.error(`[agent_spawn] ${agentType} iter ${si} failed:`, e);
          break;
        }
        const subUsage = trackTokenUsage(subModel, subRaw || '', _asTokens);

        const subParsed = extractJsonFromText(subRaw) || (() => { try { return JSON.parse(subRaw); } catch { return null; } })();
        if (!subParsed || !subParsed.command) {
          console.warn(`[agent_spawn] ${agentType} iter ${si}: unparseable response (${(subRaw||'').length} chars):`, subRaw?.substring(0, 500));
          break;
        }

        // Append assistant response to conversation
        subMessages.push({ role: 'assistant', content: subRaw });

        // ── REPORT ──
        if (subParsed.command === 'report') {
          const findings = subParsed.findings || [];
          const hypotheses = subParsed.hypotheses || [];
          for (const f of findings) mem.addFact(f);
          for (const h of hypotheses) mem.addHypothesis(h);
          const summary = subParsed.summary || findings.join('; ');
          const fullDetails = [
            ...findings.map(f => `Finding: ${f}`),
            ...hypotheses.map(h => `Hypothesis: ${h}`),
          ].join('\n');
          mem.add(summary, fullDetails, agentType);
          subagentSummaries.push({ type: agentType, task: task.substring(0, 60), steps: subActions.length, summary });
          _asPushTl({ type: 'as_sub_report', turn, agent_type: agentType, findings: findings.length, hypotheses: hypotheses.length, summary, steps_used: subActions.length, response: (subRaw || '').substring(0, 2000),
            input_tokens: subUsage.input_tokens, output_tokens: subUsage.output_tokens, cost: subUsage.cost });
          break;
        }

        // ── FRAME_TOOL ──
        if (subParsed.command === 'frame_tool') {
          const toolName = subParsed.tool || 'render_grid';
          const toolArgs = subParsed.args || {};
          const prevGrid = _cur.previousGrid || null;
          const result = _asDispatchFrameTool(toolName, subCtx.grid, prevGrid, toolArgs);
          toolResults = `Tool: ${toolName}\n${result}`;
          _asPushTl({ type: 'as_sub_tool', turn, agent_type: agentType, tool_name: toolName });
          subMessages.push({ role: 'user', content: `Frame tool result:\n${toolResults}\n\nContinue with your next command.` });
          continue; // Don't count as action, loop again
        }

        // ── ACT ──
        if (subParsed.command === 'act') {
          // Theorists cannot act
          if (isTheorist) {
            const errMsg = '(ERROR: theorists cannot take game actions — use frame_tool or report)';
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          const actionId = parseInt(subParsed.action);
          const avail = new Set(subCtx.avail);
          if (isNaN(actionId) || !avail.has(actionId)) {
            const errMsg = `(ERROR: invalid action ${subParsed.action} — available: ${subCtx.actionDesc})`;
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          // Check budget
          if (!budget.use(actionId)) {
            const errMsg = '(Budget exhausted — use "report" to yield findings)';
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          // Execute the step and SEE the result
          const stepResult = await _asExecuteOneStep(
            actionId, subParsed.data || {}, subParsed.reasoning || '', agentType, _cur, isActiveFn,
            { model: subModel, usage: subUsage }
          );

          if (stepResult.error) {
            const errMsg = `(Action ${actionId} failed — game error)`;
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          totalStepsExecuted++;
          const actDurMs = Math.round(performance.now() - t0);

          // Build observation for the subagent
          const changeSummary = _asChangeSummary(stepResult.prevGrid, stepResult.newGrid);
          const actionName = ACTION_NAMES[actionId] || `ACTION${actionId}`;
          subActions.push({
            action: actionId,
            data: subParsed.data || {},
            reasoning: subParsed.reasoning || '',
            result: `${changeSummary}, levels=${stepResult.data.levels_completed}`,
          });
          _asPushTl({ type: 'as_sub_act', turn, agent_type: agentType, action: actionId, action_name: actionName, reasoning: (subParsed.reasoning || '').substring(0, 100), step_num: _cur.stepCount, duration_ms: actDurMs,
            input_tokens: subUsage.input_tokens, output_tokens: subUsage.output_tokens, cost: subUsage.cost });

          // Build feedback for conversation continuation
          toolResults = `Last action: ${actionName} → ${changeSummary}`;

          // Check terminal
          if (stepResult.terminal) {
            subTerminal = stepResult.terminal;
            mem.add(`Game ${stepResult.terminal} after ${actionName}`, '', agentType);
            break;
          }

          // Check budget exhaustion
          let budgetNote = '';
          if (budget.exhausted()) {
            budgetNote = '\n(Budget exhausted — next response MUST be "report")';
          }

          // Append action result as user feedback for next turn
          const nextCtx = _buildContext();
          // Include full change map (not just summary count)
          const fullChangeMap = stepResult.prevGrid && stepResult.newGrid
            ? computeChangeMapJS(stepResult.prevGrid, stepResult.newGrid)
            : null;
          const changeDetail = fullChangeMap?.change_map_text || changeSummary;
          subMessages.push({ role: 'user', content: `Action result: ${actionName} → ${changeSummary}\nState: ${nextCtx.state} | Level: ${nextCtx.levels_completed}/${nextCtx.win_levels} | Budget remaining: ${budget.remaining}\n\nChange map:\n${changeDetail}\n\nUpdated grid:\n${nextCtx.gridText}${budgetNote}\n\nContinue with your next command.` });

          continue;
        }
      }

      // If subagent didn't report, auto-summarize
      if (!subagentSummaries.find(s => s.type === agentType && s.task === task.substring(0, 60))) {
        const autoSummary = subActions.length
          ? `Executed ${subActions.length} action(s): ${subActions.map(a => ACTION_NAMES[a.action] || '?').join(', ')}`
          : (isTheorist ? 'Analysis complete' : 'No actions taken');
        mem.add(autoSummary, '', agentType);
        subagentSummaries.push({ type: agentType, task: task.substring(0, 60), steps: subActions.length, summary: autoSummary });
      }

      // If terminal, stop orchestrator loop
      if (subTerminal) {
        if (subTerminal === 'WIN' || subTerminal === 'GAME_OVER') {
          checkSessionEndAndUpload();
        }
        break;
      }

      continue; // Back to orchestrator loop
    }

    // Unknown command — treat as think
    orchestratorLog.push({ turn, type: 'unknown', command, duration_ms: durMs });
  }

  // ── Return ──
  // Steps are already executed, return empty plan
  const totalDur = Math.round(performance.now() - t0Total);
  _asPushTl({ type: 'as_orch_end', totalSteps: totalStepsExecuted, totalSubagents, duration_ms: totalDur });

  return {
    raw: '', thinking: null,
    parsed: {
      observation: `Agent Spawn — ${totalSubagents} subagent(s), ${totalStepsExecuted} step(s) executed`,
      reasoning: orchestratorLog.map(l => `Turn ${l.turn}: ${l.type}${l.agent_type ? ' (' + l.agent_type + ')' : ''}`).join(', '),
      action: 0, data: {},
      plan: [], // Empty — steps already executed via _asExecuteOneStep
    },
    model: orchModel, scaffolding: 'agent_spawn',
    _clientSide: true,
    _alreadyExecuted: true, // Signal to executePlan: no-op
    agent_spawn: {
      turn: orchestratorLog.length,
      orchestrator_log: orchestratorLog,
      subagent_summaries: subagentSummaries,
      total_steps: totalStepsExecuted,
      total_subagents: totalSubagents,
      memories: { facts: [...mem.facts], hypotheses: [...mem.hypotheses], stack: mem.stack.slice(-10) },
    },
    call_duration_ms: totalDur,
  };
}
