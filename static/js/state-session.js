// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: Game session state and multi-session management.
//   Extracted from state.js to focus on: game session variables (currentGrid,
//   moveHistory, undoStack), SessionState class for multi-session tabs,
//   session persistence, and session DOM view attachment/detachment.
// ═══════════════════════════════════════════════════════════════════════════
// SESSION STATE
// ═══════════════════════════════════════════════════════════════════════════

let canvas = document.getElementById('gameCanvas');
let ctx = canvas.getContext('2d');

// Live game state (global scope — synchronized with active SessionState)
let sessionId = null;
let currentUser = null;  // {id, email, display_name} or null
let currentGrid = null;
let previousGrid = null;
let currentChangeMap = null;
let currentState = {};
let stepCount = 0;
let llmCallCount = 0;  // counts agent/LLM calls (not game steps)
let moveHistory = [];
let autoPlaying = false;
let action6Mode = false;
let modelsData = [];  // {name, provider, capabilities, available}
let undoStack = [];   // local undo snapshots (grid + state for each step)
let humanLocked = true;  // human controls locked by default
let turnCounter = 0;     // monotonic turn counter for undo grouping
let apiMode = 'local';
const clientId = 'client_' + Math.random().toString(36).slice(2, 10);
let _liveScrubMode = true;     // true = following live, false = viewing historical
let _liveScrubViewIdx = -1;    // index into moveHistory being viewed
let _liveScrubLiveGrid = null; // stashed live grid when viewing historical

// Session totals (cost tracking, upload tracking)
let sessionTotalTokens = { input: 0, output: 0, cost: 0 };
let sessionStepsBuffer = [];
let sessionStartTime = null;
let syncStepCounter = 0;

// Compact context state
let _cachedCompactSummary = '';
let _compactSummaryAtCall = 0;
let _compactSummaryAtStep = 0;
let _lastCompactPrompt = '';

// ═══════════════════════════════════════════════════════════════════════════
// MULTI-SESSION: SessionState class + registry
// ═══════════════════════════════════════════════════════════════════════════

class SessionState {
  constructor(id) {
    this.sessionId = id;
    // Game state
    this.currentGrid = null;
    this.previousGrid = null;
    this.currentChangeMap = null;
    this.currentState = {};
    // Counters
    this.stepCount = 0;
    this.llmCallCount = 0;
    this.turnCounter = 0;
    // History
    this.moveHistory = [];
    this.undoStack = [];
    this.llmObservations = [];
    // Agent
    this.autoPlaying = false;
    this.action6Mode = false;
    // Compact context
    this._cachedCompactSummary = '';
    this._compactSummaryAtCall = 0;
    this._compactSummaryAtStep = 0;
    this._lastCompactPrompt = '';
    // Cost
    this.sessionTotalTokens = { input: 0, output: 0, cost: 0 };
    // Persistence
    this.sessionStepsBuffer = [];
    this.sessionStartTime = null;
    this.syncStepCounter = 0;
    // UI
    this.gameId = '';
    this.model = '';
    this.status = 'NOT_PLAYED';
    this.createdAt = Date.now() / 1000;
    // Countdown
    this.callDurations = [];
    this.countdownInterval = null;
    this.countdownTarget = null;
    // Tab label: once set by autoplay, never overwritten
    this.tabLabel = '';
    // LLM call in flight
    this.waitingForLLM = false;
    this.abortController = null;   // AbortController for in-flight fetch
    this.waitStartTime = null;     // performance.now() when LLM call started
    // Timeline
    this.timelineEvents = [];  // [{type, duration, turn, model?, callNum?}]
    this._rlmNamespace = {};  // Persistent RLM REPL variables (survives across turns within session)
    this._tsState = null;     // Three-System state (rules, observations, snapshots) — initialized on first use
    // Observability
    this._obsEvents = [];     // Obs screen events [{event, agent, t, elapsed_s, ...}]
    this._obsStartTime = null;
    this._obsSyncCursor = 0;
    // Detach/attach: per-session DOM + settings snapshot
    this._viewEl = null;       // Detached DOM element for this session
    this._settings = null;     // Snapshot of DOM settings for background reads
    // Original settings from when this session was created/resumed (for branch-on-change detection)
    this._originalSettings = null;  // { model, scaffolding_type }
    // Upload tracking
    this._lastUploadedStep = 0;  // last step successfully uploaded to server
  }
  get avgCallDuration() {
    if (!this.callDurations.length) return 5000; // default 5s
    return this.callDurations.reduce((a, b) => a + b, 0) / this.callDurations.length;
  }
}

const sessions = new Map();  // sessionId -> SessionState
let activeSessionId = null;
function getActiveSession() { return sessions.get(activeSessionId) || null; }

// ── Sync SessionState back to globals (only if ss is the active session) ──
function syncSessionToGlobals(ss) {
  if (!ss || activeSessionId !== ss.sessionId) return;
  sessionId = ss.sessionId;
  currentGrid = ss.currentGrid;
  previousGrid = ss.previousGrid;
  currentChangeMap = ss.currentChangeMap;
  currentState = ss.currentState;
  stepCount = ss.stepCount;
  llmCallCount = ss.llmCallCount;
  turnCounter = ss.turnCounter;
  moveHistory = ss.moveHistory;
  undoStack = ss.undoStack;
  llmObservations = ss.llmObservations;
  autoPlaying = ss.autoPlaying;
  sessionTotalTokens = ss.sessionTotalTokens;
  sessionStepsBuffer = ss.sessionStepsBuffer;
  syncStepCounter = ss.syncStepCounter;
  _cachedCompactSummary = ss._cachedCompactSummary;
  _compactSummaryAtCall = ss._compactSummaryAtCall;
  _compactSummaryAtStep = ss._compactSummaryAtStep;
  _lastCompactPrompt = ss._lastCompactPrompt;
}

// ── Bridge: save globals → SessionState ──────────────────────────────────
function saveSessionToState() {
  const s = getActiveSession();
  if (!s) return;
  s.sessionId = sessionId;
  s.currentGrid = currentGrid;
  s.previousGrid = previousGrid;
  s.currentChangeMap = currentChangeMap;
  s.currentState = currentState;
  s.stepCount = stepCount;
  s.llmCallCount = llmCallCount;
  s.turnCounter = turnCounter;
  s.moveHistory = moveHistory;
  s.undoStack = undoStack;
  s.llmObservations = llmObservations;
  s.autoPlaying = autoPlaying;
  s.action6Mode = action6Mode;
  s.sessionTotalTokens = sessionTotalTokens;
  s.sessionStepsBuffer = sessionStepsBuffer;
  s.sessionStartTime = sessionStartTime;
  s.syncStepCounter = syncStepCounter;
  s._cachedCompactSummary = _cachedCompactSummary;
  s._compactSummaryAtCall = _compactSummaryAtCall;
  s._compactSummaryAtStep = _compactSummaryAtStep;
  s._lastCompactPrompt = _lastCompactPrompt;
  // Snapshot DOM settings so background sessions can read them when detached
  try {
    s._settings = {
      model: getSelectedModel(),
      input: getInputSettings(),
      compact: getCompactSettings(),
      tools_mode: getToolsMode(),
      planning_mode: getPlanningMode(),
      thinking_level: getThinkingLevel(),
      scaffolding: getScaffoldingSettings(),
      max_tokens: getMaxTokens(),
      scaffolding_type: activeScaffoldingType,
    };
  } catch (e) { console.warn('[saveSessionToState] settings snapshot failed:', e); }
  // Update metadata
  s.gameId = gameShortName(currentState.game_id) || s.gameId;
  s.model = getSelectedModel() || s.model;
  s.status = currentState.state || s.status;
}

// ── Bridge: restore SessionState → globals ───────────────────────────────
function restoreSessionFromState(s) {
  if (!s) return;
  sessionId = s.sessionId;
  currentGrid = s.currentGrid;
  previousGrid = s.previousGrid;
  currentChangeMap = s.currentChangeMap;
  currentState = s.currentState;
  stepCount = s.stepCount;
  llmCallCount = s.llmCallCount;
  turnCounter = s.turnCounter;
  moveHistory = s.moveHistory;
  undoStack = s.undoStack;
  llmObservations = s.llmObservations;
  autoPlaying = s.autoPlaying;
  action6Mode = s.action6Mode;
  sessionTotalTokens = s.sessionTotalTokens;
  sessionStepsBuffer = s.sessionStepsBuffer;
  sessionStartTime = s.sessionStartTime;
  syncStepCounter = s.syncStepCounter;
  _cachedCompactSummary = s._cachedCompactSummary;
  _compactSummaryAtCall = s._compactSummaryAtCall;
  _compactSummaryAtStep = s._compactSummaryAtStep;
  _lastCompactPrompt = s._lastCompactPrompt;

  // Rebuild reasoning from step buffer (single source of truth — never cache DOM HTML)
  const rc = document.getElementById('reasoningContent');
  if (rc) {
    if (s.sessionStepsBuffer && s.sessionStepsBuffer.length > 0) {
      renderRestoredReasoning(s.sessionStepsBuffer, null, null);
    } else {
      rc.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No reasoning yet.</div>';
    }
  }

  // If session has an LLM call in flight, show waiting indicator with elapsed time
  if (s.waitingForLLM && s.waitStartTime) {
    const elapsed = ((performance.now() - s.waitStartTime) / 1000).toFixed(1);
    const waitEl = document.createElement('div');
    waitEl.className = 'reasoning-entry llm-waiting';
    waitEl.innerHTML = `<div class="step-label" style="color:var(--dim);"><span class="spinner" style="margin-right:6px;"></span>Waiting for model response... <span class="wait-timer">${elapsed}s</span></div>`;
    if (rc.querySelector('.empty-state')) rc.innerHTML = '';
    rc.appendChild(waitEl);
    scrollReasoningToBottom();
    // Live-update the timer until the LLM call completes
    const _restoreWaitStart = s.waitStartTime;
    const _restoreWaitInterval = setInterval(() => {
      if (!s.waitingForLLM || !waitEl.parentNode) { clearInterval(_restoreWaitInterval); waitEl.remove(); return; }
      const el = waitEl.querySelector('.wait-timer');
      if (el) el.textContent = ((performance.now() - _restoreWaitStart) / 1000).toFixed(1) + 's';
    }, 100);
    document.getElementById('llmSpinner').style.display = 'inline';
    document.getElementById('topSpinner').style.display = 'inline';
  } else {
    document.getElementById('llmSpinner').style.display = 'none';
    document.getElementById('topSpinner').style.display = 'none';
  }

  // Re-render grid
  if (currentGrid) {
    canvas.style.display = 'block';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('controls').style.display = 'flex';
    document.getElementById('transportBar').style.display = 'block';
    renderGrid(currentGrid);
  } else {
    canvas.style.display = 'none';
    document.getElementById('emptyState').style.display = '';
    document.getElementById('controls').style.display = 'none';
    document.getElementById('transportBar').style.display = 'none';
  }

  // Update UI elements
  document.getElementById('gameTitle').textContent = gameShortName(currentState.game_id) || 'No game selected';
  const statusEl = document.getElementById('gameStatus');
  statusEl.textContent = currentState.state || '—';
  statusEl.className = 'status status-' + (currentState.state || 'NOT_PLAYED');
  document.getElementById('levelInfo').textContent = currentState.levels_completed !== undefined
    ? `Level ${currentState.levels_completed}/${currentState.win_levels || '?'}` : '';
  document.getElementById('stepCounter').textContent = stepCount ? `Step ${stepCount}` : '';
  updateUploadBadge();
  updateUndoBtn();
  updateAutoBtn();
  updatePanelBlur();
  updateGameListLock();

  // Re-render obs swimlane if obs mode is active
  if (isObsModeActive()) {
    updateObsStatus(s);
  }

  // Highlight the matching game card in the sidebar
  const restoredGameId = currentState.game_id || '';
  document.querySelectorAll('.game-card').forEach(c => {
    c.classList.toggle('active', restoredGameId && c.dataset.gameId === restoredGameId);
  });

  if (action6Mode) canvas.style.cursor = 'crosshair';
  else canvas.style.cursor = 'default';
}

// ── Register a SessionState in the registry ──────────────────────────────
function registerSession(id, state) {
  sessions.set(id, state);
  activeSessionId = id;
  renderSessionTabs();
  saveSessionIndex();
}

// ═══════════════════════════════════════════════════════════════════════════
// DETACH / ATTACH ENGINE — per-session DOM isolation
// ═══════════════════════════════════════════════════════════════════════════

let _sessionTemplate = null;  // Captured after initApp populates DOM

function captureSessionTemplate() {
  const ml = document.getElementById('mainLayout');
  if (!ml) return;
  _sessionTemplate = ml.cloneNode(true);
  _sessionTemplate.removeAttribute('id');
  // Ensure cloned template has loading overlay hidden (Pyodide may be loading when captured)
  const overlay = _sessionTemplate.querySelector('#pyodideGameLoading');
  if (overlay) overlay.style.display = 'none';
}

function createSessionView() {
  const view = _sessionTemplate.cloneNode(true);
  view.id = 'mainLayout';
  return view;
}

function detachSessionView(sid) {
  const host = document.getElementById('sessionViewHost');
  const currentView = host.querySelector('#mainLayout');
  if (currentView && sessions.has(sid)) {
    sessions.get(sid)._viewEl = currentView;
    host.removeChild(currentView);
  }
}

function attachSessionView(sid) {
  const host = document.getElementById('sessionViewHost');
  const ss = sessions.get(sid);
  if (!ss) return;
  // Remove any existing #mainLayout (static or stale) before attaching
  const existing = host.querySelector('#mainLayout');
  if (existing) existing.remove();
  if (!ss._viewEl) ss._viewEl = createSessionView();
  ss._viewEl.id = 'mainLayout';
  host.appendChild(ss._viewEl);
  // Re-bind dynamic event listeners (cloned DOM loses addEventListener bindings)
  attachSettingsListeners();
  // Refresh canvas reference (each session has its own canvas element)
  canvas = document.getElementById('gameCanvas');
  ctx = canvas.getContext('2d');
}

// Compact context: accumulate LLM observations across the session
let llmObservations = []; // [{step, observation, reasoning, action, analysis}]
