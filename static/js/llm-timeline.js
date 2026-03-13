// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: Timeline rendering and event management (Phase 12 extraction)
// Extracted from llm.js to isolate SVG/timeline complexity
// SRP: Timeline event reconstruction, rendering, detail management

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

// ── Timeline rendering helpers ────────────────────────────────────────────────────
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
// Colors and labels auto-assigned via reasoning.js agentColor()/agentLabel()

let _asZoom = 1.0, _asPanX = 0, _asPanY = 0;
let _asDragging = false, _asDragStart = { x: 0, y: 0, panX: 0, panY: 0 };

function _updateAsTransform(svg, container) {
  const w = container.clientWidth / _asZoom;
  const h = container.clientHeight / _asZoom;
  svg.setAttribute('viewBox', `${_asPanX} ${_asPanY} ${w} ${h}`);
}

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
      const timeStr = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
      const clickAttr = hasDetail ? `onclick="_tlToggleDetail(${evIdx})" class="timeline-block ${cssClass} clickable"` : `class="timeline-block ${cssClass}"`;
      html += `<div ${clickAttr} style="height:${h}px">
        <span class="tl-label">${timeStr ? `<span class="tl-time">${timeStr}</span> ` : ''}${_tlEsc(label)}${stepsHtml}${costHtml}${arrowHtml}</span><span class="tl-dur">${dur}</span>
      </div>`;
      if (hasDetail) {
        html += _tlBuildDetail(ev, evIdx);
      }
      evIdx++;
    }
  }
  container.innerHTML = html;
}

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
