"""Game play routes.

PHASE 10: Modularization framework in place.

ROUTES PLANNED:
- GET /api/games - List available games
- GET /api/games/<game_id>/source - Get game source/rules
- POST /api/start - Start a new game session
- POST /api/step - Advance game by one action
- POST /api/reset - Reset game to initial state
- POST /api/undo - Undo last action
- POST /api/dev/jump-level - Dev: jump to specific level
- POST /api/llm/lmstudio-proxy - Local LLM via LMStudio
- POST /api/llm/cf-proxy - Cloudflare Workers AI proxy
- GET /api/llm/models - Model registry

STATUS: Routes currently served by app.py; blueprints registered for future extraction.
"""

from flask import Blueprint

# Blueprint registration
game_bp = Blueprint('game', __name__)

# TODO: Extract game route handlers from server/app.py and register them here
# Routes moved to blueprint in Phase 10: game play, LLM proxies, model registry
# Blocked by: Session state coupling (game_sessions, session_lock)
# Solution: Extract shared session_state module in Phase 9, then extract routes

__all__ = ['game_bp']
