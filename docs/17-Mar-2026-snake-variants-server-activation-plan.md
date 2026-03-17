# Snake Variants Server Activation Plan

**Date:** 2026-03-17
**Goal:** Enable server-side tournament + evolution for `snake_random`, `snake_royale`, and `snake_2v2` variants, and re-enable `snake` (classic).

---

## Current State

- **Python engines exist:** `SnakeGame` (2P) and `SnakeGame4P` (royale/2v2) in `server/snake_engine.py`
- **Python engine MISSING:** `SnakeRandomGame` (2P with procedural walls) — only exists in JS (`arena.js`)
- **`_ACTIVE_GAMES`** = `['chess960', 'othello']` — all snake paused
- **`_GAME_SEEDS`** has no entries for `snake_random`, `snake_royale`, `snake_2v2` — seeding will silently do nothing
- **`_run_match()`** falls through to `_run_snake_match()` for any unknown game_id — no dispatch for 4P or random
- **`_validate_code()`** falls through to `_validate_agent_code()` which uses classic 2P test states — 4P agents will fail validation because they receive a state with `my_snake`/`enemy_snake` (2P format) instead of `snakes[]` (4P format)
- **Seed programs** (`.md`) exist for all 4 variants ✅
- **Seed agent files** (`.py`) only exist for classic snake: `random_agent.py`, `greedy_agent.py`, `wall_avoider.py` — these won't work for 4P or random-walls variants
- **ELO for 4P:** `arena_record_game` takes `agent1_id`/`agent2_id` (2 agents). 4P games have 4 agents — needs a different recording approach.

---

## Scope

### In Scope

1. Port `SnakeRandomGame` to Python (`server/snake_engine.py`)
2. Add `_run_snake_random_match()` and `_run_snake_4p_match()` match runners in `arena_heartbeat.py`
3. Update `_run_match()` dispatch for all 4 variant IDs
4. Write variant-specific seed agents (3 per variant = 9 new files)
5. Add variant entries to `_GAME_SEEDS`
6. Write variant-specific `_TEST_STATES` and validators for random/royale/2v2
7. Handle 4P ELO: record pairwise results (6 pairs per match) or adapt `arena_record_game`
8. Add all 4 snake variants to `_ACTIVE_GAMES`
9. Update CHANGELOG

### Out of Scope

- Client-side JS changes (already working)
- UI/arena.html changes
- Cross-variant agent sharing (classic agents auto-participating in other variants)
- New program.md content (already written)

---

## Architecture

### 1. SnakeRandomGame Python Engine

**Where:** `server/snake_engine.py` — new class `SnakeRandomGame(SnakeGame)`

Port the JS `SnakeRandomGame` logic:
- Inherit from `SnakeGame`
- Add `walls: Set[Tuple[int, int]]` attribute
- `_generate_walls(seed)`: Port the JS cluster generation (4-8 L/T-shaped clusters)
- `_flood_fill_check()`: Validate >60% reachability from both spawn points
- Override collision check: add wall collision (`head in self.walls`)
- Override `_spawn_food()`: only interior cells (avoid walls and border ring)
- Override `get_state()`: add `'walls': [list(w) for w in self.walls]`
- Port `mulberry32` PRNG for deterministic wall generation (match JS output exactly)

**Why inherit from SnakeGame:** Same 2P mechanics, just adds walls. Minimal code duplication.

### 2. Match Runners

**Where:** `server/arena_heartbeat.py`

```python
def _run_snake_random_match(code_a, code_b):
    """2P snake with random walls. New seed per match."""
    fn_a, fn_b = _load_agent_fn(code_a), _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, ...}
    seed = int(time.time() * 1000) % (2**32)
    game = SnakeRandomGame(seed=seed)
    return game.run(fn_a, fn_b)

def _run_snake_4p_match(code_a, code_b, mode='royale'):
    """4P snake. code_a controls snakes 0,2; code_b controls 1,3."""
    fn_a, fn_b = _load_agent_fn(code_a), _load_agent_fn(code_b)
    if not fn_a or not fn_b:
        return {'winner': None, ...}
    config = {'width': 30, 'height': 30, 'max_turns': 400, 'food_count': 12}
    if mode == '2v2':
        config = {'width': 24, 'height': 24, 'max_turns': 300, 'food_count': 10}
    game = SnakeGame4P(**config, mode=mode)
    return game.run([fn_a, fn_b, fn_a, fn_b])  # A controls 0,2; B controls 1,3
```

**Updated dispatch:**
```python
def _run_match(game_id, code_a, code_b):
    if game_id == 'chess960':
        return _run_chess960_match(code_a, code_b)
    if game_id == 'othello':
        return _run_othello_match(code_a, code_b)
    if game_id == 'snake_random':
        return _run_snake_random_match(code_a, code_b)
    if game_id == 'snake_royale':
        return _run_snake_4p_match(code_a, code_b, mode='royale')
    if game_id == 'snake_2v2':
        return _run_snake_4p_match(code_a, code_b, mode='2v2')
    return _run_snake_match(code_a, code_b)
```

### 3. 4P ELO Recording

**Problem:** `arena_record_game` takes 2 agent IDs. In 4P, one `code_a` controls snakes 0+2 and one `code_b` controls snakes 1+3 — so it's still effectively a 2-agent match. The winner maps to an agent:

- Royale: winner is a player index (0-3). Indices 0,2 → agent1 wins. Indices 1,3 → agent2 wins. None → draw.
- 2v2: winner is 'team0' → agent1 wins. 'team1' → agent2 wins. None → draw.

**This means no DB schema changes are needed** — the 4P match is run as agent1 vs agent2 (each controlling 2 snakes), and the result maps directly to a winner_id.

### 4. Seed Agents (9 new files)

**Where:** `server/arena_seeds/`

For `snake_random` (2P + walls):
- `snake_random_random_agent.py` — random valid move (wall-aware)
- `snake_random_greedy_agent.py` — BFS to nearest food avoiding walls
- `snake_random_wall_avoider.py` — flood-fill safety + wall avoidance

For `snake_royale` (4P FFA):
- `snake_royale_random_agent.py` — random valid move (4P state format)
- `snake_royale_greedy_agent.py` — nearest food, avoid all other snakes
- `snake_royale_cautious_agent.py` — maximize open space, avoid crowding

For `snake_2v2` (4P teams):
- `snake_2v2_random_agent.py` — random valid move (team state format)
- `snake_2v2_greedy_agent.py` — nearest food, only dodge enemies (allies pass through)
- `snake_2v2_team_agent.py` — coordinate with ally, target enemy snakes

All agents implement `get_move(state)` → `'UP'|'DOWN'|'LEFT'|'RIGHT'`.

### 5. Variant-Specific Validation

**Where:** `server/arena_heartbeat.py`

New test state arrays for each variant:

- `_TEST_STATES_RANDOM` — 12 scenarios with `walls` key in state dict, `grid_size: (20, 20)`
- `_TEST_STATES_ROYALE` — 12 scenarios with `snakes[]` array (4 entries), `my_index`, `grid_size: (30, 30)`
- `_TEST_STATES_2V2` — 12 scenarios with `snakes[]`, `ally_snake`, `enemies[]`, `my_index`, `grid_size: (24, 24)`

New validators: `_validate_snake_random_code()`, `_validate_snake_royale_code()`, `_validate_snake_2v2_code()`

Updated dispatch:
```python
def _validate_code(game_id, code):
    if game_id == 'chess960':
        return _validate_chess960_code(code)
    if game_id == 'othello':
        return _validate_othello_code(code)
    if game_id == 'snake_random':
        return _validate_snake_random_code(code)
    if game_id == 'snake_royale':
        return _validate_snake_royale_code(code)
    if game_id == 'snake_2v2':
        return _validate_snake_2v2_code(code)
    return _validate_agent_code(code)
```

### 6. `_GAME_SEEDS` Update

```python
_GAME_SEEDS = {
    'snake': {
        'seed_random': 'random_agent.py',
        'seed_greedy': 'greedy_agent.py',
        'seed_wall_avoider': 'wall_avoider.py',
    },
    'snake_random': {
        'seed_random': 'snake_random_random_agent.py',
        'seed_greedy': 'snake_random_greedy_agent.py',
        'seed_wall_avoider': 'snake_random_wall_avoider.py',
    },
    'snake_royale': {
        'seed_random': 'snake_royale_random_agent.py',
        'seed_greedy': 'snake_royale_greedy_agent.py',
        'seed_cautious': 'snake_royale_cautious_agent.py',
    },
    'snake_2v2': {
        'seed_random': 'snake_2v2_random_agent.py',
        'seed_greedy': 'snake_2v2_greedy_agent.py',
        'seed_team': 'snake_2v2_team_agent.py',
    },
    'chess960': { ... },
    'othello': { ... },
}
```

### 7. Activate

```python
_ACTIVE_GAMES = ['snake', 'snake_random', 'snake_royale', 'snake_2v2', 'chess960', 'othello']
```

---

## TODOs (ordered)

### Phase 1: Engine + Match Runners
- [ ] Port `SnakeRandomGame` to Python in `snake_engine.py` (including `mulberry32` PRNG, wall generation, flood-fill validation)
- [ ] **Verify:** Unit test `SnakeRandomGame` — walls generate, food avoids walls, game runs to completion
- [ ] Add `_run_snake_random_match()` in `arena_heartbeat.py`
- [ ] Add `_run_snake_4p_match()` in `arena_heartbeat.py`
- [ ] Update `_run_match()` dispatch
- [ ] **Verify:** Run each match runner standalone with dummy agents, confirm result dict format

### Phase 2: Seed Agents + Validation
- [ ] Write 3 seed agents for `snake_random` → `server/arena_seeds/`
- [ ] Write 3 seed agents for `snake_royale` → `server/arena_seeds/`
- [ ] Write 3 seed agents for `snake_2v2` → `server/arena_seeds/`
- [ ] Write `_TEST_STATES_RANDOM` (12 scenarios with walls)
- [ ] Write `_TEST_STATES_ROYALE` (12 scenarios, 4P FFA state format)
- [ ] Write `_TEST_STATES_2V2` (12 scenarios, 4P team state format)
- [ ] Add `_validate_snake_random_code()`, `_validate_snake_royale_code()`, `_validate_snake_2v2_code()`
- [ ] Update `_validate_code()` dispatch
- [ ] **Verify:** Each seed agent passes its variant's validator
- [ ] Update `_GAME_SEEDS` dict

### Phase 3: Activate + Smoke Test
- [ ] Update `_ACTIVE_GAMES` to include all 4 snake variants
- [ ] **Verify:** Start heartbeat, confirm seeding runs for each variant, tournament produces games
- [ ] **Verify:** Evolution creates valid agents for each variant (at least 1 generation)
- [ ] Update file headers in all modified files

### Phase 4: Docs
- [ ] Update `CHANGELOG.md`

---

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — new entry for snake variant server activation
- File headers in `server/snake_engine.py`, `server/arena_heartbeat.py`

---

## Risks

1. **Wall generation parity:** Python `mulberry32` must match JS output exactly for deterministic replays. If seeds differ, walls will look different client vs server. Mitigation: test with known seed, compare wall sets.
2. **4P agent reuse:** Each agent's `get_move()` is called for 2 snakes (indices 0+2 or 1+3) — the agent must use `state['my_index']` to differentiate. Seed agents must handle this correctly.
3. **Evolution model cost:** Adding 4 more game_ids to the evolution loop means 4× more LLM calls. Current rotation is every ~5-10 mins per game. With 6 active games, each variant evolves every ~30-60 mins. Acceptable.
