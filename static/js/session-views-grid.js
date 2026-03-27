// Author: Claude Sonnet 4.6
// Date: 27-Mar-2026
// PURPOSE: Browse sessions view — renders Human / AI / My sessions as tables
//   with columns: Timestamp, Game (with version), Levels, Steps, Time, actions.
//   Depends on fetchJSON/gameShortName/formatDuration (ui.js), currentUser (state.js),
//   getLocalSessions (session-storage.js), resumeSession (session-views-history.js).
//   Added: live session badge (mode=stream_live), sort live to top, link to Observatory live.
// SRP/DRY check: Pass — single module for browse-grid rendering, reuses ui.js helpers.

// ═══════════════════════════════════════════════════════════════════════════
// SESSION VIEWS — GRID (Browse sessions view)
// ═══════════════════════════════════════════════════════════════════════════

let _browseGlobalCache = null;  // cache server sessions
let _browseGameFilter = null;   // currently selected game filter (game_id prefix)

function loadBrowseView() {
  _loadBrowseGameList();
  _loadBrowseColumns();
}

// ── Game sidebar ─────────────────────────────────────────────────────────

async function _loadBrowseGameList() {
  const el = document.getElementById('browseGameList');
  if (el.children.length > 1) return; // already loaded
  try {
    let games = await fetchJSON('/api/games');
    if (MODE === 'prod') games = games.filter(g => g.game_id !== 'fd01-00000001');
    el.innerHTML = '';
    _renderGames(el, games, g => _browseSelectGame(g.game_id));
  } catch { el.innerHTML = '<div class="browse-empty" style="padding:12px;">Failed to load games.</div>'; }
}

function _browseSelectGame(gameId) {
  const prefix = gameId.split('-')[0].toLowerCase();
  _browseGameFilter = prefix;
  document.querySelectorAll('#browseGameList .game-card').forEach(c => {
    const cid = (c.dataset.gameId || '').split('-')[0].toLowerCase();
    c.classList.toggle('active', cid === prefix);
  });
  document.getElementById('browseFilterClear').style.display = '';
  _loadBrowseColumns();
}

function clearBrowseGameFilter() {
  _browseGameFilter = null;
  document.querySelectorAll('#browseGameList .game-card').forEach(c => c.classList.remove('active'));
  document.getElementById('browseFilterClear').style.display = 'none';
  _loadBrowseColumns();
}

function _matchesGameFilter(s) {
  if (!_browseGameFilter) return true;
  const sid = (s.game_id || '').split('-')[0].toLowerCase();
  return sid === _browseGameFilter;
}

function _loadBrowseColumns() {
  loadBrowseHuman();
  loadBrowseAI();
  loadBrowseMy();
}

// ── Table builders ───────────────────────────────────────────────────────

function _buildSessionTable(sessions, isLocal) {
  const table = document.createElement('table');
  table.className = 'browse-table';
  // Header
  const thead = document.createElement('thead');
  thead.innerHTML = `<tr>
    <th>Time</th>
    <th>Game</th>
    <th>Result</th>
    <th>Lv</th>
    <th>Steps</th>
    <th>Duration</th>
    <th class="browse-th-actions">Actions</th>
  </tr>`;
  table.appendChild(thead);
  // Body
  const tbody = document.createElement('tbody');
  for (const s of sessions) {
    tbody.appendChild(_buildSessionTr(s, isLocal));
  }
  table.appendChild(tbody);
  return table;
}

function _buildSessionTr(s, isLocal) {
  const tr = document.createElement('tr');
  tr.className = 'browse-tr';

  // Timestamp
  const date = new Date((s.created_at || 0) * 1000);
  const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

  // Game code with version
  const gameCode = (s.game_id || '?').split('-')[0];
  const ver = s.game_version || '';
  // Version dir like "00000005" → "v5"
  const verDisplay = ver && ver !== 'unknown' ? ` v${parseInt(ver, 10) || ver}` : '';

  // Result
  const result = s.result || 'NOT_FINISHED';
  const resultLabel = result === 'NOT_FINISHED' ? '...' : result === 'GAME_OVER' ? 'LOST' : result;
  const resultClass = `s-result-${result}`;

  // Levels
  const levels = s.levels != null ? s.levels : '\u2014';

  // Steps
  const steps = s.steps || 0;

  // Duration
  const durationStr = (s.duration_seconds || s.duration) ? formatDuration(s.duration_seconds || s.duration) : '\u2014';

  // Live tag — true if live_mode flag set OR session is actively streaming
  const isLive = s.live_mode === 1 || s.live_mode === true || s.mode === 'stream_live';

  // Action buttons — live sessions link to Observatory in live mode
  const replayBtn = isLive
    ? `<button class="btn browse-btn browse-live-btn" onclick="event.stopPropagation(); window.open('/#obs?session=${s.id}&live=true','_blank');" title="Watch live in Observatory">&#128250;</button>`
    : `<button class="btn browse-btn" onclick="event.stopPropagation(); window.open('/share?id=${s.id}','_blank');" title="Open shareable replay">&#9654;</button>`;
  const resumeBtn = result === 'NOT_FINISHED'
    ? `<button class="btn btn-primary browse-btn" onclick="event.stopPropagation(); browseResume('${s.id}');" title="Resume playing">&#9198;</button>`
    : '';
  const copyBtn = `<button class="btn browse-btn browse-copy-btn" onclick="event.stopPropagation(); _browseCopyId('${s.id}', this);" title="Copy session ID">&#128203;</button>`;
  const deleteBtn = isLocal
    ? `<button class="btn btn-danger browse-btn" onclick="event.stopPropagation(); browseDeleteLocal('${s.id}', this);" title="Delete local session">&times;</button>`
    : '';

  tr.innerHTML = `
    <td class="browse-td-time">${dateStr}</td>
    <td class="browse-td-game"><span class="s-game">${gameCode}</span><span class="browse-ver">${verDisplay}</span>${isLive ? ' <span class="live-tag" style="font-size:8px;padding:1px 4px;background:#dc2626;color:#fff;border-radius:3px;font-weight:700;letter-spacing:0.5px;">&#128994; LIVE</span>' : ''}</td>
    <td class="browse-td-result"><span class="s-result ${resultClass}">${resultLabel}</span></td>
    <td class="browse-td-levels">${levels}</td>
    <td class="browse-td-steps">${steps}</td>
    <td class="browse-td-duration">${durationStr}</td>
    <td class="browse-td-actions">${replayBtn}${resumeBtn}${copyBtn}${deleteBtn}</td>`;
  return tr;
}

function _browseCopyId(sid, btn) {
  navigator.clipboard.writeText(sid).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '&#10003;';
    btn.classList.add('browse-copied');
    setTimeout(() => { btn.innerHTML = orig; btn.classList.remove('browse-copied'); }, 1200);
  });
}

// ── Render into column ───────────────────────────────────────────────────

function _renderSessionColumn(el, countEl, sessions, emptyMsg, isLocal) {
  countEl.textContent = sessions.length ? `(${sessions.length})` : '';
  if (!sessions.length) {
    el.innerHTML = `<div class="browse-empty">${emptyMsg}</div>`;
    return;
  }
  el.innerHTML = '';
  el.appendChild(_buildSessionTable(sessions, isLocal));
}

// ── Human Sessions column ────────────────────────────────────────────────

async function loadBrowseHuman() {
  const el = document.getElementById('browseHumanList');
  const countEl = document.getElementById('browseHumanCount');
  el.innerHTML = '<div class="browse-empty">Loading...</div>';
  try {
    const data = await fetchJSON('/api/sessions?player_type=human');
    let sessions = (data.sessions || []).filter(s => (s.steps || 0) >= 1);
    if (MODE === 'prod') sessions = sessions.filter(s => s.game_id !== 'fd01-00000001');
    sessions = sessions.filter(_matchesGameFilter);
    _renderSessionColumn(el, countEl, sessions,
      _browseGameFilter ? 'No human sessions for this game.' : 'No human sessions yet.');
  } catch (e) {
    el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
  }
}

// ── AI Sessions column ───────────────────────────────────────────────────

async function loadBrowseAI() {
  const el = document.getElementById('browseAIList');
  const countEl = document.getElementById('browseAICount');
  el.innerHTML = '<div class="browse-empty">Loading...</div>';
  try {
    // Fetch regular sessions and live sessions in parallel
    const [agentData, liveData] = await Promise.allSettled([
      fetchJSON('/api/sessions?player_type=agent'),
      fetchJSON('/api/sessions/live'),
    ]);

    let sessions = ((agentData.status === 'fulfilled' ? agentData.value.sessions : null) || [])
      .filter(s => (s.steps || 0) >= 5);
    if (MODE === 'prod') sessions = sessions.filter(s => s.game_id !== 'fd01-00000001');

    // Merge live sessions (may not be in main list yet)
    const liveSessions = (liveData.status === 'fulfilled' ? liveData.value.sessions : null) || [];
    const liveIds = new Set(liveSessions.map(s => s.id));
    // Remove any live sessions already in main list (avoid duplicates)
    const nonLiveSessions = sessions.filter(s => !liveIds.has(s.id));
    // Mark live sessions
    for (const s of liveSessions) s.mode = 'stream_live';
    // Live sessions to the top, then regular
    sessions = [...liveSessions, ...nonLiveSessions];

    sessions = sessions.filter(_matchesGameFilter);
    _renderSessionColumn(el, countEl, sessions,
      _browseGameFilter ? 'No AI sessions for this game.' : 'No AI sessions with 5+ steps yet.');
  } catch (e) {
    el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
  }
}

// ── My Sessions column ──────────────────────────────────────────────────

async function loadBrowseMy() {
  const el = document.getElementById('browseMyList');
  const countEl = document.getElementById('browseMyCount');

  if (currentUser) {
    el.innerHTML = '<div class="browse-empty">Loading...</div>';
    try {
      const data = await fetchJSON('/api/sessions?mine=1');
      const serverSessions = data.sessions || [];
      const localSessions = getLocalSessions();
      const byId = {};
      for (const s of serverSessions) byId[s.id] = s;
      for (const s of localSessions) { if (!byId[s.id]) byId[s.id] = s; }
      let merged = Object.values(byId).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      merged = merged.filter(_matchesGameFilter);
      _renderSessionColumn(el, countEl, merged,
        _browseGameFilter ? 'No sessions for this game.' : 'No sessions yet.');
    } catch (e) {
      el.innerHTML = `<div class="browse-empty">Error: ${e.message}</div>`;
    }
    return;
  }

  // Not logged in — local-only sessions
  let localSessions = getLocalSessions().filter(_matchesGameFilter);
  _renderSessionColumn(el, countEl, localSessions,
    _browseGameFilter ? 'No local sessions for this game.' : 'Log in to see sessions across devices, or play a game.',
    true);
}

// ── Shared helpers ───────────────────────────────────────────────────────

async function fetchAllSessions(forceRefresh) {
  if (_browseGlobalCache && !forceRefresh) return _browseGlobalCache;
  const data = await fetchJSON('/api/sessions');
  let serverSessions = data.sessions || [];
  if (MODE === 'prod') {
    const byId = {};
    for (const s of serverSessions) byId[s.id] = s;
    for (const s of getLocalSessions()) { if (!byId[s.id]) byId[s.id] = s; }
    serverSessions = Object.values(byId);
  }
  serverSessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  _browseGlobalCache = serverSessions;
  return serverSessions;
}

function browseReplay(sid) {
  showAppView('play');
  loadReplay(sid);
}

function browseResume(sid) {
  showAppView('play');
  if (!sessions.has(sid)) {
    if (activeSessionId && sessions.has(activeSessionId)) {
      saveSessionToState();
      detachSessionView(activeSessionId);
    }
    const s = new SessionState(sid);
    sessions.set(sid, s);
    activeSessionId = sid;
    attachSessionView(sid);
    renderSessionTabs();
  } else {
    switchSession(sid);
  }
  resumeSession(sid);
}

function browseDeleteLocal(sid, btn) {
  if (!confirm('Delete this local session?')) return;
  deleteLocalSession(sid);
  const row = btn.closest('tr');
  if (row) row.remove();
}
