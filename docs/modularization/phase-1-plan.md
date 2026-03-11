# Phase 1 Modularization Plan — Quick Wins

**Status:** Documentation only. No code changes in this doc.  
**Date:** 2026-03-10  
**Scope:** 5 targeted changes to eliminate duplication and dead code.  
**Files surveyed:**  
- `server.py`, `agent.py`, `models.py`, `llm_providers.py` (Python)  
- `static/js/llm.js`, `static/js/scaffolding.js`, `static/js/obs-page.js`,  
  `static/js/observatory.js`, `static/js/reasoning.js`, `static/js/share-page.js`

---

## Step 1a — Create `constants.py`

### What & Why

Three Python files define overlapping constant dicts:

| Symbol | `server.py` | `agent.py` | `models.py` |
|---|---|---|---|
| `COLOR_NAMES` | lines 398–404 | lines 32–38 | — |
| `COLOR_MAP` | lines 391–397 | — (not present) | — |
| `ACTION_NAMES` | lines 405–409 | lines 39–43 | — |
| `ARC_AGI3_DESCRIPTION` | line 410 (read_text) | line 44 (read_text) | — |
| `SYSTEM_MSG` | imported from `models.py` | lines 46–49 (own copy) | lines 16–19 |

**Key divergence found — `SYSTEM_MSG`:**

```python
# models.py (lines 16–19) — "agent" present:
SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)

# agent.py (lines 46–49) — "agent" missing, slightly shorter phrasing:
SYSTEM_MSG = (
    "You are an expert puzzle-solving AI. Analyse game grids and output ONLY "
    "valid JSON — no markdown, no explanation outside JSON."
)
```

The two copies have drifted. The `models.py` version is the server's canonical copy (imported by `server.py`). The `agent.py` copy is the CLI agent's — it's missing the word "agent" and has slightly different whitespace. **Resolution: adopt `models.py` wording** as the canonical string and delete `agent.py`'s copy.

`COLOR_MAP` exists only in `server.py` — but it is a natural companion to `COLOR_NAMES` and should live in `constants.py` too so it's available to any future Python module.

### New File: `constants.py`

Full content:

```python
"""ARC-AGI-3 shared constants — palette, action labels, descriptions.

Import from here instead of defining locally in server.py or agent.py.
"""

from pathlib import Path

# ── Color palette ──────────────────────────────────────────────────────────

COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", 2: "#999999", 3: "#666666",
    4: "#333333", 5: "#000000", 6: "#E53AA3", 7: "#FF7BCC",
    8: "#F93C31", 9: "#1E93FF", 10: "#88D8F1", 11: "#FFDC00",
    12: "#FF851B", 13: "#921231", 14: "#4FCC30", 15: "#A356D6",
}

COLOR_NAMES = {
    0: "White", 1: "LightGray", 2: "Gray", 3: "DarkGray",
    4: "VeryDarkGray", 5: "Black", 6: "Magenta", 7: "LightMagenta",
    8: "Red", 9: "Blue", 10: "LightBlue", 11: "Yellow",
    12: "Orange", 13: "Maroon", 14: "Green", 15: "Purple",
}

# ── Action labels ──────────────────────────────────────────────────────────

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

# ── Game description (loaded once at import time) ──────────────────────────

ARC_AGI3_DESCRIPTION = (
    Path(__file__).parent / "prompts" / "shared" / "arc_description.txt"
).read_text().strip()

# ── System message (canonical — used by server.py via models.py and agent.py) ──
# NOTE: models.py still defines its own SYSTEM_MSG; in Phase 2, models.py
# should import this instead. For Phase 1 we only eliminate the agent.py copy.

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)
```

### Edits Required

#### `server.py` — remove 5 definitions, add 1 import

**Remove lines 391–410** (COLOR_MAP, COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION):

```python
# BEFORE (server.py lines 391–410):
COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", ...
}

COLOR_NAMES = {
    0: "White", 1: "LightGray", ...
}

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", ...
}

ARC_AGI3_DESCRIPTION = (Path(__file__).parent / "prompts" / "shared" / "arc_description.txt").read_text().strip()
```

**Replace with** (add to the import block near line 42, alongside `from models import ...`):

```python
# AFTER — add to imports section (near line 42):
from constants import COLOR_MAP, COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION
```

Note: `server.py` already imports `SYSTEM_MSG` from `models.py` — no change needed for that.

#### `agent.py` — remove 3 definitions, add 1 import

**Remove lines 32–49** (COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION, SYSTEM_MSG):

```python
# BEFORE (agent.py lines 32–49):
COLOR_NAMES = {
    0: "White", 1: "LightGray", ...
}

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", ...
}

ARC_AGI3_DESCRIPTION = (Path(__file__).parent / "prompts" / "shared" / "arc_description.txt").read_text().strip()

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI. Analyse game grids and output ONLY "
    "valid JSON — no markdown, no explanation outside JSON."
)
```

**Replace with** (add near existing imports, after `load_dotenv`):

```python
# AFTER — agent.py import block:
from constants import COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION, SYSTEM_MSG
```

**Note:** `COLOR_MAP` is not used in `agent.py` — no import needed there.

### Verification

```bash
# 1. Grep — no standalone definitions remain in server.py or agent.py:
grep -n "^COLOR_NAMES\|^COLOR_MAP\|^ACTION_NAMES\|^ARC_AGI3_DESCRIPTION\|^SYSTEM_MSG" server.py agent.py
# Expected: no output

# 2. Python import check:
python3 -c "from constants import COLOR_MAP, COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION, SYSTEM_MSG; print('OK')"

# 3. Smoke test server imports:
python3 -c "import server; print('server OK')"

# 4. Smoke test agent imports:
python3 -c "import agent; print('agent OK')"
```

---

## Step 1b — Delete dead code in `llm.js`

### What & Why

`static/js/llm.js` contains a large commented-out block: the old scaffolding-specific `_OLD_buildReasoningGroupHTML()` function, wrapped in a `/* --- REMOVED: ... --- END REMOVED */` comment. It is **completely unreachable** — the real `buildReasoningGroupHTML` lives in `reasoning.js` and is loaded before `llm.js`. The block was already renamed with `_OLD_` prefix and wrapped in a comment at an earlier cleanup pass; it was never fully deleted.

### Exact Lines to Delete

**File:** `static/js/llm.js`  
**Lines 801–1074** (274 lines):

```javascript
// Line 801:
/* --- REMOVED: old scaffolding-specific buildReasoningGroupHTML ---
function _OLD_buildReasoningGroupHTML(g, gi, options) {
  ...
  // (273 more lines)
  ...
}
--- END REMOVED */
// Line 1074 ends here
```

The surrounding context (for orientation):

```javascript
// Line 795 (KEEP):
// Keeping this block as a marker. The function below is a no-op fallback.
// Line 796 (KEEP):
if (typeof buildReasoningGroupHTML === 'undefined') {
// Line 797 (KEEP):
  // Should never happen — reasoning.js must load first
// Line 798 (KEEP):
  console.error('reasoning.js not loaded before llm.js!');
// Line 799 (KEEP):
}
// Line 800 (KEEP): [blank line]

// DELETE LINES 801–1074:
/* --- REMOVED: old scaffolding-specific buildReasoningGroupHTML ---
...
--- END REMOVED */

// Line 1075 (KEEP):
async function askLLM(ss) {
```

### What to Keep

Lines 795–800 (the `typeof buildReasoningGroupHTML === 'undefined'` guard) should be kept — it is a useful runtime assertion.

### Verification

```bash
# 1. Confirm the dead block is gone:
grep -n "_OLD_buildReasoningGroupHTML\|--- REMOVED\|--- END REMOVED" static/js/llm.js
# Expected: no output

# 2. Confirm askLLM still present and file has ~2200 lines (was 2475):
grep -n "^async function askLLM" static/js/llm.js
wc -l static/js/llm.js
# Expected: askLLM found, ~2201 lines

# 3. Open the UI and confirm LLM calls still work end-to-end.
```

---

## Step 1c — Create `static/js/utils/formatting.js`

### What & Why

HTML-escaping is implemented 6 separate times across 5 files with subtle differences:

| File | Function name | Line | Escapes `"` | Handles null? | Coerces type? |
|---|---|---|---|---|---|
| `llm.js` | `escapeHtml(str)` | 653 | ❌ | ❌ | ❌ |
| `llm.js` | `esc(s)` | 657 | ❌ | ✅ (ternary) | ❌ |
| `reasoning.js` | `_rEsc(s)` | ~63 | ❌ | ✅ (ternary) | ❌ |
| `obs-page.js` | `escHtml(s)` | 379 | ✅ | ❌ | ❌ |
| `observatory.js` | `obsEscHtml(s)` | 76 | ✅ | ✅ (via `String()`) | ✅ `String(s)` |
| `share-page.js` | `esc(s)` | 188 | ❌ | ✅ (ternary) | ❌ |

**Divergences:**
- 3 functions escape 3 chars (`&`, `<`, `>`); 2 escape 4 (`"` added)
- `obsEscHtml` coerces with `String(s)` — handles numbers/booleans passed accidentally
- Null/falsy handling inconsistent: some crash on null, others return empty string

**Canonical implementation** (conservative: 3 escapes, null-safe, string-coerced):

```javascript
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
```

For callers that currently pass through `"` chars to HTML attributes, use:

```javascript
function escapeHtmlAttr(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
```

`formatDuration` exists only in `share-page.js` (lines 179–186) but is a general utility. `formatCost` is not yet a standalone function (cost formatting is inline in llm.js line 625). Phase 1 moves `formatDuration` and provides a canonical `formatCost`.

### New File: `static/js/utils/formatting.js`

Full content:

```javascript
// ═══════════════════════════════════════════════════════════════════════════
// formatting.js — Canonical HTML escaping and formatting utilities
//
// Load this file BEFORE any script that needs escapeHtml, formatDuration,
// or formatCost. It defines globals; no module system required.
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Escape a string for safe HTML text content insertion.
 * Handles null/undefined → empty string. Coerces non-strings via String().
 * Escapes: & < >
 */
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Escape a string for safe insertion into an HTML attribute value.
 * Same as escapeHtml but also escapes double-quotes.
 * Use when building: <tag attr="${escapeHtmlAttr(value)}">
 */
function escapeHtmlAttr(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Format a duration in seconds to a human-readable string.
 * Examples: 3661 → "1h1m", 125 → "2m5s", 45 → "45s"
 * @param {number} seconds
 * @returns {string}
 */
function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m > 60) return `${Math.floor(m / 60)}h${m % 60}m`;
  if (m > 0) return `${m}m${s}s`;
  return `${s}s`;
}

/**
 * Format a USD cost value for display.
 * Examples: 0.00123 → "$0.0012", 1.5 → "$1.5000"
 * @param {number} cost - Cost in USD
 * @param {number} [decimals=4] - Decimal places
 * @returns {string}
 */
function formatCost(cost, decimals = 4) {
  if (cost == null || isNaN(cost)) return '';
  return `$${cost.toFixed(decimals)}`;
}
```

### HTML: Add `<script>` tag

In every HTML template that loads any of these JS files, add before the other scripts:

```html
<script src="/static/js/utils/formatting.js?v={{ static_v }}"></script>
```

Templates to update (check `<head>` section of each):
- `templates/index.html`
- `templates/obs.html`
- `templates/share.html`

### Per-File Edits

#### `llm.js` — remove `escapeHtml` + `esc`, use globals

**Remove lines 653–658:**
```javascript
// REMOVE:
function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function esc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
```

All existing call sites in `llm.js` (`escapeHtml(code)` at line 645, `escapeHtml(output)` at line 646) continue to work — the global `escapeHtml` from `formatting.js` takes over.

#### `reasoning.js` — remove `_rEsc`, replace calls

**Remove lines ~63–65:**
```javascript
// REMOVE:
function _rEsc(s) {
  return s ? s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
}
```

**Replace all call sites** in `reasoning.js` (`_rEsc(...)` → `escapeHtml(...)`):
```bash
grep -n "_rEsc" static/js/reasoning.js
# Expected call sites: lines ~157, ~168, ~169 (check after reading file)
```

#### `obs-page.js` — remove `escHtml`, replace calls

**Remove lines 378–380:**
```javascript
// REMOVE:
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```

**Replace call sites**: `escHtml(x)` → `escapeHtmlAttr(x)` (since this version escapes `"`, preserving the semantic).

```bash
grep -n "escHtml" static/js/obs-page.js
```

#### `observatory.js` — remove `obsEscHtml`, replace calls

**Remove lines 76–79:**
```javascript
// REMOVE:
function obsEscHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```

**Replace call sites**: `obsEscHtml(x)` → `escapeHtml(x)` (or `escapeHtmlAttr` for attribute contexts).

```bash
grep -n "obsEscHtml" static/js/observatory.js
```

#### `share-page.js` — remove `esc` and `formatDuration`, replace calls

**Remove lines 179–188:**
```javascript
// REMOVE:
function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m > 60) return `${Math.floor(m / 60)}h${m % 60}m`;
  if (m > 0) return `${m}m${s}s`;
  return `${s}s`;
}

function esc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
```

Call sites for `formatDuration` (lines 208, 236) and `esc` in `share-page.js` will automatically pick up the globals from `formatting.js`.

### Verification

```bash
# 1. No local duplicate definitions remain:
grep -n "function escapeHtml\|function _rEsc\|function escHtml\|function obsEscHtml\|function esc\b\|function formatDuration" \
  static/js/llm.js static/js/reasoning.js static/js/obs-page.js static/js/observatory.js static/js/share-page.js
# Expected: no output (all removed)

# 2. The canonical file exists and exports the right names:
grep "^function " static/js/utils/formatting.js
# Expected: escapeHtml, escapeHtmlAttr, formatDuration, formatCost

# 3. Browser smoke test: open UI, trigger an LLM call with special chars in
#    reasoning output (e.g. <think> block), verify HTML is not injected.
```

---

## Step 1d — Remove `getScaffoldingSettings()` duplicate from `llm.js`

### What & Why

**Finding differs from initial analysis:** `getScaffoldingSettings()` is **only defined once**, in `llm.js` at lines 20–112 (93 lines). There is **no copy in `scaffolding.js`** — `scaffolding.js` only *calls* it (at lines 675, 1165, 1780). So this step is actually a **move** (not a deletion of a true duplicate):

> Move `getScaffoldingSettings()` from `llm.js` lines 20–112 into `scaffolding.js`, then delete the original definition from `llm.js`.

This is the correct modularization: `getScaffoldingSettings()` reads DOM state from the scaffolding UI panels — it belongs with the rest of the scaffolding logic in `scaffolding.js`.

### Exact Lines to Move

**File:** `static/js/llm.js`  
**Lines 20–112** (93 lines):

```javascript
// Line 20:
function getScaffoldingSettings() {
  const type = activeScaffoldingType;
  const s = { scaffolding: type };

  if (type === 'linear' || type === 'linear_interrupt') {
    s.input = getInputSettings();
    ...
  } else if (type === 'rlm') {
    ...
  } else if (type === 'three_system') {
    ...
  } else if (type === 'two_system') {
    ...
  } else if (type === 'agent_spawn') {
    ...
  }

  return s;
// Line 112:
}
```

### Destination in `scaffolding.js`

Insert the full function body at the **top of `scaffolding.js`** (after any existing comment header/preamble, before the first existing function). Suggested insertion point: after line 17 of `scaffolding.js` (after the `LMSTUDIO_CAPABILITIES` const definition).

```javascript
// INSERT after line ~17 of scaffolding.js (after LMSTUDIO_CAPABILITIES):
function getScaffoldingSettings() {
  const type = activeScaffoldingType;
  const s = { scaffolding: type };
  // ... full 93-line body verbatim from llm.js lines 21–112 ...
  return s;
}
```

### Load Order Dependency

`getScaffoldingSettings()` calls `getInputSettings()`, `getSelectedModel()`, `getThinkingLevel()`, `getToolsMode()`, `getPlanningMode()`, `getMaxTokens()`, `getCompactSettings()` — all of which are defined in `llm.js`. Since `llm.js` loads after `scaffolding.js` in the current HTML template, this is a **load order problem**.

**Resolution options (choose one):**
1. Move `getScaffoldingSettings()` to the bottom of `scaffolding.js` and ensure `index.html` loads `llm.js` before `scaffolding.js` (reverse current order).
2. Keep `getScaffoldingSettings()` in `llm.js` for now and defer this step to Phase 2 once load order is settled.

**Recommendation:** Defer this step to Phase 2. The function is not a true duplicate; moving it without resolving the load order creates a runtime dependency risk. Phase 1 benefit is marginal (no DRY win, just file organization).

### Verification (if proceeding)

```bash
# 1. Exactly one definition of getScaffoldingSettings:
grep -rn "function getScaffoldingSettings" static/js/
# Expected: exactly 1 result, in scaffolding.js

# 2. All callers (scaffolding.js lines 675, 1165, 1780 + llm.js line 1900) still resolve:
grep -n "getScaffoldingSettings()" static/js/scaffolding.js static/js/llm.js
# Expected: callers present, 0 definitions in llm.js

# 3. UI smoke test: start a scaffolding session, verify settings are captured correctly.
```

---

## Step 1e — Consolidate `agentColor()` + `agentBadge()`

### What & Why

`reasoning.js` defines the authoritative implementations (lines 29–58). Survey of the other files:

**`obs-page.js`** (lines 1–17):
- Lines 1, 17: Only comments confirming it uses `reasoning.js` versions
- No function definitions — it already delegates to `reasoning.js`
- ✅ **No code change needed in obs-page.js** — it is already clean

**`observatory.js`** (lines 54–65):
```javascript
// Line 54–56: thin wrapper that just calls agentColor():
function obsAgentColor(agent) {
  if (!agent) return OBS_DEFAULT_COLOR;
  return agentColor(agent);
}

// Lines 58–62: obsAgentBadge — thin wrapper around agentColor():
function obsAgentBadge(agent) {
  if (!agent) return '<span style="color:var(--text-dim)">--</span>';
  const c = obsAgentColor(agent);
  return `<span class="obs-agent-badge" style="background:${c}">${agent}</span>`;
}
```

These are **not true duplicates** but redundant wrappers. `obsAgentBadge` uses a different CSS class (`obs-agent-badge` vs `agent-badge` in `reasoning.js`) and slightly different null HTML. This is a **styling divergence**, not just a copy.

### Finding: No True Duplicate Exists

The initial analysis description ("remove duplicates in obs-page.js and observatory.js") does not match what the code actually contains:

- `obs-page.js`: No `agentColor`/`agentBadge` definitions — already cleaned up
- `observatory.js`: Has thin wrappers with different class names / null behavior — **deliberate variants, not copy-paste**

### Recommended Action

For `observatory.js`:
1. **Delete `obsAgentColor`** (lines 54–56) — replace all callers (`obsAgentColor(x)` → `agentColor(x)`, handling the `OBS_DEFAULT_COLOR` fallback inline or by passing it to `agentColor`).
2. **Evaluate `obsAgentBadge`** before deleting: if `obs-agent-badge` CSS class is used elsewhere in `obs.html` for styling (different from `.agent-badge`), the wrapper must stay or `reasoning.js`'s `agentBadge()` must accept a custom class parameter.

**Check CSS dependency:**
```bash
grep -rn "obs-agent-badge" templates/ static/
```

If `obs-agent-badge` has unique CSS rules → keep `obsAgentBadge` as-is (it is a view-specific variant, not a duplicate).  
If it has no unique CSS → delete `obsAgentBadge` and replace callers with `agentBadge()` from `reasoning.js`.

### Steps if Proceeding with Deletion

**Remove from `observatory.js` lines 54–65:**
```javascript
// REMOVE (if obsAgentBadge CSS is redundant):
function obsAgentColor(agent) {
  if (!agent) return OBS_DEFAULT_COLOR;
  return agentColor(agent);
}

function obsAgentBadge(agent) {
  if (!agent) return '<span style="color:var(--text-dim)">--</span>';
  const c = obsAgentColor(agent);
  return `<span class="obs-agent-badge" style="background:${c}">${agent}</span>`;
}
```

**Find and update callers:**
```bash
grep -n "obsAgentColor\|obsAgentBadge" static/js/observatory.js
```
Replace `obsAgentColor(x)` → `agentColor(x) || OBS_DEFAULT_COLOR`  
Replace `obsAgentBadge(x)` → `agentBadge(x)` (if CSS is unified)

### Verification

```bash
# 1. No remaining wrapper definitions:
grep -n "function obsAgentColor\|function obsAgentBadge" static/js/observatory.js
# Expected: no output

# 2. agentColor/agentBadge defined exactly once:
grep -rn "^function agentColor\|^function agentBadge" static/js/
# Expected: exactly 2 lines, both in reasoning.js

# 3. Visual check: load /share/<session_id> with an agent session, verify
#    agent color badges render correctly in the observatory view.
```

---

## Summary Table

| Step | Files Changed | Lines Affected | Risk | Prerequisite |
|---|---|---|---|---|
| 1a: constants.py | `server.py`, `agent.py` + new `constants.py` | server.py –20, agent.py –18 | Low | None |
| 1b: dead code in llm.js | `static/js/llm.js` | –274 lines (801–1074) | None | None |
| 1c: formatting.js | 5 JS files + 3 HTML templates + new file | ~6 function removals | Medium (call-site audit) | Load order in HTML |
| 1d: getScaffoldingSettings | Deferred to Phase 2 | — | High (load order) | Phase 2 load order fix |
| 1e: agentColor/agentBadge | `static/js/observatory.js` | –12 lines (54–65) | Low (CSS audit first) | CSS class audit |

## Key Surprises / Divergences Found

1. **`SYSTEM_MSG` has drifted**: `models.py` includes "agent" in the persona string; `agent.py` does not. Adopting `models.py` wording changes `agent.py`'s behavior slightly (LLM sees itself as "agent").

2. **`getScaffoldingSettings()` is not a duplicate**: it is defined only in `llm.js`, not in `scaffolding.js`. The step as specified (delete from `llm.js`, keep in `scaffolding.js`) requires a *move*, not a deletion — and introduces a load-order risk. **Defer to Phase 2.**

3. **`obs-page.js` already clean**: the `agentColor`/`agentBadge` duplicates in `obs-page.js` were already removed in a prior cleanup (only comments remain). No code change needed there.

4. **HTML escape implementations diverge on `"`**: `obs-page.js` and `observatory.js` escape 4 chars; others escape 3. The canonical `formatting.js` provides both `escapeHtml` (3 chars) and `escapeHtmlAttr` (4 chars) — callers must be audited to pick the right one.

5. **`formatCost` does not exist yet**: only inline formatting in `llm.js` line 625. `formatting.js` introduces it as a new utility.
