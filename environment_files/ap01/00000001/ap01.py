# Atlas Push - Sokoban with momentum
#
# D-pad to move. Push blocks onto targets. Blocks slide on ice until hitting
# a wall or another block. Classic sokoban + ice physics.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_RED = 12
C_GOLD = 11
C_WHITE = 15
C_GRAY = 3
C_LIME = 14
C_ORANGE = 7

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    # L1: 6x6, 1 block, 1 target, block slides to wall
    {
        "name": "First Slide",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 2),
        "blocks": [(3, 2)],
        "targets": [(4, 2)],
    },
    # L2: 7x7, 1 block needs to slide around wall
    {
        "name": "Wall Stop",
        "grid_w": 7, "grid_h": 7,
        "walls": {(4, 3)},
        "player": (1, 3),
        "blocks": [(3, 3)],
        "targets": [(3, 1)],
    },
    # L3: 7x7, 2 blocks, 2 targets
    {
        "name": "Double Slide",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 3),
        "blocks": [(3, 1), (1, 3)],
        "targets": [(5, 1), (1, 5)],
    },
    # L4: 8x8, 2 blocks, walls as stoppers
    {
        "name": "Stoppers",
        "grid_w": 8, "grid_h": 8,
        "walls": {(4, 2), (2, 5)},
        "player": (1, 1),
        "blocks": [(3, 4), (5, 3)],
        "targets": [(3, 2), (2, 3)],
    },
    # L5: 8x8, use one block to stop another
    {
        "name": "Block Stop",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 3),
        "blocks": [(3, 3), (3, 5)],
        "targets": [(3, 4), (6, 3)],
    },
    # L6: 9x9, 3 blocks, 3 targets
    {
        "name": "Triple",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 2), (6, 5)},
        "player": (1, 4),
        "blocks": [(3, 4), (5, 4), (4, 6)],
        "targets": [(3, 2), (7, 4), (4, 7)],
    },
    # L7: 9x9, blocks + walls maze
    {
        "name": "Ice Maze",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5),
                  (6, 3), (6, 4), (6, 6), (6, 7)},
        "player": (1, 3),
        "blocks": [(2, 3), (5, 5)],
        "targets": [(2, 4), (5, 6)],
    },
    # L8: 10x10, 3 blocks, complex
    {
        "name": "Precision",
        "grid_w": 10, "grid_h": 10,
        "walls": {(4, 2), (4, 3), (4, 5), (4, 6),
                  (7, 3), (7, 4), (7, 6), (7, 7)},
        "player": (1, 4),
        "blocks": [(3, 4), (5, 4), (6, 5)],
        "targets": [(3, 5), (8, 4), (6, 7)],
    },
    # L9: 10x10, 4 blocks
    {
        "name": "Quartet",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 3), (3, 6), (6, 3), (6, 6)},
        "player": (1, 1),
        "blocks": [(2, 4), (4, 2), (5, 7), (7, 5)],
        "targets": [(2, 3), (6, 2), (5, 6), (6, 5)],
    },
    # L10: 12x10, 4 blocks, grand puzzle
    {
        "name": "Grand Push",
        "grid_w": 12, "grid_h": 10,
        "walls": {(4, 2), (4, 3), (4, 5), (4, 6), (4, 8),
                  (7, 1), (7, 3), (7, 4), (7, 6), (7, 7),
                  (10, 2), (10, 4), (10, 5), (10, 7), (10, 8)},
        "player": (1, 4),
        "blocks": [(3, 4), (5, 4), (8, 5), (9, 3)],
        "targets": [(3, 5), (5, 1), (8, 7), (10, 3)],
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


class Ap01Display(RenderableUserDisplay):
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
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Targets
        target_set = set(g.targets)
        for tx, ty in g.targets:
            px, py = ox + tx * CELL, oy + ty * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Blocks
        block_set = set(map(tuple, g.blocks))
        for bx, by in g.blocks:
            px, py = ox + bx * CELL, oy + by * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                if (bx, by) in target_set:
                    frame[py:py + CELL, px:px + CELL] = C_LIME  # on target
                else:
                    frame[py:py + CELL, px:px + CELL] = C_RED

        # Player
        ppx = ox + g.px * CELL
        ppy = oy + g.py * CELL
        if 0 <= ppx and ppx + CELL <= 64 and 0 <= ppy and ppy + CELL <= 64:
            frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        return frame


class Ap01(ARCBaseGame):
    def __init__(self):
        self.display = Ap01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "ap01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.blocks = [list(b) for b in d["blocks"]]
        self.targets = list(d["targets"])

    def _block_at(self, x, y):
        for i, (bx, by) in enumerate(self.blocks):
            if bx == x and by == y:
                return i
        return -1

    def _check_win(self):
        target_set = set(self.targets)
        for bx, by in self.blocks:
            if (bx, by) not in target_set:
                return False
        return True

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

        bi = self._block_at(nx, ny)
        if bi >= 0:
            # Push block - it slides until hitting wall or another block
            bx, by = nx, ny
            while True:
                nbx, nby = bx + dx, by + dy
                if (nbx, nby) in self.walls:
                    break
                if self._block_at(nbx, nby) >= 0:
                    break
                bx, by = nbx, nby
            if (bx, by) == (nx, ny):
                # Block can't move
                self.complete_action()
                return
            self.blocks[bi] = [bx, by]
            self.px, self.py = nx, ny
        else:
            self.px, self.py = nx, ny

        if self._check_win():
            self.next_level()

        self.complete_action()
