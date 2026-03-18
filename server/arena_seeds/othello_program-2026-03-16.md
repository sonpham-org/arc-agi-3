# Othello Agent Evolution Program

## Objective
Create agents that win competitive Othello (Reversi) games. The game rewards long-term positional thinking over greedy short-term gains — controlling corners, limiting opponent mobility, and building stable disc formations are more important than maximizing immediate flip count.

## Agent Interface
Each agent is a standalone Python file with ONE function:
```python
def get_move(state):
    # state keys:
    #   'board': 8x8 list of lists (int). 1 = black, -1 = white, 0 = empty.
    #            Row 0 = top row, Col 0 = left column.
    #   'my_color': 1 (black) or -1 (white)
    #   'legal_moves': [[row, col], ...] — all legal moves pre-computed. Never empty when called.
    #   'opponent_last_move': [row, col] or None (None if opponent passed or first move)
    #   'turn': int (half-moves played so far, 0 = black's first move)
    #   'scores': {'black': int, 'white': int, 'empty': int} — current disc counts
    #   'prev_moves': mutable list — persistent memory across turns within this game
    # Returns: [row, col] from state['legal_moves']
```

## Critical Rules
- **Board layout**: 8x8 int array. Row 0 = top, Row 7 = bottom. Col 0 = left, Col 7 = right.
- **Disc encoding**: 1 = black, -1 = white, 0 = empty. Black always goes first.
- **Move format**: `[row, col]` — a two-element list. Must be one of `state['legal_moves']`.
- **MUST return a list from `state['legal_moves']`**. Returning anything else (wrong type, move not in list, None) = instant forfeit.
- **Allowed imports**: Only standard library — `random`, `math`, `collections`, `itertools`, `functools`, `heapq`. No `os`, `subprocess`, `socket`, `sys`, `eval`, `exec`, `open`, `__import__`, or any I/O.
- **Time limit**: Must return in <100ms. Exceeding this = crash = forfeit.
- **Must not crash**. Any unhandled exception = forfeit.
- **Passing**: If a player has no legal moves, their turn is automatically skipped. Your agent is never called when it has no legal moves.
- **Game end**: The game ends when both players pass consecutively, the board is full, or 128 half-moves have been played. The player with more discs wins.

## Board Layout
```
        col0  col1  col2  col3  col4  col5  col6  col7
row 0  [  .     .     .     .     .     .     .     .  ]
row 1  [  .     .     .     .     .     .     .     .  ]
row 2  [  .     .     .     .     .     .     .     .  ]
row 3  [  .     .     .    -1     1     .     .     .  ]   (initial position)
row 4  [  .     .     .     1    -1     .     .     .  ]   (initial position)
row 5  [  .     .     .     .     .     .     .     .  ]
row 6  [  .     .     .     .     .     .     .     .  ]
row 7  [  .     .     .     .     .     .     .     .  ]
```
- Center 4 squares start occupied: (3,3)=-1 (white), (3,4)=1 (black), (4,3)=1 (black), (4,4)=-1 (white).
- To check a square: `board[row][col]` — 1=black, -1=white, 0=empty.
- Your color: `state['my_color']` — 1 or -1. Opponent is `-state['my_color']`.

## Flipping Mechanics
When you place a disc at (row, col):
1. Look in all 8 directions (horizontal, vertical, diagonal)
2. In each direction, find a contiguous line of opponent discs ending with one of your discs
3. All opponent discs in that line are flipped to your color
4. A move is legal only if it flips at least one opponent disc

```python
DIRECTIONS = [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]

def count_flips(board, row, col, my_color):
    opponent = -my_color
    total = 0
    for dr, dc in DIRECTIONS:
        flips = 0
        r, c = row + dr, col + dc
        while 0 <= r < 8 and 0 <= c < 8 and board[r][c] == opponent:
            flips += 1
            r += dr
            c += dc
        if flips > 0 and 0 <= r < 8 and 0 <= c < 8 and board[r][c] == my_color:
            total += flips
    return total
```

## Agent Memory (prev_moves)
Each agent has access to `state['prev_moves']` — a mutable list that persists across all turns within a single game. Use it to track game history, implement stateful strategies, or detect opponent patterns:
```python
def get_move(state):
    prev = state['prev_moves']
    prev.append({
        'turn': state['turn'],
        'opponent_move': state['opponent_last_move'],
        'scores': state['scores'].copy(),
    })

    # Example: detect if opponent is playing corners aggressively
    opp_corner_moves = sum(1 for p in prev if p['opponent_move'] in
                           ([0,0], [0,7], [7,0], [7,7]))

    # ... compute move ...
    return move
```

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided:**
- Most discs when the game ends = win
- Equal discs = draw (0.5 each)
- Max 128 half-moves = game ends, count discs
- Illegal move (returning a value not in legal_moves) = forfeit (instant loss)
- Crash (unhandled exception) = forfeit (instant loss)
- Timeout (>100ms) = forfeit (instant loss)

**How ELO updates:**
- Expected score: `E = 1 / (1 + 10^((opponent_elo - your_elo) / 400))`
- Win = 1.0, Draw = 0.5, Loss = 0.0
- New ELO = old ELO + 32 * (actual - expected)
- Beating higher-rated agents gives more ELO; losing to lower-rated agents costs more

**Key implications for strategy:**
- Disc count is all that matters at game end — but early disc count is misleading
- In Othello, having FEWER discs in the midgame is often advantageous (fewer targets to flip)
- Avoiding crashes and illegal moves is critical — even a weak legal move beats a forfeit
- Time management matters: a depth-3 search that times out loses to a depth-1 search that returns on time

## Your Tools
You have access to these tools — use them before creating agents:

| Tool | What it does |
|------|-------------|
| `query_db(sql)` | Run any SELECT on the DB. Tables: `agents` (name, elo, wins, losses, draws, code), `games` (agent1_id, agent2_id, winner_id, scores, turns, history) |
| `read_agent(agent_name)` | Read any agent's full source code |
| `get_agent_games(agent_name, limit)` | See an agent's recent match results — scores, turns, key moments |
| `get_game_replay(game_id, start_turn, end_turn)` | Inspect a specific portion of a game — board state, moves, flips per turn. Keep ranges small (10-20 turns) |
| `test_match(agent1_name, agent2_name)` | Run a live match between two agents and see who wins |
| `create_agent(name, code)` | Create a new agent (auto-tested before saving) |
| `edit_current_agent(name, code)` | Fix bugs in an agent you created this round |
| `run_test(agent_name)` | Run validation tests on an agent |

## Recommended Workflow
1. Study the leaderboard (provided below) and read the top agent's code with `read_agent`
2. Use `get_agent_games` to see how the top agent wins and loses — note which opponents give it trouble
3. Use `get_game_replay` to inspect critical moments (e.g., the last 20 turns of a loss, or the opening 10 turns)
4. Design a counter-strategy targeting the top agent's weaknesses
5. `create_agent` with your new strategy — it will be auto-tested
6. Use `test_match` to verify your agent beats the top agent
7. If it fails or crashes, use `edit_current_agent` to fix

## Strategies to Explore

**Corner Control**
- Corners (0,0), (0,7), (7,0), (7,7) are the most valuable squares — once taken, they can never be flipped
- Avoid X-squares (diagonally adjacent to empty corners): (1,1), (1,6), (6,1), (6,6) — these give the opponent corner access
- Avoid C-squares (edge-adjacent to empty corners): (0,1), (1,0), (0,6), (1,7), (6,0), (7,1), (6,7), (7,6)
- Once a corner is taken by either side, the adjacent X/C-squares become safe to play
- A corner grab often triggers a cascade of edge captures — plan for this

**Mobility**
- Mobility = number of legal moves you have. More options = more control.
- Maximize YOUR mobility, minimize OPPONENT's mobility
- Low opponent mobility means they're forced into bad moves (possibly giving you corners)
- "Quiet" moves that don't flip many discs often preserve mobility better than aggressive flips
- Internal moves (surrounded by discs) tend to reduce opponent's options

**Disc Stability**
- A stable disc can never be flipped for the rest of the game (corner discs, edge discs anchored to corners)
- Unstable discs can be flipped. Semi-stable discs can only be flipped in certain endgame scenarios.
- Maximize stable disc count rather than total disc count
- Wedges: placing between two opponent discs on an edge creates stable positions
- A full edge anchored by corners is completely stable

**Edge Control**
- Edges are valuable because discs there can only be attacked from fewer directions
- Balanced edges (alternating colors) are dangerous — they create opportunities for the opponent
- Unbalanced edges (long runs of one color) are more stable
- Avoid giving the opponent an "edge anchor" that lets them take the whole edge
- C-square play is risky but necessary in the late midgame when corners are taken

**Parity (Endgame)**
- Parity = who plays the last move in each empty region
- The player who moves last in a region often gets the final flips
- In the endgame, even-numbered empty regions are better for the player who moves second in them
- Try to leave an odd number of empty regions so you get the last move overall
- Parity becomes critical in the final 10-15 moves

**Endgame Counting**
- In the last ~10 moves, exact disc counting becomes feasible and critical
- Search all possible move sequences to maximize your final disc count
- With 10 empty squares, the game tree is small enough for brute-force search within 100ms
- Minimax with alpha-beta pruning can solve endgames of 12-14 empty squares
- The transition from positional play to endgame solving is one of the biggest skill jumps

**Frontier Minimization**
- Frontier discs = your discs adjacent to empty squares (exposed to being flipped)
- Minimize your frontier — fewer exposed discs means fewer opponent options
- "Quiet" play: flip as few discs as possible in the midgame to keep your frontier small
- Opponent's large frontier = they have many exposed discs you can potentially flip later

**Opening Theory**
- Standard openings: diagonal opening (black plays to (2,3) or (5,4)), perpendicular opening, parallel opening
- First few moves set the tone — center control and disc efficiency matter early
- Avoid flipping too many discs in the opening (gives opponent targets and mobility)
- The "X-square trap" is common in low-level play: avoid playing X-squares near empty corners in the opening

## Common Bugs to Avoid
- Forgetting to return a move from `state['legal_moves']` (returning None or a computed [row,col] not in the list)
- Confusing `my_color` (1 or -1) with string ('black' or 'white')
- Off-by-one errors in board indexing (valid range is 0-7 for both row and col)
- Infinite loops in minimax search (always have a depth limit)
- Exceeding 100ms time limit with deep search (start shallow, only go deeper if you have time budget)
- Modifying `state['board']` directly instead of making a copy for simulation
- Not handling the case where `state['opponent_last_move']` is None (opponent passed or first move)

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully (provided below the leaderboard). Identify its weaknesses:
- Does it only maximize flips? Add positional evaluation and mobility.
- Does it ignore corners? Build a corner-obsessed agent that forces corner access.
- Does it have weak endgame play? Add exact endgame solving for the last 10-12 moves.
- Does it play too aggressively? Build a quiet agent that minimizes frontier and maximizes mobility.
- Does it ignore stability? Count stable discs and weight them heavily.

Then build an agent specifically designed to counter and outperform it. Don't just copy the best agent — find ways to be strictly better:
- If the top agent uses a static weight map, add dynamic weights that adapt to game phase.
- If the top agent has no search, add minimax with alpha-beta pruning (depth 3-4 is feasible).
- If the top agent ignores mobility, build a mobility-focused agent that squeezes its options.
- Combine positional weights + mobility + stability + endgame solving for maximum strength.

Every new agent should aim to climb to #1 on the ELO leaderboard. Prioritize winning over novelty.
