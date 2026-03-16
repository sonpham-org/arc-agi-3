# Author: Claude Opus 4.6
# Date: 2026-03-16 20:00
# PURPOSE: Othello greedy agent. For each legal move, simulates the placement to
#   count how many opponent pieces would be flipped. Picks the move that flips the
#   most pieces. Ties broken randomly. No positional awareness — purely maximizes
#   immediate disc count gain.
# SRP/DRY check: Pass — standalone seed agent, no shared utilities needed.

"""Greedy Othello agent — maximizes immediate flip count.

Strategy: For each legal move, count how many opponent discs would be flipped
by placing there. Pick the move that flips the most. Ties broken randomly.

This beats random play easily but is vulnerable to positional strategies —
maximizing flips often means giving up corners and edges, which are strategically
superior in the long run.
"""

import random

# Eight directions: (row_delta, col_delta)
DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1),
              (0, -1),           (0, 1),
              (1, -1),  (1, 0),  (1, 1)]


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

    best_flips = -1
    best_moves = []

    for move in legal_moves:
        row, col = move[0], move[1]
        flips = _count_flips(board, row, col, my_color)

        if flips > best_flips:
            best_flips = flips
            best_moves = [move]
        elif flips == best_flips:
            best_moves.append(move)

    return random.choice(best_moves)
