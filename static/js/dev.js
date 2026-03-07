const DEV_SECRET = 'arc-dev-2026';

function openDevPanel() {
  const panel = document.getElementById('devPanel');
  const btns  = document.getElementById('devLevelBtns');
  btns.innerHTML = '';
  const total = (currentState && currentState.win_levels) || 9;
  for (let i = 0; i < total; i++) {
    const b = document.createElement('button');
    b.className = 'btn';
    b.style.cssText = 'font-size:10px;padding:2px 10px;';
    b.textContent = 'L' + (i + 1);
    b.onclick = () => devJumpLevel(i);
    btns.appendChild(b);
  }
  panel.style.display = 'block';
}

async function devJumpLevel(levelIndex) {
  if (!sessionId) { alert('[DEV] No active session — start a game first'); return; }
  try {
    // Pyodide mode: game runs in browser worker
    if (_pyodideGameActive) {
      const prevGrid = currentState && currentState.grid;
      const state = await _sendGameWorkerMsg({type: 'jump_level', level: levelIndex});
      state.change_map = computeChangeMapJS(prevGrid, state.grid);
      state.session_id = sessionId;
      state.action_labels = {};
      (state.available_actions || []).forEach(a => {
        const names = {0:'RESET',1:'ACTION1',2:'ACTION2',3:'ACTION3',4:'ACTION4',5:'ACTION5',6:'ACTION6',7:'ACTION7'};
        state.action_labels[a] = names[a] || 'ACTION' + a;
      });
      updateUI(state);
      return;
    }
    // Server mode
    const resp = await fetch('/api/dev/jump-level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Dev-Secret': DEV_SECRET },
      body: JSON.stringify({ session_id: sessionId, level: levelIndex }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert('[DEV] ' + (data.error || 'Failed')); return; }
    updateUI(data);
  } catch (e) {
    alert('[DEV] Error: ' + e.message);
  }
}

// Shift+D to toggle dev panel
document.addEventListener('keydown', e => {
  if (e.shiftKey && e.key.toUpperCase() === 'D') openDevPanel();
});
