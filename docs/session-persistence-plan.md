# Session Persistence — Architecture Analysis & Fix Plan

> **Status:** Planning only — no code changes in this document.
> **Author:** Claude Sonnet 4.6, 2026-03-11
> **Scope:** `server.py` lines 679–1025 (game flow), 1221–1636 (import/resume/branch), `session_manager.py`

---

## 1. What We Are Trying to Achieve

A session represents a single game playthrough. The system must guarantee:

1. **Durability** — a server restart must not lose a player's current position or the history of moves
2. **Undo correctness** — after undo, a resume must reproduce the post-undo state, not the pre-undo state
3. **Resume fidelity** — resuming a session must produce *exactly* the same game state as the original, without O(n) replay cost growing unboundedly
4. **Branch fidelity** — branching from step K must produce a game env that matches the original at step K
5. **Import agreement** — a session imported from the client (puter.kv) must resume identically to one that was played server-side
6. **Code clarity** — the session reconstruction logic must not be duplicated in five separate route handlers

The current code achieves none of these reliably.

---

## 2. Current Architecture (and What's Wrong With It)

### 2.1 Two Divergent Sources of Truth

There are two session representations that are maintained separately and can disagree:

| Layer | What it stores | Lifetime |
|-------|---------------|----------|
| **In-memory** | `game_sessions[sid]` (live env), `session_grids[sid]`, `session_snapshots[sid]`, `session_step_counts[sid]` | Process lifetime only — lost on restart |
| **SQLite** | `sessions` row + `session_actions` rows (compressed grids, action codes) | Durable |

After every `/api/step`, both are updated. But they are updated **sequentially, not atomically**. A crash between the two writes leaves them inconsistent.

### 2.2 Undo Is Not Durable (Critical Bug)

When `/api/undo` is called:
- `session_snapshots[sid].pop()` — the in-memory snapshot is discarded ✓
- `session_grids[sid]` is restored to the pre-step grid ✓
- **Nothing is written to the DB** ✗

After a server restart, `_reconstruct_session` replays all rows from `session_actions`. The undone action is still there. The resumed session is at step N, not step N-1. **The undo is silently reversed.**

If the player undoes 10 moves and then the server restarts, all 10 moves come back.

### 2.3 O(n) Replay on Every Resume and Branch

Both `resume_session` and `branch_session` replay the full action history through a fresh env:

```python
env, state, per_step_states = _reconstruct_session(
    sess["game_id"], actions, capture_per_step=True, ...
)
```

A 500-step session replays 500 actions synchronously on the HTTP request thread. There is no checkpoint mechanism. Resume time grows linearly with session length.

### 2.4 Duplicated Action-Row-to-Dict Conversion

Three places independently convert `session_actions` DB rows into `{action, data}` dicts for replay:

**`resume_session` (server.py ~1426–1433):**
```python
act = {"action": rd["action"]}
if rd.get("row") is not None and rd.get("col") is not None:
    act["data"] = json.dumps({"x": rd["col"], "y": rd["row"]})
else:
    act["data"] = None
```

**`branch_session` (server.py ~1588–1594):** Identical copy.

**`_try_recover_session` (session_manager.py ~100–107):**
```python
act = {"action": r["action"]}
if r["row"] is not None and r["col"] is not None:
    act["data"] = json.dumps({"x": r["col"], "y": r["row"]})
else:
    act["data"] = None
```

Three copies. `_reconstruct_session` handles both JSON string `data` and plain dict `data` via:
```python
if isinstance(data, str):
    data = json.loads(data)
```
This masks the inconsistency. It works, but the presence of the `isinstance` check is a smell that the calling code is inconsistent.

### 2.5 Feature Flag Guard Duplicated 9+ Times

Every session DB endpoint begins with:
```python
if not feature_enabled("session_db"):
    return jsonify({"error": "Session DB not enabled"}), 400
```

This is copy-pasted into `import_session`, `resume_session`, `branch_session`, `list_sessions`, `get_session`, `get_session_step`, `leaderboard`, and more.

### 2.6 DB Connections Without Context Managers

Every DB operation follows this pattern:
```python
conn = _get_db()
# ... work ...
conn.commit()
conn.close()
```

With no `try/finally`. If an exception is raised between open and close, the connection is never closed. SQLite allows multiple connections to the same file, so this doesn't deadlock, but it leaks file descriptors and can eventually exhaust the OS limit.

Some routes open the connection, close it early on an error path, then open it *again* later in the same handler (e.g., `branch_session` opens twice — once to query the parent, once to insert the new session).

### 2.7 Import Sessions May Not Match Server-Side Replay

When puter.kv uploads a session via `/api/sessions/import`, each step includes a `grid` field from the client. The server stores this in `states_json` (compressed). But when that session is later *resumed*, the server ignores these stored grids entirely and replays actions through a fresh env. If there is any divergence between client-side game execution and server-side replay (version mismatch, float precision, etc.), the resumed state will differ from the original — silently.

### 2.8 Hardcoded `change_map` Object in 5 Places

```python
state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(initial)"}
state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(resumed)"}
state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(reset)"}
state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(undo)"}
state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(branch)"}
```

---

## 3. Proposed Architecture

### 3.1 Core Principle: DB Is the Single Source of Truth

The in-memory layer (`game_sessions`, `session_grids`, etc.) is a **cache** of the DB state, not a parallel source of truth. Any operation that changes session state must write to DB *first*, then update memory. If the server restarts, memory is reconstructed from DB — not the other way around.

### 3.2 Fix 1 — Make Undo Durable (Highest Priority)

**Current behavior:** Undo pops from `session_snapshots` in RAM. DB unchanged.

**Correct behavior:** Undo must remove the last N action rows from `session_actions` and update `sessions.steps`. Memory is then trivially consistent because replay would produce the correct result.

```python
# In undo_step(), after confirming the snapshot:
if feature_enabled("session_db"):
    conn = _get_db()
    # Delete the last `count` actions
    conn.execute("""
        DELETE FROM session_actions
        WHERE session_id = ? AND step_num > (
            SELECT MAX(step_num) - ? FROM session_actions WHERE session_id = ?
        )
    """, (session_id, count, session_id))
    conn.execute(
        "UPDATE sessions SET steps = MAX(0, steps - ?) WHERE id = ?",
        (count, session_id)
    )
    conn.commit()
    conn.close()
```

The in-memory snapshot can still be used for the *immediate response* (fast, no replay needed), but on the next restart, the replay will be correct because the DB no longer has the undone actions.

**Edge case:** What if the DB write fails but the in-memory pop succeeded? The in-memory state says "undone" but the DB still has the action. On restart, the action comes back. This is acceptable for now — it degrades to the current broken behavior, which is better than a crash. A retry wrapper could be added later.

### 3.3 Fix 2 — Extract `_action_dict_from_row(row)` Helper

Replace the three duplicate conversions with one canonical function in `session_manager.py`:

```python
def _action_dict_from_row(row: dict) -> dict:
    """Convert a session_actions DB row into an {action, data} dict for replay."""
    act = {"action": row["action"]}
    if row.get("row") is not None and row.get("col") is not None:
        act["data"] = {"x": row["col"], "y": row["row"]}
    else:
        act["data"] = None
    return act
```

Note: this returns a plain dict for `data`, not a JSON string. `_reconstruct_session` must then be updated to remove the `isinstance(data, str)` branch (or keep it for backward compat with any other callers that still produce JSON strings).

### 3.4 Fix 3 — `@require_session_db` Decorator

```python
from functools import wraps

def require_session_db(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not feature_enabled("session_db"):
            return jsonify({"error": "Session DB not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper
```

Apply to all session endpoints. Remove the 9+ inline checks.

### 3.5 Fix 4 — `_empty_change_map(label)` Helper

```python
def _empty_change_map(label: str) -> dict:
    return {"changes": [], "change_count": 0, "change_map_text": label}
```

Replace all 5 hardcoded dict literals.

### 3.6 Fix 5 — DB Context Manager

Add to `db.py`:

```python
from contextlib import contextmanager

@contextmanager
def db_conn():
    """Context manager for SQLite connections. Commits on success, rolls back on error."""
    conn = _get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Usage in route handlers:
```python
with db_conn() as conn:
    sess = conn.execute("SELECT ...", (...,)).fetchone()
    conn.execute("INSERT ...", (...,))
    # auto-commit + auto-close on exit
```

This replaces every manual open/commit/close pattern (10+ sites).

### 3.7 Fix 6 — Consolidate Session Reconstruction Into One Path

Currently `resume_session` and `branch_session` each contain:
1. DB query to get session metadata
2. DB query to get action rows
3. Action-row-to-dict conversion
4. Call to `_reconstruct_session`
5. Register env in global state dicts
6. Build step_list and attach per-step stats

Steps 1–5 should be a single function `_load_and_reconstruct(session_id, up_to_step=None)` in `session_manager.py`. Both `resume_session` and `branch_session` call this. The function returns `(env, state, per_step_states, action_rows)`.

### 3.8 Long-Term — Checkpointing (Phase 2)

The O(n) replay problem requires game envs to support serialization. This is a larger effort:

1. Add `env.serialize() -> bytes` and `env.deserialize(bytes)` to `ARCBaseGame`
2. After every `CHECKPOINT_INTERVAL` steps (e.g., 50), store a serialized checkpoint in `session_actions` as a special row type (`action = -1, states_json = <pickle>`)
3. On resume, find the last checkpoint, deserialize, then replay only the delta steps after it

This is not part of the immediate fix plan. The immediate fixes (1–7) address correctness. Checkpointing addresses performance.

---

## 4. Decomposition Plan: Extract `routes/sessions.py`

Beyond fixing bugs, the ~800 lines of session-related code in `server.py` should be extracted into a Flask Blueprint.

### Target file structure

```
server.py               — app setup, game flow (/api/start, /api/step, /api/reset, /api/undo)
routes/
  sessions.py           — Blueprint: /api/sessions/* (import, resume, branch, list, get, get-step)
  analytics.py          — Blueprint: /api/sessions (list), /api/leaderboard, /api/contributors, /api/game-results, /api/comments
session_manager.py      — In-memory state, _reconstruct_session, _try_recover_session, _load_and_reconstruct (new)
db.py                   — DB init, _get_db(), db_conn() context manager
```

### Registration in `server.py`

```python
from routes.sessions import sessions_bp
from routes.analytics import analytics_bp

app.register_blueprint(sessions_bp)
app.register_blueprint(analytics_bp)
```

### What stays in `server.py`

- Flask app init + config
- Feature flags
- Game flow: `/api/start`, `/api/step`, `/api/reset`, `/api/undo`, `/api/dev/jump-level`
- Game metadata: `/api/games`, `/api/game-source`
- LLM registry: `/api/llm/models`, `/api/llm/cf-proxy`
- Auth endpoints (or move to `routes/auth.py`)

---

## 5. Implementation Order

Do these in sequence. Each step is independently testable.

| Step | Change | Risk | Test |
|------|--------|------|------|
| **5.1** | Add `db_conn()` context manager to `db.py` | Low — additive | Import check |
| **5.2** | Replace all manual `conn = _get_db() / conn.close()` with `with db_conn() as conn:` | Low | All session endpoints, smoke test |
| **5.3** | Add `_action_dict_from_row()` to `session_manager.py`; replace 3 duplicates | Low | Resume and branch sessions |
| **5.4** | Add `_empty_change_map()` to `session_manager.py` or `server.py`; replace 5 literals | Trivial | Any session response |
| **5.5** | Add `@require_session_db` decorator; replace 9+ inline checks | Low | Session endpoints |
| **5.6** | Fix undo durability (write deletes to DB in `undo_step`) | **Medium** | Undo + restart + resume must agree |
| **5.7** | Add `_load_and_reconstruct()` to `session_manager.py`; replace resume/branch duplication | Medium | Resume and branch sessions |
| **5.8** | Extract `routes/sessions.py` Blueprint | Medium | Full import check + smoke test |

### Critical regression tests after Step 5.6 (undo durability)

1. Start game, take 5 steps, undo 2 steps
2. Simulate restart (clear `game_sessions`, reload env from DB)
3. Call `/api/sessions/resume` — must return step 3 state (not step 5)
4. Verify `session_actions` has 3 rows (not 5)

---

## 6. What We Are Not Fixing (Explicitly Out of Scope)

- **Import vs. replay agreement**: the grids stored in `states_json` during import are ignored on resume. Fixing this requires either trusting client grids (risky) or always canonicalizing via server-side replay (current approach, just accept the divergence risk). Leave as-is.
- **Auth on session endpoints**: `/api/sessions` (GET) and `/api/game-results` have no `@bot_protection`. Leave for the auth plan.
- **O(n) resume**: left for the checkpointing phase. The immediate fix eliminates the *correctness* problem; the performance problem is accepted for now.
- **The `_format_action_row` / `_format_step_row` alias**: the alias can be deleted after confirming no callers use `_format_step_row` directly. Low priority.
