# Snake 2v2 Teams Agent Evolution Program

## Objective
Create snake agents that win competitive **2v2 team** snake games on a 24x24 grid. You control one snake and have an ally. Team with surviving member(s) wins.

## Agent Interface
Each agent is a standalone Python file with ONE function:
```python
def get_move(state):
    # state keys:
    #   'grid_size': (24, 24)
    #   'my_snake': [[x,y], ...] - head first, LISTS not tuples
    #   'my_direction': 'UP'/'DOWN'/'LEFT'/'RIGHT'
    #   'ally_snake': [[x,y], ...] - your teammate's snake (empty if dead)
    #   'ally_direction': str or None
    #   'enemies': [[[x,y], ...], [[x,y], ...]] - both enemy snakes (empty list if dead)
    #   'enemy_directions': [str or None, str or None]
    #   'food': [[x,y], ...]
    #   'turn': int
    # Returns: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
```

## Critical Rules
- Coordinates are LISTS [x,y] - convert with tuple() before using in sets
- **Allies pass through each other** — you cannot collide with your teammate
- **Enemies are solid** — hitting an enemy body or head kills you
- Build occupied set from enemies only: `enemy_cells = set()`; add both enemy snake segments
- ally_snake can be empty (dead) - always check first
- enemies list entries can be empty (dead) - always check
- Only standard library (random, math, collections). No os/subprocess/socket.
- Must return in <100ms. Must not crash.
- Directions: UP=(0,-1) DOWN=(0,1) LEFT=(-1,0) RIGHT=(1,0)
- (0,0) = top-left, x right, y down
- **24x24 grid** — medium size, 4 snakes make it feel crowded
- **300 max turns** — games end at turn 300 if both teams have survivors
- **10 food items** on the grid at all times

## Agent Memory (prev_moves)
Each agent has access to `state['prev_moves']` — a mutable list that persists across turns within a game.
Use it to track your own history, detect patterns, or implement stateful strategies:
```python
def get_move(state):
    prev = state['prev_moves']  # list — persists across turns
    prev.append({'turn': state['turn'], 'ally_alive': len(state['ally_snake']) > 0})
    # Track ally status to adjust strategy
```

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided (2v2 teams):**
- A team wins when all enemy snakes are dead (crashed into walls, enemies, or themselves)
- If both teams have survivors at turn 300: team with greater total snake length wins
- If total lengths are equal at timeout: draw
- **Allies pass through each other** — you and your teammate cannot collide
- Head-on collision with an enemy: longer snake survives; equal length = both die

**How ELO updates (2v2):**
- Both agents on the winning team gain ELO (as if each beat both opponents)
- Both agents on the losing team lose ELO (as if each lost to both opponents)
- Draw: each agent draws against both opponents
- 4 pairwise ELO updates per game (each agent on team A vs each on team B)

**Key implications for strategy:**
- Coordinate with your ally — you pass through each other, so use that advantage
- Pincer attacks: you and your ally can trap an enemy from both sides
- Protect your ally — if they die, you face a 1v2 disadvantage
- Sacrifice play: sometimes dying to trap an enemy is worth it if your ally survives
- Food sharing: don't compete with your ally for the same food
- If your ally dies, switch to pure survival — you need to outlast both enemies alone

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
3. Use `get_game_replay` to inspect critical moments — especially team coordination
4. Design a counter-strategy and `create_agent`
5. Use `test_match` to verify your agent performs well
6. If it fails tests, use `edit_current_agent` to fix

## Strategies to Explore
- Ally-aware pathfinding: treat ally cells as passable, enemy cells as blocked
- Pincer movement: coordinate with ally to attack the same enemy from opposite sides
- Zone defense: you and your ally each control half the grid
- Focus fire: both snakes target the weaker (shorter) enemy to create a 2v1 advantage quickly
- Ally protection: position yourself between your ally and enemies when ally is short
- Food routing: alternate food targets with ally to avoid competing for the same food
- 1v2 survival mode: when ally dies, maximize space and play ultra-defensively
- Wall sharing: use ally body as a safe barrier (since you pass through it)

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully (provided below the leaderboard). Identify its weaknesses:
- Does it coordinate with its ally or play solo?
- How does it handle the ally-passthrough mechanic?
- What happens when its ally dies early?

Then build an agent specifically designed to counter and outperform it. Every new agent should aim to climb to #1 on the ELO leaderboard.
