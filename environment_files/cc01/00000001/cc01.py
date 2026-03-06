# Checkmate Chaser - A tactical grid puzzle
#
# Controls:
# ACTION1 (^): Slide up
# ACTION2 (v): Slide down
# ACTION3 (<): Slide left
# ACTION4 (>): Slide right
#
# The player slides in a cardinal direction until hitting a wall or obstacle.
# Sliding into the enemy king captures it and wins the level.
# Sliding into a guard means game over.
# Guards patrol on fixed bounce paths and move after the player.
# All 10 levels are deterministic and solvable.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_GRAY = 3
C_MID = 5
C_AZURE = 8
C_GOLD = 11
C_RED = 12
C_WHITE = 15

# Crown icon drawn inside the king's cell (4x4)
CROWN = [
    [-1, C_GOLD, C_GOLD, -1],
    [C_GOLD, C_GOLD, C_GOLD, C_GOLD],
    [-1, C_GOLD, C_GOLD, -1],
    [C_GOLD, C_GOLD, C_GOLD, C_GOLD],
]

# Player icon (4x4)
PLAYER_ICON = [
    [-1, C_AZURE, C_AZURE, -1],
    [C_AZURE, C_AZURE, C_AZURE, C_AZURE],
    [C_AZURE, C_AZURE, C_AZURE, C_AZURE],
    [-1, C_AZURE, C_AZURE, -1],
]

# Guard icon (4x4)
GUARD_ICON = [
    [C_RED, -1, -1, C_RED],
    [C_RED, C_RED, C_RED, C_RED],
    [C_RED, C_RED, C_RED, C_RED],
    [-1, C_RED, C_RED, -1],
]


def _border(w, h):
    """Generate wall positions for the border of a grid."""
    walls = set()
    for x in range(w):
        walls.add((x, 0))
        walls.add((x, h - 1))
    for y in range(h):
        walls.add((0, y))
        walls.add((w - 1, y))
    return walls


# ============================================================================
# Level definitions
# guards: list of (x, y, dx, dy) — each guard bounces off walls/king
# ============================================================================

LEVELS = [
    # L1: 7x7, no guards — just slide right to capture king (tutorial)
    {
        "name": "First Capture",
        "grid_w": 7, "grid_h": 7,
        "walls": _border(7, 7),
        "obstacles": set(),
        "player": (1, 3),
        "king": (5, 3),
        "guards": [],
    },
    # L2: 7x7, obstacle blocks direct path, need 2-step L-shape
    # Player at bottom-left, king at top-right, obstacle forces detour
    {
        "name": "Corner Shot",
        "grid_w": 7, "grid_h": 7,
        "walls": _border(7, 7),
        "obstacles": {(5, 1)},
        "player": (1, 5),
        "king": (5, 2),
        "guards": [],
    },
    # L3: 7x7, 1 guard patrols vertically through the direct path
    # Guard starts at (3,3) blocking the direct route, need to wait
    {
        "name": "Patrol",
        "grid_w": 7, "grid_h": 7,
        "walls": _border(7, 7),
        "obstacles": set(),
        "player": (1, 3),
        "king": (5, 3),
        "guards": [(3, 3, 0, 1)],
    },
    # L4: 8x8, obstacle wall blocks direct path, 1 guard, 3-step solution
    # Vertical obstacle wall at x=3, gap at top. Must go up, right, down.
    {
        "name": "Detour",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8),
        "obstacles": {(3, 2), (3, 3), (3, 4), (3, 5), (3, 6)},
        "player": (1, 3),
        "king": (6, 5),
        "guards": [(5, 1, 0, 1)],
    },
    # L5: 8x8, 2 guards, obstacles create a barrier
    # Horizontal obstacle row forces going around, guard adds timing
    {
        "name": "Crossfire",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8),
        "obstacles": {(2, 3), (3, 3), (4, 3), (5, 3)},
        "player": (1, 1),
        "king": (6, 6),
        "guards": [(1, 4, 1, 0), (6, 2, 0, 1)],
    },
    # L6: 9x9, 2 guards, zigzag through obstacle maze
    # Two horizontal obstacle walls with staggered gaps force zigzag
    # Row y=3: blocks x=1..5, gap at x=6,7. Row y=5: blocks x=3..7, gap at x=1,2.
    {
        "name": "Zigzag",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9),
        "obstacles": {(1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
                      (3, 5), (4, 5), (5, 5), (6, 5), (7, 5)},
        "player": (1, 1),
        "king": (7, 7),
        "guards": [(6, 1, 0, 1), (2, 6, 0, -1)],
    },
    # L7: 9x9, 3 guards, horizontal obstacle rows force zigzag
    # Row y=2: blocks x=1..5, gap at x=6,7
    # Row y=5: blocks x=3..7, gap at x=1,2
    {
        "name": "Gauntlet",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9),
        "obstacles": {(1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                      (3, 5), (4, 5), (5, 5), (6, 5), (7, 5)},
        "player": (1, 1),
        "king": (7, 7),
        "guards": [(6, 1, 0, 1), (2, 4, 0, 1), (1, 6, 1, 0)],
    },
    # L8: 10x10, 3 guards, zigzag with two horizontal obstacle rows
    # Row y=3: blocks x=1..6, gap at x=7,8. Row y=6: blocks x=3..8, gap at x=1,2.
    {
        "name": "Serpentine",
        "grid_w": 10, "grid_h": 10,
        "walls": _border(10, 10),
        "obstacles": {(1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3),
                      (3, 6), (4, 6), (5, 6), (6, 6), (7, 6), (8, 6)},
        "player": (1, 1),
        "king": (8, 8),
        "guards": [(7, 1, 0, 1), (2, 4, 0, 1), (1, 7, 1, 0)],
    },
    # L9: 10x10, 4 guards, zigzag corridor maze
    # Row y=2: blocks x=1..6, gap at x=7,8 (go right at top)
    # Row y=4: blocks x=3..8, gap at x=1,2 (go left)
    # Row y=6: blocks x=1..6, gap at x=7,8 (go right)
    # King at bottom-right, reachable after 3 zigzags
    {
        "name": "Fortress",
        "grid_w": 10, "grid_h": 10,
        "walls": _border(10, 10),
        "obstacles": {(1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
                      (3, 4), (4, 4), (5, 4), (6, 4), (7, 4), (8, 4),
                      (1, 6), (2, 6), (3, 6), (4, 6), (5, 6), (6, 6)},
        "player": (1, 1),
        "king": (8, 8),
        "guards": [(7, 1, 0, 1), (2, 3, 0, 1), (7, 5, 0, 1), (2, 7, 0, 1)],
    },
    # L10: 12x10, 5 guards, grand chase zigzag
    # Three horizontal obstacle rows with staggered gaps
    # Row y=3: x=1..8 (gap at x=9,10) — forces sliding right
    # Row y=5: x=3..10 (gap at x=1,2) — forces sliding left
    # Row y=7: x=1..8 (gap at x=9,10) — forces sliding right again
    # Guards patrol in the corridors between obstacle rows
    {
        "name": "Grand Chase",
        "grid_w": 12, "grid_h": 10,
        "walls": _border(12, 10),
        "obstacles": {(1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3), (8, 3),
                      (3, 5), (4, 5), (5, 5), (6, 5), (7, 5), (8, 5), (9, 5), (10, 5),
                      (1, 7), (2, 7), (3, 7), (4, 7), (5, 7), (6, 7), (7, 7), (8, 7)},
        "player": (1, 1),
        "king": (10, 8),
        "guards": [(9, 2, 0, -1), (2, 4, 0, 1), (9, 4, 0, 1),
                   (2, 6, 0, 1), (9, 8, 0, -1)],
    },
]


# ============================================================================
# Display
# ============================================================================

class Cc01Display(RenderableUserDisplay):
    def __init__(self, game):
        super().__init__()
        self.game = game

    def render_interface(self, frame):
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw floor and walls
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                elif (gx, gy) in g.obstacles:
                    frame[py:py + CELL, px:px + CELL] = C_GRAY
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw king (crown icon)
        kx, ky = g.king_pos
        px, py = ox + kx * CELL, oy + ky * CELL
        for row_i in range(CELL):
            for col_i in range(CELL):
                c = CROWN[row_i][col_i]
                if c >= 0:
                    frame[py + row_i, px + col_i] = c

        # Draw guards
        for grd in g.guards:
            gx, gy = grd[0], grd[1]
            px, py = ox + gx * CELL, oy + gy * CELL
            for row_i in range(CELL):
                for col_i in range(CELL):
                    c = GUARD_ICON[row_i][col_i]
                    if c >= 0:
                        frame[py + row_i, px + col_i] = c

        # Draw player
        px, py = ox + g.px * CELL, oy + g.py * CELL
        for row_i in range(CELL):
            for col_i in range(CELL):
                c = PLAYER_ICON[row_i][col_i]
                if c >= 0:
                    frame[py + row_i, px + col_i] = c

        return frame


# ============================================================================
# Game
# ============================================================================

class Cc01(ARCBaseGame):
    def __init__(self):
        self.display = Cc01Display(self)
        levels = [
            Level(
                sprites=[],
                grid_size=(64, 64),
                data=d,
                name=d["name"],
            )
            for d in LEVELS
        ]
        super().__init__(
            "cc01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = set(d["walls"])
        self.obstacles = set(d["obstacles"])
        self.px, self.py = d["player"]
        self.king_pos = d["king"]
        self.guards = [[g[0], g[1], g[2], g[3]] for g in d["guards"]]

    def _is_blocking(self, x, y):
        """Check if a cell blocks sliding (wall or obstacle)."""
        if (x, y) in self.walls:
            return True
        if (x, y) in self.obstacles:
            return True
        return False

    def step(self):
        aid = self.action.id.value
        dx, dy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}.get(aid, (0, 0))
        if dx == 0 and dy == 0:
            self.complete_action()
            return

        # Slide player until hitting a wall/obstacle
        cx, cy = self.px, self.py
        while True:
            nx, ny = cx + dx, cy + dy

            # Hit wall or obstacle — stop before it
            if self._is_blocking(nx, ny):
                break

            # Sliding into king = capture = win
            if (nx, ny) == tuple(self.king_pos):
                self.px, self.py = nx, ny
                self.next_level()
                self.complete_action()
                return

            # Sliding into a guard = lose
            hit_guard = False
            for grd in self.guards:
                if (nx, ny) == (grd[0], grd[1]):
                    hit_guard = True
                    break
            if hit_guard:
                self.px, self.py = nx, ny
                self.lose()
                self.complete_action()
                return

            cx, cy = nx, ny

        self.px, self.py = cx, cy

        # If player didn't move at all, still move guards
        # Move guards (bounce off walls/obstacles/king)
        for g in self.guards:
            gx, gy, gdx, gdy = g[0], g[1], g[2], g[3]
            ngx, ngy = gx + gdx, gy + gdy
            if self._is_blocking(ngx, ngy) or (ngx, ngy) == tuple(self.king_pos):
                # Bounce: reverse direction
                g[2], g[3] = -gdx, -gdy
                ngx, ngy = gx - gdx, gy - gdy
                if self._is_blocking(ngx, ngy) or (ngx, ngy) == tuple(self.king_pos):
                    # Stuck — stay in place
                    ngx, ngy = gx, gy
            g[0], g[1] = ngx, ngy

        # Check if a guard landed on the player
        for grd in self.guards:
            if (grd[0], grd[1]) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        self.complete_action()
