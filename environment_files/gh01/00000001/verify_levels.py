#!/usr/bin/env python3
"""BFS solver for Ghost Heist levels.

State = (px, py, has_treasure, guard_states_tuple)
where guard_states_tuple = tuple of (gx, gy, patrol_index) for each guard.

Since patrols loop, the state space is finite.
"""

from collections import deque
from math import gcd
from functools import reduce


def _border(w, h):
    s = set()
    for x in range(w):
        s.add((x, 0)); s.add((x, h - 1))
    for y in range(h):
        s.add((0, y)); s.add((w - 1, y))
    return s


LEVELS = [
    # L1: 7x7, 1 guard simple up-down patrol
    {
        "name": "Easy Grab",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 5),
        "treasure": (5, 1),
        "exit": (1, 1),
        "guards": [
            (3, 3, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
        ],
    },
    # L2: 7x7, 1 guard, walls to hide behind
    {
        "name": "Wall Cover",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 2), (3, 3), (3, 4)},
        "player": (1, 5),
        "treasure": (5, 3),
        "exit": (1, 1),
        "guards": [
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L3: 8x8, 2 guards
    {
        "name": "Double Watch",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 6),
        "treasure": (6, 1),
        "exit": (1, 1),
        "guards": [
            (3, 3, [(1, 0), (1, 0), (-1, 0), (-1, 0)], 3),
            (6, 4, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
        ],
    },
    # L4: 8x8, 2 guards, corridors with gaps
    {
        "name": "Corridor Run",
        "grid_w": 8, "grid_h": 8,
        "walls": {(4, 2), (4, 3), (4, 4)},
        "player": (1, 6),
        "treasure": (6, 1),
        "exit": (1, 1),
        "guards": [
            (3, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (6, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L5: 9x9, 2 guards, treasure behind guards
    {
        "name": "Behind the Watch",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 2), (4, 3), (4, 5), (4, 6)},
        "player": (1, 7),
        "treasure": (7, 4),
        "exit": (1, 1),
        "guards": [
            (3, 4, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (6, 3, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L6: 9x9, 3 guards, must time movements
    {
        "name": "Timing Is Key",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 3), (6, 4), (6, 5)},
        "player": (1, 7),
        "treasure": (7, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (5, 4, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
            (7, 5, [(0, 1), (0, 1), (0, -1), (0, -1)], 3),
        ],
    },
    # L7: 10x10, 3 guards, complex patrols
    {
        "name": "Complex Patrol",
        "grid_w": 10, "grid_h": 10,
        "walls": {(4, 2), (4, 3), (4, 4),
                  (6, 5), (6, 6), (6, 7)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (3, 5, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 2, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (8, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L8: 10x10, 4 guards, maze
    {
        "name": "The Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 4), (6, 5), (6, 6)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 7, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (8, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L9: 10x10, 4 guards, tight timing
    {
        "name": "Tight Timing",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 2), (6, 3),
                  (6, 6), (6, 7)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (7, 4, [(-1, 0), (1, 0)], 3),
            (8, 5, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L10: 12x10, 5 guards, grand heist
    {
        "name": "Grand Heist",
        "grid_w": 12, "grid_h": 10,
        "walls": {(3, 2), (3, 3), (3, 4),
                  (5, 5), (5, 6), (5, 7),
                  (8, 2), (8, 3), (8, 4),
                  (10, 5), (10, 6), (10, 7)},
        "player": (1, 8),
        "treasure": (10, 1),
        "exit": (1, 1),
        "guards": [
            (2, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (4, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (6, 2, [(1, 0), (1, 0), (-1, 0), (-1, 0)], 3),
            (9, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (7, 8, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
        ],
    },
]


def lcm(a, b):
    return a * b // gcd(a, b)


def compute_patrol_lcm(guards):
    """LCM of all patrol cycle lengths."""
    lengths = [len(g[2]) for g in guards if g[2]]
    if not lengths:
        return 1
    return reduce(lcm, lengths)


def solve_level(level_idx):
    d = LEVELS[level_idx]
    gw, gh = d["grid_w"], d["grid_h"]

    # Build walls (border + interior)
    walls = set()
    for x in range(gw):
        walls.add((x, 0)); walls.add((x, gh - 1))
    for y in range(gh):
        walls.add((0, y)); walls.add((gw - 1, y))
    walls |= set(d["walls"])

    treasure = d["treasure"]
    exit_pos = d["exit"]
    guard_defs = d["guards"]

    patrol_lcm = compute_patrol_lcm(guard_defs)

    # State: (px, py, has_treasure, guard_key)
    # guard_key: tuple of (gx, gy, patrol_index) for each guard
    # But since guards follow deterministic patrols based only on turn number,
    # we can represent guard state just as turn_number % patrol_lcm

    def get_guard_states(turn):
        """Return guard positions and facing dirs at a given turn."""
        states = []
        for gx0, gy0, patrol, vr in guard_defs:
            gx, gy = gx0, gy0
            fdx, fdy = patrol[0] if patrol else (0, 1)
            for t in range(turn):
                if patrol:
                    pi = t % len(patrol)
                    mdx, mdy = patrol[pi]
                    ngx, ngy = gx + mdx, gy + mdy
                    if (ngx, ngy) not in walls:
                        gx, gy = ngx, ngy
                        fdx, fdy = mdx, mdy
            states.append((gx, gy, fdx, fdy, vr))
        return states

    def compute_vision(guard_states):
        """Compute all vision cells for the given guard states."""
        vision = set()
        for gx, gy, fdx, fdy, vr in guard_states:
            for i in range(1, vr + 1):
                vx, vy = gx + fdx * i, gy + fdy * i
                if (vx, vy) in walls:
                    break
                vision.add((vx, vy))
        return vision

    def advance_guards(guard_states, turn):
        """Move guards one step at the given turn. Return new guard states."""
        new_states = []
        for idx, (gx, gy, fdx, fdy, vr) in enumerate(guard_states):
            patrol = guard_defs[idx][2]
            if patrol:
                pi = turn % len(patrol)
                mdx, mdy = patrol[pi]
                ngx, ngy = gx + mdx, gy + mdy
                if (ngx, ngy) not in walls:
                    new_states.append((ngx, ngy, mdx, mdy, vr))
                else:
                    new_states.append((gx, gy, mdx, mdy, vr))
            else:
                new_states.append((gx, gy, fdx, fdy, vr))
        return tuple(new_states)

    # Initial guard states (before any moves)
    init_guard_states = []
    for gx, gy, patrol, vr in guard_defs:
        fdx, fdy = patrol[0] if patrol else (0, 1)
        init_guard_states.append((gx, gy, fdx, fdy, vr))
    init_guard_states = tuple(init_guard_states)

    # Check initial vision - player must not start detected
    init_vision = compute_vision(init_guard_states)
    px0, py0 = d["player"]
    if (px0, py0) in init_vision:
        print(f"  ERROR: Player starts in guard vision!")
        return None

    # BFS
    # State: (px, py, has_treasure, turn_mod)
    # turn_mod = turn % patrol_lcm
    start_state = (px0, py0, False, 0)
    queue = deque()
    queue.append((start_state, init_guard_states, []))
    visited = {(start_state, init_guard_states)}

    directions = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}
    dir_names = {1: "UP", 2: "DOWN", 3: "LEFT", 4: "RIGHT"}

    iterations = 0
    max_iterations = 2_000_000

    while queue:
        iterations += 1
        if iterations > max_iterations:
            print(f"  TIMEOUT after {max_iterations} iterations")
            return None

        (px, py, has_t, turn_mod), guard_st, path = queue.popleft()

        for aid, (dx, dy) in directions.items():
            nx, ny = px + dx, py + dy

            # Can't walk into walls
            if (nx, ny) in walls:
                continue

            new_has_t = has_t
            # Pick up treasure
            if not has_t and (nx, ny) == treasure:
                new_has_t = True

            # Check win
            if new_has_t and (nx, ny) == exit_pos:
                solution = path + [dir_names[aid]]
                return solution

            # Move guards
            new_turn = (turn_mod + 1) % patrol_lcm
            new_guard_st = advance_guards(guard_st, turn_mod)

            # Check vision after guards move
            vision = compute_vision(new_guard_st)
            if (nx, ny) in vision:
                continue  # detected

            # Check if player is on a guard
            guard_positions = {(g[0], g[1]) for g in new_guard_st}
            if (nx, ny) in guard_positions:
                continue  # collide with guard

            new_state = (nx, ny, new_has_t, new_turn)
            state_key = (new_state, new_guard_st)
            if state_key not in visited:
                visited.add(state_key)
                queue.append((new_state, new_guard_st, path + [dir_names[aid]]))

    print(f"  NO SOLUTION FOUND after exploring {len(visited)} states")
    return None


def main():
    all_ok = True
    for i in range(len(LEVELS)):
        lvl = LEVELS[i]
        print(f"Level {i+1}: {lvl['name']} ({lvl['grid_w']}x{lvl['grid_h']}, {len(lvl['guards'])} guards)")
        solution = solve_level(i)
        if solution is None:
            print(f"  UNSOLVABLE!")
            all_ok = False
        else:
            print(f"  Solution: {len(solution)} steps: {' '.join(solution)}")
    print()
    if all_ok:
        print("ALL LEVELS SOLVABLE")
    else:
        print("SOME LEVELS FAILED")


if __name__ == "__main__":
    main()
