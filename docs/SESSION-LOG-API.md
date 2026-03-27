# ARC3 Session Log API — Universal Harness Format

**Author:** Bubba (Claude Sonnet 4.6)  
**Date:** 27-March-2026  
**For:** Son Pham — harness developer  
**Purpose:** Define a universal session log format that any harness can produce, stream live to arc3.sonpham.net, and replay in the Observatory swimlane.

---

## Design Goals

1. **Harness-agnostic** — any architecture (single agent, multi-agent, orchestrator/subagent, tool-using, REPL-based) can emit this format
2. **Self-contained** — a single file contains everything needed to replay and visualize a session offline
3. **Live-streamable** — events push from a local harness to the server over WebSocket; viewers see them in real-time
4. **Uploadable** — completed sessions can also be uploaded after the fact
5. **Swimlane-compatible** — maps directly to the existing swimlane/Observatory visualization
6. **Memory-transparent** — memory state and log files are snapshotted at each write so you can see what the agent "knew" at any point

---

## Log Format: JSONL

One JSON object per line. Order is chronological. Each line is an **event**.

File extension: `.arc3log` (or `.jsonl` — both accepted on upload)

### Envelope (required on every event)

```json
{
  "v": 1,
  "t": "2026-03-27T19:15:00.213Z",
  "elapsed_s": 42.3,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "<event_type>"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `v` | int | Schema version. Always `1` for now. |
| `t` | ISO-8601 UTC | Wall clock timestamp |
| `elapsed_s` | float | Seconds since session start |
| `session_id` | string | Unique session ID (UUID or your choice) |
| `game_id` | string | ARC game ID (e.g. `ls20`, `ft09`) |
| `event` | string | Event type — see below |

---

## Event Types

### `session_start`

Emitted once at the beginning. Contains harness metadata.

```json
{
  "v": 1,
  "t": "2026-03-27T19:00:00.000Z",
  "elapsed_s": 0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "session_start",
  "harness": "three-system-v2",
  "agents": [
    {"id": "planner", "model": "gemini-2.5-flash", "role": "planner"},
    {"id": "executor", "model": "claude-sonnet-4-6", "role": "executor"},
    {"id": "monitor", "model": "gemini-2.5-flash", "role": "monitor"}
  ],
  "scaffolding": {
    "mode": "three_system",
    "planning_horizon": 5,
    "memory_injection": true
  },
  "game_version": "ls20-9607627b"
}
```

---

### `llm_call`

One event per LLM API call. The swimlane renders one row per unique `agent_id`.

```json
{
  "v": 1,
  "t": "2026-03-27T19:01:23.456Z",
  "elapsed_s": 83.4,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "llm_call",
  "call_id": "call-001",
  "parent_call_id": null,
  "agent_id": "planner",
  "agent_role": "planner",
  "model": "gemini-2.5-flash",
  "step_num": 3,
  "turn_num": 1,
  "input_tokens": 4200,
  "output_tokens": 380,
  "cost": 0.0018,
  "duration_ms": 1240,
  "prompt_summary": "Current grid state + history. Planning next 5 actions.",
  "response": "I see the key is in the bottom-left at col 3, row 58. I need to move LEFT then UP to reach the red tile which should transform color...",
  "coordinates_mentioned": [
    {"col": 3, "row": 58, "label": "key"},
    {"col": 10, "row": 45, "label": "color-transform tile"}
  ],
  "reasoning": "Extended thinking content if available — omit if none",
  "error": null
}
```

**`coordinates_mentioned`** is optional but enables the coordinate hover→highlight feature. Parse or extract coordinate references from the LLM response and emit them here. Format: array of `{col, row, label}` objects. `label` is a short human-readable description.

---

### `act`

One event per game action submitted. Emitted immediately after the action is applied to the game engine.

```json
{
  "v": 1,
  "t": "2026-03-27T19:01:25.000Z",
  "elapsed_s": 85.0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "act",
  "call_id": "call-001",
  "agent_id": "executor",
  "step_num": 3,
  "action": "UP",
  "action_id": 1,
  "row": null,
  "col": null,
  "grid": [[0,0,1,0,...], ...],
  "level": 1,
  "result": "ok"
}
```

**`grid`** is the full 64×64 grid state **after** the action is applied, as a 2D array of integers (0–15). This is what drives the game view on the right side of the swimlane and the scrubber.

`result` values: `"ok"` | `"level_complete"` | `"game_win"` | `"game_over"` | `"error"`

For click-based games (coordinate actions), populate `row` and `col` with the target cell.

---

### `memory_write`

Emitted whenever the agent writes to its memory file. Enables "view memory state up to this point."

```json
{
  "v": 1,
  "t": "2026-03-27T19:02:00.000Z",
  "elapsed_s": 120.0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "memory_write",
  "agent_id": "executor",
  "step_num": 5,
  "file": "MEMORY.md",
  "content": "# Level 1 Notes\nKey found at col 3, row 58. Red tile at col 10, row 45 transforms color. Blue tile rotates. Need LEFT then UP to reach red tile first.\n"
}
```

The `content` field is the **full file content at the time of write** — not a diff. This lets the viewer show a "memory at step N" view.

---

### `tool_call`

Emitted when the agent calls an external tool (REPL, code execution, external API, etc.).

```json
{
  "v": 1,
  "t": "2026-03-27T19:01:50.000Z",
  "elapsed_s": 110.0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "tool_call",
  "call_id": "call-001",
  "agent_id": "planner",
  "step_num": 4,
  "tool": "python_repl",
  "code": "grid = get_current_grid()\nblue_tiles = [(r,c) for r,row in enumerate(grid) for c,v in enumerate(row) if v == 8]\nprint(blue_tiles)",
  "output": "[(32, 15), (33, 16), (34, 17)]",
  "error": null,
  "duration_ms": 45
}
```

---

### `agent_message`

Inter-agent communication in multi-agent harnesses. Logged for transparency.

```json
{
  "v": 1,
  "t": "2026-03-27T19:02:10.000Z",
  "elapsed_s": 130.0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "agent_message",
  "from_agent": "planner",
  "to_agent": "executor",
  "call_id": "call-001",
  "step_num": 5,
  "content": "Execute plan: [LEFT, UP, LEFT, LEFT, UP]. First LEFT brings us adjacent to the red tile."
}
```

---

### `session_end`

Emitted once at the end.

```json
{
  "v": 1,
  "t": "2026-03-27T19:45:00.000Z",
  "elapsed_s": 2700.0,
  "session_id": "abc123",
  "game_id": "ls20",
  "event": "session_end",
  "result": "WIN",
  "levels_completed": 5,
  "total_steps": 312,
  "total_llm_calls": 89,
  "total_cost": 0.42,
  "total_input_tokens": 380000,
  "total_output_tokens": 28000
}
```

`result` values: `"WIN"` | `"LOSS"` | `"TIMEOUT"` | `"ERROR"` | `"ABANDONED"`

---

## Live Streaming Protocol

This is how a locally-running harness streams events to `arc3.sonpham.net` in real-time so remote viewers can watch sessions as they happen.

### Flow

```
┌──────────────┐         ┌─────────────────────┐         ┌──────────────┐
│ Local Harness │ ──WS──▶ │ arc3.sonpham.net     │ ──SSE──▶│ Browser      │
│ (your laptop) │         │ (server)             │         │ (viewer)     │
└──────────────┘         └─────────────────────┘         └──────────────┘
```

### Step 1: Register a session

```
POST /api/sessions/stream/register
Content-Type: application/json

{
  "game_id": "ls20",
  "harness": "three-system-v2",
  "agents": [...],
  "user_id": "optional-user-id"
}
```

**Response:**
```json
{
  "session_id": "abc123",
  "stream_token": "tok_xxxxxx",
  "ws_url": "wss://arc3.sonpham.net/ws/stream/abc123?token=tok_xxxxxx",
  "view_url": "https://arc3.sonpham.net/#obs?session=abc123"
}
```

The `stream_token` is a short-lived bearer token (valid for this session only). The `view_url` is the link you can share — anyone with it can watch live.

### Step 2: Connect WebSocket and push events

```python
import websockets, json, asyncio

async def stream_session(ws_url):
    async with websockets.connect(ws_url) as ws:
        # Send events as they happen
        await ws.send(json.dumps({
            "v": 1, "t": "...", "elapsed_s": 0,
            "session_id": "abc123", "game_id": "ls20",
            "event": "session_start",
            "harness": "three-system-v2",
            "agents": [...]
        }))

        # ... after each LLM call:
        await ws.send(json.dumps({
            "v": 1, "t": "...", "elapsed_s": 42.0,
            "session_id": "abc123", "game_id": "ls20",
            "event": "llm_call",
            "call_id": "call-001",
            "agent_id": "planner",
            "model": "gemini-2.5-flash",
            ...
        }))

        # ... after each action:
        await ws.send(json.dumps({
            "v": 1, "t": "...", "elapsed_s": 43.5,
            "session_id": "abc123", "game_id": "ls20",
            "event": "act",
            "step_num": 1,
            "action": "UP",
            "grid": [[...], ...],
            ...
        }))

        # ... session ends:
        await ws.send(json.dumps({
            "event": "session_end",
            "result": "WIN",
            ...
        }))
        # WebSocket closes automatically after session_end
```

### Step 3: Server-side processing

On each incoming WS message, the server:

1. **Validates** — checks `stream_token`, schema version, required fields
2. **Persists** — writes to the existing DB tables (`sessions`, `session_actions`, `llm_calls`, `tool_executions`)
3. **Broadcasts** — pushes the event to all connected SSE viewers for this session
4. **Updates session list** — marks session as `"live"` in the sessions listing

### Step 4: Viewer sees it live

The existing Observatory page connects to SSE:

```
GET /api/sessions/{session_id}/obs-events?live=true
```

When `?live=true`:
- Returns all events so far (replay catchup)
- Then holds the connection open and streams new events as they arrive from the WebSocket
- SSE closes when `session_end` is received

The swimlane, game view, and memory panel all update incrementally as events arrive — same rendering code as replay, just fed by a live stream instead of a completed DB query.

### Step 5: Session ends → becomes replay

When `session_end` arrives:
- Session status changes from `"live"` to its final result (`WIN`, `LOSS`, etc.)
- SSE connections to viewers are closed
- WebSocket is closed
- Session is now a normal replay, browsable from the sessions list

### Live Sessions Discovery

```
GET /api/sessions/live
```

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "game_id": "ls20",
      "harness": "three-system-v2",
      "model": "gemini-2.5-flash",
      "started_at": "2026-03-27T19:00:00.000Z",
      "elapsed_s": 420,
      "steps": 47,
      "levels": 2,
      "viewer_count": 3
    }
  ]
}
```

The frontend shows a "🔴 Live" badge on sessions that are currently streaming. Users can click to watch.

---

## Upload Endpoint (Post-Hoc)

For sessions that were run locally without live streaming — bulk upload the complete log.

```
POST /api/sessions/upload
Content-Type: multipart/form-data

file: <session.arc3log>
```

Or as raw body:

```
POST /api/sessions/upload
Content-Type: application/x-ndjson

<raw JSONL content>
```

**Response:**
```json
{
  "session_id": "abc123",
  "url": "https://arc3.sonpham.net/#obs?session=abc123",
  "events_ingested": 412,
  "warnings": []
}
```

Server parses the JSONL, writes all events to the DB tables, and the session is immediately available as a replay.

---

## Swimlane Mapping

How this format drives the existing visualization:

| Swimlane Feature | Driven by |
|-----------------|-----------|
| Agent swim lanes (rows) | `agent_id` on `llm_call` and `act` events |
| LLM call blocks | `llm_call` events — width = `duration_ms` |
| Action markers | `act` events — annotated on executor lane |
| Cost / token counters | `llm_call.cost`, `input_tokens`, `output_tokens` |
| Game view on right | `act.grid` — renders 64×64 grid at selected step |
| Coordinate hover highlight | `llm_call.coordinates_mentioned` — on hover, highlights those cells in the game view |
| Log-to-game-state sync | Clicking any event scrubs the game view to the nearest `act.grid` before that timestamp |
| Memory viewer | `memory_write.content` at the nearest event before the selected timestamp |

---

## DB Table Mapping

How events map to the existing `arc-agi-3` database schema:

| Event | Table | Notes |
|-------|-------|-------|
| `session_start` | `sessions` | Insert row with `id`, `game_id`, `mode`, `model`, `scaffolding_json` |
| `llm_call` | `llm_calls` | Maps directly — `agent_type` = `agent_id`, `input_json` stores prompt/response |
| `act` | `session_actions` | `action` = `action_id`, `states_json` = `[{"grid": grid}]` |
| `tool_call` | `tool_executions` | `tool_name`, `code`, `output`, `error` |
| `memory_write` | New: `memory_snapshots` | Or store in `tool_executions` with `tool_name="memory_write"` |
| `agent_message` | New: `agent_messages` | Or append to `llm_calls` with a special `agent_type` |
| `session_end` | `sessions` | Update `result`, `total_cost`, `steps`, `levels`, `duration_seconds` |

Two new event types (`memory_write`, `agent_message`) don't have existing tables. Options:
- Add two small tables (`memory_snapshots`, `agent_messages`)
- Or reuse `tool_executions` for both (simpler, less schema change)

---

## Minimal Viable Implementation

**For the harness (Son's side):**
- Emit `session_start`, `llm_call`, `act`, `session_end` — that's enough for full swimlane + game replay
- Add `coordinates_mentioned` to `llm_call` for coordinate hover highlight
- Add `memory_write` for memory panel

**For the server:**
1. `POST /api/sessions/stream/register` — creates session, returns token + WS URL
2. WebSocket handler at `/ws/stream/{session_id}` — validates, persists, broadcasts
3. `GET /api/sessions/{session_id}/obs-events?live=true` — SSE with live tail
4. `GET /api/sessions/live` — list active streaming sessions
5. `POST /api/sessions/upload` — bulk JSONL ingest for post-hoc uploads

---

## Notes for Harness Implementors

- **Don't buffer** — write/send each event immediately. Crash-safe locally, low-latency for live viewers.
- **Don't normalize** — emit raw model IDs, raw action names. The platform handles display mapping.
- **Grid state is mandatory** on `act` events — this is what makes replay possible.
- **`call_id`** on `act` events ties the action to the LLM call that decided it — enables the swimlane to draw the decision→action link.
- **Multi-agent:** each subagent gets its own `agent_id`. The swimlane shows one row per unique `agent_id`.
- **Offline fallback:** If the WS connection drops mid-session, the harness should buffer events locally and continue logging to file. Upload the complete log via `POST /api/sessions/upload` when done. The server deduplicates by `session_id` + `event timestamp`.
