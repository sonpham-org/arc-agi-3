# Phase 5 Modularization Plan — Larger Refactors
> **Status:** Planning only — no code changes in this document.  
> **Author:** Cascade subagent, 2026-03-10  
> **Files analysed:** `static/js/scaffolding.js` (2471 lines), `static/js/llm.js` (2475 lines), `static/js/session.js` (2528 lines), `models.py` (297 lines), `agent.py` (1509 lines), `server.py` (3012 lines), `llm_providers.py` (655 lines), `templates/index.html`

---

## 5a — Split `scaffolding.js` by Scaffolding Type

### Current structure

`scaffolding.js` is a monolithic 2471-line file with six logical sections:

| Section | Lines | Content |
|---------|-------|---------|
| API Mode + Models discovery | 1–346 | `onApiModeChange`, `loadModels`, `_populateSubModelSelect`, `LMSTUDIO_CAPABILITIES`, BYOK helpers, `callLLM` / `_callLLMInner` |
| Prompt helpers | 347–475 | `getPrompt`, `compressRowJS`, `buildRlmSystemPrompt`, `buildRlmUserFirst/Continue`, `_rlmPlanInstruction`, `_rlmFindFinal`, `_extractJsonFromText`, `_parseRlmClientOutput` |
| **RLM scaffolding** | **476–862** | `callLLM` + `_callLLMInner` (lines 476–672), `askLLMRlm` (lines 674–862) |
| **Three-System / Two-System** | **863–1411** | Section header at 863; `askLLMThreeSystem` starts at 1163; helper functions `_tsTemplateFill`, `_computeColorHistogram`, `_computeRegionMap`, `_tsHandleWmQuery`, `_tsSimulateActions`, `_tsRunWmUpdate`, `_tsMonitorCheck` span lines 877–1162 |
| **Agent Spawn** | **1412–2245** | Section header at 1412; `askLLMAgentSpawn` at 1778; helpers `_asExecuteOneStep` (1418), `_makeBoundedBudget` (1486), `_asRenderGrid` (1499), `_asDiffFrames` (1504), `_asChangeSummary` (1522), `_asFind` (1528), `_asBoundingBox` (1540), `_asColorCounts` (1556), `_asDispatchFrameTool` (1560), `_asCreateMemories` (1574), `_asFill` (1770) |
| **Linear prompt builder** | **2246–2371** | `buildClientPrompt` (2246–2337), `parseClientLLMResponse` (2338–2370) |
| LLM Provider / BYOK plumbing | 2372–2471 | `loadPuterJS`, `getByokKey`, `byokActive`, `_geminiThinkingConfig`, Copilot auth (`copilotStartAuth`, `copilotPollAuth`, `checkCopilotStatus`) |

### Exact line ranges for splits

| New file | Line range in current `scaffolding.js` | Key functions |
|----------|----------------------------------------|---------------|
| **`scaffolding-rlm.js`** | 374–862 (includes RLM prompt templates & helpers + `askLLMRlm`) | `buildRlmSystemPrompt`, `buildRlmUserFirst`, `buildRlmUserContinue`, `_rlmPlanInstruction`, `_rlmFindFinal`, `_extractJsonFromText`, `_parseRlmClientOutput`, `askLLMRlm` |
| **`scaffolding-three-system.js`** | 863–1411 | `_tsTemplateFill`, `_computeColorHistogram`, `_computeRegionMap`, `_tsHandleWmQuery`, `_tsSimulateActions`, `_tsRunWmUpdate`, `_tsMonitorCheck`, `askLLMThreeSystem` |
| **`scaffolding-agent-spawn.js`** | 1412–2245 | `_asExecuteOneStep`, all `_as*` helpers, `askLLMAgentSpawn` |
| **`scaffolding-linear.js`** | 2246–2371 | `buildClientPrompt`, `parseClientLLMResponse` |
| **`scaffolding.js` (residual router)** | 1–373 + 2372–2471 | `onApiModeChange`, `loadModels`, `_populateSubModelSelect`, `LMSTUDIO_CAPABILITIES`, `callLLM`, `_callLLMInner`, BYOK/Puter helpers, Copilot auth |

> **Note:** `_extractJsonFromText` (lines 412–437) is currently inside the RLM helpers block but is called by `parseClientLLMResponse` in the linear section (line 2338) as well. It must either stay in `scaffolding.js` (router) or be duplicated. **Recommended:** move to `scaffolding.js` router (shared utilities) and call it from both modules via global scope.

### Import/export strategy

**Critical constraint:** All JS files are loaded as plain `<script>` tags (no `type="module"`):

```html
<!-- templates/index.html lines 661–671 -->
<script src="/static/js/state.js?v=..."></script>
<script src="/static/js/engine.js?v=..."></script>
<script src="/static/js/reasoning.js?v=..."></script>
<script src="/static/js/ui.js?v=..."></script>
<script src="/static/js/llm.js?v=..."></script>
<script src="/static/js/scaffolding.js?v=..."></script>
<script src="/static/js/session.js?v=..."></script>
<script src="/static/js/observatory.js?v=..."></script>
<script src="/static/js/human.js?v=..."></script>
<script src="/static/js/leaderboard.js?v=..."></script>
<script src="/static/js/dev.js?v=..."></script>
```

**No ES modules.** All functions are global. Therefore:
- Each new file exposes its functions as globals (same pattern as today).
- No `import`/`export` syntax.
- Load order matters: sub-modules must be loaded **after** `scaffolding.js` (the router, which defines `callLLM` and `getPrompt` they depend on).

### Required `index.html` script load order changes

Replace:
```html
<script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
```

With (in this exact order):
```html
<script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-rlm.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-three-system.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-agent-spawn.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-linear.js?v={{ static_v }}"></script>
```

`llm.js` must remain before all scaffolding scripts (it defines `getModelInfo`, globals used in `askLLMRlm` etc.).

### New file content outlines

#### `scaffolding.js` (router + shared)
```
// Header comment — now: router + shared LLM call routing
// SECTION: API Mode (onApiModeChange, saveArcApiKey)           — lines 20–46
// SECTION: Models discovery (_populateSubModelSelect, LMSTUDIO_CAPABILITIES, loadModels) — lines 52–346
// SECTION: Shared prompt helpers (getPrompt, compressRowJS)     — lines 353–373
// SECTION: Shared utilities (_extractJsonFromText)              — moved from RLM block
// SECTION: callLLM / _callLLMInner (LLM call routing)          — lines 476–672
// SECTION: LLM Provider BYOK (loadPuterJS, getByokKey, byokActive, _geminiThinkingConfig, Copilot auth) — lines 2372–2471
```

#### `scaffolding-rlm.js`
```
// PURPOSE: RLM (Reflective Language Model) client-side scaffolding.
// Depends on: callLLM (scaffolding.js), getPrompt (scaffolding.js), window.PROMPTS (server-injected)

const _RLM_SYSTEM_PROMPT_TEMPLATE = ...
const _RLM_USER_FIRST_TEMPLATE = ...
const _RLM_USER_CONTINUE_TEMPLATE = ...

function buildRlmSystemPrompt(planHorizon) { ... }
function buildRlmUserFirst(planHorizon) { ... }
function buildRlmUserContinue(planHorizon) { ... }
function _rlmPlanInstruction(planHorizon) { ... }
function _rlmFindFinal(text) { ... }
function _parseRlmClientOutput(finalAnswer, iterationsLog, planHorizon) { ... }
async function askLLMRlm(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) { ... }
```

#### `scaffolding-three-system.js`
```
// PURPOSE: Three-System / Two-System scaffolding.
// Depends on: callLLM (scaffolding.js), getPrompt (scaffolding.js), window.PROMPTS

const TS_PLANNER_SYSTEM_BODY = ...
// ... all TS_* template constants

function _tsTemplateFill(template, vars) { ... }
function _computeColorHistogram(grid) { ... }
function _computeRegionMap(grid) { ... }
function _tsHandleWmQuery(tsState, tool, step, stepRange) { ... }
async function _tsSimulateActions(actions, tsState, context, settings) { ... }
async function _tsRunWmUpdate(tsState, context, settings, waitEl, isActive) { ... }
async function _tsMonitorCheck(step, expected, changeData, gameState, settings, tsState) { ... }
async function askLLMThreeSystem(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) { ... }
```

#### `scaffolding-agent-spawn.js`
```
// PURPOSE: Agent Spawn orchestrator — Agentica-style reactive subagent loops.
// Depends on: callLLM (scaffolding.js), getPrompt (scaffolding.js), window.PROMPTS

// Step 1: Per-step execution helper
async function _asExecuteOneStep(...) { ... }

// Step 2: Bounded budget + frame helpers
function _makeBoundedBudget(limit) { ... }
function _asRenderGrid(grid) { ... }
function _asDiffFrames(oldGrid, newGrid) { ... }
function _asChangeSummary(oldGrid, newGrid) { ... }
function _asFind(grid, ...colors) { ... }
function _asBoundingBox(grid, ...colors) { ... }
function _asColorCounts(grid) { ... }
function _asDispatchFrameTool(tool, grid, prevGrid, args) { ... }

// Step 3: Stack-based shared memory
function _asCreateMemories() { ... }

// Step 4: Agentica-style prompts
// ... all _as* prompt builder functions and constants

// Step 5: Main function — reactive subagent loops
async function askLLMAgentSpawn(_cur, model, modelInfo, waitEl, isActiveFn, historyForLLM, compactBlock, _snap) { ... }
```

#### `scaffolding-linear.js`
```
// PURPOSE: Linear (single-turn) prompt builder and response parser.
// Depends on: getPrompt (scaffolding.js), _extractJsonFromText (scaffolding.js)

function buildClientPrompt(state, history, changeMap, inputSettings, toolsMode, compactContext, planningMode) { ... }
function parseClientLLMResponse(content, modelName) { ... }
```

### Tight coupling risks for 5a

1. **`_extractJsonFromText` called cross-module** — used by both `_parseRlmClientOutput` (RLM) and `parseClientLLMResponse` (Linear). Must live in router.
2. **`callLLM._lastUsage`** — `askLLMAgentSpawn` reads `callLLM._lastUsage` directly (line 1793). Since `callLLM` stays in router, this remains accessible; no risk.
3. **`PROMPTS` global** — all scaffolding types call `getPrompt()` which reads `window.PROMPTS`. `getPrompt` stays in router; fine.
4. **`getInputSettings()` / `getScaffoldingSettings()`** — called inside `askLLMRlm`, `askLLMThreeSystem`, `askLLMAgentSpawn`. These are defined in `llm.js` (lines 11, 20). Load order is already `llm.js` → `scaffolding.js` → sub-modules; no change needed.

### Per-step verification (5a)
1. Load page; confirm `callLLM` is accessible as global after `scaffolding.js` loads.
2. Confirm `askLLMRlm` is accessible after `scaffolding-rlm.js` loads; trigger RLM mode, run one step.
3. Confirm `askLLMThreeSystem` accessible; trigger Three-System mode, run one step.
4. Confirm `askLLMAgentSpawn` accessible; trigger Agent Spawn mode, run one step.
5. Confirm `buildClientPrompt` / `parseClientLLMResponse` accessible; run Linear mode.
6. Confirm `_extractJsonFromText` is not duplicated — shared via router.

---

## 5b — Move Session Execution Out of `llm.js`

### Functions to move: exact line numbers

| Function | Lines in `llm.js` | Size |
|----------|--------------------|------|
| `updateUndoBtn()` | 1764–1768 | 5 lines |
| `updateAutoBtn()` | 1769–1779 | 11 lines |
| `askLLM(ss)` | 1076–1759 | **684 lines** |
| `executePlan(plan, resp, entry, expected, ss)` | 1780–2026 | 247 lines |
| `executeOneAction(resp)` | 2027–2082 | 56 lines |
| `stepOnce()` | 2083–2112 | 30 lines |
| `truncAutoRetry(btn, maxRetries)` | 2113–2159 | 47 lines |
| `truncIncreaseAndRetry(btn)` | 2160–2167 | 8 lines |
| `toggleAutoPlay()` | 2168–2343 | 176 lines |
| `resetSession()` | 2344–2375 | 32 lines |
| `undoStep()` | 2376–2443 | 68 lines |
| `testModel()` | 2444–2475 | 32 lines |

**`llm.js` becomes** (lines 1–1075 + residual rendering functions): timeline rendering (`_rebuildTimelineFromSteps`, `_tlEsc`, `_tlFormatCost`, `_tlCallTypeLabel`, `_tlCssClass`, `_tlBuildDetail`, `_tlToggleDetail`, `renderTimelineTree`, `_updateAsTransform`, `renderTimeline`) and token/tool formatting (`estimateTokens`, `formatTokenInfo`, `renderToolCallsHtml`, `escapeHtml`, `esc`, `scrollReasoningToBottom`, `copyReasoningLog`, `copyTimelineLogs`, `getLastReasoningEntry`, `_OLD_buildReasoningGroupHTML`).

### ⚠️ CRITICAL: Call-site analysis

**Functions in scope for move and their callers:**

#### `askLLM`
| Caller | File | Line(s) |
|--------|------|---------|
| `stepOnce()` | `llm.js` | 2093 — moving to same new file, no break |
| `truncAutoRetry()` | `llm.js` | 2125 — moving to same new file, no break |
| `toggleAutoPlay()` | `llm.js` | 2270 — moving to same new file, no break |

#### `stepOnce`
| Caller | File | Line(s) |
|--------|------|---------|
| `truncIncreaseAndRetry()` | `llm.js` | 2165 — moving to same new file |
| `templates/index.html` | HTML (inline button) | **NOT found via grep** — verify manually |

#### `toggleAutoPlay`
| Caller | File | Line(s) |
|--------|------|---------|
| `templates/index.html` button | line 471 | `onclick="toggleAutoPlay()"` — **global scope call, will break if not global** |
| `templates/index.html` obs button | line 630 | `onclick="toggleAutoPlay()"` — same |
| `resetSession()` | `llm.js` | 2347 — moving to same file |

#### `undoStep`
| Caller | File | Line(s) |
|--------|------|---------|
| `templates/index.html` button | line 474 | `onclick="undoStep()"` — **global scope call** |

#### `executePlan`, `executeOneAction`, `updateUndoBtn`, `updateAutoBtn`
- Only called within `llm.js` itself (internal to the functions being moved). No external callers found.

**Summary of break risk:**
- `toggleAutoPlay` and `undoStep` are called from `onclick` attributes in `index.html`. Since the codebase uses global scope (no modules), **these will continue to work as long as `session-execution.js` is loaded before the page becomes interactive** (i.e., before the user clicks buttons). The load order change below ensures this.
- `stepOnce` appears only to be called from within `llm.js` itself — no HTML `onclick` callers found. Verify with `grep -n "stepOnce" templates/index.html` before merge.

### New file: `session-execution.js`

```
// PURPOSE: Session-level LLM execution loop, autoplay, undo, and plan execution.
// Depends on: scaffolding.js (callLLM, askLLMRlm, askLLMThreeSystem, askLLMAgentSpawn,
//             buildClientPrompt, parseClientLLMResponse),
//             llm.js (renderTimeline, formatTokenInfo, estimateTokens, getInputSettings,
//                     getScaffoldingSettings, getModelInfo, getCanvasScreenshotB64),
//             state.js, engine.js, ui.js

function updateUndoBtn() { ... }
function updateAutoBtn() { ... }
async function askLLM(ss) { ... }
async function executePlan(plan, resp, entry, expected, ss) { ... }
async function executeOneAction(resp) { ... }
async function stepOnce() { ... }
async function truncAutoRetry(btn, maxRetries) { ... }
function truncIncreaseAndRetry(btn) { ... }
async function toggleAutoPlay() { ... }
async function resetSession() { ... }
async function undoStep() { ... }
async function testModel() { ... }
```

### `llm.js` post-split content outline

```
// PURPOSE: Timeline rendering, token formatting, LLM UI helpers.
// No session execution logic. No LLM calls.

// Canvas screenshot helper
function getCanvasScreenshotB64() { ... }           // line 5

// Input/scaffolding settings readers
function getInputSettings() { ... }                 // line 11
function getScaffoldingSettings() { ... }           // line 20

// Token estimation
function estimateTokens(text) { ... }               // line 115

// Timeline rendering
function _rebuildTimelineFromSteps(steps) { ... }   // line 141
function _tlEsc(s) { ... }                          // line 197
function _tlFormatCost(c) { ... }                   // line 199
function _tlCallTypeLabel(ev) { ... }               // line 201
function _tlCssClass(ev) { ... }                    // line 206
function _tlBuildDetail(ev, idx) { ... }            // line 212
function _tlToggleDetail(idx) { ... }               // line 238
function renderTimelineTree(container, ...) { ... } // line 253
function _updateAsTransform(svg, container) { ... } // line 522
function renderTimeline(ss) { ... }                 // line 528

// Token / tool formatting
function formatTokenInfo(resp, tokensObj) { ... }   // line 601
function renderToolCallsHtml(toolCalls) { ... }     // line 636
function escapeHtml(str) { ... }                    // line 653
function esc(s) { ... }                             // line 656
function scrollReasoningToBottom() { ... }          // line 657
function copyReasoningLog() { ... }                 // line 661
function copyTimelineLogs() { ... }                 // line 729
function getLastReasoningEntry() { ... }            // line 785
function _OLD_buildReasoningGroupHTML(g, ...) { ... } // line 802 (legacy no-op)
```

### Required `index.html` script load order changes (5b)

Add `session-execution.js` after all scaffolding scripts:
```html
<script src="/static/js/llm.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-rlm.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-three-system.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-agent-spawn.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-linear.js?v={{ static_v }}"></script>
<script src="/static/js/session-execution.js?v={{ static_v }}"></script>
<script src="/static/js/session.js?v={{ static_v }}"></script>
```

`session.js` currently has no calls to `askLLM`/`stepOnce`/etc. (confirmed via grep), so its position is unchanged.

### Tight coupling risks for 5b

1. **`askLLM` calls `renderTimeline`, `formatTokenInfo`, `getInputSettings`, `getScaffoldingSettings`, `getModelInfo`** — these stay in `llm.js`. Because `llm.js` loads first and all functions are global, no break. **BUT:** `llm.js` rendering functions reference DOM elements that may not be set up until `session-execution.js` event handlers run. This is safe as long as `askLLM` is only ever called after page load.
2. **`executePlan` calls `renderGrid`, `fetchJSON`, `pyodideUndo`** — all globals from `engine.js`, `state.js`. No change needed.
3. **`toggleAutoPlay` reads/writes `autoPlaying` global** — this is a global variable defined in `state.js`. Fine.
4. **`undoStep` references `undoStack`, `moveHistory`, `sessionStepsBuffer`, `_pyodideGameActive`, `pyodideUndo`** — all globals. Fine.
5. **`resetSession` calls `toggleAutoPlay`** — both moving to `session-execution.js`. Fine.
6. **⚠️ BIGGEST RISK:** `askLLM` is 684 lines with deep inline references to globals (`currentState`, `sessionId`, `autoPlaying`, `llmObservations`, `llmCallCount`, `moveHistory`, `stepCount`, `currentChangeMap`, `sessionTotalTokens`, etc.). Any missed global reference during the copy will cause a silent runtime error. **Mitigation:** do a full `grep` of all globals read/written by `askLLM` before extracting; run a functional test immediately after.

### Per-step verification (5b)
1. Load page; confirm `renderTimeline` is accessible from console.
2. Confirm `toggleAutoPlay` is accessible from console (needed for `onclick` buttons).
3. Click Autoplay button — confirm no "toggleAutoPlay is not defined" error.
4. Click Undo button — confirm no "undoStep is not defined" error.
5. Run one LLM step manually — confirm `askLLM` resolves, timeline renders.
6. Confirm `testModel()` button works.

---

## 5c — Consolidate Model Registry into `models.py`

### Current state: two parallel MODELS dicts

#### `models.py` — `MODEL_REGISTRY` (line 33)
- Structure: `{ key: { provider, api_model, env_key, price (string), context_window, capabilities: {image, reasoning, tools} } }`
- Used by: `llm_providers.py` (imports `MODEL_REGISTRY`), `server.py` (imports `MODEL_REGISTRY` via `from models import ...`)
- Contains: Gemini family, Anthropic family, OpenAI-compatible (Groq, Mistral, HuggingFace, Cloudflare, Copilot), LM Studio, Ollama

#### `agent.py` — `MODELS` (line 69)
- Structure: `{ key: { provider, api_model, env_key, url (optional), pricing: [in, out, think] (floats) } }`
- Used by: `agent.py` itself (`compute_cost`, `DEFAULT_MODEL`, CLI entrypoint), `server.py` lazy import at line 2879 (`from agent import MODELS`)
- Contains: Groq (3 models), Mistral (2), Gemini (8), Anthropic (3), Cloudflare (1), HuggingFace (1), Ollama (3)

### Diff / divergence analysis

| Aspect | `models.py MODEL_REGISTRY` | `agent.py MODELS` |
|--------|---------------------------|-------------------|
| Pricing field | `"price": "$X/$Y per 1M tok"` (string, display only) | `"pricing": [in, out, think]` (float list, used for cost calc) |
| Capabilities | `"capabilities": {image, reasoning, tools}` | Not present |
| Context window | `"context_window": int` | Not present |
| URL | Only for some (inferred by provider) | Explicit `"url"` for Groq, Mistral, HuggingFace |
| Models in `MODEL_REGISTRY` only | LM Studio dynamic entries, Copilot | — |
| Models in `agent.py MODELS` only | — | All Groq/Mistral/HuggingFace/Cloudflare with explicit URLs |
| Ollama | Dynamic via `_discovered_local_models` | 3 static entries (`qwen3.5`, `llama3.3`, `llama3.1`) |
| `compute_cost()` | Not in `models.py` | Defined in `agent.py` (uses `MODELS["pricing"]`) |

**Gemini model overlap check (potential key differences):**
- `models.py` has: `gemini-2.0-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash`, `gemini-3.1-flash-lite`, `gemini-3-pro`, `gemini-3.1-pro`
- `agent.py` has same set plus `gemini-3.1-flash-lite` (same).
- **Pricing divergence**: `models.py` uses human-readable strings; `agent.py` uses float arrays. Both must be kept in sync after consolidation.

### Consolidation plan for `models.py`

1. **Rename `MODEL_REGISTRY` → `MODELS`** (for backward compat, keep `MODEL_REGISTRY = MODELS` alias).
2. **Merge schema**: add `pricing: list[float]` field to every entry in `models.py`, pulling values from `agent.py MODELS`.
3. **Add `compute_cost()`** to `models.py` (move from `agent.py`, same logic).
4. **Add `DEFAULT_MODEL`** to `models.py`.
5. **Remove `MODELS` dict from `agent.py`**; replace with: `from models import MODELS, compute_cost, DEFAULT_MODEL`.
6. **Fix `server.py` line 2879**: change `from agent import MODELS` → `from models import MODELS`.
7. **Keep `FALLBACK_PARSE_MODELS`** in `agent.py` (it references specific model keys; can import after `MODELS` is in `models.py`).

### Import chain after change
```
models.py
  └─ exports: MODELS, MODEL_REGISTRY (alias), LMSTUDIO_CAPABILITIES,
              compute_cost, DEFAULT_MODEL, SYSTEM_MSG, THINKING_BUDGETS,
              OLLAMA_VRAM, OLLAMA_VISION_MODELS, _discovered_local_models

agent.py
  └─ from models import MODELS, compute_cost, DEFAULT_MODEL, ...

server.py
  └─ from models import MODELS, MODEL_REGISTRY, ...  (already imports most via models.py)
  └─ REMOVE: from agent import MODELS  (line 2879 lazy import)

llm_providers.py
  └─ from models import MODEL_REGISTRY, ...  (unchanged)
```

### Tight coupling risks for 5c

1. **`agent.py` `FALLBACK_PARSE_MODELS`** (line 1008) lists specific model keys — no schema dependency, just references `MODELS.get(m)`. Safe after move.
2. **`agent.py` CLI entrypoint** (line 1450+) does `if exec_model not in MODELS` — still works after import change.
3. **`server.py` lazy import** at line 2879 is inside a function body (`batch_start`) — `from agent import MODELS` vs `from models import MODELS`. Both are equivalent after consolidation; the lazy import could be removed or changed.
4. **`pricing` float arrays vs string**: `models.py MODEL_REGISTRY` currently has `price` (string). Adding `pricing` (float list) is additive — no existing code breaks, but all callers of `compute_cost` (in `agent.py`) must be checked to confirm they use the new `models.py` version.

### Per-step verification (5c)
1. `python3 -c "from models import MODELS, compute_cost; print(compute_cost('gemini-2.5-flash', 1000, 1000))"` — should return cost float.
2. `python3 -c "from agent import MODELS; print(len(MODELS))"` — should work via re-export.
3. `python3 -c "from server import app"` — no import error.
4. Hit `/api/llm/models` endpoint — model list returns correctly.
5. Run `python3 agent.py --model gemini-2.5-flash ...` (CLI) — no crash on model lookup.

---

## 5d — LLM Provider Base Helpers in `llm_providers.py`

### Current duplication: message building

Each of the four provider call functions builds its `messages` list independently:

| Provider function | Lines | Pattern |
|------------------|-------|---------|
| `_call_openai_compatible` | 470–478 | `messages = [{"role": "system", "content": SYSTEM_MSG}, {"role": "user", "content": user_content}]` — with image branching to list |
| `_call_cloudflare` | 506–520 | Same pattern + vision-specific image block |
| `_call_ollama` | 540–547 | `messages = [{"role": "system", ...}, {"role": "user", ...}]` + image appended as `messages[-1]["images"]` |
| `_call_anthropic` | 424–435 | Uses `content_blocks` list (different schema), not `messages` list |

`_call_gemini` (line 265) uses the Google GenAI SDK `genai.types.Content` model — structurally different, does not share the OpenAI messages schema.

### Proposed `_build_messages(system, user, image_b64=None, provider="openai")` helper

```python
def _build_messages(system: str, user: str, image_b64: str | None = None,
                    provider: str = "openai") -> list[dict]:
    """
    Build a messages list for OpenAI-compatible (or Ollama) providers.
    - provider="openai": image embedded as data URL in user content list
    - provider="ollama": image appended as base64 in messages[-1]["images"]
    - provider="anthropic": NOT handled here (Anthropic uses content_blocks schema)
    - provider="gemini": NOT handled here (uses genai SDK types)
    """
```

This covers: `_call_openai_compatible`, `_call_cloudflare`, `_call_ollama`.
Does **not** replace `_call_anthropic` (different schema) or `_call_gemini` (SDK types).

### Proposed `_extract_response_text(data, provider)` helper

Each provider function extracts the response text from a different JSON schema:

| Provider function | Lines | Extraction pattern |
|------------------|-------|-------------------|
| `_call_openai_compatible` | 489–494 | `data["choices"][0]["message"]["content"]` |
| `_call_cloudflare` | 527–534 | `data.get("result", {}).get("response", "")` |
| `_call_ollama` | 548–553 | `response["message"]["content"]` (Ollama SDK object) |
| `_call_anthropic` | 451–454 | `data["content"][0]["text"]` |

```python
def _extract_response_text(data: dict, provider: str) -> str | dict:
    """
    Extract text response from provider response JSON.
    Returns str normally; returns {"text": ..., "truncated": True} on length finish.
    """
```

### Exact lines with duplication

**Message building duplication:**
- `_call_openai_compatible` lines 470–478: `if image_b64: user_content = [...]` + `messages = [system, user_content]`
- `_call_cloudflare` lines 506–515: `messages = [system, user]` + `if image_b64 and "vision" in model_name: messages[-1] = [image, text]`
- `_call_ollama` lines 540–546: `messages = [system, user]` + `if image_b64: messages[-1]["images"] = [image_b64]`
- `_call_anthropic` lines 424–435: `content_blocks = []` + image block + text block (different schema, **do not abstract with above**)

**Response extraction duplication:**
- `_call_openai_compatible` lines 489–494
- `_call_cloudflare` lines 527–534
- `_call_ollama` line 553
- `_call_anthropic` lines 451–454

### Tight coupling risks for 5d

1. **Cloudflare vision branch** (`if image_b64 and "vision" in model_name`) — special case that differs from the OpenAI-compat pattern. The `_build_messages` helper needs a `vision_model_name` arg or the Cloudflare function keeps its own branch.
2. **`_call_openai_compatible` truncation detection** (line 490–492: `if data["choices"][0].get("finish_reason") == "length"`) — `_extract_response_text` must return a dict `{"text": ..., "truncated": True}` not just a string. All callers of the extracted helper must handle both return types. This is already the case in `_route_model_call` — verify no regression.
3. **Ollama SDK object vs dict** — `_call_ollama` gets back an Ollama SDK response object, not a plain dict; `response["message"]["content"]` is an SDK accessor. `_extract_response_text` would need to handle this type difference from raw dict providers.

### Per-step verification (5d)
1. Unit test: call `_build_messages("sys", "user", None)` → confirm standard messages list.
2. Unit test: call `_build_messages("sys", "user", "<b64>", provider="ollama")` → confirm image in `messages[-1]["images"]`.
3. End-to-end: POST to `/api/llm/call` with a Groq model → confirm response parses correctly.
4. End-to-end: POST with an Anthropic model → confirm `_call_anthropic` still uses its own schema (not the shared helper).
5. Confirm Cloudflare vision path still works with `"vision"` model key.

---

## Overall Phase 5 Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| **`askLLM` (684 lines) references dozens of globals; any missed reference silently fails** | HIGH | Full grep audit of all globals before extracting; functional test immediately |
| **`toggleAutoPlay` / `undoStep` called from HTML `onclick` — must remain global after move to `session-execution.js`** | HIGH | Verify global scope; add to script load order before page becomes interactive |
| **`_extractJsonFromText` called across both RLM and Linear modules** | MEDIUM | Keep in `scaffolding.js` router; do not copy |
| **`models.py` `pricing` field schema change** — must add float arrays alongside string prices | MEDIUM | Additive field; run `compute_cost` unit tests |
| **`server.py` lazy import `from agent import MODELS`** — lazy import hides breakage until batch endpoint is called | MEDIUM | Change immediately in same PR as 5c; add integration test for `/api/batch/start` |
| **`_call_ollama` uses SDK object not dict** — `_extract_response_text` type mismatch | LOW | Keep Ollama extraction inline or add explicit type guard |

---

## Combined Script Load Order (Post-Phase-5)

```html
<script src="/static/js/state.js?v={{ static_v }}"></script>
<script src="/static/js/engine.js?v={{ static_v }}"></script>
<script src="/static/js/reasoning.js?v={{ static_v }}"></script>
<script src="/static/js/ui.js?v={{ static_v }}"></script>
<script src="/static/js/llm.js?v={{ static_v }}"></script>           <!-- timeline + token rendering only -->
<script src="/static/js/scaffolding.js?v={{ static_v }}"></script>   <!-- router: callLLM, _callLLMInner, loadModels, BYOK -->
<script src="/static/js/scaffolding-rlm.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-three-system.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-agent-spawn.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding-linear.js?v={{ static_v }}"></script>
<script src="/static/js/session-execution.js?v={{ static_v }}"></script>  <!-- askLLM, executePlan, toggleAutoPlay, undoStep -->
<script src="/static/js/session.js?v={{ static_v }}"></script>
<script src="/static/js/observatory.js?v={{ static_v }}"></script>
<script src="/static/js/human.js?v={{ static_v }}"></script>
<script src="/static/js/leaderboard.js?v={{ static_v }}"></script>
<script src="/static/js/dev.js?v={{ static_v }}"></script>
```

---

*End of Phase 5 plan. Biggest coupling risk: `askLLM` in `llm.js` is 684 lines with implicit references to ~20 globals from `state.js`, `session.js`, and DOM state — extracting it to `session-execution.js` without a comprehensive globals audit will produce silent runtime failures that only manifest during active gameplay.*
