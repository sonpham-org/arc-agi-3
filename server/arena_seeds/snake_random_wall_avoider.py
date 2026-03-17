"""Wall avoider agent for Snake Random Maps - flood-fill safety + wall avoidance."""

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

    def flood_fill(start):
        visited = {start}
        queue = deque([start])
        count = 0
        dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        while queue:
            cx, cy = queue.popleft()
            count += 1
            for dx, dy in dirs:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) not in visited and 0 < nx < w - 1 and 0 < ny < h - 1 and (nx, ny) not in occupied:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
        return count

    def score(m):
        pos = safe[m]
        space = flood_fill(pos)
        food_dist = min((abs(pos[0] - f[0]) + abs(pos[1] - f[1]) for f in food), default=0) if food else 0
        return space * 3 - food_dist

    best = max(safe.keys(), key=score)
    return best
