"""Community and social routes.

PHASE 10: Modularization framework.

ROUTES PLANNED (7 routes):
- GET /api/leaderboard - Get global leaderboard
- GET /api/leaderboard/<game_id> - Get game-specific leaderboard
- GET /api/comments/<game_id> - Get comments for a game
- POST /api/comments - Post a new comment
- POST /api/comments/<int:comment_id>/vote - Vote on comment
- GET /api/contributors - Get list of contributors
- GET /api/game-results - Get game results/stats

STATUS: Routes in app.py; blueprints registered for future extraction.
"""

from flask import Blueprint

# Blueprint registration
social_bp = Blueprint('social', __name__)

# TODO: Extract social route handlers in Phase 10
# Relatively independent; main dependency is db module for comments/leaderboard
# Blocked by: Database coupling, session data dependencies
# Solution: Phase 10 extraction

__all__ = ['social_bp']
