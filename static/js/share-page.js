// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Share/replay page logic for ARC-AGI-3 (share.html). Renders saved session
//   replays with grid animation, step-by-step playback, reasoning display, timeline
//   visualization, and branch-from-step functionality. Consumes window.SESSION,
//   window.STEPS, window.TIMELINE_DATA injected by the share.html template.
//   Depends on reasoning.js (agentColor, renderTimeline), utils/formatting.js.
//   Modified in Phase 1 to use shared formatting utilities.
// SRP/DRY check: Pass — formatting extracted to utils/formatting.js in Phase 1
const COLORS = window.COLORS;
const ACTION_NAMES = window.ACTION_NAMES;
const SESSION = window.SESSION;
const STEPS = window.STEPS;
const BRANCH_AT_STEP = window.BRANCH_AT_STEP;
const TIMELINE_DATA = window.TIMELINE_DATA;
const CALL_LOG = window.CALL_LOG;

const canvas = document.getElementById('replayCanvas');
const ctx = canvas.getContext('2d');
const scrubber = document.getElementById('scrubber');
const stepCounter = document.getElementById('stepCounter');
const reasoningScroll = document.getElementById('reasoningScroll');
const btnPrev = document.getElementById('btnPrev');
const btnPlay = document.getElementById('btnPlay');
const btnAutoplay = document.getElementById('btnAutoplay');
const btnNext = document.getElementById('btnNext');

let currentIdx = -1;
let autoplayTimer = null;
let isAutoplaying = false;
let showDiffOverlay = false;
let diffOpacity = 0.4;
let diffColor = '#ff0000';

// ── Tab switching (mirrors main app's switchSubTab) ───────────────────
function switchTab(tab) {
  document.querySelectorAll('.subtab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.subtab-pane').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  const tabMap = { settings: 'pane-settings', graphics: 'pane-graphics', prompt: 'pane-prompt', reasoning: 'pane-reasoning', timeline: 'pane-timeline' };
  const buttons = document.querySelectorAll('.subtab-bar button');
  const idx = { settings: 0, graphics: 1, prompt: 2, reasoning: 3, timeline: 4 }[tab] || 3;
  if (buttons[idx]) buttons[idx].classList.add('active');
  const pane = document.getElementById(tabMap[tab]);
  if (pane) { pane.classList.add('active'); pane.style.display = 'flex'; }
  if (tab === 'timeline') renderShareTimeline();
}

// ── Timeline rendering for share page ─────────────────────────────────
// Labels and colors now provided by reasoning.js (loaded before this file)
function _stlCssClass(ev) {
  const t = ev.agent_type || ev.call_type || ev.type || 'reasoning';
  return t.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function _stlLabel(ev) {
  const aType = ev.agent_type || ev.call_type || ev.type || 'executor';
  return agentLabel(aType, ev.model);
}

function _stlFormatCost(c) { return c > 0 ? '$' + c.toFixed(4) : ''; }

function _stlBuildDetail(ev, idx) {
  const inTok = ev.input_tokens || 0;
  const outTok = ev.output_tokens || 0;
  const totalTok = inTok + outTok;
  const cost = ev.cost || 0;
  const promptLen = ev.prompt_length || 0;
  let html = `<div class="tl-detail" id="stlDetail${idx}">`;
  html += `<div class="tl-meta">`;
  if (totalTok > 0) html += `<span class="tl-tokens">${inTok.toLocaleString()} in + ${outTok.toLocaleString()} out = ${totalTok.toLocaleString()} tok</span>`;
  if (cost > 0) html += `<span class="tl-cost">${_stlFormatCost(cost)}</span>`;
  if (promptLen > 0) html += `<span>Prompt: ${(promptLen/1000).toFixed(1)}K chars</span>`;
  if (ev.thinking_level) html += `<span>Think: ${esc(ev.thinking_level)}</span>`;
  if (ev.cache_active) html += `<span>Cached</span>`;
  if (ev.error) html += `<span style="color:var(--red)">Error: ${esc(ev.error)}</span>`;
  html += `</div>`;
  const respPreview = ev.response_preview || '';
  if (respPreview) {
    html += `<details><summary>Response preview</summary><div class="tl-preview">${esc(respPreview.slice(0, 1000))}</div></details>`;
  }
  const promptPreview = ev.prompt_preview || '';
  if (promptPreview) {
    html += `<details><summary>Prompt preview</summary><div class="tl-preview">${esc(promptPreview.slice(0, 500))}</div></details>`;
  }
  html += `</div>`;
  return html;
}

function _stlToggleDetail(idx) {
  const detail = document.getElementById('stlDetail' + idx);
  const block = detail?.previousElementSibling;
  if (detail) {
    detail.classList.toggle('open');
    block?.classList.toggle('expanded');
  }
}

function renderShareTimeline() {
  const container = document.getElementById('timelineContent');
  if (!container) return;

  // If we have a call log from the DB, use it as the primary source
  let callLogEvents = [];
  if (CALL_LOG && CALL_LOG.length) {
    // Group call log entries by a pseudo-turn (executor calls increment turn)
    let turnNum = 0;
    for (const c of CALL_LOG) {
      const cType = c.agent_type || c.call_type || '';
      if (cType === 'executor' || cType.includes('main') || cType.includes('planner')) turnNum++;
      callLogEvents.push({
        ...c,
        type: c.agent_type || c.call_type || 'reasoning',
        duration: c.duration_ms || 0,
        turn: turnNum || 1,
      });
    }
  }

  // Prefer call log, then timeline data, then reconstruction from steps
  let events = [];
  if (callLogEvents.length) {
    events = callLogEvents;
  } else if (TIMELINE_DATA && TIMELINE_DATA.length) {
    events = TIMELINE_DATA;
  } else {
    let turnNum = 0;
    for (const g of stepGroups) {
      if (g.type === 'llm' && g.llm) {
        turnNum++;
        const dur = g.llm.call_duration_ms || 0;
        if (dur > 0) {
          const plan = g.llm.parsed?.plan && Array.isArray(g.llm.parsed.plan) ? g.llm.parsed.plan : [{ action: g.llm.parsed?.action }];
          events.push({
            type: 'reasoning', duration: dur, turn: turnNum, model: g.llm.model || '',
            stepStart: g.steps[0].step_num, actions: plan.map(p => p.action),
          });
        }
      }
    }
  }
  if (!events.length) {
    container.innerHTML = '<div class="empty-reasoning">No timing data available in this replay.</div>';
    return;
  }
  let html = '';
  let evIdx = 0;
  // Top-to-bottom for replay (ascending turn order)
  const turns = {};
  for (const ev of events) {
    const t = ev.turn || 0;
    if (!turns[t]) turns[t] = [];
    turns[t].push(ev);
  }
  for (const turn of Object.keys(turns).sort((a, b) => a - b)) {
    html += `<div class="timeline-turn-marker">Turn ${turn}</div>`;
    for (const ev of turns[turn]) {
      const h = Math.max(28, Math.min(120, ev.duration / 50));
      const dur = (ev.duration / 1000).toFixed(1) + 's';
      const label = _stlLabel(ev);
      const cssClass = _stlCssClass(ev);
      const hasDetail = ev.input_tokens || ev.response_preview || ev.prompt_preview || ev.error;
      let stepsHtml = '';
      if (ev.actions && ev.actions.length) {
        const stepParts = ev.actions.map((a, i) => {
          const stepNum = (ev.stepStart || 0) + i;
          const name = ACTION_NAMES[a] || `A${a}`;
          return `<span class="tl-step">${stepNum}:${name}</span>`;
        });
        stepsHtml = `<span class="tl-steps">${stepParts.join(' ')}</span>`;
      }
      const costStr = _stlFormatCost(ev.cost || 0);
      const costHtml = costStr ? `<span class="tl-cost" style="margin-left:6px;font-size:10px;">${costStr}</span>` : '';
      const arrowHtml = hasDetail ? '<span class="tl-expand-arrow">&#9654;</span>' : '';
      const clickAttr = hasDetail ? `onclick="_stlToggleDetail(${evIdx})" class="timeline-block ${cssClass} clickable"` : `class="timeline-block ${cssClass}"`;
      html += `<div ${clickAttr} style="height:${h}px">
        <span class="tl-label">${esc(label)}${stepsHtml}${costHtml}${arrowHtml}</span><span class="tl-dur">${dur}</span>
      </div>`;
      if (hasDetail) {
        html += _stlBuildDetail(ev, evIdx);
      }
      evIdx++;
    }
  }
  container.innerHTML = html;
}

// ── Header info ───────────────────────────────────────────────────────
(function() {
  // Format level info from last step
  const lastStep = STEPS[STEPS.length - 1];
  if (lastStep) {
    const li = document.getElementById('levelInfo');
    // Levels are tracked per-step in result_state; use session data
    if (SESSION.levels !== undefined) {
      li.textContent = `Level ${SESSION.levels}`;
    }
  }
  const sc = document.getElementById('stepCounterTop');
  sc.textContent = `${SESSION.steps || STEPS.length} steps`;

  // Compute session duration
  if (STEPS.length >= 2) {
    const first = STEPS[0].timestamp, last = STEPS[STEPS.length - 1].timestamp;
    if (first && last) {
      sc.textContent += ` | ${formatDuration(last - first)}`;
    }
  }
  if (SESSION.model) {
    sc.textContent += ` | ${SESSION.model}`;
  }
})();

// ── Settings tab ──────────────────────────────────────────────────────
(function buildSettings() {
  const firstLLMStep = STEPS.find(s => s.llm_response && typeof s.llm_response === 'object');
  const llm = firstLLMStep ? firstLLMStep.llm_response : {};
  const p = llm.parsed || {};

  const model = SESSION.model || llm.model || '\u2014';
  const thinkingLevel = llm.thinking_level || '\u2014';
  const toolsMode = llm.tools_active !== undefined ? (llm.tools_active ? 'On' : 'Off') : '\u2014';
  const hasPlan = p.plan && Array.isArray(p.plan) && p.plan.length > 1;
  const planningMode = hasPlan ? `On (${p.plan.length}-step)` : (p.plan ? 'On (1-step)' : '\u2014');
  const gameId = SESSION.game_id || '\u2014';
  const mode = SESSION.mode || '\u2014';
  const result = SESSION.result || '\u2014';
  const steps = SESSION.steps || STEPS.length;
  const totalCost = SESSION.total_cost != null ? `$${Number(SESSION.total_cost).toFixed(4)}` : '\u2014';

  let duration = '\u2014';
  if (STEPS.length >= 2) {
    const first = STEPS[0].timestamp, last = STEPS[STEPS.length - 1].timestamp;
    if (first && last) duration = formatDuration(last - first);
  }

  let created = '\u2014';
  if (SESSION.created_at) {
    const d = new Date(SESSION.created_at * 1000);
    created = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  }

  const resultClass = result === 'WIN' ? ' result-win' : (result === 'GAME_OVER' ? ' result-over' : '');

  const fields = [
    { label: 'Model', value: model },
    { label: 'Thinking Level', value: thinkingLevel },
    { label: 'Tools Mode', value: toolsMode },
    { label: 'Planning Mode', value: planningMode },
    { label: 'Game ID', value: gameId },
    { label: 'Mode', value: mode },
    { label: 'Result', value: result, cls: resultClass },
    { label: 'Steps', value: steps },
    { label: 'Total Cost', value: totalCost },
    { label: 'Duration', value: duration },
    { label: 'Created', value: created, full: true },
  ];

  let html = '<div class="settings-grid">';
  for (const f of fields) {
    html += `<div class="settings-field${f.full ? ' full-width' : ''}">
      <label>${f.label}</label>
      <div class="value${f.cls || ''}">${esc(String(f.value))}</div>
    </div>`;
  }
  html += '</div>';
  document.getElementById('settingsContent').innerHTML = html;
})();

// ── Graphics controls ─────────────────────────────────────────────────
document.getElementById('showChanges').addEventListener('change', (e) => {
  showDiffOverlay = e.target.checked;
  if (currentIdx >= 0) showStep(currentIdx);
});
document.getElementById('changeOpacity').addEventListener('input', (e) => {
  diffOpacity = parseInt(e.target.value) / 100;
  document.getElementById('changeOpacityVal').textContent = e.target.value + '%';
  if (showDiffOverlay && currentIdx >= 0) showStep(currentIdx);
});
document.getElementById('changeColor').addEventListener('input', (e) => {
  diffColor = e.target.value;
  if (showDiffOverlay && currentIdx >= 0) showStep(currentIdx);
});

// ── Rendering ─────────────────────────────────────────────────────────
function renderGrid(grid) {
  if (!grid || !grid.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  canvas.width = w * scale;
  canvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = COLORS[grid[y][x]] || '#000';
      ctx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
}

function renderGridWithChanges(grid, changeMap) {
  renderGrid(grid);
  if (!changeMap || !changeMap.changes || !changeMap.changes.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  // Parse hex color
  const r = parseInt(diffColor.slice(1,3), 16);
  const g = parseInt(diffColor.slice(3,5), 16);
  const b = parseInt(diffColor.slice(5,7), 16);
  ctx.fillStyle = `rgba(${r},${g},${b},${diffOpacity})`;
  for (const c of changeMap.changes) {
    ctx.fillRect(c.x * scale, c.y * scale, scale, scale);
  }
}

function renderToolCallsHtml(toolCalls) {
  if (!toolCalls || !toolCalls.length) return '';
  const items = toolCalls.map(tc => {
    const name = tc.name || (tc.function && tc.function.name) || '?';
    const args = tc.arguments || (tc.function && tc.function.arguments);
    const code = typeof args === 'object' ? (args.code || JSON.stringify(args, null, 1)) : (args || '');
    const output = tc.output || '';
    return `<div class="tool-call">` +
      `<span class="tool-name">${name}</span>` +
      (code ? `<div class="tool-input">${esc(code)}</div>` : '') +
      (output ? `<div class="tool-output">${esc(output)}</div>` : '') +
      `</div>`;
  }).join('');
  const label = toolCalls.length === 1 ? '1 tool call' : `${toolCalls.length} tool calls`;
  return `<details class="tool-calls-wrap"><summary>${label}</summary>${items}</details>`;
}

function renderTokenLine(usage, model) {
  if (!usage) return '';
  const inputTok = usage.input_tokens || usage.prompt_tokens || 0;
  const outputTok = usage.output_tokens || usage.completion_tokens || 0;
  const totalTok = inputTok + outputTok;
  if (!totalTok) return '';
  return `<div class="token-line">${inputTok.toLocaleString()} in + ${outputTok.toLocaleString()} out = ${totalTok.toLocaleString()} tok</div>`;
}

// ── Pre-compute reasoning blocks ──────────────────────────────────────
const reasoningIndices = [];
for (let i = 0; i < STEPS.length; i++) {
  if (STEPS[i].llm_response) reasoningIndices.push(i);
}

function nextReasoningIdx(fromIdx) {
  for (const ri of reasoningIndices) { if (ri > fromIdx) return ri; }
  return STEPS.length - 1;
}

function prevReasoningIdx(fromIdx) {
  for (let i = reasoningIndices.length - 1; i >= 0; i--) { if (reasoningIndices[i] < fromIdx) return reasoningIndices[i]; }
  return 0;
}

// ── Group steps into plan groups (same logic as main app) ────────────
const stepGroups = [];
{
  let currentGroup = null;
  let planCapacity = 0;
  for (const s of STEPS) {
    const hasLLM = s.llm_response && typeof s.llm_response === 'object' && s.llm_response.parsed;
    if (hasLLM) {
      const plan = s.llm_response.parsed.plan;
      const planSize = (plan && Array.isArray(plan)) ? plan.length : 1;
      currentGroup = { type: 'llm', steps: [s], llm: s.llm_response };
      planCapacity = planSize - 1;
      stepGroups.push(currentGroup);
    } else if (currentGroup && currentGroup.type === 'llm' && planCapacity > 0) {
      currentGroup.steps.push(s);
      planCapacity--;
    } else {
      stepGroups.push({ type: 'human', steps: [s], llm: null });
      currentGroup = null;
      planCapacity = 0;
    }
  }
}

const stepToGroup = {};
stepGroups.forEach((g, gi) => {
  g.steps.forEach(s => { stepToGroup[s.step_num] = gi; });
});

// ── Compute level progress per group ──────────────────────────────────
const groupLevels = [];
{
  let prevLevel = 0;
  for (let gi = 0; gi < stepGroups.length; gi++) {
    const g = stepGroups[gi];
    const lastStep = g.steps[g.steps.length - 1];
    const curLevel = lastStep.levels_completed || 0;
    groupLevels.push({ before: prevLevel, after: curLevel, levelUp: curLevel > prevLevel });
    prevLevel = curLevel;
  }
}

// buildReasoningGroupHTML is now in reasoning.js (loaded before this file)
/* --- REMOVED: duplicated buildReasoningGroupHTML, now in reasoning.js ---
function _OLD_buildReasoningGroupHTML(g, gi, options) {
  const showBranchBtn = options.showBranchBtn || false;
  const isRestored = options.isRestored || false;
  const isParent = options.isParent || false;
  const levelBefore = options.levelBefore || 0;
  const levelAfter = options.levelAfter || 0;
  const defaultModel = options.defaultModel || 'LLM';
  const isReplay = options.isReplay || false;
  const stepNums = g.steps.map(function(s) { return s.step_num; }).join(',');
  const levelChanged = levelAfter > levelBefore;
  const levelBadgeStyle = levelChanged ? 'background:#3fb95033;color:var(--green);' : 'background:var(--bg);color:var(--text-dim);';
  const levelBadge = '<span class="tools-badge" style="' + levelBadgeStyle + '">L' + levelAfter + '</span>';
  const tag = isRestored ? ' <span style="font-size:10px;color:var(--text-dim);">[restored]</span>'
    : isParent ? ' <span style="font-size:10px;color:var(--purple);">[parent]</span>' : '';
  const entryStyle = (isRestored || isParent) ? ' style="opacity:0.7;"' : '';

  // Cell changes: sum across all steps in group
  var cellChanges = 0;
  for (var si = 0; si < g.steps.length; si++) {
    if (g.steps[si].change_map && g.steps[si].change_map.change_count) cellChanges += g.steps[si].change_map.change_count;
  }

  if (g.type === 'llm' && g.llm && g.llm.parsed) {
    var llm = g.llm;
    var p = llm.parsed;
    var firstStep = g.steps[0].step_num;
    var lastStep = g.steps[g.steps.length - 1].step_num;
    var stepLabel = g.steps.length > 1 ? 'Steps ' + firstStep + '\u2013' + lastStep : 'Step ' + firstStep;
    var durationHtml = llm.call_duration_ms
      ? '<span style="font-size:10px;color:var(--dim);margin-left:6px;">' + (llm.call_duration_ms / 1000).toFixed(1) + 's</span>' : '';

    // Badges
    var toolsBadge = llm.tools_active ? '<span class="tools-badge">TOOLS</span>' : '';
    var thinkLevel = llm.thinking_level || '';
    var thinkBadge = (thinkLevel && thinkLevel !== 'off' && thinkLevel !== 'none')
      ? '<span class="tools-badge" style="background:#58a6ff22;color:var(--accent);">' + thinkLevel.toUpperCase() + '</span>' : '';
    var cacheBadge = llm.cache_active ? '<span class="tools-badge" style="background:#e3b34133;color:var(--yellow);">CACHED</span>' : '';
    var planSteps = (p.plan && Array.isArray(p.plan)) ? p.plan : [{ action: p.action, data: p.data || {} }];
    var planBadge = planSteps.length > 1 ? '<span class="tools-badge" style="background:#58a6ff33;color:var(--accent);">PLAN</span>' : '';

    // Tokens
    var tokensHtml = '';
    var inputTok = (llm.usage && (llm.usage.input_tokens || llm.usage.prompt_tokens)) || 0;
    var outputTok = (llm.usage && (llm.usage.output_tokens || llm.usage.completion_tokens)) || 0;
    var totalTok = inputTok + outputTok;
    if (totalTok) {
      var costStr = '';
      if (typeof TOKEN_PRICES !== 'undefined' && TOKEN_PRICES[llm.model || '']) {
        var prices = TOKEN_PRICES[llm.model || ''];
        var cost = (inputTok * prices[0] + outputTok * prices[1]) / 1000000;
        costStr = ' \u00b7 $' + cost.toFixed(4);
      }
      tokensHtml = '<div style="font-size:10px;color:var(--text-dim);margin-bottom:2px;">' + inputTok.toLocaleString() + ' in + ' + outputTok.toLocaleString() + ' out = ' + totalTok.toLocaleString() + ' tok' + costStr + '</div>';
    }

    var cellHtml = cellChanges > 0 ? '<div style="font-size:11px;color:var(--yellow);">' + cellChanges + ' cells changed</div>' : '';

    // Content
    var thinkHtml = llm.thinking
      ? '<details style="margin-top:4px;"><summary style="cursor:pointer;color:var(--text-dim);font-size:10px;">Thinking...</summary><div style="color:var(--text-dim);font-size:11px;margin-top:4px;white-space:pre-wrap;">' + esc(llm.thinking) + '</div></details>' : '';
    var analysisHtml = p.analysis
      ? '<details class="analysis-wrap"><summary>Analysis</summary><div class="analysis-content">' + esc(p.analysis) + '</div></details>' : '';
    var toolCallsHtml = renderToolCallsHtml(llm.tool_calls || p.tool_calls || []);

    var planHtml = planSteps.map(function(ps, i) {
      var aName = ACTION_NAMES[ps.action] || ('ACTION' + ps.action);
      var dataStr = (ps.data && ps.data.x !== undefined) ? ' (' + ps.data.x + ',' + ps.data.y + ')' : '';
      var done = !isReplay && i < g.steps.length;
      var cls = done ? 'plan-step done' : 'plan-step';
      var btnStyle = done ? ' style="background:var(--green);color:#000;border-color:var(--green);"' : '';
      return '<div class="' + cls + '" data-plan-idx="' + i + '">' + (i + 1) + '. <span class="action-btn"' + btnStyle + '>' + aName + '</span>' + dataStr + '</div>';
    }).join('');

    var branchBtn = showBranchBtn
      ? '<button class="branch-btn" onclick="branchFromStep(' + lastStep + ')" title="Branch from step ' + lastStep + '">&#8627; branch</button>' : '';

    return '<div class="reasoning-entry" data-group="' + gi + '" data-step-nums="' + stepNums + '"' + entryStyle + '>'
      + branchBtn
      + '<div class="step-label">' + stepLabel + ' \u2014 ' + (llm.model || defaultModel) + durationHtml + thinkBadge + toolsBadge + cacheBadge + planBadge + levelBadge + tag + '</div>'
      + tokensHtml + cellHtml
      + (p.observation ? '<div class="observation"><strong>Obs:</strong> ' + esc(p.observation) + '</div>' : '')
      + (p.reasoning ? '<div style="margin-top:4px;"><strong>Reasoning:</strong> ' + esc(p.reasoning) + '</div>' : '')
      + analysisHtml + toolCallsHtml
      + '<div class="plan-progress">' + planHtml + '</div>'
      + thinkHtml
      + '</div>';
  } else {
    // Human action
    var s = g.steps[0];
    var aName = ACTION_NAMES[s.action] || ('ACTION' + s.action);
    var coordStr = (s.data && s.data.x !== undefined) ? ' (' + s.data.x + ',' + s.data.y + ')' : '';
    var cellHtml2 = cellChanges > 0 ? ' | ' + cellChanges + ' cells changed' : '';
    var branchBtn2 = showBranchBtn
      ? '<button class="branch-btn" onclick="branchFromStep(' + s.step_num + ')" title="Branch from step ' + s.step_num + '">&#8627; branch</button>' : '';

    return '<div class="reasoning-entry human" data-group="' + gi + '" data-step-nums="' + stepNums + '"' + entryStyle + '>'
      + branchBtn2
      + '<div class="step-label" style="color:var(--yellow);">Step ' + s.step_num + ' \u2014 Human' + levelBadge + tag + '</div>'
      + '<div class="action-rec" style="color:var(--yellow);">\u2192 ' + aName + coordStr + cellHtml2 + '</div>'
      + '</div>';
  }
}
--- END REMOVED */

function buildAllReasoningEntries() {
  let html = '';
  let branchMarkerInserted = !BRANCH_AT_STEP;
  for (let gi = 0; gi < stepGroups.length; gi++) {
    const g = stepGroups[gi];

    if (!branchMarkerInserted && g.steps.some(s => !s.from_parent)) {
      branchMarkerInserted = true;
      html += `<div class="reasoning-entry" style="opacity:0.8;">
        <div class="step-label" style="color:var(--purple);">&#8627; Branched here (from parent session)</div>
      </div>`;
    }

    // Level-up marker
    if (gi > 0 && groupLevels[gi - 1].levelUp) {
      html += `<div class="level-marker">&#9733; Level ${groupLevels[gi - 1].after} completed!</div>`;
    }

    const isParent = g.steps[0].from_parent;
    html += buildReasoningGroupHTML(g, gi, {
      showBranchBtn: false,
      isRestored: false,
      isParent: !!isParent,
      levelBefore: groupLevels[gi].before,
      levelAfter: groupLevels[gi].after,
      defaultModel: SESSION.model || 'LLM',
      isReplay: true,
    });
  }
  // Final level-up
  if (stepGroups.length > 0 && groupLevels[stepGroups.length - 1].levelUp) {
    html += `<div class="level-marker">&#9733; Level ${groupLevels[stepGroups.length - 1].after} completed!</div>`;
  }
  return html;
}

// ── Step display ──────────────────────────────────────────────────────
function showStep(idx) {
  if (idx < 0 || idx >= STEPS.length) return;
  currentIdx = idx;
  const step = STEPS[idx];
  if (step.grid) {
    if (showDiffOverlay && step.change_map) {
      renderGridWithChanges(step.grid, step.change_map);
    } else {
      renderGrid(step.grid);
    }
  }
  scrubber.value = idx;
  stepCounter.textContent = `Step ${idx + 1} / ${STEPS.length}`;
  highlightCurrentStep(step.step_num);
}

function highlightCurrentStep(stepNum) {
  reasoningScroll.querySelectorAll('.reasoning-entry').forEach(e => e.classList.remove('current'));
  reasoningScroll.querySelectorAll('.plan-step .action-btn').forEach(btn => {
    btn.style.background = ''; btn.style.color = ''; btn.style.borderColor = '';
  });

  const gi = stepToGroup[stepNum];
  if (gi === undefined) return;
  const g = stepGroups[gi];
  const entry = reasoningScroll.querySelector(`[data-group="${gi}"]`);
  if (!entry) return;

  entry.classList.add('current');
  entry.scrollIntoView({ behavior: 'smooth', block: 'center' });

  const stepIdx = g.steps.findIndex(s => s.step_num === stepNum);
  if (stepIdx >= 0) {
    const planBtns = entry.querySelectorAll('.plan-step .action-btn');
    for (let i = 0; i <= stepIdx && i < planBtns.length; i++) {
      planBtns[i].style.background = 'var(--green)';
      planBtns[i].style.color = '#000';
      planBtns[i].style.borderColor = 'var(--green)';
    }
  }
}

// Render all reasoning entries once on load
reasoningScroll.innerHTML = buildAllReasoningEntries() || '<div class="empty-reasoning">No reasoning data</div>';

// ── Playback ──────────────────────────────────────────────────────────
const STEP_DELAY = 80;
const REASONING_PAUSE = 1500;

function stopAutoplay() {
  if (autoplayTimer) { clearTimeout(autoplayTimer); autoplayTimer = null; }
  isAutoplaying = false;
  btnAutoplay.classList.remove('active');
  btnAutoplay.textContent = 'Auto';
}

function playToNextReasoning() {
  stopAutoplay();
  if (currentIdx >= STEPS.length - 1) return;
  const target = nextReasoningIdx(currentIdx);
  let i = currentIdx + 1;
  function tick() {
    if (i > target || i >= STEPS.length) return;
    showStep(i);
    if (i >= target) return;
    i++;
    autoplayTimer = setTimeout(tick, STEP_DELAY);
  }
  tick();
}

function playToPrevReasoning() {
  stopAutoplay();
  if (currentIdx <= 0) return;
  showStep(prevReasoningIdx(currentIdx));
}

function toggleAutoplay() {
  if (isAutoplaying) { stopAutoplay(); return; }
  isAutoplaying = true;
  btnAutoplay.classList.add('active');
  btnAutoplay.textContent = 'Stop';
  autoplayLoop();
}

function autoplayLoop() {
  if (!isAutoplaying || currentIdx >= STEPS.length - 1) { stopAutoplay(); return; }
  const target = nextReasoningIdx(currentIdx);
  let i = currentIdx + 1;
  function tick() {
    if (!isAutoplaying) return;
    if (i > target || i >= STEPS.length) {
      if (i < STEPS.length) autoplayTimer = setTimeout(autoplayLoop, REASONING_PAUSE);
      else stopAutoplay();
      return;
    }
    showStep(i);
    if (i >= target) {
      if (i < STEPS.length - 1) autoplayTimer = setTimeout(autoplayLoop, REASONING_PAUSE);
      else stopAutoplay();
      return;
    }
    i++;
    autoplayTimer = setTimeout(tick, STEP_DELAY);
  }
  tick();
}

// ── Controls ──────────────────────────────────────────────────────────
btnPlay.addEventListener('click', playToNextReasoning);
btnPrev.addEventListener('click', playToPrevReasoning);
btnNext.addEventListener('click', () => { stopAutoplay(); if (currentIdx < STEPS.length - 1) showStep(nextReasoningIdx(currentIdx)); });
btnAutoplay.addEventListener('click', toggleAutoplay);
scrubber.addEventListener('input', () => { stopAutoplay(); showStep(parseInt(scrubber.value)); });

document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); playToNextReasoning(); }
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); playToPrevReasoning(); }
  else if (e.key === ' ') { e.preventDefault(); toggleAutoplay(); }
});

// ── Init ──────────────────────────────────────────────────────────────
if (STEPS.length > 0) {
  scrubber.max = STEPS.length - 1;
  showStep(0);
}

/* ── Theme toggle ──────────────────────────────────────────────── */
(function(){
  const saved = localStorage.getItem('arc-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeBtn();
})();
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'light' ? 'dark' : 'light';
  if (next === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('arc-theme', next);
  updateThemeBtn();
}
function updateThemeBtn() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  btn.textContent = isLight ? '\u263C' : '\u263E';
}
