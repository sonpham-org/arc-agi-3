// ═══════════════════════════════════════════════════════════════════════════
// LLM
// ═══════════════════════════════════════════════════════════════════════════

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

// estimateTokens, TOKEN_PRICES — defined in utils/tokens.js (loaded before llm.js)

let sessionTotalTokens = { input: 0, output: 0, cost: 0 };

// ── Timeline helpers ──────────────────────────────────────────────────────
function _rebuildTimelineFromSteps(steps) {
  const events = [];
  let callNum = 0;
  let planRemaining = 0;
  let currentEvent = null;
  for (const s of steps) {
    const llm = s.llm_response;

    // Agent Spawn: reconstruct as_* events from stored agent_spawn metadata
    if (llm && llm.agent_spawn) {
      const as = llm.agent_spawn;
      const ts = s.timestamp ? new Date(s.timestamp).getTime() : Date.now();
      events.push({ type: 'as_orch_start', turn: 0, timestamp: ts });

      for (const log of (as.orchestrator_log || [])) {
        if (log.type === 'think') {
          events.push({ type: 'as_orch_think', turn: log.turn, facts: log.facts || 0, hypotheses: log.hypotheses || 0, duration_ms: log.duration_ms || 0, timestamp: ts });
        } else if (log.type === 'delegate') {
          events.push({ type: 'as_orch_delegate', turn: log.turn, agent_type: log.agent_type, task: log.task || '', budget: log.budget || 0, duration_ms: log.duration_ms || 0, timestamp: ts });
          events.push({ type: 'as_sub_start', turn: log.turn, agent_type: log.agent_type, task: log.task || '', budget: log.budget || 0, parentTurn: log.turn, timestamp: ts });
          // Find matching subagent summary for report event
          const sub = (as.subagent_summaries || []).find(sm => sm.type === log.agent_type);
          if (sub) {
            // Emit act events based on step count
            for (let si = 0; si < (sub.steps || 0); si++) {
              events.push({ type: 'as_sub_act', turn: log.turn, agent_type: log.agent_type, action: 0, action_name: `Step ${si + 1}`, step_num: si, duration_ms: 0, timestamp: ts });
            }
            events.push({ type: 'as_sub_report', turn: log.turn, agent_type: log.agent_type, findings: 0, summary: sub.summary || '', steps_used: sub.steps || 0, timestamp: ts });
          }
        }
      }

      events.push({ type: 'as_orch_end', totalSteps: as.total_steps || 0, totalSubagents: as.total_subagents || 0, duration_ms: llm.call_duration_ms || 0, timestamp: ts });
      continue; // skip normal event creation for this step
    }

    if (llm && llm.parsed) {
      callNum++;
      const plan = llm.parsed.plan && Array.isArray(llm.parsed.plan) ? llm.parsed.plan : [{ action: llm.parsed.action }];
      currentEvent = {
        type: 'reasoning', duration: llm.call_duration_ms || 0, turn: callNum,
        model: llm.model || '', stepStart: s.step_num, actions: plan.map(p => p.action),
      };
      planRemaining = plan.length - 1; // first step is this one
      events.push(currentEvent);
    } else if (currentEvent && planRemaining > 0) {
      planRemaining--;
    } else {
      currentEvent = null;
      planRemaining = 0;
    }
  }
  return events;
}

// ── Timeline rendering ────────────────────────────────────────────────────
function _tlEsc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }

function _tlFormatCost(c) { return c > 0 ? '$' + c.toFixed(4) : ''; }

function _tlCallTypeLabel(ev) {
  const aType = ev.agent_type || ev.call_type || ev.type || 'executor';
  return agentLabel(aType, ev.model);
}

function _tlCssClass(ev) {
  const t = ev.agent_type || ev.call_type || ev.type || 'reasoning';
  // Normalize to a safe CSS class
  return t.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function _tlBuildDetail(ev, idx) {
  const inTok = ev.input_tokens || ev.usage?.prompt_tokens || 0;
  const outTok = ev.output_tokens || ev.usage?.candidates_tokens || 0;
  const totalTok = inTok + outTok;
  const cost = ev.cost || 0;
  const promptLen = ev.prompt_length || 0;
  let html = `<div class="tl-detail" id="tlDetail${idx}">`;
  html += `<div class="tl-meta">`;
  if (totalTok > 0) html += `<span class="tl-tokens">${inTok.toLocaleString()} in + ${outTok.toLocaleString()} out = ${totalTok.toLocaleString()} tok</span>`;
  if (cost > 0) html += `<span class="tl-cost">${_tlFormatCost(cost)}</span>`;
  if (ev.error) html += `<span style="color:var(--red)">Error: ${_tlEsc(ev.error)}</span>`;
  html += `</div>`;
  // Response preview
  const respPreview = ev.response_preview || ev.raw || '';
  if (respPreview) {
    html += `<details><summary>Response preview</summary><div class="tl-preview">${_tlEsc(respPreview.slice(0, 1000))}</div></details>`;
  }
  // Prompt preview
  const promptPreview = ev.prompt_preview || '';
  if (promptPreview) {
    html += `<details><summary>Prompt preview</summary><div class="tl-preview">${_tlEsc(promptPreview.slice(0, 500))}</div></details>`;
  }
  html += `</div>`;
  return html;
}

function _tlToggleDetail(idx) {
  const detail = document.getElementById('tlDetail' + idx);
  const block = detail?.previousElementSibling;
  if (detail) {
    detail.classList.toggle('open');
    block?.classList.toggle('expanded');
  }
}

// ── Agent Spawn Tree Timeline (SVG) ──────────────────────────────────────
// Colors and labels now auto-assigned via reasoning.js agentColor()/agentLabel()

let _asZoom = 1.0, _asPanX = 0, _asPanY = 0;
let _asDragging = false, _asDragStart = { x: 0, y: 0, panX: 0, panY: 0 };

function renderTimelineTree(container, asEvents, allEvents) {
  // Layout constants
  const TRUNK_X = 50, TRUNK_W = 24, BRANCH_W = 20;
  const MIN_H = 30, MAX_H = 200, BRANCH_GAP = 40, BRANCH_COL_W = 80;
  const PAD_TOP = 30, PAD_BOTTOM = 40;

  // Build tree structure from events
  const nodes = [];
  let y = PAD_TOP;
  let branchCol = 0; // next available branch column
  const activeBranches = []; // { agent_type, turn, col, startY, nodes: [] }

  for (let i = 0; i < asEvents.length; i++) {
    const ev = asEvents[i];
    const h = Math.max(MIN_H, Math.min(MAX_H, (ev.duration_ms || 500) / 100));

    if (ev.type === 'as_orch_start') {
      nodes.push({ ...ev, idx: i, x: TRUNK_X, y, h: MIN_H, shape: 'rect', color: agentColor('orchestrator'), trunk: true });
      y += MIN_H + 4;
    } else if (ev.type === 'as_orch_think') {
      nodes.push({ ...ev, idx: i, x: TRUNK_X, y, h, shape: 'diamond', color: agentColor('orchestrator'), trunk: true });
      y += h + 4;
    } else if (ev.type === 'as_orch_delegate') {
      const col = branchCol++;
      const branchX = TRUNK_X + TRUNK_W + BRANCH_GAP + col * BRANCH_COL_W;
      nodes.push({ ...ev, idx: i, x: TRUNK_X, y, h, shape: 'branch_dot', color: agentColor(ev.agent_type) || agentColor('orchestrator'), trunk: true, branchX, branchCol: col });
      activeBranches.push({ agent_type: ev.agent_type, turn: ev.turn, col, startY: y, x: branchX, nodes: [] });
      y += h + 4;
    } else if (ev.type === 'as_sub_start') {
      const branch = activeBranches.find(b => b.agent_type === ev.agent_type && b.turn === ev.turn);
      if (branch) {
        branch.nodes.push({ ...ev, idx: i, shape: 'rect', color: agentColor(ev.agent_type) || '#888', h: MIN_H });
      }
    } else if (ev.type === 'as_sub_tool') {
      const branch = activeBranches.find(b => b.agent_type === ev.agent_type && b.turn === ev.turn);
      if (branch) {
        branch.nodes.push({ ...ev, idx: i, shape: 'square', color: agentColor(ev.agent_type) || '#888', h: 20 });
      }
    } else if (ev.type === 'as_sub_act') {
      const branch = activeBranches.find(b => b.agent_type === ev.agent_type && b.turn === ev.turn);
      if (branch) {
        branch.nodes.push({ ...ev, idx: i, shape: 'circle', color: '#3fb950', h: 24 });
      }
    } else if (ev.type === 'as_sub_report') {
      const branch = activeBranches.find(b => b.agent_type === ev.agent_type && b.turn === ev.turn);
      if (branch) {
        branch.nodes.push({ ...ev, idx: i, shape: 'rect', color: agentColor(ev.agent_type) || '#888', h: MIN_H });
      }
    } else if (ev.type === 'as_orch_end') {
      nodes.push({ ...ev, idx: i, x: TRUNK_X, y, h: MIN_H, shape: 'rect', color: agentColor('orchestrator'), trunk: true });
      y += MIN_H + 4;
    }
  }

  // Layout branch nodes vertically within their branch
  for (const branch of activeBranches) {
    let by = branch.startY;
    for (const n of branch.nodes) {
      n.x = branch.x;
      n.y = by;
      by += n.h + 3;
    }
    branch.endY = by;
  }

  const totalW = Math.max(400, TRUNK_X + TRUNK_W + BRANCH_GAP + (branchCol + 1) * BRANCH_COL_W);
  const totalH = Math.max(y + PAD_BOTTOM, ...activeBranches.map(b => b.endY + PAD_BOTTOM));

  // Build SVG
  let svg = `<svg class="as-timeline-svg" viewBox="0 0 ${totalW} ${totalH}" xmlns="http://www.w3.org/2000/svg">`;

  // Orchestrator trunk line
  const trunkTop = PAD_TOP;
  const trunkBot = y;
  svg += `<rect x="${TRUNK_X}" y="${trunkTop}" width="${TRUNK_W}" height="${trunkBot - trunkTop}" fill="${agentColor('orchestrator')}" opacity="0.15" rx="4"/>`;
  svg += `<line x1="${TRUNK_X + TRUNK_W / 2}" y1="${trunkTop}" x2="${TRUNK_X + TRUNK_W / 2}" y2="${trunkBot}" stroke="${agentColor('orchestrator')}" stroke-width="2" opacity="0.4"/>`;

  // Trunk nodes
  for (const n of nodes) {
    const cx = n.x + TRUNK_W / 2;
    if (n.shape === 'diamond') {
      const s = 8;
      svg += `<polygon points="${cx},${n.y} ${cx + s},${n.y + n.h / 2} ${cx},${n.y + n.h} ${cx - s},${n.y + n.h / 2}" fill="${n.color}" opacity="0.85" data-event-idx="${n.idx}"/>`;
      svg += `<text x="${cx + 14}" y="${n.y + n.h / 2 + 4}" fill="${n.color}" font-size="10" font-weight="600">Think</text>`;
    } else if (n.shape === 'branch_dot') {
      svg += `<circle cx="${cx}" cy="${n.y + n.h / 2}" r="6" fill="${n.color}" data-event-idx="${n.idx}"/>`;
      // Connector line to branch
      svg += `<line x1="${cx + 6}" y1="${n.y + n.h / 2}" x2="${n.branchX}" y2="${n.y + n.h / 2}" stroke="${n.color}" stroke-width="2" stroke-dasharray="4,3" opacity="0.5"/>`;
      svg += `<text x="${cx + 14}" y="${n.y + n.h / 2 + 4}" fill="${n.color}" font-size="10" font-weight="600">${_tlEsc(n.agent_type || 'delegate')}</text>`;
    } else {
      // rect (start/end)
      svg += `<rect x="${n.x}" y="${n.y}" width="${TRUNK_W}" height="${n.h}" rx="4" fill="${n.color}" opacity="0.6" data-event-idx="${n.idx}"/>`;
      const lbl = n.type === 'as_orch_start' ? 'START' : (n.type === 'as_orch_end' ? 'END' : '');
      if (lbl) svg += `<text x="${cx}" y="${n.y + n.h / 2 + 4}" fill="#fff" font-size="8" font-weight="700" text-anchor="middle">${lbl}</text>`;
    }
  }

  // Branch bars and nodes
  for (const branch of activeBranches) {
    if (!branch.nodes.length) continue;
    const bx = branch.x;
    const bTop = branch.startY;
    const bBot = branch.endY || bTop + 30;
    // Branch background bar
    const bColor = agentColor(branch.agent_type);
    svg += `<rect x="${bx}" y="${bTop}" width="${BRANCH_W}" height="${bBot - bTop}" fill="${bColor}" opacity="0.1" rx="3"/>`;
    svg += `<line x1="${bx + BRANCH_W / 2}" y1="${bTop}" x2="${bx + BRANCH_W / 2}" y2="${bBot}" stroke="${bColor}" stroke-width="1.5" opacity="0.3"/>`;

    for (const n of branch.nodes) {
      const ncx = n.x + BRANCH_W / 2;
      if (n.shape === 'circle') {
        svg += `<circle cx="${ncx}" cy="${n.y + n.h / 2}" r="8" fill="${n.color}" opacity="0.85" data-event-idx="${n.idx}"/>`;
        const aName = n.action_name || ACTION_NAMES?.[n.action] || `A${n.action}`;
        svg += `<text x="${ncx + 14}" y="${n.y + n.h / 2 + 3}" fill="${n.color}" font-size="9">${_tlEsc(aName)}</text>`;
      } else if (n.shape === 'square') {
        svg += `<rect x="${ncx - 5}" y="${n.y + 5}" width="10" height="10" rx="2" fill="${n.color}" opacity="0.7" data-event-idx="${n.idx}"/>`;
        svg += `<text x="${ncx + 10}" y="${n.y + 14}" fill="${n.color}" font-size="9" opacity="0.7">${_tlEsc(n.tool_name || 'tool')}</text>`;
      } else {
        // rect (start/report)
        const label = n.type === 'as_sub_report' ? 'REPORT' : n.agent_type;
        svg += `<rect x="${n.x}" y="${n.y}" width="${BRANCH_W}" height="${n.h}" rx="3" fill="${n.color}" opacity="0.5" data-event-idx="${n.idx}"/>`;
        svg += `<text x="${ncx}" y="${n.y + n.h / 2 + 3}" fill="#fff" font-size="8" font-weight="600" text-anchor="middle">${_tlEsc(label).substring(0, 6)}</text>`;
      }
    }
  }

  svg += '</svg>';

  // Build container HTML
  container.innerHTML = `
    <div class="as-timeline-container" id="asTreeContainer">
      <div class="as-zoom-controls">
        <button class="as-zoom-btn" id="asCopyLogs" title="Copy logs" onclick="copyTimelineLogs()">&#128203;</button>
        <button class="as-zoom-btn" id="asZoomIn" title="Zoom in">+</button>
        <button class="as-zoom-btn" id="asZoomOut" title="Zoom out">-</button>
        <button class="as-zoom-btn" id="asZoomReset" title="Reset view">R</button>
      </div>
      ${svg}
      <div class="as-tooltip" id="asTooltip"></div>
      <div class="as-legend">
        ${[...new Set(asEvents.map(e => e.agent_type).filter(Boolean))].map(at =>
          `<div class="as-legend-item"><div class="as-legend-swatch" style="background:${agentColor(at)}"></div>${agentLabel(at)}</div>`
        ).join('')}
      </div>
    </div>`;

  // Set up interactions
  const ctr = document.getElementById('asTreeContainer');
  const svgEl = ctr?.querySelector('svg');
  const tooltip = document.getElementById('asTooltip');
  if (!ctr || !svgEl) return;

  // Reset zoom/pan state
  _asZoom = 1.0; _asPanX = 0; _asPanY = 0;
  _updateAsTransform(svgEl, ctr);

  // Zoom with scroll wheel
  ctr.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = ctr.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    const oldZoom = _asZoom;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    _asZoom = Math.max(0.2, Math.min(5, _asZoom * delta));
    // Adjust pan to zoom toward cursor
    const vw = ctr.clientWidth / oldZoom;
    const vh = ctr.clientHeight / oldZoom;
    const nvw = ctr.clientWidth / _asZoom;
    const nvh = ctr.clientHeight / _asZoom;
    _asPanX += (vw - nvw) * mx;
    _asPanY += (vh - nvh) * my;
    _updateAsTransform(svgEl, ctr);
  }, { passive: false });

  // Drag to pan
  ctr.addEventListener('mousedown', (e) => {
    if (e.target.closest('.as-zoom-btn')) return;
    _asDragging = true;
    _asDragStart = { x: e.clientX, y: e.clientY, panX: _asPanX, panY: _asPanY };
    ctr.classList.add('dragging');
  });
  ctr.addEventListener('mousemove', (e) => {
    if (!_asDragging) return;
    const dx = (e.clientX - _asDragStart.x) / _asZoom;
    const dy = (e.clientY - _asDragStart.y) / _asZoom;
    _asPanX = _asDragStart.panX - dx;
    _asPanY = _asDragStart.panY - dy;
    _updateAsTransform(svgEl, ctr);
  });
  const endDrag = () => { _asDragging = false; ctr.classList.remove('dragging'); };
  ctr.addEventListener('mouseup', endDrag);
  ctr.addEventListener('mouseleave', endDrag);

  // Zoom buttons
  document.getElementById('asZoomIn')?.addEventListener('click', () => {
    _asZoom = Math.min(5, _asZoom * 1.3); _updateAsTransform(svgEl, ctr);
  });
  document.getElementById('asZoomOut')?.addEventListener('click', () => {
    _asZoom = Math.max(0.2, _asZoom / 1.3); _updateAsTransform(svgEl, ctr);
  });
  document.getElementById('asZoomReset')?.addEventListener('click', () => {
    _asZoom = 1.0; _asPanX = 0; _asPanY = 0; _updateAsTransform(svgEl, ctr);
  });

  // Hover tooltip
  svgEl.addEventListener('mouseover', (e) => {
    const el = e.target.closest('[data-event-idx]');
    if (!el || !tooltip) return;
    const idx = parseInt(el.getAttribute('data-event-idx'));
    const ev = asEvents[idx];
    if (!ev) return;
    let html = `<div class="as-tt-title">${_tlEsc(agentLabel(ev.agent_type || ev.type))}</div>`;
    html += `<div class="as-tt-meta">`;
    if (ev.agent_type) html += `<span>Agent: ${_tlEsc(ev.agent_type)}</span> `;
    if (ev.duration_ms) html += `<span>${(ev.duration_ms / 1000).toFixed(1)}s</span>`;
    html += `</div>`;
    if (ev.type === 'as_orch_think') {
      html += `<div class="as-tt-body">Facts: ${ev.facts || 0}, Hypotheses: ${ev.hypotheses || 0}`;
      if (ev.reasoning) html += `\n${_tlEsc(ev.reasoning)}`;
      if (ev.error) html += `\n<span style="color:#f85149">ERROR: ${_tlEsc(ev.error)}</span>`;
      html += `</div>`;
    } else if (ev.type === 'as_orch_delegate') {
      html += `<div class="as-tt-body">Task: ${_tlEsc(ev.task || '')}\nBudget: ${ev.budget || 0} steps`;
      if (ev.reasoning) html += `\nReasoning: ${_tlEsc(ev.reasoning)}`;
      html += `</div>`;
    } else if (ev.type === 'as_sub_start') {
      html += `<div class="as-tt-body">Task: ${_tlEsc(ev.task || '')}`;
      html += `\nBudget: ${ev.budget || 0} steps`;
      if (ev.step_num != null) html += `\nStep: ${ev.step_num}`;
      if (ev.level) html += ` | Level: ${ev.level}`;
      if (ev.available_actions) html += `\nActions: ${_tlEsc(ev.available_actions)}`;
      if (ev.memory_summary) html += `\n\nMemory:\n${_tlEsc(ev.memory_summary)}`;
      html += `</div>`;
    } else if (ev.type === 'as_sub_act') {
      html += `<div class="as-tt-body">${_tlEsc(ev.action_name || '')}${ev.reasoning ? '\n' + _tlEsc(ev.reasoning) : ''}</div>`;
    } else if (ev.type === 'as_sub_report') {
      html += `<div class="as-tt-body">${_tlEsc(ev.summary || '')}\nFindings: ${ev.findings || 0}, Steps: ${ev.steps_used || 0}</div>`;
    } else if (ev.type === 'as_sub_tool') {
      html += `<div class="as-tt-body">Tool: ${_tlEsc(ev.tool_name || '')}</div>`;
    } else if (ev.type === 'as_orch_end') {
      html += `<div class="as-tt-body">Total: ${ev.totalSteps || 0} steps, ${ev.totalSubagents || 0} subagents\n${(ev.duration_ms / 1000).toFixed(1)}s</div>`;
    }
    tooltip.innerHTML = html;
    tooltip.classList.add('visible');
  });
  svgEl.addEventListener('mousemove', (e) => {
    if (!tooltip || !tooltip.classList.contains('visible')) return;
    const rect = ctr.getBoundingClientRect();
    tooltip.style.left = (e.clientX - rect.left + 12) + 'px';
    tooltip.style.top = (e.clientY - rect.top + 12) + 'px';
  });
  svgEl.addEventListener('mouseout', (e) => {
    const el = e.target.closest('[data-event-idx]');
    if (el && tooltip) tooltip.classList.remove('visible');
  });
  // Click to scrub to that step
  svgEl.addEventListener('click', (e) => {
    const el = e.target.closest('[data-event-idx]');
    if (!el) return;
    const idx = parseInt(el.getAttribute('data-event-idx'));
    const ev = asEvents[idx];
    if (ev && ev.step_num != null) {
      liveScrubToStep(ev.step_num);
    }
  });
  svgEl.style.cursor = 'pointer';
}

function _updateAsTransform(svg, container) {
  const w = container.clientWidth / _asZoom;
  const h = container.clientHeight / _asZoom;
  svg.setAttribute('viewBox', `${_asPanX} ${_asPanY} ${w} ${h}`);
}

function renderTimeline(ss) {
  const container = document.getElementById('timelineContent');
  if (!container) return;
  let events = ss ? ss.timelineEvents : [];
  // If in replay mode and no session events, build from replayData
  if (!events.length && typeof replayData !== 'undefined' && replayData && replayData.steps) {
    events = _rebuildTimelineFromSteps(replayData.steps);
  }

  // Agent Spawn tree view — if as_* events exist, render tree
  const asEvents = events.filter(e => e.type && e.type.startsWith('as_'));
  if (asEvents.length > 0) {
    renderTimelineTree(container, asEvents, events);
    return;
  }

  if (!events.length && !(ss && ss.waitingForLLM)) {
    container.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Timeline will populate as LLM calls are made.</div>';
    return;
  }
  // Group events by turn
  const turns = {};
  for (const ev of events) {
    const t = ev.turn || 0;
    if (!turns[t]) turns[t] = [];
    turns[t].push(ev);
  }
  let html = '<div style="display:flex;justify-content:flex-end;margin-bottom:4px;"><button class="as-zoom-btn" onclick="copyTimelineLogs()" title="Copy logs" style="font-size:11px;width:auto;padding:2px 8px;">Copy logs</button></div>';
  let evIdx = 0;
  // In-flight block (pulsing, live timer)
  if (ss && ss.waitingForLLM && ss.waitStartTime) {
    const elapsed = ((performance.now() - ss.waitStartTime) / 1000).toFixed(1);
    html += `<div class="timeline-block reasoning in-flight" id="tlInFlight">
      <span class="tl-label"><span class="spinner" style="margin-right:4px;"></span>Reasoning...</span>
      <span class="tl-dur">${elapsed}s</span>
    </div>`;
  }
  // Reverse chronological: newest turn first
  for (const turn of Object.keys(turns).sort((a, b) => b - a)) {
    html += `<div class="timeline-turn-marker">Turn ${turn}</div>`;
    for (const ev of turns[turn]) {
      const h = Math.max(28, Math.min(120, ev.duration / 50));
      const dur = (ev.duration / 1000).toFixed(1) + 's';
      const label = _tlCallTypeLabel(ev);
      const cssClass = _tlCssClass(ev);
      const hasDetail = ev.call_id || ev.input_tokens || ev.response_preview || ev.prompt_preview || ev.raw || ev.error;
      // Build step details
      let stepsHtml = '';
      if (ev.actions && ev.actions.length) {
        const stepParts = ev.actions.map((a, i) => {
          const stepNum = (ev.stepStart || 0) + i;
          const name = ACTION_NAMES[a] || `A${a}`;
          return `<span class="tl-step tl-step-clickable" onclick="event.stopPropagation();liveScrubToStep(${stepNum})">${stepNum}:${name}</span>`;
        });
        stepsHtml = `<span class="tl-steps">${stepParts.join(' ')}</span>`;
      }
      // Cost badge
      const costStr = _tlFormatCost(ev.cost || 0);
      const costHtml = costStr ? `<span class="tl-cost" style="margin-left:6px;font-size:10px;">${costStr}</span>` : '';
      const arrowHtml = hasDetail ? '<span class="tl-expand-arrow">&#9654;</span>' : '';
      const clickAttr = hasDetail ? `onclick="_tlToggleDetail(${evIdx})" class="timeline-block ${cssClass} clickable"` : `class="timeline-block ${cssClass}"`;
      html += `<div ${clickAttr} style="height:${h}px">
        <span class="tl-label">${_tlEsc(label)}${stepsHtml}${costHtml}${arrowHtml}</span><span class="tl-dur">${dur}</span>
      </div>`;
      if (hasDetail) {
        html += _tlBuildDetail(ev, evIdx);
      }
      evIdx++;
    }
  }
  container.innerHTML = html;
}

// formatTokenInfo — defined in utils/tokens.js (loaded before llm.js)

// Render tool calls as collapsible HTML (reused in reasoning + replay)
function renderToolCallsHtml(toolCalls) {
  if (!toolCalls || !toolCalls.length) return '';
  const items = toolCalls.map(tc => {
    const name = tc.name || tc.function?.name || '?';
    const args = tc.arguments || tc.function?.arguments;
    const code = typeof args === 'object' ? (args.code || JSON.stringify(args, null, 1)) : (args || '');
    const output = tc.output || '';
    return `<div class="tool-call">` +
      `<span class="tool-name">${name}</span>` +
      (code ? `<div class="tool-input">${escapeHtml(code)}</div>` : '') +
      (output ? `<div class="tool-output">${escapeHtml(output)}</div>` : '') +
      `</div>`;
  }).join('');
  const label = toolCalls.length === 1 ? '1 tool call' : `${toolCalls.length} tool calls`;
  return `<details class="tool-calls-wrap"><summary>${label}</summary>${items}</details>`;
}

function scrollReasoningToBottom() {
  const el = document.getElementById('reasoningContent');
  if (el) el.scrollTop = el.scrollHeight;
}
function copyReasoningLog() {
  const s = getActiveSession();
  const buf = s ? s.sessionStepsBuffer : sessionStepsBuffer;
  if (!buf || !buf.length) {
    navigator.clipboard.writeText('(no steps recorded)');
    _flashCopyBtn('Copied (empty)');
    return;
  }
  const lines = [];
  lines.push(`=== Reasoning Log (${buf.length} steps) ===`);
  lines.push(`Session: ${s?.sessionId || sessionId || '?'}`);
  lines.push(`Game: ${s?.gameId || ''}`);
  lines.push(`Model: ${s?.model || getSelectedModel() || '?'}`);
  lines.push('');
  for (const step of buf) {
    lines.push(`--- Step ${step.step_num} | Action ${step.action} (${ACTION_NAMES[step.action] || '?'}) ---`);
    if (step.data && Object.keys(step.data).length) lines.push(`Data: ${JSON.stringify(step.data)}`);
    if (step.levels_completed !== undefined) lines.push(`Levels: ${step.levels_completed} | State: ${step.result_state || '?'}`);
    const resp = step.llm_response;
    if (resp) {
      if (resp.parsed) {
        const p = resp.parsed;
        if (p.observation) lines.push(`Observation: ${p.observation}`);
        if (p.reasoning) lines.push(`Reasoning: ${p.reasoning}`);
        if (p.plan && Array.isArray(p.plan)) {
          lines.push(`Plan (${p.plan.length} actions): ${JSON.stringify(p.plan)}`);
        } else if (p.action !== undefined) {
          lines.push(`Action: ${p.action} Data: ${JSON.stringify(p.data || {})}`);
        }
      }
      if (resp.model) lines.push(`Model: ${resp.model}`);
      if (resp.scaffolding) lines.push(`Scaffolding: ${resp.scaffolding}`);
      // RLM iteration log
      if (resp.rlm?.log?.length) {
        lines.push(`RLM: ${resp.rlm.iterations} iterations, ${resp.rlm.sub_calls || 0} sub-calls`);
        for (const it of resp.rlm.log) {
          lines.push(`  [Iter ${it.iteration + 1}]${it.code_blocks ? ` (${it.code_blocks} code blocks)` : ''}`);
          if (it.error) { lines.push(`    ERROR: ${it.error}`); continue; }
          if (it.response) lines.push(`    Response: ${it.response.substring(0, 2000)}${it.response.length > 2000 ? '...' : ''}`);
          if (it.repl_outputs?.length) {
            for (const o of it.repl_outputs) lines.push(`    REPL: ${o.substring(0, 1000)}${o.length > 1000 ? '...' : ''}`);
          }
        }
        if (resp.rlm.final_answer) lines.push(`  FINAL: ${resp.rlm.final_answer}`);
      }
      // Three-system planner log
      if (resp.three_system?.planner_log?.length) {
        lines.push(`Planner log (${resp.three_system.planner_log.length} iterations):`);
        for (const it of resp.three_system.planner_log) {
          lines.push(`  [Iter] ${JSON.stringify(it).substring(0, 500)}`);
        }
      }
      if (resp.raw && !resp.rlm && !resp.three_system) {
        lines.push(`Raw: ${resp.raw.substring(0, 1000)}${resp.raw.length > 1000 ? '...' : ''}`);
      }
    }
    lines.push('');
  }
  navigator.clipboard.writeText(lines.join('\n'));
  _flashCopyBtn('Copied!');
}
function _flashCopyBtn(msg) {
  const btn = document.querySelector('.reasoning-toolbar button');
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => { btn.textContent = orig; }, 1500);
}
function copyTimelineLogs() {
  const s = getActiveSession();
  const events = s ? s.timelineEvents : [];
  if (!events || !events.length) {
    navigator.clipboard.writeText('(no timeline events)');
    const btn = document.getElementById('asCopyLogs');
    if (btn) { const o = btn.textContent; btn.textContent = 'Copied'; setTimeout(() => btn.textContent = o, 1500); }
    return;
  }
  const lines = [];
  lines.push(`=== Timeline Log (${events.length} events) ===`);
  lines.push(`Session: ${s?.sessionId || sessionId || '?'}`);
  lines.push(`Game: ${s?.gameId || ''}`);
  lines.push(`Model: ${s?.model || getSelectedModel() || '?'}`);
  lines.push('');
  const t0 = events[0]?.timestamp || 0;
  for (const ev of events) {
    const elapsed = t0 ? `+${Math.round(((ev.timestamp || 0) - t0) / 1000)}s` : '';
    const time = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : '';
    const agent = ev.agent_type || ev.current_agent || 'orchestrator';
    const type = ev.type || '?';
    const parts = [time.padEnd(12), elapsed.padEnd(8), agent.padEnd(14), type.padEnd(22)];
    // Add key details
    const details = [];
    if (ev.task) details.push(`task: ${ev.task}`);
    if (ev.budget) details.push(`budget: ${ev.budget}`);
    if (ev.facts) details.push(`facts: ${ev.facts}`);
    if (ev.hypotheses) details.push(`hypotheses: ${ev.hypotheses}`);
    if (ev.action_name) details.push(`action: ${ev.action_name}`);
    if (ev.reasoning) details.push(`reason: ${ev.reasoning}`);
    if (ev.summary) details.push(`summary: ${ev.summary}`);
    if (ev.error) details.push(`ERROR: ${ev.error}`);
    if (ev.duration_ms) details.push(`${ev.duration_ms}ms`);
    if (ev.totalSteps != null) details.push(`steps: ${ev.totalSteps}`);
    if (ev.totalSubagents != null) details.push(`subagents: ${ev.totalSubagents}`);
    parts.push(details.join(' | '));
    lines.push(parts.join(''));
  }
  // Also include orchestrator log if available
  const buf = s ? s.sessionStepsBuffer : [];
  if (buf?.length) {
    lines.push('');
    lines.push(`=== Steps (${buf.length}) ===`);
    for (const step of buf) {
      const resp = step.llm_response;
      if (resp?.agent_spawn?.orchestrator_log) {
        for (const entry of resp.agent_spawn.orchestrator_log) {
          lines.push(`  Turn ${entry.turn}: ${entry.type} ${entry.error || ''} ${entry.task || ''} ${entry.raw_preview || ''}`);
        }
      }
    }
  }
  navigator.clipboard.writeText(lines.join('\n'));
  const btn = document.getElementById('asCopyLogs');
  if (btn) { const o = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = o, 1500); }
}
function getLastReasoningEntry() {
  const el = document.getElementById('reasoningContent');
  if (!el) return null;
  const entries = el.querySelectorAll('.reasoning-entry');
  return entries.length ? entries[entries.length - 1] : null;
}

// buildReasoningGroupHTML is now defined in reasoning.js (loaded before this file)

// Legacy scaffolding-specific renderer removed — unified version in reasoning.js handles all cases.
// Keeping this block as a marker. The function below is a no-op fallback.
if (typeof buildReasoningGroupHTML === 'undefined') {
  // Should never happen — reasoning.js must load first
  console.error('reasoning.js not loaded before llm.js!');
}


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
// TRANSPORT CONTROLS: Step, Auto, Pause, Undo
// ═══════════════════════════════════════════════════════════════════════════

function updateUndoBtn() {
  const btn = document.getElementById('undoBtn');
  btn.disabled = undoStack.length === 0;
}

function updateAutoBtn() {
  const btn = document.getElementById('autoPlayBtn');
  if (autoPlaying) {
    btn.innerHTML = '&#9208; Pause';
    btn.classList.add('btn-pause');
  } else {
    btn.innerHTML = '&#187; Agent Autoplay';
    btn.classList.remove('btn-pause');
  }
}

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
    const isScaffoldPlan = resp?.scaffolding === 'three_system' || resp?.scaffolding === 'two_system' || resp?.scaffolding === 'rlm' || resp?.scaffolding === 'agent_spawn';
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

async function stepOnce() {
  if (!sessionId) { alert('Start a game first'); return; }
  if (currentState.state !== 'NOT_FINISHED') return;
  lockHumanControls();
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

async function testModel() {
  const model = getSelectedModel();
  if (!model) return;
  const btn = document.getElementById('testBtn');
  const resultEl = document.getElementById('testResult');
  btn.disabled = true;
  btn.textContent = '⏳ Testing...';
  resultEl.style.display = 'block';
  resultEl.style.background = '#333';
  resultEl.style.color = '#aaa';
  resultEl.textContent = `Testing ${model}...`;

  try {
    const modelInfo = getModelInfo(model);
    const provider = modelInfo?.provider;
    const testPrompt = 'Reply with exactly: {"action": 1, "observation": "test"}';
    const t0 = performance.now();
    let result;
    result = await callLLM([{role: 'user', content: testPrompt}], model);
    const latency = Math.round(performance.now() - t0);
    resultEl.style.background = '#1a3a1a';
    resultEl.style.color = '#6f6';
    resultEl.innerHTML = `<b>${model}</b> ✓ ${latency}ms`;
  } catch (e) {
    resultEl.style.background = '#3a1a1a';
    resultEl.style.color = '#f66';
    resultEl.textContent = `Error: ${e.message}`;
  }
  btn.disabled = false;
  btn.textContent = '🔗 Test';
}

