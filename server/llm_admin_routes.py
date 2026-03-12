"""LLM, admin, and configuration routes.

PHASE 10: Modularization framework.

ROUTES PLANNED (11 routes):
- GET /api/llm/models - Model registry (moved from game_routes)
- GET /api/config/mode - Get current mode (staging/prod)
- POST /api/config/apikey - Configure API key
- GET /api/memory - Get custom prompts/memory
- POST /api/memory - Set custom prompts/memory
- GET /draw - Draw environment editor UI
- GET /api/draw/scene/<int:level> - Get draw scene
- POST /api/draw/save - Save draw scene
- POST /api/draw/save_diffs - Save draw diffs
- POST /api/draw/reset - Reset draw environment
- POST /api/batch/start - Start batch job
- GET /api/batch/<batch_id> - Get batch status

STATUS: Routes in app.py; blueprints registered for future extraction.
"""

from flask import Blueprint

# Blueprint registration
llm_admin_bp = Blueprint('llm_admin', __name__)

# TODO: Extract LLM/admin route handlers in Phase 10
# Includes: config, memory management, draw environment, batch processing
# Blocked by: Dependencies on module-level state (_custom_system_prompt, _custom_hard_memory)
# Solution: Extract state vars to server/state.py (Phase 10), then extract routes

__all__ = ['llm_admin_bp']
