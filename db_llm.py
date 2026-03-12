"""LLM call logging and retrieval."""
import logging
import time
from db import _get_db

log = logging.getLogger(__name__)


def _log_llm_call(session_id: str, agent_type: str, model: str, *,
                   agent_id: str | None = None,
                   step_num: int | None = None,
                   turn_num: int | None = None,
                   parent_call_id: int | None = None,
                   input_json: str | None = None,
                   input_tokens: int = 0,
                   output_json: str | None = None,
                   output_tokens: int = 0,
                   thinking_tokens: int = 0,
                   thinking_json: str | None = None,
                   cost: float = 0,
                   duration_ms: int = 0,
                   error: str | None = None) -> int | None:
    """Insert an LLM call log row. Returns call_id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO llm_calls "
            "(session_id, agent_type, agent_id, step_num, turn_num, parent_call_id, model, "
            " input_json, input_tokens, output_json, output_tokens, "
            " thinking_tokens, thinking_json, "
            " cost, duration_ms, error, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, agent_type, agent_id,
                step_num, turn_num, parent_call_id, model,
                input_json, input_tokens, output_json, output_tokens,
                thinking_tokens, thinking_json,
                cost, duration_ms, error, time.time(),
            ),
        )
        call_id = cur.lastrowid
        conn.commit()
        conn.close()
        return call_id
    except Exception as e:
        log.warning(f"_log_llm_call failed: {e}")
        return None


def _get_session_calls(session_id: str) -> list[dict]:
    """Return all llm_calls for a session, ordered by timestamp."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_calls failed: {e}")
        return []
