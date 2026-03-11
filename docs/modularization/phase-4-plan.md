# Phase 4: Observatory Consolidation — Implementation Plan

> **Documentation only. No code has been changed.**

---

## ⚠️ CRITICAL FINDING: BOTH FILES ARE LIVE — DIFFERENT TEMPLATES

**Neither file is dead. Both are actively loaded by different HTML templates:**

| File | Template | Purpose |
|---|---|---|
| `static/js/observatory.js` | `templates/index.html` (line 668) | In-app observatory overlay — renders inside the main ARC game UI, launched via `enterObsMode()` CSS class toggle |
| `static/js/obs-page.js` | `templates/obs.html` (line 780) | Standalone dedicated observatory page — full standalone polling UI served at `/obs` route |

These are **two different products** sharing observatory domain logic. The consolidation strategy must preserve both while extracting shared rendering components into a shared library.

---

## 1. File Load Context

### `templates/index.html` script block (lines 661–671)
```html
<script src="/static/js/state.js?v={{ static_v }}"></script>
<script src="/static/js/engine.js?v={{ static_v }}"></script>
<script src="/static/js/reasoning.js?v={{ static_v }}"></script>
<script src="/static/js/ui.js?v={{ static_v }}"></script>
<script src="/static/js/llm.js?v={{ static_v }}"></script>
<script src="/static/js/scaffolding.js?v={{ static_v }}"></script>
<script src="/static/js/session.js?v={{ static_v }}"></script>
<script src="/static/js/observatory.js?v={{ static_v }}"></script>   <!-- ← HERE -->
<script src="/static/js/human.js?v={{ static_v }}"></script>
<script src="/static/js/leaderboard.js?v={{ static_v }}"></script>
<script src="/static/js/dev.js?v={{ static_v }}"></script>
```
`observatory.js` runs inside a rich JS environment: `agentColor()`, `agentBadge()`, `getActiveSession()`, `moveHistory`, `currentState`, `renderGrid()`, `COLORS`, `ACTION_NAMES`, etc. are all provided by the earlier scripts.

### `templates/obs.html` script block (lines 776–780)
```html
<script>
  // inline: window.shareSessionId = "{{ share_session_id|default('') }}"
</script>
<script src="/static/js/reasoning.js"></script>
<script src="/static/js/obs-page.js"></script>   <!-- ← HERE -->
```
`obs-page.js` runs in a minimal environment — only `reasoning.js` precedes it. It defines its own `agentColor`, `fmtK`, `hexToRgba`, `escHtml`, etc. internally. It has its own polling loop (`poll()` / `fetchStatus()` / `fetchEvents()` / `fetchGrid()`), its own state (`allEvents`, `nextOffset`, `frozenGrid`), and its own session browser.

---

## 2. Git Blame Summary

### `static/js/obs-page.js`
```
b7d7874  2026-03-08  Unify DB schema and reasoning UI: remove scaffolding-specific code
d988614  2026-03-08  Refactor: extract JS into page modules, extract llm_providers/models from server, add sh02 game, lb01 v2, agents package
```
- First appeared: **2026-03-08** (extracted from the 12,342-line monolithic `index.html`)
- Last touched: **2026-03-08** (same day — schema/reasoning unification)
- Age: ~2 days at time of this plan

### `static/js/observatory.js`
```
b7d7874  2026-03-08  Unify DB schema and reasoning UI: remove scaffolding-specific code
a0ce1b7  2026-03-08  Group Settings View and Observatory View with CSS class toggle
052e46c  2026-03-08  Fix obs view not replacing settings view (wrong querySelector scope)
32f8b4a  2026-03-06  Refactor index.html (12,342 lines) into 10 separate files
```
- First appeared: **2026-03-06** (initial extraction)
- Last touched: **2026-03-08** (schema/reasoning unification, same as obs-page.js)
- Has more commits — it was the first to be extracted and has been iterated more

**Both files are very new (< 1 week old) and both had the same final commit applied.**

---

## 3. Function-by-Function Comparison

### Functions unique to `obs-page.js` (standalone `/obs` page)

These are specific to the polling-based standalone page and have no equivalent in `observatory.js`:

| Function | Lines | Description |
|---|---|---|
| `humanAction(raw)` | 11–15 | Maps ACTION1–7/RESET to display strings |
| `lookupPricing(model)` | 41–47 | Model cost lookup from `MODEL_PRICING` table |
| `estimateCost()` | 49–58 | Compute $ total from token counts |
| `normalizeEvent(ev)` | 61–67 | Normalize `agent_type`/`agent` aliasing, `step_num→step` |
| `trackEventTokens(ev)` | 70–80 | Route tokens to `plannerTokens`/`executorTokens` |
| `resetState()` | 98–111 | Clear all state and DOM elements |
| `fetchStatus()` | 114–131 | Poll `/api/obs/status` |
| `fetchEvents()` | 134–156 | Poll `/api/obs/events?since=N` |
| `fetchGrid()` | 1027–1041 | Poll `/api/obs/grid` |
| `poll()` | 158–162 | Main polling loop (500ms) |
| `setConn(live)` | 163–172 | Connection status indicator |
| `renderStatus(s)` | 175–215 | Render status bar from API data |
| `fmtK(n)` | 217–222 | Format number as K/M |
| `renderNewEvents(events)` | 224–274 | Append rows to log table |
| `_extractReasoning(ev)` | 276–297 | Extract reasoning from raw LLM response JSON |
| `buildDetails(ev)` | 299–342 | Build human-readable detail string for event |
| `buildExpandDetail(ev)` | 344–376 | Build expandable HTML detail block |
| `escHtml(s)` | 378–380 | HTML escape |
| `toggleAutoScroll()` | 382–386 | Toggle auto-scroll on log |
| `copyObsLogs()` | 388–416 | Copy full log to clipboard |
| `findNearestGrid(evIdx)` | 418–427 | Walk backwards to find nearest grid in event history |
| `selectLogRow(tr, evIdx)` | 429–492 | Click log row to view historical grid state |
| `buildSpawnGroups(events)` | 494–588 | Parse events into orch segments + spawn groups |
| `renderChips(groupEvents, agentHex)` | 590–610 | Render action chips for timeline blocks |
| `setTimelineMode(mode)` | 612–619 | Toggle swimlane/custom timeline mode |
| `renderTimelineSwimlane()` | 622–768 | Full swimlane timeline renderer |
| `showSimpleEventTooltip(ev, e)` | 770–788 | Tooltip for individual events |
| `showProportionalTooltipForSG(sg, fraction, e)` | 790–827 | Proportional tooltip across spawn group span |
| `renderTimeline()` | 829–950 | Timeline dispatcher (swimlane vs custom) |
| `hexToRgba(hex, alpha)` | 952–958 | Hex color to rgba() |
| `showOrchTooltip(e)` | 960–983 | Tooltip for orchestrator timeline segment |
| `showProportionalTooltip(e)` | 985–995 | Proportional tooltip for custom mode blocks |
| `positionTooltip(tt, e)` | 997–1011 | Keep tooltip within viewport |
| `hideTooltip()` | 1013–1015 | Hide tooltip |
| `renderGameGrid(grid)` | 1044–1065 | Render 2D ARC grid to canvas |
| `_getGridEventIndices()` | 1068–1076 | Build index of events that have grids |
| `obsScrubReturnToLive()` *(standalone version)* | 1140–1151 | Return scrubber to live mode (standalone version) |
| `annotateCoordRefs(element)` | 1166–1193 | Annotate text nodes with coordinate refs |
| `cellsFromCoordRef(ref)` | 1196–1213 | Convert coord-ref dataset to cell list |
| `highlightCellsOnCanvas(cells)` | 1215–1232 | Draw highlight overlay on grid canvas |
| `clearCellHighlights()` | 1234–1236 | Clear canvas highlights by re-rendering |
| `toggleSessionBrowser()` | 1278–1283 | Show/hide session browser overlay |
| `fetchSessionList()` | 1287–1319 | Fetch and merge sessions from two API endpoints |
| `applySessionFilters()` | 1322–1361 | Apply game/result/model filters to session list |
| `loadSession(sessionId, gameId)` | 1363–1432 | Load and replay a historical session |
| `returnToLive()` | 1434–1439 | Exit replay, resume live polling |

### Functions unique to `observatory.js` (in-app overlay)

These are specific to the in-app overlay that integrates with the running game session:

| Function | Lines | Description |
|---|---|---|
| `toggleTheme()` / `updateThemeBtn()` | 19–33 | Theme toggle (dark/light) |
| `isObsModeActive()` | 42–44 | Check if observatory CSS class is applied |
| `obsAgentColor(agent)` | 52–55 | Thin wrapper around `agentColor()` from `reasoning.js` |
| `obsAgentBadge(agent)` | 57–61 | Build agent badge HTML |
| `obsFmtK(n)` | 63–67 | Format K/M numbers |
| `obsHexToRgba(hex, alpha)` | 69–74 | Hex to rgba |
| `obsEscHtml(s)` | 76–79 | HTML escape |
| `emitObsEvent(ss, partial)` | 83–96 | Emit an obs event from within the game session |
| `enterObsMode(ss)` | 104–156 | Activate observatory view — CSS class toggle, canvas move, sync |
| `exitObsMode()` | 158–179 | Deactivate observatory view — CSS class toggle, canvas restore |
| `syncObsReasoning()` | 182–241 | Mirror reasoning panel to obs reasoning column |
| `renderObsScreen(ss)` | 243–257 | Full re-render of obs screen from session data |
| `updateObsStatus(ss)` | 259–287 | Update obs status bar from live session |
| `updateObsElapsed(ss)` | 289–310 | Update elapsed time display |
| `startObsSync(ss)` / `stopObsSync()` | 603–611 | Start/stop 5s server sync interval |
| `syncObsEvents(ss)` | 612–628 | POST new events to `/api/sessions/:id/obs-events` |

### Functions with SAME NAME but DIFFERENT IMPLEMENTATION

These are the most important — they exist in both files but are adapted to their context:

| Function | obs-page.js lines | observatory.js lines | Key differences |
|---|---|---|---|
| `obsScrubUpdate()` | 1078–1098 | 379–396 | obs-page: uses `_getGridEventIndices()` + gridIndices for step count; observatory: uses `moveHistory` for step count |
| `obsScrubShow(sliderVal/idx)` | 1100–1138 | 398–438 | obs-page: renders via `renderGameGrid()` on `gridCanvas`; observatory: renders via `COLORS` table on `gameCanvas` inside `obsCanvasHost` |
| `obsScrubReturnToLive()` | 1140–1151 | 469–476 | obs-page: clears `frozenGrid`, restores via `renderGameGrid()`; observatory: clears `_obsScrubLive`, restores via `renderGrid()` |
| `appendObsLogRow(ev, evIdx)` | 224–274 (as `renderNewEvents`) | 312–358 | obs-page: much richer — tokens, expand detail, coord-ref annotation, click-to-select-grid; observatory: simpler — summary/error/response_preview only |
| `obsBuildDetails(ev)` | 299–342 (as `buildDetails`) | 361–377 | obs-page: full switch/case with 8 event types; observatory: 4 cases only |
| `renderObsSwimlane(ss)` / `renderTimelineSwimlane()` | 622–768 | 491–600 | obs-page: uses parsed `spawnGroups` with orchestrator lane; observatory: simpler by-agent bucketing directly from events |

---

## 4. Revised Consolidation Strategy

Since both files are live, we **cannot eliminate either**. The goal is to:

1. Extract the **rendering primitives** that are functionally equivalent (or near-equivalent) into `static/js/observatory/` shared modules
2. Have both `obs-page.js` and `observatory.js` import from those modules
3. Keep lifecycle/integration code (polling, `enterObsMode`, `emitObsEvent`, session browser) in each file — it is file-specific

### What CAN be shared (good extraction candidates)

| Candidate module | What goes in it | Source files |
|---|---|---|
| `obs-swimlane-renderer.js` | Core swimlane HTML-building logic (label+track structure, event block sizing, auto-scroll, tooltip binding pattern) | Both — but obs-page version is the richer one |
| `obs-log-renderer.js` | `escHtml`, `fmtK`/`obsFmtK`, `hexToRgba`, `agentBadge`-style helpers | Both (duplicated utility functions) |
| `obs-scrubber.js` | Scrubber DOM update logic (dot state, label, banner show/hide) — parameterized for different data sources | Both — split on data-source |
| `obs-lifecycle.js` | **Observatory.js only** — `enterObsMode`, `exitObsMode`, `syncObsReasoning` are specific to in-app mode; don't share with obs-page.js |

---

## 5. Proposed New Files — Exact Content

### 5a. `static/js/observatory/obs-scrubber.js`

**Purpose:** Shared scrubber DOM logic — updates slider position, dot indicator, label, and banner. Parameterized by a config object so each context provides its own data.

**Source:** Synthesized from `obs-page.js:1078–1151` and `observatory.js:379–476`. The DOM structure differs (obs-page uses `obsScrubSlider`/`obsScrubLabel`/`obsScrubDot`/`obsScrubBanner`; observatory uses `obsScrubSlider`/`obsScrubLbl`/`obsScrubDot`/`obsScrubBanner`). The proposed module uses the obs-page.js IDs as canonical since obs.html is the dedicated page.

**Proposed content:**
```js
/**
 * obs-scrubber.js — Shared scrubber UI logic for Observatory views.
 *
 * Requires DOM elements:
 *   #obsScrubSlider  — <input type="range">
 *   #obsScrubLabel   — text label "Step N / T"
 *   #obsScrubDot     — live/paused indicator
 *   #obsScrubBanner  — "viewing step N" banner
 *   #obsScrubBannerText — text inside banner
 *
 * Usage:
 *   obsScrubSetLive(totalSteps)
 *   obsScrubSetHistorical(stepIdx, totalSteps, stepLabel)
 *   obsScrubHideBanner()
 */

function obsScrubSetLive(totalSteps) {
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  slider.max = Math.max(0, totalSteps - 1);
  slider.value = Math.max(0, totalSteps - 1);
  const labelEl = document.getElementById('obsScrubLabel');
  if (labelEl) labelEl.textContent = `Step ${totalSteps} / ${totalSteps}`;
  const dot = document.getElementById('obsScrubDot');
  if (dot) { dot.className = 'obs-scrubber-dot is-live'; dot.innerHTML = '&#9679; LIVE'; }
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'none';
}

function obsScrubSetHistorical(stepIdx, totalSteps, stepLabel) {
  const slider = document.getElementById('obsScrubSlider');
  if (!slider) return;
  slider.max = Math.max(0, totalSteps - 1);
  slider.value = stepIdx;
  const labelEl = document.getElementById('obsScrubLabel');
  if (labelEl) labelEl.textContent = `Step ${stepIdx + 1} / ${totalSteps}`;
  const dot = document.getElementById('obsScrubDot');
  if (dot) { dot.className = 'obs-scrubber-dot is-historical'; dot.innerHTML = '&#9679; PAUSED'; }
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'flex';
  const bannerText = document.getElementById('obsScrubBannerText');
  if (bannerText) bannerText.textContent = stepLabel || `Viewing step ${stepIdx + 1}`;
}

function obsScrubHideBanner() {
  const banner = document.getElementById('obsScrubBanner');
  if (banner) banner.style.display = 'none';
}
```

**How obs-page.js uses it:**
- `obsScrubUpdate()` calls `obsScrubSetLive(gridIndices.length)` or `obsScrubSetHistorical(pos, total, label)`
- `obsScrubShow()` calls `obsScrubSetHistorical(idx, gridIndices.length, 'Viewing step N')`
- `obsScrubReturnToLive()` calls `obsScrubSetLive(gridIndices.length)`

**How observatory.js uses it:**
- `obsScrubUpdate()` calls `obsScrubSetLive(hist.length)` or `obsScrubSetHistorical(_obsScrubIdx, hist.length, label)`
- `obsScrubShow()` calls `obsScrubSetHistorical(idx, hist.length, 'Viewing step N')`
- `obsScrubReturnToLive()` calls `obsScrubSetLive(hist.length)`

> **Note:** The observatory.js template uses `obsScrubLbl` (no 'e') vs obs-page.js `obsScrubLabel`. Before using the shared module, normalize one template's IDs.

---

### 5b. `static/js/observatory/obs-swimlane-renderer.js`

**Purpose:** Shared swimlane HTML builder. The obs-page.js version (lines 622–768) is the canonical rich implementation. The observatory.js version (lines 491–600) is simpler. Extract the shared structure.

**Source lines from obs-page.js:** `622–768` (renderTimelineSwimlane function body)

**Key shared logic** (exact lines from obs-page.js):
- Label column + tracks column HTML pattern: lines 714–751
- Event block sizing formula: `left = (evT - t0) * pxPerSec; w = Math.max(evDur * pxPerSec, 4)` (line ~740)
- Auto-scroll: `scrollEl.scrollLeft = scrollEl.scrollWidth` (line ~757)
- Tooltip binding pattern: lines 760–768

**Proposed module signature:**
```js
/**
 * obs-swimlane-renderer.js — Shared swimlane rendering helper.
 *
 * renderSwimlane(config) — builds and injects the swimlane HTML
 *   config = {
 *     canvasId: string,          // element to inject HTML into
 *     scrollId: string,          // scrollable tracks element id
 *     lanes: [{                  // ordered lanes to render
 *       label: string,
 *       color: string,           // hex color
 *       blocks: [{
 *         startT: number,        // seconds from t0
 *         endT: number,
 *         opacity: number,
 *         dataAttr: string,      // e.g. 'data-obs-idx="3"'
 *       }]
 *     }],
 *     t0: number,                // timeline start (seconds)
 *     pxPerSec: number,          // pixels per second (post-zoom)
 *     totalW: number,            // total canvas width in px
 *     autoScroll: boolean,
 *     labelClass: string,        // CSS class for label divs
 *     rowClass: string,          // CSS class for row divs
 *     blockClass: string,        // CSS class for event blocks
 *     wrapClass: string,         // CSS class for outer wrap
 *   }
 *
 * The caller builds the `lanes` array and handles tooltip binding.
 */
function renderSwimlane(config) {
  const canvas = document.getElementById(config.canvasId);
  if (!canvas) return;
  let labelsHtml = '';
  let tracksHtml = '';

  for (const lane of config.lanes) {
    labelsHtml += `<div class="${config.labelClass}" style="color:${lane.color}">${lane.label}</div>`;
    tracksHtml += `<div class="${config.rowClass}">`;
    for (const blk of lane.blocks) {
      const left = (blk.startT - config.t0) * config.pxPerSec;
      const w = Math.max((blk.endT - blk.startT) * config.pxPerSec, 4);
      tracksHtml += `<div class="${config.blockClass}" style="left:${left}px;width:${w}px;background:${blk.color || lane.color};opacity:${blk.opacity}" ${blk.dataAttr || ''}></div>`;
    }
    tracksHtml += '</div>';
  }

  canvas.innerHTML =
    `<div class="${config.wrapClass}">` +
      `<div class="${config.labelClass}-column">${labelsHtml}</div>` +
      `<div class="${config.scrollClass}" id="${config.scrollId}">` +
        `<div style="width:${config.totalW + 10}px">${tracksHtml}</div>` +
      `</div>` +
    `</div>`;

  if (config.autoScroll) {
    const scrollEl = document.getElementById(config.scrollId);
    if (scrollEl) scrollEl.scrollLeft = scrollEl.scrollWidth;
  }
}
```

---

### 5c. `static/js/observatory/obs-log-renderer.js`

**Purpose:** Shared utility functions used in both log renderers. These are pure functions with no DOM dependency.

**Exact source extractions:**

From `obs-page.js`:
- `escHtml(s)` — line 378–380
- `fmtK(n)` — lines 217–222
- `hexToRgba(hex, alpha)` — lines 952–958
- `hideTooltip()` — lines 1013–1015
- `positionTooltip(tt, e)` — lines 997–1011

From `observatory.js`:
- `obsEscHtml(s)` — lines 76–79 (same as escHtml)
- `obsFmtK(n)` — lines 63–67 (same as fmtK)
- `obsHexToRgba(hex, alpha)` — lines 69–74 (same as hexToRgba)

All are identical in logic. Canonical versions from obs-page.js:

```js
/**
 * obs-log-renderer.js — Shared utility functions for observatory log/tooltip rendering.
 * No DOM dependencies except positionTooltip and hideTooltip.
 */

function obsSharedEscHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function obsSharedFmtK(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toString();
}

function obsSharedHexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Position a tooltip element near the mouse event, keeping within viewport.
 * @param {HTMLElement} tt - the tooltip element (must already have .visible class and content)
 * @param {MouseEvent} e
 */
function obsSharedPositionTooltip(tt, e) {
  const pad = 12;
  let left = e.clientX + pad;
  let top = e.clientY + pad;
  const ttRect = tt.getBoundingClientRect();
  if (left + ttRect.width > window.innerWidth - 10) left = e.clientX - ttRect.width - pad;
  if (top + ttRect.height > window.innerHeight - 10) top = e.clientY - ttRect.height - pad;
  tt.style.left = Math.max(0, left) + 'px';
  tt.style.top = Math.max(0, top) + 'px';
}

/**
 * Hide a tooltip by id.
 * @param {string} tooltipId - defaults to 'tooltip'
 */
function obsSharedHideTooltip(tooltipId = 'tooltip') {
  document.getElementById(tooltipId)?.classList.remove('visible');
}
```

---

### 5d. `static/js/observatory/obs-lifecycle.js`

**Purpose:** Contains `enterObsMode`, `exitObsMode`, `syncObsReasoning` from `observatory.js`. These are specific to the in-app overlay mode and should NOT be shared with `obs-page.js`.

**Source lines from observatory.js:**
- `enterObsMode(ss)` — lines 104–156
- `exitObsMode()` — lines 158–179
- `syncObsReasoning()` — lines 182–241

**Note:** These functions depend on `getActiveSession()`, `moveHistory`, `unlockSettings()`, `renderGrid()`, `ACTION_NAMES` — all provided by the broader index.html JS environment. This module can only be loaded in `templates/index.html` context.

```js
/**
 * obs-lifecycle.js — In-app observatory mode lifecycle management.
 *
 * Requires: state.js, reasoning.js, session.js (agentColor, getActiveSession, moveHistory,
 *           renderGrid, unlockSettings, ACTION_NAMES, COLORS)
 *
 * NOT for use in obs.html / obs-page.js context.
 */

// [Move enterObsMode, exitObsMode, syncObsReasoning verbatim from observatory.js lines 104–241]
// [Move startObsSync, stopObsSync, syncObsEvents from lines 603–628]
```

---

## 6. Script Load Order in Templates

### `templates/obs.html` — after extraction

Replace:
```html
<script src="/static/js/reasoning.js"></script>
<script src="/static/js/obs-page.js"></script>
```

With:
```html
<script src="/static/js/reasoning.js"></script>
<script src="/static/js/observatory/obs-log-renderer.js"></script>
<script src="/static/js/observatory/obs-scrubber.js"></script>
<script src="/static/js/observatory/obs-swimlane-renderer.js"></script>
<script src="/static/js/obs-page.js"></script>
```

`obs-page.js` must remain last — it contains initialization code that runs immediately (slider bindings, `poll()`, `loadSession()` on `shareSessionId`).

### `templates/index.html` — after extraction

Replace:
```html
<script src="/static/js/observatory.js?v={{ static_v }}"></script>
```

With:
```html
<script src="/static/js/observatory/obs-log-renderer.js?v={{ static_v }}"></script>
<script src="/static/js/observatory/obs-scrubber.js?v={{ static_v }}"></script>
<script src="/static/js/observatory/obs-swimlane-renderer.js?v={{ static_v }}"></script>
<script src="/static/js/observatory/obs-lifecycle.js?v={{ static_v }}"></script>
<script src="/static/js/observatory.js?v={{ static_v }}"></script>
```

`observatory.js` must remain last — it contains the `DOMContentLoaded` handler for `obsSwimlaneContainer` wheel zoom, and slider binding code.

---

## 7. Step-by-Step Implementation Plan

### Step 0: Baseline verification (before any changes)
1. Open `http://localhost:5000/` — verify main game UI loads
2. Click "Observatory" button → confirm `enterObsMode()` activates, swimlane renders, scrubber shows LIVE
3. Open `http://localhost:5000/obs` — confirm standalone obs page loads, LIVE/DISCONNECTED badge shows, log table renders
4. Run an agent step — confirm events appear in both views
5. Drag scrubber to a historical position in both views — confirm grid renders historical state, "PAUSED" dot shows
6. **Screenshot both views** for regression baseline

### Step 1: Create `static/js/observatory/` directory
```
mkdir -p static/js/observatory/
```

### Step 2: Create `obs-log-renderer.js`
- Extract `escHtml`, `fmtK`, `hexToRgba`, `positionTooltip`, `hideTooltip` from obs-page.js (lines 217–222, 378–380, 952–958, 997–1015) into `obs-log-renderer.js` with `obsShared*` prefixes
- **Do NOT remove them from obs-page.js yet**

**Verification:** Load obs.html and index.html in browser. Check console for no errors. Both pages should work identically to baseline.

### Step 3: Create `obs-scrubber.js`
- Implement `obsScrubSetLive`, `obsScrubSetHistorical`, `obsScrubHideBanner` as shown in §5a
- Load it in both templates (before the main JS files)
- **Do NOT modify obs-page.js or observatory.js yet**

**Verification:** No console errors. Pages unchanged.

### Step 4: Create `obs-swimlane-renderer.js`
- Implement `renderSwimlane(config)` as shown in §5b
- Load in both templates

**Verification:** No console errors. Pages unchanged.

### Step 5: Create `obs-lifecycle.js`
- Move `enterObsMode`, `exitObsMode`, `syncObsReasoning`, `startObsSync`, `stopObsSync`, `syncObsEvents` from `observatory.js` verbatim into `obs-lifecycle.js`
- Remove those functions from `observatory.js`
- Load `obs-lifecycle.js` in `templates/index.html` only, before `observatory.js`

**Verification:**
- Open `http://localhost:5000/` — confirm Observatory mode still activates and deactivates correctly
- Confirm reasoning panel mirrors to obs reasoning column
- Confirm 5s server sync is working (check Network tab for POST to `/api/sessions/:id/obs-events`)
- `http://localhost:5000/obs` should be **unaffected** (obs-lifecycle.js is not loaded there)

### Step 6: Refactor `obs-page.js` to call shared scrubber
- Replace body of `obsScrubUpdate()` (lines 1078–1098) to use `obsScrubSetLive`/`obsScrubSetHistorical`
- Replace body of `obsScrubShow()` (lines 1100–1138) to call `obsScrubSetHistorical` for UI updates
- Replace body of `obsScrubReturnToLive()` (lines 1140–1151) to call `obsScrubSetLive`

**Verification:**
- Open `/obs` — drag scrubber back and forth
- Confirm "PAUSED" dot appears when historical, "LIVE" when at end
- Confirm banner text shows correct step number
- Confirm grid canvas updates to correct historical state

### Step 7: Refactor `observatory.js` to call shared scrubber
- Replace body of `obsScrubUpdate()` (lines 379–396) to call `obsScrubSetLive`/`obsScrubSetHistorical`
- Replace body of `obsScrubShow()` (lines 398–438) to call `obsScrubSetHistorical` for UI updates
- Replace body of `obsScrubReturnToLive()` (lines 469–476) to call `obsScrubSetLive`
- **Note:** First normalize ID: ensure `templates/index.html` uses `obsScrubLabel` (not `obsScrubLbl`) to match the shared module

**Verification:**
- Open main game UI → Observatory mode
- Drag scrubber — confirm paused/live states work
- Exit and re-enter observatory mode — confirm scrubber resets to LIVE

### Step 8: Refactor swimlane callers to use shared renderer (optional, lower priority)
- Refactor `renderTimelineSwimlane()` in obs-page.js to build lanes array and call `renderSwimlane(config)`
- Refactor `renderObsSwimlane(ss)` in observatory.js similarly
- These are more invasive; do only after steps 1–7 are verified stable

**Verification:**
- Full swimlane renders in both views
- Zoom (Ctrl+scroll) still works
- Tooltips appear on hover

### Step 9: Remove duplicate utility functions
- Once shared functions are confirmed working in both contexts, remove `escHtml`, `fmtK`, `hexToRgba`, `hideTooltip`, `positionTooltip` from obs-page.js (replace with `obsSharedEscHtml` etc.)
- Remove `obsEscHtml`, `obsFmtK`, `obsHexToRgba` from observatory.js (replace with `obsShared*`)

**Verification:** Full regression test on both pages. Run an agent, watch logs, scrub timeline, check tooltips.

---

## 8. Per-Step Verification Checklist

After each step, verify:

| Check | How to verify |
|---|---|
| Observatory view renders in main app | Load `/`, click Observatory, confirm swimlane appears |
| Scrubber shows LIVE dot at end | At `/`, in obs mode with active session |
| Scrubber shows PAUSED dot when dragged back | Drag slider left, dot should change, grid should update |
| Scrubber returns to LIVE at end | Drag slider to max position |
| Standalone `/obs` page loads | Load `/obs`, confirm status + log table |
| Standalone `/obs` connection indicator | Should show LIVE or DISCONNECTED |
| Timeline swimlane renders in `/obs` | Events appear as colored blocks |
| Timeline zoom works in `/obs` | Ctrl+scroll on timeline container |
| Tooltips appear on hover | Hover over timeline blocks in both views |
| Session browser opens | Click Browse in `/obs` |
| Historical session loads in `/obs` | Select a session, confirm replay populates log |
| No console errors | Browser DevTools → Console, check for red errors |
| No 404s for observatory/ scripts | DevTools → Network tab, check script loads |

---

## 9. Risk Register

| Risk | Mitigation |
|---|---|
| `obsScrubLbl` vs `obsScrubLabel` ID mismatch | Normalize in template HTML before wiring shared scrubber |
| `obs-lifecycle.js` depends on `getActiveSession()` from session.js | Load obs-lifecycle.js AFTER session.js in index.html load order |
| `renderSwimlane()` CSS class names differ between views | Keep separate CSS class configs per caller; do not force same class names |
| Both files have `obsScrubUpdate()` — name collision if both loaded | They are in different templates; not a risk unless templates are merged |
| Shared module changes break one page but not the other | Always test both `/` and `/obs` after every step |

---

## 10. Files to Create/Modify Summary

| Action | File |
|---|---|
| **CREATE** | `static/js/observatory/obs-log-renderer.js` |
| **CREATE** | `static/js/observatory/obs-scrubber.js` |
| **CREATE** | `static/js/observatory/obs-swimlane-renderer.js` |
| **CREATE** | `static/js/observatory/obs-lifecycle.js` |
| **MODIFY** | `static/js/obs-page.js` — refactor scrubber calls, remove duplicate utilities |
| **MODIFY** | `static/js/observatory.js` — move lifecycle fns out, refactor scrubber calls, remove duplicate utilities |
| **MODIFY** | `templates/obs.html` — add observatory/ script tags |
| **MODIFY** | `templates/index.html` — add observatory/ script tags, normalize `obsScrubLbl` → `obsScrubLabel` |

**Files NOT touched:** All other templates, `reasoning.js`, `state.js`, `engine.js`, `ui.js`, `llm.js`, `scaffolding.js`, `session.js`, `human.js`, `leaderboard.js`, `dev.js`.
