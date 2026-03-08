// ═══════════════════════════════════════════════════════════════════════════
// LEADERBOARD — AI and Human best performances (separate tables)
// ═══════════════════════════════════════════════════════════════════════════

let _lbLoaded = false;
let _lbData = [];

function initLeaderboard() {
  if (!_lbLoaded) {
    _lbLoaded = true;
    _loadLeaderboard();
  }
}

async function _loadLeaderboard() {
  const aiBody = document.getElementById('lbAiBody');
  const humanBody = document.getElementById('lbHumanBody');
  aiBody.innerHTML = '<tr><td colspan="4" class="lb-loading">Loading...</td></tr>';
  humanBody.innerHTML = '<tr><td colspan="5" class="lb-loading">Loading...</td></tr>';

  try {
    const data = await fetchJSON('/api/leaderboard');
    _lbData = data.leaderboard || [];
  } catch {
    aiBody.innerHTML = '<tr><td colspan="4" class="lb-loading">Failed to load.</td></tr>';
    humanBody.innerHTML = '<tr><td colspan="5" class="lb-loading">Failed to load.</td></tr>';
    return;
  }

  if (!_lbData.length) {
    aiBody.innerHTML = '<tr><td colspan="4" class="lb-loading">No sessions yet.</td></tr>';
    humanBody.innerHTML = '<tr><td colspan="5" class="lb-loading">No sessions yet.</td></tr>';
    return;
  }

  _renderLeaderboardTables();
}

function _renderLeaderboardTables() {
  const aiBody = document.getElementById('lbAiBody');
  const humanBody = document.getElementById('lbHumanBody');
  aiBody.innerHTML = '';
  humanBody.innerHTML = '';

  // Collect AI and human entries separately
  const aiEntries = _lbData.filter(r => r.ai).sort((a, b) => {
    const al = a.ai.levels || 0, bl = b.ai.levels || 0;
    if (bl !== al) return bl - al;
    return (a.ai.steps || 9999) - (b.ai.steps || 9999);
  });
  const humanEntries = _lbData.filter(r => r.human).sort((a, b) => {
    const al = a.human.levels || 0, bl = b.human.levels || 0;
    if (bl !== al) return bl - al;
    return (a.human.steps || 9999) - (b.human.steps || 9999);
  });

  for (const row of aiEntries) {
    const tr = document.createElement('tr');
    tr.className = 'lb-row';
    tr.onclick = () => openLbDrilldown(row.game_id);
    const ai = row.ai;
    tr.innerHTML = `
      <td class="lb-game-name">${row.game_id.toUpperCase()}</td>
      <td>${_resultBadge(ai.result)}</td>
      <td>${ai.steps || '—'} steps</td>
      <td class="lb-model" title="${ai.model || ''}">${_shortModel(ai.model || '')}</td>
    `;
    aiBody.appendChild(tr);
  }

  if (!aiEntries.length) {
    aiBody.innerHTML = '<tr><td colspan="4" class="lb-loading">No AI attempts yet.</td></tr>';
  }

  for (const row of humanEntries) {
    const tr = document.createElement('tr');
    tr.className = 'lb-row';
    tr.onclick = () => openLbDrilldown(row.game_id);
    const h = row.human;
    const dur = h.duration_seconds ? _lbFormatDuration(h.duration_seconds) : '—';
    const author = h.author || '—';
    tr.innerHTML = `
      <td class="lb-game-name">${row.game_id.toUpperCase()}</td>
      <td>${_resultBadge(h.result)}</td>
      <td>${h.steps || '—'} steps</td>
      <td>${dur}</td>
      <td class="lb-author" title="${_esc(author)}">${_esc(author)}</td>
    `;
    humanBody.appendChild(tr);
  }

  if (!humanEntries.length) {
    humanBody.innerHTML = '<tr><td colspan="5" class="lb-loading">No human attempts yet.</td></tr>';
  }
}

function _resultBadge(result) {
  if (result === 'WIN') return '<span class="lb-badge lb-badge-win">WIN</span>';
  if (result === 'GAME_OVER') return '<span class="lb-badge lb-badge-lose">LOSE</span>';
  return '<span class="lb-badge lb-badge-progress">IN PROGRESS</span>';
}

function _shortModel(model) {
  if (!model) return '—';
  const parts = model.split('/');
  const name = parts[parts.length - 1];
  return name.length > 20 ? name.slice(0, 18) + '…' : name;
}

function _lbFormatDuration(secs) {
  if (!secs || secs <= 0) return '—';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// ── Drill-down ──────────────────────────────────────────────────────────

async function openLbDrilldown(gameId) {
  document.querySelector('.lb-tables-wrap').style.display = 'none';
  const drill = document.getElementById('lbDrilldown');
  drill.style.display = '';
  document.getElementById('lbDrillTitle').textContent = gameId.toUpperCase() + ' — Top Attempts';

  const aiBody = document.getElementById('lbDrillAI');
  const humanBody = document.getElementById('lbDrillHuman');
  aiBody.innerHTML = '<tr><td colspan="6" class="lb-loading">Loading...</td></tr>';
  humanBody.innerHTML = '<tr><td colspan="6" class="lb-loading">Loading...</td></tr>';

  try {
    const data = await fetchJSON(`/api/leaderboard/${encodeURIComponent(gameId)}`);
    _renderDrillTable(aiBody, data.ai || [], 'ai');
    _renderDrillTable(humanBody, data.human || [], 'human');
  } catch {
    aiBody.innerHTML = '<tr><td colspan="6">Failed to load</td></tr>';
    humanBody.innerHTML = '<tr><td colspan="6">Failed to load</td></tr>';
  }
}

function _renderDrillTable(tbody, rows, type) {
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="lb-loading">No ${type === 'ai' ? 'AI' : 'human'} attempts yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = '';
  rows.forEach((r, i) => {
    const tr = document.createElement('tr');
    const result = _resultBadge(r.result);
    const date = r.created_at ? new Date(r.created_at * 1000).toLocaleDateString() : '';
    if (type === 'ai') {
      const model = _shortModel(r.model || '');
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${result}</td>
        <td>${r.steps || 0}</td>
        <td>${r.levels || 0}</td>
        <td title="${r.model || ''}">${model}</td>
        <td>${date}</td>`;
    } else {
      const dur = r.duration_seconds ? _lbFormatDuration(r.duration_seconds) : '—';
      const author = r.author || '—';
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${result}</td>
        <td>${r.steps || 0}</td>
        <td>${r.levels || 0}</td>
        <td>${dur}</td>
        <td title="${_esc(author)}">${_esc(author)}</td>
        <td>${date}</td>`;
    }
    tbody.appendChild(tr);
  });
}

function closeLbDrilldown() {
  document.getElementById('lbDrilldown').style.display = 'none';
  document.querySelector('.lb-tables-wrap').style.display = '';
}

// Allow re-fetching when tab is revisited
function refreshLeaderboard() {
  _lbLoaded = false;
  _loadLeaderboard();
}
