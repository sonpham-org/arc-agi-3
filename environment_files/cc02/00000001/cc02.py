# Circuit Connect - Visit every floor tile
#
# D-pad to move. Paint every tile by walking over it to win.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0; C_MID = 5; C_AZURE = 8; C_WHITE = 15; C_LIME = 14; C_GRAY = 3

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    {"name": "L1", "grid_w": 6, "grid_h": 6, "walls": set(), "player": (1, 1)},
    {"name": "L2", "grid_w": 7, "grid_h": 7, "walls": {(3, 3)}, "player": (1, 1)},
    {"name": "L3", "grid_w": 7, "grid_h": 7, "walls": {(3, 2), (3, 4)}, "player": (1, 1)},
    {"name": "L4", "grid_w": 8, "grid_h": 8, "walls": {(3, 3), (4, 3), (3, 4), (4, 4)}, "player": (1, 1)},
    {"name": "L5", "grid_w": 8, "grid_h": 8, "walls": {(2, 2), (2, 3), (2, 5), (5, 3), (5, 4), (5, 5)}, "player": (1, 1)},
    {"name": "L6", "grid_w": 9, "grid_h": 9, "walls": {(3, 2), (3, 3), (3, 5), (3, 6), (6, 3), (6, 4), (6, 5), (6, 6)}, "player": (1, 1)},
    {"name": "L7", "grid_w": 9, "grid_h": 9, "walls": {(2, 1), (2, 2), (2, 4), (2, 5), (2, 7), (5, 2), (5, 3), (5, 5), (5, 6)}, "player": (1, 3)},
    {"name": "L8", "grid_w": 10, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 8)}, "player": (1, 4)},
    {"name": "L9", "grid_w": 10, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7)}, "player": (1, 4)},
    {"name": "L10", "grid_w": 12, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 8), (9, 1), (9, 3), (9, 4), (9, 6), (9, 7)}, "player": (1, 4)},
]

def _border(w, h):
    s = set()
    for x in range(w): s.add((x, 0)); s.add((x, h-1))
    for y in range(h): s.add((0, y)); s.add((w-1, y))
    return s

class Cc02Display(RenderableUserDisplay):
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
                elif (gx,gy) in g.painted: frame[py:py+CELL, px:px+CELL] = C_LIME
                else: frame[py:py+CELL, px:px+CELL] = C_GRAY
        ppx,ppy = ox+g.px*CELL, oy+g.py*CELL
        if 0<=ppx and ppx+CELL<=64 and 0<=ppy and ppy+CELL<=64:
            frame[ppy:ppy+CELL, ppx:ppx+CELL] = C_AZURE
        return frame

class Cc02(ARCBaseGame):
    def __init__(self):
        self.display = Cc02Display(self)
        levels = [Level(sprites=[], grid_size=(64,64), data=d, name=d["name"]) for d in LEVELS]
        super().__init__("cc02", levels, Camera(0,0,64,64,C_BLACK,C_BLACK,[self.display]), False, len(levels), [1,2,3,4])
    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w, self.grid_h = d["grid_w"], d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.painted = {(self.px, self.py)}
        self.total = sum(1 for y in range(self.grid_h) for x in range(self.grid_w) if (x,y) not in self.walls)
    def step(self):
        aid = self.action.id.value
        if aid not in _DIR: self.complete_action(); return
        dx, dy = _DIR[aid]
        nx, ny = self.px+dx, self.py+dy
        if (nx,ny) in self.walls: self.complete_action(); return
        self.px, self.py = nx, ny
        self.painted.add((nx,ny))
        if len(self.painted) >= self.total: self.next_level()
        self.complete_action()
