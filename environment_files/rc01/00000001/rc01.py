# Rune Crafter - Visit checkpoints in the correct order
#
# D-pad to move. Visit numbered checkpoints in sequence.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0; C_MID = 5; C_AZURE = 8; C_GOLD = 11; C_WHITE = 15
C_RED = 12; C_LIME = 14; C_GRAY = 3; C_ORANGE = 7

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    {"name": "L1", "grid_w": 6, "grid_h": 6, "walls": set(), "player": (1, 1), "checkpoints": [(4, 1), (4, 4)]},
    {"name": "L2", "grid_w": 7, "grid_h": 7, "walls": set(), "player": (1, 1), "checkpoints": [(5, 1), (5, 5), (1, 5)]},
    {"name": "L3", "grid_w": 7, "grid_h": 7, "walls": {(3, 2), (3, 4)}, "player": (1, 3), "checkpoints": [(2, 1), (5, 3), (2, 5)]},
    {"name": "L4", "grid_w": 8, "grid_h": 8, "walls": {(4, 1), (4, 2), (4, 4), (4, 5), (4, 6)}, "player": (1, 3), "checkpoints": [(2, 1), (6, 3), (6, 6), (2, 6)]},
    {"name": "L5", "grid_w": 8, "grid_h": 8, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6), (6, 2), (6, 3), (6, 5), (6, 6)}, "player": (1, 3), "checkpoints": [(2, 1), (4, 3), (5, 6), (7, 1), (1, 6)]},
    {"name": "L6", "grid_w": 9, "grid_h": 9, "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7)}, "player": (1, 4), "checkpoints": [(2, 1), (4, 4), (7, 1), (7, 7), (4, 7)]},
    {"name": "L7", "grid_w": 9, "grid_h": 9, "walls": {(2, 2), (2, 3), (2, 5), (2, 6), (4, 1), (4, 3), (4, 5), (4, 7), (6, 2), (6, 4), (6, 6)}, "player": (1, 4), "checkpoints": [(3, 1), (5, 4), (7, 7), (3, 7), (7, 1), (1, 1)]},
    {"name": "L8", "grid_w": 10, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 8)}, "player": (1, 4), "checkpoints": [(2, 1), (4, 3), (7, 1), (8, 8), (4, 7), (1, 8)]},
    {"name": "L9", "grid_w": 10, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 8), (6, 2), (6, 3), (6, 4), (6, 6), (6, 7), (6, 8)}, "player": (1, 4), "checkpoints": [(2, 1), (4, 4), (7, 1), (8, 5), (4, 7), (1, 8), (8, 8)]},
    {"name": "L10", "grid_w": 12, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8), (6, 1), (6, 2), (6, 4), (6, 6), (6, 7), (9, 2), (9, 3), (9, 5), (9, 6), (9, 8)}, "player": (1, 4), "checkpoints": [(2, 1), (4, 3), (7, 3), (10, 1), (10, 8), (7, 7), (4, 7), (1, 8)]},
]

def _border(w, h):
    s = set()
    for x in range(w): s.add((x, 0)); s.add((x, h-1))
    for y in range(h): s.add((0, y)); s.add((w-1, y))
    return s

class Rc01Display(RenderableUserDisplay):
    def __init__(self, game): self.game = game
    def render_interface(self, frame):
        frame[:,:] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2; oy = (64 - g.grid_h * CELL) // 2
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox+gx*CELL, oy+gy*CELL
                if px<0 or py<0 or px+CELL>64 or py+CELL>64: continue
                if (gx,gy) in g.walls: frame[py:py+CELL, px:px+CELL] = C_WHITE
                else: frame[py:py+CELL, px:px+CELL] = C_MID
        for i,(cx,cy) in enumerate(g.checkpoints):
            px,py = ox+cx*CELL, oy+cy*CELL
            if 0<=px and px+CELL<=64 and 0<=py and py+CELL<=64:
                if i < g.next_cp: frame[py:py+CELL, px:px+CELL] = C_LIME
                elif i == g.next_cp: frame[py:py+CELL, px:px+CELL] = C_GOLD
                else: frame[py:py+CELL, px:px+CELL] = C_ORANGE
        ppx,ppy = ox+g.px*CELL, oy+g.py*CELL
        if 0<=ppx and ppx+CELL<=64 and 0<=ppy and ppy+CELL<=64:
            frame[ppy:ppy+CELL, ppx:ppx+CELL] = C_AZURE
        return frame

class Rc01(ARCBaseGame):
    def __init__(self):
        self.display = Rc01Display(self)
        levels = [Level(sprites=[], grid_size=(64,64), data=d, name=d["name"]) for d in LEVELS]
        super().__init__("rc01", levels, Camera(0,0,64,64,C_BLACK,C_BLACK,[self.display]), False, len(levels), [1,2,3,4])
    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w, self.grid_h = d["grid_w"], d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.checkpoints = list(d["checkpoints"])
        self.next_cp = 0
    def step(self):
        aid = self.action.id.value
        if aid not in _DIR: self.complete_action(); return
        dx, dy = _DIR[aid]
        nx, ny = self.px+dx, self.py+dy
        if (nx,ny) in self.walls: self.complete_action(); return
        self.px, self.py = nx, ny
        if self.next_cp < len(self.checkpoints):
            if (nx,ny) == tuple(self.checkpoints[self.next_cp]):
                self.next_cp += 1
                if self.next_cp >= len(self.checkpoints): self.next_level()
        self.complete_action()
