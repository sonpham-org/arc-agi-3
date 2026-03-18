# Chess960 Agent Evolution Program

## Objective
Create chess agents that win competitive Chess960 (Fischer Random) games. The starting back-rank position is randomized each game (960 possible arrangements), so memorized openings are useless — general chess principles and strong evaluation matter most.

## Agent Interface
Each agent is a standalone Python file with ONE function:
```python
def get_move(state):
    # state keys:
    #   'board': 8x8 list of lists (int). Row 0 = rank 8 (black back rank), Row 7 = rank 1 (white back rank).
    #            Col 0 = a-file, Col 7 = h-file.
    #            Positive = white, negative = black. 0 = empty.
    #            1=Pawn, 2=Knight, 3=Bishop, 4=Rook, 5=Queen, 6=King
    #   'my_color': 'white' or 'black'
    #   'legal_moves': ['e2e4', 'g1f3', ...] — all legal moves pre-computed. Empty if not your turn.
    #   'opponent_last_move': 'e7e5' or None
    #   'turn': int (half-moves played so far, 0 = white's first move)
    #   'halfmove_clock': int (half-moves since last capture or pawn move, 50-move rule counter)
    #   'captured': {'white': [int], 'black': [int]} — piece types captured BY each side
    #   'king_in_check': bool — whether YOUR king is currently in check
    #   'prev_moves': mutable list — persistent memory across turns within this game
    # Returns: one of state['legal_moves'] (a string like 'e2e4' or 'e7e8q')
```

## Critical Rules
- **Board layout**: 8x8 int array. Row 0 = rank 8 (black back rank), Row 7 = rank 1 (white back rank). Col 0 = a-file, Col 7 = h-file.
- **Piece encoding**: 1=Pawn, 2=Knight, 3=Bishop, 4=Rook, 5=Queen, 6=King. Positive = white, negative = black, 0 = empty.
- **Move format**: Long algebraic — `"e2e4"`, `"g8f6"`, `"e7e8q"` (promotion appends lowercase piece letter: q/r/b/n).
- **MUST return a string from `state['legal_moves']`**. Returning anything else (wrong type, move not in list, None) = instant forfeit.
- **Allowed imports**: Only standard library — `random`, `math`, `collections`, `itertools`, `functools`, `heapq`. No `os`, `subprocess`, `socket`, `sys`, or any I/O.
- **Time limit**: Must return in <100ms. Exceeding this = crash = forfeit.
- **Must not crash**. Any unhandled exception = forfeit.
- **Fischer Random**: The starting position varies each game (960 possibilities). Back-rank pieces are shuffled but bishops are on opposite colors and the king is between the two rooks. Don't rely on memorized openings — they won't work.
- **No castling** in this version.

## Reading the Board
```python
def get_move(state):
    board = state['board']
    # Example: find your king's position
    my_sign = 1 if state['my_color'] == 'white' else -1
    king_pos = None
    for r in range(8):
        for c in range(8):
            if board[r][c] == my_sign * 6:  # 6 = King
                king_pos = (r, c)
                break

    # Example: count material
    PIECE_VAL = {1: 1, 2: 3, 3: 3, 4: 5, 5: 9, 6: 0}
    my_material = sum(PIECE_VAL[abs(board[r][c])]
                      for r in range(8) for c in range(8)
                      if board[r][c] * my_sign > 0)
```

## Coordinate System
```
         a    b    c    d    e    f    g    h
         c0   c1   c2   c3   c4   c5   c6   c7
row 0  [ black back rank — rank 8 ]
row 1  [ black pawns     — rank 7 ]
row 2  [                 — rank 6 ]
row 3  [                 — rank 5 ]
row 4  [                 — rank 4 ]
row 5  [                 — rank 3 ]
row 6  [ white pawns     — rank 2 ]
row 7  [ white back rank — rank 1 ]
```
- To convert algebraic to row/col: `row = 8 - int(rank_char)`, `col = ord(file_char) - ord('a')`
- To convert row/col to algebraic: `file = 'abcdefgh'[col]`, `rank = str(8 - row)`

## Agent Memory (prev_moves)
Each agent has access to `state['prev_moves']` — a mutable list that persists across all turns within a single game. Use it to track game history, implement stateful strategies, or avoid repetition:
```python
def get_move(state):
    prev = state['prev_moves']  # list — persists across turns
    prev.append({
        'turn': state['turn'],
        'opponent_move': state['opponent_last_move'],
        'in_check': state['king_in_check'],
    })

    # Example: detect if opponent keeps making the same moves (repetition)
    if len(prev) >= 6:
        last_opp_moves = [p['opponent_move'] for p in prev[-6:] if p['opponent_move']]
        if len(last_opp_moves) >= 4 and last_opp_moves[-1] == last_opp_moves[-3]:
            pass  # opponent is repeating — exploit the pattern

    # ... compute move ...
    return move
```

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided:**
- Checkmate = win for the mating side
- Stalemate = draw (0.5 each)
- 50-move rule (halfmove_clock reaches 100 half-moves without a capture or pawn move) = draw
- Max 200 full moves (400 half-moves) = draw
- Illegal move (returning a string not in legal_moves) = forfeit (instant loss)
- Crash (unhandled exception) = forfeit (instant loss)
- Timeout (>100ms) = forfeit (instant loss)

**How ELO updates:**
- Expected score: `E = 1 / (1 + 10^((opponent_elo - your_elo) / 400))`
- Win = 1.0, Draw = 0.5, Loss = 0.0
- New ELO = old ELO + 32 * (actual - expected)
- Beating higher-rated agents gives more ELO; losing to lower-rated agents costs more

**Key implications for strategy:**
- Checkmate is the ultimate goal — material advantages should be converted to checkmate
- Avoiding crashes and illegal moves is critical — even a weak legal move beats a forfeit
- Draws gain ELO only if opponent is higher-rated; play for wins against weaker agents
- Time management matters: a depth-3 search that times out loses to a depth-1 search that returns on time

## Your Tools
You have access to these tools — use them before creating agents:

| Tool | What it does |
|------|-------------|
| `query_db(sql)` | Run any SELECT on the DB. Tables: `agents` (name, elo, wins, losses, draws, code), `games` (agent1_id, agent2_id, winner_id, scores, turns, history) |
| `read_agent(agent_name)` | Read any agent's full source code |
| `get_agent_games(agent_name, limit)` | See an agent's recent match results — scores, turns, key moments |
| `get_game_replay(game_id, start_turn, end_turn)` | Inspect a specific portion of a game — board state, moves, captures per turn. Keep ranges small (10-20 turns) |
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

**Material Evaluation**
- Standard piece values: Pawn=1, Knight=3, Bishop=3, Rook=5, Queen=9
- Bishop pair bonus (+0.5 when you have both bishops)
- Adjust values based on game phase (knights stronger in closed positions, rooks stronger in open ones)

**Piece-Square Tables**
- Center control bonuses for knights and pawns (e4/d4/e5/d5 squares)
- King safety: keep king on back rank in middlegame, centralize in endgame
- Pawn structure: penalize doubled pawns, isolated pawns; reward passed pawns
- Rooks on open files bonus

**Search (Minimax with Alpha-Beta Pruning)**
- Depth 2 is safe within 100ms. Depth 3 is possible with good move ordering and pruning.
- Alpha-beta pruning eliminates branches that can't affect the result
- Move ordering is critical for pruning efficiency: try captures first, then checks, then promotions, then quiet moves
- MVV-LVA (Most Valuable Victim, Least Valuable Attacker) for capture ordering

**Tactical Patterns**
- Quiescence search: after reaching max depth, continue searching captures only to avoid horizon effect
- Check extensions: search one ply deeper when in check
- Fork detection: knight/queen moves that attack two pieces simultaneously

**King Safety**
- Count attackers near opponent's king
- Penalize open files near your own king
- Reward pawn shield in front of king

**Endgame Logic**
- Detect endgame (few pieces left) and switch evaluation: centralize king, push passed pawns
- King and pawn vs king: know the winning technique (opposition, queening square)
- Rook endgames: rook belongs behind passed pawns

**Fischer Random Principles**
- Since openings are randomized, general principles matter most:
  - Develop pieces to active squares quickly
  - Control the center with pawns and pieces
  - Don't move the same piece twice in the opening (unless forced)
  - Connect your rooks (clear the back rank)
  - Look at where bishops start — they may already be active or need to be developed
  - Knights near the center are strong; knights on the rim are weak

## Common Bugs to Avoid
- Forgetting to return a move from `state['legal_moves']` (returning None or a computed string not in the list)
- Index errors when reading the board (row/col confusion, off-by-one)
- Infinite loops in search (always have a depth limit)
- Exceeding 100ms time limit with deep search (start with depth 2, only go deeper if you have time management)
- Using `tuple()` on board rows when you need `list` comparisons, or vice versa
- Assuming standard chess starting position — it's Fischer Random, positions vary every game

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully (provided below the leaderboard). Identify its weaknesses:
- Does it use shallow search? Build a deeper-searching agent.
- Does it have weak endgame play? Add endgame-specific evaluation.
- Does it miss tactics? Add quiescence search or fork detection.
- Does it have poor move ordering? Better ordering means deeper effective search.
- Does it ignore king safety? Exploit with aggressive attacks.

Then build an agent specifically designed to counter and outperform it. Don't just copy the best agent — find ways to be strictly better:
- If the top agent uses depth 2, try depth 3 with efficient pruning.
- If the top agent has simple evaluation, add piece-square tables and pawn structure analysis.
- If the top agent plays passively, build an aggressive attacker that targets its king.
- Combine the best elements from multiple top agents and add improvements.

Every new agent should aim to climb to #1 on the ELO leaderboard. Prioritize winning over novelty.
