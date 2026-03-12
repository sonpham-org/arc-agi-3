// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Standalone Observatory page logic for ARC-AGI-3 (obs.html). Renders
//   session detail views with swimlane timelines, step-by-step log, grid replay,
//   and performance metrics. Uses obs-log-renderer.js, obs-scrubber.js, and
//   obs-swimlane-renderer.js for shared rendering. Depends on reasoning.js for
//   agent color palette. Modified in Phases 1 & 4 to extract formatting utils
//   and shared observatory rendering into separate modules. Phase 23: swimlane,
//   scrubber, and session-loader logic extracted.
// SRP/DRY check: Pass — shared rendering extracted to observatory/ modules
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

// ── Init ──
function init() {
  // Attach event handlers for scrubber and timeline zoom
  attachScrubberSliderHandler();
  attachTimelineZoomHandler();
  
  // Start polling if not in share/replay mode
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
}

// Start initialization when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
