"""Session management route handlers (Phase 8 placeholder).

ROUTES (currently in server/app.py lines 1366-1770 + 2094-2312):
- POST /api/sessions/import → import_session()
- POST /api/sessions/resume → resume_session()
- POST /api/sessions/<session_id>/event → log_session_event()
- GET /api/sessions/<session_id>/obs-events → session_obs_events()
- GET /api/sessions/browse → browse_sessions()
- POST /api/sessions/branch → branch_session()
- GET /api/sessions → list_sessions()
- GET /api/sessions/<session_id> → get_session()
- GET /api/sessions/<session_id>/step/<step_num> → get_session_step()
- GET /api/sessions/<session_id>/calls → session_calls()
- GET /share → share_session()
- GET /share/<session_id> → share_session()
- GET /api/sessions/public → list_public_sessions()

DEPENDENCIES:
- Shared state: game_sessions, session_grids, session_lock
- DB: _db_insert_session, _db_update_session, _get_session_calls, etc.
- Decorators: @bot_protection

TODO (Phase 9+):
- Extract shared state to server/state.py
- Move handlers to this file
- Create Flask Blueprint: session_bp = Blueprint('session', __name__)
- Register routes on blueprint
- Import and register in server/app.py

STATUS: Phase 8 preserves all routes in app.py for stability.
"""
