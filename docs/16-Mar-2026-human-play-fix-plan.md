# Fix "Play Against Agent" Human Play Mode in Arena

**Date:** 2026-03-16
**Author:** Claude Opus 4.6
**Branch:** `staging`

## Scope

### IN
1. JS SnakeGame engine parity — fix to match Python engine (8 food, 350 turns, correct spawns, correct walls, length tie-break)
2. State format adapter — send Python-compatible state dict to `/api/arena/agent-move`
3. Renderer swap — use `_arRenderMiniFrame()` (tournament renderer) for human play
4. In-dialog game play — render canvas inside `#arHumanDialog` overlay, not replacing `arCenter`
5. Result submission — verify POST at game end

### OUT
- Snake Random / Royale / 2v2 human play (only `snake` game ID)
- Server-side Python engine changes
- AI-vs-AI tournament runner changes

## Architecture

### Key Rule Differences (JS vs Python)

| Property | JS SnakeGame | Python SnakeGame |
|---|---|---|
| Food count | 1 single item | 8 (list) |
| Max turns | 200 | 350 |
| Snake A spawn | (4, midY) centered | (3, 3) top-left |
| Snake B spawn | (W-5, midY) centered | (W-4, H-4) bottom-right |
| Walls | Ring of wall cells (playable 1..W-2) | No wall cells (playable 0..W-1) |
| Tie-break | Score (food eaten) | Body length |

### State Format Mismatch

JS `_arBuildState` sends: `{grid, mySnake: {head, body, dir}, enemySnake, food, memory}`
Python agents expect: `{grid_size, my_snake, my_direction, enemy_snake, enemy_direction, food, turn, prev_moves}`

### Files Modified
- `static/js/arena.js` — Fix SnakeGame class + ARENA_GAMES config
- `static/js/arena-autoresearch.js` — State adapter, renderer, UI container
- `templates/arena.html` — Dialog HTML for in-game rendering

## TODOs

### Phase 1: Fix JS SnakeGame Engine
- [ ] 1.1 maxTurns default 200 → 350
- [ ] 1.2 Snake A spawn → (3,3),(2,3),(1,3)
- [ ] 1.3 Snake B spawn → (W-4,H-4),(W-3,H-4),(W-2,H-4)
- [ ] 1.4 Food: single item → array of 8, spawn across full 0..W-1 range
- [ ] 1.5 Remove wall ring from getGrid(), fix collision to `<0 / >=W`
- [ ] 1.6 Food consumption: check against food array, remove eaten, respawn
- [ ] 1.7 Tie-break by body.length not score
- [ ] 1.8 getAIState() returns food as array
- [ ] 1.9 ARENA_GAMES snake config: maxTurns 200 → 350

### Phase 2: Fix State Format
- [ ] 2.1 Create `_hpBuildPythonState(engine, player)` adapter
- [ ] 2.2 Use adapter in simultaneous game loop for `_hpFetchAiMove` calls
- [ ] 2.3 Track prev_moves in HumanPlay state

### Phase 3: Fix Renderer
- [ ] 3.1 Build mini-frame format in `_hpBuildFrame` for snake
- [ ] 3.2 Call `_arRenderMiniFrame()` instead of `game.render()` for snake

### Phase 4: In-Dialog Game Play
- [ ] 4.1 Add `#arHumanGameArea` to dialog HTML
- [ ] 4.2 arLaunchHumanPlay renders in dialog, not arCenter
- [ ] 4.3 arHumanQuit hides dialog, doesn't rebuild research view
- [ ] 4.4 _hpGameOver shows result in dialog with Close button

### Phase 5: Verify
- [ ] 5.1 Full human-vs-agent game with correct rules
- [ ] 5.2 Result submission to server
- [ ] 5.3 AI-vs-AI tournament unaffected
- [ ] 5.4 Clean up headless runner food format references

## Docs / Changelog
- CHANGELOG.md entry for the fix
