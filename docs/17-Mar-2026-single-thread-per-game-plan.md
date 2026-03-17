# Arena Heartbeat Refactor — Single Tournament Loop

**Date:** 2026-03-17
**Goal:** Prevent SQLite corruption by reducing concurrent DB writers.

## Problem

Current architecture spawns **12 daemon threads** all writing to one SQLite file:
- 6 tournament grinder threads (`_tournament_grinder` per game)
- 6 evolution threads (`_evolution_loop_for_game` per game)

This caused `database disk image is malformed` on production.

## Architecture

**Before (12 threads):**
```
_tournament_loop() → 6 grinder threads (one per game, all grinding matches nonstop)
_evolution_loop()  → 6 evolution threads (one per game, LLM calls + agent creation)
```

**After (7 threads):**
```
1 tournament thread  → round-robins all games, grinds matches sequentially
6 evolution threads  → one per game (LLM-bound, mostly idle waiting on API)
```

Tournament is CPU-bound and fast — one thread handles all games easily.
Evolution is LLM-bound (waiting on Anthropic API) — per-game threads are fine since they're mostly sleeping.

## Scope

**In:**
- Replace `_tournament_loop()` (which spawns 6 grinder threads) with a single `_tournament_loop()` that round-robins games itself
- Keep `_evolution_loop()` with per-game threads (unchanged)
- Keep all game logic, validators, ELO, exports unchanged

**Out:**
- No changes to game engines, DB layer, web API, evolution logic

## TODOs

1. Rewrite `_tournament_loop()`:
   - On startup: seed all games, warm live buffers
   - Main loop: iterate `_ACTIVE_GAMES` round-robin
     - For current game: run `_run_tournament(game_id, match_count=TOURNAMENT_BATCH)`
     - If 0 games played, skip to next game (don't sleep — just move on)
     - Periodic cleanup per game every 10 min
   - Only sleep when ALL games returned 0 matches in a full round

2. Remove `_tournament_grinder()` (the per-game grinder function)

3. Keep `_evolution_loop()` and `_evolution_loop_for_game()` as-is

4. Update `start_arena_heartbeat()`: just 2 top-level threads (tournament + evolution launcher)

5. Verify: import check + local startup + Railway deploy

## Verification

- `python -c "from server.app import app; print('OK')"` — import check
- Railway logs show `[tournament] ...` (single thread) + `[evolution:snake] ...` etc (per-game)
- No "malformed" errors
- Arena endpoints return 200 for all games
