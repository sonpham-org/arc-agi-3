#!/usr/bin/env python3
"""Verify all lb01 v2 levels are solvable with the intended mirror placements."""

import sys

BEAM_DIRS = [
    (1, 0), (1, 1), (0, 1), (-1, 1),
    (-1, 0), (-1, -1), (0, -1), (1, -1),
]
DIR_INDEX = {d: i for i, d in enumerate(BEAM_DIRS)}

REFLECT = {}
for m in range(8):
    REFLECT[m] = {}
    for d in range(8):
        out = (m - d) % 8
        REFLECT[m][d] = None if out == d else out

LEVELS = [
    {"name": "First Bend", "grid_w": 7, "grid_h": 7, "walls": set(),
     "sources": [(0, 3, 1, 0)], "targets": [{"pos": (3, 6), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(3, 3)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Two Turns", "grid_w": 8, "grid_h": 8, "walls": set(),
     "sources": [(1, 0, 0, 1)], "targets": [{"pos": (6, 4), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(1, 3), (6, 3)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Periscope", "grid_w": 9, "grid_h": 9,
     "walls": {(4, 3), (4, 4), (4, 5), (4, 6)},
     "sources": [(0, 6, 1, 0)], "targets": [{"pos": (7, 2), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(3, 6), (3, 2)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Fixed Guide", "grid_w": 9, "grid_h": 9, "walls": set(),
     "sources": [(0, 2, 1, 0)], "targets": [{"pos": (7, 6), "color": "white"}],
     "fixed_mirrors": {(4, 2): 2}, "placeable": {(4, 6)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Detour", "grid_w": 10, "grid_h": 10,
     "walls": {(5, 3), (5, 4), (5, 5)},
     "sources": [(0, 5, 1, 0)], "targets": [{"pos": (7, 3), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(4, 5), (4, 1), (7, 1)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Diagonal", "grid_w": 10, "grid_h": 10, "walls": set(),
     "sources": [(0, 2, 1, 0)], "targets": [{"pos": (7, 8), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(2, 2), (4, 4), (4, 7), (7, 7)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "Fixed Angles", "grid_w": 11, "grid_h": 11, "walls": set(),
     "sources": [(0, 5, 1, 0)], "targets": [{"pos": (10, 9), "color": "white"}],
     "fixed_mirrors": {(4, 5): 1}, "placeable": {(7, 8), (7, 9)},
     "prisms": set(), "mist": set(), "switch": None, "door": None},
    {"name": "First Prism", "grid_w": 11, "grid_h": 11, "walls": {(7, 6)},
     "sources": [(5, 0, 0, 1)],
     "targets": [{"pos": (9, 5), "color": "red"}, {"pos": (5, 9), "color": "green"},
                 {"pos": (1, 8), "color": "blue"}],
     "fixed_mirrors": {}, "placeable": {(6, 5)},
     "prisms": {(5, 4)}, "mist": set(), "switch": None, "door": None},
    {"name": "Color Maze", "grid_w": 12, "grid_h": 12, "walls": set(),
     "sources": [(0, 6, 1, 0)],
     "targets": [{"pos": (6, 1), "color": "red"}, {"pos": (10, 6), "color": "green"},
                 {"pos": (6, 10), "color": "blue"}],
     "fixed_mirrors": {}, "placeable": {(6, 4), (6, 8)},
     "prisms": {(4, 6)}, "mist": set(), "switch": None, "door": None},
    {"name": "Misty Path", "grid_w": 10, "grid_h": 10, "walls": set(),
     "sources": [(0, 4, 1, 0)], "targets": [{"pos": (8, 4), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(2, 4), (2, 2), (7, 2), (7, 4)},
     "prisms": set(), "mist": {(3, 4), (4, 4), (5, 4), (6, 4)},
     "switch": None, "door": None},
    {"name": "Open Sesame", "grid_w": 12, "grid_h": 12, "walls": {(5, 3)},
     "sources": [(0, 3, 1, 0), (0, 8, 1, 0)],
     "targets": [{"pos": (10, 8), "color": "white"}],
     "fixed_mirrors": {}, "placeable": {(4, 3), (4, 1), (7, 1), (7, 3)},
     "prisms": set(), "mist": set(), "switch": (8, 3), "door": (6, 8)},
    {"name": "Grand Finale", "grid_w": 13, "grid_h": 13,
     "walls": {(5, 2), (8, 7)},
     "sources": [(0, 2, 1, 0), (0, 9, 1, 0)],
     "targets": [{"pos": (12, 8), "color": "red"}, {"pos": (12, 9), "color": "green"},
                 {"pos": (9, 12), "color": "blue"}],
     "fixed_mirrors": {}, "placeable": {(4, 2), (4, 1), (9, 1), (9, 2), (7, 8)},
     "prisms": {(6, 9)}, "mist": {(10, 8)},
     "switch": (10, 2), "door": (4, 9)},
]

# Expected solutions: list of dicts mapping (x,y) -> mirror_id
SOLUTIONS = [
    {(3, 3): 2},                                                        # L1
    {(1, 3): 2, (6, 3): 2},                                            # L2
    {(3, 6): 6, (3, 2): 6},                                            # L3
    {(4, 6): 2},                                                        # L4
    {(4, 5): 6, (4, 1): 6, (7, 1): 2},                                  # L5
    {(2, 2): 1, (4, 4): 3, (4, 7): 2, (7, 7): 2},                     # L6
    {(7, 8): 3, (7, 9): 2},                                            # L7
    {(6, 5): 1},                                                        # L8
    {(6, 4): 5, (6, 8): 3},                                            # L9
    {(2, 4): 6, (2, 2): 6, (7, 2): 2, (7, 4): 2},                     # L10
    {(4, 3): 6, (4, 1): 6, (7, 1): 2, (7, 3): 2},                     # L11
    {(4, 2): 6, (4, 1): 6, (9, 1): 2, (9, 2): 2, (7, 8): 7},         # L12
]


def trace_beams(lvl, mirrors):
    """Trace all beams for a level. Returns (segments, targets_hit, door_open)."""
    grid_w, grid_h = lvl["grid_w"], lvl["grid_h"]

    border_walls = set()
    for x in range(grid_w):
        border_walls.add((x, 0))
        border_walls.add((x, grid_h - 1))
    for y in range(grid_h):
        border_walls.add((0, y))
        border_walls.add((grid_w - 1, y))
    for src in lvl["sources"]:
        border_walls.discard((src[0], src[1]))
    for tgt in lvl["targets"]:
        border_walls.discard(tgt["pos"])
    if lvl["switch"]:
        border_walls.discard(lvl["switch"])

    all_walls = border_walls | lvl["walls"]
    prisms = lvl["prisms"]
    mist = lvl["mist"]
    targets = lvl["targets"]
    switch_pos = lvl["switch"]
    door_pos = lvl["door"]

    def trace_single(source, color, strength, door_open):
        sx, sy, dx, dy = source
        dir_idx = DIR_INDEX[(dx, dy)]
        segments = []
        queue = [(sx + dx, sy + dy, dir_idx, color, strength)]
        visited = set()

        while queue:
            x, y, d, col, stren = queue.pop(0)
            vk = (x, y, d, col)
            if vk in visited:
                continue
            if x < 0 or y < 0 or x >= grid_w or y >= grid_h:
                continue
            if (x, y) in all_walls:
                continue
            if (x, y) == door_pos and not door_open:
                continue
            visited.add(vk)

            cur_str = stren
            if (x, y) in mist:
                cur_str -= 1
                if cur_str <= 0:
                    segments.append((x, y, col, d, 0))
                    continue
            segments.append((x, y, col, d, cur_str))

            is_target = any((x, y) == t["pos"] for t in targets)
            if is_target:
                continue

            if (x, y) in prisms and col == "white":
                for new_col, delta in [("red", -1), ("green", 0), ("blue", 1)]:
                    new_d = (d + delta) % 8
                    ndx, ndy = BEAM_DIRS[new_d]
                    queue.append((x + ndx, y + ndy, new_d, new_col, 2))
                continue

            if (x, y) in mirrors:
                mid = mirrors[(x, y)]
                new_d = REFLECT[mid][d]
                if new_d is None:
                    ndx, ndy = BEAM_DIRS[d]
                    queue.append((x + ndx, y + ndy, d, col, cur_str))
                else:
                    ndx, ndy = BEAM_DIRS[new_d]
                    queue.append((x + ndx, y + ndy, new_d, col, cur_str))
                continue

            ndx, ndy = BEAM_DIRS[d]
            queue.append((x + ndx, y + ndy, d, col, cur_str))

        return segments

    all_segs = []
    door_open = False

    # Source 0
    if len(lvl["sources"]) > 0:
        segs = trace_single(lvl["sources"][0], "white", 3, door_open)
        all_segs.extend(segs)
        if switch_pos:
            for seg in segs:
                if (seg[0], seg[1]) == switch_pos:
                    door_open = True
                    break

    # Other sources
    for i in range(1, len(lvl["sources"])):
        segs = trace_single(lvl["sources"][i], "white", 3, door_open)
        all_segs.extend(segs)

    # Check targets
    targets_hit = set()
    for ti, tgt in enumerate(targets):
        tpos = tgt["pos"]
        tcol = tgt["color"]
        for seg in all_segs:
            sx, sy, scol, sdir, sstr = seg
            if (sx, sy) == tpos and scol == tcol and sstr > 0:
                targets_hit.add(ti)
                break

    return all_segs, targets_hit, door_open


def main():
    print("=" * 60)
    print("Light Bender v2 (lb01/00000002) Level Verification")
    print("=" * 60)

    all_ok = True

    for i, (lvl, sol) in enumerate(zip(LEVELS, SOLUTIONS)):
        all_mirrors = dict(lvl["fixed_mirrors"])
        all_mirrors.update(sol)

        segs, hits, door_open = trace_beams(lvl, all_mirrors)

        placeable_ok = all(pos in lvl["placeable"] for pos in sol)
        targets_ok = hits == set(range(len(lvl["targets"])))

        status = "OK" if (targets_ok and placeable_ok) else "FAIL"
        print(f"  L{i+1:2d} {lvl['name']:20s}: {status}  "
              f"(segs={len(segs)}, targets_hit={hits}/{set(range(len(lvl['targets'])))}, "
              f"mirrors={len(all_mirrors)}, door={'open' if door_open else 'closed/none'})")

        if not targets_ok:
            missed = set(range(len(lvl["targets"]))) - hits
            for ti in missed:
                t = lvl["targets"][ti]
                print(f"       MISS: {t['color']} target at {t['pos']} not reached")
            beam_positions = {(s[0], s[1]): (s[2], s[4]) for s in segs}
            print(f"       Beam reached cells: {sorted(beam_positions.keys())[:20]}...")
            all_ok = False
        if not placeable_ok:
            bad = [p for p in sol if p not in lvl["placeable"]]
            print(f"       BAD PLACEMENT: {bad} not in placeable")
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
