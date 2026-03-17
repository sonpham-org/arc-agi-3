"""Session CRUD operations."""
# Author: Claude Opus 4.6
# Date: 2026-03-15 00:00
# PURPOSE: Session CRUD — insert/update sessions and actions in SQLite.
#   Uses _db() context manager for safe connection handling.
# SRP/DRY check: Pass — thin DB operations, no business logic
import json
import logging
import time
from db import _get_db, _db
from exceptions import handle_errors

log = logging.getLogger(__name__)

# Whitelist of columns allowed in _db_update_session to prevent SQL injection
_ALLOWED_SESSION_COLUMNS = frozenset({
    "result", "levels", "total_cost", "duration_seconds", "steps",
    "scaffolding_json", "model", "player_type", "steps_per_level_json",
    "live_mode", "live_fps", "game_version", "user_id", "mode",
    "parent_session_id", "branch_at_step",
})


@handle_errors("_db_insert_session", reraise=False, default=None)
def _db_insert_session(session_id: str, game_id: str, mode: str, user_id: str | None = None):
    """Insert a new session record."""
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, game_id, mode, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, game_id, mode, time.time(), user_id),
        )


@handle_errors("_db_insert_action", reraise=False, default=None)
def _db_insert_action(session_id: str, step_num: int, action: int,
                      states: list | None = None, *,
                      row: int | None = None, col: int | None = None,
                      author_id: str | None = None,
                      author_type: str | None = None,
                      call_id: int | None = None):
    """Insert a game action record."""
    with _db() as conn:
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


@handle_errors("_db_update_session", reraise=False, default=None)
def _db_update_session(session_id: str, **kwargs):
    """Update session fields. Only whitelisted column names are allowed."""
    bad_cols = set(kwargs) - _ALLOWED_SESSION_COLUMNS
    if bad_cols:
        raise ValueError(f"Disallowed session columns: {bad_cols}")
    with _db() as conn:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?",
                     (*kwargs.values(), session_id))
