// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Linear (single-turn) scaffolding prompt builder for ARC-AGI-3. Provides
//   buildClientPrompt() — constructs the system+user message for a single LLM call
//   with grid state, RLE compression, action history, change map, tool instructions,
//   planning mode, and compact context support. Used by llm.js autoplayStep() for the
//   default linear scaffolding type. Depends on getPrompt (scaffolding.js) and
//   extractJsonFromText (json-parsing.js). Extracted from scaffolding.js in Phase 5.
// SRP/DRY check: Pass — linear prompt logic fully separated from other scaffolding types
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING-LINEAR — Linear (single-turn) prompt builder
// Extracted from scaffolding.js — Phase 5 modularization
// Depends on: getPrompt (scaffolding.js), extractJsonFromText (json-parsing.js)
// ═══════════════════════════════════════════════════════════════════════════

function buildClientPrompt(state, history, changeMap, inputSettings, toolsMode, compactContext, planningMode) {
  const grid = state.grid || [];
  const parts = [];
  const desc = getPrompt('shared.arc_description');
  parts.push(`${desc}\n\nCOLOR PALETTE: ${COLOR_PALETTE}`);

  // Inject agent priors
  const priors = getPrompt('shared.agent_priors');
  if (priors) {
    parts.push(`## AGENT MEMORY\n${priors}`);
  }

  const actions = (state.available_actions || []).map(a => `${a}=${ACTION_NAMES[a] || 'ACTION'+a}`).join(', ');
  parts.push(`## STATE\nGame: ${state.game_id} | State: ${state.state} | Levels: ${state.levels_completed}/${state.win_levels}\nAvailable actions: ${actions}`);

  // Compact context replaces verbose history when active
  if (compactContext) {
    parts.push(compactContext);
  }

  if (history && history.length) {
    const reasoningTraceOn = document.getElementById('reasoningTrace')?.checked;
    const lines = history.map(h => {
      let line = `  Step ${h.step || '?'}: ${ACTION_NAMES[h.action] || '?'} -> ${h.result_state || '?'}`;
      if (h.change_map && h.change_map.change_count > 0) {
        line += ` (${h.change_map.change_count} cells changed)`;
        if (h.change_map.change_map_text) line += `\n    Changes: ${h.change_map.change_map_text}`;
      } else if (h.change_map && h.change_map.change_count === 0) {
        line += ` (no change)`;
      }
      if (h.observation) line += ` | ${h.observation}`;
      if (reasoningTraceOn && h.reasoning) line += `\n    Reasoning: ${h.reasoning}`;
      if (h.grid) {
        const rle = h.grid.map((r, i) => `    Row ${i}: ${compressRowJS(r)}`).join('\n');
        line += `\n${rle}`;
      }
      return line;
    });
    parts.push(`## HISTORY (${history.length} steps)\n` + lines.join('\n'));
  }

  if (inputSettings.diff && changeMap && changeMap.change_count > 0) {
    parts.push(`## CHANGES (${changeMap.change_count} cells changed)\n${changeMap.change_map_text || ''}`);
  }

  if (inputSettings.full_grid) {
    const gridText = grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n');
    parts.push(`## GRID (RLE, colors 0-15)\n${gridText}`);
  }

  const tm = toolsMode === 'on';
  const pm = planningMode && planningMode !== 'off';
  const planN = pm ? parseInt(planningMode) : 0;

  const toolInstr = tm ? `\n- You can write Python code blocks to analyse the grid. Wrap code in \\\`\\\`\\\`python fences. The variable \`grid\` is a numpy 2D int array. numpy, collections, itertools, math are available. Use print() for output. Code will be executed and results appended before your final answer.\n- Include "analysis" in your JSON with a summary of what you found.` : '';
  const analysisField = tm ? ', "analysis": "<detailed spatial analysis>"' : '';

  const interruptOn = document.getElementById('interruptPlan')?.checked;
  const expectedField = (pm && interruptOn) ? ', "expected": "<what you expect to see after this plan>"' : '';
  const expectedRule = (pm && interruptOn) ? '\n- "expected": briefly describe what you expect after the plan completes (e.g. "character at the door", "score increased").' : '';

  if (pm) {
    parts.push(`## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Plan a sequence of actions (up to ${planN} steps).

Respond with EXACTLY this JSON (nothing else):
{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{"action": <n>, "data": {}}, ...]${analysisField}${expectedField}}

Rules:
- Return a "plan" array of up to ${planN} steps. Each step has "action" (0-7) and "data" ({} or {"x": <0-63>, "y": <0-63>}).
- ACTION6: set "data" to {"x": <0-63>, "y": <0-63>}.
- Other actions: set "data" to {}.${expectedRule}${toolInstr}`);
  } else {
    parts.push(`## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {}${analysisField}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {"x": <0-63>, "y": <0-63>}.
- Other actions: set "data" to {}.${toolInstr}`);
  }

  return parts.join('\n\n');
}

// parseClientLLMResponse / parseLLMResponse — defined in utils/json-parsing.js (loaded before scaffolding.js)
