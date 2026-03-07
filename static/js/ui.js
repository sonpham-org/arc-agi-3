// ═══════════════════════════════════════════════════════════════════════════
// COLLAPSIBLE SECTIONS
// ═══════════════════════════════════════════════════════════════════════════

function toggleSection(id) {
  document.getElementById(id).classList.toggle('open');
}

function toggleCompactSettings() {
  const on = document.getElementById('compactContext')?.checked;
  const body = document.getElementById('compactSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function toggleInterruptSettings() {
  const on = document.getElementById('interruptPlan')?.checked;
  const body = document.getElementById('interruptSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function switchTopTab(tab) {
  // History tab removed — this is now a no-op kept for compat with resume/branch code
  if (tab === 'agent') switchSubTab('settings');
}

function switchSubTab(tab) {
  // Reasoning/timeline tabs removed — redirect to settings
  if (tab === 'reasoning' || tab === 'timeline') tab = 'settings';
  document.querySelectorAll('.subtab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.subtab-pane').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  const tabMap = { settings: 'subtabSettings', prompts: 'subtabPrompts', graphics: 'subtabGraphics' };
  const buttons = document.querySelectorAll('.subtab-bar button');
  const idx = { settings: 0, prompts: 1, graphics: 2 }[tab] || 0;
  if (buttons[idx]) buttons[idx].classList.add('active');
  const pane = document.getElementById(tabMap[tab]);
  if (pane) { pane.classList.add('active'); pane.style.display = 'flex'; }
  if (tab === 'prompts') renderPromptsTab();
}

function toggleAdBanner() {
  const banner = document.getElementById('adBanner');
  const showBtn = document.getElementById('adShowBtn');
  const hidden = !banner.classList.contains('hidden');
  banner.classList.toggle('hidden', hidden);
  showBtn.style.display = hidden ? 'block' : 'none';
  try { localStorage.setItem('adHidden', hidden ? '1' : ''); } catch {}
}
// Restore ad preference
try { if (localStorage.getItem('adHidden') === '1') toggleAdBanner(); } catch {}


// ═══════════════════════════════════════════════════════════════════════════
// GRAPHICS LISTENERS
// ═══════════════════════════════════════════════════════════════════════════

document.getElementById('changeOpacity').addEventListener('input', (e) => {
  document.getElementById('changeOpacityVal').textContent = e.target.value + '%';
  redrawGrid();
});
document.getElementById('showChanges').addEventListener('change', redrawGrid);
document.getElementById('changeColor').addEventListener('input', redrawGrid);

function showTransportDesc(text) {
  document.getElementById('transportDesc').textContent = text;
}
function clearTransportDesc() {
  document.getElementById('transportDesc').textContent = '';
}

function redrawGrid() {
  if (!currentGrid) return;
  if (currentChangeMap && currentChangeMap.change_count > 0 && document.getElementById('showChanges').checked) {
    renderGridWithChanges(currentGrid, currentChangeMap);
  } else {
    renderGrid(currentGrid);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MODEL CAPABILITIES → auto-disable image toggle
// ═══════════════════════════════════════════════════════════════════════════

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

  // Auto-open Model Keys section
  const sec = document.getElementById('secKeys');
  if (sec && !sec.classList.contains('open')) sec.classList.add('open');
}

// Auto-save BYOK keys on input (single delegated listener)
document.addEventListener('input', (e) => {
  if (e.target.dataset.byokProvider) {
    localStorage.setItem(`byok_key_${e.target.dataset.byokProvider}`, e.target.value.trim());
    return;
  }
  if (e.target.dataset.byokExtra) {
    localStorage.setItem(e.target.dataset.byokExtra, e.target.value.trim());
    return;
  }
});


function getModelInfo(key) {
  return modelsData.find(m => m.name === key);
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

// Moved to attachSettingsListeners() — called after renderScaffoldingSettings()

function updateModelEta() { /* removed — countdown/ETA disabled */ }

// ═══════════════════════════════════════════════════════════════════════════
// RENDERING
// ═══════════════════════════════════════════════════════════════════════════

function renderGrid(grid) {
  if (!grid || !grid.length) return;
  currentGrid = grid;
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
  if (!changeMap?.changes?.length) return;
  if (!document.getElementById('showChanges').checked) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  const opacity = parseInt(document.getElementById('changeOpacity').value) / 100;
  const color = document.getElementById('changeColor').value;
  const r = parseInt(color.slice(1,3), 16), g = parseInt(color.slice(3,5), 16), b = parseInt(color.slice(5,7), 16);
  ctx.fillStyle = `rgba(${r},${g},${b},${opacity})`;
  for (const c of changeMap.changes) ctx.fillRect(c.x * scale, c.y * scale, scale, scale);
  ctx.strokeStyle = `rgba(${r},${g},${b},${Math.min(opacity + 0.3, 1)})`;
  ctx.lineWidth = 1;
  for (const c of changeMap.changes) ctx.strokeRect(c.x * scale + 0.5, c.y * scale + 0.5, scale - 1, scale - 1);
}

// ═══════════════════════════════════════════════════════════════════════════
// COORDINATE TOOLTIP & HIGHLIGHT
// ═══════════════════════════════════════════════════════════════════════════

let _canvasHoverCell = null;  // {row, col} of cell under cursor

function drawCanvasHover(row, col) {
  if (!currentGrid) return;
  const h = currentGrid.length, w = currentGrid[0].length;
  if (row < 0 || row >= h || col < 0 || col >= w) return;
  const scale = Math.floor(512 / Math.max(h, w));
  ctx.save();
  ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
  ctx.fillRect(col * scale, row * scale, scale, scale);
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
  ctx.lineWidth = 1;
  ctx.strokeRect(col * scale + 0.5, row * scale + 0.5, scale - 1, scale - 1);
  ctx.restore();
}

canvas.addEventListener('mousemove', (e) => {
  const tip = document.getElementById('coordTooltip');
  if (!currentGrid) { tip.style.display = 'none'; _canvasHoverCell = null; return; }
  const rect = canvas.getBoundingClientRect();
  const h = currentGrid.length, w = currentGrid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  const gx = Math.floor((e.clientX - rect.left) * (canvas.width / rect.width) / scale);
  const gy = Math.floor((e.clientY - rect.top) * (canvas.height / rect.height) / scale);
  if (gx < 0 || gx >= w || gy < 0 || gy >= h) {
    tip.style.display = 'none';
    if (_canvasHoverCell) { _canvasHoverCell = null; renderGrid(currentGrid); }
    return;
  }
  // Tooltip
  if (document.getElementById('coordToggle').checked) {
    tip.textContent = `(${gy}, ${gx})`;
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY - 8) + 'px';
  } else {
    tip.style.display = 'none';
  }
  // Cell hover highlight
  if (!_canvasHoverCell || _canvasHoverCell.row !== gy || _canvasHoverCell.col !== gx) {
    _canvasHoverCell = {row: gy, col: gx};
    renderGrid(currentGrid);
    if (_highlightCells.length) drawCellHighlights(_highlightCells);
    drawCanvasHover(gy, gx);
  }
});

canvas.addEventListener('mouseleave', () => {
  document.getElementById('coordTooltip').style.display = 'none';
  if (_canvasHoverCell) {
    _canvasHoverCell = null;
    renderGrid(currentGrid);
    if (_highlightCells.length) drawCellHighlights(_highlightCells);
  }
});

let _highlightCells = [];

function drawCellHighlights(cells) {
  if (!cells.length || !currentGrid) return;
  const h = currentGrid.length, w = currentGrid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  ctx.save();
  for (const {row, col} of cells) {
    if (row < 0 || row >= h || col < 0 || col >= w) continue;
    ctx.fillStyle = 'rgba(255, 255, 100, 0.4)';
    ctx.fillRect(col * scale, row * scale, scale, scale);
    ctx.strokeStyle = 'rgba(255, 255, 100, 0.8)';
    ctx.lineWidth = 2;
    ctx.strokeRect(col * scale + 1, row * scale + 1, scale - 2, scale - 2);
  }
  ctx.restore();
}

function highlightCellsOnCanvas(cells) {
  _highlightCells = cells;
  if (currentGrid) {
    renderGrid(currentGrid);
    drawCellHighlights(cells);
  }
}

function clearCellHighlights() {
  _highlightCells = [];
  if (currentGrid) renderGrid(currentGrid);
}

function annotateCoordRefs(element) {
  // Combined regex — order matters (longest first):
  // 1. Region: "rows N-M, cols N-M" (combined into one highlight)
  // 2. Point: (row, col)
  // 3. rows? N[-N]
  // 4. cols? N[-N]
  const COORD_RE = /(?:rows?)\s+(\d+)(?:\s*[-–]\s*(\d+))?\s*,\s*(?:cols?)\s+(\d+)(?:\s*[-–]\s*(\d+))?|\((\d+),\s*(\d+)\)|(?:rows?)\s+(\d+)(?:\s*[-–]\s*(\d+))?|(?:cols?)\s+(\d+)(?:\s*[-–]\s*(\d+))?/gi;

  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  for (const node of textNodes) {
    const text = node.textContent;
    COORD_RE.lastIndex = 0;
    if (!COORD_RE.test(text)) continue;
    COORD_RE.lastIndex = 0;

    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let match;
    while ((match = COORD_RE.exec(text)) !== null) {
      if (match.index > lastIdx) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      }
      const span = document.createElement('span');
      span.className = 'coord-ref';
      if (match[1] !== undefined) {
        // Region: rows N-M, cols N-M
        span.dataset.rows = match[2] !== undefined ? `${match[1]}-${match[2]}` : match[1];
        span.dataset.cols = match[4] !== undefined ? `${match[3]}-${match[4]}` : match[3];
      } else if (match[5] !== undefined) {
        // (row, col) point
        span.dataset.row = match[5];
        span.dataset.col = match[6];
      } else if (match[7] !== undefined) {
        // rows N or rows N-M
        span.dataset.rows = match[8] !== undefined ? `${match[7]}-${match[8]}` : match[7];
      } else if (match[9] !== undefined) {
        // cols N or cols N-M
        span.dataset.cols = match[10] !== undefined ? `${match[9]}-${match[10]}` : match[9];
      }
      span.textContent = match[0];
      frag.appendChild(span);
      lastIdx = COORD_RE.lastIndex;
    }
    if (lastIdx < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    }
    if (lastIdx > 0) node.parentNode.replaceChild(frag, node);
  }
}

function cellsFromCoordRef(ref) {
  const cells = [];
  if (!currentGrid) return cells;
  const h = currentGrid.length, w = currentGrid[0].length;
  if (ref.dataset.row !== undefined && ref.dataset.col !== undefined) {
    // Single point
    cells.push({row: parseInt(ref.dataset.row), col: parseInt(ref.dataset.col)});
  } else if (ref.dataset.rows !== undefined && ref.dataset.cols !== undefined) {
    // Region: rows + cols combined
    const rp = ref.dataset.rows.split('-').map(Number);
    const cp = ref.dataset.cols.split('-').map(Number);
    const r0 = rp[0], r1 = rp.length > 1 ? rp[1] : r0;
    const c0 = cp[0], c1 = cp.length > 1 ? cp[1] : c0;
    for (let r = r0; r <= r1; r++)
      for (let c = c0; c <= c1; c++) cells.push({row: r, col: c});
  } else if (ref.dataset.rows !== undefined) {
    // Rows only — highlight full rows
    const parts = ref.dataset.rows.split('-').map(Number);
    const r0 = parts[0], r1 = parts.length > 1 ? parts[1] : r0;
    for (let r = r0; r <= r1; r++)
      for (let c = 0; c < w; c++) cells.push({row: r, col: c});
  } else if (ref.dataset.cols !== undefined) {
    // Cols only — highlight full columns
    const parts = ref.dataset.cols.split('-').map(Number);
    const c0 = parts[0], c1 = parts.length > 1 ? parts[1] : c0;
    for (let r = 0; r < h; r++)
      for (let c = c0; c <= c1; c++) cells.push({row: r, col: c});
  }
  return cells;
}

// Event delegation for coord-ref hover on reasoning content
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

// ═══════════════════════════════════════════════════════════════════════════
// API
// ═══════════════════════════════════════════════════════════════════════════

async function fetchJSON(url, body, signal) {
  const r = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: signal || undefined,
  });
  return r.json();
}

const _ARC_FOUNDATION_GAMES = ['ls20', 'vc33', 'ft09', 'lp85'];
function gameSource(gameId) {
  const short = (gameId || '').split('-')[0].toLowerCase();
  return _ARC_FOUNDATION_GAMES.includes(short) ? 'ARC Prize Foundation' : 'ARC Observatory';
}
function gameDevTag(gameId) {
  const short = (gameId || '').split('-')[0].toLowerCase();
  if (_ARC_FOUNDATION_GAMES.includes(short)) return '';
  return '<span class="dev-tag" title="The game is currently iterating through feedback before released and open-sourced">staging</span>';
}

async function loadGames() {
  let games = await fetchJSON('/api/games');
  // Hide "Find the Difference" on the online/global server for now
  // prod filtering handled server-side via HIDDEN_GAMES
  const el = document.getElementById('gameList');
  el.innerHTML = '';
  const foundation = games.filter(g => _ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
  const observatory = games.filter(g => !_ARC_FOUNDATION_GAMES.includes(g.game_id.split('-')[0].toLowerCase()));
  const sortByTitle = (a, b) => ((a.title || a.game_id).localeCompare(b.title || b.game_id));
  foundation.sort(sortByTitle);
  observatory.sort(sortByTitle);
  _renderGameGroup(el, 'ARC Prize Foundation', foundation, g => startGame(g.game_id));
  _renderGameGroup(el, 'ARC Observatory', observatory, g => startGame(g.game_id));
}

function _renderGameGroup(el, label, games, onClick) {
  if (!games.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'game-group';
  const header = document.createElement('div');
  header.className = 'game-group-header';
  header.innerHTML = `<span class="game-group-arrow">&#9662;</span> ${_esc(label)} <span class="game-group-count">${games.length}</span>`;
  header.onclick = () => {
    wrap.classList.toggle('collapsed');
    header.querySelector('.game-group-arrow').innerHTML = wrap.classList.contains('collapsed') ? '&#9656;' : '&#9662;';
  };
  wrap.appendChild(header);
  const list = document.createElement('div');
  list.className = 'game-group-list';
  games.forEach(g => {
    const div = document.createElement('div');
    div.className = 'game-card';
    const shortName = g.title || g.game_id.split('-')[0].toUpperCase();
    const tag = gameDevTag(g.game_id);
    div.innerHTML = `<div class="title">${shortName}${tag ? ' ' + tag : ''}</div>`;
    div.dataset.gameId = g.game_id;
    div.onclick = () => onClick(g);
    list.appendChild(div);
  });
  wrap.appendChild(list);
  el.appendChild(wrap);
}

function gameShortName(gameId) {
  return (gameId || '').split('-')[0].toUpperCase();
}

async function startGame(gameId) {
  // Block game change if current session already has moves
  const cur = getActiveSession();
  if (cur && cur.stepCount > 0) return;

  document.querySelectorAll('.game-card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.game-card').forEach(c => {
    if (c.dataset.gameId === gameId) c.classList.add('active');
  });

  // Pyodide mode: run game entirely client-side. Server mode: run entirely server-side.
  let data;
  if (FEATURES.pyodide_game) {
    _pyodideGameActive = true;
    _pyodideGameSessionId = activeSessionId;
    try {
      data = await pyodideStartGame(gameId);
      console.log('[PyodideGame] Game started client-side:', gameId);
    } catch (err) {
      _pyodideGameActive = false;
      alert('Game engine failed to load: ' + err.message);
      return;
    }
  } else {
    _pyodideGameActive = false;
    data = await fetchJSON('/api/start', { game_id: gameId });
  }
  if (data.error) { alert(data.error); return; }

  sessionId = data.session_id;
  stepCount = 0;
  llmCallCount = 0;
  turnCounter = 0;
  _cachedCompactSummary = '';
  _compactSummaryAtCall = 0;
  _compactSummaryAtStep = 0;
  moveHistory = [];
  undoStack = [];
  sessionStepsBuffer = [];
  sessionStartTime = Date.now() / 1000;
  syncStepCounter = 0;
  llmObservations = [];
  sessionTotalTokens = { input: 0, output: 0, cost: 0 };
  autoPlaying = false;
  updateUI(data);
  updateUndoBtn();

  if ((data.available_actions || []).includes(6)) { action6Mode = true; canvas.style.cursor = 'crosshair'; }
  document.getElementById('emptyState').style.display = 'none';
  canvas.style.display = 'block';
  document.getElementById('controls').style.display = 'flex';
  document.getElementById('transportBar').style.display = 'block';
  document.getElementById('reasoningContent').innerHTML =
    '<div class="empty-state" style="height:auto;font-size:12px;">Game started. Press Agent Autoplay to let the agent play, or use the controls to play yourself.</div>';

  // ── Multi-session: reuse current tab when switching games (no moves yet) ──
  const curSession = getActiveSession();
  if (curSession && curSession.stepCount === 0) {
    // Reuse the current tab — just swap the session ID
    const oldId = activeSessionId;
    sessions.delete(oldId);
    curSession.sessionId = data.session_id;
    curSession.gameId = gameShortName(gameId);
    curSession.status = data.state || 'NOT_FINISHED';
    curSession.createdAt = Date.now() / 1000;
    curSession.callDurations = [];
    curSession.tabLabel = '';
    sessions.set(data.session_id, curSession);
    activeSessionId = data.session_id;
    // Update Pyodide ownership to match the new session ID
    if (_pyodideGameSessionId === oldId) _pyodideGameSessionId = data.session_id;
  } else if (!curSession) {
    // No active session at all (first load)
    const s = new SessionState(data.session_id);
    s.gameId = gameShortName(gameId);
    s.status = data.state || 'NOT_FINISHED';
    s.createdAt = Date.now() / 1000;
    registerSession(data.session_id, s);
  } else {
    // Active session has moves — create a new tab
    saveSessionToState();
    detachSessionView(activeSessionId);
    const s = new SessionState(data.session_id);
    s.gameId = gameShortName(gameId);
    s.status = data.state || 'NOT_FINISHED';
    s.createdAt = Date.now() / 1000;
    sessions.set(data.session_id, s);
    activeSessionId = data.session_id;
    attachSessionView(data.session_id);
    // Re-apply DOM writes on the fresh view
    document.getElementById('emptyState').style.display = 'none';
    canvas.style.display = 'block';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    document.getElementById('reasoningContent').innerHTML =
      '<div class="empty-state" style="height:auto;font-size:12px;">Game started. Press Agent Autoplay to let the agent play, or use the controls to play yourself.</div>';
    renderSessionTabs();
    saveSessionIndex();
  }
  renderSessionTabs();
  saveSessionIndex();
  updatePanelBlur();
  updateGameListLock();

  // Blink the Agent Autoplay button to guide the user
  const autoBtn = document.getElementById('autoPlayBtn');
  if (autoBtn) autoBtn.classList.add('btn-blink');

  // Initialize live scrubber
  initLiveScrubber();
}

function updateUI(data) {
  previousGrid = currentGrid;
  currentState = data;
  currentGrid = data.grid;
  currentChangeMap = data.change_map || null;
  // If viewing historical step via either scrubber, don't render live grid
  const _inObsMode = document.getElementById('obsScreen')?.style.display === 'flex';
  const _scrubPaused = _inObsMode ? !_obsScrubLive : !_liveScrubMode;
  if (_scrubPaused) {
    if (!_inObsMode) _liveScrubLiveGrid = data.grid;
  } else if (currentChangeMap && currentChangeMap.change_count > 0 && document.getElementById('showChanges').checked) {
    renderGridWithChanges(data.grid, currentChangeMap);
  } else {
    renderGrid(data.grid);
  }
  if (_inObsMode) obsScrubUpdate();
  else liveScrubUpdate();
  const titleEl = document.getElementById('gameTitle');
  titleEl.textContent = gameShortName(data.game_id) || 'Game';
  // Show "Local" badge when running via Pyodide
  const existingBadge = titleEl.parentElement.querySelector('.pyodide-badge');
  if (existingBadge) existingBadge.remove();
  if (_pyodideGameActive) {
    const badge = document.createElement('span');
    badge.className = 'pyodide-badge';
    badge.style.cssText = 'display:inline-block;background:#4FCC30;color:#000;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:6px;vertical-align:middle;';
    badge.textContent = 'Local';
    titleEl.parentElement.insertBefore(badge, titleEl.nextSibling);
  }
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = data.state; statusEl.className = 'status status-' + data.state;
  document.getElementById('levelInfo').textContent = `Level ${data.levels_completed}/${data.win_levels}`;
  const ci = currentChangeMap?.change_count > 0 ? ` | ${currentChangeMap.change_count} cells` : '';
  document.getElementById('stepCounter').textContent = `Step ${stepCount}${ci}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// ACTIONS
// ═══════════════════════════════════════════════════════════════════════════

function showNoChangeIfSame(prevGrid, newGrid) {
  const el = document.getElementById('noChangeMsg');
  if (prevGrid && JSON.stringify(newGrid) === prevGrid) {
    el.textContent = 'no state change';
    el.className = 'no-change-flash';
    el.style.display = '';
    setTimeout(() => { el.style.display = 'none'; }, 2000);
  } else {
    el.style.display = 'none';
  }
}

function toggleHumanLock() {
  humanLocked = !humanLocked;
  const ctrl = document.getElementById('controls');
  const btn = document.getElementById('interveneBtn');
  if (humanLocked) {
    ctrl.classList.add('locked');
    btn.classList.remove('active');
    btn.innerHTML = '&#128274; Intervene as Human';
  } else {
    ctrl.classList.remove('locked');
    btn.classList.add('active');
    btn.innerHTML = '&#128275; Controls Unlocked';
  }
}

function lockHumanControls() {
  humanLocked = true;
  const ctrl = document.getElementById('controls');
  const btn = document.getElementById('interveneBtn');
  if (ctrl) ctrl.classList.add('locked');
  if (btn) { btn.classList.remove('active'); btn.innerHTML = '&#128274; Intervene as Human'; }
}

function lockSettings() {
  // Grey out settings controls but keep the scaffold diagram visible (it shows live call status)
  const body = document.getElementById('settingsBody');
  if (body) { body.style.opacity = '0.5'; body.style.pointerEvents = 'none'; }
  const scaffSelect = document.getElementById('scaffoldingSelect');
  if (scaffSelect) scaffSelect.disabled = true;
  const sidebar = document.getElementById('gameSidebar');
  if (sidebar) sidebar.classList.add('locked');
}

function unlockSettings() {
  const body = document.getElementById('settingsBody');
  if (body) { body.style.opacity = ''; body.style.pointerEvents = ''; }
  const scaffSelect = document.getElementById('scaffoldingSelect');
  if (scaffSelect) scaffSelect.disabled = false;
  updateGameListLock();  // re-evaluate — may stay locked if session in progress
}

function logHumanAction(actionId, actionData, changeMap, turnId) {
  const content = document.getElementById('reasoningContent');
  if (content.querySelector('.empty-state')) content.innerHTML = '';
  const entry = document.createElement('div');
  entry.className = 'reasoning-entry';
  if (turnId) entry.setAttribute('data-turn-id', turnId);
  const ci = changeMap?.change_count > 0 ? ` | ${changeMap.change_count} cells changed` : '';
  const coordStr = actionData?.x !== undefined ? ` at (${actionData.x}, ${actionData.y})` : '';
  entry.innerHTML = `
    <button class="branch-btn" onclick="branchFromStep(${stepCount})" title="Branch from step ${stepCount}">&#8627; branch</button>
    <div class="step-label" style="color:var(--yellow);">Step ${stepCount} — Human</div>
    <div class="action-rec" style="color:var(--yellow);">\u2192 Action ${actionId} (${ACTION_NAMES[actionId] || '?'})${coordStr}${ci}</div>`;
  content.appendChild(entry);
  annotateCoordRefs(entry);
  scrollReasoningToBottom();
}

async function doAction(actionId, isClick) {
  if (humanLocked) return;
  if (!sessionId) return;
  if (isClick || actionId === 6) {
    action6Mode = true; canvas.style.cursor = 'crosshair'; canvas.title = 'Click grid for ACTION6';
    return;
  }
  // Save undo snapshot
  turnCounter++;
  const currentTurnId = turnCounter;
  undoStack.push({
    grid: currentState.grid ? currentState.grid.map(r => [...r]) : [],
    state: currentState.state,
    levels_completed: currentState.levels_completed,
    stepCount: stepCount,
    turnId: currentTurnId,
  });
  stepCount++;
  const prevGrid = currentState.grid ? JSON.stringify(currentState.grid) : null;
  const data = await gameStep(sessionId, actionId, {}, {session_cost: sessionTotalTokens.cost});
  if (data.error) { undoStack.pop(); alert(data.error); return; }
  moveHistory.push({ step: stepCount, action: actionId, result_state: data.state, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId });
  recordStepForPersistence(actionId, {}, data.grid, data.change_map, null, null, { levels_completed: data.levels_completed, result_state: data.state });
  logHumanAction(actionId, {}, data.change_map, currentTurnId);
  updateUI(data);
  showNoChangeIfSame(prevGrid, data.grid);
  updateUndoBtn();
  checkSessionEndAndUpload();
}

canvas.addEventListener('click', async (e) => {
  if (humanLocked) return;
  if (!action6Mode || !sessionId) return;
  const rect = canvas.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) * 64 / canvas.clientWidth);
  const y = Math.floor((e.clientY - rect.top) * 64 / canvas.clientHeight);
  // Save undo snapshot
  turnCounter++;
  const currentTurnId = turnCounter;
  undoStack.push({
    grid: currentState.grid ? currentState.grid.map(r => [...r]) : [],
    state: currentState.state,
    levels_completed: currentState.levels_completed,
    stepCount: stepCount,
    turnId: currentTurnId,
  });
  stepCount++;
  const prevGrid = currentState.grid ? JSON.stringify(currentState.grid) : null;
  const data = await gameStep(sessionId, 6, { x, y }, {session_cost: sessionTotalTokens.cost});
  if (data.error) { undoStack.pop(); alert(data.error); return; }
  moveHistory.push({ step: stepCount, action: 6, result_state: data.state, x, y, levels: data.levels_completed, grid: data.grid, change_map: data.change_map, turnId: currentTurnId });
  recordStepForPersistence(6, { x, y }, data.grid, data.change_map, null, null, { levels_completed: data.levels_completed, result_state: data.state });
  logHumanAction(6, { x, y }, data.change_map, currentTurnId);
  updateUI(data);
  showNoChangeIfSame(prevGrid, data.grid);
  updateUndoBtn();
  checkSessionEndAndUpload();
  action6Mode = (data.available_actions || []).includes(6);
  if (!action6Mode) canvas.style.cursor = 'default';
});

document.addEventListener('keydown', (e) => {
  if (!sessionId) return;
  if (humanLocked) return;
  // Don't capture keyboard when user is interacting with inputs/settings
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  const map = {'ArrowUp':1,'ArrowDown':2,'ArrowLeft':3,'ArrowRight':4,'w':1,'s':2,'a':3,'d':4,'z':5,'x':7,'r':0};
  if (map[e.key] !== undefined) { e.preventDefault(); doAction(map[e.key]); }
});

// ═══════════════════════════════════════════════════════════════════════════
// WARN BEFORE LEAVING (active session protection)
// ═══════════════════════════════════════════════════════════════════════════

window.addEventListener('beforeunload', (e) => {
  // Warn if any session has steps in progress
  const hasActiveSession = sessionId && stepCount > 0 && currentState.state === 'NOT_FINISHED';
  const hasAutoplay = autoPlaying;
  if (hasActiveSession || hasAutoplay) {
    e.preventDefault();
    // Modern browsers ignore custom text but require returnValue to be set
    e.returnValue = '';
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// REASONING MODE HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function getCompactSettings() {
  const enabledEl = document.getElementById('compactContext');
  if (!enabledEl) return { enabled: false, after: null, contextLimitUnit: 'tokens', contextLimitVal: 64000, compactOnLevel: false };
  const enabled = enabledEl.checked;
  const afterVal = document.getElementById('compactAfter')?.value;
  const after = afterVal ? parseInt(afterVal) : null;  // null = disabled
  const unit = document.getElementById('contextLimitUnit')?.value || 'tokens';
  const rawVal = parseInt(document.getElementById('compactContextPct')?.value) || 64000;
  const compactOnLevel = document.getElementById('compactOnLevel')?.checked ?? true;
  return { enabled, after, contextLimitUnit: unit, contextLimitVal: rawVal, compactOnLevel };
}

function onContextLimitUnitChange() {
  const unit = document.getElementById('contextLimitUnit').value;
  const input = document.getElementById('compactContextPct');
  if (unit === 'pct') {
    input.value = 60;
  } else {
    input.value = 32000;
  }
}

// Spin context limit: dir=1 up, dir=-1 down
function spinContextLimit(dir) {
  const unit = document.getElementById('contextLimitUnit').value;
  const input = document.getElementById('compactContextPct');
  const val = parseInt(input.value) || 0;
  if (unit === 'tokens') {
    input.value = dir > 0 ? Math.min(val * 2, 2000000) : Math.max(Math.floor(val / 2), 1000);
  } else {
    input.value = dir > 0 ? Math.min(val + 5, 99) : Math.max(val - 5, 1);
  }
}

// ArrowUp/Down listener moved to attachSettingsListeners()

function getContextTokenLimit(compact, contextWindow) {
  if (compact.contextLimitUnit === 'tokens') return compact.contextLimitVal;
  return Math.floor(contextWindow * compact.contextLimitVal / 100);
}

function getSelectedModelContextWindow() {
  const model = getSelectedModel();
  const info = modelsData.find(m => m.name === model);
  return (info && info.context_window) || 128000;
}

function estimateTokens(text) {
  // Rough estimate: ~4 chars per token for English/code
  return Math.ceil((text || '').length / 4);
}

function trimHistoryForTokens(history, maxTokens) {
  // If history fits within budget, return as-is.
  // Otherwise drop grid snapshots from older steps, keeping last 5 with grids.
  const KEEP_GRIDS = 5;
  if (!history || history.length <= KEEP_GRIDS) return history;

  // Estimate token cost of full history with grids
  let totalChars = 0;
  for (const h of history) {
    totalChars += 60; // step line overhead
    if (h.grid) totalChars += h.grid.length * 30; // rough RLE per row
  }
  const est = Math.ceil(totalChars / 4);
  if (est <= maxTokens) return history; // fits, keep all

  // Strip grids from older entries, keep last KEEP_GRIDS with grids
  return history.map((h, i) => {
    if (i >= history.length - KEEP_GRIDS) return h;
    const { grid, ...rest } = h;
    return rest;
  });
}

function collectObservation(resp, ss) {
  if (!resp || !resp.parsed) return;
  const p = resp.parsed;
  const obs = ss || { llmObservations, stepCount };
  obs.llmObservations.push({
    step: obs.stepCount,
    observation: p.observation || '',
    reasoning: p.reasoning || '',
    action: p.action,
    analysis: p.analysis || '',
  });
}

let _cachedCompactSummary = '';  // LLM-generated summary, cached until refreshed
let _compactSummaryAtCall = 0;   // llmCallCount when summary was last generated
let _compactSummaryAtStep = 0;   // stepCount when summary was last generated (history cutoff)
let _lastCompactPrompt = '';     // last prompt sent to compact model

function _syncCompactToMemoryTab() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) el.value = _cachedCompactSummary;
}
function _syncCompactPromptToMemoryTab() {
  // No-op: compact prompt textarea is now user-editable template
}

function applyCompactEdit() {
  const el = document.getElementById('memoryCompactSummary');
  if (el) {
    _cachedCompactSummary = el.value;
    _compactSummaryAtCall = llmCallCount;
    _compactSummaryAtStep = stepCount;
  }
}

function buildCompactContextFallback() {
  // Heuristic fallback when LLM summary is not available yet.
  if (!llmObservations.length) return '';
  const parts = ['## COMPACT CONTEXT (accumulated knowledge from prior steps)'];
  const actionEffects = {};
  for (const o of llmObservations) {
    if (o.action !== undefined) {
      const aname = ACTION_NAMES[o.action] || `ACTION${o.action}`;
      if (!actionEffects[aname]) actionEffects[aname] = [];
      const reason = (o.reasoning || '').substring(0, 100);
      if (reason && actionEffects[aname].length < 3) actionEffects[aname].push(reason);
    }
  }
  const effectLines = Object.entries(actionEffects)
    .map(([a, reasons]) => `  ${a}: ${reasons[reasons.length - 1]}`)
    .join('\n');
  if (effectLines) parts.push(`Action effects:\n${effectLines}`);
  const last3 = llmObservations.slice(-3);
  if (last3.length) {
    const lines = last3.map(o => `  Step ${o.step}: ${o.observation || ''}`).join('\n');
    parts.push(`Recent observations:\n${lines}`);
  }
  const lastReasoning = llmObservations[llmObservations.length - 1]?.reasoning;
  if (lastReasoning) parts.push(`Current plan: ${lastReasoning}`);
  return parts.join('\n');
}

async function checkInterrupt(expected, grid, changeMap) {
  // Ask a cheap model whether the plan went as expected after a step.
  // Returns true if plan should be interrupted, false otherwise.
  const gridCompact = grid ? grid.map(r => r.join(',')).join('\n') : '';
  const changesText = changeMap ? 'Recent changes: ' + JSON.stringify(changeMap) : '';
  const template = getPrompt('linear.interrupt_prompt');
  const prompt = template
    .replace('{expected}', expected)
    .replace('{grid}', gridCompact)
    .replace('{changes}', changesText);

  const interruptModelSel = document.getElementById('interruptModelSelect')?.value || 'auto';
  const agentModel = getSelectedModel();

  function parseInterruptResult(text) {
    if (!text) return false;
    // Strip markdown fences, JSON wrappers, whitespace
    const clean = text.replace(/```[\s\S]*?```/g, m => m.replace(/```\w*/g, '').trim())
      .replace(/[{}"]/g, '').trim().toUpperCase();
    // Prompt asks "should we interrupt?" — YES means interrupt
    if (clean.startsWith('YES')) return true;
    if (/\bYES\b/.test(clean) && !/\bNO\b/.test(clean)) return true;
    if (/TRUE/.test(clean) && !/FALSE/.test(clean)) return true;
    return false;
  }

  const _intStart = performance.now();
  try {
    let rawResult = '';
    let _intResult;
    {
      // BYOK / Puter.js path
      const model = interruptModelSel === 'same' ? agentModel
        : (interruptModelSel === 'auto' || interruptModelSel === 'auto-fastest') ? null
        : interruptModelSel;
      const info = model ? getModelInfo(model) : getModelInfo(agentModel);
      const useModel = model || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
      if (useModel) {
        const result = await callLLM([{role: 'user', content: prompt}], useModel);
        rawResult = `${result} (${useModel})`;
        _syncInterruptResult(rawResult);
        _intResult = parseInterruptResult(result);
      }
    }
    // Record interrupt timing in timeline
    const _intDur = Math.round(performance.now() - _intStart);
    const _intSs = getActiveSession();
    if (_intSs && _intSs.timelineEvents) {
      _intSs.timelineEvents.push({ type: 'interrupt', call_type: 'interrupt', duration: _intDur, turn: _intSs.llmCallCount, response_preview: rawResult });
      emitObsEvent(_intSs, { event: 'interrupt', agent: 'interrupt', duration_ms: _intDur, summary: (rawResult || '').slice(0, 200) });
    }
    if (_intResult !== undefined) return _intResult;
  } catch (e) {
    console.warn('Interrupt check failed:', e);
    _syncInterruptResult('ERROR: ' + e.message);
  }
  return false; // default: don't interrupt
}

function _syncInterruptResult(text) {
  const el = document.getElementById('memoryInterruptResult');
  if (el) el.value = text;
}

async function buildCompactContext(ss) {
  // Use LLM to summarize the game history into key takeaways.
  // Falls back to heuristic if LLM call fails.
  // Re-summarize every 5 calls to stay current.
  // ss = SessionState (optional, falls back to globals)
  const _ss = ss || { _cachedCompactSummary, llmCallCount, _compactSummaryAtCall, _compactSummaryAtStep, llmObservations, moveHistory, currentState, _lastCompactPrompt, sessionId: sessionId, stepCount };
  const REFRESH_INTERVAL = 5;
  if (_ss._cachedCompactSummary && (_ss.llmCallCount - _ss._compactSummaryAtCall) < REFRESH_INTERVAL) {
    return _ss._cachedCompactSummary;
  }

  // Build a summary prompt from observations + history
  const obsText = _ss.llmObservations.map(o =>
    `Step ${o.step}: action=${ACTION_NAMES[o.action] || o.action}, obs="${o.observation || ''}", reasoning="${(o.reasoning || '').substring(0, 150)}"`
  ).join('\n');

  const histText = _ss.moveHistory.slice(-20).map(h =>
    `Step ${h.step}: ${ACTION_NAMES[h.action] || '?'} -> ${h.result_state || '?'}`
  ).join('\n');

  const promptTemplate = getPrompt('linear.compact_prompt');

  const summaryPrompt = `${promptTemplate}

OBSERVATIONS FROM GAMEPLAY:
${obsText}

RECENT MOVE HISTORY:
${histText}

Progress: Level ${_ss.currentState.levels_completed || 0}/${_ss.currentState.win_levels || 0}`;

  // Store the prompt for display in Memory tab
  _ss._lastCompactPrompt = summaryPrompt;
  if (!ss) _lastCompactPrompt = summaryPrompt;
  _syncCompactPromptToMemoryTab();

  // Determine compact model
  const compactModelSel = document.getElementById('compactModelSelectTop').value;
  const agentModel = getSelectedModel();
  // 'auto' = cheapest same provider (server decides), 'auto-fastest' = fastest same provider, 'same' = agent model, else specific model
  const compactModel = compactModelSel === 'same' ? agentModel
    : (compactModelSel === 'auto' || compactModelSel === 'auto-fastest') ? null
    : compactModelSel;

  try {
    let summary;
    const _compactStart = performance.now();
    const useCompactModel = compactModel || (FEATURES.puter_js ? 'gpt-4o-mini' : null);
    if (useCompactModel) {
      summary = await callLLM([{role: 'user', content: summaryPrompt}], useCompactModel);
    }
    if (summary) {
      const _compactDur = Math.round(performance.now() - _compactStart);
      const _tlTarget = ss || getActiveSession();
      if (_tlTarget && _tlTarget.timelineEvents) {
        _tlTarget.timelineEvents.push({ type: 'compact', call_type: 'compact', duration: _compactDur, turn: _ss.llmCallCount, response_preview: (summary || '').slice(0, 500) });
        emitObsEvent(_tlTarget, { event: 'compact', agent: 'compact', duration_ms: _compactDur, summary: (summary || '').slice(0, 200) });
      }
      _ss._cachedCompactSummary = `## COMPACT CONTEXT (LLM-summarized game knowledge)\n${summary}`;
      _ss._compactSummaryAtCall = _ss.llmCallCount;
      _ss._compactSummaryAtStep = _ss.stepCount;
      if (!ss) { _cachedCompactSummary = _ss._cachedCompactSummary; _compactSummaryAtCall = _ss._compactSummaryAtCall; _compactSummaryAtStep = _ss._compactSummaryAtStep; }
      _syncCompactToMemoryTab();
      return _ss._cachedCompactSummary;
    }
  } catch (e) {
    console.warn('Compact summary LLM call failed, using fallback:', e);
  }
  const fallback = buildCompactContextFallback();
  if (fallback) {
    _ss._cachedCompactSummary = fallback;
    if (!ss) _cachedCompactSummary = fallback;
    _syncCompactToMemoryTab();
  }
  return fallback;
}

// ── Session event logging ──────────────────────────────────────────────
function logSessionEvent(eventType, stepNum, data = {}) {
  if (!sessionId) return;
  fetchJSON(`/api/sessions/${sessionId}/event`, {
    event_type: eventType,
    step_num: stepNum,
    data: data,
  }).catch(() => {});  // fire and forget
}

async function manualCompact() {
  if (!sessionId || moveHistory.length === 0) return;
  saveSessionToState();  // sync globals → ss
  const ss = getActiveSession();
  const btn = document.getElementById('compactBtn');
  btn.disabled = true;
  btn.textContent = '\u23f3 Compacting...';
  try {
    _cachedCompactSummary = '';  // force refresh
    if (ss) ss._cachedCompactSummary = '';
    const summary = await buildCompactContext(ss);
    if (summary) {
      _cachedCompactSummary = summary;
      if (ss) ss._cachedCompactSummary = summary;
      _syncCompactToMemoryTab();
      _compactSummaryAtCall = llmCallCount;
      _compactSummaryAtStep = stepCount;
      if (ss) { ss._compactSummaryAtCall = llmCallCount; ss._compactSummaryAtStep = stepCount; }
      logSessionEvent('compact', stepCount, { call_count: llmCallCount, history_length: moveHistory.length, trigger: 'manual' });
      const content = document.getElementById('reasoningContent');
      if (content.querySelector('.empty-state')) content.innerHTML = '';
      const entry = document.createElement('div');
      entry.className = 'reasoning-entry';
      entry.innerHTML = `<div class="step-label" style="color:var(--purple);">Context compacted at step ${stepCount} (${llmCallCount} calls)</div>`;
      content.appendChild(entry);
      scrollReasoningToBottom();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '\ud83d\udcdc Compact';
  }
}

function getThinkingLevel() {
  return document.querySelector('input[name="thinkingLevel"]:checked')?.value || 'low';
}
function getToolsMode() {
  return document.querySelector('input[name="toolsMode"]:checked')?.value || 'off';
}

function getPlanningMode() {
  return document.querySelector('input[name="planMode"]:checked')?.value || 'off';
}

function getMaxTokens() {
  return parseInt(document.getElementById('maxTokensLimit')?.value) || 16384;
}
function spinMaxTokens(dir) {
  const el = document.getElementById('maxTokensLimit');
  el.value = Math.max(1024, Math.min(65536, (parseInt(el.value) || 16384) + dir * 1024));
}

function shouldAskAdaptive() {
  // In adaptive mode, ask the LLM if no level progress in last 5 steps
  if (moveHistory.length < 5) return false;
  const last5 = moveHistory.slice(-5);
  const levels = last5.map(h => h.levels ?? 0);
  return new Set(levels).size <= 1;
}

