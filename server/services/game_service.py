"""Game service layer — Game initialization and step validation.

Validation and orchestration for game operations.
Pure business logic — no Flask request/response objects.

Note: Arcade game engine operations and session in-memory state
coordination remain in app.py. This module provides helpers.
"""

import copy
import logging
import time
from arcengine import GameAction

log = logging.getLogger(__name__)


def validate_action_id(action_id) -> tuple[bool, str]:
    """Validate action_id is a valid integer. Returns (is_valid, error_msg)."""
    if action_id is None:
        return False, "action required"
    try:
        int(action_id)
        return True, ""
    except (ValueError, TypeError):
        return False, f"Invalid action: {action_id}"


def validate_game_id(game_id: str) -> tuple[bool, str]:
    """Validate game_id is present. Returns (is_valid, error_msg)."""
    if not game_id:
        return False, "game_id required"
    return True, ""


def validate_session_id(session_id: str) -> tuple[bool, str]:
    """Validate session_id is present. Returns (is_valid, error_msg)."""
    if not session_id:
        return False, "session_id required"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════
# GAME INITIALIZATION — start_game()
# ═══════════════════════════════════════════════════════════════════════════

def start(data: dict, get_arcade_fn=None, env_state_dict_fn=None, 
          session_lock=None, game_sessions=None, session_grids=None,
          session_snapshots=None, session_step_counts=None,
          feature_enabled_fn=None, _db_insert_session_fn=None, 
          get_current_user_fn=None, get_mode_fn=None,
          _cleanup_tool_session_fn=None) -> tuple[dict, int]:
    """Initialize a new game session.
    
    Returns:
        (response_dict, status_code)
        - response_dict: state with session_id, grid, etc.
        - status_code: 200 on success, 400 on error
    """
    game_id = data.get("game_id")
    is_valid, error_msg = validate_game_id(game_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    if not get_arcade_fn or not env_state_dict_fn or not session_lock:
        return {"error": "Service initialization incomplete"}, 500
    
    # Get bare game ID (strip variant suffix)
    bare_id = game_id.split("-")[0]
    arc = get_arcade_fn()
    
    try:
        env = arc.make(bare_id)
    except Exception as e:
        return {"error": str(e)}, 400
    
    # Generate session ID from env
    session_id = env._guid if hasattr(env, "_guid") else str(id(env))
    state = env_state_dict_fn(env)
    
    # Register in in-memory state
    with session_lock:
        game_sessions[session_id] = env
        session_grids[session_id] = state.get("grid", [])
        session_snapshots[session_id] = []  # reset undo stack
        session_step_counts[session_id] = 0
    
    # Cleanup tool session for LLM providers
    if _cleanup_tool_session_fn:
        _cleanup_tool_session_fn(session_id)
    
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(initial)"}
    
    # Persist to SQLite if enabled
    if feature_enabled_fn and feature_enabled_fn("session_db") and _db_insert_session_fn:
        user = get_current_user_fn() if get_current_user_fn else None
        mode = get_mode_fn() if get_mode_fn else "staging"
        _db_insert_session_fn(
            session_id, game_id, mode,
            user_id=user["id"] if user else None
        )
    
    return state, 200


# ═══════════════════════════════════════════════════════════════════════════
# GAME STEP — step_game()
# ═══════════════════════════════════════════════════════════════════════════

def step(payload: dict, get_arcade_fn=None, env_state_dict_fn=None,
         session_lock=None, game_sessions=None, session_grids=None,
         session_snapshots=None, session_step_counts=None, session_last_llm=None,
         _try_recover_session_fn=None, compute_change_map_fn=None,
         feature_enabled_fn=None, _db_insert_action_fn=None,
         _db_update_session_fn=None, _compress_grid_fn=None) -> tuple[dict, int]:
    """Execute one game action step.
    
    Returns:
        (response_dict, status_code)
        - response_dict: new state with grid, change_map, undo_depth
        - status_code: 200 on success, 400/404/500 on error
    """
    session_id = payload.get("session_id")
    action_id = payload.get("action")
    action_data = payload.get("data", {})
    reasoning = payload.get("reasoning")
    
    is_valid, error_msg = validate_session_id(session_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    is_valid, error_msg = validate_action_id(action_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    # Get or recover session
    with session_lock:
        env = game_sessions.get(session_id)
    
    if env is None and _try_recover_session_fn:
        env, _ = _try_recover_session_fn(session_id, 
                                        get_arcade_fn=get_arcade_fn,
                                        env_state_dict_fn=env_state_dict_fn)
    
    if env is None:
        return {"error": "Session not found"}, 404
    
    # Validate action ID
    try:
        action = GameAction.from_id(int(action_id))
    except ValueError:
        return {"error": f"Invalid action: {action_id}"}, 400
    
    # Save snapshot before step (for undo)
    with session_lock:
        prev_grid = session_grids.get(session_id, [])
        snapshot = {
            "grid": copy.deepcopy(prev_grid),
            "observation_space": copy.deepcopy(env.observation_space) if hasattr(env, "observation_space") else None,
        }
        session_snapshots.setdefault(session_id, []).append(snapshot)
    
    # Execute the step
    frame_data = env.step(action, data=action_data or None, reasoning=reasoning)
    if frame_data is None:
        return {"error": "Step failed"}, 500
    
    # Build response state
    state = env_state_dict_fn(env, frame_data)
    state["session_id"] = session_id
    curr_grid = state.get("grid", [])
    
    if compute_change_map_fn:
        change_map = compute_change_map_fn(prev_grid, curr_grid)
    else:
        change_map = {"changes": [], "change_count": 0, "change_map_text": ""}
    
    state["change_map"] = change_map
    state["undo_depth"] = len(session_snapshots.get(session_id, []))
    
    # Accept client-side LLM response
    client_llm_response = payload.get("llm_response")
    
    # Update in-memory state
    with session_lock:
        session_grids[session_id] = curr_grid
        session_step_counts[session_id] = session_step_counts.get(session_id, 0) + 1
        step_num = session_step_counts[session_id]
        # Pop stashed LLM response or use client-provided
        llm_resp = session_last_llm.pop(session_id, None) if session_last_llm else None
        llm_resp = llm_resp or client_llm_response
    
    # Persist action to DB if enabled
    if feature_enabled_fn and feature_enabled_fn("session_db") and _db_insert_action_fn:
        states = None
        if curr_grid and _compress_grid_fn:
            states = [{"grid": _compress_grid_fn(curr_grid)}]
        
        act_row = action_data.get("y") if action_data else None
        act_col = action_data.get("x") if action_data else None
        
        _db_insert_action_fn(
            session_id, step_num, int(action_id), states,
            row=act_row, col=act_col
        )
        
        if _db_update_session_fn:
            update_kwargs = dict(
                result=state.get("state", "NOT_FINISHED"),
                levels=state.get("levels_completed", 0),
            )
            session_cost = payload.get("session_cost")
            if session_cost is not None:
                update_kwargs["total_cost"] = float(session_cost)
            _db_update_session_fn(session_id, **update_kwargs)
    
    return state, 200


# ═══════════════════════════════════════════════════════════════════════════
# GAME RESET — reset_game()
# ═══════════════════════════════════════════════════════════════════════════

def reset(payload: dict, env_state_dict_fn=None, session_lock=None,
          game_sessions=None, session_grids=None, 
          _try_recover_session_fn=None, get_arcade_fn=None) -> tuple[dict, int]:
    """Reset game to initial state.
    
    Returns:
        (response_dict, status_code)
    """
    session_id = payload.get("session_id")
    is_valid, error_msg = validate_session_id(session_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    # Get or recover session
    with session_lock:
        env = game_sessions.get(session_id)
    
    if env is None and _try_recover_session_fn:
        env, _ = _try_recover_session_fn(session_id,
                                        get_arcade_fn=get_arcade_fn,
                                        env_state_dict_fn=env_state_dict_fn)
    
    if env is None:
        return {"error": "Session not found"}, 404
    
    # Reset the environment
    frame_data = env.reset()
    state = env_state_dict_fn(env, frame_data)
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(reset)"}
    
    # Update in-memory grid
    with session_lock:
        session_grids[session_id] = state.get("grid", [])
    
    return state, 200


# ═══════════════════════════════════════════════════════════════════════════
# UNDO STEP — undo_step()
# ═══════════════════════════════════════════════════════════════════════════

def undo(payload: dict, env_state_dict_fn=None, session_lock=None,
         game_sessions=None, session_grids=None, session_snapshots=None,
         _try_recover_session_fn=None, get_arcade_fn=None,
         feature_enabled_fn=None, db_conn_fn=None) -> tuple[dict, int]:
    """Undo one or more game steps.
    
    Returns:
        (response_dict, status_code)
    """
    session_id = payload.get("session_id")
    is_valid, error_msg = validate_session_id(session_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    # Get or recover session
    with session_lock:
        env = game_sessions.get(session_id)
        snapshots = session_snapshots.get(session_id, [])
    
    if env is None and _try_recover_session_fn:
        env, _ = _try_recover_session_fn(session_id,
                                        get_arcade_fn=get_arcade_fn,
                                        env_state_dict_fn=env_state_dict_fn)
        snapshots = session_snapshots.get(session_id, [])
    
    if env is None:
        return {"error": "Session not found"}, 404
    
    if not snapshots:
        return {"error": "Nothing to undo"}, 400
    
    count = min(int(payload.get("count", 1)), 50)
    
    # Pop snapshots
    with session_lock:
        snapshot = None
        for _ in range(count):
            if not snapshots:
                break
            snapshot = snapshots.pop()
    
    if snapshot is None:
        return {"error": "Nothing to undo"}, 400
    
    restored_grid = snapshot["grid"]
    
    # Update in-memory grid
    with session_lock:
        session_grids[session_id] = restored_grid
    
    # Persist undo to DB if enabled
    if feature_enabled_fn and feature_enabled_fn("session_db") and db_conn_fn:
        try:
            conn = db_conn_fn()
            # Delete undone actions
            result = conn.execute(
                "SELECT MAX(step_num) as max_step FROM session_actions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            current_max = result["max_step"] if result["max_step"] is not None else 0
            cutoff_step = max(0, current_max - count)
            
            # Delete actions after cutoff
            conn.execute(
                "DELETE FROM session_actions WHERE session_id = ? AND step_num > ?",
                (session_id, cutoff_step),
            )
            # Update session steps count
            conn.execute(
                "UPDATE sessions SET steps = ? WHERE id = ?",
                (cutoff_step, session_id),
            )
            conn.commit()
        except Exception as e:
            log.warning(f"Undo DB write failed for {session_id}: {e}")
            # Graceful degradation
    
    # Build response state from snapshot
    state = env_state_dict_fn(env)
    state["grid"] = restored_grid
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(undo)"}
    state["undo_depth"] = len(snapshots)
    
    return state, 200
