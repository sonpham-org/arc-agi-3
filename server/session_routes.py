"""Session management routes.

PHASE 10: Modularization framework.

ROUTES PLANNED (12 routes):
- POST /api/sessions/import - Import session from JSON
- POST /api/sessions/resume - Resume a saved session
- POST /api/sessions/<session_id>/event - Log session event
- POST /api/sessions/<session_id>/obs-events - Observable events stream
- GET /api/sessions/browse - List user's sessions
- POST /api/sessions/branch - Create branch from session
- GET /api/sessions - List all sessions (paginated)
- GET /api/sessions/<session_id> - Get session details
- GET /api/sessions/<session_id>/step/<int:step_num> - Get specific step
- GET /api/sessions/<session_id>/calls - Get LLM calls for session
- GET /share/<session_id> - Render share page
- GET /api/sessions/public - List public sessions

STATUS: Routes in app.py; blueprints registered for future extraction.
"""

from flask import Blueprint

# Blueprint registration
session_bp = Blueprint('session', __name__)

# TODO: Extract session route handlers in Phase 10
# Most tightly coupled to session_manager module
# Blocked by: Heavy dependencies on session_lock, session_grids, _db_* functions
# Solution: Phase 10 full implementation

__all__ = ['session_bp']
