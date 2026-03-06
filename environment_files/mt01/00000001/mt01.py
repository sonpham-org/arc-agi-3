"""
mt01 - Momentum Tether  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Slide up
ACTION2 (v): Slide down
ACTION3 (<): Slide left
ACTION4 (>): Slide right

An ice-sliding puzzle. When you press a direction, the player slides
until hitting a wall or obstacle. The twist: you are tethered to a
companion block that slides in the same direction simultaneously.
Both must land on their respective goal tiles at the same time.

Player and companion pass through each other (no mutual collision).
They only stop when hitting walls or the grid border.

Fully deterministic - no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_MID    = 5
C_AZURE  = 8
C_PINK   = 6
C_GOLD   = 11
C_ORANGE = 7
C_WHITE  = 15
C_LIME   = 14

# Cell size in pixels
CELL = 4

# Direction map: action_id -> (dx, dy) in grid coords
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}


# ═══════════════════════════════════════════════════════════════════════════
# Level definitions
# ═══════════════════════════════════════════════════════════════════════════
# Each level: grid dims, interior walls, player start, companion start,
# player_goal, companion_goal.
#
# Coordinates: (x, y) where x=column, y=row, (0,0)=top-left.
# Border walls: x=0, x=w-1, y=0, y=h-1 are always walls.
# Playable area: x in [1..w-2], y in [1..h-2].
#
# Optimal solutions verified by BFS solver (test_solve.py).

LEVELS = [
    # ── L1: First Slide (tutorial, no companion) ────────────────────────
    # 5x5 grid. Player only. Learn ice-sliding.
    #
    #  #####
    #  #...#
    #  #...#
    #  #@..#     @ = player(1,3)
    #  #####
    #
    #  Goal: G at (3,1)
    #  Solution (2 moves): UP, RIGHT
    {
        "name": "First Slide",
        "grid_w": 5, "grid_h": 5,
        "walls": set(),
        "player": (1, 3),
        "companion": None,
        "player_goal": (3, 1),
        "companion_goal": None,
    },

    # ── L2: Tethered (intro companion) ──────────────────────────────────
    # 6x6 grid, 1 interior wall. First level with companion.
    #
    #  ######
    #  #@...#     @ = player(1,1)
    #  ##...#     # = wall(1,2)
    #  #C...#     C = companion(1,3)
    #  #....#
    #  ######
    #
    #  Goals: P_goal(4,1), C_goal(4,4)
    #  Solution (2 moves): DOWN, RIGHT
    #    DOWN: P stays (wall blocks), C slides to (1,4).
    #    RIGHT: P(1,1)->(4,1)=pg, C(1,4)->(4,4)=cg.
    {
        "name": "Tethered",
        "grid_w": 6, "grid_h": 6,
        "walls": {(1, 2)},
        "player": (1, 1),
        "companion": (1, 3),
        "player_goal": (4, 1),
        "companion_goal": (4, 4),
    },

    # ── L3: Left Turn ──────────────────────────────────────────────────
    # 6x6 grid, 2 interior walls.
    #
    #  ######
    #  ##.@.#     walls(1,1), player(3,1)
    #  ##...#     wall(1,2)
    #  #....#
    #  #..C.#     companion(3,4)
    #  ######
    #
    #  Goals: P_goal(4,1), C_goal(4,3)
    #  Solution (3 moves): LEFT, UP, RIGHT
    {
        "name": "Left Turn",
        "grid_w": 6, "grid_h": 6,
        "walls": {(1, 1), (1, 2)},
        "player": (3, 1),
        "companion": (3, 4),
        "player_goal": (4, 1),
        "companion_goal": (4, 3),
    },

    # ── L4: Detour ─────────────────────────────────────────────────────
    # 7x7 grid, 1 interior wall.
    #
    #  #######
    #  #@.C..#     player(1,1), companion(3,1)
    #  ##....#     wall(1,2)
    #  #.....#
    #  #.....#
    #  #.....#
    #  #######
    #
    #  Goals: P_goal(5,1), C_goal(5,3)
    #  Solution (4 moves): DOWN, LEFT, UP, RIGHT
    {
        "name": "Detour",
        "grid_w": 7, "grid_h": 7,
        "walls": {(1, 2)},
        "player": (1, 1),
        "companion": (3, 1),
        "player_goal": (5, 1),
        "companion_goal": (5, 3),
    },

    # ── L5: Split Path ─────────────────────────────────────────────────
    # 7x7 grid, 2 interior walls.
    #
    #  #######
    #  ##....#     wall(1,1)
    #  #.#...#     wall(2,2)
    #  #@.C..#     player(1,3), companion(3,3)
    #  #.....#
    #  #.....#
    #  #######
    #
    #  Goals: P_goal(5,5), C_goal(5,1)
    #  Solution (4 moves): UP, LEFT, DOWN, RIGHT
    {
        "name": "Split Path",
        "grid_w": 7, "grid_h": 7,
        "walls": {(1, 1), (2, 2)},
        "player": (1, 3),
        "companion": (3, 3),
        "player_goal": (5, 5),
        "companion_goal": (5, 1),
    },

    # ── L6: Long Way Around ────────────────────────────────────────────
    # 7x7 grid, 3 interior walls.
    #
    #  #######
    #  ##.@..#     wall(1,1), player(3,1)
    #  ##....#     wall(1,2)
    #  #.#C..#     wall(2,3), companion(3,3)
    #  #.....#
    #  #.....#
    #  #######
    #
    #  Goals: P_goal(5,5), C_goal(1,5)
    #  Solution (6 moves): LEFT, DOWN, LEFT, UP, RIGHT, DOWN
    {
        "name": "Long Way Around",
        "grid_w": 7, "grid_h": 7,
        "walls": {(2, 3), (1, 1), (1, 2)},
        "player": (3, 1),
        "companion": (3, 3),
        "player_goal": (5, 5),
        "companion_goal": (1, 5),
    },

    # ── L7: Winding Path ──────────────────────────────────────────────
    # 8x8 grid, 2 interior walls.
    #
    #  ########
    #  ##..@..#     wall(1,1), player(4,1)
    #  #......#
    #  #......#
    #  #......#
    #  #......#
    #  #.#.C..#     wall(2,6), companion(4,6)
    #  ########
    #
    #  Goals: P_goal(1,6), C_goal(6,6)
    #  Solution (5 moves): LEFT, DOWN, LEFT, DOWN, RIGHT
    {
        "name": "Winding Path",
        "grid_w": 8, "grid_h": 8,
        "walls": {(1, 1), (2, 6)},
        "player": (4, 1),
        "companion": (4, 6),
        "player_goal": (1, 6),
        "companion_goal": (6, 6),
    },

    # ── L8: Zigzag ─────────────────────────────────────────────────────
    # 8x8 grid, 3 interior walls.
    #
    #  ########
    #  ##..@..#     wall(1,1), player(4,1)
    #  #......#
    #  ##.....#     wall(1,3)
    #  #.#.C..#     wall(2,4), companion(4,4)
    #  #......#
    #  #......#
    #  ########
    #
    #  Goals: P_goal(6,6), C_goal(1,6)
    #  Solution (6 moves): LEFT, DOWN, LEFT, UP, RIGHT, DOWN
    {
        "name": "Zigzag",
        "grid_w": 8, "grid_h": 8,
        "walls": {(1, 1), (1, 3), (2, 4)},
        "player": (4, 1),
        "companion": (4, 4),
        "player_goal": (6, 6),
        "companion_goal": (1, 6),
    },

    # ── L9: Labyrinth ─────────────────────────────────────────────────
    # 9x9 grid, 3 interior walls.
    #
    #  #########
    #  ##..C...#     wall(1,1), companion(4,1)
    #  #......##     wall(7,2)
    #  #.......#
    #  ##......#     wall(1,4)
    #  #.......#
    #  #.......#
    #  #@......#     player(1,7)
    #  #########
    #
    #  Goals: P_goal(7,1), C_goal(7,7)
    #  Solution (10 moves): RIGHT, UP, LEFT, DOWN, LEFT, UP, RIGHT, UP, RIGHT, DOWN
    {
        "name": "Labyrinth",
        "grid_w": 9, "grid_h": 9,
        "walls": {(7, 2), (1, 1), (1, 4)},
        "player": (1, 7),
        "companion": (4, 1),
        "player_goal": (7, 1),
        "companion_goal": (7, 7),
    },

    # ── L10: Grand Finale ─────────────────────────────────────────────
    # 9x9 grid, 4 interior walls.
    #
    #  #########
    #  ##......#     wall(1,1)
    #  ##......#     wall(1,2)
    #  #.......#
    #  #...C...#     companion(4,4)
    #  ##......#     wall(1,5)
    #  #.......#
    #  #.#.@...#     wall(2,7), player(4,7)
    #  #########
    #
    #  Goals: P_goal(1,7), C_goal(7,7)
    #  Solution (8 moves): LEFT, UP, LEFT, DOWN, LEFT, DOWN, RIGHT, DOWN
    {
        "name": "Grand Finale",
        "grid_w": 9, "grid_h": 9,
        "walls": {(1, 1), (1, 2), (2, 7), (1, 5)},
        "player": (4, 7),
        "companion": (4, 4),
        "player_goal": (1, 7),
        "companion_goal": (7, 7),
    },
]


def _border(w, h):
    """All border cells as a set."""
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


# ═══════════════════════════════════════════════════════════════════════════
# Helper draw functions
# ═══════════════════════════════════════════════════════════════════════════

def _fill(frame, px, py, color):
    """Fill a CELL x CELL block."""
    for dy in range(CELL):
        for dx in range(CELL):
            y, x = py + dy, px + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


def _dot(frame, px, py, color):
    """Draw a 2x2 dot in cell center."""
    cx, cy = px + CELL // 2, py + CELL // 2
    for dy in range(-1, 1):
        for dx in range(-1, 1):
            y, x = cy + dy, cx + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


# ═══════════════════════════════════════════════════════════════════════════
# Display
# ═══════════════════════════════════════════════════════════════════════════

class Display(RenderableUserDisplay):
    def __init__(self, game):
        super().__init__()
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        if not hasattr(g, 'grid_w'):
            return frame

        gw, gh = g.grid_w, g.grid_h
        ox = (64 - gw * CELL) // 2
        oy = (64 - gh * CELL) // 2

        # Clear
        frame[:, :] = C_BLACK

        # Draw floor and walls
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.walls:
                    _fill(frame, px, py, C_WHITE)
                else:
                    _fill(frame, px, py, C_MID)

        # Player goal
        if g.player_goal:
            gx, gy_pos = g.player_goal
            px, py = ox + gx * CELL, oy + gy_pos * CELL
            _fill(frame, px, py, C_GOLD)
            _dot(frame, px, py, C_MID)

        # Companion goal
        if g.companion_goal:
            gx, gy_pos = g.companion_goal
            px, py = ox + gx * CELL, oy + gy_pos * CELL
            _fill(frame, px, py, C_ORANGE)
            _dot(frame, px, py, C_MID)

        # Companion (draw before player so player is on top)
        if g.comp_pos:
            cx, cy = g.comp_pos
            px, py = ox + cx * CELL, oy + cy * CELL
            if g.companion_goal and (cx, cy) == g.companion_goal:
                _fill(frame, px, py, C_LIME)
                _dot(frame, px, py, C_PINK)
            else:
                _fill(frame, px, py, C_PINK)
                _dot(frame, px, py, C_WHITE)

        # Player (draw last so it's on top)
        ppx, ppy = g.px, g.py
        px, py = ox + ppx * CELL, oy + ppy * CELL
        if g.player_goal and (ppx, ppy) == g.player_goal:
            _fill(frame, px, py, C_LIME)
            _dot(frame, px, py, C_AZURE)
        else:
            _fill(frame, px, py, C_AZURE)
            _dot(frame, px, py, C_WHITE)

        return frame


# ═══════════════════════════════════════════════════════════════════════════
# Game
# ═══════════════════════════════════════════════════════════════════════════

class Mt01(ARCBaseGame):
    def __init__(self):
        self.display = Display(self)

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "mt01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],
        )
        self._setup_level()

    def on_set_level(self, level):
        self._setup_level()

    def _setup_level(self):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]

        # Build wall set: borders + interior walls
        self.walls = _border(self.grid_w, self.grid_h) | set(d["walls"])

        # Player position
        self.px, self.py = d["player"]

        # Companion position (None for L1)
        self.comp_pos = tuple(d["companion"]) if d["companion"] else None

        # Goal positions
        self.player_goal = tuple(d["player_goal"]) if d["player_goal"] else None
        self.companion_goal = tuple(d["companion_goal"]) if d["companion_goal"] else None

    def _slide(self, x, y, dx, dy):
        """Slide from (x,y) in direction (dx,dy) until hitting a wall.
        Returns the final resting position."""
        while True:
            nx, ny = x + dx, y + dy
            if (nx, ny) in self.walls:
                return (x, y)
            x, y = nx, ny

    def step(self):
        aid = self.action.id.value
        direction = _DIR.get(aid)
        if direction is None:
            self.complete_action()
            return

        dx, dy = direction

        # Slide player
        self.px, self.py = self._slide(self.px, self.py, dx, dy)

        # Slide companion (if present)
        if self.comp_pos:
            self.comp_pos = self._slide(self.comp_pos[0], self.comp_pos[1], dx, dy)

        # Check win: player on player_goal AND companion on companion_goal
        player_ok = (self.px, self.py) == self.player_goal if self.player_goal else True
        comp_ok = self.comp_pos == self.companion_goal if self.companion_goal else True
        if player_ok and comp_ok:
            self.next_level()

        self.complete_action()
