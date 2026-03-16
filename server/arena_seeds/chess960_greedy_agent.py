# Author: Claude Opus 4.6
# Date: 2026-03-16 18:00
# PURPOSE: Chess960 greedy capture agent. Evaluates moves by material gain from
#   captures, scored as victim_value - attacker_value/10. Picks the highest-scoring
#   move, breaks ties randomly. Non-captures score 0. Always plays from legal_moves.
# SRP/DRY check: Pass — standalone seed agent, no shared utilities needed.

"""Greedy capture agent — maximizes immediate material gain.

Strategy: Score each legal move by the value of the captured piece minus a small
penalty for the attacker's value (to prefer capturing with cheaper pieces).
Non-capture moves score 0. Ties broken randomly. No lookahead, no positional
awareness — purely reactive to immediate captures.

Piece values: Pawn=1, Knight=3, Bishop=3, Rook=5, Queen=9, King=0.
"""

import random

# Piece type (absolute value of board cell) -> material value
PIECE_VALUE = {0: 0, 1: 1, 2: 3, 3: 3, 4: 5, 5: 9, 6: 0}


def _parse_square(sq):
    """Convert algebraic square like 'e2' to (row, col). row 0=rank 8, row 7=rank 1."""
    col = ord(sq[0]) - ord('a')  # 0-7
    row = 8 - int(sq[1])         # '8'->0, '1'->7
    return row, col


def get_move(state):
    board = state['board']
    legal_moves = state['legal_moves']
    my_color = state['my_color']

    best_score = -1000
    best_moves = []

    for move in legal_moves:
        # Parse source and destination squares
        src_sq = move[0:2]
        dst_sq = move[2:4]

        src_row, src_col = _parse_square(src_sq)
        dst_row, dst_col = _parse_square(dst_sq)

        # Get the piece being moved (attacker) and piece on destination (victim)
        attacker = abs(board[src_row][src_col])
        victim = abs(board[dst_row][dst_col])

        # Score: victim value - attacker value / 10
        # Non-captures score 0 (victim is 0)
        if victim > 0:
            score = PIECE_VALUE.get(victim, 0) - PIECE_VALUE.get(attacker, 0) / 10.0
        else:
            score = 0.0

        # Bonus for promotion moves (e.g. "e7e8q")
        if len(move) == 5:
            promo_piece = move[4].lower()
            promo_values = {'q': 9, 'r': 5, 'b': 3, 'n': 3}
            score += promo_values.get(promo_piece, 0) - 1  # minus pawn value

        if score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    return random.choice(best_moves)
