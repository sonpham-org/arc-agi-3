# Author: Claude Opus 4.6
# Date: 2026-03-16 18:00
# PURPOSE: Chess960 positional agent using piece-square tables. For each legal move,
#   evaluates material balance + piece-square bonus at the destination. Uses standard
#   middlegame PSTs. Picks the highest-scoring move, breaks ties randomly.
# SRP/DRY check: Pass — standalone seed agent, no shared utilities needed.

"""Positional agent — uses piece-square tables for move evaluation.

Strategy: For each legal move, compute a score as:
  material_change + PST(destination) - PST(source) + capture_value

Uses standard middlegame piece-square tables (from white's perspective; mirrored
for black). Knights prefer the center, bishops prefer long diagonals, rooks prefer
open files and the 7th rank, queens prefer center, king prefers castled position.

No search depth — evaluates each move independently based on the resulting
position quality. Stronger than greedy because it considers development and
piece placement, not just captures.
"""

import random

# Piece values: P=1, N=3, B=3, R=5, Q=9, K=0
PIECE_VALUE = {0: 0, 1: 100, 2: 320, 3: 330, 4: 500, 5: 900, 6: 20000}

# Piece-square tables from White's perspective (row 0 = rank 8 = Black's back rank)
# Values in centipawns. For Black, we mirror vertically (flip row index).

# Pawn PST
PST_PAWN = [
    [  0,   0,   0,   0,   0,   0,   0,   0],
    [ 50,  50,  50,  50,  50,  50,  50,  50],
    [ 10,  10,  20,  30,  30,  20,  10,  10],
    [  5,   5,  10,  25,  25,  10,   5,   5],
    [  0,   0,   0,  20,  20,   0,   0,   0],
    [  5,  -5, -10,   0,   0, -10,  -5,   5],
    [  5,  10,  10, -20, -20,  10,  10,   5],
    [  0,   0,   0,   0,   0,   0,   0,   0],
]

# Knight PST
PST_KNIGHT = [
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20,   0,   0,   0,   0, -20, -40],
    [-30,   0,  10,  15,  15,  10,   0, -30],
    [-30,   5,  15,  20,  20,  15,   5, -30],
    [-30,   0,  15,  20,  20,  15,   0, -30],
    [-30,   5,  10,  15,  15,  10,   5, -30],
    [-40, -20,   0,   5,   5,   0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
]

# Bishop PST
PST_BISHOP = [
    [-20, -10, -10, -10, -10, -10, -10, -20],
    [-10,   0,   0,   0,   0,   0,   0, -10],
    [-10,   0,  10,  10,  10,  10,   0, -10],
    [-10,   5,   5,  10,  10,   5,   5, -10],
    [-10,   0,   5,  10,  10,   5,   0, -10],
    [-10,  10,   5,  10,  10,   5,  10, -10],
    [-10,   5,   0,   0,   0,   0,   5, -10],
    [-20, -10, -10, -10, -10, -10, -10, -20],
]

# Rook PST
PST_ROOK = [
    [  0,   0,   0,   0,   0,   0,   0,   0],
    [  5,  10,  10,  10,  10,  10,  10,   5],
    [ -5,   0,   0,   0,   0,   0,   0,  -5],
    [ -5,   0,   0,   0,   0,   0,   0,  -5],
    [ -5,   0,   0,   0,   0,   0,   0,  -5],
    [ -5,   0,   0,   0,   0,   0,   0,  -5],
    [ -5,   0,   0,   0,   0,   0,   0,  -5],
    [  0,   0,   0,   5,   5,   0,   0,   0],
]

# Queen PST
PST_QUEEN = [
    [-20, -10, -10,  -5,  -5, -10, -10, -20],
    [-10,   0,   0,   0,   0,   0,   0, -10],
    [-10,   0,   5,   5,   5,   5,   0, -10],
    [ -5,   0,   5,   5,   5,   5,   0,  -5],
    [  0,   0,   5,   5,   5,   5,   0,  -5],
    [-10,   5,   5,   5,   5,   5,   0, -10],
    [-10,   0,   5,   0,   0,   0,   0, -10],
    [-20, -10, -10,  -5,  -5, -10, -10, -20],
]

# King middlegame PST (prefers safety on the flanks)
PST_KING = [
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-20, -30, -30, -40, -40, -30, -30, -20],
    [-10, -20, -20, -20, -20, -20, -20, -10],
    [ 20,  20,   0,   0,   0,   0,  20,  20],
    [ 20,  30,  10,   0,   0,  10,  30,  20],
]

# Map piece type to PST
PST = {
    1: PST_PAWN,
    2: PST_KNIGHT,
    3: PST_BISHOP,
    4: PST_ROOK,
    5: PST_QUEEN,
    6: PST_KING,
}


def _parse_square(sq):
    """Convert algebraic square like 'e2' to (row, col). row 0=rank 8, row 7=rank 1."""
    col = ord(sq[0]) - ord('a')
    row = 8 - int(sq[1])
    return row, col


def _pst_value(piece_type, row, col, is_white):
    """Get the piece-square table value for a piece at (row, col).
    Tables are from White's perspective. For Black, mirror the row."""
    pst = PST.get(piece_type)
    if pst is None:
        return 0
    if is_white:
        return pst[row][col]
    else:
        # Mirror vertically for black
        return pst[7 - row][col]


def get_move(state):
    board = state['board']
    legal_moves = state['legal_moves']
    my_color = state['my_color']
    is_white = my_color == 'white'

    best_score = -999999
    best_moves = []

    for move in legal_moves:
        src_sq = move[0:2]
        dst_sq = move[2:4]

        src_row, src_col = _parse_square(src_sq)
        dst_row, dst_col = _parse_square(dst_sq)

        attacker_raw = board[src_row][src_col]
        attacker_type = abs(attacker_raw)
        victim_raw = board[dst_row][dst_col]
        victim_type = abs(victim_raw)

        score = 0.0

        # Capture value (in centipawns)
        if victim_type > 0:
            score += PIECE_VALUE.get(victim_type, 0)

        # PST delta: gain from moving to new square, lose from leaving old square
        moved_type = attacker_type

        # Handle promotion
        if len(move) == 5:
            promo_char = move[4].lower()
            promo_map = {'q': 5, 'r': 4, 'b': 3, 'n': 2}
            new_type = promo_map.get(promo_char, 5)
            # Gain promoted piece value, lose pawn value
            score += PIECE_VALUE.get(new_type, 0) - PIECE_VALUE.get(1, 0)
            moved_type = new_type

        # PST change
        score += _pst_value(moved_type, dst_row, dst_col, is_white)
        score -= _pst_value(attacker_type, src_row, src_col, is_white)

        # Small bonus for moving pieces off the back rank in the opening (develop)
        turn = state.get('turn', 0)
        if turn < 20 and attacker_type in (2, 3):  # Knights and bishops
            back_rank = 7 if is_white else 0
            if src_row == back_rank and dst_row != back_rank:
                score += 15  # development bonus

        # Bonus for controlling center squares with pawns
        if attacker_type == 1 and (dst_row, dst_col) in ((3, 3), (3, 4), (4, 3), (4, 4)):
            score += 10

        # Check-escape priority: if in check, all legal moves are already check-escaping,
        # so no special handling needed — we just pick the best among them.

        if score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    return random.choice(best_moves)
