#!/usr/bin/env python3
"""Verify that all rd01 levels are solvable with the intended pipe placements."""

P_EMPTY = 0; P_HORIZ = 1; P_VERT = 2
P_TL = 3; P_TR = 4; P_BL = 5; P_BR = 6

PIPE_CONN = {
    P_HORIZ: {(-1, 0), (1, 0)},
    P_VERT:  {(0, -1), (0, 1)},
    P_TL:    {(0, -1), (-1, 0)},
    P_TR:    {(0, -1), (1, 0)},
    P_BL:    {(0, 1), (-1, 0)},
    P_BR:    {(0, 1), (1, 0)},
}

PN = {P_EMPTY: 'E', P_HORIZ: 'H', P_VERT: 'V', P_TL: 'TL', P_TR: 'TR', P_BL: 'BL', P_BR: 'BR'}


def trace(src, drn, pipes, walls, gw, gh):
    water = set()
    sx, sy, fx, fy = src
    x, y = sx + fx, sy + fy
    fd = (-fx, -fy)
    vis = set()
    path = []
    while True:
        if (x, y) in vis:
            path.append(f"({x},{y})=LOOP")
            break
        if x < 0 or y < 0 or x >= gw or y >= gh:
            path.append(f"({x},{y})=OOB")
            break
        if (x, y) in walls:
            path.append(f"({x},{y})=WALL")
            break
        if (x, y) == drn:
            water.add((x, y))
            path.append(f"({x},{y})=DRAIN")
            break
        pt = pipes.get((x, y), P_EMPTY)
        if pt == P_EMPTY:
            path.append(f"({x},{y})=EMPTY")
            break
        cn = PIPE_CONN.get(pt, set())
        if fd not in cn:
            path.append(f"({x},{y})={PN[pt]}_NOCONN(fd={fd})")
            break
        vis.add((x, y))
        water.add((x, y))
        ex = cn - {fd}
        if not ex:
            path.append(f"({x},{y})=DEAD")
            break
        edx, edy = next(iter(ex))
        path.append(f"({x},{y})={PN[pt]}->{edx},{edy}")
        x, y = x + edx, y + edy
        fd = (-edx, -edy)
    return water, path


def build_walls(gw, gh, ew, src, drn):
    w = set()
    for x in range(gw):
        w.add((x, 0))
        w.add((x, gh - 1))
    for y in range(gh):
        w.add((0, y))
        w.add((gw - 1, y))
    for e in ew:
        w.add(e)
    w.discard((src[0], src[1]))
    w.discard(drn)
    return w


SOLUTIONS = [
    # L1
    {(1,3): P_HORIZ, (2,3): P_HORIZ, (3,3): P_HORIZ, (4,3): P_HORIZ, (5,3): P_HORIZ},
    # L2
    {(3,1): P_VERT, (3,2): P_VERT, (3,3): P_TR, (4,3): P_HORIZ, (5,3): P_HORIZ},
    # L3
    {(1,1): P_HORIZ, (2,1): P_HORIZ, (3,1): P_HORIZ, (4,1): P_HORIZ, (5,1): P_BL,
     (5,2): P_VERT, (5,3): P_VERT, (5,4): P_VERT, (5,5): P_VERT},
    # L4
    {(1,3): P_HORIZ, (2,3): P_HORIZ, (3,3): P_HORIZ, (4,3): P_HORIZ, (5,3): P_HORIZ},
    # L5
    {(1,3): P_HORIZ, (2,3): P_HORIZ, (3,3): P_TL, (3,2): P_BR, (4,2): P_HORIZ,
     (5,2): P_BL, (5,3): P_TR, (6,3): P_HORIZ, (7,3): P_HORIZ},
    # L6
    {(1,2): P_HORIZ, (2,2): P_HORIZ, (3,2): P_BL, (3,3): P_VERT, (3,4): P_VERT,
     (3,5): P_VERT, (3,6): P_TR, (4,6): P_HORIZ, (5,6): P_HORIZ, (6,6): P_HORIZ, (7,6): P_HORIZ},
    # L7
    {(1,1): P_VERT, (1,2): P_VERT, (1,3): P_TR, (2,3): P_HORIZ, (3,3): P_HORIZ,
     (4,3): P_BL, (4,4): P_VERT, (4,5): P_TR, (5,5): P_HORIZ, (6,5): P_HORIZ,
     (7,5): P_BL, (7,6): P_VERT, (7,7): P_VERT},
    # L8
    {(1,2): P_HORIZ, (2,2): P_HORIZ, (3,2): P_BL, (3,3): P_VERT, (3,4): P_TR,
     (4,4): P_HORIZ, (5,4): P_HORIZ, (6,4): P_BL, (6,5): P_VERT, (6,6): P_TR, (7,6): P_HORIZ},
    # L9
    {(4,1): P_VERT, (4,2): P_TR, (5,2): P_HORIZ, (6,2): P_BL,
     (6,3): P_VERT, (6,4): P_VERT, (6,5): P_TL,
     (5,5): P_HORIZ, (4,5): P_BR,
     (4,6): P_VERT, (4,7): P_VERT},
    # L10
    {(1,3): P_HORIZ, (2,3): P_HORIZ, (3,3): P_HORIZ, (4,3): P_HORIZ, (5,3): P_BL,
     (5,4): P_VERT, (5,5): P_TR, (6,5): P_HORIZ, (7,5): P_BL,
     (7,6): P_VERT, (7,7): P_TR, (8,7): P_HORIZ, (9,7): P_HORIZ},
]

LEVELS = [
    {"n": "Straight Shot", "gw": 7, "gh": 7, "ew": set(), "src": (0, 3, 1, 0), "drn": (6, 3)},
    {"n": "First Turn", "gw": 7, "gh": 7, "ew": set(), "src": (3, 0, 0, 1), "drn": (6, 3)},
    {"n": "Double Bend", "gw": 7, "gh": 7, "ew": set(), "src": (0, 1, 1, 0), "drn": (5, 6)},
    {"n": "Gap Fill", "gw": 7, "gh": 7, "ew": set(), "src": (0, 3, 1, 0), "drn": (6, 3)},
    {"n": "Wall Dodge", "gw": 9, "gh": 7, "ew": {(4, 3)}, "src": (0, 3, 1, 0), "drn": (8, 3)},
    {"n": "S-Curve", "gw": 9, "gh": 9, "ew": set(), "src": (0, 2, 1, 0), "drn": (8, 6)},
    {"n": "Maze Run", "gw": 9, "gh": 9,
     "ew": {(2,1),(3,1),(4,1),(5,1),(2,2),(1,4),(2,4),(3,4),(5,4),(5,6),(6,6),(6,7)},
     "src": (1, 0, 0, 1), "drn": (7, 8)},
    {"n": "Guided Path", "gw": 9, "gh": 9, "ew": set(), "src": (0, 2, 1, 0), "drn": (8, 6)},
    {"n": "Tight Squeeze", "gw": 9, "gh": 9,
     "ew": {(4,3),(4,4),(3,2),(3,3),(5,4)},
     "src": (4, 0, 0, 1), "drn": (4, 8)},
    {"n": "Grand Puzzle", "gw": 11, "gh": 11,
     "ew": {(3,4),(4,4),(6,3),(6,4),(4,5),(4,6),(8,5),(8,6),(6,7),(6,8),(3,6),(3,7)},
     "src": (0, 3, 1, 0), "drn": (10, 7)},
]

if __name__ == "__main__":
    all_ok = True
    for i, (lev, sol) in enumerate(zip(LEVELS, SOLUTIONS)):
        walls = build_walls(lev["gw"], lev["gh"], lev["ew"], lev["src"], lev["drn"])
        water, path = trace(lev["src"], lev["drn"], sol, walls, lev["gw"], lev["gh"])
        reached = lev["drn"] in water
        status = "OK" if reached else "FAIL"
        if not reached:
            all_ok = False
        print(f"L{i+1} ({lev['n']}): {status}")
        for p in path:
            print(f"  {p}")
        if not reached:
            print("  *** WATER DID NOT REACH DRAIN ***")
        print()

    if all_ok:
        print("ALL LEVELS VERIFIED!")
    else:
        print("SOME LEVELS FAILED!")
