# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: In-memory session state dictionaries and DB-backed session recovery
#   for ARC-AGI-3. Manages game_sessions, session_grids, session_snapshots,
#   session_api_mode, session_api_keys, session_step_counts, session_last_llm.
#   Provides _reconstruct_session (replay actions on fresh env) and
#   _try_recover_session (recover from DB). get_arcade and env_state_dict passed
#   as callables to avoid circular imports with server.py.
#   Extracted from server.py in Phase 2d. Depends on db.py and arcengine.
# SRP/DRY check: Pass — all session state and recovery logic consolidated here
"""In-memory session state and DB-backed session recovery for ARC-AGI-3.

Extracted from server.py (Phase 2d).

Circular import note: get_arcade and env_state_dict are passed as callable
parameters to avoid server.py → session_manager.py → server.py cycle.
Use stdlib logging instead of app.logger.
"""

import json
import logging
import threading
from typing import Any

from arcengine import GameAction

from db import _get_db

log = logging.getLogger(__name__)

# ── In-memory session state ────────────────────────────────────────────────

game_sessions: dict[str, Any] = {}
session_grids: dict[str, list[list[int]]] = {}
session_snapshots: dict[str, list[dict]] = {}
session_api_mode: dict[str, str] = {}
session_api_keys: dict[str, str] = {}
session_lock = threading.Lock()
session_step_counts: dict[str, int] = {}
session_last_llm: dict[str, dict] = {}


def _reconstruct_session(game_id: str, actions: list[dict],
                          capture_per_step: bool = False,
                          *, get_arcade_fn, env_state_dict_fn):
    """Replay a list of {action, data} dicts on a fresh env. Returns (env, state_dict)."""
    bare_id = game_id.split("-")[0]
    arc = get_arcade_fn()
    env = arc.make(bare_id)
    state = env_state_dict_fn(env)
    per_step_states = [] if capture_per_step else None
    for act in actions:
        action = GameAction.from_id(int(act["action"]))
        data = act.get("data") or None
        if isinstance(data, str):
            data = json.loads(data)
        frame_data = env.step(action, data=data if data else None)
        if frame_data is not None:
            state = env_state_dict_fn(env, frame_data)
        if capture_per_step:
            per_step_states.append({
                "state": state.get("state", "NOT_FINISHED"),
                "levels_completed": state.get("levels_completed", 0),
            })
    if capture_per_step:
        return env, state, per_step_states
    return env, state


def _try_recover_session(session_id: str, *, get_arcade_fn, env_state_dict_fn):
    """Try to recover a session from DB by replaying its actions.
    Returns (env, state) or (None, None)."""
    try:
        conn = _get_db()
        sess = conn.execute(
            "SELECT game_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not sess:
            conn.close()
            return None, None
        rows = conn.execute(
            "SELECT action, row, col FROM session_actions WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()

        if not rows:
            bare_id = sess["game_id"].split("-")[0]
            arc = get_arcade_fn()
            env = arc.make(bare_id)
            state = env_state_dict_fn(env)
            with session_lock:
                game_sessions[session_id] = env
                session_grids[session_id] = state.get("grid", [])
                session_snapshots[session_id] = []
                session_step_counts[session_id] = 0
            log.info(f"Recovered session {session_id} (0 actions)")
            return env, state

        actions = []
        for r in rows:
            act = {"action": r["action"]}
            if r["row"] is not None and r["col"] is not None:
                act["data"] = json.dumps({"x": r["col"], "y": r["row"]})
            else:
                act["data"] = None
            actions.append(act)

        env, state = _reconstruct_session(
            sess["game_id"], actions,
            get_arcade_fn=get_arcade_fn,
            env_state_dict_fn=env_state_dict_fn,
        )
        with session_lock:
            game_sessions[session_id] = env
            session_grids[session_id] = state.get("grid", [])
            session_snapshots[session_id] = []
            session_step_counts[session_id] = len(actions)
        log.info(f"Recovered session {session_id} ({len(actions)} actions replayed)")
        return env, state
    except Exception as e:
        log.warning(f"Session recovery failed for {session_id}: {e}")
        return None, None
