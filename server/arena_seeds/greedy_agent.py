"""Greedy agent - always moves toward nearest food, avoids obstacles."""

import random


def get_move(state):
    head = state['my_snake'][0]
    w, h = state['grid_size']
    body = set(map(tuple, state['my_snake']))
    enemy = set(map(tuple, state['enemy_snake']))
    occupied = body | enemy
    food = state['food']

    moves = {
        'UP': (head[0], head[1] - 1),
        'DOWN': (head[0], head[1] + 1),
        'LEFT': (head[0] - 1, head[1]),
        'RIGHT': (head[0] + 1, head[1]),
    }

    safe = {m: (nx, ny) for m, (nx, ny) in moves.items()
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in occupied}

    if not safe:
        return random.choice(['UP', 'DOWN', 'LEFT', 'RIGHT'])

    if food:
        nearest = min(food, key=lambda f: abs(f[0] - head[0]) + abs(f[1] - head[1]))
        best = min(safe.keys(),
                   key=lambda m: abs(safe[m][0] - nearest[0]) + abs(safe[m][1] - nearest[1]))
        return best

    return random.choice(list(safe.keys()))
