"""
ep01 - Echo Path  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

A deduction puzzle on a grid. Reach the exit without stepping on hidden traps.
Safe tiles display "echo numbers" showing how many of their 4-directional
neighbours are traps (like Minesweeper but 4-connected). Traps look identical
to floor tiles -- the player must use echo clues to deduce a safe path.

Step on a trap = lose.  Reach the exit = win.

Fully deterministic -- no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_GRAY   = 3
C_YELLOW = 4
C_MID    = 5
C_ORANGE = 7
C_AZURE  = 8
C_GOLD   = 11
C_RED    = 12
C_LIME   = 14
C_WHITE  = 15

# Cell size in pixels
CELL = 4

# Direction map: action_id -> (dx, dy)
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# 4-directional neighbour offsets
_ADJ4 = [(0, -1), (0, 1), (-1, 0), (1, 0)]

# ═══════════════════════════════════════════════════════════════════════════
# Level definitions
# ═══════════════════════════════════════════════════════════════════════════
# Each level: grid dims, interior walls (set of (x,y)), player start, exit,
# traps list. Border cells (x=0, x=w-1, y=0, y=h-1) are always walls.
# Traps are HIDDEN -- they look like floor but stepping on them = lose.
# Echo numbers on safe floor tiles reveal how many 4-dir adjacent tiles are traps.
#
# For each level, a verified solution path is documented.
#
# Legend in ASCII maps:
#   # = wall (border or interior)
#   . = floor (safe)
#   @ = player start
#   E = exit
#   T = trap (hidden, looks like floor)
#   Digits = echo number displayed on that safe tile

LEVELS = [
    # ── L1: First Steps (5x5, 1 trap) ──────────────────────────────────
    #   #####
    #   #@.E#      player (1,1), exit (3,1)
    #   #.T.#      trap at (2,2)
    #   #...#
    #   #####
    #
    # Echoes (safe interior tiles):
    #   (1,1)=0  (2,1)=1  (3,1)=exit
    #   (1,2)=1  --T--    (3,2)=1
    #   (1,3)=0  (2,3)=1  (3,3)=0
    #
    # Solution: RIGHT RIGHT  (2 moves)
    # Path: (1,1)->(2,1)->(3,1)=exit
    {
        "name": "First Steps",
        "grid_w": 5, "grid_h": 5,
        "walls": set(),
        "player": (1, 1),
        "exit": (3, 1),
        "traps": [(2, 2)],
    },

    # ── L2: Side Step (5x6, 2 traps) ───────────────────────────────────
    #   #####
    #   #@T.#      player (1,1), trap (2,1)
    #   #...#
    #   #.T.#      trap (2,3)
    #   #..E#      exit (3,4)
    #   #####
    #
    # Echoes:
    #   (1,1)=1  --T--  (3,1)=1
    #   (1,2)=1  (2,2)=2  (3,2)=1
    #   (1,3)=1  --T--  (3,3)=1
    #   (1,4)=0  (2,4)=1  (3,4)=exit
    #
    # Solution: DOWN DOWN DOWN RIGHT RIGHT  (5 moves)
    # Path: (1,1)->(1,2)->(1,3)->(1,4)->(2,4)->(3,4)=exit
    {
        "name": "Side Step",
        "grid_w": 5, "grid_h": 6,
        "walls": set(),
        "player": (1, 1),
        "exit": (3, 4),
        "traps": [(2, 1), (2, 3)],
    },

    # ── L3: Narrow Pass (6x6, 3 traps) ─────────────────────────────────
    #   ######
    #   #@..T#      player (1,1), trap (4,1)
    #   #.T..#      trap (2,2)
    #   #....#
    #   #..T.#      trap (3,4), exit (4,4)
    #   ######
    #
    # Solution: D D R R R D  (6 moves)
    # Path: (1,1)->(1,2)->(1,3)->(2,3)->(3,3)->(4,3)->(4,4)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Narrow Pass",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 1),
        "exit": (4, 4),
        "traps": [(4, 1), (2, 2), (3, 4)],
    },

    # ── L4: Zigzag (6x6, 4 traps) ──────────────────────────────────────
    #   ######
    #   #@T.T#      traps (2,1),(4,1)
    #   #....#
    #   #.T..#      trap (2,3)
    #   #..T.#      trap (3,4), exit (4,4)
    #   ######
    #
    # Solution: D R R R D D  (6 moves)
    # Path: (1,1)->(1,2)->(2,2)->(3,2)->(4,2)->(4,3)->(4,4)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Zigzag",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 1),
        "exit": (4, 4),
        "traps": [(2, 1), (4, 1), (2, 3), (3, 4)],
    },

    # ── L5: Bottleneck (7x7, 4 traps) ──────────────────────────────────
    #   #######
    #   #@..T.#      trap (4,1)
    #   #.....#
    #   #..T..#      trap (3,3)
    #   #.T...#      trap (2,4)
    #   #...TE#      trap (4,5), exit (5,5)
    #   #######
    #
    # Solution: D R R R R D D D  (8 moves)
    # Path: (1,1)->(1,2)->(2,2)->(3,2)->(4,2)->(5,2)->(5,3)->(5,4)->(5,5)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Bottleneck",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 1),
        "exit": (5, 5),
        "traps": [(4, 1), (3, 3), (2, 4), (4, 5)],
    },

    # ── L6: Serpentine (7x7, 5 traps) ───────────────────────────────────
    #   #######
    #   #@T...#      trap (2,1)
    #   #...T.#      trap (4,2)
    #   #.T...#      trap (2,3)
    #   #...T.#      trap (4,4)
    #   #.T..E#      trap (2,5), exit (5,5)
    #   #######
    #
    # 5 traps: (2,1),(4,2),(2,3),(4,4),(2,5)
    # Solution: D R R D D D R R  (8 moves)
    # Path: (1,1)->(1,2)->(2,2)->(3,2)->(3,3)->(3,4)->(3,5)->(4,5)->(5,5)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Serpentine",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 1),
        "exit": (5, 5),
        "traps": [(2, 1), (4, 2), (2, 3), (4, 4), (2, 5)],
    },

    # ── L7: Long Detour (8x8, 5 traps) ─────────────────────────────────
    #   ########
    #   #@...T.#      trap (5,1)
    #   #.T..T.#      traps (2,2),(5,2)
    #   #......#
    #   #..T..T#      traps (3,4),(6,4)
    #   #......#
    #   #.....E#      exit (6,6)
    #   ########
    #
    # 5 traps: (5,1),(2,2),(5,2),(3,4),(6,4)
    # Solution: D D R R R D D D R R  (10 moves)
    # Path: (1,1)->(1,2)->(1,3)->(2,3)->(3,3)->(4,3)->(4,4)->(4,5)
    # ->(4,6)->(5,6)->(6,6)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Long Detour",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 1),
        "exit": (6, 6),
        "traps": [(5, 1), (2, 2), (5, 2), (3, 4), (6, 4)],
    },

    # ── L8: Choke Points (8x8, 6 traps) ────────────────────────────────
    #   ########
    #   #@T....#      trap (2,1)
    #   #..T...#      trap (3,2)
    #   #....T.#      trap (5,3)
    #   #.T....#      trap (2,4)
    #   #....T.#      trap (5,5)
    #   #T....E#      trap (1,6), exit (6,6)
    #   ########
    #
    # 6 traps: (2,1),(3,2),(5,3),(2,4),(5,5),(1,6)
    # Solution: (1,1)->D(1,2)->D(1,3)->R(2,3)->R(3,3)->R(4,3)->D(4,4)->D(4,5)
    # ->D(4,6)->R(5,6)->R(6,6)=exit
    # Moves: D D R R R D D D R R = 10
    # Verify: (1,2)ok, (1,3)ok, (2,3)ok, (3,3)ok, (4,3)ok, (4,4)ok, (4,5)ok,
    # (4,6)ok, (5,6)ok, (6,6)exit. All safe!
    {
        "name": "Choke Points",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 1),
        "exit": (6, 6),
        "traps": [(2, 1), (3, 2), (5, 3), (2, 4), (5, 5), (1, 6)],
    },

    # ── L9: Dense Field (9x9, 9 traps) ─────────────────────────────────
    #   #########
    #   #@..T...#      trap (4,1)
    #   #.T...T.#      traps (2,2),(6,2)
    #   #.....T.#      trap (6,3)
    #   #T.T....#      traps (1,4),(3,4)
    #   #.....T.#      trap (6,5)
    #   #.T.....#      trap (2,6)
    #   #...T..E#      trap (4,7), exit (7,7)
    #   #########
    #
    # 9 traps: (4,1),(2,2),(6,2),(6,3),(1,4),(3,4),(6,5),(2,6),(4,7)
    # Solution: D D R R R R D D D D R R  (12 moves)
    # Path: (1,1)->(1,2)->(1,3)->(2,3)->(3,3)->(4,3)->(5,3)
    # ->(5,4)->(5,5)->(5,6)->(5,7)->(6,7)->(7,7)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Dense Field",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "player": (1, 1),
        "exit": (7, 7),
        "traps": [(4, 1), (2, 2), (6, 2), (6, 3), (1, 4), (3, 4),
                  (6, 5), (2, 6), (4, 7)],
    },

    # ── L10: Gauntlet (10x10, 12 traps) ────────────────────────────────
    #   ##########
    #   #@.T.....#      trap (3,1)
    #   #.T..T...#      traps (2,2),(5,2)
    #   #.....T..#      trap (6,3)
    #   #....T...#      trap (5,4)
    #   #.T...T..#      traps (2,5),(6,5)
    #   #...T..T.#      traps (4,6),(7,6)
    #   #.T......#      trap (2,7)
    #   #....T..E#      trap (5,8), exit (8,8)
    #   ##########
    #   + trap (8,6) not shown in map (blocks right side shortcut)
    #
    # 12 traps: (3,1),(2,2),(5,2),(6,3),(5,4),(2,5),(6,5),(4,6),(7,6),(2,7),(5,8),(8,6)
    # Solution: D D R R D D D D R R R R D R  (14 moves)
    # Path: (1,1)->(1,2)->(1,3)->(2,3)->(3,3)->(3,4)->(3,5)->(3,6)
    # ->(3,7)->(4,7)->(5,7)->(6,7)->(7,7)->(7,8)->(8,8)=exit
    # Verify: all path cells safe. OK!
    {
        "name": "Gauntlet",
        "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "player": (1, 1),
        "exit": (8, 8),
        "traps": [
            (3, 1), (2, 2), (5, 2), (6, 3), (5, 4),
            (2, 5), (6, 5), (4, 6), (7, 6), (2, 7),
            (5, 8), (8, 6),
        ],
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


def _count_adj_traps(x, y, traps):
    """Count how many 4-directional neighbours of (x,y) are traps."""
    count = 0
    for dx, dy in _ADJ4:
        if (x + dx, y + dy) in traps:
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════════════════
# Tiny digit rendering (3x3 font for digits 0-4 inside a 4x4 cell)
# ═══════════════════════════════════════════════════════════════════════════
_DIGITS_3x3 = {
    0: [
        [1, 1, 1],
        [1, 0, 1],
        [1, 1, 1],
    ],
    1: [
        [0, 1, 0],
        [1, 1, 0],
        [0, 1, 0],
    ],
    2: [
        [1, 1, 0],
        [0, 1, 0],
        [0, 1, 1],
    ],
    3: [
        [1, 1, 0],
        [0, 1, 0],
        [1, 1, 0],
    ],
    4: [
        [1, 0, 1],
        [1, 1, 1],
        [0, 0, 1],
    ],
}


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

        walls = g.all_walls
        traps = g.traps
        exit_pos = g.exit_pos

        # Draw tiles
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                pos = (gx, gy)

                if pos in walls:
                    _fill(frame, px, py, C_WHITE)
                elif pos == exit_pos:
                    _fill(frame, px, py, C_GOLD)
                elif pos in traps:
                    if g.dead:
                        # All traps revealed after death
                        _fill(frame, px, py, C_RED)
                    elif pos == (g.px, g.py):
                        # Player just stepped on this trap
                        _fill(frame, px, py, C_RED)
                    else:
                        # Hidden trap: looks like floor
                        _fill(frame, px, py, C_MID)
                else:
                    # Safe floor: draw echo number
                    _fill(frame, px, py, C_MID)
                    adj = _count_adj_traps(gx, gy, traps)
                    if adj > 0:
                        if adj == 1:
                            col = C_YELLOW
                        elif adj == 2:
                            col = C_ORANGE
                        else:
                            col = C_RED
                        _draw_digit(frame, px, py, adj, col)
                    else:
                        # 0 adjacent traps: small lime dot
                        _dot(frame, px, py, C_LIME)

        # Player (drawn on top of everything except after death)
        if not g.dead:
            ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
            _fill(frame, ppx, ppy, C_AZURE)
            _dot(frame, ppx, ppy, C_WHITE)
        else:
            ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
            _fill(frame, ppx, ppy, C_RED)
            _dot(frame, ppx, ppy, C_AZURE)

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


def _draw_digit(frame, px, py, digit, color):
    """Draw a 3x3 digit bitmap inside a CELL x CELL cell."""
    digit = min(digit, 4)
    bitmap = _DIGITS_3x3.get(digit)
    if bitmap is None:
        return
    for row in range(3):
        for col in range(3):
            if bitmap[row][col]:
                y, x = py + row, px + col
                if 0 <= y < 64 and 0 <= x < 64:
                    frame[y, x] = color


# ═══════════════════════════════════════════════════════════════════════════
# Game
# ═══════════════════════════════════════════════════════════════════════════

class Ep01(ARCBaseGame):
    def __init__(self):
        self.display = Display(self)
        self.dead = False

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "ep01",
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
        self.all_walls = _border(self.grid_w, self.grid_h) | d["walls"]
        self.px, self.py = d["player"]
        self.exit_pos = d["exit"]
        self.traps = set(tuple(t) for t in d["traps"])
        self.dead = False

    def step(self) -> None:
        if self.dead:
            self.complete_action()
            return

        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        # Bounds + wall check
        if (nx, ny) in self.all_walls:
            self.complete_action()
            return

        # Move player
        self.px, self.py = nx, ny

        # Check trap
        if (nx, ny) in self.traps:
            self.dead = True
            self.lose()
            self.complete_action()
            return

        # Check exit
        if (nx, ny) == self.exit_pos:
            self.next_level()
            self.complete_action()
            return

        self.complete_action()
