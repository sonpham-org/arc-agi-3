# Continuous Painter - Paint every floor tile by walking over it
#
# D-pad to move. Every tile you step on gets painted.
# Paint ALL tiles to win. You can't stop moving once you start
# in a direction (slide until hitting wall/painted edge).
# Actually: normal 1-step movement, just paint every tile you visit.
# Must visit every non-wall tile exactly. Revisiting is OK but wastes moves.
# Actually for more puzzle depth: once painted, tiles become slippery -
# you slide over painted tiles until hitting an unpainted one or wall.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_LIME = 14
C_WHITE = 15
C_GOLD = 11
C_GRAY = 3

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    # L1: 4x4 interior (6x6 with borders), simple path
    {
        "name": "First Coat",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 1),
    },
    # L2: 5x5 interior, walls creating corridors
    {
        "name": "Corridors",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 2), (3, 4)},
        "player": (1, 1),
    },
    # L3: 6x5 interior, L-shaped room
    {
        "name": "L-Shape",
        "grid_w": 8, "grid_h": 7,
        "walls": {(4, 1), (5, 1), (6, 1), (4, 2), (5, 2), (6, 2)},
        "player": (1, 1),
    },
    # L4: 6x6 interior, central pillar
    {
        "name": "Pillar Room",
        "grid_w": 8, "grid_h": 8,
        "walls": {(3, 3), (4, 3), (3, 4), (4, 4)},
        "player": (1, 1),
    },
    # L5: 7x6, maze corridors
    {
        "name": "Zigzag",
        "grid_w": 9, "grid_h": 8,
        "walls": {(2, 1), (2, 2), (2, 3),
                  (4, 3), (4, 4), (4, 5), (4, 6),
                  (6, 1), (6, 2), (6, 3)},
        "player": (1, 1),
    },
    # L6: 7x7, donut shape (opening at south side)
    {
        "name": "Donut",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 3), (4, 3), (5, 3),
                  (3, 4), (5, 4),
                  (3, 5), (5, 5)},
        "player": (1, 1),
    },
    # L7: 8x7, winding path
    {
        "name": "Serpentine",
        "grid_w": 10, "grid_h": 9,
        "walls": {(2, 1), (2, 2), (2, 3), (2, 4), (2, 5),
                  (4, 3), (4, 4), (4, 5), (4, 6), (4, 7),
                  (6, 1), (6, 2), (6, 3), (6, 4), (6, 5),
                  (8, 3), (8, 4), (8, 5), (8, 6), (8, 7)},
        "player": (1, 1),
    },
    # L8: 8x8, complex rooms with doorways
    {
        "name": "Apartments",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3),
                  (3, 5), (3, 6), (3, 8),
                  (6, 1), (6, 2),
                  (6, 5), (6, 6), (6, 8),
                  (1, 5), (4, 4), (5, 4),
                  (8, 4)},
        "player": (1, 1),
    },
    # L9: 9x9, spiral with openings
    {
        "name": "Spiral",
        "grid_w": 11, "grid_h": 11,
        "walls": {(2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1),
                  (9, 2), (9, 3), (9, 4), (9, 5), (9, 6), (9, 7), (9, 8),
                  (2, 8), (3, 8), (4, 8), (5, 8), (6, 8), (7, 8), (8, 8),
                  (2, 3), (2, 4), (2, 5), (2, 6), (2, 7),
                  (4, 3), (5, 3), (6, 3), (7, 3),
                  (7, 4), (7, 5), (7, 6),
                  (4, 6), (5, 6),
                  (4, 4)},
        "player": (1, 1),
    },
    # L10: 10x10, complex maze
    {
        "name": "Grand Gallery",
        "grid_w": 12, "grid_h": 12,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6),
                  (3, 8), (3, 9), (3, 10),
                  (6, 2), (6, 4), (6, 5),
                  (6, 7), (6, 8), (6, 10),
                  (9, 2), (9, 3), (9, 4), (9, 6),
                  (9, 7), (9, 9), (9, 10),
                  (1, 6), (4, 3), (5, 3),
                  (7, 6), (8, 6), (10, 3)},
        "player": (1, 1),
    },
]


def _border(w, h):
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


class Cp01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                    continue
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                elif (gx, gy) in g.painted:
                    frame[py:py + CELL, px:px + CELL] = C_LIME
                else:
                    frame[py:py + CELL, px:px + CELL] = C_GRAY

        # Player
        ppx = ox + g.px * CELL
        ppy = oy + g.py * CELL
        if 0 <= ppx and ppx + CELL <= 64 and 0 <= ppy and ppy + CELL <= 64:
            frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # HUD: unpainted count
        remaining = g.total_floor - len(g.painted)
        for i in range(min(remaining, 12)):
            hx = 1 + i * 5
            if hx + 3 > 64:
                break
            frame[0:2, hx:hx + 3] = C_GRAY

        return frame


class Cp01(ARCBaseGame):
    def __init__(self):
        self.display = Cp01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "cp01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.painted = {(self.px, self.py)}  # start tile is painted
        # Count total floor tiles
        self.total_floor = 0
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                if (gx, gy) not in self.walls:
                    self.total_floor += 1

    def step(self):
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        if (nx, ny) in self.walls:
            self.complete_action()
            return

        self.px, self.py = nx, ny
        self.painted.add((nx, ny))

        # Check win: all floor tiles painted
        if len(self.painted) >= self.total_floor:
            self.next_level()

        self.complete_action()
