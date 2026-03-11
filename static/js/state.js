// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Global application state and settings management for ARC-AGI-3 web UI.
//   Declares all global state variables (sessionId, currentGrid, moveHistory, etc.),
//   feature flags (FEATURES), color palette (COLORS), settings persistence helpers
//   (getScaffoldingSettings, attachSettingsListeners), scaffolding settings panel
//   rendering (renderScaffoldingSettings from SCAFFOLDING_SCHEMAS), session state
//   class (SessionState), multi-session tab management, and pipeline opacity updates.
//   Modified in Phase 3 to extract SCAFFOLDING_SCHEMAS to config/scaffolding-schemas.js.
// SRP/DRY check: Pass — schemas in config/scaffolding-schemas.js; rendering in ui.js;
//   this file owns state declarations and settings wiring
// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════

let canvas = document.getElementById('gameCanvas');
let ctx = canvas.getContext('2d');

let sessionId = null;
let currentUser = null;  // {id, email, display_name} or null
let currentGrid = null;
let previousGrid = null;
let currentChangeMap = null;
let currentState = {};
let stepCount = 0;
let llmCallCount = 0;  // counts agent/LLM calls (not game steps)
let moveHistory = [];
let autoPlaying = false;
let action6Mode = false;
let modelsData = [];  // {name, provider, capabilities, available}
let undoStack = [];   // local undo snapshots (grid + state for each step)
let humanLocked = true;  // human controls locked by default
let turnCounter = 0;     // monotonic turn counter for undo grouping
let apiMode = 'local';
const clientId = 'client_' + Math.random().toString(36).slice(2, 10);
let _liveScrubMode = true;     // true = following live, false = viewing historical
let _liveScrubViewIdx = -1;    // index into moveHistory being viewed
let _liveScrubLiveGrid = null; // stashed live grid when viewing historical


// ── Scaffolding Settings Renderer ─────────────────────────────────────────

function renderScaffoldingSettings(schemaId) {
  const schema = SCAFFOLDING_SCHEMAS[schemaId];
  if (!schema) return;
  activeScaffoldingType = schemaId;
  const container = document.getElementById('settingsColumns');
  if (!container) return;
  let html = '';

  // ── Scaffolding selector + pipeline visualizer ──
  html += '<div style="padding:8px 14px 0;border-bottom:1px solid var(--border);">';
  html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">';
  html += '<span style="font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Scaffolding</span>';
  html += '<select id="scaffoldingSelect" style="flex:1;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-family:inherit;font-size:12px;" onchange="switchScaffolding(this.value)">';
  for (const key of Object.keys(SCAFFOLDING_SCHEMAS)) {
    const s = SCAFFOLDING_SCHEMAS[key];
    html += `<option value="${key}"${key === schemaId ? ' selected' : ''}>${s.name}</option>`;
  }
  html += '</select></div>';
  html += `<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;">${schema.description}</div>`;
  html += '<div id="pipelineVisualizer"></div>';
  html += '</div>';
  html += '<div id="settingsBody">';

  for (const section of schema.sections) {
    const openCls = section.open ? ' open' : '';
    html += `<div class="opt-section${openCls}" id="${section.id}">`;
    html += `<div class="opt-header" onclick="toggleSection('${section.id}')">`;
    html += `<span>${section.label}</span><span class="chevron">&#9654;</span></div>`;

    if (section.customHtml) {
      html += `<div class="opt-body">${section.customHtml()}</div>`;
    } else if (section.fields) {
      // Simple section with flat fields
      html += `<div class="opt-body${section.bodyClass ? ' ' + section.bodyClass : ''}">`;
      for (const f of section.fields) {
        html += renderField(f);
      }
      html += '</div>';
    } else if (section.groups) {
      // Section with sub-groups (like Reasoning)
      html += '<div class="opt-body">';
      for (const g of section.groups) {
        html += renderGroup(g);
      }
      html += '</div>';
    }
    html += '</div>';
  }
  html += '</div>'; // close #settingsBody

  container.innerHTML = html;

  // Re-attach event listeners for dynamically rendered settings elements
  attachSettingsListeners();

  // Render pipeline SVG
  renderPipelineVisualizer(schema);

  // Re-render prompts tab if it's currently visible
  if (document.getElementById('subtabPrompts')?.classList.contains('active')) renderPromptsTab();
}

function switchScaffolding(schemaId) {
  if (!SCAFFOLDING_SCHEMAS[schemaId]) return;
  // Save current settings before switching
  saveScaffoldingToStorage();
  localStorage.setItem('arc_scaffolding_type', schemaId);
  renderScaffoldingSettings(schemaId);
  // Restore saved settings for the new scaffolding
  loadScaffoldingFromStorage(schemaId);
  // Reload models into new selects
  if (typeof loadModels === 'function') loadModels();
}

function renderPipelineVisualizer(schema) {
  const container = document.getElementById('pipelineVisualizer');
  if (!container || !schema.pipeline?.length) { if (container) container.innerHTML = ''; return; }

  const nodes = schema.pipeline;
  const edges = schema.edges || [];

  // Check enabled state for optional nodes
  function isNodeEnabled(node) {
    if (!node.enabledBy) return true;
    const [group, field] = node.enabledBy.split('.');
    if (field === 'enabled') {
      const toggleMap = { compact: 'compactContext', interrupt: 'interruptPlan' };
      const el = document.getElementById(toggleMap[group] || '');
      return el ? el.checked : true;
    }
    return true;
  }

  // Agent Spawn: custom 3-row layout (Orchestrator → 4 agents side-by-side → Memory)
  if (schema.id === 'agent_spawn') {
    const agentIds = ['explorer', 'theorist', 'tester', 'solver'];
    const agentNodes = nodes.filter(n => agentIds.includes(n.id));
    const orchNode = nodes.find(n => n.id === 'orchestrator');
    const memNode = nodes.find(n => n.id === 'memory');
    const aCount = agentNodes.length;
    const aW = 90, aH = 26, aGap = 8, orchW = 140, orchH = 30, memW = 140, memH = 26;
    const totalAgentW = aCount * aW + (aCount - 1) * aGap;
    const svgW = Math.max(totalAgentW, orchW, memW) + 40;
    const centerX = svgW / 2;
    const row1Y = 12, row2Y = 80, row3Y = 148;

    const nodePos = {};
    if (orchNode) nodePos[orchNode.id] = { x: centerX - orchW / 2, y: row1Y, w: orchW, h: orchH };
    const agentStartX = centerX - totalAgentW / 2;
    agentNodes.forEach((n, i) => {
      nodePos[n.id] = { x: agentStartX + i * (aW + aGap), y: row2Y, w: aW, h: aH };
    });
    if (memNode) nodePos[memNode.id] = { x: centerX - memW / 2, y: row3Y, w: memW, h: memH };
    const svgH = row3Y + memH + 12;

    let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto 8px;">`;
    svg += '<defs><marker id="arrow" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)"/></marker>';
    svg += '<marker id="arrowDash" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)" opacity="0.5"/></marker></defs>';

    // Edges: orchestrator → each agent (delegate)
    for (const agent of agentNodes) {
      const op = nodePos['orchestrator'], ap = nodePos[agent.id];
      if (op && ap) {
        const x1 = op.x + op.w / 2, y1 = op.y + op.h;
        const x2 = ap.x + ap.w / 2, y2 = ap.y;
        svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrow)" opacity="0.4"/>`;
        const lx = (x1 + x2) / 2 + 4, ly = (y1 + y2) / 2;
        svg += `<text x="${lx}" y="${ly}" font-size="7" fill="var(--text-dim)" opacity="0.4" dominant-baseline="middle">delegate</text>`;
      }
    }
    // Edges: each agent → memory (report)
    for (const agent of agentNodes) {
      const ap = nodePos[agent.id], mp = nodePos['memory'];
      if (ap && mp) {
        const x1 = ap.x + ap.w / 2, y1 = ap.y + ap.h;
        const x2 = mp.x + mp.w / 2, y2 = mp.y;
        svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrow)" opacity="0.4"/>`;
      }
    }
    // Edge: memory → orchestrator (context, back edge)
    if (nodePos['memory'] && nodePos['orchestrator']) {
      const mp = nodePos['memory'], op = nodePos['orchestrator'];
      const x1 = mp.x + mp.w, y1 = mp.y + mp.h / 2;
      const x2 = op.x + op.w, y2 = op.y + op.h / 2;
      const curveX = svgW - 8;
      svg += `<path d="M${x1} ${y1} C${curveX} ${y1}, ${curveX} ${y2}, ${x2} ${y2}" fill="none" stroke="var(--text-dim)" stroke-width="1" stroke-dasharray="4 3" marker-end="url(#arrowDash)" opacity="0.35"/>`;
      svg += `<text x="${curveX - 2}" y="${(y1 + y2) / 2}" font-size="7" fill="var(--text-dim)" opacity="0.35" text-anchor="end" dominant-baseline="middle">context</text>`;
    }

    // Draw nodes
    for (const node of nodes) {
      const p = nodePos[node.id];
      if (!p) continue;
      svg += `<g data-node="${node.id}">`;
      svg += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="6" fill="none" stroke="${node.color}" stroke-width="1.5"/>`;
      svg += `<text x="${p.x + p.w/2}" y="${p.y + p.h/2 + 1}" font-size="${agentIds.includes(node.id) ? 9 : 10}" fill="${node.color}" text-anchor="middle" dominant-baseline="middle" font-weight="600">${node.label}</text>`;
      svg += '</g>';
    }

    svg += '</svg>';
    container.innerHTML = svg;
    return;
  }

  // Default vertical layout for other scaffoldings
  const nodeW = 140, nodeH = 30, gapY = 36, padX = 40, padTop = 12, padBot = 12;
  const svgW = nodeW + padX * 2 + 60;
  const svgH = padTop + nodes.length * nodeH + (nodes.length - 1) * gapY + padBot;

  const nodePos = {};
  nodes.forEach((n, i) => {
    nodePos[n.id] = { x: padX, y: padTop + i * (nodeH + gapY), w: nodeW, h: nodeH };
  });

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto 8px;">`;
  svg += '<defs>';
  svg += '<marker id="arrow" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)"/></marker>';
  svg += '<marker id="arrowDash" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)" opacity="0.5"/></marker>';
  svg += '</defs>';

  const nodeIdx = {};
  nodes.forEach((n, i) => nodeIdx[n.id] = i);

  for (const e of edges) {
    const fromP = nodePos[e.from];
    const toP = nodePos[e.to];
    if (!fromP || !toP) continue;

    const fromIdx = nodeIdx[e.from];
    const toIdx = nodeIdx[e.to];
    const isBack = toIdx <= fromIdx;

    const fromEnabled = isNodeEnabled(nodes[fromIdx]);
    const toEnabled = isNodeEnabled(nodes[toIdx]);
    const edgeOpacity = (fromEnabled && toEnabled) ? 1 : 0.25;

    if (isBack) {
      const x1 = fromP.x + fromP.w;
      const y1 = fromP.y + fromP.h / 2;
      const x2 = toP.x + toP.w;
      const y2 = toP.y + toP.h / 2;
      const curveX = padX + nodeW + 35;
      svg += `<path d="M${x1} ${y1} C${curveX} ${y1}, ${curveX} ${y2}, ${x2} ${y2}" fill="none" stroke="var(--text-dim)" stroke-width="1" stroke-dasharray="4 3" marker-end="url(#arrowDash)" opacity="${edgeOpacity * 0.5}"/>`;
      const labelX = curveX + 2;
      const labelY = (y1 + y2) / 2;
      if (e.label) svg += `<text x="${labelX}" y="${labelY}" font-size="8" fill="var(--text-dim)" opacity="${edgeOpacity * 0.5}" dominant-baseline="middle">${e.label}</text>`;
    } else {
      const x = fromP.x + fromP.w / 2;
      const y1 = fromP.y + fromP.h;
      const y2 = toP.y;
      svg += `<line x1="${x}" y1="${y1}" x2="${x}" y2="${y2}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrow)" opacity="${edgeOpacity * 0.4}"/>`;
      if (e.label) {
        const labelY = (y1 + y2) / 2;
        svg += `<text x="${x + 6}" y="${labelY}" font-size="8" fill="var(--text-dim)" opacity="${edgeOpacity * 0.4}" dominant-baseline="middle">${e.label}</text>`;
      }
    }
  }

  for (const node of nodes) {
    const p = nodePos[node.id];
    const enabled = isNodeEnabled(node);
    const opacity = enabled ? 1 : 0.25;
    svg += `<g data-node="${node.id}" opacity="${opacity}">`;
    svg += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="6" fill="none" stroke="${node.color}" stroke-width="1.5"/>`;
    svg += `<text x="${p.x + p.w/2}" y="${p.y + p.h/2 + 1}" font-size="10" fill="${node.color}" text-anchor="middle" dominant-baseline="middle" font-weight="600">${node.label}</text>`;
    if (node.optional) {
      svg += `<text x="${p.x + p.w - 4}" y="${p.y + 8}" font-size="7" fill="var(--text-dim)" text-anchor="end" opacity="0.6">opt</text>`;
    }
    svg += '</g>';
  }

  svg += '</svg>';
  container.innerHTML = svg;
}

function updatePipelineOpacity() {
  const schema = SCAFFOLDING_SCHEMAS[activeScaffoldingType];
  if (!schema) return;
  renderPipelineVisualizer(schema);
}

function updateScaffoldingNodeState(nodeId, state) {
  const container = document.getElementById('pipelineVisualizer');
  if (!container) return;
  const svgEl = container.querySelector('svg');
  if (!svgEl) return;
  const nodeGroup = svgEl.querySelector(`g[data-node="${nodeId}"]`);
  if (!nodeGroup) return;

  nodeGroup.classList.remove('node-waiting', 'node-done');

  if (state === 'waiting') {
    nodeGroup.classList.add('node-waiting');
    if (!nodeGroup.querySelector('.node-spinner')) {
      const rect = nodeGroup.querySelector('rect');
      if (rect) {
        const cx = parseFloat(rect.getAttribute('x')) + parseFloat(rect.getAttribute('width')) - 12;
        const cy = parseFloat(rect.getAttribute('y')) + parseFloat(rect.getAttribute('height')) / 2;
        const r = parseFloat(rect.getAttribute('height')) * 0.25;
        const spinner = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        spinner.setAttribute('cx', cx);
        spinner.setAttribute('cy', cy);
        spinner.setAttribute('r', r);
        spinner.setAttribute('fill', 'none');
        spinner.setAttribute('stroke', 'var(--accent)');
        spinner.setAttribute('stroke-width', '2');
        spinner.setAttribute('stroke-dasharray', `${r * 2} ${r * 4}`);
        spinner.classList.add('node-spinner');
        spinner.style.transformOrigin = `${cx}px ${cy}px`;
        spinner.style.animation = 'spin 0.6s linear infinite';
        nodeGroup.appendChild(spinner);
      }
    }
  } else if (state === 'done') {
    const sp = nodeGroup.querySelector('.node-spinner');
    if (sp) sp.remove();
    nodeGroup.classList.add('node-done');
    setTimeout(() => { nodeGroup.classList.remove('node-done'); }, 600);
  } else {
    const sp = nodeGroup.querySelector('.node-spinner');
    if (sp) sp.remove();
  }
}

// ── Scaffolding Settings Persistence ──────────────────────────────────────

function saveScaffoldingToStorage() {
  try {
    const settings = getScaffoldingSettings();
    localStorage.setItem(`arc_scaffolding_${activeScaffoldingType}`, JSON.stringify(settings));
  } catch {}
}

function loadScaffoldingFromStorage(schemaId) {
  try {
    const raw = localStorage.getItem(`arc_scaffolding_${schemaId}`);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (schemaId === 'linear' || schemaId === 'linear_interrupt') {
      // Restore linear/linear_interrupt settings to DOM
      _setChecked('inputGrid', s.input?.full_grid ?? true);
      _setChecked('inputImage', s.input?.image ?? false);
      _setChecked('inputDiff', s.input?.diff ?? true);
      _setChecked('inputHistogram', s.input?.color_histogram ?? false);
      _setRadio('thinkingLevel', s.thinking_level || 'low');
      _setRadio('toolsMode', s.tools_mode || 'on');
      _setRadio('planMode', s.planning_mode || '10');
      _setVal('maxTokensLimit', s.max_tokens || 16384);
      _setChecked('compactContext', s.compact?.enabled ?? true);
      toggleCompactSettings();
      if (s.compact?.after) _setVal('compactAfter', s.compact.after);
      if (s.compact?.contextLimitVal) _setVal('compactContextPct', s.compact.contextLimitVal);
      if (s.compact?.contextLimitUnit) _setSelectVal('contextLimitUnit', s.compact.contextLimitUnit);
      _setChecked('compactOnLevel', s.compact?.compactOnLevel ?? true);
      if (schemaId === 'linear_interrupt') {
        _setChecked('interruptPlan', s.interrupt_plan ?? true);
        toggleInterruptSettings();
      }
    } else if (schemaId === 'rlm') {
      _setChecked('sf_rlm_inputGrid', s.input?.full_grid ?? true);
      _setChecked('sf_rlm_inputImage', s.input?.image ?? false);
      _setChecked('sf_rlm_inputDiff', s.input?.diff ?? true);
      _setChecked('sf_rlm_inputHistogram', s.input?.color_histogram ?? false);
      _setRadio('sf_rlm_thinking', s.thinking_level || 'low');
      _setVal('sf_rlm_maxTokens', s.max_tokens || 16384);
      _setRadio('sf_rlm_planMode', s.planning_mode || '10');
      _setRadio('sf_rlm_subThinking', s.sub_thinking_level || 'low');
      _setVal('sf_rlm_subMaxTokens', s.sub_max_tokens || 16384);
      _setVal('sf_rlm_maxDepth', s.max_depth || 3);
      _setVal('sf_rlm_maxIter', s.max_iterations || 10);
      _setVal('sf_rlm_outputTrunc', s.output_truncation || 5000);
    } else if (schemaId === 'three_system') {
      _setChecked('sf_ts_inputGrid', s.input?.full_grid ?? true);
      _setChecked('sf_ts_inputImage', s.input?.image ?? false);
      _setChecked('sf_ts_inputDiff', s.input?.diff ?? true);
      _setChecked('sf_ts_inputHistogram', s.input?.color_histogram ?? false);
      _setRadio('sf_ts_plannerThinking', s.planner_thinking_level || 'low');
      _setVal('sf_ts_plannerMaxTokens', s.planner_max_tokens || 16384);
      _setRadio('sf_ts_planHorizon', String(s.min_plan_length || 5));
      _setRadio('sf_ts_monitorThinking', s.monitor_thinking_level || 'off');
      _setVal('sf_ts_monitorMaxTokens', s.monitor_max_tokens || 4096);
      _setRadio('sf_ts_replanCooldown', String(s.replan_cooldown || 3));
      _setRadio('sf_ts_wmThinking', s.wm_thinking_level || 'low');
      _setVal('sf_ts_wmMaxTokens', s.wm_max_tokens || 16384);
      _setVal('sf_ts_plannerMaxTurns', s.planner_max_turns || 10);
      _setVal('sf_ts_wmMaxTurns', s.wm_max_turns || 5);
      _setVal('sf_ts_wmUpdateEvery', s.wm_update_every || 5);
      _setVal('sf_ts_maxPlanLength', s.max_plan_length || 15);
    } else if (schemaId === 'two_system') {
      _setChecked('sf_2s_inputGrid', s.input?.full_grid ?? true);
      _setChecked('sf_2s_inputImage', s.input?.image ?? false);
      _setChecked('sf_2s_inputDiff', s.input?.diff ?? true);
      _setChecked('sf_2s_inputHistogram', s.input?.color_histogram ?? false);
      _setRadio('sf_2s_plannerThinking', s.planner_thinking_level || 'low');
      _setVal('sf_2s_plannerMaxTokens', s.planner_max_tokens || 16384);
      _setRadio('sf_2s_planHorizon', String(s.min_plan_length || 5));
      _setRadio('sf_2s_monitorThinking', s.monitor_thinking_level || 'off');
      _setVal('sf_2s_monitorMaxTokens', s.monitor_max_tokens || 4096);
      _setRadio('sf_2s_replanCooldown', String(s.replan_cooldown || 3));
      _setVal('sf_2s_plannerMaxTurns', s.planner_max_turns || 10);
      _setVal('sf_2s_maxPlanLength', s.max_plan_length || 15);
    }
    updatePipelineOpacity();
  } catch {}
}

// DOM helpers for restoring settings
function _setChecked(id, val) { const el = document.getElementById(id); if (el) el.checked = !!val; }
function _setVal(id, val) { const el = document.getElementById(id); if (el) el.value = val; }
function _setSelectVal(id, val) { const el = document.getElementById(id); if (el) el.value = val; }
function _setRadio(name, val) {
  const el = document.querySelector(`input[name="${name}"][value="${val}"]`);
  if (el) el.checked = true;
}

function migrateOldSettingsToScaffolding() {
  // If we already have saved scaffolding settings, skip migration
  if (localStorage.getItem('arc_scaffolding_linear')) return;

  // Nothing to migrate — old settings were not persisted to localStorage
  // (they were ephemeral DOM state). Just save current defaults.
  // Model selection is restored by loadModels() separately.
}

// Auto-save settings on any change within the settings panel
document.addEventListener('change', (e) => {
  if (e.target.closest('#settingsColumns')) {
    saveScaffoldingToStorage();
  }
});
document.addEventListener('input', (e) => {
  if (e.target.closest('#settingsColumns') && e.target.type === 'number') {
    saveScaffoldingToStorage();
  }
});

function attachSettingsListeners() {
  // compactContextPct ArrowUp/Down
  const compactPctEl = document.getElementById('compactContextPct');
  if (compactPctEl) {
    compactPctEl.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp') { e.preventDefault(); spinContextLimit(1); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); spinContextLimit(-1); }
    });
  }

  // modelSelect change
  const modelSel = document.getElementById('modelSelect');
  if (modelSel) {
    modelSel.addEventListener('change', function() {
      updateModelCaps();
      updateAllByokKeys();
      const model = this.value;
      const isPuter = modelsData.some(m => m.name === model && m.provider === 'puter');
      if (isPuter) loadPuterJS();
    });
  }

  // compactModelSelectTop change
  const compactSel = document.getElementById('compactModelSelectTop');
  if (compactSel) {
    compactSel.addEventListener('change', function() {
      updateAllByokKeys();
    });
  }

  // interruptModelSelect change
  const interruptSel = document.getElementById('interruptModelSelect');
  if (interruptSel) {
    interruptSel.addEventListener('change', function() {
      updateAllByokKeys();
    });
  }

  // RLM / Three-System / Two-System model select changes — update BYOK key prompts
  for (const selId of [
    'sf_rlm_modelSelect', 'sf_rlm_subModelSelect',
    'sf_ts_plannerModelSelect', 'sf_ts_monitorModelSelect', 'sf_ts_wmModelSelect',
    'sf_2s_plannerModelSelect', 'sf_2s_monitorModelSelect',
    'sf_as_orchestratorModelSelect', 'sf_as_subagentModelSelect'
  ]) {
    const el = document.getElementById(selId);
    if (el) el.addEventListener('change', updateAllByokKeys);
  }

  // toolsMode radio — Pyodide download prompt
  document.querySelectorAll('input[name="toolsMode"]').forEach(radio => {
    radio.addEventListener('change', async (e) => {
      if (e.target.value === 'off') return;
      if (_pyodideReady) return;
      const ok = confirm(
        'Tool calls require Pyodide (Python in WebAssembly).\n\n' +
        'This will download ~10 MB on first use (cached after).\n' +
        'Load Pyodide now?'
      );
      if (!ok) {
        document.querySelector('input[name="toolsMode"][value="off"]').checked = true;
        return;
      }
      e.target.closest('.triswitch').style.opacity = '0.5';
      try {
        await ensurePyodide();
      } catch (err) {
        alert('Failed to load Pyodide: ' + err.message);
        document.querySelector('input[name="toolsMode"][value="off"]').checked = true;
      }
      e.target.closest('.triswitch').style.opacity = '1';
    });
  });
}

function renderGroup(g) {
  let h = '';
  if (g.toggleId) {
    // Sub-header with toggle
    h += '<div class="sub-header" style="display:flex;align-items:center;justify-content:space-between;">';
    h += `<span>${g.subHeader}</span>`;
    h += `<label class="toggle" style="margin:0;"><input type="checkbox" id="${g.toggleId}"${g.toggleDefault ? ' checked' : ''} onchange="${g.toggleOnChange}"><span class="slider"></span></label>`;
    h += '</div>';
    const disStyle = g.bodyDisabledDefault ? ' style="opacity:0.4;pointer-events:none;"' : '';
    h += `<div id="${g.bodyId}"${disStyle}>`;
  } else {
    h += `<div class="sub-header">${g.subHeader}</div>`;
  }
  for (const f of g.fields) {
    h += renderField(f);
  }
  if (g.toggleId) h += '</div>';
  return h;
}

function renderField(f) {
  switch (f.type) {
    case 'toggle': return renderToggle(f);
    case 'model-select': return renderModelSelect(f);
    case 'quadswitch': return renderSwitch(f, 'quadswitch');
    case 'triswitch': return renderSwitch(f, 'triswitch');
    case 'multiswitch': return renderSwitch(f, 'triswitch');
    case 'number-spin': return renderNumberSpin(f);
    case 'number-input': return renderNumberInput(f);
    case 'number-spin-unit': return renderNumberSpinUnit(f);
    case 'compact-model-select': return renderCompactModelSelect(f);
    case 'grid-2col': return renderGrid2Col(f);
    case 'grid-2col-body': return renderGrid2ColBody(f);
    default: return '';
  }
}

function renderToggle(f) {
  const rowId = f.rowId ? ` id="${f.rowId}"` : '';
  const label = f.labelHtml || f.label;
  return `<div class="opt-row"${rowId}><span class="opt-label">${label}</span><label class="toggle"><input type="checkbox" id="${f.id}"${f.default ? ' checked' : ''}><span class="slider"></span></label></div>`;
}

function renderModelSelect(f) {
  let h = '<div style="margin-bottom:8px;">';
  h += `<select id="${f.id}"><option value="">Loading...</option></select>`;
  if (f.capsId) h += `<div class="model-caps" id="${f.capsId}"></div>`;
  if (f.testResultId) h += `<div id="${f.testResultId}" style="display:none; margin-top:4px; padding:4px 8px; border-radius:4px; font-size:11px;"></div>`;
  h += '</div>';
  return h;
}

function renderSwitch(f, cls) {
  let h = '<div>';
  h += `<div class="opt-label" style="margin-bottom:4px;">${f.label}</div>`;
  h += `<div class="${cls}" id="${f.id}">`;
  for (const o of f.options) {
    h += `<label><input type="radio" name="${f.name}" value="${o.v}"${o.checked ? ' checked' : ''}><span>${o.l}</span></label>`;
  }
  h += '</div>';
  if (f.hint) h += `<div style="font-size:10px;color:var(--text-dim);margin-top:4px;">${f.hint}</div>`;
  h += '</div>';
  return h;
}

function renderNumberSpin(f) {
  if (f.inline) {
    // Inline variant without opt-row wrapper (used inside grid-2col)
    let h = '<div>';
    h += `<div class="opt-label" style="margin-bottom:4px;">${f.label}</div>`;
    h += '<span class="spin-wrap">';
    h += `<input type="number" id="${f.id}" value="${f.default}" min="${f.min}" max="${f.max}" step="${f.step}" style="width:68px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px 0 0 4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
    h += '<span class="spin-btns">';
    if (f.spinFn) {
      h += `<button class="spin-btn" onclick="${f.spinFn}(1)">&#9650;</button>`;
      h += `<button class="spin-btn" onclick="${f.spinFn}(-1)">&#9660;</button>`;
    } else {
      h += `<button class="spin-btn" onclick="document.getElementById('${f.id}').value=Math.min(${f.max},(parseInt(document.getElementById('${f.id}').value)||${f.default})+${f.step})">&#9650;</button>`;
      h += `<button class="spin-btn" onclick="document.getElementById('${f.id}').value=Math.max(${f.min},(parseInt(document.getElementById('${f.id}').value)||${f.default})-${f.step})">&#9660;</button>`;
    }
    h += '</span></span></div>';
    return h;
  }
  let h = '<div class="opt-row" style="margin-top:8px;">';
  h += `<span class="opt-label">${f.label}</span>`;
  h += '<span class="spin-wrap">';
  h += `<input type="number" id="${f.id}" value="${f.default}" min="${f.min}" max="${f.max}" step="${f.step}" style="width:68px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px 0 0 4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
  h += '<span class="spin-btns">';
  h += `<button class="spin-btn" onclick="${f.spinFn}(1)">&#9650;</button>`;
  h += `<button class="spin-btn" onclick="${f.spinFn}(-1)">&#9660;</button>`;
  h += '</span></span></div>';
  return h;
}

function renderNumberInput(f) {
  let h = `<div class="opt-row"><span class="opt-label">${f.label}</span>`;
  h += `<input type="number" id="${f.id}"`;
  if (f.default !== undefined) h += ` value="${f.default}"`;
  if (f.placeholder) h += ` placeholder="${f.placeholder}"`;
  h += ` min="${f.min}" max="${f.max}"`;
  h += ` style="width:${f.width || '55px'};background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
  h += '</div>';
  return h;
}

function renderNumberSpinUnit(f) {
  let h = `<div class="opt-row"><span class="opt-label">${f.label}</span>`;
  h += '<span class="spin-wrap">';
  h += `<input type="number" id="${f.id}" value="${f.default}" min="${f.min}" step="${f.step}" style="width:${f.width || '68px'};background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px 0 0 4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
  h += '<span class="spin-btns">';
  h += `<button class="spin-btn" onclick="${f.spinFn}(1)">&#9650;</button>`;
  h += `<button class="spin-btn" onclick="${f.spinFn}(-1)">&#9660;</button>`;
  h += '</span></span>';
  h += `<select id="${f.unitId}" style="width:62px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px 4px;font-family:inherit;font-size:11px;margin-left:4px;" onchange="${f.unitChangeFn}">`;
  for (const u of f.units) {
    h += `<option value="${u.v}"${u.selected ? ' selected' : ''}>${u.l}</option>`;
  }
  h += '</select></div>';
  return h;
}

function renderCompactModelSelect(f) {
  let h = '<div style="margin-bottom:8px;">';
  h += `<select id="${f.id}" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-family:inherit;font-size:12px;">`;
  h += '<option value="auto">Auto (cheapest of same provider)</option>';
  h += '<option value="auto-fastest">Auto (fastest of same provider)</option>';
  h += '<option value="same">Same as reasoning</option>';
  h += '</select>';
  if (f.hint) h += `<div style="font-size:9px;color:var(--dim);margin-top:3px;">${f.hint}</div>`;
  h += '</div>';
  return h;
}

function renderGrid2Col(f) {
  let h = `<div class="settings-grid"${f.marginBottom ? ` style="margin-bottom:${f.marginBottom};"` : ''}>`;
  for (const child of f.children) {
    h += renderField(child);
  }
  h += '</div>';
  return h;
}

function renderGrid2ColBody(f) {
  let h = '<div class="settings-grid">';
  for (const child of f.children) {
    h += renderField(child);
  }
  h += '</div>';
  return h;
}

// Compact context: accumulate LLM observations across the session
let llmObservations = []; // [{step, observation, reasoning, action, analysis}]

// ═══════════════════════════════════════════════════════════════════════════
// MULTI-SESSION: SessionState class + registry
// ═══════════════════════════════════════════════════════════════════════════

class SessionState {
  constructor(id) {
    this.sessionId = id;
    // Game state
    this.currentGrid = null;
    this.previousGrid = null;
    this.currentChangeMap = null;
    this.currentState = {};
    // Counters
    this.stepCount = 0;
    this.llmCallCount = 0;
    this.turnCounter = 0;
    // History
    this.moveHistory = [];
    this.undoStack = [];
    this.llmObservations = [];
    // Agent
    this.autoPlaying = false;
    this.action6Mode = false;
    // Compact context
    this._cachedCompactSummary = '';
    this._compactSummaryAtCall = 0;
    this._compactSummaryAtStep = 0;
    this._lastCompactPrompt = '';
    // Cost
    this.sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    // Persistence
    this.sessionStepsBuffer = [];
    this.sessionStartTime = null;
    this.syncStepCounter = 0;
    // UI
    this.gameId = '';
    this.model = '';
    this.status = 'NOT_PLAYED';
    this.createdAt = Date.now() / 1000;
    // Countdown
    this.callDurations = [];
    this.countdownInterval = null;
    this.countdownTarget = null;
    // Tab label: once set by autoplay, never overwritten
    this.tabLabel = '';
    // LLM call in flight
    this.waitingForLLM = false;
    this.abortController = null;   // AbortController for in-flight fetch
    this.waitStartTime = null;     // performance.now() when LLM call started
    // Timeline
    this.timelineEvents = [];  // [{type, duration, turn, model?, callNum?}]
    this._rlmNamespace = {};  // Persistent RLM REPL variables (survives across turns within session)
    this._tsState = null;     // Three-System state (rules, observations, snapshots) — initialized on first use
    // Observability
    this._obsEvents = [];     // Obs screen events [{event, agent, t, elapsed_s, ...}]
    this._obsStartTime = null;
    this._obsSyncCursor = 0;
    // Detach/attach: per-session DOM + settings snapshot
    this._viewEl = null;       // Detached DOM element for this session
    this._settings = null;     // Snapshot of DOM settings for background reads
    // Original settings from when this session was created/resumed (for branch-on-change detection)
    this._originalSettings = null;  // { model, scaffolding_type }
    // Upload tracking
    this._lastUploadedStep = 0;  // last step successfully uploaded to server
  }
  get avgCallDuration() {
    if (!this.callDurations.length) return 5000; // default 5s
    return this.callDurations.reduce((a, b) => a + b, 0) / this.callDurations.length;
  }
}

const sessions = new Map();  // sessionId -> SessionState
let activeSessionId = null;
function getActiveSession() { return sessions.get(activeSessionId) || null; }

// ── Sync SessionState back to globals (only if ss is the active session) ──
function syncSessionToGlobals(ss) {
  if (!ss || activeSessionId !== ss.sessionId) return;
  sessionId = ss.sessionId;
  currentGrid = ss.currentGrid;
  previousGrid = ss.previousGrid;
  currentChangeMap = ss.currentChangeMap;
  currentState = ss.currentState;
  stepCount = ss.stepCount;
  llmCallCount = ss.llmCallCount;
  turnCounter = ss.turnCounter;
  moveHistory = ss.moveHistory;
  undoStack = ss.undoStack;
  llmObservations = ss.llmObservations;
  autoPlaying = ss.autoPlaying;
  sessionTotalTokens = ss.sessionTotalTokens;
  sessionStepsBuffer = ss.sessionStepsBuffer;
  syncStepCounter = ss.syncStepCounter;
  _cachedCompactSummary = ss._cachedCompactSummary;
  _compactSummaryAtCall = ss._compactSummaryAtCall;
  _compactSummaryAtStep = ss._compactSummaryAtStep;
  _lastCompactPrompt = ss._lastCompactPrompt;
}

// ── Bridge: save globals → SessionState ──────────────────────────────────
function saveSessionToState() {
  const s = getActiveSession();
  if (!s) return;
  s.sessionId = sessionId;
  s.currentGrid = currentGrid;
  s.previousGrid = previousGrid;
  s.currentChangeMap = currentChangeMap;
  s.currentState = currentState;
  s.stepCount = stepCount;
  s.llmCallCount = llmCallCount;
  s.turnCounter = turnCounter;
  s.moveHistory = moveHistory;
  s.undoStack = undoStack;
  s.llmObservations = llmObservations;
  s.autoPlaying = autoPlaying;
  s.action6Mode = action6Mode;
  s.sessionTotalTokens = sessionTotalTokens;
  s.sessionStepsBuffer = sessionStepsBuffer;
  s.sessionStartTime = sessionStartTime;
  s.syncStepCounter = syncStepCounter;
  s._cachedCompactSummary = _cachedCompactSummary;
  s._compactSummaryAtCall = _compactSummaryAtCall;
  s._compactSummaryAtStep = _compactSummaryAtStep;
  s._lastCompactPrompt = _lastCompactPrompt;
  // Snapshot DOM settings so background sessions can read them when detached
  try {
    s._settings = {
      model: getSelectedModel(),
      input: getInputSettings(),
      compact: getCompactSettings(),
      tools_mode: getToolsMode(),
      planning_mode: getPlanningMode(),
      thinking_level: getThinkingLevel(),
      scaffolding: getScaffoldingSettings(),
      max_tokens: getMaxTokens(),
      scaffolding_type: activeScaffoldingType,
    };
  } catch (e) { console.warn('[saveSessionToState] settings snapshot failed:', e); }
  // Update metadata
  s.gameId = gameShortName(currentState.game_id) || s.gameId;
  s.model = getSelectedModel() || s.model;
  s.status = currentState.state || s.status;
}

// ── Bridge: restore SessionState → globals ───────────────────────────────
function restoreSessionFromState(s) {
  if (!s) return;
  sessionId = s.sessionId;
  currentGrid = s.currentGrid;
  previousGrid = s.previousGrid;
  currentChangeMap = s.currentChangeMap;
  currentState = s.currentState;
  stepCount = s.stepCount;
  llmCallCount = s.llmCallCount;
  turnCounter = s.turnCounter;
  moveHistory = s.moveHistory;
  undoStack = s.undoStack;
  llmObservations = s.llmObservations;
  autoPlaying = s.autoPlaying;
  action6Mode = s.action6Mode;
  sessionTotalTokens = s.sessionTotalTokens;
  sessionStepsBuffer = s.sessionStepsBuffer;
  sessionStartTime = s.sessionStartTime;
  syncStepCounter = s.syncStepCounter;
  _cachedCompactSummary = s._cachedCompactSummary;
  _compactSummaryAtCall = s._compactSummaryAtCall;
  _compactSummaryAtStep = s._compactSummaryAtStep;
  _lastCompactPrompt = s._lastCompactPrompt;

  // Rebuild reasoning from step buffer (single source of truth — never cache DOM HTML)
  const rc = document.getElementById('reasoningContent');
  if (rc) {
    if (s.sessionStepsBuffer && s.sessionStepsBuffer.length > 0) {
      renderRestoredReasoning(s.sessionStepsBuffer, null, null);
    } else {
      rc.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No reasoning yet.</div>';
    }
  }

  // If session has an LLM call in flight, show waiting indicator with elapsed time
  if (s.waitingForLLM && s.waitStartTime) {
    const elapsed = ((performance.now() - s.waitStartTime) / 1000).toFixed(1);
    const waitEl = document.createElement('div');
    waitEl.className = 'reasoning-entry llm-waiting';
    waitEl.innerHTML = `<div class="step-label" style="color:var(--dim);"><span class="spinner" style="margin-right:6px;"></span>Waiting for model response... <span class="wait-timer">${elapsed}s</span></div>`;
    if (rc.querySelector('.empty-state')) rc.innerHTML = '';
    rc.appendChild(waitEl);
    scrollReasoningToBottom();
    // Live-update the timer until the LLM call completes
    const _restoreWaitStart = s.waitStartTime;
    const _restoreWaitInterval = setInterval(() => {
      if (!s.waitingForLLM || !waitEl.parentNode) { clearInterval(_restoreWaitInterval); waitEl.remove(); return; }
      const el = waitEl.querySelector('.wait-timer');
      if (el) el.textContent = ((performance.now() - _restoreWaitStart) / 1000).toFixed(1) + 's';
    }, 100);
    document.getElementById('llmSpinner').style.display = 'inline';
    document.getElementById('topSpinner').style.display = 'inline';
  } else {
    document.getElementById('llmSpinner').style.display = 'none';
    document.getElementById('topSpinner').style.display = 'none';
  }

  // Re-render grid
  if (currentGrid) {
    canvas.style.display = 'block';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    renderGrid(currentGrid);
  } else {
    canvas.style.display = 'none';
    document.getElementById('emptyState').style.display = '';
    document.getElementById('controls').style.display = 'none';
    document.getElementById('transportBar').style.display = 'none';
  }

  // Update UI elements
  document.getElementById('gameTitle').textContent = gameShortName(currentState.game_id) || 'No game selected';
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = currentState.state || '—';
  statusEl.className = 'status status-' + (currentState.state || 'NOT_PLAYED');
  document.getElementById('levelInfo').textContent = currentState.levels_completed !== undefined
    ? `Level ${currentState.levels_completed}/${currentState.win_levels || '?'}` : '';
  document.getElementById('stepCounter').textContent = stepCount ? `Step ${stepCount}` : '';
  updateUploadBadge();
  updateUndoBtn();
  updateAutoBtn();
  updatePanelBlur();
  updateGameListLock();

  // Re-render obs swimlane if obs mode is active
  if (isObsModeActive()) {
    updateObsStatus(s);
  }

  // Highlight the matching game card in the sidebar
  const restoredGameId = currentState.game_id || '';
  document.querySelectorAll('.game-card').forEach(c => {
    c.classList.toggle('active', restoredGameId && c.dataset.gameId === restoredGameId);
  });

  if (action6Mode) canvas.style.cursor = 'crosshair';
  else canvas.style.cursor = 'default';
}

// ── Register a SessionState in the registry ──────────────────────────────
function registerSession(id, state) {
  sessions.set(id, state);
  activeSessionId = id;
  renderSessionTabs();
  saveSessionIndex();
}

// ═══════════════════════════════════════════════════════════════════════════
// DETACH / ATTACH ENGINE — per-session DOM isolation
// ═══════════════════════════════════════════════════════════════════════════

let _sessionTemplate = null;  // Captured after initApp populates DOM

function captureSessionTemplate() {
  const ml = document.getElementById('mainLayout');
  if (!ml) return;
  _sessionTemplate = ml.cloneNode(true);
  _sessionTemplate.removeAttribute('id');
  // Ensure cloned template has loading overlay hidden (Pyodide may be loading when captured)
  const overlay = _sessionTemplate.querySelector('#pyodideGameLoading');
  if (overlay) overlay.style.display = 'none';
}

function createSessionView() {
  const view = _sessionTemplate.cloneNode(true);
  view.id = 'mainLayout';
  return view;
}

function detachSessionView(sid) {
  const host = document.getElementById('sessionViewHost');
  const currentView = host.querySelector('#mainLayout');
  if (currentView && sessions.has(sid)) {
    sessions.get(sid)._viewEl = currentView;
    host.removeChild(currentView);
  }
}

function attachSessionView(sid) {
  const host = document.getElementById('sessionViewHost');
  const ss = sessions.get(sid);
  if (!ss) return;
  // Remove any existing #mainLayout (static or stale) before attaching
  const existing = host.querySelector('#mainLayout');
  if (existing) existing.remove();
  if (!ss._viewEl) ss._viewEl = createSessionView();
  ss._viewEl.id = 'mainLayout';
  host.appendChild(ss._viewEl);
  // Re-bind dynamic event listeners (cloned DOM loses addEventListener bindings)
  attachSettingsListeners();
  // Refresh canvas reference (each session has its own canvas element)
  canvas = document.getElementById('gameCanvas');
  ctx = canvas.getContext('2d');
}

