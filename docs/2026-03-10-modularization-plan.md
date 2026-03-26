# Plan: Modularization Refactor (SRP/DRY Audit)
**Date:** 2026-03-10
**Author:** Claude Sonnet 4.6
**Branch:** feature/modularization (new branch off master)

---

## Context

The project has grown organically to ~17,000 JS lines and ~7,000 Python lines across a handful of large files. Multiple files now handle 8–14 distinct responsibilities, and a recurring audit found ~1,400+ lines of cross-file duplication in JS alone (plus significant Python duplication). This plan decomposes the worst offenders into focused, single-responsibility modules so the codebase is easier to maintain, test, and extend.

This is a **pure refactor**: no behavioral changes, no new features. All existing tests must pass before and after.

---

## Scope

**In:**
- Python: `server.py`, `agent.py`, `db.py`, `llm_providers.py`, `batch_runner.py`
- JS: `scaffolding.js`, `llm.js`, `session.js`, `state.js`, `obs-page.js`, `observatory.js`, `ui.js`, `human.js`, `share-page.js`, `reasoning.js`

**Out:**
- Game environment files under `environment_files/`
- `scaffoldings/` Python modules (already well-decomposed)
- Behavioral changes to any scaffolding type
- New features or UI changes

---

## Findings Summary

### Python

| File | Lines | Distinct Responsibilities | Worst Violations |
|---|---|---|---|
| `server.py` | 2970 | 12 | Grid analysis, prompt building, bot protection, auth, and session state all co-located with HTTP routing |
| `agent.py` | 1509 | 8 | 3 redundant LLM call wrappers; `COLOR_NAMES`/`ACTION_NAMES` duplicated from `server.py` |
| `db.py` | 978 | 7 | DB connection opened/closed in every function (~25 repetitions); ~175-line migration blob |
| `llm_providers.py` | 655 | 7 | Provider call setup duplicated 4× (messages, image handling, response extraction, error handling) |
| `batch_runner.py` | 580 | 8 | Rate-limit monkey-patching; DB access pattern repeated 6× |

**Cross-file DRY violations:**
- `COLOR_NAMES`, `ACTION_NAMES` defined in both `server.py` and `agent.py`
- `SYSTEM_MSG` defined in 3 places (`agent.py`, `server.py`, `llm_providers.py`)
- `ARC_AGI3_DESCRIPTION` file read 3× independently
- DB open/close/commit pattern repeated ~25 times in `db.py`
- Provider message construction duplicated 4× in `llm_providers.py`

### JavaScript

| File | Lines | Distinct Responsibilities |
|---|---|---|
| `session.js` | 2528 | 14 |
| `llm.js` | 2475 | 10 (+ ~270 lines of dead code) |
| `scaffolding.js` | 2420 | 10 |
| `obs-page.js` | 1460 | 8 |
| `state.js` | 1453 | 5 (`SCAFFOLDING_SCHEMAS` is 300+ lines of config mixed with runtime state) |
| `human.js` | 1392 | 8 (27 global `_human*`-prefixed vars) |
| `observatory.js` | 630 | ~Same as `obs-page.js` — near-complete implementation duplication |

**Cross-file DRY violations:**
- `escapeHtml`/`esc`/`_rEsc` implemented in **6 separate places**: `llm.js` (×2), `obs-page.js`, `observatory.js`, `reasoning.js`, `share-page.js`
- `agentColor()` + `agentBadge()` duplicated in `reasoning.js`, `obs-page.js`, `observatory.js`
- `renderGrid()` + `renderGridWithChanges()` — identical implementations in `ui.js` and `share-page.js`
- `getScaffoldingSettings()` — **93 lines copied verbatim** in both `llm.js` and `scaffolding.js`
- `estimateTokens()` in `llm.js` and `session.js`
- Timeline cost formatting (`_tlFormatCost`/`_stlFormatCost`) in `llm.js` and `share-page.js`
- `obs-page.js` (1460 lines) and `observatory.js` (630 lines) implement roughly the same observatory functionality

---

## Phased Implementation

### Phase 1 — Quick Wins
*Zero behavioral risk. Eliminate unambiguous duplication.*

**1a. Create `constants.py`**
- Move `COLOR_NAMES`, `COLOR_MAP`, `ACTION_NAMES` from `server.py` and `agent.py`
- Unify the 3 copies of `SYSTEM_MSG`; load `ARC_AGI3_DESCRIPTION` once and export it
- Update imports in `server.py`, `agent.py`, `llm_providers.py`

**1b. Delete dead code in `llm.js`**
- Remove `_OLD_buildReasoningGroupHTML()` at lines ~802–1076 (~270 lines, unreachable — superseded by `reasoning.js`)

**1c. Create `static/js/utils/formatting.js`**
- Canonical `escapeHtml(s)` (source: `reasoning.js`'s `_rEsc`)
- `formatDuration(secs)` (from `share-page.js`)
- `formatCost(c)` (from `llm.js`'s `_tlFormatCost`)
- Replace all 6 HTML-escape duplicates with an import from here

**1d. Remove `getScaffoldingSettings()` duplicate from `llm.js`**
- Keep the authoritative copy in `scaffolding.js`; delete the 93-line verbatim copy in `llm.js`

**1e. Consolidate `agentColor()` + `agentBadge()`**
- Source of truth: `reasoning.js`
- Remove duplicates in `obs-page.js` and `observatory.js`; import from `reasoning.js`

---

### Phase 2 — Python Extractions (`server.py` decomposition)
*Reduce `server.py` from 2970 → ~2100 lines by pulling out non-HTTP concerns.*

**2a. Extract `grid_analysis.py`** (~130 lines moved from `server.py`)
- `compress_row()`, `_compress_change_row()`, `compute_change_map()`
- `compute_color_histogram()`, `compute_region_map()`

**2b. Extract `prompt_builder.py`** (~180 lines moved from `server.py`)
- `_build_prompt_parts()`, `_build_prompt()`, `_parse_llm_response()`, `_extract_json()`

**2c. Extract `bot_protection.py`** (~100 lines moved from `server.py`)
- `bot_protection` and `turnstile_required` decorators
- `_get_client_ip()`, `_is_bot_ua()`, `_check_rate_limit()`, `_verify_turnstile_token()`, `_is_turnstile_verified()`
- Rate-limit buckets and token cache dicts

**2d. Extract `session_manager.py`** (~120 lines moved from `server.py`)
- `game_sessions`, `session_grids`, `session_snapshots` dicts + `session_lock`
- `_reconstruct_session()`, `_try_recover_session()`
- Session snapshot/undo logic

**2e. DB connection context manager in `db.py`**
- Add `@contextmanager def _db()` that opens, yields, commits, and closes
- Replace all ~25 open/close patterns in `db.py` with `with _db() as conn:`
- No schema changes, no behavioral changes

---

### Phase 3 — JS Utility Extractions
*Centralize shared utilities; reduce cross-file coupling.*

**3a. Create `static/js/utils/tokens.js`**
- `TOKEN_PRICES` constant (moved from `llm.js`)
- `estimateTokens(text)` (remove duplicate in `session.js`)
- `trackTokenUsage(model, inputTok, outputTok)` — unify `llm.js`'s `formatTokenInfo` with `scaffolding.js`'s `_asTrackUsage`

**3b. Create `static/js/utils/json-parsing.js`**
- `extractJsonFromText(text)` — canonical balanced-brace extraction (from `scaffolding.js`'s `_extractJsonFromText`)
- `findFinalMarker(text)` (from `_rlmFindFinal`)
- `parseLLMResponse(content, modelName)` (from `parseClientLLMResponse`)

**3c. Create `static/js/rendering/grid-renderer.js`**
- `renderGrid(grid, canvas, ctx, colors)` — identical in `ui.js` and `share-page.js`
- `renderGridWithChanges(grid, changeMap, options)`

**3d. Create `static/js/config/scaffolding-schemas.js`**
- Move `SCAFFOLDING_SCHEMAS` object (~300 lines) out of `state.js`
- `state.js` imports it; no change to consumers

**3e. Consolidate template-fill in `scaffolding.js`**
- `_tsTemplateFill()` and `_asFill()` are identical; keep one, delete the other

---

### Phase 4 — Observatory Consolidation
*Eliminate the ~800-line near-duplication between `obs-page.js` and `observatory.js`.*

**Audit first:** Grep the HTML files to confirm which of the two is actually loaded by `index.html`. Do not merge blindly.

Once the live file is identified, extract shared components into a `static/js/observatory/` subdirectory:
- `obs-scrubber.js` — `obsScrubUpdate`, `obsScrubShow`, slider binding
- `obs-swimlane-renderer.js` — `renderObsSwimlane`, zoom/scroll, tooltips
- `obs-log-renderer.js` — `appendObsLogRow`, `obsBuildDetails`, detail toggling
- `obs-lifecycle.js` — `enterObsMode`, `exitObsMode`, `syncObsReasoning`

The non-live file's functions are then replaced with imports from the above.

---

### Phase 5 — Larger Refactors (optional follow-up)
*Further responsibility reduction; lower barrier to unit testing.*

**5a. Split `scaffolding.js` by scaffolding type**
- `scaffolding-rlm.js` — RLM loop (lines ~654–841)
- `scaffolding-three-system.js` — Three-System/Two-System loop
- `scaffolding-agent-spawn.js` — Agent Spawn orchestrator
- `scaffolding-linear.js` — Linear prompt builder
- Keep `scaffolding.js` as router + shared LLM call routing (`_callLLMInner`)

**5b. Move session execution out of `llm.js`**
- `askLLM()`, `executePlan()`, `executeOneAction()`, `stepOnce()`, `toggleAutoPlay()`, `undoStep()` → new `session-execution.js`
- `llm.js` becomes: timeline rendering + token formatting only

**5c. Consolidate model registry into `models.py`**
- Single source of truth for the `MODELS` dict
- `agent.py` and `server.py` both import from it; no more divergence

**5d. LLM provider base helpers in `llm_providers.py`**
- Extract `_build_messages(system, user, image)` shared helper
- Extract `_extract_response_text(response_json)` shared helper
- Each provider function calls these instead of reimplementing them

---

## New Files Summary

**Python (root):**
| File | Lines (est.) | Moved from |
|---|---|---|
| `constants.py` | ~40 | `server.py`, `agent.py`, `llm_providers.py` |
| `grid_analysis.py` | ~130 | `server.py` |
| `prompt_builder.py` | ~180 | `server.py` |
| `bot_protection.py` | ~100 | `server.py` |
| `session_manager.py` | ~120 | `server.py` |

**JavaScript (`static/js/`):**
| File | Lines (est.) | Moved from |
|---|---|---|
| `utils/formatting.js` | ~60 | `llm.js`, `share-page.js`, `reasoning.js` |
| `utils/tokens.js` | ~80 | `llm.js`, `scaffolding.js`, `session.js` |
| `utils/json-parsing.js` | ~100 | `scaffolding.js` |
| `rendering/grid-renderer.js` | ~80 | `ui.js`, `share-page.js` |
| `config/scaffolding-schemas.js` | ~320 | `state.js` |

---

## Expected Impact

| File | Before | After Phase 1–4 | After Phase 5 |
|---|---|---|---|
| `server.py` | 2970 | ~2100 | ~2100 |
| `llm.js` | 2475 | ~1850 | ~900 |
| `scaffolding.js` | 2420 | ~2200 | ~600 |
| `session.js` | 2528 | ~2350 | ~2200 |
| `state.js` | 1453 | ~1100 | ~1100 |
| HTML-escape duplicates | 6 copies | 1 | 1 |
| `getScaffoldingSettings` | 2 copies | 1 | 1 |

---

## Verification

After each phase:
1. `python -c "import db; import server; import agent; import batch_runner; print('OK')"` — import check
2. `python batch_runner.py --games ls20 --concurrency 1 --max-steps 5` — smoke test
3. Manual: open web UI, start a game, run one LLM step for each scaffolding type (Linear, RLM, Three-System)
4. Manual: verify Observatory view renders correctly and scrubber works
5. Manual: verify Share page renders reasoning correctly
6. `python tests/test_providers.py` — verify provider paths unaffected

---

## TODOs (ordered)

- [ ] **1. Phase 1a** — Create `constants.py`; update imports in `server.py`, `agent.py`, `llm_providers.py`
- [ ] **2. Phase 1b** — Delete dead code block in `llm.js` (~802–1076)
- [ ] **3. Phase 1c** — Create `static/js/utils/formatting.js`; replace 6 HTML-escape duplicates
- [ ] **4. Phase 1d** — Remove `getScaffoldingSettings()` duplicate from `llm.js`
- [ ] **5. Phase 1e** — Remove `agentColor`/`agentBadge` duplicates in `obs-page.js` / `observatory.js`
- [ ] **6. Phase 2a–2d** — Extract `grid_analysis`, `prompt_builder`, `bot_protection`, `session_manager` from `server.py`
- [ ] **7. Phase 2e** — Add DB context manager to `db.py`; replace ~25 open/close patterns
- [ ] **8. Phase 3a–3e** — JS utility extractions (`tokens.js`, `json-parsing.js`, `grid-renderer.js`, `scaffolding-schemas.js`, template-fill)
- [ ] **9. Phase 4** — Observatory audit then consolidation
- [ ] **10. Run full verification** — import check, smoke test, manual UI walkthrough
- [ ] **11. Push to staging**
- [ ] **12. Phase 5** (optional follow-up) — Split `scaffolding.js`, extract `session-execution.js`, consolidate `models.py`
