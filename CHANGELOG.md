# Changelog

All notable changes to this project will be documented here.
Format: [SemVer](https://semver.org/) — what / why / how. Author and model noted per entry. New entries at the top.

---

## [1.13.9] — fix: unplayable Foundation games hidden; level selector placeholders; remove Game Results tab
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Fixed
- **"Game engine failed: Unexpected token '<'" on new Foundation games** — Games in the ARC Prize API but not downloaded locally (`local_dir=None`) appeared in the sidebar and caused `Path(None)` TypeError in `game_source()`, returning HTML 500 instead of JSON. Fixed: `list_games()` now filters out `local_dir=None` entries; `game_source()` guards against it with a proper JSON 404. `_env_date()` and `_is_newer_env()` hardened for `None` local_dirs.
- **Level selector showing blank/black canvases** — Level cards showed empty `<canvas>` elements when thumbnails failed. Now draws a numbered placeholder immediately; real thumbnail overwrites when available.

### Removed
- **"Game Results" tab from Play as Human right panel** — showed nothing useful. Removed button, pane, and all related JS calls.

---

## [1.13.8] — feat: restore Agent Spawn harness with prompt caching; fix settings blank on stale scaffolding type
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Added
- **Agent Spawn harness restored** — Re-added to `SCAFFOLDING_SCHEMAS` (orchestrator + subagent model selects, thinking levels, max tokens, budget/turn/history params) and back in the JS bundle. The harness was removed in 1.13.4 but the JS file was kept on disk.
- **Prompt caching for Agent Spawn (Anthropic)** — Orchestrator loop: static premise + game reference moved to system message (cached by Anthropic handler every turn). Dynamic state (grid, memories, history) sent as user message only. Subagent multi-turn loop: non-last user messages marked `_cacheableHistory` so growing conversation prefix is cached on each iteration. Both save significant cache read tokens when using Anthropic models.

### Fixed
- **Agent Settings blank after harness removal** — If `localStorage` held a removed scaffolding type (`rlm`, `three_system`, etc.), `renderScaffoldingSettings()` returned early with an empty panel. Now validates against current `SCAFFOLDING_SCHEMAS` and falls back to `linear`, clearing the stale key.
- **Anthropic prompt caching: empty content block** — Handler now skips empty `content` text blocks when building Anthropic message arrays. Required for `_cacheableHistory` on fully-stable user messages (Agent Spawn multi-turn subagent conversations).

---

## [1.13.7] — feat: game sidebar uses dynamic Foundation detection, no subscript for ID-only games
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Changed
- **Dynamic Foundation detection** — Replaced hardcoded `_ARC_FOUNDATION_GAMES = ['ls20','vc33','ft09','lp85']` with `_isFoundationGame(game)` that detects Foundation games dynamically: title equals ID (e.g. "LS20" = game_id "ls20"). `ws03`/`ws04` are hardcoded exceptions (Observatory despite ID-like titles). New Foundation games from the ARC Prize API now auto-sort into the correct section without code changes.
- **No subscript for Foundation games** — Games like LS20, FT09 showed a redundant "LS20" label below their title. Subscript (`.game-id-label`) now only renders for Observatory games that have descriptive names (e.g. "Feeding Frenzy" → subscript "FR01").
- **Staging tag limited to px/sn** — The `[staging]` tag was shown on all Observatory games. Now limited to Potion Mixer (`px`) and Sneeze (`sn`) only.
- **Shared `_renderGames()` helper** — `human.js` and `session-views-grid.js` now call `_renderGames(el, games, onClick)` from `ui.js` instead of duplicating Foundation/Observatory split logic.

---

## [1.13.6] — fix: game version selection uses date_downloaded, not hash sort
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Fixed
- **LS20 serving wrong version** — When two Foundation game versions exist (e.g. `ls20-cb3b57cc` and `ls20-9607627b`), the server picked the one with the lexicographically larger hash suffix. `cb3b57cc > 9607627b` alphabetically, so the older version (2026-03-18) beat the newer one (2026-03-25) even though the newer one has updated mechanics. Fixed in `server/helpers.py` (`get_game_version`, new `_env_date` helper) and `server/app.py` (`list_games` deduplication and `game_source` env selection) to prefer the version with the newer `date_downloaded` in `metadata.json`. Alphabetical game_id is now only a tiebreaker.

---

## [1.13.5] — feat: hide 5 games from prod, remove 5 advanced harnesses from UI
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Changed
- **HIDDEN_GAMES expanded** — Added `ar` (Arbitrage Runner), `gh` (Ghost Heist), `pc` (Parallel Clone), `ts` (Tower Siege), `td` (Tower Defense) to `HIDDEN_GAMES` in `server/state.py`. These games are now hidden from `/api/games` in prod (still visible in staging and via `?show_all=1`).
- **Advanced harnesses removed from Play as Agent UI** — Removed `rlm`, `three_system`, `two_system`, `agent_spawn`, and `world_model` entries from `SCAFFOLDING_SCHEMAS` in `static/js/config/scaffolding-schemas.js`. The harness selector now shows only: Linear, Linear w/ Interrupt, RGB. The corresponding JS files (`scaffolding-rlm.js`, `scaffolding-three-system.js`, `scaffolding-agent-spawn.js`, `scaffolding-world-model.js`) are kept on disk for reference but no longer loaded by `templates/index.html`. Dead model-select populate/restore blocks for the removed harnesses removed from `scaffolding.js`.

---

## [1.13.4] — fix: Browse Session sidebar matches Play as Human/Agent
*Author: Claude Sonnet 4.6 | 2026-03-25*

### Fixed
- **Browse Session sidebar visual consistency** — The game list sidebar in Browse Session mode was narrower (220px vs 260px) and had a different header style (smaller font, dimmed color, lighter padding) compared to Play as Human and Play as Agent. Updated `.browse-sidebar` to 260px, and updated `.browse-sidebar-header` to match `.sidebar h2` (13px font, accent color, 14px/16px padding). Also removed the 4px inner padding from `.browse-sidebar-list` so game cards align flush like the other modes.

---

## [1.13.3] — fix: Postgres monitor GROUP BY error
*Author: GPT-5.3 Codex | 2026-03-19*

### Fixed
- **Arena monitor 500 on PostgreSQL** — `arena_get_llm_monitor_stats()` selected `provider` while grouping only by `model`, which is invalid on PostgreSQL and caused `/api/arena/monitor/stats` to fail with a grouping error. Updated the query to group by both `model` and `provider`.

---

## [1.13.2] — fix: split tournament and evolution heartbeats
*Author: GPT-5.3 Codex | 2026-03-19*

### Changed
- **Independent heartbeat lifecycle** — Tournament and evolution now have separate start/stop controls in `server/arena_heartbeat.py`, so tournament threads can run even when evolution is paused.
- **Prod bootstrap split** — `server/app.py` now starts tournament and evolution heartbeats independently in prod, with explicit pause controls via `ARENA_TOURNAMENT_PAUSED=1` and `ARENA_EVOLUTION_PAUSED=1`.
- **Heartbeat status detail** — `/api/arena/heartbeat/status` now exposes separate `tournament_running` and `evolution_running` flags plus per-game evolution worker thread counts.

---

## [1.13.1] — feat: Tower Siege real-time two-player mode (ts01 v3)
*Author: Claude Sonnet 4.6 | 2026-03-19*

### Changed
- **Real-time mode** — World auto-ticks via ACT7 at 4 FPS (live mode). No turn alternation: both players click freely at any time. Added `"live"` tag and `"default_fps": 4` to metadata.
- **Per-entity action cooldowns** — After any move/tool, unit must wait 3 ticks (0.75 s); after P2 moves a guard, it must wait 4 ticks (1 s). Prevents click-spamming. Cooling entities shown as dim (LGRAY background + color dot).
- **Bomb timer** — Wall removed after 4 ticks (1 s) instead of 1 tick.
- **Freeze after contact-kill** — Soldier frozen 4 ticks (1 s) instead of 1 tick.
- **Gate period** — 12 ticks (3 s cycle at 4 FPS) instead of 3 turns.
- **Turn limits redesigned** as tick counts: L1=120 (30 s), L2=160 (40 s), L3=200 (50 s), L4=240 (60 s), L5=160 (40 s, tight).
- **HUD** — Replaced `T:XX/YY` turn counter with `{N}S` seconds countdown (turns red at <10 s). Right panel shows `LIVE` label in green instead of `ATK`/`DEF`.
- **New version directory** `environment_files/ts/00000003/` — prior versions left intact for replay.

---

## [1.12.1] — feat: Snake Random benchmark bots + blue anchor styling
*Author: Claude Opus 4.6 | 2026-03-18*

### Added
- **3 benchmark bots for Snake Random arena** — Adapted from proven open-source snake AI algorithms (chuyangliu/snake, Hawstein/snake-ai):
  - `seed_bfs` — BFS shortest path to food with flood-fill fallback. Medium difficulty.
  - `seed_safe` — BFS + virtual snake simulation + escape-route verification + tail-chase. Hard difficulty.
  - `seed_space` — Flood-fill territory maximization + enemy space denial. Hard/aggressive playstyle.
- **Blue anchor agent styling** — All anchor/benchmark agents (`is_anchor=1`) now display with a blue row tint and blue agent name in the leaderboard, matching how human agents have purple styling.

---

## [1.12.0] — feat: Code Arena — AutoResearch for Code Optimization
*Author: Claude Opus 4.6 | 2026-03-18*

### Added
- **Code Arena page** (`/code`) — New AutoResearch page for evolving optimized code solutions. Agents compete head-to-head on benchmarks: same inputs, faster correct solution wins, ELO-ranked.
- **4 challenge categories, 7 sub-challenges**:
  - **Sorting** — Evolve fast sorting algorithms across 6 input distributions (random, nearly-sorted, reversed, duplicates, small, large). Metric: total ms.
  - **TSP** — Evolve tour-finding heuristics on 4 fixed city sets (cluster, grid, random, large). Metric: tour length.
  - **Cache Eviction** — Evolve cache eviction policies on 3 access traces (Zipf, scan, working set). Metric: hit rate %.
  - **Assembly (WASM)** — Write WebAssembly Text Format (WAT) programs: fibonacci, array sum, sort, prime count. Compiled to WASM and run natively in-browser.
- **Benchmark-based matches** — Both agents run the same deterministic benchmark suite, faster correct solution wins. Reuses the existing ELO tournament system from Games Arena.
- **Full evolution loop** — LLM tool-calling loop with query_leaderboard, read_agent, create_agent, test_match tools. Adapted from arena-autoresearch.js for code challenges.
- **Shared infrastructure** — Reuses arena API endpoints (`/api/arena/research/code_sort`, etc.), DB tables, ELO system, program.md versioning, AI Heartbeat comments.
- **Seed program.md files** — Strategy guides for each challenge with agent interface specs, benchmark descriptions, and optimization tips.

---

## [1.11.0] — feat: Program.md Auto-Evolution
*Author: Claude Opus 4.6 | 2026-03-18*

### Added
- **Program.md auto-evolution** — Every heartbeat tick, the system checks if the current program.md has created >=10 agents or >=2 hours have elapsed. When triggered, Sonnet 4.6 analyzes top agents, their code, recent game results, and previous program versions to generate an improved program.md that is auto-applied as the new default.
- **Evolution conversation log** — The full LLM conversation that produced each program.md version is stored and viewable via a "View Log" button in the UI.
- **Version dropdown** — Users can browse all program.md versions for each game via a dropdown in the program.md section header. Each version shows its author, trigger reason, and whether it was AI-evolved.
- **Heartbeat announcement** — When a new program.md is evolved, a heartbeat message is posted announcing the version and summarizing the changes.
- **New API endpoints** — `GET /api/arena/program/<game_id>/versions` lists all versions; `GET /api/arena/program-version/<id>` now includes conversation log.
- **DB migration** — Added `conversation_log`, `trigger_reason`, `auto_evolved` columns to `arena_program_versions`.

---

## [1.10.2] — feat: Agent Profile Tabs — Games, Code, Program, Evolution Log
*Author: Claude Opus 4.6 | 2026-03-18*

### Added
- **Tabbed agent profile view** — Clicking an agent in the leaderboard now shows a full tabbed profile with 4 tabs: Recent Games (game replays), Code (syntax-highlighted agent source), Program.md (strategy document at creation time), and Evolution Log (full LLM conversation that created the agent).
- **Evolution cycle storage** — The full LLM conversation from each evolution cycle is now saved to `arena_evolution_cycles` and linked to created agents via `evolution_cycle_id`. Previously the conversation log was generated but discarded.
- **Profile API endpoint** — `GET /api/arena/agents/<game_id>/<agent_id>/profile` returns all tab data in a single call (agent info, code, program, evolution log, games).
- **DB migration** — Added `evolution_cycle_id` column to `arena_agents` table.

---

## [1.10.1] — chg: Arena model rotation — drop Sonnet/Opus, add Gemini Flash Lite
*Author: Claude Opus 4.6 | 2026-03-18*

### Changed
- **Model rotation** — Removed Sonnet 4.6 and Opus 4.6 from arena evolution (all agents they created failed). New rotation: 3x Haiku 4.5, 1x Gemini 3.1 Flash Lite, 1x Gemini 3.1 Pro.
- **Cost tracking** — Added `gemini-3.1-flash-lite-preview` pricing ($0.075/$0.30 per 1M tok) to arena tool runner.

---

## [1.10.0] — fix: Sonnet/Opus evolution + AI Heartbeat analysis reports
*Author: Claude Opus 4.6 | 2026-03-18*

### Fixed
- **Sonnet/Opus unable to create agents** — `max_tokens` was 8192 for all models. Sonnet/Opus are more verbose and hit the limit, causing `stop_reason: max_tokens` which silently exits the tool loop without creating an agent. Now: Haiku=8192, Sonnet=16384, Opus=16384. Also handle `max_tokens` stop by nudging the model to call `create_agent` on next round.
- **Opus timeout** — `REQUEST_TIMEOUT` was 120s for all models. Opus can take 3-5 min. Now per-model: Haiku=120s, Sonnet=180s, Opus=300s.

### Added
- **AI Heartbeat analysis** — Every 10 evolutions per game, Haiku analyzes the arena state (top agents, model performance, creation rates, costs) and posts a status report as a heartbeat comment. Covers: dominant strategies, model effectiveness, issues, and suggested directions.

---

## [1.9.9] — fix: Monitor page rewrite — use evolution sessions, not dead arena_llm_calls
*Author: Claude Opus 4.6 | 2026-03-18*

### Fixed
- **Monitor page showing stale data** — `arena_monitor.html` was reading from `arena_llm_calls` (no longer written to since v1.9.8). Rewrote to read from `arena_evolution_sessions` which has all active data.
- **Evolution thread crash risk** — `arena_get_leaderboard()` call at end of evolution tick was outside try/except. If DB threw, the thread would silently die. Wrapped in try/except.

### Changed
- **`arena_get_llm_monitor_stats()`** — All queries now source from `arena_evolution_sessions` instead of legacy `arena_llm_calls`. Returns per-game breakdown, per-model stats with cache info, and session-level cost/latency/calls data.
- **Monitor dashboard** — Shows per-evolution stats: API calls, tool calls, tokens (in/out/cache), cost (actual with prompt caching), latency, agents created. Added "By Game" breakdown table and "Cost / Agent" card.

---

## [1.9.8] — feat: Model rotation, prompt caching, session monitoring, Gemini evolution
*Author: Claude Opus 4.6 | 2026-03-18*

### Changed
- **Model rotation** — Evolution now cycles: 3x Haiku, 1x Sonnet, 1x Opus, 1x Gemini 3.1 Pro (was Haiku-only). ~10 agents/hour across 6 games with varied model strengths.
- **Prompt caching** — Anthropic tool loop uses `cache_control` on system prompt + tools. After round 1, subsequent rounds pay ~90% less for cached content.
- **Session-level monitoring** — Replaced per-API-call logging with one `arena_evolution_sessions` record per evolution cycle. Tracks: api_calls, tool_calls, tokens, cache read/write, cost, latency, rounds, agents_created.

### Added
- **Gemini tool-calling loop** — `run_tool_loop_gemini()` in arena_tool_runner.py via Google GenAI SDK. Uses `GEMINI_API_KEY` env var.
- **`arena_evolution_sessions` table** — One row per evolution cycle with full session stats.

---

## [1.9.7] — feat: Offline agent generation CLI + upload API
*Author: Claude Opus 4.6 | 2026-03-17*

### Added
- **Offline agent upload API** — `POST /api/arena/agents/<game_id>/offline` accepts agents generated locally. Server runs full 12-scenario validation before admitting to tournament pool. Rate limited to 20/day.
- **`offline_agent_runner.py`** — CLI tool for generating arena agents locally using any LLM provider. Fetches Program.md + leaderboard from server, runs LLM tool-calling loop, validates agent, uploads to arena.
- **`offline_llm.py`** — Multi-provider LLM tool-calling module supporting Anthropic, OpenAI, Google Gemini, and LM Studio (OpenAI-compatible). All providers use httpx directly (no SDK dependencies).
- **`offline_` naming convention** — All offline agents are auto-prefixed `offline_` and enforced server-side. Instantly identifiable on the leaderboard.
- **`submit_offline_agent()`** in `arena_research_service.py` — Offline-specific validation + rate limiting.

### Usage
```bash
# Generate with Anthropic
python offline_agent_runner.py --game snake --provider anthropic

# Generate with local LM Studio
python offline_agent_runner.py --game snake --provider lmstudio

# Generate 3 agents with Gemini
python offline_agent_runner.py --game snake --provider gemini --count 3

# Dry run (validate only, no upload)
python offline_agent_runner.py --game snake --provider openai --dry-run
```

---

## [1.9.6] — feat: Simplified Program.md + open library imports + library request logging
*Author: Claude Opus 4.6 | 2026-03-18*

### Changed
- **Program.md files simplified** — All 6 game programs (snake classic, random walls, royale, 2v2, chess960, othello) reduced from ~980 lines total to ~365 lines. Removed detailed strategy instructions, common bugs, ELO math explanations. Kept: game goal, agent interface, rules, memory, tools. Added instruction to study top agents and devise counter-strategies.
- **Import sandbox: allowlist → blocklist** — Agents can now use any installed Python library (numpy, scipy, etc.), not just the 6 pre-approved stdlib modules. Dangerous modules (os, subprocess, socket, sys, etc.) remain blocked. Agents should test-import with try/except and provide fallback logic.
- **Evolution prompt** — Removed "Only standard library imports" restriction. Now tells evolution LLM that agents may use any available library.

### Added
- **Library request logging** — When an agent tries to import a non-blocked library that isn't installed, it's automatically logged to `arena_library_requests` table (deduplicated per game+library per hour). Surfaced in monitor stats and via `GET /api/arena/library-requests`.
- **New dated Program.md versions** — `*-2026-03-18.md` files in `server/arena_seeds/` for all 6 games. `_resolve_program_file()` auto-selects these as the latest version.

---

## [1.9.4] — feat: Dead snake corpse rendering in 4P modes
*Author: Claude Opus 4.6 | 2026-03-17*

### Added
- **Corpse rendering** — When a snake dies in Battle Royale or 2v2 Teams, its body remains visible as a gray cross-hatched corpse underneath living snakes. Corpses are walkable but visually persist for the rest of the match.
- **Cross-hatch overlay** — Dead snake cells rendered with diagonal cross-hatch lines (both `renderSnake4PFrame` grid renderer and `_arRenderMiniFrame` mini-canvas renderer).

### Changed
- **`SnakeGame4P` (JS + Python)** — On death, snake body saved to `corpses[]` array before clearing for collision. `getGrid()` draws corpses first, then alive snakes on top.
- **Frame snapshots** — Both code-mode and harness-mode match runners include `corpseCells` in each frame for replay rendering.

---

## [1.9.5] — feat: Snake agent memory dict + Program.md versioning
*Author: Claude Opus 4.6 | 2026-03-17*

### Added
- **Agent memory dict** — All 4 snake variants (classic, random, royale, 2v2) now expose `state['memory']` — a persistent `{}` dict per agent that survives across all turns within a game. Agents can store arbitrary data (enemy models, caches, strategy state). Capped at 500KB serialized; exceeding wipes to `{}`.
- **Program.md versioning** — Each game's Program.md now has dated copies (`snake_random_program-2026-03-17.md`, etc.) in `server/arena_seeds/`. The `_resolve_program_file()` function finds the latest dated version for each game.
- **Agent → Program.md linkage** — New `program_file` TEXT column on `arena_agents` table stores which Program.md file was active when the agent was created during evolution. Enables tracing agent lineage to specific program versions.

### Changed
- **Program.md files** — All 4 snake program files updated with new `## Agent Memory` section documenting both `prev_moves` (list) and `memory` (dict). State key comments in Agent Interface sections now list `memory`.
- **Validation test states** — All test scenarios across 4 variants include `'memory': {}` to match the new state shape.

---

## [1.13.0] — feat: Tower Siege two-player mode (ts01 v2)
*Author: Claude Sonnet 4.6 | 2026-03-19*

### Added
- **Two-player hot-seat mode** for Tower Siege (`ts01`). Player 1 (Attacker) controls Sapper/Scout/Soldier units; Player 2 (Defender) manually controls guards and can spawn reinforcements.
- **Alternating turns**: P1 acts (unit move or tool) → P2 acts (guard move, spawn, or pass by clicking outside grid) → world advances (bombs tick, freeze counters decrement, turn increments) → repeat.
- **Guard reserves**: Each level gives P2 a starting count of spare guards spawnable on any open cell adjacent to the tower exterior walls (excluding tower interior). Spawn zone shown as maroon dots when it's P2's turn with reserves available.
- **Defender click UX**: Guard selection highlighted with LightMagenta border; valid guard move destinations shown as Red dots; non-grid click passes P2's turn. Right panel shows `ATK`/`DEF` turn label, guard count `G:N`, reserve count `R:N`, and `PAS` hint.
- **Soldier contact-kill (both directions)**: Works whether attacker walks into a guard or P2 moves a guard into a Soldier cell — guard dies, Soldier frozen 1 turn.
- **New version directory** `environment_files/ts/00000002/` — old `00000001/` left intact for single-player session replay.
- **Five redesigned levels** balanced for 2-player: L1 (1 guard+1 reserve), L2 (1 guard+1 reserve, timed gate), L3 (2 guards+2 reserves), L4 (3 guards+2 reserves), L5 (3 guards+3 reserves, tight budget).

---
## [1.9.3] — feat: Snake variants server-side activation (tournament + evolution)
*Author: Claude Opus 4.6 | 2026-03-17*

### Added
- **SnakeRandomGame Python engine** — Ported procedural wall generation (L/T clusters, flood-fill validation, mulberry32 PRNG) from JS to `server/snake_engine.py`. Border-ring collision, wall collision, interior-only food spawning.
- **Server-side match runners** — `_run_snake_random_match()` and `_run_snake_4p_match()` in `arena_heartbeat.py`. 4P winner mapped to 2-agent format (agent A controls snakes 0,2; agent B controls 1,3).
- **9 variant seed agents** — 3 per variant (random/greedy/specialized) in `server/arena_seeds/`. Each uses the correct state format for its variant.
- **Variant-specific validation** — 12 test scenarios each for `snake_random` (with walls), `snake_royale` (4P FFA state), `snake_2v2` (4P team state with allies/enemies). Dispatched via `_validate_code()`.
- **`_GAME_SEEDS` entries** — All 4 snake variants now seed baseline agents on first tournament start.

### Changed
- **`_ACTIVE_GAMES`** — Now includes `snake`, `snake_random`, `snake_royale`, `snake_2v2`, `chess960`, `othello` (was only chess960 + othello).
- **`_run_match()` dispatch** — Routes all 4 snake variant IDs to their correct engine.
- **Heartbeat auto-start re-enabled** in `server/app.py` (was disabled during variant implementation).

---

## [1.9.2] — fix: Arena "Play against Agent" — engine parity, renderer, in-dialog UI
*Author: Claude Opus 4.6 | 2026-03-17*

### Fixed
- **JS SnakeGame engine now matches Python engine** — 8 food (was 1), 350 max turns (was 200), spawn at (3,3)/(W-4,H-4) (was centered), no wall ring (was ring of wall cells), tie-break by body length (was score)
- **Agent move state format** — human play sends Python-compatible state to `/api/arena/agent-move` (`grid_size`, `my_snake`, `my_direction`, `enemy_snake`, `enemy_direction`, `food` array, `prev_moves`) instead of JS-format state that Python agents couldn't parse
- **Tournament renderer for human play** — uses `_arRenderMiniFrame()` (dark theme, rounded snake segments, eyes, neon colors, score overlay) instead of flat ARC3 grid palette
- **Game renders in popup dialog** — canvas shows inside `#arHumanDialog` overlay instead of destroying the research view; quit/game-over closes the popup and research view is intact
- **All 4 snake variants playable** — Classic, Random Maps (walls), Battle Royale (4P), and 2v2 Teams (4P). For 4P modes, 2 extra agents are randomly picked from the leaderboard. State format adapters handle 2P walls and 4P `snakes`/`ally`/`enemies` fields.

---

## [1.9.1] — feat: Subdomain routing — Observatory & Arena at separate domains
*Author: Claude Opus 4.6 | 2026-03-16*

### Changed
- **Subdomain routing** — `arc3.sonpham.net/` serves Observatory, `arena.sonpham.net/` serves Arena. Single Railway service, hostname detection at request time.
- **Cross-links** — Observatory ↔ Arena navigation uses `OBSERVATORY_URL` / `ARENA_URL` env vars for full domain cross-links instead of hardcoded `/obs` / `/arena` paths.
- **Temporary aliases** — `/obs` and `/arena` still work as 302 redirects for backward compatibility.
- **Arena Monitor** — Now accessible at `/monitor`. `/arena/monitor` redirects to `/monitor`.

---

## [1.9.0] — feat: Snake Battle variants (Random Maps, Battle Royale, 2v2 Teams)
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **3 new Snake Battle variants** — each with its own game engine, Program.MD, leaderboard, ELO, games history, and live tournament:
  - **Snake: Random Maps** (`snake_random`) — 1v1 on 20×20 with procedurally generated wall clusters. Maps regenerated each match using millisecond-precision seed for true randomness. Agents must adapt to varied terrain.
  - **Snake: Battle Royale** (`snake_royale`) — 4-player free-for-all on 30×30 grid, 400 max turns, 12 food items. Last snake alive wins. Spawn in 4 corners.
  - **Snake: 2v2 Teams** (`snake_2v2`) — 2v2 team mode on 24×24 grid, 300 max turns. Allied snakes (A+C vs B+D) can pass through each other. Team wins when all opponents are dead.
- **4-player snake engine** — `SnakeGame4P` class (JS + Python) supporting royale and 2v2 modes with simultaneous 4-snake movement, ally pass-through, team win conditions
- **Random map generator** — `SnakeRandomGame` class with seeded procedural wall generation using L/T-shaped clusters, flood-fill validation ensuring playability
- **Agent lineage tracking** — New `program_version_id` column on `arena_agents` tracks which Program.MD version each agent was created under. Passed through heartbeat evolution, API submissions, and client-side creation flows.
- **Loading overlay** — Game switch in Auto Research view now shows a spinner overlay, fires all fetches in parallel (`Promise.all`), and renders content only when fully loaded
- **Sub-tab UI** — Snake Battle game card in Auto Research shows 4 inner variant tabs (Classic / Random Maps / Battle Royale / 2v2 Teams) under one parent card
- **3 seed Program.MD files** — `snake_random_program.md`, `snake_royale_program.md`, `snake_2v2_program.md` with variant-specific agent interfaces and strategy guidance
- **4-player mini-frame renderer** — Live tournament canvases render all 4 snakes with distinct color pairs for royale/2v2 matches
- **4-player AI strategies** — Adapted greedy/aggressive/cautious strategies for 4-player games

### Changed
- **Arena heartbeat** — Temporarily disabled auto-start during snake variants implementation
- **`arena.js`** — Updated ARENA_ENABLED_IDS to include all 4 snake variant IDs, `arBuildGameTabs()` groups snake variants into parent tab with sub-tabs, `arSelectGame()` shows loading overlay
- **`arena-autoresearch.js`** — Added AGENT_INTERFACE entries for new variants, seed agent aliases, 4P state builder, updated mini-frame renderer for multi-snake rendering
- **`db.py`** — Migration adds `program_version_id` column to `arena_agents`
- **`db_arena.py`** — `arena_submit_agent()` accepts `program_version_id`, leaderboard query includes it
- **`arena_research_service.py`** — Added `snake_random`, `snake_royale`, `snake_2v2` to valid game IDs and program file mappings
- **`server/snake_engine.py`** — Added `SnakeGame4P` class for server-side 4-player matches

---

## [1.8.1] — feat: Account system shared with AutoResearch Arena
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **Shared auth module** (`static/js/auth.js`) — extracted login/logout/magic link/Google OAuth/user badge functions from `session.js` into a shared module used by both Observatory and Arena pages
- **Arena login UI** — login button, user badge with dropdown, and login modal added to Arena top nav bar, matching the Observatory's account UX
- **Arena auth init** — `checkAuthStatus()` called on Arena page load; logged-in users see their name badge and can log out
- **Arena contributor attribution** — agent submissions from logged-in users now show their display name instead of generic labels

### Changed
- **`session.js`** — auth functions replaced with import of shared `auth.js`
- **`server/app.py`** — arena route now passes `google_client_id` to template for conditional Google OAuth button

---

## [1.8.0] — feat: Chess960 (Fischer Random) arena autoresearch game
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **Chess960 Python engine** (`server/chess960_engine.py`) — full legal move generation, check/checkmate/stalemate detection, en passant, pawn promotion, 50-move rule, Fischer Random position generation (960 positions)
- **Chess960 Program.md** (`server/arena_seeds/chess960_program.md`) — LLM evolution steering document for chess agent creation
- **3 seed agents** — random, greedy-material, positional (piece-square tables) in `server/arena_seeds/chess960_*.py`
- **12 chess validation scenarios** — generated lazily from engine, covering standard + Fischer Random positions, both colors, opening through middlegame
- **Multi-game heartbeat** — tournament and evolution loops now round-robin across active games (snake + chess960)
- **Chess960 match runner** — random Fischer Random position each game (time-seeded for true randomization)
- **Game-aware dispatch** — `_run_match()`, `_validate_code()`, `_load_default_program()` now dispatch by game_id
- **`ord`/`chr` in agent sandbox** — added to builtins for chess agents that need coordinate parsing
- **Chess960 enabled in frontend** — added to `ARENA_ENABLED_IDS`, config uses `Date.now() % 960` for random positions per match

### Changed
- **Tournament loop** warms live buffer and seeds baselines for all active games, not just snake
- **Evolution loop** alternates between active games on each tick
- **Tool handlers** (`test_match`, `run_test`, `edit_current_agent`, `create_agent`) use game-specific validation and match runners
- **`get_game_replay`** returns chess-specific frame data (last_move, in_check, white_to_move) for chess960 games
- **Heartbeat status** now includes `chess960_engine` flag and `active_games` list
- **Chess960 JS config** — maxMoves raised to 200, seed is a function returning `Date.now() % 960`
- **Chess preview** uses fixed seed 518 (standard chess) for consistent display

---

## [1.7.8] — feat: Create New Agent & AI Heartbeat tabs
*Author: Claude Opus 4.6 | 2026-03-16*

### Changed
- **Center column refactor** — replaced the stacked "Create New Code Agent" + "Strategy Discussion" sections with a tabbed lower panel containing two tabs:
  - **Create New Agent** — BYOK model/key inputs, inline program.md editor with live diff, and Create Agent button. Submits program.md changes before spawning the agent locally via LLM tool-calling loop, then sends to server.
  - **AI Heartbeat** — community + AI chat feed. Users can chat; the server-side evolution heartbeat auto-posts agent creation updates. Stored as `comment_type='heartbeat'` in `arena_comments` table.
- **Program.md viewer** is now read-only in the top area; editing happens in the Create New Agent tab
- **Comments API** (`GET /api/arena/comments/<game_id>`) now accepts `?type=` query param to filter by `comment_type`
- **`arena_get_comments()`** DB function accepts optional `comment_type` filter
- **Server heartbeat** posts AI status messages to the heartbeat chat when new agents are created

---

## [1.7.7] — feat: Agent profile view + leaderboard top-50 cap
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **Agent profile view** — click any leaderboard row to see an agent's profile in the right column, with 2 games vs higher-ELO opponents and 2 games vs lower-ELO opponents rendered as animated canvas replays
- **`GET /api/arena/agents/<game_id>/<agent_id>/games`** API endpoint — returns agent info + recent games with opponent ELO and frame history for replay
- **`arena_get_agent_games_for_profile()`** DB function — fetches agent games with opponent ELO, parses history JSON server-side

### Changed
- **Leaderboard capped at top 50** — "Show all (N)" link at the bottom expands to the full list; toggles back to "Show top 50"
- **Leaderboard rows are clickable** — clicking selects agent and opens profile view; re-clicking deselects and returns to Live Tournament
- **Right column toggles** between Live Tournament and Agent View — Back button and re-click restore the original view with live canvases

---

## [1.7.6] — feat: Arena LLM call monitoring dashboard
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **`arena_llm_calls` DB table** — logs every Anthropic API call from arena evolution (model, status, HTTP code, tokens, cost, latency, auth type)
- **Monitoring dashboard** at `/arena/monitor` — dark terminal-style page showing success/failure rates (1h/24h/all-time), per-model breakdown, auth type stats, recent errors, and full call log
- **Admin access control** via `ARENA_ADMIN_KEY` env var — pass `?key=<secret>` to access; open in local dev when not configured
- **Auto-refresh** every 30s on the dashboard
- **API endpoint** `/api/arena/monitor/stats` returns all monitoring data as JSON
- Cost calculation per call based on model pricing (Haiku/Sonnet/Opus)

### Changed
- `arena_tool_runner.py` — instruments `_call_with_retry()` to log every API attempt (success, error, rate-limit, retry) with latency and token counts
- `arena_heartbeat.py` — sets monitor context (game_id, generation) before each evolution cycle

---

## [1.7.5] — feat: Arena ELO chart improvements + Buy Me A Coffee
*Author: Claude Opus 4.6 | 2026-03-16*

### Added
- **Buy Me A Coffee** button in arena right column, below Live Tournament and above ELO Ratings

### Changed
- **ELO chart** — now shows all agents (was capped at 20), removed x-axis agent name labels for cleaner look, chart fills available vertical space with a minimum height of 160px

---

## [1.7.4] — feat: Grid representation options + Anthropic prompt caching
*Author: Claude Opus 4.6 | 2026-03-15*

### Changed
- **Grid representation** — replaced "Full grid (RLE)" toggle with a `<select>` dropdown offering three formats across all harnesses (Linear, Linear w/ Interrupt, RLM, 3-System, 2-System, Agent Spawn, World Model):
  - **LP16** (default) — mnemonic character encoding (`.1234KMmRBbYOrGP`), preserves color identity in a compact spatial layout
  - **Numeric** — space-separated integer grid, raw color indices
  - **RGB-Agent** — ASCII density ramp (70-char palette), maps color index to brightness character
- **Diff maps** — removed RLE compression from change maps. Now shows per-cell `col X: from->to` format for clarity.
- **Anthropic prompt caching** — three cache breakpoints on Linear/Linear w/ Interrupt prompts:
  1. **System message** (existing) — static per session, always cached
  2. **Compact context** (new) — stable between compaction cycles (~5 calls)
  3. **Old history** (new) — all history entries except the latest step, identical to previous call's history
  User message blocks are reordered (compact → old history → new step → state → grid) so the token prefix is maximally stable between consecutive calls. Each breakpoint is a separate Anthropic content block with `cache_control: ephemeral`.

### Removed
- **RLE encoding** — no longer used in any LLM prompt (grid or diff). `compressRowJS()` kept for backward compat but not called by any scaffolding.

---

## [1.7.3] — feat: Tower Siege game (ts01)
*Author: Claude Sonnet 4.6 | 2026-03-17*

### Added
- New game `ts01` Tower Siege: 5-level click-only siege puzzle with 3 unit types (Sapper/bomb, Scout/grapple+2-cell-move, Soldier/contact-kill) unlocking progressively across levels. Gate timing, gap grappling, and guard avoidance are introduced one mechanic per level. Fully deterministic; all 5 levels verified by automated smoke test.

---
## [1.7.2] — feat: Arena Auto Research layout overhaul
*Author: Claude Opus 4.6 | 2026-03-16*

### Changed
- **Auto Research layout**: Three-column restructure — left (game list with ARC-style canvas thumbnails), center (program.md viewer/editor with live diff, strategy discussion, model/API key), right (leaderboard + recent games + live tournament at 25% width).
- **Game list**: Cards now show rendered game previews using each game's `preview()` function instead of emoji icons. Removed C/L (Community/Local) buttons — community mode is default.
- **Program.md editor**: Edit button toggles inline editor with live green diff highlighting. Accept Changes button submits as a proposal. Cancel reverts to rendered view.
- **Default program.md**: Snake game shows a built-in default program when server has no program yet, with strategy guidelines and agent interface docs.
- **Auto-select snake**: Switching to Auto Research mode auto-selects snake (first enabled game) and loads community data immediately.
- **Markdown rendering**: Improved parser handles code blocks (```), blockquotes, nested lists, headings h1-h4, and inline code.

## [1.7.1] — feat: Prompt Caching + Lexical Grid Encoding (Linear scaffolding)
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **Anthropic prompt caching** — Linear and Linear w/ Interrupt scaffoldings now send the system prompt (ARC description, color palette, agent priors, task format) as a structured content block with `cache_control: {type: 'ephemeral'}`. Cached input tokens cost 10% vs 100% at Anthropic and are served faster. Cache hits logged to console.
- **Lexical grid encoding** — Replaced RLE grid compression with LexicalColorPalette16-inspired single-character encoding. Each ARC3 color maps to a mnemonic character (`.`=White, `K`=Black, `R`=Red, `B`=Blue, `G`=Green, etc.). The 64×64 grid is now a readable character map that preserves spatial layout, helping LLMs reason about 2D positions.
- **System/user message split** — `buildClientPrompt()` now returns `{system, user}` instead of a single string. Static content goes in the system message (cacheable), dynamic content (state, history, grid) goes in the user message. All providers handle this correctly.

### Changed
- Anthropic usage tracking now includes `cache_creation_input_tokens` and `cache_read_input_tokens` fields.
- Grid section header changed from "GRID (RLE, colors 0-15)" to "GRID (64×64 lexical)".
- Color palette prompt now includes the lexical legend mapping.

---

## [1.7.0] — feat: Arena Auto Research (Phase 4 — Human vs AI Play)
*Author: Claude Opus 4.6 | 2026-03-15*

### Added
- **Human vs AI play mode** — Click "Play" next to any agent in the Auto Research leaderboard to challenge it. Supports all 8 non-poker games.
- **Simultaneous games** (Snake, Tron) — Arrow keys or WASD to steer. Game ticks at the chosen delay rate. You are the BLUE player (left side).
- **Turn-based games** (Connect4, Chess960, Othello, Go 9x9, Gomoku, Artillery) — Click to make your move. Valid moves highlighted with green dots/squares. Two-click selection for chess (click piece, then destination).
- **Move timer** — Configurable per-move time limit (250ms, 500ms, 1s, 2s, or infinite). Countdown shown in header. On timeout, a random valid move is played automatically.
- **Result submission** — Game results automatically posted to `/api/arena/human-play/{game_id}` and tracked in the ELO leaderboard as `human-{delay}ms` pseudo-agents.
- **Artillery click-to-aim** — X position maps to angle (0-90°), Y position maps to power (bottom = high power).
- **Human play CSS** — Timer badge styling for the countdown display.

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

## [1.4.0] — refactor: Codebase quality + critical flow tests
*Author: Claude Opus 4.6 | 2026-03-15*

### Fixed
- **HIDDEN_GAMES config drift** — Was defined in 3 places with inconsistent values (5 vs 7 items). Consolidated to single source of truth in `server/state.py`. `"mr"` and `"mw"` prefixes were missing from `helpers.py` and `app.py` copies.
- **SQL injection guard** — `_db_update_session()` now validates column names against a whitelist. Previously built SQL from arbitrary kwargs keys.
- **DB connection leaks** — Migrated `db_sessions.py`, `db_auth.py`, `db_llm.py`, `db_tools.py`, `db_exports.py` from manual `_get_db()`/`conn.close()` to `_db()` context manager with automatic rollback on exception.
- **Missing DB indexes** — Added indexes on `session_actions(session_id)`, `sessions(user_id, created_at)`, `sessions(game_id)` for common query patterns.
- **LM Studio throttle** — Added `lmstudio: 0.0` to `PROVIDER_MIN_DELAY` (was falling back to 1.0s default for a local model).
- **Empty JS catch blocks** — Added `console.warn` to silent `catch {}` blocks in scaffolding.js, llm-config.js, session-persistence.js.

### Changed
- **Shared validators** — Created `server/services/validators.py` with `validate_game_id`, `validate_session_id`, `validate_action_id`, `validate_comment_body`, `validate_vote_direction`, `validate_comment_id`. Removed duplicate definitions from `game_service.py` and `social_service.py`.
- **SYSTEM_MSG** — `models.py` now imports from `constants.py` instead of redefining.
- **Provider dispatch** — Replaced if/elif chain in `llm_providers.py` with dispatch dictionary.
- **Dead blueprint imports** — Removed unused blueprint imports and commented-out registration from `server/app.py`.

### Added
- `tests/test_critical_flows.py` — 24 tests: game start, step, undo, game listing, validators
- `tests/test_db_safety.py` — 10 tests: SQL injection guard, context manager commit/rollback, action persistence
- `tests/test_provider_routing.py` — 14 tests: provider dispatch, fallback, throttling, registry completeness

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

## [1.3.0] — feat: AutoResearch Arena — Agent vs Agent page
*Author: Claude Opus 4.6 | 2026-03-14*

### Added
- **AutoResearch Arena page** (`/arena`) — New standalone page for watching AI agents compete head-to-head in strategy games.
- **Three-column layout** — Left panel (Agent A settings/logs), center (game canvas + scrubber), right panel (Agent B settings/logs). Side panels transition from settings mode (pre-match) to observatory mode (reasoning logs during match).
- **Snake Battle game** — First AI vs AI game: two snakes on a 20x20 grid compete for food. Simultaneous moves, wall/body collisions, fully deterministic with seeded PRNG.
- **Fischer Random Chess (Chess960)** — Full chess engine in JS: legal move generation, check/checkmate/stalemate detection, en passant, promotion. Fischer Random starting positions from seed. Two AI strategies using minimax with alpha-beta pruning (Tactician depth 3, Positional depth 2). Unicode piece rendering on ARC3-colored checkerboard. Turn-based match runner with alternating white/black moves.
- **Per-game strategy selects** — Strategy dropdowns dynamically populate based on the selected game (snake strategies vs chess strategies).
- **Three snake AI strategies** — Greedy (chase food), Aggressive (hunt when longer, feed when shorter), Cautious (flood-fill space analysis to avoid traps).
- **Personality bars** — Visual indicator of each strategy's aggression, caution, and greed traits.
- **Match scrubber** — Scrubbing the timeline renders the game state AND auto-scrolls both reasoning logs to the matching turn with highlighting.
- **Keyboard shortcuts** — Space (play/pause), arrows (step), Home/End (jump), Escape (back to setup).
- **Arena logo** — Two blocks pulsing alternately to convey turn-by-turn action.
- **Nav link** — "AutoResearch Arena" link added to the main ARC Observatory top nav.

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
