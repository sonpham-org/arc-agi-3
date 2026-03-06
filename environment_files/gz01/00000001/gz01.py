# Graze - A bullet-dodging survival puzzle
#
# D-pad to move. Dodge projectiles fired from fixed launchers.
# Survive N turns to win. "Graze" (pass adjacent to a projectile) for bonus.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_RED = 12
C_WHITE = 15
C_GOLD = 11
C_ORANGE = 7
C_GRAY = 3
C_PINK = 6
C_LIME = 14

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# Launcher: fires a projectile every N turns from a fixed position in a fixed direction
# Projectile moves 1 cell per turn in its direction, destroyed when hitting wall

LEVELS = [
    # L1: 6x6, 1 launcher from right, survive 8 turns
    {
        "name": "Warm Up",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 3),
        "launchers": [(5, 3, -1, 0, 3, 0)],  # (x, y, dx, dy, fire_interval, fire_offset)
        "survive_turns": 8,
        "safe_zone": (1, 1),  # bonus: reach here after surviving
    },
    # L2: 7x7, 2 launchers from opposite sides
    {
        "name": "Crossfire",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 3),
        "launchers": [
            (6, 3, -1, 0, 3, 0),
            (0, 3, 1, 0, 3, 1),
        ],
        "survive_turns": 10,
        "safe_zone": (3, 1),
    },
    # L3: 7x7, launchers from top and right
    {
        "name": "Corner Dodge",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 3)},
        "player": (1, 5),
        "launchers": [
            (3, 0, 0, 1, 2, 0),
            (6, 5, -1, 0, 3, 0),
        ],
        "survive_turns": 12,
        "safe_zone": (5, 1),
    },
    # L4: 8x8, 3 launchers
    {
        "name": "Triangle",
        "grid_w": 8, "grid_h": 8,
        "walls": {(4, 4)},
        "player": (1, 1),
        "launchers": [
            (7, 3, -1, 0, 3, 0),
            (3, 0, 0, 1, 3, 1),
            (0, 6, 1, 0, 4, 0),
        ],
        "survive_turns": 15,
        "safe_zone": (6, 6),
    },
    # L5: 8x8, 3 launchers, walls for cover
    {
        "name": "Take Cover",
        "grid_w": 8, "grid_h": 8,
        "walls": {(3, 2), (3, 3), (3, 5), (3, 6)},
        "player": (1, 4),
        "launchers": [
            (7, 2, -1, 0, 2, 0),
            (7, 4, -1, 0, 2, 1),
            (7, 6, -1, 0, 3, 0),
        ],
        "survive_turns": 18,
        "safe_zone": (1, 1),
    },
    # L6: 9x9, 4 launchers from all sides
    {
        "name": "Four Winds",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 4)},
        "player": (4, 3),
        "launchers": [
            (8, 4, -1, 0, 3, 0),
            (0, 4, 1, 0, 3, 1),
            (4, 0, 0, 1, 4, 0),
            (4, 8, 0, -1, 4, 2),
        ],
        "survive_turns": 20,
        "safe_zone": (1, 1),
    },
    # L7: 9x9, 4 launchers, wall maze
    {
        "name": "Maze Dodge",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7),
                  (6, 2), (6, 3), (6, 5), (6, 6)},
        "player": (1, 4),
        "launchers": [
            (8, 2, -1, 0, 2, 0),
            (8, 6, -1, 0, 2, 1),
            (4, 0, 0, 1, 3, 0),
            (4, 8, 0, -1, 3, 1),
        ],
        "survive_turns": 22,
        "safe_zone": (7, 4),
    },
    # L8: 10x10, 5 launchers
    {
        "name": "Bullet Hell",
        "grid_w": 10, "grid_h": 10,
        "walls": {(5, 5)},
        "player": (1, 1),
        "launchers": [
            (9, 2, -1, 0, 3, 0),
            (9, 5, -1, 0, 3, 1),
            (9, 8, -1, 0, 3, 2),
            (5, 0, 0, 1, 4, 0),
            (2, 9, 0, -1, 4, 2),
        ],
        "survive_turns": 25,
        "safe_zone": (8, 8),
    },
    # L9: 10x10, 5 launchers, tight corridors
    {
        "name": "Gauntlet",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 8),
                  (6, 2), (6, 4), (6, 5), (6, 7), (6, 8)},
        "player": (1, 4),
        "launchers": [
            (9, 1, -1, 0, 2, 0),
            (9, 4, -1, 0, 2, 1),
            (9, 7, -1, 0, 3, 0),
            (5, 0, 0, 1, 3, 0),
            (5, 9, 0, -1, 3, 1),
        ],
        "survive_turns": 28,
        "safe_zone": (8, 5),
    },
    # L10: 12x10, 6 launchers, grand finale
    {
        "name": "Grand Barrage",
        "grid_w": 12, "grid_h": 10,
        "walls": {(4, 2), (4, 3), (4, 5), (4, 6), (4, 8),
                  (8, 1), (8, 3), (8, 4), (8, 6), (8, 7)},
        "player": (1, 5),
        "launchers": [
            (11, 2, -1, 0, 2, 0),
            (11, 5, -1, 0, 2, 1),
            (11, 8, -1, 0, 3, 0),
            (6, 0, 0, 1, 3, 0),
            (6, 9, 0, -1, 3, 1),
            (0, 2, 1, 0, 4, 0),
        ],
        "survive_turns": 35,
        "safe_zone": (10, 1),
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


class Gz01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw floor and walls
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw safe zone
        if g.survived:
            sx, sy = g.safe_zone
            px, py = ox + sx * CELL, oy + sy * CELL
            frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Draw launchers (on border, shown as orange)
        for lx, ly, _, _, _, _ in g.launcher_defs:
            px, py = ox + lx * CELL, oy + ly * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                frame[py:py + CELL, px:px + CELL] = C_ORANGE

        # Draw projectiles
        for bx, by, _, _ in g.bullets:
            px, py = ox + bx * CELL, oy + by * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                frame[py + 1:py + 3, px + 1:px + 3] = C_RED

        # Draw player
        ppx = ox + g.px * CELL
        ppy = oy + g.py * CELL
        frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # HUD: turn counter (top)
        remaining = max(0, g.survive_target - g.turn)
        for i in range(min(remaining, 12)):
            hx = 1 + i * 5
            if hx + 3 > 64:
                break
            frame[0:2, hx:hx + 3] = C_LIME

        return frame


class Gz01(ARCBaseGame):
    def __init__(self):
        self.display = Gz01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "gz01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.launcher_defs = d["launchers"]
        self.survive_target = d["survive_turns"]
        self.safe_zone = d["safe_zone"]
        self.turn = 0
        self.survived = False
        self.bullets = []  # (x, y, dx, dy)

    def step(self):
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        # Move player
        if (nx, ny) not in self.walls:
            self.px, self.py = nx, ny

        # Check bullet collision after player move
        for bx, by, _, _ in self.bullets:
            if (bx, by) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        # Check if survived and reached safe zone
        if self.survived and (self.px, self.py) == self.safe_zone:
            self.next_level()
            self.complete_action()
            return

        # Fire new bullets from launchers
        for lx, ly, ldx, ldy, interval, offset in self.launcher_defs:
            if self.turn >= offset and (self.turn - offset) % interval == 0:
                # Fire projectile from just inside the arena
                bx, by = lx + ldx, ly + ldy
                if (bx, by) not in self.walls:
                    self.bullets.append([bx, by, ldx, ldy])

        # Move existing bullets
        new_bullets = []
        for b in self.bullets:
            b[0] += b[2]
            b[1] += b[3]
            if (b[0], b[1]) not in self.walls:
                new_bullets.append(b)
        self.bullets = new_bullets

        # Check bullet collision after bullets move
        for bx, by, _, _ in self.bullets:
            if (bx, by) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        self.turn += 1
        if self.turn >= self.survive_target:
            self.survived = True

        self.complete_action()
