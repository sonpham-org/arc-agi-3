# Changelog

All notable changes to this project will be documented here.
Format: [SemVer](https://semver.org/) — what / why / how. Author and model noted per entry. New entries at the top. 

---

## [1.6.0] — fix: Arena Auto Research (Phase 3 — Integration Wiring)
*Author: Claude Opus 4.6 | 2026-03-15*

### Fixed
- **Missing `estimateTokens()` shim** — `callLLM()` called `estimateTokens()` (from `utils/tokens.js`) which wasn't loaded in `arena.html`. Added inline shim. Anthropic provider calls would crash without this.
- **Missing `fetchJSON()` shim** — Added inline shim in `arena.html` for API helper used by `scaffolding.js`.
- **Global `modelsData` not synced** — `arenaLoadModels()` populated `Arena.modelsData` but never updated the global `modelsData` that `getModelInfo()` and `callLLM()` depend on. All LLM calls would fail with "No API key for undefined".
- **Local research mode not switching views** — `arStartLocalResearch()` now calls `switchArenaMode('research')` before starting, so the research view is visible instead of the match layout.
- **Community data fetch on local mode** — `arSelectGame('local')` no longer fetches community research data (which would error on games with no server-side data yet).
- **Model dialog loading** — `arShowLocalDialog()` now awaits `arenaLoadModels()` if models haven't been fetched yet, preventing empty model dropdown.
- **Added `toggleTheme()` shim** — Theme toggle button in arena top nav now works.

---

## [1.5.0] — feat: Arena Auto Research (Phase 2 — Headless Engine + Evolution)
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **Headless match runner** (`arRunHeadless`) — Generic function that runs any of the 9 Arena games with two arbitrary `getMove()` functions, without needing the canvas or visual rendering. Returns winner, turn count, and frame history.
- **Per-game state adapters** — Each game engine (Snake, Tron, Connect4, Chess960, Othello, Go 9x9, Gomoku, Artillery, Poker) has a state adapter that converts internal engine state to the standardized `AGENT_INTERFACE` format agents receive.
- **Per-game seed agents** — Functional baseline agents for each game (greedy/cautious/wall-following for Snake, center-preference for C4, corner-priority for Othello, etc.) replace the old dummy "return UP" seeds.
- **Live tournament canvases** — The 4 mini canvases in the Auto Research right column now animate recent tournament matches frame-by-frame during local research.
- **Automatic test match on agent creation** — When the LLM creates an agent via `create_agent` tool, a quick test match runs against a random existing agent and the result is returned in the tool response.

### Fixed
- **Tournament runner** — Rewrote `arRunTournamentRound` to use the headless match runner instead of the broken strategy-injection approach that couldn't pass custom agent functions to `game.run()`.
- **`test_match` tool** — Now uses the headless runner instead of the broken `game.run()` call.
- **BYOK key storage** — Provider detection from model name now falls back to prefix-based guessing when `getModelInfo()` doesn't have the model.
- **`arSubmitToComminity` typo** — Renamed to `arSubmitToCommunity` (old name kept as alias).

### Architecture
- Engine factories (`_arNewEngine`), turn detection (`_arWhoseTurn`), step dispatchers (`_arStepEngine`), and direction/move parsers handle the 3 game categories: simultaneous (Snake/Tron), turn-based board (C4/Chess/Othello/Go/Gomoku), and physics (Artillery).
- Poker headless not yet supported (returns draw) due to its functional/multi-round architecture.

---

## [1.4.0] — feat: Arena Auto Research (Phase 1)
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **Arena Auto Research tab** — New "Auto Research" mode switcher in the Arena top nav, toggling between Match Mode (existing) and Auto Research view. Auto Research provides per-game LLM-driven agent evolution with community collaboration.
- **Per-game research infrastructure** — 8 new DB tables: `arena_research`, `arena_agents`, `arena_games`, `arena_evolution_cycles`, `arena_comments`, `arena_program_versions`, `arena_votes`, `arena_human_sessions`. Full ELO system with provisional K-factor (K=64 for first 20 games, K=32 after).
- **Game list with C/L buttons** — Left column shows all 9 Arena games categorized. Each game has [C] (Community) and [L] (Local) buttons for launching auto research.
- **Leaderboard** — ELO-ranked agent table per game. Click agent name to view code. "Play ▶" button to challenge any AI agent as a human.
- **Strategy discussion** — Threaded comment system with upvote/downvote per game. Users discuss strategies that feed into program.md evolution steering.
- **program.md viewer/editor** — Rendered/raw/edit modes with version history. "Propose Change" starts a 10-second community vote on program.md updates.
- **Human vs AI play** — Dialog to select time delay (250ms, 500ms, 1000ms, 2000ms, infinite). Human results tracked as `human-{delay}ms` pseudo-agents in the ELO leaderboard.
- **Sustainability limits** — 200 active agents/game cap, random pruning of sub-1000 ELO agents on overflow, 48h history TTL (upsets exempt), 90-day game record TTL, 10 games/pair storage cap, ELO gap skip (>400), daily submission rate limits.
- **15 new API endpoints** under `/api/arena/*` — research overview, agent CRUD, game recording, comments, program.md voting, human play submission.
- **Service layer** (`arena_research_service.py`) — Input validation, rate limiting, orchestration.
- **DB module** (`db_arena.py`) — All arena-specific database operations with ELO calculations, upset detection, and cleanup functions.

### Architecture
- Agents are JS code strings with `getMove(state)` interface (matches existing Arena game engines)
- Community auto research runs server-side via Claude OAuth (Phase 3)
- Local auto research runs in-browser with BYOK keys (Phase 2)
- Human play uses existing JS game engines with Web Worker agent execution (Phase 4)
- Weekly ELO anchoring planned (Glicko-2 re-rating against seed agents pinned at 1000)

---

## [1.3.5] — feat: Arena Agent Mode + Observatory
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **Arena Code/Harness mode** — Each agent panel (A and B) now has an "Agent Mode" dropdown to choose between Code (built-in AI strategies) and Harness (LLM agent with full scaffolding settings). Code mode preserves the existing strategy + personality UI. Harness mode renders the same scaffolding settings as the main app (harness selector, pipeline visualizer, model select, thinking level, planning mode, compact context, BYOK keys).
- **Arena Observatory** — Per-agent observability overlay accessible via "Observe A" / "Observe B" buttons in the match transport bar. Agent A observatory shows the obs panel on the LEFT with the game canvas on the RIGHT. Agent B observatory mirrors this (canvas LEFT, obs RIGHT). Only one agent observable at a time. Agent switch buttons at the top. "Back to Match" returns to the standard match view. Keyboard shortcut: Escape exits obs mode.
- **Arena model loading** — Arena page now fetches `/api/llm/models` to populate harness model selects. Settings persist per-agent to localStorage.
- **Scaffolding schemas in Arena** — `scaffolding-schemas.js` now loads in `arena.html` with server-injected `MODE` and `FEATURES` template variables.

### Changed
- Arena side panels widened from 300px to 320px to accommodate harness settings.
- Arena server route now passes `mode` and `features` template variables (matching the main app route).

---

## [1.3.4] — feat: RGB (Read-Grep-Bash) harness
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **RGB harness** — New scaffolding option based on [alexisfox7/RGB-Agent](https://github.com/alexisfox7/RGB-Agent). Analyzer LLM reads a game prompt log using text-based Read/Grep/Bash tools, then outputs batched JSON action plans. Actions drain from a queue with zero LLM calls per step; queue flushes on score change to re-analyze.
- **Text-based tool calling** — Tool use via `<tool_call>`/`<tool_result>` XML tags in prompt text, works with every model provider (Gemini, Groq, Mistral, LM Studio, Anthropic, OpenAI, etc.). No native tool_use API dependency.
- **Files panel** — New Observatory panel (vertical split of the Memory area) showing the running game prompt log. Syntax-highlighted section markers, score lines, and analysis blocks. Scrubber support for stepping through log history.
- **Action Queue** — Client-side port of RGB Agent's action_queue.py. Parses `[ACTIONS]` JSON plans, drains one per step, flushes on score change.

---

## [1.3.3] — feat: Arena — Artillery upgrade + Texas Hold'em Poker
*Author: Claude Opus 4.6 | 2026-03-14*

### Added
- **Texas Hold'em Poker** — New "Incomplete Information" category. 10-hand match, 100 starting chips, blinds 1/2. Full hand evaluation (high card through straight flush), showdown comparison, seeded deck shuffle. 3 AI strategies: Tight (selective, premium-only), Aggressive (frequent raises, 25% bluff rate), Calculator (pot odds + equity math). Green felt table rendering with card faces, dealer button, pot/chip display.
- **Artillery: Tank Movement** — Tanks can now move left/right (3 units per move) instead of only shooting. Costs a turn. AI strategies use movement tactically: Sniper dodges incoming fire, Lobber repositions to close distance, Wildcard moves chaotically ~33% of turns.
- **Artillery: Projectile Animation** — Shots now animate with 10 sub-frames showing the shell flying along its trajectory. Glowing yellow projectile dot, growing trajectory trail, and explosion flash on impact (larger for direct hits). Movement also animates with 4 slide frames.
- **Artillery: Wind Compensation** — All AI strategies now account for wind in their trajectory simulations (previously ignored). Shared `artSimulateShot()` helper replaces duplicated simulation code.

---

## [1.3.2] — feat: Arena — 4 new games (Connect Four, Tron, Othello, Go 9x9)
*Author: Claude Opus 4.6 | 2026-03-14*

### Added
- **Connect Four** — 7x6 drop-piece game. 3 AI strategies: Dropper (greedy), Blocker (defensive), Balanced (minimax depth 5 with alpha-beta). Blue board with red/orange pieces. Turn-based.
- **Tron (Light Cycles)** — 25x25 grid, simultaneous movement, trail claiming. 3 AI strategies: Space Max (flood fill), Aggressive (cut-off), Cautious (central/safe). Last alive wins.
- **Othello (Reversi)** — 8x8 board with flanking captures. 3 AI strategies: Corner Grabber (positional weights), Maximizer (max flips), Positional (balanced). Green board with blue/red pieces.
- **Go 9x9** — Full Go rules: liberties, captures, ko, Chinese scoring (area + 6.5 komi). 3 AI strategies: Territorial (corners/edges), Aggressive (invade/capture), Balanced (territory+connection). Wooden board with star points.
- **Game tags** — Categorized all 6 Arena games: Territorial (Snake, Tron), Symbolic (Connect Four, Chess960, Othello, Go).
- **Gomoku (5-in-a-row)** — 15x15 board, first to 5 in a line wins. 3 AI strategies: Offensive (attack-weighted), Defensive (block-weighted), Balanced (center control). Line scoring evaluates open/blocked ends. Nearby-moves optimization for fast AI on 225-cell board.
- **Artillery** — 120x80 terrain with midpoint-displacement hills. Two tanks (HP 5) take turns shooting with angle + power. Per-turn wind shifts affect trajectories. 3 AI strategies: Sniper (precise simulation), Lobber (high arcs), Wildcard (jittered aim). Parabolic projectile physics with gravity.
- **Dispatcher pattern** — ARENA_GAMES entries now include `run`, `render`, `preview` functions. Simplified startMatch, renderStep, renderPreview to dispatch via game entry instead of if/else chains.

---

## [1.3.1] — fix: resume error + browse sessions & leaderboard table redesign
*Author: Claude Opus 4.6 | 2026-03-14*

### Fixed
- **Resume returning HTML 500** — `session_service.resume()` now wraps game reconstruction in try/except so errors return JSON instead of Flask's default HTML error page (which caused "Unexpected token '<'" parse error).
- **`fetchJSON` resilience** — Now checks Content-Type header; throws a readable error if server returns non-JSON (e.g., HTML error pages) instead of a cryptic JSON parse failure.

### Changed
- **Browse Sessions redesigned as tables** — Human / AI / My Sessions columns now render as proper `<table>` elements with sticky headers. Columns: Timestamp, Game (with version like "td05 v5"), Result, Level, Steps, Duration, Actions.
- **Action buttons** — Replay (play icon), Resume (for unfinished), Copy ID (clipboard icon with checkmark feedback), Delete (for local sessions). More compact than the old full-text buttons.
- **Leaderboard redesigned** — Both main and drill-down tables now show Levels and Steps prominently. Columns: Game (with version), Result, Lv, Steps, Model/Time/By, Date. Sorted by highest levels first, then fewest steps.
- **`game_version` in sessions & leaderboard APIs** — `/api/sessions` and `/api/leaderboard` now return the `game_version` field to show which version a session was played on.

---

## [1.3.0] — feat: ARC Arena — Agent vs Agent page
*Author: Claude Opus 4.6 | 2026-03-14*

### Added
- **ARC Arena page** (`/arena`) — New standalone page for watching AI agents compete head-to-head in strategy games.
- **Three-column layout** — Left panel (Agent A settings/logs), center (game canvas + scrubber), right panel (Agent B settings/logs). Side panels transition from settings mode (pre-match) to observatory mode (reasoning logs during match).
- **Snake Battle game** — First AI vs AI game: two snakes on a 20x20 grid compete for food. Simultaneous moves, wall/body collisions, fully deterministic with seeded PRNG.
- **Fischer Random Chess (Chess960)** — Full chess engine in JS: legal move generation, check/checkmate/stalemate detection, en passant, promotion. Fischer Random starting positions from seed. Two AI strategies using minimax with alpha-beta pruning (Tactician depth 3, Positional depth 2). Unicode piece rendering on ARC3-colored checkerboard. Turn-based match runner with alternating white/black moves.
- **Per-game strategy selects** — Strategy dropdowns dynamically populate based on the selected game (snake strategies vs chess strategies).
- **Three snake AI strategies** — Greedy (chase food), Aggressive (hunt when longer, feed when shorter), Cautious (flood-fill space analysis to avoid traps).
- **Personality bars** — Visual indicator of each strategy's aggression, caution, and greed traits.
- **Match scrubber** — Scrubbing the timeline renders the game state AND auto-scrolls both reasoning logs to the matching turn with highlighting.
- **Keyboard shortcuts** — Space (play/pause), arrows (step), Home/End (jump), Escape (back to setup).
- **Arena logo** — Two blocks pulsing alternately to convey turn-by-turn action.
- **Nav link** — "ARC Arena" link added to the main ARC Observatory top nav.

---

## [1.2.9] — feat: settings UX improvements (model cascade, local token cap, diff overlay, canvas section)
*Author: Claude Sonnet 4.6 | 2026-03-13*

### Added
- **Model cascade for sibling selects** — Changing the primary model in multi-model scaffolds (Three-System, Two-System, Agent Spawn, World Model) now automatically updates sibling selects that haven't been explicitly customized. Sibling follows until the user manually changes it.
- **Local model token cap** — When an lmstudio or ollama model is selected, the corresponding max tokens field is automatically capped at 1024. Applies on select change and on page load/restore.
- **Persistent Canvas section** — Diff overlay controls (show changes, opacity, highlight color) moved from the Graphics subtab (now removed) into a permanent Canvas section always visible below scaffolding settings. No more tab-switching to adjust overlays.
- **Diff overlay on by default** — `showChanges` checkbox now defaults to `checked` in HTML. New users see change highlighting immediately.

### Fixed
- **Opacity slider persistence** — Graphics settings (opacity, color, show-changes) now persist across page reloads via `arc_graphics` localStorage key. Previously the slider reset to 40% on every load.

### Removed
- **Graphics subtab** — Removed the dedicated Graphics tab from the right panel subtab bar. Controls are now in the always-visible Canvas section.

---

## [1.2.8] — fix: OAuth beta header, CORS proxy, metadata identification
*Author: Claude Opus 4.6 | 2026-03-12*

### Fixed
- **OAuth `anthropic-beta: oauth-2025-04-20` header** — OAuth tokens (`sk-ant-oat*`) require this beta header to be accepted by Anthropic's API. Without it, all OAuth calls returned 401 "OAuth authentication is currently not supported." Added to all three Anthropic call paths: proxy (`server/app.py`), server-side provider (`llm_providers_anthropic.py`), and CLI/batch runner (`agent_llm.py`).
- **CORS proxy for OAuth tokens** — Browser-side OAuth calls can't go direct to `api.anthropic.com` (Bearer auth triggers CORS preflight that Anthropic blocks). Added `/api/llm/anthropic-proxy` server route; client-side code in `scaffolding.js` detects `sk-ant-oat` tokens and routes through the proxy automatically.

### Added
- **Request identification metadata** — All Anthropic API calls now include `User-Agent: sonpham-arc3/1.2.8 (ARC Prize research; ...)` with links to three.arcprize.org, arc.markbarney.net, and arc3.sonpham.net, plus contact email. Also sends `metadata.user_id: arc-prize-research` in the request body.
- **Model select auto-sync** — When the main model dropdown changes, all scaffold sub-selects (RLM, Three-System, Two-System, Agent Spawn) that haven't been explicitly customized are automatically set to match. No more filling in every dropdown manually.
- **Visible BYOK key input** — Anthropic key field changed from `type="password"` to `type="text"` with monospace font so tokens are visible and verifiable. Label updated to "API Key / Token".

---

## [1.2.7] — feat: Claude Code OAuth tokens, Opus 4.6, model list reorder, BYOK fix
*Author: Claude Opus 4.6 | 2026-03-12*

### Added
- **Claude Code OAuth token support** — The app now accepts `sk-ant-oat*` OAuth tokens (from `claude setup-token`) in addition to standard `sk-ant-api*` API keys. OAuth tokens are sent as `Authorization: Bearer` instead of `x-api-key`, matching the Anthropic OAuth spec.
  - **`server/services/auth_service.py`** — Relaxed prefix validation to accept both `sk-ant-api*` and `sk-ant-oat*`.
  - **`llm_providers_anthropic.py`** — Added `_is_oauth_token()` helper and `_anthropic_auth_headers()` to route Bearer vs x-api-key based on token type.
  - **`static/js/scaffolding.js`** — Client-side Anthropic calls detect `sk-ant-oat` prefix and switch to Bearer auth headers.
  - **`agent_llm.py`** — CLI/batch runner path updated with the same OAuth token detection.
- **Claude Opus 4.6** added to model registry (`claude-opus-4-6`, $15/$75 per 1M tok, 200k context, image+reasoning+tools).
- **BYOK UI hint for Anthropic** — When an Anthropic model is selected, the key input shows a hint: run `claude setup-token` to get a free OAuth token from your Claude Pro/Max subscription.

### Changed
- **Model list reordered** — LM Studio (local) and Anthropic models now appear first in the dropdown. Previously Gemini was first.

### Fixed
- **BYOK key persistence** — API keys entered in the Model Keys UI were lost on page refresh because the dynamically-rendered `<input>` elements had no event listeners to save to `localStorage`. Added `input` listeners in `static/js/ui-models.js` for both `data-byok-provider` and `data-byok-extra` fields.

---

## [1.2.6] — Fix: restore dropped _humanCanvasClick function
*Author: Claude Opus 4.6 | 2026-03-12*

### Fixed
- **`static/js/human-input.js`** — `_humanCanvasClick()` (the click-to-play handler for ACTION6 games) was referenced by `_setupHumanCanvasClick()` but the function itself was dropped during the Phase 1 split of `human.js`. Restored from master. Without this, `initApp` crashed with `ReferenceError: _humanCanvasClick is not defined`.

---

## [1.2.5] — Clean up incomplete Phase 1 module split: remove dead files and duplicate functions
*Author: Claude Opus 4.6 | 2026-03-12*

### Context
Independent audit found that Phase 1 modularization left two categories of broken artifacts: (1) files that were extracted from `state.js` but never wired into the HTML template, so they sat on disk doing nothing while `state.js` still contained all the original code; (2) functions that were copied into new modules but never removed from the originals, creating silent overwrites at runtime and a double-firing `beforeunload` handler.

### Deleted (dead files, never loaded)
- **`static/js/state-session.js`** (350 lines) — extracted from `state.js` in Phase 25 but never added to `index.html`. All code still lives in `state.js`.
- **`static/js/state-scaffolding.js`** (635 lines) — same situation. All code still lives in `state.js`.

### Removed (duplicate functions)
- **`static/js/human-game.js`** — removed `_humanSaveSession()`, `_humanUploadPayload()`, `_humanBuildPayload()` (lines 187–233), and the duplicate `beforeunload` listener (lines 236–244). Canonical copies remain in `human-session.js`.
- **`static/js/human.js`** — removed `_renderThumbnail()` (lines 200–213). Canonical copy remains in `human-render.js`.

### Fixed
- **Double `beforeunload` beacon upload** — the duplicate handler in `human-game.js` caused `navigator.sendBeacon()` to fire twice on every tab close, potentially uploading the same session data twice. Now fires once (from `human-session.js` only).

---

## [1.2.4] — Fix: Analysis dropdown closes on every LLM response in Observatory
*Author: Claude Sonnet 4.6 | 2026-03-12*

### Fixed
- **`static/js/observatory/obs-lifecycle.js`** — `syncObsReasoning()` was doing `dst.innerHTML = src.innerHTML` on every LLM response (via MutationObserver, debounced 300ms), which wiped the live DOM and closed all `<details>` elements (including the "Analysis" accordion). Fix: save the index positions of open `<details>` before the sync and restore their `open` attribute after.

---

## [1.2.3] — Increase LLM timeout to 600s for local models
*Author: Claude Sonnet 4.6 | 2026-03-12*

### Changed
- **`server/app.py`** — LM Studio proxy timeout: 300s → 600s. Prevents timeouts on slow local models (e.g. large Qwen/Llama runs via LM Studio).
- **`llm_providers.py`** — `LOCAL_MODEL_TIMEOUT` default: 180s → 600s.
- **`llm_providers_openai.py`** — OpenAI-compatible call timeout: 180s → 600s (covers Ollama, LM Studio, Groq, Cloudflare, etc. through the CLI path).

---

## [1.2.2] — UI: Move agent transport controls above Intervene button
*Author: Claude Sonnet 4.6 | 2026-03-12*

### Changed
- **`templates/index.html`** — Swapped the vertical order of the agent transport bar (Autoplay / Undo / Restart) and the "Intervene as Human" controls. The transport bar now appears directly below the game canvas (where Intervene was), so agent start controls are visible without scrolling. Intervene sits below it.

---

## [1.2.1] — Senior Audit of Phase 1 Modularization
*Author: Claude Opus 4.6 (audit) | 2026-03-12*

### Context
Independent senior audit of the `refactor/phase-1-modularization` branch (56 commits, 145 files, +30k/-14k lines) prior to opening PR against `master`. Audit conducted by a different author to catch issues missed during development.

### Bugs Found & Fixed

**Python (3 issues):**
- **Broken import in `agent_scaffold.py:28`** — `_PLANNER_SYSTEM_PROMPT` was renamed to `_PLANNER_SYSTEM_PROMPT_TEMPLATE` during the refactor but this import was never updated. Would crash at runtime on any code path that imports `agent_scaffold` (batch runner, CLI agent). Fixed by updating the import.
- **`server/app.py` not directly executable** — Running `python server/app.py` failed with `ModuleNotFoundError: No module named 'models'` because the project root wasn't on `sys.path` when executed from the `server/` subdirectory. Fixed by adding `sys.path.insert(0, str(_ROOT))` after `_ROOT` is computed.
- **Dead backup file committed** — `server/app.py.backup` (836 lines, the original `server.py`) was tracked in git. Removed.

**JavaScript (7 issues — app completely broken in browser):**
- **`redrawGrid` function dropped** — Existed in master's `ui.js`, removed during Phase 24 split but never added to `ui-grid.js`. Caused immediate crash on page load. Restored to `ui-grid.js`.
- **Duplicate `let currentUser`** — Declared in both `state.js:20` and `session.js:23`. This `SyntaxError` prevented `session.js` from parsing at all, which cascaded into: `updateEmptyAppState` undefined, `initApp` never called, no games loaded, no session tabs. Removed duplicate from `session.js`.
- **`_PROMPT_SECTION_MAP` dropped** — Was in master's `session.js`, removed during split, never added to `session-views.js` where `_getPromptSections()` uses it. Restored to `session-views.js`.
- **3 split modules never added to template** — `session-storage.js`, `session-replay.js`, `session-persistence.js` were created on disk (Phase 9) but never added to `templates/index.html`. Meanwhile `session.js` was slimmed expecting them to be loaded. Added script tags in correct load order.
- **Duplicate declarations across split files** — `session-replay.js` re-declared `_liveScrubMode`, `_liveScrubViewIdx`, `_liveScrubLiveGrid` (already in `state.js`) and `turnstileVerified` (already in `session-persistence.js`). Removed duplicates.
- **`renderSessionTabs()` and `getTabDotClass()` dropped** — Were in master's `session.js`, removed during split, put in no file. Called 20+ times across the codebase. Restored to `session.js`.

### Fixed
- `CLAUDE.md` — updated two stale references from `server.py` to `server/state.py` for `HIDDEN_GAMES` list location

### Audit Summary
- **Test results:** 278 passed, 40 skipped, 0 failed
- **All module imports:** 37/37 pass (including `agent_scaffold` after fix)
- **Architecture grade:** 8/10 — service layer, DB split, and agent decomposition are well-executed
- **Remaining warnings (non-blocking):** `SYSTEM_MSG` duplication in `constants.py` and `models.py`; `FEATURES` dict duplicated in `server/state.py` and `server/helpers.py`; non-refactor work (ws03/ws04 games, Codex integration) mixed into refactor branch; chaotic phase numbering in commit history

---

## [1.2.0] — refactor/phase-1-modularization (phases 6-30)
*Author: VoynichLabs AI Team | 2026-03-12*

### Changed
- `server.py` (2566 lines) **deleted** — replaced by `server/app.py` (thin route handlers) + `server/services/` (business logic). Procfile updated to `gunicorn server.app:app`.
- `server/services/` — service layer fully populated: `auth_service.py`, `session_service.py`, `game_service.py`, `social_service.py`, `llm_admin_service.py`
- `db.py` — refactored to connection facade; domain functions extracted to `db_sessions.py`, `db_auth.py`, `db_llm.py`, `db_tools.py`, `db_exports.py`
- `llm_providers.py` — refactored to router; per-provider implementations extracted to `llm_providers_openai.py`, `llm_providers_anthropic.py`, `llm_providers_google.py`, `llm_providers_copilot.py`
- `agent.py` — `play_game()` (245 lines) decomposed into 6 focused helper functions; extracted `agent_llm.py`, `agent_response_parsing.py`, `agent_history.py`
- `static/js/llm.js` — split: `llm-executor.js` (plan execution), `llm-config.js`, `llm-timeline.js`, `llm-reasoning.js`, `llm-controls.js`
- `static/js/ui.js` — split: `ui-models.js`, `ui-tokens.js`, `ui-tabs.js`, `ui-grid.js`
- `static/js/state.js` — split: `state-scaffolding.js` (635L), `state-session.js` (350L)
- `static/js/session.js` — split: `session-storage.js`, `session-replay.js`, `session-persistence.js`, `session-views.js`, and further into `session-views-grid.js`, `session-views-history.js`
- `static/js/human.js` — split: `human-social.js`, `human-render.js`, `human-input.js`, `human-session.js`, `human-game.js`
- `static/js/obs-page.js` — split: `obs-swimlane.js`, `obs-scrubber.js`, `obs-session-loader.js`
- `static/js/ab01-page.js` — split: `ab01-constants.js`, `ab01-entities.js`, `ab01-render.js`, `ab01-input.js`, `ab01-physics.js`, `ab01-session.js`

### Added
- `models.py` — canonical `MODEL_REGISTRY` (39 models, single source of truth); `server/app.py` and frontend fetch from here
- `exceptions.py` — structured error handling: `AppError`, `DBError`, `LLMError`, `handle_db_error`, `handle_errors` decorator; 18 bare `except` patterns replaced
- `server/state.py`, `server/helpers.py` — shared request/session state extracted from app
- `tests/test_prompt_builder.py`, `tests/test_llm_providers.py`, `tests/test_db.py`, `tests/test_exceptions.py`, `tests/test_bot_protection.py`, `tests/test_services.py` — 283 passing unit tests (0 failures)
- `docs/modularization/module-map.md` — complete module reference for all Python and JS modules
- `AGENTS.md` — codebase structure guide for AI agents

### Fixed
- Session persistence bugs 1, 2, 4 (undo durability, atomic DB writes, dedup via `_action_dict_from_row`)
- LM Studio timeout: `scaffolding.js` 1500ms→15000ms, `llm_providers.py` 90s→180s; `LOCAL_MODEL_TIMEOUT` env var added
- `get_current_user()` gap: was in `server.py` but missing from `server/helpers.py` — would have caused `NameError` at runtime

---

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
- File headers (Author/Date/PURPOSE/SRP-DRY) on all 29 new and modified files per `coding-standards.md`
- `CHANGELOG.md` updated with v1.1.0 refactor entry (restored from master, not overwritten)
- `docs/2026-03-11-refactor-headers-plan.md` — plan doc for header compliance task

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
- LM Studio provider block missing from `_callLLMInner` after Phase 5 extraction (calls fell through to "Unsupported provider")
- LM Studio discovery + dummy key logic missing from `loadModels()` after Phase 5 extraction
- `LMSTUDIO_CAPABILITIES` constant missing from `scaffolding.js` after Phase 5 extraction
- `providerOrder` missing `'Lmstudio'` entry — LM Studio models not grouped in dropdown
- Server-side discovery returning `provider: "local"` instead of `provider: "lmstudio"` for port 1234
- Server-side discovery `ImportError` on `LMSTUDIO_CAPABILITIES` silently caught by `except Exception: pass`, killing all local model discovery
- `esc()` function undefined (`ReferenceError`) — refactor extracted `escapeHtml` to `formatting.js` but deleted the `esc` shorthand used ~26 times in `llm.js` and `share-page.js`

---

## [1.0.2] — feature/lmstudio-support
*Author: Mark Barney + Cascade (Claude Opus 4.6 Thinking) | 2026-03-10*

### Fixed
- **"No API key for LM Studio" error** (`scaffolding.js`) — LM Studio is a local program, not a cloud API. It doesn't need an API key. But `_callLLMInner` has a key gate that all non-Puter providers must pass. The LM Studio call block was positioned after this gate with no key set, so every LLM call threw immediately. Fix: `loadModels()` now sets a dummy key (`'local-no-key-needed'`) in localStorage when LM Studio models are discovered (both server-side and client-side paths). The key gate passes, the LM Studio block ignores the key and uses `baseUrl` from localStorage instead. No restructuring of provider routing needed.
- **CORS blocking all LM Studio calls** (`scaffolding.js`, `server.py`) — LM Studio does NOT send `Access-Control-Allow-Origin` headers. Every browser fetch to `localhost:1234` — both discovery AND chat completions — was blocked by CORS policy. Discovery was already fixed by server-side probing in staging mode. LLM calls now route through `/api/llm/lmstudio-proxy` on our Flask server, which forwards to `localhost:1234` server-to-server (no CORS). Same pattern as the existing Cloudflare Workers AI proxy (`/api/llm/cf-proxy`). Custom base URLs (Cloudflare Tunnel) are passed through.
- **LM Studio 400 Bad Request on system-only messages** (`scaffolding.js`) — LM Studio Jinja templates require at least one `user` message. The scaffold orchestrator sends `[{role:'system', content:...}]` only, which LM Studio rejects with `"No user query found in messages"`. Fix: LM Studio branch in `_callLLMInner` now promotes the system message to user role when no user message is present. Same pattern as the existing Gemini branch.
- **LM Studio proxy swallowing error details** (`server.py`) — `/api/llm/lmstudio-proxy` used `raise_for_status()` which replaced the actual LM Studio error body with a generic httpx exception string. Fix: proxy now forwards the actual response body and status code from LM Studio, so the client sees the real error message.

---

## [1.0.1] — feature/lmstudio-support
*Author: Mark Barney + Cascade (Claude Opus 4.6 Thinking) | 2026-03-10*

### Added
- **LM Studio provider** (`scaffolding.js`, `ui.js`, `models.py`, `server.py`) — users can now run inference against locally loaded LM Studio models directly from the web UI. Browser calls `localhost:1234/v1/chat/completions` directly; Railway server is never involved in the call path.
- **`LMSTUDIO_CAPABILITIES` lookup table** (`models.py`) — known capability overrides (reasoning, image) keyed on `api_model` ID. Used by both CLI (`agent.py`) and browser discovery paths.
- **`docs/lmstudio-integration.md`** — developer notes capturing every integration pitfall hit during implementation.
- **`docs/2026-03-10-lmstudio-discovery-plan.md`** — architecture plan for completing client-side discovery (pending).
- **`coding-standards.md`** — Mark's coding standards, now tracked in repo.
- **`AGENTS.md`** — agent-specific coding instructions incorporating all standards.

### Fixed
- `reasoning_content` fallback in `_callLLMInner` (`scaffolding.js`) — GLM-series models return thinking tokens in `reasoning_content`; `content` comes back `null`. Blind `content || ''` read produced empty output. Fixed to `content || reasoning_content || ''`.
- LM Studio models not appearing in model selector dropdown (`scaffolding.js`) — `'Lmstudio'` was missing from `providerOrder`; all discovered models were silently dropped.
- Duplicate model entries in dropdown (`server.py`) — static registry entries and dynamic discovery both produced entries for the same `api_model`, showing every model twice. Dynamic entries now skip any `api_model` already in the static registry. Static LM Studio entries subsequently removed entirely (see below).
- Embedding models appearing in chat model selector (`server.py`) — `text-embedding-*` models filtered out of dynamic discovery results.
- Wrong image capability on `qwen3.5-35b-a3b` (`models.py`, `server.py`) — model has confirmed vision encoder (mmproj, from load logs) but was marked `image: False`. Corrected to `True`.
- Misleading CORS error message (`scaffolding.js`) — told users to enable CORS when LM Studio 0.3+ has it on by default. Updated to direct users to check model load state instead.

### Removed
- Static LM Studio model registry entries (`models.py`) — `lmstudio-qwen3.5-35b`, `lmstudio-glm-4.7-flash`, `lmstudio-glm-4.6v-flash` were hardcoded for one developer's machine. Removed in favour of pure dynamic discovery so any model a user has loaded appears automatically.

### Completed (plan execution by Cascade, using Claude Opus 4.6 Thinking)
- **Server-side LM Studio discovery removed** from `server.py` — port 1234 removed from `LOCAL_PORTS`; `is_lmstudio` branching and `LMSTUDIO_CAPABILITIES` server-side lookup cleaned up. Ports 8080/8000 retained for other local servers.
- **Browser-side LM Studio discovery finalized** in `scaffolding.js` `loadModels()` — fetches `{baseUrl}/v1/models` directly from browser with 1.5s timeout, filters embedding models, annotates capabilities from `LMSTUDIO_CAPABILITIES`, merges into `modelsData`. Dead dedup code removed.
- **File headers added** to all edited files (`scaffolding.js`, `ui.js`, `server.py`, `models.py`) per `coding-standards.md`.
- **`docs/lmstudio-integration.md` rewritten** — architecture section now documents client-side discovery flow; pitfalls #3, #6, #7 updated to reference correct files; testing section replaced with browser-based verification; client↔server communication analysis and next-developer notes added.
- **`CHANGELOG.md` created and maintained** (this file) — was missing, now tracks all changes.
- **Dead `LMSTUDIO_CAPABILITIES` import removed** from `server.py` — no longer used after server-side discovery removal. Comment added explaining it lives in `models.py` for CLI agent path only.
- **Hybrid discovery strategy implemented** — LM Studio does NOT send CORS headers by default, so browser-only discovery fails silently. Fix: server-side discovery restored for staging mode (server is local, no CORS needed); client-side discovery kept for production (Railway, requires user to enable CORS in LM Studio). Client-side dedup prevents doubles when both paths find models. Console warning added for CORS/network failures to aid debugging. New pitfall documented in `docs/lmstudio-integration.md`.

---

## [1.0.0] — master baseline
*2026-03-10*

Initial versioned baseline. Captures the state of `master` at the time `CHANGELOG.md` was introduced. All prior work is recorded in git history.
