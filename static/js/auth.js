// Author: Claude Opus 4.6
// Date: 2026-03-16 23:30
// PURPOSE: Shared authentication module for ARC Observatory and AutoResearch Arena.
//   Handles magic link login, Google OAuth UI, user badge display, logout,
//   session claiming, and auth status polling. Extracted from session.js so both
//   pages share a single auth implementation.
//   Requires: `currentUser` global declared before this script loads.
//   DOM elements: loginBtn, userBadge, userBadgeLabel, userMenuEmail, userMenu,
//     loginModal, loginStep1, loginStep2, loginError, loginEmail, loginSendBtn, loginSentEmail.
// SRP/DRY check: Pass — single auth module shared across Observatory and Arena

// ═══════════════════════════════════════════════════════════════════════════
// AUTH — Magic link login, Google OAuth, user badge, logout
// ═══════════════════════════════════════════════════════════════════════════

function updateAuthUI() {
  const loginBtn = document.getElementById('loginBtn');
  const userBadge = document.getElementById('userBadge');
  if (!loginBtn || !userBadge) return;
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
  if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
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
  const modal = document.getElementById('loginModal');
  if (!modal) return;
  modal.style.display = 'flex';
  const s1 = document.getElementById('loginStep1');
  const s2 = document.getElementById('loginStep2');
  const err = document.getElementById('loginError');
  if (s1) s1.style.display = '';
  if (s2) s2.style.display = 'none';
  if (err) err.style.display = 'none';
  const emailEl = document.getElementById('loginEmail');
  if (emailEl) { emailEl.value = ''; emailEl.focus(); }
}

function hideLoginModal() {
  const modal = document.getElementById('loginModal');
  if (modal) modal.style.display = 'none';
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
  const menu = document.getElementById('userMenu');
  if (menu) menu.style.display = 'none';
}

async function checkAuthStatus() {
  try {
    const resp = await fetch('/api/auth/status');
    const data = await resp.json();
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
