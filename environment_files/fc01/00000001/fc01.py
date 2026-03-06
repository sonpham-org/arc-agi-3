"""
fc01 - Frontline Courier  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

A grid-based delivery puzzle. Pick up packages from pickup zones and deliver
them to matching delivery zones. Avoid patrol enemies that bounce along fixed
routes. Deliver all packages, then reach the exit to clear each level.

Rules:
- Walk onto a package = pick it up (carry only 1 at a time)
- Walk onto a matching delivery zone while carrying = deliver
- Deliver all packages = exit appears
- Step on exit = win the level
- Enemy touches player = lose

Fully deterministic -- no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_GREEN  = 2
C_GRAY   = 3
C_MID    = 5
C_ORANGE = 7
C_AZURE  = 8
C_BLUE   = 9
C_GOLD   = 11
C_RED    = 12
C_LIME   = 14
C_WHITE  = 15

# Cell size in pixels
CELL = 4

# Package colour palette (indexed by colour slot)
PKG_COLORS = [C_ORANGE, C_GREEN, C_BLUE]

# Direction map: action_id -> (dx, dy)
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# ═══════════════════════════════════════════════════════════════════════════
# Level definitions
# ═══════════════════════════════════════════════════════════════════════════
# Each level dict:
#   name       - display name
#   grid_w/h   - grid dimensions (border walls auto-generated)
#   walls      - set of (x,y) interior wall positions
#   player     - (x,y) start position
#   packages   - list of (x, y, color_idx)  -- pickup locations
#   deliveries - list of (x, y, color_idx)  -- delivery zones
#   enemies    - list of (x, y, dx, dy)     -- patrol start + direction (bounce)
#   exit       - (x, y) exit position (appears after all deliveries)
#
# color_idx: 0=orange, 1=green, 2=blue
#
# Enemies move AFTER the player each step. They advance 1 cell in their
# direction; if they'd hit a wall, they reverse direction and try the
# opposite cell; if both are walls they stay put.

LEVELS = [
    # ── L1: First Delivery (7x7, 1 pkg, 0 enemies) ───────────────────────
    # Simple intro: pick up orange package, deliver to zone, walk to exit.
    #
    #   #######
    #   #.....#
    #   #.P...#   P = player (2,2)
    #   #.....#
    #   #..p..#   p = orange package at (3,4)
    #   #...d.#   d = orange delivery at (4,5)
    #   #######
    #   exit at (5,1)
    #
    # Solution: D D pick(3,4) D deliver(4,5)→exit opens, U U U U R R R → exit(5,1)
    # Shorter: D D R D (deliver) U U U U R R → exit
    {
        "name": "First Delivery",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (2, 2),
        "packages": [(3, 4, 0)],
        "deliveries": [(4, 5, 0)],
        "enemies": [],
        "exit": (5, 1),
    },

    # ── L2: Dodge the Guard (7x7, 1 pkg, 1 enemy) ────────────────────────
    # One enemy patrols horizontally in the middle row.
    #
    #   #######
    #   #P...d#   P=player(1,1), d=orange delivery(5,1)
    #   #.....#
    #   #.E>>>>#   E=enemy at (2,3) moving right dx=1,dy=0
    #   #.....#
    #   #..p..#   p=orange package(3,5)
    #   #######
    #   exit at (5,5)
    #
    # Enemy bounces between x=1..5 on row 3.
    # Solution: go down to (1,5), right to (3,5) pick up, right right to (5,5)
    # but exit not open yet. Go up: (5,4),(5,3) -- enemy is moving, need timing.
    # Actually: D D D D R R (pick pkg) then need to deliver at (5,1).
    # Route: from (3,5) after pick, R R U U U U (deliver at 5,1) → exit opens
    # exit at (5,5): then D D D D → done.
    # Enemy at row 3: starting (2,3) moving right. Step-by-step:
    #  t0: e=(2,3) moving right
    #  t1: player (1,2), e=(3,3)
    #  t2: player (1,3), e=(4,3) -- player at row 3 col 1, enemy at col 4, safe
    #  t3: player (1,4), e=(5,3)
    #  t4: player (1,5), e=(4,3) reversed
    #  t5: player (2,5), e=(3,3)
    #  t6: player (3,5) pick, e=(2,3)
    #  t7: player (4,5), e=(1,3)
    #  t8: player (5,5), e=(2,3)
    #  t9: player (5,4), e=(3,3)
    #  t10: player (5,3), e=(4,3) -- safe (5 != 4)
    #  t11: player (5,2), e=(5,3) -- safe (row 2 != row 3... wait enemy is at (5,3) and player at (5,2)). OK safe.
    #  t12: player (5,1) deliver! exit opens. e=(4,3) reversed
    #  t13: player (5,2), e=(3,3)
    #  t14: player (5,3), e=(2,3) -- safe
    #  t15: player (5,4), e=(1,3)
    #  t16: player (5,5) = exit! Win!
    {
        "name": "Dodge the Guard",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 1),
        "packages": [(3, 5, 0)],
        "deliveries": [(5, 1, 0)],
        "enemies": [(2, 3, 1, 0)],
        "exit": (5, 5),
    },

    # ── L3: Double Drop (8x8, 2 pkgs same color, 1 enemy) ────────────────
    # Two orange packages, two orange delivery zones.
    #
    #   ########
    #   #P.....#   P=player(1,1)
    #   #......#
    #   #..E...#   E=enemy(3,3) moving dy=1 (vertical patrol)
    #   #......#
    #   #.p..p.#   p=orange pkgs at (2,5) and (5,5)
    #   #.d..d.#   d=orange deliveries at (2,6) and (5,6)
    #   ########
    #   exit at (6,1)
    #
    # Enemy patrols column 3, rows 1-6 vertically.
    {
        "name": "Double Drop",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 1),
        "packages": [(2, 5, 0), (5, 5, 0)],
        "deliveries": [(2, 6, 0), (5, 6, 0)],
        "enemies": [(3, 3, 0, 1)],
        "exit": (6, 1),
    },

    # ── L4: Color Match (8x8, 2 pkgs different colors, 1 enemy) ──────────
    # Orange pkg → orange delivery, green pkg → green delivery.
    # Must match colors correctly.
    #
    #   ########
    #   #P.....#   P=player(1,1)
    #   #......#
    #   #....E.#   E=enemy(5,3) moving dy=1 (vertical)
    #   #......#
    #   #.po...#   p=orange(2,5), o=green(3,5) (packages)
    #   #....dg#   d=orange delivery(5,6), g=green delivery(6,6)
    #   ########
    #   exit at (6,1)
    #
    # Enemy patrols column 5, rows 1-6.
    {
        "name": "Color Match",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 1),
        "packages": [(2, 5, 0), (3, 5, 1)],
        "deliveries": [(5, 6, 0), (6, 6, 1)],
        "enemies": [(5, 3, 0, 1)],
        "exit": (6, 1),
    },

    # ── L5: Crossfire (9x9, 2 pkgs, 2 enemies) ──────────────────────────
    # Two enemies patrol perpendicular routes.
    #
    #   #########
    #   #P......#   P=player(1,1)
    #   #.......#
    #   #.......#
    #   #..E1...#   E1=enemy(3,4) moving dx=1 (horizontal)
    #   #.......#
    #   #...E2..#   E2=enemy(4,6) moving dy=-1 (vertical)
    #   #.p..d..#   p=orange(2,7), d=green delivery(5,7)
    #   #########
    #   packages: orange at (2,7), green at (6,2)
    #   deliveries: orange at (5,7), green at (6,5)
    #   exit at (7,1)
    {
        "name": "Crossfire",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "player": (1, 1),
        "packages": [(2, 7, 0), (6, 2, 1)],
        "deliveries": [(5, 7, 0), (6, 5, 1)],
        "enemies": [(3, 4, 1, 0), (4, 6, 0, -1)],
        "exit": (7, 1),
    },

    # ── L6: Triple Threat (9x9, 3 pkgs, 2 enemies) ──────────────────────
    #
    #   #########
    #   #P......#   P=player(1,1)
    #   #.......#
    #   #..E1...#   E1=enemy(3,3) dx=1
    #   #.......#
    #   #.......#
    #   #....E2.#   E2=enemy(5,6) dy=-1
    #   #.p.g.b.#   p=orange(2,7), g=green(4,7), b=blue(6,7)
    #   #########
    #   deliveries: orange(2,2), green(4,2), blue(6,2)
    #   exit at (7,1)
    {
        "name": "Triple Threat",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "player": (1, 1),
        "packages": [(2, 7, 0), (4, 7, 1), (6, 7, 2)],
        "deliveries": [(2, 2, 0), (4, 2, 1), (6, 2, 2)],
        "enemies": [(3, 3, 1, 0), (5, 6, 0, -1)],
        "exit": (7, 1),
    },

    # ── L7: Patrol Maze (10x10, 3 pkgs, 3 enemies) ──────────────────────
    #
    #   ##########
    #   #P.......#   P=player(1,1)
    #   #........#
    #   #..E1....#   E1=enemy(3,3) dx=1 (horizontal)
    #   #........#
    #   #........#
    #   #.....E2.#   E2=enemy(6,6) dy=-1 (vertical)
    #   #........#
    #   #.E3.....#   E3=enemy(2,8) dx=1 (horizontal)
    #   ##########
    #   packages: orange(2,5), green(5,8), blue(7,2)
    #   deliveries: orange(7,5), green(2,2), blue(5,2)
    #   exit at (8,1)
    {
        "name": "Patrol Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "player": (1, 1),
        "packages": [(2, 5, 0), (5, 8, 1), (7, 2, 2)],
        "deliveries": [(7, 5, 0), (2, 2, 1), (5, 2, 2)],
        "enemies": [(3, 3, 1, 0), (6, 6, 0, -1), (2, 8, 1, 0)],
        "exit": (8, 1),
    },

    # ── L8: Walled Warehouse (10x10, 3 pkgs, 3 enemies, walls) ──────────
    # Interior walls create corridors.
    #
    #   ##########
    #   #P..#....#
    #   #...#....#
    #   #...#..E1#   E1=enemy(8,3) dy=1
    #   #........#   gap at (4,4)
    #   #........#
    #   #E2..#...#   E2=enemy(1,6) dx=1, wall column at x=5 rows 6-8
    #   #....#...#
    #   #..E3#...#   E3=enemy(3,8) dx=-1
    #   ##########
    #   packages: orange(2,2), green(7,1), blue(7,7)
    #   deliveries: orange(7,8), green(2,7), blue(2,4)
    #   exit at (8,1)
    {
        "name": "Walled Warehouse",
        "grid_w": 10, "grid_h": 10,
        "walls": {(4, 1), (4, 2), (4, 3),
                  (5, 6), (5, 7), (5, 8)},
        "player": (1, 1),
        "packages": [(2, 2, 0), (7, 1, 2), (7, 7, 1)],
        "deliveries": [(7, 8, 0), (2, 7, 1), (2, 4, 2)],
        "enemies": [(8, 3, 0, 1), (1, 6, 1, 0), (3, 8, -1, 0)],
        "exit": (8, 1),
    },

    # ── L9: Rush Hour (10x10, 4 pkgs, 3 enemies) ────────────────────────
    #
    #   ##########
    #   #P.......#
    #   #........#
    #   #.E1.....#   E1=enemy(2,3) dy=1
    #   #........#
    #   #.....E2.#   E2=enemy(6,5) dx=-1
    #   #........#
    #   #........#
    #   #...E3...#   E3=enemy(4,8) dx=1
    #   ##########
    #   packages: orange(1,8), green(4,2), blue(8,4), orange(8,8)
    #   deliveries: orange(1,2), green(8,2), blue(1,5), orange(8,6)
    #   exit at (8,1)
    {
        "name": "Rush Hour",
        "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "player": (1, 1),
        "packages": [(1, 8, 0), (4, 2, 1), (8, 4, 2), (8, 8, 0)],
        "deliveries": [(1, 2, 0), (8, 2, 1), (1, 5, 2), (8, 6, 0)],
        "enemies": [(2, 3, 0, 1), (6, 5, -1, 0), (4, 8, 1, 0)],
        "exit": (8, 1),
    },

    # ── L10: Final Run (12x10, 4 pkgs, 4 enemies) ───────────────────────
    #
    #   ############
    #   #P.........#
    #   #..........#
    #   #.E1.......#   E1=enemy(2,3) dx=1
    #   #..........#
    #   #.......E2.#   E2=enemy(8,5) dy=-1
    #   #..........#
    #   #..E3......#   E3=enemy(3,7) dx=1
    #   #........E4#   E4=enemy(9,8) dy=-1
    #   ############
    #   packages: orange(1,8), green(5,1), blue(10,2), orange(10,8)
    #   deliveries: orange(5,8), green(10,5), blue(1,5), orange(5,4)
    #   exit at (10,1)
    {
        "name": "Final Run",
        "grid_w": 12, "grid_h": 10,
        "walls": set(),
        "player": (1, 1),
        "packages": [(1, 8, 0), (5, 1, 1), (10, 2, 2), (10, 8, 0)],
        "deliveries": [(5, 8, 0), (10, 5, 1), (1, 5, 2), (5, 4, 0)],
        "enemies": [(2, 3, 1, 0), (8, 5, 0, -1), (3, 7, 1, 0), (9, 8, 0, -1)],
        "exit": (10, 1),
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Display
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
    cx, cy = px + 1, py + 1
    for dy in range(2):
        for dx in range(2):
            y, x = cy + dy, cx + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


class Fc01Display(RenderableUserDisplay):
    def __init__(self, game):
        super().__init__()
        self.game = game

    def render_interface(self, frame):
        g = self.game
        if not hasattr(g, 'grid_w'):
            return frame

        frame[:, :] = C_BLACK
        gw, gh = g.grid_w, g.grid_h
        ox = (64 - gw * CELL) // 2
        oy = (64 - gh * CELL) // 2

        # Draw floor and walls
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.all_walls:
                    _fill(frame, px, py, C_WHITE)
                else:
                    _fill(frame, px, py, C_MID)

        # Delivery zones (colored border with gray center)
        for dx, dy, dc in g.remaining_deliveries:
            px, py = ox + dx * CELL, oy + dy * CELL
            _fill(frame, px, py, PKG_COLORS[dc])
            _dot(frame, px, py, C_GRAY)

        # Packages (colored solid with white center dot)
        for pkx, pky, pkc in g.remaining_packages:
            px, py = ox + pkx * CELL, oy + pky * CELL
            _fill(frame, px, py, PKG_COLORS[pkc])
            _dot(frame, px, py, C_WHITE)

        # Exit (gold, only when open)
        if g.exit_open:
            ex, ey = g.exit_pos
            px, py = ox + ex * CELL, oy + ey * CELL
            _fill(frame, px, py, C_GOLD)

        # Enemies (red)
        for ex, ey, _, _ in g.enemies:
            px, py = ox + ex * CELL, oy + ey * CELL
            _fill(frame, px, py, C_RED)

        # Player (azure if empty-handed, lime if carrying)
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        pc = C_LIME if g.carrying is not None else C_AZURE
        _fill(frame, ppx, ppy, pc)
        # Show carried package color as center dot
        if g.carrying is not None:
            _dot(frame, ppx, ppy, PKG_COLORS[g.carrying])
        else:
            _dot(frame, ppx, ppy, C_WHITE)

        return frame


# ═══════════════════════════════════════════════════════════════════════════
# Game
# ═══════════════════════════════════════════════════════════════════════════

class Fc01(ARCBaseGame):
    def __init__(self):
        self.display = Fc01Display(self)
        self.carrying = None
        self.exit_open = False

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "fc01",
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
        # Build walls: borders + interior
        self.all_walls = set()
        for x in range(self.grid_w):
            self.all_walls.add((x, 0))
            self.all_walls.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.all_walls.add((0, y))
            self.all_walls.add((self.grid_w - 1, y))
        self.all_walls |= d["walls"]
        self.px, self.py = d["player"]
        self.remaining_packages = [list(p) for p in d["packages"]]
        self.remaining_deliveries = [list(dl) for dl in d["deliveries"]]
        self.enemies = [[e[0], e[1], e[2], e[3]] for e in d["enemies"]]
        self.exit_pos = d["exit"]
        self.exit_open = False
        self.carrying = None

    def step(self):
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        # Wall check
        if (nx, ny) in self.all_walls:
            self.complete_action()
            return

        # Move player
        self.px, self.py = nx, ny

        # Pick up package (only if not carrying)
        if self.carrying is None:
            for i in range(len(self.remaining_packages) - 1, -1, -1):
                pkx, pky, pkc = self.remaining_packages[i]
                if (self.px, self.py) == (pkx, pky):
                    self.carrying = pkc
                    self.remaining_packages.pop(i)
                    break

        # Deliver package (only if carrying and on matching delivery zone)
        elif self.carrying is not None:
            for i in range(len(self.remaining_deliveries) - 1, -1, -1):
                dlx, dly, dlc = self.remaining_deliveries[i]
                if (self.px, self.py) == (dlx, dly) and dlc == self.carrying:
                    self.remaining_deliveries.pop(i)
                    self.carrying = None
                    if not self.remaining_deliveries:
                        self.exit_open = True
                    break

        # Check exit
        if self.exit_open and (self.px, self.py) == tuple(self.exit_pos):
            self.next_level()
            self.complete_action()
            return

        # Move enemies (bounce off walls)
        for e in self.enemies:
            ex, ey, edx, edy = e
            nex, ney = ex + edx, ey + edy
            if (nex, ney) in self.all_walls:
                # Reverse direction
                e[2], e[3] = -edx, -edy
                nex, ney = ex - edx, ey - edy
                if (nex, ney) in self.all_walls:
                    # Stuck: stay put
                    nex, ney = ex, ey
            e[0], e[1] = nex, ney

        # Check enemy collision
        for ex, ey, _, _ in self.enemies:
            if (ex, ey) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        self.complete_action()
