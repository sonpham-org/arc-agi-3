// ui-tabs.js — Tab and panel switching
// Extracted from ui.js (Phase 24)
// Functions that switch between tabs (agent/human/obs), hide/show panels, manage the sidebar state.

function toggleSection(id) {
  document.getElementById(id).classList.toggle('open');
}

function toggleCompactSettings() {
  const on = document.getElementById('compactContext')?.checked;
  const body = document.getElementById('compactSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function toggleInterruptSettings() {
  const on = document.getElementById('interruptPlan')?.checked;
  const body = document.getElementById('interruptSettingsBody');
  if (body) { body.style.opacity = on ? '1' : '0.4'; body.style.pointerEvents = on ? 'auto' : 'none'; }
  updatePipelineOpacity();
}

function switchTopTab(tab) {
  // History tab removed — this is now a no-op kept for compat with resume/branch code
  if (tab === 'agent') switchSubTab('settings');
}

function switchSubTab(tab) {
  // Reasoning/timeline tabs removed — redirect to settings
  if (tab === 'reasoning' || tab === 'timeline') tab = 'settings';
  document.querySelectorAll('.subtab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.subtab-pane').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  const tabMap = { settings: 'subtabSettings', prompts: 'subtabPrompts', graphics: 'subtabGraphics' };
  const buttons = document.querySelectorAll('.subtab-bar button');
  const idx = { settings: 0, prompts: 1, graphics: 2 }[tab] ?? 0;
  if (buttons[idx]) buttons[idx].classList.add('active');
  const pane = document.getElementById(tabMap[tab]);
  if (pane) { pane.classList.add('active'); pane.style.display = 'flex'; }
  if (tab === 'prompts') renderPromptsTab();
}

function toggleAdBanner() {} // legacy no-op
