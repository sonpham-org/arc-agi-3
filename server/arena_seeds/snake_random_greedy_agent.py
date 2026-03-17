"""Greedy agent for Snake Random Maps - BFS to nearest food avoiding walls."""

import random
from collections import deque


def get_move(state):
    head = state['my_snake'][0]
    w, h = state['grid_size']
    body = set(map(tuple, state['my_snake']))
    enemy = set(map(tuple, state['enemy_snake']))
    walls = set(map(tuple, state.get('walls', [])))
    occupied = body | enemy | walls
    food = [tuple(f) for f in state['food']]

    moves = {
        'UP': (head[0], head[1] - 1),
        'DOWN': (head[0], head[1] + 1),
        'LEFT': (head[0] - 1, head[1]),
        'RIGHT': (head[0] + 1, head[1]),
    }

    safe = {m: (nx, ny) for m, (nx, ny) in moves.items()
            if 0 < nx < w - 1 and 0 < ny < h - 1 and (nx, ny) not in occupied}

    if not safe:
        return random.choice(['UP', 'DOWN', 'LEFT', 'RIGHT'])

    if food:
        # BFS from head to find nearest reachable food
        visited = {tuple(head)}
        queue = deque([(tuple(head), None)])  # (pos, first_move)
        dirs = {'UP': (0, -1), 'DOWN': (0, 1), 'LEFT': (-1, 0), 'RIGHT': (1, 0)}
        while queue:
            (cx, cy), first = queue.popleft()
            for m, (dx, dy) in dirs.items():
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in visited:
                    continue
                if not (0 < nx < w - 1 and 0 < ny < h - 1):
                    continue
                if (nx, ny) in occupied:
                    continue
                visited.add((nx, ny))
                fm = first if first else m
                if (nx, ny) in food and fm in safe:
                    return fm
                queue.append(((nx, ny), fm))

        # Fallback: Manhattan distance to nearest food
        nearest = min(food, key=lambda f: abs(f[0] - head[0]) + abs(f[1] - head[1]))
        best = min(safe.keys(),
                   key=lambda m: abs(safe[m][0] - nearest[0]) + abs(safe[m][1] - nearest[1]))
        return best

    return random.choice(list(safe.keys()))
