// ═══════════════════════════════════════════════════════════════════════════
// SESSION.JS — Main coordinator and entry point (Phase 9 modularization)
// ═══════════════════════════════════════════════════════════════════════════
//
// This is the residual orchestration module after Phase 9 modularization.
// It coordinates the extracted session modules and handles:
// - Global session state management (sessionId, currentGrid, moveHistory, etc.)
// - Multi-session tabs and switching (createNewSession, switchSession, closeSession, renderSessionTabs)
// - Session utilities (resetGlobalsToBlank, saveSessionIndex, loadSessionIndex, restoreSessionsFromLocalStorage)
// - Auth state and functions (currentUser, checkAuthStatus(), doLogout(), sendMagicLink(), etc.)
// - App initialization (initApp())
//
// MODULARIZATION: The following modules are loaded BEFORE this script:
// - session-storage.js (localStorage ops, replayData)
// - session-replay.js (replay UI, live scrubber, loadSessionHistory)
// - session-persistence.js (Turnstile, upload, sharing, renderRestoredReasoning)
// - session-views.js (view routing, browse, prompts, resume, branch)
//
// Load order is critical. See templates/index.html for script tag sequence.
// ═══════════════════════════════════════════════════════════════════════════

// Global auth state — currentUser is declared in state.js (loaded before this script)

function resetGlobalsToBlank() {
  sessionId = null;
  currentGrid = null;
  previousGrid = null;
  currentChangeMap = null;
  currentState = {};
  stepCount = 0;
  llmCallCount = 0;
  turnCounter = 0;
  moveHistory = [];
  undoStack = [];
  llmObservations = [];
  autoPlaying = false;
  action6Mode = false;
  sessionTotalTokens = { input: 0, output: 0, cost: 0 };
  sessionStepsBuffer = [];
  sessionStartTime = null;
  syncStepCounter = 0;
  _cachedCompactSummary = '';
  _compactSummaryAtCall = 0;
  _compactSummaryAtStep = 0;
  _lastCompactPrompt = '';
  hideLiveScrubber();
}

function createNewSession() {
  // Hide menu view if active
  if (_menuActive) {
    _menuActive = false;
    document.getElementById('menuView').classList.remove('visible');
    document.getElementById('sessionViewHost').style.display = '';
    document.getElementById('outerLayout')?.classList.remove('view-observatory');
  }
  // Save + detach current session if one exists
  if (activeSessionId && sessions.has(activeSessionId)) {
    saveSessionToState();
    detachSessionView(activeSessionId);
  }
  // Create a pending session with fresh DOM
  const pendingId = 'pending_' + Math.random().toString(36).slice(2, 10);
  const s = new SessionState(pendingId);
  sessions.set(pendingId, s);
  activeSessionId = pendingId;
  resetGlobalsToBlank();
  // Attach fresh DOM from template
  attachSessionView(pendingId);
  // Reset UI on the fresh DOM
  canvas.style.display = 'none';
  document.getElementById('emptyState').style.display = '';
  document.getElementById('transportBar').style.display = 'none';
  document.getElementById('gameTitle').textContent = 'No game selected';
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = '—';
  statusEl.className = 'status status-NOT_PLAYED';
  document.getElementById('levelInfo').textContent = '';
  document.getElementById('stepCounter').textContent = '';
  document.getElementById('reasoningContent').innerHTML =
    '<div class="empty-state" style="height:auto;font-size:12px;">Select a game from the sidebar to start.</div>';
  // Unlock sidebar for game selection
  updatePanelBlur();
  updateGameListLock();
  renderSessionTabs();
  saveSessionIndex();
}

function switchSession(targetId) {
  if (targetId === activeSessionId && !_menuActive) return;
  const target = sessions.get(targetId);
  if (!target) return;

  const wasMenu = _menuActive;
  // Hide menu view if active
  if (_menuActive) {
    _menuActive = false;
    document.getElementById('menuView').classList.remove('visible');
    document.getElementById('sessionViewHost').style.display = '';
    document.getElementById('outerLayout')?.classList.remove('view-observatory');
  }

  // If returning from menu to the same session, just re-show — don't re-attach
  if (wasMenu && targetId === activeSessionId) {
    renderSessionTabs();
    // Re-enter obs mode if session is still in autoplay
    if (target.autoPlaying) enterObsMode(target);
    return;
  }

  // Close replay if open
  closeReplay();
  // Save + detach current session (do NOT stop autoplay — let it run in background)
  if (activeSessionId && sessions.has(activeSessionId) && activeSessionId !== targetId) {
    saveSessionToState();
    detachSessionView(activeSessionId);
  }
  // Switch
  activeSessionId = targetId;
  attachSessionView(targetId);
  restoreSessionFromState(target);
  renderSessionTabs();

  // If this is a restored stub (no grid data), resume from server
  if (!target.currentGrid && target.sessionId && !target.sessionId.startsWith('pending_')) {
    resumeSession(target.sessionId);
  }

  // If target session is in obs/autoplay mode, re-enter observatory view
  if (target.autoPlaying || isObsModeActive()) {
    enterObsMode(target);
  }
}

function closeSession(id) {
  const s = sessions.get(id);
  if (!s) return;

  try {
    // Stop autoplay if running
    if (s.autoPlaying) { s.autoPlaying = false; }
    if (id === activeSessionId && autoPlaying) { autoPlaying = false; updateAutoBtn(); }
    // Abort in-flight LLM fetch
    if (s.abortController) { s.abortController.abort(); s.abortController = null; }
    // Clear REPL namespace for this session
    if (_pyodideWorker && _pyodideReady) {
      const clearId = ++_pyodideCallId;
      _pyodideWorker.postMessage({type: 'clear_session', id: clearId, session_id: s.sessionId || id});
    }
    // Upload session to main DB before deleting (if enough steps)
    if (id === activeSessionId) saveSessionToState();
    uploadClosedSession(s);
    // Persist session data to localStorage
    try {
      const steps = s.sessionStepsBuffer || [];
      if (steps.length > 0 && s.gameId) {
        saveLocalSession({
          id: s.sessionId || id,
          game_id: s.currentState?.game_id || s.gameId,
          model: s.model || '',
          result: s.currentState?.state || s.status || 'NOT_FINISHED',
          steps: s.stepCount || steps.length,
          levels: s.currentState?.levels_completed || 0,
          created_at: s.createdAt || (Date.now() / 1000),
        }, steps);
      }
    } catch (e) { console.warn('[closeSession] saveLocalSession failed:', e); }
  } catch (e) { console.warn('[closeSession] pre-delete step failed:', e); }

  // Detach + free DOM if this is the active session
  if (id === activeSessionId) {
    detachSessionView(id);
  }
  // Free detached DOM memory
  s._viewEl = null;

  // Always delete and update UI regardless of any errors above
  sessions.delete(id);

  try {
    if (id === activeSessionId) {
      const remaining = [...sessions.keys()];
      if (remaining.length > 0) {
        switchSession(remaining[remaining.length - 1]);
      } else {
        activeSessionId = null;
        resetGlobalsToBlank();
      }
    }
  } catch (e) { console.warn('[closeSession] post-delete UI update failed:', e); }

  renderSessionTabs();
  saveSessionIndex();
  updateGameListLock();
  updateEmptyAppState();
}

function updatePanelBlur() {
  // Don't blur the right panel — only blur after a game has started and ended,
  // not before. Keep it always visible so users can configure settings first.
}

function updateGameListLock() {
  const sidebar = document.getElementById('gameSidebar');
  if (sidebar) {
    // Lock the sidebar once a session has any steps — can't switch games mid-session
    const cur = getActiveSession();
    const hasSteps = (cur && cur.stepCount > 0) || stepCount > 0;
    const shouldLock = sessionId && hasSteps;
    sidebar.classList.toggle('locked', shouldLock);
  }
}

function updateEmptyAppState() {
  const empty = document.getElementById('emptyAppState');
  const sessionHost = document.getElementById('sessionViewHost');
  const menuView = document.getElementById('menuView');
  if (!empty || !sessionHost) return;
  if (_currentView !== 'play') return; // only applies to agent view
  if (_browseActive) return; // browse view handles its own display
  if (_menuActive) return; // menu view handles its own display
  if (sessions.size === 0) {
    // Show menu view instead of hero when no sessions
    empty.style.display = 'none';
    sessionHost.style.display = 'none';
    const sidebar = document.getElementById('gameSidebar');
    if (sidebar) sidebar.style.display = 'none';
    _menuActive = true;
    menuView.classList.add('visible');
    renderMenuSessions();
    renderSessionTabs();
  } else {
    empty.style.display = 'none';
    menuView.classList.remove('visible');
    const sidebar = document.getElementById('gameSidebar');
    if (sidebar) sidebar.style.display = '';
    sessionHost.style.display = '';
  }
}

// ── Countdown timer functions ────────────────────────────────────────────

function startCountdown(s) { /* removed — countdown disabled */ }
function stopCountdown(s) { /* removed — countdown disabled */ }

// ── Session tab bar rendering ─────────────────────────────────────────────

function getTabDotClass(s) {
  if (s.status === 'WIN') return 'tab-dot-win';
  if (s.status === 'GAME_OVER') return 'tab-dot-gameover';
  if ((s.autoPlaying || s.waitingForLLM) && s.status === 'NOT_FINISHED') return 'tab-dot-running';
  return 'tab-dot-idle';
}

function renderSessionTabs() {
  const bar = document.getElementById('sessionTabBar');
  if (!bar) return;
  bar.innerHTML = '';

  // Menu tab (always first)
  const menuTab = document.createElement('div');
  menuTab.className = 'session-tab-menu' + (_menuActive ? ' active' : '');
  menuTab.innerHTML = '<span class="menu-icon">&#9776;</span> Menu';
  menuTab.onclick = () => showMenuView();
  bar.appendChild(menuTab);

  // Session tabs
  for (const [id, s] of sessions) {
    const tab = document.createElement('div');
    tab.className = 'session-tab' + (id === activeSessionId && !_menuActive ? ' active' : '');
    const label = s.tabLabel || s.gameId || (id.startsWith('pending_') ? 'New Session' : id.slice(0, 8));
    const dotClass = getTabDotClass(s);
    const stepBadge = s.stepCount > 0 ? `<span class="tab-steps">${s.stepCount}</span>` : '';
    tab.innerHTML = `
      <span class="tab-dot ${dotClass}"></span>${stepBadge}
      <span class="tab-label">${label}</span>
      <span class="tab-countdown" id="tabCountdown_${id}"></span>
      <button class="tab-close" onclick="event.stopPropagation(); closeSession('${id}');">&times;</button>`;
    tab.title = `${s.gameId || 'No game'} | ${s.stepCount} steps | $${(s.sessionTotalTokens?.cost || 0).toFixed(3)}`;
    tab.onclick = () => switchSession(id);
    bar.appendChild(tab);
  }

  // Quick + button for new session
  const newBtn = document.createElement('button');
  newBtn.className = 'session-tab-new';
  newBtn.textContent = '+';
  newBtn.title = 'New Session';
  newBtn.onclick = createNewSession;
  bar.appendChild(newBtn);

  updateEmptyAppState();
}

// ── localStorage session index ───────────────────────────────────────────

const MULTI_SESSION_KEY = 'arc_multi_sessions';

function saveSessionIndex() {
  try {
    const index = [];
    for (const [id, s] of sessions) {
      if (id.startsWith('pending_') && !s.gameId) continue; // skip truly empty pending
      index.push({
        id: s.sessionId || id,
        gameId: s.gameId || '',
        tabLabel: s.tabLabel || '',
        model: s.model || '',
        status: s.status || 'NOT_PLAYED',
        steps: s.stepCount || 0,
        cost: s.sessionTotalTokens?.cost || 0,
        createdAt: s.createdAt || 0,
      });
    }
    localStorage.setItem(MULTI_SESSION_KEY, JSON.stringify(index));
  } catch {}
}

function loadSessionIndex() {
  try {
    return JSON.parse(localStorage.getItem(MULTI_SESSION_KEY)) || [];
  } catch { return []; }
}

function restoreSessionsFromLocalStorage() {
  const index = loadSessionIndex();
  if (!index.length) return;
  for (const meta of index) {
    if (sessions.has(meta.id)) continue;
    const s = new SessionState(meta.id);
    s.gameId = meta.gameId || '';
    s.tabLabel = meta.tabLabel || '';
    s.model = meta.model || '';
    s.status = meta.status || 'NOT_PLAYED';
    s.stepCount = meta.steps || 0;
    s.sessionTotalTokens = { input: 0, output: 0, cost: meta.cost || 0 };
    s.createdAt = meta.createdAt || 0;
    sessions.set(meta.id, s);
  }
  if (sessions.size > 0 && !activeSessionId) {
    activeSessionId = [...sessions.keys()][0];
  }
  renderSessionTabs();

  // Auto-resume only if we're about to show the agent/play view
  // (avoids async resume overwriting human view on default load)
  if (_currentView === 'play' && activeSessionId && !activeSessionId.startsWith('pending_')) {
    resumeSession(activeSessionId);
  } else {
    updateGameListLock();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

async function initApp() {
  console.log('[INIT] initApp starting');
  try {
    // Render scaffolding settings (must happen before loadModels populates selects)
    migrateOldSettingsToScaffolding();
    const savedScaffolding = localStorage.getItem('arc_scaffolding_type') || 'linear';
    renderScaffoldingSettings(savedScaffolding);
    loadScaffoldingFromStorage(savedScaffolding);

    loadGames();
    await loadModels();  // await so selects are populated before template capture
    // Capture populated DOM as clonable template for new sessions
    captureSessionTemplate();

    if (FEATURES.copilot) checkCopilotStatus();
    if (FEATURES.puter_js) puterKvCheckResume();

    // Establish view FIRST so _currentView is set before session restore
    // Default to human view for empty hash, #human, or #agent (old default)
    if (location.hash && location.hash !== '#' && location.hash !== '#human' && location.hash !== '#agent') {
      _routeFromHash();
    } else {
      showAppView('human');
    }

    // Restore sessions AFTER view is set (auto-resume only fires in agent/play view)
    restoreSessionsFromLocalStorage();

    // Auth: check login status (async, doesn't block init)
    checkAuthStatus();
    console.log('[INIT] initApp completed');
  } catch (e) {
    console.error('[INIT] initApp crashed:', e);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// AUTH — Magic link login
// ═══════════════════════════════════════════════════════════════════════════

function updateAuthUI() {
  console.log('[AUTH] updateAuthUI called, currentUser:', currentUser);
  const loginBtn = document.getElementById('loginBtn');
  const userBadge = document.getElementById('userBadge');
  if (currentUser) {
    loginBtn.style.display = 'none';
    userBadge.style.display = '';
    const label = currentUser.display_name || currentUser.email.split('@')[0];
    document.getElementById('userBadgeLabel').textContent = label;
    document.getElementById('userMenuEmail').textContent = currentUser.email;
  } else {
    loginBtn.style.display = '';
    userBadge.style.display = 'none';
  }
}

function toggleUserMenu() {
  const menu = document.getElementById('userMenu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

// Close user menu on outside click
document.addEventListener('click', (e) => {
  const badge = document.getElementById('userBadge');
  const menu = document.getElementById('userMenu');
  if (badge && menu && !badge.contains(e.target)) {
    menu.style.display = 'none';
  }
});

function showLoginModal() {
  try {
    console.log('[AUTH] showLoginModal called');
    const modal = document.getElementById('loginModal');
    if (!modal) { console.error('[AUTH] loginModal element not found!'); return; }
    modal.style.display = 'flex';
    console.log('[AUTH] modal display set to flex');
    const s1 = document.getElementById('loginStep1');
    const s2 = document.getElementById('loginStep2');
    const err = document.getElementById('loginError');
    if (s1) s1.style.display = '';
    if (s2) s2.style.display = 'none';
    if (err) err.style.display = 'none';
    const emailEl = document.getElementById('loginEmail');
    if (emailEl) { emailEl.value = ''; emailEl.focus(); }
    console.log('[AUTH] modal opened successfully', { s1: !!s1, s2: !!s2, err: !!err, email: !!emailEl });
  } catch (e) {
    console.error('[AUTH] showLoginModal error:', e);
  }
}

function hideLoginModal() {
  document.getElementById('loginModal').style.display = 'none';
}

// Close modal on backdrop click
document.getElementById('loginModal')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) hideLoginModal();
});

// Submit on Enter in email field
document.getElementById('loginEmail')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMagicLink();
});

async function sendMagicLink() {
  const email = document.getElementById('loginEmail').value.trim();
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginSendBtn');
  if (!email || !email.includes('@')) {
    errEl.textContent = 'Please enter a valid email address.';
    errEl.style.display = '';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Sending...';
  errEl.style.display = 'none';
  try {
    const resp = await fetch('/api/auth/magic-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errEl.textContent = data.error || 'Failed to send link';
      errEl.style.display = '';
      btn.disabled = false;
      btn.textContent = 'Send login link';
      return;
    }
    // Dev mode: if code returned, auto-verify
    if (data.dev_code) {
      window.location.href = '/api/auth/verify?code=' + data.dev_code;
      return;
    }
    document.getElementById('loginStep1').style.display = 'none';
    document.getElementById('loginStep2').style.display = '';
    document.getElementById('loginSentEmail').textContent = email;
  } catch (e) {
    errEl.textContent = 'Network error. Please try again.';
    errEl.style.display = '';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send login link';
  }
}

async function doLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (e) { /* ignore */ }
  currentUser = null;
  updateAuthUI();
  document.getElementById('userMenu').style.display = 'none';
}

async function checkAuthStatus() {
  console.log('[AUTH] checkAuthStatus called');
  try {
    const resp = await fetch('/api/auth/status');
    const data = await resp.json();
    console.log('[AUTH] status response:', data);
    if (data.authenticated && data.user) {
      currentUser = data.user;
      updateAuthUI();
      claimLocalSessions();
    } else {
      currentUser = null;
      updateAuthUI();
    }
  } catch (e) {
    console.warn('[AUTH] checkAuthStatus failed:', e);
    currentUser = null;
    updateAuthUI();
  }
  // Clean ?logged_in param from URL
  if (new URLSearchParams(window.location.search).has('logged_in')) {
    const url = new URL(window.location);
    url.searchParams.delete('logged_in');
    window.history.replaceState({}, '', url.pathname + url.search);
  }
}

async function claimLocalSessions() {
  if (!currentUser) return;
  // Collect session IDs from localStorage
  const ids = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith('arc_session_')) {
      ids.push(key.replace('arc_session_', ''));
    }
  }
  if (ids.length === 0) return;
  try {
    await fetch('/api/auth/claim-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_ids: ids }),
    });
  } catch (e) {
    console.warn('Claim sessions failed:', e);
  }
}

// If no Turnstile gate (not configured), init after all scripts are loaded
if (turnstileVerified) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initApp());
  } else {
    initApp();
  }
}
