"""Authentication and bot protection routes.

PHASE 10: Modularization framework in place.
Route handlers will be extracted from server/app.py in Phase 10+.

ROUTES PLANNED:
- POST /api/turnstile/verify - Verify Turnstile token
- POST /api/auth/magic-link - Send magic link email
- GET /api/auth/verify - Verify magic link code  
- GET /api/auth/status - Get current user status
- POST /api/auth/logout - Logout
- GET /api/auth/google - Google OAuth redirect
- GET /api/auth/google/callback - Google OAuth callback
- POST /api/auth/claim-sessions - Claim anonymous sessions
- POST /api/copilot/auth/start - Copilot auth start
- POST /api/copilot/auth/poll - Copilot auth poll
- GET /api/copilot/auth/status - Copilot auth status
- GET /api/claude/auth/status - Claude auth status
- POST /api/claude/auth/set-key - Set Claude API key
- GET /api/openai/auth/status - OpenAI auth status
- POST /api/openai/auth/set-key - Set OpenAI API key

STATUS: Routes currently served by app.py; blueprints registered for future extraction.
"""

from flask import Blueprint

# Blueprint registration (handlers imported from app.py for now)
auth_bp = Blueprint('auth', __name__)

# TODO: Extract auth route handlers from server/app.py and register them here
# Blocked by: Circular import risk (auth routes depend on app-level helpers)
# Solution: Resolve in Phase 11 (move helpers to shared module, then extract)

__all__ = ['auth_bp']
