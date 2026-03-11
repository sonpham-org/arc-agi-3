// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Universal reasoning/timeline rendering for ARC-AGI-3 web UI. Provides
//   agentColor() palette assignment, scrollReasoningToBottom(), renderTimeline() for
//   agent spawn tree views, and shared rendering helpers used by llm.js, session.js,
//   share-page.js, observatory.js, and obs-page.js. No scaffolding-specific code —
//   uses agent_type from DB/events directly. Must load before all consumer scripts.
//   Modified in Phase 1 to extract formatting to utils/formatting.js.
// SRP/DRY check: Pass — agent color palette and timeline rendering consolidated here
// ═══════════════════════════════════════════════════════════════════════════
// reasoning.js — Universal reasoning/timeline rendering
//
// No scaffolding-specific code. Uses agent_type from DB/events directly.
// Loaded before llm.js, session.js, share-page.js, observatory.js.
// ═══════════════════════════════════════════════════════════════════════════

// ── Color palette — auto-assigned to agent types ──────────────────────────

const _AGENT_PALETTE = [
  '#58a6ff', // blue
  '#3fb950', // green
  '#bc8cff', // purple
  '#d29922', // amber
  '#39c5cf', // cyan
  '#f97316', // orange
  '#ef4444', // red
  '#ec4899', // pink
  '#8b5cf6', // violet
  '#14b8a6', // teal
];
const _AGENT_COLOR_MAP = {};
let _nextColorIdx = 0;

/**
 * Get a stable color for an agent_type. Auto-assigned from palette.
 * Same agent_type always gets the same color within a session.
 */
function agentColor(agentType) {
  if (!agentType) return '#6b7280';
  const key = agentType.toLowerCase();
  if (!_AGENT_COLOR_MAP[key]) {
    _AGENT_COLOR_MAP[key] = _AGENT_PALETTE[_nextColorIdx % _AGENT_PALETTE.length];
    _nextColorIdx++;
  }
  return _AGENT_COLOR_MAP[key];
}

/**
 * Convert agent_type to a display label.
 * snake_case → Title Case, e.g. "world_model" → "World Model"
 */
function agentLabel(agentType, model) {
  if (!agentType) return model || 'LLM';
  const pretty = agentType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return model ? `${pretty} (${model})` : pretty;
}

/**
 * Create an agent badge HTML span with auto-assigned color.
 */
function agentBadge(agentType) {
  if (!agentType) return '<span style="color:#666">--</span>';
  const c = agentColor(agentType);
  const label = agentType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return `<span class="agent-badge" style="background:${c}">${label}</span>`;
}

// ── Shared action name lookup ─────────────────────────────────────────────

const _R_ACTION_NAMES = {
  1: 'UP', 2: 'DOWN', 3: 'LEFT', 4: 'RIGHT',
  5: 'ACT5', 6: 'CLICK', 7: 'ACT7',
  'ACTION1': 'UP', 'ACTION2': 'DOWN', 'ACTION3': 'LEFT', 'ACTION4': 'RIGHT',
  'ACTION5': 'ACT5', 'ACTION6': 'CLICK', 'ACTION7': 'ACT7', 'RESET': 'RESET',
};

function actionName(action) {
  return _R_ACTION_NAMES[action] || (typeof ACTION_NAMES !== 'undefined' && ACTION_NAMES[action]) || ('ACTION' + action);
}

// ── Universal reasoning group renderer ────────────────────────────────────

/**
 * Render a reasoning group (LLM call + its plan followers, or human actions).
 *
 * @param {object} g - Group: { type: 'llm'|'human', steps: [...], llm: {...}|null }
 * @param {number} gi - Group index
 * @param {object} options - { showBranchBtn, isRestored, isParent, levelBefore, levelAfter, defaultModel, isReplay }
 * @returns {string} HTML string
 */
function buildReasoningGroupHTML(g, gi, options) {
  const showBranchBtn = options.showBranchBtn || false;
  const isRestored = options.isRestored || false;
  const isParent = options.isParent || false;
  const levelBefore = options.levelBefore || 0;
  const levelAfter = options.levelAfter || 0;
  const defaultModel = options.defaultModel || 'LLM';
  const isReplay = options.isReplay || false;

  const stepNums = g.steps.map(s => s.step_num).join(',');
  const levelChanged = levelAfter > levelBefore;
  const levelBadgeStyle = levelChanged
    ? 'background:#3fb95033;color:var(--green);'
    : 'background:var(--bg);color:var(--text-dim);';
  const levelBadge = `<span class="tools-badge" style="${levelBadgeStyle}">L${levelAfter}</span>`;
  const tag = isRestored ? ' <span style="font-size:10px;color:var(--text-dim);">[restored]</span>'
    : isParent ? ' <span style="font-size:10px;color:var(--purple);">[parent]</span>' : '';
  const entryStyle = (isRestored || isParent) ? ' style="opacity:0.7;"' : '';

  if (g.type === 'llm' && g.llm && g.llm.parsed) {
    const llm = g.llm;
    const p = llm.parsed;
    const firstStep = g.steps[0].step_num;
    const lastStep = g.steps[g.steps.length - 1].step_num;
    const stepLabel = g.steps.length > 1 ? `Steps ${firstStep}\u2013${lastStep}` : `Step ${firstStep}`;
    const durationHtml = llm.call_duration_ms
      ? `<span style="font-size:10px;color:var(--dim);margin-left:6px;">${(llm.call_duration_ms / 1000).toFixed(1)}s</span>` : '';

    // Agent type badge (universal — whatever the scaffolding set)
    const aType = llm.agent_type || llm.call_type || 'executor';
    const aColor = agentColor(aType);
    const agentBadgeHtml = `<span class="tools-badge" style="background:${aColor}22;color:${aColor};">${agentLabel(aType)}</span>`;

    const modelLabel = llm.model || defaultModel;

    // Token info
    const inTok = llm.input_tokens || 0;
    const outTok = llm.output_tokens || 0;
    const tokHtml = (inTok + outTok) > 0
      ? `<span style="font-size:10px;color:var(--text-dim);margin-left:4px;">${inTok + outTok} tok</span>` : '';

    // Plan steps display
    const planSteps = (p.plan && Array.isArray(p.plan)) ? p.plan : [{ action: p.action, data: p.data || {} }];
    const planHtml = planSteps.map((ps, i) => {
      const aName = actionName(ps.action);
      const dataStr = (ps.data && ps.data.x !== undefined) ? ` (${ps.data.x},${ps.data.y})` : '';
      const done = !isReplay && i < g.steps.length;
      const cls = done ? 'plan-step done' : 'plan-step';
      const btnStyle = done ? ' style="background:var(--green);color:#000;border-color:var(--green);"' : '';
      return `<div class="${cls}" data-plan-idx="${i}">${i + 1}. <span class="action-btn"${btnStyle}>${aName}</span>${dataStr}</div>`;
    }).join('');

    // Sub-calls (REPL iterations, monitor checks, etc.) — rendered generically from sub_calls array
    let subCallsHtml = '';
    const subCalls = llm.sub_calls || llm.planner_log || (llm.three_system && llm.three_system.planner_log) || [];
    if (subCalls.length) {
      subCallsHtml = '<details style="margin-top:6px;"><summary style="cursor:pointer;font-size:10px;color:var(--text-dim);">'
        + `Sub-calls (${subCalls.length})</summary><div style="margin-top:4px;">`;
      for (let ci = 0; ci < subCalls.length; ci++) {
        const sc = subCalls[ci];
        const scType = sc.type || sc.agent_type || 'call';
        const scColor = agentColor(scType);
        const dur = sc.duration_ms ? ` (${(sc.duration_ms / 1000).toFixed(1)}s)` : '';
        subCallsHtml += `<div style="border-left:2px solid ${scColor};padding-left:8px;margin:4px 0;font-size:10px;">`;
        subCallsHtml += `<strong style="color:${scColor};">Call ${ci + 1}: ${scType}</strong>${dur}`;
        if (sc.raw) {
          subCallsHtml += `<details style="margin-top:2px;"><summary style="cursor:pointer;color:var(--text-dim);font-size:10px;">Response (${sc.raw.length} chars)</summary>`;
          subCallsHtml += `<div style="color:var(--text-dim);font-size:10px;margin-top:4px;white-space:pre-wrap;max-height:400px;overflow:auto;">${escapeHtml(sc.raw)}</div></details>`;
        }
        subCallsHtml += '</div>';
      }
      subCallsHtml += '</div></details>';
    }

    // Agent sub-reports (for multi-agent scaffoldings)
    let reportsHtml = '';
    const reports = llm.agent_reports || (llm.agent_spawn && llm.agent_spawn.subagent_summaries) || [];
    if (reports.length) {
      reportsHtml = `<details style="margin-top:4px;"><summary style="cursor:pointer;font-size:10px;color:var(--text-dim);">Agent Reports (${reports.length})</summary><div style="margin-top:4px;">`;
      for (const r of reports) {
        const rColor = agentColor(r.type || r.agent_type || 'agent');
        reportsHtml += `<div style="color:${rColor};font-size:10px;">[${r.type || r.agent_type || 'agent'}] ${r.steps || 0} steps \u2014 ${escapeHtml((r.summary || '').substring(0, 150))}</div>`;
      }
      reportsHtml += '</div></details>';
    }

    const branchBtn = showBranchBtn
      ? `<button class="branch-btn" onclick="branchFromStep(${lastStep})" title="Branch from step ${lastStep}">&#8627; branch</button>` : '';

    return `<div class="reasoning-entry" data-group="${gi}" data-step-nums="${stepNums}"${entryStyle}>`
      + branchBtn
      + `<div class="step-label">${stepLabel} \u2014 ${modelLabel}${durationHtml} ${agentBadgeHtml}${tokHtml} ${levelBadge}${tag}</div>`
      + (p.observation ? `<div class="observation"><strong>Obs:</strong> ${escapeHtml(p.observation)}</div>` : '')
      + (p.reasoning ? `<div style="margin-top:4px;"><strong>Reasoning:</strong> ${escapeHtml(p.reasoning)}</div>` : '')
      + `<div class="plan-progress">${planHtml}</div>`
      + subCallsHtml
      + reportsHtml
      + '</div>';

  } else if (g.type === 'human') {
    // Human / manual action
    const s = g.steps[0];
    const aName = actionName(s.action);
    const coordStr = (s.data && s.data.x !== undefined) ? ` (${s.data.x},${s.data.y})` : '';
    const branchBtn = showBranchBtn
      ? `<button class="branch-btn" onclick="branchFromStep(${s.step_num})" title="Branch from step ${s.step_num}">&#8627; branch</button>` : '';

    return `<div class="reasoning-entry human" data-group="${gi}" data-step-nums="${stepNums}"${entryStyle}>`
      + branchBtn
      + `<div class="step-label" style="color:var(--yellow);">Step ${s.step_num} \u2014 Human ${levelBadge}${tag}</div>`
      + `<div class="action-rec" style="color:var(--yellow);">\u2192 ${aName}${coordStr}</div>`
      + '</div>';
  }
  return '';
}
