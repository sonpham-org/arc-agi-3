"""Wall avoider agent - prioritizes staying away from walls and enemies, moves toward food."""

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

    def score(pos):
        x, y = pos
        wall_dist = min(x, w - 1 - x, y, h - 1 - y)
        enemy_dist = min((abs(x - ex) + abs(y - ey) for ex, ey in enemy), default=10)
        food_dist = min((abs(x - fx) + abs(y - fy) for fx, fy in food), default=0)
        return wall_dist * 2 + enemy_dist - food_dist * 0.5

    best = max(safe.keys(), key=lambda m: score(safe[m]))
    return best
