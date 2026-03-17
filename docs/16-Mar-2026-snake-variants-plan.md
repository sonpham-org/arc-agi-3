# Snake Battle Variants — Plan Doc

**Date:** 2026-03-16
**Author:** Claude Opus 4.6
**Status:** IMPLEMENTED — all phases complete

---

## Scope

### In scope
1. **Loading state on game switch** — Show a loading overlay in the Auto Research view until all async content (leaderboard, program.md, recent games, live tournament, elo chart) has loaded
2. **Four Snake Battle variants** — Each with its own game engine, program.md, leaderboard, elo, games tracking, and live tournament:
   - `snake` — Current classic 1v1 on fixed 20×20 grid (unchanged)
   - `snake_random` — 1v1 with procedurally generated maps (walls/obstacles) each match, seeded for determinism
   - `snake_royale` — 4-player free-for-all battle royale, last alive wins, larger grid, more turns
   - `snake_2v2` — 2v2 team mode, allied snakes can pass through each other, team wins if any ally survives
3. **Agent lineage tracking** — Track which `program_version_id` (program.md version) an agent was created under. DB migration + backfill existing agents.
4. **Cross-variant agent participation** — Any agent can be submitted to any snake variant. Same agent name can exist in multiple variants with independent elo/stats.
5. **UI: Sub-tabs in Snake Battle card** — In the Auto Research game tab bar, Snake Battle becomes a parent with 4 variant sub-tabs (Classic, Random Maps, Battle Royale, 2v2)

### Out of scope
- Changes to Chess960 or Othello
- New non-snake games
- Server-side heartbeat changes for new variants (can be done later)
- Modifying the Match Mode (left panel) — only Auto Research view changes

---

## Architecture

### Game IDs
Each variant is a separate `game_id` in the database. This means each automatically gets its own:
- `arena_research` row (program.md, generation counter)
- `arena_agents` pool (leaderboard, elo)
- `arena_games` history
- `arena_comments` / `arena_program_versions`

| Variant | `game_id` | Grid | Players | Max Turns | Special Rules |
|---------|-----------|------|---------|-----------|---------------|
| Classic | `snake` | 20×20 | 2 | 200 | Current rules, unchanged |
| Random Maps | `snake_random` | 20×20 | 2 | 200 | Seeded procedural walls/obstacles |
| Battle Royale | `snake_royale` | 30×30 | 4 | 400 | Last alive wins, 4 spawn corners |
| 2v2 Team | `snake_2v2` | 24×24 | 4 (2+2) | 300 | Allies pass through each other, team wins |

### Map Generation Algorithm (Random Maps variant)
Deterministic from seed using mulberry32 PRNG:
1. Start with border walls (same as classic)
2. Place 4–8 wall clusters: pick random center point, grow an L-shaped or T-shaped wall pattern (3–7 cells each)
3. Validate: ensure both spawn points have flood-fill connectivity to each other and to at least 60% of the grid
4. If invalid, re-seed and retry (max 10 attempts, fallback to classic map)

This keeps maps varied but always playable. The seed is included in match config so replays are deterministic.

### 4-Player Engine Extensions (Royale & 2v2)
New `SnakeGame4P` class extending the existing `SnakeGame` pattern:
- 4 snakes with distinct ARC3 colors:
  - Snake A: Blue (#1E93FF head, #88D8F1 body)
  - Snake B: Red (#F93C31 head, #FF851B body)
  - Snake C: Green (#4FCC30 head, #CCCCCC body)
  - Snake D: Purple (#A356D6 head, #FF7BCC body)
- Spawn positions: 4 corners (offset by 3 from walls)
- Simultaneous moves (all 4 snakes move at once)
- Same collision rules: wall death, self-collision death, opponent-body collision death, head-on double death

**Royale-specific:**
- Winner: last snake alive. If multiple die simultaneously on the last turn, longest wins. If all die, longest wins. All equal = draw.
- More food (12 items on 30×30 vs 8 on 20×20)

**2v2-specific:**
- Teams: (A+C) vs (B+D)
- Allied snakes can pass through each other's bodies (no collision)
- Head-on between allies: no death (pass through)
- Team wins when all opponents are dead
- If time runs out: team with more total length wins

### Agent Interface
Each variant has the same `getMove(state)` interface but with variant-specific state:

**Classic & Random Maps** — Same as current:
```javascript
// state.mySnake, state.enemySnake, state.food, state.grid, state.turn, state.memory
// Random Maps adds: state.walls (array of [x,y] wall positions beyond border)
```

**Royale:**
```javascript
// state.mySnake, state.snakes (array of all 4), state.myIndex (0-3)
// state.food, state.grid, state.turn, state.memory
```

**2v2:**
```javascript
// state.mySnake, state.allySnake, state.enemies (array of 2)
// state.myIndex, state.allyIndex, state.food, state.grid, state.turn, state.memory
```

### Agent Lineage (Program.MD tracking)

**DB Change:** Add `program_version_id` column to `arena_agents`:
```sql
ALTER TABLE arena_agents ADD COLUMN program_version_id INTEGER DEFAULT NULL;
```

This references `arena_program_versions.id` — the specific version of the program.md that was active when the agent was created. `NULL` means "created before lineage tracking" or "manually created."

**Backfill:** Existing agents get `program_version_id = NULL` (acceptable — they predate tracking). The first program version for each game gets recorded going forward.

**Integration points:**
- `arena_submit_agent()` in `db_arena.py` — accept optional `program_version_id` param
- Server heartbeat `_tool_create_agent()` — pass current program version
- Client-side `arRunEvolutionCycle()` — pass current program version when submitting
- Leaderboard display — show "Born from Program v{N}" in agent profile

### UI: Sub-tabs in Snake Battle Card

In the Auto Research game tab bar, instead of one "Snake Battle" tab, we show:

```
┌──────────────────────────────────────────┐
│ 🐍 Snake Battle                          │
│ ┌─────────┬──────────┬────────┬────────┐ │
│ │ Classic │ Random   │ Royale │  2v2   │ │
│ └─────────┴──────────┴────────┴────────┘ │
│ 47 agents · 1,203 games · Gen 15        │
└──────────────────────────────────────────┘
```

The parent card shows the currently selected variant's stats. Clicking a sub-tab:
1. Shows a loading overlay
2. Fetches that variant's data
3. Updates the entire right panel (program.md, leaderboard, recent games, live tournament, elo chart)

### Loading State

When switching games (any game, not just snake variants):
1. Show a semi-transparent overlay with a spinner over the entire research content area
2. Fire all async fetches in parallel: `research/{game_id}`, `live-tournament/{game_id}`, `elo-history/{game_id}`
3. Use `Promise.all()` to wait for all fetches
4. Hide overlay and render all content at once
5. If any fetch fails, show error state but still render whatever succeeded

---

## Modules Touched

### New files
- None — all changes go into existing files

### Modified files

| File | Changes |
|------|---------|
| `static/js/arena.js` | Add `SnakeGame4P` class, `SnakeRandomGame` class, 3 new game entries in `_ALL_ARENA_GAMES`, variant sub-tab UI in `arBuildGameTabs()`, loading overlay in `arSelectGame()`, new renderers for 4P games |
| `static/js/arena-autoresearch.js` | Update `AGENT_INTERFACE` for new variants, update agent creation to pass `program_version_id`, update tournament runner for 4P matches |
| `static/css/arena.css` | Sub-tab styles, loading overlay styles |
| `templates/arena.html` | Loading overlay DOM element |
| `db.py` | Migration: `ALTER TABLE arena_agents ADD COLUMN program_version_id` |
| `db_arena.py` | `arena_submit_agent()` accepts `program_version_id`, leaderboard query includes it |
| `server/services/arena_research_service.py` | Add new game IDs to `ARENA_GAME_IDS`, add program files for new variants |
| `server/arena_seeds/snake_random_program.md` | New: Program.md seed for random maps variant |
| `server/arena_seeds/snake_royale_program.md` | New: Program.md seed for battle royale variant |
| `server/arena_seeds/snake_2v2_program.md` | New: Program.md seed for 2v2 variant |
| `server/snake_engine.py` | Add `SnakeGame4P` class for server-side 4-player matches |
| `CHANGELOG.md` | Entry for all changes |

---

## TODOs — Ordered Implementation Steps

### Phase 1: Database & Backend (no UI changes yet)

- [ ] **1.1** Add `program_version_id` column to `arena_agents` via migration in `db.py`
- [ ] **1.2** Update `arena_submit_agent()` in `db_arena.py` to accept and store `program_version_id`
- [ ] **1.3** Update leaderboard/agent queries to include `program_version_id`
- [ ] **1.4** Add `snake_random`, `snake_royale`, `snake_2v2` to `ARENA_GAME_IDS` in `arena_research_service.py`
- [ ] **1.5** Add program file mappings in `_GAME_PROGRAM_FILES`
- [ ] **1.6** Write seed program.md files for each new variant
- [ ] **1.7** Verify: `python -c "from server.app import app; import db; print('OK')"`

### Phase 2: Game Engines (JS)

- [ ] **2.1** Implement `SnakeRandomGame` class in `arena.js` — extends `SnakeGame` with seeded wall generation
- [ ] **2.2** Implement `SnakeGame4P` class in `arena.js` — 4-player engine for royale & 2v2
- [ ] **2.3** Add royale win condition logic (last alive, longest on simultaneous death)
- [ ] **2.4** Add 2v2 team logic (ally pass-through, team win condition)
- [ ] **2.5** Add `runSnakeRandomMatch()`, `runSnakeRoyaleMatch()`, `runSnake2v2Match()` match runners
- [ ] **2.6** Add renderers: `renderSnakeRandomFrame()`, `renderSnake4PFrame()` (shared by royale & 2v2, with team color coding)
- [ ] **2.7** Add preview renderers for each variant
- [ ] **2.8** Add AI strategies for each variant (adapt existing greedy/aggressive/cautious for 4P)
- [ ] **2.9** Register 3 new entries in `_ALL_ARENA_GAMES` and add to `ARENA_ENABLED_IDS`
- [ ] **2.10** Add `AGENT_INTERFACE` entries for new variants in `arena-autoresearch.js`

### Phase 3: UI — Loading State & Sub-tabs

- [ ] **3.1** Add loading overlay DOM in `arena.html`
- [ ] **3.2** Add CSS for overlay spinner and sub-tabs
- [ ] **3.3** Modify `arSelectGame()` — show overlay, `Promise.all()` fetches, hide overlay on complete
- [ ] **3.4** Modify `arBuildGameTabs()` — group snake variants under a parent tab with sub-tabs
- [ ] **3.5** Wire sub-tab clicks to `arSelectGame(variantId)`
- [ ] **3.6** Show variant-specific stats on the parent card (from currently selected sub-tab)

### Phase 4: Lineage Integration

- [ ] **4.1** Update server heartbeat `_tool_create_agent()` to pass program version when creating agents
- [ ] **4.2** Update client-side `arRunEvolutionCycle()` to include `program_version_id` in agent submission
- [ ] **4.3** Show "Born from Program v{N}" in agent profile/leaderboard tooltip

### Phase 5: 4-Player Tournament Runner

- [ ] **5.1** Update `arRunTournamentRound()` in `arena-autoresearch.js` to handle 4-player games (matchmaking picks 4 agents instead of 2)
- [ ] **5.2** Update mini-frame renderer for 4P live tournament canvases
- [ ] **5.3** Update ELO calculation for 4-player games (pairwise ELO updates between all pairs based on placement)

### Phase 6: Server-side 4P engine

- [ ] **6.1** Add `SnakeGame4P` to `server/snake_engine.py` for batch runner / heartbeat use
- [ ] **6.2** Update heartbeat to handle new game IDs (future — out of scope but prep the structure)

### Phase 7: Verification

- [ ] **7.1** Import check: `python -c "from server.app import app; import db; print('OK')"`
- [ ] **7.2** Manual test: navigate to Arena, switch between all 4 snake variants, verify loading state
- [ ] **7.3** Manual test: run local research on each variant, verify agents created and tournaments run
- [ ] **7.4** Verify leaderboard shows program version lineage
- [ ] **7.5** Push to staging

---

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — Entry covering: 4 snake variants, loading state, agent lineage, sub-tab UI
- `CLAUDE.md` — No changes needed (arena architecture is already documented)
- Seed program.md files — 3 new files in `server/arena_seeds/`
