# Swarm Tamer - Control two workers simultaneously
#
# D-pad moves BOTH workers. Guide each to their goal.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0; C_MID = 5; C_AZURE = 8; C_PINK = 6; C_GOLD = 11
C_WHITE = 15; C_ORANGE = 7

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

LEVELS = [
    {"name": "L1", "grid_w": 6, "grid_h": 6, "walls": set(), "w1": (1, 2), "g1": (4, 2), "w2": (1, 4), "g2": (4, 4)},
    {"name": "L2", "grid_w": 7, "grid_h": 7, "walls": {(3, 2)}, "w1": (1, 2), "g1": (5, 2), "w2": (1, 5), "g2": (3, 5)},
    {"name": "L3", "grid_w": 7, "grid_h": 7, "walls": {(3, 1), (3, 2), (3, 4), (3, 5)}, "w1": (1, 2), "g1": (5, 2), "w2": (1, 4), "g2": (5, 4)},
    {"name": "L4", "grid_w": 8, "grid_h": 8, "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6), (5, 2), (5, 3), (5, 4), (5, 6)}, "w1": (1, 3), "g1": (6, 2), "w2": (1, 5), "g2": (6, 6)},
    {"name": "L5", "grid_w": 8, "grid_h": 8, "walls": {(2, 1), (2, 2), (2, 3), (2, 5), (2, 6), (5, 2), (5, 3), (5, 4), (5, 5), (5, 6)}, "w1": (1, 3), "g1": (6, 2), "w2": (1, 5), "g2": (6, 5)},
    {"name": "L6", "grid_w": 9, "grid_h": 9, "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7), (6, 2), (6, 3), (6, 4), (6, 5), (6, 6)}, "w1": (1, 2), "g1": (7, 4), "w2": (1, 6), "g2": (7, 6)},
    {"name": "L7", "grid_w": 9, "grid_h": 9, "walls": {(4, 1), (4, 2), (4, 3), (4, 5), (4, 6), (4, 7), (2, 4), (6, 4)}, "w1": (1, 2), "g1": (7, 6), "w2": (1, 6), "g2": (7, 2)},
    {"name": "L8", "grid_w": 10, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 7), (3, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7), (6, 8)}, "w1": (1, 4), "g1": (8, 2), "w2": (1, 7), "g2": (8, 7)},
    {"name": "L9", "grid_w": 10, "grid_h": 10, "walls": {(2, 2), (2, 3), (2, 5), (2, 6), (2, 7), (4, 1), (4, 2), (4, 3), (4, 4), (4, 6), (4, 7), (4, 8), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7), (8, 1), (8, 2), (8, 4), (8, 5), (8, 6), (8, 7), (8, 8)}, "w1": (1, 4), "g1": (7, 2), "w2": (1, 7), "g2": (7, 7)},
    {"name": "L10", "grid_w": 12, "grid_h": 10, "walls": {(3, 1), (3, 2), (3, 3), (3, 6), (3, 7), (3, 8), (6, 2), (6, 3), (6, 6), (6, 7), (9, 1), (9, 2), (9, 6), (9, 7), (9, 8)}, "w1": (1, 3), "g1": (10, 2), "w2": (1, 7), "g2": (10, 7)},
]

def _border(w, h):
    s = set()
    for x in range(w): s.add((x, 0)); s.add((x, h-1))
    for y in range(h): s.add((0, y)); s.add((w-1, y))
    return s

class St01Display(RenderableUserDisplay):
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
        gx,gy = g.g1; px,py = ox+gx*CELL, oy+gy*CELL
        if 0<=px and px+CELL<=64 and 0<=py and py+CELL<=64: frame[py:py+CELL, px:px+CELL] = C_GOLD; frame[py+1:py+3, px+1:px+3] = C_AZURE
        gx,gy = g.g2; px,py = ox+gx*CELL, oy+gy*CELL
        if 0<=px and px+CELL<=64 and 0<=py and py+CELL<=64: frame[py:py+CELL, px:px+CELL] = C_GOLD; frame[py+1:py+3, px+1:px+3] = C_PINK
        px,py = ox+g.w1x*CELL, oy+g.w1y*CELL
        if 0<=px and px+CELL<=64 and 0<=py and py+CELL<=64: frame[py:py+CELL, px:px+CELL] = C_AZURE
        px,py = ox+g.w2x*CELL, oy+g.w2y*CELL
        if 0<=px and px+CELL<=64 and 0<=py and py+CELL<=64: frame[py:py+CELL, px:px+CELL] = C_PINK
        return frame

class St01(ARCBaseGame):
    def __init__(self):
        self.display = St01Display(self)
        levels = [Level(sprites=[], grid_size=(64,64), data=d, name=d["name"]) for d in LEVELS]
        super().__init__("st01", levels, Camera(0,0,64,64,C_BLACK,C_BLACK,[self.display]), False, len(levels), [1,2,3,4])
    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w, self.grid_h = d["grid_w"], d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.w1x, self.w1y = d["w1"]; self.w2x, self.w2y = d["w2"]
        self.g1, self.g2 = d["g1"], d["g2"]
    def step(self):
        aid = self.action.id.value
        if aid not in _DIR: self.complete_action(); return
        dx, dy = _DIR[aid]
        nx1, ny1 = self.w1x+dx, self.w1y+dy
        if (nx1,ny1) not in self.walls and (nx1,ny1) != (self.w2x, self.w2y):
            self.w1x, self.w1y = nx1, ny1
        nx2, ny2 = self.w2x+dx, self.w2y+dy
        if (nx2,ny2) not in self.walls and (nx2,ny2) != (self.w1x, self.w1y):
            self.w2x, self.w2y = nx2, ny2
        if (self.w1x,self.w1y)==self.g1 and (self.w2x,self.w2y)==self.g2: self.next_level()
        self.complete_action()
