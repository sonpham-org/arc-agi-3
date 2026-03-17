"""Greedy agent for Snake 2v2 Teams - chases food, only dodges enemies (allies pass through)."""

import random


def get_move(state):
    head = state['my_snake'][0]
    w, h = state['grid_size']
    my_idx = state['my_index']

    # Only enemies and self are obstacles (allies pass through)
    obstacles = set(map(tuple, state['my_snake']))
    for i, s in enumerate(state['snakes']):
        if s['alive'] and not s.get('is_ally', False) and i != my_idx:
            obstacles.update(map(tuple, s['body']))

    food = [tuple(f) for f in state['food']]

    moves = {
        'UP': (head[0], head[1] - 1),
        'DOWN': (head[0], head[1] + 1),
        'LEFT': (head[0] - 1, head[1]),
        'RIGHT': (head[0] + 1, head[1]),
    }

    safe = {m: (nx, ny) for m, (nx, ny) in moves.items()
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles}

    if not safe:
        return random.choice(['UP', 'DOWN', 'LEFT', 'RIGHT'])

    if food:
        nearest = min(food, key=lambda f: abs(f[0] - head[0]) + abs(f[1] - head[1]))
        best = min(safe.keys(),
                   key=lambda m: abs(safe[m][0] - nearest[0]) + abs(safe[m][1] - nearest[1]))
        return best

    return random.choice(list(safe.keys()))
