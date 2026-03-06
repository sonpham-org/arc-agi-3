#!/usr/bin/env python3
"""Verify all lb01 levels are solvable with the intended mirror placements."""

import sys

M_SLASH = 1       # "/"
M_BACKSLASH = 2   # "\"

# "/" reflects: right->up, up->right, left->down, down->left
SLASH_REFLECT = {
    (1, 0): (0, -1),
    (-1, 0): (0, 1),
    (0, 1): (-1, 0),
    (0, -1): (1, 0),
}
# "\" reflects: right->down, down->right, left->up, up->left
BACKSLASH_REFLECT = {
    (1, 0): (0, 1),
    (-1, 0): (0, -1),
    (0, 1): (1, 0),
    (0, -1): (-1, 0),
}

LEVELS = [
    {
        "name": "First Bend", "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 3, 1, 0), "target": (3, 6),
        "fixed_mirrors": {},
        "placeable": {(3, 3)},
    },
    {
        "name": "Simple Bend", "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 2, 1, 0), "target": (3, 6),
        "fixed_mirrors": {},
        "placeable": {(3, 2)},
    },
    {
        "name": "Two Turns", "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "source": (1, 0, 0, 1), "target": (5, 7),
        "fixed_mirrors": {},
        "placeable": {(1, 3), (5, 3)},
    },
    {
        "name": "Fixed Guide", "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "source": (0, 2, 1, 0), "target": (7, 5),
        "fixed_mirrors": {(4, 2): M_BACKSLASH},
        "placeable": {(4, 5)},
    },
    {
        "name": "Triple Bounce", "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "source": (0, 1, 1, 0), "target": (4, 8),
        "fixed_mirrors": {},
        "placeable": {(2, 1), (2, 3), (4, 3)},
    },
    {
        "name": "Wall Detour", "grid_w": 9, "grid_h": 9,
        "walls": {(4, 3), (4, 4), (4, 5)},
        "source": (0, 4, 1, 0), "target": (8, 2),
        "fixed_mirrors": {},
        "placeable": {(3, 4), (3, 1), (7, 1), (7, 2)},
    },
    {
        "name": "Zigzag", "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "source": (0, 1, 1, 0), "target": (9, 8),
        "fixed_mirrors": {},
        "placeable": {(3, 1), (3, 4), (6, 4), (6, 8)},
    },
    {
        "name": "Fixed Maze", "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "source": (0, 2, 1, 0), "target": (9, 7),
        "fixed_mirrors": {(3, 2): M_BACKSLASH, (3, 5): M_BACKSLASH},
        "placeable": {(6, 5), (6, 7)},
    },
    {
        "name": "Periscope", "grid_w": 10, "grid_h": 10,
        "walls": {(5, 3), (5, 4), (5, 5)},
        "source": (0, 4, 1, 0), "target": (9, 2),
        "fixed_mirrors": {},
        "placeable": {(3, 4), (3, 1), (7, 1), (7, 2)},
    },
    {
        "name": "Grand Puzzle", "grid_w": 12, "grid_h": 10,
        "walls": {(5, 2), (5, 3), (6, 2), (6, 3), (7, 2), (7, 3)},
        "source": (2, 0, 0, 1), "target": (11, 7),
        "fixed_mirrors": {},
        "placeable": {(2, 3), (4, 3), (4, 1), (8, 1), (8, 7)},
    },
]

# Expected solutions: list of dicts mapping (x,y) -> mirror type
SOLUTIONS = [
    {(3, 3): M_BACKSLASH},
    {(3, 2): M_BACKSLASH},
    {(1, 3): M_BACKSLASH, (5, 3): M_BACKSLASH},
    {(4, 5): M_BACKSLASH},
    {(2, 1): M_BACKSLASH, (2, 3): M_BACKSLASH, (4, 3): M_BACKSLASH},
    {(3, 4): M_SLASH, (3, 1): M_SLASH, (7, 1): M_BACKSLASH, (7, 2): M_BACKSLASH},
    {(3, 1): M_BACKSLASH, (3, 4): M_BACKSLASH, (6, 4): M_BACKSLASH, (6, 8): M_BACKSLASH},
    {(6, 5): M_BACKSLASH, (6, 7): M_BACKSLASH},
    {(3, 4): M_SLASH, (3, 1): M_SLASH, (7, 1): M_BACKSLASH, (7, 2): M_BACKSLASH},
    {(2, 3): M_BACKSLASH, (4, 3): M_SLASH, (4, 1): M_SLASH, (8, 1): M_BACKSLASH, (8, 7): M_BACKSLASH},
]


def trace_beam(grid_w, grid_h, source, target, walls, mirrors):
    """Trace beam from source through mirrors. Returns (path, hit_target)."""
    # Build border walls
    border_walls = set()
    for x in range(grid_w):
        border_walls.add((x, 0))
        border_walls.add((x, grid_h - 1))
    for y in range(grid_h):
        border_walls.add((0, y))
        border_walls.add((grid_w - 1, y))
    # Remove source and target from border walls
    border_walls.discard((source[0], source[1]))
    border_walls.discard(target)
    # Combine with interior walls
    all_walls = border_walls | walls

    sx, sy, dx, dy = source
    x, y = sx + dx, sy + dy
    path = []
    visited = set()

    while True:
        if (x, y) in visited:
            break
        if (x, y) in all_walls:
            break
        if x < 0 or y < 0 or x >= grid_w or y >= grid_h:
            break
        visited.add((x, y))
        path.append((x, y))
        if (x, y) == target:
            break
        if (x, y) in mirrors:
            mtype = mirrors[(x, y)]
            if mtype == M_SLASH:
                new = SLASH_REFLECT.get((dx, dy))
            else:
                new = BACKSLASH_REFLECT.get((dx, dy))
            if new is None:
                break
            dx, dy = new
        x, y = x + dx, y + dy

    return path, target in path


def main():
    print("=" * 60)
    print("Light Bender (lb01) Level Verification")
    print("=" * 60)

    all_ok = True

    for i, (lvl, sol) in enumerate(zip(LEVELS, SOLUTIONS)):
        # Combine fixed mirrors + solution mirrors
        all_mirrors = dict(lvl["fixed_mirrors"])
        all_mirrors.update(sol)

        path, hit = trace_beam(
            lvl["grid_w"], lvl["grid_h"],
            lvl["source"], lvl["target"],
            lvl["walls"], all_mirrors,
        )

        # Verify solution mirrors are in placeable set
        placeable_ok = all(pos in lvl["placeable"] for pos in sol)

        status = "OK" if (hit and placeable_ok) else "FAIL"
        print(f"  L{i+1:2d} {lvl['name']:20s}: {status}  "
              f"(beam_len={len(path)}, "
              f"path_end={path[-1] if path else 'empty'}, "
              f"mirrors={len(all_mirrors)})")

        if not hit:
            print(f"       MISS: beam did not reach target {lvl['target']}")
            print(f"       Beam path: {path}")
            print(f"       Mirrors: {all_mirrors}")
            all_ok = False
        if not placeable_ok:
            bad = [p for p in sol if p not in lvl["placeable"]]
            print(f"       BAD PLACEMENT: mirrors {bad} not in placeable set")
            all_ok = False

    print()
    if all_ok:
        print("All levels verified SOLVABLE!")
    else:
        print("SOME LEVELS FAILED!")
    return all_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
