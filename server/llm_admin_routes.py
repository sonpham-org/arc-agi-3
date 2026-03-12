"""LLM, admin, batch, and draw route handlers (Phase 8 placeholder).

ROUTES (currently in server/app.py):
LLM/Config (lines 859-932, 1118-1338):
- POST /api/llm/lmstudio-proxy → lmstudio_proxy()
- POST /api/llm/cf-proxy → cf_proxy()
- GET /api/llm/models → llm_models()
- GET /api/config/mode → config_mode()
- POST /api/config/mode → config_mode()
- POST /api/config/apikey → config_apikey()
- GET /api/memory → memory_endpoint()
- POST /api/memory → memory_endpoint()

Draw Editor (lines 2317-2401):
- GET /draw → draw_editor()
- GET /api/draw/scene/<level> → get_draw_scene()
- POST /api/draw/save → save_draw_scene()
- POST /api/draw/save_diffs → save_draw_diffs()
- POST /api/draw/reset → reset_draw_scene()

Batch Run Orchestration (lines 2426-2520):
- POST /api/batch/start → batch_start()
- GET /api/batch/<batch_id> → batch_status()

Turnstile (lines 363-391):
- POST /api/turnstile/verify → turnstile_verify()

DEPENDENCIES:
- Shared state: _custom_system_prompt, _custom_hard_memory, arcade_instance
- DB: _log_llm_call(), _get_session_calls(), _read_custom_scenes(), etc.
- LLM providers: _route_model_call(), copilot_auth_lock, llm_providers module
- Decorators: @bot_protection, @turnstile_required

TODO (Phase 9+):
- Extract handlers to this file
- Create Flask Blueprint: llm_bp = Blueprint('llm', __name__)
- Register routes on blueprint
- Import and register in server/app.py

STATUS: Phase 8 preserves all routes in app.py for stability.
These routes have complex dependencies on LLM providers and batch system.
Requires careful handling of async batch execution and model state.
"""
