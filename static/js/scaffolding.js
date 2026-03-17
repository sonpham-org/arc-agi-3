// Author: Claude Opus 4.6 (1M context)
// Date: 2026-03-16 00:00
// PURPOSE: Core scaffolding infrastructure for ARC-AGI-3 web UI. Handles API mode
//   switching (local vs official), model discovery (loadModels + LM Studio via direct browser fetch),
//   model select population, BYOK key management, LLM call routing (callLLM → _callLLMInner
//   for Puter.js, Gemini, Anthropic, OpenAI, Cloudflare, Groq, Mistral, HuggingFace, LM Studio),
//   prompt template loading (getPrompt), grid representation encoders (gridToLexical/LP16,
//   gridToNumeric, gridToRgbAgent, formatGrid dispatcher), and Anthropic prompt caching via cache_control.
//   Phase 5 extracted scaffolding-specific logic into scaffolding-rlm.js,
//   scaffolding-three-system.js, scaffolding-agent-spawn.js, and scaffolding-linear.js.
//   Phase 3 extracted JSON parsing to utils/json-parsing.js.
// SRP/DRY check: Pass — scaffolding types in separate files; JSON parsing in json-parsing.js;
//   tokens in utils/tokens.js; this file is the shared LLM call infrastructure
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

/** Append model optgroups to a select WITHOUT clearing existing options.
 *  Used for compact/interrupt selects that have static options (auto, same, etc.). */
function _appendModelOptgroups(sel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder) {
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
}

function _populateSubModelSelect(sel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, savedVal) {
  sel.innerHTML = '';
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

/** LM Studio discovery — runs in background, doesn't block init */
async function _discoverLmStudioAsync() {
  try {
    const lmsBaseUrl = (localStorage.getItem('byok_lmstudio_base_url') || 'http://localhost:1234').replace(/\/$/, '');
    const lmsResp = await fetch(`${lmsBaseUrl}/v1/models`, { signal: AbortSignal.timeout(3000) });
    if (!lmsResp.ok) return;
    const lmsData = await lmsResp.json();
    const existingLms = new Set(modelsData.filter(m => m.provider === 'lmstudio').map(m => m.api_model));
    let added = 0;
    for (const m of (lmsData.data || [])) {
      const mid = m.id || '';
      if (!mid || mid.toLowerCase().includes('embedding') || existingLms.has(mid)) continue;
      const caps = LMSTUDIO_CAPABILITIES[mid] || { reasoning: false, image: false };
      modelsData.push({
        name: mid, api_model: mid, provider: 'lmstudio',
        price: 'Free (local)', context_window: 8192,
        capabilities: { ...caps, tools: false }, available: true,
      });
      added++;
    }
    if (added > 0) {
      localStorage.setItem('byok_key_lmstudio', 'local-no-key-needed');
      // Re-populate model selects with newly discovered models
      _populateAllModelSelects();
    }
  } catch (e) {
    if (e.name !== 'AbortError') console.warn('[LM Studio discovery] client-side fetch failed:', e.message);
  }
}

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
  // Runs in background to avoid blocking app init (fetch can take up to 15s if LM Studio
  // is not running). Results are merged into model selects asynchronously.
  _discoverLmStudioAsync();

  _populateAllModelSelects();
}

/** Populate all model <select> elements from modelsData. Called by loadModels() and async LM Studio discovery. */
function _populateAllModelSelects() {
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

  // Populate compact model selector — keep default options, add all models.
  // Cannot use _populateSubModelSelect here because it clears innerHTML,
  // which would wipe the static options (auto, auto-fastest, same).
  const csel = document.getElementById('compactModelSelectTop');
  if (!csel) { /* compact select not in current scaffolding */ } else {
  const savedVal = csel.value;
  csel.querySelectorAll('optgroup').forEach(g => g.remove());
  _appendModelOptgroups(csel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder);
  if (savedVal && [...csel.options].some(o => o.value === savedVal)) csel.value = savedVal;
  } // end compact select block

  // Populate interrupt model selector — same pattern (has static options too)
  const isel = document.getElementById('interruptModelSelect');
  if (!isel) { /* interrupt select not in current scaffolding */ } else {
  const iSavedVal = isel.value;
  isel.querySelectorAll('optgroup').forEach(g => g.remove());
  _appendModelOptgroups(isel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder);
  if (iSavedVal && [...isel.options].some(o => o.value === iSavedVal)) isel.value = iSavedVal;
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
  } catch (e) { console.warn('[scaffolding] localStorage restore RLM settings error:', e.message); }

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
  } catch (e) { console.warn('[scaffolding] localStorage restore Three-System settings error:', e.message); }

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
  } catch (e) { console.warn('[scaffolding] localStorage restore Two-System settings error:', e.message); }

  // Populate World Model harness model selects if they exist
  for (const wmSelId of ['sf_wm_agentModelSelect', 'sf_wm_wmModelSelect']) {
    const wmSel = document.getElementById(wmSelId);
    if (!wmSel) continue;
    const wmSaved = wmSel.value;
    wmSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(wmSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, wmSaved);
  }
  // Restore World Model model selections from saved settings
  try {
    const wmRaw = localStorage.getItem('arc_scaffolding_world_model');
    if (wmRaw) {
      const wmS = JSON.parse(wmRaw);
      const wmMap = {
        sf_wm_agentModelSelect: wmS.model,
        sf_wm_wmModelSelect: wmS.wm_model,
      };
      for (const [id, val] of Object.entries(wmMap)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch (e) { console.warn('[scaffolding] localStorage restore World Model settings error:', e.message); }

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
  } catch (e) { console.warn('[scaffolding] localStorage restore Agent Spawn settings error:', e.message); }

  // Populate RGB model selects if they exist
  for (const rgbSelId of ['sf_rgb_analyzerModelSelect']) {
    const rgbSel = document.getElementById(rgbSelId);
    if (!rgbSel) continue;
    const rgbSaved = rgbSel.value;
    rgbSel.innerHTML = '<option value="">Select a model...</option>';
    _populateSubModelSelect(rgbSel, groups, providerOrder, providerLabels, byokGroups, byokProviderOrder, rgbSaved);
  }
  // Restore RGB model selections from saved settings
  try {
    const rgbRaw = localStorage.getItem('arc_scaffolding_rgb');
    if (rgbRaw) {
      const rgbS = JSON.parse(rgbRaw);
      const rgbMap = { sf_rgb_analyzerModelSelect: rgbS.model };
      for (const [id, val] of Object.entries(rgbMap)) {
        const el = document.getElementById(id);
        if (el && val && [...el.options].some(o => o.value === val)) el.value = val;
      }
    }
  } catch {}

  updateModelCaps();
  // Sync main model to sub-selects on initial load
  const mainVal = document.getElementById('modelSelect')?.value || '';
  if (mainVal) syncModelToSubSelects(mainVal);
  updateAllByokKeys();

  // Sync cascade last-vals so the first cascade after restore uses the
  // correct previous value (not the empty-string set at listener-setup time).
  for (const id of ['sf_ts_plannerModelSelect', 'sf_2s_plannerModelSelect',
                     'sf_wm_agentModelSelect', 'sf_as_orchestratorModelSelect']) {
    const el = document.getElementById(id);
    if (el) el.dataset.cascadeLastVal = el.value;
  }

  // Apply local model token caps for any restored local model selections.
  if (typeof applyAllLocalModelTokenCaps === 'function') applyAllLocalModelTokenCaps();
}

// ═══════════════════════════════════════════════════════════════════════════
// CLIENT-SIDE PROMPT BUILDING (for Puter.js / BYOK — online mode)
// ═══════════════════════════════════════════════════════════════════════════

// ── Prompt templates loaded from server (prompts/*.txt) ──

function getPrompt(key) {
  const [section, name] = key.split('.');
  return localStorage.getItem('arc_prompt.' + key)
      || (window.PROMPTS && window.PROMPTS[section] && window.PROMPTS[section][name])
      || '';
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
// GRID REPRESENTATION ENCODERS
// Three formats: LP16 (lexical mnemonic), Numeric (integers), RGB-Agent (density)
// ═══════════════════════════════════════════════════════════════════════════

// ── LP16: Lexical Grid Encoding (LexicalColorPalette16-inspired) ──
// Maps ARC3 color indices 0-15 to single mnemonic characters.
// Produces a 64×64 character grid that preserves spatial layout.
const ARC3_LEXICAL_MAP = ['.','1','2','3','4','K','M','m','R','B','b','Y','O','r','G','P'];
const ARC3_LEXICAL_LEGEND = '.=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray K=Black M=Magenta m=LightMagenta R=Red B=Blue b=LightBlue Y=Yellow O=Orange r=Maroon G=Green P=Purple';

function gridToLexical(grid) {
  if (!grid || !grid.length) return '';
  return grid.map(row => row.map(c => ARC3_LEXICAL_MAP[c] ?? '?').join('')).join('\n');
}

// ── Numeric: Space-separated integer grid ──
// Each row is space-separated color indices: "0 0 5 5 0 14 14 0"
function gridToNumeric(grid) {
  if (!grid || !grid.length) return '';
  return grid.map(row => row.join(' ')).join('\n');
}

// ── RGB-Agent: ASCII density ramp ──
// Maps 0-15 linearly into a 70-char density string (from dense to light).
// Based on alexisfox7/RGB-Agent. Encodes index as brightness — discards color identity.
const _RGB_DENSITY = '$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1EG[]?-_+~<>i!lI;:,"^`\'. ';

function gridToRgbAgent(grid) {
  if (!grid || !grid.length) return '';
  const n = _RGB_DENSITY.length;
  return grid.map(row => row.map(v => {
    const idx = Math.min(Math.floor((Math.max(0, Math.min(15, v)) / 16) * (n - 1)), n - 1);
    return _RGB_DENSITY[idx];
  }).join('')).join('\n');
}

// ── Dispatcher: format grid using selected representation ──
// repr: 'lp16' | 'numeric' | 'rgb'
function formatGrid(grid, repr) {
  if (!grid || !grid.length) return '(empty grid)';
  switch (repr) {
    case 'numeric': return gridToNumeric(grid);
    case 'rgb':     return gridToRgbAgent(grid);
    case 'lp16':
    default:        return gridToLexical(grid);
  }
}

// ── Grid representation legends for system prompts ──
const GRID_REPR_LEGENDS = {
  lp16: `LEXICAL GRID LEGEND: ${ARC3_LEXICAL_LEGEND}`,
  numeric: 'NUMERIC GRID: Each row is space-separated color indices (0-15).',
  rgb: 'RGB-AGENT GRID: ASCII density ramp — darker chars = lower index, lighter = higher. Index identity only, not color.',
};

function getGridReprLegend(repr) {
  return GRID_REPR_LEGENDS[repr] || GRID_REPR_LEGENDS.lp16;
}

// ── Grid repr label for prompt section headers ──
const GRID_REPR_LABELS = { lp16: '64×64 lexical', numeric: '64×64 numeric', rgb: '64×64 rgb-agent' };
function getGridReprLabel(repr) { return GRID_REPR_LABELS[repr] || GRID_REPR_LABELS.lp16; }

// ── [Section extracted to scaffolding-rlm.js] ───────────────────────────

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
  callLLM._lastTruncated = false;
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
          } catch (e) { console.warn('[scaffolding] Gemini SSE JSON parse error:', e.message); }
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
      if (fr === 'MAX_TOKENS') callLLM._lastTruncated = true;
      return text;
    }
  }

  // ── OpenAI-compatible (OpenAI, Groq, Mistral) ──
  if (provider === 'openai' || provider === 'groq' || provider === 'mistral') {
    const urls = { openai: 'https://api.openai.com/v1/chat/completions', groq: 'https://api.groq.com/openai/v1/chat/completions', mistral: 'https://api.mistral.ai/v1/chat/completions' };
    // o-series and codex models require max_completion_tokens (not max_tokens) and omit temperature
    const isOSeries = provider === 'openai' && /^(o1|o3|o4|codex)/.test(apiModel);
    const bodyParams = isOSeries
      ? { model: apiModel, messages: messages.map(m => ({ role: m.role, content: m.content })), max_completion_tokens: maxTokens }
      : { model: apiModel, messages: messages.map(m => ({ role: m.role, content: m.content })), temperature: 0.3, max_tokens: maxTokens };
    const resp = await fetch(urls[provider], {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}` },
      body: JSON.stringify(bodyParams),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(`${resp.status} ${data.error?.message || JSON.stringify(data.error || resp.statusText)}`);
    callLLM._lastUsage = data.usage ? { input_tokens: data.usage.prompt_tokens || 0, output_tokens: data.usage.completion_tokens || 0 } : null;
    return data.choices?.[0]?.message?.content || '';
  }

  // ── Anthropic (with prompt caching) ──
  if (provider === 'anthropic') {
    const systemMsg = messages.find(m => m.role === 'system');
    const chatMsgs = messages.filter(m => m.role !== 'system');
    // Pre-flight: estimate tokens and warn if likely to exceed context window
    const modelCtx = getModelInfo(model)?.context_window || 200000;
    const allText = messages.map(m => (m._cacheablePrefix || '') + (m._cacheableHistory || '') + m.content).join('');
    const estTokens = estimateTokens(allText);
    if (estTokens > modelCtx * 0.95) {
      throw new Error(`Prompt too long (~${Math.round(estTokens/1000)}K tokens) for ${model} (${Math.round(modelCtx/1000)}K limit). Enable Compact Context or reduce history.`);
    }
    // Prompt caching: Anthropic prefix caching matches an exact token prefix.
    // Three cache breakpoints are set (most stable → least stable):
    //   1. System message — static per session (game description, task instructions)
    //   2. Compact context prefix — stable between compaction cycles (~5 calls)
    //   3. Old history — all history entries except the latest (identical to previous call)
    // Dynamic content (new step, STATE, GRID, CHANGES) comes last to maximize prefix matching.
    const body = { model: apiModel, max_tokens: maxTokens, messages: chatMsgs.map(m => {
      if (m.role === 'user' && (m._cacheablePrefix || m._cacheableHistory)) {
        const blocks = [];
        if (m._cacheablePrefix) {
          blocks.push({ type: 'text', text: m._cacheablePrefix, cache_control: { type: 'ephemeral' } });
        }
        if (m._cacheableHistory) {
          blocks.push({ type: 'text', text: m._cacheableHistory, cache_control: { type: 'ephemeral' } });
        }
        blocks.push({ type: 'text', text: m.content });
        return { role: 'user', content: blocks };
      }
      return { role: m.role, content: m.content };
    }) };
    if (systemMsg) {
      body.system = [{ type: 'text', text: systemMsg.content, cache_control: { type: 'ephemeral' } }];
    }
    const isOAuth = key.startsWith('sk-ant-oat');
    let resp;
    if (isOAuth) {
      // OAuth tokens can't go direct (CORS preflight fails) — proxy through server
      body.api_key = key;
      resp = await fetch('/api/llm/anthropic-proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } else {
      resp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify(body),
      });
    }
    const data = await resp.json();
    if (!resp.ok || data.error) {
      const errMsg = data.error?.message || JSON.stringify(data.error || resp.statusText);
      if (resp.status === 400 && errMsg.includes('too long')) {
        throw new Error(`Prompt too long for ${model}. Enable Compact Context in settings or reduce history length.`);
      }
      throw new Error(`${resp.status} ${errMsg}`);
    }
    callLLM._lastUsage = data.usage ? {
      input_tokens: data.usage.input_tokens || 0,
      output_tokens: data.usage.output_tokens || 0,
      cache_creation_input_tokens: data.usage.cache_creation_input_tokens || 0,
      cache_read_input_tokens: data.usage.cache_read_input_tokens || 0,
    } : null;
    if (data.usage?.cache_read_input_tokens > 0) {
      console.log(`[Anthropic] Cache hit: ${data.usage.cache_read_input_tokens} tokens read from cache`);
    }
    return data.content?.map(c => c.text).filter(Boolean).join('') || '';
  }

  // ── LM Studio (local, via server CORS proxy) ──
  // LM Studio does NOT send CORS headers, so the browser can't call localhost:1234
  // directly. Instead we route through /api/llm/lmstudio-proxy on our own server,
  // which forwards to localhost:1234 server-to-server (no CORS needed). Same pattern
  // as the Cloudflare proxy. The dummy key 'local-no-key-needed' was set in
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
    if (data.choices?.[0]?.finish_reason === 'length') callLLM._lastTruncated = true;
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
callLLM._lastTruncated = false;

// ── [Section extracted to scaffolding-rlm.js continued] ────────────────

// ── [Section extracted to scaffolding-three-system.js] ─────────────────

// ── [Section extracted to scaffolding-agent-spawn.js] ──────────────────

// ── [Section extracted to scaffolding-linear.js] ────────────────────────


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
  } catch (e) { console.warn('[scaffolding] Copilot poll auth error:', e.message); }
}

async function checkCopilotStatus() {
  if (!FEATURES.copilot) return;
  try {
    const data = await fetchJSON('/api/copilot/auth/status');
    if (data.authenticated) {
      document.getElementById('copilotNotAuth').style.display = 'none';
      document.getElementById('copilotAuthed').style.display = 'block';
    }
  } catch (e) { console.warn('[scaffolding] Copilot status check error:', e.message); }
}

