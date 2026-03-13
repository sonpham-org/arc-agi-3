// ═══════════════════════════════════════════════════════════════════════════
// PYODIDE — Client-side Python sandbox (Web Worker)
// ═══════════════════════════════════════════════════════════════════════════

let _pyodideWorker = null;
let _pyodideReady = false;
let _pyodideLoading = false;
let _pyodideCallId = 0;
const _pyodidePending = new Map(); // callId → {resolve, reject}

function _initPyodideWorker() {
  if (_pyodideWorker) return;
  _pyodideLoading = true;
  const workerSrc = `
    importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.4/full/pyodide.js');
    let pyodide = null;
    const _namespaces = {};  // session_id -> namespace dict

    function _getNamespace(sessionId) {
      if (!sessionId) sessionId = '__default__';
      if (!_namespaces[sessionId]) {
        _namespaces[sessionId] = pyodide.globals.get('dict')();
        pyodide.runPython('import numpy as np; import collections; from collections import Counter, defaultdict; import itertools; import math',
          {globals: _namespaces[sessionId]});
      }
      return _namespaces[sessionId];
    }

    self.onmessage = async (e) => {
      const {type, id, code, grid, prev_grid, session_id} = e.data;
      if (type === 'init') {
        try {
          pyodide = await loadPyodide();
          await pyodide.loadPackage('numpy');
          self.postMessage({type: 'ready', id});
        } catch (err) {
          self.postMessage({type: 'error', id, error: err.message});
        }
      } else if (type === 'clear_session') {
        if (session_id && _namespaces[session_id]) {
          delete _namespaces[session_id];
        }
        self.postMessage({type: 'result', id, output: 'cleared'});
      } else if (type === 'execute') {
        const ns = _getNamespace(session_id);
        try {
          // Set grid/prev_grid in namespace
          pyodide.runPython('import numpy as np', {globals: ns});
          ns.set('grid', pyodide.runPython('np.array(' + JSON.stringify(grid || [[]]) + ')', {globals: ns}));
          if (prev_grid) {
            ns.set('prev_grid', pyodide.runPython('np.array(' + JSON.stringify(prev_grid) + ')', {globals: ns}));
          } else {
            ns.set('prev_grid', pyodide.globals.get('None'));
          }

          // Capture stdout
          pyodide.runPython(\`
import io as _io, sys as _sys
_stdout_buf = _io.StringIO()
_old_stdout = _sys.stdout
_sys.stdout = _stdout_buf
\`, {globals: ns});

          pyodide.runPython(code, {globals: ns});

          const output = pyodide.runPython(\`
_sys.stdout = _old_stdout
_out = _stdout_buf.getvalue()
_stdout_buf.close()
_out
\`, {globals: ns});

          let result = output || '(no output)';
          if (result.length > 4000) result = result.substring(0, 4000) + '\\n... [truncated]';
          self.postMessage({type: 'result', id, output: result});
        } catch (err) {
          // Restore stdout on error
          try { pyodide.runPython('_sys.stdout = _old_stdout', {globals: ns}); } catch(_){}
          self.postMessage({type: 'result', id, output: err.message});
        }
      }
    };
  `;
  const blob = new Blob([workerSrc], {type: 'application/javascript'});
  _pyodideWorker = new Worker(URL.createObjectURL(blob));
  _pyodideWorker.onmessage = (e) => {
    const {type, id, output, error} = e.data;
    if (type === 'ready') {
      _pyodideReady = true;
      _pyodideLoading = false;
      console.log('Pyodide ready');
      const cb = _pyodidePending.get(id);
      if (cb) { cb.resolve('ready'); _pyodidePending.delete(id); }
    } else if (type === 'error') {
      _pyodideLoading = false;
      console.error('Pyodide init failed:', error);
      const cb = _pyodidePending.get(id);
      if (cb) { cb.reject(new Error(error)); _pyodidePending.delete(id); }
    } else if (type === 'result') {
      const cb = _pyodidePending.get(id);
      if (cb) { cb.resolve(output); _pyodidePending.delete(id); }
    }
  };
  // Start init
  const initId = ++_pyodideCallId;
  return new Promise((resolve, reject) => {
    _pyodidePending.set(initId, {resolve, reject});
    _pyodideWorker.postMessage({type: 'init', id: initId});
  });
}

async function ensurePyodide() {
  if (_pyodideReady) return;
  if (_pyodideLoading) {
    // Wait for existing init
    return new Promise((resolve) => {
      const check = setInterval(() => {
        if (_pyodideReady) { clearInterval(check); resolve(); }
      }, 200);
    });
  }
  await _initPyodideWorker();
}

async function runPyodide(code, grid, prev_grid, sessionId) {
  if (!_pyodideReady) throw new Error('Pyodide not loaded');
  const id = ++_pyodideCallId;
  return new Promise((resolve, reject) => {
    _pyodidePending.set(id, {resolve, reject});
    _pyodideWorker.postMessage({type: 'execute', id, code, grid, prev_grid, session_id: sessionId || activeSessionId});
    // Timeout after 10s
    setTimeout(() => {
      if (_pyodidePending.has(id)) {
        _pyodidePending.delete(id);
        resolve('[TIMEOUT] Code execution exceeded 10 seconds.');
      }
    }, 10000);
  });
}

// ── Tools mode confirmation (online = Pyodide, local = server sandbox) ───
// Moved to attachSettingsListeners() — called after renderScaffoldingSettings()

// Extract ```python code blocks from LLM response text
function extractPythonBlocks(text) {
  const blocks = [];
  const re = /```python\s*\n([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    blocks.push(m[1].trim());
  }
  return blocks;
}

// Run tool calls from LLM response, return tool_calls array
async function executeToolBlocks(text, grid, prev_grid, sessionId) {
  const blocks = extractPythonBlocks(text);
  if (!blocks.length) return [];
  // Pyodide only
  if (!_pyodideReady) return [];
  const toolCalls = [];
  for (const code of blocks) {
    const output = await runPyodide(code, grid, prev_grid, sessionId);
    toolCalls.push({name: 'run_python', arguments: {code}, output});
  }
  return toolCalls;
}

// ═══════════════════════════════════════════════════════════════════════════
// PYODIDE GAME ENGINE — Run arcengine in-browser via Web Worker
// ═══════════════════════════════════════════════════════════════════════════

let _pyodideGameWorker = null;
let _pyodideGameReady = false;
let _pyodideGameLoading = false;
let _pyodideGameActive = false;  // true when current session uses Pyodide
let _pyodideGameSessionId = null;  // which session owns the Pyodide game worker
let _pyodideGameCallId = 0;
const _pyodideGamePending = new Map();
let _pyodideGameProgress = { stage: '', percent: 0 };

function _initPyodideGameWorker() {
  if (_pyodideGameWorker) return Promise.resolve();
  _pyodideGameLoading = true;
  const workerSrc = `
    importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.4/full/pyodide.js');
    let pyodide = null;
    let _game_instance = null;
    let _undo_stack = [];
    let _game_class_name = '';

    function postProgress(stage, percent) {
      self.postMessage({type: 'progress', stage, percent});
    }

    self.onmessage = async (e) => {
      const msg = e.data;

      if (msg.type === 'init') {
        try {
          console.log('[PyodideWorker] Starting init...');
          postProgress('Loading Pyodide runtime...', 5);
          pyodide = await loadPyodide();
          console.log('[PyodideWorker] Pyodide loaded, loading packages...');
          postProgress('Loading packages...', 30);
          await pyodide.loadPackage(['numpy', 'pydantic']);
          console.log('[PyodideWorker] numpy+pydantic loaded, verifying...');
          await pyodide.runPythonAsync('import pydantic; print("pydantic", pydantic.__version__)');
          console.log('[PyodideWorker] pydantic verified, installing arcengine...');
          postProgress('Installing arcengine...', 60);
          // Bypass micropip entirely — it can't handle pydantic-core (C ext).
          // Fetch wheel from PyPI, extract to site-packages manually.
          await pyodide.runPythonAsync(\`
import json, zipfile, io, importlib, site
from pyodide.http import pyfetch

resp = await pyfetch("https://pypi.org/pypi/arcengine/json")
meta = json.loads(await resp.string())
whl_url = next(u["url"] for u in meta["urls"] if u["filename"].endswith("py3-none-any.whl"))
print(f"Downloading wheel: {whl_url}")

whl_resp = await pyfetch(whl_url)
whl_bytes = bytes(await whl_resp.bytes())

sp = site.getsitepackages()[0]
print(f"Extracting to: {sp}")
with zipfile.ZipFile(io.BytesIO(whl_bytes)) as zf:
    zf.extractall(sp)
    print(f"Extracted files: {zf.namelist()[:10]}...")
importlib.invalidate_caches()

# Verify arcengine imports
from arcengine import ARCBaseGame
print(f"arcengine loaded successfully: {ARCBaseGame}")
          \`);
          console.log('[PyodideWorker] arcengine installed and verified!');
          postProgress('Ready', 100);
          self.postMessage({type: 'ready', id: msg.id});
        } catch (err) {
          console.error('[PyodideWorker] Init failed:', err);
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }

      if (msg.type === 'load_game') {
        try {
          const {source, class_name, game_id, id} = msg;
          _game_class_name = class_name;
          _undo_stack = [];

          // exec the game source in a namespace that has arcengine imports
          pyodide.runPython(\`
import numpy as np
import arcengine
from arcengine import *
import copy
\`);
          // Set source via globals to avoid escaping issues
          pyodide.globals.set('_source_code', source);
          pyodide.globals.set('_class_name', class_name);
          pyodide.runPython(\`
# Provide __file__ so game code using Path(__file__) works in exec()
__file__ = '/virtual/game.py'
exec(_source_code)
_game_instance = eval(_class_name + "()")
_undo_stack = []
_reset_action = ActionInput(id=GameAction.RESET)
_frame_data = _game_instance.perform_action(_reset_action, raw=True)
\`);

          // Extract state
          const stateJson = pyodide.runPython(\`
import json
_frame = _frame_data.frame[-1].tolist() if _frame_data.frame else []
_avail = list(_frame_data.available_actions)
json.dumps({
    "grid": _frame,
    "state": _frame_data.state.value if hasattr(_frame_data.state, "value") else str(_frame_data.state),
    "levels_completed": _frame_data.levels_completed,
    "win_levels": _frame_data.win_levels,
    "available_actions": _avail,
    "game_id": _frame_data.game_id,
})
\`);
          self.postMessage({type: 'game_loaded', id, state: JSON.parse(stateJson)});
        } catch (err) {
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }

      if (msg.type === 'step') {
        try {
          const {action, data, id} = msg;
          // Save undo snapshot before stepping (game instance + frame data)
          pyodide.runPython('_undo_stack.append((copy.deepcopy(_game_instance), copy.deepcopy(_frame_data)))');

          // Perform the action
          pyodide.globals.set('_action_id', action);
          pyodide.globals.set('_action_data', data ? pyodide.toPy(data) : pyodide.globals.get('None'));
          pyodide.runPython(\`
_action = GameAction.from_id(int(_action_id))
_data = dict(_action_data) if _action_data is not None and _action_data != 'None' else None
_action_input = ActionInput(id=_action, data=_data or {})
_frame_data = _game_instance.perform_action(_action_input, raw=True)
\`);

          const stateJson = pyodide.runPython(\`
import json
_all_frames = [f.tolist() for f in _frame_data.frame] if _frame_data.frame else []
# Thin to at most 120 frames so postMessage payload stays small
_step = max(1, len(_all_frames) // 120)
_frames_out = _all_frames[::_step]
if _all_frames and _frames_out[-1] is not _all_frames[-1]:
    _frames_out.append(_all_frames[-1])
_frame = _frames_out[-1] if _frames_out else []
_avail = list(_frame_data.available_actions)
json.dumps({
    "grid": _frame,
    "frames": _frames_out,
    "state": _frame_data.state.value if hasattr(_frame_data.state, "value") else str(_frame_data.state),
    "levels_completed": _frame_data.levels_completed,
    "win_levels": _frame_data.win_levels,
    "available_actions": _avail,
    "game_id": _frame_data.game_id,
    "undo_depth": len(_undo_stack),
})
\`);
          self.postMessage({type: 'step_result', id, state: JSON.parse(stateJson)});
        } catch (err) {
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }

      if (msg.type === 'reset') {
        try {
          pyodide.runPython(\`
_reset_action = ActionInput(id=GameAction.RESET)
_frame_data = _game_instance.perform_action(_reset_action, raw=True)
_undo_stack = []
\`);
          const stateJson = pyodide.runPython(\`
import json
_frame = _frame_data.frame[-1].tolist() if _frame_data.frame else []
_avail = list(_frame_data.available_actions)
json.dumps({
    "grid": _frame,
    "state": _frame_data.state.value if hasattr(_frame_data.state, "value") else str(_frame_data.state),
    "levels_completed": _frame_data.levels_completed,
    "win_levels": _frame_data.win_levels,
    "available_actions": _avail,
    "game_id": _frame_data.game_id,
    "undo_depth": 0,
})
\`);
          self.postMessage({type: 'reset_result', id: msg.id, state: JSON.parse(stateJson)});
        } catch (err) {
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }

      if (msg.type === 'undo') {
        try {
          const {count, id} = msg;
          pyodide.globals.set('_undo_count', count);
          pyodide.runPython(\`
if len(_undo_stack) >= _undo_count:
    for _ in range(_undo_count - 1):
        _undo_stack.pop()
    _game_instance, _frame_data = _undo_stack.pop()
elif _undo_stack:
    _game_instance, _frame_data = _undo_stack[0]
    _undo_stack = []
\`);
          const stateJson = pyodide.runPython(\`
import json
_frame = _frame_data.frame[-1].tolist() if _frame_data.frame else []
_avail = list(_frame_data.available_actions)
json.dumps({
    "grid": _frame,
    "state": _frame_data.state.value if hasattr(_frame_data.state, "value") else str(_frame_data.state),
    "levels_completed": _frame_data.levels_completed,
    "win_levels": _frame_data.win_levels,
    "available_actions": _avail,
    "game_id": _frame_data.game_id,
    "undo_depth": len(_undo_stack),
})
\`);
          self.postMessage({type: 'undo_result', id, state: JSON.parse(stateJson)});
        } catch (err) {
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }

      if (msg.type === 'jump_level') {
        try {
          const {level, id} = msg;
          pyodide.globals.set('_target_level', level);
          pyodide.runPython(\`
from arcengine import GameState
_game_instance._levels[_target_level] = _game_instance._clean_levels[_target_level].clone()
_game_instance.set_level(_target_level)
_game_instance._score = _target_level
_game_instance._state = GameState.NOT_FINISHED
_frame = _game_instance.camera.render(_game_instance.current_level.get_sprites())
_undo_stack = []
\`);
          const stateJson = pyodide.runPython(\`
import json
_avail = list(_game_instance._available_actions)
json.dumps({
    "grid": _frame.tolist(),
    "state": _game_instance._state.value if hasattr(_game_instance._state, "value") else str(_game_instance._state),
    "levels_completed": _game_instance._score,
    "win_levels": _game_instance._win_score,
    "available_actions": _avail,
    "game_id": _game_instance._game_id,
    "undo_depth": 0,
})
\`);
          self.postMessage({type: 'jump_level_result', id, state: JSON.parse(stateJson)});
        } catch (err) {
          self.postMessage({type: 'error', id: msg.id, error: err.message});
        }
        return;
      }
    };
  `;
  const blob = new Blob([workerSrc], {type: 'application/javascript'});
  _pyodideGameWorker = new Worker(URL.createObjectURL(blob));
  _pyodideGameWorker.onmessage = (e) => {
    const {type, id, state, error, stage, percent} = e.data;
    if (type === 'progress') {
      _pyodideGameProgress = {stage, percent};
      _updatePyodideGameLoadingUI();
    } else if (type === 'ready') {
      _pyodideGameReady = true;
      _pyodideGameLoading = false;
      console.log('[PyodideGame] Engine ready');
      _updatePyodideGameLoadingUI();
      const cb = _pyodideGamePending.get(id);
      if (cb) { cb.resolve(); _pyodideGamePending.delete(id); }
    } else if (type === 'error') {
      console.error('[PyodideGame] Error:', error);
      const cb = _pyodideGamePending.get(id);
      if (cb) { cb.reject(new Error(error)); _pyodideGamePending.delete(id); }
    } else if (type === 'game_loaded' || type === 'step_result' || type === 'reset_result' || type === 'undo_result' || type === 'jump_level_result') {
      const cb = _pyodideGamePending.get(id);
      if (cb) { cb.resolve(state); _pyodideGamePending.delete(id); }
    }
  };
  const initId = ++_pyodideGameCallId;
  return new Promise((resolve, reject) => {
    _pyodideGamePending.set(initId, {resolve, reject});
    _pyodideGameWorker.postMessage({type: 'init', id: initId});
  });
}

function _sendGameWorkerMsg(msg) {
  const id = ++_pyodideGameCallId;
  msg.id = id;
  return new Promise((resolve, reject) => {
    _pyodideGamePending.set(id, {resolve, reject});
    _pyodideGameWorker.postMessage(msg);
    setTimeout(() => {
      if (_pyodideGamePending.has(id)) {
        _pyodideGamePending.delete(id);
        reject(new Error('[PyodideGame] Timeout'));
      }
    }, 30000);
  });
}

async function ensurePyodideGame() {
  if (_pyodideGameReady) return;
  if (_pyodideGameLoading) {
    return new Promise((resolve) => {
      const check = setInterval(() => {
        if (_pyodideGameReady) { clearInterval(check); resolve(); }
      }, 200);
    });
  }
  await _initPyodideGameWorker();
}

// ── Loading UX ──────────────────────────────────────────────────────────

function _updatePyodideGameLoadingUI() {
  const overlay = document.getElementById('pyodideGameLoading');
  if (!overlay) return;
  if (_pyodideGameReady) {
    overlay.style.display = 'none';
    // If a game start was waiting, it'll proceed via the promise resolution
    return;
  }
  if (!_pyodideGameLoading) return;
  const pct = _pyodideGameProgress.percent || 0;
  const stage = _pyodideGameProgress.stage || 'Initializing...';
  const barWidth = Math.min(100, Math.max(0, pct));
  overlay.innerHTML = `
    <div style="text-align:center;padding:20px;">
      <div style="font-size:13px;font-weight:600;margin-bottom:12px;color:var(--text);">Loading game engine (one-time)</div>
      <div style="background:var(--surface-alt,#333);border-radius:4px;height:20px;width:240px;margin:0 auto 8px;overflow:hidden;border:1px solid var(--border);">
        <div style="background:var(--green,#4FCC30);height:100%;width:${barWidth}%;transition:width 0.3s;"></div>
      </div>
      <div style="font-size:12px;color:var(--text-dim);">${stage} &nbsp; ${Math.round(pct)}%</div>
    </div>
  `;
  overlay.style.display = '';
}

// ── JS wrapper functions (produce same response shape as server) ─────────

function computeChangeMapJS(prevGrid, currGrid) {
  if (!prevGrid || !currGrid || !prevGrid.length || !currGrid.length) {
    return {changes: [], change_count: 0, change_map_text: ''};
  }
  const h = Math.min(prevGrid.length, currGrid.length);
  const w = h > 0 ? Math.min(prevGrid[0].length, currGrid[0].length) : 0;
  const changes = [];
  const rows = [];
  for (let y = 0; y < h; y++) {
    let rowChars = '';
    for (let x = 0; x < w; x++) {
      if (prevGrid[y][x] !== currGrid[y][x]) {
        changes.push({x, y, from: prevGrid[y][x], to: currGrid[y][x]});
        rowChars += 'X';
      } else {
        rowChars += '.';
      }
    }
    if (rowChars.includes('X')) {
      // Compress: runs of same char
      let compressed = '';
      let i = 0;
      while (i < rowChars.length) {
        const ch = rowChars[i];
        let count = 1;
        while (i + count < rowChars.length && rowChars[i + count] === ch) count++;
        compressed += (compressed ? ' ' : '') + (count > 1 ? `${ch}x${count}` : ch);
        i += count;
      }
      rows.push(`Row ${y}: ${compressed}`);
    }
  }
  return {
    changes,
    change_count: changes.length,
    change_map_text: rows.length ? rows.join('\n') : '(no changes)',
  };
}

async function pyodideStartGame(gameId) {
  // Fetch game source from server
  const sourceData = await fetchJSON(`/api/games/${gameId}/source`);
  if (sourceData.error) throw new Error(sourceData.error);

  // Ensure Pyodide game engine is loaded (show progress if needed)
  const loadingOverlay = document.getElementById('pyodideGameLoading');
  if (!_pyodideGameReady && loadingOverlay) {
    loadingOverlay.style.display = '';
    _updatePyodideGameLoadingUI();
  }
  await ensurePyodideGame();
  // Hide loading overlay (current DOM's copy — may differ from the one shown above)
  const loadingDone = document.getElementById('pyodideGameLoading');
  if (loadingDone) loadingDone.style.display = 'none';

  // Load game in worker
  const state = await _sendGameWorkerMsg({
    type: 'load_game',
    source: sourceData.source,
    class_name: sourceData.class_name,
    game_id: sourceData.game_id,
  });

  // Generate a client-side session ID
  const sessionId = 'pyodide-' + crypto.randomUUID();
  state.session_id = sessionId;
  state.change_map = {changes: [], change_count: 0, change_map_text: '(initial)'};
  state.action_labels = {};
  (state.available_actions || []).forEach(a => {
    const names = {0:'RESET',1:'ACTION1',2:'ACTION2',3:'ACTION3',4:'ACTION4',5:'ACTION5',6:'ACTION6',7:'ACTION7'};
    state.action_labels[a] = names[a] || `ACTION${a}`;
  });
  return state;
}

async function pyodideStep(actionId, actionData) {
  const state = await _sendGameWorkerMsg({
    type: 'step',
    action: actionId,
    data: (actionData && Object.keys(actionData).length > 0) ? actionData : null,
  });
  // Animate intermediate physics frames before returning final state
  // Skip when in human mode — human-game.js animates on its own canvas
  if (state.frames && state.frames.length > 1 && !_humanRecording) {
    const fps = (currentState && currentState.default_fps) || 20;
    const delay = Math.max(50, Math.round(1000 / fps));
    for (let i = 0; i < state.frames.length - 1; i++) {
      renderGrid(state.frames[i]);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  state.action_labels = {};
  (state.available_actions || []).forEach(a => {
    const names = {0:'RESET',1:'ACTION1',2:'ACTION2',3:'ACTION3',4:'ACTION4',5:'ACTION5',6:'ACTION6',7:'ACTION7'};
    state.action_labels[a] = names[a] || `ACTION${a}`;
  });
  return state;
}

async function pyodideReset() {
  const state = await _sendGameWorkerMsg({type: 'reset'});
  state.change_map = {changes: [], change_count: 0, change_map_text: '(reset)'};
  state.action_labels = {};
  (state.available_actions || []).forEach(a => {
    const names = {0:'RESET',1:'ACTION1',2:'ACTION2',3:'ACTION3',4:'ACTION4',5:'ACTION5',6:'ACTION6',7:'ACTION7'};
    state.action_labels[a] = names[a] || `ACTION${a}`;
  });
  return state;
}

async function pyodideUndo(count) {
  const state = await _sendGameWorkerMsg({type: 'undo', count});
  state.change_map = {changes: [], change_count: 0, change_map_text: '(undo)'};
  state.action_labels = {};
  (state.available_actions || []).forEach(a => {
    const names = {0:'RESET',1:'ACTION1',2:'ACTION2',3:'ACTION3',4:'ACTION4',5:'ACTION5',6:'ACTION6',7:'ACTION7'};
    state.action_labels[a] = names[a] || `ACTION${a}`;
  });
  return state;
}

// ── Dispatch layer ──────────────────────────────────────────────────────

async function gameStep(sessionId, actionId, actionData, extras, callerState) {
  // Use Pyodide only if this session owns the game worker
  if (_pyodideGameActive && _pyodideGameSessionId === (callerState?._ownerSessionId || activeSessionId)) {
    try {
      const prevGrid = (callerState?.grid) || currentState.grid;
      const state = await pyodideStep(actionId, actionData);
      state.change_map = computeChangeMapJS(prevGrid, state.grid);
      state.session_id = sessionId;
      return state;
    } catch (err) {
      console.error('[gameStep] Pyodide step failed:', err.message);
      return { error: err.message };
    }
  }
  // Fallback to server endpoint for non-owner sessions or server mode
  return fetchJSON('/api/step', {session_id: sessionId, action: actionId, data: actionData || {}, ...extras});
}

// ── Eager init on page load ─────────────────────────────────────────────
if (typeof FEATURES !== 'undefined' && FEATURES.pyodide_game) {
  document.addEventListener('DOMContentLoaded', () => {
    // Start loading Pyodide game engine eagerly (don't block on it)
    _initPyodideGameWorker().catch(err => {
      console.warn('[PyodideGame] Eager init failed:', err.message);
    });
  });
}

