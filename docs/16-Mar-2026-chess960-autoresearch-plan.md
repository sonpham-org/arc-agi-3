# Fischer Random Chess (Chess960) — Arena AutoResearch Integration

**Date:** 2026-03-16
**Author:** Claude Opus 4.6

## Scope

**In:**
- Python chess960 engine (`server/chess960_engine.py`) — full legal move gen, check/checkmate/stalemate, en passant, pawn promotion, 50-move rule
- Fischer Random back-rank generation (960 positions via seed)
- Chess960 Program.md for LLM evolution (`server/arena_seeds/chess960_program.md`)
- 3 seed agents: random, greedy-material, positional (piece-square tables)
- 12 chess validation test scenarios for agent testing
- Multi-game heartbeat support — tournament + evolution loops for chess960
- JS chess960 engine + renderer in `arena.js`
- Enable chess960 in `ARENA_ENABLED_IDS`

**Out (v1):**
- Castling (complex in Chess960 — deferred to v2)
- Threefold repetition detection
- Opening book / endgame tablebases
- Insufficient material detection (beyond basic K vs K)

## Architecture

### Board Representation
- 8×8 integer array. `0` = empty, positive = white, negative = black
- `1=Pawn, 2=Knight, 3=Bishop, 4=Rook, 5=Queen, 6=King`
- Row 0 = rank 8 (black's back rank), Row 7 = rank 1 (white's back rank)

### Move Format
- Long algebraic: `"e2e4"`, `"g8f6"`, `"e7e8q"` (promotion)
- Agents return one of `state['legal_moves']` — a pre-computed list

### Agent Interface (Python, server-side)
```python
def get_move(state):
    # state keys:
    #   'board': [[int]*8]*8 — 8x8 array (row 0=rank 8, row 7=rank 1)
    #   'my_color': 'white' or 'black'
    #   'legal_moves': ['e2e4', 'g1f3', ...] — all legal moves for your color
    #   'opponent_last_move': 'e7e5' or None
    #   'turn': int — total half-moves played
    #   'halfmove_clock': int — moves since last capture/pawn push (50-move rule)
    #   'captured': {'white': [...], 'black': [...]} — pieces captured by each side
    #   'king_in_check': bool — is your king currently in check?
    #   'prev_moves': [] — persistent memory across turns
    # Returns: a string from legal_moves, e.g. 'e2e4'
```

### New Files
| File | Purpose |
|------|---------|
| `server/chess960_engine.py` | Python chess engine (board, move gen, make/unmake, check, game runner) |
| `server/arena_seeds/chess960_program.md` | Evolution system prompt for chess agents |
| `server/arena_seeds/chess960_random_agent.py` | Random legal move baseline |
| `server/arena_seeds/chess960_greedy_agent.py` | Material-greedy capture agent |
| `server/arena_seeds/chess960_positional_agent.py` | Piece-square evaluation agent |

### Modified Files
| File | Changes |
|------|---------|
| `server/arena_heartbeat.py` | Add chess960 engine import, match runner, validation scenarios, seed agents, multi-game tournament/evolution loops |
| `static/js/arena.js` | JS chess960 engine, board renderer, match runner, enable in `ARENA_ENABLED_IDS` |
| `static/js/arena-autoresearch.js` | Chess960 agent template for browser evolution |
| `CHANGELOG.md` | Entry for chess960 addition |

### Key Design Decisions
1. **Turn-based** — unlike snake (simultaneous), chess alternates white/black. The match runner calls one agent per turn.
2. **Deterministic Fischer Random** — position selected by `seed % 960`. Same seed = same position across all matches in a round.
3. **50-move rule** — automatic draw after 50 half-moves with no capture or pawn move. Max 200 full moves (400 half-moves) hard limit.
4. **No castling v1** — simplifies engine significantly. Agents can't castle.
5. **Game-over detection** — checkmate, stalemate, 50-move draw, max-turn draw.
6. **History format** — `{turn, board, last_move, scores, game_over, winner}` per half-move.

## TODOs

### Phase 1: Python Engine (`server/chess960_engine.py`)
1. Piece constants, direction tables
2. Fischer Random position generator (960 positions)
3. `Chess960Game` class — board setup, state management
4. Legal move generation (pawns, knights, bishops, rooks, queens, king)
5. Check detection, pin-aware move filtering
6. En passant, pawn promotion
7. Checkmate / stalemate detection
8. `get_state(color)` — returns agent-facing state dict
9. `step(move)` — execute a move, detect game end
10. `run(agent_white_fn, agent_black_fn)` — full game runner
11. Verify: run a game between two random agents to completion

### Phase 2: Seed Agents + Program.md
12. `chess960_random_agent.py` — picks random legal move
13. `chess960_greedy_agent.py` — captures highest-value piece, else random
14. `chess960_positional_agent.py` — piece-square tables + material eval, 1-ply lookahead
15. `chess960_program.md` — full evolution steering doc
16. Verify: seed agents play to completion without crashes

### Phase 3: Heartbeat Integration
17. Import chess960 engine in `arena_heartbeat.py`
18. `_run_chess960_match(code_a, code_b)` — match runner
19. Chess960 validation scenarios (12 test states)
20. `_validate_chess960_agent_code(code)` — validate against scenarios
21. Multi-game `_seed_if_empty('chess960')` with chess seed agents
22. `_load_chess960_program()` — load chess960 program.md
23. Game-specific dispatching in `_handle_tool` (tool descriptions, match runner, validation)
24. Tournament + evolution loops for chess960 (second set of threads or unified multi-game loop)
25. Verify: start heartbeat, confirm chess960 tournament runs

### Phase 4: Frontend (JS engine + renderer)
26. JS `Chess960Game` class (port of Python engine)
27. `renderChessFrame(canvas, frame, config)` — board + pieces with ARC3 colors
28. `renderChessPreview(canvas, game)` — mini preview
29. `runChessMatch(config, agent1Code, agent2Code)` — JS match runner
30. Chess960 agent template in `arena-autoresearch.js`
31. Enable `chess960` in `ARENA_ENABLED_IDS`
32. Verify: run a match in browser, confirm rendering

### Phase 5: Finalize
33. CHANGELOG.md entry
34. Push to staging
35. Import check + smoke test

## Docs / Changelog Touchpoints
- `CHANGELOG.md` — new feature entry
- `docs/16-Mar-2026-chess960-autoresearch-plan.md` — this doc
- Update `docs/2026-03-14-chess960-plan.md` status to "superseded by autoresearch plan"
