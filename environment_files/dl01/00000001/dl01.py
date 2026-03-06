# Dual-Core Logistics - Control two workers simultaneously
#
# D-pad moves BOTH workers at the same time. Workers stop at walls independently.
# Guide both workers to their matching colored goal tiles.
# Walls and layout force different paths for each worker.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_PINK = 6
C_GOLD = 11
C_ORANGE = 7
C_WHITE = 15
C_GRAY = 3
C_LIME = 14
C_RED = 12

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    # L1: 6x6, both workers go right to goals. Simple intro.
    # W1(1,2)->G1(4,2), W2(1,4)->G2(4,4). No obstacles between.
    {
        "name": "Sync Start",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "w1": (1, 2), "g1": (4, 2),
        "w2": (1, 4), "g2": (4, 4),
    },
    # L2: 7x7, workers start on same col, goals at different cols
    # Wall between them forces different timing
    # W1(1,2)->G1(5,2), W2(1,5)->G2(3,5)
    # Wall at (3,2) blocks W1, so W1 needs to go around
    {
        "name": "Split Path",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 2)},
        "w1": (1, 2), "g1": (5, 2),
        "w2": (1, 5), "g2": (3, 5),
    },
    # L3: 7x7, offset goals requiring different routes
    {
        "name": "Offset Goals",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5)},
        "w1": (1, 2), "g1": (5, 2),
        "w2": (1, 4), "g2": (5, 4),
    },
    # L4: 8x8, workers on same side, goals require going around walls
    {
        "name": "Mirror Start",
        "grid_w": 8, "grid_h": 8,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6),
                  (5, 2), (5, 3), (5, 4), (5, 6)},
        "w1": (1, 3), "g1": (6, 2),
        "w2": (1, 5), "g2": (6, 6),
    },
    # L5: 8x8, narrow corridors
    {
        "name": "Corridors",
        "grid_w": 8, "grid_h": 8,
        "walls": {(2, 1), (2, 2), (2, 3), (2, 5), (2, 6),
                  (5, 2), (5, 3), (5, 4), (5, 5), (5, 6)},
        "w1": (1, 3), "g1": (6, 2),
        "w2": (1, 5), "g2": (6, 5),
    },
    # L6: 9x9, maze-like with walls
    {
        "name": "Maze Run",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7),
                  (6, 2), (6, 3), (6, 4), (6, 5), (6, 6)},
        "w1": (1, 2), "g1": (7, 4),
        "w2": (1, 6), "g2": (7, 6),
    },
    # L7: 9x9, workers must swap sides
    {
        "name": "Crossover",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 1), (4, 2), (4, 3), (4, 5), (4, 6), (4, 7),
                  (2, 4), (6, 4)},
        "w1": (1, 2), "g1": (7, 6),
        "w2": (1, 6), "g2": (7, 2),
    },
    # L8: 10x10, complex routing
    {
        "name": "Logistics Hub",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7), (3, 8),
                  (6, 2), (6, 3), (6, 5), (6, 6), (6, 7), (6, 8)},
        "w1": (1, 4), "g1": (8, 2),
        "w2": (1, 7), "g2": (8, 7),
    },
    # L9: 10x10, tight maze
    {
        "name": "Tight Quarters",
        "grid_w": 10, "grid_h": 10,
        "walls": {(2, 2), (2, 3), (2, 5), (2, 6), (2, 7),
                  (4, 1), (4, 2), (4, 3), (4, 4), (4, 6), (4, 7), (4, 8),
                  (6, 2), (6, 3), (6, 5), (6, 6), (6, 7),
                  (8, 1), (8, 2), (8, 4), (8, 5), (8, 6), (8, 7), (8, 8)},
        "w1": (1, 4), "g1": (7, 2),
        "w2": (1, 7), "g2": (7, 7),
    },
    # L10: 12x10, grand finale
    {
        "name": "Grand Depot",
        "grid_w": 12, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 6), (3, 7), (3, 8),
                  (6, 2), (6, 3), (6, 6), (6, 7),
                  (9, 1), (9, 2), (9, 6), (9, 7), (9, 8)},
        "w1": (1, 3), "g1": (10, 2),
        "w2": (1, 7), "g2": (10, 7),
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


def _fill(frame, px, py, color):
    for dy in range(CELL):
        for dx in range(CELL):
            y, x = py + dy, px + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


def _dot(frame, px, py, color):
    cx, cy = px + CELL // 2, py + CELL // 2
    for dy in range(-1, 1):
        for dx in range(-1, 1):
            y, x = cy + dy, cx + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


class Dl01Display(RenderableUserDisplay):
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
                if (gx, gy) in g.walls:
                    _fill(frame, px, py, C_WHITE)
                else:
                    _fill(frame, px, py, C_MID)

        # Goal 1 (azure tint)
        gx, gy = g.g1
        px, py = ox + gx * CELL, oy + gy * CELL
        _fill(frame, px, py, C_GOLD)
        _dot(frame, px, py, C_AZURE)

        # Goal 2 (pink tint)
        gx, gy = g.g2
        px, py = ox + gx * CELL, oy + gy * CELL
        _fill(frame, px, py, C_GOLD)
        _dot(frame, px, py, C_PINK)

        # Worker 1
        w1x, w1y = g.w1x, g.w1y
        px, py = ox + w1x * CELL, oy + w1y * CELL
        _fill(frame, px, py, C_AZURE)

        # Worker 2
        w2x, w2y = g.w2x, g.w2y
        px, py = ox + w2x * CELL, oy + w2y * CELL
        _fill(frame, px, py, C_PINK)

        return frame


class Dl01(ARCBaseGame):
    def __init__(self):
        self.display = Dl01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "dl01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.w1x, self.w1y = d["w1"]
        self.w2x, self.w2y = d["w2"]
        self.g1 = d["g1"]
        self.g2 = d["g2"]

    def step(self):
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]

        # Move worker 1
        nx1, ny1 = self.w1x + dx, self.w1y + dy
        if (nx1, ny1) not in self.walls:
            # Don't move into worker 2's position
            if (nx1, ny1) != (self.w2x, self.w2y):
                self.w1x, self.w1y = nx1, ny1

        # Move worker 2
        nx2, ny2 = self.w2x + dx, self.w2y + dy
        if (nx2, ny2) not in self.walls:
            # Don't move into worker 1's NEW position
            if (nx2, ny2) != (self.w1x, self.w1y):
                self.w2x, self.w2y = nx2, ny2

        # Check win
        if (self.w1x, self.w1y) == self.g1 and (self.w2x, self.w2y) == self.g2:
            self.next_level()

        self.complete_action()
