# Changelog

All notable changes to ARC-AGI-3 Web Player will be documented in this file.

## [1.1.0] — refactor/phase-1-modularization
*Author: Mark Barney + Cascade (Claude Opus 4.6 thinking) | 2026-03-11*

### Added
- `constants.py` — shared color palette, action labels, game description (extracted from server.py/agent.py)
- `bot_protection.py` — Cloudflare Turnstile verification, IP rate limiting, user-agent filtering (extracted from server.py)
- `grid_analysis.py` — RLE row compression, change maps, color histograms, flood-fill region maps (extracted from server.py)
- `prompt_builder.py` — LLM prompt construction and response parsing (extracted from server.py)
- `session_manager.py` — in-memory session state and DB-backed session recovery (extracted from server.py)
- `static/js/utils/formatting.js` — canonical HTML escaping (escapeHtml, _esc), formatDuration, formatCost
- `static/js/utils/json-parsing.js` — findFinalMarker, extractJsonFromText, parseRlmClientOutput, parseClientLLMResponse
- `static/js/utils/tokens.js` — estimateTokens, TOKEN_PRICES lookup table
- `static/js/config/scaffolding-schemas.js` — SCAFFOLDING_SCHEMAS declarative field definitions
- `static/js/rendering/grid-renderer.js` — renderGridOnCanvas, renderGridWithChangesOnCanvas (pure canvas rendering)
- `static/js/observatory/obs-lifecycle.js` — in-app observatory mode enter/exit/status lifecycle
- `static/js/observatory/obs-log-renderer.js` — shared observatory log/tooltip rendering utilities
- `static/js/observatory/obs-scrubber.js` — shared step scrubber slider UI logic
- `static/js/observatory/obs-swimlane-renderer.js` — shared swimlane timeline rendering
- `static/js/scaffolding-linear.js` — linear (single-turn) prompt builder (extracted from scaffolding.js)
- `static/js/scaffolding-rlm.js` — RLM reflective reasoning loop (extracted from scaffolding.js)
- `static/js/scaffolding-three-system.js` — three-system/two-system cognitive architecture (extracted from scaffolding.js)
- `static/js/scaffolding-agent-spawn.js` — agent spawn multi-agent orchestrator (extracted from scaffolding.js)
- LM Studio server-side proxy endpoint `/api/llm/lmstudio-proxy` to bypass CORS
- LM Studio system-message-to-user promotion in `_callLLMInner` for Jinja template compatibility

### Changed
- `server.py` — reduced to Flask glue layer; imports from new Python modules
- `agent.py` — imports shared constants from `constants.py`
- `db.py` — updated imports for session_manager.py compatibility
- `static/js/scaffolding.js` — core LLM call infrastructure only; scaffolding types extracted to separate files
- `static/js/llm.js` — formatting and token helpers extracted to utility modules
- `static/js/state.js` — SCAFFOLDING_SCHEMAS extracted to config/scaffolding-schemas.js
- `static/js/ui.js` — pure grid rendering extracted to rendering/grid-renderer.js
- `static/js/observatory.js` — shared rendering extracted to observatory/ modules
- `static/js/obs-page.js` — shared rendering extracted to observatory/ modules
- `static/js/reasoning.js` — formatting extracted to utils/formatting.js
- `static/js/share-page.js` — formatting extracted to utils/formatting.js

### Fixed
- LM Studio 400 Bad Request when only system messages present (promoted to user role)
- LM Studio proxy swallowing error body (now forwards actual response body and status)

## [1.0.0] — baseline
*Pre-refactor monolithic codebase*

### Notes
- Single-file server.py (~2400 lines), monolithic scaffolding.js (~2400 lines)
- All game logic, prompt building, session management, bot protection inline in server.py
- All scaffolding types, JSON parsing, token pricing inline in scaffolding.js
