"""Random agent for Snake 2v2 Teams - picks a random safe move, ignores ally collisions."""

import random


def get_move(state):
    head = state['my_snake'][0]
    w, h = state['grid_size']
    my_idx = state['my_index']

    # In 2v2, allies pass through each other — only dodge enemies and self
    obstacles = set(map(tuple, state['my_snake']))
    for i, s in enumerate(state['snakes']):
        if s['alive'] and not s.get('is_ally', False) and i != my_idx:
            obstacles.update(map(tuple, s['body']))

    moves = {
        'UP': (head[0], head[1] - 1),
        'DOWN': (head[0], head[1] + 1),
        'LEFT': (head[0] - 1, head[1]),
        'RIGHT': (head[0] + 1, head[1]),
    }

    safe = [m for m, (nx, ny) in moves.items()
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles]

    if safe:
        return random.choice(safe)
    return random.choice(['UP', 'DOWN', 'LEFT', 'RIGHT'])
