"""Session CRUD operations."""
import json
import logging
import time
from db import _get_db
from exceptions import handle_errors

log = logging.getLogger(__name__)


@handle_errors("_db_insert_session", reraise=False, default=None)
def _db_insert_session(session_id: str, game_id: str, mode: str, user_id: str | None = None):
    """Insert a new session record."""
    conn = _get_db()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, game_id, mode, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
        (session_id, game_id, mode, time.time(), user_id),
    )
    conn.commit()
    conn.close()


@handle_errors("_db_insert_action", reraise=False, default=None)
def _db_insert_action(session_id: str, step_num: int, action: int,
                      states: list | None = None, *,
                      row: int | None = None, col: int | None = None,
                      author_id: str | None = None,
                      author_type: str | None = None,
                      call_id: int | None = None):
    """Insert a game action record."""
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO session_actions "
        "(session_id, step_num, action, row, col, author_id, author_type, call_id, states_json, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, step_num, action,
            row, col, author_id, author_type, call_id,
            json.dumps(states) if states else None,
            time.time(),
        ),
    )
    conn.execute(
        "UPDATE sessions SET steps = ? WHERE id = ?",
        (step_num, session_id),
    )
    conn.commit()
    conn.close()


@handle_errors("_db_update_session", reraise=False, default=None)
def _db_update_session(session_id: str, **kwargs):
    """Update session fields."""
    conn = _get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?",
                 (*kwargs.values(), session_id))
    conn.commit()
    conn.close()
