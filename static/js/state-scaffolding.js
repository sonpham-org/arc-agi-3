// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: Scaffolding configuration state and settings panel rendering.
//   Extracted from state.js to focus on: scaffolding type selection,
//   settings persistence (localStorage), form field rendering, pipeline
//   visualizer, and DOM listeners for settings changes.
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING STATE
// ═══════════════════════════════════════════════════════════════════════════

let activeScaffoldingType = 'linear';  // Current scaffolding schema

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
