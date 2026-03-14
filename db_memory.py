"""Agent memory snapshot persistence — per-step memory state for inspection.

NOTE: Uses deferred import of _get_db to avoid circular import with db.py.
"""
import json
import logging
import time

log = logging.getLogger(__name__)


def _get_conn():
    """Get DB connection (deferred import to avoid circular import with db.py)."""
    from db import _get_db
    return _get_db()


def save_memory_snapshot(session_id: str, step_num: int, memory: dict, *,
                         agent_type: str = "orchestrator",
                         agent_id: str | None = None) -> int | None:
    """Save an agent memory snapshot at a given step. Returns id or None."""
    try:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO agent_memory_snapshots "
            "(session_id, step_num, agent_type, agent_id, memory_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, step_num, agent_type, agent_id,
             json.dumps(memory), time.time()),
        )
        snap_id = cur.lastrowid
        conn.commit()
        conn.close()
        return snap_id
    except Exception as e:
        log.warning(f"save_memory_snapshot failed: {e}")
        return None


def get_session_memory_snapshots(session_id: str) -> list[dict]:
    """Return all memory snapshots for a session, ordered by step_num."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_memory_snapshots WHERE session_id = ? ORDER BY step_num, id",
            (session_id,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("memory_json"):
                try:
                    d["memory"] = json.loads(d["memory_json"])
                except Exception:
                    d["memory"] = {}
                del d["memory_json"]
            result.append(d)
        return result
    except Exception as e:
        log.warning(f"get_session_memory_snapshots failed: {e}")
        return []


def get_memory_at_step(session_id: str, step_num: int) -> list[dict]:
    """Return memory snapshots at a specific step."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_memory_snapshots WHERE session_id = ? AND step_num = ? ORDER BY id",
            (session_id, step_num),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("memory_json"):
                try:
                    d["memory"] = json.loads(d["memory_json"])
                except Exception:
                    d["memory"] = {}
                del d["memory_json"]
            result.append(d)
        return result
    except Exception as e:
        log.warning(f"get_memory_at_step failed: {e}")
        return []


def bulk_save_memory_snapshots(session_id: str, snapshots: list[dict]) -> int:
    """Bulk-insert memory snapshots. Returns count inserted."""
    if not snapshots:
        return 0
    try:
        conn = _get_conn()
        # Clear existing snapshots for this session first
        conn.execute("DELETE FROM agent_memory_snapshots WHERE session_id = ?", (session_id,))
        count = 0
        for snap in snapshots:
            conn.execute(
                "INSERT INTO agent_memory_snapshots "
                "(session_id, step_num, agent_type, agent_id, memory_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, snap.get("step_num", 0),
                 snap.get("agent_type", "orchestrator"),
                 snap.get("agent_id"),
                 json.dumps(snap.get("memory", {})),
                 snap.get("timestamp", time.time())),
            )
            count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        log.warning(f"bulk_save_memory_snapshots failed: {e}")
        return 0
