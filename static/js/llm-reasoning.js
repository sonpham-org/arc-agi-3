// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: Reasoning log management and UI (Phase 12 extraction)
// Extracted from llm.js to isolate log copying and scroll management
// SRP: Reasoning panel state, log formatting, copy-to-clipboard operations

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
