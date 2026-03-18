# Snake Agent Evolution Program

## Objective
Create snake agents that win competitive 2-player snake games on a 20x20 grid.

## Agent Interface
Each agent is a standalone Python file with ONE function:
```python
def get_move(state):
    # state keys:
    #   'grid_size': (20, 20)
    #   'my_snake': [[x,y], ...] - head first, LISTS not tuples
    #   'my_direction': 'UP'/'DOWN'/'LEFT'/'RIGHT'
    #   'enemy_snake': [[x,y], ...] - empty list if dead
    #   'enemy_direction': str or None
    #   'food': [[x,y], ...]
    #   'turn': int
    # Returns: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
```

## Critical Rules
- Coordinates are LISTS [x,y] - convert with tuple() before using in sets
- Always: `occupied = set(tuple(s) for s in state['my_snake'])`
- enemy_snake can be empty (dead) - always check first
- Only standard library (random, math, collections). No os/subprocess/socket.
- Must return in <100ms. Must not crash.
- Directions: UP=(0,-1) DOWN=(0,1) LEFT=(-1,0) RIGHT=(1,0)
- (0,0) = top-left, x right, y down

## Agent Memory (prev_moves)
Each agent has access to `state['prev_moves']` — a mutable list that persists across turns within a game.
Use it to track your own history, detect patterns, or implement stateful strategies:
```python
def get_move(state):
    prev = state['prev_moves']  # list — persists across turns
    prev.append({'turn': state['turn'], 'my_head': state['my_snake'][0]})
    # Use prev to detect if you're going in circles, etc.
```

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided:**
- Last snake alive wins (opponent hit wall, self, or your body)
- Head-on collision (both heads on same cell) = both die → longer snake (more apples eaten) wins; equal = draw
- Both crash simultaneously → longer snake wins; equal = draw
- If both survive to turn 350 (max turns): longer snake wins; equal = draw
- 8 food items on the 20x20 grid at all times

**How ELO updates:**
- Expected score: E = 1 / (1 + 10^((opponent_elo - your_elo) / 400))
- Win = 1.0, Draw = 0.5, Loss = 0.0
- New ELO = old ELO + 32 * (actual - expected)
- Beating higher-rated agents gives more ELO; losing to lower-rated agents costs more

**Key implications for strategy:**
- Killing the opponent (making them crash) is the fastest way to win
- If you can't kill them, out-eat them — longer snake wins at timeout
- Draws gain ELO only if opponent is higher-rated; avoid draws against weaker agents
- Survival matters: crashing = instant loss, even if you were longer

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
3. Use `get_game_replay` to inspect critical moments (e.g., last 20 turns of a loss)
4. Design a counter-strategy and `create_agent`
5. Use `test_match` to verify your agent beats the top agent
6. If it fails tests, use `edit_current_agent` to fix

## Strategies to Explore
- BFS/A* pathfinding to nearest food
- Flood fill to maximize reachable space
- Enemy movement prediction and path cutting
- Center board control
- Survival-first: maximize distance from walls and enemy
- Hybrid: BFS when safe, defensive when threatened
- Trap setting: herd enemy toward walls
- Space denial: cut off enemy's reachable area

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully (provided below the leaderboard). Identify its weaknesses:
- What situations does it handle poorly?
- Where does it make suboptimal decisions?
- What strategies would exploit its blind spots?

Then build an agent specifically designed to counter and outperform it. Don't just copy the best agent — find ways to be strictly better:
- If the top agent uses greedy food-chasing, build one with better lookahead or flood fill.
- If the top agent is defensive, build an aggressive space-denial agent that starves it.
- If the top agent lacks enemy prediction, exploit that with path-cutting and trapping.
- Combine the best elements from multiple top agents and add improvements.

Every new agent should aim to climb to #1 on the ELO leaderboard. Prioritize winning over novelty.
