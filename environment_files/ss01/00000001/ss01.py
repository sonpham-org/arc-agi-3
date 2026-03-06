"""
ss01 - Surge & Swap  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

A grid puzzle where the player can SWAP position with adjacent colored blocks.
When moving into a colored block, the player and block exchange positions:
the player ends up where the block was, and the block ends up where the player was.

Push blocks onto matching colored goal tiles. All goals filled = win level.

Key insight: to move a block to position X, stand at X and move toward the block.
The block lands where you were standing (position X). This is the reverse of
Sokoban pushing.

Fully deterministic - no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_DBLUE  = 1
C_GREEN  = 2
C_GRAY   = 3
C_YELLOW = 4
C_MID    = 5
C_PINK   = 6
C_ORANGE = 7
C_AZURE  = 8
C_BLUE   = 9
C_GOLD   = 11
C_RED    = 12
C_LIME   = 14
C_WHITE  = 15

# Cell size in pixels
CELL = 4

# Direction map: action_id -> (dx, dy) in grid coords
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# Block/goal color IDs and their display colors
#   color_id 1 = RED, color_id 2 = ORANGE, color_id 3 = LIME
_BLOCK_COLORS = {1: C_RED, 2: C_ORANGE, 3: C_LIME}
_GOAL_COLORS  = {1: C_PINK, 2: C_YELLOW, 3: C_GREEN}

# ═══════════════════════════════════════════════════════════════════════════
# Level definitions
# ═══════════════════════════════════════════════════════════════════════════
# Each level: grid dims, extra interior walls, player start, blocks, goals.
# Border cells (x=0, x=w-1, y=0, y=h-1) are always walls.
# Blocks: (x, y, color_id). Goals: (x, y, color_id).
#
# SWAP MECHANIC: player moves into block -> they exchange positions.
# Block ends up at player's old position. Player ends up at block's old position.
# To move block to target T: stand at T, move toward block.

LEVELS = [
    # L1: 5x5, 1 block (red), 1 goal. Optimal: 3 moves.
    {
        "name": "First Swap",
        "grid_w": 5, "grid_h": 5,
        "walls": set(),
        "player": (3, 2),
        "blocks": [(2, 2, 1)],
        "goals":  [(2, 1, 1)],
    },

    # L2: 5x5, 2 blocks (red, orange), 2 goals. Optimal: 10 moves.
    {
        "name": "Double Swap",
        "grid_w": 5, "grid_h": 5,
        "walls": set(),
        "player": (3, 1),
        "blocks": [(2, 2, 1), (2, 3, 2)],
        "goals":  [(1, 2, 1), (1, 3, 2)],
    },

    # L3: 6x6, 2 blocks, walls at bottom creating corridors. Optimal: 7 moves.
    {
        "name": "Corridors",
        "grid_w": 6, "grid_h": 6,
        "walls": {(2, 4), (3, 4)},
        "player": (2, 3),
        "blocks": [(1, 2, 1), (4, 2, 2)],
        "goals":  [(1, 3, 1), (4, 3, 2)],
    },

    # L4: 7x7, 3 blocks (red, orange, lime). Optimal: 14 moves.
    {
        "name": "Triple",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 1),
        "blocks": [(2, 2, 1), (4, 2, 2), (3, 4, 3)],
        "goals":  [(2, 3, 1), (4, 3, 2), (3, 5, 3)],
    },

    # L5: 7x7, 3 blocks with scrambled color matching. Optimal: 27 moves.
    {
        "name": "Color Match",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 3),
        "blocks": [(2, 2, 1), (2, 3, 2), (2, 4, 3)],
        "goals":  [(5, 4, 1), (5, 2, 2), (5, 3, 3)],
    },

    # L6: 8x8, 4 blocks in corners, each drops down 1. Optimal: 19 moves.
    {
        "name": "Four Corners",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 1),
        "blocks": [(2, 2, 1), (5, 2, 2), (2, 5, 1), (5, 5, 2)],
        "goals":  [(2, 3, 1), (5, 3, 2), (2, 6, 1), (5, 6, 2)],
    },

    # L7: 8x8, 4 blocks move outward (left/right). Optimal: 19 moves.
    {
        "name": "Crossroads",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (3, 4),
        "blocks": [(2, 3, 1), (5, 3, 2), (2, 5, 2), (5, 5, 1)],
        "goals":  [(1, 3, 1), (6, 3, 2), (1, 5, 2), (6, 5, 1)],
    },

    # L8: 9x9, 5 blocks, walls at x=4 create channels. Optimal: 25 moves.
    {
        "name": "Five Drops",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 2), (4, 3), (4, 6)},
        "player": (1, 4),
        "blocks": [(2, 2, 1), (2, 6, 2), (6, 2, 3), (6, 6, 1), (4, 4, 2)],
        "goals":  [(2, 3, 1), (2, 7, 2), (6, 3, 3), (6, 7, 1), (4, 5, 2)],
    },

    # L9: 9x9, 5 blocks with lateral movement. Optimal: 24 moves.
    {
        "name": "Color Swap",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "player": (4, 1),
        "blocks": [(2, 3, 1), (6, 3, 2), (2, 5, 3), (6, 5, 1), (4, 7, 3)],
        "goals":  [(1, 3, 1), (7, 3, 2), (1, 5, 3), (7, 5, 1), (4, 6, 3)],
    },

    # L10: 10x10, 6 blocks, walls at x=4 and x=6 create channels. Optimal: 29 moves.
    {
        "name": "Grand Swap",
        "grid_w": 10, "grid_h": 10,
        "walls": {(4, 3), (4, 4), (4, 6), (4, 7),
                  (6, 1), (6, 2), (6, 4), (6, 5), (6, 7), (6, 8)},
        "player": (1, 1),
        "blocks": [(2, 3, 1), (2, 5, 2), (2, 7, 3),
                   (8, 3, 1), (8, 5, 3), (8, 7, 2)],
        "goals":  [(2, 4, 1), (2, 6, 2), (2, 8, 3),
                   (8, 4, 1), (8, 6, 3), (8, 8, 2)],
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

        frame[:, :] = C_BLACK

        # Draw floor and walls
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.walls:
                    _fill(frame, px, py, C_GRAY)
                else:
                    _fill(frame, px, py, C_MID)

        # Draw goal tiles (rendered under blocks)
        for gx, gy, gc in g.goals:
            px, py = ox + gx * CELL, oy + gy * CELL
            goal_col = _GOAL_COLORS.get(gc, C_PINK)
            _fill(frame, px, py, goal_col)
            _dot(frame, px, py, C_BLACK)

        # Draw blocks
        for bx, by, bc in g.blocks:
            px, py = ox + bx * CELL, oy + by * CELL
            on_goal = any(bx == ggx and by == ggy and bc == ggc
                          for ggx, ggy, ggc in g.goals)
            if on_goal:
                _fill(frame, px, py, C_GOLD)
                _dot(frame, px, py, C_WHITE)
            else:
                block_col = _BLOCK_COLORS.get(bc, C_RED)
                _fill(frame, px, py, block_col)
                _dot(frame, px, py, C_WHITE)

        # Player
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        _fill(frame, ppx, ppy, C_AZURE)
        _dot(frame, ppx, ppy, C_WHITE)

        return frame


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
# Game
# ═══════════════════════════════════════════════════════════════════════════

class Ss01(ARCBaseGame):
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
            "ss01",
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
        self.walls = _border(self.grid_w, self.grid_h) | set(d["walls"])
        self.px, self.py = d["player"]
        self.blocks = [list(b) for b in d["blocks"]]  # [x, y, color_id]
        self.goals = list(d["goals"])  # (x, y, color_id)

    def _block_at(self, x, y):
        """Return index of block at (x,y), or -1 if none."""
        for i, (bx, by, _bc) in enumerate(self.blocks):
            if bx == x and by == y:
                return i
        return -1

    def _check_win(self):
        """Check if all goals have matching-color blocks on them."""
        for gx, gy, gc in self.goals:
            bi = self._block_at(gx, gy)
            if bi < 0 or self.blocks[bi][2] != gc:
                return False
        return True

    def step(self) -> None:
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        # Blocked by wall or out of bounds
        if (nx, ny) in self.walls:
            self.complete_action()
            return
        if nx < 0 or ny < 0 or nx >= self.grid_w or ny >= self.grid_h:
            self.complete_action()
            return

        bi = self._block_at(nx, ny)
        if bi >= 0:
            old_px, old_py = self.px, self.py
            # Block can't swap into a wall or another block
            if (old_px, old_py) in self.walls or self._block_at(old_px, old_py) >= 0:
                self.complete_action()
                return
            # Swap: player -> block's cell, block -> player's old cell
            self.px, self.py = nx, ny
            self.blocks[bi][0], self.blocks[bi][1] = old_px, old_py
        else:
            self.px, self.py = nx, ny

        if self._check_win():
            self.next_level()

        self.complete_action()
