"""Authentication route handlers (Phase 8 placeholder).

ROUTES (currently in server/app.py lines 426-605 + 1185-1313):
- POST /api/auth/magic-link → auth_magic_link()
- GET /api/auth/verify → auth_verify()
- GET /api/auth/status → auth_status()
- POST /api/auth/logout → auth_logout()
- GET /api/auth/google → auth_google_redirect()
- GET /api/auth/google/callback → auth_google_callback()
- POST /api/auth/claim-sessions → auth_claim_sessions()
- POST /api/copilot/auth/start → copilot_auth_start()
- POST /api/copilot/auth/poll → copilot_auth_poll()
- GET /api/copilot/auth/status → copilot_auth_status()
- GET /api/claude/auth/status → claude_auth_status()
- POST /api/claude/auth/set-key → claude_set_key()
- GET /api/openai/auth/status → openai_auth_status()
- POST /api/openai/auth/set-key → openai_set_key()

DEPENDENCIES:
- Shared state: _auth_cache, _auth_cache_ttl
- Helpers: get_current_user(), get_mode()
- DB: find_or_create_user(), create_auth_token(), verify_auth_token(), etc.
- Decorators: @bot_protection

TODO (Phase 9+):
- Extract shared state to server/state.py
- Move handlers to this file
- Create Flask Blueprint: auth_bp = Blueprint('auth', __name__)
- Register routes on blueprint
- Import and register in server/app.py

STATUS: Phase 8 preserves all routes in app.py for stability.
"""
