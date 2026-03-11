// Author: Cascade, using Claude Opus 4.6 Thinking
// Date: 2026-03-10 21:08
// PURPOSE: Client-side scaffolding logic for ARC-AGI-3 web UI. Handles:
//   - Model discovery (cloud providers via server API + LM Studio via direct browser fetch)
//   - LLM call routing (Puter.js, Gemini, Anthropic, OpenAI-compat, LM Studio, Cloudflare)
//   - RLM (Reflective Language Model) scaffolding with REPL code execution via Pyodide
//   - Prompt building, context compaction, and multi-turn conversation management
//   - All scaffolding iteration loops run client-side per CLAUDE.md architecture
// Integration points: /api/llm/models (server model registry), localStorage (BYOK keys),
//   Pyodide (in-browser Python REPL), LM Studio localhost:1234, Puter.js SDK
// Dependencies: ui.js (DOM helpers), index.html (DOM structure), server.py (model registry API)
// SRP/DRY check: Pass — LLM routing consolidated in callLLM/_callLLMInner; model population
//   shared via _populateSubModelSelect; LMSTUDIO_CAPABILITIES mirrors models.py (intentional
//   client/server split documented in CLAUDE.md)

// ═══════════════════════════════════════════════════════════════════════════
// API MODE (Local vs Official)
// ═══════════════════════════════════════════════════════════════════════════

function onApiModeChange(mode) {
  if (mode === 'official') {
    const ok = confirm(
      'This will switch to the official ARC-AGI-3 API at three.arcprize.org.\n\n' +
      'Your current game will be reset. Results will count toward your leaderboard score.\n\n' +
      'Continue?'
    );
    if (!ok) {
      document.querySelector('input[name="apiMode"][value="local"]').checked = true;
      return;
    }
    document.getElementById('apiWarning').style.display = 'block';
    document.getElementById('apiKeySection').style.display = 'block';
  } else {
    document.getElementById('apiWarning').style.display = 'none';
    document.getElementById('apiKeySection').style.display = 'none';
  }
  apiMode = mode;
  fetchJSON('/api/config/mode', { mode, client_id: clientId });
}

async function saveArcApiKey() {
  const key = document.getElementById('arcApiKey').value.trim();
  if (!key) { alert('Please enter an API key'); return; }
  await fetchJSON('/api/config/apikey', { api_key: key, client_id: clientId });
  alert('API key saved for this session.');
}

// ═══════════════════════════════════════════════════════════════════════════
// MODELS LIST
// ═══════════════════════════════════════════════════════════════════════════

function _populateSubModelSelect(sel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, savedVal) {
  for (const prov of providerOrder) {
    const models = groups[prov];
    if (!models?.length) continue;
    const grp = document.createElement('optgroup');
    grp.label = providerLabels[prov] || prov;
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.name;
      opt.textContent = `${m.name} — ${m.price}`;
      grp.appendChild(opt);
    }
    sel.appendChild(grp);
  }
  for (const prov of byokProviderOrder) {
    const models = byokGroups[prov];
    if (!models?.length) continue;
    const grp = document.createElement('optgroup');
    grp.label = `${prov} (BYOK)`;
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.name;
      opt.textContent = `${m.name} — ${m.price}`;
      grp.appendChild(opt);
    }
    sel.appendChild(grp);
  }
  if (savedVal && [...sel.options].some(o => o.value === savedVal)) sel.value = savedVal;
}

// Known LM Studio capability overrides keyed on api_model ID.
// Mirrors LMSTUDIO_CAPABILITIES in models.py — update both together.
const LMSTUDIO_CAPABILITIES = {
  'zai-org/glm-4.7-flash':  { reasoning: true,  image: false },
  'zai-org/glm-4.6v-flash': { reasoning: true,  image: true  },
  'qwen/qwen3.5-35b-a3b':   { reasoning: true,  image: true  },
  'qwen/qwen3.5-9b':        { reasoning: true,  image: false },
};

async function loadModels() {
  const data = await fetchJSON('/api/llm/models');
  modelsData = data.models || [];

  // If the server already returned LM Studio models (staging mode server-side discovery),
  // set a dummy API key so they pass the key gate in _callLLMInner. LM Studio is a local
  // program — no real key needed — but the key gate expects something truthy.
  if (modelsData.some(m => m.provider === 'lmstudio')) {
    localStorage.setItem('byok_key_lmstudio', 'local-no-key-needed');
  }

  // ── LM Studio client-side discovery (production path) ──
  // In production (Railway), the server can't reach user's localhost:1234, so the browser
  // fetches it directly. In staging, the server already discovered LM Studio models above
  // via /api/llm/models — the dedup set below prevents doubles.
  // IMPORTANT: LM Studio does NOT always send CORS headers. If CORS is disabled, this
  // fetch fails silently and models come from server-side discovery only (staging mode).
  // In production, user MUST enable CORS in LM Studio settings for discovery to work.
  // See docs/lmstudio-integration.md "CORS pitfall" for details.
  try {
    const lmsBaseUrl = (localStorage.getItem('byok_lmstudio_base_url') || 'http://localhost:1234').replace(/\/$/, '');
    const lmsResp = await fetch(`${lmsBaseUrl}/v1/models`, { signal: AbortSignal.timeout(1500) });
    if (lmsResp.ok) {
      const lmsData = await lmsResp.json();
      // Dedup: skip models the server already returned (staging mode server-side discovery)
      const existingLms = new Set(modelsData.filter(m => m.provider === 'lmstudio').map(m => m.api_model));
      for (const m of (lmsData.data || [])) {
        const mid = m.id || '';
        // Skip empty IDs, embedding models, and duplicates from server discovery
        if (!mid || mid.toLowerCase().includes('embedding') || existingLms.has(mid)) continue;
        // Look up known capabilities; unknown models default to text-only
        const caps = LMSTUDIO_CAPABILITIES[mid] || { reasoning: false, image: false };
        modelsData.push({
          name: mid, api_model: mid, provider: 'lmstudio',
          price: 'Free (local)',
          // Context window set to 8192 — LM Studio default is 3900 which silently truncates.
          // See docs/lmstudio-integration.md pitfall #3 for details.
          context_window: 8192,
          capabilities: { ...caps, tools: false },
          available: true,
        });
      }
      // Client-side discovery found models — set dummy key for the key gate
      if (modelsData.some(m => m.provider === 'lmstudio')) {
        localStorage.setItem('byok_key_lmstudio', 'local-no-key-needed');
      }
    }
  } catch (e) {
    // LM Studio not running, unreachable, or CORS blocked — silently skip.
    // In production (HTTPS → HTTP localhost), CORS must be enabled in LM Studio settings.
    if (e.name !== 'AbortError') console.warn('[LM Studio discovery] client-side fetch failed:', e.message);
  }

  // Add Puter.js models to modelsData (before grouping)
  if (FEATURES.puter_js) {
    // Only add if not already present
    const puterNames = new Set(modelsData.filter(m => m.provider === 'puter').map(m => m.name));
    for (const m of ['gpt-4o-mini', 'gpt-4o', 'claude-3.5-sonnet', 'mistral-large-latest']) {
      if (!puterNames.has(m)) {
        modelsData.push({ name: m, provider: 'puter', price: 'Free', context_window: 128000, capabilities: { image: false, reasoning: false, tools: false }, available: true });
      }
    }
  }

  // Group models by provider (shared by all selectors)
  const groups = {};
  for (const m of modelsData) {
    if (!m.available) continue;
    const key = m.provider.charAt(0).toUpperCase() + m.provider.slice(1);
    (groups[key] ??= []).push(m);
  }
  const providerOrder = ['Local', 'Lmstudio', 'Ollama', 'Copilot', 'Gemini', 'Anthropic', 'Cloudflare', 'Groq', 'Mistral', 'Huggingface'];
  const providerLabels = { Local: 'Local Models (free)', Lmstudio: 'LM Studio (free, local)', Puter: 'Puter.js (free)' };
  // Pin qwen3.5-35b to top of LM Studio group
  if (groups['Lmstudio']) {
    groups['Lmstudio'].sort((a, b) => {
      const pin = m => (m.api_model || m.name || '').includes('qwen3.5-35b') ? 0 : 1;
      return pin(a) - pin(b);
    });
  }

  const unavail = modelsData.filter(m => !m.available);
  const byokGroups = {};
  for (const m of unavail) {
    const key = m.provider.charAt(0).toUpperCase() + m.provider.slice(1);
    (byokGroups[key] ??= []).push(m);
  }
  const byokProviderOrder = ['Gemini', 'Anthropic', 'Cloudflare', 'Groq', 'Mistral', 'Huggingface'];

  // ── Populate main reasoning model selector ──
  const sel = document.getElementById('modelSelect');
  if (sel) {
  sel.innerHTML = '';

  // Default blank option — no model pre-selected
  const defaultOpt = document.createElement('option');
  defaultOpt.value = ''; defaultOpt.textContent = 'Select a model...';
  sel.appendChild(defaultOpt);

  for (const prov of providerOrder) {
    const models = groups[prov];
    if (!models?.length) continue;
    const grp = document.createElement('optgroup');
    grp.label = providerLabels[prov] || prov;
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.name;
      const caps = [];
      if (m.capabilities?.image) caps.push('IMG');
      if (m.capabilities?.reasoning) caps.push('RSN');
      if (m.capabilities?.tools) caps.push('TLS');
      const capStr = caps.length ? ` [${caps.join(',')}]` : '';
      opt.textContent = `${m.name} — ${m.price}${capStr}`;
      grp.appendChild(opt);
    }
    sel.appendChild(grp);
  }

  for (const prov of byokProviderOrder) {
    const models = byokGroups[prov];
    if (!models?.length) continue;
    const grp = document.createElement('optgroup');
    grp.label = `${prov} (BYOK)`;
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.name;
      const caps = [];
      if (m.capabilities?.image) caps.push('IMG');
      if (m.capabilities?.reasoning) caps.push('RSN');
      if (m.capabilities?.tools) caps.push('TLS');
      const capStr = caps.length ? ` [${caps.join(',')}]` : '';
      opt.textContent = `${m.name} — ${m.price}${capStr}`;
      grp.appendChild(opt);
    }
    sel.appendChild(grp);
  }

  if (!sel.options.length) sel.innerHTML = '<option value="">No models</option>';
  } // end main select block

  // Populate compact model selector — keep default options, add all models
  const csel = document.getElementById('compactModelSelectTop');
  if (!csel) { /* compact select not in current scaffolding */ } else {
  const savedVal = csel.value;
  // Remove all optgroups (keep the static <option>s)
  csel.querySelectorAll('optgroup').forEach(g => g.remove());
  // Add available models grouped by provider
  _populateSubModelSelect(csel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, savedVal);
  } // end compact select block

  // Populate interrupt model selector — same pattern
  const isel = document.getElementById('interruptModelSelect');
  if (!isel) { /* interrupt select not in current scaffolding */ } else {
  const iSavedVal = isel.value;
  isel.querySelectorAll('optgroup').forEach(g => g.remove());
  _populateSubModelSelect(isel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, iSavedVal);
  } // end interrupt select block

  // Populate RLM model selects if they exist
  for (const rlmSelId of ['sf_rlm_modelSelect', 'sf_rlm_subModelSelect']) {
    const rlmSel = document.getElementById(rlmSelId);
    if (!rlmSel) continue;
    const rlmSaved = rlmSel.value;
    rlmSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(rlmSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, rlmSaved);
  }
  // Restore RLM model selections from saved settings
  try {
    const rlmRaw = localStorage.getItem('arc_scaffolding_rlm');
    if (rlmRaw) {
      const rlmS = JSON.parse(rlmRaw);
      const rlmMap = { sf_rlm_modelSelect: rlmS.model, sf_rlm_subModelSelect: rlmS.sub_model };
      for (const [id, val] of Object.entries(rlmMap)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch {}

  // Populate Three-System model selects if they exist
  for (const tsSelId of ['sf_ts_plannerModelSelect', 'sf_ts_monitorModelSelect', 'sf_ts_wmModelSelect']) {
    const tsSel = document.getElementById(tsSelId);
    if (!tsSel) continue;
    const tsSaved = tsSel.value;
    tsSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(tsSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, tsSaved);
  }
  // Restore Three-System model selections from saved settings
  try {
    const tsRaw = localStorage.getItem('arc_scaffolding_three_system');
    if (tsRaw) {
      const tsS = JSON.parse(tsRaw);
      const tsMap = {
        sf_ts_plannerModelSelect: tsS.planner_model,
        sf_ts_monitorModelSelect: tsS.monitor_model,
        sf_ts_wmModelSelect: tsS.wm_model,
      };
      for (const [id, val] of Object.entries(tsMap)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch {}

  // Populate Two-System model selects if they exist
  for (const tsSelId of ['sf_2s_plannerModelSelect', 'sf_2s_monitorModelSelect']) {
    const tsSel = document.getElementById(tsSelId);
    if (!tsSel) continue;
    const tsSaved = tsSel.value;
    tsSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(tsSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, tsSaved);
  }
  // Restore Two-System model selections from saved settings
  try {
    const ts2Raw = localStorage.getItem('arc_scaffolding_two_system');
    if (ts2Raw) {
      const ts2S = JSON.parse(ts2Raw);
      const ts2Map = {
        sf_2s_plannerModelSelect: ts2S.planner_model,
        sf_2s_monitorModelSelect: ts2S.monitor_model,
      };
      for (const [id, val] of Object.entries(ts2Map)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch {}

  // Populate Agent Spawn model selects if they exist
  for (const asSelId of ['sf_as_orchestratorModelSelect', 'sf_as_subagentModelSelect']) {
    const asSel = document.getElementById(asSelId);
    if (!asSel) continue;
    const asSaved = asSel.value;
    asSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(asSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, asSaved);
  }
  // Restore Agent Spawn model selections from saved settings
  try {
    const asRaw = localStorage.getItem('arc_scaffolding_agent_spawn');
    if (asRaw) {
      const asS = JSON.parse(asRaw);
      const asMap = {
        sf_as_orchestratorModelSelect: asS.orchestrator_model,
        sf_as_subagentModelSelect: asS.subagent_model,
      };
      for (const [id, val] of Object.entries(asMap)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch {}

  updateModelCaps();
  updateAllByokKeys();
}

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE PROMPT BUILDING (for Puter.js / BYOK — online mode)
// ═══════════════════════════════════════════════════════════════════════════

// ── Prompt templates loaded from server (prompts/*.txt) ──

function getPrompt(key) {
  const [section, name] = key.split('.');
  return localStorage.getItem('arc_prompt.' + key)
      || window.PROMPTS[section][name];
}

const ARC_DESCRIPTION = getPrompt('shared.arc_description');
const COLOR_PALETTE = getPrompt('shared.color_palette');

function compressRowJS(row) {
  if (!row || !row.length) return '';
  const parts = [];
  let cur = row[0], count = 1;
  for (let i = 1; i < row.length; i++) {
    if (row[i] === cur) { count++; }
    else { parts.push(count > 1 ? `${cur}x${count}` : `${cur}`); cur = row[i]; count = 1; }
  }
  parts.push(count > 1 ? `${cur}x${count}` : `${cur}`);
  return parts.join(' ');
}

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE RLM SCAFFOLDING
// ═══════════════════════════════════════════════════════════════════════════

const _RLM_SYSTEM_PROMPT_TEMPLATE = getPrompt('rlm.system_prompt');

function buildRlmSystemPrompt(planHorizon) {
  const planInstructions = `For multi-step plans (up to ${planHorizon} steps ahead):\n` +
    `  FINAL({"plan": [{"action": <int>, "observation": "..."}, ...], "reasoning": "..."})\n` +
    `Output a plan of 1-${planHorizon} actions. If the next moves are obvious, include them all. If unsure, output a plan of just 1 action.\n\n`;
  return _RLM_SYSTEM_PROMPT_TEMPLATE
    .replace('{plan_instructions}', planInstructions)
    .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}

const _RLM_USER_FIRST_TEMPLATE = getPrompt('rlm.user_first');
const _RLM_USER_CONTINUE_TEMPLATE = getPrompt('rlm.user_continue');

function _rlmPlanInstruction(planHorizon) {
  return `Output a plan of 1-${planHorizon} actions.`;
}
function buildRlmUserFirst(planHorizon) {
  return _RLM_USER_FIRST_TEMPLATE.replace('{plan_instruction}', _rlmPlanInstruction(planHorizon));
}
function buildRlmUserContinue(planHorizon) {
  return _RLM_USER_CONTINUE_TEMPLATE.replace('{plan_instruction}', _rlmPlanInstruction(planHorizon));
}

function _rlmFindFinal(text) {
  if (typeof text !== 'string') return null;
  // Strip code blocks before checking for FINAL
  const stripped = text.replace(/```repl\s*\n[\s\S]*?\n```/g, '');
  // Check for FINAL(...)
  const finalMatch = stripped.match(/^\s*FINAL\((.+)\)\s*$/ms);
  if (finalMatch) return finalMatch[1].trim();
  return null;
}

function _extractJsonFromText(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  // Balanced-brace JSON extraction (same logic as parseClientLLMResponse)
  const cleaned = text.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan || parsed.actions || parsed.command) return parsed;
        } catch {}
        break;
      }}
    }
  }
  return null;
}

function _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon) {
  let parsed = null;
  if (finalAnswer) {
    parsed = _extractJsonFromText(finalAnswer);
    if (!parsed) {
      try { parsed = JSON.parse(finalAnswer); } catch {}
    }
  }
  // Fallback: try to extract from last response
  if (!parsed && iterationsLog.length) {
    const lastResp = iterationsLog[iterationsLog.length - 1].response || '';
    parsed = _extractJsonFromText(lastResp);
  }
  if (!parsed) return null;
  // Normalize: "actions" array → "plan"
  if (parsed.actions && Array.isArray(parsed.actions) && !parsed.plan) {
    parsed.plan = parsed.actions;
    delete parsed.actions;
  }
  // Always wrap single action as 1-element plan
  if (parsed.action !== undefined && !parsed.plan) {
    parsed.plan = [{ action: parsed.action, data: parsed.data || {} }];
  }
  // Validate plan entries
  if (parsed.plan && Array.isArray(parsed.plan)) {
    const cleanPlan = [];
    for (const step of parsed.plan.slice(0, planHorizon)) {
      if (typeof step === 'object' && step !== null && step.action !== undefined) {
        cleanPlan.push({ action: parseInt(step.action), data: step.data || {}, observation: step.observation || '' });
      } else if (typeof step === 'number') {
        cleanPlan.push({ action: parseInt(step), data: {} });
      }
    }
    if (cleanPlan.length) parsed.plan = cleanPlan;
  }
  return parsed;
}

async function callLLM(messages, model, { maxTokens = 16384, thinkingLevel = 'off', onChunk = null } = {}) {
  const MAX_RETRIES = 10;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await _callLLMInner(messages, model, { maxTokens, thinkingLevel, onChunk });
    } catch (e) {
      const msg = (e.message || '').toLowerCase();
      const isRateLimit = msg.includes('429') || msg.includes('rate') || msg.includes('quota')
        || msg.includes('resource_exhausted') || msg.includes('too many requests');
      if (!isRateLimit || attempt >= MAX_RETRIES) throw e;
      // Exponential backoff: 10s, 20s, 40s, 80s, 120s, 120s... (capped at 120s)
      const wait = Math.min(10000 * Math.pow(2, attempt), 120000);
      console.warn(`[callLLM] Rate limited (attempt ${attempt + 1}/${MAX_RETRIES + 1}), retrying in ${wait / 1000}s...`, e.message);
      await new Promise(r => setTimeout(r, wait));
    }
  }
}

async function _callLLMInner(messages, model, { maxTokens = 16384, thinkingLevel = 'off', onChunk = null } = {}) {
  const modelInfo = getModelInfo(model);
  const provider = modelInfo?.provider;
  const apiModel = modelInfo?.api_model || model;

  // ── Puter.js (free, proxied) ──
  if (provider === 'puter') {
    await loadPuterJS();
    if (typeof puter === 'undefined' || !puter.ai) throw new Error('Puter.js not loaded');
    const prompt = messages.map(m => `[${m.role.toUpperCase()}]: ${m.content}`).join('\n\n');
    const resp = await puter.ai.chat(prompt, { model: model || 'gpt-4o-mini' });
    if (typeof resp === 'string') return resp;
    const text = resp.message?.content || resp.toString();
    if (resp.usage) callLLM._lastUsage = resp.usage;
    else callLLM._lastUsage = null;
    return text;
  }

  // ── All other providers need an API key ──
  // LM Studio passes this gate via a dummy key set during discovery in loadModels().
  // See loadModels() — localStorage 'byok_key_lmstudio' is set to 'local-no-key-needed'.
  const key = getByokKey(provider);
  if (!key) throw new Error(`No API key for ${PROVIDER_LABELS[provider] || provider}. Select the model and paste your key in Model Keys.`);

  // ── Gemini ──
  if (provider === 'gemini') {
    const systemMsg = messages.find(m => m.role === 'system');
    let chatMsgs = messages.filter(m => m.role !== 'system');
    // Gemini requires at least one user message in contents; if only a system
    // message was provided (common in scaffold REPL calls), promote it to user.
    let promotedSystem = false;
    if (!chatMsgs.length && systemMsg) {
      chatMsgs = [{ role: 'user', content: systemMsg.content }];
      promotedSystem = true;
    }
    const contents = chatMsgs.map(m => ({
      role: m.role === 'assistant' ? 'model' : 'user',
      parts: [{ text: m.content }]
    }));
    const isThinking = /2\.5|3-pro|3-flash|3\.1/.test(apiModel);
    const thinkingConfig = isThinking ? { thinkingConfig: { thinkingBudget: THINKING_BUDGETS[thinkingLevel] || 1024 } } : {};
    const body = {
      contents,
      generationConfig: { temperature: 0.3, maxOutputTokens: maxTokens, ...thinkingConfig },
    };
    if (systemMsg && !promotedSystem) body.systemInstruction = { parts: [{ text: systemMsg.content }] };
    if (onChunk) {
      // Streaming SSE endpoint
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${apiModel}:streamGenerateContent?key=${key}&alt=sse`;
      const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.error?.message || `Gemini API error ${resp.status}`); }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = '', buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const chunk = JSON.parse(line.slice(6));
            const text = chunk.candidates?.[0]?.content?.parts?.map(p => p.text).filter(Boolean).join('') || '';
            if (text) { accumulated += text; onChunk(accumulated); }
          } catch {}
        }
      }
      return accumulated;
    } else {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${apiModel}:generateContent?key=${key}`;
      const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(`${resp.status} ${data.error?.message || JSON.stringify(data.error || resp.statusText)}`);
      const fr = data.candidates?.[0]?.finishReason;
      const text = data.candidates?.[0]?.content?.parts?.map(p => p.text).filter(Boolean).join('') || '';
      const gUsage = data.usageMetadata;
      callLLM._lastUsage = gUsage ? { input_tokens: gUsage.promptTokenCount || 0, output_tokens: gUsage.candidatesTokenCount || 0 } : null;
      if (fr === 'MAX_TOKENS') return { text, truncated: true };
      if (fr === 'MALFORMED_FUNCTION_CALL') return { text, malformed: true, finishMessage: data.candidates?.[0]?.finishMessage || '' };
      return text;
    }
  }

  // ── OpenAI-compatible (OpenAI, Groq, Mistral) ──
  if (provider === 'openai' || provider === 'groq' || provider === 'mistral') {
    const urls = { openai: 'https://api.openai.com/v1/chat/completions', groq: 'https://api.groq.com/openai/v1/chat/completions', mistral: 'https://api.mistral.ai/v1/chat/completions' };
    const resp = await fetch(urls[provider], {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}` },
      body: JSON.stringify({ model: apiModel, messages: messages.map(m => ({ role: m.role, content: m.content })), temperature: 0.3, max_tokens: maxTokens }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(`${resp.status} ${data.error?.message || JSON.stringify(data.error || resp.statusText)}`);
    callLLM._lastUsage = data.usage ? { input_tokens: data.usage.prompt_tokens || 0, output_tokens: data.usage.completion_tokens || 0 } : null;
    return data.choices?.[0]?.message?.content || '';
  }

  // ── Anthropic ──
  if (provider === 'anthropic') {
    const systemMsg = messages.find(m => m.role === 'system');
    const chatMsgs = messages.filter(m => m.role !== 'system');
    const body = { model: apiModel, max_tokens: maxTokens, messages: chatMsgs.map(m => ({ role: m.role, content: m.content })) };
    if (systemMsg) body.system = systemMsg.content;
    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(`${resp.status} ${data.error?.message || JSON.stringify(data.error || resp.statusText)}`);
    callLLM._lastUsage = data.usage ? { input_tokens: data.usage.input_tokens || 0, output_tokens: data.usage.output_tokens || 0 } : null;
    return data.content?.map(c => c.text).filter(Boolean).join('') || '';
  }

  // ── LM Studio (local, via server CORS proxy) ──
  // LM Studio does NOT send CORS headers, so the browser can't call localhost:1234
  // directly. Instead we route through /api/llm/lmstudio-proxy on our own server,
  // which forwards to localhost:1234 server-to-server (no CORS needed). Same pattern
  // as the Cloudflare proxy above. The dummy key 'local-no-key-needed' was set in
  // loadModels() during discovery so we pass the key gate — we don't use it here.
  if (provider === 'lmstudio') {
    const baseUrl = localStorage.getItem('byok_lmstudio_base_url') || 'http://localhost:1234';
    // LM Studio Jinja templates require at least one user message. If only system
    // messages were provided (common in scaffold orchestrator calls), promote the
    // system message to user role. Same pattern as the Gemini branch above.
    let lmsMsgs = messages.map(m => ({ role: m.role, content: m.content }));
    const hasUser = lmsMsgs.some(m => m.role === 'user');
    if (!hasUser && lmsMsgs.length) {
      const sysIdx = lmsMsgs.findIndex(m => m.role === 'system');
      if (sysIdx !== -1) lmsMsgs[sysIdx] = { role: 'user', content: lmsMsgs[sysIdx].content };
    }
    const resp = await fetch('/api/llm/lmstudio-proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: apiModel,
        messages: lmsMsgs,
        temperature: 0.3,
        max_tokens: maxTokens,
        base_url: baseUrl,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      throw new Error(`LM Studio error: ${data.error || resp.statusText}. Check LM Studio is running and the model is loaded.`);
    }
    callLLM._lastUsage = data.usage ? { input_tokens: data.usage.prompt_tokens || 0, output_tokens: data.usage.completion_tokens || 0 } : null;
    const msg = data.choices?.[0]?.message || {};
    // GLM-series models return thinking tokens in reasoning_content; content may be null
    const text = msg.content || msg.reasoning_content || '';
    if (data.choices?.[0]?.finish_reason === 'length') return { text, truncated: true };
    return text;
  }

  // ── Cloudflare Workers AI (via server proxy — no browser CORS) ──
  if (provider === 'cloudflare') {
    const accountId = localStorage.getItem('byok_cf_account_id') || '';
    if (!accountId) throw new Error('Cloudflare Account ID not set. Enter it in Model Keys.');
    const resp = await fetch('/api/llm/cf-proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: key, account_id: accountId, model: apiModel,
        messages: messages.map(m => ({ role: m.role, content: m.content })),
        max_tokens: maxTokens,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(`${resp.status} ${data.error || resp.statusText}`);
    callLLM._lastUsage = null; // Cloudflare doesn't report usage
    return data.result || '';
  }

  throw new Error(`Unsupported provider: ${provider || 'unknown'}. Configure an API key or use Puter.js.`);
}
callLLM._lastUsage = null;

async function askLLMRlm(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const maxIter = parseInt(settings.max_iterations) || 10;
  const maxTokens = parseInt(settings.max_tokens) || 16384;
  const outputTrunc = parseInt(settings.output_truncation) || 5000;
  const thinkingLevel = settings.thinking_level || 'low';
  const planningMode = settings.planning_mode || 'off';
  const planHorizon = planningMode === 'off' ? 1 : (planningMode === 'unlimited' ? 999 : parseInt(planningMode));

  // Build context dict for REPL (mirrors server-side handler)
  const context = {
    grid: _cur.currentState.grid || [],
    available_actions: _cur.currentState.available_actions || [],
    history: (historyForLLM || []).slice(-20).map(h => ({
      step: h.step, action: h.action, result_state: h.result_state,
      change_count: h.change_map?.change_count
    })),
    change_map: _cur.currentChangeMap || {},
    levels_completed: _cur.currentState.levels_completed || 0,
    win_levels: _cur.currentState.win_levels || 0,
    game_id: _cur.currentState.game_id || 'unknown',
    state: _cur.currentState.state || '',
    compact_context: compactBlock || '',
  };

  // Ensure Pyodide is ready for REPL code execution
  await ensurePyodide();

  // Set up REPL context for this turn: update context variable, define helpers if first time
  const contextB64 = btoa(unescape(encodeURIComponent(JSON.stringify(context))));
  const setupCode = `import json as _json, base64 as _base64
context = _json.loads(_base64.b64decode('${contextB64}').decode('utf-8'))
if 'SHOW_VARS' not in dir():
    def SHOW_VARS():
        _skip = {'context', '_json', '_base64', 'json', 'np', 'numpy', 'collections', 'itertools', 'Counter', 'defaultdict', 'math', 'grid', 'prev_grid', 'SHOW_VARS', 'FINAL_VAR', 'llm_query', 'llm_query_batched', '_io', '_sys', '_stdout_buf', '_old_stdout', '_out'}
        _vars = {k: type(v).__name__ for k, v in globals().items() if not k.startswith('_') and k not in _skip}
        _lines = [f"  {k}: {t}" for k, t in sorted(_vars.items())]
        result = "User variables:\\n" + ("\\n".join(_lines) if _lines else "  (none)")
        print(result)
        return result
    def FINAL_VAR(name):
        val = globals().get(name)
        if val is None: return f"[ERROR] Variable '{name}' not found."
        return str(val) if not isinstance(val, str) else val
    def llm_query(prompt):
        return "[llm_query not available in browser mode - use REPL iterations to reason step-by-step]"
    def llm_query_batched(prompts):
        return ["[llm_query not available in browser mode]"] * len(prompts)`;
  await runPyodide(setupCode, context.grid, null, _cur.sessionId);

  // Build conversation messages
  const systemPrompt = buildRlmSystemPrompt(planHorizon);
  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: buildRlmUserFirst(planHorizon) },
  ];

  const iterationsLog = [];
  let finalAnswer = null;

  // Streaming preview callback
  const onChunk = (textSoFar) => {
    if (isActiveFn()) {
      const previewEl = waitEl.querySelector('.stream-preview');
      if (previewEl) {
        previewEl.style.display = 'block';
        previewEl.textContent = textSoFar.length > 500 ? textSoFar.slice(-500) : textSoFar;
        previewEl.scrollTop = previewEl.scrollHeight;
      }
    }
  };

  for (let iter = 0; iter < maxIter; iter++) {
    // Update waiting label with iteration count
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`RLM iteration ${iter + 1}/${maxIter}... `));
        if (timer) label.appendChild(timer);
      }
    }

    // Call LLM with multi-turn conversation
    let responseText;
    try {
      responseText = await callLLM(messages, model, { maxTokens, thinkingLevel, onChunk: modelInfo?.provider === 'gemini' ? onChunk : null });
    } catch (e) {
      console.error(`[RLM] Iteration ${iter} LLM call failed:`, e);
      iterationsLog.push({ iteration: iter, error: e.message });
      break;
    }

    if (!responseText) {
      iterationsLog.push({ iteration: iter, error: 'Empty response from model' });
      break;
    }

    // Extract ```repl code blocks
    const codeBlocks = [];
    const replPattern = /```repl\s*\n([\s\S]*?)\n```/g;
    let match;
    while ((match = replPattern.exec(responseText)) !== null) {
      codeBlocks.push(match[1]);
    }

    // Execute each code block via Pyodide
    const replOutputs = [];
    for (const code of codeBlocks) {
      let output = await runPyodide(code, context.grid, null, _cur.sessionId);
      if (output.length > outputTrunc) {
        output = output.substring(0, outputTrunc) + `\n... [${output.length - outputTrunc} chars truncated]`;
      }
      replOutputs.push(output);
    }

    // Log iteration
    iterationsLog.push({
      iteration: iter,
      response: responseText.substring(0, 2000),
      code_blocks: codeBlocks.length,
      repl_outputs: replOutputs.map(o => o.substring(0, 1000)),
      sub_calls: 0,
    });
    // Emit obs events for RLM
    const _rlmSs = sessions.get(_cur.sessionId);
    emitObsEvent(_rlmSs, { event: 'llm_call', agent: 'executor', model, summary: responseText.slice(0, 200) });
    if (codeBlocks.length > 0) {
      emitObsEvent(_rlmSs, { event: 'repl_exec', agent: 'repl', summary: `${codeBlocks.length} code block(s)` });
    }

    // Check for FINAL() in response text (outside code blocks)
    finalAnswer = _rlmFindFinal(responseText);
    if (finalAnswer) break;

    // Append to conversation
    messages.push({ role: 'assistant', content: responseText });

    // Build REPL output feedback
    if (replOutputs.length) {
      const feedback = replOutputs.map((out, i) => `[REPL output ${i + 1}]:\n${out}`).join('\n\n');
      messages.push({ role: 'user', content: feedback + '\n\n' + buildRlmUserContinue(planHorizon) });
    } else {
      messages.push({ role: 'user', content: buildRlmUserContinue(planHorizon) });
    }

    // Clear streaming preview for next iteration
    if (isActiveFn()) {
      const previewEl = waitEl.querySelector('.stream-preview');
      if (previewEl) { previewEl.style.display = 'none'; previewEl.textContent = ''; }
    }
  }

  // Parse final answer
  let parsed = _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon);

  // Force-action fallback
  const available = _cur.currentState.available_actions || [];
  if (!parsed && available.length) {
    const rawReasoning = iterationsLog.length ? (iterationsLog[iterationsLog.length - 1].response || '').substring(0, 500) : '';
    const safeAction = available.find(a => a !== 0) ?? available[0];
    parsed = {
      action: safeAction, data: {},
      observation: '(RLM did not produce parseable output \u2014 forcing action)',
      reasoning: rawReasoning || '(no reasoning captured)',
    };
    console.warn(`[RLM client] No parseable output after ${iterationsLog.length} iterations, forcing action=${safeAction}`);
  }

  return {
    raw: finalAnswer || (iterationsLog.length ? iterationsLog[iterationsLog.length - 1].response || '' : ''),
    thinking: null,
    parsed,
    model,
    scaffolding: 'rlm',
    _clientSide: true,
    rlm: {
      iterations: iterationsLog.length,
      sub_calls: 0,
      max_iterations: maxIter,
      final_answer: finalAnswer,
      log: iterationsLog,
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE THREE-SYSTEM / TWO-SYSTEM SCAFFOLDING
// ═══════════════════════════════════════════════════════════════════════════

// -- Prompt templates (loaded from prompts/three_system/*.txt via window.PROMPTS) --

const TS_PLANNER_SYSTEM_BODY = getPrompt('three_system.planner_system');
const TS_PLANNER_SYSTEM_BODY_NO_WM = getPrompt('three_system.planner_system_no_wm');
const TS_PLANNER_CONTEXT = window.PROMPTS.three_system.planner_context;
const TS_PLANNER_CONTEXT_NO_WM = window.PROMPTS.three_system.planner_context_no_wm;
const TS_WM_SYSTEM_PROMPT = getPrompt('three_system.wm_system');
const TS_WM_CONTEXT = window.PROMPTS.three_system.wm_context;
const TS_MONITOR_PROMPT = window.PROMPTS.three_system.monitor;

function _tsTemplateFill(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, key) => vars[key] !== undefined ? vars[key] : '')
                 .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}

// -- Color histogram & region map helpers --
function _computeColorHistogram(grid) {
  const counts = {};
  for (const row of grid) for (const c of row) counts[c] = (counts[c] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([c, n]) => `Color ${c}: ${n} cells`).join('\n');
}

function _computeRegionMap(grid) {
  if (!grid || !grid.length) return '(empty grid)';
  const rows = grid.length, cols = grid[0].length;
  const visited = Array.from({length: rows}, () => new Uint8Array(cols));
  const regions = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (visited[r][c]) continue;
      const color = grid[r][c];
      const stack = [[r, c]];
      let minR = r, maxR = r, minC = c, maxC = c, count = 0;
      while (stack.length) {
        const [cr, cc] = stack.pop();
        if (cr < 0 || cr >= rows || cc < 0 || cc >= cols) continue;
        if (visited[cr][cc] || grid[cr][cc] !== color) continue;
        visited[cr][cc] = 1;
        count++;
        if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
        if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
        stack.push([cr-1,cc],[cr+1,cc],[cr,cc-1],[cr,cc+1]);
      }
      if (count >= 2) regions.push({color, count, minR, maxR, minC, maxC});
    }
  }
  regions.sort((a, b) => b.count - a.count);
  return regions.slice(0, 30).map(r =>
    `Color ${r.color}: ${r.count} cells, rows ${r.minR}-${r.maxR}, cols ${r.minC}-${r.maxC}`
  ).join('\n') || '(no regions)';
}

// -- WM query handler (pure data, no LLM) --
function _tsHandleWmQuery(tsState, tool, step, stepRange) {
  const snapshots = tsState.snapshots;
  if (step !== undefined && step !== null) {
    const snap = snapshots.find(s => s.step === step);
    if (!snap) return `(no data for step ${step})`;
    if (tool === 'change_map') return snap.change_map_text || '(no changes)';
    if (tool === 'histogram') return _computeColorHistogram(snap.grid || []);
    if (tool === 'grid') return (snap.grid || []).map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n');
  } else if (stepRange && stepRange.length >= 2) {
    const [start, end] = [stepRange[0], stepRange[stepRange.length - 1]];
    const snaps = snapshots.filter(s => s.step >= start && s.step <= end);
    if (!snaps.length) return `(no data for steps ${start}-${end})`;
    return snaps.map(snap => {
      const aname = ACTION_NAMES[snap.action] || '?';
      let detail = '';
      if (tool === 'change_map') detail = snap.change_map_text || '  (no changes)';
      else if (tool === 'histogram') detail = _computeColorHistogram(snap.grid || []);
      else if (tool === 'grid') detail = (snap.grid || []).map((r, i) => `  Row ${i}: ${compressRowJS(r)}`).join('\n');
      return `Step ${snap.step} (${aname}):\n${detail}`;
    }).join('\n');
  }
  return '(invalid query — specify step or step_range)';
}

// -- Simulate actions using WM rules --
async function _tsSimulateActions(actions, tsState, context, settings) {
  const rulesDoc = tsState.rules_doc;
  if (!rulesDoc) return actions.map(() => 'unknown — no rules discovered yet, try it and observe');
  const wmModel = settings.wm_model || settings.model || 'gemini-2.5-flash';
  const wmThinking = settings.wm_thinking_level || 'low';
  const wmMaxTokens = Math.min(parseInt(settings.wm_max_tokens) || 8192, 65536);
  const actionDescs = actions.map(act => {
    const a = act.action || 0;
    const aname = ACTION_NAMES[a] || `ACTION${a}`;
    const data = act.data || {};
    return a === 6 && data.x !== undefined ? `${aname}@(${data.x},${data.y})` : aname;
  });
  const prompt = `You are a World Model predicting game outcomes.

## RULES (v${tsState.rules_version})
${rulesDoc}

## CURRENT STATE
Game: ${context.game_id || '?'} | Step: ${context.step_num || 0} | Levels: ${context.levels_completed || 0}/${context.win_levels || 0}

## ACTIONS TO PREDICT
${actionDescs.map((d, i) => `${i + 1}. ${d}`).join('\n')}

For each action, predict what would happen based on your rules.
Respond with EXACTLY this JSON:
{"predictions": ["<prediction for action 1>", "<prediction for action 2>", ...]}

If uncertain, say "uncertain — <best guess>". Keep each prediction under 100 chars.`;
  try {
    const raw = await callLLM(
      [{role: 'system', content: prompt}],
      wmModel, { maxTokens: wmMaxTokens, thinkingLevel: wmThinking }
    );
    const parsed = _extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();
    if (parsed && parsed.predictions) {
      const preds = parsed.predictions;
      while (preds.length < actions.length) preds.push('no prediction');
      return preds.slice(0, actions.length);
    }
  } catch (e) { console.warn('[ts_simulate] error:', e); }
  return actions.map(() => 'prediction unavailable');
}

// -- Recover truncated rules_document from raw WM response --
function _tsRecoverTruncatedRules(raw) {
  if (!raw) return null;
  const m = raw.match(/"rules_document"\s*:\s*"/);
  if (!m) return null;
  const start = m.index + m[0].length;
  let result = '', i = start;
  while (i < raw.length) {
    const c = raw[i];
    if (c === '\\' && i + 1 < raw.length) {
      const nc = raw[i + 1];
      if (nc === 'n') result += '\n';
      else if (nc === 't') result += '\t';
      else if (nc === '"') result += '"';
      else if (nc === '\\') result += '\\';
      else result += nc;
      i += 2;
    } else if (c === '"') break;
    else { result += c; i++; }
  }
  return result.trim().length > 20 ? result.trim() : null;
}

// -- WM update REPL loop --
async function _tsRunWmUpdate(tsState, context, settings, waitEl, isActive) {
  const wmModel = settings.wm_model || settings.model || 'gemini-2.5-flash';
  const wmThinking = settings.wm_thinking_level || 'low';
  const wmMaxTokens = Math.min(parseInt(settings.wm_max_tokens) || 16384, 65536);
  const maxTurns = parseInt(settings.wm_max_turns) || 5;

  const rulesDoc = tsState.rules_doc || '(No rules yet — this is your first analysis!)';
  const obs = tsState.observations;
  const obsLines = obs.map(o => {
    const aname = ACTION_NAMES[o.action] || '?';
    let line = `Step ${o.step}: ${aname} -> levels=${o.levels || '?'}, state=${o.state || '?'}`;
    const cm = typeof o.change_map_text === 'object' ? (o.change_map_text?.change_map_text || '') : (o.change_map_text || '');
    if (cm) line += '\n  ' + cm.trim().split('\n').slice(0, 4).join('\n  ');
    return line;
  });
  const obsText = obsLines.length ? obsLines.join('\n') : '(no new observations)';
  const obsStart = obs.length ? obs[0].step : 0;
  const obsEnd = obs.length ? obs[obs.length - 1].step : 0;

  const conversation = [];
  const wmLog = [];

  for (let turn = 1; turn <= maxTurns; turn++) {
    let ctxText = _tsTemplateFill(TS_WM_CONTEXT, {
      game_id: context.game_id || '?', step_num: context.step_num || 0,
      levels_done: context.levels_completed || 0, win_levels: context.win_levels || 0,
      rules_version: tsState.rules_version, rules_doc: rulesDoc,
      observations_text: obsText, obs_start: obsStart, obs_end: obsEnd,
      turn_num: turn, max_turns: maxTurns,
    });
    if (conversation.length) ctxText += '\n\n## WORLD MODEL CONVERSATION\n' + conversation.join('\n\n');
    if (turn === maxTurns) ctxText += '\n\n!! THIS IS YOUR LAST TURN — you MUST commit your rules document now. !!';

    const prompt = TS_WM_SYSTEM_PROMPT + '\n\n' + ctxText;
    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], wmModel, { maxTokens: wmMaxTokens, thinkingLevel: wmThinking });
    } catch (e) {
      console.error(`[ts_wm] turn ${turn} failed:`, e);
      wmLog.push({turn, type: 'error', error: e.message, duration_ms: 0});
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    // Emit obs event for WM call
    emitObsEvent(getActiveSession(), { event: 'wm_update', agent: 'world_model', model: wmModel, duration_ms: durMs, summary: (raw || '').slice(0, 200) });

    const parsed = _extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.type) {
      const recovered = _tsRecoverTruncatedRules(raw);
      if (recovered) {
        tsState.rules_doc = recovered;
        tsState.rules_version++;
        tsState.observations = [];
        wmLog.push({turn, type: 'commit', confidence: 0.5, duration_ms: durMs, recovered: true});
        break;
      }
      wmLog.push({turn, type: 'error', error: 'unparseable', duration_ms: durMs});
      break;
    }

    if (parsed.type === 'query') {
      const tool = parsed.tool || 'change_map';
      const resultText = _tsHandleWmQuery(tsState, tool, parsed.step, parsed.step_range);
      const truncResult = resultText.length > 2000 ? resultText.substring(0, 2000) + '\n... (truncated)' : resultText;
      conversation.push(`[Turn ${turn}] Queried '${tool}':\n${truncResult}`);
      wmLog.push({turn, type: 'query', tool, duration_ms: durMs});
    } else if (parsed.type === 'commit') {
      const newRules = parsed.rules_document || '';
      if (newRules) {
        tsState.rules_doc = newRules;
        tsState.rules_version++;
        tsState.observations = [];
        wmLog.push({turn, type: 'commit', confidence: parsed.confidence || 0.5, duration_ms: durMs});
        break;
      }
      wmLog.push({turn, type: 'commit_empty', duration_ms: durMs});
    }
  }

  return {
    ran_update: true, wm_log: wmLog,
    rules_version: tsState.rules_version,
    rules_preview: (tsState.rules_doc || '').substring(0, 200),
  };
}

// -- Monitor check --
async function _tsMonitorCheck(step, expected, changeData, gameState, settings, tsState) {
  const monitorModel = settings.monitor_model || settings.model || 'gemini-2.5-flash';
  const monitorThinking = settings.monitor_thinking_level || 'off';
  const monitorMaxTokens = Math.min(parseInt(settings.monitor_max_tokens) || 4096, 16384);

  const actionName = ACTION_NAMES[step.action] || `ACTION${step.action}`;
  const changeSummary = changeData?.change_map_text || (changeData?.change_count > 0 ? `${changeData.change_count} cells changed` : 'no changes');
  const levelChange = (gameState.levels_completed || 0) > (gameState.prev_levels || 0) ? 'LEVEL UP!' : 'same level';
  const replanCooldown = parseInt(settings.replan_cooldown) || 3;
  const plansSince = tsState.plans_since_replan || 99;
  const onCooldown = plansSince < replanCooldown;
  const cooldownLine = onCooldown
    ? `Replan cooldown: ON COOLDOWN (${plansSince}/${replanCooldown} plans) — you MUST return CONTINUE`
    : `Replan cooldown: available (${plansSince}/${replanCooldown} plans since last replan)`;

  const prompt = _tsTemplateFill(TS_MONITOR_PROMPT, {
    game_id: gameState.game_id || '?', step_num: gameState.step_num || 0,
    levels_done: gameState.levels_completed || 0, win_levels: gameState.win_levels || 0,
    action_name: actionName, expected: expected,
    change_summary: changeSummary, level_change: levelChange,
    state: gameState.state || 'NOT_FINISHED',
    replan_cooldown: replanCooldown, cooldown_line: cooldownLine,
  });

  const t0 = performance.now();
  try {
    const raw = await callLLM([{role: 'system', content: prompt}], monitorModel, { maxTokens: monitorMaxTokens, thinkingLevel: monitorThinking });
    const durMs = Math.round(performance.now() - t0);
    const parsed = _extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();
    if (!parsed) return {verdict: 'CONTINUE', reason: 'monitor parse error', discovery: null, duration_ms: durMs};

    let verdict = (parsed.verdict || 'CONTINUE').toUpperCase();
    if (verdict !== 'CONTINUE' && verdict !== 'REPLAN') verdict = 'CONTINUE';

    let suppressed = false;
    if (verdict === 'REPLAN' && onCooldown) {
      verdict = 'CONTINUE';
      suppressed = true;
    } else if (verdict === 'REPLAN') {
      tsState.plans_since_replan = 0;
    }

    // Store discovery in observations
    if (parsed.discovery) {
      tsState.observations.push({
        step: gameState.step_num || 0, action: step.action,
        levels: gameState.levels_completed || 0, state: gameState.state || 'NOT_FINISHED',
        change_map_text: changeSummary, discovery: parsed.discovery,
      });
    }

    // Emit obs event for monitor
    emitObsEvent(getActiveSession(), { event: 'monitor_call', agent: 'monitor', model: monitorModel, duration_ms: durMs, summary: `${verdict}${parsed.reason ? ': ' + parsed.reason : ''}` });
    return {verdict, reason: parsed.reason || '', discovery: parsed.discovery || null, duration_ms: durMs, replan_suppressed: suppressed};
  } catch (e) {
    console.error('[ts_monitor] failed:', e);
    return {verdict: 'CONTINUE', reason: 'monitor error', discovery: null, duration_ms: 0};
  }
}

// -- Main Three-System planner --
async function askLLMThreeSystem(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const t0Total = performance.now();
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const plannerModel = settings.planner_model || settings.model || model;
  const plannerThinking = settings.planner_thinking_level || settings.thinking_level || 'low';
  const plannerMaxTokens = Math.min(parseInt(settings.planner_max_tokens || settings.max_tokens) || 16384, 65536);
  const maxTurns = parseInt(settings.planner_max_turns) || 10;
  const maxPlan = parseInt(settings.max_plan_length) || 15;
  const minPlan = parseInt(settings.min_plan_length) || 3;
  const wmUpdateEvery = parseInt(settings.wm_update_every) || 5;
  const wmModel = settings.wm_model; // empty = WM disabled (two_system mode)
  const wmEnabled = !!wmModel;
  const scaffoldingType = settings.scaffolding || 'three_system';

  // Get/init tsState from session
  if (!_cur._tsState) {
    _cur._tsState = {
      rules_doc: '', rules_version: 0,
      observations: [], snapshots: [],
      turn_count: 0, plans_since_replan: 99,
    };
  }
  const ss = _cur._tsState;
  ss.turn_count++;

  const context = {
    grid: _cur.currentState.grid || [],
    available_actions: _cur.currentState.available_actions || [],
    history: historyForLLM || [],
    change_map: _cur.currentChangeMap || {},
    levels_completed: _cur.currentState.levels_completed || 0,
    win_levels: _cur.currentState.win_levels || 0,
    game_id: _cur.currentState.game_id || 'unknown',
    state: _cur.currentState.state || '',
    step_num: _cur.stepCount || 0,
    compact_context: compactBlock || '',
  };

  // 1. World Model update if enough observations
  let wmInfo = {ran_update: false, wm_log: [], rules_version: ss.rules_version, rules_preview: (ss.rules_doc || '').substring(0, 200)};
  if (wmEnabled && ss.observations.length >= wmUpdateEvery) {
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode('WM updating rules... '));
        if (timer) label.appendChild(timer);
      }
    }
    wmInfo = await _tsRunWmUpdate(ss, context, settings, waitEl, isActiveFn);
  }

  // 2. Planner REPL
  const desc = getPrompt('shared.arc_description');
  const planLenVars = {min_plan_length: minPlan, max_plan_length: maxPlan};
  const plannerSystemPrompt = wmEnabled
    ? desc + '\n\n' + _tsTemplateFill(TS_PLANNER_SYSTEM_BODY, planLenVars)
    : desc + '\n\n' + _tsTemplateFill(TS_PLANNER_SYSTEM_BODY_NO_WM, planLenVars);

  const actionDesc = context.available_actions.map(a => `${a}=${ACTION_NAMES[a] || 'ACTION' + a}`).join(', ');

  // History block
  let historyBlock = '';
  const hist = context.history;
  if (hist.length) {
    const lines = hist.map(h => {
      const aname = ACTION_NAMES[h.action] || '?';
      const obs = (h.observation || '').substring(0, 500);
      let line = `  Step ${h.step || '?'}: ${aname} -> levels=${h.levels || '?'} | ${obs}`;
      if (h.reasoning) line += `\n    Reasoning: ${h.reasoning.substring(0, 500)}`;
      return line;
    });
    historyBlock = `## HISTORY (all ${hist.length})\n` + lines.join('\n');
  }

  // Change map block
  const cm = context.change_map;
  let changeMapBlock = '';
  if (typeof cm === 'object' && cm?.change_map_text) changeMapBlock = cm.change_map_text;
  else if (typeof cm === 'string' && cm) changeMapBlock = cm;

  // Grid block
  const gridText = context.grid.length ? context.grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n') : '(no grid)';
  const gridBlock = `## GRID (RLE)\n${gridText}`;

  const rulesDoc = ss.rules_doc || '(No rules discovered yet — explore to learn!)';
  const conversation = [];
  const plannerLog = [];

  for (let turn = 1; turn <= maxTurns; turn++) {
    if (isActiveFn()) {
      const label = waitEl.querySelector('.step-label');
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`Planner turn ${turn}/${maxTurns}... `));
        if (timer) label.appendChild(timer);
      }
    }

    const ctxVars = {
      game_id: context.game_id, state: context.state,
      levels_done: context.levels_completed, win_levels: context.win_levels,
      step_num: context.step_num, action_desc: actionDesc,
      memory_block: '', history_block: historyBlock,
      change_map_block: changeMapBlock, grid_block: gridBlock,
      rules_version: ss.rules_version, rules_doc: rulesDoc,
      turn_num: turn, max_turns: maxTurns,
    };
    let ctxText = wmEnabled
      ? _tsTemplateFill(TS_PLANNER_CONTEXT, ctxVars)
      : _tsTemplateFill(TS_PLANNER_CONTEXT_NO_WM, ctxVars);
    if (conversation.length) ctxText += '\n\n## PLANNER CONVERSATION\n' + conversation.join('\n\n');

    const prompt = plannerSystemPrompt + '\n\n' + ctxText;
    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], plannerModel, { maxTokens: plannerMaxTokens, thinkingLevel: plannerThinking });
    } catch (e) {
      console.error(`[ts_planner] turn ${turn} failed:`, e);
      plannerLog.push({turn, type: 'error', error: e.message, duration_ms: 0});
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    // Emit obs event for planner call
    emitObsEvent(getActiveSession(), { event: 'planner_call', agent: 'planner', model: plannerModel, duration_ms: durMs, summary: (raw || '').slice(0, 200) });

    const parsed = _extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.type) {
      plannerLog.push({turn, type: 'error', error: 'unparseable', duration_ms: durMs, raw});
      if (turn === maxTurns) break;
      conversation.push(`[Turn ${turn}] (unparseable response, trying again)`);
      continue;
    }

    if (parsed.type === 'simulate') {
      if (!wmEnabled) {
        conversation.push(`[Turn ${turn}] No World Model available — cannot simulate. Use 'analyze' or 'commit' instead.`);
        plannerLog.push({turn, type: 'simulate_skipped', duration_ms: durMs});
        continue;
      }
      const actions = parsed.actions || [];
      const question = parsed.question || '';
      const predictions = await _tsSimulateActions(actions, ss, context, settings);
      const resultText = `Simulation of ${actions.length} action(s):\n` +
        actions.map((act, i) => `  ${i + 1}. ${ACTION_NAMES[act.action || 0] || '?'}: ${predictions[i]}`).join('\n');
      conversation.push(`[Turn ${turn}] You simulated: ${question}\nResult: ${resultText}`);
      plannerLog.push({turn, type: 'simulate', actions: actions.map(a => a.action || 0), predictions: predictions.slice(0, 5), duration_ms: durMs});

    } else if (parsed.type === 'analyze') {
      const tool = parsed.tool || 'region_map';
      let resultText;
      if (tool === 'region_map') resultText = _computeRegionMap(context.grid);
      else if (tool === 'histogram') resultText = _computeColorHistogram(context.grid);
      else if (tool === 'change_map' && changeMapBlock) resultText = changeMapBlock;
      else resultText = '(no data available)';
      conversation.push(`[Turn ${turn}] Analyzed '${tool}':\n${resultText}`);
      plannerLog.push({turn, type: 'analyze', tool, duration_ms: durMs});

    } else if (parsed.type === 'commit') {
      const plan = parsed.plan || [];
      const goal = parsed.goal || '';
      const observation = parsed.observation || '';
      const reasoning = parsed.reasoning || '';
      const avail = new Set(context.available_actions);
      const validPlan = [];
      for (const step of plan.slice(0, maxPlan)) {
        if (step.action !== undefined && avail.has(step.action)) {
          validPlan.push({action: parseInt(step.action), data: step.data || {}, expected: step.expected || ''});
        }
      }

      // Reject short plans (unless last turn)
      if (validPlan.length < minPlan && turn < maxTurns) {
        conversation.push(`[Turn ${turn}] REJECTED: Your plan has only ${validPlan.length} action(s). The minimum is ${minPlan}. Think further ahead — plan a sequence of at least ${minPlan} actions to reach your goal. Try again.`);
        plannerLog.push({turn, type: 'rejected', plan_length: validPlan.length, min_required: minPlan, duration_ms: durMs});
        continue;
      }

      // Last turn: pad if needed
      if (validPlan.length < minPlan) {
        const exploratory = context.available_actions.filter(a => a !== 0);
        let idx = 0;
        while (validPlan.length < minPlan && exploratory.length) {
          validPlan.push({action: exploratory[idx % exploratory.length], data: {}, expected: 'explore'});
          idx++;
        }
      }

      plannerLog.push({turn, type: 'commit', plan_length: validPlan.length, raw_plan_length: plan.length, duration_ms: durMs});
      ss.plans_since_replan = (ss.plans_since_replan || 0) + 1;
      const totalDur = Math.round(performance.now() - t0Total);

      return {
        raw, thinking: null,
        parsed: {
          observation, reasoning,
          action: validPlan.length ? validPlan[0].action : 0,
          data: validPlan.length ? validPlan[0].data || {} : {},
          plan: validPlan,
        },
        model: plannerModel, scaffolding: scaffoldingType,
        _clientSide: true,
        three_system: {
          turn: ss.turn_count, goal,
          planner_log: plannerLog, world_model: wmInfo,
        },
        call_duration_ms: totalDur,
      };
    }
  }

  // Fallback: exploratory plan
  const exploratory = context.available_actions.filter(a => a !== 0);
  const fallbackPlan = [];
  let idx = 0;
  const target = Math.max(minPlan, 6);
  while (fallbackPlan.length < target && exploratory.length) {
    fallbackPlan.push({action: exploratory[idx % exploratory.length], data: {}, expected: 'explore'});
    idx++;
  }
  const totalDur = Math.round(performance.now() - t0Total);

  return {
    raw: '', thinking: null,
    parsed: {
      observation: 'Planner could not commit a plan',
      reasoning: 'Max REPL turns reached or errors occurred, falling back to exploration',
      action: fallbackPlan.length ? fallbackPlan[0].action : 0,
      data: {},
      plan: fallbackPlan,
    },
    model: plannerModel, scaffolding: scaffoldingType,
    _clientSide: true, _fallbackAction: true,
    three_system: {
      turn: ss.turn_count, goal: 'explore — planner fallback',
      planner_log: plannerLog, world_model: wmInfo,
    },
    call_duration_ms: totalDur,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// AGENT SPAWN — Agentica-style orchestrator + reactive subagent loops
// ═══════════════════════════════════════════════════════════════════════════

// ── Step 1: Per-step execution helper ────────────────────────────────────

async function _asExecuteOneStep(actionId, actionData, reasoning, agentType, _cur, isActiveFn, llmMeta) {
  // Push undo snapshot
  const currentTurnId = _cur.turnCounter;
  _cur.undoStack.push({
    grid: _cur.currentState.grid ? _cur.currentState.grid.map(r => [...r]) : [],
    state: _cur.currentState.state,
    levels_completed: _cur.currentState.levels_completed,
    stepCount: _cur.stepCount,
    turnId: currentTurnId,
  });

  const prevGrid = _cur.currentState.grid ? _cur.currentState.grid.map(r => [...r]) : [];
  _cur.stepCount++;

  const extras = { session_cost: _cur.sessionTotalTokens?.cost || 0 };
  const data = await gameStep(_cur.sessionId, actionId, actionData || {}, extras,
    { grid: _cur.currentState.grid, _ownerSessionId: _cur.sessionId });

  if (data.error) {
    // Rollback
    _cur.undoStack.pop();
    _cur.stepCount--;
    return { data, terminal: null, prevGrid, newGrid: prevGrid, error: true };
  }

  // Update session state
  _cur.currentState = data;
  _cur.currentGrid = data.grid;
  _cur.currentChangeMap = data.change_map;

  // Compute change map
  const newGrid = data.grid || [];
  const changeMap = computeChangeMapJS(prevGrid, newGrid);
  _cur.currentChangeMap = changeMap;

  // Push to move history
  _cur.moveHistory.push({
    step: _cur.stepCount, action: actionId,
    result_state: data.state, levels: data.levels_completed,
    grid: data.grid, change_map: changeMap,
    turnId: currentTurnId,
    observation: `[${agentType}] ${reasoning || ''}`,
    reasoning: reasoning || '',
  });

  // Record for persistence — include subagent LLM metadata so reasoning is available on resume
  const _stepLlm = {
    parsed: { observation: `[${agentType}] ${reasoning || ''}`, reasoning: reasoning || '', action: actionId, data: actionData || {} },
    model: llmMeta?.model || '', scaffolding: 'agent_spawn',
    usage: llmMeta?.usage || null,
    call_duration_ms: llmMeta?.call_duration_ms || null,
  };
  recordStepForPersistence(actionId, actionData || {}, data.grid, changeMap, _stepLlm, _cur,
    { levels_completed: data.levels_completed, result_state: data.state });

  // Update UI if active
  if (isActiveFn()) { updateUI(data); updateUndoBtn(); }

  // Determine terminal
  let terminal = null;
  if (data.state === 'WIN') terminal = 'WIN';
  else if (data.state === 'GAME_OVER') terminal = 'GAME_OVER';

  return { data, terminal, prevGrid, newGrid, error: false };
}

// ── Step 2: Bounded budget + frame helpers ───────────────────────────────

function _makeBoundedBudget(limit) {
  return {
    remaining: limit, total: limit,
    use(actionId) {
      if (actionId === 0) return true; // RESET doesn't cost budget
      if (this.remaining <= 0) return false;
      this.remaining--;
      return true;
    },
    exhausted() { return this.remaining <= 0; },
  };
}

function _asRenderGrid(grid) {
  if (!grid || !grid.length) return '(empty grid)';
  return grid.map((r, i) => `Row ${String(i).padStart(2)}: ${compressRowJS(r)}`).join('\n');
}

function _asDiffFrames(oldGrid, newGrid) {
  if (!oldGrid || !newGrid) return '(no diff available)';
  const cm = computeChangeMapJS(oldGrid, newGrid);
  if (!cm.changes.length) return '(no changes)';
  // Group changes by region
  const byRow = {};
  for (const c of cm.changes) {
    if (!byRow[c.y]) byRow[c.y] = [];
    byRow[c.y].push(c);
  }
  const lines = [];
  for (const [row, changes] of Object.entries(byRow).sort((a, b) => a[0] - b[0])) {
    const details = changes.map(c => `col ${c.x}: ${c.from}->${c.to}`).join(', ');
    lines.push(`Row ${row}: ${details}`);
  }
  return lines.join('\n');
}

function _asChangeSummary(oldGrid, newGrid) {
  if (!oldGrid || !newGrid) return 'No previous grid';
  const cm = computeChangeMapJS(oldGrid, newGrid);
  return `${cm.change_count} cell(s) changed`;
}

function _asFind(grid, ...colors) {
  if (!grid || !grid.length) return '(empty grid)';
  const colorSet = new Set(colors.map(Number));
  const results = [];
  for (let r = 0; r < grid.length; r++) {
    for (let c = 0; c < grid[r].length; c++) {
      if (colorSet.has(grid[r][c])) results.push(`(${r},${c})=${grid[r][c]}`);
    }
  }
  return results.length ? results.join(', ') : '(none found)';
}

function _asBoundingBox(grid, ...colors) {
  if (!grid || !grid.length) return '(empty grid)';
  const colorSet = new Set(colors.map(Number));
  let minR = Infinity, maxR = -1, minC = Infinity, maxC = -1;
  for (let r = 0; r < grid.length; r++) {
    for (let c = 0; c < grid[r].length; c++) {
      if (colorSet.has(grid[r][c])) {
        if (r < minR) minR = r; if (r > maxR) maxR = r;
        if (c < minC) minC = c; if (c > maxC) maxC = c;
      }
    }
  }
  if (maxR === -1) return '(no cells with those colors)';
  return `rows ${minR}-${maxR}, cols ${minC}-${maxC} (${maxR-minR+1}x${maxC-minC+1})`;
}

function _asColorCounts(grid) {
  return _computeColorHistogram(grid);
}

function _asDispatchFrameTool(tool, grid, prevGrid, args) {
  switch (tool) {
    case 'render_grid': return _asRenderGrid(grid);
    case 'diff_frames': return _asDiffFrames(prevGrid, grid);
    case 'change_summary': return _asChangeSummary(prevGrid, grid);
    case 'find_colors': return _asFind(grid, ...(args?.colors || []));
    case 'bounding_box': return _asBoundingBox(grid, ...(args?.colors || []));
    case 'color_counts': return _asColorCounts(grid);
    default: return `Unknown frame tool: ${tool}`;
  }
}

// ── Step 3: Stack-based shared memory ────────────────────────────────────

function _asCreateMemories() {
  return {
    facts: [],
    hypotheses: [],
    stack: [], // [{summary, details, agentType, timestamp}]

    addFact(fact) { if (!this.facts.includes(fact)) this.facts.push(fact); },
    addHypothesis(h) { if (!this.hypotheses.includes(h)) this.hypotheses.push(h); },

    add(summary, details, agentType) {
      this.stack.push({ summary, details: details || '', agentType: agentType || 'system', timestamp: Date.now() });
    },

    summaries() {
      return this.stack.map((m, i) => `[${i}] (${m.agentType}) ${m.summary}`);
    },

    formatForPrompt() {
      const parts = [];
      if (this.facts.length) {
        const recent = this.facts.slice(-5);
        parts.push('## Facts\n' + recent.map((f, i) => `${i + 1}. ${f}`).join('\n'));
      }
      if (this.hypotheses.length) {
        const recent = this.hypotheses.slice(-5);
        parts.push('## Hypotheses\n' + recent.map((h, i) => `${i + 1}. ${h}`).join('\n'));
      }
      if (this.stack.length) {
        const recent = this.stack.slice(-8);
        parts.push('## Agent Reports\n' + recent.map((m, i) =>
          `[${i}] (${m.agentType}) ${m.summary}${m.details ? '\n   ' + m.details : ''}`
        ).join('\n'));
      }
      return parts.length ? parts.join('\n\n') : '(none yet)';
    },
  };
}

// ── Step 4: Agentica-style prompts ───────────────────────────────────────

const AS_GAME_REFERENCE = `# ARC-AGI-3 Game Reference

## Grid
The game is played on a grid (up to 64x64). Each cell has a color value 0-15.
Colors: 0=White, 1=LightGray, 2=Gray, 3=DarkGray, 4=VeryDarkGray, 5=Black, 6=Magenta, 7=LightMagenta, 8=Red, 9=Blue, 10=LightBlue, 11=Yellow, 12=Orange, 13=Maroon, 14=Green, 15=Purple.

## Actions
Actions are integers. Common mapping:
  0=RESET (restart current level), 1=UP, 2=DOWN, 3=LEFT, 4=RIGHT, 5=ACT5, 6=CLICK, 7=ACT7
Not all actions are available in every game — check available_actions.

## RESET Discipline
Action 0 (RESET) restarts the current level to its initial state. Use it when stuck or to test hypotheses from a clean state. RESET does NOT cost budget.

## Level Progression
- levels_completed increments mid-action when you complete a level's objective.
- state='WIN' ONLY when ALL levels are done (levels_completed == win_levels).
- A single action can complete a level (levels_completed goes up) while state stays 'NOT_FINISHED' if more levels remain.

## Frame Tools
You can use frame tools to analyze the grid without taking an action:
- render_grid: Full text rendering of the current grid with row numbers
- diff_frames: Region-grouped diff between previous and current grid
- change_summary: One-line summary of how many cells changed
- find_colors(colors): Find pixel coordinates matching given color values
- bounding_box(colors): Tight bounding box around cells of given colors
- color_counts: Color histogram of the grid

Usage: {"command": "frame_tool", "tool": "<name>", "args": {"colors": [1, 2]}}

## Memory
Findings are stored in shared memory. Reference by index: "See report [2]".
Add findings as you discover them — other agents can see your reports.

## Methodology
1. Hypothesize what an action might do
2. Test by executing the action
3. Verify by analyzing the grid changes (use diff_frames / change_summary)
4. Record confirmed findings as facts
5. Always analyze changes AFTER each action — never assume the result`;

const AS_ORCHESTRATOR_PREMISE = `You are the ORCHESTRATOR for an ARC-AGI-3 game-playing system.

## Your Role
You are a MANAGER, not a player. You coordinate subagents to explore, theorize, test, and solve.
You do NOT have submit_action. You CANNOT play the game directly.
Your only tools are THINKING and DELEGATING to subagents.

## Subagent Types
- **explorer**: Systematic action sampling. Tries available actions, uses frame tools, reports what each action does. Best for early-game discovery.
- **theorist**: Analysis only — receives data, outputs hypotheses, challenges assumptions. Has NO game actions. Can only use frame_tool and report.
- **tester**: Receives a hypothesis. Designs a minimal experiment (1-3 actions), executes, reports whether hypothesis is confirmed or refuted.
- **solver**: Receives a strategy. Executes a sequence of actions efficiently. Reports progress and obstacles.

## Orchestration Phases
1. **Explore** — Spawn explorer(s) to try all available actions and map mechanics
2. **Hypothesize** — Spawn theorist to analyze findings and propose level-solving strategy
3. **Test** — Spawn tester to verify critical hypotheses before committing
4. **Iterate** — If tests fail, update hypotheses and re-test
5. **Solve** — Spawn solver with a clear strategy to complete the level
6. **Next Level** — After level completion, re-explore (mechanics may change)

## Briefing Subagents
Always tell subagents:
- What is known so far (summarize key facts)
- What they should focus on (specific task)
- Reference memory indices: "See reports [0]-[2] for explored actions"

## Commands
You MUST respond with exactly one JSON object:

Option A — Delegate to a subagent:
{"command": "delegate", "reasoning": "why this delegation is the right next step", "agent_type": "explorer|theorist|tester|solver", "task": "specific instructions", "budget": <1-10>}

Option B — Think and record to memory:
{"command": "think", "reasoning": "analysis of current situation", "facts": ["confirmed fact", ...], "hypotheses": ["working theory", ...], "next": "what to do next"}`;

const AS_AGENT_SYSTEM = {
  explorer: `You are an EXPLORER subagent for ARC-AGI-3.

Your mission: systematically try ALL available actions to discover what they do.
- Try each available action at least once
- Use frame tools (diff_frames, change_summary) AFTER each action to see what changed
- Try actions from different grid states (use RESET to get a clean slate)
- Report: what each action does, which actions seem to advance the level, any patterns

You have a limited action budget. Prioritize coverage over depth — try different actions rather than repeating the same one.
Respond in JSON only.`,

  theorist: `You are a THEORIST subagent for ARC-AGI-3.

Your mission: analyze data from other agents and formulate hypotheses.
- You have NO game actions — you CANNOT use the "act" command
- You CAN use frame_tool to examine the current grid state
- Study the facts and agent reports in shared memory
- Propose testable hypotheses about game mechanics and level solutions
- Challenge existing assumptions — look for what might be wrong
- Be specific: "Action 4 moves the player right by 1 cell" not "actions move things"

Respond in JSON only.`,

  tester: `You are a TESTER subagent for ARC-AGI-3.

Your mission: test a specific hypothesis with minimal actions.
- Design the smallest possible experiment to confirm or refute the hypothesis
- RESET first if you need a clean state
- Execute actions and analyze results with frame tools
- Report conclusively: CONFIRMED or REFUTED, with evidence
- Keep experiments small (1-3 actions) — don't waste budget on exploration

Respond in JSON only.`,

  solver: `You are a SOLVER subagent for ARC-AGI-3.

Your mission: execute a strategy to complete the current level.
- Follow the orchestrator's plan but adapt if results are unexpected
- Use frame tools to verify progress after each action
- If stuck, report the obstacle rather than thrashing
- Report progress: what worked, what didn't, current state

Respond in JSON only.`,
};

const AS_AGENT_TURN = `# Task from Orchestrator
{task}

# Current State
- Step: {step_num} | Budget remaining: {budget_remaining}/{budget_total}
- Level: {levels_done} / {win_levels}
- State: {state_str}
- Available actions: {action_desc}

# Grid
{grid_block}

# Changes from last action
{change_map_block}

# Shared Memories
{memories}

# My Actions This Session
{session_history}
{tool_results}
# Commands
Respond with exactly one JSON object:

Option A — Take a game action (NOT available for theorist):
{"command": "act", "action": <action_id>, "data": {}, "reasoning": "why this action"}

Option B — Use a frame tool to analyze the grid:
{"command": "frame_tool", "tool": "render_grid|diff_frames|change_summary|find_colors|bounding_box|color_counts", "args": {"colors": [1, 2]}}

Option C — Report findings and yield to orchestrator:
{"command": "report", "findings": ["finding1", ...], "hypotheses": ["hypothesis1", ...], "summary": "what I learned"}`;

function _asFill(template, vars) {
  let s = template;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll('{' + k + '}', String(v));
  return s;
}

// ── Step 5: Main function — reactive subagent loops ──────────────────────

async function askLLMAgentSpawn(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) {
  const t0Total = performance.now();
  const settings = _snap?.scaffolding || getScaffoldingSettings();
  const orchModel = settings.orchestrator_model || settings.model || model;
  const orchThinking = settings.orchestrator_thinking_level || 'high';
  const orchMaxTokens = Math.min(parseInt(settings.orchestrator_max_tokens) || 16384, 65536);
  const subModel = settings.subagent_model || orchModel;
  const subThinking = settings.subagent_thinking_level || 'med';
  const subMaxTokens = Math.min(parseInt(settings.subagent_max_tokens) || 16384, 65536);
  const maxSubBudget = parseInt(settings.max_subagent_budget) || 5;
  const orchMaxTurns = parseInt(settings.orchestrator_max_turns) || 5;

  // Token/cost tracking helper — accumulates into session totals
  const _asTokens = _cur.sessionTotalTokens || sessionTotalTokens;
  function _asTrackUsage(model, rawText) {
    const usage = callLLM._lastUsage;
    let inputTok = usage?.input_tokens || 0;
    let outputTok = usage?.output_tokens || 0;
    // Estimate if API didn't report
    if (!inputTok && rawText) inputTok = Math.ceil((rawText).length / 4);
    if (!outputTok && rawText) outputTok = Math.ceil((rawText).length / 4);
    _asTokens.input += inputTok;
    _asTokens.output += outputTok;
    const prices = TOKEN_PRICES[model] || null;
    let cost = 0;
    if (prices) {
      cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
      _asTokens.cost += cost;
    }
    callLLM._lastUsage = null;
    return { input_tokens: inputTok, output_tokens: outputTok, cost };
  }

  // Init shared memory on session (stack-based)
  if (!_cur._asMemories) {
    _cur._asMemories = _asCreateMemories();
  }
  const mem = _cur._asMemories;

  // Assign a turn ID for all steps in this call
  _cur.turnCounter++;
  const currentTurnId = _cur.turnCounter;

  const orchestratorLog = [];
  const subagentSummaries = [];
  let totalStepsExecuted = 0;
  let totalSubagents = 0;

  // Timeline event helper — push granular as_* events for tree view
  const _asSess = sessions.get(_cur.sessionId);
  const _asTlEvents = _asSess ? _asSess.timelineEvents : null;
  function _asPushTl(ev) {
    if (!_asTlEvents) return;
    ev.timestamp = Date.now();
    _asTlEvents.push(ev);
    if (isActiveFn() && _asSess) renderTimeline(_asSess);
    // Map agent spawn events to obs events
    const _asTypeMap = { as_orch_start: 'orchestrator', as_orch_decide: 'orchestrator',
      as_subagent_start: null, as_subagent_report: null, as_step: null };
    const agentType = ev.agent_type || ev.current_agent || 'orchestrator';
    const obsEvent = ev.type?.startsWith('as_') ? ev.type.replace('as_', '') : ev.type;
    const obsData = {
      event: obsEvent || ev.type, agent: agentType.toLowerCase(),
    };
    // Only include non-empty fields
    if (ev.model) obsData.model = ev.model;
    if (ev.duration_ms) obsData.duration_ms = ev.duration_ms;
    if (ev.input_tokens) obsData.input_tokens = ev.input_tokens;
    if (ev.output_tokens) obsData.output_tokens = ev.output_tokens;
    if (ev.cost) obsData.cost = ev.cost;
    if (ev.task || ev.summary) obsData.summary = ev.task || ev.summary;
    if (ev.reasoning) obsData.reasoning = ev.reasoning;
    if (ev.response) obsData.response = ev.response;
    if (ev.findings != null) obsData.findings = ev.findings;
    if (ev.hypotheses != null) obsData.hypotheses = ev.hypotheses;
    if (ev.steps_used != null) obsData.steps_used = ev.steps_used;
    if (ev.tool_name) obsData.tool_name = ev.tool_name;
    if (ev.action_name) obsData.action_name = ev.action_name;
    emitObsEvent(_asSess, obsData);
  }

  _asPushTl({ type: 'as_orch_start', turn: 0 });

  // Helper: build current context from _cur (re-read each time for fresh state)
  function _buildContext() {
    const grid = _cur.currentState.grid || [];
    const avail = _cur.currentState.available_actions || [];
    const cm = _cur.currentChangeMap || {};
    let changeMapBlock = '';
    if (typeof cm === 'object' && cm?.change_map_text) changeMapBlock = cm.change_map_text;
    else if (typeof cm === 'string' && cm) changeMapBlock = cm;
    else changeMapBlock = '(no changes)';

    return {
      game_id: _cur.currentState.game_id || 'unknown',
      state: _cur.currentState.state || '',
      step_num: _cur.stepCount || 0,
      levels_completed: _cur.currentState.levels_completed || 0,
      win_levels: _cur.currentState.win_levels || 0,
      grid, avail,
      actionDesc: avail.map(a => `${a}=${ACTION_NAMES[a] || 'ACTION' + a}`).join(', '),
      gridText: grid.length ? grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n') : '(no grid)',
      changeMapBlock,
    };
  }

  // Helper: format history with grid + change map per step
  const orchHistoryLength = parseInt(settings.orchestrator_history_length) || 10;
  function _buildHistoryBlock() {
    const hist = _cur.moveHistory || [];
    if (!hist.length) return '(none)';
    return hist.slice(-orchHistoryLength).map(h => {
      const aname = ACTION_NAMES[h.action] || '?';
      const lines = [`--- Step ${h.step || '?'}: ${aname} | levels=${h.levels || '?'} | state=${h.result_state || '?'} ---`];
      if (h.observation) lines.push(`  Observation: ${h.observation}`);
      // Include change map (full, no truncation)
      const cmText = h.change_map?.change_map_text || '';
      if (cmText && cmText !== '(no changes)' && cmText !== '(initial)') {
        lines.push(`  Changes:\n${cmText}`);
      }
      // Include full grid snapshot (RLE compressed, all rows)
      if (h.grid && h.grid.length) {
        const gridLines = h.grid.map((r, i) => `    Row ${i}: ${compressRowJS(r)}`);
        lines.push(`  Grid:\n${gridLines.join('\n')}`);
      }
      return lines.join('\n');
    }).join('\n\n');
  }

  // ── Orchestrator REPL loop ──
  for (let turn = 1; turn <= orchMaxTurns; turn++) {
    if (!isActiveFn()) break;
    // Check terminal
    if (_cur.currentState.state === 'WIN' || _cur.currentState.state === 'GAME_OVER') break;

    // Update wait label
    const label = waitEl?.querySelector('.step-label');
    if (label) {
      const timer = label.querySelector('.wait-timer');
      const spinner = label.querySelector('.spinner');
      label.innerHTML = '';
      if (spinner) label.appendChild(spinner);
      label.appendChild(document.createTextNode(`Orchestrator turn ${turn}/${orchMaxTurns}... `));
      if (timer) label.appendChild(timer);
    }

    const ctx = _buildContext();
    const turnVars = {
      game_id: ctx.game_id, step_num: ctx.step_num, levels_done: ctx.levels_completed,
      win_levels: ctx.win_levels, state_str: ctx.state, action_desc: ctx.actionDesc,
      grid_block: ctx.gridText, change_map_block: ctx.changeMapBlock,
      memories: mem.formatForPrompt(),
      history_block: _buildHistoryBlock(),
      history_length: orchHistoryLength,
    };

    const prompt = AS_ORCHESTRATOR_PREMISE + '\n\n' + AS_GAME_REFERENCE + '\n\n' + _asFill(
      `# Current State
- Game: {game_id}
- Step: {step_num}
- Level: {levels_done} / {win_levels}
- State: {state_str}
- Available actions: {action_desc}

# Grid
{grid_block}

# Change from last step
{change_map_block}

# Shared Memories
{memories}

# Recent History (last {history_length} steps with grid snapshots)
{history_block}

Decide your next move. Respond with a JSON object (delegate or think).`, turnVars);

    const t0 = performance.now();
    let raw;
    try {
      raw = await callLLM([{role: 'system', content: prompt}], orchModel, { maxTokens: orchMaxTokens, thinkingLevel: orchThinking });
    } catch (e) {
      console.error(`[agent_spawn] orchestrator turn ${turn} failed:`, e);
      orchestratorLog.push({ turn, type: 'error', error: e.message });
      break;
    }
    const durMs = Math.round(performance.now() - t0);
    const orchUsage = _asTrackUsage(orchModel, raw || '');
    const parsed = _extractJsonFromText(raw) || (() => { try { return JSON.parse(raw); } catch { return null; } })();

    if (!parsed || !parsed.command) {
      console.warn(`[agent_spawn] orchestrator turn ${turn}: unparseable response (${(raw||'').length} chars):`, raw?.substring(0, 500));
      orchestratorLog.push({ turn, type: 'error', error: 'unparseable', raw_preview: (raw||'').substring(0, 300), duration_ms: durMs });
      _asPushTl({ type: 'as_orch_think', turn, facts: 0, hypotheses: 0, duration_ms: durMs, error: 'unparseable response',
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      continue;
    }

    const command = parsed.command;

    // ── THINK ──
    if (command === 'think') {
      const facts = parsed.facts || [];
      const hypotheses = parsed.hypotheses || [];
      for (const f of facts) mem.addFact(f);
      for (const h of hypotheses) mem.addHypothesis(h);
      if (parsed.reasoning) mem.add(parsed.reasoning, '', 'orchestrator');
      orchestratorLog.push({ turn, type: 'think', facts: facts.length, hypotheses: hypotheses.length, duration_ms: durMs, raw_preview: (raw||'').substring(0, 500) });
      _asPushTl({ type: 'as_orch_think', turn, facts: facts.length, hypotheses: hypotheses.length, duration_ms: durMs, reasoning: parsed.next || parsed.reasoning || '', response: (raw||'').substring(0, 1000),
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      continue;
    }

    // ── DELEGATE ──
    if (command === 'delegate' || command === 'spawn') {
      const agentType = (['explorer', 'theorist', 'tester', 'solver'].includes(parsed.agent_type))
        ? parsed.agent_type : 'explorer';
      const task = parsed.task || 'explore the game';
      const isTheorist = agentType === 'theorist';
      const budgetLimit = isTheorist ? 0 : Math.min(parseInt(parsed.budget) || 3, maxSubBudget);
      const budget = _makeBoundedBudget(budgetLimit);

      orchestratorLog.push({ turn, type: 'delegate', agent_type: agentType, task: task.substring(0, 100), budget: budgetLimit, duration_ms: durMs, raw_preview: (raw||'').substring(0, 500) });
      _asPushTl({ type: 'as_orch_delegate', turn, agent_type: agentType, task: task.substring(0, 80), budget: budgetLimit, duration_ms: durMs, reasoning: parsed.reasoning || '', response: (raw||'').substring(0, 1000),
        input_tokens: orchUsage.input_tokens, output_tokens: orchUsage.output_tokens, cost: orchUsage.cost });
      totalSubagents++;
      const subStartCtx = _buildContext();
      _asPushTl({ type: 'as_sub_start', turn, agent_type: agentType, task: task.substring(0, 200), budget: budgetLimit, parentTurn: turn,
        step_num: subStartCtx.step_num, level: `${subStartCtx.levels_completed}/${subStartCtx.win_levels}`,
        available_actions: subStartCtx.actionDesc, memory_summary: mem.formatForPrompt().substring(0, 500),
      });

      // Update wait label
      if (label) {
        const timer = label.querySelector('.wait-timer');
        const spinner = label.querySelector('.spinner');
        label.innerHTML = '';
        if (spinner) label.appendChild(spinner);
        label.appendChild(document.createTextNode(`[${agentType}] ${task.substring(0, 40)}... `));
        if (timer) label.appendChild(timer);
      }

      // ── SUBAGENT REACTIVE LOOP (multi-turn conversation) ──
      const subActions = [];
      let toolResults = '';
      const maxIter = isTheorist ? 3 : (budgetLimit + 3); // theorist gets 3 iterations for frame_tool + report
      let subTerminal = null;

      // Build initial system prompt + first user turn
      const systemPrompt = AS_AGENT_SYSTEM[agentType] || AS_AGENT_SYSTEM.explorer;
      const subMessages = [{ role: 'system', content: systemPrompt + '\n\n' + AS_GAME_REFERENCE }];

      for (let si = 0; si < maxIter; si++) {
        if (!isActiveFn()) break;
        if (subTerminal) break;

        // Re-read current state from _cur (fresh after each _asExecuteOneStep)
        const subCtx = _buildContext();

        const subVars = {
          task,
          step_num: subCtx.step_num,
          budget_remaining: budget.remaining,
          budget_total: budget.total,
          levels_done: subCtx.levels_completed,
          win_levels: subCtx.win_levels,
          state_str: subCtx.state,
          action_desc: subCtx.actionDesc,
          grid_block: subCtx.gridText,
          change_map_block: subCtx.changeMapBlock,
          memories: mem.formatForPrompt(),
          session_history: subActions.length
            ? subActions.map((a, i) => `  ${i + 1}. ${ACTION_NAMES[a.action] || '?'}: ${a.reasoning || ''} → ${a.result || ''}`).join('\n')
            : '(none yet)',
          tool_results: toolResults ? `\n# Frame Tool Results\n${toolResults}\n` : '',
        };

        // First iteration: full context as user message. Subsequent: feedback as user message.
        if (si === 0) {
          subMessages.push({ role: 'user', content: _asFill(AS_AGENT_TURN, subVars) });
        }
        // (feedback appended at end of loop for subsequent iterations)

        let subRaw;
        try {
          subRaw = await callLLM(subMessages, subModel, { maxTokens: subMaxTokens, thinkingLevel: subThinking });
        } catch (e) {
          console.error(`[agent_spawn] ${agentType} iter ${si} failed:`, e);
          break;
        }
        const subUsage = _asTrackUsage(subModel, subRaw || '');

        const subParsed = _extractJsonFromText(subRaw) || (() => { try { return JSON.parse(subRaw); } catch { return null; } })();
        if (!subParsed || !subParsed.command) {
          console.warn(`[agent_spawn] ${agentType} iter ${si}: unparseable response (${(subRaw||'').length} chars):`, subRaw?.substring(0, 500));
          break;
        }

        // Append assistant response to conversation
        subMessages.push({ role: 'assistant', content: subRaw });

        // ── REPORT ──
        if (subParsed.command === 'report') {
          const findings = subParsed.findings || [];
          const hypotheses = subParsed.hypotheses || [];
          for (const f of findings) mem.addFact(f);
          for (const h of hypotheses) mem.addHypothesis(h);
          const summary = subParsed.summary || findings.join('; ');
          const fullDetails = [
            ...findings.map(f => `Finding: ${f}`),
            ...hypotheses.map(h => `Hypothesis: ${h}`),
          ].join('\n');
          mem.add(summary, fullDetails, agentType);
          subagentSummaries.push({ type: agentType, task: task.substring(0, 60), steps: subActions.length, summary });
          _asPushTl({ type: 'as_sub_report', turn, agent_type: agentType, findings: findings.length, hypotheses: hypotheses.length, summary, steps_used: subActions.length, response: (subRaw || '').substring(0, 2000),
            input_tokens: subUsage.input_tokens, output_tokens: subUsage.output_tokens, cost: subUsage.cost });
          break;
        }

        // ── FRAME_TOOL ──
        if (subParsed.command === 'frame_tool') {
          const toolName = subParsed.tool || 'render_grid';
          const toolArgs = subParsed.args || {};
          const prevGrid = _cur.previousGrid || null;
          const result = _asDispatchFrameTool(toolName, subCtx.grid, prevGrid, toolArgs);
          toolResults = `Tool: ${toolName}\n${result}`;
          _asPushTl({ type: 'as_sub_tool', turn, agent_type: agentType, tool_name: toolName });
          subMessages.push({ role: 'user', content: `Frame tool result:\n${toolResults}\n\nContinue with your next command.` });
          continue; // Don't count as action, loop again
        }

        // ── ACT ──
        if (subParsed.command === 'act') {
          // Theorists cannot act
          if (isTheorist) {
            const errMsg = '(ERROR: theorists cannot take game actions — use frame_tool or report)';
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          const actionId = parseInt(subParsed.action);
          const avail = new Set(subCtx.avail);
          if (isNaN(actionId) || !avail.has(actionId)) {
            const errMsg = `(ERROR: invalid action ${subParsed.action} — available: ${subCtx.actionDesc})`;
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          // Check budget
          if (!budget.use(actionId)) {
            const errMsg = '(Budget exhausted — use "report" to yield findings)';
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          // Execute the step and SEE the result
          const stepResult = await _asExecuteOneStep(
            actionId, subParsed.data || {}, subParsed.reasoning || '', agentType, _cur, isActiveFn,
            { model: subModel, usage: subUsage }
          );

          if (stepResult.error) {
            const errMsg = `(Action ${actionId} failed — game error)`;
            toolResults = errMsg;
            subMessages.push({ role: 'user', content: errMsg });
            continue;
          }

          totalStepsExecuted++;
          const actDurMs = Math.round(performance.now() - t0);

          // Build observation for the subagent
          const changeSummary = _asChangeSummary(stepResult.prevGrid, stepResult.newGrid);
          const actionName = ACTION_NAMES[actionId] || `ACTION${actionId}`;
          subActions.push({
            action: actionId,
            data: subParsed.data || {},
            reasoning: subParsed.reasoning || '',
            result: `${changeSummary}, levels=${stepResult.data.levels_completed}`,
          });
          _asPushTl({ type: 'as_sub_act', turn, agent_type: agentType, action: actionId, action_name: actionName, reasoning: (subParsed.reasoning || '').substring(0, 100), step_num: _cur.stepCount, duration_ms: actDurMs,
            input_tokens: subUsage.input_tokens, output_tokens: subUsage.output_tokens, cost: subUsage.cost });

          // Build feedback for conversation continuation
          toolResults = `Last action: ${actionName} → ${changeSummary}`;

          // Check terminal
          if (stepResult.terminal) {
            subTerminal = stepResult.terminal;
            mem.add(`Game ${stepResult.terminal} after ${actionName}`, '', agentType);
            break;
          }

          // Check budget exhaustion
          let budgetNote = '';
          if (budget.exhausted()) {
            budgetNote = '\n(Budget exhausted — next response MUST be "report")';
          }

          // Append action result as user feedback for next turn
          const nextCtx = _buildContext();
          // Include full change map (not just summary count)
          const fullChangeMap = stepResult.prevGrid && stepResult.newGrid
            ? computeChangeMapJS(stepResult.prevGrid, stepResult.newGrid)
            : null;
          const changeDetail = fullChangeMap?.change_map_text || changeSummary;
          subMessages.push({ role: 'user', content: `Action result: ${actionName} → ${changeSummary}\nState: ${nextCtx.state} | Level: ${nextCtx.levels_completed}/${nextCtx.win_levels} | Budget remaining: ${budget.remaining}\n\nChange map:\n${changeDetail}\n\nUpdated grid:\n${nextCtx.gridText}${budgetNote}\n\nContinue with your next command.` });

          continue;
        }
      }

      // If subagent didn't report, auto-summarize
      if (!subagentSummaries.find(s => s.type === agentType && s.task === task.substring(0, 60))) {
        const autoSummary = subActions.length
          ? `Executed ${subActions.length} action(s): ${subActions.map(a => ACTION_NAMES[a.action] || '?').join(', ')}`
          : (isTheorist ? 'Analysis complete' : 'No actions taken');
        mem.add(autoSummary, '', agentType);
        subagentSummaries.push({ type: agentType, task: task.substring(0, 60), steps: subActions.length, summary: autoSummary });
      }

      // If terminal, stop orchestrator loop
      if (subTerminal) {
        if (subTerminal === 'WIN' || subTerminal === 'GAME_OVER') {
          checkSessionEndAndUpload();
        }
        break;
      }

      continue; // Back to orchestrator loop
    }

    // Unknown command — treat as think
    orchestratorLog.push({ turn, type: 'unknown', command, duration_ms: durMs });
  }

  // ── Return ──
  // Steps are already executed, return empty plan
  const totalDur = Math.round(performance.now() - t0Total);
  _asPushTl({ type: 'as_orch_end', totalSteps: totalStepsExecuted, totalSubagents, duration_ms: totalDur });

  return {
    raw: '', thinking: null,
    parsed: {
      observation: `Agent Spawn — ${totalSubagents} subagent(s), ${totalStepsExecuted} step(s) executed`,
      reasoning: orchestratorLog.map(l => `Turn ${l.turn}: ${l.type}${l.agent_type ? ' (' + l.agent_type + ')' : ''}`).join(', '),
      action: 0, data: {},
      plan: [], // Empty — steps already executed via _asExecuteOneStep
    },
    model: orchModel, scaffolding: 'agent_spawn',
    _clientSide: true,
    _alreadyExecuted: true, // Signal to executePlan: no-op
    agent_spawn: {
      turn: orchestratorLog.length,
      orchestrator_log: orchestratorLog,
      subagent_summaries: subagentSummaries,
      total_steps: totalStepsExecuted,
      total_subagents: totalSubagents,
      memories: { facts: [...mem.facts], hypotheses: [...mem.hypotheses], stack: mem.stack.slice(-10) },
    },
    call_duration_ms: totalDur,
  };
}

function buildClientPrompt(state, history, changeMap, inputSettings, toolsMode, compactContext, planningMode) {
  const grid = state.grid || [];
  const parts = [];
  const desc = getPrompt('shared.arc_description');
  parts.push(`${desc}\n\nCOLOR PALETTE: ${COLOR_PALETTE}`);

  // Inject agent priors
  const priors = getPrompt('shared.agent_priors');
  if (priors) {
    parts.push(`## AGENT MEMORY\n${priors}`);
  }

  const actions = (state.available_actions || []).map(a => `${a}=${ACTION_NAMES[a] || 'ACTION'+a}`).join(', ');
  parts.push(`## STATE\nGame: ${state.game_id} | State: ${state.state} | Levels: ${state.levels_completed}/${state.win_levels}\nAvailable actions: ${actions}`);

  // Compact context replaces verbose history when active
  if (compactContext) {
    parts.push(compactContext);
  }

  if (history && history.length) {
    const reasoningTraceOn = document.getElementById('reasoningTrace')?.checked;
    const lines = history.map(h => {
      let line = `  Step ${h.step || '?'}: ${ACTION_NAMES[h.action] || '?'} -> ${h.result_state || '?'}`;
      if (h.change_map && h.change_map.change_count > 0) {
        line += ` (${h.change_map.change_count} cells changed)`;
        if (h.change_map.change_map_text) line += `\n    Changes: ${h.change_map.change_map_text}`;
      } else if (h.change_map && h.change_map.change_count === 0) {
        line += ` (no change)`;
      }
      if (h.observation) line += ` | ${h.observation}`;
      if (reasoningTraceOn && h.reasoning) line += `\n    Reasoning: ${h.reasoning}`;
      if (h.grid) {
        const rle = h.grid.map((r, i) => `    Row ${i}: ${compressRowJS(r)}`).join('\n');
        line += `\n${rle}`;
      }
      return line;
    });
    parts.push(`## HISTORY (${history.length} steps)\n` + lines.join('\n'));
  }

  if (inputSettings.diff && changeMap && changeMap.change_count > 0) {
    parts.push(`## CHANGES (${changeMap.change_count} cells changed)\n${changeMap.change_map_text || ''}`);
  }

  if (inputSettings.full_grid) {
    const gridText = grid.map((r, i) => `Row ${i}: ${compressRowJS(r)}`).join('\n');
    parts.push(`## GRID (RLE, colors 0-15)\n${gridText}`);
  }

  const tm = toolsMode === 'on';
  const pm = planningMode && planningMode !== 'off';
  const planN = pm ? parseInt(planningMode) : 0;

  const toolInstr = tm ? `\n- You can write Python code blocks to analyse the grid. Wrap code in \\\`\\\`\\\`python fences. The variable \`grid\` is a numpy 2D int array. numpy, collections, itertools, math are available. Use print() for output. Code will be executed and results appended before your final answer.\n- Include "analysis" in your JSON with a summary of what you found.` : '';
  const analysisField = tm ? ', "analysis": "<detailed spatial analysis>"' : '';

  const interruptOn = document.getElementById('interruptPlan')?.checked;
  const expectedField = (pm && interruptOn) ? ', "expected": "<what you expect to see after this plan>"' : '';
  const expectedRule = (pm && interruptOn) ? '\n- "expected": briefly describe what you expect after the plan completes (e.g. "character at the door", "score increased").' : '';

  if (pm) {
    parts.push(`## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Plan a sequence of actions (up to ${planN} steps).

Respond with EXACTLY this JSON (nothing else):
{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{"action": <n>, "data": {}}, ...]${analysisField}${expectedField}}

Rules:
- Return a "plan" array of up to ${planN} steps. Each step has "action" (0-7) and "data" ({} or {"x": <0-63>, "y": <0-63>}).
- ACTION6: set "data" to {"x": <0-63>, "y": <0-63>}.
- Other actions: set "data" to {}.${expectedRule}${toolInstr}`);
  } else {
    parts.push(`## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {}${analysisField}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {"x": <0-63>, "y": <0-63>}.
- Other actions: set "data" to {}.${toolInstr}`);
  }

  return parts.join('\n\n');
}

function parseClientLLMResponse(content, modelName) {
  let thinking = '';
  const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/);
  if (thinkMatch) {
    thinking = thinkMatch[1].trim();
    content = content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  }
  // Extract JSON using balanced-brace matching
  // Strip comments first, then find each top-level { } block via brace counting
  const cleaned = content.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan) {
            return { raw: content, thinking: thinking ? thinking.substring(0, 500) : null, parsed, model: modelName };
          }
        } catch {}
        break;
      }}
    }
  }
  return { raw: content, parsed: null, model: modelName };
}

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE LLM PROVIDERS (Puter.js + BYOK)
// ═══════════════════════════════════════════════════════════════════════════

// Lazy-load Puter.js SDK on demand
let _puterJsLoading = null;
function loadPuterJS() {
  if (typeof puter !== 'undefined') return Promise.resolve();
  if (_puterJsLoading) return _puterJsLoading;
  _puterJsLoading = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://js.puter.com/v2/';
    s.onload = () => resolve();
    s.onerror = () => { _puterJsLoading = null; reject(new Error('Failed to load Puter.js')); };
    document.head.appendChild(s);
  });
  return _puterJsLoading;
}


function getByokKey(provider) {
  // New per-provider keys
  const key = localStorage.getItem(`byok_key_${provider}`);
  if (key) return key;
  // Legacy fallback
  const oldProvider = localStorage.getItem('byok_provider');
  if (oldProvider === provider) return localStorage.getItem('byok_key') || '';
  return '';
}

function byokActive() {
  // Check if any provider has a saved key
  for (const p of ['openai', 'gemini', 'anthropic', 'groq', 'mistral', 'cloudflare']) {
    if (localStorage.getItem(`byok_key_${p}`)) return true;
  }
  // Legacy check
  return !!(localStorage.getItem('byok_key'));
}

const THINKING_BUDGETS = { off: 0, low: 1024, med: 4096, high: 8192, max: 24576 };

function _geminiThinkingConfig(apiModel) {
  const isThinking = /2\.5|3-pro|3-flash|3\.1/.test(apiModel);
  if (!isThinking) return {};
  const budget = THINKING_BUDGETS[getThinkingLevel()] ?? 1024;
  return { thinkingConfig: { thinkingBudget: budget } };
}



// ═══════════════════════════════════════════════════════════════════════════
// COPILOT AUTH (local only)
// ═══════════════════════════════════════════════════════════════════════════

let copilotPollTimer = null;

async function copilotStartAuth() {
  try {
    const data = await fetchJSON('/api/copilot/auth/start', {});
    if (data.error) { alert(data.error); return; }
    document.getElementById('copilotDeviceCode').style.display = 'block';
    document.getElementById('copilotUserCode').textContent = data.user_code;
    const link = document.getElementById('copilotVerifyLink');
    link.href = data.verification_uri;
    link.textContent = `Open ${data.verification_uri}`;
    // Start polling
    const interval = (data.interval || 5) * 1000;
    copilotPollTimer = setInterval(() => copilotPollAuth(), interval);
  } catch (e) { alert('Copilot auth error: ' + e.message); }
}

async function copilotPollAuth() {
  try {
    const data = await fetchJSON('/api/copilot/auth/poll', {});
    if (data.status === 'authenticated') {
      clearInterval(copilotPollTimer);
      copilotPollTimer = null;
      document.getElementById('copilotNotAuth').style.display = 'none';
      document.getElementById('copilotAuthed').style.display = 'block';
      loadModels(); // Refresh model list to include Copilot models
    } else if (data.status === 'slow_down') {
      // Slow down polling
      clearInterval(copilotPollTimer);
      copilotPollTimer = setInterval(() => copilotPollAuth(), (data.interval || 10) * 1000);
    }
    // 'pending' → keep polling
  } catch {}
}

async function checkCopilotStatus() {
  if (!FEATURES.copilot) return;
  try {
    const data = await fetchJSON('/api/copilot/auth/status');
    if (data.authenticated) {
      document.getElementById('copilotNotAuth').style.display = 'none';
      document.getElementById('copilotAuthed').style.display = 'block';
    }
  } catch {}
}

