// ═══════════════════════════════════════════════════════════════════════════
// HUMAN PLAY MODE — Social Features (Comments, Contributors, Feedback)
// ═══════════════════════════════════════════════════════════════════════════
// Extracted from human.js (Phase 16 refactor)
// Provides: game comments, contributor stats, feedback submission

// ── Comments System ────────────────────────────────────────────────────────

function _getCommenterId() {
  // Use logged-in user ID, or generate a persistent anonymous ID
  if (typeof currentUser !== 'undefined' && currentUser?.id) return currentUser.id;
  let id = localStorage.getItem('arc_commenter_id');
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('arc_commenter_id', id); }
  return id;
}

function _getCommenterName() {
  if (typeof currentUser !== 'undefined' && currentUser) {
    return currentUser.display_name || currentUser.email?.split('@')[0] || 'User';
  }
  return 'anon-' + _getCommenterId().slice(0, 6);
}

function _timeAgo(ts) {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

async function loadComments() {
  const gameId = _humanGameId;
  const list = document.getElementById('commentsList');
  const compose = document.getElementById('commentCompose');
  if (!gameId) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Select a game to see comments.</div>';
    compose.style.display = 'none';
    return;
  }
  compose.style.display = '';
  list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Loading...</div>';
  try {
    const comments = await fetchJSON('/api/comments/' + encodeURIComponent(gameId.split('-')[0]) + '?voter_id=' + encodeURIComponent(_getCommenterId()));
    if (!comments.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No comments yet. Be the first!</div>';
      return;
    }
    list.innerHTML = comments.map(c => _renderComment(c, 'game')).join('');
  } catch (e) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Failed to load comments.</div>';
  }
}

function _renderComment(c, context) {
  const upClass = c.my_vote === 1 ? ' active-up' : '';
  const downClass = c.my_vote === -1 ? ' active-down' : '';
  const ctx = context ? `,'${context}'` : '';
  return `<div class="comment-card" id="comment-${c.id}">
    <div class="comment-header">
      <span class="comment-author">${_esc(c.author_name)}</span>
      <span class="comment-time">${_timeAgo(c.created_at)}</span>
    </div>
    <div class="comment-body">${_esc(c.body)}</div>
    <div class="comment-actions">
      <button class="vote-btn${upClass}" onclick="voteComment(${c.id}, ${c.my_vote === 1 ? 0 : 1}${ctx})">&#9650; ${c.upvotes || 0}</button>
      <button class="vote-btn${downClass}" onclick="voteComment(${c.id}, ${c.my_vote === -1 ? 0 : -1}${ctx})">&#9660; ${c.downvotes || 0}</button>
    </div>
  </div>`;
}

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function submitComment() {
  const input = document.getElementById('commentInput');
  const body = input.value.trim();
  if (!body || !_humanGameId) return;
  const gameId = _humanGameId.split('-')[0];
  try {
    const resp = await fetch('/api/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: gameId,
        body,
        author_id: _getCommenterId(),
        author_name: _getCommenterName(),
      }),
    });
    if (resp.ok) {
      input.value = '';
      document.getElementById('commentCharCount').textContent = '0 / 2000';
      loadComments();
    }
  } catch (e) { /* ignore */ }
}

async function voteComment(commentId, vote, context) {
  const card = document.getElementById('comment-' + commentId);
  const btns = card?.querySelectorAll('.vote-btn');
  // Optimistic UI: update buttons immediately
  if (btns && btns.length >= 2) {
    const upBtn = btns[0], downBtn = btns[1];
    const wasUp = upBtn.classList.contains('active-up');
    const wasDown = downBtn.classList.contains('active-down');
    upBtn.classList.remove('active-up');
    downBtn.classList.remove('active-down');
    let upCount = parseInt(upBtn.textContent.replace(/[^\d]/g, '')) || 0;
    let downCount = parseInt(downBtn.textContent.replace(/[^\d]/g, '')) || 0;
    if (wasUp) upCount--;
    if (wasDown) downCount--;
    if (vote === 1) { upCount++; upBtn.classList.add('active-up'); }
    if (vote === -1) { downCount++; downBtn.classList.add('active-down'); }
    upBtn.innerHTML = '&#9650; ' + upCount;
    downBtn.innerHTML = '&#9660; ' + downCount;
    // Update onclick to toggle correctly
    upBtn.setAttribute('onclick', `voteComment(${commentId}, ${vote === 1 ? 0 : 1}, '${context || ''}')`);
    downBtn.setAttribute('onclick', `voteComment(${commentId}, ${vote === -1 ? 0 : -1}, '${context || ''}')`);
  }
  try {
    await fetch('/api/comments/' + commentId + '/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voter_id: _getCommenterId(), vote }),
    });
  } catch (e) { /* ignore */ }
}

// Wire up char counter
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('commentInput');
  if (input) input.addEventListener('input', () => {
    document.getElementById('commentCharCount').textContent = input.value.length + ' / 2000';
  });
});

// ── Contributors Page ──────────────────────────────────────────────────────

let _contribLoaded = false;

function _fmtTime(secs) {
  if (!secs) return '-';
  if (secs < 60) return Math.round(secs) + 's';
  if (secs < 3600) return Math.round(secs / 60) + 'm';
  return (secs / 3600).toFixed(1) + 'h';
}

async function loadContributors() {
  if (_contribLoaded) return;
  try {
    const data = await fetchJSON('/api/contributors');
    // Human players
    const hBody = document.getElementById('contribHumans');
    if (data.human_players?.length) {
      hBody.innerHTML = data.human_players.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.uid === 'anon' ? 'Anonymous' : r.uid.slice(0, 8))}</td>
        <td>${r.session_count}</td><td>${r.games_played}</td>
        <td>${r.total_steps}</td><td>${_fmtTime(r.total_time)}</td>
      </tr>`).join('');
    } else {
      hBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    // Commenters
    const cBody = document.getElementById('contribCommenters');
    if (data.commenters?.length) {
      cBody.innerHTML = data.commenters.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.author_name)}</td>
        <td>${r.comment_count}</td><td>${r.total_upvotes || 0}</td>
      </tr>`).join('');
    } else {
      cBody.innerHTML = '<tr><td colspan="4" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    // AI contributors
    const aBody = document.getElementById('contribAI');
    if (data.ai_contributors?.length) {
      aBody.innerHTML = data.ai_contributors.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${_esc(r.uid === 'anon' ? 'Anonymous' : r.uid.slice(0, 8))}</td>
        <td>${r.session_count}</td><td>${r.games_played}</td>
        <td>${r.total_steps}</td><td>${_esc(r.model || '-')}</td>
      </tr>`).join('');
    } else {
      aBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);text-align:center;">No data yet</td></tr>';
    }
    _contribLoaded = true;
  } catch (e) {
    console.error('Failed to load contributors', e);
  }
}

// ── Feedback Page ──────────────────────────────────────────────────────────

let _feedbackLoaded = false;

async function loadFeedback() {
  const list = document.getElementById('feedbackList');
  list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Loading...</div>';
  try {
    const comments = await fetchJSON('/api/comments/_feedback?voter_id=' + encodeURIComponent(_getCommenterId()));
    if (!comments.length) {
      list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">No feedback yet. Be the first!</div>';
    } else {
      list.innerHTML = comments.map(c => _renderComment(c, 'feedback')).join('');
    }
  } catch (e) {
    list.innerHTML = '<div class="empty-state" style="height:auto;font-size:12px;">Failed to load feedback.</div>';
  }
}

async function submitFeedback() {
  const input = document.getElementById('feedbackInput');
  const body = input.value.trim();
  if (!body) return;
  try {
    const resp = await fetch('/api/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: '_feedback',
        body,
        author_id: _getCommenterId(),
        author_name: _getCommenterName(),
      }),
    });
    if (resp.ok) {
      input.value = '';
      document.getElementById('feedbackCharCount').textContent = '0 / 2000';
      loadFeedback();
    }
  } catch (e) { /* ignore */ }
}

// Wire up feedback char counter
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('feedbackInput');
  if (input) input.addEventListener('input', () => {
    document.getElementById('feedbackCharCount').textContent = input.value.length + ' / 2000';
  });
});
