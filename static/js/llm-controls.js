// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-12
// PURPOSE: LLM control button state management (Phase 12 extraction)
// Extracted from llm.js to isolate UI state management
// SRP: Undo/autoplay button updates, session testing

function updateUndoBtn() {
  const btn = document.getElementById('undoBtn');
  btn.disabled = undoStack.length === 0;
}

function updateAutoBtn() {
  const btn = document.getElementById('autoPlayBtn');
  if (autoPlaying) {
    btn.innerHTML = '&#9208; Pause';
    btn.classList.add('btn-pause');
  } else {
    btn.innerHTML = '&#187; Agent Autoplay';
    btn.classList.remove('btn-pause');
  }
}

async function testModel() {
  const model = getSelectedModel();
  if (!model) return;
  const btn = document.getElementById('testBtn');
  const resultEl = document.getElementById('testResult');
  btn.disabled = true;
  btn.textContent = '⏳ Testing...';
  resultEl.style.display = 'block';
  resultEl.style.background = '#333';
  resultEl.style.color = '#aaa';
  resultEl.textContent = `Testing ${model}...`;

  try {
    const modelInfo = getModelInfo(model);
    const provider = modelInfo?.provider;
    const testPrompt = 'Reply with exactly: {"action": 1, "observation": "test"}';
    const t0 = performance.now();
    let result;
    result = await callLLM([{role: 'user', content: testPrompt}], model);
    const latency = Math.round(performance.now() - t0);
    resultEl.style.background = '#1a3a1a';
    resultEl.style.color = '#6f6';
    resultEl.innerHTML = `<b>${model}</b> ✓ ${latency}ms`;
  } catch (e) {
    resultEl.style.background = '#3a1a1a';
    resultEl.style.color = '#f66';
    resultEl.textContent = `Error: ${e.message}`;
  }
  btn.disabled = false;
  btn.textContent = '🔗 Test';
}
