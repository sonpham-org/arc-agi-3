"""Tool execution logging and retrieval."""
import json
import logging
import time
from db import _get_db

log = logging.getLogger(__name__)


def _log_tool_execution(session_id: str, tool_name: str, *,
                         call_id: int | None = None,
                         agent_id: str | None = None,
                         code: str | None = None,
                         output: str | None = None,
                         error: str | None = None,
                         variables_snapshot: dict | None = None,
                         is_checkpoint: bool = False) -> int | None:
    """Insert a tool execution record. Returns id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO tool_executions "
            "(session_id, call_id, agent_id, tool_name, code, output, error, "
            " variables_snapshot_json, is_checkpoint, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, call_id, agent_id, tool_name,
                code, output, error,
                json.dumps(variables_snapshot) if variables_snapshot else None,
                int(is_checkpoint), time.time(),
            ),
        )
        exec_id = cur.lastrowid
        conn.commit()
        conn.close()
        return exec_id
    except Exception as e:
        log.warning(f"_log_tool_execution failed: {e}")
        return None


def _get_session_tool_executions(session_id: str) -> list[dict]:
    """Return all tool_executions for a session, ordered by id."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_tool_executions failed: {e}")
        return []
