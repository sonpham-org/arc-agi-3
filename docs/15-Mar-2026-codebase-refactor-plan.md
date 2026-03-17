# Codebase Refactor + Critical Flow Tests

**Date:** 2026-03-15
**Author:** Claude Opus 4.6
**Branch:** `staging`

---

## Scope

### IN
1. **Critical fixes** — config duplication (HIDDEN_GAMES drift), SQL injection guard, DB connection safety
2. **High-impact refactors** — shared validators, magic number constants, dead code cleanup
3. **Critical flow tests** — game start, game step, undo, session resume, game listing, LLM provider routing
4. **JS quick wins** — empty catch handlers, localStorage key constants

### OUT
- Full architecture overhaul (ServiceContext dataclass, state.js split, blueprint migration)
- HTML template refactoring (inline styles, onclick handlers, accessibility)
- Game file headers (49 files — separate task)
- Root-level module reorganization
- Frontend DOM selector centralization

---

## Architecture

### Files Modified

| File | Change |
|------|--------|
| `server/state.py` | Single source of truth for FEATURES, HIDDEN_GAMES |
| `server/helpers.py` | Import from state.py instead of redefining |
| `server/app.py` | Import from state.py instead of redefining |
| `db_sessions.py` | Whitelist allowed columns in `_db_update_session` |
| `db_auth.py` | Migrate to context manager for connection safety |
| `db_sessions.py` | Migrate to context manager |
| `db_llm.py` | Migrate to context manager |
| `db_exports.py` | Migrate to context manager |
| `server/services/game_service.py` | Import shared validators |
| `server/services/social_service.py` | Import shared validators |
| `server/services/validators.py` | **NEW** — shared validation functions |
| `constants.py` | Add SERVICE_LIMITS, THINKING_TEXT_MAX_CHARS |
| `models.py` | Import SYSTEM_MSG from constants instead of redefining |
| `llm_providers.py` | Dispatch dict instead of if/elif chain |
| `db_deprecated.py` | Remove if truly unused |

### Files Created

| File | Purpose |
|------|---------|
| `server/services/validators.py` | Shared validation functions (game_id, session_id, action_id, comment) |
| `tests/test_critical_flows.py` | Tests for game start, step, undo, resume, game listing |
| `tests/test_db_safety.py` | Tests for SQL injection guard, connection management |
| `tests/test_provider_routing.py` | Tests for LLM provider dispatch |

---

## TODOs

### Phase 1: Critical Fixes

- [ ] **1.1** Consolidate HIDDEN_GAMES/FEATURES → single definition in `server/state.py`, import in `helpers.py` and `app.py`
- [ ] **1.2** Add column whitelist to `_db_update_session()` in `db_sessions.py`
- [ ] **1.3** Migrate `db_auth.py`, `db_sessions.py`, `db_llm.py`, `db_exports.py` to use `db_conn()` context manager
- [ ] **1.4** Add missing DB indexes (session_actions.session_id, sessions.user_id, sessions.game_id)

**Verify:** Import check passes, existing tests pass

### Phase 2: High-Impact Refactors

- [ ] **2.1** Create `server/services/validators.py` with shared validate_game_id, validate_session_id, validate_action_id, validate_comment
- [ ] **2.2** Update game_service.py and social_service.py to import from validators.py
- [ ] **2.3** Add SERVICE_LIMITS and THINKING_TEXT_MAX_CHARS to `constants.py`
- [ ] **2.4** Import SYSTEM_MSG in `models.py` from `constants.py`
- [ ] **2.5** Replace provider routing if/elif with dispatch dict in `llm_providers.py`
- [ ] **2.6** Remove `db_deprecated.py` if unused (verify first)
- [ ] **2.7** Remove dead blueprint imports from `server/app.py` if registration is still commented out

**Verify:** Import check passes, existing tests pass

### Phase 3: Critical Flow Tests

- [ ] **3.1** Write `tests/test_critical_flows.py`:
  - `test_game_start_returns_valid_state` — start ls20, verify grid/state/session_id
  - `test_game_start_missing_game_id` — 400 error
  - `test_game_start_invalid_game_id` — 400 error
  - `test_game_step_valid_move` — start + step, verify grid changes
  - `test_game_step_invalid_session` — 404 error
  - `test_game_step_invalid_action` — 400 error
  - `test_undo_restores_previous_state` — start + step + undo, verify grid matches original
  - `test_undo_nothing_to_undo` — start + undo (no steps), verify 400
  - `test_undo_multiple_steps` — start + N steps + undo(count=N), verify grid
  - `test_game_listing_returns_games` — verify /api/games returns non-empty list with expected fields
  - `test_game_listing_hides_games_in_prod` — verify HIDDEN_GAMES filtered in prod mode
  - `test_session_resume_roundtrip` — start + steps + save + resume, verify state matches
- [ ] **3.2** Write `tests/test_db_safety.py`:
  - `test_update_session_rejects_bad_columns` — verify whitelist blocks injection
  - `test_db_conn_context_manager_commits` — verify data persists
  - `test_db_conn_context_manager_rollback_on_error` — verify rollback on exception
- [ ] **3.3** Write `tests/test_provider_routing.py`:
  - `test_known_model_routes_correctly` — verify dispatch for each provider type
  - `test_unknown_model_falls_back_to_ollama` — verify fallback
  - `test_throttle_delays_applied` — verify per-provider rate limiting

**Verify:** `pytest tests/test_critical_flows.py tests/test_db_safety.py tests/test_provider_routing.py -v` all pass

### Phase 4: JS Quick Wins

- [ ] **4.1** Add `console.warn` to all empty `catch {}` blocks in scaffolding.js, llm-config.js, session-persistence.js
- [ ] **4.2** (Optional) Add STORAGE_KEYS constant to a shared JS file

**Verify:** No JS errors in browser console on page load

---

## Docs / Changelog

- Update `CHANGELOG.md` with refactoring entry
- No README changes needed
