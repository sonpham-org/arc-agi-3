// ═══════════════════════════════════════════════════════════════════════════
// ui-models.js — Model management UI
// Extracted from ui.js (Phase 24)
// Purpose: Model selector population, model info display, BYOK key management
// ═══════════════════════════════════════════════════════════════════════════

// Provider name mapping for BYOK prompt
const PROVIDER_LABELS = {
  gemini: 'Google Gemini', anthropic: 'Anthropic', openai: 'OpenAI',
  cloudflare: 'Cloudflare', groq: 'Groq', mistral: 'Mistral', huggingface: 'Huggingface',
  local: 'Local Model', ollama: 'Ollama',
};

// ── Centralized BYOK Key Management ──
// Scans ALL model selects, collects unique providers, renders key inputs dynamically.
// Called on any model select change. Future-proof: no per-scaffold wiring needed.

const _BYOK_FREE_PROVIDERS = new Set(['puter', 'copilot', 'ollama', 'local']);
const _BYOK_PROVIDER_EXTRA_FIELDS = {
  cloudflare: [{ key: 'byok_cf_account_id', label: 'Cloudflare Account ID', placeholder: 'Paste Account ID here...', hint: 'Found in Cloudflare dashboard → Workers & Pages.', type: 'password' }],
};

function getSelectedModel() {
  if (activeScaffoldingType === 'rlm') {
    return document.getElementById('sf_rlm_modelSelect')?.value || '';
  }
  if (activeScaffoldingType === 'three_system') {
    return document.getElementById('sf_ts_plannerModelSelect')?.value || '';
  }
  if (activeScaffoldingType === 'two_system') {
    return document.getElementById('sf_2s_plannerModelSelect')?.value || '';
  }
  if (activeScaffoldingType === 'agent_spawn') {
    return document.getElementById('sf_as_orchestratorModelSelect')?.value || '';
  }
  return document.getElementById('modelSelect')?.value || '';
}

function getModelInfo(key) {
  return modelsData.find(m => m.name === key);
}

function updateAllByokKeys() {
  const container = document.getElementById('byokKeysContainer');
  if (!container) return;

  // 1. Collect all model select IDs (main + compact + interrupt + all scaffold sub-selects)
  const allSelectIds = ['modelSelect', 'compactModelSelectTop', 'interruptModelSelect',
    'sf_rlm_modelSelect', 'sf_rlm_subModelSelect',
    'sf_ts_plannerModelSelect', 'sf_ts_monitorModelSelect', 'sf_ts_wmModelSelect',
    'sf_2s_plannerModelSelect', 'sf_2s_monitorModelSelect',
    'sf_as_orchestratorModelSelect', 'sf_as_subagentModelSelect'];

  // 2. Collect unique providers that need keys
  const neededProviders = new Set();
  for (const selId of allSelectIds) {
    const val = document.getElementById(selId)?.value;
    if (!val || val === 'auto' || val === 'auto-fastest' || val === 'same') continue;
    const info = getModelInfo(val);
    if (info && !_BYOK_FREE_PROVIDERS.has(info.provider)) {
      neededProviders.add(info.provider);
    }
  }

  // 3. Build HTML for each provider (preserving existing input values)
  // Save current values before rebuilding
  const savedValues = {};
  container.querySelectorAll('input[data-byok-provider]').forEach(inp => {
    savedValues[inp.dataset.byokProvider] = inp.value;
  });
  container.querySelectorAll('input[data-byok-extra]').forEach(inp => {
    savedValues[inp.dataset.byokExtra] = inp.value;
  });

  if (neededProviders.size === 0) {
    container.innerHTML = '<div style="padding:8px 0;font-size:11px;color:var(--text-dim);font-style:italic;">Required keys will appear when models are selected.</div>';
    return;
  }

  let html = '';
  for (const provider of neededProviders) {
    const label = PROVIDER_LABELS[provider] || provider;
    const saved = savedValues[provider] || localStorage.getItem(`byok_key_${provider}`) || '';
    html += `<div style="margin-bottom:8px;">`;
    html += `<div style="font-size:10px;color:var(--dim);margin-bottom:3px;text-transform:uppercase;letter-spacing:0.5px;">${label} API Key</div>`;
    html += `<input type="password" class="text-input" data-byok-provider="${provider}" value="${saved.replace(/"/g, '&quot;')}" placeholder="Paste API key for ${label} here..." style="margin-bottom:4px;">`;
    // Extra fields (e.g. Cloudflare Account ID)
    const extras = _BYOK_PROVIDER_EXTRA_FIELDS[provider] || [];
    for (const extra of extras) {
      const extraSaved = savedValues[extra.key] || localStorage.getItem(extra.key) || '';
      html += `<div style="font-size:10px;color:var(--dim);margin-bottom:3px;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px;">${extra.label}</div>`;
      html += `<input type="${extra.type || 'text'}" class="text-input" data-byok-extra="${extra.key}" value="${extraSaved.replace(/"/g, '&quot;')}" placeholder="${extra.placeholder}" style="margin-bottom:2px;">`;
      if (extra.hint) html += `<div style="font-size:9px;color:var(--dim);font-style:italic;">${extra.hint}</div>`;
    }
    html += `<div style="font-size:9px;color:var(--dim);font-style:italic;">Key stored locally only — never sent to our server.</div></div>`;
  }
  container.innerHTML = html;

  // Persist BYOK keys and extra fields to localStorage on input
  container.querySelectorAll('input[data-byok-provider]').forEach(inp => {
    inp.addEventListener('input', e => {
      localStorage.setItem(`byok_key_${e.target.dataset.byokProvider}`, e.target.value);
    });
  });
  container.querySelectorAll('input[data-byok-extra]').forEach(inp => {
    inp.addEventListener('input', e => {
      localStorage.setItem(e.target.dataset.byokExtra, e.target.value);
    });
  });

  // Auto-open Model Keys section
  const sec = document.getElementById('secKeys');
  if (sec && !sec.classList.contains('open')) sec.classList.add('open');
}

function updateModelCaps() {
  const key = getSelectedModel();
  const info = getModelInfo(key);
  const caps = info?.capabilities || {};
  const el = document.getElementById('modelCaps');

  if (el) {
    const badges = [];
    if (caps.image) badges.push('<span class="opt-badge badge-img">IMAGE</span>');
    else badges.push('<span class="opt-badge badge-off">no image</span>');
    if (caps.reasoning) badges.push('<span class="opt-badge badge-reason">REASONING</span>');
    if (caps.tools) badges.push('<span class="opt-badge badge-tools">TOOLS</span>');
    el.innerHTML = badges.join(' ');
  }

  // Disable image toggle if model doesn't support it
  const imgToggle = document.getElementById('inputImage');
  const imgRow = document.getElementById('imageRow');
  if (imgToggle && imgRow) {
    if (!caps.image) {
      imgToggle.checked = false;
      imgToggle.disabled = true;
      imgRow.classList.add('disabled');
    } else {
      imgToggle.disabled = false;
      imgRow.classList.remove('disabled');
    }
  }
}
