# Author: Claude Opus 4.6
# Date: 2026-03-16 20:00
# PURPOSE: Othello positional agent using a static weight map. Evaluates each legal
#   move as flips*2 + position_weight. Corners are heavily rewarded (+100), edges
#   get moderate bonus (+10), X-squares (diagonally adjacent to corners) are penalized
#   (-25), C-squares (edge-adjacent to corners) are penalized (-12). Picks the best
#   score, ties broken randomly.
# SRP/DRY check: Pass — standalone seed agent, no shared utilities needed.

"""Positional Othello agent — combines flip count with positional weights.

Strategy: Score each legal move as (flips * 2) + position_weight. The weight
map encodes classical Othello positional knowledge:
  - Corners (a1, a8, h1, h8) are the most valuable squares (+100) because
    they can never be flipped once taken.
  - Edges are moderately valuable (+10) because they are harder to flip.
  - X-squares (diagonally adjacent to corners) are dangerous (-25) because
    taking them often gives the opponent access to the corner.
  - C-squares (edge-adjacent to corners) are risky (-12) for similar reasons.
  - Center squares get a small bonus (+1) for early game influence.

This agent is stronger than greedy because it avoids giving away corners and
prioritizes stable positions. However, it has no lookahead and no adaptive
strategy — it evaluates each move in isolation.
"""

import random

# Eight directions: (row_delta, col_delta)
DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1),
              (0, -1),           (0, 1),
              (1, -1),  (1, 0),  (1, 1)]

# Static positional weight map for an 8x8 Othello board.
# Rows/cols indexed 0-7. Symmetric across both axes.
POSITION_WEIGHTS = [
    [ 100, -12,  10,   5,   5,  10, -12,  100],
    [ -12, -25,  -1,  -1,  -1,  -1, -25,  -12],
    [  10,  -1,   1,   1,   1,   1,  -1,   10],
    [   5,  -1,   1,   1,   1,   1,  -1,    5],
    [   5,  -1,   1,   1,   1,   1,  -1,    5],
    [  10,  -1,   1,   1,   1,   1,  -1,   10],
    [ -12, -25,  -1,  -1,  -1,  -1, -25,  -12],
    [ 100, -12,  10,   5,   5,  10, -12,  100],
]


def _count_flips(board, row, col, my_color):
    """Count how many opponent pieces would be flipped by placing at (row, col)."""
    opponent = -my_color
    total_flips = 0

    for dr, dc in DIRECTIONS:
        flips = 0
        r, c = row + dr, col + dc
        while 0 <= r < 8 and 0 <= c < 8 and board[r][c] == opponent:
            flips += 1
            r += dr
            c += dc
        # Only count if the line ends with our own piece
        if flips > 0 and 0 <= r < 8 and 0 <= c < 8 and board[r][c] == my_color:
            total_flips += flips

    return total_flips


def get_move(state):
    board = state['board']
    legal_moves = state['legal_moves']
    my_color = state['my_color']

    best_score = -999999
    best_moves = []

    for move in legal_moves:
        row, col = move[0], move[1]
        flips = _count_flips(board, row, col, my_color)

        # Score = flip bonus + positional weight
        score = flips * 2 + POSITION_WEIGHTS[row][col]

        if score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    return random.choice(best_moves)
