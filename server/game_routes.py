"""Game route handlers (Phase 8 placeholder).

ROUTES (currently in server/app.py lines 682-859 + 622-654):
- POST /api/start → start_game()
- POST /api/step → step_game()
- POST /api/reset → reset_game()
- POST /api/dev/jump-level → dev_jump_level()  
- POST /api/undo → undo_step()
- GET /api/games → list_games()
- GET /api/games/<game_id>/source → game_source()

DEPENDENCIES: 
- Shared state: game_sessions, session_grids, session_lock, arcade_instance
- Decorators: @bot_protection, @turnstile_required
- Helpers: get_arcade(), env_state_dict(), frame_to_grid()

TODO (Phase 9+):
- Extract shared state to server/state.py
- Move handlers to this file
- Create Flask Blueprint: game_bp = Blueprint('game', __name__)
- Register routes on blueprint
- Import and register in server/app.py

STATUS: Phase 8 preserves all routes in app.py for stability.
"""
