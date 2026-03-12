// ═══════════════════════════════════════════════════════════════════════════
// SESSION VIEWS — App routing, menu, and prompts management
// ═══════════════════════════════════════════════════════════════════════════
//
// This module handles:
// - App view routing and switching (showAppView, _routeFromHash)
// - Menu view (showMenuView, renderMenuSessions, menuResume)
// - Prompts/Memory tab editing (_humanizePromptName, renderPromptsTab, etc.)
// - Session view initialization and management
//
// Session view structure:
// - Play (agent) view: live game board with LLM agent
// - Human view: manual puzzle playing
// - Browse view: session browsing/filtering (delegated to session-views-grid.js)
// - Menu view: saved session list
// - Leaderboards, Contributors, Feedback views
//
// Dependencies:
// - showAppView() calls loadBrowseView() (from session-views-grid.js)
// - showAppView() calls resumeSession() (from session-views-history.js)
// - fetchJSON(), gameShortName(), renderGrid(), startGame(), updateUI() (from ui.js)
// - currentUser, currentState, currentGrid, sessionId, moveHistory, stepCount (from state.js)
// - sessions, activeSessionId, getActiveSession(), registerSession(), saveSessionToState(), renderSessionTabs(), updateEmptyAppState() (from ui.js globals)
// - getLocalSessions() (from session-storage.js)
// - getPrompt() (from llm.js)
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// MEMORY TAB (system prompt + hard memory editing)
// ═══════════════════════════════════════════════════════════════════════════

// ── Prompt section helpers (scaffolding-specific prompts from window.PROMPTS) ──

const _PROMPT_SECTION_MAP = {
  linear: ['shared', 'linear'],
  linear_interrupt: ['shared', 'linear'],
  rlm: ['shared', 'rlm'],
  three_system: ['shared', 'three_system'],
};

function _humanizePromptName(name) {
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _getPromptSections(schemaId) {
  const sections = _PROMPT_SECTION_MAP[schemaId] || ['shared'];
  const result = [];
  for (const section of sections) {
    const prompts = window.PROMPTS[section];
    if (!prompts) continue;
    for (const name of Object.keys(prompts).sort()) {
      result.push({ section, name, label: _humanizePromptName(name) });
    }
  }
  return result;
}

function _savePromptField(textarea) {
  const key = textarea.dataset.promptKey; // format: section.name
  if (!key) return;
  const [section, name] = key.split('.');
  const defaultVal = (window.PROMPTS[section] && window.PROMPTS[section][name]) || '';
  const lsKey = 'arc_prompt.' + key;
  if (textarea.value === defaultVal) {
    localStorage.removeItem(lsKey);
  } else {
    localStorage.setItem(lsKey, textarea.value);
  }
}

function _populatePromptFields() {
  document.querySelectorAll('textarea[data-prompt-key]').forEach(ta => {
    ta.value = getPrompt(ta.dataset.promptKey);
  });
}

// Which runtime fields each scaffold gets in the Prompts tab
const _PROMPTS_TAB_FEATURES = {
  linear:           { compact: true,  interrupt: false },
  linear_interrupt: { compact: true,  interrupt: true  },
  rlm:              { compact: false, interrupt: false },
  three_system:     { compact: false, interrupt: true  },
  two_system:       { compact: false, interrupt: true  },
};

function renderPromptsTab() {
  const container = document.getElementById('promptsTabBody');
  if (!container) return;
  const schemaId = localStorage.getItem('arc_scaffolding_type') || 'linear';
  const features = _PROMPTS_TAB_FEATURES[schemaId] || { compact: false, interrupt: false };
  const promptSections = _getPromptSections(schemaId);
  let html = '';
  for (const { section, name, label } of promptSections) {
    const key = `${section}.${name}`;
    html += `<div class="mem-section"><label>${label}</label>`;
    html += `<textarea data-prompt-key="${key}" rows="6" placeholder="${key}..."`;
    html += ` onblur="_savePromptField(this)"></textarea></div>`;
  }
  // Runtime fields (read-only, auto-generated) — only shown for relevant scaffolds
  if (features.compact) {
    html += '<div class="mem-section"><label>Compact Summary <span style="font-size:10px;color:var(--text-dim);text-transform:none;">(auto-generated)</span></label>';
    html += '<textarea id="memoryCompactSummary" rows="3" readonly placeholder="No compact summary yet." style="opacity:0.8;"></textarea></div>';
  }
  if (features.interrupt) {
    html += '<div class="mem-section"><label>Interrupt Result <span style="font-size:10px;color:var(--text-dim);text-transform:none;">(auto-generated)</span></label>';
    html += '<textarea id="memoryInterruptResult" rows="2" readonly placeholder="—" style="opacity:0.8;"></textarea></div>';
  }
  html += '<div style="font-size:9px;color:var(--dim);margin-top:4px;font-style:italic;">Edits to prompt templates auto-save to your browser on blur.</div>';
  container.innerHTML = html;
  _populatePromptFields();
  // Restore runtime fields
  const compactEl = document.getElementById('memoryCompactSummary');
  if (compactEl && _cachedCompactSummary) compactEl.value = _cachedCompactSummary;
}

// ═══════════════════════════════════════════════════════════════════════════
// APP ROUTING & VIEW MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════

let _browseActive = false;
let _menuActive = false;
let _currentView = 'human';  // tracks which top-level view is active (default: human)

// Hash-to-view mapping
const _VIEW_HASHES = { agent: 'play', human: 'human', sessions: 'browse', leaderboards: 'leaderboard', contributors: 'contributors', feedback: 'feedback' };
const _VIEW_TO_HASH = { play: 'agent', human: 'human', browse: 'sessions', leaderboard: 'leaderboards', contributors: 'contributors', feedback: 'feedback' };

function showAppView(view, skipHash) {
  // Update URL hash (unless called from hashchange handler)
  if (!skipHash) {
    const hash = _VIEW_TO_HASH[view] || 'human';
    if (location.hash !== '#' + hash) history.replaceState(null, '', '#' + hash);
  }

  _currentView = view;
  document.querySelectorAll('.top-nav .nav-link').forEach(l => l.classList.remove('active'));
  const links = document.querySelectorAll('.top-nav .nav-link');
  const browseView = document.getElementById('browseView');
  const sessionHost = document.getElementById('sessionViewHost');
  const tabBar = document.getElementById('sessionTabBar');
  const emptyApp = document.getElementById('emptyAppState');
  const menuView = document.getElementById('menuView');
  const humanView = document.getElementById('humanView');
  const leaderboardView = document.getElementById('leaderboardView');
  const contributorsView = document.getElementById('contributorsView');
  const feedbackView = document.getElementById('feedbackView');

  const sidebar = document.getElementById('gameSidebar');
  const outerLayout = document.getElementById('outerLayout');

  // Auto-pause human session when navigating away
  if (view !== 'human' && typeof _humanRecording !== 'undefined' && _humanRecording && !_humanPaused) {
    humanTogglePause();
  }

  // Hide everything first
  outerLayout.style.display = 'none';
  browseView.style.display = 'none';
  if (humanView) humanView.style.display = 'none';
  if (leaderboardView) leaderboardView.style.display = 'none';
  if (contributorsView) contributorsView.style.display = 'none';
  if (feedbackView) feedbackView.style.display = 'none';
  tabBar.style.display = 'none';
  emptyApp.style.display = 'none';
  menuView.classList.remove('visible');

  // Highlight nav link by href (no brittle index assumptions)
  const _navHighlight = hash => document.querySelector(`.top-nav a[href="#${hash}"]`)?.classList.add('active');
  if (view === 'browse') {
    _navHighlight('sessions');
    _browseActive = true;
    _menuActive = false;
    browseView.style.display = 'flex';
    loadBrowseView();
  } else if (view === 'human') {
    _navHighlight('human');
    _browseActive = false;
    _menuActive = false;
    if (humanView) {
      humanView.style.display = 'flex';
      if (typeof initHumanView === 'function') initHumanView();
    }
  } else if (view === 'leaderboard') {
    _navHighlight('leaderboards');
    _browseActive = false;
    _menuActive = false;
    if (leaderboardView) {
      leaderboardView.style.display = 'flex';
      if (typeof initLeaderboard === 'function') initLeaderboard();
    }
  } else if (view === 'contributors') {
    _navHighlight('contributors');
    _browseActive = false;
    _menuActive = false;
    if (contributorsView) {
      contributorsView.style.display = 'flex';
      if (typeof loadContributors === 'function') loadContributors();
    }
  } else if (view === 'feedback') {
    _navHighlight('feedback');
    _browseActive = false;
    _menuActive = false;
    if (feedbackView) {
      feedbackView.style.display = 'flex';
      if (typeof loadFeedback === 'function') loadFeedback();
    }
  } else {
    // Default: agent / play
    _navHighlight('agent');
    _browseActive = false;
    outerLayout.style.display = '';
    tabBar.style.display = 'flex';
    if (_menuActive) {
      menuView.classList.add('visible');
      sessionHost.style.display = 'none';
      sidebar.style.display = 'none';
    } else {
      menuView.classList.remove('visible');
      sidebar.style.display = '';
      updateEmptyAppState();
      if (sessions.size > 0) sessionHost.style.display = '';
      // Lazy-resume: if active session hasn't been loaded from server yet, resume now
      if (activeSessionId && !activeSessionId.startsWith('pending_')) {
        const _s = sessions.get(activeSessionId);
        if (_s && !_s.currentGrid) resumeSession(activeSessionId);
      }
    }
  }
}

// Route from URL hash on page load and back/forward navigation
function _routeFromHash() {
  const hash = location.hash.replace('#', '');
  const view = _VIEW_HASHES[hash];
  if (view) showAppView(view, true);
}
window.addEventListener('hashchange', _routeFromHash);

// ── Menu view ─────────────────────────────────────────────────────────────

function showMenuView() {
  _menuActive = true;
  _browseActive = false;
  // Save current session state
  if (activeSessionId && sessions.has(activeSessionId)) saveSessionToState();
  // Hide game layout, show menu (do NOT detach — just hide the host)
  const menuView = document.getElementById('menuView');
  const sessionHost = document.getElementById('sessionViewHost');
  const emptyApp = document.getElementById('emptyAppState');
  const browseView = document.getElementById('browseView');
  menuView.classList.add('visible');
  sessionHost.style.display = 'none';
  emptyApp.style.display = 'none';
  browseView.style.display = 'none';
  const sidebar = document.getElementById('gameSidebar');
  if (sidebar) sidebar.style.display = 'none';
  // Highlight Play nav link
  document.querySelectorAll('.top-nav .nav-link').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.top-nav .nav-link')[0]?.classList.add('active');
  renderMenuSessions();
  renderSessionTabs();
}

function renderMenuSessions() {
  const container = document.getElementById('menuSessionList');
  if (!container) return;
  const saved = getLocalSessions();
  if (!saved.length) {
    container.innerHTML = '<div class="menu-empty">No saved sessions yet. Start a new session to play!</div>';
    return;
  }
  container.innerHTML = '';
  for (const s of saved) {
    const row = document.createElement('div');
    row.className = 'menu-session-row';
    const gameName = s.game_id || s.id?.slice(0, 8) || '?';
    const steps = s.steps || 0;
    const result = s.result || 'NOT_FINISHED';
    const badgeClass = 'ms-badge-' + result.replace(/\s/g, '_');
    const date = s.created_at ? new Date(s.created_at * 1000).toLocaleDateString() : '';
    const liveTag = s.live_mode ? ' <span class="live-tag" style="font-size:9px;padding:1px 4px;">LIVE</span>' : '';
    row.innerHTML = `
      <span class="ms-game">${gameName}${liveTag}</span>
      <span class="ms-steps">${steps} steps</span>
      <span class="ms-badge ${badgeClass}">${result.replace(/_/g, ' ')}</span>
      <span class="ms-date">${date}</span>
      <button class="ms-resume" onclick="event.stopPropagation(); menuResume('${s.id}');">Resume</button>`;
    container.appendChild(row);
  }
}

function menuResume(sid) {
  _menuActive = false;
  document.getElementById('menuView').classList.remove('visible');
  showAppView('play');
  browseResume(sid);
}
