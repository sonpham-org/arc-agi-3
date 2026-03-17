"""Random agent for Snake Random Maps - picks a random safe move, avoids walls."""

import random


def get_move(state):
    head = state['my_snake'][0]
    w, h = state['grid_size']
    body = set(map(tuple, state['my_snake']))
    enemy = set(map(tuple, state['enemy_snake']))
    walls = set(map(tuple, state.get('walls', [])))
    occupied = body | enemy | walls

    moves = {
        'UP': (head[0], head[1] - 1),
        'DOWN': (head[0], head[1] + 1),
        'LEFT': (head[0] - 1, head[1]),
        'RIGHT': (head[0] + 1, head[1]),
    }

    safe = [m for m, (nx, ny) in moves.items()
            if 0 < nx < w - 1 and 0 < ny < h - 1 and (nx, ny) not in occupied]

    if safe:
        return random.choice(safe)
    return random.choice(['UP', 'DOWN', 'LEFT', 'RIGHT'])
