"""
td02 – Timeline Detective  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

Goal: Visit numbered checkpoints in ascending order (1, 2, 3, ...),
then reach the exit. Stepping on a future checkpoint out of order = lose.
Walls and obstacles force routing decisions.
10 levels with increasing complexity.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4  # pixels per grid cell (64 / 16 = 4 max for 16-wide grids)

# Colour palette
C_BLACK = 0    # background
C_MID = 5      # floor
C_AZURE = 8    # player
C_GOLD = 11    # next checkpoint to visit
C_LIME = 14    # visited checkpoint
C_RED = 12     # unvisited future checkpoint
C_WHITE = 15   # walls
C_GRAY = 3     # floor variant (unused but reserved)
C_ORANGE = 7   # exit (when all checkpoints visited)

# ── Level definitions ────────────────────────────────────────────────────────
# Coordinates are (x, y) in grid space.  x=col, y=row.
# Borders are auto-added; "walls" lists interior walls only.
# Player, checkpoints, and exit must NOT be on wall or border tiles.

LEVELS = [
    # L1: 5x5, 2 checkpoints, simple path
    {
        "name": "First Steps",
        "grid_w": 5, "grid_h": 5,
        "walls": [],
        "player": (1, 1),
        "checkpoints": [(3, 1), (3, 3)],
        "exit": (1, 3),
    },
    # L2: 6x6, 3 checkpoints, open layout
    {
        "name": "Three Marks",
        "grid_w": 6, "grid_h": 6,
        "walls": [],
        "player": (1, 1),
        "checkpoints": [(4, 1), (4, 4), (1, 4)],
        "exit": (1, 2),
    },
    # L3: 7x7, 4 checkpoints, walls force detours
    {
        "name": "Walled Garden",
        "grid_w": 7, "grid_h": 7,
        "walls": [
            (3, 1), (3, 2), (3, 3),  # vertical wall in middle
        ],
        "player": (1, 1),
        "checkpoints": [(2, 1), (5, 2), (5, 5), (1, 5)],
        "exit": (1, 3),
    },
    # L4: 7x7, 4 checkpoints, must backtrack
    {
        "name": "Backtrack",
        "grid_w": 7, "grid_h": 7,
        "walls": [
            (2, 3), (3, 3), (4, 3),  # horizontal wall
        ],
        "player": (1, 1),
        "checkpoints": [(5, 1), (1, 2), (5, 5), (1, 5)],
        "exit": (3, 5),
    },
    # L5: 8x8, 5 checkpoints, maze walls
    {
        "name": "Maze Runner",
        "grid_w": 8, "grid_h": 8,
        "walls": [
            (2, 1), (2, 2), (2, 3),          # left vertical wall
            (4, 4), (4, 5), (4, 6),           # middle vertical wall
            (5, 2), (6, 2),                   # top horizontal stub
        ],
        "player": (1, 1),
        "checkpoints": [(1, 4), (3, 1), (6, 1), (6, 4), (1, 6)],
        "exit": (6, 6),
    },
    # L6: 8x8, 5 checkpoints, tight corridors
    {
        "name": "Tight Squeeze",
        "grid_w": 8, "grid_h": 8,
        "walls": [
            (2, 2), (3, 2), (4, 2), (5, 2),  # top horizontal wall
            (2, 4), (3, 4),                   # middle-left wall
            (5, 4), (5, 5),                   # middle-right wall
        ],
        "player": (1, 1),
        "checkpoints": [(6, 1), (6, 3), (1, 3), (1, 6), (6, 6)],
        "exit": (3, 6),
    },
    # L7: 9x9, 6 checkpoints, serpentine walls
    {
        "name": "Labyrinth",
        "grid_w": 9, "grid_h": 9,
        "walls": [
            (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),   # row 2 wall (gap at 1,7)
            (4, 4), (5, 4), (6, 4), (7, 4),             # row 4 wall (gap at 1-3)
            (2, 6), (3, 6), (4, 6), (5, 6),             # row 6 wall (gap at 1,6-7)
        ],
        "player": (1, 1),
        "checkpoints": [(7, 1), (7, 3), (1, 3), (1, 5), (7, 5), (7, 7)],
        "exit": (1, 7),
    },
    # L8: 9x9, 6 checkpoints, tighter serpentine variant
    {
        "name": "Serpentine",
        "grid_w": 9, "grid_h": 9,
        "walls": [
            (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),   # row 2 wall (gap at 6-7)
            (3, 4), (4, 4), (5, 4), (6, 4), (7, 4),   # row 4 wall (gap at 1-2)
            (1, 6), (2, 6), (3, 6), (4, 6), (5, 6),   # row 6 wall (gap at 6-7)
        ],
        "player": (1, 1),
        "checkpoints": [(7, 1), (7, 3), (1, 3), (1, 5), (7, 5), (7, 7)],
        "exit": (1, 7),
    },
    # L9: 10x10, 7 checkpoints
    {
        "name": "Grand Tour",
        "grid_w": 10, "grid_h": 10,
        "walls": [
            (3, 1), (3, 2), (3, 3),                    # upper-left vertical
            (5, 2), (5, 3), (5, 4),                    # center vertical
            (7, 3), (7, 4),                             # upper-right vertical
            (2, 5), (3, 5), (4, 5),                    # mid-left horizontal
            (6, 6), (7, 6),                             # mid-right horizontal
            (3, 7), (4, 7),                             # lower horizontal
        ],
        "player": (1, 1),
        "checkpoints": [
            (2, 1), (8, 1), (8, 5), (6, 8), (1, 8), (1, 4), (6, 4)
        ],
        "exit": (8, 8),
    },
    # L10: 10x10, 8 checkpoints, grand maze
    {
        "name": "Grand Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": [
            (2, 2), (3, 2),                             # top-left horizontal
            (5, 1), (5, 2), (5, 3),                    # center-top vertical
            (7, 2), (7, 3),                             # right-top vertical
            (2, 4), (3, 4),                             # mid-left horizontal
            (5, 5), (6, 5), (7, 5),                    # mid horizontal
            (2, 6), (3, 6),                             # left-lower horizontal
            (5, 7), (5, 8),                             # center-lower vertical
            (7, 7), (8, 7),                             # right-lower horizontal
        ],
        "player": (1, 1),
        "checkpoints": [
            (4, 1), (8, 1), (8, 4), (1, 3), (1, 5), (4, 8), (8, 6), (1, 8)
        ],
        "exit": (8, 8),
    },
]


# ── Display ──────────────────────────────────────────────────────────────────

class Td02Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        gw, gh = g.grid_w, g.grid_h
        ox = (64 - gw * CELL) // 2
        oy = (64 - gh * CELL) // 2

        # Draw floor and walls
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.wall_set:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw checkpoints
        for i, (cx, cy) in enumerate(g.checkpoints):
            px, py = ox + cx * CELL, oy + cy * CELL
            if i < g.next_cp:
                # Visited
                frame[py:py + CELL, px:px + CELL] = C_LIME
            elif i == g.next_cp:
                # Next target (gold)
                frame[py:py + CELL, px:px + CELL] = C_GOLD
            else:
                # Future (not yet reachable)
                frame[py:py + CELL, px:px + CELL] = C_RED

        # Draw exit (only when all checkpoints visited)
        if g.next_cp >= len(g.checkpoints):
            ex, ey = g.exit_pos
            px, py = ox + ex * CELL, oy + ey * CELL
            frame[py:py + CELL, px:px + CELL] = C_ORANGE

        # Draw player on top
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        return frame


# ── Game ─────────────────────────────────────────────────────────────────────

class Td02(ARCBaseGame):
    def __init__(self):
        self.display = Td02Display(self)

        # Mutable state – properly set by on_set_level
        self.grid_w = 5
        self.grid_h = 5
        self.wall_set = set()
        self.px = 1
        self.py = 1
        self.checkpoints = []
        self.exit_pos = (1, 3)
        self.next_cp = 0

        game_levels = [
            Level(sprites=[], grid_size=(64, 64), data=d, name=d["name"])
            for d in LEVELS
        ]
        super().__init__(
            "td02",
            game_levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(game_levels),
            [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]

        # Build wall set: interior walls + borders
        self.wall_set = set()
        for w in d["walls"]:
            self.wall_set.add(tuple(w))
        # Add borders
        for x in range(self.grid_w):
            self.wall_set.add((x, 0))
            self.wall_set.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.wall_set.add((0, y))
            self.wall_set.add((self.grid_w - 1, y))

        self.px, self.py = d["player"]
        self.checkpoints = list(d["checkpoints"])
        self.exit_pos = tuple(d["exit"])
        self.next_cp = 0

    def step(self):
        aid = self.action.id.value
        dx, dy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}.get(aid, (0, 0))

        if dx == 0 and dy == 0:
            self.complete_action()
            return

        nx, ny = self.px + dx, self.py + dy

        # Bounds check
        if nx < 0 or nx >= self.grid_w or ny < 0 or ny >= self.grid_h:
            self.complete_action()
            return

        # Wall check
        if (nx, ny) in self.wall_set:
            self.complete_action()
            return

        self.px, self.py = nx, ny

        # Check checkpoint logic
        if self.next_cp < len(self.checkpoints):
            current_pos = (self.px, self.py)
            # Check if we stepped on the correct next checkpoint
            cp = self.checkpoints[self.next_cp]
            if current_pos == cp:
                self.next_cp += 1
            else:
                # Check if stepped on a WRONG (future) checkpoint
                for i in range(self.next_cp + 1, len(self.checkpoints)):
                    if current_pos == self.checkpoints[i]:
                        self.lose()
                        self.complete_action()
                        return

        # Check exit (only reachable after all checkpoints visited)
        if self.next_cp >= len(self.checkpoints):
            if (self.px, self.py) == self.exit_pos:
                if not self.is_last_level():
                    self.next_level()
                else:
                    self.win()
                self.complete_action()
                return

        self.complete_action()
