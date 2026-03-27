// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking) + Claude Sonnet 4.6
// Date: 27-Mar-2026
// PURPOSE: Session browser, fetch, load, and replay for Observatory page.
//   Allows users to browse saved sessions, filter by game/model/result, load
//   historical session data, display replay metadata, and return to live mode.
//   Added: live mode via EventSource SSE when URL has ?live=true or session is stream_live.
// Depends on: obs-page.js (allEvents, state, resetState, renderNewEvents, renderTimeline, renderGameGrid, etc.)
// SRP/DRY check: Pass — live mode handled here; swimlane rendering delegated to renderNewEvents.

// ── Session Browser ──

let replayMode = false;
let allSessions = [];

function toggleSessionBrowser() {
  const overlay = document.getElementById('sessionOverlay');
  const visible = overlay.classList.toggle('visible');
  document.getElementById('browseBtn').classList.toggle('active', visible);
  if (visible) fetchSessionList();
}

async function fetchSessionList() {
  try {
    // Try both sources and merge (file-based + central DB)
    const [fileRes, dbRes] = await Promise.allSettled([
      fetch('/api/sessions/browse'),
      fetch('/api/sessions/list-for-obs'),
    ]);
    const seen = new Set();
    allSessions = [];
    for (const res of [fileRes, dbRes]) {
      if (res.status === 'fulfilled' && res.value.ok) {
        const data = await res.value.json();
        for (const s of (data.sessions || [])) {
          if (!seen.has(s.id)) { seen.add(s.id); allSessions.push(s); }
        }
      }
    }
    allSessions.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    // Populate model filter dropdown
    const models = [...new Set(allSessions.map(s => s.model).filter(Boolean))].sort();
    const modelSelect = document.getElementById('filterModel');
    const curModel = modelSelect.value;
    modelSelect.innerHTML = '<option value="">All models</option>';
    for (const m of models) {
      modelSelect.innerHTML += `<option value="${escapeHtmlAttr(m)}">${escapeHtmlAttr(m.replace(/^(gemini|claude|groq|mistral|ollama)\//, ''))}</option>`;
    }
    modelSelect.value = curModel;

    applySessionFilters();
  } catch (e) {
    console.error('Failed to fetch sessions:', e);
  }
}

function applySessionFilters() {

  const gameFilter = (document.getElementById('filterGame').value || '').toLowerCase();
  const resultFilter = document.getElementById('filterResult').value;
  const modelFilter = document.getElementById('filterModel').value;

  const filtered = allSessions.filter(s => {
    if (gameFilter && !(s.game_id || '').toLowerCase().includes(gameFilter)) return false;
    if (resultFilter && s.result !== resultFilter) return false;
    if (modelFilter && s.model !== modelFilter) return false;
    return true;
  });

  const tbody = document.getElementById('sessionListBody');
  document.getElementById('sessionCount').textContent = `${filtered.length} of ${allSessions.length}`;

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#555;padding:20px">No sessions found</td></tr>';
    return;
  }
  tbody.innerHTML = '';
  for (const s of filtered) {
    const tr = document.createElement('tr');
    const result = (s.result || '').toUpperCase();
    const badgeClass = result.includes('WON') || result.includes('WIN') || result.includes('COMPLETE') ? 'won'
      : result.includes('LOST') || result.includes('FAIL') || result.includes('DEAD') ? 'lost' : 'other';
    const date = s.created_at ? new Date(s.created_at * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--';
    const cost = s.total_cost ? '$' + s.total_cost.toFixed(3) : '--';
    tr.innerHTML = `
      <td style="color:#e0e0e0;font-weight:500">${escapeHtmlAttr(s.game_id || '')}</td>
      <td>${escapeHtmlAttr((s.model || '').replace(/^(gemini|claude|groq|mistral|ollama)\//, ''))}</td>
      <td>${s.steps || 0}</td>
      <td>${s.levels || 0}</td>
      <td><span class="result-badge ${badgeClass}">${escapeHtmlAttr(s.result || 'N/A')}</span></td>
      <td>${cost}</td>
      <td style="color:#666">${date}</td>
    `;
    tr.addEventListener('click', () => loadSession(s.id, s.game_id));
    tbody.appendChild(tr);
  }
}

async function loadSession(sessionId, gameId) {
  // Close browser
  document.getElementById('sessionOverlay').classList.remove('visible');
  document.getElementById('browseBtn').classList.remove('active');

  // Stop live polling
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  replayMode = true;

  // Reset state
  resetState();
  setConn(false);
  document.getElementById('connStatus').textContent = 'REPLAY';
  document.getElementById('connStatus').className = 'conn';
  document.getElementById('connStatus').style.color = '#3b82f6';
  document.getElementById('replayBadge').textContent = `[${gameId || sessionId.slice(0, 8)}]`;

  // Fetch reconstructed obs events
  try {
    const r = await fetch(`/api/sessions/${sessionId}/obs-events`);
    if (!r.ok) { console.error('Failed to load session obs events'); return; }
    const data = await r.json();
    if (data.events && data.events.length > 0) {
      data.events.forEach(normalizeEvent);
      allEvents = data.events;

      // Compute status summary from events
      let totalIn = 0, totalOut = 0, totalCost = 0, totalCalls = 0, maxStep = 0;
      let model = '';
      for (const ev of allEvents) {
        if (ev.input_tokens) totalIn += ev.input_tokens;
        if (ev.output_tokens) totalOut += ev.output_tokens;
        if (ev.cost) totalCost += ev.cost;
        if (ev.event === 'llm_call' || ev.event === 'orchestrator_decide') { totalCalls++; if (ev.model) model = ev.model; }
        if (ev.step_num != null && ev.step_num > maxStep) maxStep = ev.step_num;
        trackEventTokens(ev);
      }

      // Populate status bar
      document.getElementById('sGame').textContent = gameId || '--';
      document.getElementById('sState').textContent = 'REPLAY';
      document.getElementById('sStep').textContent = maxStep;
      document.getElementById('sCalls').textContent = totalCalls;
      document.getElementById('sTokens').textContent = `${fmtK(totalIn)} / ${fmtK(totalOut)}`;
      if (totalCost > 0) {
        document.getElementById('sCost').textContent = '$' + totalCost.toFixed(3);
      }
      const elapsed = allEvents.length > 0 ? allEvents[allEvents.length - 1].elapsed_s || 0 : 0;
      if (elapsed < 60) {
        document.getElementById('sElapsed').textContent = `${Math.round(elapsed)}s`;
      } else {
        document.getElementById('sElapsed').textContent = `${(elapsed / 60).toFixed(1)}m`;
      }
      document.getElementById('sAgent').textContent = model || '--';

      // Render
      renderNewEvents(allEvents);
      renderTimeline();

      // Show first grid if available
      const firstGrid = allEvents.find(ev => ev.grid && ev.grid.length > 0);
      if (firstGrid) {
        currentGrid = firstGrid.grid;
        renderGameGrid(firstGrid.grid);
      }
    }
  } catch (e) {
    console.error('Failed to load session:', e);
  }
}

function returnToLive() {
  replayMode = false;
  resetState();
  document.getElementById('replayBadge').textContent = '';
  document.getElementById('connStatus').style.color = '';
  poll();
}

// ── Live Session Streaming via EventSource (SSE) ─────────────────────────

let _liveEventSource = null;

/**
 * Load a session and subscribe to its live SSE stream.
 * Called when URL has &live=true or when a live session card is clicked.
 */
async function loadLiveSession(sessionId, gameId) {
  // Close any existing live stream
  closeLiveStream();

  // Close browser panel
  const overlay = document.getElementById('sessionOverlay');
  if (overlay) overlay.classList.remove('visible');
  const browseBtn = document.getElementById('browseBtn');
  if (browseBtn) browseBtn.classList.remove('active');

  // Stop poll timer
  if (typeof pollTimer !== 'undefined' && pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  replayMode = true;

  resetState();
  setConn(false);
  const connStatus = document.getElementById('connStatus');
  if (connStatus) {
    connStatus.textContent = 'LIVE';
    connStatus.className = 'conn';
    connStatus.style.color = '#dc2626';
  }
  const replayBadge = document.getElementById('replayBadge');
  if (replayBadge) replayBadge.textContent = `[${gameId || sessionId.slice(0, 8)}] 🔴`;

  // Show live indicator
  _setLiveIndicator(true);

  const url = `/api/sessions/${sessionId}/obs-events?live=true`;
  _liveEventSource = new EventSource(url);

  let initialized = false;

  _liveEventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);

      if (!initialized) {
        // First message contains existing events + live flag
        initialized = true;
        const existingEvents = data.events || [];
        if (existingEvents.length > 0) {
          existingEvents.forEach(ev => { if (typeof normalizeEvent === 'function') normalizeEvent(ev); });
          allEvents = existingEvents;
          renderNewEvents(allEvents);
          if (typeof renderTimeline === 'function') renderTimeline();
          const firstGrid = allEvents.find(ev => ev.grid && ev.grid.length > 0);
          if (firstGrid && typeof renderGameGrid === 'function') {
            currentGrid = firstGrid.grid;
            renderGameGrid(firstGrid.grid);
          }
        }
        return;
      }

      // Subsequent messages are individual events
      if (data.event === 'stream_end') {
        // Session ended — transition to replay mode
        _setLiveIndicator(false);
        if (connStatus) {
          connStatus.textContent = 'REPLAY';
          connStatus.style.color = '#3b82f6';
        }
        if (replayBadge) replayBadge.textContent = `[${gameId || sessionId.slice(0, 8)}]`;
        closeLiveStream();
        return;
      }

      // Live event — append to swimlane
      if (typeof normalizeEvent === 'function') normalizeEvent(data);
      allEvents.push(data);
      if (typeof renderNewEvents === 'function') renderNewEvents([data]);
      if (typeof renderTimeline === 'function') renderTimeline();
      if (data.grid && data.grid.length > 0 && typeof renderGameGrid === 'function') {
        currentGrid = data.grid;
        renderGameGrid(data.grid);
      }
      // Update counters
      if (typeof trackEventTokens === 'function') trackEventTokens(data);

    } catch (err) {
      console.warn('Live SSE parse error:', err);
    }
  };

  _liveEventSource.onerror = (err) => {
    console.warn('Live SSE error:', err);
    _setLiveIndicator(false);
    if (connStatus) connStatus.style.color = '#f59e0b';
    // Don't close — EventSource auto-reconnects
  };
}

function closeLiveStream() {
  if (_liveEventSource) {
    _liveEventSource.close();
    _liveEventSource = null;
  }
  _setLiveIndicator(false);
}

function _setLiveIndicator(active) {
  const badge = document.getElementById('liveBadge');
  if (badge) {
    badge.style.display = active ? 'inline-block' : 'none';
    badge.textContent = '🔴 LIVE';
  }
}

// Check URL params on load — if ?session=X&live=true, auto-load in live mode
(function _checkUrlLiveParam() {
  const params = new URLSearchParams(window.location.search);
  // Also check hash params (#obs?session=X&live=true)
  const hash = window.location.hash.replace(/^#[^?]*\??/, '');
  const hashParams = new URLSearchParams(hash);

  const sessionId = params.get('session') || hashParams.get('session');
  const isLive = params.get('live') === 'true' || hashParams.get('live') === 'true';

  if (sessionId && isLive) {
    // Delay to let page initialize
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => loadLiveSession(sessionId, null));
    } else {
      setTimeout(() => loadLiveSession(sessionId, null), 300);
    }
  }
})();
