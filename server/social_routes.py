"""Social and community route handlers (Phase 8 placeholder).

ROUTES (currently in server/app.py lines 1811-2070):
- GET /api/leaderboard → leaderboard()
- GET /api/leaderboard/<game_id> → leaderboard_detail()
- GET /api/comments/<game_id> → get_comments()
- POST /api/comments → post_comment()
- POST /api/comments/<comment_id>/vote → vote_comment()
- GET /api/contributors → contributors()
- GET /api/game-results → game_results()

DEPENDENCIES:
- DB: session data lookups, comment/leaderboard queries
- Helpers: _format_action_row()
- Decorators: @bot_protection

TODO (Phase 9+):
- Extract handlers to this file
- Create Flask Blueprint: social_bp = Blueprint('social', __name__)
- Register routes on blueprint
- Import and register in server/app.py

STATUS: Phase 8 preserves all routes in app.py for stability.
These routes have minimal shared state coupling (mostly read-only DB queries).
Could be among the first routes extracted in Phase 9.
"""
