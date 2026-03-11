// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Standalone Observatory page logic for ARC-AGI-3 (obs.html). Renders
//   session detail views with swimlane timelines, step-by-step log, grid replay,
//   and performance metrics. Uses obs-log-renderer.js, obs-scrubber.js, and
//   obs-swimlane-renderer.js for shared rendering. Depends on reasoning.js for
//   agent color palette. Modified in Phases 1 & 4 to extract formatting utils
//   and shared observatory rendering into separate modules.
// SRP/DRY check: Pass — shared rendering extracted to observatory/ modules in Phase 4
// Agent colors now provided by reasoning.js agentColor()
// (obs-page.html must load reasoning.js before this file)
const DEFAULT_COLOR = '#6b7280';

// ── Readable action names ──
const ACTION_DISPLAY = {
  'ACTION1': 'UP', 'ACTION2': 'DOWN', 'ACTION3': 'LEFT', 'ACTION4': 'RIGHT',
  'ACTION5': 'ACT5', 'ACTION6': 'CLICK', 'ACTION7': 'ACT7', 'RESET': 'RESET',
};

function humanAction(raw) {
  if (!raw) return raw;
  // Replace ACTION1@(x,y) -> UP@(x,y), ACTION2 -> DOWN, etc.
  return raw.replace(/ACTION[0-7]|RESET/g, m => ACTION_DISPLAY[m] || m);
}

// agentColor() and agentBadge() now provided by reasoning.js

// ── Cost estimation ($ per 1M tokens) ──
const MODEL_PRICING = {
  // Gemini
  'gemini-3-flash':    { input: 0.10, output: 0.40 },
  'gemini-3-pro':      { input: 1.25, output: 10.00 },
  'gemini-3.1-pro':    { input: 1.25, output: 10.00 },
  'gemini-2.5-flash':  { input: 0.15, output: 0.60 },
  'gemini-2.5-pro':    { input: 1.25, output: 10.00 },
  // Anthropic
  'claude-sonnet-4-5': { input: 3.00, output: 15.00 },
  'claude-haiku-4-5':  { input: 0.80, output: 4.00 },
  // Free tier
  'groq':     { input: 0, output: 0 },
  'mistral':  { input: 0, output: 0 },
  'ollama':   { input: 0, output: 0 },
  '_default': { input: 0.50, output: 1.50 },  // fallback estimate
};

// Track per-model tokens from events
let plannerTokens = { input: 0, output: 0 };
let executorTokens = { input: 0, output: 0 };

function lookupPricing(model) {
  if (!model) return MODEL_PRICING['_default'];
  for (const [key, p] of Object.entries(MODEL_PRICING)) {
    if (key !== '_default' && model.includes(key)) return p;
  }
  return MODEL_PRICING['_default'];
}

function estimateCost() {
  const pp = lookupPricing(statusData?.planner_model);
  const ep = lookupPricing(statusData?.executor_model);
  let total = 0;
  total += (plannerTokens.input / 1_000_000) * pp.input;
  total += (plannerTokens.output / 1_000_000) * pp.output;
  total += (executorTokens.input / 1_000_000) * ep.input;
  total += (executorTokens.output / 1_000_000) * ep.output;
  return total;
}

// Normalize event — use agent_type directly, no scaffolding-specific mapping
function normalizeEvent(ev) {
  // Ensure agent_type is set
  if (!ev.agent_type && ev.agent) ev.agent_type = ev.agent;
  if (!ev.agent && ev.agent_type) ev.agent = ev.agent_type;
  // Alias step_num → step so findNearestGrid/selectLogRow work
  if (ev.step_num != null && ev.step == null) ev.step = ev.step_num;
  return ev;
}

function trackEventTokens(ev) {
  const inTok = ev.input_tokens || 0;
  const outTok = ev.output_tokens || 0;
  if (!inTok && !outTok) return;
  if (ev.event === 'orchestrator_decide') {
    plannerTokens.input += inTok;
    plannerTokens.output += outTok;
  } else {
    executorTokens.input += inTok;
    executorTokens.output += outTok;
  }
}

// ── State ──
let allEvents = [];
let nextOffset = 0;
let autoScroll = true;
let statusData = null;
let pollTimer = null;
let failCount = 0;
let timelineZoom = 1.0;  // multiplier on pxPerSec
let timelineAutoScroll = true;  // stop auto-scrolling once user zooms
let currentSessionId = null;  // detect new runs
let timelineMode = 'swimlane';  // 'swimlane' (adaptive) or 'custom' (orch bar + blocks)
let selectedEventIdx = -1;  // index into allEvents for historical grid view
let frozenGrid = null;  // when viewing historical grid, pause live updates
let currentGrid = null;  // latest parsed grid for highlight lookups

function resetState() {
  allEvents = [];
  nextOffset = 0;
  plannerTokens = { input: 0, output: 0 };
  executorTokens = { input: 0, output: 0 };
  timelineZoom = 1.0;
  timelineAutoScroll = true;
  selectedEventIdx = -1;
  frozenGrid = null;
  document.getElementById('logBody').innerHTML = '';
  document.getElementById('timelineCanvas').innerHTML = '';
  document.getElementById('zoomLabel').textContent = '1.0x';
  document.getElementById('gridModeLabel').classList.remove('active');
}

// ── Polling ──
async function fetchStatus() {
  try {
    const r = await fetch('/api/obs/status');
    if (r.ok) {
      statusData = await r.json();
      // Detect new run — reset everything
      if (statusData.session_id && statusData.session_id !== currentSessionId) {
        currentSessionId = statusData.session_id;
        resetState();
      }
      renderStatus(statusData);
      failCount = 0;
      setConn(true);
    } else {
      failCount++;
      if (failCount > 3) setConn(false);
    }
  } catch { failCount++; if (failCount > 3) setConn(false); }
}

async function fetchEvents() {
  try {
    const r = await fetch(`/api/obs/events?since=${nextOffset}`);
    if (!r.ok) return;
    const data = await r.json();
    // Server may reset offset if file was cleared (new run)
    if (data.next_offset < nextOffset) {
      resetState();
    }
    nextOffset = data.next_offset;
    if (data.events && data.events.length > 0) {
      data.events.forEach(normalizeEvent);
      allEvents.push(...data.events);
      renderNewEvents(data.events);
      renderTimeline();
      obsScrubUpdate();
      // If any event is an action, fetch grid immediately for sync
      if (data.events.some(ev => ev.event === 'act')) {
        fetchGrid();
      }
    }
  } catch {}
}

async function poll() {
  await Promise.all([fetchStatus(), fetchEvents(), fetchGrid()]);
  pollTimer = setTimeout(poll, 500);
}

function setConn(live) {
  const el = document.getElementById('connStatus');
  if (live) {
    el.textContent = 'LIVE';
    el.className = 'conn live';
  } else {
    el.textContent = 'DISCONNECTED';
    el.className = 'conn dead';
  }
}

// ── Status rendering ──
function renderStatus(s) {
  document.getElementById('sGame').textContent = s.game || '--';

  const stateEl = document.getElementById('sState');
  stateEl.textContent = s.state || '--';
  stateEl.className = 'value state-' + (s.state || '');

  document.getElementById('sStep').textContent = s.step != null ? `${s.step} / ${s.max_steps}` : '--';
  document.getElementById('sLevel').textContent = s.level || '--';
  document.getElementById('sTurn').textContent = s.turn != null ? s.turn.toLocaleString() : '--';
  document.getElementById('sCalls').textContent = s.total_llm_calls != null ? s.total_llm_calls.toLocaleString() : '--';

  const tokIn = s.total_input_tokens || 0;
  const tokOut = s.total_output_tokens || 0;
  document.getElementById('sTokens').textContent = `${fmtK(tokIn)} / ${fmtK(tokOut)}`;

  // Cost estimate
  const cost = estimateCost();
  const costEl = document.getElementById('sCost');
  if (cost < 0.01) {
    costEl.textContent = cost > 0 ? '<$0.01' : '$0.00';
  } else {
    costEl.textContent = '$' + cost.toFixed(2);
  }
  costEl.style.color = cost > 1 ? '#ef4444' : cost > 0.10 ? '#f59e0b' : '#22c55e';

  const elapsed = s.elapsed_min != null ? s.elapsed_min : 0;
  if (elapsed < 1) {
    document.getElementById('sElapsed').textContent = `${Math.round(elapsed * 60)}s`;
  } else if (elapsed < 60) {
    document.getElementById('sElapsed').textContent = `${elapsed.toFixed(1)}m`;
  } else {
    document.getElementById('sElapsed').textContent = `${(elapsed / 60).toFixed(1)}h`;
  }

  document.getElementById('sAgent').innerHTML = agentBadge(s.current_agent);

  const taskEl = document.getElementById('sTask');
  taskEl.textContent = s.current_task || '--';
  taskEl.title = s.current_task || '';
}

function fmtK(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toString();
}

// ── Call log ──
function renderNewEvents(events) {
  const tbody = document.getElementById('logBody');
  const startIdx = allEvents.length - events.length;  // index of first new event in allEvents
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    const evIdx = startIdx + i;
    trackEventTokens(ev);
    const tr = document.createElement('tr');
    tr.setAttribute('data-ev-idx', evIdx);
    const agent = ev.agent || ev.agent_type || ev.current_agent || '';
    const c = agentColor(agent);
    tr.style.borderLeft = `3px solid ${c}`;

    const time = ev.t ? ev.t.split('T')[1] || ev.t : '';
    const elapsed = ev.elapsed_s != null ? `+${ev.elapsed_s.toFixed(0)}` : '';
    const tokIn = ev.input_tokens || '';
    const tokOut = ev.output_tokens || '';
    const dur = ev.duration_ms ? `${ev.duration_ms}ms` : '';

    let details = buildDetails(ev);
    const hasGrid = ev.grid && ev.grid.length > 0;
    // Build expandable detail block
    const expandHtml = buildExpandDetail(ev);

    tr.innerHTML = `
      <td>${time}</td>
      <td class="dur">${elapsed}</td>
      <td>${agentBadge(agent)}</td>
      <td>${ev.event || ''}</td>
      <td class="details" title="Click to expand">${escapeHtmlAttr(details)}${expandHtml}</td>
      <td class="tok">${tokIn ? fmtK(tokIn) + '/' + fmtK(tokOut) : ''}</td>
      <td class="dur">${dur}</td>
    `;
    // Click-to-expand on details cell
    const detailsCell = tr.querySelector('.details');
    detailsCell.addEventListener('click', (e) => {
      e.stopPropagation();
      detailsCell.classList.toggle('expanded');
    });
    // Click row to show historical grid state (any row — finds nearest grid)
    tr.addEventListener('click', () => selectLogRow(tr, evIdx));
    // Annotate coordinate references for grid highlighting
    annotateCoordRefs(detailsCell);
    tbody.appendChild(tr);
  }

  if (autoScroll) {
    const wrap = document.getElementById('logWrap');
    wrap.scrollTop = wrap.scrollHeight;
  }
}

function _extractReasoning(ev) {
  // Extract reasoning from the raw LLM response JSON
  if (!ev.response) return '';
  try {
    // Try to parse JSON from the response
    const match = ev.response.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed = JSON.parse(match[0]);
      // Collect reasoning fields
      const parts = [];
      if (parsed.reasoning) parts.push(parsed.reasoning);
      if (parsed.next) parts.push(`Next: ${parsed.next}`);
      if (parsed.facts?.length) parts.push(`Facts: ${parsed.facts.join('; ')}`);
      if (parsed.hypotheses?.length) parts.push(`Hypotheses: ${parsed.hypotheses.join('; ')}`);
      if (parts.length) return parts.join(' | ');
    }
    // If no JSON, show the raw text (might be thinking/reasoning before JSON)
    const beforeJson = ev.response.split('{')[0].trim();
    if (beforeJson.length > 10) return beforeJson;
  } catch {}
  return '';
}

function buildDetails(ev) {
  switch (ev.event) {
    case 'orchestrator_decide': {
      const header = `${ev.command || ''}${ev.agent_type ? ' -> ' + ev.agent_type : ''}${ev.task ? ': ' + ev.task : ''}`;
      const reasoning = _extractReasoning(ev);
      return reasoning ? `${header}\n${reasoning}` : header;
    }
    case 'subagent_start': {
      let detail = `task: ${ev.task || ''} (budget: ${ev.budget || '?'})`;
      if (ev.level) detail += ` | level: ${ev.level}`;
      if (ev.available_actions) detail += `\nactions: ${ev.available_actions}`;
      if (ev.memory_summary) detail += `\nmemory: ${ev.memory_summary}`;
      return detail;
    }
    case 'act': {
      const header = `${humanAction(ev.action) || ''}${ev.state ? ' [' + ev.state + ']' : ''}${ev.reasoning ? ' - ' + ev.reasoning : ''}`;
      const reasoning = _extractReasoning(ev);
      return reasoning ? `${header}\n${reasoning}` : header;
    }
    case 'llm_call': {
      // Show LLM output (response), not input (prompt)
      const model = ev.model ? ev.model.replace(/^(gemini|claude|groq|mistral|ollama)\//, '') : '';
      const step = ev.step != null ? `step ${ev.step}` : '';
      const header = [model, step].filter(Boolean).join(' | ');
      const resp = ev.response || '';
      return resp ? `${header}\n${resp}` : header;
    }
    case 'subagent_report':
    case 'sub_report':
      return `steps: ${ev.steps_used || 0}, findings: ${ev.findings || 0}${ev.summary ? '\n' + ev.summary : ''}`;
    case 'frame_tool':
    case 'sub_tool':
      return `tool: ${ev.tool || ev.tool_name || ''}`;
    case 'game_start':
      return ev.model || '';
    case 'game_end':
      return ev.result || '';
    default:
      // Show any extra keys, skip empty values
      const skip = new Set(['t','elapsed_s','event','agent','agent_type','grid','current_agent']);
      const extra = Object.entries(ev).filter(([k, v]) => !skip.has(k) && v !== '' && v != null && v !== 0);
      return extra.map(([k,v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
  }
}

function buildExpandDetail(ev) {
  const parts = [];
  const skipKeys = new Set(['t','elapsed_s','event','agent','agent_type','grid',
    'input_tokens','output_tokens','duration_ms','current_agent',
    'response','prompt_preview']);

  // Full response gets priority display
  if (ev.response && ev.response.length > 0) {
    parts.push(`<span class="resp-label">LLM Response (${ev.response.length.toLocaleString()} chars)</span>${escapeHtmlAttr(ev.response)}`);
  }

  // Show all other fields as structured key-value pairs (prompt_preview last)
  const fields = Object.entries(ev).filter(([k]) => !skipKeys.has(k));
  if (fields.length > 0) {
    const fieldLines = fields.map(([k, v]) => {
      const val = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
      return `<span style="color:#666">${k}:</span> ${escapeHtmlAttr(val)}`;
    }).join('\n');
    if (parts.length > 0) {
      parts.push(`\n<span class="resp-label" style="margin-top:8px">Event Fields</span>${fieldLines}`);
    } else {
      parts.push(fieldLines);
    }
  }

  // Prompt preview at the bottom, collapsed
  if (ev.prompt_preview && ev.prompt_preview.length > 0) {
    parts.push(`\n<span class="resp-label" style="margin-top:8px;color:#555">Prompt Preview (${ev.prompt_preview.length.toLocaleString()} chars)</span><span style="color:#555">${escapeHtmlAttr(ev.prompt_preview)}</span>`);
  }

  if (parts.length === 0) return '';
  return `<div class="response-detail">${parts.join('\n')}</div>`;
}


function toggleAutoScroll() {
  autoScroll = !autoScroll;
  const btn = document.getElementById('autoScrollBtn');
  btn.classList.toggle('active', autoScroll);
}

function copyObsLogs() {
  if (!allEvents.length) {
    navigator.clipboard.writeText('(no events)');
    return;
  }
  const lines = [];
  lines.push(`=== Observatory Log (${allEvents.length} events) ===`);
  if (currentSessionId) lines.push(`Session: ${currentSessionId}`);
  lines.push('');
  lines.push('Time'.padEnd(12) + '+s'.padEnd(8) + 'Agent'.padEnd(14) + 'Event'.padEnd(22) + 'Details');
  lines.push('-'.repeat(80));
  for (const ev of allEvents) {
    const time = ev.t ? (ev.t.split('T')[1] || ev.t) : '';
    const elapsed = ev.elapsed_s != null ? `+${ev.elapsed_s.toFixed(0)}` : '';
    const agent = ev.agent || ev.agent_type || ev.current_agent || '';
    const details = buildDetails(ev);
    const tok = (ev.input_tokens || ev.output_tokens) ? ` [${fmtK(ev.input_tokens||0)}/${fmtK(ev.output_tokens||0)}]` : '';
    const dur = ev.duration_ms ? ` ${ev.duration_ms}ms` : '';
    lines.push(time.padEnd(12) + elapsed.padEnd(8) + agent.padEnd(14) + (ev.event||'').padEnd(22) + details + tok + dur);
    // Include full response if present
    if (ev.response) {
      lines.push('  [response] ' + ev.response.substring(0, 2000));
    }
  }
  navigator.clipboard.writeText(lines.join('\n'));
  event.target.textContent = 'Copied!';
  setTimeout(() => { event.target.textContent = 'Copy logs'; }, 1500);
}

// ── Find nearest grid at or before a given event index ──
function findNearestGrid(evIdx) {
  // Walk backwards from evIdx to find the most recent event with a grid
  for (let i = evIdx; i >= 0; i--) {
    if (allEvents[i] && allEvents[i].grid && allEvents[i].grid.length > 0) {
      return { grid: allEvents[i].grid, sourceIdx: i, step: allEvents[i].step };
    }
  }
  return null;
}

// ── Select log row to show historical grid ──
function selectLogRow(tr, evIdx) {
  const tbody = document.getElementById('logBody');
  const modeLabel = document.getElementById('gridModeLabel');
  const infoEl = document.getElementById('gridInfo');

  // Toggle off if clicking the same row
  if (selectedEventIdx === evIdx) {
    selectedEventIdx = -1;
    frozenGrid = null;
    tr.classList.remove('selected');
    modeLabel.classList.remove('active');
    // Restore live grid
    if (currentGrid) renderGameGrid(currentGrid);
    infoEl.textContent = `Step ${statusData?.step ?? '--'} | LIVE`;
    obsScrubUpdate();
    return;
  }

  // Deselect previous
  tbody.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));

  selectedEventIdx = evIdx;
  tr.classList.add('selected');

  const ev = allEvents[evIdx];
  // Use this event's grid, or find the nearest prior grid
  const gridSource = (ev && ev.grid && ev.grid.length > 0)
    ? { grid: ev.grid, sourceIdx: evIdx, step: ev.step }
    : findNearestGrid(evIdx);

  if (gridSource) {
    frozenGrid = gridSource.grid;
    currentGrid = gridSource.grid;
    renderGameGrid(gridSource.grid);
    const step = ev.step ?? gridSource.step ?? '?';
    const agent = ev.agent || ev.agent_type || '';
    const label = humanAction(ev.action) || ev.event || '';
    // Note if grid is from a prior event
    const suffix = (gridSource.sourceIdx !== evIdx) ? ' (nearest state)' : '';
    infoEl.textContent = `Step ${step} | ${label}${agent ? ' (' + agent + ')' : ''}${suffix}`;
    modeLabel.classList.add('active');
  } else {
    // No grid available at all yet
    infoEl.textContent = `Step ${ev?.step ?? '?'} | ${ev?.event || ''} (no grid yet)`;
    modeLabel.classList.add('active');
  }
  // Sync scrubber slider to match
  const gridIndices = _getGridEventIndices();
  const srcIdx = gridSource ? gridSource.sourceIdx : -1;
  const sliderPos = gridIndices.indexOf(srcIdx);
  if (sliderPos >= 0) {
    document.getElementById('obsScrubSlider').value = sliderPos;
    const dot = document.getElementById('obsScrubDot');
    dot.className = 'obs-scrubber-dot is-historical';
    dot.innerHTML = '&#9679; PAUSED';
    document.getElementById('obsScrubLabel').textContent = `Step ${sliderPos + 1} / ${gridIndices.length}`;
    const banner = document.getElementById('obsScrubBanner');
    banner.style.display = 'flex';
    document.getElementById('obsScrubBannerText').textContent = `Viewing step ${ev.step ?? '?'}`;
  }
}

// ── Timeline: Data Model ──

// Build structured spawn groups from raw events
function buildSpawnGroups(events) {
  if (!events.length) return { orchSegments: [], spawnGroups: [], t0: 0, tMax: 1 };

  const t0 = events[0].elapsed_s || 0;
  const tMax = events[events.length - 1].elapsed_s || 1;

  // Build orchestrator segments — only the LLM thinking call
  const orchSegments = []; // { startT, endT, idle, evIdx, ev }
  let lastOrchEnd = t0;

  // Track active subagents with unique keys to handle overlapping same-type agents
  const activeAgents = {};  // key = unique id
  let spawnCounter = 0;
  const spawnGroups = []; // { orchSegIdx, agentType, color, startT, endT, events[] }

  for (let j = 0; j < events.length; j++) {
    const ev = events[j];
    const t = ev.elapsed_s || 0;

    if (ev.event === 'orchestrator_decide') {
      // Idle gap before this thinking call
      if (t > lastOrchEnd + 0.01) {
        orchSegments.push({ startT: lastOrchEnd, endT: t, idle: true, evIdx: -1, ev: null });
      }
      const endT = ev.duration_ms ? t + ev.duration_ms / 1000 : t + 0.2;
      orchSegments.push({ startT: t, endT, idle: false, evIdx: j, ev });
      lastOrchEnd = endT;
      continue;
    }

    if (ev.event === 'subagent_start') {
      const agentType = (ev.agent_type || 'agent').toLowerCase();
      const parentSegIdx = orchSegments.length > 0 ? orchSegments.length - 1 : -1;
      // Unique key so two agents of same type don't overwrite
      const uid = agentType + '_' + (spawnCounter++);
      activeAgents[uid] = {
        agentType,
        orchSegIdx: parentSegIdx,
        startT: t,
        events: [{ idx: j, ev }],
      };
      continue;
    }

    if (ev.event === 'subagent_report') {
      const agentType = (ev.agent_type || '').toLowerCase();
      // Find oldest active agent of this type (FIFO)
      const uid = Object.keys(activeAgents).find(k => activeAgents[k].agentType === agentType);
      if (uid) {
        const ag = activeAgents[uid];
        ag.events.push({ idx: j, ev });
        spawnGroups.push({
          orchSegIdx: ag.orchSegIdx,
          agentType,
          color: agentColor(agentType),
          startT: ag.startT,
          endT: t,
          events: ag.events,
        });
        delete activeAgents[uid];
      }
      continue;
    }

    // act / frame_tool — attach to the active agent matching this agent type
    const agent = (ev.agent || '').toLowerCase();
    if (agent) {
      const uid = Object.keys(activeAgents).find(k => activeAgents[k].agentType === agent);
      if (uid) {
        activeAgents[uid].events.push({ idx: j, ev });
      }
    }
  }

  // Close any still-active agents (no report yet)
  for (const [uid, ag] of Object.entries(activeAgents)) {
    spawnGroups.push({
      orchSegIdx: ag.orchSegIdx,
      agentType: ag.agentType,
      color: agentColor(ag.agentType),
      startT: ag.startT,
      endT: tMax,
      events: ag.events,
      active: true,
    });
  }

  // Trailing idle segment
  if (lastOrchEnd < tMax) {
    orchSegments.push({ startT: lastOrchEnd, endT: tMax, idle: true, evIdx: -1, ev: null });
  }

  return { orchSegments, spawnGroups, t0, tMax };
}

// ── Render chips (colored to match parent agent) ──
function renderChips(groupEvents, agentHex) {
  const chips = [];
  for (const { ev } of groupEvents) {
    if (ev.event === 'act' && ev.action) {
      const displayAction = typeof humanAction === 'function' ? humanAction(ev.action) : ev.action;
      chips.push(`<span class="chip" style="background:${hexToRgba(agentHex,0.18)};color:${agentHex};border:1px solid ${hexToRgba(agentHex,0.3)}" title="${escapeHtmlAttr(displayAction)}">${escapeHtmlAttr(displayAction)}</span>`);
    } else if (ev.event === 'frame_tool' && ev.tool) {
      chips.push(`<span class="chip" style="background:${hexToRgba(agentHex,0.12)};color:${agentHex};border:1px solid ${hexToRgba(agentHex,0.2)}" title="${escapeHtmlAttr(ev.tool)}">${escapeHtmlAttr(ev.tool)}</span>`);
    }
  }
  if (chips.length === 0) return '';
  const MAX_CHIPS = 8;
  if (chips.length > MAX_CHIPS) {
    const overflow = chips.length - MAX_CHIPS;
    const shown = chips.slice(0, MAX_CHIPS);
    shown.push(`<span class="chip more">+${overflow}</span>`);
    return shown.join('');
  }
  return chips.join('');
}

// ── Timeline mode toggle ──
function setTimelineMode(mode) {
  timelineMode = mode;
  document.getElementById('modeSwimlane').classList.toggle('active', mode === 'swimlane');
  document.getElementById('modeCustom').classList.toggle('active', mode === 'custom');
  renderTimeline();
}

// ── Swimlane renderer ──
// Each subagent spawn gets its own lane. Orchestrator is always lane 0.
// Labels are frozen on the left; tracks scroll horizontally.
function renderTimelineSwimlane() {
  if (allEvents.length === 0) return;

  const canvas = document.getElementById('timelineCanvas');
  const container = document.getElementById('timelineContainer');

  const t0 = allEvents[0].elapsed_s || 0;
  const tMax = allEvents[allEvents.length - 1].elapsed_s || 1;
  const duration = Math.max(tMax - t0, 1);

  const containerW = container.clientWidth - 90; // 80 label + 10 pad
  const basePxPerSec = Math.max(containerW / duration, 2);
  const pxPerSec = basePxPerSec * timelineZoom;
  const totalW = Math.max(Math.ceil(duration * pxPerSec), containerW);

  const { orchSegments, spawnGroups } = buildSpawnGroups(allEvents);

  // Build lanes: lane 0 = orchestrator, lanes 1+ = one per spawn group (in order)
  const lanes = []; // { label, color, blocks[] }

  // Lane 0: orchestrator
  const orchBlocks = [];
  for (let si = 0; si < orchSegments.length; si++) {
    const seg = orchSegments[si];
    orchBlocks.push({
      startT: seg.startT,
      endT: seg.endT,
      idle: seg.idle,
      orchIdx: si,
    });
  }
  lanes.push({ label: 'orchestrator', color: agentColor('orchestrator'), blocks: orchBlocks });

  // One lane per subagent spawn
  for (let si = 0; si < spawnGroups.length; si++) {
    const sg = spawnGroups[si];
    const blocks = [];

    // Background lifecycle span
    blocks.push({
      startT: sg.startT,
      endT: sg.endT,
      sgIdx: si,
      isSpan: true,
      color: sg.color,
      active: sg.active,
    });

    // Individual event blocks on top
    for (const { ev, idx } of sg.events) {
      if (ev.event === 'subagent_start' || ev.event === 'subagent_report') continue;
      const evT = ev.elapsed_s || 0;
      const evDur = ev.duration_ms ? ev.duration_ms / 1000 : 0;
      blocks.push({
        startT: evT,
        endT: evT + Math.max(evDur, 0.1),
        ev,
        evIdx: idx,
        isInner: true,
        color: sg.color,
      });
    }

    lanes.push({ label: sg.agentType, color: sg.color, blocks });
  }

  // Render: two-column layout (frozen labels | scrollable tracks)
  let labelsHtml = '';
  let tracksHtml = '';

  for (let i = 0; i < lanes.length; i++) {
    const lane = lanes[i];
    const c = lane.color;

    labelsHtml += `<div class="swimlane-label" style="color:${c}">${lane.label}</div>`;
    tracksHtml += `<div class="swimlane-row">`;

    for (const blk of lane.blocks) {
      const left = (blk.startT - t0) * pxPerSec;
      const w = Math.max((blk.endT - blk.startT) * pxPerSec, 4);

      if (i === 0) {
        // Orchestrator
        if (blk.idle) {
          tracksHtml += `<div class="event-block" style="left:${left}px;width:${w}px;background:${c};opacity:0.10"></div>`;
        } else {
          tracksHtml += `<div class="event-block" style="left:${left}px;width:${w}px;background:${c};opacity:0.7" data-orch-idx="${blk.orchIdx}"></div>`;
        }
      } else if (blk.isSpan) {
        const opacity = blk.active ? '0.25' : '0.15';
        tracksHtml += `<div class="event-block" style="left:${left}px;width:${w}px;background:${blk.color};opacity:${opacity};border-left:2px solid ${blk.color}" data-sg-idx="${blk.sgIdx}"></div>`;
      } else if (blk.isInner) {
        let opacity = '0.6';
        if (blk.ev?.event === 'frame_tool') opacity = '0.3';
        tracksHtml += `<div class="event-block" style="left:${left}px;width:${w}px;background:${blk.color};opacity:${opacity}" data-ev-idx="${blk.evIdx}"></div>`;
      }
    }

    tracksHtml += `</div>`;
  }

  const tracksCanvasW = totalW + 10;
  canvas.innerHTML =
    `<div class="swimlane-wrap">` +
      `<div class="swimlane-labels">${labelsHtml}</div>` +
      `<div class="swimlane-tracks-scroll" id="swimlaneScroll">` +
        `<div class="swimlane-tracks-canvas" style="width:${tracksCanvasW}px">${tracksHtml}</div>` +
      `</div>` +
    `</div>`;

  // Auto-scroll the tracks area
  if (timelineAutoScroll) {
    const scrollEl = document.getElementById('swimlaneScroll');
    if (scrollEl) scrollEl.scrollLeft = scrollEl.scrollWidth;
  }

  // Store data for tooltips
  canvas._orchSegments = orchSegments;
  canvas._spawnGroups = spawnGroups;

  // Attach hover events
  canvas.querySelectorAll('.event-block[data-orch-idx]').forEach(el => {
    el.addEventListener('mouseenter', showOrchTooltip);
    el.addEventListener('mouseleave', hideTooltip);
  });
  canvas.querySelectorAll('.event-block[data-sg-idx]').forEach(el => {
    el.addEventListener('mousemove', (e) => {
      const sgIdx = parseInt(e.target.dataset.sgIdx);
      const sg = spawnGroups[sgIdx];
      if (!sg) return;
      const rect = e.target.getBoundingClientRect();
      const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      showProportionalTooltipForSG(sg, fraction, e);
    });
    el.addEventListener('mouseleave', hideTooltip);
  });
  canvas.querySelectorAll('.event-block[data-ev-idx]').forEach(el => {
    el.addEventListener('mouseenter', (e) => {
      const idx = parseInt(e.target.dataset.evIdx);
      const ev = allEvents[idx];
      if (!ev) return;
      showSimpleEventTooltip(ev, e);
    });
    el.addEventListener('mouseleave', hideTooltip);
  });
}

// Simple tooltip for individual events (used in swimlane view)
function showSimpleEventTooltip(ev, e) {
  const agent = ev.agent || ev.agent_type || '';
  const c = agentColor(agent);
  let html = `<div class="tt-agent" style="color:${c}">${agent || 'system'}</div>`;
  html += `<div>${ev.event}</div>`;
  if (ev.elapsed_s != null) html += `<div class="tt-dim">t = +${ev.elapsed_s.toFixed(1)}s</div>`;
  if (ev.duration_ms) html += `<div>Duration: ${ev.duration_ms}ms</div>`;
  if (ev.input_tokens) html += `<div>Tokens: ${fmtK(ev.input_tokens)} in / ${fmtK(ev.output_tokens || 0)} out</div>`;
  if (ev.action) html += `<div>Action: ${typeof humanAction === 'function' ? humanAction(ev.action) : ev.action}</div>`;
  if (ev.tool) html += `<div>Tool: ${ev.tool}</div>`;
  if (ev.reasoning) html += `<div style="max-width:300px;word-break:break-word;color:#aaa">${escapeHtmlAttr(ev.reasoning)}</div>`;
  if (ev.task) html += `<div style="max-width:300px;word-break:break-word;">Task: ${ev.task}</div>`;

  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.classList.add('visible');
  positionTooltip(tt, e);
}

// Proportional tooltip helper for spawn group (shared by both views)
function showProportionalTooltipForSG(sg, fraction, e) {
  const spanStart = sg.startT;
  const spanEnd = sg.endT;
  const spanDur = Math.max(spanEnd - spanStart, 0.01);
  const targetT = spanStart + fraction * spanDur;

  let bestEv = sg.events[0];
  let bestDist = Infinity;
  for (const entry of sg.events) {
    const et = entry.ev.elapsed_s || 0;
    const dist = Math.abs(et - targetT);
    if (dist < bestDist) { bestDist = dist; bestEv = entry; }
  }

  const ev = bestEv.ev;
  const c = sg.color;
  const agent = ev.agent || ev.agent_type || sg.agentType;
  const progressPct = Math.round(fraction * 100);
  const progressBar = `<div style="background:#1a1a24;border-radius:2px;height:4px;margin:4px 0;overflow:hidden"><div style="background:${c};height:100%;width:${progressPct}%;border-radius:2px"></div></div>`;

  let html = `<div class="tt-agent" style="color:${c}">${agent}</div>`;
  html += progressBar;
  html += `<div>${ev.event}</div>`;
  if (ev.action) html += `<div>Action: ${typeof humanAction === 'function' ? humanAction(ev.action) : ev.action}</div>`;
  if (ev.tool) html += `<div>Tool: ${ev.tool}</div>`;
  if (ev.reasoning) html += `<div style="max-width:300px;word-break:break-word;color:#aaa">${escapeHtmlAttr(ev.reasoning)}</div>`;
  if (ev.task) html += `<div style="max-width:300px;word-break:break-word;">Task: ${ev.task}</div>`;
  if (ev.summary) html += `<div style="max-width:300px;word-break:break-word;">Summary: ${ev.summary}</div>`;
  if (ev.elapsed_s != null) html += `<div class="tt-dim">t = +${ev.elapsed_s.toFixed(1)}s</div>`;
  if (ev.duration_ms) html += `<div>Duration: ${ev.duration_ms}ms</div>`;
  if (ev.input_tokens) html += `<div>Tokens: ${fmtK(ev.input_tokens)} in / ${fmtK(ev.output_tokens || 0)} out</div>`;

  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.classList.add('visible');
  positionTooltip(tt, e);
}

// ── Timeline rendering (dispatcher) ──
function renderTimeline() {
  if (allEvents.length === 0) return;

  if (timelineMode === 'swimlane') {
    renderTimelineSwimlane();
    return;
  }

  // Custom mode (orch bar + positioned blocks)
  const canvas = document.getElementById('timelineCanvas');
  const container = document.getElementById('timelineContainer');
  const containerW = container.clientWidth - 20;

  const { orchSegments, spawnGroups, t0, tMax } = buildSpawnGroups(allEvents);
  const duration = Math.max(tMax - t0, 0.1);

  // Compute canvas width based on zoom
  const baseW = Math.max(containerW, 400);
  const canvasW = Math.max(baseW * timelineZoom, containerW);
  canvas.style.width = canvasW + 'px';

  // Helper: time → percentage string
  const toPct = (t) => ((t - t0) / duration * 100).toFixed(4) + '%';
  const toW = (dt) => (dt / duration * 100).toFixed(4) + '%';

  // ── 1. Render orchestrator bar (only LLM thinking segments) ──
  let orchHtml = '<div class="orch-bar">';
  for (let i = 0; i < orchSegments.length; i++) {
    const seg = orchSegments[i];
    const left = toPct(seg.startT);
    const width = toW(Math.max(seg.endT - seg.startT, duration * 0.003));

    if (seg.idle) {
      orchHtml += `<div class="orch-segment idle" style="left:${left};width:${width}" data-orch-idx="${i}"></div>`;
    } else {
      // Only "thinking" label — spawning is shown by the subagent blocks below
      orchHtml += `<div class="orch-segment decide" style="left:${left};width:${width}" data-orch-idx="${i}">thinking</div>`;
    }
  }
  orchHtml += '</div>';

  // ── 2. Render subagent blocks with accurate time positioning ──
  // Row-pack: assign each spawn group to a row, stacking when time ranges overlap
  const sorted = spawnGroups.map((sg, i) => ({ ...sg, sgIdx: i }));
  sorted.sort((a, b) => a.startT - b.startT);

  const rows = []; // each row = array of { startT, endT }
  const rowAssignment = new Array(spawnGroups.length).fill(0);

  for (const sg of sorted) {
    let placed = false;
    for (let r = 0; r < rows.length; r++) {
      const overlaps = rows[r].some(blk => sg.startT < blk.endT && sg.endT > blk.startT);
      if (!overlaps) {
        rows[r].push({ startT: sg.startT, endT: sg.endT });
        rowAssignment[sg.sgIdx] = r;
        placed = true;
        break;
      }
    }
    if (!placed) {
      rows.push([{ startT: sg.startT, endT: sg.endT }]);
      rowAssignment[sg.sgIdx] = rows.length - 1;
    }
  }

  const blockHeight = 28;
  const blockGap = 3;
  const connectorH = 8;
  const numRows = Math.max(rows.length, 1);
  const spawnContainerH = connectorH + numRows * (blockHeight + blockGap);

  let spawnHtml = `<div class="spawn-groups-container" style="height:${spawnContainerH}px">`;

  for (let i = 0; i < spawnGroups.length; i++) {
    const sg = spawnGroups[i];
    const row = rowAssignment[i];
    const bgAlpha = sg.active ? 0.25 : 0.15;
    const bgColor = sg.color;
    const chips = renderChips(sg.events, bgColor);

    // Accurate horizontal position: left and width from actual startT→endT
    const left = toPct(sg.startT);
    const width = toW(Math.max(sg.endT - sg.startT, duration * 0.005));
    const top = connectorH + row * (blockHeight + blockGap);

    // Connector line from orch bar down to this block
    const orchSeg = sg.orchSegIdx >= 0 && sg.orchSegIdx < orchSegments.length ? orchSegments[sg.orchSegIdx] : null;
    if (orchSeg) {
      const connLeft = toPct(orchSeg.startT + (orchSeg.endT - orchSeg.startT) / 2);
      spawnHtml += `<div class="spawn-connector" style="left:${connLeft};top:0;height:${top}px"></div>`;
    }

    spawnHtml += `<div class="subagent-block" style="left:${left};width:${width};top:${top}px;background:${hexToRgba(bgColor, bgAlpha)};border-left-color:${bgColor}" data-sg-idx="${i}">`;
    spawnHtml += `<span class="sa-label" style="color:${bgColor}">${sg.agentType}</span>`;
    if (chips) spawnHtml += `<span class="chips">${chips}</span>`;
    spawnHtml += `</div>`;
  }
  spawnHtml += '</div>';

  canvas.innerHTML = orchHtml + spawnHtml;

  // Auto-scroll timeline to right
  if (timelineAutoScroll) {
    container.scrollLeft = container.scrollWidth;
  }

  // ── Attach hover events ──
  canvas.querySelectorAll('.orch-segment.decide').forEach(el => {
    el.addEventListener('mouseenter', showOrchTooltip);
    el.addEventListener('mouseleave', hideTooltip);
  });
  canvas.querySelectorAll('.subagent-block').forEach(el => {
    el.addEventListener('mousemove', showProportionalTooltip);
    el.addEventListener('mouseleave', hideTooltip);
  });

  // Store parsed data for tooltip access
  canvas._spawnGroups = spawnGroups;
  canvas._orchSegments = orchSegments;
}

// ── Hex to rgba helper ──
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Orch segment tooltip ──
function showOrchTooltip(e) {
  const canvas = document.getElementById('timelineCanvas');
  const idx = parseInt(e.target.dataset.orchIdx);
  const seg = canvas._orchSegments?.[idx];
  if (!seg || !seg.ev) return;

  const ev = seg.ev;
  const c = agentColor('orchestrator');

  let html = `<div class="tt-agent" style="color:${c}">orchestrator</div>`;
  html += `<div>orchestrator_decide</div>`;
  if (ev.command) html += `<div>Command: ${ev.command}</div>`;
  if (ev.agent_type) html += `<div>Agent: ${ev.agent_type}</div>`;
  if (ev.task) html += `<div style="max-width:300px;word-break:break-word;">Task: ${ev.task}</div>`;
  if (ev.elapsed_s != null) html += `<div class="tt-dim">t = +${ev.elapsed_s.toFixed(1)}s</div>`;
  if (ev.duration_ms) html += `<div>Duration: ${ev.duration_ms}ms</div>`;
  if (ev.input_tokens) html += `<div>Tokens: ${fmtK(ev.input_tokens)} in / ${fmtK(ev.output_tokens || 0)} out</div>`;

  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.classList.add('visible');
  positionTooltip(tt, e);
}

// ── Proportional tooltip on subagent blocks (custom view) ──
function showProportionalTooltip(e) {
  const block = e.currentTarget;
  const canvas = document.getElementById('timelineCanvas');
  const sgIdx = parseInt(block.dataset.sgIdx);
  const sg = canvas._spawnGroups?.[sgIdx];
  if (!sg || !sg.events.length) return;
  const rect = block.getBoundingClientRect();
  const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  showProportionalTooltipForSG(sg, fraction, e);
}

// ── Position tooltip near cursor ──
function positionTooltip(tt, e) {
  const pad = 12;
  let left = e.clientX + pad;
  let top = e.clientY + pad;
  // Keep within viewport
  const ttRect = tt.getBoundingClientRect();
  if (left + ttRect.width > window.innerWidth - 10) {
    left = e.clientX - ttRect.width - pad;
  }
  if (top + ttRect.height > window.innerHeight - 10) {
    top = e.clientY - ttRect.height - pad;
  }
  tt.style.left = Math.max(0, left) + 'px';
  tt.style.top = Math.max(0, top) + 'px';
}

function hideTooltip() {
  document.getElementById('tooltip').classList.remove('visible');
}

// ── Grid rendering ──
const GRID_COLORS = {
  0: '#FFFFFF', 1: '#CCCCCC', 2: '#999999', 3: '#666666',
  4: '#333333', 5: '#000000', 6: '#E53AA3', 7: '#FF7BCC',
  8: '#F93C31', 9: '#1E93FF', 10: '#88D8F1', 11: '#FFDC00',
  12: '#FF851B', 13: '#921231', 14: '#4FCC30', 15: '#A356D6',
};

let lastGridJson = '';

async function fetchGrid() {
  try {
    const r = await fetch('/api/obs/grid');
    if (!r.ok) return;
    const text = await r.text();
    if (text === lastGridJson) return;  // no change
    lastGridJson = text;
    const grid = JSON.parse(text);
    // Don't overwrite when user is viewing a historical grid
    if (!frozenGrid) {
      currentGrid = grid;
      renderGameGrid(grid);
      obsScrubUpdate();
    }
  } catch {}
}

function renderGameGrid(grid) {
  if (!grid || !grid.length) return;
  const canvas = document.getElementById('gridCanvas');
  const ctx = canvas.getContext('2d');
  const h = grid.length, w = grid[0].length;
  const maxPx = 800;
  const scale = Math.max(1, Math.floor(maxPx / Math.max(h, w)));
  canvas.width = w * scale;
  canvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = GRID_COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
  // Update info
  const info = document.getElementById('gridInfo');
  const step = statusData?.step ?? '--';
  info.textContent = `Step ${step} | ${w}x${h}`;
}

// ── Observatory scrubber ──

// Build an index of event indices that have grids
function _getGridEventIndices() {
  const indices = [];
  for (let i = 0; i < allEvents.length; i++) {
    if (allEvents[i] && allEvents[i].grid && allEvents[i].grid.length > 0) {
      indices.push(i);
    }
  }
  return indices;
}

function obsScrubUpdate() {
  const gridIndices = _getGridEventIndices();
  const total = gridIndices.length;
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  slider.max = Math.max(0, total - 1);
  if (!frozenGrid) {
    // Live mode — snap to end
    slider.value = Math.max(0, total - 1);
    document.getElementById('obsScrubLabel').textContent = `Step ${total} / ${total}`;
    const dot = document.getElementById('obsScrubDot');
    dot.className = 'obs-scrubber-dot is-live';
    dot.innerHTML = '&#9679; LIVE';
    document.getElementById('obsScrubBanner').style.display = 'none';
  } else {
    // Historical — find current position in gridIndices
    const pos = gridIndices.indexOf(selectedEventIdx);
    const displayPos = pos >= 0 ? pos + 1 : '?';
    document.getElementById('obsScrubLabel').textContent = `Step ${displayPos} / ${total}`;
  }
}

function obsScrubShow(sliderVal) {
  const gridIndices = _getGridEventIndices();
  const idx = parseInt(sliderVal);
  if (idx < 0 || idx >= gridIndices.length) return;
  const evIdx = gridIndices[idx];
  const ev = allEvents[evIdx];
  if (!ev || !ev.grid) return;

  // Set frozen/historical state
  selectedEventIdx = evIdx;
  frozenGrid = ev.grid;
  currentGrid = ev.grid;
  renderGameGrid(ev.grid);

  // Update grid info
  const infoEl = document.getElementById('gridInfo');
  const step = ev.step ?? '?';
  const agent = ev.agent || ev.agent_type || '';
  const label = humanAction(ev.action) || ev.event || '';
  infoEl.textContent = `Step ${step} | ${label}${agent ? ' (' + agent + ')' : ''}`;

  // Update mode label
  document.getElementById('gridModeLabel').classList.add('active');

  // Highlight matching log row
  const tbody = document.getElementById('logBody');
  tbody.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
  const matchRow = tbody.querySelector(`tr[data-ev-idx="${evIdx}"]`);
  if (matchRow) matchRow.classList.add('selected');

  // Update scrubber UI
  const dot = document.getElementById('obsScrubDot');
  dot.className = 'obs-scrubber-dot is-historical';
  dot.innerHTML = '&#9679; PAUSED';
  document.getElementById('obsScrubLabel').textContent = `Step ${idx + 1} / ${gridIndices.length}`;
  const banner = document.getElementById('obsScrubBanner');
  banner.style.display = 'flex';
  document.getElementById('obsScrubBannerText').textContent = `Viewing step ${step}`;
}

function obsScrubReturnToLive() {
  selectedEventIdx = -1;
  frozenGrid = null;
  document.getElementById('gridModeLabel').classList.remove('active');
  // Deselect log rows
  document.getElementById('logBody').querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
  // Restore live grid
  if (currentGrid) renderGameGrid(currentGrid);
  // Update scrubber
  obsScrubUpdate();
}

// Bind slider events
document.getElementById('obsScrubSlider').oninput = function() {
  const gridIndices = _getGridEventIndices();
  const idx = parseInt(this.value);
  if (idx >= gridIndices.length - 1 && !frozenGrid) {
    obsScrubReturnToLive();
  } else {
    obsScrubShow(idx);
  }
};

// ── Coordinate reference highlighting ──
const COORD_RE = /(?:rows?)\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?\s*,\s*(?:cols?)\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?|\((\d+),\s*(\d+)\)|(?:rows?)\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?|(?:cols?)\s+(\d+)(?:\s*[-\u2013]\s*(\d+))?/gi;

function annotateCoordRefs(element) {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  for (const node of textNodes) {
    const text = node.textContent;
    COORD_RE.lastIndex = 0;
    if (!COORD_RE.test(text)) continue;
    COORD_RE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let lastIdx = 0, match;
    while ((match = COORD_RE.exec(text)) !== null) {
      if (match.index > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      const span = document.createElement('span');
      span.className = 'coord-ref';
      if (match[1] !== undefined) {
        span.dataset.rows = match[2] !== undefined ? `${match[1]}-${match[2]}` : match[1];
        span.dataset.cols = match[4] !== undefined ? `${match[3]}-${match[4]}` : match[3];
      } else if (match[5] !== undefined) { span.dataset.row = match[5]; span.dataset.col = match[6]; }
      else if (match[7] !== undefined) { span.dataset.rows = match[8] !== undefined ? `${match[7]}-${match[8]}` : match[7]; }
      else if (match[9] !== undefined) { span.dataset.cols = match[10] !== undefined ? `${match[9]}-${match[10]}` : match[9]; }
      span.textContent = match[0];
      frag.appendChild(span);
      lastIdx = COORD_RE.lastIndex;
    }
    if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    if (lastIdx > 0) node.parentNode.replaceChild(frag, node);
  }
}

function cellsFromCoordRef(ref) {
  const cells = [];
  if (!currentGrid || !currentGrid.length) return cells;
  const h = currentGrid.length, w = currentGrid[0].length;
  if (ref.dataset.row !== undefined && ref.dataset.col !== undefined) {
    cells.push({ row: parseInt(ref.dataset.row), col: parseInt(ref.dataset.col) });
  } else if (ref.dataset.rows !== undefined && ref.dataset.cols !== undefined) {
    const rp = ref.dataset.rows.split('-').map(Number), cp = ref.dataset.cols.split('-').map(Number);
    for (let r = rp[0]; r <= (rp[1] ?? rp[0]); r++) for (let c = cp[0]; c <= (cp[1] ?? cp[0]); c++) cells.push({ row: r, col: c });
  } else if (ref.dataset.rows !== undefined) {
    const p = ref.dataset.rows.split('-').map(Number);
    for (let r = p[0]; r <= (p[1] ?? p[0]); r++) for (let c = 0; c < w; c++) cells.push({ row: r, col: c });
  } else if (ref.dataset.cols !== undefined) {
    const p = ref.dataset.cols.split('-').map(Number);
    for (let r = 0; r < h; r++) for (let c = p[0]; c <= (p[1] ?? p[0]); c++) cells.push({ row: r, col: c });
  }
  return cells;
}

function highlightCellsOnCanvas(cells) {
  if (!cells.length || !currentGrid) return;
  const canvas = document.getElementById('gridCanvas');
  const ctx = canvas.getContext('2d');
  const h = currentGrid.length, w = currentGrid[0].length;
  const scale = Math.max(1, Math.floor(600 / Math.max(h, w)));
  ctx.save();
  ctx.fillStyle = 'rgba(59, 130, 246, 0.4)';
  ctx.strokeStyle = 'rgba(59, 130, 246, 0.8)';
  ctx.lineWidth = 2;
  for (const { row, col } of cells) {
    if (row >= 0 && row < h && col >= 0 && col < w) {
      ctx.fillRect(col * scale, row * scale, scale, scale);
      ctx.strokeRect(col * scale, row * scale, scale, scale);
    }
  }
  ctx.restore();
}

function clearCellHighlights() {
  if (currentGrid) renderGameGrid(currentGrid);
}

// Event delegation for coord-ref hover on log details
document.addEventListener('mouseover', (e) => {
  const ref = e.target.closest('.coord-ref');
  if (!ref) return;
  highlightCellsOnCanvas(cellsFromCoordRef(ref));
});
document.addEventListener('mouseout', (e) => {
  const ref = e.target.closest('.coord-ref');
  if (!ref) return;
  clearCellHighlights();
});

// ── Timeline zoom (Ctrl+Scroll) ──
document.getElementById('timelineContainer').addEventListener('wheel', (e) => {
  if (!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();

  // In swimlane mode, the scrollable element is #swimlaneScroll, not the container
  const scrollEl = document.getElementById('swimlaneScroll') || document.getElementById('timelineContainer');
  const rect = scrollEl.getBoundingClientRect();
  const mouseX = e.clientX - rect.left + scrollEl.scrollLeft;
  const fraction = mouseX / (scrollEl.scrollWidth || 1);

  const oldZoom = timelineZoom;
  const factor = e.deltaY < 0 ? 1.25 : 0.8;
  timelineZoom = Math.max(0.1, Math.min(100, timelineZoom * factor));
  timelineAutoScroll = false;
  document.getElementById('zoomLabel').textContent = timelineZoom.toFixed(1) + 'x';

  renderTimeline();

  // Keep mouse anchored to same point in timeline
  const newScrollEl = document.getElementById('swimlaneScroll') || document.getElementById('timelineContainer');
  const newMouseX = fraction * newScrollEl.scrollWidth;
  newScrollEl.scrollLeft = newMouseX - (e.clientX - rect.left);
}, { passive: false });

// ── Session Browser ──
let replayMode = false;

function toggleSessionBrowser() {
  const overlay = document.getElementById('sessionOverlay');
  const visible = overlay.classList.toggle('visible');
  document.getElementById('browseBtn').classList.toggle('active', visible);
  if (visible) fetchSessionList();
}

let allSessions = [];

async function fetchSessionList() {
  try {
    // Try both sources and merge (file-based + central DB)
    const [fileRes, dbRes] = await Promise.allSettled([
      fetch('/api/sessions/browse'),
      fetch('/api/sessions/list-for-obs'),
    ]);
    const seen = new Set();
    allSessions = [];
    for (const res of [fileRes, dbRes]) {
      if (res.status === 'fulfilled' && res.value.ok) {
        const data = await res.value.json();
        for (const s of (data.sessions || [])) {
          if (!seen.has(s.id)) { seen.add(s.id); allSessions.push(s); }
        }
      }
    }
    allSessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    // Populate model filter dropdown
    const models = [...new Set(allSessions.map(s => s.model).filter(Boolean))].sort();
    const modelSelect = document.getElementById('filterModel');
    const curModel = modelSelect.value;
    modelSelect.innerHTML = '<option value="">All models</option>';
    for (const m of models) {
      modelSelect.innerHTML += `<option value="${escapeHtmlAttr(m)}">${escapeHtmlAttr(m.replace(/^(gemini|claude|groq|mistral|ollama)\//, ''))}</option>`;
    }
    modelSelect.value = curModel;

    applySessionFilters();
  } catch (e) {
    console.error('Failed to fetch sessions:', e);
  }
}

function applySessionFilters() {
  const gameFilter = (document.getElementById('filterGame').value || '').toLowerCase();
  const resultFilter = document.getElementById('filterResult').value;
  const modelFilter = document.getElementById('filterModel').value;

  const filtered = allSessions.filter(s => {
    if (gameFilter && !(s.game_id || '').toLowerCase().includes(gameFilter)) return false;
    if (resultFilter && s.result !== resultFilter) return false;
    if (modelFilter && s.model !== modelFilter) return false;
    return true;
  });

  const tbody = document.getElementById('sessionListBody');
  document.getElementById('sessionCount').textContent = `${filtered.length} of ${allSessions.length}`;

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#555;padding:20px">No sessions found</td></tr>';
    return;
  }
  tbody.innerHTML = '';
  for (const s of filtered) {
    const tr = document.createElement('tr');
    const result = (s.result || '').toUpperCase();
    const badgeClass = result.includes('WON') || result.includes('WIN') || result.includes('COMPLETE') ? 'won'
      : result.includes('LOST') || result.includes('FAIL') || result.includes('DEAD') ? 'lost' : 'other';
    const date = s.created_at ? new Date(s.created_at * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--';
    const cost = s.total_cost ? '$' + s.total_cost.toFixed(3) : '--';
    tr.innerHTML = `
      <td style="color:#e0e0e0;font-weight:500">${escapeHtmlAttr(s.game_id || '')}</td>
      <td>${escapeHtmlAttr((s.model || '').replace(/^(gemini|claude|groq|mistral|ollama)\//, ''))}</td>
      <td>${s.steps || 0}</td>
      <td>${s.levels || 0}</td>
      <td><span class="result-badge ${badgeClass}">${escapeHtmlAttr(s.result || 'N/A')}</span></td>
      <td>${cost}</td>
      <td style="color:#666">${date}</td>
    `;
    tr.addEventListener('click', () => loadSession(s.id, s.game_id));
    tbody.appendChild(tr);
  }
}

async function loadSession(sessionId, gameId) {
  // Close browser
  document.getElementById('sessionOverlay').classList.remove('visible');
  document.getElementById('browseBtn').classList.remove('active');

  // Stop live polling
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  replayMode = true;

  // Reset state
  resetState();
  setConn(false);
  document.getElementById('connStatus').textContent = 'REPLAY';
  document.getElementById('connStatus').className = 'conn';
  document.getElementById('connStatus').style.color = '#3b82f6';
  document.getElementById('replayBadge').textContent = `[${gameId || sessionId.slice(0, 8)}]`;

  // Fetch reconstructed obs events
  try {
    const r = await fetch(`/api/sessions/${sessionId}/obs-events`);
    if (!r.ok) { console.error('Failed to load session obs events'); return; }
    const data = await r.json();
    if (data.events && data.events.length > 0) {
      data.events.forEach(normalizeEvent);
      allEvents = data.events;

      // Compute status summary from events
      let totalIn = 0, totalOut = 0, totalCost = 0, totalCalls = 0, maxStep = 0;
      let model = '';
      for (const ev of allEvents) {
        if (ev.input_tokens) totalIn += ev.input_tokens;
        if (ev.output_tokens) totalOut += ev.output_tokens;
        if (ev.cost) totalCost += ev.cost;
        if (ev.event === 'llm_call' || ev.event === 'orchestrator_decide') { totalCalls++; if (ev.model) model = ev.model; }
        if (ev.step_num != null && ev.step_num > maxStep) maxStep = ev.step_num;
        trackEventTokens(ev);
      }

      // Populate status bar
      document.getElementById('sGame').textContent = gameId || '--';
      document.getElementById('sState').textContent = 'REPLAY';
      document.getElementById('sStep').textContent = maxStep;
      document.getElementById('sCalls').textContent = totalCalls;
      document.getElementById('sTokens').textContent = `${fmtK(totalIn)} / ${fmtK(totalOut)}`;
      if (totalCost > 0) {
        document.getElementById('sCost').textContent = '$' + totalCost.toFixed(3);
      }
      const elapsed = allEvents.length > 0 ? allEvents[allEvents.length - 1].elapsed_s || 0 : 0;
      if (elapsed < 60) {
        document.getElementById('sElapsed').textContent = `${Math.round(elapsed)}s`;
      } else {
        document.getElementById('sElapsed').textContent = `${(elapsed / 60).toFixed(1)}m`;
      }
      document.getElementById('sAgent').textContent = model || '--';

      // Render
      renderNewEvents(allEvents);
      renderTimeline();

      // Show first grid if available
      const firstGrid = allEvents.find(ev => ev.grid && ev.grid.length > 0);
      if (firstGrid) {
        currentGrid = firstGrid.grid;
        renderGameGrid(firstGrid.grid);
      }
    }
  } catch (e) {
    console.error('Failed to load session:', e);
  }
}

function returnToLive() {
  replayMode = false;
  resetState();
  document.getElementById('replayBadge').textContent = '';
  document.getElementById('connStatus').style.color = '';
  poll();
}

// ── Init ──
const shareSessionId = window.shareSessionId;
if (shareSessionId) {
  // Share mode: fetch session metadata for game_id, then auto-load
  (async () => {
    let gameId = '';
    try {
      const r = await fetch(`/api/sessions/${shareSessionId}`);
      if (r.ok) {
        const d = await r.json();
        gameId = d.session?.game_id || '';
      }
    } catch {}
    document.title = gameId ? `${gameId} — Observatory` : 'Observatory';
    loadSession(shareSessionId, gameId);
  })();
} else {
  poll();
}
