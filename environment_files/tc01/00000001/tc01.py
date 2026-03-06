# Trench Crafter - Dig trenches to redirect water flow
#
# D-pad to move. ACTION5 digs the tile you're standing on (floor -> trench).
# Water flows from source through trenches to reach the target.
# Dig a connected path of trenches from source to target to win.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay
from collections import deque

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_BLUE = 9
C_GOLD = 11
C_WHITE = 15
C_GRAY = 3
C_LIME = 14
C_RED = 12

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    {
        "name": "First Trench",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 3),
        "source": (1, 3),
        "target": (5, 3),
        "pre_dug": set(),
        "max_digs": 4,
    },
    {
        "name": "Around the Bend",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 2), (3, 3), (3, 4)},
        "player": (1, 1),
        "source": (1, 3),
        "target": (5, 3),
        "pre_dug": set(),
        "max_digs": 8,
    },
    {
        "name": "Two Paths",
        "grid_w": 8, "grid_h": 7,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5)},
        "player": (1, 3),
        "source": (1, 3),
        "target": (6, 3),
        "pre_dug": set(),
        "max_digs": 6,
    },
    {
        "name": "Long Route",
        "grid_w": 8, "grid_h": 8,
        "walls": {(2, 1), (2, 2), (2, 3), (2, 5), (2, 6),
                  (5, 2), (5, 3), (5, 4), (5, 5), (5, 6)},
        "player": (1, 4),
        "source": (1, 1),
        "target": (6, 6),
        "pre_dug": set(),
        "max_digs": 14,
    },
    {
        "name": "Island Hop",
        "grid_w": 9, "grid_h": 8,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6),
                  (6, 2), (6, 3), (6, 4), (6, 5), (6, 6)},
        "player": (1, 4),
        "source": (1, 1),
        "target": (7, 6),
        "pre_dug": set(),
        "max_digs": 16,
    },
    {
        "name": "Narrow Pass",
        "grid_w": 9, "grid_h": 9,
        "walls": {(2, 2), (2, 3), (2, 5), (2, 6), (2, 7),
                  (4, 1), (4, 2), (4, 3), (4, 5), (4, 6),
                  (6, 3), (6, 4), (6, 5), (6, 6), (6, 7)},
        "player": (1, 4),
        "source": (1, 1),
        "target": (7, 7),
        "pre_dug": set(),
        "max_digs": 18,
    },
    {
        "name": "Pre-Dug",
        "grid_w": 10, "grid_h": 8,
        "walls": {(4, 1), (4, 2), (4, 4), (4, 5), (4, 6),
                  (7, 2), (7, 3), (7, 4), (7, 5), (7, 6)},
        "player": (1, 3),
        "source": (1, 1),
        "target": (8, 6),
        "pre_dug": {(2, 1), (3, 1), (3, 3), (5, 3), (5, 1), (6, 1)},
        "max_digs": 12,
    },
    {
        "name": "Reservoir",
        "grid_w": 10, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7),
                  (6, 2), (6, 3), (6, 4), (6, 6), (6, 7)},
        "player": (1, 4),
        "source": (1, 1),
        "target": (8, 7),
        "pre_dug": {(2, 1), (2, 4), (4, 4), (5, 4), (5, 1), (7, 1)},
        "max_digs": 14,
    },
    {
        "name": "Aqueduct",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8),
                  (6, 2), (6, 3), (6, 5), (6, 6), (6, 8)},
        "player": (1, 5),
        "source": (1, 1),
        "target": (8, 8),
        "pre_dug": {(2, 1), (2, 3), (4, 3), (4, 6), (5, 6)},
        "max_digs": 18,
    },
    {
        "name": "Grand Canal",
        "grid_w": 12, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 8),
                  (6, 2), (6, 3), (6, 4), (6, 6), (6, 7), (6, 8),
                  (9, 1), (9, 2), (9, 4), (9, 5), (9, 7), (9, 8)},
        "player": (1, 4),
        "source": (1, 1),
        "target": (10, 8),
        "pre_dug": {(2, 1), (2, 4), (4, 4), (5, 4), (5, 1), (7, 1), (7, 5), (8, 5)},
        "max_digs": 20,
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


class Tc01Display(RenderableUserDisplay):
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
                elif (gx, gy) in g.water_cells:
                    frame[py:py + CELL, px:px + CELL] = C_BLUE
                elif (gx, gy) in g.trenches:
                    frame[py:py + CELL, px:px + CELL] = C_GRAY
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Source
        sx, sy = g.source_pos
        px, py = ox + sx * CELL, oy + sy * CELL
        if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
            frame[py:py + CELL, px:px + CELL] = C_RED

        # Target
        tx, ty = g.target_pos
        px, py = ox + tx * CELL, oy + ty * CELL
        if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
            frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Player
        ppx = ox + g.px * CELL
        ppy = oy + g.py * CELL
        if 0 <= ppx and ppx + CELL <= 64 and 0 <= ppy and ppy + CELL <= 64:
            frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # HUD: remaining digs
        for i in range(g.remaining_digs):
            hx = 1 + i * 3
            if hx + 2 > 64:
                break
            frame[0:2, hx:hx + 2] = C_LIME

        return frame


class Tc01(ARCBaseGame):
    def __init__(self):
        self.display = Tc01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "tc01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4, 5],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.source_pos = d["source"]
        self.target_pos = d["target"]
        self.trenches = set(d["pre_dug"]) | {d["source"], d["target"]}
        self.remaining_digs = d["max_digs"]
        self.water_cells = set()
        self._flow_water()

    def _flow_water(self):
        """BFS from source through connected trenches."""
        self.water_cells = set()
        start = self.source_pos
        if start not in self.trenches:
            return
        visited = {start}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            self.water_cells.add((x, y))
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nx, ny = x + dx, y + dy
                if (nx, ny) in self.trenches and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    def step(self):
        aid = self.action.id.value

        if aid == 5:
            # Dig trench at current position
            pos = (self.px, self.py)
            if pos not in self.walls and pos not in self.trenches and self.remaining_digs > 0:
                self.trenches.add(pos)
                self.remaining_digs -= 1
                self._flow_water()
                if self.target_pos in self.water_cells:
                    self.next_level()
            self.complete_action()
            return

        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        if (nx, ny) in self.walls:
            self.complete_action()
            return

        self.px, self.py = nx, ny
        self.complete_action()
