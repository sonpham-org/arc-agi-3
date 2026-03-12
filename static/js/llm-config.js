// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: LLM configuration getters (Phase 12 extraction)
// Extracted from llm.js to reduce core file complexity
// SRP: Pure getters for input/scaffolding settings, canvas state

function getCanvasScreenshotB64() {
  // Return the canvas content as base64 PNG (without data URL prefix)
  const dataUrl = canvas.toDataURL('image/png');
  return dataUrl.replace(/^data:image\/png;base64,/, '');
}

function getInputSettings() {
  return {
    diff: document.getElementById('inputDiff')?.checked ?? true,
    full_grid: document.getElementById('inputGrid')?.checked ?? true,
    image: document.getElementById('inputImage')?.checked ?? false,
    color_histogram: document.getElementById('inputHistogram')?.checked ?? false,
  };
}

function getScaffoldingSettings() {
  const type = activeScaffoldingType;
  const s = { scaffolding: type };

  if (type === 'linear' || type === 'linear_interrupt') {
    s.input = getInputSettings();
    s.model = getSelectedModel();
    s.thinking_level = getThinkingLevel();
    s.tools_mode = getToolsMode();
    s.planning_mode = getPlanningMode();
    s.max_tokens = getMaxTokens();
    s.interrupt_plan = document.getElementById('interruptPlan')?.checked || false;
    s.compact = getCompactSettings();
  } else if (type === 'rlm') {
    s.input = {
      diff: document.getElementById('sf_rlm_inputDiff')?.checked ?? true,
      full_grid: document.getElementById('sf_rlm_inputGrid')?.checked ?? true,
      image: document.getElementById('sf_rlm_inputImage')?.checked ?? false,
      color_histogram: document.getElementById('sf_rlm_inputHistogram')?.checked ?? false,
    };
    s.model = document.getElementById('sf_rlm_modelSelect')?.value || '';
    s.thinking_level = document.querySelector('input[name="sf_rlm_thinking"]:checked')?.value || 'low';
    s.max_tokens = parseInt(document.getElementById('sf_rlm_maxTokens')?.value) || 16384;
    s.sub_model = document.getElementById('sf_rlm_subModelSelect')?.value || '';
    s.sub_thinking_level = document.querySelector('input[name="sf_rlm_subThinking"]:checked')?.value || 'low';
    s.sub_max_tokens = parseInt(document.getElementById('sf_rlm_subMaxTokens')?.value) || 16384;
    s.planning_mode = document.querySelector('input[name="sf_rlm_planMode"]:checked')?.value || 'off';
    s.max_depth = parseInt(document.getElementById('sf_rlm_maxDepth')?.value) || 3;
    s.max_iterations = parseInt(document.getElementById('sf_rlm_maxIter')?.value) || 10;
    s.output_truncation = parseInt(document.getElementById('sf_rlm_outputTrunc')?.value) || 5000;
  } else if (type === 'three_system') {
    s.input = {
      diff: document.getElementById('sf_ts_inputDiff')?.checked ?? true,
      full_grid: document.getElementById('sf_ts_inputGrid')?.checked ?? true,
      image: document.getElementById('sf_ts_inputImage')?.checked ?? false,
      color_histogram: document.getElementById('sf_ts_inputHistogram')?.checked ?? false,
    };
    s.planner_model = document.getElementById('sf_ts_plannerModelSelect')?.value || '';
    s.planner_thinking_level = document.querySelector('input[name="sf_ts_plannerThinking"]:checked')?.value || 'low';
    s.planner_max_tokens = parseInt(document.getElementById('sf_ts_plannerMaxTokens')?.value) || 16384;
    s.monitor_model = document.getElementById('sf_ts_monitorModelSelect')?.value || '';
    s.monitor_thinking_level = document.querySelector('input[name="sf_ts_monitorThinking"]:checked')?.value || 'off';
    s.monitor_max_tokens = parseInt(document.getElementById('sf_ts_monitorMaxTokens')?.value) || 4096;
    s.replan_cooldown = parseInt(document.querySelector('input[name="sf_ts_replanCooldown"]:checked')?.value) || 3;
    s.wm_model = document.getElementById('sf_ts_wmModelSelect')?.value || '';
    s.wm_thinking_level = document.querySelector('input[name="sf_ts_wmThinking"]:checked')?.value || 'low';
    s.wm_max_tokens = parseInt(document.getElementById('sf_ts_wmMaxTokens')?.value) || 16384;
    s.planner_max_turns = parseInt(document.getElementById('sf_ts_plannerMaxTurns')?.value) || 10;
    s.wm_max_turns = parseInt(document.getElementById('sf_ts_wmMaxTurns')?.value) || 5;
    s.wm_update_every = parseInt(document.getElementById('sf_ts_wmUpdateEvery')?.value) || 5;
    s.min_plan_length = parseInt(document.querySelector('input[name="sf_ts_planHorizon"]:checked')?.value) || 5;
    s.max_plan_length = parseInt(document.getElementById('sf_ts_maxPlanLength')?.value) || 15;
    // Also set model to planner_model for DB tracking
    s.model = s.planner_model;
  } else if (type === 'two_system') {
    s.input = {
      diff: document.getElementById('sf_2s_inputDiff')?.checked ?? true,
      full_grid: document.getElementById('sf_2s_inputGrid')?.checked ?? true,
      image: document.getElementById('sf_2s_inputImage')?.checked ?? false,
      color_histogram: document.getElementById('sf_2s_inputHistogram')?.checked ?? false,
    };
    s.planner_model = document.getElementById('sf_2s_plannerModelSelect')?.value || '';
    s.planner_thinking_level = document.querySelector('input[name="sf_2s_plannerThinking"]:checked')?.value || 'low';
    s.planner_max_tokens = parseInt(document.getElementById('sf_2s_plannerMaxTokens')?.value) || 16384;
    s.monitor_model = document.getElementById('sf_2s_monitorModelSelect')?.value || '';
    s.monitor_thinking_level = document.querySelector('input[name="sf_2s_monitorThinking"]:checked')?.value || 'off';
    s.monitor_max_tokens = parseInt(document.getElementById('sf_2s_monitorMaxTokens')?.value) || 4096;
    s.replan_cooldown = parseInt(document.querySelector('input[name="sf_2s_replanCooldown"]:checked')?.value) || 3;
    s.planner_max_turns = parseInt(document.getElementById('sf_2s_plannerMaxTurns')?.value) || 10;
    s.min_plan_length = parseInt(document.querySelector('input[name="sf_2s_planHorizon"]:checked')?.value) || 5;
    s.max_plan_length = parseInt(document.getElementById('sf_2s_maxPlanLength')?.value) || 15;
    s.model = s.planner_model;
  } else if (type === 'agent_spawn') {
    s.input = {
      diff: document.getElementById('sf_as_inputDiff')?.checked ?? true,
      full_grid: document.getElementById('sf_as_inputGrid')?.checked ?? true,
      image: document.getElementById('sf_as_inputImage')?.checked ?? false,
      color_histogram: document.getElementById('sf_as_inputHistogram')?.checked ?? false,
    };
    s.orchestrator_model = document.getElementById('sf_as_orchestratorModelSelect')?.value || '';
    s.orchestrator_thinking_level = document.querySelector('input[name="sf_as_orchestratorThinking"]:checked')?.value || 'low';
    s.orchestrator_max_tokens = parseInt(document.getElementById('sf_as_orchestratorMaxTokens')?.value) || 16384;
    s.subagent_model = document.getElementById('sf_as_subagentModelSelect')?.value || '';
    s.subagent_thinking_level = document.querySelector('input[name="sf_as_subagentThinking"]:checked')?.value || 'low';
    s.subagent_max_tokens = parseInt(document.getElementById('sf_as_subagentMaxTokens')?.value) || 16384;
    s.max_subagent_budget = parseInt(document.getElementById('sf_as_maxSubagentBudget')?.value) || 5;
    s.orchestrator_max_turns = parseInt(document.getElementById('sf_as_orchestratorMaxTurns')?.value) || 5;
    s.orchestrator_history_length = parseInt(document.getElementById('sf_as_orchestratorHistoryLength')?.value) || 15;
    s.model = s.orchestrator_model;
  }

  return s;
}
