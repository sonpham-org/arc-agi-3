# Phase 3 Implementation Plan: JS Utility Extractions

**Date:** 2026-03-10  
**Author:** Claude Sonnet 4.6 (subagent)  
**Branch:** feature/modularization (continue from Phase 2)  
**Status:** PLAN ONLY — no code changes

---

## Overview

Phase 3 extracts five categories of duplication from the JS codebase into focused utility modules. Each step is a pure refactor with zero behavioral changes.

**Files read for this plan:**
- `static/js/llm.js` (2475 lines)
- `static/js/session.js` (2528 lines)
- `static/js/scaffolding.js` (2471 lines)
- `static/js/ui.js` (1190 lines)
- `static/js/share-page.js` (690 lines)
- `static/js/state.js` (1453 lines)
- `templates/index.html` (script load order)

**Current script load order in `templates/index.html` (lines 661–671):**
```html
661: <script src="/static/js/state.js?v={{ static_v }}"></script>
662: <script src="/static/js/engine.js?v={{ static_v }}"></script>
663: <script src="/static/js/reasoning.js?v={{ static_v }}"></script>
664: <script src="/static/js/ui.js?v={{ static_v }}"></script>
665: <script src="/static/js/llm.js?v={{ static_v }}"></script>
666: <script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
667: <script src="/static/js/session.js?v={{ static_v }}"></script>
668: <script src="/static/js/observatory.js?v={{ static_v }}"></script>
669: <script src="/static/js/human.js?v={{ static_v }}"></script>
670: <script src="/static/js/leaderboard.js?v={{ static_v }}"></script>
671: <script src="/static/js/dev.js?v={{ static_v }}"></script>
```

**Note on `share-page.js`:** This file (690 lines) is NOT referenced in any HTML template — not in `templates/index.html`, `templates/share.html`, `templates/obs.html`, or anywhere else in the project. It declares globals (`COLORS`, `SESSION`, etc.) via `window.*` assignments at the top, suggesting it was intended to be loaded standalone in a share page that hasn't been wired up yet. Until it is wired up, changes to it carry no load-order risk. The plan covers it for completeness.

---

## ⚠️ Critical Pre-flight: Script Load Order Issues

Phase 3 introduces three new files that must be loaded **before** existing files that depend on them:

| New File | Must Load Before |
|---|---|
| `static/js/config/scaffolding-schemas.js` | `state.js` (line 661) |
| `static/js/utils/tokens.js` | `llm.js` (line 665), `scaffolding.js` (line 666), `session.js` (line 667) |
| `static/js/utils/json-parsing.js` | `scaffolding.js` (line 666) |
| `static/js/rendering/grid-renderer.js` | `ui.js` (line 664) |

**Required new load order (lines 661–671 become lines 661–675):**
```html
661: <script src="/static/js/config/scaffolding-schemas.js?v={{ static_v }}"></script>  ← NEW (before state.js)
662: <script src="/static/js/state.js?v={{ static_v }}"></script>
663: <script src="/static/js/engine.js?v={{ static_v }}"></script>
664: <script src="/static/js/reasoning.js?v={{ static_v }}"></script>
665: <script src="/static/js/utils/tokens.js?v={{ static_v }}"></script>               ← NEW (before ui.js, llm.js, scaffolding.js)
666: <script src="/static/js/rendering/grid-renderer.js?v={{ static_v }}"></script>    ← NEW (before ui.js)
667: <script src="/static/js/ui.js?v={{ static_v }}"></script>
668: <script src="/static/js/utils/json-parsing.js?v={{ static_v }}"></script>          ← NEW (before llm.js, scaffolding.js)
669: <script src="/static/js/llm.js?v={{ static_v }}"></script>
670: <script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
671: <script src="/static/js/session.js?v={{ static_v }}"></script>
672: <script src="/static/js/observatory.js?v={{ static_v }}"></script>
673: <script src="/static/js/human.js?v={{ static_v }}"></script>
674: <script src="/static/js/leaderboard.js?v={{ static_v }}"></script>
675: <script src="/static/js/dev.js?v={{ static_v }}"></script>
```

> **Note:** `tokens.js` must be before `ui.js` (not just before `llm.js`) because `formatTokenInfo` calls `estimateTokens`, and `ui.js` may be refactored to call token utilities in a future phase. Being conservative and placing it after `reasoning.js` is safe.

---

## Step 3a: Create `static/js/utils/tokens.js`

### What it extracts

Token pricing constants, estimation, and cost-tracking from `llm.js` and `scaffolding.js`.

### Source: `static/js/llm.js`

**Extract lines 115–136** (the `estimateTokens` function and `TOKEN_PRICES` constant):

```
115: function estimateTokens(text) {
116:   if (!text) return 0;
117:   return Math.ceil(text.length / 4);
118: }
119: (blank)
120: // Per-1M-token pricing (input/output) — rough lookup
121: const TOKEN_PRICES = {
122:   // [input $/1M tok, output $/1M tok]
123:   'gemini-3.1-pro': [2.0, 12.0],
124:   'gemini-3-pro': [2.0, 12.0],
125:   'gemini-3-flash': [0.50, 3.0],
126:   'gemini-2.5-pro': [1.25, 10.0],
127:   'gemini-2.5-flash': [0.30, 2.50],
128:   'gemini-2.5-flash-lite': [0.10, 0.40],
129:   'gemini-2.0-flash': [0.10, 0.40],
130:   'gemini-2.0-flash-lite': [0.075, 0.30],
131:   'claude-sonnet-4-6': [3.0, 15.0],
132:   'claude-sonnet-4-5': [3.0, 15.0],
133:   'claude-haiku-4-5': [0.80, 4.0],
134:   'gpt-4o': [2.50, 10.0],
135:   'gpt-4o-mini': [0.15, 0.60],
136: };
```

**Extract lines 601–633** (the `formatTokenInfo` function):

```
601: function formatTokenInfo(resp, tokensObj) {
602:   // Use API-reported usage if available
603:   const tokens = tokensObj || sessionTotalTokens;
...
633: }
```

> **Note on `estimateTokens` in `session.js`:** The original modularization audit (2026-03-10 plan) listed `estimateTokens` as duplicated in both `llm.js` and `session.js`. Upon inspection, `session.js` does NOT define its own `estimateTokens` — it relies on the global from `llm.js`. No duplicate to remove there.

### ⚠️ Divergence: `formatTokenInfo` vs `_asTrackUsage`

The task brief asks to "unify `formatTokenInfo` with `_asTrackUsage`." These two functions are **NOT interchangeable**:

| Property | `formatTokenInfo` (llm.js:601) | `_asTrackUsage` (scaffolding.js:1792) |
|---|---|---|
| Signature | `(resp, tokensObj)` | `(model, rawText)` — inner function, closes over `_asTokens` |
| Input token source | `resp.usage` object | `callLLM._lastUsage` global sideband |
| Input estimation | From `resp.prompt_length` | Direct `rawText.length / 4` for both in/out |
| Output | Returns HTML string | Returns `{input_tokens, output_tokens, cost}` object |
| Side effect | Updates `tokensObj` | Clears `callLLM._lastUsage = null` |
| Scope | Module-level function | Inner function (defined inside `askLLMAgentSpawn`) |

**Recommendation:** Extract both to `tokens.js` unchanged. `_asTrackUsage` becomes `trackTokenUsage(model, rawText, tokensAccumulator)` where `tokensAccumulator` is passed in instead of closed over. `formatTokenInfo` stays as-is. A true unification of their logic is Phase 4 work after behavioral tests are in place.

### `_asTrackUsage` location

`_asTrackUsage` is defined **inside** `async function askLLMAgentSpawn(...)` at scaffolding.js line 1778. It begins at line 1792:

```
1778: async function askLLMAgentSpawn(_cur, model, ...) {
...
1791:   const _asTokens = _cur.sessionTotalTokens || sessionTotalTokens;
1792:   function _asTrackUsage(model, rawText) {
...
1807:   }
```

To extract it, `_asTrackUsage` must be refactored to accept `tokensAccumulator` as a parameter (replacing closure over `_asTokens`). All 3 call sites within `askLLMAgentSpawn` pass in `_asTokens`.

Call sites in scaffolding.js:
- Line 1966: `const orchUsage = _asTrackUsage(orchModel, raw || '');`
- Line 2069: `const subUsage = _asTrackUsage(subModel, subRaw || '');`
- One more near line 2100 (confirm with grep before implementing)

### Full content of `static/js/utils/tokens.js`

```javascript
// ═══════════════════════════════════════════════════════════════════════════
// TOKENS UTILITY
// Extracted from llm.js and scaffolding.js — Phase 3 modularization
// Load order: must be loaded before llm.js, scaffolding.js, session.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Rough token count estimate: 1 token ≈ 4 characters.
 * @param {string} text
 * @returns {number}
 */
function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}

/**
 * Per-1M-token pricing table [input $/1M, output $/1M].
 * Source: llm.js lines 121–136.
 */
const TOKEN_PRICES = {
  'gemini-3.1-pro': [2.0, 12.0],
  'gemini-3-pro': [2.0, 12.0],
  'gemini-3-flash': [0.50, 3.0],
  'gemini-2.5-pro': [1.25, 10.0],
  'gemini-2.5-flash': [0.30, 2.50],
  'gemini-2.5-flash-lite': [0.10, 0.40],
  'gemini-2.0-flash': [0.10, 0.40],
  'gemini-2.0-flash-lite': [0.075, 0.30],
  'claude-sonnet-4-6': [3.0, 15.0],
  'claude-sonnet-4-5': [3.0, 15.0],
  'claude-haiku-4-5': [0.80, 4.0],
  'gpt-4o': [2.50, 10.0],
  'gpt-4o-mini': [0.15, 0.60],
};

/**
 * Format token usage as an HTML info line for display in the reasoning panel.
 * Accumulates totals into `tokensObj` (or the global `sessionTotalTokens` if omitted).
 * Source: llm.js lines 601–633.
 *
 * @param {object} resp - LLM response object with .usage, .model, .prompt_length, .raw, .thinking
 * @param {object} [tokensObj] - Accumulator {input, output, cost}; defaults to sessionTotalTokens
 * @returns {string} HTML string or ''
 */
function formatTokenInfo(resp, tokensObj) {
  const tokens = tokensObj || sessionTotalTokens;
  let inputTok = resp.usage?.input_tokens || resp.usage?.prompt_tokens || 0;
  let outputTok = resp.usage?.output_tokens || resp.usage?.completion_tokens || 0;

  if (!inputTok && resp.prompt_length > 0) inputTok = Math.ceil(resp.prompt_length / 4);
  if (!outputTok) outputTok = estimateTokens(resp.raw || '');
  if (resp.thinking) outputTok += estimateTokens(resp.thinking);

  const totalTok = inputTok + outputTok;
  if (!totalTok) return '';

  const model = resp.model || '';
  const prices = TOKEN_PRICES[model] || null;
  let costStr = '';
  if (prices) {
    const cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
    tokens.input += inputTok;
    tokens.output += outputTok;
    tokens.cost += cost;
    costStr = ` · $${cost.toFixed(4)} (session: $${tokens.cost.toFixed(3)})`;
  } else {
    tokens.input += inputTok;
    tokens.output += outputTok;
  }

  return `<div style="font-size:10px;color:var(--text-dim);margin-bottom:2px;">` +
    `${inputTok.toLocaleString()} in + ${outputTok.toLocaleString()} out = ${totalTok.toLocaleString()} tok${costStr}</div>`;
}

/**
 * Track token usage for a single LLM call (used by agent_spawn scaffolding).
 * Reads usage from callLLM._lastUsage sideband, clears it, accumulates into tokensAccumulator.
 * Source: scaffolding.js _asTrackUsage (inner function, lines 1792–1807).
 *
 * NOTE: This replaces the inner `_asTrackUsage` closure. Callers must pass `tokensAccumulator`
 * explicitly (was previously closed over as `_asTokens`).
 *
 * @param {string} model - Model name for price lookup
 * @param {string} rawText - Raw response text (for fallback estimation)
 * @param {object} tokensAccumulator - {input, output, cost} accumulator to update in place
 * @returns {{input_tokens: number, output_tokens: number, cost: number}}
 */
function trackTokenUsage(model, rawText, tokensAccumulator) {
  const usage = callLLM._lastUsage;
  let inputTok = usage?.input_tokens || 0;
  let outputTok = usage?.output_tokens || 0;
  if (!inputTok && rawText) inputTok = Math.ceil(rawText.length / 4);
  if (!outputTok && rawText) outputTok = Math.ceil(rawText.length / 4);
  tokensAccumulator.input += inputTok;
  tokensAccumulator.output += outputTok;
  const prices = TOKEN_PRICES[model] || null;
  let cost = 0;
  if (prices) {
    cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
    tokensAccumulator.cost += cost;
  }
  callLLM._lastUsage = null;
  return { input_tokens: inputTok, output_tokens: outputTok, cost };
}
```

### Changes to source files

#### `static/js/llm.js`

| Action | Lines | Detail |
|---|---|---|
| DELETE | 115–118 | `function estimateTokens(...)` body (4 lines) |
| DELETE | 120–136 | `TOKEN_PRICES` constant (17 lines) |
| DELETE | 601–633 | `function formatTokenInfo(...)` (33 lines) |

> After deletion, all references to `estimateTokens`, `TOKEN_PRICES`, `formatTokenInfo` in `llm.js` continue to work because `tokens.js` is loaded first and these become globals.

Remaining references in `llm.js` that use these (do not remove):
- Line 610: `outputTok = estimateTokens(resp.raw || '')`
- Line 611: `if (resp.thinking) outputTok += estimateTokens(resp.thinking)`
- Line 618: `const prices = TOKEN_PRICES[model] || null`
- Line 1146: `const histTokenEst = estimateTokens(JSON.stringify(_cur.moveHistory))`
- Lines 1408, 1694: `formatTokenInfo(resp, _cur.sessionTotalTokens)`

#### `static/js/scaffolding.js`

| Action | Lines | Detail |
|---|---|---|
| DELETE | 1792–1807 | Inner `function _asTrackUsage(model, rawText)` definition |
| DELETE | 1791 | `const _asTokens = ...` line — move into call sites or keep as local var, do NOT delete if still used by other things in scope |
| UPDATE | 1966 | Change `_asTrackUsage(orchModel, raw || '')` → `trackTokenUsage(orchModel, raw || '', _asTokens)` |
| UPDATE | 2069 | Change `_asTrackUsage(subModel, subRaw || '')` → `trackTokenUsage(subModel, subRaw || '', _asTokens)` |
| UPDATE | any other call sites | Same pattern — verify with grep before implementing |

> `_asTokens` remains as a local variable in `askLLMAgentSpawn`; only the inner function definition is deleted.

#### `templates/index.html`

Add before `state.js` (insert before line 661):
```html
<script src="/static/js/utils/tokens.js?v={{ static_v }}"></script>
```

Wait — `tokens.js` references `sessionTotalTokens` (in `formatTokenInfo`) and `callLLM._lastUsage` (in `trackTokenUsage`). These are globals defined in `llm.js`. Since we're using plain `<script>` globals and `formatTokenInfo`/`trackTokenUsage` are only *called* after `llm.js` has run, the file just needs to define the functions — the references are resolved at call time, not at parse time. So **`tokens.js` can be loaded anywhere before the first caller**, which is `llm.js` itself.

**Confirmed safe placement: after `reasoning.js` (line 663), before `ui.js` (line 664).**

### Verification

```bash
# Confirm no remaining definition of TOKEN_PRICES or estimateTokens in llm.js
grep -n "^const TOKEN_PRICES\|^function estimateTokens" static/js/llm.js
# Should return nothing

# Confirm TOKEN_PRICES used (but not defined) in session.js
grep -n "TOKEN_PRICES" static/js/session.js

# Confirm no _asTrackUsage inner function definition left
grep -n "function _asTrackUsage" static/js/scaffolding.js
# Should return nothing

# Confirm call sites updated
grep -n "trackTokenUsage\|_asTrackUsage" static/js/scaffolding.js

# Smoke test: open app in browser, run one LLM call, check token display in reasoning panel
```

---

## Step 3b: Create `static/js/utils/json-parsing.js`

### What it extracts

JSON extraction and LLM response parsing from `scaffolding.js`.

### Source: `static/js/scaffolding.js`

**Extract lines 402–410** (`_rlmFindFinal`):
```javascript
function _rlmFindFinal(text) {
  if (typeof text !== 'string') return null;
  // Strip code blocks before checking for FINAL
  const stripped = text.replace(/```repl\s*\n[\s\S]*?\n```/g, '');
  // Check for FINAL(...)
  const finalMatch = stripped.match(/^\s*FINAL\((.+)\)\s*$/ms);
  if (finalMatch) return finalMatch[1].trim();
  return null;
}
```

**Extract lines 412–435** (`_extractJsonFromText`):
```javascript
function _extractJsonFromText(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  // Balanced-brace JSON extraction (same logic as parseClientLLMResponse)
  const cleaned = text.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan || parsed.actions || parsed.command) return parsed;
        } catch {}
        break;
      }}
    }
  }
  return null;
}
```

**Extract lines 2338–2374** (`parseClientLLMResponse`):
```javascript
function parseClientLLMResponse(content, modelName) {
  let thinking = '';
  const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/);
  if (thinkMatch) {
    thinking = thinkMatch[1].trim();
    content = content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  }
  const cleaned = content.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan) {
            return { raw: content, thinking: thinking ? thinking.substring(0, 500) : null, parsed, model: modelName };
          }
        } catch {}
        break;
      }}
    }
  }
  return { raw: content, parsed: null, model: modelName };
}
```

### ⚠️ Divergence: `_extractJsonFromText` vs `parseClientLLMResponse`

Both functions use identical balanced-brace JSON extraction logic with comment stripping. They differ only in:
- `_extractJsonFromText` checks for `parsed.action !== undefined || parsed.plan || parsed.actions || parsed.command`
- `parseClientLLMResponse` checks `parsed.action !== undefined || parsed.plan` (narrower)
- `parseClientLLMResponse` also strips `<think>...</think>` blocks and wraps the result in a response envelope

These are **distinct functions, not duplicates**. They should remain as separate exported functions in `json-parsing.js`.

### Full content of `static/js/utils/json-parsing.js`

```javascript
// ═══════════════════════════════════════════════════════════════════════════
// JSON PARSING UTILITY
// Extracted from scaffolding.js — Phase 3 modularization
// Load order: must be loaded before scaffolding.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Find a FINAL(...) marker in RLM response text.
 * Strips repl code blocks before searching.
 * Source: scaffolding.js _rlmFindFinal, lines 402–410.
 *
 * @param {string} text
 * @returns {string|null} Content inside FINAL(...), or null
 */
function findFinalMarker(text) {
  if (typeof text !== 'string') return null;
  const stripped = text.replace(/```repl\s*\n[\s\S]*?\n```/g, '');
  const finalMatch = stripped.match(/^\s*FINAL\((.+)\)\s*$/ms);
  if (finalMatch) return finalMatch[1].trim();
  return null;
}

/**
 * Extract a valid JSON action/command object from LLM response text.
 * Uses balanced-brace matching after stripping line comments.
 * Accepts objects with keys: action, plan, actions, or command.
 * Source: scaffolding.js _extractJsonFromText, lines 412–435.
 *
 * @param {string|*} text - Response text (non-strings are JSON.stringify'd)
 * @returns {object|null} Parsed JSON object, or null
 */
function extractJsonFromText(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  const cleaned = text.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          try {
            const parsed = JSON.parse(cleaned.substring(i, j + 1));
            if (parsed.action !== undefined || parsed.plan || parsed.actions || parsed.command) return parsed;
          } catch {}
          break;
        }
      }
    }
  }
  return null;
}

/**
 * Parse a client-side LLM response string into a structured response envelope.
 * Extracts <think>...</think> blocks, then finds the JSON action/plan object.
 * Source: scaffolding.js parseClientLLMResponse, lines 2338–2374.
 *
 * @param {string} content - Raw LLM response text
 * @param {string} modelName - Model name (passed through to result)
 * @returns {{raw: string, thinking: string|null, parsed: object|null, model: string}}
 */
function parseLLMResponse(content, modelName) {
  let thinking = '';
  const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/);
  if (thinkMatch) {
    thinking = thinkMatch[1].trim();
    content = content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  }
  const cleaned = content.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          try {
            const parsed = JSON.parse(cleaned.substring(i, j + 1));
            if (parsed.action !== undefined || parsed.plan) {
              return { raw: content, thinking: thinking ? thinking.substring(0, 500) : null, parsed, model: modelName };
            }
          } catch {}
          break;
        }
      }
    }
  }
  return { raw: content, parsed: null, model: modelName };
}
```

### Changes to source files

#### `static/js/scaffolding.js`

| Action | Lines | Detail |
|---|---|---|
| DELETE | 402–410 | `function _rlmFindFinal(text)` — replaced by global `findFinalMarker` |
| DELETE | 412–435 | `function _extractJsonFromText(text)` — replaced by global `extractJsonFromText` |
| DELETE | 2338–2374 | `function parseClientLLMResponse(content, modelName)` — replaced by global `parseLLMResponse` |
| UPDATE | 441 | Change `_extractJsonFromText(finalAnswer)` → `extractJsonFromText(finalAnswer)` |
| UPDATE | 449 | Change `_extractJsonFromText(lastResp)` → `extractJsonFromText(lastResp)` |
| UPDATE | 809 | Change `_rlmFindFinal(responseText)` → `findFinalMarker(responseText)` |
| UPDATE | 979, 1060, 1130, 1296, 1967, 2071 | Change `_extractJsonFromText(raw)` → `extractJsonFromText(raw)` |

> `parseClientLLMResponse` is called externally (from other files). If any JS file calls it by the old name, add an alias: `const parseClientLLMResponse = parseLLMResponse;` at the bottom of `json-parsing.js` until all callers are updated.

Check callers:
```bash
grep -rn "parseClientLLMResponse" static/js/
```

#### `templates/index.html`

Add after `reasoning.js` and `tokens.js`, before `ui.js`:
```html
<script src="/static/js/utils/json-parsing.js?v={{ static_v }}"></script>
```

See the consolidated load order in the Pre-flight section above.

### Verification

```bash
# No remaining definition of these functions in scaffolding.js
grep -n "^function _rlmFindFinal\|^function _extractJsonFromText\|^function parseClientLLMResponse" static/js/scaffolding.js
# Should return nothing

# All call sites updated
grep -n "_rlmFindFinal\|_extractJsonFromText" static/js/scaffolding.js
# Should return nothing

# New functions exist
grep -n "^function findFinalMarker\|^function extractJsonFromText\|^function parseLLMResponse" static/js/utils/json-parsing.js

# Run RLM scaffolding in browser — FINAL() parsing and JSON extraction must work
```

---

## Step 3c: Create `static/js/rendering/grid-renderer.js`

### What it extracts

`renderGrid()` and `renderGridWithChanges()` from `ui.js` and `share-page.js`.

### ⚠️ DIVERGENCE FOUND — These functions are NOT identical

| Aspect | `ui.js` | `share-page.js` |
|---|---|---|
| `renderGrid` sets `currentGrid` | **Yes** (line 240: `currentGrid = grid;`) | **No** |
| `renderGridWithChanges` early exit | **Yes** — exits if `document.getElementById('showChanges').checked` is false | **No** — always renders |
| `renderGridWithChanges` color source | DOM elements `changeOpacity`, `changeColor` (read each call) | Module-level vars `diffOpacity`, `diffColor` |
| `renderGridWithChanges` stroke outline | **Yes** — draws `strokeRect` for each changed cell | **No** — only `fillRect` |

These are **meaningfully different functions** sharing a common core. A naïve copy would break one or both.

**Recommended approach:** Create `grid-renderer.js` with the common core, plus parameters for the differing behavior:

### Full content of `static/js/rendering/grid-renderer.js`

```javascript
// ═══════════════════════════════════════════════════════════════════════════
// GRID RENDERER
// Extracted from ui.js and share-page.js — Phase 3 modularization
// Load order: must be loaded before ui.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Render a grid onto a canvas element.
 * Source: ui.js lines 238–251 / share-page.js lines 288–299.
 *
 * The `ui.js` version also sets the module-level `currentGrid = grid`.
 * That side effect is intentionally NOT included here; ui.js's wrapper does it.
 *
 * @param {number[][]} grid - 2D array of color indices
 * @param {HTMLCanvasElement} targetCanvas - Canvas to draw on
 * @param {CanvasRenderingContext2D} targetCtx - Canvas 2D context
 * @param {object} colors - Color index → CSS color string map
 */
function renderGridOnCanvas(grid, targetCanvas, targetCtx, colors) {
  if (!grid || !grid.length) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  targetCanvas.width = w * scale;
  targetCanvas.height = h * scale;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      targetCtx.fillStyle = colors[grid[y][x]] || '#000';
      targetCtx.fillRect(x * scale, y * scale, scale, scale);
    }
  }
}

/**
 * Render a grid with change highlights.
 * Source: ui.js lines 253–271 / share-page.js lines 302–320.
 *
 * @param {number[][]} grid
 * @param {object} changeMap - {changes: [{x, y}, ...]}
 * @param {HTMLCanvasElement} targetCanvas
 * @param {CanvasRenderingContext2D} targetCtx
 * @param {object} colors
 * @param {object} opts - Rendering options:
 *   opts.opacity {number} - 0–1 fill opacity
 *   opts.color {string} - Hex highlight color e.g. '#ff0000'
 *   opts.stroke {boolean} - Whether to draw stroke outline (ui.js=true, share-page.js=false)
 *   opts.enabled {boolean} - If false, skip highlights (used by ui.js checkbox check)
 */
function renderGridWithChangesOnCanvas(grid, changeMap, targetCanvas, targetCtx, colors, opts = {}) {
  renderGridOnCanvas(grid, targetCanvas, targetCtx, colors);
  if (!changeMap?.changes?.length) return;
  if (opts.enabled === false) return;
  const h = grid.length, w = grid[0].length;
  const scale = Math.floor(512 / Math.max(h, w));
  const opacity = opts.opacity ?? 0.4;
  const color = opts.color ?? '#ff0000';
  const r = parseInt(color.slice(1,3), 16);
  const g = parseInt(color.slice(3,5), 16);
  const b = parseInt(color.slice(5,7), 16);
  targetCtx.fillStyle = `rgba(${r},${g},${b},${opacity})`;
  for (const c of changeMap.changes) targetCtx.fillRect(c.x * scale, c.y * scale, scale, scale);
  if (opts.stroke) {
    targetCtx.strokeStyle = `rgba(${r},${g},${b},${Math.min(opacity + 0.3, 1)})`;
    targetCtx.lineWidth = 1;
    for (const c of changeMap.changes) targetCtx.strokeRect(c.x * scale + 0.5, c.y * scale + 0.5, scale - 1, scale - 1);
  }
}
```

### Changes to source files

#### `static/js/ui.js`

Replace `renderGrid` (lines 238–251) with a thin wrapper:
```javascript
function renderGrid(grid) {
  if (!grid || !grid.length) return;
  currentGrid = grid;  // ui.js-specific side effect
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
}
```

Replace `renderGridWithChanges` (lines 253–271) with:
```javascript
function renderGridWithChanges(grid, changeMap) {
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
  const enabled = document.getElementById('showChanges').checked;
  const opacity = parseInt(document.getElementById('changeOpacity').value) / 100;
  const color = document.getElementById('changeColor').value;
  renderGridWithChangesOnCanvas(grid, changeMap, canvas, ctx, COLORS, { opacity, color, stroke: true, enabled });
}
```

> **Note:** The wrapper re-calls `renderGridOnCanvas` via `renderGridWithChangesOnCanvas`, which internally calls `renderGridOnCanvas`. This means the base grid renders twice in `renderGridWithChanges`. To avoid this, `renderGridWithChanges` should call `renderGridOnCanvas` directly first, then call only the highlights portion. This is a minor optimization; correct behavior is preserved either way. The simplest safe approach is to keep `renderGridWithChanges` calling `renderGridWithChangesOnCanvas` as above (double render is imperceptible for ARC grids).

#### `static/js/share-page.js`

Replace `renderGrid` (lines 288–299):
```javascript
function renderGrid(grid) {
  if (!grid || !grid.length) return;
  renderGridOnCanvas(grid, canvas, ctx, COLORS);
}
```

Replace `renderGridWithChanges` (lines 302–320):
```javascript
function renderGridWithChanges(grid, changeMap) {
  renderGridWithChangesOnCanvas(grid, changeMap, canvas, ctx, COLORS, {
    opacity: diffOpacity,
    color: diffColor,
    stroke: false,
  });
}
```

> **share-page.js load order:** This file is currently NOT referenced in any template. When it is wired up, ensure `grid-renderer.js` is loaded before `share-page.js` in that template's script tags. The `canvas`, `ctx`, `COLORS`, `diffOpacity`, `diffColor` references are module-level vars in `share-page.js` — no changes needed there.

#### `templates/index.html`

Add before `ui.js` (line 664):
```html
<script src="/static/js/rendering/grid-renderer.js?v={{ static_v }}"></script>
```

### Verification

```bash
# No remaining full renderGrid implementation in ui.js or share-page.js
grep -n "canvas.width = w \* scale" static/js/ui.js static/js/share-page.js
# Should return nothing (the impl is now in grid-renderer.js)

# New file exists and has both functions
grep -n "^function" static/js/rendering/grid-renderer.js

# Browser smoke test: load a game, verify grid renders, enable diff overlay, make a move
# share-page.js: once wired up, load a share URL and verify replay rendering
```

---

## Step 3d: Create `static/js/config/scaffolding-schemas.js`

### What it extracts

`SCAFFOLDING_SCHEMAS` constant from `state.js`. The constant is **438 lines** (lines 87–524), not the ~300 estimated in the original plan.

### Source: `static/js/state.js`

**Lines 87–524** — the entire `SCAFFOLDING_SCHEMAS` constant declaration:
```
87:  const SCAFFOLDING_SCHEMAS = {
88:    linear: {
89:      id: 'linear',
...
524:  };
```

Internal references within `state.js` that use `SCAFFOLDING_SCHEMAS` (these continue to work via global after extraction):
- Line 529: `const schema = SCAFFOLDING_SCHEMAS[schemaId];`
- Lines 541–542: `for (const key of Object.keys(SCAFFOLDING_SCHEMAS))`
- Line 591: `if (!SCAFFOLDING_SCHEMAS[schemaId]) return;`
- Line 764: `const schema = SCAFFOLDING_SCHEMAS[activeScaffoldingType];`

### Full content of `static/js/config/scaffolding-schemas.js`

```javascript
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING SCHEMAS CONFIG
// Extracted from state.js lines 87–524 — Phase 3 modularization
// Load order: must be loaded before state.js
// ═══════════════════════════════════════════════════════════════════════════

// [PASTE VERBATIM: state.js lines 87–524]
// This is a straight cut-and-paste of the SCAFFOLDING_SCHEMAS constant.
// No changes to the content. Lines 87–524 of state.js become this file's body.
const SCAFFOLDING_SCHEMAS = {
  // ... [438 lines verbatim from state.js lines 88–524] ...
};
```

> **Implementation note:** Do not retype the schema. Copy lines 87–524 verbatim from `state.js` into the new file. The schema contains complex nested objects for all scaffolding types (linear, rlm, three_system, two_system, agent_spawn). Any transcription error will break the settings UI for that scaffolding type.

### Changes to source files

#### `static/js/state.js`

| Action | Lines | Detail |
|---|---|---|
| DELETE | 87–524 | Entire `const SCAFFOLDING_SCHEMAS = { ... };` block (438 lines) |

After deletion, lines 529+ shift up by 437 lines (new line numbers: old 529 becomes new 92, etc.). All `SCAFFOLDING_SCHEMAS` references remain valid because the constant is now a global from the pre-loaded `scaffolding-schemas.js`.

#### `templates/index.html`

Add before `state.js` (before current line 661):
```html
<script src="/static/js/config/scaffolding-schemas.js?v={{ static_v }}"></script>
```

### Verification

```bash
# SCAFFOLDING_SCHEMAS no longer defined in state.js
grep -n "^const SCAFFOLDING_SCHEMAS" static/js/state.js
# Should return nothing

# New file defines it
grep -n "^const SCAFFOLDING_SCHEMAS" static/js/config/scaffolding-schemas.js
# Should return: 1: const SCAFFOLDING_SCHEMAS = {

# All scaffolding types still render settings panel in browser
# Load app → switch between linear / rlm / three_system / two_system / agent_spawn
# Verify settings panel renders for each without console errors
```

---

## Step 3e: Consolidate Template Fill in `scaffolding.js`

### What it changes

Two template-fill functions in `scaffolding.js` that the task brief describes as "identical." Upon inspection, they are **NOT identical** and cannot be trivially merged.

### Source: `static/js/scaffolding.js`

**`_tsTemplateFill`** — lines 877–880:
```javascript
function _tsTemplateFill(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, key) => vars[key] !== undefined ? vars[key] : '')
                 .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}
```

**`_asFill`** — lines 1770–1773:
```javascript
function _asFill(template, vars) {
  let s = template;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll('{' + k + '}', String(v));
  return s;
}
```

### ⚠️ DIVERGENCE: These functions differ in behavior

| Property | `_tsTemplateFill` | `_asFill` |
|---|---|---|
| Replacement method | Regex `/\{(\w+)\}/g` | `String.replaceAll('{key}', val)` |
| Missing key behavior | Replaces with `''` | Leaves `{key}` in place (replaceAll skips missing entries) |
| Literal brace escaping | **Yes** — `{{` → `{`, `}}` → `}` | **No** |
| Value coercion | `vars[key]` (may be non-string) | `String(v)` (explicit string coercion) |

**The `{{`/`}}` escape support in `_tsTemplateFill` is used by the TS system templates.** Removing it would corrupt any template string containing literal `{{` or `}}`. Check all usages:

```bash
grep -n "{{" static/js/scaffolding.js | grep -v "^[0-9]*:\s*//" | head -20
```

### Usage analysis

`_tsTemplateFill` call sites (all in scaffolding.js, TS system):
- Lines 1036, 1117, 1222, 1223, 1278, 1279

`_asFill` call sites (all in scaffolding.js, AS system):
- Lines 1934, 2058 (and possibly more — grep before implementing)

### Recommendation: Keep both, document them

Given the behavioral differences and risk of template corruption, **do not delete either function in Phase 3**. Instead:

1. Add a comment above each explaining why they differ
2. Plan Phase 4 to analyze whether `_tsTemplateFill` templates actually contain `{{`/`}}` sequences (if not, they could be unified)

**Changes to make in Phase 3 (safe, low-risk):**

```javascript
// In scaffolding.js, replace line 877–880 with:
/**
 * Template fill for Three-System (TS) prompts.
 * Supports {{/}} escaping for literal brace output.
 * NOTE: Do NOT replace with _asFill — _asFill lacks {{ }} escape support.
 */
function _tsTemplateFill(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, key) => vars[key] !== undefined ? vars[key] : '')
                 .replace(/\{\{/g, '{').replace(/\}\}/g, '}');
}

// In scaffolding.js, replace line 1770–1773 with:
/**
 * Template fill for Agent-Spawn (AS) prompts.
 * Uses replaceAll with explicit String() coercion.
 * NOTE: Does not support {{/}} escaping. Do NOT replace with _tsTemplateFill
 * without verifying no AS templates need literal { } output.
 */
function _asFill(template, vars) {
  let s = template;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll('{' + k + '}', String(v));
  return s;
}
```

This documents the divergence clearly for whoever tackles true consolidation later.

### If consolidation is required by Phase 3 scope

If the requirement is to **keep one and delete the other**, the safer choice is to keep `_tsTemplateFill` (superset) and replace `_asFill` with a wrapper:

```javascript
// Replace _asFill body (lines 1770–1773) with:
function _asFill(template, vars) {
  // Wrapper: delegates to _tsTemplateFill. AS templates do not use {{ or }}.
  const strVars = Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, String(v)]));
  return _tsTemplateFill(template, strVars);
}
```

**Risk:** If any AS template string happens to contain `{{` or `}}`, the output changes. Verify before merging:
```bash
# Check AS prompt templates for {{ or }}
grep -n "AS_\|const AS" static/js/scaffolding.js | head -30
# Then grep for {{ in those template strings
```

### Verification

```bash
# Both functions still exist (or _asFill wrapper exists if consolidated)
grep -n "_tsTemplateFill\|_asFill" static/js/scaffolding.js

# TS system: run three_system scaffolding, verify prompts render without literal {key} appearing
# AS system: run agent_spawn scaffolding, verify subagent prompts render correctly
```

---

## Summary Table

| Step | New File | Source Lines Extracted | Index.html Changes | Key Divergences |
|---|---|---|---|---|
| 3a | `utils/tokens.js` | llm.js:115–136, 601–633; scaffolding.js:1792–1807 | Add before ui.js | `_asTrackUsage` is inner closure, not standalone; `estimateTokens` NOT in session.js |
| 3b | `utils/json-parsing.js` | scaffolding.js:402–435, 2338–2374 | Add before llm.js | `_extractJsonFromText` checks `.actions`/`.command` too; `parseLLMResponse` wraps with envelope |
| 3c | `rendering/grid-renderer.js` | ui.js:238–271; share-page.js:288–320 | Add before ui.js | Significant divergence in `renderGridWithChanges` (DOM vs vars, stroke vs no stroke, checkbox gating) |
| 3d | `config/scaffolding-schemas.js` | state.js:87–524 (438 lines, not ~300) | Add before state.js | None — verbatim copy |
| 3e | (none) | scaffolding.js:877–880, 1770–1773 | None | NOT identical — `_tsTemplateFill` has `{{`/`}}` escaping; `_asFill` does not |

## Critical Notes for Implementer

1. **Load order is the highest-risk part.** Getting a script loaded after a dependent will produce silent "X is not defined" errors at runtime. Follow the consolidated load order in the Pre-flight section exactly.

2. **`share-page.js` has no template.** It's not loaded anywhere. Don't block on it. Update it for correctness, but don't add a `<script>` tag for it until a template wires it up.

3. **`SCAFFOLDING_SCHEMAS` is 438 lines, not ~300.** The original plan underestimated. Copy verbatim — do not retype.

4. **`_tsTemplateFill` and `_asFill` are NOT identical.** Do not delete one without checking that no TS template contains `{{` or `}}` literal sequences that the AS-style implementation would corrupt.

5. **`_asTrackUsage` is an inner function** dependent on closure over `_asTokens` and `callLLM._lastUsage`. When extracted to `trackTokenUsage`, the `tokensAccumulator` parameter replaces the closure, and all call sites in `askLLMAgentSpawn` must be updated to pass `_asTokens` explicitly.
