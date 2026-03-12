"""Session export/import to self-contained per-session directories."""
import json
import logging
import sqlite3
from pathlib import Path
from db import _get_db, _DATA_DIR

log = logging.getLogger(__name__)

SESSIONS_DIR = _DATA_DIR / "sessions"


def _export_session_to_file(session_id: str) -> Path | None:
    """Export a session from the central DB into a self-contained per-session directory.

    Creates data/sessions/{session_id}/session.db (full SQLite copy) and
    data/sessions/{session_id}/meta.json (lightweight index).
    Idempotent — re-export overwrites existing files.
    Returns the directory path, or None on failure.
    """
    try:
        conn = _get_db()
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess_row:
            conn.close()
            log.warning(f"_export_session_to_file: session {session_id} not found")
            return None
        sess = dict(sess_row)

        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        tool_execs = [dict(r) for r in conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        conn.close()

        # Create directory
        out_dir = SESSIONS_DIR / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_db_path = out_dir / "session.db"

        # Create self-contained SQLite with new schema
        out_conn = sqlite3.connect(str(out_db_path))
        out_conn.execute("PRAGMA journal_mode=WAL")
        out_conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, game_id TEXT NOT NULL, created_at REAL NOT NULL,
                user_id TEXT, player_type TEXT DEFAULT 'agent', scaffolding_json TEXT,
                model TEXT DEFAULT '', result TEXT DEFAULT 'NOT_FINISHED',
                steps INTEGER DEFAULT 0, levels INTEGER DEFAULT 0,
                steps_per_level_json TEXT, total_cost REAL DEFAULT 0,
                duration_seconds REAL, parent_session_id TEXT, branch_at_step INTEGER,
                mode TEXT DEFAULT 'local'
            );
            CREATE TABLE IF NOT EXISTS session_actions (
                session_id TEXT NOT NULL, step_num INTEGER NOT NULL, action INTEGER NOT NULL,
                row INTEGER, col INTEGER, author_id TEXT, author_type TEXT,
                call_id INTEGER, states_json TEXT, timestamp REAL NOT NULL,
                PRIMARY KEY (session_id, step_num)
            );
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                agent_id TEXT, step_num INTEGER, turn_num INTEGER, parent_call_id INTEGER,
                model TEXT NOT NULL, input_json TEXT, input_tokens INTEGER DEFAULT 0,
                output_json TEXT, output_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0, duration_ms INTEGER DEFAULT 0,
                error TEXT, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_executions (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, call_id INTEGER,
                agent_id TEXT, tool_name TEXT NOT NULL, code TEXT, output TEXT, error TEXT,
                variables_snapshot_json TEXT, is_checkpoint INTEGER DEFAULT 0,
                timestamp REAL NOT NULL
            );
        """)

        # Insert session
        sess_cols = ["id", "game_id", "created_at", "user_id", "player_type", "scaffolding_json",
                     "model", "result", "steps", "levels", "steps_per_level_json",
                     "total_cost", "duration_seconds", "parent_session_id", "branch_at_step", "mode"]
        out_conn.execute(
            f"INSERT OR REPLACE INTO sessions ({','.join(sess_cols)}) VALUES ({','.join('?' for _ in sess_cols)})",
            tuple(sess.get(c) for c in sess_cols),
        )

        # Insert actions
        action_cols = ["session_id", "step_num", "action", "row", "col",
                       "author_id", "author_type", "call_id", "states_json", "timestamp"]
        for a in actions:
            out_conn.execute(
                f"INSERT OR REPLACE INTO session_actions ({','.join(action_cols)}) VALUES ({','.join('?' for _ in action_cols)})",
                tuple(a.get(c) for c in action_cols),
            )

        # Insert calls
        call_cols = ["id", "session_id", "agent_type", "agent_id", "step_num", "turn_num",
                     "parent_call_id", "model", "input_json", "input_tokens",
                     "output_json", "output_tokens", "cost", "duration_ms", "error", "timestamp"]
        for c in calls:
            out_conn.execute(
                f"INSERT OR REPLACE INTO llm_calls ({','.join(call_cols)}) VALUES ({','.join('?' for _ in call_cols)})",
                tuple(c.get(col) for col in call_cols),
            )

        # Insert tool executions
        te_cols = ["id", "session_id", "call_id", "agent_id", "tool_name", "code",
                   "output", "error", "variables_snapshot_json", "is_checkpoint", "timestamp"]
        for t in tool_execs:
            out_conn.execute(
                f"INSERT OR REPLACE INTO tool_executions ({','.join(te_cols)}) VALUES ({','.join('?' for _ in te_cols)})",
                tuple(t.get(col) for col in te_cols),
            )

        out_conn.commit()
        out_conn.close()

        # Write meta.json
        total_cost = sess.get("total_cost", 0) or 0
        meta = {
            "id": session_id,
            "game_id": sess.get("game_id", ""),
            "model": sess.get("model", ""),
            "result": sess.get("result", "NOT_FINISHED"),
            "steps": sess.get("steps", 0),
            "levels": sess.get("levels", 0),
            "total_cost": round(total_cost, 4),
            "created_at": sess.get("created_at", 0),
            "calls": len(calls),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta))

        log.info(f"Exported session {session_id} to {out_dir}")
        return out_dir
    except Exception as e:
        log.exception("Error in _export_session_to_file (session_id=%s): %s", session_id, str(e), extra={"operation": "_export_session_to_file", "session_id": session_id, "error_type": type(e).__name__})
        return None


def _read_session_from_file(session_id: str) -> dict | None:
    """Read a session from its per-session file directory.

    Returns {"session": {...}, "actions": [...], "calls": [...], "tool_executions": [...]}
    or None if the directory doesn't exist.
    """
    session_dir = SESSIONS_DIR / session_id
    db_path = session_dir / "session.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess_row:
            conn.close()
            return None
        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        tool_execs = [dict(r) for r in conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        conn.close()
        return {"session": dict(sess_row), "actions": actions, "calls": calls, "tool_executions": tool_execs}
    except Exception as e:
        log.exception("Error in _read_session_from_file (session_id=%s): %s", session_id, str(e), extra={"operation": "_read_session_from_file", "session_id": session_id, "error_type": type(e).__name__})
        return None


def _list_file_sessions() -> list[dict]:
    """Scan data/sessions/*/meta.json and return list of metadata dicts, sorted by created_at desc."""
    results = []
    if not SESSIONS_DIR.exists():
        return results
    for meta_path in SESSIONS_DIR.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
            results.append(meta)
        except Exception:
            pass
    results.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return results
