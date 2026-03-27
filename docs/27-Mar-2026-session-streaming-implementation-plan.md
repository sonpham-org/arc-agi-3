# Session Streaming — Implementation Plan

**Author:** Bubba (Claude Sonnet 4.6)  
**Date:** 27-March-2026  
**Scope:** Add live session streaming to arc-agi-3 (arc3.sonpham.net)  
**Spec:** [`docs/SESSION-LOG-API.md`](SESSION-LOG-API.md)  
**Status:** Ready for implementation

---

## Objective

External harnesses running locally can stream game sessions in real-time to arc3.sonpham.net. Live sessions appear in Browse Sessions → AI Sessions. Viewers watch the Observatory swimlane update live. When the session ends, it becomes a normal replay.

---

## Architecture

```
Local Harness ──WS──▶ Flask (flask-sock) ──▶ SQLite DB
                                           ──▶ SSE broadcast to viewers
```

No framework change. Flask stays. One new WebSocket endpoint via `flask-sock`. Everything else is REST/SSE as-is.

---

## Dependencies

**New pip package:**
```
flask-sock>=0.7.0
```

Add to `requirements.txt`. Works with existing Gunicorn `--threads 8` config. No Procfile change.

---

## Implementation Steps

### Step 1: Stream token table

Add a `stream_tokens` table to the DB schema in `db.py`:

```sql
CREATE TABLE IF NOT EXISTS stream_tokens (
    session_id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    active INTEGER DEFAULT 1
);
```

Token is a random 32-byte hex string. Expires after 4 hours. One token per session.

**File:** `db.py` — add to `_init_db()` schema creation block.

### Step 2: Register endpoint

**Route:** `POST /api/sessions/stream/register`

**File:** `server/app.py` (or a new `server/stream_routes.py` if you prefer to keep it separate — but `app.py` is fine given it already has 63 routes).

**Request:**
```json
{
  "game_id": "ls20",
  "harness": "three-system-v2",
  "agents": [{"id": "planner", "model": "gemini-2.5-flash", "role": "planner"}],
  "user_id": "optional"
}
```

**Logic:**
1. Generate `session_id` (UUID4)
2. Generate `stream_token` (secrets.token_hex(32))
3. Insert into `sessions` table: `id`, `game_id`, `mode="stream"`, `player_type="agent"`, `model` (from first agent), `scaffolding_json` (JSON of agents + harness)
4. Insert into `stream_tokens`: `session_id`, `token`, `created_at`, `expires_at` (now + 4h), `active=1`
5. Return:
```json
{
  "session_id": "abc123",
  "stream_token": "tok_xxx",
  "ws_url": "wss://arc3.sonpham.net/ws/stream/abc123?token=tok_xxx",
  "view_url": "https://arc3.sonpham.net/#obs?session=abc123"
}
```

### Step 3: WebSocket ingest handler

**Route:** `/ws/stream/<session_id>` via `flask-sock`

**File:** New file `server/stream_ws.py` — keeps WS logic separate from REST routes.

```python
# server/stream_ws.py
from flask_sock import Sock
import json, time, secrets
from db import _db
from db_sessions import _db_insert_action, _db_update_session
from db_llm import _db_insert_llm_call
from db_tools import _db_insert_tool_execution

sock = Sock()

# In-memory: session_id → list of SSE queue references
_live_viewers = {}  # session_id → [queue.Queue, ...]

def init_stream_ws(app):
    sock.init_app(app)

@sock.route('/ws/stream/<session_id>')
def stream_session(ws, session_id):
    # 1. Validate token
    token = ws.environ.get('HTTP_SEC_WEBSOCKET_PROTOCOL') or \
            _extract_query_param(ws.environ, 'token')
    if not _validate_stream_token(session_id, token):
        ws.close(4001, 'Invalid or expired stream token')
        return

    # 2. Mark session as live
    _db_update_session(session_id, mode='stream_live')

    # 3. Event loop
    try:
        while True:
            raw = ws.receive(timeout=300)  # 5 min idle timeout
            if raw is None:
                break
            event = json.loads(raw)
            _process_event(session_id, event)
            _broadcast_to_viewers(session_id, event)

            if event.get('event') == 'session_end':
                _finalize_session(session_id, event)
                break
    except Exception:
        pass
    finally:
        # Mark session as no longer live
        _mark_session_ended(session_id)
        _cleanup_viewers(session_id)
```

**`_process_event(session_id, event)`** — dispatcher:

| `event.event` | Action |
|---------------|--------|
| `session_start` | Update `sessions` row with `scaffolding_json`, `model`, `game_version` |
| `llm_call` | Insert into `llm_calls` via `_db_insert_llm_call()` — map `agent_id` → `agent_type`, `response` → `output_json`, etc. |
| `act` | Insert into `session_actions` via `_db_insert_action()` — `action_id` → `action`, `grid` → `states_json` as `[{"grid": grid}]` |
| `memory_write` | Insert into `tool_executions` with `tool_name="memory_write"`, `code`=file name, `output`=content |
| `tool_call` | Insert into `tool_executions` via `_db_insert_tool_execution()` |
| `agent_message` | Insert into `tool_executions` with `tool_name="agent_message"`, `code`=from→to, `output`=content |
| `session_end` | Update `sessions` row: `result`, `total_cost`, `steps`, `levels`, `duration_seconds` |

**`_broadcast_to_viewers(session_id, event)`** — push event JSON to all SSE queues in `_live_viewers[session_id]`.

### Step 4: SSE live tail

**Modify:** `obs_server.py` → `get_session_obs_events()`

When `?live=true` is passed:
1. Return all existing events (same as current code)
2. Register a `queue.Queue` in `_live_viewers[session_id]`
3. Enter a loop: `yield queue.get(timeout=30)` — sends each event as SSE
4. On timeout with no events, send SSE `:keepalive` comment
5. When session ends (queue receives sentinel), close the SSE connection

```python
@app.route("/api/sessions/<session_id>/obs-events")
def get_session_obs_events(session_id):
    live = request.args.get('live') == 'true'

    # ... existing code to build events from DB ...

    if not live:
        return jsonify({"events": events})

    # Live mode: return SSE stream
    def generate():
        # 1. Yield existing events as initial payload
        yield f"data: {json.dumps({'events': events, 'live': True})}\n\n"

        # 2. Register viewer queue
        q = queue.Queue()
        _live_viewers.setdefault(session_id, []).append(q)
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                    if event is None:  # sentinel = session ended
                        yield f"data: {json.dumps({'event': 'stream_end'})}\n\n"
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            _live_viewers[session_id].remove(q)

    return Response(generate(), mimetype='text/event-stream')
```

### Step 5: Live sessions listing

**Route:** `GET /api/sessions/live`

**File:** `server/app.py` (or `stream_ws.py`)

```python
@app.route("/api/sessions/live")
def list_live_sessions():
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, game_id, model, created_at, steps, levels, total_cost "
            "FROM sessions WHERE mode = 'stream_live' ORDER BY created_at DESC"
        ).fetchall()
    sessions = []
    for r in rows:
        d = dict(r)
        d["viewer_count"] = len(_live_viewers.get(d["id"], []))
        d["elapsed_s"] = round(time.time() - (d.get("created_at") or 0), 1)
        sessions.append(d)
    return jsonify({"sessions": sessions})
```

### Step 6: Upload endpoint (post-hoc)

**Route:** `POST /api/sessions/upload`

**File:** `server/app.py` (or `stream_ws.py`)

Accept `multipart/form-data` with a `.arc3log` file, or raw `application/x-ndjson` body.

**Logic:**
1. Parse each line as JSON
2. Extract `session_id` from first event
3. Check session doesn't already exist (or allow overwrite with `?force=true`)
4. Process each event through `_process_event()` (same function as WS handler)
5. Return `{"session_id": "...", "url": "...", "events_ingested": N}`

### Step 7: Frontend — Live badge in session browser

**File:** `static/js/session-views-grid.js` (or wherever the session list renders)

When rendering AI sessions, check if `session.mode === 'stream_live'`:
- Show "🔴 Live" badge
- Sort live sessions to top
- Link clicks → Observatory with `?live=true`

### Step 8: Frontend — Observatory live mode

**File:** `static/js/obs-session-loader.js`

When loading a session with `?live=true`:
1. Fetch `/api/sessions/{id}/obs-events?live=true` as EventSource (SSE)
2. On initial data, render swimlane as normal
3. On each new SSE event, append to swimlane, update game view, update counters
4. On `stream_end`, remove live indicator, close EventSource

The swimlane renderer (`obs-swimlane.js`) already handles incremental event addition — it just needs to be called on each incoming SSE event instead of only on page load.

---

## File Summary

| File | Change | Type |
|------|--------|------|
| `requirements.txt` | Add `flask-sock>=0.7.0` | Edit |
| `db.py` | Add `stream_tokens` table to schema | Edit |
| `server/stream_ws.py` | **New** — WS handler, event processor, viewer broadcast, upload endpoint | New |
| `server/app.py` | Import and init `stream_ws`, add register + live list + upload routes | Edit |
| `obs_server.py` | Add `?live=true` SSE tail to `get_session_obs_events` | Edit |
| `static/js/session-views-grid.js` | Live badge rendering, sort live sessions to top | Edit |
| `static/js/obs-session-loader.js` | SSE EventSource for live Observatory mode | Edit |
| `CHANGELOG.md` | New entry for session streaming feature | Edit |

---

## Verification Checklist

1. [ ] `pip install flask-sock` succeeds, Gunicorn starts with no errors
2. [ ] `POST /api/sessions/stream/register` returns valid session_id, token, ws_url
3. [ ] WebSocket connects with valid token, rejects invalid token
4. [ ] Send `session_start` + `llm_call` + `act` + `session_end` over WS → verify rows in `sessions`, `llm_calls`, `session_actions`
5. [ ] `GET /api/sessions/live` shows the streaming session while WS is open
6. [ ] `GET /api/sessions/{id}/obs-events?live=true` streams events in real-time to a second terminal
7. [ ] Session disappears from `/live` after `session_end`
8. [ ] Session appears as normal replay in Browse Sessions → AI Sessions after end
9. [ ] `POST /api/sessions/upload` with a `.arc3log` file creates a replayable session
10. [ ] Observatory swimlane renders live events incrementally
11. [ ] Live badge appears in session browser
12. [ ] Railway deploy: WS connections survive through Railway's proxy

---

## Railway Notes

- Railway supports WebSocket connections natively — no special config needed
- Gunicorn with `--threads 8` handles `flask-sock` — each WS connection uses one thread
- With 8 threads and 1 worker, you can support ~6 concurrent streaming sessions (leaving 2 threads for REST). If you need more, bump `--threads 16` or add `--workers 2`.
- Railway has a 5-minute idle timeout on WebSocket connections — the harness should send events at least every 4 minutes. If no game events are happening, send a keepalive:
  ```json
  {"v": 1, "event": "keepalive", "t": "...", "session_id": "...", "game_id": "..."}
  ```
