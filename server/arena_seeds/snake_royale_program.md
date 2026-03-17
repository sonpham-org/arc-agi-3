# Snake Royale Agent Evolution Program

## Objective
Create snake agents that win competitive **4-player free-for-all** snake games on a 30x30 grid. Last snake alive wins. Placement determines ELO change.

## Agent Interface
Each agent is a standalone Python file with ONE function:
```python
def get_move(state):
    # state keys:
    #   'grid_size': (30, 30)
    #   'my_snake': [[x,y], ...] - head first, LISTS not tuples
    #   'my_direction': 'UP'/'DOWN'/'LEFT'/'RIGHT'
    #   'snakes': [[[x,y], ...], ...] - all 4 snakes (including yours), head first
    #   'directions': ['UP', 'DOWN', ...] - direction for each snake (or None if dead)
    #   'my_index': int - your index in the snakes/directions arrays
    #   'food': [[x,y], ...]
    #   'turn': int
    #   'alive': [True, True, False, True] - which snakes are still alive
    # Returns: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
```

## Critical Rules
- Coordinates are LISTS [x,y] - convert with tuple() before using in sets
- Always build occupied set from ALL alive snakes: `occupied = set()`; for each alive snake, add all segments
- `state['snakes'][state['my_index']]` is YOUR snake (same as `state['my_snake']`)
- Dead snakes have empty body lists `[]` and `alive[i] == False`
- Only standard library (random, math, collections). No os/subprocess/socket.
- Must return in <100ms. Must not crash.
- Directions: UP=(0,-1) DOWN=(0,1) LEFT=(-1,0) RIGHT=(1,0)
- (0,0) = top-left, x right, y down
- **30x30 grid** — larger than standard snake, more room to maneuver
- **400 max turns** — games end at turn 400 if multiple snakes survive
- **12 food items** on the grid at all times

## Agent Memory (prev_moves)
Each agent has access to `state['prev_moves']` — a mutable list that persists across turns within a game.
Use it to track your own history, detect patterns, or implement stateful strategies:
```python
def get_move(state):
    prev = state['prev_moves']  # list — persists across turns
    prev.append({'turn': state['turn'], 'alive': list(state['alive'])})
    # Track which opponents died and when
```

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided (4-player FFA):**
- Last snake alive wins (1st place)
- Order of death determines placement: die first = 4th, die second = 3rd, etc.
- If multiple snakes die on the same turn, the longer snake gets better placement; equal length = tied placement
- If multiple snakes survive to turn 400: ranked by length (most food eaten = 1st)
- Head-on collisions between any two snakes kill both — longer snake survives; equal = both die

**How ELO updates (FFA):**
- Each game generates 6 pairwise results (4 choose 2)
- For each pair: higher placement = win (1.0), same placement = draw (0.5), lower = loss (0.0)
- Standard ELO formula applied to each pair with K=32
- This means 1st place gains ELO from all 3 opponents; 4th loses to all 3

**Key implications for strategy:**
- Survival is paramount — dying first costs the most ELO
- You face 3 opponents, not 1 — collision risks are tripled
- Playing defensively (avoiding all enemies) can secure 2nd/3rd place consistently
- Aggressive play can win 1st but risks early elimination
- The center of the 30x30 grid gives the most escape routes
- Watch for 2v1 situations where two snakes inadvertently trap you

## Your Tools
You have access to these tools — use them before creating agents:

| Tool | What it does |
|------|-------------|
| `query_db(sql)` | Run any SELECT on the DB. Tables: `agents` (name, elo, wins, losses, draws, code), `games` (agent1_id, agent2_id, winner_id, scores, turns, history) |
| `read_agent(agent_name)` | Read any agent's full source code |
| `get_agent_games(agent_name, limit)` | See an agent's recent match results — scores, turns, key moments |
| `get_game_replay(game_id, start_turn, end_turn)` | Inspect a specific portion of a game — snake positions, food, scores per turn. Keep ranges small (10-20 turns) |
| `test_match(agent1_name, agent2_name)` | Run a live match between two agents and see who wins |
| `create_agent(name, code)` | Create a new agent (auto-tested) |
| `edit_current_agent(name, code)` | Fix bugs in an agent you created this round |
| `run_test(agent_name)` | Run validation tests on an agent |

**Recommended workflow:**
1. Study the leaderboard (provided below) and read the top agent's code
2. Use `get_agent_games` to see how the top agent wins and loses
3. Use `get_game_replay` to inspect critical moments — especially multi-snake collisions
4. Design a counter-strategy and `create_agent`
5. Use `test_match` to verify your agent performs well
6. If it fails tests, use `edit_current_agent` to fix

## Strategies to Explore
- Flood fill with multi-enemy awareness — maximize YOUR reachable space, not just avoid one enemy
- Defensive perimeter play: stay near walls to reduce attack vectors from 3 opponents
- Opportunistic aggression: attack weakened (short) snakes while avoiding strong ones
- Territory control: claim a quadrant of the 30x30 grid and defend it
- Late-game awareness: as snakes die, shift from survival to aggression
- Food denial: eat food near opponents to keep them short
- Third-party exploitation: let two enemies fight while you eat safely
- Voronoi-based space partitioning to identify safe zones

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully (provided below the leaderboard). Identify its weaknesses:
- Does it handle 3 opponents correctly or only track one?
- How does it behave when cornered by multiple snakes?
- Does it adapt when opponents start dying?

Then build an agent specifically designed to counter and outperform it. Every new agent should aim to climb to #1 on the ELO leaderboard.
