"""Standalone observability server for batch_runner.py.

Lightweight Flask app with only obs-related endpoints.
Does NOT import server.py.
"""

import json
import sqlite3
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from arcengine import GameAction
from db import _get_db, _decompress_grid, _list_file_sessions, _read_session_from_file

app = Flask(__name__)

_OBS_DIR = Path(".agent_obs")
_DATA_DIR = Path(__file__).parent / "data"


def _find_session_db(session_id: str) -> sqlite3.Connection | None:
    """Search all timestamped session DBs for a session_id. Returns open connection or None."""
    for db_path in sorted(_DATA_DIR.glob("sessions_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        if db_path.stat().st_size == 0:
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT id FROM sessions WHERE id = ? LIMIT 1", (session_id,)).fetchone()
            if row:
                return conn
            conn.close()
        except Exception:
            pass
    return None


@app.route("/obs")
def obs_dashboard():
    return render_template("obs.html")


@app.route("/api/obs/status")
def obs_status():
    status_path = _OBS_DIR / "status.json"
    if not status_path.exists():
        return jsonify({"error": "No active agent run"}), 404
    try:
        return Response(status_path.read_text(), mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/obs/grid")
def obs_grid():
    grid_path = _OBS_DIR / "grid.json"
    if not grid_path.exists():
        return jsonify({"error": "No grid data"}), 404
    try:
        return Response(grid_path.read_text(), mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/obs/events")
def obs_events():
    events_path = _OBS_DIR / "events.jsonl"
    if not events_path.exists():
        return jsonify([])

    since = int(request.args.get("since", 0))
    try:
        lines = events_path.read_text().splitlines()
        if since > len(lines):
            since = 0
        new_lines = lines[since:]
        events = []
        for line in new_lines:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return jsonify({"events": events, "next_offset": len(lines)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/list-for-obs")
def list_sessions_for_obs():
    try:
        seen = set()
        sessions = []

        # Central DB
        try:
            conn = _get_db()
            rows = conn.execute(
                """SELECT s.id, s.game_id, s.model, s.created_at, s.result, s.steps, s.levels, s.total_cost
                   FROM sessions s
                   WHERE s.steps > 0
                   ORDER BY s.created_at DESC
                   LIMIT 200"""
            ).fetchall()
            conn.close()
            for r in rows:
                d = dict(r)
                seen.add(d["id"])
                sessions.append(d)
        except Exception:
            pass

        # Timestamped batch DBs
        for db_path in sorted(_DATA_DIR.glob("sessions_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
            if db_path.stat().st_size == 0:
                continue
            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT id, game_id, model, created_at, result, steps, levels, total_cost
                       FROM sessions WHERE steps > 0
                       ORDER BY created_at DESC LIMIT 200"""
                ).fetchall()
                conn.close()
                for r in rows:
                    d = dict(r)
                    if d["id"] not in seen:
                        seen.add(d["id"])
                        sessions.append(d)
            except Exception:
                pass

        sessions.sort(key=lambda s: s.get("created_at") or 0, reverse=True)
        return jsonify({"sessions": sessions[:200]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/obs-events")
def get_session_obs_events(session_id):
    try:
        conn = _get_db()
        stored = conn.execute(
            "SELECT event_json FROM obs_events WHERE session_id = ? ORDER BY event_idx",
            (session_id,),
        ).fetchall()
        if stored:
            # Enrich events with grid snapshots from session_steps
            grid_rows = conn.execute(
                "SELECT step_num, grid_snapshot FROM session_steps "
                "WHERE session_id = ? AND grid_snapshot IS NOT NULL ORDER BY step_num",
                (session_id,),
            ).fetchall()
            conn.close()
            step_grids = {}
            for gr in grid_rows:
                try:
                    step_grids[gr["step_num"]] = _decompress_grid(gr["grid_snapshot"])
                except Exception:
                    pass
            events = []
            for r in stored:
                ev = json.loads(r["event_json"])
                if not ev.get("grid") and ev.get("step_num") is not None:
                    grid = step_grids.get(ev["step_num"])
                    if grid:
                        ev["grid"] = grid
                events.append(ev)
            return jsonify({"events": events})

        calls = conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        steps = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()

        # Fallback: search timestamped batch DBs if central DB has no data
        if not calls and not steps:
            alt_conn = _find_session_db(session_id)
            if alt_conn:
                calls = alt_conn.execute(
                    "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY timestamp",
                    (session_id,),
                ).fetchall()
                steps = alt_conn.execute(
                    "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                    (session_id,),
                ).fetchall()
                alt_conn.close()

        raw_events = []
        for c in calls:
            c = dict(c)
            raw_events.append({
                "ts": c.get("timestamp", 0),
                "agent": c.get("call_type", "planner"),
                "event": "llm_call",
                "model": c.get("model", ""),
                "input_tokens": c.get("input_tokens", 0),
                "output_tokens": c.get("output_tokens", 0),
                "cost": c.get("cost", 0),
                "duration_ms": c.get("duration_ms", 0),
                "step_num": c.get("step_num"),
                "turn_num": c.get("turn_num"),
                "thinking_level": c.get("thinking_level"),
                "response": c.get("response_preview", ""),
                "prompt_preview": c.get("prompt_preview", ""),
            })
        for s in steps:
            s = dict(s)
            grid = None
            if s.get("grid_snapshot"):
                try:
                    grid = _decompress_grid(s["grid_snapshot"])
                except Exception:
                    pass
            action_id = s.get("action", 0)
            try:
                action_name = GameAction.from_id(int(action_id)).name
            except Exception:
                action_name = str(action_id)
            data = {}
            if s.get("data_json"):
                try:
                    data = json.loads(s["data_json"]) if isinstance(s["data_json"], str) else s["data_json"]
                except Exception:
                    pass
            if data and "x" in data and "y" in data:
                action_name = f"{action_name}@({data['x']},{data['y']})"
            raw_events.append({
                "ts": s.get("timestamp", 0),
                "agent": "executor",
                "event": "act",
                "action": action_name,
                "step_num": s.get("step_num", 0),
                "grid": grid,
            })

        raw_events.sort(key=lambda e: e.get("ts", 0))
        t0 = raw_events[0]["ts"] if raw_events else 0
        events = []
        for ev in raw_events:
            ts = ev.pop("ts", 0)
            ev["t"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            ev["elapsed_s"] = round(ts - t0, 2)
            events.append(ev)

        return jsonify({"events": events})
    except Exception as e:
        app.logger.warning(f"get_session_obs_events failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/browse")
def browse_sessions():
    """List sessions from per-session file exports (meta.json)."""
    try:
        sessions = _list_file_sessions()
        return jsonify({"sessions": sessions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/full")
def get_session_full(session_id):
    """Get full session data from per-session file export."""
    try:
        data = _read_session_from_file(session_id)
        if not data:
            return jsonify({"error": "Session not found"}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>")
def get_session(session_id):
    try:
        conn = _get_db()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"session": dict(row)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/live/")
def live_dashboard():
    return render_template("obs.html")


@app.route("/share/<session_id>")
def share_session(session_id):
    return render_template("obs.html", share_session_id=session_id)


def start_obs_server() -> int:
    """Start obs server on a random available port in a daemon thread. Returns the port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    from werkzeug.serving import make_server
    server = make_server("0.0.0.0", port, app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return port
