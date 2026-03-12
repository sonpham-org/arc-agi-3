"""ARC-AGI-3 Web Player server package.

Phase 8 Status: Modularization framework in place.

STRUCTURE:
- server/app.py: Main Flask application (2566 lines)
  - Flask app initialization and configuration
  - All 57 route handlers and decorators
  - Shared state: _auth_cache, arcade_instance, _custom_system_prompt, _custom_hard_memory
  - Helper functions: get_mode(), feature_enabled(), get_current_user(), get_arcade(), etc.
  - Middleware: @app.after_request cache headers

ROUTE ORGANIZATION (by concern):
All currently in server/app.py; planned extraction documented in:
- server/game_routes.py → /api/start, /api/step, /api/reset, /api/undo, /api/dev/jump-level, /api/games
- server/auth_routes.py → /api/auth/*, /api/copilot/auth/*, /api/claude/auth/*, /api/openai/auth/*
- server/session_routes.py → /api/sessions/*, /share/*
- server/social_routes.py → /api/leaderboard*, /api/comments*, /api/contributors, /api/game-results
- server/llm_admin_routes.py → /api/llm/*, /api/config/*, /api/memory, /api/batch/*, /draw*, /api/turnstile/*

INDEX & STATIC:
- GET / → index() [render index.html with features, prompts, auth status]
- GET /games/ab → game_ab() [render ab01.html]

TOTAL ROUTES: 57 @app.route decorators

KNOWN COUPLING:
1. Session operations (game_sessions, session_lock, session_grids) are heavily coupled
   - Across: game routes, session routes, some batch operations
   - Solution: Extract to shared session_state module in Phase 9

2. Auth cache (_auth_cache) accessed in:
   - auth_logout() (clearing token)
   - get_current_user() (lookup/cache)
   - Solution: Keep in shared auth_state or move to db module

3. Custom prompts (_custom_system_prompt, _custom_hard_memory) in:
   - memory_endpoint() (read/write)
   - Agent batch runner (read)
   - Solution: Move to shared memory_state module

ENTRY POINT:
```python
if __name__ == "__main__":
    # See bottom of server/app.py for dual-port setup (5000 staging, 5001 prod)
    from server.app import app
    app.run(...)
```

Can be run as:
  python -m server.app
  python server/app.py

TESTING:
```bash
cd /Users/macmini/Documents/GitHub/sonpham-arc3
source venv/bin/activate
python -c "from server.app import app; print('✓ Server imports OK'); app.config['TESTING'] = True; print(f'✓ {len(app.url_map._rules)} routes registered')"
```

NEXT PHASES:
Phase 9: Extract shared state modules
- server/state.py: arcade_instance, app globals
- server/auth_state.py: _auth_cache, _AUTH_CACHE_TTL
- server/memory_state.py: _custom_system_prompt, _custom_hard_memory
- server/session_state.py: game_sessions, session_grids, session_snapshots, locks

Phase 10: Create Blueprint modules and extract routes
- Convert each route group to Flask Blueprint
- Move handlers to respective *_routes.py files
- Register blueprints in app.py create_app() function
- Verify all 57 routes still accessible with same URLs

Phase 11: Client-side modularization (session.js → 4 modules)
- session-storage.js (localStorage ops)
- session-replay.js (replay/scrubbing UI)
- session-persistence.js (upload/sharing)
- session-views.js (routing/menus)
"""

from server.app import app

# Re-exports for backward compatibility with tests
# These functions are imported from prompt_builder into app.py
try:
    from server.app import _extract_json, _parse_llm_response
except ImportError:
    from prompt_builder import _extract_json, _parse_llm_response

__all__ = ['app', '_extract_json', '_parse_llm_response']
