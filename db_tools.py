"""Tool execution logging and retrieval."""
# Author: Claude Opus 4.6
# Date: 2026-03-15 00:00
# PURPOSE: Tool execution persistence — insert and query tool_executions table.
#   Uses _db() context manager for safe connection handling.
# SRP/DRY check: Pass — thin DB operations only
import json
import logging
import time
from db import _db

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
        with _db() as conn:
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
            return cur.lastrowid
    except Exception as e:
        log.warning(f"_log_tool_execution failed: {e}")
        return None


def _get_session_tool_executions(session_id: str) -> list[dict]:
    """Return all tool_executions for a session, ordered by id."""
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_tool_executions failed: {e}")
        return []
