# Author: Claude Sonnet 4.6
# Date: 27-Mar-2026
# PURPOSE: WebSocket ingest handler for live session streaming. External harnesses connect
#   via /ws/stream/<session_id>?token=<stream_token>, send JSONL events, and this module
#   persists them to existing DB tables (llm_calls, session_actions, tool_executions) while
#   broadcasting to SSE viewers watching the same session live.
#   Also provides GET /api/sessions/live and POST /api/sessions/upload endpoints.
# SRP/DRY check: Pass — all streaming logic isolated here; reuses existing DB functions
#   (_db_insert_action, _db_update_session, _log_llm_call, _log_tool_execution) without
#   duplicating them. REST routes for register + live list kept in app.py per plan doc.
"""Session streaming — WebSocket ingest, SSE broadcast, live list, upload."""

import json
import logging
import queue
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

from flask_sock import Sock

from db import _db
from db_sessions import _db_insert_action, _db_update_session
from db_llm import _log_llm_call
from db_tools import _log_tool_execution

log = logging.getLogger(__name__)

sock = Sock()

# ── In-memory viewer registry ─────────────────────────────────────────────
# session_id → list of queue.Queue instances (one per SSE viewer)
_live_viewers: dict[str, list] = {}
_viewers_lock = __import__("threading").Lock()


# ═══════════════════════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════════════════════

def init_stream_ws(app):
    """Attach flask-sock to the Flask app. Call once at startup."""
    sock.init_app(app)


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def _validate_stream_token(session_id: str, token: str | None) -> bool:
    """Return True if the token is valid, not expired, and active for session_id."""
    if not token:
        return False
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT token, expires_at, active FROM stream_tokens WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return False
        if not secrets.compare_digest(str(row["token"]), str(token)):
            return False
        if row["expires_at"] < time.time():
            return False
        if not row["active"]:
            return False
        return True
    except Exception as e:
        log.warning("_validate_stream_token error: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# QUERY PARAM EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def _extract_query_param(environ: dict, param: str) -> str | None:
    """Extract a query param from the WSGI environ's QUERY_STRING."""
    qs = environ.get("QUERY_STRING", "")
    parsed = urllib.parse.parse_qs(qs)
    values = parsed.get(param, [])
    return values[0] if values else None


# ═══════════════════════════════════════════════════════════════════════════
# EVENT PROCESSING
# ═══════════════════════════════════════════════════════════════════════════

def _process_event(session_id: str, event: dict) -> None:
    """Dispatch a single streaming event to the correct DB table.

    Event shape follows the SESSION-LOG-API.md spec — key field is event["event"].
    """
    etype = event.get("event", "")

    if etype == "session_start":
        _handle_session_start(session_id, event)

    elif etype == "llm_call":
        _handle_llm_call(session_id, event)

    elif etype == "act":
        _handle_act(session_id, event)

    elif etype == "memory_write":
        _handle_memory_write(session_id, event)

    elif etype == "tool_call":
        _handle_tool_call(session_id, event)

    elif etype == "agent_message":
        _handle_agent_message(session_id, event)

    elif etype == "session_end":
        _handle_session_end(session_id, event)

    elif etype == "keepalive":
        pass  # no-op — just keeps the WS connection alive

    else:
        log.debug("Unknown stream event type '%s' for session %s", etype, session_id)


def _handle_session_start(session_id: str, event: dict) -> None:
    """Update session metadata from session_start event."""
    kwargs: dict = {}
    if event.get("game_version"):
        kwargs["game_version"] = event["game_version"]
    if event.get("agents"):
        agents = event["agents"]
        if isinstance(agents, list) and agents:
            kwargs["model"] = agents[0].get("model", "")
        kwargs["scaffolding_json"] = json.dumps({
            "harness": event.get("harness", ""),
            "agents": agents,
        })
    if kwargs:
        _db_update_session(session_id, **kwargs)


def _handle_llm_call(session_id: str, event: dict) -> None:
    """Insert an llm_calls row from an llm_call event."""
    usage = event.get("usage") or {}
    _log_llm_call(
        session_id=session_id,
        agent_type=event.get("agent_id", "planner"),
        model=event.get("model", ""),
        agent_id=event.get("agent_id"),
        step_num=event.get("step"),
        turn_num=event.get("turn"),
        input_json=json.dumps(event.get("messages")) if event.get("messages") else None,
        input_tokens=usage.get("input_tokens", 0),
        output_json=json.dumps(event.get("response")) if event.get("response") else None,
        output_tokens=usage.get("output_tokens", 0),
        thinking_tokens=usage.get("thinking_tokens", 0),
        cost=event.get("cost", 0),
        duration_ms=int(event.get("duration_ms", 0)),
        error=event.get("error"),
    )


def _handle_act(session_id: str, event: dict) -> None:
    """Insert a session_actions row from an act event."""
    action_id = event.get("action_id", 0)
    grid = event.get("grid")
    states = [{"grid": grid}] if grid else None
    _db_insert_action(
        session_id=session_id,
        step_num=event.get("step", 0),
        action=int(action_id) if str(action_id).isdigit() else 0,
        states=states,
        row=event.get("row"),
        col=event.get("col"),
        author_id=event.get("agent_id"),
        author_type="agent",
    )


def _handle_memory_write(session_id: str, event: dict) -> None:
    """Insert a tool_executions row for a memory_write event."""
    _log_tool_execution(
        session_id=session_id,
        tool_name="memory_write",
        agent_id=event.get("agent_id"),
        code=event.get("file") or event.get("key"),
        output=event.get("content"),
    )


def _handle_tool_call(session_id: str, event: dict) -> None:
    """Insert a tool_executions row for a generic tool_call event."""
    _log_tool_execution(
        session_id=session_id,
        tool_name=event.get("tool_name", "unknown"),
        agent_id=event.get("agent_id"),
        code=json.dumps(event.get("args")) if event.get("args") else None,
        output=json.dumps(event.get("result")) if event.get("result") else None,
        error=event.get("error"),
    )


def _handle_agent_message(session_id: str, event: dict) -> None:
    """Insert a tool_executions row for an agent_message event."""
    from_agent = event.get("from", "")
    to_agent = event.get("to", "")
    _log_tool_execution(
        session_id=session_id,
        tool_name="agent_message",
        agent_id=from_agent,
        code=f"{from_agent}→{to_agent}",
        output=event.get("content"),
    )


def _handle_session_end(session_id: str, event: dict) -> None:
    """Update sessions row with final outcome from session_end event."""
    kwargs: dict = {"mode": "stream"}  # no longer live after session_end
    if event.get("result") is not None:
        kwargs["result"] = str(event["result"])
    if event.get("total_cost") is not None:
        kwargs["total_cost"] = float(event["total_cost"])
    steps = event.get("total_steps") or event.get("steps")
    if steps is not None:
        kwargs["steps"] = int(steps)
    levels = event.get("levels_completed") or event.get("levels")
    if levels is not None:
        kwargs["levels"] = int(levels)
    duration = event.get("duration_seconds") or (event.get("elapsed_s"))
    if duration is not None:
        kwargs["duration_seconds"] = float(duration)
    _db_update_session(session_id, **kwargs)
    # Deactivate the stream token
    try:
        with _db() as conn:
            conn.execute(
                "UPDATE stream_tokens SET active = 0 WHERE session_id = ?",
                (session_id,),
            )
    except Exception as e:
        log.warning("Failed to deactivate stream token for %s: %s", session_id, e)


# ═══════════════════════════════════════════════════════════════════════════
# SSE BROADCAST
# ═══════════════════════════════════════════════════════════════════════════

def _broadcast_to_viewers(session_id: str, event: dict) -> None:
    """Push event to all SSE queues watching this session."""
    with _viewers_lock:
        queues = list(_live_viewers.get(session_id, []))
    for q in queues:
        try:
            q.put_nowait(event)
        except Exception:
            pass  # viewer queue full or gone — skip


def _cleanup_viewers(session_id: str) -> None:
    """Send sentinel None to all viewers so they close their SSE connections."""
    with _viewers_lock:
        queues = list(_live_viewers.get(session_id, []))
    for q in queues:
        try:
            q.put_nowait(None)  # None = sentinel = session ended
        except Exception:
            pass


def register_viewer(session_id: str) -> "queue.Queue":
    """Register a new SSE viewer for session_id. Returns the queue to read from."""
    q: queue.Queue = queue.Queue(maxsize=500)
    with _viewers_lock:
        _live_viewers.setdefault(session_id, []).append(q)
    return q


def unregister_viewer(session_id: str, q: "queue.Queue") -> None:
    """Remove a viewer queue from the registry."""
    with _viewers_lock:
        viewers = _live_viewers.get(session_id, [])
        try:
            viewers.remove(q)
        except ValueError:
            pass
        if not viewers and session_id in _live_viewers:
            del _live_viewers[session_id]


def get_viewer_count(session_id: str) -> int:
    """Return current number of SSE viewers for session_id."""
    with _viewers_lock:
        return len(_live_viewers.get(session_id, []))


def get_live_session_ids() -> list[str]:
    """Return list of session_ids that currently have an open WS connection."""
    with _viewers_lock:
        # Any session in _live_viewers is live (viewers registered = WS still open)
        return list(_live_viewers.keys())


# ═══════════════════════════════════════════════════════════════════════════
# WEBSOCKET ROUTE
# ═══════════════════════════════════════════════════════════════════════════

@sock.route("/ws/stream/<session_id>")
def stream_session(ws, session_id):
    """WebSocket ingest endpoint for live session streaming.

    Harness connects with a valid stream_token, sends JSONL events.
    Events are persisted to DB and broadcast to SSE viewers.
    """
    environ = ws.environ if hasattr(ws, "environ") else {}
    token = (
        environ.get("HTTP_SEC_WEBSOCKET_PROTOCOL")
        or _extract_query_param(environ, "token")
    )

    if not _validate_stream_token(session_id, token):
        log.warning("WS stream rejected: invalid token for session %s", session_id)
        ws.close(4001, "Invalid or expired stream token")
        return

    # Mark session as live
    _db_update_session(session_id, mode="stream_live")
    # Register a viewer queue so SSE viewers can attach before first event
    q = register_viewer(session_id)
    log.info("WS stream started for session %s", session_id)

    try:
        while True:
            try:
                raw = ws.receive(timeout=300)  # 5-min idle timeout
            except Exception:
                break
            if raw is None:
                break

            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                log.warning("Invalid JSON from stream for session %s", session_id)
                continue

            _process_event(session_id, event)
            _broadcast_to_viewers(session_id, event)

            if event.get("event") == "session_end":
                break

    except Exception as e:
        log.warning("WS stream error for session %s: %s", session_id, e)
    finally:
        unregister_viewer(session_id, q)
        _cleanup_viewers(session_id)
        # Only mark ended if not already finalized by session_end event
        try:
            with _db() as conn:
                row = conn.execute(
                    "SELECT mode FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
            if row and row["mode"] == "stream_live":
                _db_update_session(session_id, mode="stream")
        except Exception:
            pass
        log.info("WS stream ended for session %s", session_id)


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD ENDPOINT HELPER (called from app.py route)
# ═══════════════════════════════════════════════════════════════════════════

def process_upload(lines: list[str], force: bool = False) -> dict:
    """Process a list of JSONL lines as a batch upload. Returns result dict or raises ValueError."""
    events = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON on line {i + 1}: {e}") from e

    if not events:
        raise ValueError("No events found in upload")

    # Extract session_id from first event
    session_id = events[0].get("session_id")
    if not session_id:
        raise ValueError("First event must contain 'session_id'")

    # Check for existing session
    with _db() as conn:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    if existing and not force:
        raise ValueError(
            f"Session {session_id} already exists. Use ?force=true to overwrite."
        )

    # Insert session row if new
    if not existing:
        game_id = events[0].get("game_id", "unknown")
        with _db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, game_id, mode, created_at, player_type) "
                "VALUES (?, ?, 'stream', ?, 'agent')",
                (session_id, game_id, time.time()),
            )

    # Process all events
    count = 0
    for event in events:
        try:
            _process_event(session_id, event)
            count += 1
        except Exception as e:
            log.warning("Upload: error processing event %s for %s: %s", event.get("event"), session_id, e)

    return {
        "session_id": session_id,
        "url": f"/#obs?session={session_id}",
        "events_ingested": count,
    }
