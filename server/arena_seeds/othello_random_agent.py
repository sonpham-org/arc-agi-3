# Author: Claude Opus 4.6
# Date: 2026-03-16 20:00
# PURPOSE: Othello random baseline agent. Picks a uniformly random legal move.
#   Serves as the weakest seed agent for ELO calibration — any agent that can't
#   beat random play is fundamentally broken.
# SRP/DRY check: Pass — standalone seed agent, no shared utilities needed.

"""Random Othello agent — picks a uniformly random legal move.

Strategy: None. This is a pure baseline for ELO calibration. Every legal move
has equal probability regardless of board position. Expected to lose to any
agent with even minimal positional or tactical awareness.
"""

import random


def get_move(state):
    return random.choice(state['legal_moves'])
