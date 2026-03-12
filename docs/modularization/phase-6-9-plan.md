# Phases 6–9 Modularization Plan — sonpham-arc3

> **Status:** Analysis complete; awaiting approval for implementation
> **Author:** Research subagent (2026-03-12)
> **Based on:** Phase 1–5 completion (see phase-5-plan.md)

---

## Executive Summary

Phases 1–5 successfully extracted utilities, rendering, and scaffolding modules. Remaining codebase still has major SRP/DRY violations in six files totaling 11,812 lines:

| File | Lines | Violations |
|------|-------|-----------|
| session.js | 2528 | Mixes localStorage, replay, upload, views, auth → 4 modules |
| server.py | 2566 | 77 routes (games, auth, sessions, batch, social, draw) → 5 blueprints |
| llm.js | 2153 | Remaining after Phase 5: timeline + tokens (acceptable) |
| human.js | 1392 | Game play mixed with comments/feedback (wrong layer) |
| ui.js | 1169 | UI handlers (acceptable, defer) |
| agent.py | 1498 | Duplicates grid utils (grid_analysis.py) + MODELS (models.py) |

---

## Phase 6: Extract Grid Utilities from agent.py → grid_analysis.py

**Target:** Deduplicate grid analysis code
**Time estimate:** 30 minutes
**Complexity:** Small
**Risk:** Very Low

### Current state
`agent.py` lines 328–437 defines:
- `compress_row(row)`
- `compute_change_map(prev_grid, curr_grid)`
- `compute_color_histogram(grid)`
- `compute_region_map(grid)`
- `_compress_change_row(row)` (helper)

These exact functions **already exist in `grid_analysis.py`** (extracted during Phase 1).

Agent.py is NOT importing them; instead maintaining duplicate definitions.

### Extraction steps
1. Delete lines 328–437 from agent.py
2. Add at top of agent.py: `from grid_analysis import compress_row, compute_change_map, compute_color_histogram, compute_region_map`
3. Verify calls in `build_context_block()` (line 826+) now use imported versions
4. Run test: grid analysis calls produce same output before/after

### Rationale
- Eliminates code duplication immediately
- Single source of truth for grid utilities
- agent.py shrinks ~110 lines
- No behavior change; same functions, same signatures

### Precautions
1. Diff agent.py vs grid_analysis.py implementations to confirm they're identical
2. Test `compute_change_map()` with sample grids before/after
3. Verify agent CLI still works: `python3 agent.py --model groq/llama-3.3-70b-versatile --game c59eb873 --max-steps 5`

### Files modified
- `agent.py` (remove duplicate functions, add import)
- `grid_analysis.py` (no changes)

### Commit message
```
chore(phase-6): deduplicate grid utilities — agent.py imports from grid_analysis.py

Removes ~110 lines of duplicated compress_row, compute_change_map, 
compute_color_histogram, compute_region_map from agent.py. These are 
already defined in grid_analysis.py (extracted in Phase 1).

- Remove lines 328–437 from agent.py
- Add import from grid_analysis
- Verify build_context_block() calls use imported versions
- Test: agent CLI still resolves grid utils correctly

No behavior change. Single source of truth for grid analysis.
```

---

## Phase 7: Consolidate MODELS Registry — agent.py → models.py

**Target:** Merge MODELS dict and related cost functions
**Time estimate:** 1 hour
**Complexity:** Small–Medium
**Risk:** Low

### Current state

**models.py MODEL_REGISTRY** (line 33):
```python
MODELS = {
    "gemini-2.5-flash": {
        "provider": "gemini",
        "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10 / $0.40 per 1M tokens",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": True}
    },
    ...
}
```

**agent.py MODELS** (line 69):
```python
MODELS = {
    "gemini-2.5-flash": {
        "provider": "gemini",
        "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "pricing": [0.10, 0.40, 0.0]  # [input, output, thinking] in USD per 1M
    },
    ...
}
```

**Schema differences:**
- `models.py`: `price` (display string), `capabilities`, `context_window`
- `agent.py`: `pricing` (float array for cost calculation), `url` (for some providers)

**agent.py functions:** `compute_cost()` (lines 149–200), `DEFAULT_MODEL` constant (line 143)

**Problem:** Two parallel MODELS dicts that must stay in sync. Changes to pricing, capabilities, or new models require dual maintenance.

### Consolidation steps

1. **Enhance models.py MODELS:**
   - Add `pricing: [input_usd, output_usd, thinking_usd]` float array to every entry
   - Pull values from agent.py MODELS or official pricing docs
   - Cross-check with Phase 5c documentation for Gemini/Anthropic/OpenAI pricing

2. **Move compute_cost() to models.py:**
   ```python
   def compute_cost(model_key: str, input_tokens: int, output_tokens: int,
                    thinking_tokens: int = 0) -> float:
       """Calculate cost for a model call in USD."""
       if model_key not in MODELS:
           return 0.0
       pricing = MODELS[model_key].get("pricing", [0, 0, 0])
       return (input_tokens * pricing[0] + output_tokens * pricing[1] + 
               thinking_tokens * pricing[2]) / 1e6
   ```

3. **Move DEFAULT_MODEL constant to models.py:**
   ```python
   DEFAULT_MODEL = "gemini-2.5-flash"  # or whatever agent.py defines
   ```

4. **Remove from agent.py:**
   - Lines 69–148: MODELS dict
   - Lines 149–200: compute_cost() function
   - Line 143: DEFAULT_MODEL constant

5. **Add import at top of agent.py:**
   ```python
   from models import MODELS, compute_cost, DEFAULT_MODEL
   ```

6. **Update server.py line 2879:**
   - Change: `from agent import MODELS`
   - To: `from models import MODELS`

### Rationale
- Single source of truth for all model metadata + costs
- Completes Phase 5c intent (consolidate registries)
- agent.py shrinks ~200 lines; becomes pure CLI agent logic
- No duplication of pricing/capabilities data
- Easier to add new models (one place only)

### Precautions
1. Verify all models in agent.py MODELS are in models.py MODEL_REGISTRY (or vice versa)
2. Cross-check pricing arrays against official rates:
   - Gemini pricing at cloud.google.com/generative-ai/pricing
   - Anthropic at anthropic.com/pricing
   - OpenAI at openai.com/pricing
3. Test compute_cost() before and after:
   ```python
   # Should give same results
   from models import compute_cost
   cost = compute_cost("gemini-2.5-flash", 1000000, 1000000, 100000)
   print(cost)  # should be ~$0.50 + $2.00 + $0.03 = ~$2.53
   ```
4. Verify server.py batch runner still calculates costs correctly
5. Test agent CLI: `python3 agent.py --model gemini-2.5-flash --game c59eb873`

### Files modified
- `models.py` (enhance MODELS, add compute_cost, add DEFAULT_MODEL)
- `agent.py` (remove MODELS dict, functions, add import)
- `server.py` (update lazy import on line 2879)

### Commit message
```
chore(phase-7): consolidate MODELS registry — agent.py imports from models.py

Merges agent.py MODELS dict into models.py MODEL_REGISTRY. Adds pricing 
float arrays to all entries; moves compute_cost() and DEFAULT_MODEL to models.py.

- Add pricing: [input_usd, output_usd, thinking_usd] to all model entries in models.py
- Move compute_cost() from agent.py (lines 149–200) to models.py
- Move DEFAULT_MODEL from agent.py to models.py
- Remove MODELS dict from agent.py; import from models.py
- Update server.py lazy import: from agent import MODELS → from models import MODELS

Single source of truth for model metadata + costs. No behavior change.
Completes Phase 5c consolidation work. agent.py shrinks ~200 lines.
```

---

## Phase 8: Modularize server.py by Endpoint Group

**Target:** Split monolithic Flask app into 5 logical blueprints
**Time estimate:** 2 hours
**Complexity:** Large
**Risk:** Medium

### Current state

`server.py` is a single 2566-line file with 77 `@app.route` decorators:
- **Game routes** (start, step, reset, undo, dev/jump-level)
- **Auth routes** (magic-link, Google OAuth, Turnstile, logout, claim-sessions)
- **Session routes** (resume, branch, list, get, step detail, events, import, browse)
- **LLM routes** (models registry, LM Studio proxy, Cloudflare proxy, config)
- **Social routes** (leaderboard, comments, contributors, game-results)
- **Batch routes** (async batch run orchestration)
- **Draw editor routes** (custom scene CRUD)
- **Admin routes** (memory endpoint)

All 77 routes are mixed together with no logical grouping. Hard to navigate, test, or extend.

### Proposed structure

Create `server/` Python package with blueprints:

```
server/
├── __init__.py
├── app.py (250 lines)              # Flask init, globals, index, share, cache headers
├── game_routes.py (250 lines)       # start, step, reset, undo, dev/jump-level
├── auth_routes.py (200 lines)       # magic-link, OAuth, Turnstile, logout, claim
├── session_routes.py (350 lines)    # resume, branch, list, get, events, import
├── social_routes.py (200 lines)     # leaderboard, comments, contributors, results
└── llm_admin_routes.py (150 lines)  # models, proxies, batch, draw, memory
```

Plus update:
- `templates/index.html` — load order unchanged (all scripts are client-side)
- `server.py` → deprecated, moved to `server/app.py`

### Modularization plan

#### server/app.py (250 lines)
**What to keep:**
- Flask app initialization: `app = Flask(...)`
- Config: `app.config["TEMPLATES_AUTO_RELOAD"] = True`, secret_key, logging
- Feature flags: `FEATURES` dict (lines 71–90)
- Global helpers:
  - `get_mode()` — return current mode
  - `feature_enabled(name)` — feature flag check
  - `get_enabled_features()` — return all flags
  - `get_current_user()` — authenticated user from Flask session
  - `_load_prompts()` — load prompt templates from server
  - `get_arcade()` — ARC engine instance
  - `get_game_version(game_id)` — version number
  - `frame_to_grid(frame)` — convert engine frame to grid list
  - `env_state_dict(env, ...)` — convert engine state to API response dict
- Middleware: `@app.after_request def add_cache_headers()`
- Routes: `@app.route("/")` index, `@app.route("/games/ab")` AB test, `@app.route("/share/*")` share page
- DB utilities: `_get_db()`, `_init_db()`, DB_PATH
- Blueprint registration:
  ```python
  from server.game_routes import game_bp
  from server.auth_routes import auth_bp
  from server.session_routes import session_bp
  from server.social_routes import social_bp
  from server.llm_admin_routes import admin_bp
  
  app.register_blueprint(game_bp)
  app.register_blueprint(auth_bp)
  app.register_blueprint(session_bp)
  app.register_blueprint(social_bp)
  app.register_blueprint(admin_bp)
  ```
- Main entry point: `if __name__ == "__main__"` with dual-port logic

#### server/game_routes.py (250 lines)
**What to extract from server.py:**
- Lines 685–859: Game endpoints
  - `@app.route("/api/start", methods=["POST"])` + `start_game()`
  - `@app.route("/api/step", methods=["POST"])` + `step_game()`
  - `@app.route("/api/reset", methods=["POST"])` + `reset_game()`
  - `@app.route("/api/dev/jump-level", methods=["POST"])` + `dev_jump_level()`
  - `@app.route("/api/undo", methods=["POST"])` + `undo_step()`
- Helpers: `start_game()`, `step_game()`, `reset_game()`, `dev_jump_level()`, `undo_step()`
- Dependencies: session_manager, engine, state globals

**Pattern:**
```python
from flask import Blueprint
game_bp = Blueprint('game', __name__)

@game_bp.route("/api/start", methods=["POST"])
def start_game():
    ...
```

#### server/auth_routes.py (200 lines)
**What to extract:**
- Lines 426–605: Auth endpoints
  - `@app.route("/api/auth/magic-link", methods=["POST"])`
  - `@app.route("/api/auth/verify")`
  - `@app.route("/api/auth/status")`
  - `@app.route("/api/auth/logout", methods=["POST"])`
  - `@app.route("/api/auth/google")` → Google OAuth redirect
  - `@app.route("/api/auth/google/callback")` → OAuth callback
  - `@app.route("/api/auth/claim-sessions", methods=["POST"])`
  - `@app.route("/api/copilot/auth/start", methods=["POST"])`
  - `@app.route("/api/copilot/auth/poll", methods=["POST"])`
  - `@app.route("/api/copilot/auth/status")`
- Helpers: `_send_magic_email()`, Google OAuth redirect/callback logic, Turnstile validation
- Dependencies: bot_protection, session_manager, Google API client

#### server/session_routes.py (350 lines)
**What to extract:**
- Lines 1521–1768: Session endpoints
  - `@app.route("/api/sessions")` — list sessions
  - `@app.route("/api/sessions/<id>")` — get session detail
  - `@app.route("/api/sessions/<id>/step/<n>")` — get step detail
  - `@app.route("/api/sessions/<id>/calls")` — LLM call log
  - `@app.route("/api/sessions/<id>/event", methods=["POST"])` — log event
  - `@app.route("/api/sessions/<id>/obs-events", ...)` — observatory events
  - `@app.route("/api/sessions/resume", methods=["POST"])` — resume session
  - `@app.route("/api/sessions/branch", methods=["POST"])` — branch from step
  - `@app.route("/api/sessions/import", methods=["POST", "OPTIONS"])` — import session
  - `@app.route("/api/sessions/browse")` — public sessions
  - `@app.route("/api/sessions/public")` — list public sessions
- Helpers: `resume_session()`, `branch_session()`, `import_session()`, `browse_sessions()`, `list_sessions()`, `get_session()`, `get_session_step()`, `session_calls()`, `log_session_event()`, `session_obs_events()`
- Dependencies: session_manager, grid_analysis, db

#### server/social_routes.py (200 lines)
**What to extract:**
- Lines 1811–2070: Social/leaderboard endpoints
  - `@app.route("/api/leaderboard")` — global leaderboard
  - `@app.route("/api/leaderboard/<game_id>")` — per-game leaderboard
  - `@app.route("/api/comments/<game_id>")` — get game comments
  - `@app.route("/api/comments", methods=["POST"])` — post comment
  - `@app.route("/api/comments/<id>/vote", methods=["POST"])` — vote on comment
  - `@app.route("/api/contributors")` — list game contributors
  - `@app.route("/api/game-results")` — game win stats
- Helpers: `leaderboard()`, `leaderboard_detail()`, `get_comments()`, `post_comment()`, `vote_comment()`, `contributors()`, `game_results()`, `_format_action_row()`
- Dependencies: session_manager, db

#### server/llm_admin_routes.py (150 lines)
**What to extract:**
- Lines 859–932: LLM/model routes
  - `@app.route("/api/llm/models")` — model registry + OLLAMA discovery
  - `@app.route("/api/llm/lmstudio-proxy", methods=["POST"])` — LM Studio proxy
  - `@app.route("/api/llm/cf-proxy", methods=["POST"])` — Cloudflare Workers AI proxy
- Lines 1118–1338: Config/auth routes
  - `@app.route("/api/config/mode", methods=["GET", "POST"])`
  - `@app.route("/api/config/apikey", methods=["POST"])`
  - `@app.route("/api/claude/auth/status")`
  - `@app.route("/api/openai/auth/status")`
  - `@app.route("/api/memory", methods=["GET", "POST"])`
  - `@app.route("/api/claude/auth/set-key", methods=["POST"])`
  - `@app.route("/api/openai/auth/set-key", methods=["POST"])`
- Lines 2317–2517: Batch + draw routes
  - `@app.route("/api/batch/start", methods=["POST"])` — start batch run
  - `@app.route("/api/batch/<batch_id>")` — batch status
  - `@app.route("/draw")` — draw editor page
  - `@app.route("/api/draw/scene/<level>")` — get draw scene
  - `@app.route("/api/draw/save", methods=["POST"])` — save scene
  - `@app.route("/api/draw/save_diffs", methods=["POST"])`
  - `@app.route("/api/draw/reset", methods=["POST"])`
- Helpers: `_load_fd_module()`, `_read_custom_scenes()`, `_write_custom_scenes()`, batch runner, `_require_batch_auth()`
- Dependencies: llm_providers, models, agent (batch runner), db

### Implementation steps

1. Create `server/__init__.py` (empty or minimal exports)
2. Copy `server.py` → `server/app.py`; remove route-specific code, keep globals
3. Create `server/game_routes.py`, extract lines 685–859
4. Create `server/auth_routes.py`, extract lines 426–605 + Copilot auth
5. Create `server/session_routes.py`, extract lines 1521–1768 + public sessions
6. Create `server/social_routes.py`, extract lines 1811–2070
7. Create `server/llm_admin_routes.py`, extract lines 859–932 + config + batch + draw
8. Update `server/app.py` to import and register all blueprints
9. Delete old `server.py` (keep for reference in git history)
10. Update imports in `__main__`: `python3 server/app.py` or `python3 -m server.app`

### Backward compatibility
- All route URLs remain identical
- API contracts unchanged
- Client-side code (JS) makes same requests

### Testing plan
1. **Blueprint isolation:** Each blueprint should be importable independently
2. **Route functionality:** 
   - Test game flow: start → step → step → undo → step
   - Test auth: magic-link → verify → status
   - Test session: resume → branch
   - Test social: leaderboard, comments
   - Test batch: start batch → poll status
   - Test draw: load, save, reset
3. **Database:** Verify session_manager, DB operations work across blueprints
4. **Configuration:** Verify FEATURES flags accessible from all blueprints
5. **Middleware:** Verify cache headers applied to all routes

### Precautions
1. **Circular imports:** Ensure no blueprint imports app.py before app is fully initialized. Use late imports if needed.
2. **Shared globals:** session_manager, DB connection, config must be accessible to all blueprints. Use `from server.app import ...` or pass via Flask app context.
3. **Secret key:** All blueprints run under same Flask secret_key; session cookies work across all routes.
4. **URL registration:** Verify all 77 routes are registered; grep `/api/` in app to confirm none are missed.
5. **Feature flags:** FEATURES dict must be accessible to all route functions (define at module level or via app.config).

### Files created/modified
- `server/__init__.py` (new, ~10 lines)
- `server/app.py` (new, ~250 lines, moved from server.py)
- `server/game_routes.py` (new, ~250 lines)
- `server/auth_routes.py` (new, ~200 lines)
- `server/session_routes.py` (new, ~350 lines)
- `server/social_routes.py` (new, ~200 lines)
- `server/llm_admin_routes.py` (new, ~150 lines)
- `server.py` (old, deleted or archived; kept in git history)

### Commit message
```
refactor(phase-8): modularize server.py by endpoint group → Flask blueprints

Splits monolithic 2566-line server.py into 5 logical blueprints:
- server/app.py (250): Flask init, globals, cache, index, share, main()
- server/game_routes.py (250): Game endpoints (start, step, reset, undo)
- server/auth_routes.py (200): Auth endpoints (magic-link, OAuth, Turnstile)
- server/session_routes.py (350): Session endpoints (resume, branch, list, detail)
- server/social_routes.py (200): Social endpoints (leaderboard, comments, contributors)
- server/llm_admin_routes.py (150): LLM/batch/draw endpoints (models, proxy, batch, draw)

Benefits:
- Single responsibility per blueprint
- Easier to test (blueprint + blueprint dependencies only)
- Easier to add/remove features (enable/disable blueprint)
- Code navigation: find route in specific blueprint
- No API change; all URLs, contracts identical

All 77 routes now clearly organized. No behavior change.
```

---

## Phase 9: Modularize session.js by Concern

**Target:** Split 2528-line session.js into 4 focused modules + residual router
**Time estimate:** 2 hours
**Complexity:** Large
**Risk:** Medium

### Current state

`session.js` mixes five orthogonal concerns:
1. **localStorage ops** (lines 15–67): `getLocalSessions()`, `saveLocalSessionIndex()`, `saveLocalSession()`, `getLocalSessionData()`, `deleteLocalSession()`
2. **Session history UI** (lines 78–149): `loadSessionHistory()` — fetch + render server session list
3. **Replay/scrubbing** (lines 151–382): `loadReplay()`, `showReplayStep()`, live scrubber controls
4. **Persistence/upload** (lines 404–810): Turnstile validation, build payload, autoUpload, share, Puter KV
5. **App view routing** (lines 1567–1954): Menu, browse (human/AI/my), prompts tab, session resumption, branching

Plus auth integration (lines 2428–2528): `checkAuthStatus()`, `doLogin()`, `doLogout()`, `claimLocalSessions()`, `updateAuthUI()`

### Proposed structure

#### static/js/session-storage.js (250 lines)
**Purpose:** Pure localStorage session persistence
**Extracted from session.js:**
- Lines 6–14: Constants (`LOCAL_SESSIONS_KEY`, `LOCAL_SESSION_PREFIX`, `MAX_LOCAL_SESSIONS`, `replayData` var)
- Lines 15–67: Functions
  - `getLocalSessions()`
  - `saveLocalSessionIndex(sessions)`
  - `saveLocalSession(sessionMeta, steps)`
  - `getLocalSessionData(sid)`
  - `deleteLocalSession(sid)`
  - `formatDuration(seconds)`

**Dependencies:** None (pure utility)

**Globals exported:** `replayData` (mutable state), all functions

#### static/js/session-replay.js (400 lines)
**Purpose:** Replay and live scrubbing UI
**Extracted from session.js:**
- Lines 151–382: All replay/scrubbing functions
  - `loadReplay(sid)`
  - `showReplayStep(stepIdx)`
  - `replayPrev()`, `replayNext()`, `closeReplay()`
  - `initLiveScrubber()`, `liveScrubUpdate()`, `liveScrubShow()`, `liveScrubReturnToLive()`, `liveScrubToStep()`, `hideLiveScrubber()`
  - `_renderGridPreview(grid)`
  - State vars: `_liveScrubLiveGrid`, `_liveScrubber*`

**Dependencies:** 
- `renderGrid()`, `currentGrid`, `currentChangeMap` globals from ui.js
- `fetchJSON()` from ui.js

**Globals exported:** All replay-related functions, state

#### static/js/session-persistence.js (300 lines)
**Purpose:** Session recording, upload, sharing
**Extracted from session.js:**
- Lines 404–459: Turnstile + Puter setup
  - `onTurnstileSuccess(token)`
  - `puterKvKey(sid)`
  - Auth status integration
- Lines 470–810: Recording/upload functions
  - `_collectPrompts()`
  - `buildSessionPayload(ss)`
  - `recordStepForPersistence(actionId, actionData, grid, changeMap, llmResponse, ss)`
  - `autoUploadSession(ss)`, `uploadClosedSession(s)`, `checkSessionEndAndUpload()`
  - `showShareLink(sid)`, `updateShareBtnVisibility()`, `updateUploadBadge()`
  - `shareCurrentSession()`
  - `puterKvCheckResume()`, `resumeFromPuterKv(kvKey)`, `dismissResumeBanner()`
  - `renderRestoredReasoning(steps, bannerText, ...)`

**Dependencies:**
- `currentUser` global (auth status)
- `currentState`, `sessionId`, `moveHistory`, `currentChangeMap` globals
- `fetchJSON()`, `renderGrid()` from ui.js

**Globals exported:** All upload/share functions

#### static/js/session-views.js (500 lines)
**Purpose:** App view routing and rendering
**Extracted from session.js:**
- Lines 1478–1523: Prompt field management
  - `_humanizePromptName(name)`
  - `_getPromptSections(schemaId)`
  - `_savePromptField(textarea)`
  - `_populatePromptFields()`
  - `renderPromptsTab()`
- Lines 1567–1680: View routing
  - `showAppView(view, skipHash)`
  - `_routeFromHash()`
  - `showMenuView()`, `showMenuSessions()`
- Lines 1703–1954: Menu and browse views
  - `renderMenuSessions()`, `menuResume(sid)`
  - `loadBrowseView()`, `_loadBrowseGameList()`, `_browseSelectGame()`, `clearBrowseGameFilter()`
  - `_loadBrowseColumns()`, `loadBrowseHuman()`, `loadBrowseAI()`, `loadBrowseMy()`
  - `buildSessionRow(s, isLocal)`, `browseReplay(sid)`, `_matchesGameFilter(s)`
- Lines 907–1225: Session resumption/branching
  - `resumeSession(sid)`
  - `branchFromStep(stepNum)`
  - `branchHere()`

**Dependencies:**
- `currentUser` (auth check)
- `currentState`, `sessionId`, `moveHistory` (session globals)
- `fetchJSON()`, `renderGrid()`, `startGame()` from ui.js
- `loadSessionHistory()` from residual session.js

**Globals exported:** All view functions, `showAppView` (entry point)

#### static/js/session.js (residual, ~300 lines)
**Purpose:** Auth integration, session history list, routing entry point
**Remains in session.js:**
- Lines 78–149: `loadSessionHistory()` — fetch + render server session list
- Lines 2428–2528: Auth functions
  - `doLogin()`, `doLogout()`
  - `updateAuthUI()`, `updateAuthButton()`
  - `checkAuthStatus()`
  - `claimLocalSessions()`
- New: Module initialization + routing orchestration
  - On page load: `checkAuthStatus()` → then route to appropriate view
  - Entry point for view routing
  - Global auth state: `currentUser`

**Globals exported:** `currentUser`, `checkAuthStatus()`, `doLogin()`, `doLogout()`

### Implementation steps

1. Create `session-storage.js`: Copy lines 6–67 from session.js, add `replayData` var
2. Create `session-replay.js`: Copy lines 151–382 + helpers
3. Create `session-persistence.js`: Copy lines 404–810 + Turnstile
4. Create `session-views.js`: Copy lines 1478–1954 + resumption/branching
5. Update `session.js`:
   - Remove all extracted lines
   - Keep: `loadSessionHistory()`, auth functions, `currentUser` global
   - Add imports: none (global scope, load order handles dependencies)
6. Update `index.html` script load order (see below)
7. Test page load, view routing, session resume, replay, upload

### New script load order in index.html

Add after other core modules, before session.js:

```html
<!-- templates/index.html lines ~661–671 (existing: state, engine, etc.) -->
<script src="/static/js/state.js?v=..."></script>
<script src="/static/js/engine.js?v=..."></script>
<script src="/static/js/reasoning.js?v=..."></script>
<script src="/static/js/ui.js?v=..."></script>
<script src="/static/js/llm.js?v=..."></script>
<!-- ... scaffolding scripts ... -->

<!-- Phase 9: Session modules (new order) -->
<script src="/static/js/session-storage.js?v={{ static_v }}"></script>
<script src="/static/js/session-replay.js?v={{ static_v }}"></script>
<script src="/static/js/session-persistence.js?v={{ static_v }}"></script>
<script src="/static/js/session-views.js?v={{ static_v }}"></script>
<script src="/static/js/session.js?v={{ static_v }}"></script>

<!-- Existing: observatory, human, leaderboard, dev -->
<script src="/static/js/observatory.js?v=..."></script>
<script src="/static/js/human.js?v=..."></script>
<script src="/static/js/leaderboard.js?v=..."></script>
<script src="/static/js/dev.js?v=..."></script>
```

**Load order rationale:**
- `session-storage.js` first: Pure utils, no deps
- `session-replay.js` second: Depends on renderGrid (from ui.js)
- `session-persistence.js` third: Depends on auth, UI
- `session-views.js` fourth: Depends on storage, replay, persistence
- `session.js` last (residual): Orchestrates all, calls modules on page load

### Testing plan

1. **Page load:** Open app → `checkAuthStatus()` runs → route based on user/no-user
2. **Menu view:** Click browse, check session list loads
3. **Browse view:** Click a session row → resume it
4. **Resume → Replay:** Resume, then click "Replay" button → replay UI loads
5. **Live scrubber:** Use scrubber to jump to step → grid updates
6. **Upload:** Start a game, make some steps, close → auto-upload triggers
7. **Share:** Generate share link → copy button works
8. **Branch:** Resume session → click "Branch here" → create new session from step
9. **Prompts tab:** Click prompts, edit a field → saves correctly
10. **localStorage:** Go offline, create local session → check localStorage key exists

### Precautions

1. **Globals:** Ensure all state (currentUser, currentState, sessionId, moveHistory, replayData) is accessible across modules
   - Declare at module scope or rely on global scope (no modules, script tags)
   - Test by logging in console: `console.log(currentUser, replayData, sessionId)`

2. **Auth status:** `checkAuthStatus()` must run BEFORE any view routing
   - Verify page load order: session.js init runs last, calls `checkAuthStatus()` on `window.load`

3. **Hash routing:** `_routeFromHash()` uses `window.location.hash`
   - Test: Click menu button, hash changes to `#menu`
   - Test: Type `#browse?filter=human` in URL, view updates

4. **Circular dependencies:** None expected (storage → replay → persistence → views → session glue)
   - All data flow is downward; no backward references

5. **DOM elements:** Verify all ID references still exist in HTML
   - Moved functions reference `#historyList`, `#replayContainer`, etc.
   - Check these IDs exist in index.html

### Files created/modified

- `static/js/session-storage.js` (new, 250 lines)
- `static/js/session-replay.js` (new, 400 lines)
- `static/js/session-persistence.js` (new, 300 lines)
- `static/js/session-views.js` (new, 500 lines)
- `static/js/session.js` (modified, ~300 lines residual)
- `templates/index.html` (modified, update script tags for Phase 9 modules)

### Commit message

```
refactor(phase-9): modularize session.js by concern → 4 focused modules

Splits 2528-line session.js into 5 focused modules:
- session-storage.js (250): Pure localStorage session persistence
- session-replay.js (400): Replay/live scrubbing UI and controls
- session-persistence.js (300): Session recording, upload, sharing
- session-views.js (500): App routing and view rendering (menu, browse, prompts)
- session.js residual (300): Auth integration, history list, routing entry point

Benefits:
- Each module has single responsibility
- session-storage.js can be unit-tested independently
- Easier to add new view types (add to session-views.js)
- session.js main file ~90% smaller, acts as orchestrator
- Clearer data flow: storage → replay → persistence → views → glue

No behavior change. Pure structural refactor. Script load order critical.
```

---

## Summary Table

| Phase | Component | Target | Time | Complexity | Safety | Lines before | Lines after | Net change |
|-------|-----------|--------|------|-----------|--------|--------------|-------------|-----------|
| 6 | Grid dedup | agent.py | 30 min | Small | ✅ Safe | 1498 | 1388 | −110 |
| 7 | MODELS merge | models.py + agent.py | 1 hr | Med | ✅ Safe | 1388 + 650 | 1588 + 1188 | −250 (agent) |
| 8 | server.py blueprint | server/ package | 2 hrs | Large | ⚠️ Medium | 2566 | 2600 (spread) | +34 (imports) |
| 9 | session.js split | session* modules | 2 hrs | Large | ⚠️ Medium | 2528 | 2650 (spread) | +122 (imports) |
| | | **TOTAL** | **5.5 hrs** | | | **~9850** | **~9500** | −350 |

---

## Recommended Implementation Order

1. **Phase 6** (Day 1 AM, 30 min) — Grid utils cleanup — very safe, quick win
2. **Phase 7** (Day 1 PM, 1 hour) — MODELS consolidation — low risk
3. **Phase 8** (Day 2 AM–PM, 2 hours) — server.py blueprints — test all 77 routes
4. **Phase 9** (Day 3 AM–PM, 2 hours) — session.js split — test routing, auth, views

**Parallelization:** Phase 6 + 7 can be one commit; Phase 8 can run during Phase 7 (no cross-deps).

**Commits:** 4 total (one per phase)

---

**Next steps:**
1. Review this plan for accuracy and feasibility
2. Get approval from main agent
3. Spawn Phase 6 implementation subagent
4. Continue phases sequentially

---

*End of Phase 6–9 Analysis. Detailed, conservative refactor plan balancing SRP/DRY improvements with minimal risk.*
