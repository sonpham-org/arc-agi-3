// ═══════════════════════════════════════════════════════════════════════════
// LEADERBOARD — AI vs Human best performances
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
  const body = document.getElementById('lbBody');
  body.innerHTML = '<tr><td colspan="8" class="lb-loading">Loading...</td></tr>';

  try {
    const data = await fetchJSON('/api/leaderboard');
    _lbData = data.leaderboard || [];
  } catch {
    body.innerHTML = '<tr><td colspan="8" class="lb-loading">Failed to load leaderboard.</td></tr>';
    return;
  }

  if (!_lbData.length) {
    body.innerHTML = '<tr><td colspan="8" class="lb-loading">No sessions yet. Play some games!</td></tr>';
    return;
  }

  _renderLeaderboardTable();
}

function _renderLeaderboardTable() {
  const body = document.getElementById('lbBody');
  body.innerHTML = '';

  for (const row of _lbData) {
    const tr = document.createElement('tr');
    tr.className = 'lb-row';
    tr.onclick = () => openLbDrilldown(row.game_id);

    const gameName = row.game_id.toUpperCase();
    const ai = row.ai;
    const human = row.human;

    // Determine winner
    let aiWins = false, humanWins = false;
    if (ai && human) {
      if ((ai.levels || 0) > (human.levels || 0)) aiWins = true;
      else if ((human.levels || 0) > (ai.levels || 0)) humanWins = true;
      else if ((ai.steps || 9999) < (human.steps || 9999)) aiWins = true;
      else if ((human.steps || 9999) < (ai.steps || 9999)) humanWins = true;
    } else if (ai) {
      aiWins = true;
    } else if (human) {
      humanWins = true;
    }

    tr.innerHTML = `
      <td class="lb-game-name">${gameName}</td>
      ${_renderAiCell(ai, aiWins)}
      <td class="lb-vs">${ai && human ? 'vs' : ''}</td>
      ${_renderHumanCell(human, humanWins)}
    `;
    body.appendChild(tr);
  }
}

function _renderAiCell(ai, isWinner) {
  if (!ai) return '<td class="lb-empty" colspan="3">—</td>';
  const cls = isWinner ? ' lb-winner' : '';
  const result = _resultBadge(ai.result);
  const model = _shortModel(ai.model || '');
  return `
    <td class="lb-ai-result${cls}">${result}</td>
    <td class="lb-ai-steps${cls}">${ai.steps || '—'} steps</td>
    <td class="lb-ai-model${cls}" title="${ai.model || ''}">${model}</td>
  `;
}

function _renderHumanCell(human, isWinner) {
  if (!human) return '<td class="lb-empty" colspan="3">—</td>';
  const cls = isWinner ? ' lb-winner' : '';
  const result = _resultBadge(human.result);
  const dur = human.duration_seconds ? _lbFormatDuration(human.duration_seconds) : '—';
  return `
    <td class="lb-human-result${cls}">${result}</td>
    <td class="lb-human-steps${cls}">${human.steps || '—'} steps</td>
    <td class="lb-human-time${cls}">${dur}</td>
  `;
}

function _resultBadge(result) {
  if (result === 'WIN') return '<span class="lb-badge lb-badge-win">WIN</span>';
  if (result === 'GAME_OVER') return '<span class="lb-badge lb-badge-lose">LOSE</span>';
  return '<span class="lb-badge lb-badge-progress">IN PROGRESS</span>';
}

function _shortModel(model) {
  if (!model) return '—';
  // Trim provider prefix and long model names
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
  document.querySelector('.lb-table-wrap').style.display = 'none';
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
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${result}</td>
        <td>${r.steps || 0}</td>
        <td>${r.levels || 0}</td>
        <td>${dur}</td>
        <td>${date}</td>`;
    }
    tbody.appendChild(tr);
  });
}

function closeLbDrilldown() {
  document.getElementById('lbDrilldown').style.display = 'none';
  document.querySelector('.lb-table-wrap').style.display = '';
}

// Allow re-fetching when tab is revisited
function refreshLeaderboard() {
  _lbLoaded = false;
  _loadLeaderboard();
}
